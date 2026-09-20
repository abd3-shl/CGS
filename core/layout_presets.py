"""
Dynamic Layout & Smart Text Zones: preset di scena a "zone" (1080x1920).

REELS-FIX v6 (clipping-fix definitivo, face-anchor dinamico):
- Split 115% (~1242px) paste DINAMICO face-anchor (volto 25%/75% ≈270/810,
  mai hardcoded -380/+430/overhang 420 che tagliavano mezza faccia);
  center 132% centrato con occupancy top ~852 (gap 132px dalla fascia testo).
- Posa 2 larga (676px) sempre center; pose 4/5 sempre split.
- Center testo SOLO fascia alta Y[140,720]; split testo colonne strette
  X[665,1000]/X[80,415] Y[320,1250]; punch zoom 1.15x fascia Y[140,620].
- Text Safe Zones rigide + occupancy_box AABB con fascia +120/+24px +
  nudge anti-overlap dinamico: verify_zero_overlap() garantisce IoU==0,
  verify_face_visible() garantisce volto integro con margine 40px.

Niente figura intera: i personaggi sono ingranditi in scala su larghezza
e ancorati in alto a Y=200 con le gambe fuori inquadratura
(i piedi non sono MAI visibili, la testa resta sempre in campo).
Il cropping e' solo compositivo: le coordinate (X, Y) possono uscire dal
canvas e il paste ritaglia il visibile.

Preset (canvas 1080x1920, asset di riferimento 768x1376 figura intera):
- `layout_center_standard`: 125% larghezza, centrato in basso (mezza figura,
  testa-busto-fianchi). Testo in alto (Y 150-900).
- `layout_center_punch_in`: 170% larghezza (primo piano busto/testa).
  Testo nel terzo superiore in sovrimpressione con pill ad alto contrasto.
- `layout_split_left`: 130% larghezza, spalla sinistra fuori campo
  (overhang negativo). Testo a destra (X 640-1000, banda centrale).
- `layout_split_right`: speculare (testo a sinistra, X 80-420).
  Con la posa 4 ("indicare") il personaggio indica verso il testo.

Punch-in: flag per-chunk (jump-cut con ingrandimento improvviso per enfasi,
max 2 per video). Su un preset normale applica PUNCH_IN_FACTOR alle
dimensioni; sul preset punch_in la scala e' gia' ravvicinata.

Geometria misurata sugli asset (testa src x300-470/y130-340, spalle da y380):
le safe area sono scelte per non sovrapporsi mai al volto/busto; il text
engine e il character engine risolvono entrambi da `resolve_chunk_layout`
(vedi core/character_selector.py), quindi non possono divergere.

Margini/padding configurabili: SPLIT_OVERHANG_X, SAFE_AREA inset nei box,
TEXT_PILL_*.
"""

from config import VIDEO_HEIGHT, VIDEO_WIDTH

# Nomi preset validi (ordine stabile, usato anche dal fallback deterministico).
VALID_LAYOUT_PRESETS: list[str] = [
    "layout_center_standard",
    "layout_center_punch_in",
    "layout_split_left",
    "layout_split_right",
]

# Vecchi nomi (sistema a zone v1): ancora accettati, mappati sui nuovi.
DEPRECATED_PRESET_ALIASES: dict[str, str] = {
    "layout_bottom_focus": "layout_center_standard",
    "layout_closeup_center": "layout_center_punch_in",
}

# Transizioni di ingresso valide (nuovo sistema a zone).
VALID_TRANSITION_IN: list[str] = [
    "slide_from_left",
    "slide_from_right",
    "slide_up",
    "slide_from_bottom",
    "fade",
    "none",
]

# Transizioni legacy (posizionamento statico v1) -> canoniche del nuovo sistema.
# "slide_side" e' direzionale: la risoluzione dipende dal lato del preset.
LEGACY_TRANSITION_MAP: dict[str, str | None] = {
    "slide_up": "slide_up",
    "slide_side": None,  # risolto in base al lato (left/right)
    "fade": "fade",
    "none": "none",
}

# Posizioni legacy v1 -> preset piu' vicino (per output LLM in formato vecchio
# o chunk arricchiti senza layout: nessuna regressione).
LEGACY_POSITION_TO_PRESET: dict[str, str] = {
    "bottom_left": "layout_split_left",
    "side_left": "layout_split_left",
    "bottom_right": "layout_split_right",
    "side_right": "layout_split_right",
    "bottom_center": "layout_center_standard",
}

# --- Scala personaggio: percentuale della LARGHEZZA schermo ---
# REELS-FIX v6 (clipping-fix: volto sempre integro in split):
# split al 115% (~1242px su 1080, visibile ~515-540px = mezza metà schermo,
# gutter garantito), center 130-134% (~1405-1450px), punch-in 1.50x con
# PUNCH_IN_FACTOR 1.15x. Il 120% precedente rendeva il visibile troppo largo
# (>560px) e forzava overhang eccessivo con mezzo-taglio del volto.
PRESET_WIDTH_PCT: dict[str, float] = {
    "layout_center_standard": 1.32,
    "layout_center_punch_in": 1.50,
    "layout_split_left": 1.15,
    "layout_split_right": 1.15,
}

# Vincoli matematici Perfect-Crop (spec §3, canvas 1080x1920).
# REELS-FIX v6: split 110-118% ammesso (target 115%), center 130-134%,
# punch max 1.55.
PERFECT_CROP_SCALE_MIN: float = 1.10
PERFECT_CROP_SCALE_MAX: float = 1.40
# Offset positivo Y: il fondo scende SEMPRE sotto il bordo (gambe mai visibili,
# petto/volto centrati). Formula STORICA: paste_y = canvas_h - new_h + OFFSET.
# DEPRECATA per il bug decapitazione (con new_h molto alta dava paste_y
# negativo e testa fuori schermo): ora si usa HEADROOM_TOP fisso (vedi sotto).
PERFECT_CROP_Y_OFFSET: int = 150
# Slide orizzontale split_left <-> split_right: durata + easing.
SLIDE_X_DURATION: float = 0.30

# --- REGOLA D'ORO ANTI-DECAPITAZIONE + REELS GRID (Canvas 1080x1920) ---
# La testa del personaggio DEVE essere SEMPRE visibile e MAI sotto il testo.
# HEADROOM_TOP: margine superiore dell'immagine (paste_y). Split restano alti
# (Y=200) per lasciare colonna testo libera; il center_standard e' spinto in
# basso (occupancy garantita Y>=950) cosi' la fascia testo Y[140,720] e' libera.
HEADROOM_TOP: int = 200
# DEPRECATI (causa mezzo-taglio): paste fisso ignorava new_w e trim per-posa
# (X=+430/-380 tagliavano mezza faccia sul bordo 1080). Il path attivo usa
# ancoraggio DINAMICO al volto (face-anchor 25%/75%, vedi pose_paste_x/
# preset_paste_x sotto). Conservati per compatibilita' import, NON usare.
SPLIT_LEFT_X: int = -420
SPLIT_RIGHT_X: int = 420
# Ancoraggio orizzontale DINAMICO del volto (frazione larghezza canvas):
# split_left -> volto al 25% (X≈270), split_right -> volto al 75% (X≈810).
# Il paste_x e' calcolato come target - face_cx*scala, poi corretto di un
# nudge anti-overlap (max ±60px) per garantire gutter testo/personaggio.
FACE_ANCHOR_LEFT_FRAC: float = 0.25
FACE_ANCHOR_RIGHT_FRAC: float = 0.75
# Nudge massimo anti-overlap (px): oltre si preferisce stringere la scala.
FACE_ANCHOR_MAX_NUDGE_PX: int = 60
# Gutter centrale di garanzia tra testo e personaggio (px).
CENTER_GUTTER_PX: int = 80
# Fascia di rispetto occupancy: +120px sopra la testa, +-24px sui lati
# (bbox per-posa gia' strette: 24px bastano, 60px mangiava il gutter testo).
OCCUPANCY_HEADROOM_PX: int = 120
OCCUPANCY_SIDE_PX: int = 24
# Occupancy minima garantita per center_standard (testo sopra, corpo sotto).
CENTER_CHARACTER_TOP_MIN: int = 950

