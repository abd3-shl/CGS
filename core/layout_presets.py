"""
Dynamic Layout & Smart Text Zones: preset di scena a "zone" (1080x1920).

Niente figura intera: i personaggi sono ingranditi in scala su larghezza
(120-180% dello schermo) e ancorati dal basso con le gambe fuori inquadratura
(i piedi non sono MAI visibili, la testa resta sempre in campo con una
headroom configurabile). Il cropping e' solo compositivo: le coordinate
(X, Y) possono uscire dal canvas e il paste ritaglia il visibile.

Preset (canvas 1080x1920, asset di riferimento 768x1376 figura intera):
- `layout_center_standard`: 125% larghezza, centrato in basso (mezza figura,
  testa-busto-fianchi). Testo in alto (Y 150-900).
- `layout_center_punch_in`: 170% larghezza (primo piano busto/testa).
  Testo nel terzo superiore in sovrimpressione con pill ad alto contrasto.
- `layout_split_left`: 130% larghezza, spalla sinistra fuori campo
  (overhang negativo). Testo a destra (X 640-1000, banda centrale).
- `layout_split_right`: speculare (testo a sinistra, X 80-420).
  Posa 4 ("indicare" verso la sua sinistra = verso destra dello spettatore):
  SEMPRE in `layout_split_left` (a sinistra, indica verso il testo a destra);
  mai a destra (indicherebbe fuori campo). Vincolo configurabile in
  `config.CHARACTER_POSE_SIDE_MAP` (es. "4:left") per futuri asset.

Punch-in: flag per-chunk (jump-cut con ingrandimento improvviso per enfasi,
max 2 per video). Su un preset normale applica PUNCH_IN_FACTOR alle
dimensioni; sul preset punch_in la scala e' gia' ravvicinata.

Geometria misurata sugli asset (testa src x300-470/y130-340, spalle da y380):
le safe area sono scelte per non sovrapporsi mai al volto/busto; il text
engine e il character engine risolvono entrambi da `resolve_chunk_layout`
(vedi core/character_selector.py), quindi non possono divergere.

Margini/padding configurabili: SPLIT_OVERHANG_X, SAFE_AREA inset nei box,
TEXT_PILL_*.
"""

from config import VIDEO_HEIGHT, VIDEO_WIDTH

# Nomi preset validi (ordine stabile, usato anche dal fallback deterministico).
VALID_LAYOUT_PRESETS: list[str] = [
    "layout_center_standard",
    "layout_center_punch_in",
    "layout_split_left",
    "layout_split_right",
]

# Vecchi nomi (sistema a zone v1): ancora accettati, mappati sui nuovi.
DEPRECATED_PRESET_ALIASES: dict[str, str] = {
    "layout_bottom_focus": "layout_center_standard",
    "layout_closeup_center": "layout_center_punch_in",
}

# Transizioni di ingresso valide (nuovo sistema a zone).
# "zoom_in": scala dolce 0.92 -> 1.0 + fade (alternativa a slide_up per i center,
# ritmo coerente senza movimenti laterali continui). "none" solo per continuita'
# pixel-identica (stessa identita': taglio invisibile, nessuna animazione).
VALID_TRANSITION_IN: list[str] = [
    "slide_from_left",
    "slide_from_right",
    "slide_up",
    "slide_from_bottom",
    "fade",
    "zoom_in",
    "none",
]

# Transizioni legacy (posizionamento statico v1) -> canoniche del nuovo sistema.
# "slide_side" e' direzionale: la risoluzione dipende dal lato del preset.
LEGACY_TRANSITION_MAP: dict[str, str | None] = {
    "slide_up": "slide_up",
    "slide_side": None,  # risolto in base al lato (left/right)
    "fade": "fade",
    "none": "none",
}

# Posizioni legacy v1 -> preset piu' vicino (per output LLM in formato vecchio
# o chunk arricchiti senza layout: nessuna regressione).
LEGACY_POSITION_TO_PRESET: dict[str, str] = {
    "bottom_left": "layout_split_left",
    "side_left": "layout_split_left",
    "bottom_right": "layout_split_right",
    "side_right": "layout_split_right",
    "bottom_center": "layout_center_standard",
}

# --- Scala personaggio: percentuale della LARGHEZZA schermo ---
PRESET_WIDTH_PCT: dict[str, float] = {
    "layout_center_standard": 1.25,
    "layout_center_punch_in": 1.70,
    "layout_split_left": 1.30,
    "layout_split_right": 1.30,
}

# Moltiplicatore punch-in su preset normali (jump-cut di ingrandimento).
PUNCH_IN_FACTOR: float = 1.35
# Max punch-in per video (frasi chiave / rivelazioni / CTA finali).
MAX_PUNCH_INS_PER_VIDEO: int = 2

