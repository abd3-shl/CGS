"""
Advanced Kinetics Engine (Full Engine Upgrade — Fase 2).

Tipografia cinetica multi-tier T0-T3 con easing dedicato, glyph-cache e
interpolazione matematica su timestamp esatti. Tutto opt-in via
`ENABLE_ADVANCED_KINETICS`: a flag spento il comportamento e' identico al
legacy (nessuna regressione).

Tier (quando abilitato):
  - T0/T1 base: bianco/grigio + bordo nero 3px (KINETIC_T0_STROKE_PX),
    fade-in rapida in 2 frame.
  - T2 keyword: COLOR_BRAND_ACCENT, picco 110% sui primi 3-4 frame con
    Ease-Out Back poi 100%.
  - T3 hero: badge/pill semi-trasparente COLOR_HERO_BG + font display
    HERO_WORD_FONT_PATH + micro-shake/bounce.

Z-Index (composite stack): bg Z=0 < character Z=10 < dimmer Z=20 <
subtitles Z=30 < debug Z=99. Questo modulo disegna solo il livello Z=30
(testo) e il badge hero (sempre sotto il glifo, sopra dimmer).

Glyph-cache: LRU {(font_key, word, fill, stroke): tile RGBA} per evitare
colli di bottiglia Pillow su caption da 2-3 parole. Le curve di
interpolazione (rotazione/opacita'/scala) sono pure e lavorano sui timestamp
esatti (nessuna allocazione nel loop caldo).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

try:
    from config import (
        COLOR_BRAND_ACCENT,
        COLOR_HERO_BG,
        ENABLE_ADVANCED_KINETICS,
        EASING_CURVES,
        KINETIC_T0_STROKE_PX,
        KINETIC_T2_PEAK_FRAMES,
        KINETIC_T2_SCALE_PEAK,
        KINETIC_T3_SHAKE_PX,
        VIDEO_FPS,
    )
except Exception:  # config datata / import isolato
    COLOR_BRAND_ACCENT = "#FF3366"
    COLOR_HERO_BG = "#000000A6"
    ENABLE_ADVANCED_KINETICS = True
    EASING_CURVES = {}
    KINETIC_T0_STROKE_PX = 3
    KINETIC_T2_PEAK_FRAMES = 4
    KINETIC_T2_SCALE_PEAK = 1.10
    KINETIC_T3_SHAKE_PX = 4.0
    VIDEO_FPS = 30

try:
    from core.easing import (
        clamp01,
        ease_in_cubic,
        ease_out_back,
        ease_out_cubic,
        ease_out_elastic,
        ease_out_quad,
    )
except Exception:  # pragma: no cover
    def clamp01(t: float) -> float:  # type: ignore
        return max(0.0, min(1.0, float(t)))

    def ease_out_cubic(t: float) -> float:  # type: ignore
        t = clamp01(t)
        return 1.0 - pow(1.0 - t, 3)

    def ease_out_back(t: float) -> float:  # type: ignore
        t = clamp01(t)
        c1, c3 = 1.70158, 2.70158
        return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)

    def ease_out_quad(t: float) -> float:  # type: ignore
        t = clamp01(t)
        return 1.0 - (1.0 - t) * (1.0 - t)

    def ease_in_cubic(t: float) -> float:  # type: ignore
        return clamp01(t) ** 3

    def ease_out_elastic(t: float) -> float:  # type: ignore
        return ease_out_back(t)


# ---------------------------------------------------------------- glyph cache
class GlyphCache:
    """LRU di tile RGBA per (font_key, word, fill, stroke). Max 512 voci."""

    def __init__(self, maxsize: int = 512) -> None:
        self._max = max(16, int(maxsize))
        self._store: OrderedDict[tuple, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _key(self, font_key: Any, word: str, fill: Any, stroke: int) -> tuple:
        try:
            f = tuple(fill) if isinstance(fill, (list, tuple)) else str(fill)
        except Exception:
            f = str(fill)
        return (str(font_key), str(word), f, int(stroke))

    def get(self, font_key: Any, word: str, fill: Any, stroke: int) -> Any | None:
        try:
            k = self._key(font_key, word, fill, stroke)
            hit = self._store.get(k)
            if hit is not None:
                self._store.move_to_end(k)
                self.hits += 1
                return hit
            self.misses += 1
            return None
        except Exception:
            return None

    def put(self, font_key: Any, word: str, fill: Any, stroke: int, tile: Any) -> None:
        try:
            k = self._key(font_key, word, fill, stroke)
            self._store[k] = tile
            self._store.move_to_end(k)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self._store.clear()
        except Exception:
            pass


_glyph_cache = GlyphCache(maxsize=512)


def get_glyph_cache() -> GlyphCache:
    return _glyph_cache


# ------------------------------------------------------- interpolazione pura
def lerp(a: float, b: float, t: float) -> float:
    """Interpolazione lineare con clamp (nessuna allocazione)."""
    try:
        t = clamp01(t)
        return float(a) + (float(b) - float(a)) * t
    except Exception:
        return float(a)


def scale_at(t_norm: float, scale_from: float = 0.7, curve: str = "t2_pop") -> float:
    """Scala eased  su timestamp normalizzato (0..1)."""
    try:
        name = (EASING_CURVES.get(curve, "ease_out_back") if isinstance(EASING_CURVES, dict) else "ease_out_back")
        fn = {"ease_out_back": ease_out_back, "ease_out_elastic": ease_out_elastic,
              "ease_out_cubic": ease_out_cubic, "ease_out_quad": ease_out_quad}.get(name, ease_out_back)
        eased = fn(clamp01(t_norm))
        return float(scale_from) + (1.0 - float(scale_from)) * float(eased)
    except Exception:
        return 1.0


def opacity_at(t_norm: float, curve: str = "t0_fade") -> int:
    try:
        name = (EASING_CURVES.get(curve, "ease_out_cubic") if isinstance(EASING_CURVES, dict) else "ease_out_cubic")
        fn = {"ease_out_cubic": ease_out_cubic, "ease_out_quad": ease_out_quad,
              "ease_in_cubic": ease_in_cubic}.get(name, ease_out_cubic)
        return int(round(255 * fn(clamp01(t_norm))))
    except Exception:
        return 255


def rotation_at(t_norm: float, amp_deg: float = 0.0) -> float:
    """Rotazione decorativa (default 0: i sottotitoli restano dritti)."""
    try:
        if abs(float(amp_deg)) < 1e-9:
            return 0.0
        return float(amp_deg) * math.sin(math.pi * clamp01(t_norm))
    except Exception:
        return 0.0


# ------------------------------------------------------------- T2 peak / T3
def t2_peak_scale(frame_idx: int, base_scale: float = 1.0) -> float:
    """Picco 110% sui primi KINETIC_T2_PEAK_FRAMES frame (degrada a base).

    Da applicare SOLO quando ENABLE_ADVANCED_KINETICS: il pop Ease-Out Back
    gia' fa overshoot, ma il picco esplicito garantisce il 110% sui primi
    3-4 frame come da spec anche con preset soft (pop_from 0.8).
    """
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return float(base_scale)
        peak = max(1.0, float(KINETIC_T2_SCALE_PEAK))
        n = max(1, int(KINETIC_T2_PEAK_FRAMES))
        if frame_idx < 0:
            return float(base_scale)
        if frame_idx >= n:
            return float(base_scale)
        # Rampa lineare peak -> base sui primi N frame.
        k = 1.0 - (float(frame_idx + 1) / float(n + 1))
        return float(base_scale) * (1.0 + (peak - 1.0) * max(0.0, min(1.0, k)))
    except Exception:
        return float(base_scale)


def hero_shake_offset(frame_idx: int, fps: int = 30) -> tuple[int, int]:
    """Micro-shake badge hero: sinusoide ±KINETIC_T3_SHAKE_PX (solo se enabled)."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return (0, 0)
        amp = max(0.0, float(KINETIC_T3_SHAKE_PX))
        if amp <= 0:
            return (0, 0)
        t = float(frame_idx) / max(1, int(fps or VIDEO_FPS))
        dx = int(round(math.sin(t * 2 * math.pi * 6.0) * amp * 0.5))
        dy = int(round(math.cos(t * 2 * math.pi * 5.0) * amp * 0.35))
        return (dx, dy)
    except Exception:
        return (0, 0)


