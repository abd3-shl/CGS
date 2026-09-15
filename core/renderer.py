"""
Modulo di rendering grafico: genera, per ogni chunk di sottotitolo,
un'immagine PNG trasparente con il testo centrato (stile "caption TikTok",
colore dal tema dinamico, senza contorno), pronta per essere sovrapposta
al video con ffmpeg.
Le parole chiave (vedi core/keywords.py) sono disegnate ognuna nel proprio colore.
"""

import os
from PIL import Image, ImageDraw, ImageFont

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    SUBTITLE_FONT_PATH,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_COLOR,
    SUBTITLE_STROKE_COLOR,
    SUBTITLE_STROKE_WIDTH,
    TEMP_DIR,
)
from core.keywords import normalize_word

# Font di sistema comuni, usati come fallback se non specificato in config.
_FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Carica il font indicato in config, oppure il primo fallback disponibile."""
    candidates = []
    if SUBTITLE_FONT_PATH:
        candidates.append(SUBTITLE_FONT_PATH)
    candidates.extend(_FALLBACK_FONTS)

    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    # Ultimo fallback: font di default di Pillow (bitmap, poco bello ma non crasha)
    return ImageFont.load_default()


def _wrap_words(words: list[str], font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[list[str]]:
    """Raggruppa le parole in righe che non superano la larghezza massima."""
    lines: list[list[str]] = []
    current: list[str] = []
    current_width = 0.0
    space_w = draw.textlength(" ", font=font)

    for word in words:
        w = draw.textlength(word, font=font)
        extra = w + (space_w if current else 0)
        if current_width + extra <= max_width or not current:
            current.append(word)
            current_width += extra
        else:
            lines.append(current)
            current = [word]
            current_width = w

    if current:
        lines.append(current)

    return lines


def render_subtitle_image(
    text: str,
    index: int,
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
) -> str:
    """
    Genera un'immagine PNG trasparente (stesse dimensioni del video) con il
    testo del sottotitolo centrato orizzontalmente e verticalmente.

    Args:
        text: testo del sottotitolo da renderizzare.
        index: indice del chunk, usato per il nome del file.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} per
            evidenziare le parole chiave (vedi core/keywords.py).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).
            Con chunk da 2-3 parole il font resta fisso: il risultato visivo
            è già proporzionato senza scaling adattivo.

    Returns:
        Percorso assoluto del file PNG generato.
    """
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = _load_font(SUBTITLE_FONT_SIZE)

    max_text_width = int(VIDEO_WIDTH * 0.85)
    lines = _wrap_words(text.split(), font, max_text_width, draw)
    space_w = draw.textlength(" ", font=font)

    # Calcola larghezza/altezza di ogni riga per centrarla.
    line_heights = []
    line_widths = []
    for words in lines:
        bbox = draw.textbbox((0, 0), " ".join(words), font=font)
        line_widths.append(
            sum(draw.textlength(w, font=font) for w in words) + space_w * (len(words) - 1)
        )
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = 12
    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    # Centro verticale (e orizzontale, vedi x sotto) del video.
    start_y = (VIDEO_HEIGHT - total_height) // 2

    y = start_y
    base_fill = text_color or SUBTITLE_COLOR
    for words, lw, lh in zip(lines, line_widths, line_heights):
        x = (VIDEO_WIDTH - lw) // 2
        for j, word in enumerate(words):
            if keyword_colors:
                fill = keyword_colors.get(normalize_word(word), base_fill)
            else:
                fill = base_fill
            draw.text(
                (x, y),
                word,
                font=font,
                fill=fill,
                stroke_width=SUBTITLE_STROKE_WIDTH,
                stroke_fill=SUBTITLE_STROKE_COLOR,
            )
            x += draw.textlength(word, font=font)
            if j < len(words) - 1:
                x += space_w
        y += lh + line_spacing

    output_path = os.path.join(TEMP_DIR, f"subtitle_{index:04d}.png")
    img.save(output_path)
    return output_path


def render_all_subtitles(
    chunks: list[dict],
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
) -> list[dict]:
    """
    Renderizza tutte le immagini dei sottotitoli per la lista di chunk.

    Args:
        chunks: lista di dict {"text", "start", "end"}.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} (opzionale).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).

    Returns:
        La stessa lista di chunk, con una chiave aggiuntiva "image_path".
    """
    enriched = []
    for i, chunk in enumerate(chunks):
        image_path = render_subtitle_image(chunk["text"], i, keyword_colors, text_color)
        enriched.append({**chunk, "image_path": image_path})
    return enriched
