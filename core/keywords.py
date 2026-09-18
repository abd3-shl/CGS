"""
Estrazione delle parole chiave dallo script tramite LLM Groq
(modello `openai/gpt-oss-120b` via Chat Completions, cfr.
https://console.groq.com/docs/text-chat).

Le keyword vengono evidenziate nei sottotitoli con un colore dedicato
(uno per parola, deterministico, mai giallo). Per evitare ammassi:
al massimo KEYWORDS_MAX keyword, scelte in ordine di importanza e
distanziate di almeno KEYWORDS_MIN_GAP parole nel testo.
"""

import hashlib
import json
import re
from collections.abc import Callable

from PIL.ImageColor import getrgb
from groq import Groq

from config import GROQ_API_KEYS, GROQ_LLM_MODEL, KEYWORDS_MAX, KEYWORDS_MIN_GAP


class KeywordError(Exception):
    """Errore durante l'estrazione delle parole chiave."""
    pass


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    client = Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


# Palette premium in hex ("#RRGGBB", mai neon/arcobaleno): usata come default
# e come integrazione per core/theme.py (importata come _FALLBACK_PALETTE_HEX).
# Toni smorzati e armonici su sfondi scuri (ori/sky/lavanda/rosa/menta).
_FALLBACK_PALETTE_HEX: list[str] = [
    "#D4AF37",  # oro smorzato (hero premium)
    "#7DD3FC",  # sky soft
    "#A78BFA",  # lavanda
    "#FF8FA3",  # rosa soft
    "#00E5FF",  # ciano tech
    "#34D399",  # menta
    "#FFD166",  # oro caldo chiaro
    "#F5D67B",  # oro tint
]


def _hex_to_rgba(hex_color: str) -> tuple:
    r, g, b = getrgb(hex_color)
    return (r, g, b, 255)


# Palette RGBA derivata (mantenuta per retrocompatibilità).
KEYWORD_PALETTE: list[tuple] = [_hex_to_rgba(h) for h in _FALLBACK_PALETTE_HEX]


def normalize_word(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (per il match nei sottotitoli)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", word.lower(), flags=re.UNICODE)


def color_for_keyword(word: str, palette: list[tuple] | None = None) -> tuple:
    """Colore deterministico in base alla parola (stessa parola = stesso colore)."""
    pal = palette or KEYWORD_PALETTE
    digest = hashlib.md5(word.encode("utf-8")).hexdigest()
    return pal[int(digest, 16) % len(pal)]


def _parse_keywords(content: str) -> list[str]:
    """Estrae la lista di keyword da una risposta JSON (robusto a fence markdown)."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    items = data.get("keywords", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    seen: list[str] = []
    for item in items:
        if not isinstance(item, str) or " " in item.strip():
            continue  # solo singole parole
        norm = normalize_word(item)
        if norm and norm not in seen:
            seen.append(norm)
    return seen


def _spread_keywords(candidates: list[str], script_words: list[str], target: int) -> list[str]:
    """Seleziona le keyword in ordine di importanza imponendo la distanza minima.

    Scorre i candidati (già ordinati per importanza dall'LLM) e accetta una
    parola solo se la sua prima occorrenza dista almeno `gap` parole da quelle
    già accettate: così le più importanti vincono e restano distribuite.
    """
    positions: dict[str, int] = {}
    for i, w in enumerate(script_words):
        positions.setdefault(normalize_word(w), i)  # prima occorrenza
    gap = max(KEYWORDS_MIN_GAP, len(script_words) // max(target, 1) // 2)
    accepted: list[str] = []
    accepted_pos: list[int] = []
    for cand in candidates:
        if len(accepted) >= target:
            break
        pos = positions.get(cand)
        if pos is None:
            continue  # parola non presente nello script, scarta
        if all(abs(pos - p) >= gap for p in accepted_pos):
            accepted.append(cand)
            accepted_pos.append(pos)
    return accepted


def extract_keywords(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
    keyword_palette_hex: list[str] | None = None,
) -> dict[str, tuple]:
    """Estrae le parole chiave dallo script: {parola_normalizzata: colore_RGBA}.

    Usa `GROQ_LLM_MODEL` con rotazione delle chiavi in GROQ_API_KEYS.

    Args:
        keyword_palette_hex: palette hex dal tema dinamico (core/theme.py);
            se assente si usa la palette storica.
    """
    script_words = script_text.split()
    if not script_words:
        raise KeywordError("Script vuoto: nessuna parola chiave da estrarre.")

    if not GROQ_API_KEYS:
        raise KeywordError(
            "Mancano le GROQ_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env."
        )

    target = max(3, min(KEYWORDS_MAX, len(script_words) // 30))

    system = (
        "Sei un assistente che estrae parole chiave da uno script per video brevi. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        f"Estrai al massimo {target} parole chiave SINGOLE (una parola ciascuna, "
        "esattamente come appaiono nel testo) dal seguente script. Scegli le parole "
        "più importanti e significative, distribuite uniformemente in tutto il testo "
        "(inizio, centro e fine, non concentrate in un solo punto), in ordine di "
        "importanza decrescente. Rispondi SOLO con: {\"keywords\": [\"parola1\", ...]}\n\n"
        f"SCRIPT:\n{script_text}"
    )

    total = len(GROQ_API_KEYS)
    failures: list[str] = []
    content: str | None = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=512,  # l'SDK groq installato usa max_tokens (non max_completion_tokens)
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            note = f"chiave {index}/{total}: {e}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            content = None
            continue
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: keyword estratte")
        break

    if content is None:
        raise KeywordError(
            f"Tutte le {total} chiavi Groq hanno fallito. Dettagli: " + " | ".join(failures)
        )

    candidates = _parse_keywords(content)
    selected = _spread_keywords(candidates, script_words, target)
    try:
        palette = (
            [_hex_to_rgba(h) for h in keyword_palette_hex]
            if keyword_palette_hex
            else KEYWORD_PALETTE
        )
    except ValueError:
        palette = KEYWORD_PALETTE  # hex non validi: palette storica
    return {word: color_for_keyword(word, palette) for word in selected}
