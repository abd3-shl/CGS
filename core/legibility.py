"""
Leggibilità adattiva P0 (WS-D): logica PURA, testabile con `unittest`.

- `relative_luminance` / `contrast_ratio`: formula WCAG.
- `decide_text_effects(stats, text_rgb, font_px, tier, cfg) -> TextEffects`:
  livello 0 (pulito, nessun effetto) … 3 (massimo: stroke + ombra + scrim/pill).

Livelli (auto, dallo sfondo DIETRO il testo):
  0 pulito: std_lum < 0.04 E contrasto >= 7:1 → nessuno (look TikTok attuale).
  1 soft:   std 0.04-0.10 O contrasto 4.5-7 → ombra morbida.
  2 forte:  std 0.10-0.18 O contrasto 3-4.5 → stroke 0.04-0.05·font + ombra.
  3 massimo: std > 0.18 O contrasto < 3 → stroke 0.06·font + ombra + scrim/pill.

Tier T2/T3 con sfondo non piatto: almeno livello 1.
Niente I/O qui (il probe dello sfondo vive in core/background_probe.py).
"""

from __future__ import annotations


def _chan(c: float) -> float:
    try:
        v = max(0.0, min(1.0, float(c) / 255.0))
    except (TypeError, ValueError):
        return 0.0
    if v <= 0.03928:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb) -> float:
    """Luminanza relativa WCAG 0..1 da (R,G,B) 0..255. Mai eccezioni."""
    try:
        r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    except (TypeError, ValueError, IndexError):
        return 1.0
    return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)


def contrast_ratio(fg, bg) -> float:
    """Rapporto di contrasto WCAG 1..21. Mai eccezioni."""
    try:
        l1 = relative_luminance(fg)
        l2 = relative_luminance(bg)
        hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
        return (hi + 0.05) / (lo + 0.05)
    except Exception:
        return 21.0


def _cfg(key: str, default):
    try:
        import config as _c
        return getattr(_c, key, default)
    except Exception:
        return default


def legibility_mode() -> str:
    """auto | off | always. Mai eccezioni."""
    try:
        m = str(_cfg("LEGIBILITY_MODE", "auto") or "auto").strip().lower()
        return m if m in ("auto", "off", "always") else "auto"
    except Exception:
        return "auto"


def forced_level() -> int | None:
    """LEGIBILITY_FORCE_LEVEL 0-3 per test (None = auto). Mai eccezioni."""
    try:
        raw = _cfg("LEGIBILITY_FORCE_LEVEL", "")
        if raw is None or str(raw).strip() == "":
            return None
        v = int(str(raw).strip())
        return v if 0 <= v <= 3 else None
    except (TypeError, ValueError):
        return None


def _is_flat(stats) -> bool:
    try:
        return float(stats.get("std_lum", 0.0)) < 0.04
    except (TypeError, ValueError):
        return True


def decide_text_effects(
    stats: dict | None,
    text_rgb=(255, 255, 255),
    font_px: int = 84,
    tier: str = "base",
    bg_rgb=(0, 0, 0),
    cfg: dict | None = None,
) -> dict:
    """Decide gli effetti di leggibilità (puro, deterministico).

    Args:
        stats: {mean_lum, std_lum, p10, p90, edge_density} (luminanze 0..1).
        text_rgb: colore testo (R,G,B).
        font_px: dimensione font effettiva.
        tier: "base" | "impact" | "accent" | "hero" (T2/T3 → min livello 1
            se lo sfondo non è piatto).
        bg_rgb: luminanza media sfondo (per il contrasto).
        cfg: override {"mode", "force_level", "scrim", "allow_color_flip"}.

    Returns:
        TextEffects dict {level, stroke_px, stroke_rgba, shadow, pill,
        scrim_alpha, color_override}. Mai eccezioni.
    """
    try:
        font_px = max(8, int(font_px))
    except (TypeError, ValueError):
        font_px = 84
    try:
        st = dict(stats or {})
        std = float(st.get("std_lum", 0.0))
    except (TypeError, ValueError):
        std = 0.0
        st = {}
    try:
        text = (int(text_rgb[0]), int(text_rgb[1]), int(text_rgb[2]))
    except (TypeError, ValueError, IndexError):
        text = (255, 255, 255)
    try:
        bg = (int(bg_rgb[0]), int(bg_rgb[1]), int(bg_rgb[2]))
    except (TypeError, ValueError, IndexError):
        bg = (0, 0, 0)

    mode = str((cfg or {}).get("mode", "") or legibility_mode()).lower()
    force = (cfg or {}).get("force_level", None)
    if force is None:
        force = forced_level()
    try:
        allow_flip = bool((cfg or {}).get("allow_color_flip", _cfg("LEGIBILITY_ALLOW_COLOR_FLIP", False)))
    except Exception:
        allow_flip = False
    try:
        scrim_on = bool((cfg or {}).get("scrim", _cfg("LEGIBILITY_SCRIM", True)))
    except Exception:
        scrim_on = True

    if mode == "off":
        return _effects(0, font_px, text, 21.0, False, 0.0, None)
    if force is not None:
        try:
            level = max(0, min(3, int(force)))
        except (TypeError, ValueError):
            level = 0
        cr = contrast_ratio(text, bg)
        return _effects(level, font_px, text, cr, scrim_on, _scrim_alpha(level), None)

    cr = contrast_ratio(text, bg)
    # Peggio tra condizione texture e condizione contrasto.
    if std < 0.04:
        lvl_tex = 0
    elif std < 0.10:
        lvl_tex = 1
    elif std <= 0.18:
        lvl_tex = 2
    else:
        lvl_tex = 3
    if cr >= 7.0:
        lvl_con = 0
    elif cr >= 4.5:
        lvl_con = 1
    elif cr >= 3.0:
        lvl_con = 2
    else:
        lvl_con = 3
    level = max(lvl_tex, lvl_con)
    # Livello 0 richiede ENTRAMBE le condizioni pulite (già garantito dal max).
    # Tier T2/T3 su sfondo non piatto: almeno livello 1.
    try:
        if str(tier).lower() in ("impact", "accent", "hero", "t2", "t3") and not _is_flat(st):
            level = max(1, level)
    except Exception:
        pass
    if mode == "always" and level < 1:
        level = 1

    color_override = None
    if allow_flip and cr < 3.0 and level >= 2:
        # Schiarisci/scurisci mantenendo la tinta (solo se abilitato).
        color_override = _lift_toward_readable(text, bg)

    return _effects(level, font_px, text, cr, scrim_on, _scrim_alpha(level),
                    color_override)