# Moltiplicatore punch-in REELS-FIX v5: 1.15x (non piu' 1.35 mostruoso).
PUNCH_IN_FACTOR: float = 1.15
# Max punch-in per video (frasi chiave / rivelazioni / CTA finali).
MAX_PUNCH_INS_PER_VIDEO: int = 2

# --- Ancoraggio verticale: headroom px dal bordo superiore al top asset ---
# REELS-FIX v5: split alti (200, colonna testo libera Y[320,1250]), center
# spinto in basso (occupancy top >=950) cosi' fascia testo Y[140,720] libera.
# Il fondo esce sempre sotto canvas_h (gambe mai visibili).
# Misurato su assets reali 768x1376 (bbox alpha 218,82,551,1298):
# testa src y130-340, bbox visibile 43% larghezza centrata. Con scala 132%
# (1425px) la testa reale sta a py+241: py=820 -> testa Y~1061 (>=950 ok),
# occupancy (py+bbox_y0-120) ~852, gap 132px dalla fascia testo Y1=720.
PRESET_HEADROOM_PX: dict[str, int] = {
    "layout_center_standard": 820,
    "layout_center_punch_in": 200,
    "layout_split_left": 200,
    "layout_split_right": 200,
}

# --- Ancoraggio orizzontale split: DEPRECATO l'overhang fisso ---
# SPLIT_OVERHANG_X (420px) causava il mezzo-taglio: ignorava new_w e la bbox
# reale per-posa. Conservato per compatibilita', ma il path attivo e'
# face-anchor dinamico (vedi preset_paste_x/pose_paste_x). NON usare.
SPLIT_OVERHANG_X: int = 420
# Overhang MASSIMO tollerato per la spalla esterna (estetica, px su 1080).
# Il volto/busto centrale MAI fuori: solo la spalla puo' uscire fino a qui.
SPLIT_MAX_SHOULDER_OVERHANG_PX: int = 40

# --- SPLIT FIT-TO-HALF v7 (fix definitivo "personaggio tagliato") ---
# Il personaggio negli split DEVE stare interamente nella sua meta' schermo
# con margine dal bordo; il testo ha una Safe Area dedicata senza overlap.
# NESSUN numero magico assoluto nel calcolo: le soglie sotto sono definite
# su canvas 1080 e scalate proporzionalmente via _split_thresholds(canvas_w).
# - ancoraggio: centro della bbox VISIBILE sul centro di meta' schermo
#   (SX: 25% canvas, DX: 75% canvas):
#   paste_x = CANVAS_W * frac - (bx0 * k + vis_w * k / 2)
# - emergency autoscale: se la bbox visibile scalata supera MAX_VISIBLE_W,
#   la scala si riduce iterativamente (*FIT_STEP) fino a rientrare, mai
#   sotto MIN_SCALE_ABS. Garantisce: x1 <= canvas - margine, x0 >= margine.
# - testo dinamico: box dal bordo opposto fino a TEXT_GAP px prima del bbox.
SPLIT_EDGE_MARGIN_PX: int = 20
SPLIT_TEXT_GAP_PX: int = 40
SPLIT_MAX_VISIBLE_W_PX: int = 600
SPLIT_MIN_SCALE_ABS: float = 0.60
SPLIT_FIT_STEP: float = 0.95
SPLIT_MIN_TEXT_W_PX: int = 200

# Text Safe Area per preset: (x_min, y_min, x_max, y_max) su 1080x1920.
# REELS-FIX v7 FIT-TO-HALF (TikTok/Reels):
# - center_standard: SOLO fascia alta X[90,990] Y[140,720], corpo sotto Y>=950.
# - split_left (char SX fittato, visibile dentro [20,1060]) -> testo DX
#   X[665,1000] Y[320,1250] (worst-case su tutte le pose incl. punch).
# - split_right (char DX fittato) -> testo SX X[80,415] Y[320,1250].
# - center_punch_in -> fascia alta X[80,1000] Y[140,620] (+pill, zoom 1.15x).
# Nel render si usa preset_safe_area_dynamic() (bordo a 40px dall'occupancy
# reale della posa, box piu' larghi per-posa); questi statici restano il
# fallback sicuro senza posa nota. Il wrapping e' FORZATO su (X_MAX-X_MIN);
# auto-fit riduce fino a 38px (vedi renderer / text_animator).
PRESET_SAFE_AREA: dict[str, tuple[int, int, int, int]] = {
    "layout_center_standard": (90, 140, 990, 720),
    "layout_center_punch_in": (80, 140, 1000, 620),
    "layout_split_left": (665, 320, 1000, 1250),
    "layout_split_right": (80, 320, 415, 1250),
}

# Scala font per preset (box stretti degli split -> testo leggermente minore).
PRESET_FONT_SCALE: dict[str, float] = {
    "layout_center_standard": 1.0,
    "layout_center_punch_in": 1.0,
    "layout_split_left": 0.9,
    "layout_split_right": 0.9,
}

# Lato del personaggio (guida le transizioni direzionali e gli exit).
PRESET_SIDE: dict[str, str] = {
    "layout_center_standard": "center",
    "layout_center_punch_in": "center",
    "layout_split_left": "left",
    "layout_split_right": "right",
}

# Transizione di ingresso di default per preset.
PRESET_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "layout_center_standard": "slide_up",
    "layout_center_punch_in": "fade",
    "layout_split_left": "slide_from_left",
    "layout_split_right": "slide_from_right",
}

# Preset che richiedono la pill ad alto contrasto dietro il testo.
PRESET_TEXT_BACKGROUND: dict[str, bool] = {
    "layout_center_standard": False,
    "layout_center_punch_in": True,
    "layout_split_left": False,
    "layout_split_right": False,
}

# Auto-pill elegante REELS-FIX v5 (solo quando contrasto <80, vedi renderer).
TEXT_PILL_FILL: tuple[int, int, int, int] = (0, 0, 0, 120)
TEXT_PILL_PAD: int = 20
TEXT_PILL_PAD_Y: int = 10
TEXT_PILL_RADIUS: int = 24


def is_valid_preset(name) -> bool:
    """Vero se `name` e' un layout preset noto (inclusi gli alias deprecati)."""
    return name in VALID_LAYOUT_PRESETS or name in DEPRECATED_PRESET_ALIASES


def normalize_preset(name, fallback: str = "layout_center_standard") -> str:
    """Normalizza il preset (alias deprecati e position legacy mappate).

    Ritorna sempre un nome canonico di VALID_LAYOUT_PRESETS.
    """
    if name in VALID_LAYOUT_PRESETS:
        return name
    if isinstance(name, str) and name in DEPRECATED_PRESET_ALIASES:
        return DEPRECATED_PRESET_ALIASES[name]
    if isinstance(name, str) and name in LEGACY_POSITION_TO_PRESET:
        return LEGACY_POSITION_TO_PRESET[name]
    return fallback if fallback in VALID_LAYOUT_PRESETS else "layout_center_standard"


def perfect_crop_y(new_h: int, canvas_h: int = VIDEO_HEIGHT,
                     offset: int = PERFECT_CROP_Y_OFFSET) -> int:
    """Coordinata Y Perfect-Crop STORICA: `canvas_h - new_h + offset`.

    DEPRECATA (bug decapitazione): con new_h molto alta dava paste_y negativo
    e testa fuori schermo. Conservata per compatibilita'; il path attivo usa
    `character_anchor_y()` = HEADROOM_TOP fisso (vedi REGOLA D'ORO sopra).
    """
    try:
        return int(canvas_h) - int(new_h) + int(offset)
    except (TypeError, ValueError):
        return int(canvas_h) - int(new_h)


