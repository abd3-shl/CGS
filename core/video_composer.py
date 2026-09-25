"""
Video Composer (Full Engine Upgrade — Fase 5).

Compositing FFMPEG con Z-Index strict e filter-graph puliti:

  Z=0  background (tinta tema o Ken Burns dinamico)
  Z=10 character 2D (gia' composito nei micro-clip con pill/testo)
  Z=20 dimmer/vignette (solo sullo sfondo, mai sul testo)
  Z=30 kinetic subtitles & hero badges (nei micro-clip, sopra dimmer)
  Z=99 debug safe-zone overlay (solo render-mode=debug_safezones)

Architettura non-blocking: filter pesanti isolati in un unico
filter_complex; il mux audio/video finale e' un passaggio atomico separato
(`-c:v copy` quando possibile, altrimenti encode dedicato).

Se ENABLE_DYNAMIC_BACKGROUNDS=0: delega a `video_builder.build_video`
(legacy invariato). Altrimenti: sfondo Ken Burns (zoompan impercettibile
min(zoom+step,max) d=125 centrato) + vignette/dimmer, poi overlay chunk
come legacy (finestre contigue anti-blink, setpts, GOP 60).
"""

from __future__ import annotations

import os
import subprocess

try:
    from config import (
        DYNAMIC_BG_DURATION,
        DYNAMIC_BG_ZOOM_MAX,
        DYNAMIC_BG_ZOOM_STEP,
        ENABLE_DYNAMIC_BACKGROUNDS,
        FFMPEG_PRESET,
        OUTPUT_DIR,
        TEMP_DIR,
        VIDEO_FPS,
        VIDEO_HEIGHT,
        VIDEO_WIDTH,
    )
except Exception:  # config datata
    DYNAMIC_BG_DURATION = 125
    DYNAMIC_BG_ZOOM_MAX = 1.08
    DYNAMIC_BG_ZOOM_STEP = 0.0015
    ENABLE_DYNAMIC_BACKGROUNDS = True
    FFMPEG_PRESET = "veryfast"
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")
    VIDEO_FPS = 30
    VIDEO_HEIGHT = 1920
    VIDEO_WIDTH = 1080

from core.video_builder import (
    VideoBuildError,
    _check_ffmpeg,
    _chunk_frames,
    _ffmpeg_color,
    _get_audio_duration,
    _is_animated_chunk,
    build_chunk_clip,
    build_video as _legacy_build_video,
    cleanup_temp_files,
)


def kenburns_filter(duration_s: float) -> str:
    """Filtro zoompan Ken Burns impercettibile (mai eccezioni)."""
    try:
        zmax = max(1.0, min(1.5, float(DYNAMIC_BG_ZOOM_MAX)))
    except Exception:
        zmax = 1.08
    try:
        step = max(0.0002, min(0.01, float(DYNAMIC_BG_ZOOM_STEP)))
    except Exception:
        step = 0.0015
    try:
        d = max(25, int(DYNAMIC_BG_DURATION))
    except Exception:
        d = 125
    # zoompan lavora su still ingrandita (s=WxH upscalato): input color gia'
    # maggiorato 1.2x per avere pixel da zoomare senza bordi.
    return (
        f"zoompan=z='min(zoom+{step},{zmax})':d={d}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
    )


def dimmer_filter() -> str:
    """Dimmer/vignette Z=20 (contrasto sotto i sottotitoli, mai sul testo)."""
    return "eq=brightness=-0.03:saturation=1.05,vignette=PI/4"


