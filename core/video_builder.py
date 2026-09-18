"""
Modulo di composizione video: usa ffmpeg per unire uno sfondo colorato
(dal tema dinamico, default nero), la traccia audio generata e i sottotitoli,
producendo il file MP4 finale.

Due modalita' supportate:
- Statica (legacy): ogni chunk ha un singolo "image_path" PNG, sovrapposto
  con `overlay=enable='between(t,start,end)'` (un overlay per chunk).
- Animata (Fase 3): ogni chunk ha "frames"/"frame_paths" (output di
  `core/text_animator.generate_animated_chunk_frames`). I frame PNG del chunk
  vengono prima composti in un micro-video con alpha (WebM/VP9) via
  `build_chunk_clip`, poi sovrapposti con UN SOLO overlay per chunk
  (stesso numero di overlay della modalita' statica, stesse performance),
  sincronizzato con `setpts` in modo che il frame 0 del clip corrisponda
  esattamente a `chunk.start` nel video principale.
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
    # Verifica sequenza 0..N-1 contigua.
    for i, p in enumerate(frame_paths):
        expected = f"{prefix}{i:05d}{suffix}"
        if os.path.basename(p) != expected or os.path.dirname(p) != dirname:
            return None
        if not os.path.isfile(p):
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
    for p in frame_paths:
        if not os.path.isfile(p):
            raise VideoBuildError(f"build_chunk_clip: frame mancante: {p}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    codec_args = _clip_codec_args(output_path)

    pattern = _chunk_frame_pattern(frame_paths)
    if pattern is not None:
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-start_number", "0",
            "-i", pattern,
        ] + codec_args + [output_path]
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
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
        ] + codec_args + [output_path]
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


def build_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
) -> str:
    """
    Costruisce il video finale: sfondo colorato, audio narrato, sottotitoli
    sincronizzati come overlay.

    Accetta sia chunk statici ({"image_path","start","end"} da
    `renderer.render_all_subtitles`) sia chunk animati ({"frames"/
    "frame_paths","start","end"} da `text_animator.render_all_chunks_animated`).
    Nel caso animato, ogni chunk viene prima pre-renderizzato in un micro-video
    WebM/VP9 con alpha (`build_chunk_clip`) e poi sovrapposto con un solo
    overlay per chunk, sincronizzato via `setpts` (frame 0 del clip = chunk.start).

    Args:
        audio_path: percorso del file audio narrato.
        subtitle_chunks: lista di chunk statici o animati (vedi sopra).
        output_filename: nome del file MP4 finale in OUTPUT_DIR.
        background_color: colore sfondo in hex "#RRGGBB" (default: nero).

    Returns:
        Percorso assoluto del video finale generato.
    """
    _check_ffmpeg()

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
        # --- Percorso animato (Fase 3): un micro-video per chunk + un overlay per chunk ---
        # Clip in MOV/PNG (veloce + alpha perfetta su CPU); i .webm/VP9 restano
        # supportati se il chunk porta gia' un clip_path .webm.
        clip_infos: list[tuple[str, float, float, bool]] = []  # (path, start, end, is_video)
        for idx, chunk in enumerate(subtitle_chunks):
            start = float(chunk["start"])
            end = float(chunk["end"])
            if _is_animated_chunk(chunk):
                frame_paths = _chunk_frames(chunk)
                if not frame_paths:
                    raise VideoBuildError(f"Chunk animato {idx} senza frame.")
                clip_path = os.path.join(TEMP_DIR, f"chunk_{idx:04d}.mov")
                build_chunk_clip(frame_paths, VIDEO_FPS, clip_path)
                clip_infos.append((clip_path, start, end, True))
            elif chunk.get("clip_path"):
                clip_infos.append((chunk["clip_path"], start, end, True))
            elif chunk.get("image_path"):
                clip_infos.append((chunk["image_path"], start, end, False))
            else:
                raise VideoBuildError(f"Chunk {idx} senza frame/immagine ne' clip: {chunk}")

        for clip_path, _s, _e, _is_vid in clip_infos:
            inputs.extend(["-i", clip_path])

        filter_parts = []
        last_label = "0:v"
        for idx, (_clip_path, start, end, is_video) in enumerate(clip_infos):
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
                    f"[{last_label}][{clip_label}]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
                )
            else:
                filter_parts.append(
                    f"[{last_label}][{input_index}:v]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
                )
            last_label = out_label
        filter_complex = ";".join(filter_parts)

    output_path = os.path.join(OUTPUT_DIR, output_filename)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
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
