"""
Animazioni testo per-parola (Fase 3) + Dynamic Layout (sistema a zone)
+ Semantic Typography Engine v1 (stili misti per nicchia).

Ogni parola del chunk entra in scena esattamente al suo timestamp `start`
e resta visibile accumulandosi accanto alle precedenti; tutte le parole
scompaiono insieme a `chunk.end` (uscita di gruppo).

Tier moto T0-T3 (path tipografico; legacy solo T0/T2 per stabilita'):
- T0 base: entrata minimal (solo fade con `ease_out_cubic`, scala 1.0).
- T1 accent: rise-fade (opacita' + y +lift->0 con `ease_out_cubic`,
  MAI scala per non deformare handwritten; max 1 per chunk).
- T2 impact/keyword: pop premium (opacita' + scala pop_from->1.0 con
  `ease_out_back`; pop_from da preset nicchia 0.6-0.8, hook override vince).
  Unificazione: style==impact <=> keyword ai fini del MOTO (keywords.py resta
  fonte del COLORE, text_tagger resta fonte del MOTO).
- T3 hero: 1 parola/video (verbo CTA o climax hook, mai numeri): pop marcato
  0.6->1.0 in 0.22s + exit ritardata di 0.06s (~2 frame).
- T3-num: impact con cifre: pop corto dedicato 0.15s, mai hero.
- Uscita: fade di gruppo con `ease_in_cubic`; solo hero ha delay dedicato.
  `ease_out_bounce`/`elastic` restano disponibili ma non usati di default
  (troppo giocosi per caption da 2-3 parole).

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

Personaggio (mezzo busto/mezza figura, mai figura intera): idle breathing
leggero (solo bob verticale dolce 4px@0.4Hz, nessuna rotazione laterale);
prima apparizione slide&pop 0.20s da +300px (back+quad); cambi posa/lato
morph smart 0.40s dalla vecchia posizione (opaco, niente flash); sparizione
slide-drop +400px + fade 0.16s; punch_in zoom fluido 0.60s (mai jump secco);
stessa identita' -> hold invisibile; gap TTS coperti da tail anti-blink.

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
    CHARACTER_ENTRY_DURATION,
    CHARACTER_EXIT_DURATION,
    CHARACTER_FIRST_ENTRY_DURATION,
    CHARACTER_GAP_HOLD_ENABLED,
    CHARACTER_GAP_HOLD_MAX,
    CHARACTER_IDLE_AMP_Y,
    CHARACTER_IDLE_ENABLED,
    CHARACTER_IDLE_FREQ,
    CHARACTER_IDLE_TILT_DEG,
    CHARACTER_MORPH_DURATION,
    CHARACTER_PUNCH_ZOOM_DURATION,
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
    TEXT_ANIMATION_ACCENT_LIFT_PX,
    TEXT_ANIMATION_HERO_SCALE_FROM,
    TEXT_ANIMATION_HERO_ENTRY_DURATION,
    TEXT_ANIMATION_HERO_EXIT_DELAY,
    TEXT_ANIMATION_NUMBER_ENTRY_DURATION,
    TYPOGRAPHY_ENGINE_ENABLED,
    TYPOGRAPHY_BASE_FONT_SIZE,
    TYPOGRAPHY_BASE_WEIGHT,
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
    ease_out_quad,
    ease_in_out_cubic,
    ease_in_cubic,
)
try:
    from config import (
        ENABLE_ADVANCED_KINETICS as _ADV_KINETICS,
        COLOR_BRAND_ACCENT as _BRAND_ACCENT,
        BASE_WORD_FONT_PATH as _BASE_FONT_PATH,
        HERO_WORD_FONT_PATH as _HERO_FONT_PATH,
    )
except Exception:  # config datata
    _ADV_KINETICS = False
    _BRAND_ACCENT = "#FF3366"
    _BASE_FONT_PATH = "assets/fonts/Inter-Bold.ttf"
    _HERO_FONT_PATH = "assets/fonts/Montserrat-Black.ttf"
try:
    from core.advanced_kinetics import (
        advanced_entry_duration as _adv_entry_dur,
        advanced_stroke_for as _adv_stroke_for,
        brand_accent_rgba as _brand_rgba,
        draw_hero_badge as _draw_hero_badge,
        hero_shake_offset as _hero_shake,
        t2_peak_scale as _t2_peak,
    )
except Exception:  # modulo opzionale: path legacy invariato
    _adv_entry_dur = None
    _adv_stroke_for = None
    _brand_rgba = None
    _draw_hero_badge = None
    _hero_shake = None
    _t2_peak = None
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
# Entrata slide&pop: offset Y fisso +300px (spec), durata ENTRY (~0.20s).
_CHARACTER_ENTRY_SLIDE_Y = 300
# Uscita slide-drop: verso +400px con ease_in_cubic, durata EXIT (~0.16s).
_CHARACTER_EXIT_DROP_Y = 400
# Sistema a zone: prima apparizione fade+slide/zoom ENTRY (~0.20s, ~6 frame);
# uscita slide-drop+fade EXIT (~0.16s, ~5 frame) quando sparisce; morph di
# continuita' 0.40s e zoom punch smart 0.60s restano morbidi (ritmo coerente).
# Valori da config (override via env), fallback storici se import fallisce.
try:
    _CHARACTER_ZONE_ENTRY_DURATION = max(0.05, float(CHARACTER_ENTRY_DURATION))
except Exception:
    _CHARACTER_ZONE_ENTRY_DURATION = 0.20
try:
    _CHARACTER_ZONE_FIRST_DURATION = max(0.05, float(CHARACTER_FIRST_ENTRY_DURATION))
except Exception:
    _CHARACTER_ZONE_FIRST_DURATION = 0.20
try:
    _CHARACTER_ZONE_EXIT_DURATION = max(0.05, float(CHARACTER_EXIT_DURATION))
except Exception:
    _CHARACTER_ZONE_EXIT_DURATION = 0.16
try:
    _CHARACTER_MORPH_DURATION = max(0.05, float(CHARACTER_MORPH_DURATION))
except Exception:
    _CHARACTER_MORPH_DURATION = 0.40
try:
    _CHARACTER_PUNCH_DURATION = max(0.20, float(CHARACTER_PUNCH_ZOOM_DURATION))
except Exception:
    _CHARACTER_PUNCH_DURATION = 0.60
# Zoom-in dolce per transizione "zoom_in" (center alternativi): scala 0.92->1.0.
_CHARACTER_ZOOM_FROM = 0.92
_CHARACTER_ZOOM_DURATION = 0.45
# Idle breathing leggero ma visibile (spec): solo bob verticale dolce
# dy=sin(2*pi*f*t)*amp_y (4px@0.4Hz); tilt disabilitato (0 = nessuna
# rotazione laterale, niente dondolio). Overhead <5ms: bob = offset intero
# (costo zero); il ramo tilt resta solo se l'utente lo riabilita via env.
try:
    _IDLE_ENABLED = int(CHARACTER_IDLE_ENABLED) != 0
except Exception:
    _IDLE_ENABLED = True
try:
    _IDLE_AMP_Y = max(0.0, float(CHARACTER_IDLE_AMP_Y))
except Exception:
    _IDLE_AMP_Y = 4.0
try:
    _IDLE_FREQ = max(0.05, float(CHARACTER_IDLE_FREQ))
except Exception:
    _IDLE_FREQ = 0.4
try:
    _IDLE_TILT_DEG = max(0.0, float(CHARACTER_IDLE_TILT_DEG))
except Exception:
    _IDLE_TILT_DEG = 0.0
_IDLE_TILT_STEP = 0.3  # quantizzazione tilt per cache (<=9 varianti per size)
_TWO_PI = 6.283185307179586
# Cache rotazioni tilt: {(id(img), tilt_q): img ruotata} con lock, cap 64.
_tilt_cache: dict[tuple[int, float], Image.Image] = {}
_tilt_cache_lock = threading.Lock()
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


# Cache varianti opacity personaggio: {(id(char), opacity//16): img} evita copy+point per frame.
_char_opacity_cache: dict[tuple[int, int], Image.Image] = {}
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
    key = (id(char_img), q)
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
# Tier animazioni testo T0-T3 (premium senza over-engineering)
# ---------------------------------------------------------------------------
# Unificazione moto/colore (singola fonte di verita'):
# - moto  = (style, is_hero, is_number) da text_tagger/narrative_structure
#   (style==impact <=> keyword ai fini dell'animazione; keywords.py resta
#   fonte del COLORE, text_tagger resta fonte del MOTO);
# - colore = _styled_fills (tema + highlight preset + palette keyword fallback).
# Tier:
#   T0 base   fade (solo opacita', scala 1, draw diretto: costo ~0);
#   T1 accent rise-fade (opacita' + y lift px, MAI scala: non deforma
#     handwritten; costo +5%, solo offset, nessun resize);
#   T2 impact pop standard (opacita' + scala ease_out_back, tile resize);
#   T3 hero   1 parola/video (pop marcato + durata lunga + exit ritardata);
#   T3-num    impact con cifre (pop corto dedicato, mai hero).
# Path legacy (senza styled_words) usa solo T0/T2 per stabilita'.

def _has_digit_fast(text: str) -> bool:
    """Vero se contiene una cifra (numeri/dati -> pop corto, mai hero)."""
    try:
        for _c in str(text or ""):
            if "0" <= _c <= "9":
                return True
        return False
    except Exception:
        return False


def _resolve_motion_params(
    preset: dict | None,
    chunk: dict | None,
) -> tuple[float, float, float, float, float, float]:
    """Risolvi (entry_dur, scale_from, accent_lift, hero_dur, hero_from,
    number_dur) con priorita' stabile e clamp.

    - entry_dur: base config * anim_entry_mult del chunk (hook scattante);
      hero usa poi HERO_ENTRY_DURATION (override, non moltiplicato).
    - scale_from: chunk anim_pop_from esplicito (hook) > preset anim.pop_from
      (nicchia) > KEYWORD_ENTRY_SCALE_FROM globale.
    Mai eccezioni: fallback ai default storici.
    """
    try:
        _entry_base = max(0.01, float(TEXT_ANIMATION_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _entry_base = 0.18
    try:
        _mult = float((chunk or {}).get("anim_entry_mult", 1.0)) if isinstance(chunk, dict) else 1.0
        if 0.3 <= _mult <= 1.5:
            entry_dur = max(0.01, _entry_base * _mult)
        else:
            entry_dur = _entry_base
    except (TypeError, ValueError, AttributeError):
        entry_dur = _entry_base
    try:
        _global_from = float(KEYWORD_ENTRY_SCALE_FROM)
        if not (0.1 <= _global_from <= 1.0):
            _global_from = 0.7
    except (TypeError, ValueError, NameError):
        _global_from = 0.7
    # Preset nicchia (se disponibile) come default di tier.
    try:
        _preset_from = float((preset or {}).get("anim", {}).get("pop_from", _global_from))
        if not (0.1 <= _preset_from <= 1.0):
            _preset_from = _global_from
    except (TypeError, ValueError, AttributeError):
        _preset_from = _global_from
    scale_from = _preset_from
    # Override esplicito per-chunk (hook narrativo) vince su tutto.
    try:
        if isinstance(chunk, dict) and "anim_pop_from" in chunk:
            _pop = float(chunk.get("anim_pop_from", scale_from))
            if 0.1 <= _pop <= 1.0:
                scale_from = _pop
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        _lift = float(TEXT_ANIMATION_ACCENT_LIFT_PX)
        _lift = min(24.0, max(0.0, _lift))
    except (TypeError, ValueError, NameError):
        _lift = 10.0
    try:
        _hero_dur = max(0.05, float(TEXT_ANIMATION_HERO_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _hero_dur = 0.22
    try:
        _hero_from = float(TEXT_ANIMATION_HERO_SCALE_FROM)
        if not (0.1 <= _hero_from <= 1.0):
            _hero_from = 0.6
    except (TypeError, ValueError, NameError):
        _hero_from = 0.6
    try:
        _num_dur = max(0.05, float(TEXT_ANIMATION_NUMBER_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _num_dur = 0.15
    try:
        _hero_delay = max(0.0, float(TEXT_ANIMATION_HERO_EXIT_DELAY))
        _hero_delay = min(0.20, _hero_delay)
    except (TypeError, ValueError, NameError):
        _hero_delay = 0.06
    return entry_dur, scale_from, _lift, _hero_dur, _hero_from, _num_dur


def _hero_exit_delay() -> float:
    """Ritardo exit hero in secondi (clamp 0-0.20, default 0.06 ~2 frame)."""
    try:
        _d = max(0.0, float(TEXT_ANIMATION_HERO_EXIT_DELAY))
        return min(0.20, _d)
    except (TypeError, ValueError, NameError):
        return 0.06


def _word_tier(word: dict) -> tuple[str, bool, bool]:
    """Tier moto per parola tipografica: (style, is_hero, is_number).

    Normalizza style a base/impact/accent; is_hero vale solo su impact senza
    cifre (numeri mai hero); is_number da flag o digit check. Mai eccezioni.
    """
    try:
        _style = str((word or {}).get("style", "base"))
    except Exception:
        _style = "base"
    if _style not in ("base", "impact", "accent"):
        # Compat legacy: is_keyword True <=> impact (unificazione).
        try:
            _style = "impact" if bool((word or {}).get("is_keyword", False)) else "base"
        except Exception:
            _style = "base"
    try:
        _is_num = bool((word or {}).get("is_number", False)) or _has_digit_fast(
            str((word or {}).get("word", "")))
    except Exception:
        _is_num = False
    try:
        _is_hero = bool((word or {}).get("is_hero", False))
    except Exception:
        _is_hero = False
    if _style != "impact" or _is_num:
        _is_hero = False
    return _style, _is_hero, _is_num


def _hero_exit_factor(
    t: float,
    chunk_end: float,
    exit_dur: float,
    exit_factor_base: float,
) -> float:
    """Exit factor ritardato per hero: resta 1.0 per hero_delay, poi fade compresso.

    Mantiene l'allineamento a chunk_end (nessun frame oltre): se exit_dur <=
    delay, usa il fade base. Curva identica al gruppo (ease_in_cubic).
    """
    try:
        if exit_dur <= 0:
            return exit_factor_base
        _delay = _hero_exit_delay()
        if _delay <= 0.0 or exit_dur <= _delay + 1e-6:
            return exit_factor_base
        _start = chunk_end - exit_dur + _delay
        if t < _start:
            return 1.0
        _p = clamp01((t - _start) / max(1e-6, exit_dur - _delay))
        return 1.0 - ease_in_cubic(_p)
    except Exception:
        return exit_factor_base


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


def _resolve_base_weight() -> int:
    """Peso desiderato del font base (default 600 = SemiBold, clamp 400-800)."""
    try:
        w = int(TYPOGRAPHY_BASE_WEIGHT)
    except (TypeError, ValueError, NameError):
        w = 600
    return min(800, max(400, w))


def _apply_font_weight(font, weight: int) -> bool:
    """Imposta l'asse Weight di un font variabile (es. 600 = SemiBold).

    Cerca l'asse "Weight" tra quelli del file (ordine qualunque: funziona con
    Inter[opsz,wght], Roboto[wdth,wght] e single-axis), preserva i default
    degli altri assi e clamp al range del font. Ritorna True se applicato.
    Ritorna False per font statici (Anton, Poppins, ...): per quelli il
    chiamante usa il grassetto sintetico (stroke 1px stesso colore).
    Mai eccezioni.
    """
    if font is None:
        return False
    try:
        axes = font.get_variation_axes()
    except Exception:
        return False
    if not axes:
        return False
    try:
        w_idx = None
        for i, ax in enumerate(axes):
            try:
                nm = ax.get("name", b"") if isinstance(ax, dict) else b""
                nm = bytes(nm).lower() if isinstance(nm, bytes) else str(nm).lower().encode("utf-8", "ignore")
            except Exception:
                continue
            if b"weight" in nm:
                w_idx = i
                break
        if w_idx is None:
            return False
        coords: list = []
        for i, ax in enumerate(axes):
            try:
                lo = float(ax["minimum"])
                de = float(ax["default"])
                hi = float(ax["maximum"])
            except (KeyError, TypeError, ValueError):
                return False
            if i == w_idx:
                coords.append(int(round(min(hi, max(lo, float(weight))))))
            else:
                coords.append(de)
        font.set_variation_by_axes(coords)
        return True
    except Exception:
        return False


# Grassetto sintetico per font base statici (Poppins/Lato/...): 1px con lo
# stesso colore del fill = inspessimento leggero, nessun contorno nero.
_BASE_SYNTHETIC_STROKE_WIDTH = 1


def _load_typography_fonts(preset: dict, font_scale: float = 1.0) -> dict:
    """Carica i 3 font PIL del preset alle dimensioni ponderate.

    - base:   size standard (es. 60px) * font_scale del layout preset,
      SEMPRE al peso TYPOGRAPHY_BASE_WEIGHT (600 = SemiBold: leggermente più
      in grassetto del Regular, non troppo). Vedi `_apply_font_weight`.
    - impact: base * impact_scale (1.3x-1.5x, es. 80-90px, peso suo proprio)
    - accent: base * accent_scale (1.1x, peso suo proprio)
    Ritorna {"base": font, "impact": font, "accent": font, "sizes": {...},
    "paths": {...}, "names": {...}, "base_weight": int,
    "base_weight_applied": bool}. Se False (font statico), il rendering usa
    il grassetto sintetico per le parole base (vedi _BASE_SYNTHETIC_STROKE_WIDTH).
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
    # Peso base (600 = SemiBold): nella chiave cache del base, così istanze
    # con pesi diversi non si condividono mai.
    base_weight = _resolve_base_weight()
    fonts_cfg = preset.get("fonts", {}) if isinstance(preset, dict) else {}
    out: dict = {"sizes": sizes, "paths": {}, "names": {},
                 "base_weight": base_weight, "base_weight_applied": False}
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
                key = (path, sizes[role], base_weight) if role == "base" else (path, sizes[role])
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
                            key = (fb_path, sizes[role], base_weight) if role == "base" else (fb_path, sizes[role])
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
    # Peso SemiBold sul base (testo chiaro): True su variabile, False su
    # statico (il rendering usa allora il grassetto sintetico per il base).
    # Idempotente sulle istanze cachate (stesso peso = nessun cambio).
    try:
        out["base_weight_applied"] = bool(_apply_font_weight(out.get("base"), base_weight))
    except Exception:
        out["base_weight_applied"] = False
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
    """Metadati character dal chunk arricchito (None se assenti/disabilitati/nascosti).

    Presenza discontinua (Breath & Focus): se chunk["character"]["visible"]
    e' False (o char_visible False / guard_hidden) il personaggio e' HIDDEN
    in questo chunk (nessun layer, schermo pulito solo testo). Risolve
    tramite `resolve_chunk_layout` (singola fonte condivisa col text engine).
    """
    if not CHARACTER_ENABLED:
        return None
    try:
        if isinstance(chunk, dict):
            _ch = chunk.get("character")
            if isinstance(_ch, dict) and not bool(_ch.get("visible", True)):
                return None
            if chunk.get("char_visible") is False:
                return None
            if chunk.get("guard_hidden") is True:
                return None
    except Exception:
        pass
    try:
        return resolve_chunk_layout(chunk)
    except Exception:
        return None


