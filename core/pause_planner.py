"""
Pause Planner P0 (WS-B): logica PURA per il montaggio delle pause.

`plan_pauses(words, script_text, duration_s, niche, cfg) -> PausePlan`:
accorcia le pause eccessive, allunga quelle drammatiche, fissa head/tail.
Niente I/O, deterministico, testabile con `unittest`.

Confini: sentence_end (. ! ?) / clause (, ; : — …) / none.
Profili di pace: tight (fitness/dark) | balanced (default) | breathing
(educational); `pace=auto` sceglie per nicchia.

Output: {"segments": [(src_start, src_end, dst_start)], "insertions",
"cuts", "stats", ...} + `map_time(t, plan)` monotona.
"""

from __future__ import annotations

import re

# Target per confine e profilo (secondi). I valori balanced sono anche i
# default di config (PAUSE_SENTENCE_TARGET_S=0.32, CLAUSE=0.14, NONE=0.10).
PACE_TABLE: dict[str, dict[str, float]] = {
    "tight": {"sentence_end": 0.24, "clause": 0.10, "none": 0.08},
    "balanced": {"sentence_end": 0.32, "clause": 0.14, "none": 0.10},
    "breathing": {"sentence_end": 0.42, "clause": 0.20, "none": 0.14},
}

TIGHT_NICHES = frozenset({"fitness_sport", "dark_motivational"})
BREATHING_NICHES = frozenset({"educational"})

_SENTENCE_END = (".", "!", "?")
_CLAUSE_END = (",", ";", ":", "—", "–", "-", "…", "…" )


def _cfg_float(cfg: dict | None, key: str, default: float) -> float:
    try:
        if isinstance(cfg, dict) and key in cfg and cfg[key] is not None:
            return float(cfg[key])
    except (TypeError, ValueError):
        pass
    try:
        import config as _c
        if hasattr(_c, key):
            return float(getattr(_c, key))
    except Exception:
        pass
    return default


def resolve_pace_profile(niche: str | None, cfg: dict | None = None) -> str:
    """Profilo di pace (auto → per nicchia). Mai eccezioni."""
    try:
        want = str((cfg or {}).get("pace", "") or "")
    except Exception:
        want = ""
    if not want:
        try:
            import config as _c
            want = str(getattr(_c, "PAUSE_PACE_PROFILE", "auto") or "auto")
        except Exception:
            want = "auto"
    want = want.strip().lower()
    if want in PACE_TABLE:
        return want
    try:
        n = str(niche or "").strip().lower().replace("-", "_").replace(" ", "_")
    except Exception:
        n = ""
    if n in TIGHT_NICHES:
        return "tight"
    if n in BREATHING_NICHES:
        return "breathing"
    return "balanced"


def classify_boundary(word_text: str) -> str:
    """Classifica il confine DOPO la parola: sentence_end | clause | none."""
    try:
        t = str(word_text or "").strip()
    except Exception:
        return "none"
    if not t:
        return "none"
    last = t[-1]
    if last in (".", "!", "?"):
        return "sentence_end"
    if last in (",", ";", ":", "—", "–", "…"):
        return "clause"
    # Ellissi testuale "..." o "--".
    if t.endswith("...") or t.endswith("--"):
        return "clause"
    return "none"


def _sentence_spans(words: list[dict]) -> list[tuple[int, int]]:
    """Spans (idx_start, idx_end) delle frasi (da punteggiatura .!?)."""
    spans: list[tuple[int, int]] = []
    try:
        start = 0
        for i, w in enumerate(words):
            try:
                txt = str(w.get("word", ""))
            except Exception:
                continue
            if txt.strip() and txt.strip()[-1] in (".", "!", "?"):
                spans.append((start, i))
                start = i + 1
        if start < len(words):
            spans.append((start, len(words) - 1))
    except Exception:
        pass
    return spans


def _has_digit(text: str) -> bool:
    try:
        return bool(re.search(r"\d", text or ""))
    except Exception:
        return False


