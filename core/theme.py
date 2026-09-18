"""
Palette tematica premium: analizza lo script con l'LLM Groq
(modello `GROQ_THEME_MODEL`, default `openai/gpt-oss-120b`, via Chat
Completions come in core/keywords.py) e genera una palette moderna e
coerente (sfondo scuro premium desaturato + testo bianco caldo + accenti
armonici).

Design system (look premium TikTok, mai casuale):
- Sfondi: SOLO neri cinematici desaturati dalla lista curata
  PREMIUM_BACKGROUNDS (navy/slate/espresso/plum/forest, mai rosso-arancione
  saturo o colori neon). Qualunque scelta LLM fuori gamma viene snappata al
  premium più vicino (stessa intenzione cromatica, resa premium).
- Testi: SOLO bianchi caldi (mai testi colorati saturi).
- Keyword/accenti: max 4 toni armonici dalla lista PREMIUM_ACCENTS
  (ori/ciano/rosa/lavanda/menta), mai arcobaleno, mai gialli neon puri.

Tutti i colori viaggiano come hex string "#RRGGBB"; la conversione per
Pillow/ffmpeg avviene lato codice. Se la generazione fallisce, si usa
un default premium (midnight slate, non nero piatto): mai blocco pipeline.
"""

import json
import re
from collections.abc import Callable

from groq import Groq

from config import (
    GROQ_API_KEYS,
    GROQ_THEME_MODEL,
    THEME_MIN_LUMINANCE_DIFF,
)
from core.keywords import _FALLBACK_PALETTE_HEX


class ThemeError(Exception):
    """Errore durante la generazione del tema (input non valido)."""
    pass


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    from groq import Groq as _Groq
    client = _Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# --- Design system premium: sfondi cinematici scuri, mai saturi ---
# Ogni sfondo ha luminanza <40 e saturazione bassa: resa "costosa" su mobile,
# testo bianco sempre leggibile, nessun effetto "arancione economico".
PREMIUM_BACKGROUNDS: dict[str, str] = {
    "#0B0B0D": "Onyx Black (universale, dark motivational)",
    "#0F172A": "Midnight Slate (business/tech/educational)",
    "#111318": "Graphite (universale)",
    "#141210": "Espresso Black (lifestyle/business)",
    "#0E1B2C": "Deep Navy (business/tech)",
    "#121826": "Slate Navy (business/educational)",
    "#161022": "Plum Black (lifestyle/dark)",
    "#101A14": "Forest Black (fitness/educational)",
    "#1A1512": "Warm Charcoal (lifestyle/business)",
    "#0C1A1A": "Teal Black (tech/fitness)",
    "#1C1210": "Ember Black (dark/fitness, caldo senza arancione)",
    "#201A17": "Coffee Black (lifestyle)",
}

# Bianchi caldi ammessi per il testo (mai testi colorati).
PREMIUM_TEXTS: list[str] = ["#FFFFFF", "#F5F5F5", "#FDFBF7"]

# Accenti premium per keyword/highlight: saturazione controllata,
# luminanza medio-alta per contrasto su sfondi scuri, mai neon puri.
# Oro smorzato > giallo neon; corallo soft > arancione saturo.
PREMIUM_ACCENTS: list[str] = [
    "#D4AF37",  # oro smorzato (hero premium)
    "#FFD166",  # oro caldo chiaro
    "#7DD3FC",  # sky soft
    "#00E5FF",  # ciano tech
    "#A78BFA",  # lavanda
    "#FF8FA3",  # rosa soft
    "#34D399",  # menta
    "#F5D67B",  # oro chiaro (accent tint)
]

DEFAULT_THEME: dict = {
    "background_color": "#0F172A",
    "text_color": "#FFFFFF",
    "keyword_colors": list(_FALLBACK_PALETTE_HEX),
}


