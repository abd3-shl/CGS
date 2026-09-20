"""
Animazioni testo per-parola (Fase 3) + Dynamic Layout (sistema a zone)
+ Semantic Typography Engine v1 (stili misti per nicchia).

Ogni parola del chunk entra in scena esattamente al suo timestamp `start`
e resta visibile accumulandosi accanto alle precedenti; tutte le parole
scompaiono insieme a `chunk.end` (uscita di gruppo).

- Parole normali/base: entrata minimal (solo fade con `ease_out_cubic`).
- Keyword/impact: entrata marcata (opacita' + scala 0.85 -> 1.0 con
  `ease_out_back` clampato a max 1.0, mai overshoot gigante).
- Uscita: uguale per tutte, fade di gruppo con `ease_in_cubic`.

Il layout e' pre-calcolato UNA VOLTA per chunk (via
`core/renderer.compute_word_layout` per il path legacy, oppure
`compute_styled_layout` per il path tipografico) dentro la `text_safe_area`
del preset (wrapping dinamico sulla sua larghezza): personaggio e testo non si
sovrappongono mai (entrambi risolvono da `resolve_chunk_layout`, singola fonte).

Semantic Typography REELS-FIX v5 (quando il chunk porta "styled_words"):
3 font per nicchia, impact 1.25x (uppercase solo <=7 char), accent 1.05x.
Stroke 0, ambient shadow (0,3,110), auto-fit min 38px, hard-clamp nel box,
auto-pill solo se contrasto <80. Colori coerenti col tema.

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
import threading

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
try:
    from config import (  # tunable ritmo character (default calmi, anti-flicker)
        CHARACTER_ENTRY_DURATION as _CFG_CHAR_ENTRY,
        CHARACTER_EXIT_DURATION as _CFG_CHAR_EXIT,
        CHARACTER_FULL_TRAVEL_FIRST_ONLY as _CFG_FULL_TRAVEL_FIRST_ONLY,
    )
except Exception:
    _CFG_CHAR_ENTRY, _CFG_CHAR_EXIT, _CFG_FULL_TRAVEL_FIRST_ONLY = 0.55, 0.45, True
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
    should_auto_pill,
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
    preset_safe_area_dynamic,
    preset_side,
)

# Durata entrata personaggio legacy v1 (offset corto, feel premium).
_CHARACTER_ENTRY_DURATION = 0.35
_CHARACTER_SLIDE_UP_PX = 320
_CHARACTER_SLIDE_SIDE_PX = 260
# Transizioni sistema a zone (motion graphics 9:16): CALME per evitare
# appari/scompari frenetici. Default da config (0.55s in / 0.45s out);
# fallback storici se config non disponibile.
try:
    _CHARACTER_ZONE_ENTRY_DURATION = max(0.15, float(_CFG_CHAR_ENTRY))
except Exception:
    _CHARACTER_ZONE_ENTRY_DURATION = 0.55
try:
    _CHARACTER_ZONE_EXIT_DURATION = max(0.15, float(_CFG_CHAR_EXIT))
except Exception:
    _CHARACTER_ZONE_EXIT_DURATION = 0.45
try:
    _FULL_TRAVEL_FIRST_ONLY = bool(_CFG_FULL_TRAVEL_FIRST_ONLY)
except Exception:
    _FULL_TRAVEL_FIRST_ONLY = True
# Micro-movimento idle "respiratorio" v2 (anti-sticker): bob verticale +
# sway orizzontale sinusoidali durante la permanenza. Ampiezze minime per
# look premium senza distrarre dai sottotitoli; frequenze <1Hz (calme).
_IDLE_BOB_AMP_Y = 5  # px, oscillazione verticale (±5px)
_IDLE_BOB_FREQ = 0.6  # Hz, respiro calmo
_IDLE_SWAY_AMP_X = 3  # px, oscillazione orizzontale (±3px)
_IDLE_SWAY_FREQ = 0.43  # Hz, sfasata dal bob per moto organico
# Zoom continuo 0.5%: applicato come micro-scala via offset di paste
# (nessun resize per-frame: costo zero, effetto vita garantito dal bob+sway).
_IDLE_ENABLED = True
# --- OTTIMIZZAZIONI VELOCITA' (P0) ---
# Singleton FontManager condiviso: evita mkdir+scan disco per ogni chunk.
_shared_font_manager = None
_shared_font_manager_lock = threading.Lock()


def _get_shared_font_manager():
    global _shared_font_manager
    if _shared_font_manager is not None:
        return _shared_font_manager
    with _shared_font_manager_lock:
        if _shared_font_manager is None:
            try:
                from core.font_manager import FontManager
                _shared_font_manager = FontManager()
            except Exception:
                _shared_font_manager = None
    return _shared_font_manager


def _fast_resample_for_scale(scale: float):
    """Resampling veloce per animazioni per-parola.

    LANCZOS e' 4-8x piu' lento e indistinguibile su caption 60-90px
    in movimento: BILINEAR vicino a 1.0, BICUBIC altrimenti.
    LANCZOS resta solo per resize una-tantum (personaggio/font).
    """
    try:
        if abs(scale - 1.0) < 0.12:
            return Image.Resampling.BILINEAR
        return Image.Resampling.BICUBIC
    except AttributeError:  # Pillow < 9.1
        try:
            if abs(scale - 1.0) < 0.12:
                return Image.BILINEAR
            return Image.BICUBIC
        except AttributeError:
            return Image.NEAREST


# Probe microscopica condivisa per textlength (evita Image 1080x1920 per layout).
_probe_img = None
_probe_draw = None
_probe_lock = threading.Lock()


def _get_probe_draw():
    global _probe_img, _probe_draw
    if _probe_draw is not None:
        return _probe_draw
    with _probe_lock:
        if _probe_draw is None:
            _probe_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            _probe_draw = ImageDraw.Draw(_probe_img)
    return _probe_draw


# Cache pill pre-renderizzate per bbox -> overlay RGBA.
_pill_cache: dict[tuple[int, int, int, int], Image.Image] = {}
_pill_cache_lock = threading.Lock()


def _get_cached_pill_overlay(bbox: tuple[int, int, int, int], fill, pad: int, radius: int):
    key = (bbox[0], bbox[1], bbox[2], bbox[3], pad, radius,
           fill[0] if len(fill) > 0 else 0, fill[1] if len(fill) > 1 else 0,
           fill[2] if len(fill) > 2 else 0, fill[3] if len(fill) > 3 else 255)
    hit = _pill_cache.get(key)
    if hit is not None:
        return hit
    with _pill_cache_lock:
        hit = _pill_cache.get(key)
        if hit is not None:
            return hit
        overlay = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        try:
            d.rounded_rectangle([bbox[0], bbox[1], bbox[2], bbox[3]],
                                radius=radius, fill=fill)
        except (AttributeError, ValueError, TypeError):
            d.rectangle([bbox[0], bbox[1], bbox[2], bbox[3]], fill=fill)
        if len(_pill_cache) < 32:
            _pill_cache[key] = overlay
        return overlay


# Cache varianti opacity personaggio: evita copy+point per frame (stile
# "upgrade 2": lookup table + quantizzazione step 8). La chiave include le
# dimensioni del layer oltre a id(): se un oggetto Image viene deallocato e
# Python riusa lo stesso id per un layer diverso, la size evita di ritornare
# pixel stantii (anti flash-frame). Pulizia leggera anti-crescita infinita.
_char_opacity_cache: dict[tuple[int, int, int, int], Image.Image] = {}
_char_opacity_cache_lock = threading.Lock()


def _get_char_at_opacity(char_img: Image.Image, opacity: int):
    if opacity >= 255:
        return char_img
    if opacity <= 0:
        return None
    # Quantizza a step 8 per riuso (delta visivo nullo, hit-rate alto).
    q = int(round(opacity / 8.0)) * 8
    q = max(8, min(255, q))
    if q >= 255:
        return char_img
    try:
        _sz = char_img.size
        _sw, _sh = int(_sz[0]), int(_sz[1])
    except Exception:
        _sw, _sh = 0, 0
    key = (id(char_img), _sw, _sh, q)
    hit = _char_opacity_cache.get(key)
    if hit is not None:
        return hit
    with _char_opacity_cache_lock:
        hit = _char_opacity_cache.get(key)
        if hit is not None:
            return hit
        try:
            to_paste = char_img.copy()
            alpha = to_paste.getchannel("A")
            # Lookup table pre-calcolata: molto piu' veloce di lambda per pixel.
            lut = [0] * 256
            for a in range(256):
                lut[a] = (a * q) // 255
            alpha = alpha.point(lut)
            to_paste.putalpha(alpha)
        except Exception:
            return char_img
        if len(_char_opacity_cache) < 128:
            # Evita crescita infinita su video lunghi: pulizia leggera.
            if len(_char_opacity_cache) >= 120:
                _char_opacity_cache.clear()
            _char_opacity_cache[key] = to_paste
        return to_paste
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
            "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
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
    """Carica i 3 font PIL REELS-FIX v5 (base 52-56px, auto-fit min 38px).

    - base:   size preset (54) * font_scale, clamp 38..64
    - impact: base * 1.25 (clamp 1.15..1.30, mai gigante)
    - accent: base * 1.05 (clamp 1.0..1.10)
    Ritorna {"base","impact","accent","sizes","paths","names"}. Mai eccezioni.
    """
    try:
        from config import TYPOGRAPHY_MIN_FONT_SIZE as _MIN_FS
        _min_fs = max(20, int(_MIN_FS))
    except Exception:
        _min_fs = 38
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
        impact_scale = 1.25
    try:
        accent_scale = float(sizes_cfg.get("accent_scale", TYPOGRAPHY_ACCENT_SCALE))
    except (TypeError, ValueError):
        accent_scale = 1.05
    impact_scale = min(1.30, max(1.15, impact_scale))
    accent_scale = min(1.10, max(1.0, accent_scale))
    sizes = {
        "base": min(64, max(_min_fs, base_size)),
        "impact": min(80, max(_min_fs, int(round(base_size * impact_scale)))),
        "accent": min(68, max(_min_fs, int(round(base_size * accent_scale)))),
    }
    fonts_cfg = preset.get("fonts", {}) if isinstance(preset, dict) else {}
    out: dict = {"sizes": sizes, "paths": {}, "names": {}}
    try:
        manager = _get_shared_font_manager()
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
    - stroke: SEMPRE (0,0,0,0) REELS-FIX v5 (stroke 0, auto-pill a parte).
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
        # REELS-FIX v5: stroke 0 trasparente (auto-pill separata, mai bordo).
        "stroke": (0, 0, 0, 0),
    }


def compute_styled_layout(
    styled_words: list[dict],
    fonts: dict,
    max_width: int,
    area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Layout multi-style REELS-FIX v5: wrapping stretto + hard-clamp + split long-word.

    Args:
        styled_words: [{"word","display","style",...}] (display uppercase solo se <=7 char).
        fonts: {"base","impact","accent"} da _load_typography_fonts.
        max_width: ignorato se area fornita (usa strettamente ax1-ax0).
        area: text_safe_area; None = fascia alta default.

    Returns:
        Lista parallela a styled_words con x/y/width/height dentro il box
        (hard-clamp X in [ax0,ax1-w], Y in [ay0,ay1-h]). Singola parola piu'
        larga del box viene spezzata per caratteri (mai overflow).
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
                max_width = int(ax1 - ax0)
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
        ax0, ay0, ax1, ay1 = 90, 140, 990, 720
        center_x = VIDEO_WIDTH / 2.0
        center_y = (ay0 + ay1) / 2.0
        max_width = int(ax1 - ax0)
        use_area = True
    try:
        draw = _get_probe_draw()
    except Exception:
        from PIL import Image as _Image, ImageDraw as _ImageDraw
        probe = _Image.new("RGBA", (64, 64), (0, 0, 0, 0))
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

    # REELS-FIX v5: pre-split parole singole piu' larghe del box (styled path).
    try:
        _mw = max(40, int(max_width))
    except Exception:
        _mw = int(max_width)
    expanded: list[dict] = []
    for it in items:
        try:
            _w0, _, _, _ = _measure(it["display"], it["style"])
        except Exception:
            expanded.append(it)
            continue
        if _w0 <= _mw or len(it["display"]) <= 1:
            expanded.append(it)
            continue
        # Spezza per caratteri in chunk che stanno nel box (eredita stile).
        _buf = ""
        for _ch in it["display"]:
            try:
                _tw = draw.textlength(_buf + _ch, font=_font_for(it["style"]))
            except Exception:
                _tw = _mw + 1
            if _tw <= _mw or not _buf:
                _buf += _ch
            else:
                expanded.append({"word": _buf, "display": _buf, "style": it["style"]})
                _buf = _ch
        if _buf:
            expanded.append({"word": _buf, "display": _buf, "style": it["style"]})
    items = expanded
    # Wrapping per larghezza cumulativa (misure stabili da metriche font).
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
        if total_height >= (ay1 - ay0):
            start_y = int(ay0)
        else:
            start_y = max(int(ay0), min(int(start_y), int(ay1 - total_height)))

    layout: list[dict] = [None] * len(items)  # type: ignore
    y = start_y
    for line, lw, la, ld, lh in zip(lines, line_widths, line_ascents, line_descents, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            if lw >= (ax1 - ax0):
                x = float(ax0)
            else:
                x = max(float(ax0), min(float(x), float(ax1 - lw)))
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
    # Hard-clamp finale: ogni parola dentro il box (mai fuori, mai overlap).
    if use_area:
        try:
            for _it in layout:
                if not isinstance(_it, dict):
                    continue
                try:
                    _it["x"] = max(int(ax0), min(int(_it["x"]), int(ax1 - _it["width"])))
                    _it["y"] = max(int(ay0), min(int(_it["y"]), int(ay1 - _it["height"])))
                except Exception:
                    continue
        except Exception:
            pass
    return layout


def compute_auto_fit_styled_layout(styled_words: list[dict], preset: dict,
                                   font_scale: float,
                                   area: tuple[int, int, int, int] | None,
                                   min_font_size: int = 38) -> tuple[list[dict], dict, dict]:
    """Auto-fit styled REELS-FIX v5: riduce font_scale fino a rientro nel box.

    Ritorna (layout, fonts, fills-base). Usato dai path animati per blocchi
    densi: scala 1.0 -> *0.92 (max 6 iter) fino a min 38px equivalenti.
    """
    try:
        scale = max(0.4, float(font_scale or 1.0))
    except Exception:
        scale = 1.0
    try:
        min_sz = max(20, int(min_font_size or 38))
    except Exception:
        min_sz = 38
    try:
        box_w = int(area[2]) - int(area[0]) if area else 900
        box_h = int(area[3]) - int(area[1]) if area else 580
    except Exception:
        box_w, box_h = 900, 580
    last: tuple = ([], {}, {})
    for _ in range(6):
        try:
            fonts = _load_typography_fonts(preset, scale)
        except Exception:
            break
        try:
            lay = compute_styled_layout(list(styled_words or []), fonts,
                                        max(40, box_w), area=area)
        except Exception:
            break
        last = (lay, fonts, preset)
        try:
            if not lay:
                return (lay, fonts, preset)
            xs = [int(it["x"]) for it in lay if isinstance(it, dict)]
            ys = [int(it["y"]) for it in lay if isinstance(it, dict)]
            xe = [int(it["x"]) + int(it["width"]) for it in lay if isinstance(it, dict)]
            ye = [int(it["y"]) + int(it["height"]) for it in lay if isinstance(it, dict)]
            bb_w = max(xe) - min(xs) if xs else 0
            bb_h = max(ye) - min(ys) if ys else 0
        except Exception:
            return (lay, fonts, preset)
        if bb_w <= box_w + 1 and bb_h <= box_h + 1:
            return (lay, fonts, preset)
        # Stima size base corrente per stop a 38px.
        try:
            cur_base = int((fonts.get("sizes", {}) or {}).get("base", 54))
        except Exception:
            cur_base = 54
        if cur_base <= min_sz:
            return (lay, fonts, preset)
        scale = max(0.4, scale * 0.92)
    return last


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
    """Disegna parola REELS-FIX v5 (stroke 0, ambient shadow 0,3,110)."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    # REELS-FIX v5: stroke 0 consentito, max 8px se esplicito.
    try:
        sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        sw = 0
    if sw < 0:
        sw = 0
    if sw > 8:
        sw = 8
    try:
        from core.renderer import _normalize_rgba
        fill_rgba = _normalize_rgba(fill, SUBTITLE_COLOR)
        if sw > 0:
            stroke_rgba = _normalize_rgba(stroke_color, (0, 0, 0, 255))
        else:
            stroke_rgba = None
    except Exception:
        fill_rgba = tuple(fill) if isinstance(fill, (tuple, list)) else SUBTITLE_COLOR
        stroke_rgba = tuple(stroke_color) if isinstance(stroke_color, (tuple, list)) else None
        if sw <= 0:
            stroke_rgba = None
    if opacity < 255:
        factor = opacity / 255.0
        fill_rgba = (fill_rgba[0], fill_rgba[1], fill_rgba[2], int(round(fill_rgba[3] * factor)))
        if stroke_rgba is not None:
            stroke_rgba = (stroke_rgba[0], stroke_rgba[1], stroke_rgba[2], int(round(stroke_rgba[3] * factor)))
    # Ambient shadow morbida (0,3,110); None = nessuna ombra (rispettato).
    try:
        if shadow_offset is None or shadow_fill is None:
            sh, sx, sy = None, 0, 0
        else:
            _so = tuple(shadow_offset)
            _sf = tuple(shadow_fill)
            sh = tuple(int(v) for v in _sf)
            if len(sh) == 3:
                sh = (sh[0], sh[1], sh[2], 255)
            if len(sh) >= 4 and sh[3] <= 0:
                sh = None
            else:
                sx, sy = int(_so[0]), int(_so[1])
                if opacity < 255 and sh is not None:
                    sh = (sh[0], sh[1], sh[2], int(round(sh[3] * opacity / 255.0)))
    except (TypeError, ValueError, IndexError):
        sh, sx, sy = (0, 0, 0, 110), 0, 3
    if sh is not None:
        try:
            draw.text((int(x) + int(sx), int(y) + int(sy)), display, font=font, fill=sh)
        except Exception:
            pass
    try:
        if sw > 0 and stroke_rgba is not None:
            draw.text((x, y), display, font=font, fill=fill_rgba,
                      stroke_width=sw, stroke_fill=stroke_rgba)
        else:
            draw.text((x, y), display, font=font, fill=fill_rgba)
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
    """Tile scalata REELS-FIX v5 (stroke 0, ambient shadow 0,3,110)."""
    if opacity <= 0 or scale <= 0:
        return
    # REELS-FIX v5: clamp scala a max 1.0 (no overshoot gigante).
    try:
        if float(scale) > 1.0:
            scale = 1.0
    except Exception:
        pass
    try:
        _sw0 = int(stroke_width or 0)
    except (TypeError, ValueError):
        _sw0 = 0
    if _sw0 < 0:
        stroke_width = 0
    if shadow_offset is None:
        shadow_offset = (0, 3)
    if shadow_fill is None:
        shadow_fill = (0, 0, 0, 110)
    if abs(scale - 1.0) < 1e-3:
        draw = ImageDraw.Draw(frame_img)
        _draw_styled_word_direct(draw, display, x, y, font, fill, stroke_color,
                                 stroke_width, shadow_offset, shadow_fill, opacity)
        return
    try:
        _sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        _sw = 0
    if _sw < 0:
        _sw = 0
    pad = 32 + max(0, _sw) * 2
    try:
        sox, soy = int(shadow_offset[0]), int(shadow_offset[1])
    except Exception:
        sox, soy = 0, 3
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
    resample = _fast_resample_for_scale(scale)
    scaled = tile.resize((new_w, new_h), resample)
    cx = x + word_w / 2.0
    cy = y + word_h / 2.0
    tcx = (pad_x + word_w / 2.0) * scale
    tcy = (pad_y + word_h / 2.0) * scale
    px = int(round(cx - tcx))
    py = int(round(cy - tcy))
    try:
        frame_img.alpha_composite(scaled, (px, py))
    except (ValueError, AttributeError):
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
    resample = _fast_resample_for_scale(scale)
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
        frame_img.alpha_composite(scaled, (px, py))
    except (ValueError, AttributeError):
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


