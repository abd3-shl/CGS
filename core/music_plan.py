"""
Piano musicale deterministico (Background Music — Fase 3).

LOGICA PURA: niente I/O, niente ffmpeg, niente config importata a runtime
(la config arriva come dict `cfg`, con default di questo modulo).
Testabile con solo `unittest`.

Il guadagno assoluto al tempo t è:
    gain_db(t) = voice_lufs + offset_sezione(t) − track_lufs + modulazioni(t)
così il rapporto voce/musica è costante qualunque siano voce e traccia.
"""

from __future__ import annotations


# Default allineati a spec §4.2 / §5 (sovrascrivibili via cfg dict).
DEFAULTS: dict = {
    "MUSIC_OFFSET_HOOK_LU": -17.0,
    "MUSIC_OFFSET_BODY_LU": -20.0,
    "MUSIC_OFFSET_CTA_LU": -18.0,
    "MUSIC_CTA_RAMP_S": 0.6,
    "MUSIC_PAUSE_MIN_S": 0.35,
    "MUSIC_PAUSE_BOOST_DB": 4.0,
    "MUSIC_PAUSE_ATTACK_S": 0.12,
    "MUSIC_PAUSE_RELEASE_S": 0.25,
    "MUSIC_PAUSE_MIN_GAP_S": 0.8,  # anti-pumping: max una modulazione ogni 0.8 s
    "MUSIC_HERO_DIP_DB": -4.0,
    "MUSIC_HERO_DIP_S": 0.35,
    "MUSIC_HERO_DOWN_S": 0.06,
    "MUSIC_HERO_UP_S": 0.25,
    "MUSIC_FADE_IN_S": 0.8,
    "MUSIC_FADE_OUT_S": 2.0,
    "MUSIC_SHORT_VIDEO_S": 8.0,  # sotto: fade 0.4/1.0, nessun dip hero
    "MUSIC_SHORT_FADE_IN_S": 0.4,
    "MUSIC_SHORT_FADE_OUT_S": 1.0,
    "MUSIC_MAX_GAIN_DB": 6.0,
    "MUSIC_MIN_GAIN_DB": -40.0,
    "MUSIC_MAX_KEYFRAMES": 40,
    "MUSIC_FUSE_S": 0.08,  # keyframe più vicini vengono fusi
    "MUSIC_OUTRO_TAIL_S": 0.0,
}


def _cfg(cfg: dict | None, key: str) -> float:
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
    return float(DEFAULTS[key])


def _words_sorted(words: list[dict] | None) -> list[dict]:
    try:
        ws = [w for w in (words or []) if isinstance(w, dict)]
        return sorted(ws, key=lambda w: (float(w.get("start", 0.0)), float(w.get("end", 0.0))))
    except Exception:
        return []


def _section_bounds(chunks: list[dict] | None) -> tuple[float | None, float | None]:
    """Ritorna (hook_end, cta_start). None se non determinabili."""
    hook_end: float | None = None
    cta_start: float | None = None
    try:
        for ch in (chunks or []):
            if not isinstance(ch, dict):
                continue
            role = str(ch.get("narrative_role", "") or "").lower()
            try:
                s = float(ch.get("start", 0.0))
                e = float(ch.get("end", s))
            except (TypeError, ValueError):
                continue
            if role == "hook":
                hook_end = e if hook_end is None else max(hook_end, e)
            if role == "cta" or bool(ch.get("cta_card")):
                cta_start = s if cta_start is None else min(cta_start, s)
    except Exception:
        pass
    return hook_end, cta_start


def _is_hero_word(w: dict) -> bool:
    try:
        if bool(w.get("is_hero")) or bool(w.get("sfx_trigger")):
            return True
        tier = str(w.get("tier", "") or "").upper()
        if tier == "T3":
            return True
    except Exception:
        pass
    return False


def _hero_words(chunks: list[dict] | None, words: list[dict] | None) -> list[float]:
    """Tempi di inizio delle parole hero (deduplicati < 0.5 s)."""
    times: list[float] = []
    try:
        for w in _words_sorted(words):
            if _is_hero_word(w):
                try:
                    times.append(float(w.get("start", 0.0)))
                except (TypeError, ValueError):
                    continue
        for ch in (chunks or []):
            try:
                if not isinstance(ch, dict):
                    continue
                for s in (ch.get("styled_words") or []):
                    if isinstance(s, dict) and (bool(s.get("is_hero")) or bool(s.get("sfx_trigger"))):
                        times.append(float(ch.get("start", 0.0)))
                        break
            except Exception:
                continue
    except Exception:
        pass
    times = sorted(t for t in times if t >= 0.0)
    dedup: list[float] = []
    for t in times:
        if not dedup or t - dedup[-1] >= 0.5:
            dedup.append(t)
    return dedup