def dramatic_gap_indices(words: list[dict]) -> set[int]:
    """Indici dei gap (dopo words[i]) candidati a pausa drammatica.

    Segnali deterministici: fine prima frase, prima dell'ultima frase, dopo
    domanda retorica (?), prima/dopo frasi con cifre/percentuali.
    Max una ogni ~3s (diradamento greedy sul tempo medio del gap).
    """
    cand: set[int] = set()
    try:
        n = len(words)
        if n < 2:
            return cand
        spans = _sentence_spans(words)
        if spans:
            # Fine prima frase (stacco dopo l'hook).
            if spans[0][1] < n - 1:
                cand.add(spans[0][1])
            # Prima dell'ultima frase (CTA): gap prima del suo inizio.
            if len(spans) > 1 and spans[-1][0] > 0:
                cand.add(spans[-1][0] - 1)
        for i, w in enumerate(words):
            try:
                txt = str(w.get("word", ""))
            except Exception:
                continue
            # Dopo domanda retorica.
            if txt.strip().endswith("?") and i < n - 1:
                cand.add(i)
        # Frasi con cifre/percentuali: gap prima e dopo la frase.
        for (s, e) in spans:
            try:
                joined = " ".join(str(words[k].get("word", "")) for k in range(s, e + 1))
            except Exception:
                continue
            if _has_digit(joined) or "%" in joined:
                if s > 0:
                    cand.add(s - 1)
                if e < n - 1:
                    cand.add(e)
        # Diradamento: max una ogni ~3s (per tempo medio gap).
        if len(cand) > 1:
            def _t(i: int) -> float:
                try:
                    return (float(words[i].get("end", 0.0)) + float(words[i + 1].get("start", 0.0))) / 2.0
                except Exception:
                    return 0.0
            ordered = sorted(cand, key=_t)
            kept: list[int] = []
            for i in ordered:
                if all(abs(_t(i) - _t(k)) >= 3.0 for k in kept):
                    kept.append(i)
            cand = set(kept)
    except Exception:
        pass
    return cand


