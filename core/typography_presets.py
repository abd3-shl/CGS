"""
Semantic Typography Engine v1 — Preset tipografici per nicchia.

Ogni nicchia definisce 3 livelli visivi:
  - base:   parlato standard / congiunzioni / testo generico
  - impact: keyword ad alto valore, dati numerici, concetti chiave
  - accent: domande retoriche, citazioni, parole tra virgolette, espressioni d'effetto

Per ogni livello: lista font in ordine di preferenza, colore, scala dimensione.
Look pulito: NESSUN contorno (stroke_width=0) e NESSUNA ombra di default.
Leggibilità garantita da contrasto tema + pill sul punch-in (vedi config.py).

Uso:
    from core.typography_presets import get_preset, VALID_NICHES, FALLBACK_NICHE
    preset = get_preset("tech_ai")
"""

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
            "impact": ["Anton", "Impact"],
            "accent": ["Playfair Display", "Caveat"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#FFD700",  # giallo oro
            "accent": "#FFE8A3",  # champagne: distinto dal base, armonico col gold
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.4,   # 84px
            "accent_scale": 1.1,   # 66px
        },
        "stroke_width": 0,  # nessun contorno: look pulito
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
            "base": 60,
            "impact_scale": 1.4,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
            "base": 60,
            "impact_scale": 1.45,  # più aggressivo
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
            "base": 60,
            "impact_scale": 1.3,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
            "base": 60,
            "impact_scale": 1.35,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
            "base": 62,
            "impact_scale": 1.45,  # 90px, massimo impatto cinematico
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
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
    return {
        "niche": key,
        "fonts": {
            "base": list(src["fonts"].get("base", [])),
            "impact": list(src["fonts"].get("impact", [])),
            "accent": list(src["fonts"].get("accent", [])),
        },
        "colors": dict(src.get("colors", {})),
        "sizes": dict(src.get("sizes", {})),
        "stroke_width": int(src.get("stroke_width", 0)),
        "shadow": {
            "offset": tuple(src.get("shadow", {}).get("offset", (0, 0))),
            "fill": tuple(src.get("shadow", {}).get("fill", (0, 0, 0, 0))),
        },
        "impact_uppercase": bool(src.get("impact_uppercase", True)),
    }


def list_niches_for_prompt() -> str:
    """Riga per prompt LLM: 'business_finance, tech_ai, ...'."""
    return ", ".join(VALID_NICHES)
