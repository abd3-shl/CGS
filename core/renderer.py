"""
Modulo di rendering grafico: genera, per ogni chunk di sottotitolo,
un'immagine PNG trasparente con il testo centrato (stile "caption TikTok",
colore dal tema dinamico, senza contorno), pronta per essere sovrapposta
al video con ffmpeg.
Le parole chiave (vedi core/keywords.py) sono disegnate ognuna nel proprio colore.

Fase 3: la logica di layout/wrapping e di disegno della singola parola e'
estratta in funzioni pure riusabili (`compute_word_layout`, `draw_word`),
usate sia dal rendering statico (compatibilita'/fallback) sia dal modulo
animato `core/text_animator.py` (pre-calcolo layout fisso + frame per-parola).

Dynamic Layout: `compute_word_layout` accetta una Text Safe Area
`(x_min, y_min, x_max, y_max)` e centra il testo dentro quel box (wrapping
sulla sua larghezza, con rete anti-sconfinamento); col preset punch-in il
testo e' protetto da una pill ad alto contrasto (`draw_text_background`).
`calculate_character_transform` scala su larghezza (120-180%) con ancoraggio
dal basso: niente figura intera, piedi mai visibili (`get_character_layer`
cachato, usato da statico e animato).
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
    normalize_preset,
    preset_font_scale,
    preset_headroom_px,
    preset_needs_text_background,
    preset_overhang_x,
    preset_safe_area,
    preset_width_pct,
)

# Cache layer personaggio width-based: {(pose, new_w, new_h): PIL.Image RGBA}.
_character_layer_cache: dict[tuple[int, int, int], Image.Image] = {}

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
        ax0, ay0, ax1, ay1 = (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
        if ax1 > ax0 and ay1 > ay0:
            max_width = min(int(max_width), ax1 - ax0)
            center_x = (ax0 + ax1) / 2.0
            center_y = (ay0 + ay1) / 2.0
            use_area = True
        else:
            use_area = False
    else:
        use_area = False
    if not use_area:
        center_x = VIDEO_WIDTH / 2.0
        center_y = VIDEO_HEIGHT / 2.0
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
        # Il blocco resta dentro la safe area quando ci sta.
        start_y = max(ay0, min(start_y, ay1 - total_height))

    layout: list[dict] = []
    y = start_y
    for line_words, lw, lh in zip(lines, line_widths, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            # Rete di sicurezza: la riga non sconfina mai a sinistra nella zona
            # personaggio (parole singole piu' larghe del box slitta a destra,
            # verso il margine schermo che e' sempre zona sicura del testo).
            x = max(float(ax0), x)
            if x + lw > VIDEO_WIDTH - 8:
                x = max(float(ax0), VIDEO_WIDTH - 8 - lw)
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
    return layout


def draw_text_background(
    img: Image.Image,
    layout: list[dict],
    fill: tuple[int, int, int, int] = TEXT_PILL_FILL,
    pad: int = TEXT_PILL_PAD,
    radius: int = TEXT_PILL_RADIUS,
) -> None:
    """Disegna la pill semi-trasparente dietro il blocco di testo (closeup).

    Usa il bounding box del `layout` (vedi `compute_word_layout`) espanso di
    `pad` px. Non fa nulla con layout vuoto. Va chiamata PRIMA di `draw_word`
    (Z-index: pill sotto il testo, sopra il personaggio).
    """
    if not layout:
        return
    try:
        x0 = min(item["x"] for item in layout) - pad
        y0 = min(item["y"] for item in layout) - pad
        x1 = max(item["x"] + item["width"] for item in layout) + pad
        y1 = max(item["y"] + item["height"] for item in layout) + pad
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
) -> None:
    """Disegna una singola parola nel contesto dato.

    Funzione pura riusabile: non crea immagini, disegna solo la parola
    nella posizione pre-calcolata (vedi `compute_word_layout`).

    Args:
        draw: contesto ImageDraw dell'immagine di destinazione.
        word: testo della parola.
        position: (x, y) angolo superiore-sinistro.
        font: font Pillow.
        fill_color: colore RGBA di base (l'alpha viene modulato da `opacity`).
        stroke_color: colore RGBA del contorno (default: SUBTITLE_STROKE_COLOR).
        stroke_width: spessore contorno (default: SUBTITLE_STROKE_WIDTH).
        opacity: 0-255, moltiplicato all'alpha di fill/stroke.
    """
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    fill = _normalize_rgba(fill_color, SUBTITLE_COLOR)
    stroke = _normalize_rgba(stroke_color, SUBTITLE_STROKE_COLOR) if stroke_color is not None else SUBTITLE_STROKE_COLOR
    if opacity < 255:
        factor = opacity / 255.0
        fill = (fill[0], fill[1], fill[2], int(round(fill[3] * factor)))
        stroke = (stroke[0], stroke[1], stroke[2], int(round(stroke[3] * factor)))
    x, y = position
    draw.text(
        (x, y),
        word,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke,
    )


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
) -> tuple[int, int, int, int]:
    """Calcola dimensioni e coordinate di overlay del personaggio (width-based).

    Niente figura intera: la larghezza scala al 120-180% dello schermo
    (vedi PRESET_WIDTH_PCT in core/layout_presets.py, amplificata da
    PUNCH_IN_FACTOR se `is_punch_in` su preset normale), l'altezza segue
    l'aspect ratio dell'asset e l'ancoraggio e' dal basso con headroom
    configurabile: il bordo inferiore scende SEMPRE oltre `canvas_h`
    (gambe/piedi fuori inquadratura, testa sempre in campo).

    Args:
        image_size: (w, h) dell'asset originale.
        layout_preset: uno di VALID_LAYOUT_PRESETS (alias deprecati e position
            legacy tollerati via normalize_preset).
        is_punch_in: jump-cut di ingrandimento per enfasi.
        canvas_w/canvas_h: dimensioni canvas (default 1080x1920).

    Returns:
        (new_w, new_h, paste_x, paste_y): dimensioni scalate e angolo
        superiore-sinistro di incollaggio. Le coordinate possono uscire dal
        canvas (crop compositivo "mezzo busto", nessun taglio fisico).
    """
    try:
        src_w, src_h = int(image_size[0]), int(image_size[1])
    except (TypeError, ValueError):
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT
    if src_w <= 0 or src_h <= 0:
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT

    preset = normalize_preset(layout_preset)
    new_w = max(1, int(round(canvas_w * preset_width_pct(preset, bool(is_punch_in)))))
    new_h = max(1, int(round(src_h * new_w / float(src_w))))

    side_map = {"layout_split_left": "left", "layout_split_right": "right"}
    side = side_map.get(preset, "center")
    if side == "left":
        paste_x = -preset_overhang_x(canvas_w)
    elif side == "right":
        paste_x = canvas_w - new_w + preset_overhang_x(canvas_w)
    else:
        paste_x = (canvas_w - new_w) // 2

    paste_y = preset_headroom_px(preset, canvas_h)
    # Invariante spec: il bordo inferiore coincide con canvas_h o scende oltre
    # (mai piedi visibili, mai spazio vuoto sotto il personaggio).
    if paste_y + new_h < canvas_h:
        paste_y = canvas_h - new_h
    return (int(new_w), int(new_h), int(paste_x), int(paste_y))


def get_character_layer(
    pose: int,
    layout_preset: str,
    is_punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[Image.Image, int, int]:
    """Ritorna (immagine ridimensionata LANCZOS con alpha, paste_x, paste_y).

    Layer pronto per il paste con maschera, cachato per (posa, dimensioni).
    Solleva CharacterError se l'asset manca (il chiamante decide se e'
    bloccante: i render lo trattano come non-bloccante).
    """
    from core.character_selector import load_character_original
    original = load_character_original(pose)
    new_w, new_h, px, py = calculate_character_transform(
        original.size, layout_preset, is_punch_in, canvas_w, canvas_h)
    key = (int(pose), new_w, new_h)
    cached = _character_layer_cache.get(key)
    if cached is None:
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:  # Pillow < 9.1
            resample = Image.LANCZOS
        cached = original.resize((new_w, new_h), resample)
        if cached.mode != "RGBA":
            cached = cached.convert("RGBA")
        _character_layer_cache[key] = cached
    return cached.copy(), px, py


def clear_character_layer_cache() -> None:
    """Svuota la cache dei layer ridimensionati (utile nei test)."""
    _character_layer_cache.clear()


def _draw_character_static(img: Image.Image, character: dict | None) -> None:
    """Disegna il personaggio sul frame (Z-index: sopra lo sfondo, sotto i sottotitoli).

    `character` e' un dict di metadati come arricchito in main.py via
    core/character_selector.enrich_chunks_with_characters (oppure il chunk
    stesso). La risoluzione passa da `resolve_chunk_layout`: col preset valido
    si usa `get_character_layer` (scala width-based + ancoraggio dal basso,
    punch_in amplificato), altrimenti il posizionamento legacy v1.
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
    except Exception:
        return
    _paste_character_clipped(img, char_img, x, y)