def character_anchor_y(canvas_h: int = VIDEO_HEIGHT, preset_name: str | None = None) -> int:
    """Ancoraggio Y REELS-FIX v5 (mai solleva).

    Split/punch: HEADROOM_TOP=200 (colonna testo libera). Center_standard:
    620px (occupancy volto/busto >=950, fascia testo Y[140,720] libera).
    MAI canvas_h - new_h. Scalato su canvas diversi da 1080x1920.
    """
    try:
        base = int(PRESET_HEADROOM_PX.get(normalize_preset(preset_name), HEADROOM_TOP)) \
            if preset_name is not None else int(HEADROOM_TOP)
    except Exception:
        base = int(HEADROOM_TOP)
    if canvas_h == VIDEO_HEIGHT:
        return int(base)
    try:
        return int(round(float(base) * float(canvas_h) / float(VIDEO_HEIGHT)))
    except (TypeError, ValueError, ZeroDivisionError):
        return int(base)


def _face_anchor_target(preset: str, canvas_w: int) -> float | None:
    """Target X del CENTRO VOLTO su canvas (px) per i layout split.

    split_left  -> 25% larghezza (≈270 su 1080), split_right -> 75% (≈810).
    Ritorna None per i center (ancoraggio centrale classico).
    """
    try:
        cw = float(canvas_w)
    except (TypeError, ValueError):
        cw = float(VIDEO_WIDTH)
    if preset == "layout_split_left":
        try:
            return float(cw) * float(FACE_ANCHOR_LEFT_FRAC)
        except Exception:
            return float(cw) * 0.25
    if preset == "layout_split_right":
        try:
            return float(cw) * float(FACE_ANCHOR_RIGHT_FRAC)
        except Exception:
            return float(cw) * 0.75
    return None


def _face_anchor_base_paste(face_cx_native: float, new_w: int,
                            canvas_w: int, target_x: float) -> int:
    """paste_x che porta il centro volto nativo esattamente su target_x.

    Scala width-based: kx = new_w / src_w (768). Formula pura, nessun
    hardcoded: paste = target - face_cx * kx. Mantiene il volto perfettamente
    in camera a qualsiasi scala/risoluzione.
    """
    try:
        sw0 = float(MEASURED_SRC_SIZE[0]) or 768.0
    except Exception:
        sw0 = 768.0
    try:
        kx = float(new_w) / sw0 if sw0 else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        kx = 1.0
    try:
        return int(round(float(target_x) - float(face_cx_native) * kx))
    except (TypeError, ValueError):
        return 0


def _gutter_nudge_for_split(preset: str, base_px: int, new_w: int,
                            canvas_w: int,
                            vis_dx0: float, vis_dx1: float) -> int:
    """Nudge anti-overlap testo/personaggio (dinamico, max ±60px).

    Confronta l'occupancy orizzontale (visibile + OCCUPANCY_SIDE_PX) con la
    Text Safe Area del preset: se il gap < 24px sposta il personaggio verso
    l'esterno (destra per split_right, sinistra per split_left) del deficit
    esatto. Clampato a FACE_ANCHOR_MAX_NUDGE_PX per non allontanare il volto
    dal target 25%/75%. Il volto resta SEMPRE dentro con margine 40px
    (verificato dal chiamante via verify_face_visible).
    """
    try:
        gutter_need = 24
        try:
            gutter_need = int(OCCUPANCY_SIDE_PX)
            # OCCUPANCY_SIDE_PX e' il padding occupancy; il gap minimo reale
            # testo/occupancy e' 24px (vedi verify_zero_overlap).
            gutter_need = 24
        except Exception:
            gutter_need = 24
        safe = PRESET_SAFE_AREA.get(preset)
        if safe is None or len(safe) != 4:
            return int(base_px)
        try:
            max_nudge = int(FACE_ANCHOR_MAX_NUDGE_PX)
        except Exception:
            max_nudge = 60
        try:
            side = int(OCCUPANCY_SIDE_PX)
        except Exception:
            side = 24
        occ_x0 = float(base_px) + float(vis_dx0) - float(side)
        occ_x1 = float(base_px) + float(vis_dx1) + float(side)
        if preset == "layout_split_right":
            # Testo a SX: serve occ_x0 >= safe_x1 + gutter.
            need = float(safe[2]) + float(gutter_need)
            if occ_x0 >= need:
                return int(base_px)
            deficit = need - occ_x0
            shift = min(float(max_nudge), float(deficit))
            return int(round(float(base_px) + float(shift)))
        if preset == "layout_split_left":
            # Testo a DX: serve occ_x1 <= safe_x0 - gutter.
            need = float(safe[0]) - float(gutter_need)
            if occ_x1 <= need:
                return int(base_px)
            deficit = occ_x1 - need
            shift = min(float(max_nudge), float(deficit))
            return int(round(float(base_px) - float(shift)))
    except Exception:
        pass
    return int(base_px)


def _split_thresholds(canvas_w: int = VIDEO_WIDTH
                    ) -> tuple[int, int, int, int]:
    """Soglie split scalate sulla larghezza canvas (mai numeri magici assoluti).

    Ritorna (margine_bordo, gap_testo, max_larghezza_visibile, min_testo_w)
    proporzionali a canvas_w/1080. Mai solleva.
    """
    try:
        cw = float(canvas_w) if canvas_w else float(VIDEO_WIDTH)
    except (TypeError, ValueError):
        cw = float(VIDEO_WIDTH)
    if cw <= 0:
        cw = float(VIDEO_WIDTH)
    s = cw / 1080.0
    try:
        m = int(round(float(SPLIT_EDGE_MARGIN_PX) * s))
    except Exception:
        m = int(round(20.0 * s))
    try:
        g = int(round(float(SPLIT_TEXT_GAP_PX) * s))
    except Exception:
        g = int(round(40.0 * s))
    try:
        mv = int(round(float(SPLIT_MAX_VISIBLE_W_PX) * s))
    except Exception:
        mv = int(round(600.0 * s))
    try:
        mt = int(round(float(SPLIT_MIN_TEXT_W_PX) * s))
    except Exception:
        mt = int(round(200.0 * s))
    return (max(4, m), max(8, g), max(120, mv), max(80, mt))


def split_column_frac(preset_name: str) -> float:
    """Frazione del centro visivo di meta' schermo: 0.25 SX, 0.75 DX, 0.5 center."""
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        return 0.5
    if preset == "layout_split_left":
        return 0.25
    if preset == "layout_split_right":
        return 0.75
    return 0.5


def fit_split_scale(native_visible_w: float, base_scale_abs: float,
                    canvas_w: int = VIDEO_WIDTH) -> float:
    """Emergency autoscale FIT-TO-HALF (mai solleva).

    Se la bbox visibile scalata (native_visible_w * scala) supera la soglia
    di mezza colonna (+margine), riduce la scala di FIT_STEP finche' rientra
    o tocca MIN_SCALE_ABS. Ritorna la scala assoluta (<= base).
    """
    try:
        vw = float(native_visible_w)
    except (TypeError, ValueError):
        return base_scale_abs
    try:
        sc = float(base_scale_abs)
    except (TypeError, ValueError):
        return base_scale_abs
    if vw <= 0 or sc <= 0:
        return sc
    try:
        _, _, maxvis, _ = _split_thresholds(canvas_w)
    except Exception:
        maxvis = 600
    try:
        floor = float(SPLIT_MIN_SCALE_ABS)
    except Exception:
        floor = 0.60
    try:
        step = float(SPLIT_FIT_STEP)
        if not 0.5 < step < 1.0:
            step = 0.95
    except Exception:
        step = 0.95
    guard = 0
    while vw * sc > float(maxvis) and sc > floor and guard < 60:
        sc = max(floor, sc * step)
        guard += 1
        if sc <= floor:
            break
    return float(sc)