def build_composed_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
    debug_safezones: bool = False,
) -> str:
    """Compone il video finale con background dinamico + dimmer + overlay.

    - Statico/animato come legacy (micro-clip .mov + overlay unico per chunk,
      finestre contigue clip_start/clip_end, setpts, GOP 60, faststart).
    - Sfondo: Ken Burns + dimmer quando ENABLE_DYNAMIC_BACKGROUNDS, altrimenti
      tinta unita legacy (delega diretta, zero divergenza).
    - debug_safezones=True: box rossi semi-trasparenti Z=99 sopra tutto.
    - Mux audio atomico separato alla fine (invariant non-blocking).
    """
    try:
        dyn = str(os.environ.get(
            "ENABLE_DYNAMIC_BACKGROUNDS", "1" if ENABLE_DYNAMIC_BACKGROUNDS else "0"
        )).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        dyn = bool(ENABLE_DYNAMIC_BACKGROUNDS)
    if not dyn and not debug_safezones:
        return _legacy_build_video(audio_path, subtitle_chunks, output_filename, background_color)

    _check_ffmpeg()
    duration = _get_audio_duration(audio_path)
    bg = _ffmpeg_color(background_color)
    # Sfondo maggiorato 1.2x per il crop dello zoom (niente bordi neri).
    big_w, big_h = int(VIDEO_WIDTH * 1.2), int(VIDEO_HEIGHT * 1.2)
    if big_w % 2:
        big_w += 1
    if big_h % 2:
        big_h += 1

    animated = any(_is_animated_chunk(c) for c in subtitle_chunks)

    def _window(c: dict, nxt: dict | None):
        try:
            s = float(c.get("clip_start", c.get("start", 0.0)))
        except (TypeError, ValueError):
            s = 0.0
        try:
            e = float(c.get("clip_end", c.get("end", s)))
        except (TypeError, ValueError):
            e = s
        if e <= s:
            e = s + 0.1
        if nxt is not None:
            try:
                ns = float(nxt.get("clip_start", nxt.get("start", e)))
            except (TypeError, ValueError):
                ns = e
            if ns > s and ns > e:
                e = ns
        return (s, e)

    # --- Micro-clip animati (come legacy, ThreadPool) ---
    import concurrent.futures as _fut

    clip_infos: list[tuple[str, float, float, bool] | None] = [None] * len(subtitle_chunks)
    jobs: list[tuple[int, list[str], str]] = []
    for idx, chunk in enumerate(subtitle_chunks):
        nxt_c = subtitle_chunks[idx + 1] if idx + 1 < len(subtitle_chunks) else None
        s, e = _window(chunk, nxt_c)
        if _is_animated_chunk(chunk):
            fps = chunk.get("fps", VIDEO_FPS) if isinstance(chunk, dict) else VIDEO_FPS
            frame_paths = _chunk_frames(chunk)
            if not frame_paths:
                raise VideoBuildError(f"Chunk animato {idx} senza frame.")
            clip_path = os.path.join(TEMP_DIR, f"chunk_{idx:04d}.mov")
            try:
                if os.path.isfile(clip_path):
                    cmt = os.path.getmtime(clip_path)
                    f0 = os.path.getmtime(frame_paths[0])
                    try:
                        f1 = os.path.getmtime(frame_paths[-1])
                    except (IndexError, OSError):
                        f1 = f0
                    if cmt >= f0 and cmt >= f1:
                        clip_infos[idx] = (clip_path, s, e, True)
                        continue
            except OSError:
                pass
            jobs.append((idx, frame_paths, clip_path))
            clip_infos[idx] = (clip_path, s, e, True)
        elif chunk.get("clip_path"):
            clip_infos[idx] = (chunk["clip_path"], s, e, True)
        elif chunk.get("image_path"):
            clip_infos[idx] = (chunk["image_path"], s, e, False)
        else:
            raise VideoBuildError(f"Chunk {idx} senza frame/immagine ne' clip: {chunk}")
    if jobs:
        try:
            cpu = max(2, (os.cpu_count() or 4))
        except Exception:
            cpu = 4
        workers = max(2, min(4, cpu - 1, len(jobs)))

        def _one(job: tuple[int, list[str], str]):
            _i, _fr, _out = job
            build_chunk_clip(_fr, VIDEO_FPS, _out)
            return _i

        with _fut.ThreadPoolExecutor(max_workers=workers) as _ex:
            for _fu in _fut.as_completed([_ex.submit(_one, j) for j in jobs]):
                _fu.result()
    clip_infos = [c for c in clip_infos if c is not None]

    # --- Filter graph: bg Ken Burns + dimmer, poi overlay chunk, poi debug ---
    inputs = [
        "-f", "lavfi",
        "-i", f"color=c={bg}:s={big_w}x{big_h}:r={VIDEO_FPS}:d={duration}",
        "-i", audio_path,
    ]
    for clip_path, _s, _e, _is_vid in clip_infos:
        inputs.extend(["-i", clip_path])

    parts: list[str] = []
    # Z=0 -> Z=20: background dinamico + dimmer/vignette (solo sfondo).
    parts.append(f"[0:v]{kenburns_filter(duration)}[bgzoom]")
    parts.append("[bgzoom]" + dimmer_filter() + "[base]")
    last = "base"
    for idx, (_clip_path, start, end, is_video) in enumerate(clip_infos):
        in_idx = idx + 2
        out = f"v{idx}"
        if is_video:
            cl = f"c{idx}"
            if _clip_path.lower().endswith(".webm"):
                parts.append(f"[{in_idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{start}/TB[{cl}]")
            else:
                parts.append(f"[{in_idx}:v]setpts=PTS-STARTPTS+{start}/TB[{cl}]")
            parts.append(f"[{last}][{cl}]overlay=0:0:enable='between(t,{start},{end})'[{out}]")
        else:
            parts.append(f"[{last}][{in_idx}:v]overlay=0:0:enable='between(t,{start},{end})'[{out}]")
        last = out
    if debug_safezones:
        # Z=99: box rossi UI (solo debug, sopra tutto, semi-trasparenti).
        try:
            from core.layout_guard import debug_safezone_boxes

            boxes = debug_safezone_boxes(VIDEO_WIDTH, VIDEO_HEIGHT)
            for bi, b in enumerate(boxes):
                out = f"dbg{bi}"
                parts.append(
                    f"[{last}]drawbox=x={int(b['x0'])}:y={int(b['y0'])}:"
                    f"w={int(b['x1']) - int(b['x0'])}:h={int(b['y1']) - int(b['y0'])}:"
                    f"color=red@0.35:t=fill[{out}]"
                )
                last = out
        except Exception:
            pass
    filter_complex = ";".join(parts)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    preset = (os.environ.get("FFMPEG_PRESET", FFMPEG_PRESET) or "veryfast").strip() or "veryfast"
    if preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
        preset = "veryfast"
    # Passaggio 1: video track (filter pesanti isolati) + mux atomico finale.
    cmd = ["ffmpeg", "-y", "-threads", "auto"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{last}]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", "20",
        "-g", "60",
        "-keyint_min", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-filter_threads", "auto",
        "-threads", "auto",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise VideoBuildError(f"ffmpeg video_composer ha fallito:\n{res.stderr[-2000:]}")
    return output_path
