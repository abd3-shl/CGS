"""
Animazioni testo per-parola (Fase 3) + Dynamic Layout (sistema a zone).

Ogni parola del chunk entra in scena esattamente al suo timestamp `start`
e resta visibile accumulandosi accanto alle precedenti; tutte le parole
scompaiono insieme a `chunk.end` (uscita di gruppo).

- Parole normali: entrata minimal (solo fade con `ease_out_cubic`).
- Keyword: entrata marcata (opacita' + scala 0.7 -> 1.0 con `ease_out_back`,
  effetto "pop" premium; `ease_out_bounce` resta disponibile come variante
  piu' giocosa ma di default si usa `ease_out_back`, meno distraente su
  caption da 2-3 parole).
- Uscita: uguale per tutte, fade di gruppo con `ease_in_cubic`.

Il layout e' pre-calcolato UNA VOLTA per chunk (via
`core/renderer.compute_word_layout`) e resta fisso: le parole entrano gia'
nella loro posizione definitiva, mai riposizionate quando ne entra una nuova.
Col sistema a zone il layout e' confinato nella Text Safe Area del preset
(vedi core/layout_presets.py): personaggio e testo non si sovrappongono mai
(perche' entrambi risolvono da `resolve_chunk_layout`, singola fonte).

Personaggio: entrata da fuori campo in 0.3s (slide_from_left/right/up) o fade;
quando il layout successivo cambia lato (split_left <-> split_right) il
personaggio esce scendendo in basso (`slide_down`, 0.3s) e rientra dal lato
opposto nel chunk dopo (lookahead in `render_all_chunks_animated`); se preset
e posa restano identici, l'uscita e' trattenuta (`hold`) per un taglio
invisibile.

Lo sfondo resta trasparente (il colore di sfondo e' applicato da ffmpeg
come oggi in `core/video_builder.py`): il parametro `background_color`
e' accettato per compatibilita' API ma non viene disegnato nei frame.
"""

import math
import os

from PIL import Image, ImageDraw

from config import (
    CHARACTER_ENABLED,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_COLOR,
    SUBTITLE_STROKE_COLOR,
    SUBTITLE_STROKE_WIDTH,
    TEMP_DIR,
    TEXT_ANIMATION_ENTRY_DURATION,
    TEXT_ANIMATION_EXIT_DURATION,
    KEYWORD_ENTRY_SCALE_FROM,
)
from core.easing import (
    clamp01,
    ease_out_cubic,
    ease_out_back,
    ease_in_cubic,
)
from core.keywords import normalize_word
from core.renderer import load_font, compute_word_layout, draw_word, draw_text_background

# Re-export per spec ("RENDER E POSIZIONAMENTO (... / core/text_animator.py)").
from core.character_selector import (
    calculate_character_bbox as calculate_character_bbox,
    resolve_chunk_layout as resolve_chunk_layout,
)
from core.layout_presets import (
    layout_character_xy,
    preset_char_height,
    preset_needs_text_background,
    preset_safe_area,
    preset_side,
)

# Durata entrata personaggio legacy v1 (offset corto, feel premium).
_CHARACTER_ENTRY_DURATION = 0.35
_CHARACTER_SLIDE_UP_PX = 320
_CHARACTER_SLIDE_SIDE_PX = 260
# Durata entrata/uscita personaggio nel sistema a zone (slide da fuori campo).
_CHARACTER_ZONE_ENTRY_DURATION = 0.30
_CHARACTER_ZONE_EXIT_DURATION = 0.30
# Modalita' di uscita del personaggio a fine chunk (vedi render_all lookahead).
_CHAR_EXIT_WITH_TEXT = "with_text"  # segue il fade di gruppo del testo
_CHAR_EXIT_SLIDE_DOWN = "slide_down"  # scende fuori campo (cambio lato dopo)
_CHAR_EXIT_HOLD = "hold"  # resta opaco fino al taglio (stesso preset+posa dopo)


class TextAnimationError(Exception):
    """Errore durante la generazione dei frame animati."""
    pass