def column_anchor_paste_x(preset_name: str, bx0_native: float,
                          vis_w_native: float, scale_abs: float,
                          canvas_w: int = VIDEO_WIDTH) -> int:
    """paste_x che centra la bbox VISIBILE sul centro di meta' schermo.

    Formula pura (zero magic numbers):
      target = canvas_w * frac (0.25 SX / 0.75 DX)
      paste  = target - (bx0 * k + vis_w * k / 2)
    dove k = scala assoluta width-based. Mai solleva.
    """
    try:
        frac = float(split_column_frac(preset_name))
    except Exception:
        frac = 0.5
    try:
        cw = float(canvas_w) if canvas_w else float(VIDEO_WIDTH)
    except (TypeError, ValueError):
        cw = float(VIDEO_WIDTH)
    try:
        k = float(scale_abs)
    except (TypeError, ValueError):
        k = 1.0
    try:
        bx0 = float(bx0_native)
    except (TypeError, ValueError):
        bx0 = 0.0
    try:
        vw = float(vis_w_native)
    except (TypeError, ValueError):
        vw = cw
    return int(round(cw * frac - (bx0 * k + vw * k / 2.0)))


def clamp_paste_visible_inside(paste_x: int, bx0_scaled: float,
                               vis_w_scaled: float,
                               canvas_w: int = VIDEO_WIDTH) -> int:
    """Hard clamp: bbox visibile sempre dentro [margine, canvas-margine].

    Vincolo assoluto anti-taglio (mai solleva), ESATTO all'intero: lo snap
    finale verifica i bordi e compensa il ±0.5px del round, cosi' il margine
    e' garantito anche con bbox frazionarie (kx irrazionale). Se la larghezza
    visibile eccede lo spazio utile (solo quando l'autoscale ha toccato il
    floor), ancora il lato sinistro: best effort, mai crash.
    """
    import math as _math
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        margin, _, _, _ = _split_thresholds(cw)
    except Exception:
        margin = 20
    try:
        bx0s = float(bx0_scaled)
        vws = float(vis_w_scaled)
        p = float(paste_x)
    except (TypeError, ValueError):
        return int(paste_x)
    lo, hi = float(margin), float(cw - margin)
    if hi <= lo or vws < 0:
        return int(paste_x)
    if vws >= (hi - lo):
        # Piu' larga dello spazio utile: ancora il bordo sinistro (best effort).
        return int(round(lo - bx0s))
    if p + bx0s + vws > hi:
        p = hi - bx0s - vws
    if p + bx0s < lo:
        p = lo - bx0s
    # Snap intero con verifica (il round da solo puo' sforare di 0.5px).
    pi = int(round(p))
    if pi + bx0s < lo:
        pi = int(_math.ceil(lo - bx0s - 1e-9))
    if pi + bx0s + vws > hi:
        pi -= int(_math.ceil((pi + bx0s + vws) - hi - 1e-9))
    if pi + bx0s < lo:
        pi = int(_math.ceil(lo - bx0s - 1e-9))
    return int(pi)


def resolve_split_geometry(preset_name: str, native_full_w: float,
                           bx0_native: float, vis_w_native: float,
                           base_scale_abs: float,
                           canvas_w: int = VIDEO_WIDTH) -> dict:
    """Geometria split completa con garanzie matematiche (mai solleva).

    1. fit_split_scale: scala d'emergenza se visibile > soglia mezza colonna.
    2. column_anchor_paste_x: centra la bbox visibile sul 25%/75% canvas.
    3. clamp_paste_visible_inside: vincolo assoluto
       vis_x0 >= margine e vis_x1 <= canvas - margine.

    Ritorna dict {scale, paste_x, vis_x0, vis_x1, full_x0, full_x1, iters}.
    NOTA: full_x* include il padding trasparente del PNG (invisibile):
    la garanzia anti-taglio vale sulla bbox VISIBILE (viso+busto reali).
    """
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        preset = str(preset_name)
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        nfw = float(native_full_w)
    except (TypeError, ValueError):
        nfw = 768.0
    try:
        bx0 = float(bx0_native)
    except (TypeError, ValueError):
        bx0 = 0.0
    try:
        vw = float(vis_w_native)
    except (TypeError, ValueError):
        vw = nfw
    try:
        base = float(base_scale_abs)
    except (TypeError, ValueError):
        base = 1.0
    if nfw <= 0:
        nfw = 768.0
    if vw <= 0:
        vw = nfw
    if base <= 0:
        base = 1.0
    fitted = fit_split_scale(vw, base, cw)
    iters = 0 if fitted >= base - 1e-12 else 1
    paste = column_anchor_paste_x(preset, bx0, vw, fitted, cw)
    bx0s = bx0 * fitted
    vws = vw * fitted
    paste = clamp_paste_visible_inside(paste, bx0s, vws, cw)
    vis_x0 = paste + bx0s
    vis_x1 = vis_x0 + vws
    return {
        "scale": float(fitted),
        "paste_x": int(paste),
        "vis_x0": float(vis_x0),
        "vis_x1": float(vis_x1),
        "full_x0": float(paste),
        "full_x1": float(paste + nfw * fitted),
        "iters": int(iters),
    }


def fitted_split_character_size(preset_name: str, src_w: int, src_h: int,
                                canvas_w: int = VIDEO_WIDTH,
                                base_width_pct: float | None = None,
                                pose: int | None = None) -> tuple[int, int, float]:
    """Dimensioni personaggio con emergency autoscale (mai solleva).

    Ritorna (new_w, new_h, scala_assoluta) dopo il fit della bbox visibile.
    Per i center ritorna la taglia base invariata.
    """
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        preset = "layout_center_standard"
    try:
        sw, sh = int(src_w), int(src_h)
    except (TypeError, ValueError):
        sw, sh = (768, 1376)
    if sw <= 0 or sh <= 0:
        sw, sh = (768, 1376)
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    if preset not in ("layout_split_left", "layout_split_right"):
        try:
            pct = float(base_width_pct) if base_width_pct else float(preset_width_pct(preset, False))
        except Exception:
            pct = 1.32
        nw = max(1, int(round(cw * pct)))
        nh = max(1, int(round(sh * nw / float(sw))))
        return (nw, nh, float(nw) / float(sw))
    try:
        pct = float(base_width_pct) if base_width_pct else float(preset_width_pct(preset, False))
    except Exception:
        pct = 1.15
    base_nw = max(1, int(round(cw * pct)))
    try:
        base_scale = float(base_nw) / float(sw)
    except ZeroDivisionError:
        base_scale = 1.0
    try:
        _ref_w = float(MEASURED_SRC_SIZE[0]) or 768.0
    except Exception:
        _ref_w = 768.0
    try:
        bx0, _, bx1, _ = pose_visible_bbox(pose)
        # La bbox per-posa e' misurata su asset 768px: riscalala su src_w reali.
        w_ratio = float(sw) / _ref_w if _ref_w else 1.0
        nat_bx0 = float(bx0) * w_ratio
        nat_vw = float(bx1 - bx0) * w_ratio
    except Exception:
        nat_bx0, nat_vw = 0.0, float(sw)
    fitted = fit_split_scale(nat_vw, base_scale, cw)
    nw = max(1, int(round(float(sw) * fitted)))
    nh = max(1, int(round(float(sh) * fitted)))
    return (int(nw), int(nh), float(fitted))


