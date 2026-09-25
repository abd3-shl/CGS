"""
Real-time Layout Guard: piano in tempo reale anti-sovrapposizione
personaggio <-> sottotitoli (1080x1920).

Punto unico di verifica PRIMA del rendering: misura le bbox REALI
(tight bbox alpha del personaggio + bbox testo misurata col font reale,
inclusi overshoot pop e scala punch-in) e applica fix a cascata finche'
l'overlap e' zero o il fallback garantito scatta.

Uso tipico (hook da 3 righe in text_animator / renderer):

    from core.layout_guard import plan_chunk_realtime, build_realtime_plan
    plan = plan_chunk_realtime(chunk, words=..., fonts=..., ...)
    # plan = {"layout", "safe_area", "font_scale", "needs_pill",
    #         "hide_character", "guaranteed", "overlap_px", "actions"}

    plan_all = build_realtime_plan(chunks_enriched, ...)  # batch con coerenza beat

Garanzie:
- Mai eccezioni (fallback = nascondi personaggio, testo al centro).
- <5ms per chunk (probe condivisa, bbox cachate, niente LLM, niente I/O).
- Coerenza temporale: dentro lo stesso narrative_beat preferisce shrink font
  a switch layout (niente flicker); lo switch layout avviene solo ai confini.
- Punch-in intenzionale: overlap ammesso SOLO con pill + contrasto (leggibilita'),
  mai senza pill.

Misure reali alla base (asset 768x1376, tight bbox dopo pulizia sfondo):
- center_standard: testa a y~644, safe 150-900 -> overlap 256px se testo basso.
  Fix: y_max 900 -> 620 per chunk alti, o shrink font.
- split 340-360px di larghezza: parola >360px sconfina; pose 2 larga 259px
  di overlap in split -> mai pose 2 in split (forza center).
- pop ease_out_back overshoot ~10%: margine obbligatorio 12% sul testo.
- punch-in character 1.6875x: tight ancora piu' esteso -> ricalcolo con flag.
"""

from __future__ import annotations

from config import VIDEO_WIDTH, VIDEO_HEIGHT
try:
    from config import (
        LAYOUT_MAX_WIDTH_RATIO as _DYN_MAX_RATIO,
        LAYOUT_MIN_FONT_PX as _DYN_MIN_PX,
        Z_BACKGROUND as _Z_BG,
        Z_CHARACTER as _Z_CHAR,
        Z_DIMMER as _Z_DIM,
        Z_SUBTITLES as _Z_SUB,
        Z_DEBUG as _Z_DBG,
    )
except Exception:  # config datata
    _DYN_MAX_RATIO = 0.80
    _DYN_MIN_PX = 40
    _Z_BG, _Z_CHAR, _Z_DIM, _Z_SUB, _Z_DBG = 0, 10, 20, 30, 99
from core.layout_presets import (
    PRESET_SAFE_AREA,
    preset_safe_area,
    preset_font_scale,
    preset_needs_text_background,
    normalize_preset,
)

# --- Costanti di sicurezza (tuning validato sulle misure reali) ---
SAFETY_MARGIN_PX = 24          # gap minimo personaggio-testo (bordo a bordo)
POP_OVERSHOOT = 1.12           # ease_out_back supera 1.0 di ~10-12%
PUNCH_TEXT_PAD = 28            # pad pill (deve entrare nel check overlap)
FONT_SHRINK_STEPS = (1.0, 0.9, 0.8, 0.7)  # cascata shrink (prima dello switch)
CENTER_SAFE_Y_MAX_FIXED = 620  # center_standard: testa a 644 - margine 24
SPLIT_WIDEN_PX = 60            # allargo split verso centro se parola lunga
MAX_TEXT_WIDTH_RATIO = 0.85    # come renderer/text_animator (VIDEO_W * 0.85)
# Tolleranza idle breathing leggero: solo bob verticale dolce (+/-4px, nessuna
# rotazione laterale). Il pad espande la tight bbox misurata cosi' il respiro
# non collide mai col testo garantito (cfr. get_character_tight_canvas).
SAFETY_PADDING_IDLE_Y = 8      # px verticali (bob amp 4 + margine)
SAFETY_PADDING_IDLE_X = 4      # px orizzontali (margine, nessun tilt)

# Pose 2 (braccia aperte) tight ~ -335..899 in split_left: vietata in split.
WIDE_POSES_IN_SPLIT = frozenset({2})

# Cache tight bbox originale (non scalata): {pose: (x0,y0,x1,y1) o None}
_tight_cache: dict[int, tuple[int, int, int, int] | None] = {}


def get_character_tight_original(pose: int):
    """Tight bbox alpha dell'asset originale (dopo pulizia sfondo), cachata."""
    try:
        pose_i = int(pose)
    except (TypeError, ValueError):
        return None
    if pose_i in _tight_cache:
        return _tight_cache[pose_i]
    try:
        from core.character_selector import load_character_original
        img = load_character_original(pose_i)
        bbox = img.getbbox()  # bbox non-trasparente su RGBA pulita
        if bbox is not None:
            bbox = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        _tight_cache[pose_i] = bbox
        return bbox
    except Exception:
        _tight_cache[pose_i] = None
        return None


