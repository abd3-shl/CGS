"""
Timestamp Enricher (Full Engine Upgrade — Fase 1).

Arricchisce i timestamp Whisper word-level SENZA mai alterare `start`/`end`
(invariante Timestamp Preservation):

  enrich_whisper_timestamps(whisper_data) -> list[dict]

Ogni parola arricchita conserva `word/start/end` originali e aggiunge:
  - `tier`: "T0" (connettivi) | "T1" (base) | "T2" (keyword) | "T3" (hero)
  - `vfx_type`: "none" | "pop_scale" | "glow" | "badge_slide"
  - `sfx_trigger`: True per T3 o picchi emotivi (punti esclamativi/domande,
    parole tutte maiuscole, keyword enfatiche).

Input accettati (tolleranti, mai eccezioni):
  - lista di dict [{word,start,end,...}]
  - dict Whisper verbose {"words": [...]}
  - lista di stringhe (fallback: timing uniformi 0.3s, solo per test/debug)

Euristica deterministica (nessun LLM, nessun I/O):
  - T3: parola in `hero_words` esplicite (match normalizzato) oppure
    (MAIUSCOLO 4+ con `!` vicino) — max 1 per chiamata se `single_hero=True`.
  - T2: parola in `keywords` (match normalizzato) o con cifre o MAIUSCOLA 3+.
  - T0: connettivi/articoli/preposizioni (lista IT+EN).
  - T1: resto.

`sfx_trigger=True` se T3, oppure T2 con `!`/`?` adiacente, oppure parola con
marker emotivo (caps, punti esclamativi ripetuti, emoji-base).
"""

from __future__ import annotations

import re
from typing import Any

_T0_CONNECTIVES: frozenset[str] = frozenset({
    # IT articoli/preposizioni/congiunzioni
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra", "il", "lo",
    "la", "i", "gli", "le", "un", "una", "uno", "e", "o", "ma", "che",
    "non", "si", "mi", "ti", "ci", "ne", "del", "della", "dei", "delle",
    "dello", "al", "allo", "alla", "ai", "agli", "alle", "dal", "dallo",
    "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella", "nei",
    "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "come", "quando", "dove", "perche", "perché", "questo", "questa",
    "questi", "queste", "quello", "quella", "molto", "tanto", "anche",
    # EN
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "it", "this", "that", "you",
})

_EMOTIVE_RE = re.compile(r"[!?]{1,}|[\U0001F300-\U0001FAFF]")
_DIGIT_RE = re.compile(r"\d")


def _norm(word: str) -> str:
    try:
        return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)
    except Exception:
        return ""


def _as_word_list(whisper_data: Any) -> list[dict]:
    """Normalizza l'input a lista di dict word (copie sicure, mai eccezioni)."""
    try:
        if isinstance(whisper_data, dict) and isinstance(whisper_data.get("words"), list):
            items = whisper_data["words"]
        elif isinstance(whisper_data, (list, tuple)):
            items = list(whisper_data)
        else:
            return []
        out: list[dict] = []
        t = 0.0
        for w in items:
            try:
                if isinstance(w, str):
                    out.append({"word": w, "start": t, "end": t + 0.3})
                    t += 0.3
                elif isinstance(w, dict):
                    word = str(w.get("word", w.get("text", "")))
                    try:
                        s = float(w.get("start", 0.0))
                    except (TypeError, ValueError):
                        s = 0.0
                    try:
                        e = float(w.get("end", s + 0.3))
                    except (TypeError, ValueError):
                        e = s + 0.3
                    if e <= s:
                        e = s + 0.1
                    entry = dict(w)
                    entry["word"] = word
                    entry["start"] = float(s)
                    entry["end"] = float(e)
                    out.append(entry)
            except Exception:
                continue
        return out
    except Exception:
        return []


def enrich_whisper_timestamps(
    whisper_data: Any,
    keywords: list[str] | set[str] | None = None,
    hero_words: list[str] | set[str] | None = None,
    single_hero: bool = True,
) -> list[dict]:
    """Arricchisce ogni parola con tier/vfx/sfx SENZA toccare start/end.

    Args:
        whisper_data: lista word-dict o dict verbose Whisper o lista stringhe.
        keywords: parole T2 (match normalizzato, case-insensitive).
        hero_words: parole T3 esplicite (match normalizzato). Se vuote, T3
            viene dedotta da euristica emotiva (caps + `!`).
        single_hero: se True, al massimo 1 T3 (la prima hero-candidata vince;
            le altre degradano a T2 per non saturare badge/SFX).

    Returns:
        Nuova lista di dict (originali mai mutati) con chiavi aggiuntive
        `tier`, `vfx_type`, `sfx_trigger`. Timestamp identici agli input.
    """
    words = _as_word_list(whisper_data)
    try:
        kw_norm = {_norm(str(k)) for k in (keywords or []) if _norm(str(k))}
    except Exception:
        kw_norm = set()
    try:
        hero_norm = {_norm(str(h)) for h in (hero_words or []) if _norm(str(h))}
    except Exception:
        hero_norm = set()

    enriched: list[dict] = []
    hero_assigned = False
    n = len(words)
    for i, w in enumerate(words):
        try:
            entry = dict(w)
            # --- Invariante: preserva start/end originali (float identici) ---
            try:
                entry["start"] = float(w["start"])
                entry["end"] = float(w["end"])
            except (KeyError, TypeError, ValueError):
                pass
            raw = str(w.get("word", ""))
            norm = _norm(raw)
            nxt_raw = str(words[i + 1].get("word", "")) if i + 1 < n else ""
            has_digit = bool(_DIGIT_RE.search(raw))
            is_caps = len(raw.strip("!?.,;: ")) >= 3 and raw.strip("!?.,;: ").isupper()
            emotive = bool(_EMOTIVE_RE.search(raw + " " + nxt_raw))

            # --- Tier ---
            tier = "T1"
            try:
                if norm in hero_norm and not (single_hero and hero_assigned):
                    tier = "T3"
                elif norm in kw_norm or has_digit or (is_caps and len(norm) >= 3):
                    tier = "T2"
                    # Euristica hero implicita: caps forte + emotivo vicino.
                    if (not hero_norm and is_caps and emotive
                            and not has_digit and not (single_hero and hero_assigned)):
                        tier = "T3"
                elif norm in _T0_CONNECTIVES or len(norm) <= 2:
                    tier = "T0"
                else:
                    tier = "T1"
            except Exception:
                tier = "T1"
            if tier == "T3" and single_hero:
                if hero_assigned:
                    tier = "T2"
                else:
                    hero_assigned = True

            # --- VFX ---
            if tier == "T3":
                vfx = "badge_slide"
            elif tier == "T2":
                vfx = "pop_scale" if not has_digit else "glow"
            elif tier == "T1":
                vfx = "none"
            else:
                vfx = "none"

            # --- SFX ---
            try:
                sfx = bool(tier == "T3" or (tier == "T2" and emotive))
            except Exception:
                sfx = False

            entry["tier"] = tier
            entry["vfx_type"] = vfx
            entry["sfx_trigger"] = sfx
            enriched.append(entry)
        except Exception:
            try:
                enriched.append(dict(w))
            except Exception:
                continue
    return enriched
