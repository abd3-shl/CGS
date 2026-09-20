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

# ---- Sottotitoli (REELS-FIX v5: stroke 0, ambient shadow) ----
SUBTITLE_FONT_PATH = _get_str_or_none("SUBTITLE_FONT_PATH")  # None = usa un font di default del sistema, vedi core/renderer.py
SUBTITLE_FONT_SIZE = _get_int("SUBTITLE_FONT_SIZE", 54)
SUBTITLE_COLOR = _get_tuple("SUBTITLE_COLOR", (255, 255, 255, 255))  # bianco RGBA
SUBTITLE_STROKE_COLOR = _get_tuple("SUBTITLE_STROKE_COLOR", (0, 0, 0, 0))  # stroke 0 di default
SUBTITLE_STROKE_WIDTH = _get_int("SUBTITLE_STROKE_WIDTH", 0)  # 0 = nessun contorno (REELS-FIX v5)
SUBTITLE_MAX_CHARS = _get_int("SUBTITLE_MAX_CHARS", 38)   # lunghezza massima approx per chunk di sottotitolo
SUBTITLE_MAX_WORDS = _get_int("SUBTITLE_MAX_WORDS", 7)    # numero massimo di parole per chunk
# Auto-fit: dimensione minima assoluta per blocchi densi (mai sotto).
SUBTITLE_MIN_FONT_SIZE = _get_int("SUBTITLE_MIN_FONT_SIZE", 38)
# Auto-pill elegante quando contrasto < soglia (anziche' stroke).
SUBTITLE_PILL_FILL = _get_tuple("SUBTITLE_PILL_FILL", (0, 0, 0, 120))
SUBTITLE_PILL_RADIUS = _get_int("SUBTITLE_PILL_RADIUS", 24)

# ---- Animazioni testo per-parola (Fase 3, REELS-FIX v5: pop 0.85->1.0, no overshoot) ----
TEXT_ANIMATION_ENABLED = os.environ.get("TEXT_ANIMATION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TEXT_ANIMATION_ENTRY_DURATION = _get_float("TEXT_ANIMATION_ENTRY_DURATION", 0.18)  # secondi, durata entrata singola parola
TEXT_ANIMATION_EXIT_DURATION = _get_float("TEXT_ANIMATION_EXIT_DURATION", 0.15)  # secondi, durata fade-out di gruppo
KEYWORD_ENTRY_SCALE_FROM = _get_float("KEYWORD_ENTRY_SCALE_FROM", 0.85)  # 0.85 -> 1.0, mai oltre 1.0

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
# Ritmo transizioni (secondi): valori calmi per evitare flicker/appari-scompari
# troppo veloci. Entry = ingresso slide, exit = uscita slide_down su cambio lato.
CHARACTER_ENTRY_DURATION = _get_float("CHARACTER_ENTRY_DURATION", 0.55)
CHARACTER_EXIT_DURATION = _get_float("CHARACTER_EXIT_DURATION", 0.45)
# Max chunk consecutivi con stessa posa+layout (anti-sticker senza frenesia).
# 3 = ~4-6s di permanenza con chunk da 2-3 parole; CTA tollera +1.
CHARACTER_MAX_CONSECUTIVE = _get_int("CHARACTER_MAX_CONSECUTIVE", 3)
# Minimum Dwell Time (secondi): nessuna apparizione/scomparsa a ritmo di singola
# parola o chunk breve. Ogni permanenza (stessa identità) dura almeno 3.0s salvo
# ai confini narrativi forti (hook->corpo, corpo->CTA) dove il cambio è libero.
CHARACTER_MIN_DWELL_SECONDS = _get_float("CHARACTER_MIN_DWELL_SECONDS", 3.0)
# 1 = slide lunga da fuori-campo solo alla prima apparizione; i cambi successivi
# usano slide corta (260-320px) a piena opacità: niente salti da un bordo all'altro.
CHARACTER_FULL_TRAVEL_FIRST_ONLY = os.environ.get("CHARACTER_FULL_TRAVEL_FIRST_ONLY", "1").strip().lower() not in ("0", "false", "no", "off", "")
# Larghezza massima del SOGGETTO visibile (non dell'immagine intera col padding
# trasparente) in frazione di VIDEO_WIDTH. Vince sempre sulla scala da altezza:
# le pose larghe (es. braccia tese) vengono ridotte finché ci stanno.
CHARACTER_MAX_WIDTH_RATIO = _get_float("CHARACTER_MAX_WIDTH_RATIO", 0.62)
# Margine di sicurezza (px) dai bordi del frame per soggetto e faccia.
CHARACTER_SAFE_MARGIN_PX = _get_int("CHARACTER_SAFE_MARGIN_PX", 40)
# Frazione minima del soggetto che deve restare visibile a riposo (1.0 = intero).
CHARACTER_MIN_VISIBLE_RATIO = _get_float("CHARACTER_MIN_VISIBLE_RATIO", 0.97)
# Frazione minima della faccia che deve restare visibile (1.0 = mai tagliata).
CHARACTER_FACE_MIN_VISIBLE = _get_float("CHARACTER_FACE_MIN_VISIBLE", 1.0)
# 1 = salva in TEMP_DIR/debug_char/ un PNG per chunk con bordo frame, safe zone,
# subject_bbox, face_box e fascia testo + log di visible_ratio e correzioni.
CHARACTER_DEBUG = _get_int("CHARACTER_DEBUG", 0)
# Alias storici (retrocompatibilita').
CHARACTER_POSITIONS = CHARACTER_VALID_POSITIONS
CHARACTER_TRANSITIONS = CHARACTER_VALID_TRANSITIONS

# ---- Semantic Typography Engine v2 (REELS-FIX v5) ----
# 1 = font/colori/dimensioni per nicchia + tagging LLM (base/impact/accent),
# 0 = path legacy (singolo font + keyword palette).
# STROKE 0 ASSOLUTO di default; leggibilita' da contrasto + ambient shadow
# morbida (0,3,110) + auto-pill (0,0,0,120). Base 52-56px, minimo auto-fit 38px.
TYPOGRAPHY_ENGINE_ENABLED = os.environ.get("TYPOGRAPHY_ENGINE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_BASE_FONT_SIZE = _get_int("TYPOGRAPHY_BASE_FONT_SIZE", 54)  # px, prima di font_scale del preset
TYPOGRAPHY_MIN_FONT_SIZE = _get_int("TYPOGRAPHY_MIN_FONT_SIZE", 38)  # minimo auto-fit per blocchi densi
TYPOGRAPHY_IMPACT_SCALE = _get_float("TYPOGRAPHY_IMPACT_SCALE", 1.25)
TYPOGRAPHY_ACCENT_SCALE = _get_float("TYPOGRAPHY_ACCENT_SCALE", 1.05)
TYPOGRAPHY_STROKE_WIDTH = _get_int("TYPOGRAPHY_STROKE_WIDTH", 0)  # 0 = nessun contorno
TYPOGRAPHY_SHADOW_ENABLED = os.environ.get("TYPOGRAPHY_SHADOW_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_SHADOW_OFFSET = _get_tuple("TYPOGRAPHY_SHADOW_OFFSET", (0, 3))
TYPOGRAPHY_SHADOW_FILL = _get_tuple("TYPOGRAPHY_SHADOW_FILL", (0, 0, 0, 110))
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
