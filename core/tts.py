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


def _mask_key(key: str) -> str:
    """Maschera una chiave per i log (mostra solo inizio/fine)."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-2:]}"


def generate_audio(
    script_text: str,
    output_filename: str = "narration.mp3",
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
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
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
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

        # 400/404(voce unica)/422 (richiesta o configurazione non valida):
        # un'altra chiave non risolverebbe, fallimento immediato.
        raise TTSError(detail)

    raise TTSError(
        f"Tutte le {total} chiavi ElevenLabs hanno fallito. Dettagli: "
        + " | ".join(failures)
    )