def _scrim_alpha(level: int) -> float:
    if level >= 3:
        return 0.40
    return 0.0


def _effects(level, font_px, text, contrast, scrim_on, scrim_alpha, color_override) -> dict:
    eff = {
        "level": int(level),
        "stroke_px": 0,
        "stroke_rgba": (0, 0, 0, 0),
        "shadow": None,
        "pill": False,
        "scrim_alpha": 0.0,
        "color_override": color_override,
        "contrast": round(float(contrast), 2),
    }
    try:
        lum = relative_luminance(text)
        dark_stroke = lum >= 0.35  # testo chiaro → stroke scuro e viceversa
    except Exception:
        dark_stroke = True
    stroke_col = (0, 0, 0, 230) if dark_stroke else (255, 255, 255, 230)
    if level == 1:
        eff["shadow"] = {
            "dx": 0,
            "dy": max(1, int(round(0.05 * font_px))),
            "blur": max(2, int(round(0.08 * font_px))),
            "alpha": 0.45,
        }
    elif level == 2:
        eff["stroke_px"] = max(3, int(round(0.045 * font_px)))
        eff["stroke_rgba"] = stroke_col
        eff["shadow"] = {
            "dx": 0,
            "dy": max(1, int(round(0.05 * font_px))),
            "blur": max(2, int(round(0.08 * font_px))),
            "alpha": 0.45,
        }
    elif level >= 3:
        eff["stroke_px"] = min(8, max(3, int(round(0.06 * font_px))))
        eff["stroke_rgba"] = stroke_col
        eff["shadow"] = {
            "dx": 0,
            "dy": max(1, int(round(0.05 * font_px))),
            "blur": max(2, int(round(0.08 * font_px))),
            "alpha": 0.45,
        }
        eff["pill"] = True
        eff["scrim_alpha"] = float(scrim_alpha) if scrim_on else 0.0
    return eff


def _lift_toward_readable(text: tuple, bg: tuple) -> tuple | None:
    """Sposta la luminosità del testo mantenendo la tinta (puro)."""
    try:
        lum_t = relative_luminance(text)
        lum_b = relative_luminance(bg)
        # Direzione: lontano dallo sfondo.
        target = 0.85 if lum_b < 0.5 else 0.15
        k = target / max(1e-3, lum_t) if lum_t > 0 else 1.0
        k = max(0.2, min(3.0, k))
        # Applica come mix verso bianco/nero per non saturare la tinta.
        mix = (255, 255, 255) if lum_b < 0.5 else (0, 0, 0)
        out = tuple(max(0, min(255, int(round(0.45 * text[i] + 0.55 * mix[i])))) for i in range(3))
        if contrast_ratio(out, bg) > contrast_ratio(text, bg):
            return out
        return None
    except Exception:
        return None


def should_apply_legibility() -> bool:
    """Vero se il path P0 è attivo (LEGIBILITY_ENABLED=1 e mode != off)."""
    try:
        val = _cfg("LEGIBILITY_ENABLED", True)
        enabled = val if isinstance(val, bool) else str(val).strip().lower() not in ("0", "false", "no", "off", "")
        return bool(enabled) and legibility_mode() != "off"
    except Exception:
        return True
