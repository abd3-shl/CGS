"""
Modulo di composizione video REELS-FIX v5: sfondo tema + audio + sottotitoli
overlay in MP4 finale, con invariante geometrica zero-overlap verificata
prima dell'encode (vedi verify_zero_overlap sotto).

Due modalita' supportate:
- Statica (legacy): un PNG per chunk con overlay between(t,start,end).
- Animata: frame per-parola -> micro-video alpha -> singolo overlay per
  chunk sincronizzato con setpts (frame 0 = chunk.start).
"""

import os
import re
import subprocess
import shutil
import tempfile

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    OUTPUT_DIR,
    TEMP_DIR,
)


class VideoBuildError(Exception):
    """Errore durante la composizione del video con ffmpeg."""
    pass


def verify_zero_overlap(text_bbox, character_occupancy, gutter: int = 24):
    """Invariante geometrica obbligatoria REELS-FIX v5 (re-export stabile).

    overlap_x = not (text.x1 <= char.x0 - gutter or text.x0 >= char.x1 + gutter)
    overlap_y = not (text.y1 <= char.y0 - gutter or text.y0 >= char.y1 + gutter)
    assert not (overlap_x and overlap_y), "CRITICAL: Text overlap detected!"
    Re-esportata da layout_presets per API stabile (importabile da builder).
    """
    try:
        from core.layout_presets import verify_zero_overlap as _v
        return _v(text_bbox, character_occupancy, gutter)
    except AssertionError:
        raise
    except Exception:
        # Fallback locale se import fallisce (mai bloccare l'encode per check).
        try:
            ax0, ay0, ax1, ay1 = (int(text_bbox[0]), int(text_bbox[1]),
                                  int(text_bbox[2]), int(text_bbox[3]))
            bx0, by0, bx1, by1 = (int(character_occupancy[0]), int(character_occupancy[1]),
                                  int(character_occupancy[2]), int(character_occupancy[3]))
            g = int(gutter or 0)
            overlap_x = not (ax1 <= bx0 - g or ax0 >= bx1 + g)
            overlap_y = not (ay1 <= by0 - g or ay0 >= by1 + g)
            assert not (overlap_x and overlap_y), (
                f"CRITICAL: Text overlap detected! Text: {text_bbox}, Char: {character_occupancy}")
        except AssertionError:
            raise
        except Exception:
            return None


def assert_no_text_overlap(chunks: list[dict] | None, gutter: int = 24) -> int:
    """Pre-flight geometrico: safe-area testo vs occupancy (mai solleva fatal).

    Per ogni chunk con layout valido verifica che la Text Safe Area DINAMICA
    (v7: bordo a 40px dal personaggio reale) non intersechi
    character_occupancy_box con gutter. Ritorna n. violazioni (0 = ok) e
    logga warning; non blocca mai l'encode (fail-safe).
    """
    try:
        if not chunks:
            return 0
        from core.layout_presets import (preset_safe_area, preset_safe_area_dynamic,
                                         character_occupancy_box,
                                         boxes_overlap, normalize_preset)
    except Exception:
        return 0
    try:
        if not chunks:
            return 0
        from core.layout_presets import (preset_safe_area, character_occupancy_box,
                                         boxes_overlap, normalize_preset)
    except Exception:
        return 0
    bad = 0
    try:
        for i, ch in enumerate(chunks or []):
            try:
                if not isinstance(ch, dict):
                    continue
                raw = ch.get("layout", ch.get("layout_preset"))
                if not isinstance(raw, str):
                    continue
                # Punch-in con pill: overlap intenzionale protetto, skip check.
                try:
                    if bool(ch.get("punch_in", False)):
                        continue
                except Exception:
                    pass
                preset = normalize_preset(raw)
                if preset == "layout_center_punch_in":
                    continue
                try:
                    punch = bool(ch.get("punch_in", False))
                except Exception:
                    punch = False
                try:
                    _ppre = int(ch.get("pose")) if ch.get("pose") is not None else None
                except Exception:
                    _ppre = None
                try:
                    if preset in ("layout_split_left", "layout_split_right"):
                        area = preset_safe_area_dynamic(
                            preset, VIDEO_WIDTH, VIDEO_HEIGHT, _ppre, punch)
                    else:
                        area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
                except Exception:
                    area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
                occ = character_occupancy_box(preset, punch, None, None,
                                              VIDEO_WIDTH, VIDEO_HEIGHT,
                                              None, _ppre)
                if boxes_overlap(area, occ, gutter):
                    bad += 1
                    try:
                        print(f"[video_builder] CRITICAL overlap pre-flight chunk {i} "
                              f"({preset}): safe {area} vs occ {occ}")
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass
    return int(bad)


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise VideoBuildError(
            "ffmpeg non è stato trovato nel PATH di sistema. "
            "Installalo e assicurati che sia accessibile da terminale."
        )