def dynamic_split_text_area(preset_name: str, char_x0: float, char_x1: float,
                            canvas_w: int = VIDEO_WIDTH,
                            canvas_h: int = VIDEO_HEIGHT) -> tuple[int, int, int, int]:
    """Text Safe Area dinamica: dal bordo opposto a 40px prima del personaggio.

    `char_x0/char_x1` sono i bordi della bbox VISIBILE fittata; il box testo
    termina a SPLIT_TEXT_GAP_PX (40px) prima del BOUNDING BOX occupancy
    (visibile + OCCUPANCY_SIDE_PX), cioe' ~64px prima dei pixel disegnati:
    restano 40px utili oltre il padding occupancy, quindi verify_zero_overlap
    con gutter 24px passa STRUTTURALMENTE (40 >= 24). Il gutter centrale non
    e' mai un abisso vuoto e l'overlap e' impossibile per costruzione.
    Y invariate dallo statico. Mai solleva; larghezza minima garantita.
    """
    import math as _math
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        preset = "layout_center_standard"
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        ch = int(canvas_h) if canvas_h else VIDEO_HEIGHT
    except (TypeError, ValueError):
        ch = VIDEO_HEIGHT
    base = PRESET_SAFE_AREA.get(preset, PRESET_SAFE_AREA["layout_center_standard"])
    if cw != VIDEO_WIDTH or ch != VIDEO_HEIGHT:
        sx, sy = cw / VIDEO_WIDTH, ch / VIDEO_HEIGHT
        base = (int(round(base[0] * sx)), int(round(base[1] * sy)),
                int(round(base[2] * sx)), int(round(base[3] * sy)))
    if preset not in ("layout_split_left", "layout_split_right"):
        return base
    try:
        _, gap, _, min_tw = _split_thresholds(cw)
    except Exception:
        gap, min_tw = 40, 200
    try:
        side = int(OCCUPANCY_SIDE_PX)
    except Exception:
        side = 24
    try:
        cx0, cx1 = float(char_x0), float(char_x1)
    except (TypeError, ValueError):
        return base
    total = float(side) + float(gap)  # 64px su 1080: padding + gap utile
    if preset == "layout_split_right":
        # Testo a SX: [margine_sx, ..., floor(occ_x0 - gap)] (floor: mai overlap).
        x0 = int(base[0])
        x1 = int(_math.floor(cx0 - total))
        max_x1 = int(round(cw - float(gap)))
        x1 = min(x1, max_x1)
        if x1 < x0 + min_tw:
            x1 = x0 + min_tw
            if x1 > cw - gap:
                x1 = cw - gap
        return (int(x0), int(base[1]), int(x1), int(base[3]))
    # split_left, testo a DX: [ceil(occ_x1 + gap), ..., margine_dx].
    x1 = int(base[2])
    x0 = int(_math.ceil(cx1 + total))
    min_x0 = int(round(float(gap)))
    x0 = max(x0, min_x0)
    if x1 < x0 + min_tw:
        x0 = max(min_x0, x1 - min_tw)
    return (int(x0), int(base[1]), int(x1), int(base[3]))


def preset_safe_area_dynamic(name: str, canvas_w: int = VIDEO_WIDTH,
                             canvas_h: int = VIDEO_HEIGHT,
                             pose: int | None = None,
                             punch_in: bool = False) -> tuple[int, int, int, int]:
    """Safe area testo con bordo dinamico sul personaggio reale (mai solleva).

    Per gli split calcola la geometria fittata del personaggio (stessa usata
    dal renderer) e deriva il box testo fino a 40px prima del suo bbox, con
    Y identiche allo statico. Center invariati. Fallback: preset_safe_area().
    """
    try:
        preset = normalize_preset(name)
    except Exception:
        return preset_safe_area(name, canvas_w, canvas_h)
    if preset not in ("layout_split_left", "layout_split_right"):
        return preset_safe_area(preset, canvas_w, canvas_h)
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        chh = int(canvas_h) if canvas_h else VIDEO_HEIGHT
    except (TypeError, ValueError):
        chh = VIDEO_HEIGHT
    try:
        pct = float(preset_width_pct(preset, bool(punch_in)))
    except Exception:
        pct = 1.15
    try:
        _ref = float(MEASURED_SRC_SIZE[0]) or 768.0
    except Exception:
        _ref = 768.0
    try:
        bx0, _, bx1, _ = pose_visible_bbox(pose)
        nat_bx0 = float(bx0)
        nat_vw = float(bx1 - bx0)
        base_scale = float(cw * pct) / _ref
    except Exception:
        return preset_safe_area(preset, cw, chh)
    try:
        geo = resolve_split_geometry(preset, _ref, nat_bx0, nat_vw,
                                     base_scale, cw)
        return dynamic_split_text_area(preset, geo["vis_x0"], geo["vis_x1"],
                                       cw, chh)
    except Exception:
        return preset_safe_area(preset, cw, chh)


def preset_paste_x(preset_name: str, new_w: int, canvas_w: int = VIDEO_WIDTH) -> int:
    """Coordinata X FIT-TO-HALF v7 (ancoraggio colonna + hard clamp, mai tagliato).

    - split_left:  bbox visibile centrata sul 25% canvas (X≈270 su 1080)
    - split_right: bbox visibile centrata sul 75% canvas (X≈810 su 1080)
    - center/*:    centrato ((canvas_w - new_w) // 2).
    Formula pura (zero magic numbers):
      paste = canvas_w * frac - (bx0 * k + vis_w * k / 2),
    poi hard clamp della bbox visibile dentro [20px, canvas-20px].
    Il ridimensionamento d'emergenza (visibile > 600px) e' compito del
    renderer via fitted_split_character_size(); qui la posizione e'
    comunque garantita dentro il canvas per qualsiasi larghezza fittabile.
    """
    preset = normalize_preset(preset_name)
    try:
        cw = int(canvas_w)
        nw = int(new_w)
    except (TypeError, ValueError):
        cw, nw = VIDEO_WIDTH, VIDEO_WIDTH
    if preset not in ("layout_split_left", "layout_split_right"):
        return (cw - nw) // 2
    try:
        sw0 = float(MEASURED_SRC_SIZE[0]) or 768.0
    except Exception:
        sw0 = 768.0
    try:
        k = float(nw) / sw0 if sw0 else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        k = 1.0
    try:
        gb = MEASURED_TRIM_BBOX
        nat_bx0, nat_vw = float(gb[0]), float(gb[2] - gb[0])
    except Exception:
        nat_bx0, nat_vw = 0.0, float(nw) / k if k else float(nw)
    try:
        base = column_anchor_paste_x(preset, nat_bx0, nat_vw, k, cw)
        return int(clamp_paste_visible_inside(base, nat_bx0 * k, nat_vw * k, cw))
    except Exception:
        pass
    # Ultimo fallback: centrato sulla colonna + clamp full-width (mai assoluto).
    try:
        frac = float(split_column_frac(preset))
        fb = int(round(float(cw) * frac - float(nw) / 2.0))
        return int(clamp_paste_visible_inside(fb, 0.0, float(nw), cw))
    except Exception:
        return (cw - nw) // 2


def out_cubic_01(progress: float) -> float:
    """Easing `out_cubic` puro 0..1 per slide X (spec §3: 0.3s, mai fade).

    1-(1-t)^3: partenza veloce, arrivo morbido. Clampato, mai solleva.
    """
    try:
        t = float(progress)
    except (TypeError, ValueError):
        return 1.0
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 1.0 - pow(1.0 - t, 3)


def interpolate_x_out_cubic(x_from: int, x_to: int, progress: float) -> int:
    """Posizione X interpolata con `out_cubic` (slide split_left<->split_right)."""
    try:
        eased = out_cubic_01(progress)
        return int(round(float(x_from) + (float(x_to) - float(x_from)) * eased))
    except (TypeError, ValueError):
        return int(x_to)


def preset_width_pct(name: str, punch_in: bool = False) -> float:
    """Percentuale larghezza schermo REELS-FIX v6 (mai solleva).

    Split 115% (~1242px: visibile ~515-540px = meta' schermo, volto integro),
    center 132% (~1425px), punch_in 150% con PUNCH_IN_FACTOR 1.15x
    (max 1.55). Se il 115% risultasse ancora largo per una posa, il chiamante
    puo' scendere fino a 110% (1110%: visibile ~500px, ancora pieno e vivo).
    """
    preset = normalize_preset(name)
    pct = PRESET_WIDTH_PCT.get(preset, 1.32)
    if punch_in and preset != "layout_center_punch_in":
        pct *= PUNCH_IN_FACTOR
    try:
        pct_f = float(pct)
    except (TypeError, ValueError):
        return 1.15 if "split" in preset else 1.32
    if preset == "layout_center_punch_in" or punch_in:
        return min(1.55, max(PERFECT_CROP_SCALE_MIN, pct_f))
    if "split" in preset:
        # Split: 110-118% (target 115%, volto integro + gutter garantito).
        return min(1.18, max(1.10, pct_f))
    return min(PERFECT_CROP_SCALE_MAX, max(PERFECT_CROP_SCALE_MIN, pct_f))


