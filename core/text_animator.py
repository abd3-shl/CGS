"""
Animazioni testo per-parola (Fase 3) + Dynamic Layout (sistema a zone)
+ Semantic Typography Engine v1 (stili misti per nicchia).

Ogni parola del chunk entra in scena esattamente al suo timestamp `start`
e resta visibile accumulandosi accanto alle precedenti; tutte le parole
scompaiono insieme a `chunk.end` (uscita di gruppo).

- Parole normali/base: entrata minimal (solo fade con `ease_out_cubic`).
- Keyword/impact: entrata marcata (opacita' + scala 0.7 -> 1.0 con `ease_out_back`,
  effetto "pop" premium; `ease_out_bounce` resta disponibile come variante
  piu' giocosa ma di default si usa `ease_out_back`, meno distraente su
  caption da 2-3 parole).
- Uscita: uguale per tutte, fade di gruppo con `ease_in_cubic`.

Il layout e' pre-calcolato UNA VOLTA per chunk (via
`core/renderer.compute_word_layout` per il path legacy, oppure
`compute_styled_layout` per il path tipografico) dentro la `text_safe_area`
del preset (wrapping dinamico sulla sua larghezza): personaggio e testo non si
sovrappongono mai (entrambi risolvono da `resolve_chunk_layout`, singola fonte).

Semantic Typography (quando il chunk porta "styled_words" + "typography_niche",
vedi core/text_tagger.py): 3 font per nicchia (base/impact/accent via
core/font_manager.py), impact 1.3x-1.5x uppercase colore highlight, accent
handwritten 1.1x con colore dedicato per ruolo. NESSUN contorno nero e
NESSUNA ombra di default (look pulito TikTok): leggibilità da contrasto
tema + pill sul punch-in. Colori sempre coerenti col tema (base dal tema,
highlight/accent validati per contrasto sullo sfondo).

Personaggio (mezzo busto/mezza figura, mai figura intera): slide rapida da
fuori campo in 0.2s; cambio lato split -> slide_down 0.2s + rientro dal lato
opposto; punch_in -> JUMP-CUT netto (stacco di camera, nessuna transizione
morbida); stesso preset+posa -> hold invisibile.

Struttura narrativa (hook/corpo/CTA, vedi core/narrative_structure.py):
i chunk portano narrative_role + override anim_entry_mult/anim_pop_from
(hook scattante). I chunk CTA con cta_card=true sono renderizzati come
UNICA card persistente (generate_cta_card_frames): messaggio finale fisso
con reveal karaoke, pill badge, personaggio bloccato e dissolvenza unica.

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
    TYPOGRAPHY_ENGINE_ENABLED,
    TYPOGRAPHY_BASE_FONT_SIZE,
    TYPOGRAPHY_IMPACT_SCALE,
    TYPOGRAPHY_ACCENT_SCALE,
    TYPOGRAPHY_STROKE_WIDTH,
    TYPOGRAPHY_SHADOW_ENABLED,
    TYPOGRAPHY_SHADOW_OFFSET,
    TYPOGRAPHY_SHADOW_FILL,
)
from core.easing import (
    clamp01,
    ease_out_cubic,
    ease_out_back,
    ease_in_cubic,
)
from core.keywords import normalize_word
from core.renderer import (
    load_font,
    compute_word_layout,
    draw_word,
    draw_text_background,
    get_character_layer,
)

# Re-export per spec ("RENDER E POSIZIONAMENTO (... / core/text_animator.py)").
from core.character_selector import (
    calculate_character_bbox as calculate_character_bbox,
    resolve_chunk_layout as resolve_chunk_layout,
)
from core.renderer import calculate_character_transform as calculate_character_transform
from core.layout_presets import (
    preset_font_scale,
    preset_needs_text_background,
    preset_safe_area,
    preset_side,
)

# Durata entrata personaggio legacy v1 (offset corto, feel premium).
_CHARACTER_ENTRY_DURATION = 0.35
_CHARACTER_SLIDE_UP_PX = 320
_CHARACTER_SLIDE_SIDE_PX = 260
# Slide rapide del sistema a zone (motion graphics 9:16): 0.2s in/out.
_CHARACTER_ZONE_ENTRY_DURATION = 0.20
_CHARACTER_ZONE_EXIT_DURATION = 0.20
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


# ---------------------------------------------------------------------------
# Semantic Typography Engine v1 — helpers multi-style
# ---------------------------------------------------------------------------

# Cache font tipografici {(path, size): PIL font} per non ricaricare per frame.
_typo_font_cache: dict[tuple[str, int], object] = {}


def _is_typography_chunk(chunk: dict) -> bool:
    """Vero se il chunk porta styled_words validi (vedi core/text_tagger.py)."""
    try:
        if not TYPOGRAPHY_ENGINE_ENABLED:
            return False
    except NameError:
        pass
    styled = (chunk or {}).get("styled_words")
    if not isinstance(styled, list) or not styled:
        return False
    for s in styled:
        if isinstance(s, dict) and str(s.get("word", "")).strip() and s.get("style") in ("base", "impact", "accent"):
            return True
    return False


def _resolve_typography_preset(chunk: dict, explicit_niche=None, explicit_preset=None) -> dict:
    """Preset tipografico effettivo (explicit_preset > chunk niche > explicit_niche > fallback)."""
    try:
        from core.typography_presets import get_preset
    except Exception:
        return {
            "niche": "fallback", "fonts": {"base": [], "impact": [], "accent": []},
            "colors": {"base": "#FFFFFF", "highlight": "#FFD700", "accent": "#FFE8A3", "stroke": "#000000"},
            "sizes": {"base": TYPOGRAPHY_BASE_FONT_SIZE, "impact_scale": TYPOGRAPHY_IMPACT_SCALE, "accent_scale": TYPOGRAPHY_ACCENT_SCALE},
            "stroke_width": 0,
            "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
            "impact_uppercase": True,
        }
    if isinstance(explicit_preset, dict) and "fonts" in explicit_preset:
        return explicit_preset
    niche = None
    try:
        if isinstance(chunk, dict) and chunk.get("typography_niche"):
            niche = chunk.get("typography_niche")
        elif explicit_niche:
            niche = explicit_niche
    except Exception:
        niche = explicit_niche
    return get_preset(niche)


def _load_typography_fonts(preset: dict, font_scale: float = 1.0) -> dict:
    """Carica i 3 font PIL del preset alle dimensioni ponderate.

    - base:   size standard (es. 60px) * font_scale del layout preset
    - impact: base * impact_scale (1.3x-1.5x, es. 80-90px)
    - accent: base * accent_scale (1.1x)
    Ritorna {"base": font, "impact": font, "accent": font, "sizes": {...}, "paths": {...}}.
    Mai eccezioni: fallback a renderer.load_font.
    """
    try:
        scale = float(font_scale)
    except (TypeError, ValueError):
        scale = 1.0
    if scale <= 0:
        scale = 1.0
    sizes_cfg = preset.get("sizes", {}) if isinstance(preset, dict) else {}
    try:
        base_size = int(round(float(sizes_cfg.get("base", TYPOGRAPHY_BASE_FONT_SIZE)) * scale))
    except (TypeError, ValueError):
        base_size = TYPOGRAPHY_BASE_FONT_SIZE
    try:
        impact_scale = float(sizes_cfg.get("impact_scale", TYPOGRAPHY_IMPACT_SCALE))
    except (TypeError, ValueError):
        impact_scale = 1.4
    try:
        accent_scale = float(sizes_cfg.get("accent_scale", TYPOGRAPHY_ACCENT_SCALE))
    except (TypeError, ValueError):
        accent_scale = 1.1
    impact_scale = min(1.6, max(1.2, impact_scale))
    accent_scale = min(1.3, max(1.0, accent_scale))
    sizes = {
        "base": max(24, base_size),
        "impact": max(24, int(round(base_size * impact_scale))),
        "accent": max(24, int(round(base_size * accent_scale))),
    }
    fonts_cfg = preset.get("fonts", {}) if isinstance(preset, dict) else {}
    out: dict = {"sizes": sizes, "paths": {}, "names": {}}
    try:
        from core.font_manager import FontManager
        manager = FontManager()
    except Exception:
        manager = None
    for role in ("base", "impact", "accent"):
        candidates = fonts_cfg.get(role, []) if isinstance(fonts_cfg, dict) else []
        if not isinstance(candidates, list):
            candidates = []
        font_obj = None
        chosen_path = ""
        chosen_name = ""
        for cand in candidates:
            name = str(cand or "").strip()
            if not name:
                continue
            path = ""
            if manager is not None:
                try:
                    path = manager.ensure_font_exists(name)
                except Exception:
                    path = ""
            if path:
                key = (path, sizes[role])
                cached = _typo_font_cache.get(key)
                if cached is not None:
                    font_obj = cached
                    chosen_path = path
                    chosen_name = name
                    break
                try:
                    from PIL import ImageFont
                    font_obj = ImageFont.truetype(path, sizes[role])
                    _typo_font_cache[key] = font_obj
                    chosen_path = path
                    chosen_name = name
                    break
                except Exception:
                    continue
        if font_obj is None:
            # Fallback coerente PER RUOLO (mai lo stesso font per tutti i ruoli
            # se possibile): base -> sans pulito, impact -> heavy/display,
            # accent -> handwritten/serif. Così i 3 livelli restano distinguibili
            # anche senza rete o con asset mancanti.
            role_fallback_names = {
                "base": ["Arial", "Inter", "Roboto"],
                "impact": ["Anton", "Impact", "Oswald"],
                "accent": ["Caveat", "Patrick Hand", "Playfair Display"],
            }
            loaded = False
            if manager is not None:
                for fb_name in role_fallback_names.get(role, []):
                    try:
                        fb_path = manager.ensure_font_exists(fb_name)
                    except Exception:
                        fb_path = ""
                    if fb_path:
                        try:
                            from PIL import ImageFont as _IF
                            key = (fb_path, sizes[role])
                            cached = _typo_font_cache.get(key)
                            if cached is not None:
                                font_obj = cached
                            else:
                                font_obj = _IF.truetype(fb_path, sizes[role])
                                _typo_font_cache[key] = font_obj
                            chosen_path = fb_path
                            chosen_name = fb_name + " (fallback ruolo)"
                            loaded = True
                            break
                        except Exception:
                            continue
            if not loaded:
                try:
                    font_obj = load_font(sizes[role])
                except Exception:
                    from PIL import ImageFont
                    font_obj = ImageFont.load_default()
        out[role] = font_obj
        out["paths"][role] = chosen_path
        out["names"][role] = chosen_name
    # Garanzia anti-collasso: se due ruoli hanno risolto lo STESSO file font,
    # prova a differenziare l'accent con un fallback alternativo (evita che
    # base/accent risultino visivamente identici).
    try:
        _paths = out.get("paths", {})
        if _paths.get("accent") and _paths.get("accent") == _paths.get("base"):
            # L'accent è collassato sul base: il tagging resta comunque valido
            # (distinzione per colore dedicato, vedi _styled_fills), nessun crash.
            pass
    except Exception:
        pass
    return out


def _luminance_rgba(rgba: tuple) -> float:
    """Luminanza percepita 0-255 da RGBA (canali 0-2)."""
    try:
        r, g, b = int(rgba[0]), int(rgba[1]), int(rgba[2])
    except Exception:
        return 255.0
    return 0.299 * r + 0.587 * g + 0.114 * b


def _contrast_ok(fg: tuple, bg_hex_or_rgba, min_diff: int = 80) -> bool:
    """Vero se la differenza di luminanza fg/bg supera la soglia."""
    try:
        bg = _to_rgba(bg_hex_or_rgba, (0, 0, 0, 255))
        return abs(_luminance_rgba(fg) - _luminance_rgba(bg)) >= float(min_diff)
    except Exception:
        return True


def _styled_fills(
    preset: dict,
    base_override=None,
    background_color=None,
    keyword_colors: dict | None = None,
) -> dict:
    """Colori RGBA per ruolo, coerenti al 100% con tema + sfondo + keyword.

    Regole di attribuzione (singola fonte di verità):
    - base:   colore testo del TEMA (base_override) se fornito, altrimenti
      preset. Se il contrasto sullo sfondo è insufficiente, flip a
      bianco/nero (il più distante dallo sfondo).
    - impact: highlight del preset, MA validato per contrasto sullo sfondo:
      se illeggibile prova in ordine la palette keyword del video, poi
      l'highlight_alt del preset, poi bianco/nero sicuri. Deve inoltre essere
      distinto dal base (se troppo simile, preferisce l'alternativa).
    - accent: colore dedicato del preset (mai uguale al base per costruzione
      dei preset v2). Se manca o è uguale al base, deriva una tinta coerente;
      se illeggibile sullo sfondo, ripiega sul base (distinzione resta via font).
    - stroke: sempre trasparente (nessun contorno nero). La chiave resta per
      compatibilità API ma con width=0 non viene mai disegnata.
    """
    from config import THEME_MIN_LUMINANCE_DIFF
    colors = preset.get("colors", {}) if isinstance(preset, dict) else {}
    preset_base_hex = colors.get("base", "#FFFFFF")
    highlight_hex = colors.get("highlight", "#FFD700")
    highlight_alt = colors.get("highlight_alt")
    accent_hex = colors.get("accent", None)

    # --- base: il tema vince (coerenza sfondo/testo della pipeline) ---
    if base_override is not None:
        base_rgba = _to_rgba(base_override, _to_rgba(preset_base_hex, SUBTITLE_COLOR))
    else:
        base_rgba = _to_rgba(preset_base_hex, SUBTITLE_COLOR)
    if background_color is not None and not _contrast_ok(
        base_rgba, background_color, THEME_MIN_LUMINANCE_DIFF
    ):
        bg_lum = _luminance_rgba(_to_rgba(background_color, (0, 0, 0, 255)))
        base_rgba = (255, 255, 255, 255) if abs(255 - bg_lum) >= abs(0 - bg_lum) else (0, 0, 0, 255)

    # --- impact: highlight validato, con fallback a catena ---
    impact_candidates: list[tuple] = [_to_rgba(highlight_hex, base_rgba)]
    if isinstance(keyword_colors, dict):
        for _v in keyword_colors.values():
            impact_candidates.append(_to_rgba(_v, base_rgba))
    if highlight_alt:
        impact_candidates.append(_to_rgba(highlight_alt, base_rgba))
    bg_lum_for_bw: float | None = None
    if background_color is not None:
        try:
            bg_lum_for_bw = _luminance_rgba(_to_rgba(background_color, (0, 0, 0, 255)))
        except Exception:
            bg_lum_for_bw = None
    impact_rgba = impact_candidates[0]
    for cand in impact_candidates:
        if background_color is not None and not _contrast_ok(
            cand, background_color, THEME_MIN_LUMINANCE_DIFF
        ):
            continue
        # Distinto dal base: differenza luminanza minima o tinta diversa.
        try:
            same_lum = abs(_luminance_rgba(cand) - _luminance_rgba(base_rgba)) < 40
            same_rgb = tuple(cand[:3]) == tuple(base_rgba[:3])
        except Exception:
            same_lum, same_rgb = False, False
        if same_rgb or same_lum:
            # Cerca un'alternativa più distinta prima di accettarlo.
            continue
        impact_rgba = cand
        break
    else:
        # Nessun candidato ideale: prendi il primo leggibile, o bianco/nero sicuro.
        for cand in impact_candidates:
            if background_color is None or _contrast_ok(
                cand, background_color, THEME_MIN_LUMINANCE_DIFF
            ):
                impact_rgba = cand
                break
        else:
            if bg_lum_for_bw is not None:
                impact_rgba = (255, 255, 255, 255) if bg_lum_for_bw < 128 else (0, 0, 0, 255)
        # Ultima rete: mai identico al base.
        try:
            if tuple(impact_rgba[:3]) == tuple(base_rgba[:3]):
                impact_rgba = (255, 255, 255, 255) if tuple(base_rgba[:3]) != (255, 255, 255) else (0, 0, 0, 255)
        except Exception:
            pass

    # --- accent: dedicato, distinto dal base, leggibile ---
    if isinstance(accent_hex, str) and accent_hex.strip():
        accent_rgba = _to_rgba(accent_hex, base_rgba)
    else:
        accent_rgba = base_rgba
    try:
        accent_same_as_base = tuple(accent_rgba[:3]) == tuple(base_rgba[:3])
    except Exception:
        accent_same_as_base = True
    if accent_same_as_base:
        # Deriva una tinta coerente dall'impact (stessa famiglia, più chiara):
        # mix 55% impact + 45% base per restare armonico ma distinguibile.
        try:
            accent_rgba = tuple(
                int(round(0.55 * impact_rgba[i] + 0.45 * base_rgba[i])) for i in range(3)
            ) + (255,)
            if tuple(accent_rgba[:3]) == tuple(base_rgba[:3]):
                accent_rgba = impact_rgba
        except Exception:
            accent_rgba = impact_rgba
    if background_color is not None and not _contrast_ok(
        accent_rgba, background_color, THEME_MIN_LUMINANCE_DIFF
    ):
        accent_rgba = base_rgba  # ripiego leggibile; distinzione resta via font

    return {
        "base": base_rgba,
        "impact": impact_rgba,
        "accent": accent_rgba,
        # Trasparente: nessun contorno nero su nessuna parola.
        "stroke": (0, 0, 0, 0),
    }


def compute_styled_layout(
    styled_words: list[dict],
    fonts: dict,
    max_width: int,
    area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Layout multi-style: misura OGNI parola col suo font e wrappa per larghezza cumulativa.

    Args:
        styled_words: [{"word","display","style",...}] (display già uppercase per impact).
        fonts: {"base": font, "impact": font, "accent": font} da _load_typography_fonts.
        max_width: larghezza massima blocco (es. VIDEO_WIDTH*0.85, poi min con area).
        area: text_safe_area (x_min,y_min,x_max,y_max); None = centro schermo.

    Returns:
        Lista parallela a styled_words: {"word","display","style","x","y","width","height","font_role"}.
        Il blocco è centrato DENTRO l'area e resta dentro quando ci sta
        (stessa semantica di renderer.compute_word_layout).
    """
    from PIL import Image as _Image, ImageDraw as _ImageDraw
    from core.renderer import LINE_SPACING
    items: list[dict] = []
    for s in styled_words or []:
        role = s.get("style", "base") if isinstance(s, dict) else "base"
        if role not in ("base", "impact", "accent"):
            role = "base"
        word = str((s or {}).get("display", (s or {}).get("word", "")))
        items.append({"word": str((s or {}).get("word", "")), "display": word, "style": role})
    if not items:
        return []
    if area is not None:
        try:
            ax0, ay0, ax1, ay1 = (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
            if ax1 > ax0 and ay1 > ay0:
                max_width = min(int(max_width), ax1 - ax0)
                center_x = (ax0 + ax1) / 2.0
                center_y = (ay0 + ay1) / 2.0
                use_area = True
            else:
                use_area = False
        except (TypeError, ValueError, IndexError):
            use_area = False
    else:
        use_area = False
    if not use_area:
        ax0, ay0, ax1, ay1 = 0, 0, VIDEO_WIDTH, VIDEO_HEIGHT
        center_x = VIDEO_WIDTH / 2.0
        center_y = VIDEO_HEIGHT / 2.0
    probe = _Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = _ImageDraw.Draw(probe)

    def _font_for(role: str):
        f = fonts.get(role)
        if f is None:
            f = fonts.get("base")
        return f

    def _metrics_for(role: str) -> tuple[int, int]:
        """(ascent, descent) del font dalla baseline (getmetrics, mai crash)."""
        f = _font_for(role)
        try:
            asc, desc = f.getmetrics()
            asc, desc = int(asc), int(desc)
            if asc <= 0 or desc < 0 or asc + desc <= 0:
                raise ValueError("metriche degeneri")
            return asc, desc
        except Exception:
            # Fallback bitmap/default: proporzioni standard del size.
            try:
                size = int(getattr(f, "size", 60))
            except Exception:
                size = 60
            return max(8, int(round(size * 0.80))), max(0, int(round(size * 0.20)))

    def _measure(display: str, role: str) -> tuple[float, int, int, int]:
        """(larghezza, ascent, descent, altezza_linea) per la parola."""
        f = _font_for(role)
        try:
            w = float(draw.textlength(display, font=f))
        except Exception:
            w = float(len(display) * 30)
        asc, desc = _metrics_for(role)
        return w, asc, desc, max(8, asc + desc)

    # Spazio medio: usa il base (stabile tra righe miste).
    try:
        space_w = float(draw.textlength(" ", font=_font_for("base")))
    except Exception:
        space_w = 20.0

    # Wrapping per larghezza cumulativa (misure stabili da metriche font,
    # non da bbox glifo-dipendente: niente salti tra maiuscole/minuscole).
    lines: list[list[int]] = []
    current: list[int] = []
    current_width = 0.0
    widths: list[float] = []
    ascents: list[int] = []
    descents: list[int] = []
    heights: list[int] = []
    for idx, it in enumerate(items):
        w, asc, desc, h = _measure(it["display"], it["style"])
        widths.append(w)
        ascents.append(asc)
        descents.append(desc)
        heights.append(h)
    for idx, it in enumerate(items):
        w = widths[idx]
        extra = w + (space_w if current else 0)
        if current_width + extra <= max_width or not current:
            current.append(idx)
            current_width += extra
        else:
            lines.append(current)
            current = [idx]
            current_width = w
    if current:
        lines.append(current)

    # Altezza riga da metriche: max ascent + max descent della riga.
    # Tutte le parole della riga condividono la STESSA baseline
    # (allineamento professionale, mai parole "flottanti").
    line_widths: list[float] = []
    line_ascents: list[int] = []
    line_descents: list[int] = []
    line_heights: list[int] = []
    for line in lines:
        lw = sum(widths[i] for i in line) + space_w * (len(line) - 1) if line else 0.0
        la = max([ascents[i] for i in line]) if line else 0
        ld = max([descents[i] for i in line]) if line else 0
        line_widths.append(lw)
        line_ascents.append(la)
        line_descents.append(ld)
        line_heights.append(la + ld)
    total_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1) if lines else 0
    start_y = int(round(center_y - total_height / 2.0))
    if use_area and lines:
        start_y = max(ay0, min(start_y, ay1 - total_height))

    layout: list[dict] = [None] * len(items)  # type: ignore
    y = start_y
    for line, lw, la, ld, lh in zip(lines, line_widths, line_ascents, line_descents, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            x = max(float(ax0), x)
            if x + lw > VIDEO_WIDTH - 8:
                x = max(float(ax0), VIDEO_WIDTH - 8 - lw)
        baseline = y + la  # baseline comune di riga (anchor "la": y = baseline - ascent)
        for j, idx in enumerate(line):
            it = items[idx]
            w = widths[idx]
            asc = ascents[idx]
            # Top per anchor default "la": baseline - ascent del SINGOLO font.
            # Così base piccolo e impact grosso stanno sulla stessa baseline.
            y_top = baseline - asc
            layout[idx] = {
                "word": it["word"],
                "display": it["display"],
                "style": it["style"],
                "font_role": it["style"],
                "x": int(round(x)),
                "y": int(round(y_top)),
                "width": int(round(w)),
                "height": int(heights[idx]),
                "line_height": int(lh),
                "baseline": int(round(baseline)),
                "ascent": int(asc),
                "descent": int(descents[idx]),
            }
            x += w
            if j < len(line) - 1:
                x += space_w
        y += lh + LINE_SPACING
    return layout


def _draw_styled_word_direct(
    draw,
    display: str,
    x: int,
    y: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    shadow_offset: tuple[int, int] | None,
    shadow_fill: tuple | None,
    opacity: int,
) -> None:
    """Disegna parola pulita (nessun contorno di default) + ombra opzionale."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    try:
        sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        sw = 0
    if sw < 0:
        sw = 0
    try:
        from core.renderer import _normalize_rgba
        fill_rgba = _normalize_rgba(fill, SUBTITLE_COLOR)
        stroke_rgba = _normalize_rgba(stroke_color, (0, 0, 0, 0))
    except Exception:
        fill_rgba = tuple(fill) if isinstance(fill, (tuple, list)) else SUBTITLE_COLOR
        stroke_rgba = tuple(stroke_color) if isinstance(stroke_color, (tuple, list)) else (0, 0, 0, 0)
    if opacity < 255:
        factor = opacity / 255.0
        fill_rgba = (fill_rgba[0], fill_rgba[1], fill_rgba[2], int(round(fill_rgba[3] * factor)))
        stroke_rgba = (stroke_rgba[0], stroke_rgba[1], stroke_rgba[2], int(round(stroke_rgba[3] * factor)))
    # Ombra prima (solo se abilitata esplicitamente e non trasparente).
    if shadow_offset is not None and shadow_fill is not None and TYPOGRAPHY_SHADOW_ENABLED:
        try:
            sh = tuple(int(v) for v in shadow_fill)
            if len(sh) == 3:
                sh = (sh[0], sh[1], sh[2], 255)
            if len(sh) >= 4 and sh[3] <= 0:
                sh = None
            else:
                sx, sy = int(shadow_offset[0]), int(shadow_offset[1])
                if sx == 0 and sy == 0:
                    sh = None
                elif opacity < 255:
                    sh = (sh[0], sh[1], sh[2], int(round(sh[3] * opacity / 255.0)))
        except (TypeError, ValueError, IndexError):
            sh = None
        if sh is not None:
            try:
                draw.text((x + sx, y + sy), display, font=font, fill=sh)
            except Exception:
                pass
    try:
        if sw <= 0:
            # Path pulito: nessun contorno nero.
            draw.text((x, y), display, font=font, fill=fill_rgba)
        else:
            draw.text((x, y), display, font=font, fill=fill_rgba,
                      stroke_width=sw, stroke_fill=stroke_rgba)
    except Exception:
        try:
            draw.text((x, y), display, font=font, fill=fill_rgba)
        except Exception:
            pass


def _render_styled_scaled_word(
    frame_img,
    display: str,
    x: int,
    y: int,
    word_w: int,
    word_h: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    shadow_offset,
    shadow_fill,
    opacity: int,
    scale: float,
) -> None:
    """Come _render_scaled_word ma con drop shadow inclusa nella tile scalata."""
    if opacity <= 0 or scale <= 0:
        return
    if abs(scale - 1.0) < 1e-3:
        draw = ImageDraw.Draw(frame_img)
        _draw_styled_word_direct(draw, display, x, y, font, fill, stroke_color,
                                 stroke_width, shadow_offset, shadow_fill, opacity)
        return
    try:
        _sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        _sw = 0
    pad = 32 + max(0, _sw) * 2
    try:
        if shadow_offset is None or not TYPOGRAPHY_SHADOW_ENABLED:
            sox, soy = 0, 0
        else:
            sox, soy = int(shadow_offset[0]), int(shadow_offset[1])
    except Exception:
        sox, soy = 0, 0
    pad_x = pad + max(0, sox)
    pad_y = pad + max(0, soy)
    tile_w = max(1, int(word_w + pad_x * 2))
    tile_h = max(1, int(word_h + pad_y * 2))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    _draw_styled_word_direct(tile_draw, display, pad_x, pad_y, font, fill, stroke_color,
                             stroke_width, shadow_offset, shadow_fill, opacity)
    new_w = max(1, int(round(tile_w * scale)))
    new_h = max(1, int(round(tile_h * scale)))
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS
    scaled = tile.resize((new_w, new_h), resample)
    cx = x + word_w / 2.0
    cy = y + word_h / 2.0
    tcx = (pad_x + word_w / 2.0) * scale
    tcy = (pad_y + word_h / 2.0) * scale
    px = int(round(cx - tcx))
    py = int(round(cy - tcy))
    try:
        frame_img.paste(scaled, (px, py), scaled)
    except ValueError:
        fx0, fy0 = max(0, px), max(0, py)
        tx0, ty0 = fx0 - px, fy0 - py
        tx1 = min(new_w, VIDEO_WIDTH - px)
        ty1 = min(new_h, VIDEO_HEIGHT - py)
        if tx1 > tx0 and ty1 > ty0:
            cropped = scaled.crop((tx0, ty0, tx1, ty1))
            frame_img.paste(cropped, (fx0, fy0), cropped)


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
            return preset_side(info.get("layout"))
        except Exception:
            return "center"
    return "left" if "left" in str(info.get("position", "")) else (
        "right" if "right" in str(info.get("position", "")) else "center")


def _load_chunk_character_layer(info: dict | None):
    """Layer personaggio (immagine + XY) per il chunk, o (None, None).

    Col preset usa `get_character_layer` (scala width-based + punch_in);
    errori non bloccanti (asset mancante, posa invalida): il frame viene
    generato senza personaggio (nessuna regressione).
    """
    if info is None:
        return None, None
    try:
        if info.get("use_preset"):
            char_img, px, py = get_character_layer(
                int(info["pose"]), info.get("layout"),
                bool(info.get("punch_in", False)),
                VIDEO_WIDTH, VIDEO_HEIGHT)
            return char_img, (px, py)
        from core.character_selector import character_target_height, load_and_process_character_image
        target_h = character_target_height(info.get("scale", 0.75), VIDEO_HEIGHT)
        char_img = load_and_process_character_image(int(info["pose"]), target_h)
        return char_img, calculate_character_bbox(
            char_img.size, info.get("position", "bottom_center"),
            VIDEO_WIDTH, VIDEO_HEIGHT)
    except Exception:
        return None, None


def _character_entry_offset_opacity(
    transition: str,
    side: str,
    progress: float,
    img_w: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    full_travel: bool = False,
    fade: bool = True,
) -> tuple[int, int, int]:
    """Offset (dx, dy) e opacita' 0-255 del personaggio al `progress` 0..1.

    Sistema a zone (`full_travel=True`): slide da completamente fuori campo
    (bordo schermo -> posizione preset) in stile motion graphics.
    Legacy v1 (`full_travel=False`): offset corti (320/260px) come storico.

    - slide_from_left/slide_from_right (o slide_side legacy): entrata
      orizzontale (con fade se `fade=True`, altrimenti a piena opacita').
    - slide_up (o slide_from_bottom): risalita dal basso (idem).
    - fade: solo opacita' (con `fade=False` diventa apparizione istantanea).
    - none: gia' in posizione, opaco da subito.

    `fade=False` serve quando il personaggio era gia' visibile nel chunk
    precedente (cambio posa/layout): lo slide resta, ma senza dissolvenza,
    cosi' il personaggio non sparisce mai a meta' video (anti-glitch).
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
    opacity = int(round(255 * eased)) if fade else 255
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
    fade: bool = True,
) -> tuple[int, int, int]:
    """Offset/uscita del personaggio nella finestra di uscita di fine chunk.

    - "slide_down": scende fuori campo basso (il chunk successivo, con lato
      opposto, rientra con slide laterale: niente taglio netto). Con
      `fade=False` resta a piena opacita' mentre scende (solo movimento,
      nessuna sparizione: anti-glitch sui cambi layout).
    - "hold": resta fermo e opaco (stesso personaggio dopo, o jump-cut
      punch-in: taglio invisibile/netto senza dissolvenze).
    - altro ("with_text"): nessuna animazione propria (segue il fade di gruppo,
      usato quando il personaggio deve chiaramente scomparire).
    """
    if mode == _CHAR_EXIT_HOLD:
        return (0, 0, 255)
    if mode == _CHAR_EXIT_SLIDE_DOWN:
        e = ease_in_cubic(clamp01(progress))
        dy = int(round((VIDEO_HEIGHT - base_y) * e))
        opacity = int(round(255 * (1.0 - e))) if fade else 255
        return (0, dy, opacity)
    return (0, 0, 255)


def _punch_of(info) -> bool:
    """Flag punch_in (robusto a None e formati legacy senza chiave)."""
    try:
        return bool(info.get("punch_in", False)) if isinstance(info, dict) else False
    except Exception:
        return False


def _character_identity(info) -> tuple | None:
    """Identita' del personaggio (posa + zona + punch), o None se assente.

    Due chunk con stessa identita' mostrano pixel identici: il taglio tra loro
    e' invisibile e il personaggio resta stabile (anti-glitch).
    """
    try:
        if not isinstance(info, dict) or info.get("pose") is None:
            return None
        zone = info.get("layout") if info.get("use_preset") else info.get("position")
        return (int(info.get("pose")), str(zone), bool(info.get("punch_in", False)))
    except Exception:
        return None


def decide_char_exit_mode(current: dict | None, nxt: dict | None) -> str:
    """Modalita' di uscita del personaggio guardando il chunk successivo.

    Invariante anti-glitch: il personaggio svanisce SOLO quando deve
    chiaramente scomparire (chunk dopo senza personaggio, o fine video).
    In tutti gli altri casi resta visibile fino allo stacco:

    - Chunk dopo senza personaggio (o fine video) -> "with_text" (fade di
      gruppo: sparizione chiara e intenzionale).
    - Punch-in che si accende/spegne -> "hold" (il jump-cut non ha dissolvenze).
    - Stessa identita' (posa+zona+punch) dopo -> "hold" (taglio invisibile).
    - Cambio lato (split_left <-> split_right) -> "slide_down" (scende a piena
      opacita', poi il chunk dopo rientra dal lato opposto).
    - Altri cambi (es. centro <-> split, legacy) -> "hold" (resta fino allo
      stacco, il chunk dopo entra con slide a piena opacita').
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
    if after is None:
        return _CHAR_EXIT_WITH_TEXT  # sparizione (o fine video): fade
    if _punch_of(cur) != _punch_of(after):
        return _CHAR_EXIT_HOLD  # jump-cut: niente transizioni morbide
    if _character_identity(cur) == _character_identity(after):
        return _CHAR_EXIT_HOLD  # stesso personaggio: taglio invisibile
    if bool(cur.get("use_preset")) and bool(after.get("use_preset")):
        try:
            cur_side = preset_side(cur.get("layout"))
            nxt_side = preset_side(after.get("layout"))
        except Exception:
            return _CHAR_EXIT_HOLD
        if {cur_side, nxt_side} == {"left", "right"}:
            return _CHAR_EXIT_SLIDE_DOWN
    return _CHAR_EXIT_HOLD


def decide_char_entry_jump(prev: dict | None, current: dict | None) -> bool:
    """Vero se l'entrata del personaggio dev'essere un jump-cut istantaneo.

    Solo quando il punch-in cambia rispetto al chunk precedente (stacco di
    camera televisivo: nessuna slide, scala nuova da subito) o il video inizia
    gia' in punch-in. Accetta chunk grezzi o info risolte; mai eccezioni.
    """
    try:
        cur = current if isinstance(current, dict) and "pose" in current and "use_preset" in current \
            else resolve_chunk_layout(current)
    except Exception:
        return False
    if cur is None or not _punch_of(cur):
        return False
    try:
        before = prev if isinstance(prev, dict) and "pose" in prev and "use_preset" in prev \
            else resolve_chunk_layout(prev)
    except Exception:
        return True
    if before is None:
        return True
    return _punch_of(before) != _punch_of(cur)


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
    text_safe_area: tuple[int, int, int, int] | None = None,
    char_entry_jump: bool = False,
    char_entry_fade: bool = True,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[dict]:
    """Genera la sequenza di frame PNG per un chunk con animazione per-parola.

    Args:
        chunk: {"text", "start", "end", "words": [{"word","start","end",...}]}.
            Se "words" manca, viene ricostruita (vedi `enrich_chunk_words`).
            Puo' contenere pose/layout/punch_in del personaggio
            (vedi core/character_selector.py): il personaggio (mezzo busto,
            mai figura intera) viene disegnato sotto il testo (Z-index: sfondo
            ffmpeg < personaggio < sottotitoli, con pill ad alto contrasto per
            il punch-in) con slide rapida da fuori campo (0.2s).
            Con Semantic Typography Engine v1 puo' contenere anche
            "styled_words" (vedi core/text_tagger.py) + "typography_niche":
            in quel caso il rendering usa 3 font/colori/dimensioni per nicchia
            (base/impact/accent) con stroke nero + drop shadow su ogni parola.
        background_color: hex #RRGGBB da theme.py (frame restano trasparenti,
            lo sfondo e' applicato da ffmpeg; param tenuto per compatibilita').
        text_color: hex #RRGGBB da theme.py (accetta anche tupla RGBA).
        keyword_colors: {parola_normalizzata: hex} da keywords.py
            (accetta anche valori RGBA come quelli reali di `extract_keywords`).
            Con tipografia attiva, l'impact usa il colore highlight del preset
            (la palette keyword resta come fallback legacy quando il tagging manca).
        output_dir: cartella dove salvare i frame PNG del chunk.
        chunk_index: per naming file univoco.
        fps: frame rate (default: VIDEO_FPS da config.py).
        safe_area: Text Safe Area esplicita (x_min, y_min, x_max, y_max);
            se assente si usa quella del preset del chunk, altrimenti il
            centro schermo storico. Il wrapping segue la larghezza del box.
        char_exit_mode: "with_text" (segue il fade di gruppo), "slide_down"
            (esce in basso a fine chunk, 0.2s) o "hold" (resta opaco fino al
            taglio: jump-cut punch-in o stesso layout+posa). Di solito calcolato
            con `decide_char_exit_mode` guardando il chunk successivo
            (vedi `render_all_chunks_animated`).
        char_exit_duration: durata in secondi della finestra di uscita
            per "slide_down" (default 0.20s).
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.
        char_entry_jump: True per entrata jump-cut istantanea (punch_in che si
            accende, o stesso identico personaggio del chunk precedente:
            taglio invisibile). Di solito calcolato con `decide_char_entry_jump`
            guardando il chunk precedente.
        char_entry_fade: True per dissolvenza in entrata (prima apparizione:
            il personaggio appare con stile); False quando il personaggio era
            gia' visibile nel chunk precedente (slide a piena opacita', mai
            sparizioni a meta' video). Di solito calcolato in
            `render_all_chunks_animated` guardando il chunk precedente.
        typography_niche: nicchia esplicita (override di chunk["typography_niche"]).
        typography_preset: preset dict esplicito (da core/typography_presets.get_preset).

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
    explicit_box = text_safe_area if text_safe_area is not None else safe_area
    if explicit_box is not None:
        try:
            area = (int(explicit_box[0]), int(explicit_box[1]),
                    int(explicit_box[2]), int(explicit_box[3]))
            area = area if area[2] > area[0] and area[3] > area[1] else None
        except (TypeError, ValueError, IndexError):
            area = None
        needs_pill, font_scale = False, 1.0
    elif use_preset:
        preset = char_info.get("layout")
        area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
        needs_pill = preset_needs_text_background(preset)
        font_scale = preset_font_scale(preset)
    else:
        area, needs_pill, font_scale = None, False, 1.0

    # --- Semantic Typography: path multi-style o legacy single-font ---
    # Look pulito: stroke sempre 0 (nessun contorno nero), ombra solo se
    # abilitata esplicitamente da config (default OFF).
    use_typography = _is_typography_chunk(chunk)
    typo_preset: dict | None = None
    typo_fonts: dict | None = None
    typo_fills: dict | None = None
    typo_stroke_color: tuple = (0, 0, 0, 0)
    typo_stroke_width: int = 0
    typo_shadow_offset = None
    typo_shadow_fill = None
    styled_words: list[dict] | None = None

    if use_typography:
        try:
            typo_preset = _resolve_typography_preset(chunk, typography_niche, typography_preset)
        except Exception:
            use_typography = False
            typo_preset = None
    if use_typography and typo_preset is not None:
        # Costruisci styled_words con timing (chunk già arricchito da text_tagger;
        # se manca, deriva da words con is_keyword -> impact).
        raw_styled = chunk.get("styled_words")
        try:
            uppercase_impact = bool(typo_preset.get("impact_uppercase", True))
        except Exception:
            uppercase_impact = True
        if isinstance(raw_styled, list) and raw_styled:
            styled_words = []
            # Mappa timing da words (ordine identico nella pipeline normale).
            for i, s in enumerate(raw_styled):
                if not isinstance(s, dict):
                    continue
                style = s.get("style", "base")
                if style not in ("base", "impact", "accent"):
                    style = "base"
                word_text = str(s.get("word", ""))
                if not word_text.strip():
                    continue
                try:
                    st = float(s.get("start", words[i]["start"] if i < len(words) else chunk.get("start", 0.0)))
                    en = float(s.get("end", words[i]["end"] if i < len(words) else chunk.get("end", 0.0)))
                except (TypeError, ValueError, KeyError, IndexError):
                    st = float(words[i]["start"]) if i < len(words) else float(chunk.get("start", 0.0))
                    en = float(words[i]["end"]) if i < len(words) else float(chunk.get("end", 0.0))
                display = str(s.get("display", word_text.upper() if (style == "impact" and uppercase_impact) else word_text))
                if style == "impact" and uppercase_impact:
                    display = display.upper()
                styled_words.append({
                    "word": word_text, "display": display, "style": style,
                    "start": st, "end": en,
                    "is_keyword": style == "impact",
                })
        if not styled_words:
            # Deriva da words legacy: keyword -> impact, resto base.
            styled_words = []
            for w in words:
                style = "impact" if w.get("is_keyword") else "base"
                disp = str(w["word"]).upper() if (style == "impact" and uppercase_impact) else str(w["word"])
                styled_words.append({
                    "word": str(w["word"]), "display": disp, "style": style,
                    "start": float(w["start"]), "end": float(w["end"]),
                    "is_keyword": bool(w.get("is_keyword", False)),
                })
        if not styled_words:
            use_typography = False
    if use_typography and typo_preset is not None and styled_words:
        typo_fonts = _load_typography_fonts(typo_preset, font_scale)
        # Attribuzione colori coerente: tema (base) + sfondo (contrasto) +
        # palette keyword del video (fallback impact). Mai contorno nero.
        typo_fills = _styled_fills(
            typo_preset,
            base_override=text_color,
            background_color=background_color,
            keyword_colors=keyword_colors,
        )
        typo_stroke_color = (0, 0, 0, 0)
        try:
            # Lo stroke resta configurabile ma di default è 0 (look pulito).
            # Valori >0 sono permessi solo se l'utente li forza esplicitamente.
            cfg_w = int(typo_preset.get("stroke_width", TYPOGRAPHY_STROKE_WIDTH))
        except (TypeError, ValueError):
            cfg_w = TYPOGRAPHY_STROKE_WIDTH
        try:
            cfg_w = int(TYPOGRAPHY_STROKE_WIDTH) if str(TYPOGRAPHY_STROKE_WIDTH).strip() != "0" else 0
        except (TypeError, ValueError):
            cfg_w = 0
        typo_stroke_width = max(0, cfg_w if cfg_w else 0)
        if not TYPOGRAPHY_SHADOW_ENABLED:
            typo_shadow_offset = None
            typo_shadow_fill = None
        else:
            try:
                sh = typo_preset.get("shadow", {})
                _off = sh.get("offset", tuple(TYPOGRAPHY_SHADOW_OFFSET))
                _fill = sh.get("fill", tuple(TYPOGRAPHY_SHADOW_FILL))
                typo_shadow_offset = tuple(_off) if _off else None
                typo_shadow_fill = tuple(_fill) if _fill else None
                # Ombra "vuota" (0,0 / alpha 0) = disabilitata di fatto.
                if typo_shadow_offset == (0, 0):
                    typo_shadow_offset = None
                try:
                    if typo_shadow_fill is not None and len(typo_shadow_fill) >= 4 and int(typo_shadow_fill[3]) <= 0:
                        typo_shadow_fill = None
                except Exception:
                    pass
                if typo_shadow_offset is None or typo_shadow_fill is None:
                    typo_shadow_offset = None
                    typo_shadow_fill = None
            except Exception:
                typo_shadow_offset = None
                typo_shadow_fill = None
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_styled_layout(styled_words, typo_fonts, max_text_width, area=area)
        if len(layout) != len(styled_words):
            raise TextAnimationError("Layout/words fuori sync: conteggio diverso.")
        # Fills per parola per ruolo (la tipografia vince sulla palette keyword).
        fills = [typo_fills.get(layout[i].get("style", "base"), typo_fills["base"]) for i in range(len(layout))]
        word_starts = [float(s["start"]) for s in styled_words]
        # Per il loop di rendering riusa `words` come alias di styled (is_keyword=impact).
        words = [
            {"word": s["display"], "start": s["start"], "end": s["end"],
             "is_keyword": s["style"] == "impact", "style": s["style"]}
            for s in styled_words
        ]
    else:
        use_typography = False
        # --- Pre-calcolo layout legacy (una sola volta, fisso per tutto il chunk) ---
        try:
            text_font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale))))
        except (TypeError, ValueError):
            text_font_size = SUBTITLE_FONT_SIZE
        font = load_font(text_font_size)
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
    # Override narrativi per atto (hook più scattante e pop marcato;
    # chiavi assenti = default legacy, piena retrocompatibilità).
    try:
        mult = float(chunk.get("anim_entry_mult", 1.0))
        if 0.3 <= mult <= 1.5:
            entry_dur = max(0.01, entry_dur * mult)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        pop = float(chunk.get("anim_pop_from", scale_from))
        if 0.1 <= pop <= 1.0:
            scale_from = pop
    except (TypeError, ValueError, AttributeError):
        pass

    # --- Personaggio del chunk (layer UNA volta, riusato in ogni frame) ---
    # Z-index sui frame: 1. sfondo (ffmpeg) / 2. personaggio / 2.5 pill / 3. testo.
    char_img, char_base_xy = _load_chunk_character_layer(char_info)
    if char_img is not None and char_base_xy is not None and char_info is not None:
        char_transition = char_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(char_info)
        char_full_travel = bool(use_preset)
        char_entry_dur = max(0.01, _CHARACTER_ZONE_ENTRY_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        char_entry_jump = bool(char_entry_jump)
        char_entry_fade = bool(char_entry_fade)
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
        # Anti-glitch: la dissolvenza scatta SOLO in apparizione (entry_fade)
        # o sparizione (with_text); nei cambi resta sempre visibile.
        if char_img is not None and char_base_xy is not None:
            if char_entry_jump:
                # Jump-cut istantaneo (punch-in o continuazione identica).
                edx, edy, entry_opacity = 0, 0, 255
            else:
                entry_prog = clamp01((t - chunk_start) / char_entry_dur)
                edx, edy, entry_opacity = _character_entry_offset_opacity(
                    char_transition, char_side, entry_prog,
                    char_img.size[0], char_base_xy[0], char_base_xy[1],
                    full_travel=char_full_travel,
                    fade=char_entry_fade,
                )
            if char_exit_mode == _CHAR_EXIT_HOLD:
                char_opacity, xdx, xdy = entry_opacity, 0, 0
            elif char_exit_mode == _CHAR_EXIT_SLIDE_DOWN and char_exit_dur > 0 \
                    and t >= chunk_end - char_exit_dur:
                xprog = clamp01((t - (chunk_end - char_exit_dur)) / char_exit_dur)
                xdx, xdy, exit_opacity = _character_exit_offset_opacity(
                    _CHAR_EXIT_SLIDE_DOWN, xprog, char_base_xy[1], fade=False)
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
            if use_typography:
                role = item.get("style", w.get("style", "base"))
                try:
                    wfont = typo_fonts.get(role, typo_fonts.get("base"))
                except Exception:
                    wfont = typo_fonts.get("base") if isinstance(typo_fonts, dict) else font
                _render_styled_scaled_word(
                    frame_img, w["word"], item["x"], item["y"],
                    item["width"], item["height"], wfont,
                    fills[wi], typo_stroke_color, typo_stroke_width,
                    typo_shadow_offset, typo_shadow_fill,
                    opacity=opacity, scale=scale,
                )
            else:
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


def _is_cta_card_chunk(chunk: dict | None) -> bool:
    """Vero se il chunk è parte di una CTA card persistente (karaoke)."""
    try:
        return bool((chunk or {}).get("cta_card", False))
    except Exception:
        return False


def generate_cta_card_frames(
    cta_chunks: list[dict],
    chunk_states: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    start_index: int = 0,
    fps: int = VIDEO_FPS,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[list[dict]]:
    """Card CTA persistente: messaggio finale fisso con reveal karaoke.

    A differenza dei chunk normali (ogni caption appare e scompare), la card
    mostra l'INTERO messaggio CTA per tutta la sezione: le parole già dette
    restano visibili, la parola corrente entra con pop, le future sono nascoste.
    Il personaggio è bloccato (stessa identità per lock narrativo) e tutto
    svanisce insieme solo alla fine (un'unica dissolvenza, zero flicker).

    Args:
        cta_chunks: chunk CTA consecutivi (stessa sezione, time-ordered).
        chunk_states: per chunk {"exit_mode","entry_jump","entry_fade"} come
            calcolati in render_all_chunks_animated (lookahead/lookbehind).
        Gli altri parametri come generate_animated_chunk_frames.

    Returns:
        Lista (una per chunk) di liste frame {"image_path","start","end"}.
        Non solleva per input vuoti (liste vuote); solleva TextAnimationError
        solo per timestamp invalidi come il path normale.
    """
    if not cta_chunks:
        return []
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    keyword_colors = keyword_colors or {}

    # --- Parole di sezione (timing originali, mai alterati) ---
    use_typography = all(_is_typography_chunk(c) for c in cta_chunks)
    typo_preset: dict | None = None
    if use_typography:
        try:
            typo_preset = _resolve_typography_preset(
                cta_chunks[0], typography_niche, typography_preset)
        except Exception:
            use_typography = False
            typo_preset = None
    try:
        uppercase_impact = bool((typo_preset or {}).get("impact_uppercase", True))
    except Exception:
        uppercase_impact = True

    section: list[dict] = []  # {word,display,style,start,end,is_keyword}
    if use_typography and typo_preset is not None:
        for ch in cta_chunks:
            for s in (ch.get("styled_words") or []):
                if not isinstance(s, dict) or not str(s.get("word", "")).strip():
                    continue
                style = s.get("style", "base")
                if style not in ("base", "impact", "accent"):
                    style = "base"
                section.append({
                    "word": str(s.get("word", "")),
                    "display": str(s.get("display") or s.get("word", "")),
                    "style": style,
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("end", 0.0)),
                    "is_keyword": style == "impact",
                })
    else:
        use_typography = False
        for ch in cta_chunks:
            for w in enrich_chunk_words(ch, keyword_colors):
                style = "impact" if w.get("is_keyword") else "base"
                section.append({
                    "word": str(w.get("word", "")),
                    "display": str(w.get("word", "")),
                    "style": style,
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0)),
                    "is_keyword": bool(w.get("is_keyword", False)),
                })
    if not section:
        return [[] for _ in cta_chunks]
    section.sort(key=lambda s: (s["start"], s["end"]))

    # --- Area testo CTA (centro fisso) + pill badge ---
    first_info = _character_info_from_chunk(cta_chunks[0])
    use_preset = bool(first_info is not None and first_info.get("use_preset"))
    explicit_box = text_safe_area if text_safe_area is not None else safe_area
    if explicit_box is not None:
        try:
            area = (int(explicit_box[0]), int(explicit_box[1]),
                    int(explicit_box[2]), int(explicit_box[3]))
            area = area if area[2] > area[0] and area[3] > area[1] else None
        except (TypeError, ValueError, IndexError):
            area = None
        font_scale = 1.0
    elif use_preset:
        area = preset_safe_area(first_info.get("layout"), VIDEO_WIDTH, VIDEO_HEIGHT)
        try:
            font_scale = float(preset_font_scale(first_info.get("layout")))
        except Exception:
            font_scale = 1.0
    else:
        area, font_scale = None, 1.0
    needs_pill = True  # la card è un badge intenzionale, sempre ancorato
    card_scale = 0.92  # la card contiene più parole: leggermente più compatta

    # --- Font/fill di sezione (una volta sola: niente cambi a metà card) ---
    if use_typography and typo_preset is not None:
        typo_fonts = _load_typography_fonts(typo_preset, font_scale * card_scale)
        typo_fills = _styled_fills(
            typo_preset, base_override=text_color,
            background_color=background_color, keyword_colors=keyword_colors)
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_styled_layout(section, typo_fonts, max_text_width, area=area)
        if len(layout) != len(section):
            raise TextAnimationError("Layout/words fuori sync nella CTA card.")
        fills = [typo_fills.get(layout[i].get("style", "base"), typo_fills["base"])
                 for i in range(len(layout))]
        stroke_color, stroke_width = (0, 0, 0, 0), 0
        shadow_off, shadow_fill = None, None
    else:
        use_typography = False
        try:
            text_font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale) * card_scale)))
        except (TypeError, ValueError):
            text_font_size = SUBTITLE_FONT_SIZE
        font = load_font(text_font_size)
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_word_layout([s["word"] for s in section], font, max_text_width, area=area)
        if len(layout) != len(section):
            raise TextAnimationError("Layout/words fuori sync nella CTA card.")
        base_rgba = _to_rgba(text_color, SUBTITLE_COLOR)
        fills = [_resolve_word_fill(normalize_word(s["word"]), base_rgba, keyword_colors)
                 for s in section]
        typo_fonts = None

    entry_dur = max(0.01, float(TEXT_ANIMATION_ENTRY_DURATION))
    try:
        last_exit = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    except (TypeError, ValueError):
        last_exit = 0.15
    try:
        scale_from = float(KEYWORD_ENTRY_SCALE_FROM)
        if not (0.1 <= scale_from <= 1.0):
            scale_from = 0.7
    except (TypeError, ValueError):
        scale_from = 0.7

    # --- Personaggio bloccato (layer unico per tutta la card) ---
    char_img, char_base_xy = _load_chunk_character_layer(first_info)
    if char_img is not None and char_base_xy is not None and first_info is not None:
        char_transition = first_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(first_info)
        char_full_travel = bool(use_preset)
        char_entry_dur = max(0.01, _CHARACTER_ZONE_ENTRY_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
    else:
        char_base_xy = None
    try:
        char_exit_dur = max(0.0, float(_CHARACTER_ZONE_EXIT_DURATION))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION

    os.makedirs(output_dir, exist_ok=True)
    per_chunk_frames: list[list[dict]] = []
    for k, ch in enumerate(cta_chunks):
        try:
            cs = float(ch.get("start", section[0]["start"]))
            ce = float(ch.get("end", section[-1]["end"]))
        except (TypeError, ValueError) as e:
            raise TextAnimationError(f"Timestamp CTA non validi: {e}")
        if ce <= cs:
            ce = cs + 0.1
        is_last = (k == len(cta_chunks) - 1)
        exit_dur = last_exit if is_last else 0.0  # dissolvenza SOLO alla fine
        try:
            st = chunk_states[k] if k < len(chunk_states) else {}
            exit_mode = st.get("char_exit_mode", _CHAR_EXIT_WITH_TEXT)
            entry_jump = bool(st.get("char_entry_jump", False))
            entry_fade = bool(st.get("char_entry_fade", k == 0))
        except Exception:
            exit_mode, entry_jump, entry_fade = _CHAR_EXIT_WITH_TEXT, False, k == 0
        if exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
            exit_mode = _CHAR_EXIT_WITH_TEXT

        num_frames = max(1, int(math.ceil((ce - cs) * fps)))
        step = 1.0 / float(fps)
        frames: list[dict] = []
        for fi in range(num_frames):
            t = cs + fi * step
            if t >= ce:
                t = ce - 1e-6
            frame_end = min(t + step, ce)
            if exit_dur > 0 and t >= ce - exit_dur:
                exit_factor = 1.0 - ease_in_cubic(clamp01((t - (ce - exit_dur)) / exit_dur))
            else:
                exit_factor = 1.0
            frame_img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
            if char_img is not None and char_base_xy is not None:
                if entry_jump:
                    edx, edy, entry_opacity = 0, 0, 255
                else:
                    entry_prog = clamp01((t - cs) / char_entry_dur)
                    edx, edy, entry_opacity = _character_entry_offset_opacity(
                        char_transition, char_side, entry_prog,
                        char_img.size[0], char_base_xy[0], char_base_xy[1],
                        full_travel=char_full_travel, fade=entry_fade)
                if exit_mode == _CHAR_EXIT_HOLD:
                    cop, xdx, xdy = entry_opacity, 0, 0
                elif exit_mode == _CHAR_EXIT_SLIDE_DOWN and char_exit_dur > 0 \
                        and t >= ce - char_exit_dur:
                    xp = clamp01((t - (ce - char_exit_dur)) / char_exit_dur)
                    xdx, xdy, xop = _character_exit_offset_opacity(
                        _CHAR_EXIT_SLIDE_DOWN, xp, char_base_xy[1], fade=False)
                    cop = min(entry_opacity, xop)
                else:
                    cop, xdx, xdy = int(round(entry_opacity * exit_factor)), 0, 0
                _paste_character_frame(
                    frame_img, char_img,
                    char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy, cop)
            if needs_pill:
                draw_text_background(frame_img, layout)
            for wi, w in enumerate(section):
                if t < w["start"]:
                    continue  # parola futura: nascosta (reveal karaoke)
                local = clamp01((t - w["start"]) / entry_dur)
                if w["is_keyword"]:
                    eased = ease_out_back(local)
                    opacity = int(round(255 * min(1.0, max(0.0, eased))))
                    scale = max(0.05, scale_from + (1.0 - scale_from) * eased)
                else:
                    opacity = int(round(255 * ease_out_cubic(local)))
                    scale = 1.0
                opacity = int(round(opacity * exit_factor))
                if opacity <= 0:
                    continue
                item = layout[wi]
                if use_typography:
                    role = item.get("style", w.get("style", "base"))
                    try:
                        wfont = typo_fonts.get(role, typo_fonts.get("base"))
                    except Exception:
                        wfont = typo_fonts.get("base")
                    _render_styled_scaled_word(
                        frame_img, w["display"], item["x"], item["y"],
                        item["width"], item["height"], wfont,
                        fills[wi], stroke_color, stroke_width,
                        shadow_off, shadow_fill, opacity=opacity, scale=scale)
                else:
                    _render_scaled_word(
                        frame_img, w["word"], item["x"], item["y"],
                        item["width"], item["height"], font,
                        fills[wi], SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
                        opacity=opacity, scale=scale)
            fname = f"chunk_{start_index + k:04d}_frame_{fi:05d}.png"
            fpath = os.path.join(output_dir, fname)
            frame_img.save(fpath, compress_level=1)
            frames.append({"image_path": fpath, "start": t, "end": frame_end})
        per_chunk_frames.append(frames)
    return per_chunk_frames


def render_all_chunks_animated(
    chunks: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    fps: int = VIDEO_FPS,
    on_chunk=None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[dict]:
    """Genera i frame animati per tutti i chunk.

    Args:
        chunks: lista di chunk con "text"/"start"/"end"/"words" (+ metadati
            character opzionali: pose/layout/transition_in, e con tipografia
            attiva anche "styled_words" + "typography_niche" da core/text_tagger.py).
        background_color: hex da theme.py (tenuto per compatibilita').
        text_color: hex o RGBA del testo base.
        keyword_colors: {norm: colore} (hex o RGBA).
        output_dir: cartella dei frame PNG.
        fps: frame rate.
        on_chunk: callback opzionale (idx, totale) a fine chunk, per logging GUI.
        safe_area: Text Safe Area esplicita per TUTTI i chunk (override dei
            preset; None = preset del singolo chunk o centro schermo).
        text_safe_area: alias di safe_area (ha precedenza).
        typography_niche: nicchia esplicita (override per tutti i chunk senza niche propria).
        typography_preset: preset dict esplicito (da core/typography_presets.get_preset).

    Il lookahead sul chunk successivo decide l'uscita del personaggio
    (vedi `decide_char_exit_mode`): sparizione solo se il personaggio deve
    chiaramente scomparire, altrimenti hold/slide_down a piena visibilita'.
    Il lookbehind sul chunk precedente decide l'entrata: dissolvenza solo
    alla prima apparizione, slide a piena opacita' nei cambi, jump-cut
    istantaneo per punch-in e continuazioni identiche (taglio invisibile).
    Risultato: il personaggio resta stabile finche' non deve scomparire.

    Returns:
        Lista di chunk arricchiti: {**chunk, "frames": [...], "frame_paths": [...],
        "clip_start": start, "clip_end": end}.
    """
    enriched_all: list[dict] = []
    total = len(chunks)
    # Stati personaggio per chunk (lookahead/lookbehind), calcolati una volta:
    # servono sia al path normale sia alla CTA card (stessa stabilita').
    states: list[dict] = []
    for i, chunk in enumerate(chunks):
        nxt = chunks[i + 1] if i + 1 < total else None
        prev = chunks[i - 1] if i - 1 >= 0 else None
        exit_mode = decide_char_exit_mode(chunk, nxt)
        try:
            cur_info = _character_info_from_chunk(chunk)
            prev_info = _character_info_from_chunk(prev) if prev is not None else None
        except Exception:
            cur_info, prev_info = None, None
        try:
            # Stesso identico personaggio del chunk prima: taglio invisibile
            # (niente replay dell'entrata: resterebbe un blink a ogni stacco).
            same_as_prev = (
                cur_info is not None and prev_info is not None
                and _character_identity(cur_info) == _character_identity(prev_info)
            )
            entry_jump = bool(same_as_prev or decide_char_entry_jump(prev, chunk))
            # Dissolvenza in entrata SOLO alla prima apparizione: se il
            # personaggio era gia' visibile, entra a piena opacita'.
            entry_fade = prev_info is None
        except Exception:
            entry_jump, entry_fade = False, True
        states.append({
            "char_exit_mode": exit_mode,
            "char_entry_jump": entry_jump,
            "char_entry_fade": entry_fade,
        })
    i = 0
    while i < total:
        chunk = chunks[i]
        # CTA card: run consecutivi di chunk card -> un'unica card persistente
        # (stessa sezione: niente buchi, niente modi misti nel run).
        if _is_cta_card_chunk(chunk):
            try:
                section_id = (chunk or {}).get("cta_section_id", i)
            except Exception:
                section_id = i
            run = [i]
            j = i + 1
            while j < total and _is_cta_card_chunk(chunks[j]):
                try:
                    same_section = (chunks[j] or {}).get("cta_section_id", j) == section_id
                except Exception:
                    same_section = True
                if not same_section:
                    break
                run.append(j)
                j += 1
            run_chunks = [chunks[k] for k in run]
            run_states = [states[k] for k in run]
            try:
                run_frames = generate_cta_card_frames(
                    run_chunks, run_states, background_color, text_color,
                    keyword_colors or {}, output_dir, run[0], fps,
                    safe_area=safe_area, text_safe_area=text_safe_area,
                    typography_niche=typography_niche,
                    typography_preset=typography_preset,
                )
            except TextAnimationError:
                raise
            except Exception as e:
                raise TextAnimationError(f"CTA card fallita: {e}")
            for pos, k in enumerate(run):
                frames = run_frames[pos] if pos < len(run_frames) else []
                enriched_all.append({
                    **chunks[k],
                    "frames": frames,
                    "frame_paths": [f["image_path"] for f in frames],
                    "clip_start": chunks[k].get("start"),
                    "clip_end": chunks[k].get("end"),
                })
                if on_chunk is not None:
                    try:
                        on_chunk(k + 1, total)
                    except Exception:
                        pass
            i = j
            continue
        st = states[i]
        frames = generate_animated_chunk_frames(
            chunk, background_color, text_color,
            keyword_colors or {}, output_dir, i, fps,
            safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
            text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
            char_entry_fade=st["char_entry_fade"],
            typography_niche=typography_niche, typography_preset=typography_preset,
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
        i += 1
    return enriched_all