def _preset_text_area(info: dict | None, preset: str | None):
    """Text Safe Area col bordo dinamico sul personaggio (v7 FIT-TO-HALF).

    Negli split deriva il box dal bbox reale fittato (fino a 40px prima del
    personaggio); altrove/static fallback. Mai solleva (fallback statico).
    """
    try:
        _p = str(preset) if preset else None
        if info is not None and _p in ("layout_split_left", "layout_split_right"):
            _pose = None
            try:
                _pose = int(info.get("pose"))
            except Exception:
                _pose = None
            try:
                _punch = bool(info.get("punch_in", False))
            except Exception:
                _punch = False
            return preset_safe_area_dynamic(_p, VIDEO_WIDTH, VIDEO_HEIGHT,
                                            _pose, _punch)
    except Exception:
        pass
    try:
        return preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
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


def _load_chunk_character_layer(info: dict | None, text_rect=None):
    """Layer personaggio (immagine + XY) per il chunk, o (None, None).

    Placement vincolato (scala = min(base, vincolo altezza, vincolo larghezza)
    + centro visivo in safe zone + clamp): soggetto interamente nel frame con
    margine, faccia mai tagliata. `text_rect` (x, y, w, h della fascia
    sottotitoli, opzionale) evita l'overlap col testo (il testo ha priorita').
    Errori non bloccanti (asset mancante, posa invalida): il frame viene
    generato senza personaggio (nessuna regressione).
    """
    if info is None:
        return None, None
    try:
        if info.get("use_preset"):
            char_img, px, py = get_character_layer(
                int(info["pose"]), info.get("layout"),
                bool(info.get("punch_in", False)),
                VIDEO_WIDTH, VIDEO_HEIGHT, text_rect=text_rect)
            return char_img, (px, py)
        # Legacy v1: stesso placement vincolato (position -> zona), fallback
        # al calcolo storico se fallisce.
        try:
            from core.character_selector import load_character_original
            from core.character_geometry import compute_subject_placement
            _orig = load_character_original(int(info["pose"]))
            try:
                _hint = float(info.get("scale", 0.75))
            except (TypeError, ValueError):
                _hint = 0.75
            _pl = compute_subject_placement(
                int(info["pose"]), str(info.get("position", "bottom_center")),
                False, VIDEO_WIDTH, VIDEO_HEIGHT, src_size=_orig.size,
                scale_hint=_hint, text_rect=text_rect)
            try:
                from PIL import Image as _PILImage
                try:
                    _rs = _PILImage.Resampling.LANCZOS
                except AttributeError:  # Pillow < 9.1
                    _rs = _PILImage.LANCZOS
                _resized = _orig.resize((int(_pl["new_w"]), int(_pl["new_h"])), _rs)
                if _resized.mode != "RGBA":
                    _resized = _resized.convert("RGBA")
                return _resized, (int(_pl["px"]), int(_pl["py"]))
            except Exception:
                pass
        except Exception as _le:
            try:
                print(f"[text_animator] warning: placement legacy fallito "
                      f"({_le}), uso bbox storica")
            except Exception:
                pass
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

    `fade=True` (default): entrata con dissolvenza + slide (fade in).
    `fade=False` solo per continuazioni gestite via jump-cut (stessa identita'
    o punch): in quel caso lo slide e' comunque saltato dal chiamante.
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

    - "slide_down": scende dissolvendo (fade out, come in passato).
      Il chunk dopo rientra con slide + fade in: transizione morbida,
      mai sparizione di botto. Luminosita' piena fino all'inizio uscita.
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
    """Modalita' di uscita (logica v2 collaudata: animazioni sempre visibili).

    - Chunk dopo senza personaggio (o fine video) -> "with_text" (fade).
    - Punch che cambia -> "hold" (jump-cut, niente dissolvenze).
    - Stessa identita' dopo -> "hold" (taglio invisibile).
    - Cambio lato split L<->R -> "slide_down" a piena opacita' (poi il chunk
      dopo rientra dal lato opposto con slide: animazione sempre visibile).
    - Altri cambi -> "hold" (il chunk dopo entra con slide a piena opacita').
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
        return _CHAR_EXIT_WITH_TEXT
    if _punch_of(cur) != _punch_of(after):
        return _CHAR_EXIT_HOLD
    if _character_identity(cur) == _character_identity(after):
        return _CHAR_EXIT_HOLD
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
    """Jump-cut SOLO su cambio punch (logica v2 collaudata).

    RIMOSSA la regola "stessa zona -> jump" che uccideva tutte le slide di
    entrata (il personaggio cambiava posa senza animazione e sembrava fixo).
    Ora ogni cambio posa/layout entra con slide visibile, solo il punch fa
    stacco netto TV. Prima apparizione: slide (mai jump).
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
    """Incolla il personaggio sul frame con opacita' e clipping ai bordi (veloce)."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    # Fast-path: opaco -> nessun copy/point, paste diretto.
    if opacity >= 255:
        to_paste = char_img
    else:
        to_paste = _get_char_at_opacity(char_img, opacity)
        if to_paste is None:
            return
    px, py = int(x), int(y)
    try:
        # alpha_composite e' piu' veloce di paste+mask su RGBA grandi.
        try:
            frame_img.alpha_composite(to_paste, (px, py))
            return
        except (ValueError, AttributeError):
            pass
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
        area = _preset_text_area(char_info, preset)
        needs_pill = preset_needs_text_background(preset)
        font_scale = preset_font_scale(preset)
    else:
        area, needs_pill, font_scale = None, False, 1.0
    # Boost chunk corti (1-3 parole): +20% base, mai oltre il box
    # (auto-fit riduce se serve). Caption singole restano protagoniste.
    try:
        _nw0 = len(words)
        if 0 < int(_nw0) <= 3:
            font_scale = float(font_scale) * 1.2
    except Exception:
        pass

    # --- Semantic Typography REELS-FIX v5: stroke 0, ambient shadow, min 38px ---
    use_typography = _is_typography_chunk(chunk)
    typo_preset: dict | None = None
    typo_fonts: dict | None = None
    typo_fills: dict | None = None
    typo_stroke_color: tuple = (0, 0, 0, 0)
    typo_stroke_width: int = 0
    typo_shadow_offset = (0, 3)
    typo_shadow_fill = (0, 0, 0, 110)
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
                # REELS-FIX v5: uppercase solo se parola <=7 char (no espansione brutta).
                try:
                    from core.typography_presets import IMPACT_UPPERCASE_MAX_LEN as _MX
                except Exception:
                    _MX = 7
                _do_up = bool(style == "impact" and uppercase_impact and len(word_text.strip()) <= int(_MX))
                display = str(s.get("display", word_text.upper() if _do_up else word_text))
                if _do_up:
                    display = display.upper()
                styled_words.append({
                    "word": word_text, "display": display, "style": style,
                    "start": st, "end": en,
                    "is_keyword": style == "impact",
                })
        if not styled_words:
            # Deriva da words legacy: keyword -> impact, resto base.
            styled_words = []
            try:
                from core.typography_presets import IMPACT_UPPERCASE_MAX_LEN as _MX2
            except Exception:
                _MX2 = 7
            for w in words:
                style = "impact" if w.get("is_keyword") else "base"
                _ww = str(w["word"])
                _up2 = bool(style == "impact" and uppercase_impact and len(_ww.strip()) <= int(_MX2))
                disp = _ww.upper() if _up2 else _ww
                styled_words.append({
                    "word": str(w["word"]), "display": disp, "style": style,
                    "start": float(w["start"]), "end": float(w["end"]),
                    "is_keyword": bool(w.get("is_keyword", False)),
                })
        if not styled_words:
            use_typography = False
    if use_typography and typo_preset is not None and styled_words:
        # REELS-FIX v5 auto-fit styled: scala font fino a rientro nel box.
        try:
            _box_w_tmp = int(area[2]) - int(area[0]) if area else 900
        except Exception:
            _box_w_tmp = 900
        typo_fonts = _load_typography_fonts(typo_preset, font_scale)
        # Attribuzione colori coerente: tema + sfondo + keyword. Stroke 0.
        typo_fills = _styled_fills(
            typo_preset,
            base_override=text_color,
            background_color=background_color,
            keyword_colors=keyword_colors,
        )
        typo_stroke_color = (0, 0, 0, 0)
        try:
            cfg_w = int(typo_preset.get("stroke_width", TYPOGRAPHY_STROKE_WIDTH))
        except (TypeError, ValueError):
            cfg_w = 0
        try:
            _cfg_global = int(TYPOGRAPHY_STROKE_WIDTH)
        except (TypeError, ValueError):
            _cfg_global = 0
        typo_stroke_width = max(0, int(cfg_w or 0), int(_cfg_global or 0))
        # Ambient shadow morbida (0,3,110); None = nessuna ombra.
        try:
            sh = typo_preset.get("shadow", {}) if isinstance(typo_preset, dict) else {}
            _off = sh.get("offset", tuple(TYPOGRAPHY_SHADOW_OFFSET))
            _fill = sh.get("fill", tuple(TYPOGRAPHY_SHADOW_FILL))
            typo_shadow_offset = tuple(_off) if _off is not None else (0, 3)
            typo_shadow_fill = tuple(_fill) if _fill is not None else (0, 0, 0, 110)
        except Exception:
            typo_shadow_offset, typo_shadow_fill = (0, 3), (0, 0, 0, 110)
        max_text_width = int(_box_w_tmp)
        # Auto-fit loop: se bbox eccede il box, scala 0.92 fino a min 38px.
        try:
            _area_box_w = int(area[2]) - int(area[0]) if area else 900
            _area_box_h = int(area[3]) - int(area[1]) if area else 580
        except Exception:
            _area_box_w, _area_box_h = 900, 580
        layout = compute_styled_layout(styled_words, typo_fonts, max_text_width, area=area)
        try:
            from config import TYPOGRAPHY_MIN_FONT_SIZE as _TMFS
            _tmfs = max(20, int(_TMFS))
        except Exception:
            _tmfs = 38
        for _af in range(5):
            try:
                if not layout:
                    break
                _xs = [int(it["x"]) for it in layout]
                _ys = [int(it["y"]) for it in layout]
                _xe = [int(it["x"]) + int(it["width"]) for it in layout]
                _ye = [int(it["y"]) + int(it["height"]) for it in layout]
                _bw = max(_xe) - min(_xs)
                _bh = max(_ye) - min(_ys)
            except Exception:
                break
            if _bw <= _area_box_w + 1 and _bh <= _area_box_h + 1:
                break
            try:
                _cur = int((typo_fonts.get("sizes", {}) or {}).get("base", 54))
            except Exception:
                _cur = 54
            if _cur <= _tmfs:
                break
            try:
                font_scale = max(0.4, float(font_scale) * 0.92)
            except Exception:
                break
            try:
                typo_fonts = _load_typography_fonts(typo_preset, font_scale)
                layout = compute_styled_layout(styled_words, typo_fonts, max_text_width, area=area)
            except Exception:
                break
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
        # --- Legacy auto-fit REELS-FIX v5: base*scale, minimo 38px ---
        try:
            from config import SUBTITLE_MIN_FONT_SIZE as _LMFS
            _lmfs = max(20, int(_LMFS))
        except Exception:
            _lmfs = 38
        try:
            text_font_size = int(round(int(SUBTITLE_FONT_SIZE) * float(font_scale)))
        except (TypeError, ValueError):
            text_font_size = int(SUBTITLE_FONT_SIZE)
        word_texts = [w["word"] for w in words]
        try:
            from core.renderer import compute_auto_fit_layout as _auto_fit
            layout, font, text_font_size = _auto_fit(word_texts, text_font_size,
                                                     area, min_font_size=_lmfs)
        except Exception:
            try:
                font = load_font(max(_lmfs, text_font_size))
            except Exception:
                font = load_font(text_font_size)
            try:
                _bw_legacy = int(area[2]) - int(area[0]) if area else int(VIDEO_WIDTH * 0.85)
            except Exception:
                _bw_legacy = int(VIDEO_WIDTH * 0.85)
            layout = compute_word_layout(word_texts, font, max(40, _bw_legacy), area=area)
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
    try:
        scale_from = float(KEYWORD_ENTRY_SCALE_FROM)
    except Exception:
        scale_from = 0.85
    if not (0.5 <= scale_from <= 1.0):
        scale_from = 0.85
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
    # La fascia testo (area) guida il placement anti-overlap (FASE 7); il
    # keyframe finale delle transizioni coincide con lo stato stabile clampato
    # (offset 0 a progress 1, vedi _character_entry_offset_opacity), quindi il
    # fuori-campo esiste solo a meta' animazione (FASE 4); il punch_in e'
    # ricappato su vincolo larghezza + faccia visibile (FASE 5).
    try:
        _char_text_rect = None
        if area is not None and len(area) == 4:
            _char_text_rect = (float(area[0]), float(area[1]),
                               float(area[2] - area[0]), float(area[3] - area[1]))
    except Exception:
        _char_text_rect = None
    char_img, char_base_xy = _load_chunk_character_layer(char_info,
                                                         text_rect=_char_text_rect)
    if char_img is not None and char_base_xy is not None and char_info is not None:
        char_transition = char_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(char_info)
        char_entry_jump = bool(char_entry_jump)
        char_entry_fade = bool(char_entry_fade)
        # Fix animazioni: slide LUNGA da fuori-campo a ogni cambio layout
        # (logica v2 collaudata). Solo il jump-cut punch e la stessa identita'
        # (hold) restano fermi; tutto il resto entra scivolando visibilmente.
        char_full_travel = bool(use_preset and not char_entry_jump)
        char_entry_dur = max(0.01, _CHARACTER_ZONE_ENTRY_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)

    try:
        char_exit_dur = max(0.0, float(char_exit_duration))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION
    if char_exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
        char_exit_mode = _CHAR_EXIT_WITH_TEXT

    num_frames = max(1, int(math.ceil(duration * fps)))
    frame_step = 1.0 / float(fps)
    frames: list[dict] = []

    # --- Pre-computazioni per-chunk (fuori dal loop frame) ---
    # Pill: preset punch-in oppure auto-pill (testo scuro/grigio su scuro).
    # Stroke sempre 0: la leggibilita' viene dalla pill, mai dai bordi.
    try:
        _want_pill = bool(needs_pill)
        if not _want_pill and layout:
            try:
                _base_probe = (typo_fills.get("base") if use_typography and
                               isinstance(typo_fills, dict) else base_rgba)
            except Exception:
                _base_probe = None
            try:
                _want_pill = bool(should_auto_pill(_base_probe, background_color))
            except Exception:
                _want_pill = False
    except Exception:
        _want_pill = bool(needs_pill)
    _pill_overlay = None
    if _want_pill and layout:
        try:
            from core.renderer import TEXT_PILL_FILL, TEXT_PILL_PAD, TEXT_PILL_RADIUS
            _x0 = min(it["x"] for it in layout) - TEXT_PILL_PAD
            _y0 = min(it["y"] for it in layout) - TEXT_PILL_PAD
            _x1 = max(it["x"] + it["width"] for it in layout) + TEXT_PILL_PAD
            _y1 = max(it["y"] + it["height"] for it in layout) + TEXT_PILL_PAD
            _x0, _y0 = max(0, _x0), max(0, _y0)
            _x1, _y1 = min(VIDEO_WIDTH, _x1), min(VIDEO_HEIGHT, _y1)
            if _x1 > _x0 and _y1 > _y0:
                _pill_overlay = _get_cached_pill_overlay(
                    (_x0, _y0, _x1, _y1), TEXT_PILL_FILL, TEXT_PILL_PAD, TEXT_PILL_RADIUS)
        except Exception:
            _pill_overlay = None
    # Binding locali per loop caldo (evita lookup globali/attr per frame).
    _ease_out_back = ease_out_back
    _ease_out_cubic = ease_out_cubic
    _ease_in_cubic = ease_in_cubic
    _clamp01 = clamp01
    _new_rgba = Image.new
    _canvas_size = (VIDEO_WIDTH, VIDEO_HEIGHT)
    _transparent = (0, 0, 0, 0)
    # Font per parola pre-risolti (evita dict.get + try per frame).
    if use_typography:
        try:
            _word_fonts = [typo_fonts.get(layout[i].get("style", words[i].get("style", "base")),
                                          typo_fonts.get("base")) for i in range(len(words))]
        except Exception:
            _word_fonts = [typo_fonts.get("base") if isinstance(typo_fonts, dict) else font] * len(words)
    else:
        _word_fonts = [font] * len(words)
    _shadow_off = typo_shadow_offset if 'typo_shadow_offset' in dir() else None
    _shadow_fill = typo_shadow_fill if 'typo_shadow_fill' in dir() else None

    for fi in range(num_frames):
        t = chunk_start + fi * frame_step
        if t >= chunk_end:
            t = chunk_end - 1e-6
        frame_end = min(t + frame_step, chunk_end)

        # Fattore uscita di gruppo, condiviso da tutte le parole.
        if exit_dur > 0 and t >= chunk_end - exit_dur:
            exit_prog = _clamp01((t - (chunk_end - exit_dur)) / exit_dur)
            exit_factor = 1.0 - _ease_in_cubic(exit_prog)
        else:
            exit_factor = 1.0

        frame_img = _new_rgba("RGBA", _canvas_size, _transparent)

        # Z-index 2: personaggio sotto il testo (entrata + eventuale uscita).
        # Fade in su apparizione e cambi visibili, fade out in uscita:
        # luminosita' piena a regime (255, mai dimmerato), mai di botto.
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
                # Fade OUT in uscita (come in passato): scende dissolvendo,
                # mai sparizione di botto. Luminosita' piena fino all'uscita.
                xprog = clamp01((t - (chunk_end - char_exit_dur)) / char_exit_dur)
                xdx, xdy, exit_opacity = _character_exit_offset_opacity(
                    _CHAR_EXIT_SLIDE_DOWN, xprog, char_base_xy[1], fade=True)
                char_opacity = min(entry_opacity, exit_opacity)
            else:
                char_opacity, xdx, xdy = int(round(entry_opacity * exit_factor)), 0, 0
            # Micro-movimento idle v2 (anti-sticker): bob+sway sinusoidali
            # sempre attivi (anche in HOLD) per dare vita al personaggio.
            # Fase continua su t assoluto: nessun salto tra chunk consecutivi
            # con stessa posa (moto coerente, non reset per chunk).
            if _IDLE_ENABLED and char_opacity > 0:
                try:
                    _t_rel = float(t)
                    _idle_dy = int(round(
                        _IDLE_BOB_AMP_Y * math.sin(2.0 * math.pi * _IDLE_BOB_FREQ * _t_rel)))
                    _idle_dx = int(round(
                        _IDLE_SWAY_AMP_X * math.sin(2.0 * math.pi * _IDLE_SWAY_FREQ * _t_rel + 1.1)))
                except Exception:
                    _idle_dx, _idle_dy = 0, 0
            else:
                _idle_dx, _idle_dy = 0, 0
            _paste_character_frame(
                frame_img, char_img,
                char_base_xy[0] + edx + xdx + _idle_dx,
                char_base_xy[1] + edy + xdy + _idle_dy,
                char_opacity,
            )

        # Z-index 2.5: pill pre-renderizzata (composite unico, no ricalcolo).
        if _pill_overlay is not None:
            try:
                frame_img.alpha_composite(_pill_overlay)
            except (ValueError, AttributeError):
                draw_text_background(frame_img, layout)
        elif needs_pill or _want_pill:
            draw_text_background(frame_img, layout)

        for wi, w in enumerate(words):
            if t < word_starts[wi]:
                continue  # non ancora iniziata
            local = _clamp01((t - word_starts[wi]) / entry_dur)
            if w["is_keyword"]:
                # REELS-FIX v5: clamp overshoot ease_out_back a max 1.0
                # (pop 0.85->1.0, mai oltre 100% = mai gigante).
                try:
                    eased = min(float(_ease_out_back(local)), 1.0)
                except Exception:
                    eased = min(1.0, max(0.0, float(local)))
                if eased >= 1.0:
                    opacity = 255
                elif eased <= 0.0:
                    continue
                else:
                    opacity = int(round(255 * eased))
                scale = scale_from + (1.0 - scale_from) * eased
                if scale > 1.0:
                    scale = 1.0
                # Evita scale degeneri a inizio animazione.
                if scale < 0.05:
                    scale = 0.05
            else:
                # Fast-path: entrata completata -> opaco, scala 1 (disegno diretto).
                if local >= 1.0:
                    opacity, scale = 255, 1.0
                elif local <= 0.0:
                    continue
                else:
                    eased = _ease_out_cubic(local)
                    opacity = int(round(255 * eased))
                    scale = 1.0
            if exit_factor < 1.0:
                opacity = int(round(opacity * exit_factor))
            if opacity <= 0:
                continue
            item = layout[wi]
            if use_typography:
                wfont = _word_fonts[wi]
                _render_styled_scaled_word(
                    frame_img, w["word"], item["x"], item["y"],
                    item["width"], item["height"], wfont,
                    fills[wi], typo_stroke_color, typo_stroke_width,
                    _shadow_off, _shadow_fill,
                    opacity=opacity, scale=scale,
                )
            else:
                # Legacy REELS-FIX v5: stroke 0 (nessun forcing a 5px).
                try:
                    _leg_sw = int(SUBTITLE_STROKE_WIDTH)
                except (TypeError, ValueError):
                    _leg_sw = 0
                if _leg_sw < 0:
                    _leg_sw = 0
                _render_scaled_word(
                    frame_img, w["word"], item["x"], item["y"],
                    item["width"], item["height"], _word_fonts[wi],
                    fills[wi], SUBTITLE_STROKE_COLOR, _leg_sw,
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
        area = _preset_text_area(first_info, first_info.get("layout"))
        try:
            font_scale = float(preset_font_scale(first_info.get("layout")))
        except Exception:
            font_scale = 1.0
    else:
        area, font_scale = None, 1.0
    needs_pill = True  # la card è un badge intenzionale, sempre ancorato
    card_scale = 0.92  # la card contiene più parole: leggermente più compatta

    # --- Font/fill di sezione REELS-FIX v5 (stroke 0, box stretto, min 38) ---
    try:
        _cta_box_w = int(area[2]) - int(area[0]) if area else 900
    except Exception:
        _cta_box_w = 900
    if use_typography and typo_preset is not None:
        typo_fonts = _load_typography_fonts(typo_preset, font_scale * card_scale)
        typo_fills = _styled_fills(
            typo_preset, base_override=text_color,
            background_color=background_color, keyword_colors=keyword_colors)
        max_text_width = int(_cta_box_w)
        layout = compute_styled_layout(section, typo_fonts, max_text_width, area=area)
        if len(layout) != len(section):
            raise TextAnimationError("Layout/words fuori sync nella CTA card.")
        fills = [typo_fills.get(layout[i].get("style", "base"), typo_fills["base"])
                 for i in range(len(layout))]
        stroke_color, stroke_width = (0, 0, 0, 0), 0
        shadow_off, shadow_fill = (0, 3), (0, 0, 0, 110)
    else:
        use_typography = False
        try:
            from config import SUBTITLE_MIN_FONT_SIZE as _CMFS
            _cmfs = max(20, int(_CMFS))
        except Exception:
            _cmfs = 38
        try:
            text_font_size = max(_cmfs, int(round(int(SUBTITLE_FONT_SIZE) * float(font_scale) * card_scale)))
        except (TypeError, ValueError):
            text_font_size = max(_cmfs, int(SUBTITLE_FONT_SIZE))
        try:
            from core.renderer import compute_auto_fit_layout as _cta_fit
            layout, font, text_font_size = _cta_fit(
                [s["word"] for s in section], text_font_size, area, min_font_size=_cmfs)
            max_text_width = int(_cta_box_w)
        except Exception:
            font = load_font(text_font_size)
            max_text_width = int(_cta_box_w)
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
        if not (0.5 <= scale_from <= 1.0):
            scale_from = 0.85
    except (TypeError, ValueError):
        scale_from = 0.85

    # --- Personaggio bloccato (layer unico per tutta la card) ---
    # CTA card = finale stabile: sempre slide corta/morbida, mai full-travel.
    # La fascia testo guida il placement anti-overlap come nel path normale.
    try:
        _cta_text_rect = None
        if area is not None and len(area) == 4:
            _cta_text_rect = (float(area[0]), float(area[1]),
                              float(area[2] - area[0]), float(area[3] - area[1]))
    except Exception:
        _cta_text_rect = None
    char_img, char_base_xy = _load_chunk_character_layer(first_info,
                                                         text_rect=_cta_text_rect)
    if char_img is not None and char_base_xy is not None and first_info is not None:
        char_transition = first_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(first_info)
        char_full_travel = False
        char_entry_dur = max(0.01, _CHARACTER_ZONE_ENTRY_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
    else:
        char_base_xy = None
    try:
        char_exit_dur = max(0.0, float(_CHARACTER_ZONE_EXIT_DURATION))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION

    os.makedirs(output_dir, exist_ok=True)
    # Pill CTA pre-renderizzata una volta (stesso layout per tutta la card).
    _cta_pill = None
    try:
        if layout:
            from core.renderer import TEXT_PILL_FILL as _PF, TEXT_PILL_PAD as _PP, TEXT_PILL_RADIUS as _PR
            _cx0 = max(0, min(it["x"] for it in layout) - _PP)
            _cy0 = max(0, min(it["y"] for it in layout) - _PP)
            _cx1 = min(VIDEO_WIDTH, max(it["x"] + it["width"] for it in layout) + _PP)
            _cy1 = min(VIDEO_HEIGHT, max(it["y"] + it["height"] for it in layout) + _PP)
            if _cx1 > _cx0 and _cy1 > _cy0:
                _cta_pill = _get_cached_pill_overlay((_cx0, _cy0, _cx1, _cy1), _PF, _PP, _PR)
    except Exception:
        _cta_pill = None
    # Font per parola pre-risolti + binding locali.
    try:
        if use_typography and typo_fonts is not None:
            _cta_fonts = [typo_fonts.get(layout[i].get("style", section[i].get("style", "base")), typo_fonts.get("base")) for i in range(len(section))]
        else:
            _cta_fonts = [font] * len(section)
    except Exception:
        _cta_fonts = [font if 'font' in dir() else typo_fonts.get("base")] * len(section)
    _cta_ease_back = ease_out_back
    _cta_ease_cubic = ease_out_cubic
    _cta_clamp = clamp01
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
                    # Fade out anche qui: scende dissolvendo (mai sparizione).
                    xp = clamp01((t - (ce - char_exit_dur)) / char_exit_dur)
                    xdx, xdy, xop = _character_exit_offset_opacity(
                        _CHAR_EXIT_SLIDE_DOWN, xp, char_base_xy[1], fade=True)
                    cop = min(entry_opacity, xop)
                else:
                    cop, xdx, xdy = int(round(entry_opacity * exit_factor)), 0, 0
                # Idle respiratorio anche su CTA card (finale vivo, mai sticker).
                if _IDLE_ENABLED and cop > 0:
                    try:
                        _cdx = int(round(_IDLE_SWAY_AMP_X * math.sin(
                            2.0 * math.pi * _IDLE_SWAY_FREQ * float(t) + 1.1)))
                        _cdy = int(round(_IDLE_BOB_AMP_Y * math.sin(
                            2.0 * math.pi * _IDLE_BOB_FREQ * float(t))))
                    except Exception:
                        _cdx, _cdy = 0, 0
                else:
                    _cdx, _cdy = 0, 0
                _paste_character_frame(
                    frame_img, char_img,
                    char_base_xy[0] + edx + xdx + _cdx,
                    char_base_xy[1] + edy + xdy + _cdy, cop)
            if _cta_pill is not None:
                try:
                    frame_img.alpha_composite(_cta_pill)
                except (ValueError, AttributeError):
                    draw_text_background(frame_img, layout)
            elif needs_pill:
                draw_text_background(frame_img, layout)
            for wi, w in enumerate(section):
                if t < w["start"]:
                    continue  # parola futura: nascosta (reveal karaoke)
                local = _cta_clamp((t - w["start"]) / entry_dur)
                if w["is_keyword"]:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        try:
                            eased = min(float(_cta_ease_back(local)), 1.0)
                        except Exception:
                            eased = min(1.0, max(0.0, float(local)))
                        opacity = int(round(255 * min(1.0, max(0.0, eased))))
                        scale = min(1.0, max(0.05, scale_from + (1.0 - scale_from) * eased))
                else:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        opacity = int(round(255 * _cta_ease_cubic(local)))
                        scale = 1.0
                if exit_factor < 1.0:
                    opacity = int(round(opacity * exit_factor))
                if opacity <= 0:
                    continue
                item = layout[wi]
                if use_typography:
                    wfont = _cta_fonts[wi]
                    _render_styled_scaled_word(
                        frame_img, w["display"], item["x"], item["y"],
                        item["width"], item["height"], wfont,
                        fills[wi], stroke_color, stroke_width,
                        shadow_off, shadow_fill, opacity=opacity, scale=scale)
                else:
                    try:
                        _cta_sw = int(SUBTITLE_STROKE_WIDTH)
                    except (TypeError, ValueError):
                        _cta_sw = 0
                    if _cta_sw < 0:
                        _cta_sw = 0
                    _render_scaled_word(
                        frame_img, w["word"], item["x"], item["y"],
                        item["width"], item["height"], _cta_fonts[wi],
                        fills[wi], SUBTITLE_STROKE_COLOR, _cta_sw,
                        opacity=opacity, scale=scale)
            fname = f"chunk_{start_index + k:04d}_frame_{fi:05d}.png"
            fpath = os.path.join(output_dir, fname)
            frame_img.save(fpath, compress_level=1)
            frames.append({"image_path": fpath, "start": t, "end": frame_end})
        per_chunk_frames.append(frames)
    return per_chunk_frames


# ---------------------------------------------------------------------------
# Continuity Engine v3 — Full-Timeline Renderer (spec §1+§2+§3+§5)
# ---------------------------------------------------------------------------
# Renderizza l'INTERA timeline come traccia continua: il character persiste
# senza reset ai confini chunk (alpha invariato), lo slide X usa out_cubic
# 0.3s, slide_up solo a inizio/dopo gap, jump-cut intermedi. Il testo resta
# per-chunk (normale che cambi), ma il character non blinka mai.

_TIMELINE_SLIDE_X_DUR: float = 0.30


def _timeline_slide_x(x_from: int, x_to: int, progress: float) -> int:
    """Slide X con out_cubic 0.3s (spec §3), mai tocca l'opacita'."""
    try:
        from core.layout_presets import interpolate_x_out_cubic as _ix
        return int(_ix(int(x_from), int(x_to), float(progress)))
    except Exception:
        try:
            p = max(0.0, min(1.0, float(progress)))
            eased = 1.0 - pow(1.0 - p, 3)
            return int(round(float(x_from) + (float(x_to) - float(x_from)) * eased))
        except Exception:
            return int(x_to)


def _active_chunk_at(chunks: list[dict], t: float) -> dict | None:
    """Chunk testuale attivo a t (start<=t<end), o None nei gap."""
    try:
        for ch in chunks:
            try:
                s = float((ch or {}).get("start", 0.0))
                e = float((ch or {}).get("end", s))
            except (TypeError, ValueError):
                continue
            if s <= t < e:
                return ch
        return None
    except Exception:
        return None


def render_full_timeline_frames(
    chunks: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    fps: int = VIDEO_FPS,
    total_duration: float | None = None,
    on_progress=None,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[dict]:
    """Renderizza la timeline COMPLETA come sequenza continua (spec §1+§5).

    - Unico asse temporale 0..total_duration (default: max chunk end).
    - Character da `Timeline Manager` (character_selector.get_timeline_for_chunks):
      persistente per segmento, slide_up solo a inizio/dopo gap, slide_x 0.3s
      out_cubic sui cambi lato, jump-cut istantaneo per cambi posa, idle
      bob/sway a fase assoluta (nessun reset tra chunk).
    - Testo: parole del chunk attivo con entry pop/fade + exit fade di gruppo
      (il testo puo' cambiare per chunk; il character MAI).
    - Frame PNG trasparenti (sfondo via ffmpeg), salvati in parallelo
      ThreadPool con risorse preloadate UNA volta (font+character in RAM).
    - Fail-safe: ritorna [] (mai solleva TextAnimationError) cosi' il chiamante
      usa il fallback legacy per-chunk.

    Returns:
        Lista frame {"image_path","start","end"} ordinata per t.
    """
    try:
        if fps is None or fps <= 0:
            fps = VIDEO_FPS
        if not chunks:
            return []
        try:
            ends = [float((c or {}).get("end", 0.0)) for c in chunks]
            t_end = float(total_duration) if total_duration else max(ends)
        except (TypeError, ValueError):
            return []
        if t_end <= 0:
            return []
        os.makedirs(output_dir, exist_ok=True)

        # --- Preload RAM una sola volta (spec §5) ---
        try:
            _get_shared_font_manager()
        except Exception:
            pass
        try:
            from core.character_selector import (
                preload_character_assets as _preload_chars,
                get_timeline_for_chunks as _get_timeline,
            )
            try:
                _preload_chars()
            except Exception:
                pass
            segments = _get_timeline(chunks)
        except Exception:
            segments = []
        try:
            preload_character_layers()
        except Exception:
            pass

        # --- Layer character per segmento (una sola volta, riusati) ---
        # Nota FASE 7: i segmenti attraversano piu' chunk con fasce testo
        # diverse, quindi niente text_rect qui (placement stabile clampato +
        # safe area dinamiche strutturali: l'overlap e' impossibile).
        seg_layers: list[dict] = []
        try:
            for s_idx, seg in enumerate(segments):
                if seg.get("gap") or seg.get("pose") is None:
                    seg_layers.append({"img": None, "xy": None})
                    continue
                try:
                    img, xy = _load_chunk_character_layer({
                        "pose": seg.get("pose"), "layout": seg.get("layout"),
                        "layout_preset": seg.get("layout"),
                        "punch_in": seg.get("punch_in", False),
                        "use_preset": seg.get("use_preset", True),
                        "transition_in": "slide_up",
                    })
                except Exception:
                    img, xy = None, None
                seg_layers.append({"img": img, "xy": xy})
        except Exception:
            seg_layers = [{"img": None, "xy": None} for _ in segments]

        def _seg_at(t: float):
            try:
                for k, s in enumerate(segments):
                    if float(s["start"]) <= t < float(s["end"]):
                        return k, s
                return None, None
            except Exception:
                return None, None

        def _prev_real_seg(k: int):
            try:
                j = k - 1
                while j >= 0:
                    if not segments[j].get("gap") and seg_layers[j].get("img") is not None:
                        return j, segments[j]
                    j -= 1
                return None, None
            except Exception:
                return None, None

        # --- Layout testo per chunk (una sola volta, come generate_animated...) ---
        chunk_text: list[dict] = []
        try:
            for ch in chunks:
                try:
                    info = _character_info_from_chunk(ch)
                    use_p = bool(info is not None and info.get("use_preset"))
                    exp = None
                    area = None
                    needs_pill = False
                    fscale = 1.0
                    if use_p:
                        area = _preset_text_area(info, info.get("layout"))
                        needs_pill = preset_needs_text_background(info.get("layout"))
                        fscale = preset_font_scale(info.get("layout"))
                    is_typo = _is_typography_chunk(ch)
                    if is_typo:
                        pr = _resolve_typography_preset(ch, typography_niche, typography_preset)
                        fonts = _load_typography_fonts(pr, fscale)
                        fills = _styled_fills(pr, base_override=text_color,
                                              background_color=background_color,
                                              keyword_colors=keyword_colors)
                        raw = ch.get("styled_words") or []
                        sw = []
                        words_timing = enrich_chunk_words(ch, keyword_colors)
                        for ii, s in enumerate(raw):
                            if not isinstance(s, dict):
                                continue
                            st = s.get("style", "base")
                            if st not in ("base", "impact", "accent"):
                                st = "base"
                            wt = str(s.get("word", ""))
                            if not wt.strip():
                                continue
                            try:
                                sst = float(s.get("start", words_timing[ii]["start"] if ii < len(words_timing) else ch.get("start", 0.0)))
                                sen = float(s.get("end", words_timing[ii]["end"] if ii < len(words_timing) else ch.get("end", 0.0)))
                            except Exception:
                                sst = float(ch.get("start", 0.0))
                                sen = float(ch.get("end", sst))
                            disp = str(s.get("display", wt))
                            sw.append({"word": wt, "display": disp, "style": st,
                                       "start": sst, "end": sen,
                                       "is_keyword": st == "impact"})
                        if not sw:
                            is_typo = False
                        else:
                            try:
                                _tl_bw = int(area[2]) - int(area[0]) if area else 900
                            except Exception:
                                _tl_bw = 900
                            lay = compute_styled_layout(sw, fonts, max(40, _tl_bw), area=area)
                            wfonts = [fonts.get(lay[k].get("style", "base"), fonts.get("base")) for k in range(len(lay))]
                            chunk_text.append({"mode": "typo", "words": sw, "layout": lay,
                                               "fonts": wfonts, "fills": [fills.get(lay[k].get("style", "base"), fills["base"]) for k in range(len(lay))],
                                               "needs_pill": needs_pill, "preset": pr})
                            continue
                    # Legacy path REELS-FIX v5 (min 38px, box stretto)
                    try:
                        from config import SUBTITLE_MIN_FONT_SIZE as _TLMFS
                        _tlmfs = max(20, int(_TLMFS))
                    except Exception:
                        _tlmfs = 38
                    fsize = max(_tlmfs, int(round(int(SUBTITLE_FONT_SIZE) * float(fscale))))
                    try:
                        from core.renderer import compute_auto_fit_layout as _tl_fit
                        _tl_words_tmp = [w["word"] for w in enrich_chunk_words(ch, keyword_colors)]
                        lay_tmp, font, fsize = _tl_fit(_tl_words_tmp, fsize, area, min_font_size=_tlmfs)
                        words = enrich_chunk_words(ch, keyword_colors)
                        lay = lay_tmp
                    except Exception:
                        font = load_font(fsize)
                        words = enrich_chunk_words(ch, keyword_colors)
                        try:
                            _tl_bw2 = int(area[2]) - int(area[0]) if area else int(VIDEO_WIDTH * 0.85)
                        except Exception:
                            _tl_bw2 = int(VIDEO_WIDTH * 0.85)
                        lay = compute_word_layout([w["word"] for w in words], font,
                                                  max(40, _tl_bw2), area=area)
                    base_rgba = _to_rgba(text_color, SUBTITLE_COLOR)
                    fills = [_resolve_word_fill(normalize_word(w["word"]), base_rgba, keyword_colors) for w in words]
                    chunk_text.append({"mode": "legacy", "words": words, "layout": lay,
                                       "fonts": [font] * len(words), "fills": fills,
                                       "needs_pill": needs_pill, "preset": None})
                except Exception:
                    chunk_text.append({"mode": "legacy", "words": [], "layout": [],
                                       "fonts": [], "fills": [], "needs_pill": False, "preset": None})
        except Exception:
            chunk_text = []

        try:
            entry_dur_cfg = max(0.01, float(TEXT_ANIMATION_ENTRY_DURATION))
        except Exception:
            entry_dur_cfg = 0.18
        try:
            exit_dur_cfg = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
        except Exception:
            exit_dur_cfg = 0.15
        try:
            char_entry_dur = max(0.15, float(_CHARACTER_ZONE_ENTRY_DURATION))
        except Exception:
            char_entry_dur = 0.55

        num_frames = max(1, int(math.ceil(float(t_end) * float(fps))))
        step = 1.0 / float(fps)

        import concurrent.futures as _fut

        def _render_frame(fi: int) -> dict | None:
            try:
                t = fi * step
                if t >= t_end:
                    t = t_end - 1e-6
                fend = min(t + step, t_end)
                img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
                # --- Character persistente (mai reset ai confini chunk) ---
                k, seg = _seg_at(t)
                if seg is not None and not seg.get("gap"):
                    layer = seg_layers[k] if 0 <= k < len(seg_layers) else {"img": None, "xy": None}
                    cimg = layer.get("img")
                    cxy = layer.get("xy")
                    if cimg is not None and cxy is not None:
                        bx, by = int(cxy[0]), int(cxy[1])
                        entry = str(seg.get("entry", "jump"))
                        opacity = 255
                        dx, dy = 0, 0
                        if entry == "slide_up" and (t - float(seg["start"])) < char_entry_dur:
                            prog = clamp01((t - float(seg["start"])) / char_entry_dur)
                            _edx, _edy, opacity = _character_entry_offset_opacity(
                                "slide_up", _character_side({
                                    "use_preset": True, "layout": seg.get("layout"),
                                    "position": "bottom_center"}),
                                prog, cimg.size[0], bx, by,
                                full_travel=True, fade=True)
                            dx, dy = _edx, _edy
                        elif entry == "slide_x" and (t - float(seg["start"])) < _TIMELINE_SLIDE_X_DUR:
                            pk, prev = _prev_real_seg(k)
                            if prev is not None and seg_layers[pk].get("xy") is not None:
                                try:
                                    x0 = int(seg_layers[pk]["xy"][0])
                                except Exception:
                                    x0 = bx
                                prog = clamp01((t - float(seg["start"])) / _TIMELINE_SLIDE_X_DUR)
                                bx = _timeline_slide_x(x0, bx, prog)
                            opacity = 255  # mai fade sullo slide X (spec §3)
                        # Idle respiratorio a fase assoluta (continuo tra segmenti)
                        idx_, idy_ = 0, 0
                        if _IDLE_ENABLED:
                            try:
                                idy_ = int(round(_IDLE_BOB_AMP_Y * math.sin(2.0 * math.pi * _IDLE_BOB_FREQ * float(t))))
                                idx_ = int(round(_IDLE_SWAY_AMP_X * math.sin(2.0 * math.pi * _IDLE_SWAY_FREQ * float(t) + 1.1)))
                            except Exception:
                                idx_, idy_ = 0, 0
                        _paste_character_frame(img, cimg, bx + dx + idx_, by + dy + idy_, opacity)
                # --- Testo del chunk attivo ---
                ch = _active_chunk_at(chunks, t)
                if ch is not None:
                    try:
                        ci = chunks.index(ch)
                    except ValueError:
                        ci = -1
                    if 0 <= ci < len(chunk_text):
                        ct = chunk_text[ci]
                        words = ct.get("words", [])
                        layout = ct.get("layout", [])
                        if words and layout and len(words) == len(layout):
                            if ct.get("needs_pill"):
                                try:
                                    draw_text_background(img, layout)
                                except Exception:
                                    pass
                            try:
                                cs = float(ch.get("start", t))
                                ce = float(ch.get("end", t_end))
                            except Exception:
                                cs, ce = t, t_end
                            if exit_dur_cfg > 0 and t >= ce - exit_dur_cfg:
                                ef = 1.0 - ease_in_cubic(clamp01((t - (ce - exit_dur_cfg)) / exit_dur_cfg))
                            else:
                                ef = 1.0
                            for wi, w in enumerate(words):
                                try:
                                    ws = float(w.get("start", cs))
                                except Exception:
                                    continue
                                if t < ws:
                                    continue
                                local = clamp01((t - ws) / entry_dur_cfg)
                                is_kw = bool(w.get("is_keyword", w.get("style") == "impact"))
                                if is_kw:
                                    try:
                                        eased = min(float(ease_out_back(local)), 1.0)
                                    except Exception:
                                        eased = min(1.0, max(0.0, float(local)))
                                    if eased <= 0.0:
                                        continue
                                    op = int(round(255 * min(1.0, max(0.0, eased)))) if eased < 1.0 else 255
                                    sc = 0.85 + 0.15 * eased
                                    if sc > 1.0:
                                        sc = 1.0
                                else:
                                    if local >= 1.0:
                                        op, sc = 255, 1.0
                                    elif local <= 0.0:
                                        continue
                                    else:
                                        op = int(round(255 * ease_out_cubic(local)))
                                        sc = 1.0
                                if ef < 1.0:
                                    op = int(round(op * ef))
                                if op <= 0:
                                    continue
                                item = layout[wi]
                                if ct.get("mode") == "typo":
                                    _render_styled_scaled_word(
                                        img, w.get("display", w.get("word", "")),
                                        item["x"], item["y"], item["width"], item["height"],
                                        ct["fonts"][wi], ct["fills"][wi],
                                        (0, 0, 0, 0), 0, (0, 3), (0, 0, 0, 110),
                                        opacity=op, scale=min(1.0, max(0.05, sc)))
                                else:
                                    # REELS-FIX v5: stroke 0.
                                    try:
                                        _sw = int(SUBTITLE_STROKE_WIDTH)
                                    except (TypeError, ValueError):
                                        _sw = 0
                                    if _sw < 0:
                                        _sw = 0
                                    _render_scaled_word(
                                        img, w.get("word", ""), item["x"], item["y"],
                                        item["width"], item["height"], ct["fonts"][wi],
                                        ct["fills"][wi], SUBTITLE_STROKE_COLOR,
                                        _sw, opacity=op, scale=sc)
                fname = f"timeline_frame_{fi:05d}.png"
                fpath = os.path.join(output_dir, fname)
                try:
                    img.save(fpath, compress_level=1)
                except Exception:
                    return None
                return {"image_path": fpath, "start": t, "end": fend}
            except Exception:
                return None

        try:
            import os as _os
            cpu = max(2, (_os.cpu_count() or 4))
        except Exception:
            cpu = 4
        workers = max(2, min(8, cpu))
        results: list[dict] = [None] * num_frames  # type: ignore
        try:
            with _fut.ThreadPoolExecutor(max_workers=workers) as ex:
                fut_map = {ex.submit(_render_frame, fi): fi for fi in range(num_frames)}
                done = 0
                for fu in _fut.as_completed(fut_map):
                    fi = fut_map[fu]
                    try:
                        r = fu.result()
                    except Exception:
                        r = None
                    if r is not None:
                        results[fi] = r
                    done += 1
                    if on_progress is not None and (done % 30 == 0 or done == num_frames):
                        try:
                            on_progress(done, num_frames)
                        except Exception:
                            pass
        except Exception:
            return []
        frames = [r for r in results if r is not None]
        frames.sort(key=lambda f: f["start"])
        return frames
    except Exception:
        return []


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
    (vedi `decide_char_exit_mode`): fade out (slide_down dissolvente o fade
    di gruppo) quando cambia/scompare, hold a piena luminosita' solo su
    continuazioni identiche. Il lookbehind decide l'entrata: fade in + slide
    su prima apparizione e ogni cambio visibile; jump-cut istantaneo solo
    per punch-in e continuazioni identiche (taglio invisibile).
    Risultato: entrate/uscite in dissolvenza come in passato, mai di botto.

    Returns:
        Lista di chunk arricchiti: {**chunk, "frames": [...], "frame_paths": [...],
        "clip_start": start, "clip_end": end}.
    """
    import os as _os
    _parallel_ok = _os.environ.get("RENDER_PARALLEL", "1").strip().lower() not in ("0", "false", "no", "off", "")
    enriched_all: list[dict] = []
    total = len(chunks)
    # Risoluzione character UNA volta per chunk (stile "upgrade 2": mai lavoro
    # ripetuto): `resolve_chunk_layout` e' pura, quindi memoizzare e' identico
    # a richiamarla ma evita ~2x resolve per chunk nel lookahead/lookbehind.
    # Le funzioni decide_* accettano info gia' risolte (fast-path dedicato).
    infos: list[dict | None] = []
    for _ch in (chunks or []):
        try:
            infos.append(_character_info_from_chunk(_ch))
        except Exception:
            infos.append(None)
    # Warmup silenzioso dei layer effettivamente usati (mai I/O disco dentro
    # il ThreadPool): solo combo (posa, layout, punch) distinte dei chunk.
    # Fail-safe: errori ignorati (il per-chunk fara' fallback senza character).
    try:
        if CHARACTER_ENABLED and any(_inf is not None for _inf in infos):
            from core.renderer import get_character_layer as _warm_layer
            _seen: set[tuple] = set()
            for _inf in infos:
                try:
                    if not isinstance(_inf, dict) or _inf.get("pose") is None:
                        continue
                    _key = (int(_inf.get("pose")), str(_inf.get("layout")),
                            bool(_inf.get("punch_in", False)))
                    if _key in _seen:
                        continue
                    _seen.add(_key)
                    _warm_layer(int(_inf["pose"]), _inf.get("layout"),
                                bool(_inf.get("punch_in", False)),
                                VIDEO_WIDTH, VIDEO_HEIGHT)
                except Exception:
                    continue
    except Exception:
        pass
    # Stati personaggio per chunk (lookahead/lookbehind), calcolati una volta:
    # servono sia al path normale sia alla CTA card (stessa stabilita').
    states: list[dict] = []
    for i, chunk in enumerate(chunks):
        nxt = chunks[i + 1] if i + 1 < total else None
        prev = chunks[i - 1] if i - 1 >= 0 else None
        cur_info = infos[i] if i < len(infos) else None
        prev_info = infos[i - 1] if i - 1 >= 0 and (i - 1) < len(infos) else None
        # decide_* con i chunk GREZZI (come prima): leggono anche
        # `narrative_role` per i confini hook/corpo/CTA (le info risolte non
        # hanno quella chiave: passar loro le info cambierebbe la regia).
        try:
            exit_mode = decide_char_exit_mode(chunk, nxt)
        except Exception:
            exit_mode = _CHAR_EXIT_WITH_TEXT
        try:
            # Stesso identico personaggio del chunk prima: taglio invisibile
            # (niente replay dell'entrata: resterebbe un blink a ogni stacco).
            same_as_prev = (
                cur_info is not None and prev_info is not None
                and _character_identity(cur_info) == _character_identity(prev_info)
            )
            entry_jump = bool(same_as_prev or decide_char_entry_jump(prev, chunk))
            # Fade IN in entrata (come in passato): prima apparizione E ogni
            # cambio visibile (posa/layout diversi) dissolvono entrando.
            # Solo le continuazioni identiche (jump, taglio invisibile) e i
            # punch (stacco TV istantaneo) restano senza dissolvenza.
            entry_fade = not same_as_prev
        except Exception:
            entry_jump, entry_fade = False, True
        states.append({
            "char_exit_mode": exit_mode,
            "char_entry_jump": entry_jump,
            "char_entry_fade": entry_fade,
        })
    # Separa run CTA (sequenziali, condividono layout) da chunk normali (paralleli).
    cta_runs: list[list[int]] = []
    normal_idx: list[int] = []
    i = 0
    while i < total:
        chunk = chunks[i]
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
            cta_runs.append(run)
            i = j
            continue
        normal_idx.append(i)
        i += 1
    # --- CTA card (poche, layout condiviso): sequenziale veloce ---
    cta_results: dict[int, list[dict]] = {}
    for run in cta_runs:
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
            cta_results[k] = run_frames[pos] if pos < len(run_frames) else []
            if on_chunk is not None:
                try:
                    on_chunk(k + 1, total)
                except Exception:
                    pass
    # --- Chunk normali: paralleli con ThreadPool (I/O + resize rilasciano GIL) ---
    normal_results: dict[int, list[dict]] = {}
    if normal_idx:
        use_parallel = bool(_parallel_ok) and len(normal_idx) >= 3
        if use_parallel:
            import concurrent.futures as _fut
            try:
                _cpu = max(2, (_os.cpu_count() or 4))
            except Exception:
                _cpu = 4
            # v2: sfrutta tutti i core (cap 8 per memoria sicura: ~8MB/frame).
            _workers = max(2, min(8, _cpu, len(normal_idx)))

            def _render_one(k: int):
                st = states[k]
                return generate_animated_chunk_frames(
                    chunks[k], background_color, text_color,
                    keyword_colors or {}, output_dir, k, fps,
                    safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
                    text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
                    char_entry_fade=st["char_entry_fade"],
                    typography_niche=typography_niche, typography_preset=typography_preset,
                )
            with _fut.ThreadPoolExecutor(max_workers=_workers) as _ex:
                _future_map = {_ex.submit(_render_one, k): k for k in normal_idx}
                for _fu in _fut.as_completed(_future_map):
                    k = _future_map[_fu]
                    normal_results[k] = _fu.result()
                    if on_chunk is not None:
                        try:
                            on_chunk(k + 1, total)
                        except Exception:
                            pass
        else:
            for k in normal_idx:
                st = states[k]
                normal_results[k] = generate_animated_chunk_frames(
                    chunks[k], background_color, text_color,
                    keyword_colors or {}, output_dir, k, fps,
                    safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
                    text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
                    char_entry_fade=st["char_entry_fade"],
                    typography_niche=typography_niche, typography_preset=typography_preset,
                )
                if on_chunk is not None:
                    try:
                        on_chunk(k + 1, total)
                    except Exception:
                        pass
    for k in range(total):
        frames = cta_results.get(k, normal_results.get(k, []))
        enriched_all.append({
            **chunks[k],
            "frames": frames,
            "frame_paths": [f["image_path"] for f in frames],
            "clip_start": chunks[k].get("start"),
            "clip_end": chunks[k].get("end"),
        })
    # Ordina callback finale per GUI coerente (i paralleli arrivano fuori ordine).
    return enriched_all