def _character_event_of(chunk: dict | None) -> str:
    """Evento macro-blocco del chunk (ENTRY/SUSTAIN/EXIT/NONE, mai eccezioni)."""
    try:
        from core.character_animator import CharacterFrameAnimator as _A
        return _A.event_of(chunk)
    except Exception:
        pass
    try:
        if not isinstance(chunk, dict):
            return "NONE"
        _ch = chunk.get("character")
        if isinstance(_ch, dict):
            if not bool(_ch.get("visible", True)):
                return "NONE"
            _ev = str(_ch.get("event", "") or "").strip().upper()
            if _ev in ("ENTRY", "SUSTAIN", "EXIT", "NONE"):
                return _ev
        _ev2 = str(chunk.get("char_event", "") or "").strip().upper()
        if _ev2 in ("ENTRY", "SUSTAIN", "EXIT", "NONE"):
            return _ev2
        return "SUSTAIN" if chunk.get("pose") is not None else "NONE"
    except Exception:
        return "NONE"


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


def _character_entry_transform(
    transition: str,
    side: str,
    progress: float,
    img_w: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    full_travel: bool = False,
    fade: bool = True,
) -> tuple[int, int, int, float]:
    """Offset (dx, dy), opacita' 0-255 e scala del personaggio al `progress`.

    Entrata slide&pop (spec ~0.20s, ~6 frame): fade fluido (ease_out_quad) +
    slide con ease_out_back (overshoot leggero, effetto pop premium) da offset
    Y fisso +300px, o zoom dolce 0.92->1.0 per "zoom_in". L'overshoot supera di
    poco la posizione finale e rientra: niente scatti, ritmo coerente.
    """
    p = clamp01(progress)
    t = str(transition or "fade")
    if t == "slide_side":
        t = "slide_from_left" if side == "left" else "slide_from_right"
    elif t == "slide_from_bottom":
        t = "slide_up"
    if t in ("none",):
        return (0, 0, 255, 1.0)
    # Fade fluido (quad) + pop con overshoot leggero (back): ingresso premium.
    fade_eased = ease_out_quad(p)
    pop_eased = ease_out_back(p)
    move_eased = ease_out_cubic(p)
    opacity = int(round(255 * fade_eased)) if fade else 255
    if t == "fade":
        return (0, 0, opacity, 1.0)
    if t in ("zoom", "zoom_in", "scale_in", "scale-in"):
        scale = _CHARACTER_ZOOM_FROM + (1.0 - _CHARACTER_ZOOM_FROM) * move_eased
        return (0, 0, opacity, float(scale))
    if t in ("slide_from_left", "slide_from_right"):
        if full_travel and img_w > 0:
            start_x = -img_w if t == "slide_from_left" else VIDEO_WIDTH
            dx = int(round((start_x - base_x) * (1.0 - pop_eased)))
        else:
            direction = -1 if t == "slide_from_left" else 1
            dx = int(round(direction * _CHARACTER_SLIDE_SIDE_PX * (1.0 - pop_eased)))
        return (dx, 0, opacity, 1.0)
    # slide_up (default anche per valori ignoti: mai un taglio secco a sorpresa)
    # Spec: offset Y fisso +300px (non full off-screen), pop con overshoot.
    if full_travel:
        dy = int(round(_CHARACTER_ENTRY_SLIDE_Y * (1.0 - pop_eased)))
    else:
        dy = int(round(_CHARACTER_SLIDE_UP_PX * (1.0 - pop_eased)))
    return (0, dy, opacity, 1.0)


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
    """Offset (dx, dy) e opacita' 0-255 (compat: ignora la scala zoom_in).

    Per lo zoom_in la scala e' gestita dal chiamante via
    `_character_entry_transform` (0.92->1.0 fluido); qui ritorna solo
    offset+opacita' per non rompere i chiamanti legacy.
    """
    dx, dy, op, _scale = _character_entry_transform(
        transition, side, progress, img_w, base_x, base_y, full_travel, fade)
    return (dx, dy, op)