def _to_rgba(color, default: tuple) -> tuple[int, int, int, int]:
    """Converte hex "#RRGGBB" o tupla RGB/RGBA in RGBA.

    Accetta entrambi i formati per compatibilita' pipeline:
    - theme.py viaggia in hex, keywords.py in RGBA (vedi core/keywords.py).
    """
    if color is None:
        return default
    if isinstance(color, str):
        s = color.strip()
        if s.startswith("#") and len(s) == 7:
            try:
                return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 255)
            except ValueError:
                return default
        return default
    if isinstance(color, (tuple, list)):
        try:
            c = tuple(int(v) for v in color)
        except (TypeError, ValueError):
            return default
        if len(c) == 3:
            return (c[0], c[1], c[2], 255)
        if len(c) >= 4:
            return (c[0], c[1], c[2], c[3])
    return default


def _resolve_word_fill(word_norm: str, base_rgba: tuple, keyword_colors: dict | None) -> tuple:
    """Colore della parola: colore keyword se match, altrimenti testo base."""
    if keyword_colors:
        hit = keyword_colors.get(word_norm)
        if hit is not None:
            return _to_rgba(hit, base_rgba)
    return base_rgba


def enrich_chunk_words(chunk: dict, keyword_colors: dict | None = None) -> list[dict]:
    """Ritorna le parole del chunk con flag `is_keyword`.

    Il match e' case-insensitive e normalizzato senza punteggiatura
    (riusa `core.keywords.normalize_word`). Se il chunk non ha la chiave
    "words" (chunk legacy), la ricostruisce distribuendo uniformemente
    la durata del chunk sulle parole di `chunk["text"]`.
    """
    raw_words = chunk.get("words")
    if not raw_words:
        text = (chunk.get("text") or "").split()
        if not text:
            return []
        start = float(chunk.get("start", 0.0))
        end = float(chunk.get("end", start))
        if end <= start:
            end = start + 0.3 * len(text)
        span = (end - start) / len(text)
        raw_words = [
            {"word": w, "start": start + span * i, "end": start + span * (i + 1)}
            for i, w in enumerate(text)
        ]
    enriched: list[dict] = []
    for w in raw_words:
        word_text = str(w.get("word", ""))
        norm = normalize_word(word_text)
        is_kw = bool(keyword_colors and norm in keyword_colors)
        enriched.append({
            "word": word_text,
            "start": float(w.get("start", chunk.get("start", 0.0))),
            "end": float(w.get("end", chunk.get("end", 0.0))),
            "is_keyword": bool(w.get("is_keyword", is_kw)),
        })
    # Se il dict originale aveva gia' is_keyword esplicito, rispettalo;
    # altrimenti usa il match appena calcolato (gestito sopra via .get default).
    return enriched


def _render_scaled_word(
    frame_img: Image.Image,
    word: str,
    x: int,
    y: int,
    word_w: int,
    word_h: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    opacity: int,
    scale: float,
) -> None:
    """Disegna una parola con scala via resize LANCZOS, centro fisso.

    Disegna la parola a dimensione base su una tile temporanea, la ridimensiona
    col fattore `scale` e la incolla sul frame mantenendo il centro originale
    (il layout delle altre parole non si muove mai).
    """
    if opacity <= 0:
        return
    if scale <= 0:
        return
    # Caso veloce: scala unitaria -> disegno diretto.
    if abs(scale - 1.0) < 1e-3:
        draw = ImageDraw.Draw(frame_img)
        draw_word(draw, word, (x, y), font, fill, stroke_color, stroke_width, opacity=opacity)
        return
    pad = 24 + int(stroke_width) * 2
    tile_w = max(1, int(word_w + pad * 2))
    tile_h = max(1, int(word_h + pad * 2))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    draw_word(tile_draw, word, (pad, pad), font, fill, stroke_color, stroke_width, opacity=opacity)
    new_w = max(1, int(round(tile_w * scale)))
    new_h = max(1, int(round(tile_h * scale)))
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:  # Pillow < 9.1
        resample = Image.LANCZOS
    scaled = tile.resize((new_w, new_h), resample)
    # Centro originale della parola nel frame.
    cx = x + word_w / 2.0
    cy = y + word_h / 2.0
    # Centro della parola dentro la tile (coordinate tile, poi scalate).
    tcx = (pad + word_w / 2.0) * scale
    tcy = (pad + word_h / 2.0) * scale
    px = int(round(cx - tcx))
    py = int(round(cy - tcy))
    # Paste con maschera alpha (gestisce anche posizioni parzialmente fuori canvas).
    try:
        frame_img.paste(scaled, (px, py), scaled)
    except ValueError:
        # Fallback: ritaglia la porzione visibile se paste fallisce ai bordi.
        fx0, fy0 = max(0, px), max(0, py)
        tx0, ty0 = fx0 - px, fy0 - py
        tx1 = min(new_w, VIDEO_WIDTH - px)
        ty1 = min(new_h, VIDEO_HEIGHT - py)
        if tx1 > tx0 and ty1 > ty0:
            cropped = scaled.crop((tx0, ty0, tx1, ty1))
            frame_img.paste(cropped, (fx0, fy0), cropped)


