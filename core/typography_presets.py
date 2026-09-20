"""
Semantic Typography Engine v2 — Preset tipografici per nicchia (REELS-FIX v5).

Ogni nicchia definisce 3 livelli visivi:
  - base:   parlato standard SemiBold 52-56px (auto-fit minimo 38px)
  - impact: keyword 1.25x (uppercase solo se <=7 char), colore highlight
  - accent: citazioni/domande 1.05x handwritten, colore dedicato

Per ogni livello: lista font in ordine di preferenza, colore, scala dimensione.
REELS-FIX v5: stroke 0 assoluto, ambient shadow morbida (0,3,110) +
auto-pill (0,0,0,120) solo se contrasto <80.

Uso:
    from core.typography_presets import get_preset, VALID_NICHES, FALLBACK_NICHE
    preset = get_preset("tech_ai")
"""

# REELS-FIX v5: STROKE 0 ASSOLUTO di default (nessun contorno nero).
# Leggibilita' da contrasto + ambient shadow morbida (0,3,110) + auto-pill.
FORCED_STROKE_WIDTH: int = 0
FORCED_SHADOW_OFFSET: tuple[int, int] = (0, 3)
FORCED_SHADOW_FILL: tuple[int, int, int, int] = (0, 0, 0, 110)
# Dimensione base target 52-56px SemiBold, auto-fit minimo 38px (mai sotto).
MIN_BASE_FONT_SIZE: int = 38
TARGET_BASE_FONT_SIZE: int = 54
# Parole impact piu' lunghe di N char restano minuscole (no espansione brutta).
IMPACT_UPPERCASE_MAX_LEN: int = 7
# Pill dinamica quando contrasto < soglia: sfondo elegante, non stroke.
AUTO_PILL_FILL: tuple[int, int, int, int] = (0, 0, 0, 120)
AUTO_PILL_RADIUS: int = 24
AUTO_PILL_PAD_X: int = 20
AUTO_PILL_PAD_Y: int = 10

# Nicchia di fallback quando il rilevamento LLM è incerto o fallisce.
FALLBACK_NICHE: str = "dark_motivational"

VALID_NICHES: list[str] = [
    "business_finance",
    "tech_ai",
    "fitness_sport",
    "lifestyle_vlog",
    "educational",
    "dark_motivational",
]

# Descrizioni brevi per il prompt LLM di rilevamento nicchia.
NICHE_DESCRIPTIONS: dict[str, str] = {
    "business_finance": "soldi, investimenti, business, finanza, guadagni, strategia aziendale, marketing",
    "tech_ai": "tecnologia, intelligenza artificiale, software, coding, robot, digitale, innovazione",
    "fitness_sport": "fitness, palestra, sport, allenamento, muscoli, dieta, salute fisica",
    "lifestyle_vlog": "lifestyle, vlog quotidiano, viaggi, moda, bellezza, routine, emozioni personali",
    "educational": "educazione, scuola, spiegazioni, storia, scienza, lezioni, curiosità, tutorial",
    "dark_motivational": "motivazione cupa/cinematica, disciplina, mentalità, sacrificio, successo, citazioni forti",
}

