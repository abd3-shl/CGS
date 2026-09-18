"""
Semantic Typography Engine v1 — Analisi semantica e tagging LLM (Groq).

Due analisi:
  A. Rilevamento nicchia: lo script completo -> una di VALID_NICHES
     (vedi core/typography_presets.py). Fallback deterministico se LLM assente.
  B. Tagging parole (word-level): ogni chunk -> parole con categoria
     "base" | "impact" | "accent":
       - base:   parlato standard / congiunzioni / testo generico
       - impact: keyword ad alto valore, numeri, concetti chiave (es. SMETTI, RISULTATI)
       - accent: domande retoriche, citazioni, virgolettati, espressioni d'effetto

Formato output LLM per chunk (spec):
    {"chunk_index": 0, "words": [{"text": "Smetti di ", "type": "base"}, ...]}

I timestamp originali (STT + alignment) non vengono mai alterati: il tagging
riallinea i segmenti LLM alle parole timestampate con match normalizzato.
Se l'LLM fallisce, fallback euristico deterministico (mai bloccante).
"""

import json
import re
from collections.abc import Callable

from config import GROQ_API_KEYS, GROQ_LLM_MODEL
from core.typography_presets import (
    FALLBACK_NICHE,
    NICHE_DESCRIPTIONS,
    VALID_NICHES,
    list_niches_for_prompt,
    normalize_niche,
)


class TextTaggerError(Exception):
    """Errore nel tagging tipografico (input non valido)."""


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    from groq import Groq as _Groq
    client = _Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


def _heuristic_tagging(chunks: list[dict]) -> list[dict]:
    """Fallback euristico unificato (evita triplicazione codice, istantaneo)."""
    out: list[dict] = []
    for i, ch in enumerate(chunks):
        timed = (ch or {}).get("words") or [{"word": t} for t in str((ch or {}).get("text", "")).split()]
        out.append({
            "chunk_index": i,
            "words": [
                {"text": str(w.get("word", "")), "type": _heuristic_style(str(w.get("word", "")), str((ch or {}).get("text", "")))}
                for w in timed if str(w.get("word", "")).strip()
            ] or [{"text": str((ch or {}).get("text", "")), "type": "base"}],
        })
    return out


VALID_TYPES = ("base", "impact", "accent")


# ---------------------------------------------------------------------------
# A. Rilevamento nicchia
# ---------------------------------------------------------------------------

# Parole segnale per fallback euristico (italiano + inglese, lowercase).
_NICHE_KEYWORDS: dict[str, list[str]] = {
    "business_finance": [
        "soldi", "invest", "business", "finanza", "guadagn", "profitto", "fatturato",
        "marketing", "vendite", "clienti", "azienda", "startup", "capitale", "banca",
        "trading", "crypto", "money", "revenue", "strategy", "strategia",
    ],
    "tech_ai": [
        "intelligenza artificiale", "ai", "robot", "software", "codice", "coding",
        "algoritmo", "dati", "digital", "tecnolog", "computer", "app", "chatgpt",
        "machine learning", "automazione", "tech", "innovazione",
    ],
    "fitness_sport": [
        "palestra", "allenamento", "workout", "muscol", "proteine", "dieta",
        "cardio", "sport", "fitness", "corpo", "peso", "corsa", "calcio", "atleta",
    ],
    "lifestyle_vlog": [
        "vlog", "viaggio", "routine", "mattina", "moda", "bellezza", "trucco",
        "outfit", "giornata", "emozione", "lifestyle", "weekend", "casa",
    ],
    "educational": [
        "scuola", "lezione", "storia", "scienza", "spieg", "impara", "studio",
        "curiosit", "tutorial", "come funziona", "perché", "perche", "educazione",
        "universit", "esame",
    ],
    "dark_motivational": [
        "disciplina", "mentalit", "sacrificio", "successo", "fallimento", "dolore",
        "smetti", "svegliati", "nessuno", "lotta", "guerra", "vincere", "perdente",
        "motivazione", "mindset", "grind", "hustle",
    ],
}


