"""
Configurazione centrale del progetto.
Le API key vanno inserite qui oppure, meglio, tramite variabili d'ambiente
(consigliato per non salvare chiavi in chiaro nei file).

Priorità dei valori:
  1. variabili d'ambiente di sistema
  2. file `.env` nella root del progetto (vedi `.env.example`)
  3. default definiti qui sotto
"""

import os
import sys
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def _load_env_file() -> None:
    """Carica `.env` dalla cartella del progetto (non dalla working directory).

    Usa python-dotenv se disponibile, altrimenti un parser minimo integrato.
    Le variabili d'ambiente di sistema hanno sempre la precedenza (come dotenv).
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        return
    except ImportError:
        pass

    # Fallback senza dipendenze: parsing riga-per-riga di KEY=valore.
    try:
        with open(ENV_PATH, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    print(
        "Avviso: python-dotenv non installato, uso il parser .env integrato "
        "(consigliato: pip install -r requirements.txt).",
        file=sys.stderr,
    )
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[name] = value


_load_env_file()


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_tuple(key: str, default: tuple) -> tuple:
    raw = os.environ.get(key, "")
    if not raw or not raw.strip():
        return default
    try:
        return tuple(int(x.strip()) for x in raw.split(","))
    except ValueError:
        return default


def _get_str_or_none(key: str) -> str | None:
    raw = os.environ.get(key, "")
    return raw.strip() or None


def _get_str_list(*names: str) -> list[str]:
    """Legge una o più variabili d'ambiente come lista di stringhe.

    Accetta valori separati da virgola e/o a capo, rimuove spazi, virgolette
    e duplicati (mantenendo l'ordine). Es.:
        ELEVENLABS_API_KEYS="chiave1, chiave2, chiave3"
    """
    items: list[str] = []
    for name in names:
        raw = os.environ.get(name, "")
        if not raw:
            continue
        for part in raw.replace("\n", ",").split(","):
            item = part.strip().strip('"').strip("'").strip()
            if item and item not in items:
                items.append(item)
    return items


def _get_key_list(*names: str) -> list[str]:
    """Alias di _get_str_list per la lettura delle API key."""
    return _get_str_list(*names)

# ---- API KEYS ----
# Priorità: env di sistema > file `.env` > stringa vuota.
# Copia `.env.example` in `.env` e compilalo (vedi README, sezione Setup).
#
# Sono supportate PIÙ chiavi per servizio (fallback automatico): se una chiave
# fallisce (quota esaurita, rate limit, chiave non valida...), il codice prova
# la successiva finché una non funziona. Formati accettati:
#   ELEVENLABS_API_KEYS="chiave1,chiave2,chiave3"   (consigliato per multi-key)
#   ELEVENLABS_API_KEY="chiave-singola"             (equivalente a una sola chiave)
# Le due variabili si cumulano (prima le _KEYS, poi la _KEY singola).

ELEVENLABS_API_KEYS: list[str] = _get_key_list("ELEVENLABS_API_KEYS", "ELEVENLABS_API_KEY")
GROQ_API_KEYS: list[str] = _get_key_list("GROQ_API_KEYS", "GROQ_API_KEY")

# Alias singola chiave (prima disponibile o "") per retrocompatibilità
# con eventuale codice che importa ELEVENLABS_API_KEY / GROQ_API_KEY.
ELEVENLABS_API_KEY = ELEVENLABS_API_KEYS[0] if ELEVENLABS_API_KEYS else ""
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

# ---- ElevenLabs ----
# Voce default ("Rachel"), usata per tutte le chiavi se VOICE_IDS non è impostato.
# Lista voci disponibili: https://elevenlabs.io/app/voice-library
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # voce default ("Rachel"), sostituibile
# Voci per-chiave (opzionale): serve quando ogni account ha voci diverse
# (es. voci clonate esistenti solo sull'account che le ha create).
#   - 1 solo ID   -> vale per tutte le chiavi (come ELEVENLABS_VOICE_ID)
#   - N ID = N key -> abbinamento 1:1 (chiave[i] usa voce[i])
#   - altri casi  -> errore di configurazione (sollevato all'avvio del job)
ELEVENLABS_VOICE_IDS: list[str] = _get_str_list("ELEVENLABS_VOICE_IDS")
# Modello TTS (supporta l'italiano)
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")  # supporta l'italiano
# Formato audio di output (query param `output_format` dell'endpoint
# POST /v1/text-to-speech/{voice_id}; default dei docs ufficiali).
ELEVENLABS_OUTPUT_FORMAT = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")


def get_elevenlabs_voice_id(key_index: int, total_keys: int) -> str:
    """Restituisce il voice ID da usare con la chiave n. `key_index` (0-based).

    Regole di risoluzione (vedi ELEVENLABS_VOICE_IDS sopra):
      - nessun ID in lista  -> ELEVENLABS_VOICE_ID per tutte le chiavi;
      - 1 solo ID in lista  -> quell'ID per tutte le chiavi;
      - N ID = N chiavi     -> abbinamento 1:1.

    Raises:
        ValueError: se la lista ha più di 1 elemento ma lunghezza diversa
            dal numero di chiavi (configurazione ambigua).
    """
    if not ELEVENLABS_VOICE_IDS:
        return ELEVENLABS_VOICE_ID
    if len(ELEVENLABS_VOICE_IDS) == 1:
        return ELEVENLABS_VOICE_IDS[0]
    if len(ELEVENLABS_VOICE_IDS) == total_keys:
        return ELEVENLABS_VOICE_IDS[key_index]
    raise ValueError(
        f"ELEVENLABS_VOICE_IDS contiene {len(ELEVENLABS_VOICE_IDS)} voci ma le "
        f"chiavi sono {total_keys}: usa 1 sola voce (vale per tutte le chiavi) "
        f"oppure esattamente una voce per chiave (abbinamento 1:1)."
    )

# ---- Groq ----
GROQ_WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")  # rapido ed economico, ottimo per trascrizione
# Modello LLM per l'estrazione delle parole chiave (cfr. https://console.groq.com/docs/models)
GROQ_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "openai/gpt-oss-120b")

# ---- Parole chiave ----
KEYWORDS_MAX = _get_int("KEYWORDS_MAX", 10)  # n. massimo di parole chiave evidenziate per video
KEYWORDS_MIN_GAP = _get_int("KEYWORDS_MIN_GAP", 12)  # distanza minima in parole tra due keyword (anti-ammasso)

# ---- Tema dinamico ----
# Modello LLM per la palette tema (default: stesso delle keyword, ma separabile).
GROQ_THEME_MODEL = os.environ.get("GROQ_THEME_MODEL", GROQ_LLM_MODEL)
# Soglia minima di differenza di luminanza (0-255) per la validazione contrasto.
THEME_MIN_LUMINANCE_DIFF = _get_int("THEME_MIN_LUMINANCE_DIFF", 80)

# ---- Raggruppamento per enfasi ----
EMPHASIS_MAX_WORDS_PER_CHUNK = _get_int("EMPHASIS_MAX_WORDS_PER_CHUNK", 3)  # max parole per chunk
EMPHASIS_MIN_WORDS_PER_CHUNK = _get_int("EMPHASIS_MIN_WORDS_PER_CHUNK", 1)  # min parole per chunk

# ---- Video ----
VIDEO_WIDTH = _get_int("VIDEO_WIDTH", 1080)
VIDEO_HEIGHT = _get_int("VIDEO_HEIGHT", 1920)
VIDEO_FPS = _get_int("VIDEO_FPS", 30)
# Nota: lo sfondo video viene dal tema dinamico (core/theme.py),
# non più da un colore fisso in configurazione.

# ---- Sottotitoli ----
SUBTITLE_FONT_PATH = _get_str_or_none("SUBTITLE_FONT_PATH")  # None = usa un font di default del sistema, vedi core/renderer.py
SUBTITLE_FONT_SIZE = _get_int("SUBTITLE_FONT_SIZE", 64)
SUBTITLE_COLOR = _get_tuple("SUBTITLE_COLOR", (255, 255, 255, 255))  # bianco RGBA
SUBTITLE_STROKE_COLOR = _get_tuple("SUBTITLE_STROKE_COLOR", (0, 0, 0, 255))  # contorno nero per leggibilità
SUBTITLE_STROKE_WIDTH = _get_int("SUBTITLE_STROKE_WIDTH", 0)  # 0 = nessun contorno sul testo
SUBTITLE_MAX_CHARS = _get_int("SUBTITLE_MAX_CHARS", 38)   # lunghezza massima approx per chunk di sottotitolo
SUBTITLE_MAX_WORDS = _get_int("SUBTITLE_MAX_WORDS", 7)    # numero massimo di parole per chunk

# ---- Animazioni testo per-parola (Fase 3 + Tier T0-T3) ----
# T0 base fade / T1 accent rise-fade / T2 impact pop / T3 hero-pop (1 per video).
# Fonte moto = style LLM (base/impact/accent) + flag deterministico is_hero;
# fonte colore = tema + palette keyword (vedi core/text_animator._styled_fills).
# Path legacy (senza tipografia) usa solo T0/T2 per stabilita'.
TEXT_ANIMATION_ENABLED = os.environ.get("TEXT_ANIMATION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TEXT_ANIMATION_ENTRY_DURATION = _get_float("TEXT_ANIMATION_ENTRY_DURATION", 0.18)  # secondi, durata entrata singola parola
TEXT_ANIMATION_EXIT_DURATION = _get_float("TEXT_ANIMATION_EXIT_DURATION", 0.15)  # secondi, durata fade-out di gruppo
KEYWORD_ENTRY_SCALE_FROM = _get_float("KEYWORD_ENTRY_SCALE_FROM", 0.7)  # scala iniziale entrata keyword (0.7 -> 1.0)
# T1 accent: risalita verticale senza scala (non deforma handwritten), solo in entry.
TEXT_ANIMATION_ACCENT_LIFT_PX = _get_float("TEXT_ANIMATION_ACCENT_LIFT_PX", 10.0)  # px, rise 10 -> 0
# T3 hero: 1 parola per video (climax hook o verbo CTA), pop marcato + hold.
TEXT_ANIMATION_HERO_SCALE_FROM = _get_float("TEXT_ANIMATION_HERO_SCALE_FROM", 0.6)  # scala iniziale hero (0.6 -> 1.0)
TEXT_ANIMATION_HERO_ENTRY_DURATION = _get_float("TEXT_ANIMATION_HERO_ENTRY_DURATION", 0.22)  # s, overshoot leggibile (>=5 frame)
TEXT_ANIMATION_HERO_EXIT_DELAY = _get_float("TEXT_ANIMATION_HERO_EXIT_DELAY", 0.06)  # s, ~2 frame @30fps oltre il gruppo
# Numeri/dati (impact con cifre): pop piu' corto e secco, mai hero.
TEXT_ANIMATION_NUMBER_ENTRY_DURATION = _get_float("TEXT_ANIMATION_NUMBER_ENTRY_DURATION", 0.15)  # s

# ---- Personaggi 2D "Character-Driven Overlay" ----
# 1 = personaggi sovrapposti tra sfondo e sottotitoli, 0 = video senza personaggi.
CHARACTER_ENABLED = os.environ.get("CHARACTER_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
# Cartella asset personaggi (pose 1.jpg ... 5.jpg; supportati anche .png/.jpeg).
CHARACTERS_DIR = Path(BASE_DIR) / "assets" / "characters"
# Posizionamenti e transizioni validi (cfr. core/character_selector.py).
CHARACTER_VALID_POSITIONS: list[str] = ["bottom_center", "bottom_left", "bottom_right", "side_left", "side_right"]
CHARACTER_VALID_TRANSITIONS: list[str] = ["slide_up", "slide_side", "fade", "none"]
# N. pose disponibili (1.jpg ... 5.jpg) e scala relativa all'altezza 1920px.
CHARACTER_POSE_COUNT = _get_int("CHARACTER_POSE_COUNT", 5)
CHARACTER_SCALE_MIN = _get_float("CHARACTER_SCALE_MIN", 0.65)
CHARACTER_SCALE_MAX = _get_float("CHARACTER_SCALE_MAX", 0.90)
# Alias storici (retrocompatibilita').
CHARACTER_POSITIONS = CHARACTER_VALID_POSITIONS
CHARACTER_TRANSITIONS = CHARACTER_VALID_TRANSITIONS
# ---- Ritmo visivo personaggi (stabile, mai statico) ----
# Max chunk consecutivi con STESSA posa / STESSO lato prima di forzare un cambio.
# 2 = ritmo calmo (mai 3 uguali di fila). Le apparizioni (macro-blocchi) usano
# una posa/lato unici per blocco; tra blocchi adiacenti si evita la ripetizione
# (posa diversa e, quando possibile, lato diverso). Applica a corpo e fallback;
# hook primo chunk e CTA card restano bloccati per stabilita' intenzionale.
CHARACTER_MAX_SAME_POSE = _get_int("CHARACTER_MAX_SAME_POSE", 2)
CHARACTER_MAX_SAME_SIDE = _get_int("CHARACTER_MAX_SAME_SIDE", 2)
# ---- Idle breathing leggero ma visibile (personaggio vivo, video mai statico) ----
# Solo bob verticale dolce, NESSUNA rotazione laterale (tilt=0: il dondolio
# destra-sinistra rendeva il video instabile). 1 = ON, 0 = OFF.
CHARACTER_IDLE_ENABLED = _get_int("CHARACTER_IDLE_ENABLED", 1)  # 1 = ON, 0 = OFF
CHARACTER_IDLE_AMP_Y = _get_float("CHARACTER_IDLE_AMP_Y", 4.0)  # px, respiro percettibile ma delicato
CHARACTER_IDLE_FREQ = _get_float("CHARACTER_IDLE_FREQ", 0.4)  # Hz, ritmo calmo (~2.5s per ciclo)
CHARACTER_IDLE_TILT_DEG = _get_float("CHARACTER_IDLE_TILT_DEG", 0.0)  # gradi, 0 = nessuna rotazione laterale
# ---- Animazioni character (entrate/uscite per-frame fluidi + morph coerente) ----
# Entrata slide&pop ~0.20s (~6 frame @30fps) da offset Y +300px con ease_out_back;
# uscita slide-drop ~0.16s (~5 frame @30fps) verso +400px con ease_in_cubic.
# Morph di continuita' (0.40) e zoom punch smart (0.60) restano piu' morbidi per
# ritmo coerente (mai frenetico): l'entrata/uscita rapida riguarda solo
# apparizione/sparizione, non i cambi posa/lato (morph fluido anti-blink).
CHARACTER_ENTRY_DURATION = _get_float("CHARACTER_ENTRY_DURATION", 0.20)
CHARACTER_FIRST_ENTRY_DURATION = _get_float("CHARACTER_FIRST_ENTRY_DURATION", 0.20)
CHARACTER_EXIT_DURATION = _get_float("CHARACTER_EXIT_DURATION", 0.16)
CHARACTER_PUNCH_ZOOM_DURATION = _get_float("CHARACTER_PUNCH_ZOOM_DURATION", 0.60)
CHARACTER_MORPH_DURATION = _get_float("CHARACTER_MORPH_DURATION", 0.40)
# Persistenza nei gap inter-chunk: 1 = il character resta visibile durante le
# pause quando continua nel chunk dopo (fix blink sparizione/riapparizione).
CHARACTER_GAP_HOLD_ENABLED = os.environ.get("CHARACTER_GAP_HOLD_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
CHARACTER_GAP_HOLD_MAX = _get_float("CHARACTER_GAP_HOLD_MAX", 1.5)  # cap secondi per gap
# ---- Stabilita' macro-blocchi + presenza discontinua ("Breath & Focus") ----
# Il personaggio NON cambia posa/lato dentro lo stesso macro-blocco narrativo:
# ogni apparizione dura almeno CHARACTER_MIN_BLOCK_DURATION secondi.
# Con DISCONTINUOUS_MODE=1 il personaggio appare in Hook e CTA e scompare
# nei beat intermedi (Body) per lasciare spazio al testo (anti-flicker).
CHARACTER_MIN_BLOCK_DURATION = _get_float("CHARACTER_MIN_BLOCK_DURATION", 2.5)  # durata min apparizione in sec
CHARACTER_DISCONTINUOUS_MODE = _get_int("CHARACTER_DISCONTINUOUS_MODE", 1)  # 1 = ON (scompare nei beat), 0 = sempre visibile
CHARACTER_HOOK_VISIBLE = _get_int("CHARACTER_HOOK_VISIBLE", 1)  # 1 = sempre visibile in Hook
CHARACTER_CTA_VISIBLE = _get_int("CHARACTER_CTA_VISIBLE", 1)  # 1 = sempre visibile in CTA
CHARACTER_BODY_VISIBLE_RATIO = _get_float("CHARACTER_BODY_VISIBLE_RATIO", 0.6)  # frazione blocchi Body visibili (~60%: pause nascoste brevi e distribuite, mai lunghi tratti senza personaggio)

def _get_pose_side_map(key: str, default: str) -> dict[int, str]:
    """Mappa posa -> vincolo lato (any|center|left|right|split).

    Formato env: '1:any,2:center,3:center,4:left,5:split'.
    Pensata per adattarsi a futuri asset senza toccare il codice: se una
    nuova posa indica verso sinistra (come l'attuale posa 4 che punta verso
    destra dello spettatore), basta impostarla a 'left' (personaggio a
    sinistra, testo a destra); se punta verso destra, a 'right'.
    """
    raw = os.environ.get(key, default)
    if raw is None:
        raw = default
    try:
        text = str(raw or default)
    except Exception:
        text = default
    allowed = {"any", "center", "left", "right", "split"}
    out: dict[int, str] = {}
    try:
        for part in text.replace("\n", ",").replace(";", ",").split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            left, _, right = part.partition(":")
            try:
                pose = int(left.strip())
            except (TypeError, ValueError):
                continue
            side = right.strip().lower()
            if side in allowed:
                out[pose] = side
    except Exception:
        pass
    return out


# ---- Direzione pose 2D (adattabile a futuri asset senza codice) ----
# Significato vincoli:
#   any    = nessun vincolo (segue il lato richiesto dal ritmo/narrazione)
#   center = solo layout_center_standard (pose larghe come la 2 a braccia aperte)
#   left   = solo layout_split_left (personaggio a SINISTRA, testo a DESTRA)
#   right  = solo layout_split_right (personaggio a DESTRA, testo a SINISTRA)
#   split  = solo split (alternati left/right, es. posa 5 riflessiva)
# Posa 4 (indica verso la SUA sinistra = verso DESTRA dello spettatore):
# deve stare SEMPRE a sinistra (split_left) cosi' indica verso il testo a destra.
# Metterla a destra la farebbe indicare fuori campo (lontano dal testo).
CHARACTER_POSE_SIDE_MAP: dict[int, str] = _get_pose_side_map(
    "CHARACTER_POSE_SIDES", "1:any,2:center,3:center,4:left,5:split"
)
# Riempie eventuali pose mancanti (1..POSE_COUNT) con default coerenti.
try:
    _POSE_SIDE_DEFAULTS: dict[int, str] = {1: "any", 2: "center", 3: "center", 4: "left", 5: "split"}
    for _p in range(1, max(1, int(CHARACTER_POSE_COUNT)) + 1):
        CHARACTER_POSE_SIDE_MAP.setdefault(_p, _POSE_SIDE_DEFAULTS.get(_p, "any"))
except Exception:
    pass


def get_pose_side_constraint(pose: int) -> str:
    """Vincolo lato per posa ('any' se ignota, mai eccezioni)."""
    try:
        return CHARACTER_POSE_SIDE_MAP.get(int(pose), "any")
    except Exception:
        return "any"

# ---- Semantic Typography Engine v1 ----
# 1 = font/colori/dimensioni per nicchia + tagging LLM (base/impact/accent),
# 0 = path legacy (singolo font + keyword palette).
# Look pulito stile TikTok: NESSUN contorno nero (stroke=0) e NESSUNA ombra
# di default. La leggibilità è garantita dal contrasto tema (sfondo/testo
# validato in core/theme.py) + pill semi-trasparente sul preset punch-in.
TYPOGRAPHY_ENGINE_ENABLED = os.environ.get("TYPOGRAPHY_ENGINE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_BASE_FONT_SIZE = _get_int("TYPOGRAPHY_BASE_FONT_SIZE", 60)  # px, prima di font_scale del preset
TYPOGRAPHY_IMPACT_SCALE = _get_float("TYPOGRAPHY_IMPACT_SCALE", 1.4)  # 1.3x-1.5x da spec
TYPOGRAPHY_ACCENT_SCALE = _get_float("TYPOGRAPHY_ACCENT_SCALE", 1.1)
# Peso del font BASE (testo chiaro e leggibile): 600 = SemiBold, leggermente
# più in grassetto del Regular (400) ma non troppo (niente ExtraBold/Black).
# Applicato all'asse Weight dei font variabili (Inter/Roboto/Montserrat/...);
# per i font statici (Poppins/Lato/...) si usa un grassetto sintetico leggero
# (stroke 1px stesso colore, nessun contorno nero). Solo il base: impact e
# accent restano invariati per stile.
TYPOGRAPHY_BASE_WEIGHT = _get_int("TYPOGRAPHY_BASE_WEIGHT", 600)
TYPOGRAPHY_STROKE_WIDTH = _get_int("TYPOGRAPHY_STROKE_WIDTH", 0)  # 0 = nessun contorno (look pulito)
TYPOGRAPHY_SHADOW_ENABLED = os.environ.get("TYPOGRAPHY_SHADOW_ENABLED", "0").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_SHADOW_OFFSET = _get_tuple("TYPOGRAPHY_SHADOW_OFFSET", (3, 3))
TYPOGRAPHY_SHADOW_FILL = _get_tuple("TYPOGRAPHY_SHADOW_FILL", (0, 0, 0, 180))
# Cartella font scaricati (vedi core/font_manager.py).
FONTS_DIR = Path(BASE_DIR) / "assets" / "fonts"

# ---- Struttura narrativa hook / corpo a beat / CTA ----
# 1 = il video viene letto come struttura in 3 atti (hook, corpo a beat,
# CTA-outro) con tecniche dedicate per atto e finale stabilizzato;
# 0 = pipeline piatta legacy (nessuna differenziazione).
NARRATIVE_ENABLED = os.environ.get("NARRATIVE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
NARRATIVE_HOOK_MAX_CHUNKS = _get_int("NARRATIVE_HOOK_MAX_CHUNKS", 3)  # hook = prime 1-3 caption
NARRATIVE_CTA_MAX_CHUNKS = _get_int("NARRATIVE_CTA_MAX_CHUNKS", 4)  # CTA = ultime 1-4 caption con segnali
NARRATIVE_CTA_CARD = os.environ.get("NARRATIVE_CTA_CARD", "1").strip().lower() not in ("0", "false", "no", "off", "")
NARRATIVE_CTA_CARD_MAX_WORDS = _get_int("NARRATIVE_CTA_CARD_MAX_WORDS", 14)  # card persistente solo se CTA breve
NARRATIVE_HOOK_ENTRY_MULT = _get_float("NARRATIVE_HOOK_ENTRY_MULT", 0.7)  # hook più scattante (0.7x durata entrata)
NARRATIVE_HOOK_POP_FROM = _get_float("NARRATIVE_HOOK_POP_FROM", 0.55)  # pop hook più marcato (0.55 -> 1.0)

# ---- Performance / velocita' (stessi limiti, stesso output) ----
# PIPELINE_FAST=1: salta gli LLM pesanti (emphasis/character/tagging/nicchia -> euristiche
# deterministiche istantanee). Tema + keyword LLM restano attivi. Ideale per bulk veloci.
PIPELINE_FAST = os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", "")
# RENDER_PARALLEL=1: chunk animati e micro-video ffmpeg in ThreadPool (3-4 worker).
RENDER_PARALLEL = os.environ.get("RENDER_PARALLEL", "1").strip().lower() not in ("0", "false", "no", "off", "")
# FFMPEG_PRESET: veryfast default (qualita' invariata); ultrafast per bozze.
FFMPEG_PRESET = (os.environ.get("FFMPEG_PRESET", "veryfast") or "veryfast").strip() or "veryfast"

# ---- Percorsi progetto ----
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "outputs"))
TEMP_DIR = os.environ.get("TEMP_DIR", os.path.join(BASE_DIR, "temp"))

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-2:]}"


def check_keys() -> int:
    """Verifica ogni chiave con una chiamata gratuita di sola lettura.

    ElevenLabs: GET /v1/user (mostra anche i caratteri residui).
    Groq:       GET /v1/models (endpoint OpenAI-compatibile).
    Non consuma crediti. Ritorna il numero di chiavi NON funzionanti.
    Uso:  python config.py --check-keys
    """
    import requests

    print(f"Cartella progetto: {BASE_DIR}")
    print(f"File .env: {'trovato' if os.path.isfile(ENV_PATH) else 'NON TROVATO'}")
    bad = 0

    print(f"\nElevenLabs: {len(ELEVENLABS_API_KEYS)} chiavi")
    if not ELEVENLABS_API_KEYS:
        print("  (nessuna chiave configurata)")
    for i, key in enumerate(ELEVENLABS_API_KEYS, start=1):
        tag = f"  [{i}/{len(ELEVENLABS_API_KEYS)}] {_mask_secret(key)}"
        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": key},
                timeout=10,
            )
        except Exception as e:
            bad += 1
            print(f"{tag} ERRORE di rete: {e}")
            continue
        if resp.status_code == 200:
            try:
                sub = resp.json().get("subscription", {})
                print(
                    f"{tag} OK "
                    f"(tier={sub.get('tier')}, "
                    f"caratteri usati={sub.get('character_count')}/{sub.get('character_limit')})"
                )
            except Exception:
                print(f"{tag} OK")
        else:
            bad += 1
            print(f"{tag} FALLITA ({resp.status_code}): {resp.text[:150]}")

    print(f"\nGroq: {len(GROQ_API_KEYS)} chiavi")
    if not GROQ_API_KEYS:
        print("  (nessuna chiave configurata)")
    for i, key in enumerate(GROQ_API_KEYS, start=1):
        tag = f"  [{i}/{len(GROQ_API_KEYS)}] {_mask_secret(key)}"
        try:
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
        except Exception as e:
            bad += 1
            print(f"{tag} ERRORE di rete: {e}")
            continue
        if resp.status_code == 200:
            print(f"{tag} OK")
        else:
            bad += 1
            print(f"{tag} FALLITA ({resp.status_code}): {resp.text[:150]}")

    print(f"\nRisultato: {bad} chiavi non funzionanti.")
    return bad


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check-keys":
        sys.exit(1 if check_keys() else 0)
    print(
        "Uso: python config.py --check-keys   "
        "(verifica tutte le chiavi senza consumare crediti)"
    )