def _character_info_from_chunk(chunk: dict) -> dict | None:
    """Metadati character dal chunk arricchito (None se assenti/disabilitati).

    Risolve tramite `resolve_chunk_layout` (singola fonte condivisa col text
    engine): ritorna pose/use_preset/layout_preset/transition_in + campi legacy.
    """
    if not CHARACTER_ENABLED:
        return None
    try:
        return resolve_chunk_layout(chunk)
    except Exception:
        return None


def _character_side(info: dict) -> str:
    """Lato del personaggio ('left' | 'right' | 'center')."""
    if info.get("use_preset"):
        try:
            return preset_side(info.get("layout_preset"))
        except Exception:
            return "center"
    return "left" if "left" in str(info.get("position", "")) else (
        "right" if "right" in str(info.get("position", "")) else "center")


def _load_chunk_character_image(info: dict | None):
    """Carica l'immagine personaggio per il chunk (None se non disponibile).

    Col preset valido usa l'altezza dettata dal preset (sistema a zone),
    altrimenti la scala legacy v1. Errori non bloccanti (asset mancante,
    posa invalida): ritorna None e il frame viene generato senza personaggio.
    """
    if info is None:
        return None
    try:
        from core.character_selector import character_target_height, load_and_process_character_image
        if info.get("use_preset"):
            target_h = preset_char_height(info.get("layout_preset"))
        else:
            target_h = character_target_height(info.get("scale", 0.75), VIDEO_HEIGHT)
        return load_and_process_character_image(int(info["pose"]), target_h)
    except Exception:
        return None


def _character_base_xy(info: dict, char_size: tuple[int, int]) -> tuple[int, int]:
    """Coordinate base (X, Y) del personaggio (preset o legacy v1)."""
    if info.get("use_preset"):
        return layout_character_xy(
            info.get("layout_preset"), char_size, VIDEO_WIDTH, VIDEO_HEIGHT)
    return calculate_character_bbox(
        char_size, info.get("position", "bottom_center"), VIDEO_WIDTH, VIDEO_HEIGHT)