def plan_pauses(
    words: list[dict] | None,
    script_text: str = "",
    duration_s: float = 0.0,
    niche: str | None = None,
    cfg: dict | None = None,
) -> dict:
    """Pianifica gli edit delle pause. Ritorna il PausePlan (dict, mai eccezioni).

    Il piano descrive tagli (cuts) e inserimenti (insertions) nel WAV;
    `segments` = [(src_start, src_end, dst_start)] per `map_time`.
    Piano vuoto → {"no_change": True} (nessuna modifica all'audio).
    """
    empty: dict = {
        "segments": [], "cuts": [], "insertions": [],
        "src_duration": float(duration_s or 0.0),
        "dst_duration": float(duration_s or 0.0),
        "stats": {"shortened": 0, "lengthened": 0, "shorten_s": 0.0,
                  "lengthen_s": 0.0, "head_delta_s": 0.0, "tail_delta_s": 0.0},
        "profile": "balanced", "no_change": True,
    }
    try:
        ws = [dict(w) for w in (words or []) if isinstance(w, dict)]
    except Exception:
        return empty
    try:
        dur = max(0.0, float(duration_s))
    except (TypeError, ValueError):
        return empty
    if len(ws) < 1 or dur <= 0:
        return empty

    pace = resolve_pace_profile(niche, cfg)
    table = PACE_TABLE.get(pace, PACE_TABLE["balanced"])
    tol = _cfg_float(cfg, "tolerance", _cfg_float(cfg, "PAUSE_TOLERANCE_S", 0.06))
    min_edit = _cfg_float(cfg, "min_edit", _cfg_float(cfg, "PAUSE_MIN_EDIT_S", 0.05))
    max_gap = _cfg_float(cfg, "max_gap", _cfg_float(cfg, "PAUSE_MAX_S", 0.60))
    t_sentence = _cfg_float(cfg, "sentence", _cfg_float(cfg, "PAUSE_SENTENCE_TARGET_S", table["sentence_end"]))
    t_clause = _cfg_float(cfg, "clause", _cfg_float(cfg, "PAUSE_CLAUSE_TARGET_S", table["clause"]))
    t_none = _cfg_float(cfg, "none_max", _cfg_float(cfg, "PAUSE_NONE_MAX_S", table["none"]))
    drama_extra = _cfg_float(cfg, "dramatic_extra", _cfg_float(cfg, "PAUSE_DRAMATIC_EXTRA_S", 0.18))
    head_t = _cfg_float(cfg, "head", _cfg_float(cfg, "PAUSE_HEAD_TARGET_S", 0.06))
    tail_t = _cfg_float(cfg, "tail", _cfg_float(cfg, "PAUSE_TAIL_TARGET_S", 0.35))
    max_ratio = _cfg_float(cfg, "max_change", _cfg_float(cfg, "PAUSE_MAX_TOTAL_CHANGE_RATIO", 0.12))

    targets = {"sentence_end": t_sentence, "clause": t_clause, "none": t_none}
    drama = dramatic_gap_indices(ws)

    # --- Raccogli edit (gap interni) ---
    # Ogni edit: {"kind": "cut"|"insert", "gap": i, "at": src_time, "dur": s}
    # EPS tollera la polvere floating-point sui confronti di soglia.
    EPS = 1e-6
    edits: list[dict] = []
    shortened = lengthened = 0
    for i in range(len(ws) - 1):
        try:
            e = float(ws[i].get("end", 0.0))
            s = float(ws[i + 1].get("start", e))
        except (TypeError, ValueError):
            continue
        g = max(0.0, s - e)
        if g < min_edit - EPS:
            continue
        b = classify_boundary(ws[i].get("word", ""))
        target = targets[b]
        if b == "none":
            # Per "none" il target è un MASSIMO: accorcia solo l'eccesso.
            if g > max(target + tol, max_gap) + EPS or g > max_gap + EPS:
                want = min(target, g - min_edit)
                if g - want >= min_edit - EPS:
                    at = e + (g - (g - want)) / 2.0
                    edits.append({"kind": "cut", "gap": i, "at": e + (g / 2.0),
                                  "dur": g - want, "boundary": b, "drama": False})
                    shortened += 1
            continue
        # Confini di frase/proposizione.
        if g > target + tol + EPS or g > max_gap + EPS:
            want = min(target, g - min_edit) if g > min_edit else target
            remove = g - want
            if remove >= min_edit - EPS:
                edits.append({"kind": "cut", "gap": i, "at": e + g / 2.0,
                              "dur": remove, "boundary": b, "drama": False})
                shortened += 1
        elif i in drama and g < target + drama_extra - 1e-9:
            add = (target + drama_extra) - g
            if add >= min_edit - EPS:
                edits.append({"kind": "insert", "gap": i, "at": e + g / 2.0,
                              "dur": add, "boundary": b, "drama": True})
                lengthened += 1

    # --- Head / tail ---
    head_delta = tail_delta = 0.0
    try:
        first_start = max(0.0, float(ws[0].get("start", 0.0)))
        if first_start - head_t >= min_edit:
            edits.append({"kind": "cut", "gap": -1, "at": (first_start - head_t) / 2.0 + 0.0,
                          "dur": first_start - head_t, "boundary": "head", "drama": False,
                          "head": (0.0, first_start - head_t)})
            head_delta = -(first_start - head_t)
    except (TypeError, ValueError):
        pass
    try:
        last_end = float(ws[-1].get("end", dur))
        tail_have = max(0.0, dur - last_end)
        if tail_have - tail_t >= min_edit:
            edits.append({"kind": "cut", "gap": len(ws), "at": 0.0,
                          "dur": tail_have - tail_t, "boundary": "tail", "drama": False,
                          "tail": (last_end + tail_t, dur)})
            tail_delta = -(tail_have - tail_t)
        elif tail_t - tail_have >= min_edit:
            edits.append({"kind": "insert", "gap": len(ws), "at": dur,
                          "dur": tail_t - tail_have, "boundary": "tail", "drama": False})
            tail_delta = tail_t - tail_have
    except (TypeError, ValueError):
        pass
    # Head troppo corto (voce che parte dopo)? Non si allunga la testa
    # (retention: la voce parte subito) — solo tagli.

    if not edits:
        empty["profile"] = pace
        return empty

    # --- Limiti di sicurezza ---
    total_cut = sum(e["dur"] for e in edits if e["kind"] == "cut")
    total_ins = sum(e["dur"] for e in edits if e["kind"] == "insert")
    budget = max_ratio * dur
    if total_cut + total_ins > budget and (total_cut + total_ins) > 0:
        # Priorità: head/tail + shorten; sacrifica prima gli allungamenti.
        ins_edits = [e for e in edits if e["kind"] == "insert" and e.get("boundary") != "tail"]
        cut_edits = [e for e in edits if e not in ins_edits]
        keep_ins: list[dict] = []
        used = sum(e["dur"] for e in cut_edits)
        for e in sorted(ins_edits, key=lambda x: -float(x["dur"])):
            if used + float(e["dur"]) <= budget:
                keep_ins.append(e)
                used += float(e["dur"])
        edits = cut_edits + keep_ins
        total_cut = sum(e["dur"] for e in edits if e["kind"] == "cut")
        total_ins = sum(e["dur"] for e in edits if e["kind"] == "insert")
        if total_cut + total_ins > budget:
            # Scala uniformemente i tagli.
            f = budget / (total_cut + total_ins)
            for e in edits:
                e["dur"] = float(e["dur"]) * f
                # Le tuple head/tail vanno riscalate (altrimenti ignorano il budget).
                if "head" in e:
                    c0, _c1 = e["head"]
                    e["head"] = (c0, c0 + float(e["dur"]))
                if "tail" in e:
                    c0, _c1 = e["tail"]
                    e["tail"] = (c0, c0 + float(e["dur"]))
            total_cut *= f
            total_ins *= f
        shortened = sum(1 for e in edits if e["kind"] == "cut" and e.get("gap", -2) >= 0)
        lengthened = sum(1 for e in edits if e["kind"] == "insert" and e.get("gap", -2) >= 0)
    dst_dur = dur - total_cut + total_ins
    if dst_dur < 5.0 and dur >= 5.0:
        # Non scendere sotto i 5s: scala i tagli.
        allow_cut = max(0.0, (dur - 5.0) + total_ins)
        if total_cut > allow_cut and total_cut > 0:
            f = allow_cut / total_cut
            for e in edits:
                if e["kind"] == "cut":
                    e["dur"] = float(e["dur"]) * f
                    if "head" in e:
                        c0, _c1 = e["head"]
                        e["head"] = (c0, c0 + float(e["dur"]))
                    if "tail" in e:
                        c0, _c1 = e["tail"]
                        e["tail"] = (c0, c0 + float(e["dur"]))
            total_cut = sum(e["dur"] for e in edits if e["kind"] == "cut")
            dst_dur = dur - total_cut + total_ins

    # --- Costruisci tagli concreti (src) e inserimenti ---
    cuts: list[tuple[float, float]] = []  # (cut_start, cut_end) in src
    insertions: list[tuple[float, float]] = []  # (src_anchor, dur)
    for e in edits:
        try:
            if e["kind"] == "cut" and "head" in e:
                c0, c1 = e["head"]
                if c1 - c0 >= 0.01:
                    cuts.append((max(0.0, c0), max(0.0, c1)))
            elif e["kind"] == "cut" and "tail" in e:
                c0, c1 = e["tail"]
                if c1 - c0 >= 0.01:
                    cuts.append((c0, min(dur, c1)))
            elif e["kind"] == "cut":
                i = int(e["gap"])
                en = float(ws[i].get("end", 0.0))
                st = float(ws[i + 1].get("start", en))
                rm = float(e["dur"])
                # Taglio al centro del gap, con margine 10ms dalle parole.
                c0 = en + (st - en - rm) / 2.0
                c1 = c0 + rm
                if c0 >= en + 0.005 and c1 <= st - 0.005 and c1 > c0:
                    cuts.append((c0, c1))
            else:
                insertions.append((float(e["at"]), float(e["dur"])))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    cuts.sort()
    # Fondi tagli sovrapposti (sicurezza).
    merged: list[list[float]] = []
    for c0, c1 in cuts:
        if merged and c0 <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], c1)
        else:
            merged.append([c0, c1])
    cuts = [(a, b) for a, b in merged if b - a >= 0.005]
    insertions.sort(key=lambda p: p[0])

    if not cuts and not insertions:
        empty["profile"] = pace
        return empty

    # --- Segmenti keep: [(src_start, src_end, dst_start)] ---
    segments: list[tuple[float, float, float]] = []
    ins_by_anchor = sorted(insertions, key=lambda p: p[0])
    dst = 0.0
    cur = 0.0
    ii = 0
    for (c0, c1) in cuts + [(dur, dur)]:
        if c0 > cur:
            # Inserimenti con anchor in [cur, c0): cadono qui.
            while ii < len(ins_by_anchor) and ins_by_anchor[ii][0] < c0:
                        # (anchor < cur impossibile per costruzione: gap interni)
                dst += float(ins_by_anchor[ii][1])
                ii += 1
            segments.append((cur, c0, dst))
            dst += c0 - cur
        else:
            while ii < len(ins_by_anchor) and ins_by_anchor[ii][0] < c0:
                dst += float(ins_by_anchor[ii][1])
                ii += 1
        cur = max(cur, c1)
    while ii < len(ins_by_anchor):
        dst += float(ins_by_anchor[ii][1])
        ii += 1
    dst_duration = dst

    shorten_s = sum(b - a for a, b in cuts)
    lengthen_s = sum(d for _, d in insertions)
    # Statistiche derivate dai tagli/inserimenti FINALI (post-budget).
    try:
        _head_s = sum(b - a for a, b in cuts if a <= 0.001)
    except Exception:
        _head_s = 0.0
    try:
        _tail_cut_s = sum(b - a for a, b in cuts if b >= dur - 0.001 and a > 0.001)
    except Exception:
        _tail_cut_s = 0.0
    try:
        _tail_ins_s = sum(d for a, d in insertions if a >= dur - 0.001)
    except Exception:
        _tail_ins_s = 0.0
    plan = {
        "segments": segments,
        "cuts": cuts,
        "insertions": insertions,
        "src_duration": dur,
        "dst_duration": dst_duration,
        "stats": {
            "shortened": sum(1 for e in edits if e["kind"] == "cut" and int(e.get("gap", -2)) >= 0 and "head" not in e and "tail" not in e),
            "lengthened": lengthened,
            "shorten_s": round(shorten_s, 3),
            "lengthen_s": round(lengthen_s, 3),
            "head_delta_s": round(-_head_s, 3),
            "tail_delta_s": round(_tail_ins_s - _tail_cut_s, 3),
        },
        "profile": pace,
        "no_change": False,
    }
    return plan


