"""
Safe zone UI P0 (WS-C): profili per piattaforma in un solo punto.

Valori in px su 1080x1920 (approssimati: ricavati dalle UI delle app e
variabili tra versioni → sovrascrivibili via SAFE_ZONE_OVERRIDES_JSON).
`universal` (default) = intersezione conservativa: bottom 420, laterali
120 base; 220 solo nella fascia rail (y 700-1600) dove vivono i pulsanti.

API pure: get_profile, safe_rect, rail_rects, text_allowed_rect,
rect_violations, apply_overrides, cover_safe_rect. Niente I/O.
"""

from __future__ import annotations

import json

CANVAS_W = 1080
CANVAS_H = 1920

# top, bottom, left, right + rail destra (x extra, fascia y).
PROFILES: dict[str, dict] = {
    "tiktok": {"top": 130, "bottom": 420, "left": 60, "right": 120,
               "rail_extra": 221, "rail_y0": 700, "rail_y1": 1600},
    "reels": {"top": 130, "bottom": 360, "left": 60, "right": 120,
              "rail_extra": 100, "rail_y0": 700, "rail_y1": 1600},
    "shorts": {"top": 150, "bottom": 340, "left": 60, "right": 120,
               "rail_extra": 100, "rail_y0": 700, "rail_y1": 1600},
    "universal": {"top": 150, "bottom": 420, "left": 120, "right": 120,
                 "rail_extra": 220, "rail_y0": 700, "rail_y1": 1600},
}

DEFAULT_PROFILE = "universal"

# Banda sicura per frame 0 / hook title (il feed/griglia ritaglia i bordi).
COVER_SAFE_TOP = 285
COVER_SAFE_BOTTOM = 285


def _custom_overrides() -> dict:
    try:
        import config as _c
        raw = str(getattr(_c, "SAFE_ZONE_OVERRIDES_JSON", "") or "").strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def normalize_profile_name(name: str | None) -> str:
    try:
        n = str(name or "").strip().lower()
    except Exception:
        return DEFAULT_PROFILE
    if n in PROFILES:
        return n
    try:
        import config as _c
        env = str(getattr(_c, "PLATFORM_PROFILE", DEFAULT_PROFILE) or DEFAULT_PROFILE)
        if env.strip().lower() in PROFILES:
            return env.strip().lower()
    except Exception:
        pass
    return DEFAULT_PROFILE


def get_profile(name: str | None = None) -> dict:
    """Profilo safe zone (copia) con override applicati. Mai eccezioni."""
    pname = normalize_profile_name(name)
    base = dict(PROFILES[pname])
    try:
        ov = _custom_overrides()
        # Forma: {"universal": {"bottom": 400}} oppure {"bottom": 400} (profilo attivo).
        scoped = ov.get(pname) if isinstance(ov.get(pname), dict) else None
        flat = {k: v for k, v in ov.items() if k in base} if isinstance(ov, dict) else {}
        for src in (scoped, flat):
            if not src:
                continue
            for k in ("top", "bottom", "left", "right", "rail_extra", "rail_y0", "rail_y1"):
                if k in src:
                    try:
                        base[k] = max(0, int(src[k]))
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    base["name"] = pname
    return base


def apply_overrides(profile: dict, overrides: dict | None) -> dict:
    """Applica override a un profilo (puro, per test). Mai eccezioni."""
    try:
        out = dict(profile or {})
        for k, v in (overrides or {}).items():
            if k in ("top", "bottom", "left", "right", "rail_extra", "rail_y0", "rail_y1"):
                try:
                    out[k] = max(0, int(v))
                except (TypeError, ValueError):
                    continue
        return out
    except Exception:
        try:
            return dict(profile or {})
        except Exception:
            return {}


def padding_px() -> int:
    """Padding extra oltre le riserve UI (MARGIN esistente, configurabile)."""
    try:
        import config as _c
        return max(0, int(getattr(_c, "SAFE_ZONE_PADDING_PX", 24)))
    except Exception:
        return 24


def safe_rect(profile: dict | None = None, canvas_w: int = CANVAS_W,
              canvas_h: int = CANVAS_H) -> tuple[int, int, int, int]:
    """Rettangolo sicuro (x0, y0, x1, y1) con padding. Mai eccezioni."""
    try:
        p = dict(profile) if isinstance(profile, dict) else get_profile()
        pad = padding_px()
        sx = canvas_w / CANVAS_W
        sy = canvas_h / CANVAS_H
        return (
            int(round((p.get("left", 120) + pad) * sx)),
            int(round((p.get("top", 150) + pad) * sy)),
            int(round(canvas_w - (p.get("right", 120) + pad) * sx)),
            int(round(canvas_h - (p.get("bottom", 420) + pad) * sy)),
        )
    except Exception:
        return (144, 174, CANVAS_W - 144, CANVAS_H - 444)


