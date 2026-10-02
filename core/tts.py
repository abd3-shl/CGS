"""
Modulo TTS: converte lo script testuale in un file audio tramite l'API di ElevenLabs.

Endpoint usato (cfr. docs ufficiali
https://elevenlabs.io/docs/api-reference/text-to-speech/convert):
    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...
    Headers: xi-api-key, Content-Type: application/json
    Body:    {text, model_id, voice_settings}

Supporta più API key con fallback automatico: le chiavi in
config.ELEVENLABS_API_KEYS vengono provate in ordine e alla prima che
fallisce per motivi legati alla chiave/servizio (chiave non valida, quota
esaurita, rate limit, errore di rete o 5xx) si passa alla successiva.
Ogni chiave può avere la propria voce (config.ELEVENLABS_VOICE_IDS,
abbinamento 1:1): utile quando gli account hanno voci diverse
(es. voci clonate presenti solo su un account).
"""

import os
from collections.abc import Callable
import requests

from config import (
    ELEVENLABS_API_KEYS,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    TEMP_DIR,
    get_elevenlabs_voice_id,
)


class TTSError(Exception):
    """Errore generico durante la generazione audio."""
    pass


# Status HTTP per cui ha senso provare la chiave successiva: il problema
# è probabilmente legato alla singola chiave o a un limite temporaneo,
# non alla richiesta in sé (che è identica per tutte le chiavi).
_RETRYABLE_STATUS = {401, 402, 403, 429, 500, 502, 503, 504}


def _cfg_float(key: str, default: float) -> float:
    try:
        import config as _c
        return float(getattr(_c, key, default))
    except (TypeError, ValueError):
        return default