def _resolve_safe_area(
    character: dict | None,
    safe_area: tuple[int, int, int, int] | None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> tuple[tuple[int, int, int, int] | None, bool, float]:
    """Safe area effettiva + flag pill + scala font per il testo.

    Precedenza: `text_safe_area` > `safe_area` > guard per-chunk >
    preset del character > None (centro schermo storico).
    Ritorna (area_o_None, needs_pill, font_scale).
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
            area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
            pill = preset_needs_text_background(preset)
            fscale = preset_font_scale(preset)
            # Guard real-time (core/layout_guard.py): override per-chunk.
            try:
                _gsa = character.get("guard_safe_area")
                if _gsa is not None:
                    _gb = (int(_gsa[0]), int(_gsa[1]), int(_gsa[2]), int(_gsa[3]))
                    if _gb[2] > _gb[0] and _gb[3] > _gb[1]:
                        area = _gb
                _gfs = character.get("guard_font_scale")
                if _gfs is not None:
                    _gf = float(_gfs)
                    if 0.5 <= _gf <= 1.5:
                        fscale = _gf
                if character.get("guard_pill"):
                    pill = True
            except Exception:
                pass
            return area, pill, fscale
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
    # Guard real-time (core/layout_guard.py): propagati al render.
    if chunk.get("guard_safe_area") is not None:
        info["guard_safe_area"] = chunk.get("guard_safe_area")
    if chunk.get("guard_font_scale") is not None:
        info["guard_font_scale"] = chunk.get("guard_font_scale")
    if chunk.get("guard_pill") is not None:
        info["guard_pill"] = chunk.get("guard_pill")
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

    try:
        font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale))))
    except (TypeError, ValueError):
        font_size = SUBTITLE_FONT_SIZE
    font = load_font(font_size)

    max_text_width = int(VIDEO_WIDTH * 0.85)
    words = text.split()
    layout = compute_word_layout(words, font, max_text_width, area=area)

    # Z-index 2.5: pill protettiva (preset punch-in), sotto il testo.
    if needs_pill:
        draw_text_background(img, layout)

    draw = ImageDraw.Draw(img)

    base_fill = text_color or SUBTITLE_COLOR
    for item in layout:
        word = item["word"]
        if keyword_colors:
            fill = keyword_colors.get(normalize_word(word), base_fill)
        else:
            fill = base_fill
        draw_word(
            draw, word, (item["x"], item["y"]), font,
            fill, SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
            opacity=255,
        )

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