def _character_morph_offset(
    from_xy: tuple[int, int] | None,
    to_xy: tuple[int, int],
    progress: float,
) -> tuple[int, int]:
    """Offset di morph da posizione precedente a quella corrente (smart animate).

    Il character parte dalla vecchia posizione (continuità, niente flash di
    sfondo) e scivola alla nuova con ease_in_out_cubic (partenza/arrivo
    morbidi). Sempre a piena opacita': niente sparizioni nei cambi posa/lato.
    Se from_xy e' None o uguale a to_xy, ritorna (0,0).
    """
    try:
        if from_xy is None:
            return (0, 0)
        fx, fy = int(from_xy[0]), int(from_xy[1])
        tx, ty = int(to_xy[0]), int(to_xy[1])
    except (TypeError, ValueError, IndexError):
        return (0, 0)
    dx0, dy0 = fx - tx, fy - ty
    if dx0 == 0 and dy0 == 0:
        return (0, 0)
    e = ease_in_out_cubic(clamp01(progress))
    return (int(round(dx0 * (1.0 - e))), int(round(dy0 * (1.0 - e))))


def _idle_bob_tilt(t_abs: float) -> tuple[int, float]:
    """Respiro idle leggero al tempo assoluto video `t_abs` (secondi).

    - Bob verticale dolce: dy = sin(2*pi*freq*t) * amp_y (default 0.4Hz, 4px:
      leggero ma percettibile, mai statico).
    - Tilt disabilitato di default (0.0 gradi: nessuna rotazione laterale, il
      dondolio destra-sinistra rendeva il video instabile). Resta attivo solo
      se l'utente imposta CHARACTER_IDLE_TILT_DEG > 0 via env.
    Ritorna (dy_px_int, tilt_deg_float). Costo ~1us (sin+cos). Con idle
    disabilitato o ampiezze zero ritorna (0, 0.0) senza calcoli trig.
    """
    try:
        if not _IDLE_ENABLED or (_IDLE_AMP_Y <= 0 and _IDLE_TILT_DEG <= 0):
            return (0, 0.0)
        phase = _TWO_PI * _IDLE_FREQ * float(t_abs)
    except (TypeError, ValueError):
        return (0, 0.0)
    try:
        dy = int(round(math.sin(phase) * _IDLE_AMP_Y)) if _IDLE_AMP_Y > 0 else 0
    except Exception:
        dy = 0
    try:
        tilt = float(math.cos(phase) * _IDLE_TILT_DEG) if _IDLE_TILT_DEG > 0 else 0.0
    except Exception:
        tilt = 0.0
    return (dy, tilt)


def _get_tilted_char(char_img: Image.Image, tilt_deg: float):
    """Layer ruotato di `tilt_deg` attorno al punto inferiore centrale (w/2, h).

    L'ancoraggio in basso evita che il personaggio si stacchi dal fondo: la
    base resta ferma, la testa culla lateralmente. Tilt quantizzato a step
    0.3 gradi e cachato (<=9 varianti per size): hit = lookup <1ms, miss =
    una rotazione BILINEAR ammortizzata. tilt ~0 o idle OFF = layer originale.
    Mai eccezioni (fallback: originale).
    """
    try:
        if char_img is None:
            return char_img
        if not _IDLE_ENABLED:
            return char_img
        try:
            tilt = float(tilt_deg)
        except (TypeError, ValueError):
            return char_img
        if abs(tilt) < 1e-9:
            return char_img
        q = round(tilt / _IDLE_TILT_STEP) * _IDLE_TILT_STEP
        q = max(-3.0, min(3.0, float(q)))
        if abs(q) < 1e-9:
            return char_img
        key = (id(char_img), q)
        hit = _tilt_cache.get(key)
        if hit is not None:
            return hit
        with _tilt_cache_lock:
            hit = _tilt_cache.get(key)
            if hit is not None:
                return hit
            try:
                w, h = char_img.size
                rotated = char_img.rotate(
                    q, resample=Image.BILINEAR, center=(w / 2.0, float(h)))
                if rotated.mode != "RGBA":
                    rotated = rotated.convert("RGBA")
            except Exception:
                return char_img
            if len(_tilt_cache) < 64:
                if len(_tilt_cache) >= 60:
                    _tilt_cache.clear()
                _tilt_cache[key] = rotated
            return rotated
    except Exception:
        try:
            return char_img
        except Exception:
            return None


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


def _same_pose(a: dict | None, b: dict | None) -> bool:
    """Vero se entrambi hanno la STESSA posa (stessa immagine), o None altrimenti.

    E' il check anti-sparizione: stessa posa = stessa immagine = il
    personaggio non deve mai uscire di scena (niente slide_down, niente
    rientro da fuori campo). Mai eccezioni.
    """
    try:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        if a.get("pose") is None or b.get("pose") is None:
            return False
        return int(a.get("pose")) == int(b.get("pose"))
    except Exception:
        return False


