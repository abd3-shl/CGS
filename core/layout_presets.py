"""
Dynamic Layout & Smart Subtitles: preset di scena a "zone" (1080x1920).

Il personaggio e il testo si spartiscono lo schermo: ogni preset definisce
l'altezza del personaggio, il suo ancoraggio (anche fuori campo per l'effetto
"mezzo busto") e la Text Safe Area in cui i sottotitoli vengono wrappati e
centrati, senza mai sovrapporsi al viso/petto del personaggio.

Preset (vedi `LAYOUT_PRESETS`):
- `layout_split_left`:   personaggio grande a sinistra (spalla tagliata fuori
  campo), testo nella meta' destra. Transizione naturale: slide_from_left.
- `layout_split_right`:  speculare (personaggio a destra, testo a sinistra).
  Ideale con la posa 4 ("indicare"): il personaggio indica verso il testo.
- `layout_bottom_focus`: figura intera in basso al centro, testo nella meta'
  superiore (Y 200-800). Transizione naturale: slide_up.
- `layout_closeup_center`: busto/testa massicci al centro, testo in
  sovrimpressione bassa con pill semi-trasparente per la leggibilita'.

Il cropping e' solo compositivo: le coordinate (X, Y) possono uscire dal
canvas (X < 0, X + W > 1080, Y + H > 1920) e il paste ritaglia il visibile,
creando il "mezzo busto" senza tagliare fisicamente l'asset.
"""

from config import VIDEO_HEIGHT, VIDEO_WIDTH

# Nomi preset validi (ordine stabile, usato anche dal fallback deterministico).
VALID_LAYOUT_PRESETS: list[str] = [
    "layout_split_left",
    "layout_split_right",
    "layout_bottom_focus",
    "layout_closeup_center",
]

# Transizioni di ingresso valide (nuovo sistema a zone).
VALID_TRANSITION_IN: list[str] = [
    "slide_from_left",
    "slide_from_right",
    "slide_up",
    "slide_from_bottom",
    "fade",
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
# o chunk arricchiti senza layout_preset: nessuna regressione).
LEGACY_POSITION_TO_PRESET: dict[str, str] = {
    "bottom_left": "layout_split_left",
    "side_left": "layout_split_left",
    "bottom_right": "layout_split_right",
    "side_right": "layout_split_right",
    "bottom_center": "layout_bottom_focus",
}

# Altezze personaggio dettate dai preset (px su canvas 1920).
PRESET_CHAR_HEIGHT: dict[str, int] = {
    "layout_split_left": 1300,
    "layout_split_right": 1300,
    "layout_bottom_focus": 1000,
    "layout_closeup_center": 1600,
}

# Text Safe Area per preset: (x_min, y_min, x_max, y_max) sul canvas 1080x1920.
PRESET_SAFE_AREA: dict[str, tuple[int, int, int, int]] = {
    "layout_split_left": (560, 480, 1040, 1440),    # meta' destra
    "layout_split_right": (40, 480, 520, 1440),     # meta' sinistra
    "layout_bottom_focus": (90, 200, 990, 800),     # meta' superiore
    "layout_closeup_center": (90, 1500, 990, 1820),  # fascia bassa estrema
}

# Lato del personaggio (guida le transizioni direzionali e gli exit).
PRESET_SIDE: dict[str, str] = {
    "layout_split_left": "left",
    "layout_split_right": "right",
    "layout_bottom_focus": "center",
    "layout_closeup_center": "center",
}

# Transizione di ingresso di default per preset.
PRESET_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "layout_split_left": "slide_from_left",
    "layout_split_right": "slide_from_right",
    "layout_bottom_focus": "slide_up",
    "layout_closeup_center": "fade",
}

# Preset che richiedono la pill semi-trasparente dietro il testo.
PRESET_TEXT_BACKGROUND: dict[str, bool] = {
    "layout_split_left": False,
    "layout_split_right": False,
    "layout_bottom_focus": False,
    "layout_closeup_center": True,
}

# Offset orizzontale fuori campo per gli split (spalla tagliata).
_SPLIT_OFFSCREEN_X = 180

# Colore/alpha della pill dietro il testo (nero semi-trasparente).
TEXT_PILL_FILL: tuple[int, int, int, int] = (0, 0, 0, 170)
TEXT_PILL_PAD: int = 28
TEXT_PILL_RADIUS: int = 36


def is_valid_preset(name) -> bool:
    """Vero se `name` e' un layout preset noto."""
    return name in VALID_LAYOUT_PRESETS