def rail_rects(profile: dict | None = None, canvas_w: int = CANVAS_W,
               canvas_h: int = CANVAS_H) -> list[tuple[int, int, int, int]]:
    """Fasce rail (pulsanti laterali): testo vietato quando le interseca."""
    try:
        p = dict(profile) if isinstance(profile, dict) else get_profile()
        sx = canvas_w / CANVAS_W
        sy = canvas_h / CANVAS_H
        extra = int(round(p.get("rail_extra", 220) * sx))
        y0 = int(round(p.get("rail_y0", 700) * sy))
        y1 = int(round(p.get("rail_y1", 1600) * sy))
        right = int(round(p.get("right", 120) * sx))
        if extra <= right:
            return []
        # La rail è la parte ECCEDENTE la riserva laterale (a destra).
        return [(canvas_w - extra, y0, canvas_w - right, y1)]
    except Exception:
        return []


def cover_safe_rect(canvas_w: int = CANVAS_W,
                    canvas_h: int = CANVAS_H) -> tuple[int, int, int, int]:
    """Banda sicura per frame 0 / hook title (contro il crop del feed)."""
    try:
        sx = canvas_w / CANVAS_W
        sy = canvas_h / CANVAS_H
        return (0, int(round(COVER_SAFE_TOP * sy)),
                canvas_w, int(round(canvas_h - COVER_SAFE_BOTTOM * sy)))
    except Exception:
        return (0, 285, canvas_w, canvas_h - 285)


def text_allowed_rect(
    layout_box: tuple[int, int, int, int] | None,
    profile: dict | None = None,
    canvas_w: int = CANVAS_W,
    canvas_h: int = CANVAS_H,
) -> tuple[int, int, int, int]:
    """Intersezione tra zona del layout e safe_rect del profilo (puro)."""
    try:
        sx0, sy0, sx1, sy1 = safe_rect(profile, canvas_w, canvas_h)
        if layout_box is None:
            return (sx0, sy0, sx1, sy1)
        lx0, ly0, lx1, ly1 = (int(layout_box[0]), int(layout_box[1]),
                              int(layout_box[2]), int(layout_box[3]))
        # Scala il layout su canvas diversi.
        if canvas_w != CANVAS_W or canvas_h != CANVAS_H:
            fx, fy = canvas_w / CANVAS_W, canvas_h / CANVAS_H
            lx0, ly0, lx1, ly1 = (int(round(lx0 * fx)), int(round(ly0 * fy)),
                                  int(round(lx1 * fx)), int(round(ly1 * fy)))
        x0, y0 = max(sx0, lx0), max(sy0, ly0)
        x1, y1 = min(sx1, lx1), min(sy1, ly1)
        if x1 <= x0 or y1 <= y0:
            return (sx0, sy0, sx1, sy1)
        return (x0, y0, x1, y1)
    except Exception:
        try:
            return safe_rect(profile, canvas_w, canvas_h)
        except Exception:
            return (144, 174, canvas_w - 144, canvas_h - 444)


def _overlaps(a: tuple, b: tuple) -> bool:
    try:
        return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])
    except Exception:
        return False


def rect_violations(
    rect: tuple[int, int, int, int] | None,
    profile: dict | None = None,
    canvas_w: int = CANVAS_W,
    canvas_h: int = CANVAS_H,
) -> list[str]:
    """Violazioni safe zone di un bbox testo (inclusi stroke/ombra/pop).

    Ritorna lista di stringhe (vuota = ok). Mai eccezioni.
    """
    try:
        if rect is None:
            return []
        p = dict(profile) if isinstance(profile, dict) else get_profile()
        x0, y0, x1, y1 = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        sx = canvas_w / CANVAS_W
        sy = canvas_h / CANVAS_H
        top = (p.get("top", 150)) * sy
        bottom = canvas_h - (p.get("bottom", 420)) * sy
        left = (p.get("left", 120)) * sx
        right = canvas_w - (p.get("right", 120)) * sx
        out: list[str] = []
        if y0 < top:
            out.append("testo-in-top-ui")
        if y1 > bottom:
            out.append("testo-in-bottom-ui")
        if x0 < left:
            out.append("testo-in-left-ui")
        if x1 > right:
            out.append("testo-in-right-ui")
        for r in rail_rects(p, canvas_w, canvas_h):
            if _overlaps((x0, y0, x1, y1), r):
                out.append("testo-in-rail")
                break
        if x0 < 0 or y0 < 0 or x1 > canvas_w or y1 > canvas_h:
            out.append("testo-fuori-canvas")
        return out
    except Exception:
        return []


def should_use_safe_zones() -> bool:
    try:
        import config as _c
        val = getattr(_c, "SAFE_ZONES_ENABLED", True)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        return True