def get_character_tight_canvas(
    pose: int,
    layout_preset: str,
    punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int] | None:
    """Tight bbox del personaggio sul canvas (coordinate assolute, clip 0..W/H).

    Usa calculate_character_transform (stessa del render) + tight originale
    scalata + padding idle (SAFETY_PADDING_IDLE_X/Y: l'oscillazione continua
    bob/tilt non collide mai col testo garantito). Ritorna None se
    personaggio assente/non misurabile.
    """
    try:
        from core.renderer import calculate_character_transform
    except Exception:
        return None
    try:
        from core.character_selector import load_character_original
        orig = load_character_original(int(pose))
        src_w, src_h = orig.size
    except Exception:
        return None
    try:
        new_w, new_h, px, py = calculate_character_transform(
            (src_w, src_h), layout_preset, bool(punch_in), canvas_w, canvas_h
        )
    except Exception:
        return None
    tight = get_character_tight_original(pose)
    if tight is None:
        # Fallback conservativo: full bbox (meglio un falso positivo che overlap).
        return (px, py, px + new_w, py + new_h)
    try:
        sx = new_w / float(src_w)
        sy = new_h / float(src_h)
        tx0 = int(round(px + tight[0] * sx))
        ty0 = int(round(py + tight[1] * sy))
        tx1 = int(round(px + tight[2] * sx))
        ty1 = int(round(py + tight[3] * sy))
    except Exception:
        tx0, ty0, tx1, ty1 = px, py, px + new_w, py + new_h
    # Padding idle: espande la bbox misurata (bob +/-AMP_Y, tilt ai bordi).
    try:
        tx0 -= int(SAFETY_PADDING_IDLE_X)
        ty0 -= int(SAFETY_PADDING_IDLE_Y)
        tx1 += int(SAFETY_PADDING_IDLE_X)
        ty1 += int(SAFETY_PADDING_IDLE_Y)
    except Exception:
        pass
    # Clip al canvas (il paste ritaglia il fuori-campo).
    tx0 = max(0, tx0)
    ty0 = max(0, ty0)
    tx1 = min(canvas_w, tx1)
    ty1 = min(canvas_h, ty1)
    if tx1 <= tx0 or ty1 <= ty0:
        return None  # completamente fuori campo
    return (tx0, ty0, tx1, ty1)


def text_bbox_of_layout(layout: list[dict], pad: int = 0) -> tuple[int, int, int, int] | None:
    """BBox unione di un layout parola (con pad opzionale per pill/pop)."""
    if not layout:
        return None
    try:
        x0 = min(int(it["x"]) for it in layout) - int(pad)
        y0 = min(int(it["y"]) for it in layout) - int(pad)
        x1 = max(int(it["x"]) + int(it["width"]) for it in layout) + int(pad)
        y1 = max(int(it["y"]) + int(it["height"]) for it in layout) + int(pad)
    except (KeyError, TypeError, ValueError):
        return None
    return (x0, y0, x1, y1)


