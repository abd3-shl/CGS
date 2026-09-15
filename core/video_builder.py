"""
Modulo di composizione video: usa ffmpeg per unire uno sfondo colorato
(dal tema dinamico, default nero), la traccia audio generata e le immagini
dei sottotitoli (con i loro timestamp), producendo il file MP4 finale.
"""

import os
import re
import subprocess
import shutil

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


def build_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
) -> str:
    """
    Costruisce il video finale: sfondo colorato, audio narrato, sottotitoli
    sincronizzati come overlay PNG.

    Args:
        audio_path: percorso del file audio narrato.
        subtitle_chunks: lista di dict con "image_path", "start", "end"
                         (l'output di renderer.render_all_subtitles).
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
    """Rimuove i file temporanei generati durante il processo (audio, PNG sottotitoli)."""
    for fname in os.listdir(TEMP_DIR):
        fpath = os.path.join(TEMP_DIR, fname)
        try:
            if os.path.isfile(fpath):
                os.remove(fpath)
        except OSError:
            pass