def preset_headroom_px(name: str, canvas_h: int = VIDEO_HEIGHT) -> int:
    """Headroom (px) per il preset, scalato su canvas diversi da 1080x1920.

    ANTI-DECAPITAZIONE v4: ritorna sempre HEADROOM_TOP (200px su 1920).
    """
    preset = normalize_preset(name)
    base = PRESET_HEADROOM_PX.get(preset, HEADROOM_TOP)
    if canvas_h == VIDEO_HEIGHT:
        return int(base)
    return int(round(float(base) * float(canvas_h) / float(VIDEO_HEIGHT)))


def preset_overhang_x(canvas_w: int = VIDEO_WIDTH) -> int:
    """Overhang laterale degli split (px), scalato sulla larghezza canvas."""
    if canvas_w == VIDEO_WIDTH:
        return SPLIT_OVERHANG_X
    return int(round(SPLIT_OVERHANG_X * canvas_w / VIDEO_WIDTH))


def preset_safe_area(
    name: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int]:
    """Text Safe Area (x_min, y_min, x_max, y_max) per il preset.

    Le aree sono disegnate per 1080x1920; su canvas diversi vengono scalate
    proporzionalmente (i default di canvas coincidono con le costanti sopra).
    """
    box = PRESET_SAFE_AREA.get(
        normalize_preset(name), PRESET_SAFE_AREA["layout_center_standard"])
    if canvas_w == VIDEO_WIDTH and canvas_h == VIDEO_HEIGHT:
        return box
    sx, sy = canvas_w / VIDEO_WIDTH, canvas_h / VIDEO_HEIGHT
    return (
        int(round(box[0] * sx)), int(round(box[1] * sy)),
        int(round(box[2] * sx)), int(round(box[3] * sy)),
    )


def preset_font_scale(name: str) -> float:
    """Moltiplicatore dimensione font per il preset (1.0 default)."""
    try:
        return float(PRESET_FONT_SCALE.get(normalize_preset(name), 1.0))
    except (TypeError, ValueError):
        return 1.0


def preset_side(name: str) -> str:
    """Lato del personaggio: 'left' | 'right' | 'center'."""
    return PRESET_SIDE.get(normalize_preset(name), "center")


def preset_default_transition(name: str) -> str:
    """Transizione di ingresso naturale per il preset."""
    return PRESET_DEFAULT_TRANSITION_IN.get(normalize_preset(name), "fade")


def preset_needs_text_background(name: str) -> bool:
    """Vero se il testo va protetto con la pill ad alto contrasto."""
    return bool(PRESET_TEXT_BACKGROUND.get(normalize_preset(name), False))


def normalize_transition_in(value, preset_name: str = "layout_center_standard") -> str:
    """Normalizza una transizione al vocabolario del nuovo sistema.

    Accetta i nomi nuovi e quelli legacy v1 (slide_up/slide_side/fade/none):
    'slide_side' diventa slide_from_left/right in base al lato del preset.
    Valori ignoti/None -> default del preset.
    """
    preset = normalize_preset(preset_name)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in VALID_TRANSITION_IN:
            return "slide_up" if v == "slide_from_bottom" else v
        if v in LEGACY_TRANSITION_MAP:
            mapped = LEGACY_TRANSITION_MAP[v]
            if mapped is not None:
                return mapped
            # slide_side direzionale
            side = preset_side(preset)
            return "slide_from_left" if side == "left" else "slide_from_right"
    return preset_default_transition(preset)


def legacy_transition(transition_in: str) -> str:
    """Compatibilita' v1: transition_in canonica -> transizione legacy."""
    mapping = {
        "slide_from_left": "slide_side",
        "slide_from_right": "slide_side",
        "slide_up": "slide_up",
        "slide_from_bottom": "slide_up",
        "fade": "fade",
        "none": "none",
    }
    return mapping.get(transition_in, "fade")


def legacy_position(preset_name: str) -> str:
    """Compatibilita' v1: preset -> posizione legacy piu' vicina."""
    mapping = {
        "layout_split_left": "bottom_left",
        "layout_split_right": "bottom_right",
        "layout_center_standard": "bottom_center",
        "layout_center_punch_in": "bottom_center",
    }
    return mapping.get(normalize_preset(preset_name), "bottom_center")


def describe_preset(name: str) -> str:
    """Riga descrittiva del preset (per prompt LLM e logging)."""
    info = {
        "layout_center_standard": "mezza figura centrata in basso (132%, top Y~820), testo in ALTO Y[140,720]",
        "layout_center_punch_in": "PRIMO PIANO (150%, zoom 1.15x), testo fascia alta Y[140,620] con pill",
        "layout_split_left": "personaggio a SINISTRA (fit-to-half, bbox visibile dentro [20,1060], volto integro), testo a DESTRA X[665,1000] dinamico fino a 40px dal personaggio (posa 4: indica il testo; posa 2 MAI qui)",
        "layout_split_right": "personaggio a DESTRA (fit-to-half, bbox visibile dentro [20,1060], volto integro), testo a SINISTRA X[80,415] dinamico fino a 40px dal personaggio",
    }
    return info.get(normalize_preset(name), str(name))


# ---------------------------------------------------------------------------
# Dynamic Engine v2 — helper anti-statici (usati da character_selector).
# ---------------------------------------------------------------------------

def alternate_preset(preset_name: str, flip: int = 0) -> str:
    """Ritorna il preset alternato per ritmo visivo (split L<->R, centro->split).

    Deterministico su `flip` (indice chunk): ideale per rotazione ogni 3 chunk.
    """
    p = normalize_preset(preset_name)
    if p == "layout_split_left":
        return "layout_split_right"
    if p == "layout_split_right":
        return "layout_split_left"
    # Dal centro: alterna lati (mai punch_in qui: solo movimento laterale).
    return "layout_split_left" if flip % 2 == 0 else "layout_split_right"


def verify_perfect_crop(new_w: int, new_h: int, paste_x: int, paste_y: int,
                        canvas_w: int = VIDEO_WIDTH, canvas_h: int = VIDEO_HEIGHT,
                        preset_name: str | None = None,
                        punch_in: bool = False) -> dict:
    """Verifica invarianti REELS-FIX v7 mezzo-busto (mai solleva).

    - Scala: split 60-118% (base 110-118%, target 115%; sotto 110% solo per
      emergency autoscale FIT-TO-HALF su pose larghe: mai un warning falso
      quando il fit salva il personaggio dal taglio); con punch_in lo zoom
      intenzionale 1.15x sposta il cap a 155% come il preset punch_in.
      Center 110-140%, punch fino 155%.
    - paste_y: split/punch 0<=py<=300; center 700<=py<=950 (testa Y~1060,
      occupancy ~852, fascia testo Y1=720 libera con gutter).
    - Fondo fuori campo: paste_y + new_h >= canvas_h.
    """
    try:
        scale_pct = float(new_w) / float(canvas_w) if canvas_w else 0.0
        bottom = int(paste_y) + int(new_h)
        anchored = bottom >= (int(canvas_h) + 100)
        bottom_ok = bottom >= int(canvas_h)
        try:
            preset = normalize_preset(preset_name) if preset_name else None
        except Exception:
            preset = None
        if preset == "layout_center_standard":
            head_ok = 700 <= int(paste_y) <= 950
        else:
            head_ok = 0 <= int(paste_y) <= 300
        try:
            _punch = bool(punch_in)
        except Exception:
            _punch = False
        if preset in ("layout_split_left", "layout_split_right"):
            try:
                _floor = float(SPLIT_MIN_SCALE_ABS)
            except Exception:
                _floor = 0.60
            _cap = 1.55 if _punch else 1.18
            scale_ok = _floor <= scale_pct <= _cap
        elif preset == "layout_center_punch_in":
            scale_ok = 1.10 <= scale_pct <= 1.55
        else:
            scale_ok = (PERFECT_CROP_SCALE_MIN <= scale_pct <= PERFECT_CROP_SCALE_MAX) or \
                (1.45 <= scale_pct <= 1.55)
        ok = bool(scale_ok) and bool(bottom_ok) and bool(head_ok)
        return {"ok": bool(ok), "scale_pct": float(scale_pct), "anchored": bool(anchored),
                "head_ok": bool(head_ok), "bottom": int(bottom)}
    except Exception:
        return {"ok": False, "scale_pct": 0.0, "anchored": False, "head_ok": False}


