"""
Motore struttura narrativa: hook / corpo a beat / CTA-outro.

Ogni video viene letto come struttura in 3 atti, ognuno con tecniche dedicate:

- HOOK (prime 1-3 caption): deve fermare lo scroll. Tecniche dedicate:
  posa 1 assertiva + punch-in sul climax, tagging impact potenziato,
  entrata più scattante (×0.7) e pop più marcato (0.55 → 1.0).
- CORPO (a beat): ogni frase/pensiero è un beat; dentro il beat il personaggio
  è BLOCCATO sulla stessa identità (niente jitter ogni 2 parole), cambia solo
  ai confini di beat con slide pulita. Pose per tono: domande → 5 (split),
  dati/numeri → 4 (split, indica), resto → 2 (aperta).
- CTA/outro (ultime caption): finale STABILE. CTA forte (verbi d'azione:
  seguimi/commenta/clicca...) → "card" persistente: il messaggio completo resta
  fisso e si illumina parola per parola (karaoke), personaggio bloccato
  (posa 3, centro), un'unica dissolvenza finale. Outro debole (senza segnali)
  → chunk bloccati su posa 2 neutra, stessa stabilità senza card.

Tutto deterministico (posizione + punteggiatura + parole-segnale, mai LLM):
la stabilità richiede regole, non varianza. Non solleva mai: in caso di input
degeneri assegna ruoli sicuri (tutto corpo) e la pipeline prosegue piatta.
I ruoli vivono SUI chunk (chiavi narrative_*): i moduli a valle
(character_selector, text_tagger, text_animator) li leggono senza cambi firma.
"""

import re
from collections.abc import Callable

try:
    from core.subtitle_grouping import _WEAK_TRAILING_WORDS as _NARR_WEAK_WORDS
except Exception:
    _NARR_WEAK_WORDS = frozenset()

from config import (
    NARRATIVE_CTA_CARD,
    NARRATIVE_CTA_CARD_MAX_WORDS,
    NARRATIVE_CTA_MAX_CHUNKS,
    NARRATIVE_ENABLED,
    NARRATIVE_HOOK_ENTRY_MULT,
    NARRATIVE_HOOK_MAX_CHUNKS,
    NARRATIVE_HOOK_POP_FROM,
)

HOOK = "hook"
BODY = "body"
CTA = "cta"

# Segnali CTA (sottostringhe, lowercase, IT + EN): se un chunk li contiene,
# probabilmente è call-to-action. Copre follow, commenti, link/bio, download,
# acquisti, lead-magnet e imperativi di ingaggio.
_CTA_CUES: frozenset[str] = frozenset({
    "segui", "follow", "iscriv", "subscribe", "commenta", "commento",
    "link", "bio", "clicca", "click", "scarica", "download", "prova",
    "gratis", "free", "condividi", "share", "salva", "save", "like",
    "scopri", "inizia", "compra", "acquista", "ordina", "prenota",
    "chiama", "visita", "sito", "corso", "guida", "pdf", "checklist",
    "webinar", "sconto", "offerta", "promo", "dm", "direct",
    "scrivimi", "mandami", "tap", "swipe", "scorri",
})

# Verbi d'azione CTA (parola intera normalizzata): nel tagging CTA diventano
# impact anche se il tagger generico li lascerebbe base.
_CTA_ACTION_VERBS: frozenset[str] = frozenset({
    "segui", "seguimi", "iscriviti", "commenta", "clicca", "scarica",
    "prova", "condividi", "salva", "scopri", "inizia", "compra",
    "acquista", "scrivimi", "mandami", "guarda", "leggi", "ascolta",
    "follow", "subscribe", "comment", "click", "download", "share",
    "save", "try", "start", "shop", "buy",
})

# Chiusura di frase/pensiero (confine di beat nel corpo).
_STRONG_END = (".", "!", "?", "…", ":", ";")


def _norm_word(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (match cue robusto)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)


def _chunk_text(chunk: dict) -> str:
    try:
        return str((chunk or {}).get("text", "") or "")
    except Exception:
        return ""


def _has_cta_cue(text: str) -> bool:
    low = (text or "").lower()
    return any(cue in low for cue in _CTA_CUES)