def _heuristic_niche(script_text: str) -> str:
    """Fallback deterministico: conta le parole segnale per nicchia."""
    text = (script_text or "").lower()
    if not text.strip():
        return FALLBACK_NICHE
    scores: dict[str, int] = {}
    for niche, keywords in _NICHE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text:
                # Pesa le espressioni multi-parola (più specifiche).
                score += 2 if " " in kw else 1
        scores[niche] = score
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0:
        return FALLBACK_NICHE
    return best


def _parse_niche(content: str) -> tuple[str | None, float]:
    """Estrae (niche, confidence) dalla risposta LLM. (None, 0.0) se invalida."""
    text = (content or "").strip()
    if not text:
        return None, 0.0
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None, 0.0
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, 0.0
    if not isinstance(data, dict):
        return None, 0.0
    raw_niche = data.get("niche", data.get("category", data.get("label")))
    if not isinstance(raw_niche, str):
        return None, 0.0
    try:
        conf = float(data.get("confidence", data.get("score", 0.8)))
    except (TypeError, ValueError):
        conf = 0.8
    conf = max(0.0, min(1.0, conf))
    niche = normalize_niche(raw_niche)
    # Se l'LLM ha scritto una nicchia ignota, normalize torna il fallback:
    # in quel caso la confidence va azzerata per segnalare incertezza.
    if raw_niche.strip().lower().replace("-", "_").replace(" ", "_") not in VALID_NICHES \
            and niche == FALLBACK_NICHE:
        # Potrebbe essere un alias valido (es. "business"): ricontrolla.
        if normalize_niche(raw_niche) not in VALID_NICHES:
            return None, 0.0
    return niche, conf


