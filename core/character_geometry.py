"""
Geometria del soggetto 2D: misura, scala vincolata, posizionamento e clamp.

Questo modulo risolve il taglio dei personaggi ai bordi del frame (soggetto
piu' largo del canvas, asse visivo fuori campo). Interventi mirati e
retrocompatibili: nessuna dipendenza nuova (Pillow + numpy opzionale), nessuna
chiamata LLM aggiuntiva, nessun I/O nel loop frame (la geometria e' calcolata
una sola volta per asset e cachata in RAM).

Contenuti:
- `SubjectGeometry` / `get_subject_geometry`: subject_bbox del contenuto
  visibile dopo rimozione sfondo, aspect, visual_center_x (baricentro del
  torso/gambe, non delle braccia tese) e face_box approssimata. Cache in RAM
  con chiave path + mtime.
- `constrained_scale_abs`: scala = min(scala da altezza, vincolo larghezza).
  Il vincolo `CHARACTER_MAX_WIDTH_RATIO * VIDEO_WIDTH` vince sempre.
- `safe_zone_for_layout` / `compute_subject_placement`: il centro visivo
  (visual_center_x scalato) viene piazzato nella safe zone del layout, con
  piedi del soggetto al bordo inferiore e testa mai tagliata.
- `clamp_subject_to_frame`: clamp universale (stato stabile dentro il frame
  con margine, faccia mai tagliata, visible_ratio >= soglia; in transizione
  il fuori-campo e' ammesso solo a meta' animazione, mai al keyframe finale).
- `validate_pose_layout_pair`: accoppiamento posa<->layout (pose larghe solo
  al centro, pose che indicano/pensano solo laterali), con log "layout corretto".
- `adjust_for_text_overlap`: il testo ha priorita' (soglia 25% dell'area testo).
- `save_debug_png`: diagnostica per CHARACTER_DEBUG=1.
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter

from config import (
    CHARACTER_FACE_MIN_VISIBLE,
    CHARACTER_MAX_WIDTH_RATIO,
    CHARACTER_MIN_VISIBLE_RATIO,
    CHARACTER_SAFE_MARGIN_PX,
    CHARACTER_SCALE_MAX,
    CHARACTER_SCALE_MIN,
    TEMP_DIR,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from core.layout_presets import (
    PUNCH_IN_FACTOR,
    VALID_LAYOUT_PRESETS,
    pose_visible_bbox,
    preset_width_pct,
)


# Soglia alpha per "pixel visibile" (dopo `_remove_black_background`).
_ALPHA_THRESHOLD = 12

# Minimo di sanita' scala: sotto `0.35 * VIDEO_HEIGHT` di altezza soggetto
# si cambia layout a bottom_center invece di rimpicciolire ancora.
_MIN_SANITY_HEIGHT_RATIO = 0.35

# Soglia overlap testo/soggetto (frazione dell'area testo coperta).
_TEXT_OVERLAP_THRESHOLD = 0.25

# Passo di riduzione scala nel ribilanciamento col testo.
_TEXT_SHRINK_STEP = 0.87


class CharacterGeometryError(Exception):
    """Errore interno di geometria (mai propagato ai render: c'e' il fallback)."""


@dataclass
class SubjectGeometry:
    """Misura del soggetto visibile di un asset (una sola volta, poi cache)."""

    pose: int
    path: str
    mtime: float
    # subject_bbox nativa (x0, y0, x1, y1) del contenuto visibile.
    bbox: tuple[float, float, float, float]
    # Dimensioni native del soggetto.
    w: float
    h: float
    # Aspect ratio w/h del soggetto.
    aspect: float
    # Baricentro orizzontale del corpo (mediana colonne del 60% inferiore).
    visual_center_x: float
    # Face box approssimata nativa (primi ~22% di altezza, su visual_center_x).
    face_box: tuple[float, float, float, float]
    # Dimensioni dell'immagine intera (con padding trasparente).
    src_size: tuple[int, int]
    # Note diagnostiche (es. "fallback bbox hardcoded").
    notes: list[str] = field(default_factory=list)


# Cache geometrie: {pose: SubjectGeometry} + chiave di validita' path+mtime.
_geometry_cache: dict[int, SubjectGeometry] = {}


def _default_geometry(pose: int, note: str = "") -> SubjectGeometry:
    """Geometria di ripiego dalle bbox misurate hardcoded (mai solleva)."""
    try:
        bx0, by0, bx1, by1 = pose_visible_bbox(pose)
    except Exception:
        bx0, by0, bx1, by1 = (218, 82, 551, 1298)
    try:
        sw, sh = float(bx1 - bx0), float(by1 - by0)
    except Exception:
        sw, sh = (333.0, 1216.0)
    if sw <= 0:
        sw = 333.0
    if sh <= 0:
        sh = 1216.0
    vcx = float(bx0 + bx1) / 2.0
    face = _face_box_for(bx0, by0, bx1, by1, vcx)
    notes = [note] if note else []
    return SubjectGeometry(
        pose=int(pose) if isinstance(pose, int) else 1,
        path="",
        mtime=0.0,
        bbox=(float(bx0), float(by0), float(bx1), float(by1)),
        w=sw,
        h=sh,
        aspect=float(sw) / float(sh),
        visual_center_x=float(vcx),
        face_box=face,
        src_size=(768, 1376),
        notes=notes,
    )


def _face_box_for(
    bx0: float, by0: float, bx1: float, by1: float, vcx: float
) -> tuple[float, float, float, float]:
    """Face box approssimata: primi ~22% di altezza, centrata su vcx."""
    try:
        sw, sh = float(bx1 - bx0), float(by1 - by0)
        fw = min(190.0, max(140.0, 0.5 * sw))
        fh = 0.22 * sh
        cx = min(float(bx1) - fw / 2.0, max(float(bx0) + fw / 2.0, float(vcx)))
        return (cx - fw / 2.0, float(by0), cx + fw / 2.0, float(by0) + fh)
    except Exception:
        return (float(bx0), float(by0), float(bx1), float(by0) + 200.0)


def measure_subject_from_image(
    img_rgba: Image.Image, pose: int = 1, path: str = "", mtime: float = 0.0
) -> SubjectGeometry:
    """Misura il soggetto da un'immagine RGBA gia' pulita (sfondo rimosso).

    Usa il canale alpha come maschera (con chiusura morfologica 3x3 per
    pulire i bordi tratteggiati); il visual_center_x e' la mediana delle
    colonne occupate nel 60% inferiore (torso/gambe, non braccia tese).
    Usa numpy se disponibile, altrimenti Pillow puro (fallback: centro bbox).
    """
    try:
        src_w, src_h = int(img_rgba.size[0]), int(img_rgba.size[1])
    except Exception:
        return _default_geometry(pose, "immagine non leggibile: fallback hardcoded")
    try:
        if img_rgba.mode != "RGBA":
            img_rgba = img_rgba.convert("RGBA")
        alpha = img_rgba.split()[3]
        mask = alpha.point(lambda a: 255 if a > _ALPHA_THRESHOLD else 0)
        # Chiusura morfologica: riempie micro-buchi e regolarizza i bordi.
        try:
            mask = mask.filter(ImageFilter.MaxFilter(3)).filter(
                ImageFilter.MinFilter(3)
            )
        except Exception:
            pass
        bbox = mask.getbbox()
        if bbox is None:
            return _default_geometry(pose, "maschera vuota: fallback hardcoded")
        bx0, by0, bx1, by1 = (float(bbox[0]), float(bbox[1]),
                              float(bbox[2]), float(bbox[3]))
        sw, sh = bx1 - bx0, by1 - by0
        if sw <= 4 or sh <= 4:
            return _default_geometry(pose, "bbox degenere: fallback hardcoded")
        vcx = (bx0 + bx1) / 2.0
        try:
            import numpy as np  # type: ignore

            arr = np.array(mask) > 0
            yl0 = int(by0 + 0.4 * sh)
            yl1 = int(by1)
            if yl1 > yl0 and arr.shape[0] >= yl1:
                band = arr[yl0:yl1, int(bx0):int(bx1)]
                col_counts = band.sum(axis=0)
                need = max(2, int(0.03 * (yl1 - yl0)))
                occupied = [
                    int(bx0) + i
                    for i, c in enumerate(col_counts)
                    if int(c) >= need
                ]
                if len(occupied) >= 3:
                    vcx = float(statistics.median(occupied))
        except ImportError:
            pass  # senza numpy: centro bbox (approssimazione documentata)
        face = _face_box_for(bx0, by0, bx1, by1, vcx)
        return SubjectGeometry(
            pose=int(pose),
            path=str(path),
            mtime=float(mtime or 0.0),
            bbox=(bx0, by0, bx1, by1),
            w=float(sw),
            h=float(sh),
            aspect=float(sw) / float(sh),
            visual_center_x=float(vcx),
            face_box=face,
            src_size=(int(src_w), int(src_h)),
            notes=[],
        )
    except Exception as e:
        print(f"[character_geometry] warning: misura posa {pose} fallita ({e}), "
              f"uso fallback hardcoded")
        return _default_geometry(pose, f"misura fallita ({e}): fallback hardcoded")


def get_subject_geometry(pose_number: int) -> SubjectGeometry:
    """Ritorna la geometria cachata della posa (calcolata una sola volta).

    Chiave di cache: path asset + mtime (se il file cambia, si rimisura).
    Non solleva mai: in caso di errore ritorna il fallback hardcoded.
    """
    try:
        pose = int(pose_number)
    except (TypeError, ValueError):
        return _default_geometry(1, "posa non valida: fallback posa 1")
    try:
        from core.character_selector import (  # lazy: evita import circolare
            clear_character_cache,
            load_character_original,
            resolve_character_path,
        )

        path = resolve_character_path(pose)
        if path is None:
            cached = _geometry_cache.get(pose)
            if cached is not None:
                return cached
            print(f"[character_geometry] warning: asset posa {pose} mancante, "
                  f"uso bbox hardcoded")
            geo = _default_geometry(pose, "asset mancante: bbox hardcoded")
            _geometry_cache[pose] = geo
            return geo
        try:
            mtime = float(os.path.getmtime(path))
        except OSError:
            mtime = 0.0
        cached = _geometry_cache.get(pose)
        if cached is not None and cached.path == str(path) and cached.mtime == mtime:
            return cached
        if cached is not None and cached.mtime != mtime:
            # Asset cambiato su disco: invalida anche la cache immagini.
            try:
                clear_character_cache()
            except Exception:
                pass
        img = load_character_original(pose)
        geo = measure_subject_from_image(img, pose, str(path), mtime)
        _geometry_cache[pose] = geo
        return geo
    except Exception as e:
        print(f"[character_geometry] warning: geometria posa {pose} in fallback ({e})")
        cached = _geometry_cache.get(pose)
        if cached is not None:
            return cached
        geo = _default_geometry(pose, f"eccezione ({e}): bbox hardcoded")
        _geometry_cache[pose] = geo
        return geo


def clear_geometry_cache() -> None:
    """Svuota la cache delle geometrie (utile nei test)."""
    _geometry_cache.clear()


# ------------------------------------------------------------ Safe zone
# Ogni layout definisce una SAFE ZONE orizzontale (frazioni di VIDEO_WIDTH)
# dove deve stare il CENTRO VISIVO del soggetto (non l'angolo immagine).

SAFE_ZONES: dict[str, tuple[float, float, float]] = {
    # nome -> (min, max, default) come frazioni di larghezza canvas.
    "bottom_center": (0.50, 0.50, 0.50),
    "bottom_left": (0.30, 0.42, 0.36),
    "bottom_right": (0.58, 0.70, 0.64),
    "side_left": (0.18, 0.32, 0.25),
    "side_right": (0.68, 0.82, 0.75),
    "layout_center_standard": (0.50, 0.50, 0.50),
    "layout_center_punch_in": (0.50, 0.50, 0.50),
    "layout_split_left": (0.18, 0.32, 0.25),
    "layout_split_right": (0.68, 0.82, 0.75),
}

# Famiglie di direzione (per "layout ammesso piu' vicino").
_LAYOUT_FAMILY: dict[str, str] = {
    "bottom_center": "center",
    "layout_center_standard": "center",
    "layout_center_punch_in": "center",
    "bottom_left": "left",
    "side_left": "left",
    "layout_split_left": "left",
    "bottom_right": "right",
    "side_right": "right",
    "layout_split_right": "right",
}

# Rappresentante canonico per famiglia e per vocabolario (preset vs legacy).
_FAMILY_PRESET: dict[str, str] = {
    "center": "layout_center_standard",
    "left": "layout_split_left",
    "right": "layout_split_right",
}
_FAMILY_LEGACY: dict[str, str] = {
    "center": "bottom_center",
    "left": "bottom_left",
    "right": "bottom_right",
}


def safe_zone_for_layout(layout: str) -> tuple[float, float, float]:
    """Safe zone (min, max, default) come frazioni di larghezza (mai solleva)."""
    try:
        hit = SAFE_ZONES.get(str(layout))
        if hit is not None and len(hit) == 3:
            return (float(hit[0]), float(hit[1]), float(hit[2]))
    except Exception:
        pass
    return (0.50, 0.50, 0.50)


def layout_family(layout: str) -> str:
    """Famiglia di direzione: 'left' | 'right' | 'center' (mai solleva)."""
    try:
        return _LAYOUT_FAMILY.get(str(layout), "center")
    except Exception:
        return "center"


def is_preset_layout(layout: str) -> bool:
    """Vero se e' un preset del sistema a zone (altrimenti e' legacy v1)."""
    try:
        return str(layout) in VALID_LAYOUT_PRESETS
    except Exception:
        return False


# ------------------------------------------------------------ Scala vincolata (FASE 2)


def constrained_scale_abs(
    subject_w: float,
    subject_h: float,
    src_full_w: float,
    layout: str,
    punch: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
    scale_hint: float = 0.75,
) -> tuple[float, float, bool]:
    """Scala assoluta (riferita all'immagine intera) con vincolo di larghezza.

    Ritorna (scala, punch_effettivo, cappato): la scala e' il minimo tra la
    scala base (preset width-based, oppure altezza target per i legacy) e i
    vincoli di altezza/larghezza; il vincolo di larghezza vince sempre, per le
    pose molto larghe la scala scende automaticamente.
    """
    try:
        sw = float(subject_w)
        sh = float(subject_h)
        fw = float(src_full_w)
        cw = int(canvas_w) or VIDEO_WIDTH
        ch = int(canvas_h) or VIDEO_HEIGHT
    except (TypeError, ValueError):
        return (1.0, 1.0, False)
    if sw <= 0 or sh <= 0 or fw <= 0:
        return (1.0, 1.0, False)
    try:
        ratio = float(CHARACTER_MAX_WIDTH_RATIO)
    except Exception:
        ratio = 0.62
    try:
        smin = float(CHARACTER_SCALE_MIN)
        smax = float(CHARACTER_SCALE_MAX)
    except Exception:
        smin, smax = (0.65, 0.90)
    if is_preset_layout(layout):
        try:
            pct = float(preset_width_pct(str(layout), False))
        except Exception:
            pct = 1.25
        k0 = float(cw) * pct / fw
    else:
        try:
            hint = min(smax, max(smin, float(scale_hint)))
        except (TypeError, ValueError):
            hint = 0.75
        # Legacy v1: altezza target riferita al SOGGETTO (non all'immagine).
        try:
            from config import VIDEO_HEIGHT as _VH

            ref_h = float(_VH)
        except Exception:
            ref_h = 1920.0
        k0 = float(hint) * ref_h / sh
    try:
        punch_factor = float(PUNCH_IN_FACTOR) if bool(punch) else 1.0
    except Exception:
        punch_factor = 1.0
    try:
        if str(layout) == "layout_center_punch_in":
            punch_factor = 1.0  # scala gia' ravvicinata nel preset
    except Exception:
        pass
    k_req = k0 * punch_factor
    try:
        margin = int(CHARACTER_SAFE_MARGIN_PX)
    except Exception:
        margin = 40
    # Vincoli: soggetto mai piu' alto di SCALE_MAX*H, mai piu' largo di
    # RATIO*W, testa mai sopra il margine con piedi al bordo inferiore.
    k_h = (smax * float(ch)) / sh
    k_w = (ratio * float(cw)) / sw
    k_fit_h = (float(ch) - float(margin)) / sh
    k = min(k_req, k_h, k_w, k_fit_h)
    # Center standard: la testa resta SOTTO la fascia testo del preset
    # (testo alto Y[140,490], corpo sotto con gutter 24: separazione v8).
    # Il punch-in e' sovrimpressione intenzionale con pill: nessun tetto testo.
    # Gli split separano in orizzontale (area dinamica): nessun tetto testo.
    try:
        _lay_n = str(layout)
        if _lay_n in ("layout_center_standard", "bottom_center"):
            from core.layout_presets import PRESET_SAFE_AREA as _AREAS

            _tb = _AREAS.get("layout_center_standard",
                             (90, 140, 990, 490))[3]
            # Scala aree su canvas diversi da 1080x1920.
            try:
                _tb = float(_tb) * float(ch) / 1920.0
            except Exception:
                pass
            k_text = (float(ch) - float(_tb) - 24.0) / sh
            if k_text < k:
                k = k_text
    except Exception:
        pass
    if k <= 0:
        k = min(k_h, k_w)
    capped = k < k_req - 1e-9
    punch_eff = (k / k0) if k0 > 0 else 1.0
    return (float(k), float(punch_eff), bool(capped))


# ------------------------------------------------------------ Clamp universale (FASE 4)


def rect_visible_ratio(
    rect: tuple[float, float, float, float],
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> float:
    """Frazione dell'area del rettangolo (x, y, w, h) visibile nel frame."""
    try:
        x, y, w, h = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        cw, ch = float(canvas_w), float(canvas_h)
        if w <= 0 or h <= 0 or cw <= 0 or ch <= 0:
            return 0.0
        ix0, iy0 = max(0.0, x), max(0.0, y)
        ix1, iy1 = min(cw, x + w), min(ch, y + h)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        return max(0.0, min(1.0, inter / (w * h)))
    except Exception:
        return 0.0


def rects_overlap_fraction(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
) -> float:
    """Frazione dell'area di B coperta da A (0..1, mai solleva)."""
    try:
        ax, ay, aw, ah = (float(rect_a[0]), float(rect_a[1]),
                          float(rect_a[2]), float(rect_a[3]))
        bx, by, bw, bh = (float(rect_b[0]), float(rect_b[1]),
                          float(rect_b[2]), float(rect_b[3]))
        if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
            return 0.0
        ix0, iy0 = max(ax, bx), max(ay, by)
        ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        return max(0.0, min(1.0, inter / (bw * bh)))
    except Exception:
        return 0.0


def clamp_subject_to_frame(
    x: float,
    y: float,
    w: float,
    h: float,
    margin: int = CHARACTER_SAFE_MARGIN_PX,
    mode: str = "stable",
    face_box: tuple[float, float, float, float] | None = None,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
    chunk_index: int | None = None,
    pose: int | None = None,
    layout: str | None = None,
) -> tuple[float, float, float, bool]:
    """Clamp universale del soggetto al frame.

    Args:
        x, y, w, h: rettangolo del SOGGETTO su canvas (non dell'immagine).
        margin: margine di sicurezza (px) dai bordi.
        mode: "stable" (stato a riposo: tutto dentro, faccia mai tagliata) o
            "transition" (a meta' animazione il fuori-campo e' ammesso: ritorna
            invariato; il keyframe finale coincide con lo stato stabile perche'
            gli offset di entrata/uscita valgono 0 a progress 1).
        face_box: (fx0, fy0, fx1, fy1) su canvas o None.
        chunk_index/pose/layout: contesto per il warning quando corregge.

    Returns:
        (x, y, fattore_scala, corretto): in "stable" il soggetto sta in
        [margin, W-margin] x [margin, H] (i piedi possono toccare il bordo
        inferiore: e' voluto) e la faccia e' interamente visibile.
    """
    try:
        m = int(margin)
    except (TypeError, ValueError):
        m = 40
    try:
        cw, ch = int(canvas_w), int(canvas_h)
    except (TypeError, ValueError):
        cw, ch = (VIDEO_WIDTH, VIDEO_HEIGHT)
    try:
        rx, ry, rw, rh = float(x), float(y), float(w), float(h)
    except (TypeError, ValueError):
        return (float(x), float(y), 1.0, False)
    if mode == "transition":
        return (rx, ry, 1.0, False)
    if rw <= 0 or rh <= 0 or cw <= 0 or ch <= 0:
        return (rx, ry, 1.0, False)
    corrected = False
    scale_factor = 1.0
    try:
        fb: tuple[float, float, float, float] | None = None
        if face_box is not None and len(face_box) == 4:
            fb = (float(face_box[0]), float(face_box[1]),
                  float(face_box[2]), float(face_box[3]))
    except (TypeError, ValueError):
        fb = None

    def _shift_both(dx: float, dy: float) -> None:
        nonlocal rx, ry, fb
        rx += dx
        ry += dy
        if fb is not None:
            fb = (fb[0] + dx, fb[1] + dy, fb[2] + dx, fb[3] + dy)

    def _shrink_both(s: float) -> None:
        """Riduce soggetto e faccia attorno all'angolo superiore-sinistro."""
        nonlocal rx, ry, rw, rh, fb, scale_factor, corrected
        rw, rh = rw * s, rh * s
        if fb is not None:
            fb = (rx + (fb[0] - rx) * s, ry + (fb[1] - ry) * s,
                  rx + (fb[2] - rx) * s, ry + (fb[3] - ry) * s)
        scale_factor *= s
        corrected = True

    # 1) Riduci finche' ci sta (spazio utile: margini laterali + testa;
    #    i piedi possono arrivare fino a H, bordo inferiore voluto).
    avail_w = float(cw) - 2.0 * float(m)
    avail_h = float(ch) - float(m)
    if avail_w <= 0 or avail_h <= 0:
        return (rx, ry, 1.0, False)
    need = min(avail_w / rw if rw > 0 else 1.0, avail_h / rh if rh > 0 else 1.0)
    if need < 1.0:
        _shrink_both(max(0.05, need))
    # 2) Sposta dentro: x in [m, W-m-rw], y in [m, H-rh] (fondo fino a H).
    nx = min(float(cw - m) - rw, max(float(m), rx))
    ny = min(float(ch) - rh, max(float(m), ry))
    if abs(nx - rx) > 1e-9 or abs(ny - ry) > 1e-9:
        corrected = True
    _shift_both(nx - rx, ny - ry)
    # 3) Faccia mai tagliata (CHARACTER_FACE_MIN_VISIBLE=1.0): sposta il
    #    minimo per includerla (se il soggetto resta dentro), altrimenti
    #    riduci del 5% e riprova (max 2 volte).
    try:
        _face_min = float(CHARACTER_FACE_MIN_VISIBLE)
    except Exception:
        _face_min = 1.0
    for _ in range(2):
        if fb is None or _face_min <= 0.0:
            break
        try:
            inside = (fb[0] >= m and fb[1] >= m
                      and fb[2] <= cw - m and fb[3] <= ch - m)
        except Exception:
            break
        if inside:
            break
        try:
            dx = 0.0
            if fb[0] < m:
                dx = float(m) - fb[0]
            elif fb[2] > cw - m:
                dx = float(cw - m) - fb[2]
            dy = 0.0
            if fb[1] < m:
                dy = float(m) - fb[1]
            elif fb[3] > ch - m:
                dy = float(ch - m) - fb[3]
            trx, try_ = rx + dx, ry + dy
            if (m <= trx and trx + rw <= cw - m
                    and m <= try_ and try_ + rh <= ch):
                _shift_both(dx, dy)
                corrected = True
                break
            _shrink_both(0.95)
            nx2 = min(float(cw - m) - rw, max(float(m), rx))
            ny2 = min(float(ch) - rh, max(float(m), ry))
            _shift_both(nx2 - rx, ny2 - ry)
        except Exception as e:
            print(f"[character_geometry] warning: clamp faccia fallito ({e})")
            break
    if corrected:
        try:
            tag = ""
            if chunk_index is not None or pose is not None or layout is not None:
                tag = (f" (chunk={chunk_index}, posa={pose}, "
                       f"layout={layout})")
            print(f"[character_geometry] warning: soggetto clampato al frame"
                  f"{tag}: scala x{scale_factor:.3f}")
        except Exception:
            pass
    return (float(rx), float(ry), float(scale_factor), bool(corrected))


# ------------------------------------------------------------ Accoppiamento posa<->layout (FASE 6)


def pose_is_wide(pose: int) -> bool:
    """Vero se la posa e' larga (il vincolo larghezza scatta prima di quello
    altezza): solo bottom_center, oppure laterali con scala ridotta."""
    try:
        geo = get_subject_geometry(int(pose))
        sw, sh = float(geo.w), float(geo.h)
        if sw <= 0 or sh <= 0:
            return int(pose) == 2
        try:
            smax = float(CHARACTER_SCALE_MAX)
            ratio = float(CHARACTER_MAX_WIDTH_RATIO)
        except Exception:
            smax, ratio = (0.90, 0.62)
        return (sw * smax / sh) > ratio * 1.02 or (sw / sh) > 0.45
    except Exception:
        try:
            return int(pose) == 2
        except Exception:
            return False


def allowed_layouts_for_pose(pose: int) -> list[str]:
    """Layout ammessi per la posa (preset canonici)."""
    try:
        p = int(pose)
    except (TypeError, ValueError):
        return ["layout_center_standard",
                "layout_split_left", "layout_split_right"]
    if p in (4, 5):
        return ["layout_split_left", "layout_split_right"]
    try:
        if pose_is_wide(p):
            return ["layout_center_standard", "layout_center_punch_in"]
    except Exception:
        if p == 2:
            return ["layout_center_standard", "layout_center_punch_in"]
    return ["layout_center_standard", "layout_center_punch_in",
            "layout_split_left", "layout_split_right"]


def validate_pose_layout_pair(
    pose: int, layout: str
) -> tuple[str, bool]:
    """Valida la coppia posa/layout; se non ammessa usa il layout ammesso piu'
    vicino per direzione e logga "layout corretto". Non solleva mai."""
    try:
        p = int(pose)
    except (TypeError, ValueError):
        return (str(layout), False)
    raw = str(layout)
    fam = layout_family(raw)
    preset_vocab = is_preset_layout(raw) or raw in (
        "layout_center_standard", "layout_center_punch_in",
        "layout_split_left", "layout_split_right",
        "layout_bottom_focus", "layout_closeup_center",
    )
    try:
        allowed = allowed_layouts_for_pose(p)
    except Exception:
        return (raw, False)
    # Normalizza l'input alla famiglia per il confronto.
    allowed_fams = {layout_family(a) for a in allowed}
    if fam in allowed_fams:
        return (raw, False)
    # Sostituisci col piu' vicino per direzione (stessa famiglia se ammessa,
    # altrimenti default deterministico per posa).
    try:
        if p == 4:
            want = "right"
        elif p == 5:
            want = "left"
        elif fam in allowed_fams:
            want = fam
        else:
            want = layout_family(allowed[0])
    except Exception:
        want = "center"
    table = _FAMILY_PRESET if preset_vocab else _FAMILY_LEGACY
    fixed = table.get(want, allowed[0] if allowed else raw)
    try:
        print(f"[character_geometry] layout corretto: posa {p} {raw} -> {fixed} "
              f"(coppia non ammessa)")
    except Exception:
        pass
    return (fixed, True)


# ------------------------------------------------------------ Posizionamento sul soggetto (FASE 3 + 5)


def _feasible_center_interval(
    vcx: float, bx0: float, bx1: float, k: float,
    zmin: float, zmax: float, canvas_w: int, margin: int,
) -> tuple[float, float] | None:
    """Intervallo di centri visivi ammissibili (zona + frame), o None."""
    try:
        lo = max(float(zmin) * canvas_w, float(margin) + (float(vcx) - float(bx0)) * k)
        hi = min(float(zmax) * canvas_w,
                 float(canvas_w - margin) - (float(bx1) - float(vcx)) * k)
        if hi >= lo:
            return (lo, hi)
        return None
    except Exception:
        return None


def compute_subject_placement(
    pose: int,
    layout: str,
    punch: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
    src_size: tuple[int, int] | None = None,
    scale_hint: float = 0.75,
    text_rect: tuple[float, float, float, float] | None = None,
    chunk_index: int | None = None,
) -> dict:
    """Calcola scala + posizione del soggetto (fail-safe, mai solleva).

    - Scala = min(scala base, vincolo altezza, vincolo larghezza): il vincolo
      di larghezza vince sempre; il punch_in scala attorno a visual_center_x /
      bordo inferiore e viene ricappato (mai fuori campo).
    - Il centro visivo va nella safe zone del layout; x = centro - vcx*k.
    - Y: piedi del soggetto al bordo inferiore (H), testa mai sopra il margine.
    - Se non ci sta: sposta il centro nella zona il minimo necessario, poi
      riduci la scala (mai sotto 0.35*H di altezza soggetto, sotto la quale si
      passa a bottom_center).

    Ritorna dict {new_w, new_h, px, py, scale_abs, layout_used, corrected,
    notes, subject_rect, face_rect, visible_ratio, punch_effective}.
    """
    notes: list[str] = []
    try:
        cw = int(canvas_w) or VIDEO_WIDTH
    except (TypeError, ValueError):
        cw = VIDEO_WIDTH
    try:
        ch = int(canvas_h) or VIDEO_HEIGHT
    except (TypeError, ValueError):
        ch = VIDEO_HEIGHT
    try:
        p = int(pose)
    except (TypeError, ValueError):
        p = 1
    raw_layout = str(layout or "layout_center_standard")
    try:
        do_punch = bool(punch)
    except Exception:
        do_punch = False

    def _safe_fallback(reason: str) -> dict:
        try:
            print(f"[character_geometry] warning: fallback sicuro ({reason}) "
                  f"posa {p}/{raw_layout}")
        except Exception:
            pass
        geo0 = get_subject_geometry(p)
        try:
            k0 = (0.55 * float(ch)) / float(geo0.h)
        except Exception:
            k0 = 0.8
        k0 = max(0.2, min(1.0, float(k0)))
        try:
            fw0, fh0 = (768, 1376)
            if src_size is not None and len(src_size) == 2:
                fw0, fh0 = int(src_size[0]), int(src_size[1])
        except Exception:
            fw0, fh0 = (768, 1376)
        nw0 = max(1, int(round(fw0 * k0)))
        nh0 = max(1, int(round(fh0 * k0)))
        px0 = (cw - nw0) // 2
        py0 = ch - int(round(float(geo0.bbox[3]) * k0))
        sx0 = px0 + float(geo0.bbox[0]) * k0
        sy0 = py0 + float(geo0.bbox[1]) * k0
        _fw0 = float(geo0.w) * k0
        _fh0 = 0.22 * float(geo0.h) * k0
        _fx0 = sx0 + max(0.0, (_fw0 - min(_fw0, 190.0 * k0)) / 2.0)
        return {
            "new_w": nw0, "new_h": nh0, "px": int(px0), "py": int(py0),
            "scale_abs": float(k0), "layout_used": "bottom_center",
            "corrected": True, "notes": [reason, "fallback bottom_center"],
            "subject_rect": (sx0, sy0, float(geo0.w) * k0, float(geo0.h) * k0),
            "face_rect": (_fx0, sy0, min(_fw0, 190.0 * k0), _fh0),
            "visible_ratio": 1.0, "punch_effective": 1.0,
        }

    try:
        # 1) Coppia posa/layout valida (log "layout corretto" se cambia).
        layout_v, pair_fixed = validate_pose_layout_pair(p, raw_layout)
        if pair_fixed:
            notes.append(f"layout corretto: {raw_layout} -> {layout_v}")
        # 2) Geometria + scala vincolata.
        geo = get_subject_geometry(p)
        try:
            fw, fh = (int(geo.src_size[0]), int(geo.src_size[1]))
            if src_size is not None and len(src_size) == 2 \
                    and int(src_size[0]) > 0 and int(src_size[1]) > 0:
                # Riscala la bbox nativa sulle dimensioni reali dell'asset.
                rx_ratio = float(src_size[0]) / float(fw) if fw else 1.0
                fw, fh = int(src_size[0]), int(src_size[1])
                bx0 = float(geo.bbox[0]) * rx_ratio
                by0 = float(geo.bbox[1]) * rx_ratio
                bx1 = float(geo.bbox[2]) * rx_ratio
                by1 = float(geo.bbox[3]) * rx_ratio
                vcx = float(geo.visual_center_x) * rx_ratio
                sw = float(geo.w) * rx_ratio
                sh = float(geo.h) * rx_ratio
                fb = (float(geo.face_box[0]) * rx_ratio,
                      float(geo.face_box[1]) * rx_ratio,
                      float(geo.face_box[2]) * rx_ratio,
                      float(geo.face_box[3]) * rx_ratio)
            else:
                bx0, by0, bx1, by1 = (float(geo.bbox[0]), float(geo.bbox[1]),
                                      float(geo.bbox[2]), float(geo.bbox[3]))
                vcx = float(geo.visual_center_x)
                sw, sh = float(geo.w), float(geo.h)
                fb = (float(geo.face_box[0]), float(geo.face_box[1]),
                      float(geo.face_box[2]), float(geo.face_box[3]))
        except Exception as e:
            return _safe_fallback(f"bbox non valida ({e})")
        try:
            margin = int(CHARACTER_SAFE_MARGIN_PX)
        except Exception:
            margin = 40
        k, punch_eff, capped = constrained_scale_abs(
            sw, sh, float(fw), layout_v, do_punch, cw, ch, scale_hint)
        if capped:
            notes.append(f"scala cappata a {k:.3f} (punch_eff x{punch_eff:.2f})")
        try:
            k_min = (_MIN_SANITY_HEIGHT_RATIO * float(ch)) / sh
        except Exception:
            k_min = 0.4
        # 3) Centro visivo nella safe zone, soggetto dentro [m, W-m].
        zmin, zmax, zdef = safe_zone_for_layout(layout_v)
        interval = _feasible_center_interval(vcx, bx0, bx1, k, zmin, zmax, cw, margin)
        if interval is None:
            # Riduci la scala finche' zona e frame sono compatibili.
            try:
                k_fit = (float(cw) - 2.0 * float(margin)) / sw
            except Exception:
                k_fit = k
            if k_fit < k:
                notes.append(f"scala ridotta {k:.3f} -> {k_fit:.3f} per la zona")
                k = k_fit
            if k < k_min:
                # Sotto il minimo di sanita': passa a bottom_center.
                notes.append(f"scala {k:.3f} sotto minimo: layout -> bottom_center")
                layout_v = (_FAMILY_LEGACY["center"]
                            if not is_preset_layout(raw_layout)
                            else _FAMILY_PRESET["center"])
                zmin, zmax, zdef = safe_zone_for_layout(layout_v)
                k = max(k, min(k_min, (float(cw) - 2.0 * float(margin)) / sw
                               if sw > 0 else k_min))
            interval = _feasible_center_interval(vcx, bx0, bx1, k, zmin, zmax,
                                                 cw, margin)
            if interval is None:
                return _safe_fallback("zona/frame incompatibili")
        lo, hi = interval
        cx = min(hi, max(lo, float(zdef) * float(cw)))
        corrected = bool(pair_fixed or capped or abs(cx - zdef * cw) > 1e-9)
        x_full = cx - vcx * k
        y_full = float(ch) - float(by1) * k  # piedi al bordo inferiore
        subj = (x_full + bx0 * k, y_full + by0 * k, sw * k, sh * k)
        # fb e' in coordinate asset (spazio immagine intera): su canvas va
        # scalata di k e traslata di (x_full, y_full). Formato (x, y, w, h).
        face = (x_full + fb[0] * k, y_full + fb[1] * k,
                (fb[2] - fb[0]) * k, (fb[3] - fb[1]) * k)
        # 4) Testo ha priorita' (FASE 7): overlap > 25% dell'area testo.
        # Il punch-in e' sovrimpressione intenzionale protetta da pill
        # (come nel pre-flight di video_builder): nessun ribilanciamento.
        if text_rect is not None and layout_v != "layout_center_punch_in":
            try:
                adj = adjust_for_text_overlap(
                    p, layout_v, do_punch, k, x_full, y_full,
                    vcx, bx0, by0, bx1, by1, sw, sh, fb,
                    text_rect, cw, ch, margin, k_min)
                if adj is not None:
                    (layout_v, k, x_full, y_full,
                     subj, face, tnotes) = adj
                    notes.extend(tnotes)
                    corrected = True
            except Exception as e:
                notes.append(f"adjust testo saltato ({e})")
                print(f"[character_geometry] warning: adjust testo fallito ({e})")
        # 5) Clamp universale sullo stato stabile.
        try:
            min_vis = float(CHARACTER_MIN_VISIBLE_RATIO)
        except Exception:
            min_vis = 0.97
        fx0, fy0, fw_sub, fh_sub = subj
        ffb = (face[0], face[1], face[0] + face[2], face[1] + face[3])
        nx, ny, sf, clamp_fixed = clamp_subject_to_frame(
            fx0, fy0, fw_sub, fh_sub, margin, "stable", ffb, cw, ch,
            chunk_index=chunk_index, pose=p, layout=layout_v)
        if sf < 1.0 - 1e-9:
            # Il clamp ha ridotto attorno all'angolo superiore-sinistro:
            # adotta la nuova scala e ricalcola tutto dai nativi (coerente).
            k = k * sf
            x_full = nx - bx0 * k
            y_full = ny - by0 * k
            subj = (nx, ny, sw * k, sh * k)
            face = (x_full + fb[0] * k, y_full + fb[1] * k,
                    (fb[2] - fb[0]) * k, (fb[3] - fb[1]) * k)
            notes.append(f"clamp: scala x{sf:.3f}")
            corrected = True
        elif clamp_fixed:
            dx, dy = nx - fx0, ny - fy0
            x_full, y_full = x_full + dx, y_full + dy
            subj = (nx, ny, fw_sub, fh_sub)
            face = (face[0] + dx, face[1] + dy, face[2], face[3])
            notes.append("clamp: posizione corretta")
            corrected = True
        new_w = max(1, int(round(float(fw) * k)))
        new_h = max(1, int(round(float(fh) * k)))
        vis = rect_visible_ratio(
            (subj[0], subj[1], subj[2], subj[3]), cw, ch)
        if vis < min_vis - 1e-9:
            notes.append(f"visible_ratio {vis:.3f} < {min_vis}")
        return {
            "new_w": new_w, "new_h": new_h,
            "px": int(round(x_full)), "py": int(round(y_full)),
            "scale_abs": float(k), "layout_used": str(layout_v),
            "corrected": bool(corrected or clamp_fixed), "notes": notes,
            "subject_rect": (float(subj[0]), float(subj[1]),
                             float(subj[2]), float(subj[3])),
            "face_rect": (float(face[0]), float(face[1]),
                          float(face[2]), float(face[3])),
            "visible_ratio": float(vis),
            "punch_effective": float(punch_eff),
        }
    except Exception as e:
        return _safe_fallback(str(e))


def adjust_for_text_overlap(
    pose: int,
    layout: str,
    punch: bool,
    k: float,
    x_full: float,
    y_full: float,
    vcx: float,
    bx0: float,
    by0: float,
    bx1: float,
    by1: float,
    sw: float,
    sh: float,
    fb_native: tuple[float, float, float, float],
    text_rect: tuple[float, float, float, float],
    canvas_w: int,
    canvas_h: int,
    margin: int,
    k_min: float,
) -> tuple | None:
    """Ribilancia soggetto vs fascia sottotitoli (il testo ha priorita').

    Se il soggetto copre oltre il 25% dell'area testo, prova nell'ordine:
    layout opposto ammesso, scala -13%, spostamento al bordo della safe zone.
    Ritorna (layout, k, x_full, y_full, subj, face, notes) o None se tutto ok.
    Non solleva mai (None in caso di errore = tieni il piazzamento).
    """
    try:
        subj = (x_full + bx0 * k, y_full + by0 * k, sw * k, sh * k)
        tx, ty, tw, th = (float(text_rect[0]), float(text_rect[1]),
                          float(text_rect[2]), float(text_rect[3]))
        if tw <= 0 or th <= 0:
            return None
        overlap = rects_overlap_fraction(subj, (tx, ty, tw, th))
        if overlap <= _TEXT_OVERLAP_THRESHOLD:
            return None
        notes = [f"overlap testo {overlap:.2f} > {_TEXT_OVERLAP_THRESHOLD}"]
        fam = layout_family(layout)
        # 1) Layout opposto ammesso (stessa direzione solo se gia' opposto).
        if fam in ("left", "right"):
            want = "right" if fam == "left" else "left"
            table = (_FAMILY_PRESET if is_preset_layout(layout)
                     else _FAMILY_LEGACY)
            cand = table.get(want, layout)
            fixed, ok_corr = validate_pose_layout_pair(pose, cand)
            if not ok_corr or layout_family(fixed) == want:
                zmin, zmax, zdef = safe_zone_for_layout(fixed)
                interval = _feasible_center_interval(
                    vcx, bx0, bx1, k, zmin, zmax, canvas_w, margin)
                if interval is not None:
                    lo, hi = interval
                    cx = min(hi, max(lo, float(zdef) * float(canvas_w)))
                    xf = cx - vcx * k
                    yf = float(canvas_h) - float(by1) * k
                    sj = (xf + bx0 * k, yf + by0 * k, sw * k, sh * k)
                    if rects_overlap_fraction(sj, (tx, ty, tw, th)) <= \
                            _TEXT_OVERLAP_THRESHOLD:
                        fc = (xf + fb_native[0] * k, yf + fb_native[1] * k,
                              (fb_native[2] - fb_native[0]) * k,
                              (fb_native[3] - fb_native[1]) * k)
                        notes.append(f"layout opposto ammesso: {fixed}")
                        return (fixed, k, xf, yf, sj, fc, notes)
        # 2) Scala ridotta del 13% (mai sotto il minimo di sanita').
        k2 = max(float(k_min), float(k) * float(_TEXT_SHRINK_STEP))
        if k2 < k - 1e-9:
            zmin, zmax, zdef = safe_zone_for_layout(layout)
            interval = _feasible_center_interval(
                vcx, bx0, bx1, k2, zmin, zmax, canvas_w, margin)
            if interval is not None:
                lo, hi = interval
                cx = min(hi, max(lo, float(zdef) * float(canvas_w)))
                xf = cx - vcx * k2
                yf = float(canvas_h) - float(by1) * k2
                sj = (xf + bx0 * k2, yf + by0 * k2, sw * k2, sh * k2)
                fc = (xf + fb_native[0] * k2,
                      yf + fb_native[1] * k2,
                      (fb_native[2] - fb_native[0]) * k2,
                      (fb_native[3] - fb_native[1]) * k2)
                notes.append(f"scala ridotta a {k2:.3f} per il testo")
                return (layout, k2, xf, yf, sj, fc, notes)
        # 3) Spostamento verso il bordo entro la safe zone (lontano dal testo).
        try:
            zmin, zmax, zdef = safe_zone_for_layout(layout)
            interval = _feasible_center_interval(
                vcx, bx0, bx1, k, zmin, zmax, canvas_w, margin)
            if interval is not None:
                lo, hi = interval
                text_cx = tx + tw / 2.0
                subj_cx = x_full + vcx * k
                edge = lo if text_cx > subj_cx else hi
                xf = edge - vcx * k
                sj = (xf + bx0 * k, y_full + by0 * k, sw * k, sh * k)
                fc = (xf + fb_native[0] * k, y_full + fb_native[1] * k,
                      (fb_native[2] - fb_native[0]) * k,
                      (fb_native[3] - fb_native[1]) * k)
                notes.append("spostato al bordo zona per il testo")
                return (layout, k, xf, y_full, sj, fc, notes)
        except Exception as e:
            notes.append(f"shift testo saltato ({e})")
        notes.append("overlap testo residuo: testo resta prioritario")
        return None
    except Exception as e:
        print(f"[character_geometry] warning: adjust testo fallito ({e})")
        return None


# ------------------------------------------------------------ Diagnostica (FASE 8)


def save_debug_png(
    output_path: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
    subject_rect: tuple[float, float, float, float] | None = None,
    face_rect: tuple[float, float, float, float] | None = None,
    text_rect: tuple[float, float, float, float] | None = None,
    safe_zone: tuple[float, float, float] | None = None,
    pose: int | None = None,
    layout: str | None = None,
    base_image: Image.Image | None = None,
) -> str | None:
    """Salva il PNG di debug (bordo frame, margini, safe zone, bbox, faccia,
    testo). Non solleva mai (None in caso di errore)."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        if base_image is not None:
            try:
                img = base_image.convert("RGB").copy()
                if img.size != (int(canvas_w), int(canvas_h)):
                    img = img.resize((int(canvas_w), int(canvas_h)))
            except Exception:
                img = Image.new("RGB", (int(canvas_w), int(canvas_h)), (18, 18, 24))
        else:
            img = Image.new("RGB", (int(canvas_w), int(canvas_h)), (18, 18, 24))
        d = ImageDraw.Draw(img)
        try:
            margin = int(CHARACTER_SAFE_MARGIN_PX)
        except Exception:
            margin = 40
        d.rectangle([0, 0, canvas_w - 1, canvas_h - 1],
                    outline=(255, 255, 255), width=4)
        d.rectangle([margin, margin, canvas_w - margin, canvas_h - margin],
                    outline=(0, 255, 0), width=2)
        if safe_zone is not None:
            try:
                zx0 = safe_zone[0] * canvas_w
                zx1 = safe_zone[1] * canvas_w
                d.rectangle([zx0, 0, zx1, canvas_h],
                            outline=(0, 150, 255), width=2)
            except Exception:
                pass
        if text_rect is not None:
            try:
                tx, ty, tw, th = text_rect
                d.rectangle([tx, ty, tx + tw, ty + th],
                            outline=(0, 255, 255), width=2)
            except Exception:
                pass
        if subject_rect is not None:
            try:
                sx, sy, sw2, sh2 = subject_rect
                d.rectangle([sx, sy, sx + sw2, sy + sh2],
                            outline=(255, 0, 0), width=3)
            except Exception:
                pass
        if face_rect is not None:
            try:
                fx, fy, fw3, fh3 = face_rect
                # face_rect puo' essere (x, y, w, h) o (x0, y0, x1, y1):
                # qui usiamo (x, y, w, h) come da compute_subject_placement.
                d.rectangle([fx, fy, fx + fw3, fy + fh3],
                            outline=(255, 255, 0), width=3)
            except Exception:
                pass
        try:
            d.text((12, 12), f"posa={pose} layout={layout}", fill=(255, 255, 255))
        except Exception:
            pass
        img.save(output_path)
        return output_path
    except Exception as e:
        print(f"[character_geometry] warning: debug PNG fallito ({e})")
        return None


def debug_dir() -> str:
    """Cartella dei PNG di debug (TEMP_DIR/debug_char)."""
    try:
        base = str(TEMP_DIR)
    except Exception:
        base = "temp"
    return os.path.join(base, "debug_char")
