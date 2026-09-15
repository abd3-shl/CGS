"""
Modulo di raggruppamento sottotitoli.

Prende la lista di parole con timestamp (output di transcription.py) e le
raggruppa in "chunk" leggibili: non parola-per-parola, non frase intera,
ma gruppi di senso che rispettano la punteggiatura e la lunghezza massima.

Regole di raggruppamento:
- Un chunk si chiude quando si raggiunge un segno di punteggiatura forte
  (. ! ? ... : ;) -> fine naturale di un pensiero.
- Un chunk si chiude anche se supera SUBTITLE_MAX_CHARS o SUBTITLE_MAX_WORDS,
  ma si cerca di chiuderlo alla virgola più vicina o comunque dopo una
  parola "intera", mai spezzando articoli/preposizioni dal loro nome
  (es. non lasciare "di" da solo a fine chunk).
"""

from config import SUBTITLE_MAX_CHARS, SUBTITLE_MAX_WORDS

# Se un chunk risulta più corto di questa soglia (in caratteri) dopo il
# raggruppamento iniziale, si prova a fonderlo con il chunk adiacente più
# piccolo, purché il risultato non superi il limite massimo.
_MIN_CHUNK_CHARS = 12

# Parole che, se possibile, non dovrebbero rimanere isolate a fine chunk
# (si preferisce spingerle nel chunk successivo insieme alla parola seguente)
_WEAK_TRAILING_WORDS = {
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno",
    "e", "o", "ma", "che", "non", "si", "mi", "ti", "ci",
    "del", "della", "dei", "delle", "dello", "al", "allo", "alla",
}

_STRONG_PUNCT = {".", "!", "?", "...", ":", ";"}
_SOFT_PUNCT = {","}


def _clean_word(word: str) -> str:
    return word.strip()


def _ends_with_punct(word: str, punct_set: set) -> bool:
    stripped = word.strip()
    return any(stripped.endswith(p) for p in punct_set)


def group_words_into_subtitles(words: list[dict]) -> list[dict]:
    """
    Raggruppa la lista di parole (con start/end) in chunk di sottotitoli.

    Args:
        words: lista di dict {"word": str, "start": float, "end": float}

    Returns:
        Lista di dict {"text": str, "start": float, "end": float}
        pronta per essere renderizzata come sottotitolo.
    """
    if not words:
        return []

    chunks = []
    current_words = []

    def flush_chunk():
        if not current_words:
            return
        text = " ".join(_clean_word(w["word"]) for w in current_words)
        start = current_words[0]["start"]
        end = current_words[-1]["end"]
        chunks.append({"text": text, "start": start, "end": end})

    i = 0
    n = len(words)

    while i < n:
        w = words[i]
        current_words.append(w)

        current_text = " ".join(_clean_word(cw["word"]) for cw in current_words)
        char_count = len(current_text)
        word_count = len(current_words)

        is_strong_end = _ends_with_punct(w["word"], _STRONG_PUNCT)
        is_soft_end = _ends_with_punct(w["word"], _SOFT_PUNCT)
        over_limit = char_count >= SUBTITLE_MAX_CHARS or word_count >= SUBTITLE_MAX_WORDS

        should_close = False

        if is_strong_end:
            # Fine naturale di una frase: chiudi sempre.
            should_close = True
        elif over_limit:
            # Abbiamo superato il limite: cerchiamo il punto migliore per chiudere.
            last_word_clean = _clean_word(w["word"]).lower().strip(".,!?;:")
            if is_soft_end:
                # Siamo su una virgola ed è già oltre il limite: ottimo punto di chiusura.
                should_close = True
            elif last_word_clean in _WEAK_TRAILING_WORDS and i + 1 < n:
                # Non chiudere qui: questa parola "debole" deve stare
                # insieme alla prossima. Continuiamo ad aggiungere.
                should_close = False
            else:
                should_close = True

        if should_close:
            flush_chunk()
            current_words = []

        i += 1

    # Eventuali parole rimaste in coda
    flush_chunk()

    return _merge_short_chunks(chunks)


def _merge_short_chunks(chunks: list[dict]) -> list[dict]:
    """
    Passata di post-processing: fonde i chunk troppo corti (es. una singola
    parola rimasta isolata dopo un punto) con il chunk precedente, se il
    risultato combinato non supera la lunghezza massima consentita.
    """
    if len(chunks) <= 1:
        return chunks

    merged = [chunks[0]]

    for chunk in chunks[1:]:
        prev = merged[-1]
        combined_text = f"{prev['text']} {chunk['text']}"

        is_prev_short = len(prev["text"]) < _MIN_CHUNK_CHARS
        is_current_short = len(chunk["text"]) < _MIN_CHUNK_CHARS
        fits_limit = len(combined_text) <= SUBTITLE_MAX_CHARS + 15  # piccolo margine

        if (is_prev_short or is_current_short) and fits_limit:
            merged[-1] = {
                "text": combined_text,
                "start": prev["start"],
                "end": chunk["end"],
            }
        else:
            merged.append(chunk)

    return merged