def detect_niche(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
    min_confidence: float = 0.4,
) -> str:
    """Rileva la nicchia dello script (una di VALID_NICHES).

    Non solleva mai per errori API/validazione: in quel caso ritorna il
    fallback (euristico su parole segnale, poi FALLBACK_NICHE).
    Se la confidence LLM < min_confidence, usa il fallback euristico.
    """
    if not script_text or not script_text.strip():
        return FALLBACK_NICHE
    import os as _os2
    if _os2.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        return _heuristic_niche(script_text)
    if not GROQ_API_KEYS:
        if on_attempt is not None:
            try:
                on_attempt(0, 0, False, "nessuna GROQ_API_KEY: nicchia euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)

    snippet = script_text.strip().replace("\n", " ")
    if len(snippet) > 1500:
        snippet = snippet[:1500] + "..."
    niche_lines = "\n".join(
        f"- {n}: {NICHE_DESCRIPTIONS.get(n, '')}" for n in VALID_NICHES
    )
    system = (
        "Sei un analista che classifica script per video brevi in nicchie tipografiche. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Classifica lo script in UNA di queste nicchie:\n"
        f"{niche_lines}\n\n"
        f"NICCHIE VALIDE: {list_niches_for_prompt()}\n\n"
        "Rispondi SOLO con JSON: {\"niche\": \"<una di quelle valide>\", "
        "\"confidence\": 0.0-1.0, \"reason\": \"breve motivo\"}\n\n"
        f"SCRIPT:\n{snippet}"
    )

    total = len(GROQ_API_KEYS)
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
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            if on_attempt is not None:
                try:
                    on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
                except Exception:
                    pass
            content = None
            continue
        if on_attempt is not None:
            try:
                on_attempt(index, total, True, f"chiave {index}/{total}: nicchia ricevuta")
            except Exception:
                pass
        break

    if content is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "LLM nicchia fallito: uso euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)

    niche, conf = _parse_niche(content)
    if niche is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "JSON nicchia non valido: uso euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)
    if conf < min_confidence:
        heur = _heuristic_niche(script_text)
        if on_attempt is not None:
            try:
                on_attempt(total, total, True,
                           f"nicchia incerta ({niche} conf={conf:.2f}): uso euristica -> {heur}")
            except Exception:
                pass
        return heur
    return niche


# ---------------------------------------------------------------------------
# B. Tagging parole (word-level)
# ---------------------------------------------------------------------------

def _normalize_token(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (per riallineare LLM -> timing)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)


def _heuristic_style(word: str, chunk_text: str = "") -> str:
    """Stile euristico per singola parola (fallback quando l'LLM fallisce)."""
    raw = word or ""
    stripped = raw.strip()
    if not stripped:
        return "base"
    norm = _normalize_token(stripped)
    if not norm:
        return "base"
    # Numeri / percentuali / date -> impatto (dati ad alto valore).
    if re.search(r"\d", stripped):
        return "impact"
    # Tutto maiuscolo (3+ lettere) -> impatto.
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", stripped)
    if len(letters) >= 3 and letters.isupper():
        return "impact"
    # Virgolettati / domande / esclamazioni enfatiche -> accento.
    if '"' in chunk_text or '"' in chunk_text or "'" in chunk_text or "«" in chunk_text:
        if norm in _normalize_token(chunk_text).split():
            # Euristica grezza: se il chunk contiene virgolette, le parole
            # lunghe del chunk sono probabilmente la citazione.
            if len(norm) >= 4:
                return "accent"
    if stripped.endswith("?") or chunk_text.strip().endswith("?"):
        return "accent"
    # Parole enfatiche italiane/inglesi -> impatto.
    emphasis = {
        "smetti", "mai", "sempre", "tutti", "nessuno", "tutto", "niente",
        "segreto", "verità", "verita", "gratis", "soldi", "successo", "risultati",
        "risultato", "strategia", "errore", "errori", "stop", "attenzione",
        "incredibile", "impossibile", "garantito", "prova", "fallimento",
    }
    if norm in emphasis or (len(norm) >= 8 and norm not in {
        "perché", "perche", "quando", "quindi", "mentre", "anche", "della",
        "nella", "quello", "questo", "molto", "tanto",
    }):
        # Parole lunghe non-comuni -> probabile concetto chiave.
        if len(norm) >= 9:
            return "impact"
        if norm in emphasis:
            return "impact"
    return "base"


def _parse_tagged_response(content: str, n: int) -> list[dict] | None:
    """Parsa la risposta LLM in [{"chunk_index": i, "words": [{"text","type"}]}].

    Ritorna None se non valida (numero chunk errato, tipi ignoti, ecc.).
    Accetta sia array bare sia {"chunks": [...]} / {"tagged": [...]}.
    """
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        for key in ("chunks", "tagged", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return None
    if not isinstance(data, list):
        return None
    by_index: dict[int, dict] = {}
    unordered: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        ci = entry.get("chunk_index", entry.get("index"))
        try:
            ci_int = int(ci)
        except (TypeError, ValueError):
            unordered.append(entry)
            continue
        if 0 <= ci_int < n and ci_int not in by_index:
            by_index[ci_int] = entry
        else:
            unordered.append(entry)
    result: list[dict] = []
    it = iter(unordered)
    for i in range(n):
        if i in by_index:
            result.append(by_index[i])
        else:
            try:
                result.append(next(it))
            except StopIteration:
                return None
    # Valida e normalizza ogni voce.
    normalized: list[dict] = []
    for i, entry in enumerate(result):
        words = entry.get("words", entry.get("tokens"))
        if not isinstance(words, list) or not words:
            return None
        norm_words: list[dict] = []
        for w in words:
            if not isinstance(w, dict):
                return None
            t = w.get("text", w.get("word", ""))
            typ = str(w.get("type", w.get("style", "base"))).strip().lower()
            if typ not in VALID_TYPES:
                # Tolleranze per output LLM creativi.
                if typ in ("keyword", "highlight", "emphasis", "strong", "key"):
                    typ = "impact"
                elif typ in ("quote", "question", "italic", "handwritten", "citation"):
                    typ = "accent"
                else:
                    return None
            if not isinstance(t, str) or not t.strip():
                continue
            norm_words.append({"text": t, "type": typ})
        if not norm_words:
            return None
        normalized.append({"chunk_index": i, "words": norm_words})
    return normalized


def _split_tagged_into_tokens(tagged_words: list[dict]) -> list[tuple[str, str]]:
    """Appiattisce i segmenti LLM in [(token, type)] splittando sugli spazi."""
    out: list[tuple[str, str]] = []
    for seg in tagged_words:
        typ = seg.get("type", "base")
        for tok in str(seg.get("text", "")).split():
            if tok:
                out.append((tok, typ))
    return out


def _align_tags_to_timed_words(
    timed_words: list[dict],
    tagged_tokens: list[tuple[str, str]],
    chunk_text: str = "",
) -> list[dict]:
    """Riallinea i token taggati alle parole timestampate.

    Match sequenziale normalizzato (case-insensitive, punteggiatura ignorata):
    se il token LLM corrisponde alla parola timed, eredita il type; altrimenti
    fallback euristico per quella parola. I token extra LLM vengono ignorati,
    le parole timed senza match usano l'euristica. Non solleva mai.
    """
    styled: list[dict] = []
    ti = 0
    for w in timed_words:
        word_text = str(w.get("word", ""))
        norm = _normalize_token(word_text)
        style = None
        # Cerca il prossimo token LLM che matcha (finestra di 3 per tollerare
        # piccole divergenze: articoli fusi/split dall'LLM).
        for look in range(min(3, len(tagged_tokens) - ti)):
            tok, typ = tagged_tokens[ti + look]
            if _normalize_token(tok) == norm and norm:
                style = typ
                ti = ti + look + 1
                break
        if style is None:
            # Nessun match: se c'è ancora un token non consumato ma diverso,
            # consumalo comunque se siamo fuori sync di 1 (evita deriva totale)?
            # No: meglio euristica puntuale per non propagare errori.
            style = _heuristic_style(word_text, chunk_text)
        styled.append({
            "word": word_text,
            "start": float(w.get("start", 0.0)),
            "end": float(w.get("end", 0.0)),
            "style": style,
        })
    return styled


def tag_chunk_words(
    chunks: list[dict],
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Tagga ogni chunk in formato spec (senza timing).

    Returns:
        [{"chunk_index": i, "words": [{"text": str, "type": "base|impact|accent"}]}]
        Lungo quanto `chunks`. Non solleva mai: in caso di errore LLM usa
        l'euristica (un token per parola, stile euristico).
    """
    if not chunks:
        return []
    import os as _os
    if _os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        return _heuristic_tagging(chunks)
    if not GROQ_API_KEYS:
        return _heuristic_tagging(chunks)

    n = len(chunks)
    has_narrative = any(
        isinstance(ch, dict) and (ch or {}).get("narrative_role") in ("hook", "body", "cta")
        for ch in chunks
    )
    lines = []
    for i, ch in enumerate(chunks):
        text = str((ch or {}).get("text", "")).strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "..."
        if has_narrative and isinstance(ch, dict):
            role = str(ch.get("narrative_role", "body"))
            tag = {"hook": "HOOK", "body": "CORPO", "cta": "CTA"}.get(role, "CORPO")
            lines.append(f"{i} [{tag}]: {text}")
        else:
            lines.append(f"{i}: {text}")
    chunk_block = "\n".join(lines)

    system = (
        "Sei un motion graphics designer che marca le parole dei sottotitoli "
        "per video brevi. Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Per OGNI chunk, suddividi il testo in segmenti consecutivi e assegna a "
        "ciascuno UN tipo. NON alterare le parole (stesse parole, stesso ordine).\n"
        "TIPI:\n"
        '- \"base\": parlato standard, congiunzioni, articoli, testo generico.\n'
        '- \"impact\": keyword ad alto valore, numeri/dati, concetti chiave, '
        "parole enfatiche da urlare (es. SMETTI, RISULTATI, STRATEGIA, GRATIS).\n"
        '- \"accent\": domande retoriche, citazioni, parole tra virgolette, '
        "espressioni d'effetto.\n"
        "ESEMPIO: chunk \"Smetti di SPRECARE TEMPO con metodi inutili\" -> "
        '[{"text": \"Smetti di \", \"type\": \"base\"}, '
        '{"text": \"SPRECARE TEMPO\", \"type\": \"impact\"}, '
        '{"text": \" con metodi inutili\", \"type\": \"base\"}]\n'
        + (
            "REGOLE NARRATIVE (tag [HOOK]/[CORPO]/[CTA], ignorali nel testo):\n"
            "- [HOOK]: almeno una parola impact (la più forte d'apertura).\n"
            "- [CTA]: verbi d'azione (seguimi, commenta, clicca, scarica, scopri...) "
            "sempre impact.\n\n"
            if has_narrative else "\n"
        ) +
        f"CHUNK ({n} totali, 'indice: testo'):\n{chunk_block}\n\n"
        "Rispondi SOLO con un array JSON con ESATTAMENTE "
        f"{n} oggetti: "
        "'[{\"chunk_index\": 0, \"words\": [{\"text\": \"...\", \"type\": \"base\"}]}]'"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
    _dyn_max = max(512, min(4096, 256 + n * 64))
    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=_dyn_max,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            if on_attempt is not None:
                try:
                    on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
                except Exception:
                    pass
            content = None
            continue
        if on_attempt is not None:
            try:
                on_attempt(index, total, True, f"chiave {index}/{total}: tagging ricevuto")
            except Exception:
                pass
        break

    if content is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "LLM tagging fallito: uso euristica")
            except Exception:
                pass
        return _heuristic_tagging(chunks)

    parsed = _parse_tagged_response(content, n)
    if parsed is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "JSON tagging non valido: uso euristica")
            except Exception:
                pass
        return _heuristic_tagging(chunks)
    return parsed


def enrich_chunks_with_typography(
    chunks: list[dict],
    script_text: str = "",
    niche: str | None = None,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> tuple[str, list[dict]]:
    """Pipeline completa: rileva nicchia (se None) + tagga + riallinea timing.

    Args:
        chunks: chunk con "text"/"start"/"end"/"words" (da emphasis grouping).
        script_text: script originale (per il rilevamento nicchia).
        niche: nicchia forzata (se None, rilevata da script_text).
        on_attempt: callback logging (idx, totale, ok, dettaglio).

    Returns:
        (niche, enriched): enriched è la lista chunk con in più
        "typography_niche" e "styled_words" =
        [{"word","start","end","style","display"}] dove display è il testo
        da disegnare (impact -> UPPERCASE se il preset lo richiede).
        Non solleva mai per errori LLM (fallback euristici).
    """
    if not chunks:
        resolved = normalize_niche(niche) if niche else detect_niche(script_text or "", on_attempt)
        return resolved, []
    resolved = normalize_niche(niche) if niche else detect_niche(script_text or "", on_attempt)
    tagged = tag_chunk_words(chunks, on_attempt)
    try:
        from core.typography_presets import get_preset
        preset = get_preset(resolved)
        uppercase_impact = bool(preset.get("impact_uppercase", True))
    except Exception:
        uppercase_impact = True

    enriched: list[dict] = []
    for i, ch in enumerate(chunks):
        base = dict(ch or {})
        timed = base.get("words")
        if not timed:
            text = str(base.get("text", "")).split()
            start = float(base.get("start", 0.0))
            end = float(base.get("end", start))
            if end <= start:
                end = start + 0.3 * max(1, len(text))
            span = (end - start) / max(1, len(text))
            timed = [
                {"word": w, "start": start + span * k, "end": start + span * (k + 1)}
                for k, w in enumerate(text)
            ]
        tagged_entry = tagged[i] if i < len(tagged) else None
        if tagged_entry is not None:
            tokens = _split_tagged_into_tokens(tagged_entry.get("words", []))
            styled = _align_tags_to_timed_words(timed, tokens, str(base.get("text", "")))
        else:
            styled = [
                {"word": str(w.get("word", "")), "start": float(w.get("start", 0.0)),
                 "end": float(w.get("end", 0.0)),
                 "style": _heuristic_style(str(w.get("word", "")), str(base.get("text", "")))}
                for w in timed
            ]
        # Display: impact -> uppercase (se preset), altri invariati.
        for s in styled:
            if s.get("style") == "impact" and uppercase_impact:
                s["display"] = str(s.get("word", "")).upper()
            else:
                s["display"] = str(s.get("word", ""))
        # Boost narrativo: hook sempre d'impatto, CTA con verbi d'azione
        # impact (stabilita' visiva del finale). Corpo invariato.
        try:
            role = (base.get("narrative_role")
                    if isinstance(base, dict) else None)
            if role in ("hook", "cta"):
                from core.narrative_structure import boost_typography_styles
                styled = boost_typography_styles(
                    styled, role, str(base.get("text", "")), uppercase_impact
                )
        except Exception:
            pass
        base["typography_niche"] = resolved
        base["styled_words"] = styled
        enriched.append(base)
    return resolved, enriched