def _character_entry_offset_opacity(
    transition: str,
    side: str,
    progress: float,
    img_w: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    full_travel: bool = False,
) -> tuple[int, int, int]:
    """Offset (dx, dy) e opacita' 0-255 del personaggio al `progress` 0..1.

    Sistema a zone (`full_travel=True`): slide da completamente fuori campo
    (bordo schermo -> posizione preset) in stile motion graphics.
    Legacy v1 (`full_travel=False`): offset corti (320/260px) come storico.

    - slide_from_left/slide_from_right (o slide_side legacy): entrata
      orizzontale con fade.
    - slide_up (o slide_from_bottom): risalita dal basso con fade.
    - fade: solo opacita'.
    - none: gia' in posizione, opaco da subito.
    """
    p = clamp01(progress)
    t = str(transition or "fade")
    if t == "slide_side":
        t = "slide_from_left" if side == "left" else "slide_from_right"
    elif t == "slide_from_bottom":
        t = "slide_up"
    if t == "none":
        return (0, 0, 255)
    eased = ease_out_cubic(p)
    opacity = int(round(255 * eased))
    if t == "fade":
        return (0, 0, opacity)
    if t in ("slide_from_left", "slide_from_right"):
        if full_travel and img_w > 0:
            start_x = -img_w if t == "slide_from_left" else VIDEO_WIDTH
            dx = int(round((start_x - base_x) * (1.0 - eased)))
        else:
            direction = -1 if t == "slide_from_left" else 1
            dx = int(round(direction * _CHARACTER_SLIDE_SIDE_PX * (1.0 - eased)))
        return (dx, 0, opacity)
    # slide_up (default anche per valori ignoti: mai un taglio secco a sorpresa)
    if full_travel:
        dy = int(round((VIDEO_HEIGHT - base_y) * (1.0 - eased)))
    else:
        dy = int(round(_CHARACTER_SLIDE_UP_PX * (1.0 - eased)))
    return (0, dy, opacity)


def _character_exit_offset_opacity(
    mode: str,
    progress: float,
    base_y: int = 0,
) -> tuple[int, int, int]:
    """Offset/uscita del personaggio nella finestra di uscita di fine chunk.

    - "slide_down": scende fuori campo basso con fade (il chunk successivo,
      con lato opposto, rientra con slide laterale: niente taglio netto).
    - "hold": resta fermo e opaco (il chunk successivo ha stesso preset+posa:
      taglio invisibile).
    - altro ("with_text"): nessuna animazione propria (segue il fade di gruppo).
    """
    if mode == _CHAR_EXIT_HOLD:
        return (0, 0, 255)
    if mode == _CHAR_EXIT_SLIDE_DOWN:
        e = ease_in_cubic(clamp01(progress))
        dy = int(round((VIDEO_HEIGHT - base_y) * e))
        return (0, dy, int(round(255 * (1.0 - e))))
    return (0, 0, 255)


def decide_char_exit_mode(current: dict | None, nxt: dict | None) -> str:
    """Modalita' di uscita del personaggio guardando il chunk successivo.

    - Stesso preset + stessa posa dopo -> "hold" (taglio invisibile).
    - Cambio lato (split_left <-> split_right) -> "slide_down" (scende, poi il
      chunk dopo rientra dal lato opposto: movimento combinato, niente stacco).
    - Altrimenti -> "with_text" (segue il fade di gruppo dei sottotitoli).
    Accetta chunk grezzi o info gia' risolte; mai eccezioni.
    """
    try:
        cur = current if isinstance(current, dict) and "pose" in current and "use_preset" in current \
            else resolve_chunk_layout(current)
        after = nxt if isinstance(nxt, dict) and "pose" in nxt and "use_preset" in nxt \
            else resolve_chunk_layout(nxt)
    except Exception:
        return _CHAR_EXIT_WITH_TEXT
    if cur is None:
        return _CHAR_EXIT_WITH_TEXT
    if after is None or not after.get("use_preset") or not cur.get("use_preset"):
        return _CHAR_EXIT_WITH_TEXT
    if after.get("layout_preset") == cur.get("layout_preset") and after.get("pose") == cur.get("pose"):
        return _CHAR_EXIT_HOLD
    try:
        cur_side = preset_side(cur.get("layout_preset"))
        nxt_side = preset_side(after.get("layout_preset"))
    except Exception:
        return _CHAR_EXIT_WITH_TEXT
    if {cur_side, nxt_side} == {"left", "right"}:
        return _CHAR_EXIT_SLIDE_DOWN
    return _CHAR_EXIT_WITH_TEXT