def _default_theme() -> dict:
    """Copia profonda del default (la lista keyword non deve mai essere condivisa)."""
    return {
        "background_color": DEFAULT_THEME["background_color"],
        "text_color": DEFAULT_THEME["text_color"],
        "keyword_colors": list(DEFAULT_THEME["keyword_colors"]),
    }


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converte "#RRGGBB" in (R, G, B). Solleva ValueError se non valido."""
    if not HEX_RE.match(hex_color):
        raise ValueError(f"Colore hex non valido: {hex_color!r}")
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Converte "#RRGGBB" in (R, G, B, 255) per Pillow."""
    r, g, b = hex_to_rgb(hex_color)
    return (r, g, b, 255)


def _is_yellowish(hex_color: str) -> bool:
    """Vero solo per gialli neon puri (illeggibili/cheap), NON per ori premium.

    Soglie strette: vieta #FFD700/#FFFF00/#FFEB3B ma permette ori smorzati
    come #D4AF37 (212,175,55) e #FFD166, che sono accenti premium validi.
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
    except ValueError:
        return True
    return r > 230 and g > 195 and b < 100


def luminance(hex_color: str) -> float:
    """Luminanza percepita approssimata (WCAG-like), scala 0-255."""
    r, g, b = hex_to_rgb(hex_color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _saturation_of(hex_color: str) -> float:
    """Saturazione HSV 0-1 (0=grigio, 1=neon puro)."""
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    _, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return s


def _hue_of(hex_color: str) -> float:
    """Tinta HSV 0-360."""
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    h, _, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return h * 360.0


def _is_garish_background(hex_color: str) -> bool:
    """Vero per sfondi cheap: chiari o cromaticamente accesi (es. rosso-arancione).

    Premium = scuro (lum <=70) E croma assoluto contenuto (max-min <=80).
    Si usa la croma assoluta e non la saturazione HSV relativa: i navy scuri
    come #0F172A hanno S HSV alta ma croma bassa (27) e look desaturato/premium,
    mentre un arancione #FF5733 ha croma 204 e risulta cheap anche se scuro.
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
        lum = luminance(hex_color)
    except ValueError:
        return True
    if lum > 70:
        return True
    if max(r, g, b) - min(r, g, b) > 80:
        return True
    return False


def _nearest_premium_bg(requested_hex: str) -> str:
    """Snappa un bg arbitrario al premium più vicino (distanza RGB).

    Preserva l'intenzione cromatica (richiesta calda -> ember/warm charcoal,
    fredda -> navy/slate) ma con resa sempre premium.
    """
    try:
        rr, rg, rb = hex_to_rgb(requested_hex)
    except ValueError:
        return "#0F172A"
    best, best_d = "#0F172A", float("inf")
    for cand in PREMIUM_BACKGROUNDS:
        try:
            cr, cg, cb = hex_to_rgb(cand)
        except ValueError:
            continue
        d = (rr - cr) ** 2 + (rg - cg) ** 2 + (rb - cb) ** 2
        # Bonus tinta: se la richiesta è calda (rosso/arancio), premia i
        # premium caldi; se fredda (blu/teal), premia i navy. Peso leggero.
        try:
            h_req = _hue_of(requested_hex)
            h_cand = _hue_of(cand)
            hue_bonus = 0.0
            if (h_req < 50 or h_req > 340) and ("Ember" in PREMIUM_BACKGROUNDS[cand] or "Warm" in PREMIUM_BACKGROUNDS[cand] or "Coffee" in PREMIUM_BACKGROUNDS[cand] or "Espresso" in PREMIUM_BACKGROUNDS[cand]):
                hue_bonus = -800.0
            elif 180 <= h_req <= 260 and ("Navy" in PREMIUM_BACKGROUNDS[cand] or "Slate" in PREMIUM_BACKGROUNDS[cand] or "Teal" in PREMIUM_BACKGROUNDS[cand]):
                hue_bonus = -800.0
            d += hue_bonus
        except Exception:
            pass
        if d < best_d:
            best, best_d = cand, d
    return best