def build_music_plan(
    chunks: list[dict] | None,
    words: list[dict] | None,
    duration_s: float,
    track_info: dict | None,
    voice_lufs: float | None,
    cfg: dict | None = None,
) -> dict:
    """Costruisce il MusicPlan (dict). Mai eccezioni: al peggio piano piatto."""
    try:
        duration = max(1.0, float(duration_s))
    except (TypeError, ValueError):
        duration = 10.0
    try:
        track_lufs = float((track_info or {}).get("lufs", -14.0))
    except (TypeError, ValueError):
        track_lufs = -14.0
    try:
        vlufs = float(voice_lufs) if voice_lufs is not None else -16.0
    except (TypeError, ValueError):
        vlufs = -16.0

    off_hook = _cfg(cfg, "MUSIC_OFFSET_HOOK_LU")
    off_body = _cfg(cfg, "MUSIC_OFFSET_BODY_LU")
    off_cta = _cfg(cfg, "MUSIC_OFFSET_CTA_LU")
    cta_ramp = max(0.1, _cfg(cfg, "MUSIC_CTA_RAMP_S"))
    pause_min = max(0.05, _cfg(cfg, "MUSIC_PAUSE_MIN_S"))
    pause_boost = abs(_cfg(cfg, "MUSIC_PAUSE_BOOST_DB"))
    pause_att = max(0.02, _cfg(cfg, "MUSIC_PAUSE_ATTACK_S"))
    pause_rel = max(0.02, _cfg(cfg, "MUSIC_PAUSE_RELEASE_S"))
    pause_gap = max(0.1, _cfg(cfg, "MUSIC_PAUSE_MIN_GAP_S"))
    hero_dip = -abs(_cfg(cfg, "MUSIC_HERO_DIP_DB"))
    hero_dur = max(0.1, _cfg(cfg, "MUSIC_HERO_DIP_S"))
    hero_down = max(0.02, _cfg(cfg, "MUSIC_HERO_DOWN_S"))
    hero_up = max(0.05, _cfg(cfg, "MUSIC_HERO_UP_S"))
    short_thr = _cfg(cfg, "MUSIC_SHORT_VIDEO_S")
    fi = _cfg(cfg, "MUSIC_FADE_IN_S")
    fo = _cfg(cfg, "MUSIC_FADE_OUT_S")
    short_video = duration < short_thr
    if short_video:
        fi = _cfg(cfg, "MUSIC_SHORT_FADE_IN_S")
        fo = _cfg(cfg, "MUSIC_SHORT_FADE_OUT_S")
    fi = max(0.1, min(fi, duration / 2))
    fo = max(0.2, min(fo, duration / 2))
    gmax = _cfg(cfg, "MUSIC_MAX_GAIN_DB")
    gmin = _cfg(cfg, "MUSIC_MIN_GAIN_DB")
    gmin, gmax = (min(gmin, gmax), max(gmin, gmax))
    max_kf = max(8, int(_cfg(cfg, "MUSIC_MAX_KEYFRAMES")))
    fuse_s = max(0.01, _cfg(cfg, "MUSIC_FUSE_S"))

    hook_end, cta_start = _section_bounds(chunks)
    ws = _words_sorted(words)
    try:
        last_word_end = max(float(w.get("end", 0.0)) for w in ws) if ws else duration
    except Exception:
        last_word_end = duration

    # Fade-out: mai prima dell'ultima parola se lascerebbe > 1 s di voce su fade.
    fade_out_start = duration - fo
    try:
        if last_word_end > 0 and fade_out_start < last_word_end - 1.0:
            fade_out_start = max(0.0, last_word_end - 1.0)
            fo = max(0.2, duration - fade_out_start)
    except Exception:
        pass

    norm = vlufs - track_lufs  # track_gain_db: normalizzazione traccia -> voce

    def base_offset(t: float) -> float:
        # Hook dall'inizio fino a hook_end (se noto), poi body, poi CTA con rampa.
        if hook_end is not None and t < hook_end:
            base = off_hook
        else:
            base = off_body
        if cta_start is not None and t >= cta_start:
            if t < cta_start + cta_ramp:
                k = (t - cta_start) / cta_ramp
                # Rampa morbida body -> CTA.
                base = off_body + (off_cta - off_body) * (k * k * (3 - 2 * k))
            else:
                base = off_cta
        return base

    def base_gain(t: float) -> float:
        return norm + base_offset(t)

    kf: list[list[float]] = []  # [t, gain]
    events: list[dict] = []

    def add_kf(t: float, g: float):
        try:
            t = max(0.0, min(duration, float(t)))
            g = max(gmin, min(gmax, float(g)))
        except (TypeError, ValueError):
            return
        kf.append([t, g])

    # Ancoraggi di sezione (garantiscono la rampa CTA e i bordi hook/body).
    add_kf(0.0, base_gain(0.0))
    if hook_end is not None and 0.0 < hook_end < duration:
        add_kf(hook_end - 0.001, norm + off_hook)
        add_kf(hook_end, base_gain(hook_end))
        events.append({"type": "section", "name": "hook_end", "t": round(hook_end, 3)})
    if cta_start is not None and 0.0 < cta_start < duration:
        add_kf(max(0.0, cta_start - 0.001), base_gain(max(0.0, cta_start - 0.001)))
        add_kf(cta_start, base_gain(cta_start))
        if cta_start + cta_ramp < duration:
            add_kf(cta_start + cta_ramp, base_gain(cta_start + cta_ramp))
        events.append({"type": "section", "name": "cta_start", "t": round(cta_start, 3)})

    # Pause tra parole: boost con attacco/rilascio (anti-pumping: max 1 ogni pause_gap).
    last_pause_t = -1e9
    pause_count = 0
    try:
        for a, b in zip(ws, ws[1:]):
            try:
                gap_start = float(a.get("end", 0.0))
                gap_end = float(b.get("start", gap_start))
            except (TypeError, ValueError):
                continue
            gap = gap_end - gap_start
            if gap < pause_min:
                continue
            if gap_start - last_pause_t < pause_gap:
                continue
            if gap_end <= 0.05 or gap_start >= duration - 0.05:
                continue
            last_pause_t = gap_start
            pause_count += 1
            g0 = base_gain(gap_start)
            g1 = base_gain(gap_end)
            # Salita rapida a inizio pausa, tenuta, discesa all'ingresso parola.
            add_kf(gap_start, g0)
            add_kf(gap_start + min(pause_att, gap / 3), g0 + pause_boost)
            add_kf(max(gap_start + min(pause_att, gap / 3), gap_end - 0.02), g1 + pause_boost)
            add_kf(min(duration, gap_end + pause_rel), g1)
            events.append({"type": "pause", "t": round(gap_start, 3), "dur": round(gap, 3)})
    except Exception:
        pass

    # Dip hero (saltati su video brevi).
    hero_count = 0
    if not short_video:
        try:
            for hs in _hero_words(chunks, words):
                half = hero_dur / 2
                t0 = hs - half
                t1 = t0 + hero_down
                t3 = hs + half
                t2 = t3 - hero_up
                if t3 <= 0.05 or t0 >= duration - 0.05:
                    continue
                gb = base_gain(max(0.0, min(duration, hs)))
                add_kf(t0, gb)
                add_kf(t1, gb + hero_dip)
                if t2 > t1 + 0.02:
                    add_kf(t2, gb + hero_dip)
                add_kf(t3, base_gain(max(0.0, min(duration, t3))))
                hero_count += 1
                events.append({"type": "hero", "t": round(hs, 3)})
        except Exception:
            pass

    add_kf(duration, base_gain(duration))

    # Ordina, fondi keyframe troppo vicini (< fuse_s: sposta in avanti, resta monotono).
    kf.sort(key=lambda p: (p[0], p[1]))
    fused: list[list[float]] = []
    for t, g in kf:
        if fused and t - fused[-1][0] < fuse_s:
            t = fused[-1][0] + fuse_s
            if t > duration:
                # Fondi davvero: tieni il guadagno più estremo.
                prev = fused[-1]
                fused[-1] = [prev[0], g if abs(g - base_gain(prev[0])) > abs(prev[1] - base_gain(prev[0])) else prev[1]]
                continue
        fused.append([round(t, 3), round(g, 2)])
    # Decimazione greedy sopra max_kf (toglie il punto con errore minore).
    while len(fused) > max_kf:
        best_i, best_err = -1, None
        for i in range(1, len(fused) - 1):
            t0, g0 = fused[i - 1]
            t1, g1 = fused[i]
            t2, g2 = fused[i + 1]
            try:
                interp = g0 + (g2 - g0) * ((t1 - t0) / (t2 - t0) if t2 > t0 else 0.0)
            except Exception:
                interp = g0
            err = abs(g1 - interp)
            # Non togliere mai gli ancoraggi di sezione/pause/hero (sono in events).
            protected = any(abs(e.get("t", -1) - t1) < 0.12 for e in events)
            if protected:
                err += 50.0
            if best_err is None or err < best_err:
                best_err, best_i = err, i
        if best_i < 0:
            break
        fused.pop(best_i)

    loop = False
    try:
        loop = bool(track_info) and float((track_info or {}).get("duration", duration + 1)) < duration + fo * 0.5
    except Exception:
        loop = False

    plan = {
        "track_gain_db": round(norm, 2),
        "keyframes": [[t, g] for t, g in fused],
        "fade_in_s": round(fi, 3),
        "fade_out_s": round(fo, 3),
        "fade_out_start_s": round(fade_out_start, 3),
        "events": events,
        "loop": loop,
        "voice_lufs": vlufs,
        "track_lufs": track_lufs,
        "duration_s": duration,
        "offsets_lu": {"hook": off_hook, "body": off_body, "cta": off_cta},
        "pause_count": pause_count,
        "hero_count": hero_count,
    }
    return plan