def _ends_sentence(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith("..."):
        return True
    return s.endswith(_STRONG_END)


def _detect_cta(chunks: list[dict]) -> tuple[list[int], str]:
    """Range CTA: sequenza finale con segnali (forte) o ultimo chunk (outro debole).

    Returns:
        (indici_cta, forza): forza in {"strong", "soft", "none"}.
    """
    n = len(chunks)
    if n <= 0:
        return [], "none"
    try:
        max_c = max(1, int(NARRATIVE_CTA_MAX_CHUNKS))
    except Exception:
        max_c = 4
    run: list[int] = []
    for i in range(n - 1, max(-1, n - 1 - max_c), -1):
        if _has_cta_cue(_chunk_text(chunks[i])):
            run.append(i)
        else:
            break
    if run:
        return sorted(run), "strong"
    # Outro debole: stabilizza comunque il finale (posa neutra bloccata).
    if n >= 3:
        return [n - 1], "soft"
    return [], "none"


def _detect_hook(chunks: list[dict], cta_start: int | None) -> list[int]:
    """Hook: prima frase entro le prime N caption (mai dentro la CTA)."""
    n = len(chunks)
    if n <= 0:
        return []
    try:
        max_h = max(1, int(NARRATIVE_HOOK_MAX_CHUNKS))
    except Exception:
        max_h = 3
    limit = n if cta_start is None else max(0, min(n, cta_start))
    limit = min(limit, max_h)
    if limit <= 0:
        return []
    for i in range(limit):
        if _ends_sentence(_chunk_text(chunks[i])):
            return list(range(i + 1))
    # Nessuna frase chiusa: 1 chunk se brevissimo, altrimenti 2.
    size = 1 if n <= 3 else min(2, limit)
    return list(range(size))


def _split_body_beats(body_idx: list[int], chunks: list[dict]) -> list[list[int]]:
    """Divide il corpo in beat ai confini di frase; fonde i beat minuscoli."""
    if not body_idx:
        return []
    beats: list[list[int]] = []
    current: list[int] = []
    for i in body_idx:
        current.append(i)
        if _ends_sentence(_chunk_text(chunks[i])):
            beats.append(current)
            current = []
    if current:
        beats.append(current)
    # Fonde i beat da 1 chunk col successivo (o col precedente se ultimo).
    merged: list[list[int]] = []
    k = 0
    while k < len(beats):
        if len(beats[k]) < 2 and len(beats) > 1:
            if k + 1 < len(beats):
                merged.append(beats[k] + beats[k + 1])
                k += 2
                continue
            merged[-1] = merged[-1] + beats[k]
            k += 1
            continue
        merged.append(beats[k])
        k += 1
    return merged or ([list(body_idx)] if body_idx else [])


def beat_tone(beat_chunks: list[dict]) -> str:
    """Tono di un beat: question | data | key | explainer (per posa/layout)."""
    text = " ".join(_chunk_text(c) for c in beat_chunks)
    if "?" in text:
        return "question"
    if re.search(r"\d", text):
        return "data"
    if "!" in text or _has_cta_cue(text):
        return "key"
    return "explainer"


def _function_word(word_norm: str) -> bool:
    """Vero per articoli/preposizioni/congiunzioni (mai impact)."""
    weak = _NARR_WEAK_WORDS
    extra = {
        "che", "non", "come", "quando", "dove", "perche", "perché", "quindi",
        "mentre", "anche", "molto", "tanto", "questo", "quello", "questa",
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on",
        "for", "with", "you", "your", "quest", "questa",
    }
    return word_norm in weak or word_norm in extra


def _has_digit(text: str) -> bool:
    """Vero se il testo contiene una cifra (numeri/dati, mai hero)."""
    try:
        return bool(re.search(r"\d", str(text or "")))
    except Exception:
        return False


def boost_typography_styles(
    styled: list[dict],
    role: str | None,
    chunk_text: str = "",
    uppercase_impact: bool = True,
) -> list[dict]:
    """Boost tipografico per atto (post-process deterministico, mai eccezioni).

    - hook: garantisce ≥1 impact (promuove la parola contenuto più lunga);
      l'hook deve colpire visivamente al primo fotogramma.
    - cta: verbi d'azione → impact; garantisce ≥1 impact per chunk CTA.
    - body/altro: invariato (il tagger generico resta sovrano nel corpo).
    Aggiorna anche "display" (impact → UPPER se il preset lo richiede).
    Inizializza sempre "is_hero"=False e "is_number" (digit check): la scelta
    dell'unico hero del video avviene dopo in `assign_hero_flags` (video-wide),
    mai qui per-chunk (evita N hero). Il moto resta deciso dal renderer da
    (style, is_hero, is_number): keywords.py resta fonte colore, il tagger
    resta fonte moto (unificazione keyword==impact per l'animazione).
    """
    try:
        if role not in ("hook", "cta") or not styled:
            return styled
        norm_of = [_norm_word(str(s.get("word", ""))) for s in styled]

        def longest_content(exclude: set[int] | None = None) -> int | None:
            best, best_len = None, 0
            for k, s in enumerate(styled):
                if exclude is not None and k in exclude:
                    continue
                w = norm_of[k]
                if not w or _function_word(w):
                    continue
                raw = str(s.get("word", ""))
                if len(w) > best_len or (len(w) == best_len and re.search(r"\d", raw)):
                    best, best_len = k, len(w)
            return best

        if role == "cta":
            for k, s in enumerate(styled):
                try:
                    if norm_of[k] in _CTA_ACTION_VERBS and s.get("style") != "impact":
                        s["style"] = "impact"
                except Exception:
                    continue
        has_impact = any(s.get("style") == "impact" for s in styled)
        if not has_impact:
            pick = longest_content()
            if pick is not None:
                try:
                    styled[pick]["style"] = "impact"
                except Exception:
                    pass
        if uppercase_impact:
            for s in styled:
                try:
                    if s.get("style") == "impact":
                        s["display"] = str(s.get("word", "")).upper()
                except Exception:
                    continue
        # Flag moto: default stabili (hero scelto video-wide dopo).
        for s in styled:
            try:
                if not isinstance(s, dict):
                    continue
                s.setdefault("is_hero", False)
                _w = str(s.get("word", ""))
                s["is_number"] = _has_digit(_w)
                # I numeri non sono mai hero (pop corto dedicato T3-num).
                if s.get("is_number"):
                    s["is_hero"] = False
            except Exception:
                continue
        return styled
    except Exception:
        return styled


def assign_hero_flags(chunks: list[dict]) -> list[dict]:
    """Marca l'UNICA parola hero del video (T3 hero-pop, mai eccezioni).

    Gerarchia deterministica (nessun LLM, nessun costo):
      1. primo verbo d'azione CTA in chunk CTA con style impact e senza cifre;
      2. altrimenti parola contenuto piu' lunga del primo hook con impact e
         senza cifre (stessa regola di `boost_typography_styles`);
      3. altrimenti nessuna hero (video piatto, nessun cambio visivo).

    Inizializza `is_hero=False` su tutte le styled_words e `True` su una sola
    parola in tutto il video. I numeri (`is_number`) non sono mai hero.
    Da chiamare dopo `enrich_chunks_with_typography` (o fine tagging): il
    renderer legge `(style, is_hero, is_number)` per scegliere T0-T3.
    Ritorna gli stessi dict (mutati in place per compatibilita').
    """
    try:
        if not chunks:
            return chunks
        # Reset stabile: al massimo 1 hero per video.
        for _ch in chunks:
            try:
                for _s in ((_ch or {}).get("styled_words") or []):
                    if isinstance(_s, dict):
                        _s["is_hero"] = False
                        if "is_number" not in _s:
                            _s["is_number"] = _has_digit(str(_s.get("word", "")))
            except Exception:
                continue
        # 1. CTA: primo verbo d'azione impact senza cifre.
        for _ch in chunks:
            try:
                if not isinstance(_ch, dict) or _ch.get("narrative_role") != CTA:
                    continue
                for _s in (_ch.get("styled_words") or []):
                    if not isinstance(_s, dict):
                        continue
                    _norm = _norm_word(str(_s.get("word", "")))
                    if (_s.get("style") == "impact" and _norm in _CTA_ACTION_VERBS
                            and not _has_digit(str(_s.get("word", "")))):
                        _s["is_hero"] = True
                        return chunks
            except Exception:
                continue
        # 2. Hook: contenuto piu' lungo tra gli impact senza cifre (primo hook).
        _best = None  # (chunk_idx, word_idx, length)
        for _ci, _ch in enumerate(chunks):
            try:
                if not isinstance(_ch, dict) or _ch.get("narrative_role") != HOOK:
                    continue
                for _wi, _s in enumerate(_ch.get("styled_words") or []):
                    if not isinstance(_s, dict) or _s.get("style") != "impact":
                        continue
                    if _has_digit(str(_s.get("word", ""))):
                        continue
                    _norm = _norm_word(str(_s.get("word", "")))
                    if not _norm or _function_word(_norm):
                        continue
                    _cand = (_ci, _wi, len(_norm))
                    if _best is None or _cand[2] > _best[2]:
                        _best = _cand
            except Exception:
                continue
        if _best is not None:
            try:
                chunks[_best[0]]["styled_words"][_best[1]]["is_hero"] = True
            except Exception:
                pass
        return chunks
    except Exception:
        return chunks


def _cta_words_count(cta_idx: list[int], chunks: list[dict]) -> int:
    total = 0
    for i in cta_idx:
        try:
            words = (chunks[i] or {}).get("words")
            if isinstance(words, list) and words:
                total += sum(1 for w in words if str((w or {}).get("word", "")).strip())
            else:
                total += len(_chunk_text(chunks[i]).split())
        except Exception:
            continue
    return total


def classify_narrative(
    chunks: list[dict],
    script_text: str = "",
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> tuple[dict, list[dict]]:
    """Classifica i chunk in hook / corpo a beat / CTA e li arricchisce.

    Args:
        chunks: chunk da emphasis grouping (con "text"/"start"/"end"/"words").
        script_text: non usato per ora (firma futura per hint LLM), ignorato.
        on_attempt: callback opzionale (singola chiamata di riepilogo).

    Returns:
        (sections, enriched): sections = {"hook": [...], "body": [...],
        "body_beats": [[...]], "beat_tones": [...], "cta": [...],
        "cta_strength": "strong|soft|none", "cta_mode": "card|locked|none"}.
        enriched = chunk + {narrative_role, narrative_beat (-1 fuori corpo),
        beat_tone, anim_entry_mult/anim_pop_from (hook), cta_card, cta_section_id}.
        Non solleva mai.
    """
    try:
        if not NARRATIVE_ENABLED:
            return (
                {"hook": [], "body": list(range(len(chunks or []))),
                 "body_beats": [list(range(len(chunks or [])))] if chunks else [],
                 "beat_tones": ["explainer"] if chunks else [],
                 "cta": [], "cta_strength": "none", "cta_mode": "none"},
                [dict(c or {}) for c in (chunks or [])],
            )
    except Exception:
        pass
    if not chunks:
        empty = {"hook": [], "body": [], "body_beats": [], "beat_tones": [],
                 "cta": [], "cta_strength": "none", "cta_mode": "none"}
        return empty, []

    n = len(chunks)
    try:
        cta_idx, strength = _detect_cta(chunks)
    except Exception:
        cta_idx, strength = [], "none"
    cta_start = min(cta_idx) if cta_idx else None
    try:
        hook_idx = _detect_hook(chunks, cta_start)
    except Exception:
        hook_idx = [0] if (cta_start is None or cta_start > 0) else []
    hook_set, cta_set = set(hook_idx), set(cta_idx)
    body_idx = [i for i in range(n) if i not in hook_set and i not in cta_set]
    try:
        beats = _split_body_beats(body_idx, chunks)
    except Exception:
        beats = [list(body_idx)] if body_idx else []
    try:
        tones = [beat_tone([chunks[i] for i in b]) for b in beats]
    except Exception:
        tones = ["explainer"] * len(beats)

    # Modalità CTA: card persistente solo se forte, breve e abilitata.
    cta_mode = "none"
    if cta_idx:
        if strength == "strong":
            try:
                card_ok = bool(NARRATIVE_CTA_CARD)
                max_w = int(NARRATIVE_CTA_CARD_MAX_WORDS)
            except Exception:
                card_ok, max_w = True, 14
            if card_ok and _cta_words_count(cta_idx, chunks) <= max(1, max_w):
                cta_mode = "card"
            else:
                cta_mode = "locked"
        else:
            cta_mode = "locked"

    try:
        entry_mult = float(NARRATIVE_HOOK_ENTRY_MULT)
        entry_mult = min(1.0, max(0.3, entry_mult))
    except Exception:
        entry_mult = 0.7
    try:
        pop_from = float(NARRATIVE_HOOK_POP_FROM)
        pop_from = min(1.0, max(0.1, pop_from))
    except Exception:
        pop_from = 0.55

    beat_of = {i: b for b, beat in enumerate(beats) for i in beat}
    enriched: list[dict] = []
    for i, ch in enumerate(chunks):
        try:
            base = dict(ch or {})
        except Exception:
            base = {}
        if i in hook_set:
            base["narrative_role"] = HOOK
            base["narrative_beat"] = -1
            base["beat_tone"] = "hook"
            base["anim_entry_mult"] = entry_mult
            base["anim_pop_from"] = pop_from
            base["cta_card"] = False
        elif i in cta_set:
            base["narrative_role"] = CTA
            base["narrative_beat"] = -1
            base["beat_tone"] = "cta"
            base["cta_strength"] = strength
            base["cta_card"] = (cta_mode == "card")
            base["cta_section_id"] = cta_idx[0] if cta_idx else i
        else:
            base["narrative_role"] = BODY
            base["narrative_beat"] = int(beat_of.get(i, -1))
            try:
                base["beat_tone"] = tones[beat_of[i]] if i in beat_of else "explainer"
            except Exception:
                base["beat_tone"] = "explainer"
            base["cta_card"] = False
        enriched.append(base)

    sections = {
        "hook": list(hook_idx),
        "body": list(body_idx),
        "body_beats": [list(b) for b in beats],
        "beat_tones": list(tones),
        "cta": list(cta_idx),
        "cta_strength": strength if cta_idx else "none",
        "cta_mode": cta_mode,
    }
    if on_attempt is not None:
        try:
            on_attempt(
                1, 1, True,
                f"hook={hook_idx} beat={len(beats)} cta={cta_idx}({sections['cta_strength']}/{cta_mode})",
            )
        except Exception:
            pass
    return sections, enriched