def advanced_stroke_for(style: str, base_stroke: int = 0) -> int:
    """Stroke T0/T1 in modalita' avanzata: 3px neri, altrimenti base."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return int(base_stroke)
        if str(style) in ("base", "accent"):
            return max(int(base_stroke), int(KINETIC_T0_STROKE_PX))
        return int(base_stroke)
    except Exception:
        return int(base_stroke)


def advanced_entry_duration(style: str, entry_dur: float, fps: int = 30) -> float:
    """T0/T1 fade-in rapida in 2 frame quando abilitato (spec Fase 2)."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return float(entry_dur)
        if str(style) in ("base", "accent"):
            two_frames = 2.0 / max(1, int(fps or VIDEO_FPS))
            return max(0.01, min(float(entry_dur), two_frames))
        return float(entry_dur)
    except Exception:
        return float(entry_dur)


def parse_hex_rgba(hex_color: str, default: tuple = (255, 51, 102, 255)) -> tuple:
    """Parse #RRGGBB[#AA] -> RGBA (mai eccezioni)."""
    try:
        s = str(hex_color or "").strip()
        if s.startswith("#") and len(s) in (7, 9):
            r, g, b = int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
            a = int(s[7:9], 16) if len(s) == 9 else 255
            return (r, g, b, a)
        return default
    except Exception:
        return default


def brand_accent_rgba() -> tuple:
    try:
        return parse_hex_rgba(str(COLOR_BRAND_ACCENT), (255, 51, 102, 255))
    except Exception:
        return (255, 51, 102, 255)


def hero_bg_rgba() -> tuple:
    try:
        return parse_hex_rgba(str(COLOR_HERO_BG), (0, 0, 0, 166))
    except Exception:
        return (0, 0, 0, 166)


def draw_hero_badge(
    frame_img: Any,
    bbox: tuple[int, int, int, int],
    pad: int = 18,
    radius: int = 26,
) -> None:
    """Badge T3: pill semi-trasparente sotto il glifo (Z=30, sopra dimmer).

    Disegna direttamente su `frame_img` (RGBA). Mai eccezioni: a canvas
    degenere non fa nulla.
    """
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return
        from PIL import ImageDraw as _ID

        x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        if x1 <= x0 or y1 <= y0:
            return
        W, H = frame_img.size
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad // 2)
        x1, y1 = min(W, x1 + pad), min(H, y1 + pad // 2)
        d = _ID.Draw(frame_img)
        try:
            d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=hero_bg_rgba())
        except (AttributeError, ValueError, TypeError):
            d.rectangle([x0, y0, x1, y1], fill=hero_bg_rgba())
    except Exception:
        pass