# BBox alpha native misurate su asset reali 768x1376 (RGBA getbbox):
# pose strette ~333px (43%), posa 2 (braccia aperte) 676px (88%, doppia!).
# Usate per ancorare la PERSONA visibile invece dell'immagine intera
# (il padding trasparente spostava il volto di ~370px e tagliava meta' faccia).
POSE_VISIBLE_BBOX: dict[int, tuple[int, int, int, int]] = {
    1: (218, 82, 551, 1298),
    2: (46, 82, 722, 1298),
    3: (193, 82, 565, 1298),
    4: (211, 82, 569, 1298),
    5: (214, 84, 563, 1298),
}
# Stima generica (posa sconosciuta): bbox posa 1.
MEASURED_TRIM_BBOX: tuple[int, int, int, int] = (218, 82, 551, 1298)
MEASURED_SRC_SIZE: tuple[int, int] = (768, 1376)
# Centro faccia nativo (testa src x300-470/y130-340 -> cx 385, cy 235).
POSE_FACE_CENTER: dict[int, tuple[int, int]] = {
    1: (385, 235),
    2: (385, 235),
    3: (385, 235),
    4: (385, 235),
    5: (385, 235),
}
# Target di framing split: bordo visibile del corpo ammesso fuori canvas
# (spalla, estetica) + margine minimo garantito per la faccia.
# Crop 40: gap testo/persona >=40px su tutte le pose strette; faccia dentro.
SPLIT_VISIBLE_CROP_PX: int = 40
FACE_MARGIN_PX: int = 40


def pose_visible_bbox(pose: int | None) -> tuple[int, int, int, int]:
    """BBox nativa della persona visibile per posa (fallback: stima generica)."""
    try:
        hit = POSE_VISIBLE_BBOX.get(int(pose))
        if hit is not None and len(hit) == 4:
            return (int(hit[0]), int(hit[1]), int(hit[2]), int(hit[3]))
    except Exception:
        pass
    return MEASURED_TRIM_BBOX


def pose_paste_x(pose: int | None, preset_name: str, new_w: int,
                 canvas_w: int = VIDEO_WIDTH) -> int:
    """Paste X FIT-TO-HALF v7 per-posa (ancoraggio colonna + hard clamp).

    Ancoraggio geometrico (nessun hardcoded):
      target = 25% canvas (split_left, ≈270) | 75% canvas (split_right, ≈810)
      paste  = target - (bx0_nativo * k + vis_w_nativa * k / 2)
    dove la bbox visibile e' quella reale della posa (POSE_VISIBLE_BBOX),
    poi hard clamp dentro [margine, canvas-margine] (20px su 1080).

    - center/*: centrato classico.
    Il volto resta SEMPRE integro con margine FACE_MARGIN_PX (clamp finale);
    la bbox visibile (viso+busto) non esce MAI dal canvas. Il resize
    d'emergenza (visibile > 600px) e' compito del renderer via
    fitted_split_character_size(): qui la posizione e' comunque garantita
    dentro il canvas per qualsiasi larghezza fittabile.
    """
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        preset = "layout_center_standard"
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
        nw = int(new_w) if new_w else VIDEO_WIDTH
    except Exception:
        cw, nw = VIDEO_WIDTH, VIDEO_WIDTH
    if preset not in ("layout_split_left", "layout_split_right"):
        return (cw - nw) // 2
    try:
        sw0 = float(MEASURED_SRC_SIZE[0]) or 768.0
    except Exception:
        sw0 = 768.0
    try:
        kx = float(nw) / sw0 if sw0 else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        kx = 1.0
    try:
        bx0, _, bx1, _ = pose_visible_bbox(pose)
        nat_bx0, nat_vw = float(bx0), float(bx1 - bx0)
    except Exception:
        nat_bx0, nat_vw = 0.0, sw0
    try:
        base = column_anchor_paste_x(preset, nat_bx0, nat_vw, kx, cw)
        clamped = clamp_paste_visible_inside(base, nat_bx0 * kx, nat_vw * kx, cw)
        # Clamp di sicurezza volto: SEMPRE dentro con margine (mai fuori).
        try:
            m = int(FACE_MARGIN_PX)
        except Exception:
            m = 40
        try:
            est_h = int(round(float(1376) * float(nw) / 768.0))
            py_est = int(PRESET_HEADROOM_PX.get(preset, HEADROOM_TOP))
            fb = face_box_on_canvas(pose, int(clamped), int(py_est),
                                    int(nw), int(est_h))
            if fb is not None:
                if fb[0] < m:
                    clamped = int(clamped) + (int(m) - int(fb[0]))
                elif fb[2] > int(cw) - m:
                    clamped = int(clamped) - (int(fb[2]) - (int(cw) - int(m)))
                # Re-verifica bbox visibile dopo il nudge volto (mai fuori).
                _vx0 = float(clamped) + nat_bx0 * kx
                _vx1 = _vx0 + nat_vw * kx
                try:
                    _mg, _, _, _ = _split_thresholds(cw)
                except Exception:
                    _mg = 20
                if _vx1 > float(cw) - float(_mg) or _vx0 < float(_mg):
                    clamped = clamp_paste_visible_inside(
                        int(clamped), nat_bx0 * kx, nat_vw * kx, cw)
        except Exception:
            pass
        return int(clamped)
    except Exception:
        pass
    try:
        frac = float(split_column_frac(preset))
        fb = int(round(float(cw) * frac - float(nw) / 2.0))
        return int(clamp_paste_visible_inside(fb, 0.0, float(nw), cw))
    except Exception:
        return (cw - nw) // 2