def normalize_preset(name, fallback: str = "layout_bottom_focus") -> str:
    """Normalizza il preset (legacy position mappate, ignoti -> fallback)."""
    if name in VALID_LAYOUT_PRESETS:
        return name
    if isinstance(name, str) and name in LEGACY_POSITION_TO_PRESET:
        return LEGACY_POSITION_TO_PRESET[name]
    return fallback


def preset_char_height(name: str) -> int:
    """Altezza personaggio (px) dettata dal preset."""
    return PRESET_CHAR_HEIGHT.get(normalize_preset(name), 1000)


def preset_safe_area(
    name: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int]:
    """Text Safe Area (x_min, y_min, x_max, y_max) per il preset.

    Le aree sono disegnate per 1080x1920; su canvas diversi vengono scalate
    proporzionalmente (i default di canvas coincidono con le costanti sopra).
    """
    box = PRESET_SAFE_AREA.get(normalize_preset(name), PRESET_SAFE_AREA["layout_bottom_focus"])
    if canvas_w == VIDEO_WIDTH and canvas_h == VIDEO_HEIGHT:
        return box
    sx, sy = canvas_w / VIDEO_WIDTH, canvas_h / VIDEO_HEIGHT
    return (
        int(round(box[0] * sx)), int(round(box[1] * sy)),
        int(round(box[2] * sx)), int(round(box[3] * sy)),
    )


def preset_side(name: str) -> str:
    """Lato del personaggio: 'left' | 'right' | 'center'."""
    return PRESET_SIDE.get(normalize_preset(name), "center")


def preset_default_transition(name: str) -> str:
    """Transizione di ingresso naturale per il preset."""
    return PRESET_DEFAULT_TRANSITION_IN.get(normalize_preset(name), "fade")


def preset_needs_text_background(name: str) -> bool:
    """Vero se il testo va protetto con la pill semi-trasparente."""
    return bool(PRESET_TEXT_BACKGROUND.get(normalize_preset(name), False))


def normalize_transition_in(value, preset_name: str = "layout_bottom_focus") -> str:
    """Normalizza una transizione al vocabolario del nuovo sistema.

    Accetta i nomi nuovi e quelli legacy v1 (slide_up/slide_side/fade/none):
    'slide_side' diventa slide_from_left/right in base al lato del preset.
    Valori ignoti/None -> default del preset.
    """
    preset = normalize_preset(preset_name)
    if isinstance(value, str):
        v = value.strip().lower()
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


def legacy_transition(transition_in: str) -> str:
    """Compatibilita' v1: transition_in canonica -> transizione legacy."""
    mapping = {
        "slide_from_left": "slide_side",
        "slide_from_right": "slide_side",
        "slide_up": "slide_up",
        "slide_from_bottom": "slide_up",
        "fade": "fade",
        "none": "none",
    }
    return mapping.get(transition_in, "fade")


def legacy_position(preset_name: str) -> str:
    """Compatibilita' v1: preset -> posizione legacy piu' vicina."""
    mapping = {
        "layout_split_left": "bottom_left",
        "layout_split_right": "bottom_right",
        "layout_bottom_focus": "bottom_center",
        "layout_closeup_center": "bottom_center",
    }
    return mapping.get(normalize_preset(preset_name), "bottom_center")


def layout_character_xy(
    preset_name: str,
    image_size: tuple[int, int],
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int]:
    """Coordinate (X, Y) di overlay del personaggio per il preset.

    Possono uscire dal canvas (X < 0, X + W > canvas_w, Y + H > canvas_h):
    il paste ritaglia il visibile (effetto "mezzo busto" compositivo,
    nessun taglio fisico dell'asset).
    """
    preset = normalize_preset(preset_name)
    img_w, img_h = int(image_size[0]), int(image_size[1])
    if preset == "layout_split_left":
        return (-_SPLIT_OFFSCREEN_X, canvas_h - img_h)
    if preset == "layout_split_right":
        return (canvas_w - img_w + _SPLIT_OFFSCREEN_X, canvas_h - img_h)
    # bottom_focus e closeup: centrati orizzontalmente, ancorati in basso.
    return ((canvas_w - img_w) // 2, canvas_h - img_h)


def describe_preset(name: str) -> str:
    """Riga descrittiva del preset (per prompt LLM e logging)."""
    info = {
        "layout_split_left": "personaggio grande a SINISTRA (h=1300px), testo a DESTRA",
        "layout_split_right": "personaggio grande a DESTRA (h=1300px), testo a SINISTRA (ideale posa 4: indica il testo)",
        "layout_bottom_focus": "figura intera in basso al centro (h=1000px), testo in ALTO (y 200-800)",
        "layout_closeup_center": "primo piano centrale massiccio (h=1600px, busto/testa), testo in BASSO con sfondo semi-trasparente",
    }
    return info.get(normalize_preset(name), name)