def gain_at(plan: dict, t: float) -> float:
    """Guadagno assoluto interpolato (per test/debug). Mai eccezioni."""
    try:
        kf = plan.get("keyframes") or []
        t = max(0.0, min(float(plan.get("duration_s", 0.0)), float(t)))
        if not kf:
            return float(plan.get("track_gain_db", 0.0))
        if t <= kf[0][0]:
            return float(kf[0][1])
        for (t0, g0), (t1, g1) in zip(kf, kf[1:]):
            if t <= t1:
                k = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                return float(g0 + (g1 - g0) * k)
        return float(kf[-1][1])
    except Exception:
        return 0.0


def _db_to_lin(g_db: float) -> float:
    """dB -> guadagno lineare per il filtro ffmpeg `volume` (eval=frame)."""
    try:
        return 10.0 ** (float(g_db) / 20.0)
    except Exception:
        return 1.0


def build_gain_expr(plan: dict, max_chars: int = 3500) -> str:
    """Espressione ffmpeg `volume=...:eval=frame` da keyframe.

    IMPORTANTE: `volume` con `eval=frame` valuta l'espressione in guadagno
    LINEARE (non dB: un valore negativo verrebbe clippato). I keyframe in dB
    sono quindi convertiti in lineare e interpolati in lineare; le rampe brevi
    (0.06-0.6 s) restano psicoacusticamente corrette.
    Forma annidata `if(lt(t,t1), l0+(l1-l0)*(t-t0)/(t1-t0), ...)` tra apici singoli
    a cura del chiamante. Se troppo lunga, decimazione interna (mai eccezioni,
    al peggio guadagno costante).
    """
    try:
        kf = [[float(t), _db_to_lin(float(g))] for t, g in (plan.get("keyframes") or [])]
    except Exception:
        kf = []
    try:
        if len(kf) < 2:
            l = kf[0][1] if kf else _db_to_lin(float(plan.get("track_gain_db", 0.0)))
            return f"{l:.6f}"
        # Decima finché entra nel budget (tieni sempre primo e ultimo).
        while len(kf) > 2:
            # Stima rozza: ~64 char per segmento.
            if len(kf) * 64 < max_chars:
                break
            # Toglie il punto interno con errore minore.
            best_i, best_err = -1, None
            for i in range(1, len(kf) - 1):
                t0, g0 = kf[i - 1]
                t1, g1 = kf[i]
                t2, g2 = kf[i + 1]
                interp = g0 + (g2 - g0) * ((t1 - t0) / (t2 - t0) if t2 > t0 else 0.0)
                err = abs(g1 - interp)
                if best_err is None or err < best_err:
                    best_err, best_i = err, i
            if best_i < 0:
                break
            kf.pop(best_i)
            if len(kf) <= 4:
                break
        segs: list[str] = []
        for (t0, g0), (t1, g1) in zip(kf, kf[1:]):
            try:
                dt = t1 - t0
                if dt <= 0:
                    continue
                slope = (g1 - g0) / dt
                segs.append((t1, f"{g0:.6f}+({slope:.6f})*(t-{t0:.3f})"))
            except Exception:
                continue
        if not segs:
            return f"{kf[0][1]:.6f}"
        last_g = kf[-1][1]
        expr = f"{last_g:.6f}"
        for t1, body in reversed(segs):
            expr = f"if(lt(t,{t1:.3f}),{body},{expr})"
        if len(expr) > max_chars:  # ultima rete: costante media
            avg = sum(g for _, g in kf) / len(kf)
            return f"{avg:.6f}"
        return expr
    except Exception:
        try:
            return f"{_db_to_lin(float(plan.get('track_gain_db', 0.0))):.6f}"
        except Exception:
            return "1.000000"