TYPOGRAPHY_PRESETS: dict[str, dict] = {
    "business_finance": {
        "fonts": {
            "base": ["Inter", "Roboto"],
            # v2: Impact rimosso (font di sistema, non Google Fonts) -> Oswald/Bebas
            # equivalenti visivi 1:1 stabili (vedi VISUAL_FALLBACK_MATRIX).
            "impact": ["Anton", "Oswald", "Bebas Neue"],
            "accent": ["Playfair Display", "Caveat"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#FFD700",  # giallo oro
            "accent": "#FFE8A3",  # champagne: distinto dal base, armonico col gold
            "stroke": "#000000",
        },
        "sizes": {
            "base": 54,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,  # REELS-FIX v5: stroke 0, leggibilita' da contrasto+ombra
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
    "tech_ai": {
        "fonts": {
            "base": ["Roboto", "Inter"],
            "impact": ["Bebas Neue", "Orbitron"],
            "accent": ["Space Mono", "Caveat"],
        },
        "colors": {
            "base": "#F5F5F5",
            "highlight": "#00E5FF",  # ciano
            "accent": "#B8F4FF",  # ciano-chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 54,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
    "fitness_sport": {
        "fonts": {
            "base": ["Open Sans", "Roboto"],
            "impact": ["Oswald", "Bebas Neue"],
            "accent": ["Permanent Marker", "Kalam"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#FF2400",  # rosso fuoco
            "accent": "#FFC4B8",  # corallo chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 54,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
    "lifestyle_vlog": {
        "fonts": {
            "base": ["Poppins", "Lato"],
            "impact": ["Cinzel", "Bodoni Moda"],
            "accent": ["Caveat", "Pacifico"],
        },
        "colors": {
            "base": "#FDFBF7",
            "highlight": "#B76E79",  # rosa antico
            "accent": "#F3C6CE",  # rosa chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 54,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
    "educational": {
        "fonts": {
            "base": ["Nunito", "Roboto"],
            "impact": ["League Spartan", "Anton"],
            "accent": ["Patrick Hand", "Kalam"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#2962FF",  # blu elettrico
            "accent": "#B3C6FF",  # azzurro chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 54,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
    "dark_motivational": {
        "fonts": {
            # Anton primo: peso heavy reale (Montserrat variable da solo
            # renderebbe Regular, non Black). Accent con font open-source
            # scaricabili (Pristina/Editors Note non esistono su Google Fonts
            # e causavano sempre fallback incoerenti).
            "base": ["Montserrat", "Inter"],
            "impact": ["Anton", "Montserrat"],
            "accent": ["Caveat", "Kalam", "Patrick Hand"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#D4AF37",  # oro (alternativa #FF0000 per varianti aggressive)
            "highlight_alt": "#FF0000",
            "accent": "#F5D67B",  # oro chiaro: distinto dal bianco, coerente col highlight
            "stroke": "#000000",
        },
        "sizes": {
            "base": 56,
            "impact_scale": 1.25,
            "accent_scale": 1.05,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 3), "fill": (0, 0, 0, 110)},
        "impact_uppercase": True,
    },
}


def normalize_niche(name) -> str:
    """Normalizza il nome nicchia al vocabolario valido (fallback se ignoto)."""
    if isinstance(name, str):
        key = name.strip().lower().replace("-", "_").replace(" ", "_")
        # Tolleranze per output LLM leggermente diversi.
        aliases = {
            "business": "business_finance",
            "finance": "business_finance",
            "money": "business_finance",
            "tech": "tech_ai",
            "ai": "tech_ai",
            "technology": "tech_ai",
            "fitness": "fitness_sport",
            "sport": "fitness_sport",
            "gym": "fitness_sport",
            "lifestyle": "lifestyle_vlog",
            "vlog": "lifestyle_vlog",
            "education": "educational",
            "motivation": "dark_motivational",
            "motivational": "dark_motivational",
            "dark": "dark_motivational",
        }
        if key in TYPOGRAPHY_PRESETS:
            return key
        if key in aliases:
            return aliases[key]
    return FALLBACK_NICHE


def get_preset(niche: str | None) -> dict:
    """Ritorna il preset per la nicchia (fallback automatico se ignota/None).

    Ritorna SEMPRE un dict valido con chiavi fonts/colors/sizes/stroke_width/shadow.
    Il dict è una copia superficiale sicura da modificare (liste copiate).
    """
    key = normalize_niche(niche) if niche else FALLBACK_NICHE
    src = TYPOGRAPHY_PRESETS.get(key, TYPOGRAPHY_PRESETS[FALLBACK_NICHE])
    # REELS-FIX v5: stroke 0 di default, nessun pavimento rigido.
    # Legacy con stroke>0 viene rispettato solo se esplicitamente >0,
    # ma il default e' sempre 0 (elegante, no contorno nero).
    try:
        _sw = int(src.get("stroke_width", FORCED_STROKE_WIDTH))
    except (TypeError, ValueError):
        _sw = int(FORCED_STROKE_WIDTH)
    if _sw < 0:
        _sw = 0
    try:
        _off = tuple(src.get("shadow", {}).get("offset", FORCED_SHADOW_OFFSET))
        _fill = tuple(src.get("shadow", {}).get("fill", FORCED_SHADOW_FILL))
    except Exception:
        _off, _fill = FORCED_SHADOW_OFFSET, FORCED_SHADOW_FILL
    # Ambient shadow morbida consentita; (0,0) = nessuna ombra (rispettato).
    # Base target 52-56px, minimo auto-fit 38px (mai sotto).
    try:
        _sizes = dict(src.get("sizes", {}))
        try:
            _b = int(_sizes.get("base", TARGET_BASE_FONT_SIZE))
        except Exception:
            _b = int(TARGET_BASE_FONT_SIZE)
        if _b < int(MIN_BASE_FONT_SIZE):
            _b = int(MIN_BASE_FONT_SIZE)
        if _b > 64:
            _b = 64
        _sizes["base"] = int(_b)
    except Exception:
        _sizes = dict(src.get("sizes", {}))
    return {
        "niche": key,
        "fonts": {
            "base": list(src["fonts"].get("base", [])),
            "impact": list(src["fonts"].get("impact", [])),
            "accent": list(src["fonts"].get("accent", [])),
        },
        "colors": dict(src.get("colors", {})),
        "sizes": _sizes,
        "stroke_width": int(_sw),
        "shadow": {
            "offset": tuple(_off),
            "fill": tuple(_fill),
        },
        "impact_uppercase": bool(src.get("impact_uppercase", True)),
    }


def list_niches_for_prompt() -> str:
    """Riga per prompt LLM: 'business_finance, tech_ai, ...'."""
    return ", ".join(VALID_NICHES)