def _cfg_bool(key: str, default: bool) -> bool:
    try:
        import config as _c
        val = getattr(_c, key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        return default


# Profili voce per nicchia (default da spec P0; override via TTS_PROFILES_JSON).
# Nessuna chiamata LLM: la nicchia arriva da detect_niche euristico prima del TTS.
TTS_PROFILES: dict[str, dict] = {
    "fitness_sport": {"stability": 0.40, "style": 0.40, "speed": 1.10},
    "dark_motivational": {"stability": 0.45, "style": 0.35, "speed": 1.06},
    "tech_ai": {"stability": 0.50, "style": 0.25, "speed": 1.08},
    "lifestyle_vlog": {"stability": 0.45, "style": 0.30, "speed": 1.08},
    "business_finance": {"stability": 0.55, "style": 0.20, "speed": 1.06},
    "educational": {"stability": 0.60, "style": 0.15, "speed": 1.04},
}

# Capacità voice_settings per modello: alcuni modelli (es. v3/Flash) non
# accettano `style` / `use_speaker_boost`. Override via
# ELEVENLABS_MODEL_CAPABILITIES_JSON: {"model_id": ["stability", ...]}.
_MODEL_CAPABILITIES: dict[str, set[str]] = {
    "eleven_multilingual_v2": {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"},
    "eleven_multilingual_v1": {"stability", "similarity_boost", "style", "use_speaker_boost"},
    "eleven_monolingual_v1": {"stability", "similarity_boost"},
    "eleven_turbo_v2": {"stability", "similarity_boost", "speed"},
    "eleven_turbo_v2_5": {"stability", "similarity_boost", "speed"},
    "eleven_flash_v2": {"stability", "similarity_boost", "speed"},
    "eleven_flash_v2_5": {"stability", "similarity_boost", "speed"},
}

_FULL_SETTINGS = ("stability", "similarity_boost", "style", "speed", "use_speaker_boost")


def _custom_profiles() -> dict:
    """Override JSON dei profili da .env (TTS_PROFILES_JSON). Mai eccezioni."""
    try:
        import config as _c
        raw = str(getattr(_c, "TTS_PROFILES_JSON", "") or "").strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        import json as _json
        data = _json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def model_capabilities(model_id: str | None) -> set[str]:
    """Chiavi voice_settings accettate dal modello (mai eccezioni)."""
    try:
        mid = str(model_id or "").strip()
    except Exception:
        mid = ""
    # Override esplicito da env.
    try:
        import config as _c
        raw = str(getattr(_c, "ELEVENLABS_MODEL_CAPABILITIES_JSON", "") or "").strip()
        if raw:
            import json as _json
            data = _json.loads(raw)
            if isinstance(data, dict) and mid in data and isinstance(data[mid], list):
                return {str(k) for k in data[mid]}
    except Exception:
        pass
    if mid in _MODEL_CAPABILITIES:
        return set(_MODEL_CAPABILITIES[mid])
    # Modello ignoto: prudente (solo i due universali).
    if not mid:
        return set(_FULL_SETTINGS)
    return {"stability", "similarity_boost"}


def build_voice_settings(
    niche: str | None = None,
    model_id: str | None = None,
) -> dict:
    """Costruisce le voice_settings (puro, testabile).

    - Base da config (TTS_STABILITY/SIMILARITY/STYLE/SPEED/SPEAKER_BOOST).
    - Override per nicchia (TTS_PROFILES + TTS_PROFILES_JSON).
    - Clamp: speed in [TTS_SPEED_MIN, TTS_SPEED_MAX], style in [0, 0.45].
    - Filtra per capacità del modello (style/speaker_boost non universali).
    """
    try:
        stability = _cfg_float("TTS_STABILITY", 0.5)
        similarity = _cfg_float("TTS_SIMILARITY", 0.75)
        style = _cfg_float("TTS_STYLE", 0.25)
        speed = _cfg_float("TTS_SPEED", 1.08)
        boost = _cfg_bool("TTS_USE_SPEAKER_BOOST", True)
    except Exception:
        stability, similarity, style, speed, boost = 0.5, 0.75, 0.25, 1.08, True
    # Profili per nicchia (custom JSON vince sui default).
    try:
        key = str(niche or "").strip().lower().replace("-", "_").replace(" ", "_")
        merged = dict(TTS_PROFILES)
        for k, v in _custom_profiles().items():
            if isinstance(v, dict):
                merged[str(k)] = v
        prof = merged.get(key)
        if isinstance(prof, dict):
            if "stability" in prof:
                stability = float(prof["stability"])
            if "style" in prof:
                style = float(prof["style"])
            if "speed" in prof:
                speed = float(prof["speed"])
            if "similarity_boost" in prof:
                similarity = float(prof["similarity_boost"])
            if "use_speaker_boost" in prof:
                boost = bool(prof["use_speaker_boost"])
    except (TypeError, ValueError):
        pass
    except Exception:
        pass
    # Clamp di sicurezza (speed valido 0.7-1.2; default [1.0, 1.15]).
    try:
        smin = _cfg_float("TTS_SPEED_MIN", 1.0)
        smax = _cfg_float("TTS_SPEED_MAX", 1.15)
        lo, hi = (min(smin, smax), max(smin, smax))
    except Exception:
        lo, hi = 1.0, 1.15
    try:
        speed = min(hi, max(lo, float(speed)))
    except (TypeError, ValueError):
        speed = 1.08
    try:
        style = min(0.45, max(0.0, float(style)))
    except (TypeError, ValueError):
        style = 0.25
    try:
        stability = min(1.0, max(0.0, float(stability)))
        similarity = min(1.0, max(0.0, float(similarity)))
    except (TypeError, ValueError):
        pass
    full = {
        "stability": stability,
        "similarity_boost": similarity,
        "style": style,
        "speed": speed,
        "use_speaker_boost": bool(boost),
    }
    try:
        caps = model_capabilities(model_id if model_id is not None else ELEVENLABS_MODEL_ID)
        return {k: v for k, v in full.items() if k in caps}
    except Exception:
        return {"stability": stability, "similarity_boost": similarity}


def downgrade_voice_settings(settings: dict) -> dict | None:
    """Livello inferiore di voice_settings dopo un 400/422 (puro).

    full (5 chiavi) → senza style/speaker_boost (3 chiavi) → solo i primi due.
    Ritorna None se già al minimo (il chiamante solleva TTSError).
    """
    try:
        keys = set(settings or {})
    except Exception:
        return None
    if "style" in keys or "use_speaker_boost" in keys:
        return {k: v for k, v in settings.items()
                if k in ("stability", "similarity_boost", "speed")}
    if "speed" in keys:
        return {k: v for k, v in settings.items()
                if k in ("stability", "similarity_boost")}
    return None


def _mask_key(key: str) -> str:
    """Maschera una chiave per i log (mostra solo inizio/fine)."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-2:]}"


def generate_audio(
    script_text: str,
    output_filename: str = "narration.mp3",
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
    niche: str | None = None,
) -> str:
    """
    Genera un file audio a partire dal testo dello script, usando ElevenLabs.

    Prova le chiavi in ELEVENLABS_API_KEYS in ordine finché una non ha
    successo (fallback automatico su quota esaurita / rate limit / chiave
    non valida / errori di rete o del server). La voce usata per ogni
    tentativo è risolta con config.get_elevenlabs_voice_id (voce singola
    oppure abbinamento 1:1 chiave<->voce).

    Args:
        script_text: il testo da convertire in voce.
        output_filename: nome del file audio da salvare in TEMP_DIR.
        on_attempt: callback opzionale (index_1based, totale, riuscita, dettaglio)
            invocata dopo ogni tentativo con una chiave, per mostrare il ciclo.

    Returns:
        Il percorso assoluto del file audio generato.

    Raises:
        TTSError: se mancano le chiavi, lo script è vuoto, la configurazione
            voci/chiavi è ambigua, la richiesta non è valida (400/422, e 404
            con voce unica: riprovare con un'altra chiave non aiuterebbe)
            oppure tutte le chiavi hanno fallito.
    """
    if not script_text or not script_text.strip():
        raise TTSError("Lo script è vuoto: niente da convertire in audio.")

    if not ELEVENLABS_API_KEYS:
        raise TTSError(
            "Mancano le ELEVENLABS_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env (puoi inserirne più di una separate da "
            "virgola per il fallback automatico)."
        )

    total = len(ELEVENLABS_API_KEYS)

    try:
        voices = [get_elevenlabs_voice_id(i, total) for i in range(total)]
    except ValueError as e:
        raise TTSError(str(e))

    # Se ogni chiave usa una voce diversa, anche un 404 (voce non trovata
    # su quell'account) può risolversi con la coppia chiave/voce successiva.
    # Con voce unica, invece, un 404 non si risolve cambiando chiave.
    retryable_status = set(_RETRYABLE_STATUS)
    if len(set(voices)) > 1:
        retryable_status.add(404)

    payload = {
        "text": script_text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": build_voice_settings(niche, ELEVENLABS_MODEL_ID),
    }
    params = {"output_format": ELEVENLABS_OUTPUT_FORMAT}

    failures: list[str] = []

    for index, (api_key, voice_id) in enumerate(zip(ELEVENLABS_API_KEYS, voices), start=1):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, json=payload, params=params, headers=headers, timeout=120)
        except requests.RequestException as e:
            # Errore di rete/timeout: potrebbe essere transitorio o legato
            # alla chiave, quindi si passa alla successiva.
            note = f"chiave {index}/{total} ({_mask_key(api_key)}): errore di rete: {e}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            continue

        if response.status_code == 200:
            if on_attempt is not None:
                on_attempt(index, total, True, f"chiave {index}/{total}: audio generato")
            output_path = os.path.join(TEMP_DIR, output_filename)
            with open(output_path, "wb") as f:
                f.write(response.content)
            return output_path

        detail = (
            f"Errore ElevenLabs ({response.status_code}) "
            f"[voce {voice_id}]: {response.text[:300]}"
        )

        if response.status_code in retryable_status:
            # Chiave non valida / quota esaurita / rate limit / voce non
            # trovata su quell'account (solo in modalità voci per-chiave) /
            # 5xx: si passa alla coppia chiave/voce successiva.
            note = f"chiave {index}/{total} ({_mask_key(api_key)}): {detail}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            continue

        # 400/422 con riferimento a voice_settings: il modello potrebbe non
        # accettare style/speed/speaker_boost → downgrade e UN solo retry con
        # la stessa chiave (mai fatale per questo motivo).
        if response.status_code in (400, 422):
            try:
                body_low = (response.text or "").lower()
            except Exception:
                body_low = ""
            if "voice_settings" in body_low or "voice setting" in body_low:
                lowered = downgrade_voice_settings(payload.get("voice_settings") or {})
                if lowered is not None:
                    try:
                        if on_attempt is not None:
                            on_attempt(index, total, False,
                                       f"chiave {index}/{total}: downgrade voice_settings "
                                       f"({sorted((payload.get('voice_settings') or {}).keys())} -> "
                                       f"{sorted(lowered.keys())})")
                    except Exception:
                        pass
                    payload = dict(payload)
                    payload["voice_settings"] = lowered
                    try:
                        response2 = requests.post(url, json=payload, params=params,
                                                  headers=headers, timeout=120)
                    except requests.RequestException as e2:
                        note = (f"chiave {index}/{total} ({_mask_key(api_key)}): "
                                f"errore di rete al retry: {e2}")
                        failures.append(note)
                        if on_attempt is not None:
                            on_attempt(index, total, False, note)
                        continue
                    if response2.status_code == 200:
                        if on_attempt is not None:
                            on_attempt(index, total, True,
                                       f"chiave {index}/{total}: audio generato (downgrade)")
                        output_path = os.path.join(TEMP_DIR, output_filename)
                        with open(output_path, "wb") as f:
                            f.write(response2.content)
                        return output_path
                    # Secondo livello di downgrade (solo stability+similarity).
                    lowered2 = downgrade_voice_settings(lowered)
                    if lowered2 is not None and response2.status_code in (400, 422):
                        payload["voice_settings"] = lowered2
                        try:
                            response3 = requests.post(url, json=payload, params=params,
                                                      headers=headers, timeout=120)
                        except requests.RequestException:
                            response3 = None
                        if response3 is not None and response3.status_code == 200:
                            if on_attempt is not None:
                                on_attempt(index, total, True,
                                           f"chiave {index}/{total}: audio generato (downgrade 2)")
                            output_path = os.path.join(TEMP_DIR, output_filename)
                            with open(output_path, "wb") as f:
                                f.write(response3.content)
                            return output_path
                        if response3 is not None:
                            detail = (
                                f"Errore ElevenLabs ({response3.status_code}) "
                                f"[voce {voice_id}]: {response3.text[:300]}"
                            )
                    else:
                        detail = (
                            f"Errore ElevenLabs ({response2.status_code}) "
                            f"[voce {voice_id}]: {response2.text[:300]}"
                        )

        # 400/404(voce unica)/422 (richiesta o configurazione non valida):
        # un'altra chiave non risolverebbe, fallimento immediato.
        raise TTSError(detail)

    raise TTSError(
        f"Tutte le {total} chiavi ElevenLabs hanno fallito. Dettagli: "
        + " | ".join(failures)
    )
