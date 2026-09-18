"""
Raggruppamento sottotitoli per enfasi: chunk brevi da 2-3 parole decisi
dall'LLM Groq (stesso modello/client di core/keywords.py, con rotazione
chiavi e failover) in base a enfasi/significato della frase.

Vincolo di sicurezza: l'LLM riceve solo parole indicizzate e restituisce
SOLO gli indici di taglio (ultima parola di ogni gruppo). Testo e timestamp
(prodotti da STT + alignment) non vengono mai alterati. Se la risposta è
invalida o le chiavi falliscono, si usa un fallback deterministico a
blocchi di 2 (3 se la terza è "leggera").
"""

import json
import re
from collections.abc import Callable

from groq import Groq

from config import (
    GROQ_API_KEYS,
    GROQ_LLM_MODEL,
    EMPHASIS_MAX_WORDS_PER_CHUNK,
    EMPHASIS_MIN_WORDS_PER_CHUNK,
)
from core.subtitle_grouping import _WEAK_TRAILING_WORDS, _STRONG_PUNCT
from core.keywords import normalize_word


class EmphasisGroupingError(Exception):
    """Errore irrecuperabile di rete/chiave nel grouping per enfasi."""
    pass


def _ends_strong(word: str) -> bool:
    stripped = word.strip()
    return any(stripped.endswith(p) for p in _STRONG_PUNCT)


def _is_weak(word: str) -> bool:
    return normalize_word(word) in _WEAK_TRAILING_WORDS


def _make_chunk(group: list[dict]) -> dict:
    """Crea un chunk con testo/timing + parole individuali timestampate.

    La chiave "words" (lista di {"word", "start", "end"}) serve alla Fase 3
    (animazioni per-parola in core/text_animator.py): ogni parola entra
    al suo timestamp individuale, il layout resta fisso.
    """
    return {
        "text": " ".join(w["word"].strip() for w in group),
        "start": group[0]["start"],
        "end": group[-1]["end"],
        "words": [
            {"word": w["word"], "start": w["start"], "end": w["end"]}
            for w in group
        ],
    }


def _deterministic_fallback(words: list[dict]) -> list[dict]:
    """Blocchi di 2 parole (3 se la terza è leggera), taglio su punteggiatura forte."""
    chunks: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        group = [words[i]]
        if i + 1 < n and not _ends_strong(words[i]["word"]):
            group.append(words[i + 1])
            if (
                len(group) == 2
                and i + 2 < n
                and not _ends_strong(words[i + 1]["word"])
                and _is_weak(words[i + 2]["word"])
            ):
                group.append(words[i + 2])
        chunks.append(_make_chunk(group))
        i += len(group)
    return chunks


def _validate_cuts(cuts, n: int) -> bool:
    """Verifica indici interi crescenti in [0, n-1], ultimo = n-1, gruppi 1-3."""
    if not isinstance(cuts, list) or not cuts:
        return False
    if any(not isinstance(c, int) or isinstance(c, bool) for c in cuts):
        return False
    if any(c < 0 or c >= n for c in cuts):
        return False
    if len(set(cuts)) != len(cuts) or cuts != sorted(cuts):
        return False
    if cuts[-1] != n - 1:
        return False
    prev = -1
    for c in cuts:
        size = c - prev
        if size < EMPHASIS_MIN_WORDS_PER_CHUNK or size > EMPHASIS_MAX_WORDS_PER_CHUNK:
            return False
        prev = c
    return True


def _parse_cuts(content: str) -> list | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("cut_indices")


def group_words_by_emphasis(
    words: list[dict],
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Raggruppa le parole timestampate in chunk brevi (2-3 parole) per enfasi.

    Stesso formato di output di subtitle_grouping.group_words_into_subtitles,
    piu' la chiave "words" con le singole parole timestampate
    ({"word", "start", "end"}) per le animazioni per-parola (Fase 3).
    Non solleva mai per errori API/validazione: usa il fallback deterministico.
    """
    if not words:
        return []

    if not GROQ_API_KEYS:
        return _deterministic_fallback(words)

    n = len(words)
    system = (
        "Sei un assistente che divide frasi in brevi gruppi di parole per sottotitoli "
        "video. Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Leggi l'elenco di parole in ordine (l'indice e la posizione nell'array, "
        "0-based) e decidi dove tagliare in base a enfasi e significato. Regole:\n"
        f"1. Ogni gruppo deve avere minimo {EMPHASIS_MIN_WORDS_PER_CHUNK} e massimo "
        f"{EMPHASIS_MAX_WORDS_PER_CHUNK} parole: preferisci gruppi da 2-3 parole.\n"
        "2. Un gruppo da 3 parole va bene quando la terza e un elemento leggero "
        "(articolo, preposizione, congiunzione breve) che si appoggia alle prime due; "
        "non iniziare mai un nuovo gruppo con una parola leggera isolata (di, il, che) "
        "se puo restare attaccata al gruppo precedente.\n"
        "3. La punteggiatura forte (. ! ? ... : ;) e quasi sempre un taglio obbligato: "
        "se una parola termina cosi, quel punto DEVE essere un taglio.\n"
        "Restituisci SOLO: {\"cut_indices\": [...]} con gli indici (0-based) "
        "dell'ULTIMA parola di ogni gruppo, in ordine crescente; l'ultimo indice "
        "deve essere quello dell'ultima parola. Esempio per 10 parole in "
        "[0-1][2-3-4][5-6][7-8-9]: {\"cut_indices\": [1, 4, 6, 9]}\n\n"
        f"PAROLE: {json.dumps({'words': [w['word'] for w in words]}, ensure_ascii=False)}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
    succeeded_at = 0

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
        except Exception as e:
            if on_attempt is not None:
                on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
            continue
        succeeded_at = index
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: tagli ricevuti")
        break

    cuts = _parse_cuts(content) if content is not None else None
    if cuts is None or not _validate_cuts(cuts, n):
        if on_attempt is not None:
            on_attempt(succeeded_at, total, False, "tagli LLM invalidi: uso raggruppamento deterministico")
        return _deterministic_fallback(words)

    chunks: list[dict] = []
    prev = 0
    for cut in cuts:
        chunks.append(_make_chunk(words[prev:cut + 1]))
        prev = cut + 1
    return chunks