def character_occupancy_box(preset_name: str, punch_in: bool = False,
                            char_w: int | None = None, char_h: int | None = None,
                            canvas_w: int = VIDEO_WIDTH,
                            canvas_h: int = VIDEO_HEIGHT,
                            trim_bbox: tuple[int, int, int, int] | None = None,
                            pose: int | None = None
                            ) -> tuple[int, int, int, int]:
    """AABB occupazione reale (mai solleva, per-posa).

    paste (pose-aware: pose_paste_x su split) + dimensioni scalate + bbox
    visibile della posa (o trim esplicito) + fascia +120/-60px.
    """
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        preset = "layout_center_standard"
    try:
        cw = int(canvas_w) if canvas_w else VIDEO_WIDTH
    except Exception:
        cw = VIDEO_WIDTH
    try:
        ch = int(canvas_h) if canvas_h else VIDEO_HEIGHT
    except Exception:
        ch = VIDEO_HEIGHT
    # Dimensioni stimate se non fornite (da width_pct + aspect 768x1376).
    # v7 FIT-TO-HALF: negli split la stima applica l'emergency autoscale
    # (stessa del renderer) cosi' occupancy e render non divergono mai.
    try:
        pct = float(preset_width_pct(preset, bool(punch_in)))
    except Exception:
        pct = 1.15 if "split" in preset else 1.32
    if char_w is None or char_h is None or char_w <= 0 or char_h <= 0:
        est_w = int(round(cw * pct))
        est_h = int(round(est_w * 1376.0 / 768.0))
        if preset in ("layout_split_left", "layout_split_right"):
            try:
                fw, fh, _ = fitted_split_character_size(
                    preset, 768, 1376, cw, pct, pose)
                est_w, est_h = int(fw), int(fh)
            except Exception:
                pass
    else:
        try:
            est_w, est_h = int(char_w), int(char_h)
        except Exception:
            est_w = int(round(cw * pct))
            est_h = int(round(est_w * 1376.0 / 768.0))
    try:
        if pose is not None and preset in ("layout_split_left", "layout_split_right"):
            px = int(pose_paste_x(pose, preset, est_w, cw))
        else:
            px = int(preset_paste_x(preset, est_w, cw))
    except Exception:
        px = (cw - est_w) // 2
    try:
        py = int(character_anchor_y(ch, preset))
    except Exception:
        py = int(HEADROOM_TOP)
    # Bbox visibile: trim esplicito > bbox della posa > stima generica.
    dx0, dy0, dx1, dy1 = 0, 0, est_w, est_h
    try:
        if trim_bbox is not None and len(trim_bbox) == 4:
            dx0, dy0, dx1, dy1 = (int(trim_bbox[0]), int(trim_bbox[1]),
                                  int(trim_bbox[2]), int(trim_bbox[3]))
            if not (0 <= dx0 < dx1 <= est_w + 2 and 0 <= dy0 < dy1 <= est_h + 2):
                raise ValueError("trim fuori range")
        else:
            try:
                _sw, _sh = float(MEASURED_SRC_SIZE[0]), float(MEASURED_SRC_SIZE[1])
                _kx = float(est_w) / _sw if _sw else 1.0
                _ky = float(est_h) / float(MEASURED_SRC_SIZE[1]) if float(MEASURED_SRC_SIZE[1]) else _kx
                _pb = pose_visible_bbox(pose)
                dx0 = int(round(float(_pb[0]) * _kx))
                dy0 = int(round(float(_pb[1]) * _ky))
                dx1 = int(round(float(_pb[2]) * _kx))
                dy1 = int(round(float(_pb[3]) * _ky))
            except Exception:
                dx0, dy0, dx1, dy1 = 0, 0, est_w, est_h
    except Exception:
        dx0, dy0, dx1, dy1 = 0, 0, est_w, est_h
    try:
        sx = int(OCCUPANCY_SIDE_PX)
    except Exception:
        sx = 60
    try:
        hy = int(OCCUPANCY_HEADROOM_PX)
    except Exception:
        hy = 120
    x0 = px + dx0 - sx
    y0 = py + dy0 - hy
    x1 = px + dx1 + sx
    y1 = py + dy1 + sx
    return (int(x0), int(y0), int(x1), int(y1))


def boxes_overlap(a: tuple, b: tuple, gutter: int = 0) -> bool:
    """Vero se due AABB (x0,y0,x1,y1) si intersecano (con gutter, mai solleva)."""
    try:
        ax0, ay0, ax1, ay1 = (int(a[0]), int(a[1]), int(a[2]), int(a[3]))
        bx0, by0, bx1, by1 = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        g = int(gutter or 0)
        overlap_x = not (ax1 <= bx0 - g or ax0 >= bx1 + g)
        overlap_y = not (ay1 <= by0 - g or ay0 >= by1 + g)
        return bool(overlap_x and overlap_y)
    except Exception:
        return False


def verify_zero_overlap(text_bbox, character_occupancy, gutter: int = 24) -> None:
    """Invariante geometrica obbligatoria: IoU testo/personaggio == 0.

    Solleva AssertionError con dettaglio se overlap su entrambi gli assi
    (con gutter 24px). Usata da renderer/video_builder prima del render.
    """
    try:
        if boxes_overlap(text_bbox, character_occupancy, gutter):
            raise AssertionError(
                f"CRITICAL: Text overlap detected! Text: {text_bbox}, "
                f"Char: {character_occupancy}, gutter={gutter}")
    except AssertionError:
        raise
    except Exception:
        return None


def text_box_overlaps_character(text_box: tuple, preset_name: str,
                                canvas_w: int = VIDEO_WIDTH,
                                canvas_h: int = VIDEO_HEIGHT,
                                punch_in: bool = False,
                                char_size: tuple[int, int] | None = None,
                                pose: int | None = None) -> bool:
    """Test AABB reale testo vs occupancy per-posa (mai solleva).

    NESSUN return False preventivo: split inclusi. Ritorna True se
    text_box interseca character_occupancy_box con gutter 0px.
    """
    try:
        x0, y0, x1, y1 = (int(text_box[0]), int(text_box[1]),
                           int(text_box[2]), int(text_box[3]))
        if x1 <= x0 or y1 <= y0:
            return False
        preset = normalize_preset(preset_name)
        cw = None
        chh = None
        try:
            if char_size is not None and len(char_size) == 2:
                cw, chh = int(char_size[0]), int(char_size[1])
        except Exception:
            cw, chh = None, None
        occ = character_occupancy_box(preset, punch_in, cw, chh,
                                      canvas_w, canvas_h, None, pose)
        return bool(boxes_overlap((x0, y0, x1, y1), occ, 0))
    except Exception:
        return False


def face_box_on_canvas(pose: int | None, paste_x: int, paste_y: int,
                       new_w: int, new_h: int) -> tuple[int, int, int, int] | None:
    """BBox della faccia su canvas (margine testa ~85px nativi per lato).

    Usata per garantire: faccia SEMPRE dentro il canvas (il corpo puo'
    uscire fino a SPLIT_VISIBLE_CROP_PX). Ritorna None se non calcolabile.
    """
    try:
        fx, fy = POSE_FACE_CENTER.get(int(pose), (385, 235))
    except Exception:
        fx, fy = (385, 235)
    try:
        _sw0 = float(MEASURED_SRC_SIZE[0]) or 768.0
        _sh0 = float(MEASURED_SRC_SIZE[1]) or 1376.0
        kx = float(new_w) / _sw0
        ky = float(new_h) / _sh0
        cx = float(paste_x) + float(fx) * kx
        cy = float(paste_y) + float(fy) * ky
        hw = 85.0 * kx
        hh = 105.0 * ky
        return (int(round(cx - hw)), int(round(cy - hh)),
                int(round(cx + hw)), int(round(cy + hh)))
    except Exception:
        return None


def verify_face_visible(pose: int | None, paste_x: int, paste_y: int,
                        new_w: int, new_h: int,
                        canvas_w: int = VIDEO_WIDTH,
                        canvas_h: int = VIDEO_HEIGHT,
                        margin: int = FACE_MARGIN_PX) -> None:
    """Invariante: faccia dentro il canvas con margine (default 40px).

    Solleva AssertionError se un bordo faccia esce oltre il margine.
    Il corpo puo' uscire (estetica); la faccia MAI.
    """
    try:
        fb = face_box_on_canvas(pose, paste_x, paste_y, new_w, new_h)
        if fb is None:
            return None
        m = int(margin)
        if fb[0] < m or fb[1] < m or fb[2] > int(canvas_w) - m or fb[3] > int(canvas_h) - m:
            raise AssertionError(
                f"CRITICAL: face outside canvas! Face: {fb}, "
                f"canvas=({canvas_w}x{canvas_h}), margin={m}")
    except AssertionError:
        raise
    except Exception:
        return None


def fallback_preset_for_overflow(preset_name: str, text_len_chars: int = 0,
                                 n_words: int = 0) -> str:
    """Catena fallback: Shrink -> Center->Split -> Shift Y (mai solleva).

    Se il testo e' denso (>40 char o >6 parole) e il preset e' center,
    ritorna split alternato; altrimenti ritorna il preset normalizzato.
    Lo shrink font e lo shift Y sono applicati dal renderer/auto-fit.
    """
    try:
        preset = normalize_preset(preset_name)
    except Exception:
        return "layout_center_standard"
    try:
        dense = int(text_len_chars or 0) > 40 or int(n_words or 0) > 6
    except Exception:
        dense = False
    if dense and preset in ("layout_center_standard", "layout_center_punch_in"):
        # Alterna per non impilare sempre dallo stesso lato (hash stabile).
        try:
            flip = (int(text_len_chars or 0) + int(n_words or 0)) % 2
        except Exception:
            flip = 0
        return "layout_split_left" if flip == 0 else "layout_split_right"
    return preset