def _is_near_white(hex_color: str) -> bool:
    """Vero per bianchi caldi (testi ammessi): luminosi e poco saturi."""
    try:
        return luminance(hex_color) >= 190 and _saturation_of(hex_color) <= 0.25
    except ValueError:
        return False


def _validate_theme(raw: dict) -> dict:
    """Valida/corregge la palette LLM in chiave premium (mai casuale).

    - bg non-hex o garish (saturo/chiaro, es. rosso-arancione) -> snap al
      premium più vicino (stessa famiglia cromatica, resa cinematica);
    - testo non bianco-caldo o basso contrasto -> bianco caldo a max contrasto;
    - keyword: scarta neon illeggibili/gialli puri/basso contrasto, max 4
      accenti armonici (no arcobaleno); integra da PREMIUM_ACCENTS.
    """
    bg = raw.get("background_color", "")
    text = raw.get("text_color", "")
    kws = raw.get("keyword_colors", [])

    if not isinstance(bg, str) or not HEX_RE.match(bg):
        bg = "#0F172A"
    elif _is_garish_background(bg):
        bg = _nearest_premium_bg(bg)
    if not isinstance(text, str) or not HEX_RE.match(text):
        text = "#FFFFFF"
    if not isinstance(kws, list):
        kws = []

    # Testo: solo bianchi premium con alto contrasto (mai testi colorati).
    if not _is_near_white(text) or abs(luminance(text) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
        candidates = [c for c in PREMIUM_TEXTS if abs(luminance(c) - luminance(bg)) >= THEME_MIN_LUMINANCE_DIFF]
        if candidates:
            # Il più distante dallo sfondo (max contrasto).
            text = max(candidates, key=lambda c: abs(luminance(c) - luminance(bg)))
        else:
            text = "#FFFFFF" if abs(255 - luminance(bg)) >= abs(0 - luminance(bg)) else "#000000"

    def _is_pure_neon(hex_color: str) -> bool:
        """Neon primario/secondario puro (#00FF00, #00FFFF, #FF00FF...).

        Gli accenti premium (es. #00E5FF) sono esentati: saturi ma con
        mezzotono calibrato, non primari puri.
        """
        try:
            if hex_color.upper() in (c.upper() for c in PREMIUM_ACCENTS):
                return False
            r, g, b = hex_to_rgb(hex_color)
        except ValueError:
            return True
        if max(r, g, b) - min(r, g, b) < 200:
            return False
        mid = sorted((r, g, b))[1]
        return mid < 30 or mid > 225

    # Keyword: max 4 accenti premium armonici (no arcobaleno cheap).
    clean_kws: list[str] = []
    seen_hues: list[float] = []
    for kw in kws:
        if len(clean_kws) >= 4:
            break
        if not isinstance(kw, str) or not HEX_RE.match(kw):
            continue
        if _is_yellowish(kw):
            continue
        try:
            if _is_pure_neon(kw):
                continue  # verdi/ciano/magenta primari puri: cheap su video
            if _saturation_of(kw) > 0.95 and luminance(kw) > 180:
                continue  # neon puro
        except ValueError:
            continue
        if abs(luminance(kw) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
            continue
        if kw in clean_kws:
            continue
        # Anti-arcobaleno: accetta solo tinte distinte (>25°) o neutre.
        try:
            h = _hue_of(kw)
            sat = _saturation_of(kw)
            if sat > 0.15 and any(abs(h - sh) < 25 and abs(h - sh) > 0.01 for sh in seen_hues):
                continue
        except ValueError:
            continue
        clean_kws.append(kw)
        try:
            seen_hues.append(_hue_of(kw))
        except ValueError:
            pass

    for fb in PREMIUM_ACCENTS + list(_FALLBACK_PALETTE_HEX):
        if len(clean_kws) >= 4:
            break
        if not isinstance(fb, str) or not HEX_RE.match(fb):
            continue
        if _is_yellowish(fb):
            continue
        if fb in clean_kws:
            continue
        if abs(luminance(fb) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
            continue
        try:
            h = _hue_of(fb)
            sat = _saturation_of(fb)
            if sat > 0.15 and any(abs(h - sh) < 25 for sh in seen_hues):
                continue
        except ValueError:
            continue
        clean_kws.append(fb)
        try:
            seen_hues.append(_hue_of(fb))
        except ValueError:
            pass

    if len(clean_kws) < 2:
        # Rete finale: oro + sky, sempre leggibili su premium dark.
        for fb in ("#D4AF37", "#7DD3FC"):
            if fb not in clean_kws and abs(luminance(fb) - luminance(bg)) >= THEME_MIN_LUMINANCE_DIFF:
                clean_kws.append(fb)
            if len(clean_kws) >= 2:
                break

    return {"background_color": bg, "text_color": text, "keyword_colors": clean_kws}


def _parse_theme(content: str) -> dict | None:
    """Estrae il dict tema da una risposta JSON (robusto a fence markdown)."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def generate_theme(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> dict:
    """Analizza il tema dello script e genera una palette colori coerente.

    Usa `GROQ_THEME_MODEL` con rotazione delle chiavi in GROQ_API_KEYS.
    Non fallisce mai per errori API: in quel caso restituisce DEFAULT_THEME.

    Returns:
        {"background_color": "#RRGGBB", "text_color": "#RRGGBB",
         "keyword_colors": ["#RRGGBB", ...]}

    Raises:
        ThemeError: se lo script è vuoto.
    """
    if not script_text or not script_text.strip():
        raise ThemeError("Script vuoto: impossibile generare il tema.")

    if not GROQ_API_KEYS:
        return _default_theme()

    premium_list = ", ".join(sorted(PREMIUM_BACKGROUNDS.keys()))
    system = (
        "Sei un art director premium per video brevi verticali (stile TikTok "
        "cinematico, mai cheap). Rispondi SOLO con JSON valido, senza spiegazioni."
    )
    user = (
        "Genera una palette PREMIUM per questo script. Obiettivo: moderna, "
        "costosa, cinematica — mai casuale o saturata.\n"
        "REGOLE RIGIDE:\n"
        f"1. background_color: SOLO uno di questi neri cinematici: {premium_list}. "
        "Scegli la tinta in base al mood (business/tech->navy/slate, "
        "lifestyle->warm/espresso/plum, fitness->forest/teal/ember, "
        "dark/motivazionale->onyx/ember). VIETATO qualunque sfondo saturo o "
        "medio-chiaro (NO rosso-arancione, NO orange, NO colori neon, NO grigi slavati).\n"
        "2. text_color: SOLO bianco premium (#FFFFFF, #F5F5F5 o #FDFBF7). "
        "MAI testi colorati (no testi rossi/gialli/blu).\n"
        "3. keyword_colors: max 3-4 accenti ARMONICI (stessa famiglia o complementari "
        "eleganti: ori #D4AF37/#FFD166, sky #7DD3FC, ciano #00E5FF, lavanda #A78BFA, "
        "rosa #FF8FA3, menta #34D399). MAI arcobaleno (no 6-8 colori tutti diversi), "
        "MAI gialli neon puri, tutti leggibili sullo sfondo.\n"
        "Rispondi SOLO con questo JSON (colori hex #RRGGBB): "
        '{"background_color": "#RRGGBB", "text_color": "#RRGGBB", '
        '"keyword_colors": ["#RRGGBB", "#RRGGBB"]}\n\n'
        f"SCRIPT:\n{script_text}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_THEME_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            content = None
            if on_attempt is not None:
                on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
            continue
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: tema generato")
        break

    if content is None:
        return _default_theme()

    parsed = _parse_theme(content)
    if parsed is None:
        return _default_theme()
    return _validate_theme(parsed)