# --- Ancoraggio verticale: headroom px dal bordo superiore al top asset ---
# (il fondo esce sempre sotto canvas_h: gambe/piedi fuori inquadratura).
PRESET_HEADROOM_PX: dict[str, int] = {
    "layout_center_standard": 500,
    "layout_center_punch_in": 110,
    "layout_split_left": 250,
    "layout_split_right": 250,
}

# --- Ancoraggio orizzontale split: spalla fuori campo (px su 1080) ---
SPLIT_OVERHANG_X: int = 420

# Text Safe Area per preset: (x_min, y_min, x_max, y_max) su 1080x1920.
PRESET_SAFE_AREA: dict[str, tuple[int, int, int, int]] = {
    "layout_center_standard": (90, 150, 990, 900),    # meta' superiore
    "layout_center_punch_in": (90, 150, 990, 640),    # terzo superiore (+pill)
    "layout_split_left": (640, 560, 1000, 940),       # destra, banda centrale
    "layout_split_right": (80, 560, 420, 940),        # sinistra, banda centrale
}

# Scala font per preset (box stretti degli split -> testo leggermente minore).
PRESET_FONT_SCALE: dict[str, float] = {
    "layout_center_standard": 1.0,
    "layout_center_punch_in": 1.0,
    "layout_split_left": 0.9,
    "layout_split_right": 0.9,
}

# Lato del personaggio (guida le transizioni direzionali e gli exit).
PRESET_SIDE: dict[str, str] = {
    "layout_center_standard": "center",
    "layout_center_punch_in": "center",
    "layout_split_left": "left",
    "layout_split_right": "right",
}

# Transizione di ingresso di default per preset.
# I center alternano slide_up / zoom_in per varieta' ritmica (vedi
# character_selector._enforce_rhythm_variety); gli split restano direzionali.
PRESET_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "layout_center_standard": "slide_up",
    "layout_center_punch_in": "fade",
    "layout_split_left": "slide_from_left",
    "layout_split_right": "slide_from_right",
}

# Alternativa dolce per i center (stessa famiglia, nessun movimento laterale).
PRESET_ALTERNATE_TRANSITION_IN: dict[str, str] = {
    "layout_center_standard": "zoom_in",
    "layout_center_punch_in": "fade",
    "layout_split_left": "fade",
    "layout_split_right": "fade",
}

# Preset che richiedono la pill ad alto contrasto dietro il testo.
PRESET_TEXT_BACKGROUND: dict[str, bool] = {
    "layout_center_standard": False,
    "layout_center_punch_in": True,
    "layout_split_left": False,
    "layout_split_right": False,
}

# Colore/alpha della pill dietro il testo (nero semi-trasparente).
TEXT_PILL_FILL: tuple[int, int, int, int] = (0, 0, 0, 170)
TEXT_PILL_PAD: int = 28
TEXT_PILL_RADIUS: int = 36


def is_valid_preset(name) -> bool:
    """Vero se `name` e' un layout preset noto (inclusi gli alias deprecati)."""
    return name in VALID_LAYOUT_PRESETS or name in DEPRECATED_PRESET_ALIASES


def normalize_preset(name, fallback: str = "layout_center_standard") -> str:
    """Normalizza il preset (alias deprecati e position legacy mappate).

    Ritorna sempre un nome canonico di VALID_LAYOUT_PRESETS.
    """
    if name in VALID_LAYOUT_PRESETS:
        return name
    if isinstance(name, str) and name in DEPRECATED_PRESET_ALIASES:
        return DEPRECATED_PRESET_ALIASES[name]
    if isinstance(name, str) and name in LEGACY_POSITION_TO_PRESET:
        return LEGACY_POSITION_TO_PRESET[name]
    return fallback if fallback in VALID_LAYOUT_PRESETS else "layout_center_standard"


def preset_width_pct(name: str, punch_in: bool = False) -> float:
    """Percentuale larghezza schermo per il preset (punch_in la amplifica)."""
    preset = normalize_preset(name)
    pct = PRESET_WIDTH_PCT.get(preset, 1.25)
    if punch_in and preset != "layout_center_punch_in":
        pct *= PUNCH_IN_FACTOR
    return pct


def preset_headroom_px(name: str, canvas_h: int = VIDEO_HEIGHT) -> int:
    """Headroom (px) per il preset, scalato su canvas diversi da 1080x1920."""
    preset = normalize_preset(name)
    base = PRESET_HEADROOM_PX.get(preset, 500)
    if canvas_h == VIDEO_HEIGHT:
        return base
    return int(round(base * canvas_h / VIDEO_HEIGHT))