def decide_char_exit_mode(current: dict | None, nxt: dict | None) -> str:
    """Modalita' di uscita del personaggio guardando il chunk successivo.

    Invariante anti-blink (fix sparizione/riapparizione): il personaggio resta
    visibile fino allo stacco OGNI VOLTA che il chunk dopo ha un personaggio,
    qualunque sia il cambio (posa/lato/punch). L'uscita animata scatta SOLO
    quando deve chiaramente scomparire (chunk dopo senza personaggio, o fine
    video): fade-out fluido dedicato (non legato al fade testo).

    - Chunk dopo senza personaggio (o fine video) -> "with_text" (fade-out
      fluido con durata character dedicata: sparizione chiara e intenzionale).
    - Chunk dopo CON personaggio -> "hold" SEMPRE (niente slide_down: lo
      slide_down storico svuotava lo schermo a fine chunk e creava il blink
      nei gap; ora il morph in entrata del chunk dopo parte dalla vecchia
      posizione con continuita' pixel, e la persistenza nei gap copre le pause).
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
        return _CHAR_EXIT_WITH_TEXT  # sparizione (o fine video): fade fluido
    return _CHAR_EXIT_HOLD  # continuita': resta fino allo stacco, morph dopo


def decide_char_entry_jump(prev: dict | None, current: dict | None) -> bool:
    """Vero se l'entrata dev'essere istantanea (taglio invisibile).

    SOLO a identita' pixel-identica (stessa posa+zona+punch del chunk prima):
    il frame e' identico, nessuna animazione da replayare (replay creerebbe
    un blink a ogni stacco). In tutti gli altri casi (cambio posa/lato,
    punch che si accende/spegne, zoom hook) l'entrata e' MORPH/zoom fluido,
    MAI jump-cut secco (fix scatto hook). Accetta chunk grezzi o info risolte;
    mai eccezioni.
    """
    try:
        cur = current if isinstance(current, dict) and "pose" in current and "use_preset" in current \
            else resolve_chunk_layout(current)
    except Exception:
        return False
    if cur is None:
        return False
    try:
        before = prev if isinstance(prev, dict) and "pose" in prev and "use_preset" in prev \
            else resolve_chunk_layout(prev)
    except Exception:
        return False
    if before is None:
        return False
    try:
        return _character_identity(cur) == _character_identity(before)
    except Exception:
        return False


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
    char_entry_from_xy: tuple[int, int] | None = None,
    tail_hold_duration: float = 0.0,
    char_prev_layer=None,
    char_micro_blend: bool = False,
) -> list[dict]:
    """Genera la sequenza di frame PNG per un chunk con animazione per-parola.

    Args:
        chunk: {"text", "start", "end", "words": [{"word","start","end",...}]}.
            Se "words" manca, viene ricostruita (vedi `enrich_chunk_words`).
            Puo' contenere pose/layout/punch_in del personaggio
            (vedi core/character_selector.py): il personaggio (mezzo busto,
            mai figura intera) viene disegnato sotto il testo (Z-index: sfondo
            ffmpeg < personaggio < sottotitoli, con pill ad alto contrasto per
            il punch-in) con slide&pop 0.20s +300px alla prima apparizione,
            idle breathing/sway continuo, morph smart nei cambi e zoom fluido
            0.6s per il punch hook (mai jump-cut secco).
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
        char_exit_mode: "with_text" (fade-out fluido dedicato quando il
            personaggio sparisce), "slide_down" (legacy, trattato come hold
            per continuita') o "hold" (resta opaco fino allo stacco +
            persistenza nel gap, mai blink). Di solito calcolato con
            `decide_char_exit_mode` guardando il chunk successivo
            (vedi `render_all_chunks_animated`).
        char_exit_duration: durata fade-out personaggio (default da config).
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.
        char_entry_jump: True SOLO a identita' pixel-identica (stesso
            posa+zona+punch del chunk prima: taglio invisibile, nessuna
            animazione). Di solito calcolato con `decide_char_entry_jump`.
        char_entry_fade: True alla prima apparizione (fade+slide/zoom da fuori
            campo); False nei morph di continuita' (slide dalla vecchia
            posizione a piena opacita', niente flash di sfondo).
        char_entry_from_xy: posizione base (x,y) del character nel chunk
            precedente per il morph smart (None = prima apparizione).
        tail_hold_duration: secondi extra oltre chunk.end in cui clonare
            l'ultimo frame (persistenza nel gap quando il character continua:
            fix blink sparizione/riapparizione). Solo con hold.
        typography_niche: nicchia esplicita (override di chunk["typography_niche"]).
        typography_preset: preset dict esplicito (da core/typography_presets.get_preset).

    Returns:
        Lista di dict {"image_path": str, "start": float, "end": float}
        - uno per ogni frame generato, con la finestra temporale in cui
        quel frame specifico deve essere mostrato (frame N valido da
        t_N a t_N+1/fps). Include gli eventuali tail di persistenza.
        Formato compatibile con `core/video_builder.py` (micro-video per chunk).
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
    # Real-time Layout Guard (core/layout_guard.py): override per-chunk
    # (safe area + font shrink + pill) calcolato prima del render.
    # Precedenza: explicit globale > guard > preset.
    try:
        if explicit_box is None and isinstance(chunk, dict):
            _gsa = chunk.get("guard_safe_area")
            if _gsa is not None:
                _gbox = (int(_gsa[0]), int(_gsa[1]), int(_gsa[2]), int(_gsa[3]))
                if _gbox[2] > _gbox[0] and _gbox[3] > _gbox[1]:
                    area = _gbox
            _gfs = chunk.get("guard_font_scale")
            if _gfs is not None:
                _gfs_f = float(_gfs)
                if 0.5 <= _gfs_f <= 1.5:
                    font_scale = _gfs_f
            if chunk.get("guard_pill"):
                needs_pill = True
    except Exception:
        pass

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
                _is_num_s = bool(s.get("is_number", False)) or _has_digit_fast(word_text)
                _is_hero_s = bool(s.get("is_hero", False)) and style == "impact" and not _is_num_s
                styled_words.append({
                    "word": word_text, "display": display, "style": style,
                    "start": st, "end": en,
                    "is_keyword": style == "impact",
                    "is_hero": _is_hero_s,
                    "is_number": _is_num_s,
                })
        if not styled_words:
            # Deriva da words legacy: keyword -> impact, resto base.
            styled_words = []
            for w in words:
                style = "impact" if w.get("is_keyword") else "base"
                disp = str(w["word"]).upper() if (style == "impact" and uppercase_impact) else str(w["word"])
                _wn = str(w.get("word", ""))
                _in = _has_digit_fast(_wn)
                styled_words.append({
                    "word": _wn, "display": disp, "style": style,
                    "start": float(w["start"]), "end": float(w["end"]),
                    "is_keyword": bool(w.get("is_keyword", False)),
                    "is_hero": False,
                    "is_number": _in,
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
        # Per il loop di rendering riusa `words` come alias di styled
        # (is_keyword <=> style==impact per unificazione moto; hero/number
        # preservati per i tier T3).
        words = [
            {"word": s["display"], "start": s["start"], "end": s["end"],
             "is_keyword": s["style"] == "impact", "style": s["style"],
             "is_hero": bool(s.get("is_hero", False)),
             "is_number": bool(s.get("is_number", False))}
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

    # Grassetto sintetico per il base statico (Poppins/Lato/...): se il peso
    # variabile NON è stato applicato, le parole base usano stroke 1px dello
    # stesso colore (inspessimento leggero, nessun contorno nero).
    try:
        _base_synth = bool(use_typography and isinstance(typo_fonts, dict)
                           and not typo_fonts.get("base_weight_applied", False))
    except Exception:
        _base_synth = False

    # Tier T0-T3: entry/scala da config + preset nicchia + override hook.
    # Priorita' scala: chunk anim_pop_from (hook) > preset anim.pop_from >
    # globale. Hero e numeri hanno durate dedicate (vedi _resolve_motion_params).
    try:
        exit_dur = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    except (TypeError, ValueError, NameError):
        exit_dur = 0.15
    try:
        entry_dur, scale_from, accent_lift, hero_dur, hero_from, number_dur = (
            _resolve_motion_params(typo_preset if use_typography else None, chunk)
        )
    except Exception:
        entry_dur, scale_from = 0.18, 0.7
        accent_lift, hero_dur, hero_from, number_dur = 10.0, 0.22, 0.6, 0.15
    # Per-parola (fuori loop frame): tier + durata entry dedicata.
    # Legacy (no tipografia): solo T0/T2 via is_keyword, mai accent/hero/number.
    try:
        if use_typography:
            _tiers = [_word_tier(w) for w in words]
            _entry_per_word = [
                (hero_dur if _h else (number_dur if (_s == "impact" and _n) else entry_dur))
                for (_s, _h, _n) in _tiers
            ]
            _scale_per_word = [
                (hero_from if _h else scale_from) if _s == "impact" else 1.0
                for (_s, _h, _n) in _tiers
            ]
        else:
            _tiers = [("impact" if bool(w.get("is_keyword", False)) else "base", False, False)
                      for w in words]
            _entry_per_word = [entry_dur] * len(words)
            _scale_per_word = [(scale_from if _s == "impact" else 1.0) for (_s, _, _) in _tiers]
    except Exception:
        _tiers = [("base", False, False)] * len(words)
        _entry_per_word = [entry_dur] * len(words)
        _scale_per_word = [1.0] * len(words)

    # --- Full Engine Upgrade Fase 2: cinetica avanzata (opt-in, mai regressioni) ---
    # T0/T1 fade-in 2 frame, T2 brand accent con picco 110%, T3 badge+shake.
    # Timestamp start/end MAI toccati: solo durate di entrata e resa visiva.
    _adv_enabled = False
    try:
        _adv_enabled = bool(_ADV_KINETICS) and (_adv_entry_dur is not None)
    except Exception:
        _adv_enabled = False
    if _adv_enabled:
        try:
            _fps_adv = int(fps) if int(fps) > 0 else 30
        except Exception:
            _fps_adv = 30
        try:
            for _ai, (_s, _h, _n) in enumerate(list(_tiers)):
                if _s in ("base", "accent") and _adv_entry_dur is not None:
                    try:
                        _entry_per_word[_ai] = float(_adv_entry_dur(_s, float(_entry_per_word[_ai]), _fps_adv))
                    except Exception:
                        pass
            # T2 -> brand accent (coerenza marchio); T3 tiene highlight + badge.
            if _brand_rgba is not None:
                try:
                    _brand_fill = _brand_rgba()
                    for _ai, (_s, _h, _n) in enumerate(list(_tiers)):
                        if _s == "impact" and not _h and not _n and _ai < len(fills):
                            fills[_ai] = _brand_fill
                except Exception:
                    pass
        except Exception:
            pass

    # --- Personaggio del chunk (layer UNA volta, riusato in ogni frame) ---
    # Z-index sui frame: 1. sfondo (ffmpeg) / 2. personaggio / 2.5 pill / 3. testo.
    # Slide&pop 0.20s +300px alla prima apparizione; morph smart 0.40s in
    # continuita' (piena opacita', niente flash); identita' pixel-identica:
    # taglio invisibile (jump); punch: zoom 0.6s smart; idle continuo sopra.
    char_img, char_base_xy = _load_chunk_character_layer(char_info)
    char_punch = bool(char_info is not None and char_info.get("punch_in", False)) if char_info is not None else False
    char_base_img = None  # layer non-punch per zoom fluido (punch=true)
    char_base_pos: tuple[int, int] | None = None
    char_original = None  # sorgente full-res per resize zoom per-frame
    if char_img is not None and char_base_xy is not None and char_info is not None:
        char_transition = char_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(char_info)
        char_full_travel = bool(use_preset)
        char_entry_jump = bool(char_entry_jump)
        char_entry_fade = bool(char_entry_fade)
        # Prima apparizione: slide&pop 0.20s +300px (spec, back+quad).
        # Morph di continuita': 0.40s dalla vecchia posizione (smart animate).
        if char_entry_fade:
            char_entry_dur = max(0.01, _CHARACTER_ZONE_FIRST_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        else:
            char_entry_dur = max(0.01, _CHARACTER_MORPH_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        # Morph: valida from_xy (deve essere on-screen e sensato).
        char_morph_from: tuple[int, int] | None = None
        if not char_entry_jump and not char_entry_fade and char_entry_from_xy is not None:
            try:
                _fx, _fy = int(char_entry_from_xy[0]), int(char_entry_from_xy[1])
                if -VIDEO_WIDTH < _fx < VIDEO_WIDTH * 2 and -VIDEO_HEIGHT < _fy < VIDEO_HEIGHT * 2:
                    if (_fx, _fy) != (int(char_base_xy[0]), int(char_base_xy[1])):
                        char_morph_from = (_fx, _fy)
            except (TypeError, ValueError, IndexError):
                char_morph_from = None
        else:
            char_morph_from = None
        # Punch zoom fluido: prepara base + sorgente per interpolazione scala.
        char_punch_active = bool(char_punch and not char_entry_jump)
        if char_punch_active:
            try:
                if bool(char_info.get("use_preset")):
                    char_base_img, _bx, _by = get_character_layer(
                        int(char_info["pose"]), char_info.get("layout"),
                        False, VIDEO_WIDTH, VIDEO_HEIGHT)
                    char_base_pos = (int(_bx), int(_by))
                else:
                    char_base_img, char_base_pos = char_img, tuple(char_base_xy)
                try:
                    from core.character_selector import load_character_original as _load_orig
                    char_original = _load_orig(int(char_info["pose"]))
                except Exception:
                    char_original = None
            except Exception:
                char_base_img, char_base_pos, char_original = None, None, None
            try:
                char_punch_dur = max(0.20, float(_CHARACTER_PUNCH_DURATION))
            except Exception:
                char_punch_dur = 0.60
        else:
            char_punch_active = False
            char_punch_dur = 0.0
    else:
        char_base_xy = None
        char_morph_from = None
        char_punch_active = False
        char_punch_dur = 0.0

    try:
        char_exit_dur = max(0.0, float(char_exit_duration))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION
    # Uscita slide-drop + fade (spec ~0.16s, +400px in_cubic) quando sparisce.
    # slide_down legacy -> hold (continuita' morph).
    if char_exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
        char_exit_mode = _CHAR_EXIT_WITH_TEXT
    if char_exit_mode == _CHAR_EXIT_SLIDE_DOWN:
        char_exit_mode = _CHAR_EXIT_HOLD
    try:
        _tail_hold = max(0.0, float(tail_hold_duration))
    except (TypeError, ValueError):
        _tail_hold = 0.0
    # Tail solo con hold + character presente (persistenza gap, fix blink).
    if char_exit_mode != _CHAR_EXIT_HOLD or char_base_xy is None:
        _tail_hold = 0.0

    num_frames = max(1, int(math.ceil(duration * fps)))
    frame_step = 1.0 / float(fps)
    frames: list[dict] = []

    # --- Pre-computazioni per-chunk (fuori dal loop frame) ---
    # Pill: overlay pre-renderizzato una volta, poi alpha_composite (no ricalcolo bbox).
    _pill_overlay = None
    if needs_pill and layout:
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
    _ease_out_quad = ease_out_quad
    _ease_in_cubic = ease_in_cubic
    _clamp01 = clamp01
    _new_rgba = Image.new
    _canvas_size = (VIDEO_WIDTH, VIDEO_HEIGHT)
    _transparent = (0, 0, 0, 0)
    _accent_lift_i = int(round(accent_lift))
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

        # Z-index 2: personaggio sotto il testo (idle + entrate/uscite fluidi).
        # - idle breathing&sway continuo (bob sin + tilt cos, anchor basso);
        # - jump (identico): opaco fermo, taglio invisibile;
        # - punch: zoom smart 0.6s ease_out (mai scatto secco hook);
        # - morph (continuita'): slide dalla vecchia posizione 0.40s in_out,
        #   sempre opaco (niente flash di sfondo, niente sparizioni);
        # - prima apparizione: slide&pop 0.20s +300px back/quad fluidi;
        # - sparizione (with_text): slide-drop +400px in_cubic + fade 0.16s.
        if char_img is not None and char_base_xy is not None:
            _char_scale = 1.0
            _char_layer = char_img
            if char_entry_jump:
                edx, edy, entry_opacity = 0, 0, 255
            elif 'char_punch_active' in dir() and char_punch_active:
                # Zoom smart: scala+posizione interpolate base->punch con ease.
                try:
                    _pp = clamp01((t - chunk_start) / max(0.01, char_punch_dur))
                except Exception:
                    _pp = 1.0
                _pe = ease_out_cubic(_pp)
                try:
                    _bx, _by = (char_base_pos if char_base_pos is not None else char_base_xy)
                    _ex, _ey = int(char_base_xy[0]), int(char_base_xy[1])
                    # Start posizione: morph da vecchia se presente, else base.
                    if 'char_morph_from' in dir() and char_morph_from is not None:
                        _sx, _sy = int(char_morph_from[0]), int(char_morph_from[1])
                    else:
                        _sx, _sy = int(_bx), int(_by)
                    # Fine zoom: posizione punch + fade solo se prima apparizione.
                    _morph_e = ease_in_out_cubic(_pp)
                    edx = int(round((_sx - _ex) * (1.0 - _morph_e)))
                    edy = int(round((_sy - _ey) * (1.0 - _morph_e)))
                    if char_entry_fade:
                        entry_opacity = int(round(255 * ease_out_quad(_pp)))
                    else:
                        entry_opacity = 255
                    # Scala: interpola dimensioni base->punch (resize da sorgente).
                    try:
                        _bw, _bh = (char_base_img.size if char_base_img is not None else char_img.size)
                        _pw, _ph = char_img.size
                        _iw = int(round(_bw + (_pw - _bw) * _pe))
                        _ih = int(round(_bh + (_ph - _bh) * _pe))
                        if _pp < 1.0 and _iw > 0 and _ih > 0 and char_original is not None:
                            try:
                                _rs = _fast_resample_for_scale(1.0 + (_pe * 0.35))
                                _char_layer = char_original.resize((_iw, _ih), _rs)
                                if _char_layer.mode != "RGBA":
                                    _char_layer = _char_layer.convert("RGBA")
                            except Exception:
                                _char_layer = char_img
                                edx, edy = int(round((_bx - _ex) * (1.0 - _pe))), int(round((_by - _ey) * (1.0 - _pe)))
                        else:
                            _char_layer = char_img
                            edx, edy = (edx, edy) if _pp < 1.0 else (0, 0)
                    except Exception:
                        _char_layer = char_img
                except Exception:
                    edx, edy, entry_opacity = 0, 0, 255
                    _char_layer = char_img
            elif 'char_morph_from' in dir() and char_morph_from is not None:
                # Morph smart tra posizioni (cambio posa/lato): slide fluida.
                try:
                    _mp = clamp01((t - chunk_start) / max(0.01, _CHARACTER_MORPH_DURATION))
                except Exception:
                    _mp = 1.0
                edx, edy = _character_morph_offset(char_morph_from, tuple(char_base_xy), _mp)
                entry_opacity = 255
            else:
                entry_prog = clamp01((t - chunk_start) / char_entry_dur)
                edx, edy, entry_opacity, _char_scale = _character_entry_transform(
                    char_transition, char_side, entry_prog,
                    char_img.size[0], char_base_xy[0], char_base_xy[1],
                    full_travel=char_full_travel,
                    fade=char_entry_fade,
                )
                if abs(_char_scale - 1.0) >= 1e-3:
                    # Zoom_in prima apparizione: scala tile 0.92->1.0 fluida.
                    try:
                        _zw, _zh = char_img.size
                        _nw = max(1, int(round(_zw * _char_scale)))
                        _nh = max(1, int(round(_zh * _char_scale)))
                        _rs2 = _fast_resample_for_scale(_char_scale)
                        _scaled = char_img.resize((_nw, _nh), _rs2)
                        # Centro fisso: ricentra sullo stesso centro base.
                        _cx = char_base_xy[0] + _zw / 2.0
                        _cy = char_base_xy[1] + _zh / 2.0
                        _px = int(round(_cx - _nw / 2.0)) + edx
                        _py = int(round(_cy - _nh / 2.0)) + edy
                        _char_layer = _scaled
                        _zoom_xy = (_px, _py)
                    except Exception:
                        _char_layer = char_img
                        _zoom_xy = None
                else:
                    _zoom_xy = None
            if char_exit_mode == _CHAR_EXIT_HOLD:
                char_opacity, xdx, xdy = entry_opacity, 0, 0
            else:
                # Uscita slide-drop (spec ~0.16s, ~5 frame): 0 -> +400px con
                # ease_in_cubic (accelera verso il basso) + fade quad.
                if char_exit_dur > 0 and t >= chunk_end - char_exit_dur:
                    try:
                        _xp = clamp01((t - (chunk_end - char_exit_dur)) / char_exit_dur)
                    except Exception:
                        _xp = 1.0
                    _char_fade = 1.0 - ease_out_quad(_xp)
                    char_opacity = int(round(entry_opacity * max(0.0, min(1.0, _char_fade))))
                    try:
                        xdy = int(round(_CHARACTER_EXIT_DROP_Y * ease_in_cubic(_xp)))
                    except Exception:
                        xdy = 0
                    xdx = 0
                else:
                    char_opacity = entry_opacity
                    xdx, xdy = 0, 0
            # Idle breathing & sway (tempo assoluto video: fase continua tra
            # chunk, niente salti ai tagli). Bob = offset Y, tilt = rotazione
            # cachata attorno a (w/2, h). Durante zoom attivi (punch/scale)
            # solo bob (niente tilt su tile temporanee: niente churn cache).
            try:
                _idle_dy, _idle_tilt = _idle_bob_tilt(t)
            except Exception:
                _idle_dy, _idle_tilt = 0, 0.0
            try:
                _scale_active = abs(float(_char_scale if '_char_scale' in dir() else 1.0) - 1.0) >= 1e-3
            except Exception:
                _scale_active = False
            try:
                _punch_zooming = bool(char_punch_active) and (
                    (t - chunk_start) < max(0.01, char_punch_dur)) if 'char_punch_active' in dir() else False
            except Exception:
                _punch_zooming = False
            _zooming = bool(_scale_active or _punch_zooming)
            if _idle_tilt and not _zooming:
                try:
                    _char_layer = _get_tilted_char(_char_layer, _idle_tilt)
                except Exception:
                    pass
            if _idle_dy:
                edy += int(_idle_dy)
            # --- Fase 3: micro cross-fade d'aura dentro il blocco Focus ---
            # Se posa cambia a stesso block_id (niente tagli netti): blend alpha
            # 3-4 frame + micro-scala 2% sui primi frame. Solo quando il
            # chiamante passa char_prev_layer (default None = legacy invariato).
            if char_micro_blend and char_prev_layer is not None and '_char_layer' in dir():
                try:
                    from core.character_selector import (
                        blend_character_layers as _blend_layers,
                        micro_blend_progress as _blend_prog,
                        micro_scale_factor as _micro_scale,
                    )
                    try:
                        _micro_n = 4
                        try:
                            from config import CHARACTER_MICRO_XFADE_FRAMES as _mn
                            _micro_n = max(1, int(_mn))
                        except Exception:
                            pass
                        if int(fi) < int(_micro_n) and _char_layer is not None:
                            _bp = _blend_prog(int(fi))
                            _blended = _blend_layers(char_prev_layer, _char_layer, _bp)
                            try:
                                _ms = float(_micro_scale(int(fi)))
                            except Exception:
                                _ms = 1.0
                            if abs(_ms - 1.0) >= 1e-4 and _blended is not None:
                                try:
                                    _bw2, _bh2 = _blended.size
                                    _nw2, _nh2 = max(1, int(round(_bw2 * _ms))), max(1, int(round(_bh2 * _ms)))
                                    _blended = _blended.resize((_nw2, _nh2), _fast_resample_for_scale(_ms))
                                except Exception:
                                    pass
                            if _blended is not None:
                                _char_layer = _blended
                    except Exception:
                        pass
                except Exception:
                    pass
            try:
                if '_zoom_xy' in dir() and _zoom_xy is not None and '_char_scale' in dir() and abs(_char_scale - 1.0) >= 1e-3:
                    _paste_character_frame(frame_img, _char_layer, _zoom_xy[0], _zoom_xy[1] + (int(_idle_dy) if _idle_dy else 0), char_opacity)
                else:
                    _paste_character_frame(
                        frame_img, _char_layer,
                        char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy,
                        char_opacity,
                    )
            except Exception:
                try:
                    _paste_character_frame(
                        frame_img, char_img,
                        char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy,
                        char_opacity,
                    )
                except Exception:
                    pass

        # Z-index 2.5: pill pre-renderizzata (composite unico, no ricalcolo).
        if _pill_overlay is not None:
            try:
                frame_img.alpha_composite(_pill_overlay)
            except (ValueError, AttributeError):
                draw_text_background(frame_img, layout)
        elif needs_pill:
            draw_text_background(frame_img, layout)

        for wi, w in enumerate(words):
            if t < word_starts[wi]:
                continue  # non ancora iniziata
            # Tier T0-T3 per-parola (durate dedicate pre-calcolate fuori loop).
            try:
                _cur_entry = _entry_per_word[wi]
            except (IndexError, TypeError):
                _cur_entry = entry_dur
            if _cur_entry <= 0:
                _cur_entry = 0.01
            local = _clamp01((t - word_starts[wi]) / _cur_entry)
            try:
                _style_w, _hero_w, _num_w = _tiers[wi]
            except (IndexError, TypeError, ValueError):
                _style_w, _hero_w, _num_w = ("impact" if w.get("is_keyword") else "base", False, False)
            try:
                _sfrom_w = _scale_per_word[wi]
            except (IndexError, TypeError):
                _sfrom_w = scale_from
            _dy = 0
            if _style_w == "impact":
                # T2 pop standard / T3 hero (durata+scala dedicate) / T3-num
                # (pop corto per cifre, mai hero). Overshoot scala non clampato
                # (effetto pop), opacita' sempre saturata a 255.
                eased = _ease_out_back(local)
                if eased >= 1.0:
                    opacity = 255
                elif eased <= 0.0:
                    continue
                else:
                    opacity = int(round(255 * eased))
                scale = _sfrom_w + (1.0 - _sfrom_w) * eased
                if scale < 0.05:
                    scale = 0.05
            elif _style_w == "accent" and use_typography:
                # T1 rise-fade: opacita' cubic + risalita lift->0, MAI scala
                # (handwritten non deformato). Completata -> draw diretto.
                if local >= 1.0:
                    opacity, scale = 255, 1.0
                elif local <= 0.0:
                    continue
                else:
                    eased = _ease_out_cubic(local)
                    opacity = int(round(255 * eased))
                    scale = 1.0
                    if _accent_lift_i > 0:
                        try:
                            _dy = int(round(_accent_lift_i * (1.0 - _ease_out_quad(local))))
                        except Exception:
                            _dy = int(round(_accent_lift_i * (1.0 - eased)))
            else:
                # T0 base fade (fast-path a entrata completata).
                if local >= 1.0:
                    opacity, scale = 255, 1.0
                elif local <= 0.0:
                    continue
                else:
                    eased = _ease_out_cubic(local)
                    opacity = int(round(255 * eased))
                    scale = 1.0
            # Uscita: gruppo per tutti, hero ritardato di ~2 frame (T3).
            try:
                if _hero_w and exit_factor < 1.0:
                    _ef = _hero_exit_factor(t, chunk_end, exit_dur, exit_factor)
                    opacity = int(round(opacity * _ef))
                elif exit_factor < 1.0:
                    opacity = int(round(opacity * exit_factor))
            except Exception:
                if exit_factor < 1.0:
                    opacity = int(round(opacity * exit_factor))
            if opacity <= 0:
                continue
            item = layout[wi]
            _ry = item["y"] + _dy if _dy else item["y"]
            _rx = item["x"]
            # --- Fase 2 avanzata: picco T2, badge+shake T3, stroke T0/T1 ---
            _adv_draw = False
            try:
                _adv_draw = bool(_adv_enabled)
            except Exception:
                _adv_draw = False
            if _adv_draw:
                try:
                    if _style_w == "impact" and not _hero_w and _t2_peak is not None:
                        try:
                            _frame_rel = int(round((t - float(word_starts[wi])) * float(fps)))
                            scale = float(_t2_peak(_frame_rel, float(scale)))
                        except Exception:
                            pass
                    if _hero_w and _hero_shake is not None and _draw_hero_badge is not None:
                        try:
                            _sx, _sy = _hero_shake(int(fi), int(fps))
                            _rx = int(_rx) + int(_sx)
                            _ry = int(_ry) + int(_sy)
                            _draw_hero_badge(frame_img, (int(item["x"]), int(item["y"]),
                                                         int(item["x"]) + int(item["width"]),
                                                         int(item["y"]) + int(item["height"])))
                        except Exception:
                            pass
                except Exception:
                    pass
            if use_typography:
                wfont = _word_fonts[wi]
                if _base_synth and _style_w == "base":
                    _sw, _sc = _BASE_SYNTHETIC_STROKE_WIDTH, fills[wi]
                else:
                    _sw, _sc = typo_stroke_width, typo_stroke_color
                if _adv_draw and _adv_stroke_for is not None:
                    try:
                        _sw = int(_adv_stroke_for(_style_w, int(_sw)))
                        if int(_sw) > 0 and _sc == (0, 0, 0, 0):
                            _sc = (0, 0, 0, 255)
                    except Exception:
                        pass
                _render_styled_scaled_word(
                    frame_img, w["word"], _rx, _ry,
                    item["width"], item["height"], wfont,
                    fills[wi], _sc, _sw,
                    _shadow_off, _shadow_fill,
                    opacity=opacity, scale=scale,
                )
            else:
                _sw_legacy, _sc_legacy = SUBTITLE_STROKE_WIDTH, SUBTITLE_STROKE_COLOR
                if _adv_draw and _adv_stroke_for is not None:
                    try:
                        _sw_legacy = int(_adv_stroke_for("base", int(_sw_legacy)))
                        if int(_sw_legacy) > 0 and _sc_legacy == (0, 0, 0, 0):
                            _sc_legacy = (0, 0, 0, 255)
                    except Exception:
                        pass
                _render_scaled_word(
                    frame_img, w["word"], _rx, _ry,
                    item["width"], item["height"], _word_fonts[wi],
                    fills[wi], _sc_legacy, _sw_legacy,
                    opacity=opacity, scale=scale,
                )

        fname = f"chunk_{chunk_index:04d}_frame_{fi:05d}.png"
        fpath = os.path.join(output_dir, fname)
        # compress_level=1: PNG lossless ma scrittura ~2x piu' veloce
        # (file temp piu' grandi, cancellati a fine job; nessun impatto visivo).
        frame_img.save(fpath, compress_level=1)
        frames.append({"image_path": fpath, "start": t, "end": frame_end})

    # --- Persistenza nel gap (fix blink): clona ultimo frame oltre chunk.end.
    # L'ultimo frame con hold ha character opaco + testo gia' svanito (exit
    # fade completato): clonarlo copre la pausa TTS senza sparizioni.
    # Per la CTA card intermedia l'ultimo frame ha card piena: clonarlo tiene
    # la card persistente. Mai eccezioni (tail best-effort).
    if _tail_hold > 0.001 and frames:
        try:
            import shutil as _shutil
            _extra_n = max(1, int(round(_tail_hold * float(fps))))
            # Cap di sicurezza: max 2s di tail (evita esplosione frame su gap anomali).
            _extra_n = min(_extra_n, max(1, int(round(2.0 * float(fps)))))
            _last = frames[-1]
            _last_path = _last.get("image_path", "")
            _tail_start = float(chunk_end)
            _step = 1.0 / float(fps)
            for _k in range(_extra_n):
                _fi2 = num_frames + _k
                _t2 = _tail_start + _k * _step
                _e2 = _t2 + _step
                _fname2 = f"chunk_{chunk_index:04d}_frame_{_fi2:05d}.png"
                _fpath2 = os.path.join(output_dir, _fname2)
                try:
                    _shutil.copyfile(_last_path, _fpath2)
                except Exception:
                    break
                frames.append({"image_path": _fpath2, "start": _t2, "end": _e2})
        except Exception:
            pass

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

    section: list[dict] = []  # {word,display,style,start,end,is_keyword,is_hero,is_number}
    if use_typography and typo_preset is not None:
        for ch in cta_chunks:
            for s in (ch.get("styled_words") or []):
                if not isinstance(s, dict) or not str(s.get("word", "")).strip():
                    continue
                style = s.get("style", "base")
                if style not in ("base", "impact", "accent"):
                    style = "base"
                _wstr = str(s.get("word", ""))
                _is_num = bool(s.get("is_number", False)) or _has_digit_fast(_wstr)
                _is_hero = bool(s.get("is_hero", False)) and style == "impact" and not _is_num
                section.append({
                    "word": _wstr,
                    "display": str(s.get("display") or _wstr),
                    "style": style,
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("end", 0.0)),
                    "is_keyword": style == "impact",
                    "is_hero": _is_hero,
                    "is_number": _is_num,
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
                    "is_hero": False,
                    "is_number": _has_digit_fast(str(w.get("word", ""))),
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
    # Guard real-time anche sulla CTA card (primo chunk della sezione).
    try:
        if explicit_box is None and isinstance(cta_chunks[0], dict):
            _gsa0 = cta_chunks[0].get("guard_safe_area")
            if _gsa0 is not None:
                _gb0 = (int(_gsa0[0]), int(_gsa0[1]), int(_gsa0[2]), int(_gsa0[3]))
                if _gb0[2] > _gb0[0] and _gb0[3] > _gb0[1]:
                    area = _gb0
            _gfs0 = cta_chunks[0].get("guard_font_scale")
            if _gfs0 is not None:
                _gf0 = float(_gfs0)
                if 0.5 <= _gf0 <= 1.5:
                    font_scale = _gf0
    except Exception:
        pass
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

    # Come nel path normale: base statico -> grassetto sintetico leggero.
    try:
        _cta_synth = bool(use_typography and isinstance(typo_fonts, dict)
                          and not typo_fonts.get("base_weight_applied", False))
    except Exception:
        _cta_synth = False

    # Tier T0-T3 anche sulla card (stessi default del path normale).
    try:
        last_exit = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    except (TypeError, ValueError, NameError):
        last_exit = 0.15
    try:
        entry_dur, scale_from, accent_lift, hero_dur, hero_from, number_dur = (
            _resolve_motion_params(typo_preset if use_typography else None, cta_chunks[0] if cta_chunks else None)
        )
    except Exception:
        entry_dur, scale_from = 0.18, 0.7
        accent_lift, hero_dur, hero_from, number_dur = 10.0, 0.22, 0.6, 0.15
    # CTA card: nessun hook mult (card stabile); scala da preset nicchia.
    # Se il primo chunk CTA porta anim_pop_from esplicito, _resolve lo ha gia'
    # applicato: qui lo neutralizziamo solo se e' un hook residue (mai in CTA).
    try:
        _cta_tiers = [_word_tier(w) for w in section]
        _cta_entry = [
            (hero_dur if _h else (number_dur if (_s == "impact" and _n) else entry_dur))
            for (_s, _h, _n) in _cta_tiers
        ]
        _cta_scale = [
            (hero_from if _h else scale_from) if _s == "impact" else 1.0
            for (_s, _h, _n) in _cta_tiers
        ]
    except Exception:
        _cta_tiers = [("base", False, False)] * len(section)
        _cta_entry = [entry_dur] * len(section)
        _cta_scale = [1.0] * len(section)
    try:
        _cta_lift_i = int(round(accent_lift))
    except Exception:
        _cta_lift_i = 10

    # --- Personaggio bloccato (layer unico per tutta la card, entrata fluida) ---
    char_img, char_base_xy = _load_chunk_character_layer(first_info)
    if char_img is not None and char_base_xy is not None and first_info is not None:
        char_transition = first_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(first_info)
        char_full_travel = bool(use_preset)
        try:
            _cs0 = chunk_states[0] if chunk_states else {}
            _first_fade = bool(_cs0.get("char_entry_fade", True))
        except Exception:
            _first_fade = True
        if _first_fade:
            char_entry_dur = max(0.01, _CHARACTER_ZONE_FIRST_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        else:
            char_entry_dur = max(0.01, _CHARACTER_MORPH_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        try:
            _cta_morph_from = (_cs0.get("char_entry_from_xy") if isinstance(_cs0, dict) else None)
            if _cta_morph_from is not None:
                _cta_morph_from = (int(_cta_morph_from[0]), int(_cta_morph_from[1]))
                if _cta_morph_from == (int(char_base_xy[0]), int(char_base_xy[1])):
                    _cta_morph_from = None
        except (TypeError, ValueError, IndexError):
            _cta_morph_from = None
    else:
        char_base_xy = None
        _cta_morph_from = None
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
    _cta_ease_quad = ease_out_quad
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
                _cta_scale = 1.0
                _cta_layer = char_img
                if entry_jump:
                    edx, edy, entry_opacity = 0, 0, 255
                elif k == 0 and '_cta_morph_from' in dir() and _cta_morph_from is not None and not entry_fade:
                    # Handoff fluido corpo->CTA: morph dalla vecchia posizione.
                    try:
                        _mp0 = clamp01((t - cs) / max(0.01, _CHARACTER_MORPH_DURATION))
                    except Exception:
                        _mp0 = 1.0
                    edx, edy = _character_morph_offset(_cta_morph_from, tuple(char_base_xy), _mp0)
                    entry_opacity = 255
                else:
                    entry_prog = clamp01((t - cs) / char_entry_dur)
                    edx, edy, entry_opacity, _cta_scale = _character_entry_transform(
                        char_transition, char_side, entry_prog,
                        char_img.size[0], char_base_xy[0], char_base_xy[1],
                        full_travel=char_full_travel, fade=entry_fade)
                    if abs(_cta_scale - 1.0) >= 1e-3:
                        try:
                            _zw, _zh = char_img.size
                            _nw = max(1, int(round(_zw * _cta_scale)))
                            _nh = max(1, int(round(_zh * _cta_scale)))
                            _cta_layer = char_img.resize((_nw, _nh), _fast_resample_for_scale(_cta_scale))
                            _ccx = char_base_xy[0] + _zw / 2.0
                            _ccy = char_base_xy[1] + _zh / 2.0
                            edx = int(round(_ccx - _nw / 2.0)) - int(char_base_xy[0])
                            edy = int(round(_ccy - _nh / 2.0)) - int(char_base_xy[1])
                        except Exception:
                            _cta_layer = char_img
                if exit_mode == _CHAR_EXIT_HOLD or exit_mode == _CHAR_EXIT_SLIDE_DOWN:
                    cop, xdx, xdy = entry_opacity, 0, 0
                else:
                    # Uscita slide-drop CTA finale (~0.16s): +400px in_cubic + fade.
                    if char_exit_dur > 0 and t >= ce - char_exit_dur:
                        try:
                            _xp = clamp01((t - (ce - char_exit_dur)) / char_exit_dur)
                        except Exception:
                            _xp = 1.0
                        cop = int(round(entry_opacity * max(0.0, min(1.0, 1.0 - ease_out_quad(_xp)))))
                        try:
                            xdy = int(round(_CHARACTER_EXIT_DROP_Y * ease_in_cubic(_xp)))
                        except Exception:
                            xdy = 0
                        xdx = 0
                    else:
                        cop = entry_opacity
                        xdx, xdy = 0, 0
                # Idle anche sulla card (stessa fase assoluta, continuita').
                try:
                    _c_dy, _c_tilt = _idle_bob_tilt(t)
                except Exception:
                    _c_dy, _c_tilt = 0, 0.0
                try:
                    _c_zooming = abs(float(_cta_scale) - 1.0) >= 1e-3
                except Exception:
                    _c_zooming = False
                if _c_tilt and not _c_zooming:
                    try:
                        _cta_layer = _get_tilted_char(_cta_layer, _c_tilt)
                    except Exception:
                        pass
                if _c_dy:
                    edy += int(_c_dy)
                _paste_character_frame(
                    frame_img, _cta_layer,
                    char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy, cop)
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
                try:
                    _ced = _cta_entry[wi]
                except (IndexError, TypeError):
                    _ced = entry_dur
                if _ced <= 0:
                    _ced = 0.01
                local = _cta_clamp((t - w["start"]) / _ced)
                try:
                    _cs, _ch, _cn = _cta_tiers[wi]
                except (IndexError, TypeError, ValueError):
                    _cs, _ch, _cn = ("impact" if w.get("is_keyword") else "base", bool(w.get("is_hero", False)), False)
                try:
                    _csf = _cta_scale[wi]
                except (IndexError, TypeError):
                    _csf = scale_from
                _cdy = 0
                if _cs == "impact":
                    if local >= 1.0:
                        # Nota: eased>=1 qui significa entrata finita (scale 1);
                        # l'overshoot >1 vive solo dentro local<1 (vedi sotto).
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        eased = _cta_ease_back(local)
                        opacity = int(round(255 * min(1.0, max(0.0, eased))))
                        scale = max(0.05, _csf + (1.0 - _csf) * eased)
                elif _cs == "accent" and use_typography:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        eased = _cta_ease_cubic(local)
                        opacity = int(round(255 * eased))
                        scale = 1.0
                        if _cta_lift_i > 0:
                            try:
                                _cdy = int(round(_cta_lift_i * (1.0 - _cta_ease_quad(local))))
                            except Exception:
                                _cdy = int(round(_cta_lift_i * (1.0 - eased)))
                else:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        opacity = int(round(255 * _cta_ease_cubic(local)))
                        scale = 1.0
                try:
                    if _ch and exit_factor < 1.0:
                        _ef = _hero_exit_factor(t, ce, exit_dur, exit_factor)
                        opacity = int(round(opacity * _ef))
                    elif exit_factor < 1.0:
                        opacity = int(round(opacity * exit_factor))
                except Exception:
                    if exit_factor < 1.0:
                        opacity = int(round(opacity * exit_factor))
                if opacity <= 0:
                    continue
                item = layout[wi]
                _cy = item["y"] + _cdy if _cdy else item["y"]
                if use_typography:
                    wfont = _cta_fonts[wi]
                    if _cta_synth and _cs == "base":
                        _csw, _csc = _BASE_SYNTHETIC_STROKE_WIDTH, fills[wi]
                    else:
                        _csw, _csc = stroke_width, stroke_color
                    _render_styled_scaled_word(
                        frame_img, w["display"], item["x"], _cy,
                        item["width"], item["height"], wfont,
                        fills[wi], _csc, _csw,
                        shadow_off, shadow_fill, opacity=opacity, scale=scale)
                else:
                    _render_scaled_word(
                        frame_img, w["word"], item["x"], _cy,
                        item["width"], item["height"], _cta_fonts[wi],
                        fills[wi], SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
                        opacity=opacity, scale=scale)
            fname = f"chunk_{start_index + k:04d}_frame_{fi:05d}.png"
            fpath = os.path.join(output_dir, fname)
            frame_img.save(fpath, compress_level=1)
            frames.append({"image_path": fpath, "start": t, "end": frame_end})
        # Tail persistenza gap anche per la card (intermedi: card piena).
        try:
            _st_k = chunk_states[k] if k < len(chunk_states) else {}
            _tail_k = float((_st_k or {}).get("char_tail", 0.0) or 0.0)
        except Exception:
            _tail_k = 0.0
        if _tail_k > 0.001 and frames and not (k == len(cta_chunks) - 1):
            try:
                import shutil as _sh2
                _n2 = min(max(1, int(round(_tail_k * float(fps)))), max(1, int(round(2.0 * float(fps)))))
                _lp = frames[-1].get("image_path", "")
                for _kk in range(_n2):
                    _fi2 = num_frames + _kk
                    _t2 = ce + _kk * step
                    _fn2 = f"chunk_{start_index + k:04d}_frame_{_fi2:05d}.png"
                    _fp2 = os.path.join(output_dir, _fn2)
                    try:
                        _sh2.copyfile(_lp, _fp2)
                    except Exception:
                        break
                    frames.append({"image_path": _fp2, "start": _t2, "end": _t2 + step})
            except Exception:
                pass
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

    Il lookahead sul chunk successivo decide l'uscita (hold quando il dopo ha
    un character, slide-drop+fade 0.16s solo in sparizione); il lookbehind
    decide l'entrata (slide&pop 0.20s +300px alla prima apparizione, morph
    smart 0.40s dalla vecchia posizione nei cambi, jump solo a identita'
    pixel-identica, zoom fluido 0.6s per il punch hook mai secco). Idle
    breathing/sway continuo sopra ogni frame visibile. I gap TTS sono coperti
    da tail di persistenza (hold) per fix blink. Ritmo coerente e dinamico.

    Returns:
        Lista di chunk arricchiti: {**chunk, "frames": [...], "frame_paths": [...],
        "clip_start": start, "clip_end": end (+tail), "clip_tail": secondi}.
    """
    import os as _os
    _parallel_ok = _os.environ.get("RENDER_PARALLEL", "1").strip().lower() not in ("0", "false", "no", "off", "")
    try:
        _gap_hold_ok = str(_os.environ.get("CHARACTER_GAP_HOLD_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        _gap_hold_ok = True
    try:
        _gap_hold_max = max(0.0, float(CHARACTER_GAP_HOLD_MAX))
    except Exception:
        _gap_hold_max = 1.5
    if not (_gap_hold_max > 0):
        _gap_hold_max = 1.5
    enriched_all: list[dict] = []
    total = len(chunks)
    # Pre-carica posizioni base character per morph (cached, veloce).
    _base_xy_cache: dict[int, tuple[int, int] | None] = {}
    for _ci in range(total):
        try:
            _inf = _character_info_from_chunk(chunks[_ci])
            if _inf is None:
                _base_xy_cache[_ci] = None
            else:
                _img, _xy = _load_chunk_character_layer(_inf)
                _base_xy_cache[_ci] = (int(_xy[0]), int(_xy[1])) if _xy is not None else None
        except Exception:
            _base_xy_cache[_ci] = None
    # Stati personaggio per chunk (lookahead/lookbehind), calcolati una volta:
    # servono sia al path normale sia alla CTA card (stessa fluidita').
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
            # Taglio invisibile SOLO a identita' pixel-identica (stessa
            # posa+zona+punch): nessun replay (replay = blink a ogni stacco).
            # Cambio posa/lato/punch -> morph/zoom fluido, MAI jump secco.
            entry_jump = bool(decide_char_entry_jump(prev, chunk))
            # Dissolvenza SOLO alla prima apparizione; morph opachi dopo.
            entry_fade = prev_info is None
        except Exception:
            entry_jump, entry_fade = False, True
        # Macro-blocchi (Breath & Focus): l'evento guida entrata/uscita.
        # ENTRY = slide-in pulito; SUSTAIN/EXIT (non-primi) = hold invisibile
        # (stessa posa/lato ancorati nel blocco, nessun replay); NONE/hidden
        # = nessun layer. Tra blocchi visibili diversi il morph parte dalla
        # posizione precedente (switch diretto, mai fade out/in).
        try:
            _ev = _character_event_of(chunk)
            if cur_info is None or _ev == "NONE":
                entry_jump, entry_fade = True, False
            elif _ev == "ENTRY":
                # Riapparizione dopo gap -> slide-in con fade; se il chunk
                # prima aveva gia' un character (blocchi visibili adiacenti),
                # switch diretto senza fade (morph dalla vecchia posizione).
                if prev_info is None:
                    entry_jump, entry_fade = False, True
                else:
                    entry_jump, entry_fade = False, False
            elif _ev in ("SUSTAIN", "EXIT"):
                entry_jump, entry_fade = True, False
        except Exception:
            pass
        # Morph smart: posizione precedente per slide continua (niente flash).
        try:
            from_xy = None
            if not entry_jump and not entry_fade and cur_info is not None and prev_info is not None:
                from_xy = _base_xy_cache.get(i - 1)
        except Exception:
            from_xy = None
        # Tail persistenza gap: hold -> copre la pausa fino al chunk dopo.
        try:
            tail = 0.0
            if _gap_hold_ok and exit_mode == _CHAR_EXIT_HOLD and cur_info is not None and nxt is not None:
                try:
                    _end = float(chunk.get("end", 0.0))
                    _nxt_start = float(nxt.get("start", _end))
                except (TypeError, ValueError):
                    _end, _nxt_start = 0.0, 0.0
                _gap = _nxt_start - _end
                if _gap > 1.0 / max(1, int(fps or VIDEO_FPS)) + 1e-6:
                    tail = min(max(0.0, _gap), _gap_hold_max)
        except Exception:
            tail = 0.0
        # --- Fase 3: micro cross-fade dentro il blocco Focus (no tagli netti) ---
        _micro = False
        _prev_layer = None
        try:
            from core.character_selector import is_focus_pose_switch as _is_focus_sw
            _prev_chunk = chunks[i - 1] if i - 1 >= 0 else None
            if _prev_chunk is not None and bool(_is_focus_sw(_prev_chunk, chunk)):
                try:
                    _pi = _character_info_from_chunk(_prev_chunk)
                    if _pi is not None:
                        _pl, _px = _load_chunk_character_layer(_pi)
                        if _pl is not None:
                            _prev_layer = _pl
                            _micro = True
                except Exception:
                    _prev_layer, _micro = None, False
        except Exception:
            _prev_layer, _micro = None, False
        states.append({
            "char_exit_mode": exit_mode,
            "char_entry_jump": entry_jump,
            "char_entry_fade": entry_fade,
            "char_entry_from_xy": from_xy,
            "char_tail": float(tail or 0.0),
            "char_micro_blend": bool(_micro),
            "char_prev_layer": _prev_layer,
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
            _workers = max(2, min(4, _cpu - 1, len(normal_idx)))

            def _render_one(k: int):
                st = states[k]
                return generate_animated_chunk_frames(
                    chunks[k], background_color, text_color,
                    keyword_colors or {}, output_dir, k, fps,
                    safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
                    text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
                    char_entry_fade=st["char_entry_fade"],
                    typography_niche=typography_niche, typography_preset=typography_preset,
                    char_entry_from_xy=st.get("char_entry_from_xy"),
                    tail_hold_duration=float(st.get("char_tail", 0.0) or 0.0),
                    char_prev_layer=st.get("char_prev_layer"),
                    char_micro_blend=bool(st.get("char_micro_blend", False)),
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
                    char_entry_from_xy=st.get("char_entry_from_xy"),
                    tail_hold_duration=float(st.get("char_tail", 0.0) or 0.0),
                    char_prev_layer=st.get("char_prev_layer"),
                    char_micro_blend=bool(st.get("char_micro_blend", False)),
                )
                if on_chunk is not None:
                    try:
                        on_chunk(k + 1, total)
                    except Exception:
                        pass
    for k in range(total):
        frames = cta_results.get(k, normal_results.get(k, []))
        try:
            _tail_k = float((states[k] or {}).get("char_tail", 0.0) or 0.0)
        except Exception:
            _tail_k = 0.0
        try:
            _end_k = float(chunks[k].get("end", chunks[k].get("start", 0.0)))
        except (TypeError, ValueError):
            _end_k = 0.0
        enriched_all.append({
            **chunks[k],
            "frames": frames,
            "frame_paths": [f["image_path"] for f in frames],
            "clip_start": chunks[k].get("start"),
            "clip_end": (_end_k + _tail_k) if _tail_k > 0 else chunks[k].get("end"),
            "clip_tail": _tail_k,
        })
    # Ordina callback finale per GUI coerente (i paralleli arrivano fuori ordine).
    return enriched_all