def _paste_character_frame(
    frame_img: Image.Image,
    char_img: Image.Image,
    x: int,
    y: int,
    opacity: int,
) -> None:
    """Incolla il personaggio sul frame con opacita' e clipping ai bordi."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    to_paste = char_img
    if opacity < 255:
        to_paste = char_img.copy()
        alpha = to_paste.getchannel("A")
        alpha = alpha.point(lambda a: (a * opacity) // 255)
        to_paste.putalpha(alpha)
    px, py = int(x), int(y)
    try:
        frame_img.paste(to_paste, (px, py), to_paste)
        return
    except ValueError:
        pass
    cw, ch = frame_img.size
    iw, ih = to_paste.size
    fx0, fy0 = max(0, px), max(0, py)
    tx0, ty0 = fx0 - px, fy0 - py
    tx1 = min(iw, cw - px)
    ty1 = min(ih, ch - py)
    if tx1 > tx0 and ty1 > ty0:
        cropped = to_paste.crop((tx0, ty0, tx1, ty1))
        frame_img.paste(cropped, (fx0, fy0), cropped)


def generate_animated_chunk_frames(
    chunk: dict,
    background_color: str,
    text_color: str,
    keyword_colors: dict,
    output_dir: str,
    chunk_index: int,
    fps: int = VIDEO_FPS,
    safe_area: tuple[int, int, int, int] | None = None,
    char_exit_mode: str = _CHAR_EXIT_WITH_TEXT,
    char_exit_duration: float = _CHARACTER_ZONE_EXIT_DURATION,
) -> list[dict]:
    """Genera la sequenza di frame PNG per un chunk con animazione per-parola.

    Args:
        chunk: {"text", "start", "end", "words": [{"word","start","end",...}]}.
            Se "words" manca, viene ricostruita (vedi `enrich_chunk_words`).
            Puo' contenere pose/layout_preset/transition_in del personaggio
            (vedi core/character_selector.py): il personaggio viene disegnato
            sotto il testo (Z-index: sfondo ffmpeg < personaggio < sottotitoli,
            con pill protettiva per il closeup) con slide da fuori campo.
        background_color: hex #RRGGBB da theme.py (frame restano trasparenti,
            lo sfondo e' applicato da ffmpeg; param tenuto per compatibilita').
        text_color: hex #RRGGBB da theme.py (accetta anche tupla RGBA).
        keyword_colors: {parola_normalizzata: hex} da keywords.py
            (accetta anche valori RGBA come quelli reali di `extract_keywords`).
        output_dir: cartella dove salvare i frame PNG del chunk.
        chunk_index: per naming file univoco.
        fps: frame rate (default: VIDEO_FPS da config.py).
        safe_area: Text Safe Area esplicita (x_min, y_min, x_max, y_max);
            se assente si usa quella del preset del chunk, altrimenti il
            centro schermo storico. Il wrapping segue la larghezza del box.
        char_exit_mode: "with_text" (segue il fade di gruppo), "slide_down"
            (esce in basso a fine chunk) o "hold" (resta opaco fino al taglio).
            Di solito calcolato con `decide_char_exit_mode` guardando il chunk
            successivo (vedi `render_all_chunks_animated`).
        char_exit_duration: durata in secondi della finestra di uscita
            per "slide_down" (default 0.30s).

    Returns:
        Lista di dict {"image_path": str, "start": float, "end": float}
        - uno per ogni frame generato, con la finestra temporale in cui
        quel frame specifico deve essere mostrato (frame N valido da
        t_N a t_N+1/fps). Formato compatibile con la pipeline di
        `core/video_builder.py` (micro-video per chunk via `build_chunk_clip`).
    """
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    words = enrich_chunk_words(chunk, keyword_colors)
    if not words:
        return []
    try:
        chunk_start = float(chunk.get("start", words[0]["start"]))
        chunk_end = float(chunk.get("end", words[-1]["end"]))
    except (TypeError, ValueError) as e:
        raise TextAnimationError(f"Timestamp chunk non validi: {e}")
    if chunk_end <= chunk_start:
        chunk_end = chunk_start + 0.1
    duration = chunk_end - chunk_start
    if duration <= 0:
        return []

    os.makedirs(output_dir, exist_ok=True)

    # --- Personaggio + safe area: un'unica fonte (niente overlap possibile) ---
    char_info = _character_info_from_chunk(chunk)
    use_preset = bool(char_info is not None and char_info.get("use_preset"))
    if safe_area is not None:
        try:
            area = (int(safe_area[0]), int(safe_area[1]), int(safe_area[2]), int(safe_area[3]))
            area = area if area[2] > area[0] and area[3] > area[1] else None
        except (TypeError, ValueError, IndexError):
            area = None
        needs_pill = False
    elif use_preset:
        area = preset_safe_area(char_info.get("layout_preset"), VIDEO_WIDTH, VIDEO_HEIGHT)
        needs_pill = preset_needs_text_background(char_info.get("layout_preset"))
    else:
        area, needs_pill = None, False

    # --- Pre-calcolo layout (una sola volta, fisso per tutto il chunk) ---
    font = load_font(SUBTITLE_FONT_SIZE)
    max_text_width = int(VIDEO_WIDTH * 0.85)
    word_texts = [w["word"] for w in words]
    layout = compute_word_layout(word_texts, font, max_text_width, area=area)
    if len(layout) != len(words):
        raise TextAnimationError("Layout/words fuori sync: conteggio diverso.")

    base_rgba = _to_rgba(text_color, SUBTITLE_COLOR)
    fills = [
        _resolve_word_fill(normalize_word(w["word"]), base_rgba, keyword_colors)
        for w in words
    ]
    word_starts = [float(w["start"]) for w in words]

    entry_dur = max(0.01, float(TEXT_ANIMATION_ENTRY_DURATION))
    exit_dur = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    scale_from = float(KEYWORD_ENTRY_SCALE_FROM)
    if not (0.1 <= scale_from <= 1.0):
        scale_from = 0.7

    # --- Personaggio del chunk (caricato UNA volta, riusato in ogni frame) ---
    # Z-index sui frame: 1. sfondo (ffmpeg) / 2. personaggio / 2.5 pill / 3. testo.
    char_img = _load_chunk_character_image(char_info)
    if char_img is not None and char_info is not None:
        char_base_xy = _character_base_xy(char_info, char_img.size)
        char_transition = char_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(char_info)
        char_full_travel = bool(use_preset)
        char_entry_dur = max(0.01, _CHARACTER_ZONE_ENTRY_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
    else:
        char_base_xy = None

    try:
        char_exit_dur = max(0.0, float(char_exit_duration))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION
    if char_exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
        char_exit_mode = _CHAR_EXIT_WITH_TEXT

    num_frames = max(1, int(math.ceil(duration * fps)))
    frame_step = 1.0 / float(fps)
    frames: list[dict] = []

    for fi in range(num_frames):
        t = chunk_start + fi * frame_step
        if t >= chunk_end:
            t = chunk_end - 1e-6
        frame_end = min(t + frame_step, chunk_end)

        # Fattore uscita di gruppo, condiviso da tutte le parole.
        if exit_dur > 0 and t >= chunk_end - exit_dur:
            exit_prog = clamp01((t - (chunk_end - exit_dur)) / exit_dur)
            exit_factor = 1.0 - ease_in_cubic(exit_prog)
        else:
            exit_factor = 1.0

        frame_img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))

        # Z-index 2: personaggio sotto il testo (entrata + eventuale uscita).
        if char_img is not None and char_base_xy is not None:
            entry_prog = clamp01((t - chunk_start) / char_entry_dur)
            edx, edy, entry_opacity = _character_entry_offset_opacity(
                char_transition, char_side, entry_prog,
                char_img.size[0], char_base_xy[0], char_base_xy[1],
                full_travel=char_full_travel,
            )
            if char_exit_mode == _CHAR_EXIT_HOLD:
                char_opacity, xdx, xdy = entry_opacity, 0, 0
            elif char_exit_mode == _CHAR_EXIT_SLIDE_DOWN and char_exit_dur > 0 \
                    and t >= chunk_end - char_exit_dur:
                xprog = clamp01((t - (chunk_end - char_exit_dur)) / char_exit_dur)
                xdx, xdy, exit_opacity = _character_exit_offset_opacity(
                    _CHAR_EXIT_SLIDE_DOWN, xprog, char_base_xy[1])
                char_opacity = min(entry_opacity, exit_opacity)
            else:
                char_opacity, xdx, xdy = int(round(entry_opacity * exit_factor)), 0, 0
            _paste_character_frame(
                frame_img, char_img,
                char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy,
                char_opacity,
            )

        # Z-index 2.5: pill protettiva dietro il testo (solo closeup preset).
        if needs_pill:
            draw_text_background(frame_img, layout)

        for wi, w in enumerate(words):
            if t < word_starts[wi]:
                continue  # non ancora iniziata
            local = clamp01((t - word_starts[wi]) / entry_dur)
            if w["is_keyword"]:
                eased = ease_out_back(local)
                # Opacita': clamp 0-255 (l'overshoot >1 va saturato).
                opacity = int(round(255 * min(1.0, max(0.0, eased))))
                scale = scale_from + (1.0 - scale_from) * eased
                # Evita scale degeneri a inizio animazione.
                scale = max(0.05, scale)
            else:
                eased = ease_out_cubic(local)
                opacity = int(round(255 * eased))
                scale = 1.0
            opacity = int(round(opacity * exit_factor))
            if opacity <= 0:
                continue
            item = layout[wi]
            _render_scaled_word(
                frame_img, w["word"], item["x"], item["y"],
                item["width"], item["height"], font,
                fills[wi], SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
                opacity=opacity, scale=scale,
            )

        fname = f"chunk_{chunk_index:04d}_frame_{fi:05d}.png"
        fpath = os.path.join(output_dir, fname)
        # compress_level=1: PNG lossless ma scrittura ~2x piu' veloce
        # (file temp piu' grandi, cancellati a fine job; nessun impatto visivo).
        frame_img.save(fpath, compress_level=1)
        frames.append({"image_path": fpath, "start": t, "end": frame_end})

    return frames


def render_all_chunks_animated(
    chunks: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    fps: int = VIDEO_FPS,
    on_chunk=None,
    safe_area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Genera i frame animati per tutti i chunk.

    Args:
        chunks: lista di chunk con "text"/"start"/"end"/"words" (+ metadati
            character opzionali: pose/layout_preset/transition_in).
        background_color: hex da theme.py (tenuto per compatibilita').
        text_color: hex o RGBA del testo base.
        keyword_colors: {norm: colore} (hex o RGBA).
        output_dir: cartella dei frame PNG.
        fps: frame rate.
        on_chunk: callback opzionale (idx, totale) a fine chunk, per logging GUI.
        safe_area: Text Safe Area esplicita per TUTTI i chunk (override dei
            preset; None = preset del singolo chunk o centro schermo).

    Il lookahead sul chunk successivo decide l'uscita del personaggio
    (vedi `decide_char_exit_mode`): cambio lato -> slide_down combinato con
    la slide di entrata del chunk dopo; stesso preset+posa -> hold invisibile.

    Returns:
        Lista di chunk arricchiti: {**chunk, "frames": [...], "frame_paths": [...],
        "clip_start": start, "clip_end": end}.
    """
    enriched_all: list[dict] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        nxt = chunks[i + 1] if i + 1 < total else None
        exit_mode = decide_char_exit_mode(chunk, nxt)
        frames = generate_animated_chunk_frames(
            chunk, background_color, text_color,
            keyword_colors or {}, output_dir, i, fps,
            safe_area=safe_area, char_exit_mode=exit_mode,
        )
        enriched_all.append({
            **chunk,
            "frames": frames,
            "frame_paths": [f["image_path"] for f in frames],
            "clip_start": chunk.get("start"),
            "clip_end": chunk.get("end"),
        })
        if on_chunk is not None:
            try:
                on_chunk(i + 1, total)
            except Exception:
                pass
    return enriched_all
