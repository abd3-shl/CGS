"""
Pause Editor P0 (WS-B): applica il PausePlan al WAV, solo stdlib.

- Lavora su WAV decodificato (pcm 16-bit): tagli/inserimenti a livello di
  campione, giunzioni al centro dei gap, crossfade equal-power da
  PAUSE_JOIN_FADE_MS (12 ms) → nessun click.
- Verifica silenzio (RMS < −45 dBFS) sul tratto da rimuovere: se non è
  silenzio, SALTA quella modifica (mai tagliare parlato).
- Silenzio inserito = rumore di fondo campionato dai tratti più silenziosi
  della stessa voce (niente "buchi" udibili); fallback silenzio digitale
  con fade di 10 ms.
- `retime_words` applica `map_time` una sola volta: aggiunge
  `orig_start`/`orig_end` (additive), aggiorna `start`/`end`, garantisce
  `start < end` e monotonia.
- La mappa src→dst è esatta al campione: i fade di giunzione accorciano
  l'output di `f` frame per giunzione e i segmenti effettivi ne tengono
  conto (coerenza audio/parole entro ±1 campione nelle zone keep).

Tutto best-effort: `apply_pause_plan` ritorna None in caso di errore
(il chiamante usa l'audio originale). Usa solo `wave`/`array` (niente ffmpeg).
"""

from __future__ import annotations

import array
import math
import wave


def _cfg_int(key: str, default: int) -> int:
    try:
        import config as _c
        return int(getattr(_c, key, default))
    except (TypeError, ValueError):
        return default


def _rms_dbfs(samples: array.array, lo: int, hi: int) -> float:
    """RMS in dBFS sui campioni [lo, hi) (interleaved, normalizzato a 32768)."""
    try:
        n = max(0, min(len(samples), hi) - max(0, lo))
        if n <= 0:
            return -120.0
        s = 0.0
        for i in range(max(0, lo), max(0, lo) + n):
            v = float(samples[i]) / 32768.0
            s += v * v
        rms = math.sqrt(s / n)
        if rms <= 1e-9:
            return -120.0
        return 20.0 * math.log10(rms)
    except Exception:
        return -120.0


