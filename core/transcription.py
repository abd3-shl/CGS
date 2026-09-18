"""
Modulo di trascrizione: usa l'API Whisper di Groq per trascrivere l'audio
generato, ottenendo i timestamp a livello di singola parola.

Supporta più API key con fallback automatico: le chiavi in
config.GROQ_API_KEYS vengono provate in ordine e alla prima che fallisce
per motivi legati alla chiave/servizio (chiave non valida, quota esaurita,
rate limit, errore di rete o 5xx) si passa alla successiva.
"""

import os
from collections.abc import Callable

from groq import Groq

from config import GROQ_API_KEYS, GROQ_WHISPER_MODEL


class TranscriptionError(Exception):
    """Errore generico durante la trascrizione."""
    pass


# Sottostringhe (case-insensitive) che indicano un problema legato alla
# singola chiave o a un limite temporaneo -> vale la pena provare la
# chiave successiva.
_RETRYABLE_HINTS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "insufficient",
    "credit",
    "balance",
    "billing",
    "expired",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "authentication",
    "permission",
    "forbidden",
    "overload",
    "timeout",
    "timed out",
    "connection",
    "unavailable",
    "server error",
    "internal error",
    "401",
    "402",
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def _mask_key(key: str) -> str:
    """Maschera una chiave per i log (mostra solo inizio/fine)."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-2:]}"


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    client = Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


def _is_retryable_with_next_key(error: Exception) -> bool:
    """Decide se ha senso riprovare con la chiave successiva.

    Ritorna False solo per errori chiaramente indipendenti dalla chiave
    (es. modello inesistente 400/404, formato audio non valido 422):
    in quel caso un'altra chiave fallirebbe allo stesso modo.
    In caso di dubbio ritorna True (meglio un tentativo in più che
    bloccare la pipeline).
    """
    status = getattr(error, "status_code", None)
    if status in (400, 404, 422):
        message = str(error).lower()
        if not any(h in message for h in _RETRYABLE_HINTS):
            return False
    return True


def transcribe_audio(
    audio_path: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """
    Trascrive un file audio e restituisce la lista di parole con i relativi
    timestamp (inizio/fine in secondi).

    Prova le chiavi in GROQ_API_KEYS in ordine finché una non ha successo
    (fallback automatico su quota esaurita / rate limit / chiave non valida
    / errori di rete o del server).

    Args:
        audio_path: percorso del file audio (es. .mp3) da trascrivere.
        on_attempt: callback opzionale (index_1based, totale, riuscita, dettaglio)
            invocata dopo ogni tentativo con una chiave, per mostrare il ciclo.

    Returns:
        Lista di dict del tipo:
        [{"word": "Ciao", "start": 0.12, "end": 0.45}, ...]

    Raises:
        TranscriptionError: se mancano le chiavi, il file audio non esiste,
            la richiesta non è valida oppure tutte le chiavi hanno fallito.
    """
    if not GROQ_API_KEYS:
        raise TranscriptionError(
            "Mancano le GROQ_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env (puoi inserirne più di una separate da "
            "virgola per il fallback automatico)."
        )

    if not audio_path or not os.path.isfile(audio_path):
        raise TranscriptionError(f"File audio non trovato: {audio_path}")

    total = len(GROQ_API_KEYS)
    failures: list[str] = []
    transcription = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        client = _get_groq_client(api_key)

        try:
            with open(audio_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=audio_file,
                    model=GROQ_WHISPER_MODEL,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
        except Exception as e:
            detail = f"chiave {index}/{total} ({_mask_key(api_key)}): {e}"
            failures.append(detail)
            if on_attempt is not None:
                on_attempt(index, total, False, detail)
            if index < total and _is_retryable_with_next_key(e):
                # Problema legato alla chiave/servizio: si passa alla successiva.
                continue
            if index < total:
                # Errore non legato alla chiave (es. modello inesistente):
                # un'altra chiave fallirebbe allo stesso modo, stop immediato.
                raise TranscriptionError(
                    f"Errore durante la trascrizione Groq ({detail})"
                )
            raise TranscriptionError(
                f"Tutte le {total} chiavi Groq hanno fallito. Dettagli: "
                + " | ".join(failures)
            )
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: trascrizione riuscita")
        break

    words = getattr(transcription, "words", None)
    if not words:
        raise TranscriptionError(
            "La trascrizione non ha restituito timestamp a livello di parola. "
            "Verifica che il modello supporti 'timestamp_granularities=word'."
        )

    result = []
    for w in words:
        # 'w' può essere un dict o un oggetto, gestiamo entrambi i casi
        if isinstance(w, dict):
            result.append({"word": w["word"], "start": w["start"], "end": w["end"]})
        else:
            result.append({"word": w.word, "start": w.start, "end": w.end})

    return result