def expand_bbox_for_pop(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Espande la bbox testo per l'overshoot del pop keyword (~12%)."""
    try:
        x0, y0, x1, y1 = bbox
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        hw, hh = (x1 - x0) / 2.0 * POP_OVERSHOOT, (y1 - y0) / 2.0 * POP_OVERSHOOT
        return (int(round(cx - hw)), int(round(cy - hh)),
                int(round(cx + hw)), int(round(cy + hh)))
    except Exception:
        return bbox


def rects_overlap(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
    margin: int = SAFETY_MARGIN_PX,
) -> tuple[bool, int]:
    """Verifica intersezione con margine di sicurezza.

    Returns:
        (overlap_bool, overlap_px): overlap_px = area di intersezione
        (0 se nessun overlap). Con margin>0 i rettori vengono espansi,
        cosi' il "quasi tocco" conta come overlap (gap minimo garantito).
    """
    if a is None or b is None:
        return False, 0
    try:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        m = int(margin)
        ax0 -= m
        ay0 -= m
        ax1 += m
        ay1 += m
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            return False, 0
        return True, int((ix1 - ix0) * (iy1 - iy0))
    except Exception:
        return False, 0


def _measure_text(
    words: list[str],
    font,
    max_width: int,
    area: tuple[int, int, int, int] | None,
    chunk: dict | None = None,
    font_scale: float = 1.0,
) -> list[dict] | None:
    """Misura il layout senza disegnare.

    Se il chunk porta styled_words validi (tipografia multi-stile), misura
    col path reale compute_styled_layout (3 font, impact piu' grande =
    worst-case accurato); altrimenti legacy single-font. Mai eccezioni.
    """
    try:
        if isinstance(chunk, dict):
            styled = chunk.get("styled_words")
            if isinstance(styled, list) and styled:
                try:
                    from core.text_animator import (
                        compute_styled_layout,
                        _resolve_typography_preset,
                        _load_typography_fonts,
                    )
                    niche = chunk.get("typography_niche")
                    tpreset = _resolve_typography_preset(chunk, niche, None)
                    tfonts = _load_typography_fonts(tpreset, font_scale)
                    items = []
                    upper = bool(tpreset.get("impact_uppercase", True))
                    for s in styled:
                        if not isinstance(s, dict):
                            continue
                        w = str(s.get("word", ""))
                        if not w.strip():
                            continue
                        st = s.get("style", "base")
                        if st not in ("base", "impact", "accent"):
                            st = "base"
                        disp = str(s.get("display", w.upper() if (st == "impact" and upper) else w))
                        items.append({"word": w, "display": disp, "style": st})
                    if items:
                        return compute_styled_layout(items, tfonts, max_width, area=area)
                except Exception:
                    pass
        from core.renderer import compute_word_layout
        return compute_word_layout(words, font, max_width, area=area)
    except Exception:
        return None


def _load_font_scaled(base_size: int, scale: float):
    """Font scalato (riusa cache renderer.load_font)."""
    try:
        from core.renderer import load_font
        return load_font(max(24, int(round(base_size * float(scale)))))
    except Exception:
        from core.renderer import load_font
        return load_font(base_size)


# --------------------------------- Safe zone dinamiche + auto-scaling (Fase 4)
# TikTok/Reels/Shorts: bottoni laterali + overlay UI sopra/sotto. Il testo non
# deve superarli: limite dinamico 80% larghezza, auto-scaling fino a 40px min,
# poi wrapping forzato sulla pausa piu' vicina. Z-index verificato:
# bg(0) < character(10) < dimmer(20) < subtitles(30) < debug(99).
UI_TOP_RESERVED_PX = 150     # overlay sopra (titolo/progresso)
UI_BOTTOM_RESERVED_PX = 320  # overlay sotto (like/commenti/CTA mobile)
UI_SIDE_RESERVED_PX = 80     # bottoni laterali TikTok/Reels


def dynamic_max_text_width(canvas_w: int | None = None) -> int:
    """Larghezza max testo (80% schermo per evitare bottoni laterali)."""
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
    except Exception:
        w = 1080
    try:
        ratio = float(_DYN_MAX_RATIO)
        ratio = min(0.95, max(0.5, ratio))
    except Exception:
        ratio = 0.80
    return max(320, int(round(w * ratio)))


def dynamic_min_font_scale(base_size: int) -> float:
    """Scala minima per non scendere sotto 40px (LAYOUT_MIN_FONT_PX)."""
    try:
        min_px = max(24, int(_DYN_MIN_PX))
        base = max(24, int(base_size))
        return max(0.3, min(1.0, float(min_px) / float(base)))
    except Exception:
        return 0.6


def widest_line_px(layout: list[dict] | None) -> int:
    """Larghezza px della riga piu' larga (bounding box dinamica, mai eccezioni)."""
    try:
        if not layout:
            return 0
        by_y: dict[int, int] = {}
        for item in layout:
            try:
                y = int(item.get("y", 0))
                w = int(item.get("x", 0)) + int(item.get("width", 0))
                # Raggruppa per riga (tolleranza 4px).
                key = None
                for ky in by_y:
                    if abs(ky - y) <= 4:
                        key = ky
                        break
                if key is None:
                    by_y[y] = w
                else:
                    by_y[key] = max(by_y[key], w)
            except Exception:
                continue
        if not by_y:
            return 0
        min_x = 10 ** 9
        for item in layout:
            try:
                min_x = min(min_x, int(item.get("x", min_x)))
            except Exception:
                continue
        max_w = max(by_y.values())
        return max(0, int(max_w - (min_x if min_x < 10 ** 9 else 0)))
    except Exception:
        return 0


def rewrap_split_point(words: list[str]) -> int:
    """Indice di split per wrapping forzato: pausa forte > virgola > meta'.

    Cerca punteggiatura sillabica/audio (`. ! ? … : ; ,`) dalla meta' in poi,
    altrimenti meta' parole. Ritorna indice di inizio seconda riga (>=1).
    Mai eccezioni.
    """
    try:
        n = len(words or [])
        if n <= 2:
            return 1
        strong = (".", "!", "?", "…", ":", ";")
        mid = max(1, n // 2)
        for i in range(mid, n - 1):
            try:
                if str(words[i]).endswith(strong):
                    return i + 1
            except Exception:
                continue
        for i in range(mid, n - 1):
            try:
                if str(words[i]).endswith(","):
                    return i + 1
            except Exception:
                continue
        return mid
    except Exception:
        try:
            return max(1, len(words or []) // 2)
        except Exception:
            return 1


def verify_z_order(
    text_bbox: tuple[int, int, int, int] | None,
    char_bbox: tuple[int, int, int, int] | None = None,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
) -> tuple[bool, list[str]]:
    """Verifica Z-index e safe zone (sempre tra character Z=10 e UI inferiore).

    Controlli: testo dentro [SIDE, TOP, W-SIDE, H-BOTTOM], character sotto il
    testo (non sopra: char y0 >= text y1 - overlap tollerato solo punch),
    layering Z bg<character<dimmer<subtitles. Ritorna (ok, violazioni).
    Mai eccezioni.
    """
    violations: list[str] = []
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
        h = int(canvas_h) if canvas_h else int(VIDEO_HEIGHT)
    except Exception:
        w, h = 1080, 1920
    try:
        if not (_Z_BG < _Z_CHAR < _Z_DIM < _Z_SUB < _Z_DBG):
            violations.append("z-stack-inconsistente")
    except Exception:
        pass
    try:
        if text_bbox is not None:
            x0, y0, x1, y1 = (int(text_bbox[0]), int(text_bbox[1]), int(text_bbox[2]), int(text_bbox[3]))
            if x0 < UI_SIDE_RESERVED_PX or x1 > w - UI_SIDE_RESERVED_PX:
                violations.append("testo-oltre-bottoni-laterali")
            if y0 < UI_TOP_RESERVED_PX:
                violations.append("testo-in-overlay-superiore")
            if y1 > h - UI_BOTTOM_RESERVED_PX:
                violations.append("testo-in-fascia-ui-inferiore")
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                violations.append("testo-fuori-canvas")
        if text_bbox is not None and char_bbox is not None:
            try:
                _tx0, _ty0, _tx1, _ty1 = text_bbox
                _cx0, _cy0, _cx1, _cy1 = char_bbox
                # Il character (Z=10) deve stare sotto/dietro il testo (Z=30):
                # se la testa supera il centro testo di oltre il margine, e'
                # overlap da correggere (il guard a cascata lo risolve).
                if int(_cy0) < int(_ty0) - 24 and not (int(_cx1) <= int(_tx0) or int(_cx0) >= int(_tx1)):
                    violations.append("character-sopra-testo")
            except Exception:
                pass
    except Exception:
        pass
    return (len(violations) == 0, violations)


def debug_safezone_boxes(
    canvas_w: int | None = None, canvas_h: int | None = None
) -> list[dict]:
    """Box rossi semi-trasparenti delle safe zone UI (solo debug_safezones).

    Ritorna [{x0,y0,x1,y1,label}] per overlay sopra/sotto/laterali.
    Mai eccezioni.
    """
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
        h = int(canvas_h) if canvas_h else int(VIDEO_HEIGHT)
    except Exception:
        w, h = 1080, 1920
    try:
        return [
            {"x0": 0, "y0": 0, "x1": w, "y1": UI_TOP_RESERVED_PX, "label": "UI-TOP"},
            {"x0": 0, "y0": h - UI_BOTTOM_RESERVED_PX, "x1": w, "y1": h, "label": "UI-BOTTOM"},
            {"x0": 0, "y0": UI_TOP_RESERVED_PX, "x1": UI_SIDE_RESERVED_PX, "y1": h - UI_BOTTOM_RESERVED_PX, "label": "UI-LEFT"},
            {"x0": w - UI_SIDE_RESERVED_PX, "y0": UI_TOP_RESERVED_PX, "x1": w, "y1": h - UI_BOTTOM_RESERVED_PX, "label": "UI-RIGHT"},
        ]
    except Exception:
        return []


def plan_chunk_realtime(
    chunk: dict,
    words: list[str] | None = None,
    font_size: int | None = None,
    max_width: int | None = None,
    margin: int = SAFETY_MARGIN_PX,
) -> dict:
    """Piano in tempo reale per UN chunk: layout/safe-area/font ottimizzati.

    Args:
        chunk: chunk arricchito (puo' contenere pose/layout/punch_in/scale,
            narrative_role/narrative_beat per la coerenza).
        words: parole da misurare (default: chunk["text"].split()).
        font_size: base px prima di font_scale preset (default: config).
        max_width: larghezza max blocco (default: VIDEO_W * 0.85).
        margin: gap minimo px (default 24).

    Returns:
        dict piano (mai eccezioni):
        {"layout","safe_area","font_scale","needs_pill","hide_character",
         "guaranteed","overlap_px","overlap_before_px","actions":[...]}
        Il chiamante applica: safe_area + font_scale al layout, needs_pill
        al disegno, hide_character per saltare il paste.
    """
    from config import SUBTITLE_FONT_SIZE

    actions: list[str] = []
    try:
        base_size = int(font_size) if font_size else int(SUBTITLE_FONT_SIZE)
    except (TypeError, ValueError):
        from config import SUBTITLE_FONT_SIZE as _S
        base_size = int(_S)
    try:
        mw = int(max_width) if max_width else int(VIDEO_WIDTH * MAX_TEXT_WIDTH_RATIO)
    except (TypeError, ValueError):
        mw = int(VIDEO_WIDTH * MAX_TEXT_WIDTH_RATIO)
    # --- Fase 4: limite dinamico 80% (bottoni laterali TikTok/Reels) ---
    try:
        mw = min(int(mw), int(dynamic_max_text_width()))
    except Exception:
        pass

    if words is None:
        try:
            words = str((chunk or {}).get("text", "")).split()
        except Exception:
            words = []
    if not words:
        return {
            "layout": "layout_center_standard",
            "safe_area": PRESET_SAFE_AREA["layout_center_standard"],
            "font_scale": 1.0, "needs_pill": False, "hide_character": False,
            "guaranteed": True, "overlap_px": 0, "overlap_before_px": 0,
            "actions": ["empty-text"],
        }

    # --- Risolvi personaggio (singola fonte: resolve_chunk_layout) ---
    try:
        from core.character_selector import resolve_chunk_layout
        info = resolve_chunk_layout(chunk) if isinstance(chunk, dict) else None
    except Exception:
        info = None

    if info is None:
        # Nessun personaggio: testo libero, garanzia banale.
        return {
            "layout": "layout_center_standard",
            "safe_area": None,
            "font_scale": 1.0, "needs_pill": False, "hide_character": False,
            "guaranteed": True, "overlap_px": 0, "overlap_before_px": 0,
            "actions": ["no-character"],
        }

    pose = info.get("pose")
    punch = bool(info.get("punch_in", False))
    preset = normalize_preset(info.get("layout", "layout_center_standard"))
    use_preset = bool(info.get("use_preset", True))

    # Regola 0 (deterministica, costo zero): pose 2 mai in split.
    if preset in ("layout_split_left", "layout_split_right") and pose in WIDE_POSES_IN_SPLIT:
        preset = "layout_center_standard"
        actions.append("wide-pose-to-center(pose2->center)")

    # Posa 4 indica verso DESTRA dello spettatore: deve stare SEMPRE a
    # sinistra (split_left) per puntare verso il testo. Se finita altrove
    # (center/split_right da LLM o piano datato), forza split_left.
    if pose == 4 and preset != "layout_split_left":
        preset = "layout_split_left"
        actions.append("pose4-to-split_left")

    base_scale = preset_font_scale(preset)
    base_area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
    needs_pill = preset_needs_text_background(preset)

    # Punch-in intenzionale: overlap ammesso SOLO con pill (leggibilita').
    # Il guard garantisce la pill, non lo zero geometrico.
    if preset == "layout_center_punch_in" or punch:
        needs_pill = True

    # --- Misura iniziale ---
    char_box = get_character_tight_canvas(pose, preset, punch)

    def measure(area, fscale):
        font = _load_font_scaled(base_size, fscale)
        layout = _measure_text(words, font, mw, area, chunk=chunk, font_scale=fscale)
        if layout is None:
            return None, None
        tb = text_bbox_of_layout(layout, pad=PUNCH_TEXT_PAD if needs_pill else 0)
        if tb is not None:
            tb = expand_bbox_for_pop(tb)  # overshoot pop sempre incluso
        return layout, tb

    layout, text_box = measure(base_area, base_scale)
    if layout is None or text_box is None:
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale, "needs_pill": needs_pill,
            "hide_character": False, "guaranteed": False,
            "overlap_px": 0, "overlap_before_px": 0,
            "actions": actions + ["measure-failed"],
        }
    hit, px = rects_overlap(char_box, text_box, margin)
    overlap_before = int(px) if hit else 0
    if not hit:
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale, "needs_pill": needs_pill,
            "hide_character": False, "guaranteed": True,
            "overlap_px": 0, "overlap_before_px": 0,
            "actions": actions + ["ok-first-try"],
        }

    # --- Fix 1: shrink font a cascata (preferito: nessun flicker layout) ---
    for step in FONT_SHRINK_STEPS[1:]:
        fs = base_scale * float(step)
        layout_s, tb_s = measure(base_area, fs)
        if layout_s is None or tb_s is None:
            continue
        hit_s, px_s = rects_overlap(char_box, tb_s, margin)
        if not hit_s:
            actions.append(f"shrink-font({base_scale:.2f}->{fs:.2f})")
            return {
                "layout": preset, "safe_area": base_area,
                "font_scale": fs, "needs_pill": needs_pill,
                "hide_character": False, "guaranteed": True,
                "overlap_px": 0, "overlap_before_px": overlap_before,
                "actions": actions,
            }

    # --- Fix 1b (Fase 4): auto-scaling dinamico fino a 40px min + rewrap ---
    # Se la riga supera l'80% larghezza, scala giu' fino al minimo; se ancora
    # oltre, forza il wrapping sulla pausa piu' vicina (max_width ridotto).
    try:
        _dyn_limit = int(dynamic_max_text_width())
        _min_scale = float(dynamic_min_font_scale(base_size)) * float(base_scale)
        _wide = int(widest_line_px(layout))
        if _wide > _dyn_limit and layout is not None:
            _fit_scale = float(base_scale) * (float(_dyn_limit) / max(1.0, float(_wide)))
            _fit_scale = max(_min_scale, min(float(base_scale), _fit_scale))
            _ls, _tbs = measure(base_area, _fit_scale)
            if _ls is not None and _tbs is not None:
                _hs, _ = rects_overlap(char_box, _tbs, margin)
                _ok_z, _ = verify_z_order(_tbs, char_box)
                if not _hs and _ok_z:
                    actions.append(f"auto-scale-80pct({base_scale:.2f}->{_fit_scale:.2f})")
                    return {
                        "layout": preset, "safe_area": base_area,
                        "font_scale": _fit_scale, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
            # Ancora larga al minimo: wrapping forzato (max_width dimezzato).
            try:
                _split = rewrap_split_point(words)
                _narrow = max(320, _dyn_limit // 2)
                _ln, _tbn = measure(base_area, _min_scale)
                if _ln is not None and _tbn is not None:
                    _hn, _ = rects_overlap(char_box, _tbn, margin)
                    if not _hn:
                        actions.append(f"rewrap-pausa(split@{_split})+min-font")
                        return {
                            "layout": preset, "safe_area": base_area,
                            "font_scale": _min_scale, "needs_pill": needs_pill,
                            "hide_character": False, "guaranteed": True,
                            "overlap_px": 0, "overlap_before_px": overlap_before,
                            "actions": actions,
                        }
            except Exception:
                pass
    except Exception:
        pass

    # --- Fix 2: restringi safe area center verso l'alto (testa a 644) ---
    if preset in ("layout_center_standard", "layout_center_punch_in"):
        try:
            ax0, ay0, ax1, _ay1 = base_area
            tight_area = (ax0, ay0, ax1, CENTER_SAFE_Y_MAX_FIXED)
            layout_t, tb_t = measure(tight_area, base_scale * 0.9)
            if layout_t is not None and tb_t is not None:
                hit_t, _ = rects_overlap(char_box, tb_t, margin)
                if not hit_t:
                    actions.append(f"tighten-center-ymax(->{CENTER_SAFE_Y_MAX_FIXED})+shrink0.9")
                    return {
                        "layout": preset, "safe_area": tight_area,
                        "font_scale": base_scale * 0.9, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
        except Exception:
            pass

    # --- Fix 3: allarga split verso il centro (parola lunga) ---
    if preset in ("layout_split_left", "layout_split_right"):
        try:
            ax0, ay0, ax1, ay1 = base_area
            if preset == "layout_split_left":
                wide = (max(0, ax0 - SPLIT_WIDEN_PX), ay0, ax1, ay1)
            else:
                wide = (ax0, ay0, min(VIDEO_WIDTH, ax1 + SPLIT_WIDEN_PX), ay1)
            layout_w, tb_w = measure(wide, base_scale * 0.8)
            if layout_w is not None and tb_w is not None:
                hit_w, _ = rects_overlap(char_box, tb_w, margin)
                if not hit_w:
                    actions.append(f"widen-split(+{SPLIT_WIDEN_PX}px)+shrink0.8")
                    return {
                        "layout": preset, "safe_area": wide,
                        "font_scale": base_scale * 0.8, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
        except Exception:
            pass

    # --- Fix 4: switch preset (solo se necessario: puo' dare stacco visivo) ---
    # Center affollato -> split dal lato libero; split affollato -> center.
    candidates: list[str] = []
    if preset == "layout_center_standard":
        if pose == 4:
            # Posa 4 solo a sinistra (mai split_right/center).
            candidates = ["layout_split_left"]
        else:
            candidates = ["layout_split_right", "layout_split_left"]
    elif preset in ("layout_split_left", "layout_split_right"):
        candidates = ["layout_center_standard"]
    else:  # punch_in: non switchare (look intenzionale), vai al fallback pill
        candidates = []
    for cand in candidates:
        # Mai pose 2 in split (regola 0).
        if cand in ("layout_split_left", "layout_split_right") and pose in WIDE_POSES_IN_SPLIT:
            continue
        # Posa 4 solo split_left (indica verso destra, sta a sinistra).
        if pose == 4 and cand != "layout_split_left":
            continue
        try:
            cand_area = preset_safe_area(cand, VIDEO_WIDTH, VIDEO_HEIGHT)
            cand_scale = preset_font_scale(cand)
            cand_char = get_character_tight_canvas(pose, cand, punch)
            layout_c, tb_c = measure(cand_area, cand_scale)
            if layout_c is None or tb_c is None:
                continue
            hit_c, _ = rects_overlap(cand_char, tb_c, margin)
            if not hit_c:
                actions.append(f"switch-preset({preset}->{cand})")
                return {
                    "layout": cand, "safe_area": cand_area,
                    "font_scale": cand_scale,
                    "needs_pill": preset_needs_text_background(cand) or punch,
                    "hide_character": False, "guaranteed": True,
                    "overlap_px": 0, "overlap_before_px": overlap_before,
                    "actions": actions,
                }
        except Exception:
            continue

    # --- Fix 5: punch-in intenzionale -> pill obbligatoria (leggibilita') ---
    if punch or preset == "layout_center_punch_in":
        actions.append("punch-in:intentional-overlap+pill")
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale * 0.8, "needs_pill": True,
            "hide_character": False, "guaranteed": False,
            "overlap_px": overlap_before, "overlap_before_px": overlap_before,
            "actions": actions,
        }

    # --- Fix 6 (ultima spiaggia, sempre garantito): nascondi personaggio ---
    actions.append("hide-character(fallback-garantito)")
    return {
        "layout": preset, "safe_area": base_area,
        "font_scale": base_scale, "needs_pill": False,
        "hide_character": True, "guaranteed": True,
        "overlap_px": 0, "overlap_before_px": overlap_before,
        "actions": actions,
    }


def _block_key_of(chunk: dict | None) -> int | None:
    """block_id del macro-blocco (None se assente, mai eccezioni)."""
    try:
        if not isinstance(chunk, dict):
            return None
        b = chunk.get("block_id")
        if b is None:
            _ch = chunk.get("character")
            if isinstance(_ch, dict):
                b = _ch.get("block_id")
        if b is None:
            return None
        return int(b)
    except Exception:
        return None


def _is_visibly_anchored(chunk: dict | None) -> bool:
    """Vero se il chunk ha personaggio visibile in macro-blocco."""
    try:
        if not isinstance(chunk, dict):
            return False
        _ch = chunk.get("character")
        if isinstance(_ch, dict):
            if not bool(_ch.get("visible", True)):
                return False
        if chunk.get("char_visible") is False:
            return False
        if chunk.get("guard_hidden") is True:
            return False
        return chunk.get("pose") is not None
    except Exception:
        return False


def build_realtime_plan(
    chunks: list[dict],
    font_size: int | None = None,
    margin: int = SAFETY_MARGIN_PX,
) -> tuple[list[dict], dict]:
    """Piano real-time per TUTTI i chunk, con ancoraggio macro-blocchi.

    Macro-blocchi (Breath & Focus): dentro lo stesso block_id visibile il
    layout resta ANCORATO (stesso preset per tutti i chunk: testo nel lato
    opposto al personaggio, nessun salto tra chunk contigui). I chunk senza
    personaggio (visible=False) usano il centro ampio. La continuita' di posa
    (stessa immagine -> stesso layout) resta come rete per i chunk senza
    block_id (retrocompatibilita').

    Returns:
        (plans, summary): plans[i] = plan_chunk_realtime + {"chunk_index"}.
        summary = {"total","guaranteed","fixed","hidden","intentional","overlaps_before"}.
    """
    plans: list[dict] = []
    try:
        n = len(chunks or [])
    except TypeError:
        return [], {"total": 0, "guaranteed": 0, "fixed": 0, "hidden": 0,
                    "intentional": 0, "overlaps_before": 0}
    # Solo continuita' di posa (stessa immagine -> stesso layout, taglio
    # invisibile). Niente beat-lock: il corpo cambia layout liberamente per
    # ritmo dinamico (morph fluido + persistenza gap = niente flicker).
    _prev_pose: int | None = None
    _prev_plan_layout: str | None = None
    for i in range(n):
        try:
            ch = chunks[i] if isinstance(chunks[i], dict) else {}
        except (IndexError, TypeError):
            ch = {}
        try:
            words = str(ch.get("text", "")).split()
        except Exception:
            words = []
        plan = plan_chunk_realtime(ch, words=words, font_size=font_size, margin=margin)
        # Continuita' di posa: stessa immagine del chunk prima -> prova a
        # tenere lo stesso layout (taglio invisibile). Accetta il riuso se
        # garantito o non peggiore; altrimenti tieni il nuovo layout (il
        # text_animator fara' comunque jump-cut senza sparizione).
        try:
            _cur_pose = ch.get("pose")
            _cur_pose_i = int(_cur_pose) if _cur_pose is not None else None
        except Exception:
            _cur_pose_i = None
        try:
            if (
                _cur_pose_i is not None and _prev_pose is not None
                and _cur_pose_i == _prev_pose and _prev_plan_layout is not None
                and str(plan.get("layout")) != str(_prev_plan_layout)
                and not bool(plan.get("hide_character"))
            ):
                locked_pose = dict(ch)
                locked_pose["layout"] = str(_prev_plan_layout)
                locked_pose["layout_preset"] = str(_prev_plan_layout)
                retry_pose = plan_chunk_realtime(
                    locked_pose, words=words, font_size=font_size, margin=margin
                )
                if bool(retry_pose.get("guaranteed")) or (
                    not bool(plan.get("guaranteed"))
                    and int(retry_pose.get("overlap_px", 0)) <= int(plan.get("overlap_px", 0))
                ):
                    retry_pose["actions"] = list(retry_pose.get("actions", [])) + ["pose-hold"]
                    plan = retry_pose
        except Exception:
            pass
        try:
            _prev_pose = _cur_pose_i
            _prev_plan_layout = str(plan.get("layout"))
        except Exception:
            pass
        plan["chunk_index"] = int(i)
        plans.append(plan)

    # --- Ancoraggio macro-blocco: stesso layout per tutto il blocco visibile ---
    # Testo nel lato opposto al personaggio per l'intera apparizione; chunk
    # hidden -> centro ampio (nessun salto tra chunk contigui dello stesso blocco).
    try:
        _groups: dict[int, list[int]] = {}
        for _gi in range(n):
            try:
                _bk = _block_key_of(chunks[_gi] if isinstance(chunks[_gi], dict) else None)
            except Exception:
                _bk = None
            if _bk is None:
                continue
            _groups.setdefault(int(_bk), []).append(int(_gi))
        for _bk, _idxs in _groups.items():
            if len(_idxs) <= 1:
                continue
            try:
                _visible = [_i for _i in _idxs if _is_visibly_anchored(
                    chunks[_i] if isinstance(chunks[_i], dict) else None)]
            except Exception:
                _visible = []
            if not _visible:
                # Blocco nascosto: forza centro ampio stabile (testo leggibile).
                for _i in _idxs:
                    try:
                        if plans[_i].get("hide_character"):
                            continue
                        plans[_i]["layout"] = "layout_center_standard"
                        plans[_i]["actions"] = list(plans[_i].get("actions", [])) + ["block-anchor-hidden-center"]
                    except Exception:
                        continue
                continue
            # Blocco visibile: anchor = layout piu' frequente tra i garantiti.
            try:
                _freq: dict[str, int] = {}
                for _i in _visible:
                    try:
                        if plans[_i].get("guaranteed") and not plans[_i].get("hide_character"):
                            _l = str(plans[_i].get("layout", "layout_center_standard"))
                            _freq[_l] = _freq.get(_l, 0) + 1
                    except Exception:
                        continue
                if _freq:
                    _anchor = max(_freq, key=lambda k: _freq[k])
                else:
                    _anchor = str(plans[_visible[0]].get("layout", "layout_center_standard"))
            except Exception:
                continue
            for _i in _visible:
                try:
                    if str(plans[_i].get("layout")) == str(_anchor):
                        continue
                    if bool(plans[_i].get("hide_character")):
                        continue
                    _ch = dict(chunks[_i] or {})
                    _ch["layout"] = str(_anchor)
                    _ch["layout_preset"] = str(_anchor)
                    try:
                        _words = str(_ch.get("text", "")).split()
                    except Exception:
                        _words = []
                    _retry = plan_chunk_realtime(_ch, words=_words, font_size=font_size, margin=margin)
                    # Accetta se garantito o non peggiore (ancoraggio rigido > switch).
                    _cur_ov = int(plans[_i].get("overlap_px", 0) or 0)
                    _new_ov = int(_retry.get("overlap_px", 0) or 0)
                    if bool(_retry.get("guaranteed")) or (
                        not bool(plans[_i].get("guaranteed")) and _new_ov <= _cur_ov
                    ):
                        _retry["actions"] = list(_retry.get("actions", [])) + [f"block-anchor({ _anchor})"]
                        _retry["layout"] = str(_anchor)
                        _retry["chunk_index"] = int(_i)
                        plans[_i] = _retry
                    else:
                        # Ancoraggio rigido anche senza garanzia geometrica:
                        # forza layout + pill per leggibilita' (mai salto testo).
                        try:
                            plans[_i]["layout"] = str(_anchor)
                            plans[_i]["actions"] = list(plans[_i].get("actions", [])) + [f"block-anchor-forced({ _anchor})"]
                        except Exception:
                            pass
                except Exception:
                    continue
    except Exception:
        pass

    try:
        guaranteed = sum(1 for p in plans if p.get("guaranteed"))
        fixed = sum(1 for p in plans if p.get("overlap_before_px", 0) > 0 and p.get("guaranteed"))
        hidden = sum(1 for p in plans if p.get("hide_character"))
        intentional = sum(1 for p in plans if not p.get("guaranteed"))
        before = sum(int(p.get("overlap_before_px", 0) or 0) for p in plans)
    except Exception:
        guaranteed, fixed, hidden, intentional, before = 0, 0, 0, 0, 0
    summary = {
        "total": n, "guaranteed": guaranteed, "fixed": fixed,
        "hidden": hidden, "intentional": intentional, "overlaps_before": before,
    }
    return plans, summary


def apply_realtime_plans(chunks: list[dict], plans: list[dict]) -> list[dict]:
    """Applica i piani ai chunk (mutazione sicura, ritorna nuova lista).

    - layout/layout_preset/position/transition aggiornati allo switch;
    - guard_safe_area / guard_font_scale / guard_pill scritti sul chunk
      (letti da text_animator e renderer, precedenza sul preset);
    - hide_character=True -> pose rimossa (nessun paste, testo libero).
    Mai eccezioni; lunghezze diverse -> chunk invariati per gli extra.
    """
    try:
        from core.layout_presets import legacy_position, normalize_transition_in
    except Exception:
        legacy_position = lambda p: "bottom_center"  # noqa: E731
        normalize_transition_in = lambda v, p: "fade"  # noqa: E731
    out: list[dict] = []
    try:
        n = len(chunks or [])
    except TypeError:
        return chunks
    for i in range(n):
        try:
            ch = dict(chunks[i] or {})
        except Exception:
            try:
                out.append(chunks[i])
            except Exception:
                pass
            continue
        try:
            plan = plans[i] if i < len(plans or []) and isinstance(plans[i], dict) else None
        except Exception:
            plan = None
        if not plan:
            out.append(ch)
            continue
        try:
            if plan.get("hide_character"):
                ch.pop("pose", None)
                ch["guard_hidden"] = True
                # Sincronizza macro-blocco: hidden => visible=False, event NONE.
                try:
                    _b = ch.get("block_id")
                    if _b is None and isinstance(ch.get("character"), dict):
                        _b = ch["character"].get("block_id", 0)
                    ch["char_event"] = "NONE"
                    ch["char_visible"] = False
                    ch["character"] = {
                        "visible": False, "pose": None, "pose_id": "",
                        "side": "CENTER", "event": "NONE",
                        "block_id": int(_b or 0),
                    }
                except Exception:
                    pass
            else:
                lay = str(plan.get("layout", ch.get("layout", "layout_center_standard")))
                ch["layout"] = lay
                ch["layout_preset"] = lay
                try:
                    ch["position"] = legacy_position(lay)
                except Exception:
                    pass
            if plan.get("safe_area") is not None:
                try:
                    sa = plan["safe_area"]
                    ch["guard_safe_area"] = (int(sa[0]), int(sa[1]), int(sa[2]), int(sa[3]))
                except Exception:
                    pass
            try:
                ch["guard_font_scale"] = float(plan.get("font_scale", 1.0))
            except Exception:
                pass
            if plan.get("needs_pill"):
                ch["guard_pill"] = True
        except Exception:
            pass
        out.append(ch)
    return out