def _read_wav(path: str) -> tuple[dict, array.array] | tuple[None, None]:
    """Legge un WAV pcm 8/16/32-bit. Ritorna (params, campioni interleaved s16)."""
    try:
        with wave.open(path, "rb") as w:
            nch, _sw, fr, nf, ct, cn = w.getparams()
            raw = w.readframes(nf)
            sw = _sw
        if sw == 1:
            a = array.array("B", raw)
            conv = array.array("h", ((int(v) - 128) * 256 for v in a))
        elif sw == 2:
            conv = array.array("h")
            conv.frombytes(raw)
        elif sw == 4:
            tmp = array.array("i")
            tmp.frombytes(raw)
            conv = array.array("h", (max(-32768, min(32767, int(v) // 65536)) for v in tmp))
        else:
            return None, None
        params = {"nchannels": nch, "sampwidth": 2, "framerate": fr,
                  "comptype": ct, "compname": cn}
        return params, conv
    except Exception:
        return None, None


def _write_wav(path: str, params: dict, samples: array.array) -> bool:
    try:
        nch = int(params["nchannels"])
        fr = int(params["framerate"])
        nframes = len(samples) // max(1, nch)
        with wave.open(path, "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(2)
            w.setframerate(fr)
            w.writeframes(samples.tobytes()[:nframes * nch * 2])
        return True
    except Exception:
        return False


def _blend_frames(
    tail: array.array, head: array.array, f: int, nch: int
) -> array.array:
    """Equal-power blend di `f` frame: coda di `tail` + testa di `head`."""
    try:
        out = array.array("h")
        for i in range(f):
            t = float(i) / float(max(1, f))
            g2 = math.sin(t * math.pi / 2.0)
            g1 = math.cos(t * math.pi / 2.0)
            for c in range(nch):
                a = float(tail[(len(tail) // nch - f + i) * nch + c])
                b = float(head[i * nch + c])
                out.append(int(round(max(-32768, min(32767, a * g1 + b * g2)))))
        return out
    except Exception:
        return array.array("h")


def _quiet_bed(samples: array.array, nch: int, fr: int, need_frames: int) -> array.array | None:
    """Rumore di fondo dal tratto più silenzioso (finestra 0.4s, max ~40 probe)."""
    try:
        total_frames = len(samples) // max(1, nch)
        win = max(1, int(fr * 0.4))
        step = max(1, int(fr * 0.2))
        best: array.array | None = None
        best_rms = float("inf")
        starts = list(range(0, max(1, total_frames - win), step))
        if len(starts) > 40:
            stride = len(starts) / 40.0
            starts = [starts[int(i * stride)] for i in range(40)]
        for sf in starts:
            r = _rms_dbfs(samples, sf * nch, (sf + win) * nch)
            if r < best_rms:
                best_rms = r
                best = samples[sf * nch:(sf + win) * nch]
        if best is None:
            return None
        bed = array.array("h")
        while len(bed) // max(1, nch) < need_frames:
            bed.extend(best)
        return bed[:need_frames * nch]
    except Exception:
        return None


def _fade_edges(samples: array.array, nch: int, fr: int, ms: int = 10) -> array.array:
    """Fade in/out lineare ai bordi (per il silenzio inserito)."""
    try:
        f = max(1, int(fr * ms / 1000.0))
        total = len(samples) // max(1, nch)
        f = min(f, total // 2) if total >= 2 else 0
        if f <= 0:
            return samples
        out = array.array("h", samples)
        for i in range(f):
            g = float(i + 1) / float(f + 1)
            for c in range(nch):
                out[i * nch + c] = int(round(float(out[i * nch + c]) * g))
                j = (total - 1 - i) * nch + c
                out[j] = int(round(float(out[j]) * g))
        return out
    except Exception:
        return samples


def apply_pause_plan(
    in_wav: str,
    out_wav: str,
    plan: dict,
    on_log=None,
) -> dict | None:
    """Applica il piano al WAV. Ritorna il piano EFFETTIVO o None (fallback).

    Il piano effettivo ha gli stessi campi del piano in ingresso ma con
    `cuts`/`insertions`/`segments` ricalcolati sulle modifiche applicate
    davvero (i tagli su non-silenzio vengono saltati) + `skipped`.
    """
    def _log(msg: str):
        try:
            if on_log:
                on_log(msg)
        except Exception:
            pass

    try:
        import copy as _copy
        plan = _copy.deepcopy(plan or {})
    except Exception:
        return None
    try:
        if not plan or plan.get("no_change"):
            return None
        cuts = [(float(a), float(b)) for a, b in (plan.get("cuts") or [])]
        insertions = [(float(a), float(d)) for a, d in (plan.get("insertions") or [])]
        if not cuts and not insertions:
            return None
    except Exception:
        return None

    params, samples = _read_wav(in_wav)
    if params is None or samples is None:
        return None
    try:
        nch = max(1, int(params["nchannels"]))
        fr = max(8000, int(params["framerate"]))
    except Exception:
        return None
    try:
        fade_ms = _cfg_int("PAUSE_JOIN_FADE_MS", 12)
        fade_frames = max(1, int(fr * max(1, fade_ms) / 1000.0))
    except Exception:
        fade_frames = max(1, int(fr * 0.012))

    total_frames = len(samples) // nch

    def _f(t: float) -> int:
        try:
            return max(0, min(total_frames, int(round(float(t) * fr))))
        except Exception:
            return 0

    # --- 1. Tagli: verifica silenzio, costruisci pezzi keep (frame src) ---
    pieces: list[tuple[int, int]] = []
    eff_cuts: list[tuple[float, float]] = []
    skipped = 0
    cur = 0
    for (c0, c1) in sorted(cuts, key=lambda p: p[0]):
        f0, f1 = _f(c0), _f(c1)
        if f1 - f0 < max(4, fade_frames):
            skipped += 1
            continue
        m = max(1, fade_frames)
        rms = _rms_dbfs(samples, (f0 + m) * nch, (f1 - m) * nch)
        if rms >= -45.0:
            skipped += 1
            _log(f"[Pause] salto taglio {c0:.2f}-{c1:.2f}s (non silenzio: {rms:.1f} dBFS)")
            continue
        pieces.append((cur, f0))
        eff_cuts.append((c0, c1))
        cur = f1
    pieces.append((cur, total_frames))

    # --- 2. Fade per giunzione (esatti) + cucitura keep ---
    n_joins = max(0, len(pieces) - 1)
    join_f: list[int] = []
    for k in range(n_joins):
        len_l = pieces[k][1] - pieces[k][0]
        len_r = pieces[k + 1][1] - pieces[k + 1][0]
        join_f.append(max(1, min(fade_frames, len_l, len_r)) if min(len_l, len_r) > 1 else 0)

    out = array.array("h")
    # Segmenti esatti (secondi src → dst) sulle zone keep nette.
    segments: list[tuple[float, float, float]] = []
    dst_f = 0
    for k, (p0, p1) in enumerate(pieces):
        head_cons = join_f[k - 1] if k > 0 else 0
        tail_cons = join_f[k] if k < n_joins else 0
        keep0, keep1 = p0 + head_cons, p1 - tail_cons
        if keep1 > keep0:
            out.extend(samples[keep0 * nch:keep1 * nch])
            segments.append((keep0 / fr, keep1 / fr, dst_f / fr))
            dst_f += keep1 - keep0
        if k < n_joins and join_f[k] > 0:
            f = join_f[k]
            tail = samples[(pieces[k][1] - f) * nch:pieces[k][1] * nch]
            head = samples[pieces[k + 1][0] * nch:(pieces[k + 1][0] + f) * nch]
            out.extend(_blend_frames(tail, head, f, nch))
            dst_f += f

    # --- 3. Inserimenti (splice con bed sfumato, posizioni via mappa esatta) ---
    def _map_frames(src_f: int) -> int:
        """Src frame → out frame (prima degli inserimenti, via segments)."""
        t = src_f / fr
        for (s0, s1, d0) in segments:
            if s0 <= t <= s1:
                return int(round((d0 + (t - s0)) * fr))
            if t < s0:
                return int(round(d0 * fr))
        if segments:
            s0, s1, d0 = segments[-1]
            return int(round((d0 + (s1 - s0)) * fr))
        return 0

    eff_ins: list[tuple[float, float]] = []
    ins_applied_frames: list[tuple[int, int]] = []  # (out_pos_pre, need_frames)
    # Applica in ordine di anchor crescente tenendo l'offset cumulato.
    acc = 0
    for (anchor_t, dur_s) in sorted(insertions, key=lambda p: p[0]):
        try:
            need = max(1, int(round(float(dur_s) * fr)))
        except (TypeError, ValueError):
            continue
        at = max(0, min(len(out) // nch, _map_frames(_f(anchor_t)) + acc))
        bed = _quiet_bed(samples, nch, fr, need)
        if bed is None:
            bed = array.array("h", [0] * (need * nch))
            bed = _fade_edges(bed, nch, fr, 10)
        else:
            bed = _fade_edges(bed, nch, fr, 5)
        head = out[:at * nch]
        tail = out[at * nch:]
        new = array.array("h", head)
        new.extend(bed)
        new.extend(tail)
        out = new
        # Posizione pre-insert (timeline senza inserimenti) per lo shift segmenti.
        ins_applied_frames.append((at - acc, need))
        acc += need
        eff_ins.append((float(anchor_t), float(dur_s)))

    if not eff_cuts and not eff_ins:
        return None
    try:
        if not _write_wav(out_wav, params, out):
            return None
    except Exception:
        return None

    # --- 4. Piano effettivo (segmenti ESATTI: fade di giunzione + insert) ---
    # I segmenti dello step 2 sono esatti al campione (tengono conto dei fade
    # che accorciano l'output); qui si aggiunge solo lo shift degli inserimenti.
    try:
        final_segments: list[tuple[float, float, float]] = []
        for (s0, s1, d0) in segments:
            try:
                d0f = float(d0) * fr
                shift = sum(need for (at, need) in ins_applied_frames if at <= d0f + 1)
                final_segments.append((float(s0), float(s1), float(d0) + shift / fr))
            except Exception:
                final_segments.append((float(s0), float(s1), float(d0)))
        if final_segments:
            segments = final_segments
        dst_dur = len(out) // nch / fr
    except Exception:
        try:
            dst_dur = len(out) // nch / fr
        except Exception:
            dst_dur = 0.0
    eff = dict(plan)
    eff["cuts"] = sorted(eff_cuts)
    eff["insertions"] = sorted(eff_ins)
    eff["segments"] = segments
    try:
        eff["dst_duration"] = float(dst_dur)
    except Exception:
        pass
    eff["skipped"] = skipped
    eff["no_change"] = False
    return eff


def _enforce_monotonic(words: list[dict]) -> None:
    """Garantisce start<end e monotonia (come core/alignment)."""
    try:
        prev_end = 0.0
        for w in words:
            try:
                if float(w.get("start", 0.0)) < prev_end:
                    w["start"] = prev_end
                if float(w.get("end", 0.0)) <= float(w.get("start", 0.0)):
                    w["end"] = float(w.get("start", 0.0)) + 0.05
                prev_end = float(w["end"])
            except (TypeError, ValueError):
                continue
    except Exception:
        pass


def retime_words(words: list[dict] | None, plan: dict | None) -> list[dict]:
    """Applica map_time alle parole UNA sola volta (additivo, mai eccezioni).

    Aggiunge `orig_start`/`orig_end`, aggiorna `start`/`end`, garantisce
    `start < end` e monotonia. Con piano vuoto/None: ritorna copia invariata.
    """
    try:
        ws = [dict(w) for w in (words or [])]
    except Exception:
        return []
    try:
        if not plan or plan.get("no_change") or not plan.get("segments"):
            return ws
        from core.pause_planner import map_time as _map
        for w in ws:
            try:
                s = float(w.get("start", 0.0))
                e = float(w.get("end", s))
                if "orig_start" not in w:
                    w["orig_start"] = s
                if "orig_end" not in w:
                    w["orig_end"] = e
                w["start"] = _map(s, plan)
                w["end"] = _map(e, plan)
            except (TypeError, ValueError):
                continue
        _enforce_monotonic(ws)
        return ws
    except Exception:
        try:
            return [dict(w) for w in (words or [])]
        except Exception:
            return []