def preset_overhang_x(canvas_w: int = VIDEO_WIDTH) -> int:
    """Overhang laterale degli split (px), scalato sulla larghezza canvas."""
    if canvas_w == VIDEO_WIDTH:
        return SPLIT_OVERHANG_X
    return int(round(SPLIT_OVERHANG_X * canvas_w / VIDEO_WIDTH))


def preset_safe_area(
    name: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int]:
    """Text Safe Area (x_min, y_min, x_max, y_max) per il preset.

    Le aree sono disegnate per 1080x1920; su canvas diversi vengono scalate
    proporzionalmente (i default di canvas coincidono con le costanti sopra).
    """
    box = PRESET_SAFE_AREA.get(
        normalize_preset(name), PRESET_SAFE_AREA["layout_center_standard"])
    if canvas_w == VIDEO_WIDTH and canvas_h == VIDEO_HEIGHT:
        return box
    sx, sy = canvas_w / VIDEO_WIDTH, canvas_h / VIDEO_HEIGHT
    return (
        int(round(box[0] * sx)), int(round(box[1] * sy)),
        int(round(box[2] * sx)), int(round(box[3] * sy)),
    )


def preset_font_scale(name: str) -> float:
    """Moltiplicatore dimensione font per il preset (1.0 default)."""
    try:
        return float(PRESET_FONT_SCALE.get(normalize_preset(name), 1.0))
    except (TypeError, ValueError):
        return 1.0


def preset_side(name: str) -> str:
    """Lato del personaggio: 'left' | 'right' | 'center'."""
    return PRESET_SIDE.get(normalize_preset(name), "center")


def preset_default_transition(name: str) -> str:
    """Transizione di ingresso naturale per il preset."""
    return PRESET_DEFAULT_TRANSITION_IN.get(normalize_preset(name), "fade")


def preset_needs_text_background(name: str) -> bool:
    """Vero se il testo va protetto con la pill ad alto contrasto."""
    return bool(PRESET_TEXT_BACKGROUND.get(normalize_preset(name), False))


def normalize_transition_in(value, preset_name: str = "layout_center_standard") -> str:
    """Normalizza una transizione al vocabolario del nuovo sistema.

    Accetta i nomi nuovi e quelli legacy v1 (slide_up/slide_side/fade/none):
    'slide_side' diventa slide_from_left/right in base al lato del preset.
    Valori ignoti/None -> default del preset.
    """
    preset = normalize_preset(preset_name)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("zoom", "zoom_in", "scale_in", "scale-in"):
            return "zoom_in"
        if v in VALID_TRANSITION_IN:
            return "slide_up" if v == "slide_from_bottom" else v
        if v in LEGACY_TRANSITION_MAP:
            mapped = LEGACY_TRANSITION_MAP[v]
            if mapped is not None:
                return mapped
            # slide_side direzionale
            side = preset_side(preset)
            return "slide_from_left" if side == "left" else "slide_from_right"
    return preset_default_transition(preset)


def preset_alternate_transition(name: str) -> str:
    """Transizione alternativa dolce per il preset (varieta' ritmica)."""
    try:
        return PRESET_ALTERNATE_TRANSITION_IN.get(normalize_preset(name), "fade")
    except Exception:
        return "fade"


def legacy_transition(transition_in: str) -> str:
    """Compatibilita' v1: transition_in canonica -> transizione legacy."""
    mapping = {
        "slide_from_left": "slide_side",
        "slide_from_right": "slide_side",
        "slide_up": "slide_up",
        "slide_from_bottom": "slide_up",
        "fade": "fade",
        "zoom_in": "fade",
        "none": "none",
    }
    return mapping.get(transition_in, "fade")


def legacy_position(preset_name: str) -> str:
    """Compatibilita' v1: preset -> posizione legacy piu' vicina."""
    mapping = {
        "layout_split_left": "bottom_left",
        "layout_split_right": "bottom_right",
        "layout_center_standard": "bottom_center",
        "layout_center_punch_in": "bottom_center",
    }
    return mapping.get(normalize_preset(preset_name), "bottom_center")


def describe_preset(name: str) -> str:
    """Riga descrittiva del preset (per prompt LLM e logging)."""
    info = {
        "layout_center_standard": "mezza figura centrata in basso (125% larghezza), testo in ALTO (y 150-900)",
        "layout_center_punch_in": "PRIMO PIANO busto/testa (170% larghezza), testo nel terzo superiore con sfondo ad alto contrasto",
        "layout_split_left": "personaggio a SINISTRA (130%, spalla fuori campo), testo a DESTRA (ideale posa 4: indica il testo)",
        "layout_split_right": "personaggio a DESTRA (130%), testo a SINISTRA",
    }
    return info.get(normalize_preset(name), str(name))