def build_segments(
    cuts: list[tuple[float, float]],
    insertions: list[tuple[float, float]],
    duration_s: float,
) -> tuple[list[tuple[float, float, float]], float]:
    """Ricostruisce segments + dst_duration da tagli/inserimenti (puro).

    Usato dal planner e dal pause_editor (che può saltare tagli non silenziosi
    e deve ricalcolare la mappa). Mai eccezioni.
    """
    try:
        dur = max(0.0, float(duration_s))
        cs = sorted((float(a), float(b)) for a, b in (cuts or []) if float(b) > float(a))
        ins = sorted(((float(a), float(d)) for a, d in (insertions or []) if float(d) > 0),
                     key=lambda p: p[0])
    except Exception:
        return [], float(duration_s or 0.0)
    merged: list[list[float]] = []
    for c0, c1 in cs:
        if merged and c0 <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], c1)
        else:
            merged.append([c0, c1])
    segments: list[tuple[float, float, float]] = []
    dst = 0.0
    cur = 0.0
    ii = 0
    for (c0, c1) in merged + [[dur, dur]]:
        if c0 > cur:
            while ii < len(ins) and ins[ii][0] < c0:
                dst += float(ins[ii][1])
                ii += 1
            segments.append((cur, c0, dst))
            dst += c0 - cur
        else:
            while ii < len(ins) and ins[ii][0] < c0:
                dst += float(ins[ii][1])
                ii += 1
        cur = max(cur, c1)
    while ii < len(ins):
        dst += float(ins[ii][1])
        ii += 1
    return segments, dst


def map_time(t: float, plan: dict) -> float:
    """Mappa un tempo src → dst (monotona; zone tagliate → punto di giunzione).

    Pura. Nelle zone keep: interpolazione lineare; nelle zone tagliate:
    il dst del punto di giunzione; oltre i bordi: clamp.
    """
    try:
        tt = max(0.0, float(t))
    except (TypeError, ValueError):
        return 0.0
    try:
        segs = plan.get("segments") or []
        if not segs:
            return tt
        prev_end = 0.0
        for (s0, s1, d0) in segs:
            if tt < s0:
                # Dentro un taglio (o prima del primo keep): punto di giunzione.
                return float(prev_end)
            if tt <= s1:
                return float(d0 + (tt - s0))
            prev_end = float(d0 + (s1 - s0))
        # Oltre l'ultimo segmento: clamp alla fine.
        return float(prev_end)
    except Exception:
        try:
            return max(0.0, float(t))
        except Exception:
            return 0.0
