"""
Modulo di rendering grafico v8: PNG trasparenti con testo confinato
nella Text Safe Zone (stile caption TikTok/Reels, stroke 0, ambient shadow
morbida + auto-pill solo se contrasto <80), pronti per ffmpeg overlay.

- Split 130% presenza piena (bbox visibile ancorata alla colonna + hard clamp
  dentro [20,1060], mai tagliata), center 125% naturale con occupancy top
  ~520 e fascia testo Y[140,490]; punch zoom 1.15x.
- `compute_word_layout` + `compute_auto_fit_layout`: wrapping FORZATO su
  (X_MAX-X_MIN), hard-clamp X/Y dentro il box, auto-fit 0.92x fino a 38px.
- `draw_word`: stroke 0 di default (nessun pavimento 5px), ombra (0,3,110).
- `calculate_character_transform`: scala width-based + ancoraggio per-preset
  (vedi layout_presets.character_anchor_y) + verify_zero_overlap().
"""

import os
from PIL import Image, ImageDraw, ImageFont

from config import (
    CHARACTER_ENABLED,
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

# Re-export per spec ("RENDER E POSIZIONAMENTO (core/renderer.py / ...)"):
# il calcolo bbox vive in core/character_selector.py, qui riesportato per API.
from core.character_selector import (
    calculate_character_bbox as calculate_character_bbox,
    character_target_height as character_target_height,
    resolve_chunk_layout as resolve_chunk_layout,
)
from core.layout_presets import (
    TEXT_PILL_FILL,
    TEXT_PILL_PAD,
    TEXT_PILL_RADIUS,
    HEADROOM_TOP,
    normalize_preset,
    character_anchor_y,
    character_occupancy_box,
    verify_zero_overlap,
    boxes_overlap,
    text_box_overlaps_character,
    preset_paste_x,
    preset_font_scale,
    preset_headroom_px,
    preset_needs_text_background,
    preset_overhang_x,
    preset_safe_area,
    preset_width_pct,
)
try:
    from core.layout_presets import TEXT_PILL_PAD_Y as _PILL_PAD_Y
except Exception:
    _PILL_PAD_Y = 10

# Ancoraggi verticali per-preset (Canvas 1080x1920): split Y~250, center ~500,
# punch ~110 — vedi PRESET_HEADROOM_PX in core/layout_presets.py.
# HEADROOM_TOP = 200 e' solo il default generico (vedi core/layout_presets.py).


def validate_character_bounds(paste_x, paste_y, scaled_w, scaled_h,
                              canvas_w: int = VIDEO_WIDTH,
                              canvas_h: int = VIDEO_HEIGHT) -> tuple[int, int, int, int]:
    """Sanity check v8 (mai solleva, mai crash).

    Range valido: 0<=py<=800 (split 100-400, center 400-600, punch 0-300).
    Fuori range: warning + clamp al bordo valido piu' vicino (non forza).
    Dimensioni degenerate clampate 1..8x canvas; fondo oltre bordo verificato.
    """
    try:
        cw = int(canvas_w)
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        ch = int(canvas_h)
    except (TypeError, ValueError):
        ch = VIDEO_HEIGHT
    try:
        px = int(paste_x)
    except (TypeError, ValueError):
        px = 0
    try:
        py = int(paste_y)
    except (TypeError, ValueError):
        py = int(HEADROOM_TOP)
    try:
        sw = int(scaled_w)
    except (TypeError, ValueError):
        sw = cw
    try:
        sh = int(scaled_h)
    except (TypeError, ValueError):
        sh = ch
    # Anti-buchi memoria / frame neri: dimensioni sane 1..8x canvas.
    if sw <= 0:
        sw = cw
    if sh <= 0:
        sh = ch
    if sw > cw * 8:
        sw = cw * 8
    if sh > ch * 8:
        sh = ch * 8
    # v8: 0<=py<=800 (split 250, center 500, punch 110). Clamp morbido.
    if py < 0 or py > 800:
        try:
            print(f"[renderer] warning: paste_y={paste_y} fuori range 0-800: clamp")
        except Exception:
            pass
        try:
            py = max(0, min(int(py), 800))
        except Exception:
            py = int(HEADROOM_TOP)
    # Fondo: deve spingere oltre il bordo (gambe tagliate in automatico).
    try:
        if py + sh < ch:
            print(f"[renderer] warning: fondo character a {py + sh} < canvas {ch} "
                  f"(gambe potenzialmente visibili / buco sotto)")
    except Exception:
        pass
    return (int(px), int(py), int(sw), int(sh))

# Cache layer personaggio width-based FULL-IMAGE {(pose, new_w, new_h): RGBA}.
# Niente trim (rimosso: disallineava il paste di +368px e tagliava il volto).
# Cap 32 (5 pose x 3 layout x 2 punch = 30 max + margine).
_character_layer_cache: dict[tuple[int, int, int], Image.Image] = {}
_CHARACTER_LAYER_CACHE_MAX: int = 32
# Cache matematica transform (stessi asset -> stessi numeri, mai ricalcolati):
# {(src_w, src_h, preset, punch, cw, ch): (new_w, new_h, paste_x, paste_y)}.
_transform_cache: dict[tuple[int, int, str, bool, int, int], tuple[int, int, int, int]] = {}
_TRANSFORM_CACHE_MAX: int = 128

# Font di sistema comuni, usati come fallback se non specificato in config.
_FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

# Spaziatura verticale tra righe (deve restare identica tra statico e animato).
LINE_SPACING = 12


_font_cache: dict[tuple[str | None, int], object] = {}
try:
    from functools import lru_cache as _lru  # noqa: F401
except Exception:
    pass


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Carica il font indicato in config, oppure il primo fallback disponibile (cachato)."""
    try:
        size_i = max(8, int(size))
    except (TypeError, ValueError):
        size_i = 64
    key = (SUBTITLE_FONT_PATH, size_i)
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    candidates = []
    if SUBTITLE_FONT_PATH:
        candidates.append(SUBTITLE_FONT_PATH)
    candidates.extend(_FALLBACK_FONTS)

    for path in candidates:
        try:
            if os.path.exists(path):
                f = ImageFont.truetype(path, size_i)
                if len(_font_cache) < 16:
                    _font_cache[key] = f
                return f
        except Exception:
            continue

    # Ultimo fallback: font di default di Pillow (bitmap, poco bello ma non crasha)
    fb = ImageFont.load_default()
    if len(_font_cache) < 16:
        _font_cache[key] = fb
    return fb


# Alias storico (retrocompatibilita' per import privati).
_load_font = load_font


def _wrap_words(words: list[str], font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[list[str]]:
    """Raggruppa le parole in righe che non superano la larghezza massima.

    WORD-WRAPPING FORZATO (zero-overlap v4): nessuna riga supera MAI
    max_width (= X_MAX-X_MIN della Safe Zone). Le parole singole piu' larghe
    del box vengono spezzate per caratteri (mai overflow sul personaggio).
    """
    # Pre-split: spezza parole ultra-lunghe per caratteri (mai overflow).
    expanded: list[str] = []
    try:
        mw = max(1, int(max_width))
    except (TypeError, ValueError):
        mw = int(max_width)
    for word in words:
        try:
            ww = draw.textlength(word, font=font)
        except Exception:
            expanded.append(word)
            continue
        if ww <= mw or len(word) <= 1:
            expanded.append(word)
            continue
        # Spezza per caratteri in chunk che stanno nel box.
        buf = ""
        for ch in word:
            try:
                tw = draw.textlength(buf + ch, font=font)
            except Exception:
                tw = mw + 1
            if tw <= mw or not buf:
                buf += ch
            else:
                expanded.append(buf)
                buf = ch
        if buf:
            expanded.append(buf)
    words = expanded
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


def _normalize_rgba(color: tuple | list | None, default: tuple) -> tuple[int, int, int, int]:
    """Normalizza un colore in RGBA (accetta RGB o RGBA, lista o tupla)."""
    if color is None:
        return default
    try:
        c = tuple(int(v) for v in color)
    except (TypeError, ValueError):
        return default
    if len(c) == 3:
        return (c[0], c[1], c[2], 255)
    if len(c) >= 4:
        return (c[0], c[1], c[2], c[3])
    return default


def compute_word_layout(
    words: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Calcola la posizione (x, y) finale di ogni parola, SENZA disegnare nulla.

    Usa la stessa logica di wrapping/centering del rendering statico:
    il risultato e' la posizione definitiva nel canvas VIDEO_WIDTH x VIDEO_HEIGHT.

    Args:
        words: parole del chunk in ordine (gia' splittate, es. text.split()).
        font: font Pillow caricato (vedi `load_font`).
        max_width: larghezza massima del blocco di testo (es. VIDEO_WIDTH * 0.85).
        area: Text Safe Area opzionale (x_min, y_min, x_max, y_max) dal sistema
            a zone (vedi core/layout_presets.py): il wrapping usa la larghezza
            del box e il blocco e' centrato DENTRO il box, non sullo schermo
            intero. None = comportamento storico (centro schermo).

    Returns:
        Lista parallela a `words`, un dict per parola:
        {"word": str, "x": int, "y": int, "width": int, "height": int}
        dove (x, y) e' l'angolo superiore-sinistro della parola e
        width/height sono le dimensioni misurate (textlength / altezza riga).
    """
    if not words:
        return []
    if area is not None:
        try:
            ax0, ay0, ax1, ay1 = (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
        except Exception:
            ax0, ay0, ax1, ay1 = (0, 0, VIDEO_WIDTH, VIDEO_HEIGHT)
        if ax1 > ax0 and ay1 > ay0:
            # REELS-FIX v5: larghezza STRETTAMENTE vincolata al box (mai 0.85*W).
            max_width = int(ax1 - ax0)
            center_x = (ax0 + ax1) / 2.0
            center_y = (ay0 + ay1) / 2.0
            use_area = True
        else:
            use_area = False
    else:
        use_area = False
    if not use_area:
        ax0, ay0, ax1, ay1 = (int(VIDEO_WIDTH * 0.075), 140,
                              int(VIDEO_WIDTH * 0.925), 720)
        center_x = VIDEO_WIDTH / 2.0
        center_y = (ay0 + ay1) / 2.0
        max_width = int(ax1 - ax0)
        use_area = True
    # Misuratore temporaneo: basta 64x64 per textlength/textbbox (no 1080x1920).
    try:
        from core.text_animator import _get_probe_draw as _shared_probe
        draw = _shared_probe()
    except Exception:
        probe = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
    space_w = draw.textlength(" ", font=font)

    lines = _wrap_words(words, font, max_width, draw)

    line_widths: list[float] = []
    line_heights: list[int] = []
    for line_words in lines:
        bbox = draw.textbbox((0, 0), " ".join(line_words), font=font)
        line_widths.append(
            sum(draw.textlength(w, font=font) for w in line_words) + space_w * (len(line_words) - 1)
        )
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1)
    start_y = int(round(center_y - total_height / 2.0))
    if use_area:
        # Hard-clamp verticale dentro il box (mai fuori, mai sopra la testa).
        if total_height >= (ay1 - ay0):
            start_y = int(ay0)
        else:
            start_y = max(int(ay0), min(int(start_y), int(ay1 - total_height)))

    layout: list[dict] = []
    y = start_y
    for line_words, lw, lh in zip(lines, line_widths, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            # REELS-FIX v5 hard-clamp: X in [ax0, ax1-lw] (mai fuori box,
            # mai VIDEO_WIDTH-8 che violava la colonna split).
            if lw >= (ax1 - ax0):
                x = float(ax0)
            else:
                x = max(float(ax0), min(float(x), float(ax1 - lw)))
        for j, word in enumerate(line_words):
            w = draw.textlength(word, font=font)
            layout.append({
                "word": word,
                "x": int(round(x)),
                "y": int(y),
                "width": int(round(w)),
                "height": int(lh),
            })
            x += w
            if j < len(line_words) - 1:
                x += space_w
        y += lh + LINE_SPACING
    # Hard-clamp finale assoluto: ogni parola dentro il box (mai fuori).
    if use_area:
        try:
            for _it in layout:
                try:
                    _it["x"] = max(int(ax0), min(int(_it["x"]), int(ax1 - _it["width"])))
                    _it["y"] = max(int(ay0), min(int(_it["y"]), int(ay1 - _it["height"])))
                except Exception:
                    continue
        except Exception:
            pass
    return layout


def compute_auto_fit_layout(words: list[str], font_size: int,
                            area: tuple[int, int, int, int] | None,
                            min_font_size: int = 38,
                            font_path: str | None = None) -> tuple[list[dict], object, int]:
    """Auto-fit dinamico REELS-FIX v5 (mai solleva, mai overflow).

    Prova font_size -> *0.92 fino a min_font_size finche' il blocco
    (total_height<=box_h e max_line<=box_w) rientra nel box. Ritorna
    (layout, font, size_usata). Larghezza strettamente ax1-ax0.
    """
    try:
        size = max(int(min_font_size), int(font_size or 54))
    except Exception:
        size = 54
    try:
        min_sz = max(20, int(min_font_size or 38))
    except Exception:
        min_sz = 38
    last_layout: list[dict] = []
    last_font = None
    last_size = size
    for _ in range(8):
        try:
            if font_path:
                try:
                    from PIL import ImageFont as _IF
                    f = _IF.truetype(font_path, size)
                except Exception:
                    f = load_font(size)
            else:
                f = load_font(size)
        except Exception:
            f = load_font(size)
        try:
            box_w = int(area[2]) - int(area[0]) if area else int(VIDEO_WIDTH * 0.85)
            box_h = int(area[3]) - int(area[1]) if area else 580
        except Exception:
            box_w, box_h = int(VIDEO_WIDTH * 0.85), 580
        try:
            lay = compute_word_layout(list(words or []), f, max(40, box_w), area=area)
        except Exception:
            return (last_layout, last_font or f, last_size)
        last_layout, last_font, last_size = lay, f, size
        try:
            if not lay:
                return (lay, f, size)
            xs = [int(it["x"]) for it in lay]
            ys = [int(it["y"]) for it in lay]
            xe = [int(it["x"]) + int(it["width"]) for it in lay]
            ye = [int(it["y"]) + int(it["height"]) for it in lay]
            bb_w = max(xe) - min(xs) if xs else 0
            bb_h = max(ye) - min(ys) if ys else 0
        except Exception:
            return (lay, f, size)
        if bb_w <= box_w + 1 and bb_h <= box_h + 1:
            return (lay, f, size)
        if size <= min_sz:
            return (lay, f, size)
        size = max(min_sz, int(round(size * 0.92)))
        if size >= last_size:
            return (lay, f, size)
    return (last_layout, last_font, last_size)


def text_layout_bbox(layout: list[dict]) -> tuple[int, int, int, int] | None:
    """BBox (x0,y0,x1,y1) del layout testo o None se vuoto (mai solleva)."""
    try:
        if not layout:
            return None
        x0 = min(int(it["x"]) for it in layout)
        y0 = min(int(it["y"]) for it in layout)
        x1 = max(int(it["x"]) + int(it["width"]) for it in layout)
        y1 = max(int(it["y"]) + int(it["height"]) for it in layout)
        if x1 > x0 and y1 > y0:
            return (int(x0), int(y0), int(x1), int(y1))
        return None
    except Exception:
        return None


def should_auto_pill(text_rgba, background_hex_or_rgba=None) -> bool:
    """Vero se serve la pill dietro il testo (mai solleva).

    - Testo scuro su sfondo scuro (ffmpeg applica tinta unita; senza bg
      esplicito si assume nero): contrasto insufficiente.
    - Testo grigio slavato (lum 100-200) su sfondo scuro (lum <70): il
      controllo luminanza standard lo promuove ma resta slavato.
    Lo stroke resta sempre 0: la leggibilita' viene dalla pill, mai bordi.
    """
    try:
        from config import THEME_MIN_LUMINANCE_DIFF as _MD
        md = float(_MD)
    except Exception:
        md = 80.0
    try:
        t = _normalize_rgba(text_rgba, SUBTITLE_COLOR)
        tlum = 0.299 * int(t[0]) + 0.587 * int(t[1]) + 0.114 * int(t[2])
    except Exception:
        return False
    try:
        if background_hex_or_rgba is None:
            blum = 0.0
        else:
            from core.text_animator import _to_rgba as _c2r  # lazy, evita cicli
            b = _c2r(background_hex_or_rgba, (0, 0, 0, 255))
            blum = 0.299 * int(b[0]) + 0.587 * int(b[1]) + 0.114 * int(b[2])
    except Exception:
        blum = 0.0
    try:
        if abs(tlum - blum) < md and tlum < 60:
            return True
        if blum < 70.0 and 100.0 <= tlum <= 200.0:
            return True
    except Exception:
        pass
    return False


def draw_text_background(
    img: Image.Image,
    layout: list[dict],
    fill: tuple[int, int, int, int] = TEXT_PILL_FILL,
    pad: int = TEXT_PILL_PAD,
    radius: int = TEXT_PILL_RADIUS,
    pad_y: int | None = None,
) -> None:
    """Auto-pill elegante REELS-FIX v5 (stroke 0, pill solo se serve).

    BBox del layout espanso di pad_x=20 / pad_y=10, radius 24. Chiamare PRIMA
    di draw_word (Z: pill sotto testo, sopra personaggio).
    """
    if not layout:
        return
    try:
        _py = int(pad_y) if pad_y is not None else int(_PILL_PAD_Y)
    except Exception:
        _py = 10
    try:
        x0 = min(item["x"] for item in layout) - pad
        y0 = min(item["y"] for item in layout) - _py
        x1 = max(item["x"] + item["width"] for item in layout) + pad
        y1 = max(item["y"] + item["height"] for item in layout) + _py
    except (KeyError, TypeError, ValueError):
        return
    cw, ch = img.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(cw, x1), min(ch, y1)
    if x1 <= x0 or y1 <= y0:
        return
    draw = ImageDraw.Draw(img)
    try:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    except (AttributeError, ValueError, TypeError):
        draw.rectangle([x0, y0, x1, y1], fill=fill)


def draw_word(
    draw: ImageDraw.ImageDraw,
    word: str,
    position: tuple,
    font: ImageFont.FreeTypeFont,
    fill_color: tuple,
    stroke_color: tuple | None = None,
    stroke_width: int = 0,
    opacity: int = 255,
    shadow_offset: tuple[int, int] | None = (0, 3),
    shadow_fill: tuple | None = (0, 0, 0, 110),
) -> None:
    """Disegna una singola parola REELS-FIX v5 (stroke 0, ambient shadow).

    Stroke 0 assoluto di default (nessun pavimento 5px): se stroke_width<=0
    nessun contorno. Ombra morbida (0,3,110) sempre sotto il testo per
    profondita' senza contorno netto. Auto-pill gestita dal chiamante.
    """
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    fill = _normalize_rgba(fill_color, SUBTITLE_COLOR)
    # REELS-FIX v5: stroke 0 consentito (nessun forcing a 5px).
    try:
        sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        sw = 0
    if sw < 0:
        sw = 0
    if sw > 8:
        sw = 8
    stroke = None
    if sw > 0:
        stroke = _normalize_rgba(stroke_color, (0, 0, 0, 255))
        try:
            if len(stroke) >= 4 and int(stroke[3]) <= 0:
                stroke = (0, 0, 0, 255)
        except Exception:
            stroke = (0, 0, 0, 255)
    if opacity < 255:
        factor = opacity / 255.0
        fill = (fill[0], fill[1], fill[2], int(round(fill[3] * factor)))
        if stroke is not None:
            stroke = (stroke[0], stroke[1], stroke[2], int(round(stroke[3] * factor)))
    x, y = position
    # Ambient shadow morbida (0,3,110) prima del testo.
    try:
        if shadow_fill is not None and shadow_offset is not None:
            sox, soy = int(shadow_offset[0]), int(shadow_offset[1])
            sh = _normalize_rgba(shadow_fill, (0, 0, 0, 110))
            if sh[3] > 0:
                sh_a = int(round(sh[3] * (opacity / 255.0)))
                draw.text((int(x) + sox, int(y) + soy), word, font=font,
                          fill=(sh[0], sh[1], sh[2], sh_a))
    except Exception:
        pass
    try:
        if sw > 0 and stroke is not None:
            draw.text((x, y), word, font=font, fill=fill,
                      stroke_width=sw, stroke_fill=stroke)
        else:
            draw.text((x, y), word, font=font, fill=fill)
    except Exception:
        try:
            draw.text((x, y), word, font=font, fill=fill)
        except Exception:
            pass


def _paste_character_clipped(canvas: Image.Image, char_img: Image.Image, x: int, y: int) -> None:
    """Incolla il personaggio sul canvas gestendo posizioni parzialmente fuori campo."""
    try:
        try:
            canvas.alpha_composite(char_img, (int(x), int(y)))
            return
        except (ValueError, AttributeError):
            pass
        canvas.paste(char_img, (int(x), int(y)), char_img)
        return
    except ValueError:
        pass
    # Fallback: ritaglia la porzione visibile.
    cw, ch = canvas.size
    iw, ih = char_img.size
    fx0, fy0 = max(0, int(x)), max(0, int(y))
    tx0, ty0 = fx0 - int(x), fy0 - int(y)
    tx1 = min(iw, cw - int(x))
    ty1 = min(ih, ch - int(y))
    if tx1 > tx0 and ty1 > ty0:
        cropped = char_img.crop((tx0, ty0, tx1, ty1))
        canvas.paste(cropped, (fx0, fy0), cropped)


def calculate_character_transform(
    image_size: tuple[int, int],
    layout_preset: str,
    is_punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
    pose: int | None = None,
) -> tuple[int, int, int, int]:
    """Coordinate overlay width-based (v8 presenza piena, taglio impossibile).

    - Larghezza: preset_width_pct (split 130%, center 125%, punch 170% /
      1.15x), poi EMERGENCY AUTOSCALE negli split: se la bbox visibile della
      posa supera 690px (su 1080) la scala scende (*0.95) finche' il
      personaggio entra nella sua meta' schermo (mai sotto 0.60 assoluto).
    - X: ancoraggio di colonna sulla bbox VISIBILE (25% SX / 75% DX =
      paste_x = canvas_w * frac - (bx0*k + vis_w*k/2)) + hard clamp dentro
      [20px, canvas-20px]. NESSUN offset hardcoded: la posizione deriva da
      larghezza canvas, larghezza scalata e bbox reale della posa.
    - Y: preset_headroom_px() per-preset (center 500, split 250, punch 110)
      con fallback bottom-anchor se il fondo restasse sopra il bordo
      (gambe sempre fuori).
    La bbox visibile (viso+busto) non esce MAI dal canvas; il testo usa la
    Safe Area dinamica fino a 40px prima del personaggio (zero overlap).
    """
    try:
        src_w, src_h = int(image_size[0]), int(image_size[1])
    except (TypeError, ValueError):
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT
    if src_w <= 0 or src_h <= 0:
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT
    try:
        cw = int(canvas_w)
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        ch = int(canvas_h)
    except (TypeError, ValueError):
        ch = VIDEO_HEIGHT

    preset = normalize_preset(layout_preset)
    try:
        _pose_key: int | None = int(pose) if pose is not None else None
    except Exception:
        _pose_key = None
    # Fast-path cachato (chiave include la posa: paste split per-posa).
    try:
        _tkey = (int(src_w), int(src_h), str(preset), bool(is_punch_in), int(cw), int(ch), _pose_key)
        _thit = _transform_cache.get(_tkey)
        if _thit is not None:
            return (int(_thit[0]), int(_thit[1]), int(_thit[2]), int(_thit[3]))
    except Exception:
        _tkey = None
    new_w = max(1, int(round(cw * preset_width_pct(preset, bool(is_punch_in)))))
    new_h = max(1, int(round(src_h * new_w / float(src_w))))

    # v7 FIT-TO-HALF: negli split riduci la taglia se la bbox visibile
    # supera la mezza colonna (stessa funzione usata da occupancy e testo).
    if preset in ("layout_split_left", "layout_split_right"):
        try:
            from core.layout_presets import fitted_split_character_size as _fit_sz
            from core.layout_presets import preset_width_pct as _pwp
            _base_pct = float(_pwp(preset, bool(is_punch_in)))
            _fw, _fh, _fs = _fit_sz(preset, int(src_w), int(src_h),
                                    int(cw), _base_pct, _pose_key)
            if float(_fs) < float(new_w) / float(src_w) - 1e-9:
                new_w, new_h = int(_fw), int(_fh)
        except Exception:
            pass

    # X ancorato alla bbox visibile su split (viso+busto SEMPRE dentro con
    # margine 20px: ancoraggio di colonna + hard clamp, mai fuori canvas).
    try:
        if _pose_key is not None and preset in ("layout_split_left", "layout_split_right"):
            from core.layout_presets import pose_paste_x as _ppx
            paste_x = int(_ppx(_pose_key, preset, new_w, cw))
        else:
            paste_x = int(preset_paste_x(preset, new_w, cw))
    except Exception:
        paste_x = (cw - new_w) // 2

    # Y per-preset con fallback bottom-anchor (testa in campo, gambe fuori).
    try:
        paste_y = int(preset_headroom_px(preset, ch))
    except Exception:
        try:
            paste_y = int(character_anchor_y(ch, preset))
        except Exception:
            paste_y = int(HEADROOM_TOP)
    try:
        if int(paste_y) + int(new_h) < int(ch):
            paste_y = int(ch) - int(new_h)
    except Exception:
        pass

    # Sanity check prima del return (testa Y=200, fondo oltre bordo).
    # validate ritorna (px, py, sw, sh): riapplica per coerenza + X validato.
    try:
        vpx, vpy, vsw, vsh = validate_character_bounds(
            paste_x, paste_y, new_w, new_h, cw, ch)
        paste_x, paste_y, new_w, new_h = int(vpx), int(vpy), int(vsw), int(vsh)
    except Exception:
        pass
    _res = (int(new_w), int(new_h), int(paste_x), int(paste_y))
    try:
        if _tkey is not None:
            if len(_transform_cache) >= _TRANSFORM_CACHE_MAX:
                _transform_cache.clear()
            _transform_cache[_tkey] = _res
    except Exception:
        pass
    return _res


def preload_character_layers(canvas_w: int = VIDEO_WIDTH,
                               canvas_h: int = VIDEO_HEIGHT) -> int:
    """Warmup RAM v2: precarica in memoria tutti i layer personaggio standard.

    Precarica le 5 pose x 3 layout principali (center + 2 split) + varianti
    punch: azzera resize LANCZOS in loop frame. Ritorna n. layer precaricati.
    Mai solleva (fail-safe: asset mancanti saltati con warning).
    """
    try:
        from core.character_selector import CHARACTER_POSE_COUNT as _N
    except Exception:
        _N = 5
    layouts = ("layout_center_standard", "layout_split_left", "layout_split_right")
    ok = 0
    for pose in range(1, int(_N) + 1):
        for lay in layouts:
            for punch in (False, True):
                try:
                    get_character_layer(pose, lay, punch, canvas_w, canvas_h)
                    ok += 1
                except Exception as e:
                    try:
                        print(f"[renderer] warning: layer posa {pose}/{lay}"
                              f"{' punch' if punch else ''} saltato ({e})")
                    except Exception:
                        pass
    return ok


def get_character_layer(
    pose: int,
    layout_preset: str,
    is_punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[Image.Image, int, int]:
    """Layer personaggio (v6 face-anchor: full-image, niente trim).

    RIMOSSO il trim del bbox alpha: spostava il paste di +368px a destra e,
    combinato col paste fisso, tagliava meta' volto sul bordo destro (e la
    posa 2 larga copriva il testo). Il layer intero (con padding trasparente)
    si incolla esattamente a (px,py) da calculate_character_transform
    (face-anchor 25%/75%, volto integro): costo +~10ms/frame.
    """
    from core.character_selector import load_character_original
    try:
        original = load_character_original(pose)
    except Exception:
        raise
    try:
        _pp: int | None = None
        try:
            _pp = int(pose)
        except Exception:
            _pp = None
        new_w, new_h, px, py = calculate_character_transform(
            original.size, layout_preset, is_punch_in, canvas_w, canvas_h,
            pose=_pp)
    except Exception:
        new_w, new_h, px, py = int(canvas_w * 1.30), int(canvas_h), 0, int(HEADROOM_TOP)
    try:
        px, py, new_w, new_h = validate_character_bounds(
            px, py, new_w, new_h, canvas_w, canvas_h)
    except Exception:
        pass
    try:
        from core.layout_presets import verify_perfect_crop
        try:
            _vpunch = bool(is_punch_in)
        except Exception:
            _vpunch = False
        check = verify_perfect_crop(new_w, new_h, px, py, canvas_w, canvas_h,
                                    layout_preset, _vpunch)
        if not check.get("ok"):
            try:
                print(f"[renderer] warning: fuori invariante "
                      f"posa {pose}/{layout_preset} scala {check.get('scale_pct', 0):.2f} "
                      f"head_ok={check.get('head_ok')} anchored={check.get('anchored')}")
            except Exception:
                pass
    except Exception:
        pass
    key = (int(pose), new_w, new_h)
    cached = _character_layer_cache.get(key)
    if cached is None:
        try:
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:  # Pillow < 9.1
                resample = Image.LANCZOS
            full = original.resize((new_w, new_h), resample)
            if full.mode != "RGBA":
                full = full.convert("RGBA")
            cached = full
            if len(_character_layer_cache) >= _CHARACTER_LAYER_CACHE_MAX:
                _character_layer_cache.clear()
            _character_layer_cache[key] = cached
        except Exception:
            try:
                return original.copy(), px, py
            except Exception:
                raise
    try:
        return cached.copy(), px, py
    except Exception:
        return cached, px, py


def clear_character_layer_cache() -> None:
    """Svuota le cache dei layer (immagini + transform)."""
    _character_layer_cache.clear()
    try:
        _transform_cache.clear()
    except Exception:
        pass


def _draw_character_static(img: Image.Image, character: dict | None) -> None:
    """Disegna il personaggio sul frame (Z-index: sopra lo sfondo, sotto i sottotitoli).

    `character` e' un dict di metadati come arricchito in main.py via
    core/character_selector.enrich_chunks_with_characters (oppure il chunk
    stesso). La risoluzione passa da `resolve_chunk_layout`: col preset valido
    si usa `get_character_layer` (scala 130-140% + ancoraggio ALTO Y=200,
    punch_in amplificato), altrimenti il posizionamento legacy v1 (validato
    anti-decapitazione: mai testa fuori schermo).
    Errori non bloccanti (asset mancante, posa invalida): nessun disegno.
    """
    if not CHARACTER_ENABLED:
        return
    try:
        from core.character_selector import resolve_chunk_layout as _resolve
        info = _resolve(character) if isinstance(character, dict) else None
    except Exception:
        return
    if info is None:
        return
    try:
        if info["use_preset"]:
            char_img, x, y = get_character_layer(
                info["pose"], info["layout"], info.get("punch_in", False),
                VIDEO_WIDTH, VIDEO_HEIGHT)
        else:
            from core.character_selector import (
                character_target_height,
                load_and_process_character_image,
            )
            target_h = character_target_height(info["scale"], VIDEO_HEIGHT)
            char_img = load_and_process_character_image(info["pose"], target_h)
            x, y = calculate_character_bbox(char_img.size, info["position"], VIDEO_WIDTH, VIDEO_HEIGHT)
            # Sanity anti-decapitazione anche sul path legacy.
            try:
                x, y, _sw, _sh = validate_character_bounds(
                    x, y, char_img.size[0], char_img.size[1],
                    VIDEO_WIDTH, VIDEO_HEIGHT)
            except Exception:
                pass
    except Exception:
        return
    _paste_character_clipped(img, char_img, x, y)


def _resolve_safe_area(
    character: dict | None,
    safe_area: tuple[int, int, int, int] | None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> tuple[tuple[int, int, int, int] | None, bool, float]:
    """Safe area effettiva + flag pill + scala font per il testo.

    Precedenza: `text_safe_area` > `safe_area` > preset del character >
    None (centro schermo storico). Ritorna (area_o_None, needs_pill, font_scale).
    Negli split il box e' DINAMICO (v7): dal bordo opposto fino a 40px prima
    del bbox reale del personaggio, cosi' il gutter non e' mai un abisso e
    l'overlap e' strutturalmente impossibile.
    """
    for explicit in (text_safe_area, safe_area):
        if explicit is not None:
            try:
                box = (int(explicit[0]), int(explicit[1]), int(explicit[2]), int(explicit[3]))
                if box[2] > box[0] and box[3] > box[1]:
                    return box, False, 1.0
            except (TypeError, ValueError, IndexError):
                pass
    if isinstance(character, dict):
        try:
            from core.character_selector import resolve_chunk_layout as _resolve
            info = _resolve(character)
        except Exception:
            info = None
        if info is not None and info["use_preset"]:
            preset = info["layout"]
            if preset in ("layout_split_left", "layout_split_right"):
                try:
                    from core.layout_presets import preset_safe_area_dynamic as _dyn
                    _pp: int | None = None
                    try:
                        _pp = int(info.get("pose"))
                    except Exception:
                        _pp = None
                    return (_dyn(preset, VIDEO_WIDTH, VIDEO_HEIGHT, _pp,
                                bool(info.get("punch_in", False))),
                            preset_needs_text_background(preset),
                            preset_font_scale(preset))
                except Exception:
                    pass
            return (preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT),
                    preset_needs_text_background(preset),
                    preset_font_scale(preset))
    return None, False, 1.0


def _character_info_from_chunk(chunk: dict) -> dict | None:
    """Estrae i metadati character da un chunk arricchito (o None se assenti)."""
    if not isinstance(chunk, dict) or chunk.get("pose") is None:
        return None
    info: dict = {
        "pose": chunk.get("pose"),
        "position": chunk.get("position", "bottom_center"),
        "transition": chunk.get("transition", "slide_up"),
        "scale": chunk.get("scale", 0.75),
    }
    # Chiavi del sistema a zone (se presenti, il render le preferisce).
    if chunk.get("layout") is not None:
        info["layout"] = chunk.get("layout")
    if chunk.get("layout_preset") is not None:
        info["layout_preset"] = chunk.get("layout_preset")
    if chunk.get("punch_in") is not None:
        info["punch_in"] = chunk.get("punch_in")
    if chunk.get("transition_in") is not None:
        info["transition_in"] = chunk.get("transition_in")
    return info


def render_subtitle_image(
    text: str,
    index: int,
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
    character: dict | None = None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> str:
    """
    Genera un'immagine PNG trasparente (stesse dimensioni del video) con il
    testo del sottotitolo confinato nella Text Safe Area del layout.

    Args:
        text: testo del sottotitolo da renderizzare.
        index: indice del chunk, usato per il nome del file.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} per
            evidenziare le parole chiave (vedi core/keywords.py).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).
        character: metadati character {"pose","layout","punch_in",...}
            (opzionale, cfr. core/character_selector.py). Z-index: il
            personaggio e' disegnato PRIMA del testo (tra sfondo e sottotitoli).
            Col preset valido, scala width-based/ancoraggio/safe area seguono
            il preset (punch_in amplificato).
        safe_area: Text Safe Area esplicita (x_min, y_min, x_max, y_max);
            se assente si usa quella del preset, altrimenti centro schermo.
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.

    Returns:
        Percorso assoluto del file PNG generato.
    """
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    # Z-index 2: personaggio (lo sfondo tinta unita e' applicato da ffmpeg).
    if character is not None:
        _draw_character_static(img, character)
    area, needs_pill, font_scale = _resolve_safe_area(character, safe_area, text_safe_area)
    if area is None:
        area = (90, 140, 990, 720)

    # REELS-FIX v5 auto-fit: base 54*scale, minimo 38px, mai gigante.
    try:
        from config import SUBTITLE_MIN_FONT_SIZE as _MIN_FS
        _min_fs = int(_MIN_FS)
    except Exception:
        _min_fs = 38
    try:
        target_size = int(round(int(SUBTITLE_FONT_SIZE) * float(font_scale)))
    except Exception:
        target_size = int(SUBTITLE_FONT_SIZE)
    words = text.split()
    # Boost chunk corti (1-3 parole): +20% fino a 76px, mai oltre il box
    # (l'auto-fit riduce se serve). Evita caption mingherline tipo "fermi".
    if 0 < len(words) <= 3:
        try:
            target_size = min(76, int(round(target_size * 1.2)))
        except Exception:
            pass
    layout, font, _used = compute_auto_fit_layout(words, target_size, area,
                                                  min_font_size=_min_fs)

    # Z-index 2.5: pill se preset punch-in, testo scuro o testo grigio
    # slavato su sfondo scuro (auto-pill, stroke resta 0).
    try:
        _show_pill = bool(needs_pill)
        if not _show_pill and layout:
            _show_pill = bool(should_auto_pill(text_color or SUBTITLE_COLOR,
                                               None))
        if _show_pill:
            draw_text_background(img, layout)
    except Exception:
        if needs_pill:
            try:
                draw_text_background(img, layout)
            except Exception:
                pass

    draw = ImageDraw.Draw(img)

    # REELS-FIX v5: stroke 0 (nessun forcing), ambient shadow (0,3,110).
    try:
        _sw = int(SUBTITLE_STROKE_WIDTH)
    except (TypeError, ValueError):
        _sw = 0
    if _sw < 0:
        _sw = 0
    base_fill = text_color or SUBTITLE_COLOR
    for item in layout:
        word = item["word"]
        if keyword_colors:
            fill = keyword_colors.get(normalize_word(word), base_fill)
        else:
            fill = base_fill
        draw_word(
            draw, word, (item["x"], item["y"]), font,
            fill, (0, 0, 0, 0), _sw,
            opacity=255, shadow_offset=(0, 3), shadow_fill=(0, 0, 0, 110),
        )

    # SANITY CHECK geometrico per-posa (warning, mai crash):
    # 1) testo mai sopra il character (IoU==0) 2) faccia sempre in campo.
    try:
        _tb = text_layout_bbox(layout)
        if character is not None:
            try:
                from core.character_selector import resolve_chunk_layout as _res
                _info = _res(character) if isinstance(character, dict) else None
            except Exception:
                _info = None
            if _info is not None and _info.get("use_preset"):
                try:
                    _pose_chk: int | None = None
                    try:
                        _pose_chk = int(_info.get("pose"))
                    except Exception:
                        _pose_chk = None
                    if _tb is not None:
                        _occ = character_occupancy_box(
                            _info.get("layout"), bool(_info.get("punch_in", False)),
                            None, None, VIDEO_WIDTH, VIDEO_HEIGHT, None, _pose_chk)
                        verify_zero_overlap(_tb, _occ, 24)
                except AssertionError as _ae:
                    try:
                        print(f"[renderer] CRITICAL overlap statico: {_ae}")
                    except Exception:
                        pass
                # Faccia in campo: usa il layer effettivo appena disegnato.
                try:
                    from core.layout_presets import verify_face_visible as _vfv
                    _ci = _character_info_from_chunk(
                        character if isinstance(character, dict) else {})
                    _lay = get_character_layer(
                        int(_info.get("pose")), _info.get("layout"),
                        bool(_info.get("punch_in", False)),
                        VIDEO_WIDTH, VIDEO_HEIGHT) if _info.get("pose") is not None else None
                    if _lay is not None:
                        _img_lay, _lx, _ly = _lay
                        try:
                            _lw, _lh = _img_lay.size
                        except Exception:
                            _lw, _lh = VIDEO_WIDTH, VIDEO_HEIGHT
                        _vfv(_info.get("pose"), int(_lx), int(_ly),
                             int(_lw), int(_lh), VIDEO_WIDTH, VIDEO_HEIGHT)
                except AssertionError as _fe:
                    try:
                        print(f"[renderer] CRITICAL faccia fuori campo: {_fe}")
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        pass

    # SANITY CHECK prima del save: dimensioni canvas + no frame degeneri.
    try:
        if img.size != (VIDEO_WIDTH, VIDEO_HEIGHT):
            print(f"[renderer] warning: frame size {img.size} != "
                  f"({VIDEO_WIDTH},{VIDEO_HEIGHT})")
    except Exception:
        pass
    try:
        # Frame completamente vuoto (né testo né character): warning, mai crash.
        # (Sfondo trasparente e' normale: il colore viene da ffmpeg; il check
        # rileva solo frame senza alcun contenuto = possibile buco.)
        if not layout and character is None:
            print("[renderer] warning: frame vuoto (nessun testo/character)")
    except Exception:
        pass
    output_path = os.path.join(TEMP_DIR, f"subtitle_{index:04d}.png")
    img.save(output_path)
    return output_path


def render_all_subtitles(
    chunks: list[dict],
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
    character_plan: list[dict] | None = None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """
    Renderizza tutte le immagini dei sottotitoli per la lista di chunk.

    Args:
        chunks: lista di dict {"text", "start", "end", ...}. Se i chunk sono
            gia' arricchiti con pose/layout/punch_in (vedi
            core/character_selector.enrich_chunks_with_characters), il
            personaggio viene disegnato sotto il testo (Z-index corretto) e il
            testo e' confinato nella safe area del preset.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} (opzionale).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).
        character_plan: piano opzionale parallelo a `chunks` (stesso formato
            di plan_character_layout); se fornito, ha precedenza sui metadati
            gia' presenti nei chunk.
        safe_area: Text Safe Area esplicita per TUTTI i chunk (override del
            preset; None = preset del chunk o centro schermo).
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.

    Returns:
        La stessa lista di chunk, con una chiave aggiuntiva "image_path".
    """
    enriched = []
    for i, chunk in enumerate(chunks):
        if character_plan is not None and i < len(character_plan) and isinstance(character_plan[i], dict):
            character = character_plan[i]
        else:
            character = _character_info_from_chunk(chunk)
        image_path = render_subtitle_image(chunk["text"], i, keyword_colors, text_color, character, safe_area, text_safe_area)
        enriched.append({**chunk, "image_path": image_path})
    return enriched