def _get_audio_duration(audio_path: str) -> float:
    """Ottiene la durata dell'audio in secondi tramite ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoBuildError(f"ffprobe ha fallito: {result.stderr}")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise VideoBuildError(f"ffprobe ha restituito una durata non valida: {result.stdout.strip()!r}")


def _ffmpeg_color(hex_color: str | None) -> str:
    """Converte "#RRGGBB" nel formato del filtro color di ffmpeg ("0xRRGGBB")."""
    if isinstance(hex_color, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        return "0x" + hex_color[1:]
    return "black"


def _chunk_frame_pattern(frame_paths: list[str]) -> str | None:
    """Deriva il pattern image2 "%05d" se i frame sono sequenziali chunk_XXXX_frame_YYYYY.png.

    Ritorna il pattern ffmpeg o None se non derivabile (fallback a concat demuxer).
    """
    if not frame_paths:
        return None
    first = frame_paths[0]
    dirname = os.path.dirname(first)
    basename = os.path.basename(first)
    m = re.fullmatch(r"(chunk_\d+_frame_)\d+(\.png)", basename)
    if not m:
        return None
    prefix, suffix = m.group(1), m.group(2)
    # Verifica nomi senza stat su disco (lo stat e' gia' fatto a campione in build_chunk_clip).
    # Controlla primo, ultimo e lunghezza: sufficiente per pattern image2 sequenziale.
    try:
        if os.path.basename(frame_paths[-1]) != f"{prefix}{len(frame_paths)-1:05d}{suffix}":
            return None
        if len(frame_paths) > 2:
            mid = len(frame_paths) // 2
            if os.path.basename(frame_paths[mid]) != f"{prefix}{mid:05d}{suffix}":
                return None
        # Verifica dirname coerente solo su primo/ultimo (no loop O(N)).
        if os.path.dirname(frame_paths[-1]) != dirname:
            return None
    except (IndexError, TypeError):
        return None
    return os.path.join(dirname, f"{prefix}%05d{suffix}")


def _clip_codec_args(output_path: str) -> list[str]:
    """Argomenti codec per il micro-video con alpha in base all'estensione.

    - `.mov`  -> PNG nativo RGBA (veloce su CPU, alpha perfetto via overlay;
      usato di default dalla pipeline su hardware senza GPU come i5 8th gen).
    - `.webm` -> VP9 yuva420p (compatta, ma ~6x piu' lenta da codificare e
      l'overlay richiede `format=yuva420p`; tenuta per compatibilita' spec).
    - altre estensioni -> PNG (fallback sicuro con alpha).
    """
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".webm":
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-auto-alt-ref", "0", "-crf", "18", "-b:v", "0"]
    # .mov e default: PNG lossless RGBA (veloce, alpha garantita).
    return ["-c:v", "png"]


def build_chunk_clip(frame_paths: list[str], fps: int, output_path: str) -> str:
    """Compone i frame PNG di un singolo chunk in un micro-video con alpha.

    Formato in base all'estensione di `output_path` (vedi `_clip_codec_args`):
    `.mov` -> PNG/RGBA (default pipeline: veloce + alpha perfetta),
    `.webm` -> VP9/yuva420p (compatta, da spec Fase 3).

    Args:
        frame_paths: lista ordinata di PNG (output di `generate_animated_chunk_frames`).
        fps: frame rate (deve coincidere col video principale per la sincronia).
        output_path: percorso del micro-video da creare (es. TEMP_DIR/chunk_0000.mov).

    Returns:
        Il percorso del micro-video creato.

    Raises:
        VideoBuildError: se mancano i frame o ffmpeg fallisce.
    """
    _check_ffmpeg()
    if not frame_paths:
        raise VideoBuildError("build_chunk_clip: nessun frame da comporre.")
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    # Veloce: controlla solo primo/ultimo + pattern (evita N stat su 900 file).
    if not os.path.isfile(frame_paths[0]) or not os.path.isfile(frame_paths[-1]):
        raise VideoBuildError(f"build_chunk_clip: frame mancante: {frame_paths[0]}")
    if len(frame_paths) > 4:
        import random as _rnd
        _spot = _rnd.sample(frame_paths[1:-1], min(2, len(frame_paths) - 2))
        for p in _spot:
            if not os.path.isfile(p):
                raise VideoBuildError(f"build_chunk_clip: frame mancante: {p}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    codec_args = _clip_codec_args(output_path)

    pattern = _chunk_frame_pattern(frame_paths)
    if pattern is not None:
        cmd = [
            "ffmpeg", "-y", "-threads", "auto",
            "-framerate", str(fps),
            "-start_number", "0",
            "-i", pattern,
        ] + codec_args + ["-threads", "auto", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(output_path):
            return output_path
        # Fallback a concat demuxer se il pattern fallisce (es. build ffmpeg senza libvpx).
        last_err = result.stderr[-2000:]
    else:
        last_err = "pattern non derivabile, uso concat demuxer"

    # --- Fallback: concat demuxer con lista file ---
    frame_dur = 1.0 / float(fps)
    list_fd, list_path = tempfile.mkstemp(prefix="chunk_concat_", suffix=".txt", dir=TEMP_DIR)
    try:
        with os.fdopen(list_fd, "w", encoding="utf-8") as f:
            for p in frame_paths:
                # Virgolette singole con escape per ffmpeg concat.
                esc = p.replace("'", "'\\''")
                f.write(f"file '{esc}'\n")
                f.write(f"duration {frame_dur}\n")
            # L'ultimo file va ripetuto senza duration (spec concat demuxer).
            esc = frame_paths[-1].replace("'", "'\\''")
            f.write(f"file '{esc}'\n")
        cmd = [
            "ffmpeg", "-y", "-threads", "auto",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
        ] + codec_args + ["-threads", "auto", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise VideoBuildError(
                f"ffmpeg build_chunk_clip ha fallito (pattern: {last_err}):\n{result.stderr[-2000:]}"
            )
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass
    if not os.path.isfile(output_path):
        raise VideoBuildError("build_chunk_clip: micro-video non creato (output mancante).")
    return output_path


def _is_animated_chunk(chunk: dict) -> bool:
    """Vero se il chunk porta frame animati (Fase 3) invece del singolo PNG statico."""
    if chunk.get("frame_paths"):
        return True
    frames = chunk.get("frames")
    if isinstance(frames, list) and frames:
        return True
    return False


def _chunk_frames(chunk: dict) -> list[str]:
    """Estrae la lista di frame PNG da un chunk animato."""
    if chunk.get("frame_paths"):
        return list(chunk["frame_paths"])
    frames = chunk.get("frames") or []
    return [f["image_path"] for f in frames if f.get("image_path")]


def _collect_gapless_png_timeline(subtitle_chunks: list[dict],
                                  fps: int) -> list[dict] | None:
    """Sequenza PNG gapless 0..max_end per single-pass (spec §1+§5, mai solleva).

    Raccoglie tutti i frame per-chunk {"image_path","start","end"}, li ordina
    per t e RIEMPIE i gap (end[N] < start[N+1]) clonando l'ultimo frame del
    chunk precedente (hold visivo): nessun intervallo resta senza overlay, il
    canale alpha/character non si azzera mai ai confini -> zero flash neri.
    Ritorna lista frame ordinata o None se non usabile (fallback legacy).
    """
    try:
        if fps is None or fps <= 0:
            fps = VIDEO_FPS
        all_frames: list[dict] = []
        for chunk in subtitle_chunks or []:
            try:
                frames = chunk.get("frames")
                if isinstance(frames, list) and frames:
                    for f in frames:
                        if isinstance(f, dict) and f.get("image_path"):
                            all_frames.append({
                                "image_path": str(f["image_path"]),
                                "start": float(f.get("start", chunk.get("start", 0.0))),
                                "end": float(f.get("end", chunk.get("start", 0.0))),
                            })
                    continue
                for p in _chunk_frames(chunk):
                    all_frames.append({
                        "image_path": str(p),
                        "start": float(chunk.get("start", 0.0)),
                        "end": float(chunk.get("end", 0.0)),
                    })
            except (TypeError, ValueError, AttributeError):
                continue
        # Filtra path mancanti (frame corrotti saltati, mai crash).
        all_frames = [f for f in all_frames
                      if f.get("image_path") and os.path.isfile(f["image_path"])]
        if not all_frames:
            return None
        all_frames.sort(key=lambda f: (f["start"], f["end"]))
        # Dedup sovrapposizioni esatte + riempi gap clonando ultimo frame.
        gapless: list[dict] = []
        step = 1.0 / float(fps)
        for f in all_frames:
            try:
                if gapless and float(f["start"]) < float(gapless[-1]["end"]) - 1e-9:
                    # Sovrapposizione da arrotondamenti: allinea senza buchi.
                    f = {**f, "start": float(gapless[-1]["end"])}
                if gapless and float(f["start"]) > float(gapless[-1]["end"]) + 1e-9:
                    # Gap reale (causa dei flash neri): hold dell'ultimo frame.
                    gapless.append({
                        "image_path": gapless[-1]["image_path"],
                        "start": float(gapless[-1]["end"]),
                        "end": float(f["start"]),
                    })
                if float(f["end"]) <= float(f["start"]):
                    f = {**f, "end": float(f["start"]) + step}
                gapless.append(f)
            except (TypeError, ValueError, KeyError):
                continue
        return gapless if gapless else None
    except Exception:
        return None


def _encode_gapless_single_pass(gapless: list[dict], audio_path: str,
                                output_path: str, background_color: str | None,
                                duration: float) -> str:
    """Encode single-pass da sequenza PNG gapless + sfondo + audio (spec §5).

    Composita ogni PNG sullo sfondo tinta unita in Python (Pillow, parallelo
    ThreadPool, risorse gia' in RAM) in una sequenza full-timeline numerata,
    poi UN SOLO encode ffmpeg image2 -> libx264 + AAC (zero .mov intermedi,
    zero filter_complex N-overlay, zero desync: timestamps nativi 1/fps).
    Solleva VideoBuildError se ffmpeg fallisce (il chiamante usa fallback).
    """
    import concurrent.futures as _fut
    from PIL import Image as _PILImage

    if not gapless:
        raise VideoBuildError("Timeline gapless vuota.")
    # Sfondo tinta unita (stesso colore del path legacy).
    try:
        bg_hex = str(background_color or "#000000").strip()
        if len(bg_hex) == 7 and bg_hex.startswith("#"):
            bg_rgb = (int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16), 255)
        else:
            bg_rgb = (0, 0, 0, 255)
    except (TypeError, ValueError):
        bg_rgb = (0, 0, 0, 255)
    seq_dir = os.path.join(TEMP_DIR, "timeline_seq")
    os.makedirs(seq_dir, exist_ok=True)
    # Pulizia sequenza precedente (stesso job dir, mai fuori TEMP_DIR).
    try:
        for _fn in os.listdir(seq_dir):
            if _fn.startswith("tframe_") and _fn.endswith(".png"):
                try:
                    os.remove(os.path.join(seq_dir, _fn))
                except OSError:
                    pass
    except OSError:
        pass

    try:
        _cpu = max(2, (os.cpu_count() or 4))
    except Exception:
        _cpu = 4
    workers = max(2, min(8, _cpu))

    def _one(idx_frame):
        idx, fr = idx_frame
        try:
            base = _PILImage.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), bg_rgb)
            try:
                with _PILImage.open(fr["image_path"]) as ov:
                    ov_rgba = ov.convert("RGBA") if ov.mode != "RGBA" else ov.copy()
                    try:
                        base.alpha_composite(ov_rgba, (0, 0))
                    except (ValueError, AttributeError):
                        try:
                            base.paste(ov_rgba, (0, 0), ov_rgba)
                        except (ValueError, AttributeError):
                            base.paste(ov_rgba, (0, 0))
            except Exception:
                pass  # frame corrotto -> sfondo pieno (mai nero imprevisto)
            out = os.path.join(seq_dir, f"tframe_{idx:05d}.png")
            try:
                base.convert("RGB").save(out, compress_level=1)
            except Exception:
                base.save(out)
            return out
        except Exception as e:
            raise VideoBuildError(f"Compositing frame {idx} fallito: {e}")

    with _fut.ThreadPoolExecutor(max_workers=workers) as ex:
        seq_paths = list(ex.map(_one, enumerate(gapless)))
    if not seq_paths or not all(os.path.isfile(p) for p in seq_paths):
        raise VideoBuildError("Sequenza timeline incompleta.")
    pattern = os.path.join(seq_dir, "tframe_%05d.png")
    import os as _os2
    _preset = (_os2.environ.get("FFMPEG_PRESET", "veryfast") or "veryfast").strip() or "veryfast"
    if _preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
        _preset = "veryfast"
    cmd = [
        "ffmpeg", "-y", "-threads", "auto",
        "-framerate", str(VIDEO_FPS),
        "-start_number", "0",
        "-i", pattern,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", _preset, "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoBuildError(
            f"ffmpeg single-pass timeline fallito:\n{result.stderr[-2000:]}")
    if not os.path.isfile(output_path):
        raise VideoBuildError("Output single-pass mancante.")
    return output_path


def build_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
) -> str:
    """
    Costruisce il video finale: sfondo colorato, audio narrato, sottotitoli
    sincronizzati come overlay (Continuous Timeline v3 + fallback legacy).

    Path primario (spec §1+§5): sequenza PNG gapless single-pass — tutti i
    frame per-chunk vengono cuciti in un'unica timeline senza gap (hold
    dell'ultimo frame nei buchi) e codificati in UN SOLO encode image2->H264
    + audio. Zero .mov intermedi nel path felice, zero `between()` con buchi,
    zero desync (timestamps nativi 1/fps).
    Fallback legacy: N micro-video .mov + filter_complex overlay (invariato).

    Accetta sia chunk statici ({"image_path","start","end"} da
    `renderer.render_all_subtitles`) sia chunk animati ({"frames"/
    "frame_paths","start","end"} da `text_animator.render_all_chunks_animated`).

    Args:
        audio_path: percorso del file audio narrato.
        subtitle_chunks: lista di chunk statici o animati (vedi sopra).
        output_filename: nome del file MP4 finale in OUTPUT_DIR.
        background_color: colore sfondo in hex "#RRGGBB" (default: nero).

    Returns:
        Percorso assoluto del video finale generato.
    """
    _check_ffmpeg()
    # REELS-FIX v5 pre-flight: safe-area vs occupancy (warning, mai fatal).
    try:
        _bad = assert_no_text_overlap(subtitle_chunks, 24)
        if _bad:
            try:
                print(f"[video_builder] warning: {int(_bad)} chunk con safe-area in "
                      f"overlap teorico (auto-fit/hard-clamp attivi a valle).")
            except Exception:
                pass
    except Exception:
        pass

    duration = _get_audio_duration(audio_path)

    # 1. Costruiamo l'input: sfondo generato con il filtro "color",
    #    della durata esatta dell'audio.
    bg = _ffmpeg_color(background_color)
    inputs = [
        "-f", "lavfi",
        "-i", f"color=c={bg}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}:d={duration}",
        "-i", audio_path,
    ]

    animated = any(_is_animated_chunk(c) for c in subtitle_chunks)

    if not animated:
        # --- Percorso statico legacy (invariato) ---
        # 2. Aggiungiamo ogni immagine di sottotitolo come input separato,
        #    ognuna verrà mostrata solo nella sua finestra temporale.
        for chunk in subtitle_chunks:
            inputs.extend(["-i", chunk["image_path"]])

        # 3. Costruiamo il filtro di overlay: ogni sottotitolo viene sovrapposto
        #    al layer precedente, ma "enable" ne limita la visibilità alla
        #    finestra temporale [start, end] tramite un'espressione ffmpeg.
        filter_parts = []
        last_label = "0:v"  # lo sfondo (input 0) è il layer di base

        for idx, chunk in enumerate(subtitle_chunks):
            input_index = idx + 2  # 0 = sfondo, 1 = audio, 2..N = sottotitoli
            out_label = f"v{idx}"
            start = chunk["start"]
            end = chunk["end"]
            filter_parts.append(
                f"[{last_label}][{input_index}:v]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
            )
            last_label = out_label

        filter_complex = ";".join(filter_parts)
    else:
        # --- Path primario v3: gapless single-pass (zero .mov, zero flash) ---
        # Cuce i frame per-chunk in un'unica timeline senza gap (hold) e fa UN
        # SOLO encode image2->H264 + audio. Se fallisce -> fallback legacy.
        try:
            _gapless = _collect_gapless_png_timeline(subtitle_chunks, VIDEO_FPS)
            if _gapless:
                _out = os.path.join(OUTPUT_DIR, output_filename)
                try:
                    return _encode_gapless_single_pass(
                        _gapless, audio_path, _out, background_color, duration)
                except VideoBuildError:
                    pass  # fallback legacy sotto
        except Exception:
            pass
        # --- Fallback legacy (Fase 3): micro-video paralleli + overlay ---
        # Clip in MOV/PNG (veloce + alpha). Build parallelo: ogni clip e'
        # indipendente, ThreadPool riduce il wall-time di ~3x su 30 chunk.
        import concurrent.futures as _fut
        clip_infos: list[tuple[str, float, float, bool] | None] = [None] * len(subtitle_chunks)
        _jobs: list[tuple[int, list[str], str]] = []
        for idx, chunk in enumerate(subtitle_chunks):
            start = float(chunk["start"])
            end = float(chunk["end"])
            if _is_animated_chunk(chunk):
                frame_paths = _chunk_frames(chunk)
                if not frame_paths:
                    raise VideoBuildError(f"Chunk animato {idx} senza frame.")
                clip_path = os.path.join(TEMP_DIR, f"chunk_{idx:04d}.mov")
                # Riuso: se clip gia' esistente e piu' recente dei frame, salta encode.
                try:
                    if os.path.isfile(clip_path) and os.path.getmtime(clip_path) >= os.path.getmtime(frame_paths[0]):
                        clip_infos[idx] = (clip_path, start, end, True)
                        continue
                except OSError:
                    pass
                _jobs.append((idx, frame_paths, clip_path))
                clip_infos[idx] = (clip_path, start, end, True)
            elif chunk.get("clip_path"):
                clip_infos[idx] = (chunk["clip_path"], start, end, True)
            elif chunk.get("image_path"):
                clip_infos[idx] = (chunk["image_path"], start, end, False)
            else:
                raise VideoBuildError(f"Chunk {idx} senza frame/immagine ne' clip: {chunk}")
        if _jobs:
            try:
                _cpu = max(2, (os.cpu_count() or 4))
            except Exception:
                _cpu = 4
            # v2: tutti i core disponibili (cap 8, job I/O+ffmpeg esterni).
            _workers = max(2, min(8, _cpu, len(_jobs)))

            def _one(job: tuple[int, list[str], str]):
                _idx, _frames, _out = job
                build_chunk_clip(_frames, VIDEO_FPS, _out)
                return _idx

            with _fut.ThreadPoolExecutor(max_workers=_workers) as _ex:
                for _fu in _fut.as_completed([_ex.submit(_one, j) for j in _jobs]):
                    _fu.result()  # solleva VideoBuildError al chiamante se fallisce
        clip_infos = [c for c in clip_infos if c is not None]

        for clip_path, _s, _e, _is_vid in clip_infos:
            inputs.extend(["-i", clip_path])

        # Continuity fix v3 (fallback): estendi l'overlay fino a next_start
        # quando l'identita' character e' invariata -> nessun gap scoperto
        # tra end[N] e start[N+1] (il blink nero nasceva proprio li').
        try:
            from core.character_selector import timeline_identity_of as _tl_id
            _ext_ends: list[float] = [float(e) for _, _, e, _ in clip_infos]
            for _k in range(len(clip_infos) - 1):
                try:
                    _cur_id = _tl_id(subtitle_chunks[_k] if _k < len(subtitle_chunks) else None)
                    _nxt_id = _tl_id(subtitle_chunks[_k + 1] if _k + 1 < len(subtitle_chunks) else None)
                    if _cur_id is not None and _cur_id == _nxt_id:
                        _nxt_start = float(clip_infos[_k + 1][1])
                        if _nxt_start > _ext_ends[_k]:
                            _ext_ends[_k] = _nxt_start
                except Exception:
                    continue
        except Exception:
            _ext_ends = [float(e) for _, _, e, _ in clip_infos]
        filter_parts = []
        last_label = "0:v"
        for idx, (_clip_path, start, end, is_video) in enumerate(clip_infos):
            try:
                end_eff = float(_ext_ends[idx]) if idx < len(_ext_ends) else float(end)
            except (TypeError, ValueError, IndexError):
                end_eff = float(end)
            input_index = idx + 2
            out_label = f"v{idx}"
            if is_video:
                # Shift temporale: il frame 0 del clip deve apparire a chunk.start.
                # Per i clip WebM/VP9 si forza yuva420p (l'alpha VP9 richiede il
                # formato esplicito, altrimenti le aree trasparenti diventano nere).
                clip_label = f"c{idx}"
                if _clip_path.lower().endswith(".webm"):
                    filter_parts.append(
                        f"[{input_index}:v]format=yuva420p,setpts=PTS-STARTPTS+{start}/TB[{clip_label}]"
                    )
                else:
                    filter_parts.append(
                        f"[{input_index}:v]setpts=PTS-STARTPTS+{start}/TB[{clip_label}]"
                    )
                filter_parts.append(
                    f"[{last_label}][{clip_label}]overlay=0:0:enable='between(t,{start},{end_eff})'[{out_label}]"
                )
            else:
                filter_parts.append(
                    f"[{last_label}][{input_index}:v]overlay=0:0:enable='between(t,{start},{end_eff})'[{out_label}]"
                )
            last_label = out_label
        filter_complex = ";".join(filter_parts)

    output_path = os.path.join(OUTPUT_DIR, output_filename)

    # Preset finale configurabile: FFMPEG_PRESET=veryfast default (qualita' invariata),
    # ultrafast per bozze veloci. Threads espliciti per filter+encode.
    import os as _os2
    _preset = (_os2.environ.get("FFMPEG_PRESET", "veryfast") or "veryfast").strip() or "veryfast"
    if _preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
        _preset = "veryfast"
    cmd = ["ffmpeg", "-y", "-threads", "auto"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", _preset,
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-filter_threads", "auto",
        "-threads", "auto",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise VideoBuildError(f"ffmpeg ha fallito durante la composizione:\n{result.stderr[-2000:]}")

    return output_path


def cleanup_temp_files():
    """Rimuove i file temporanei generati durante il processo (audio, PNG, MOV/WebM, liste concat)."""
    if not os.path.isdir(TEMP_DIR):
        return
    for root, dirs, files in os.walk(TEMP_DIR, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        for dname in dirs:
            dpath = os.path.join(root, dname)
            try:
                os.rmdir(dpath)
            except OSError:
                pass
