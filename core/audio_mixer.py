"""
Audio Mixer: voce + SFX + musica di sottofondo (Background Music).

Catena unica ffmpeg per video: voce uniformata (44.1 kHz stereo) con `asplit`
(key separata per il sidechain: un'etichetta ffmpeg non può essere consumata
due volte), musica con inviluppo deterministico (`core/music_plan.py`) +
sidechain residua fine, SFX sintetizzati offline, `alimiter` + `loudnorm`
finale verso -14 LUFS / TP -1.5.

Intermedi in WAV (`pcm_s16le` 44.1 kHz stereo) dentro TEMP_DIR: un solo encode
lossy finale (AAC, nei builder). La voce originale resta per Whisper.

Tutto best-effort con fallback sicuro: qualsiasi errore → voce+SFX (o voce
originale), mai blocca la pipeline. Nessuna eccezione verso i chiamanti
(tranne i tipi già esistenti nei rami legacy).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

try:
    import config as _cfg
    BG_MUSIC_DUCKING_DB = getattr(_cfg, "BG_MUSIC_DUCKING_DB", -12.0)
    ENABLE_AUTO_SFX = getattr(_cfg, "ENABLE_AUTO_SFX", True)
    SFX_VOLUME_DB = getattr(_cfg, "SFX_VOLUME_DB", -15.0)
    TEMP_DIR = getattr(_cfg, "TEMP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp"))
except Exception:  # config datata
    BG_MUSIC_DUCKING_DB = -12.0
    ENABLE_AUTO_SFX = True
    SFX_VOLUME_DB = -15.0
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")


def _ffmpeg() -> str | None:
    try:
        return shutil.which("ffmpeg")
    except Exception:
        return None


def _get_cfg(key: str, default):
    try:
        return getattr(_cfg, key, default)
    except Exception:
        return default


def _ffprobe_duration(path: str) -> float | None:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            return None
        return float(res.stdout.strip())
    except Exception:
        return None


def measure_loudness(path: str) -> dict | None:
    """Misura LUFS integrati / true peak / LRA (solo misura, `-f null`).

    Ritorna {lufs, true_peak, lra, threshold} o None. Mai eccezioni.
    """
    try:
        ff = _ffmpeg()
        if not ff or not path or not os.path.isfile(path):
            return None
        res = subprocess.run(
            [ff, "-hide_banner", "-i", path, "-filter_complex",
             "loudnorm=I=-24:TP=-2:LRA=11:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
        err = res.stderr or ""
        start, end = err.find("{"), err.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(err[start:end + 1])
        out: dict = {}
        try:
            out["lufs"] = float(data.get("input_i"))
        except (TypeError, ValueError):
            return None
        for src, dst in (("input_tp", "true_peak"), ("input_lra", "lra"),
                         ("input_thresh", "threshold")):
            try:
                out[dst] = float(data.get(src))
            except (TypeError, ValueError):
                out[dst] = None
        # Campi measured_* per il secondo passaggio loudnorm.
        try:
            out["measured"] = {
                "measured_I": float(data.get("input_i")),
                "measured_TP": float(data.get("input_tp")),
                "measured_LRA": float(data.get("input_lra")),
                "measured_thresh": float(data.get("input_thresh")),
                "offset": float(data.get("target_offset", 0.0)),
            }
        except (TypeError, ValueError):
            out["measured"] = None
        return out
    except Exception:
        return None


def sfx_events_from_chunks(chunks: list[dict] | None) -> list[tuple[float, str]]:
    """Estrae [(time_sec, kind)] dai chunk arricchiti (mai eccezioni).

    kind: "pop" (T3 hero / sfx_trigger), "whoosh" (ENTRY cambi posa/blocco),
    "click" (CTA card). Timestamp originali preservati (solo lettura).
    Deduplica eventi <80ms per evitare saturazione SFX.
    """
    events: list[tuple[float, str]] = []
    try:
        if not chunks:
            return events
        for ch in chunks:
            try:
                if not isinstance(ch, dict):
                    continue
                t = float(ch.get("start", 0.0))
                # Hero / sfx_trigger diretto (enricher o styled is_hero).
                hero = False
                try:
                    for s in (ch.get("styled_words") or []):
                        if isinstance(s, dict) and (bool(s.get("is_hero")) or bool(s.get("sfx_trigger"))):
                            hero = True
                            break
                    for w in (ch.get("words") or []):
                        if isinstance(w, dict) and bool(w.get("sfx_trigger")):
                            hero = True
                            break
                except Exception:
                    pass
                if hero:
                    events.append((max(0.0, t), "pop"))
                    continue
                # CTA card -> click discreto.
                try:
                    if bool(ch.get("cta_card")):
                        events.append((max(0.0, t), "click"))
                        continue
                except Exception:
                    pass
                # ENTRY macro-blocco -> whoosh morbido.
                try:
                    ev = ""
                    c = ch.get("character")
                    if isinstance(c, dict):
                        ev = str(c.get("event", "") or "").upper()
                    if not ev:
                        ev = str(ch.get("char_event", "") or "").upper()
                    if ev == "ENTRY":
                        events.append((max(0.0, t), "whoosh"))
                except Exception:
                    pass
            except Exception:
                continue
        # Deduplica <80ms (tiene il primo).
        events.sort(key=lambda e: e[0])
        dedup: list[tuple[float, str]] = []
        for tm, kind in events:
            if dedup and abs(tm - dedup[-1][0]) < 0.08:
                continue
            dedup.append((tm, kind))
        return dedup[:24]  # cap: max 24 SFX per video (no saturazione)
    except Exception:
        return []


def _sfx_filter(kind: str, at_sec: float, vol_db: float) -> str:
    """Filtro ffmpeg per un singolo SFX sintetizzato al tempo `at_sec`."""
    try:
        ms = max(0, int(round(float(at_sec) * 1000)))
        vol = max(-40.0, min(0.0, float(vol_db)))
    except Exception:
        ms, vol = 0, -15.0
    try:
        if kind == "pop":
            # Pop breve 880Hz, 90ms, attacco rapido.
            return f"sine=frequency=880:duration=0.09,volume={vol}dB,adelay={ms}|{ms}"
        if kind == "click":
            # Click secco 1400Hz, 50ms.
            return f"sine=frequency=1400:duration=0.05,volume={vol}dB,adelay={ms}|{ms}"
        # whoosh: rumore filtrato 0.25s con fade in/out.
        return (
            f"anoisesrc=color=white:duration=0.25:sample_rate=44100,"
            f"highpass=f=800,lowpass=f=6000,volume={vol - 3.0}dB,"
            f"afade=t=in:st=0:d=0.08,afade=t=out:st=0.17:d=0.08,adelay={ms}|{ms}"
        )
    except Exception:
        return f"sine=frequency=880:duration=0.09,volume=-15dB,adelay={ms}|{ms}"


# ----------------------------------------------------------------------------
# Catena unica voce + SFX + musica


_UNIFORM = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"

_SFX_LAVFI = {
    "pop": "sine=frequency=880:duration=0.09:sample_rate=44100",
    "click": "sine=frequency=1400:duration=0.05:sample_rate=44100",
    "whoosh": "anoisesrc=color=white:duration=0.25:sample_rate=44100",
}


def _sfx_chain(idx: int, kind: str, at_sec: float, vol_db: float) -> str:
    """Catena filtro per un input lavfi SFX (uniforma + volume + adelay)."""
    try:
        ms = max(0, int(round(float(at_sec) * 1000)))
        vol = max(-40.0, min(0.0, float(vol_db)))
    except Exception:
        ms, vol = 0, -15.0
    if kind == "whoosh":
        return (
            f"[{idx}:a]{_UNIFORM},highpass=f=800,lowpass=f=6000,volume={vol - 3.0}dB,"
            f"afade=t=in:st=0:d=0.08,afade=t=out:st=0.17:d=0.08,"
            f"adelay={ms}|{ms}[s{idx}]"
        )
    return f"[{idx}:a]{_UNIFORM},volume={vol}dB,adelay={ms}|{ms}[s{idx}]"


def _music_chain(track_path: str, duration: float, plan: dict | None,
                 voice_lufs: float | None) -> tuple[str, dict]:
    """Catena filtro musica: uniforma + trim lead + loop + inviluppo + fade.

    Ritorna (filter_snippet_con_[mus]_finale, debug_info). Mai eccezioni
    (al peggio inviluppo piatto al gain di normalizzazione).
    """
    dbg: dict = {}
    try:
        from core.music_plan import build_gain_expr, build_music_plan
    except Exception:
        build_gain_expr = None  # type: ignore
        build_music_plan = None  # type: ignore
    try:
        lowcut = float(_get_cfg("MUSIC_LOW_CUT_HZ", 35))
    except Exception:
        lowcut = 35.0
    try:
        presence_db = float(_get_cfg("MUSIC_PRESENCE_CUT_DB", -3.0))
    except Exception:
        presence_db = -3.0
    try:
        fi = float((plan or {}).get("fade_in_s", 0.8))
        fo = float((plan or {}).get("fade_out_s", 2.0))
        fo_start = float((plan or {}).get("fade_out_start_s", max(0.0, duration - 2.0)))
    except Exception:
        fi, fo, fo_start = 0.8, 2.0, max(0.0, duration - 2.0)
    try:
        if build_gain_expr is not None and plan:
            expr = build_gain_expr(plan)
        else:
            expr = f"{float((plan or {}).get('track_gain_db', -6.0)):.2f}"
    except Exception:
        expr = "-6.00"
    dbg["gain_expr_len"] = len(expr)
    try:
        lead = max(0.0, float(((plan or {}).get("track_info") or {}).get("lead_silence", 0.0) or 0.0))
    except Exception:
        lead = 0.0
    # Il trim del silenzio iniziale è applicato con -ss in input (vedi sotto);
    # qui resta solo documentato per il debug.
    dbg["lead_trim_s"] = round(lead if lead >= 0.4 else 0.0, 3)
    parts = [
        f"[1:a]{_UNIFORM}",
        "atrim=0:{:.3f}".format(duration + 0.5),
        "asetpts=PTS-STARTPTS",
        "highpass=f={:.0f}".format(max(20.0, min(200.0, lowcut))),
        "equalizer=f=2800:t=q:w=1.0:g={:.1f}".format(max(-12.0, min(0.0, presence_db))),
        "volume='{expr}':eval=frame".replace("{expr}", expr),
        "afade=t=in:st=0:d={:.3f}:curve=qsin".format(max(0.05, fi)),
        "afade=t=out:st={:.3f}:d={:.3f}:curve=qsin".format(max(0.0, fo_start), max(0.1, fo)),
    ]
    return (",".join(parts) + "[mus]", dbg)


def _sidechain_filter() -> str:
    try:
        thr = float(_get_cfg("MUSIC_SIDECHAIN_THRESHOLD", 0.04))
        ratio = float(_get_cfg("MUSIC_SIDECHAIN_RATIO", 2.5))
        att = int(float(_get_cfg("MUSIC_SIDECHAIN_ATTACK_MS", 15)))
        rel = int(float(_get_cfg("MUSIC_SIDECHAIN_RELEASE_MS", 450)))
    except Exception:
        thr, ratio, att, rel = 0.04, 2.5, 15, 450
    thr = max(0.001, min(1.0, thr))
    ratio = max(1.0, min(10.0, ratio))
    att = max(1, min(200, att))
    rel = max(20, min(2000, rel))
    return (f"[mus][v_key]sidechaincompress=threshold={thr}:ratio={ratio}:"
            f"attack={att}:release={rel}:makeup=1[mus_d]")


def _run(cmd: list[str], timeout: int = 600) -> tuple[bool, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0:
            return True, ""
        tail = (res.stderr or "")[-1500:]
        return False, tail
    except Exception as e:
        return False, str(e)[:500]


def mix_audio_with_music(
    voice_path: str,
    chunks: list[dict] | None = None,
    words: list[dict] | None = None,
    music_choice: dict | None = None,
    music_plan: dict | None = None,
    output_path: str | None = None,
    sfx_volume_db: float | None = None,
    voice_lufs: float | None = None,
    duration_s: float | None = None,
    on_log=None,
    debug_stems_dir: str | None = None,
) -> str:
    """Mix unico voce + SFX + musica in WAV. Ritorna path finale o fallback.

    - `music_choice`: dict da `music_selector.choose_track` (path/duration/lufs/...).
    - `music_plan`: dict da `music_plan.build_music_plan` (se None e musica presente,
      piano piatto costruito qui con parole/chunk dati).
    - `debug_stems_dir`: se impostata, esporta `voice.wav`, `music_processed.wav`,
      `mix_final.wav` + `audio_debug.json` e li mantiene.
    Mai eccezioni: al peggio ritorna `voice_path`.
    """
    def _log(msg: str):
        try:
            if on_log:
                on_log(msg)
        except Exception:
            pass

    try:
        if not voice_path or not os.path.isfile(voice_path):
            return voice_path
        ff = _ffmpeg()
        if ff is None:
            return voice_path
        try:
            vol = float(sfx_volume_db) if sfx_volume_db is not None else float(SFX_VOLUME_DB)
        except Exception:
            vol = -15.0
        try:
            enabled = str(os.environ.get("ENABLE_AUTO_SFX", "1" if ENABLE_AUTO_SFX else "0")
                          ).strip().lower() not in ("0", "false", "no", "off", "")
        except Exception:
            enabled = bool(ENABLE_AUTO_SFX)
        try:
            events = sfx_events_from_chunks(chunks) if enabled else []
        except Exception:
            events = []
        try:
            has_music = bool(music_choice) and bool((music_choice or {}).get("path")) \
                and os.path.isfile(str((music_choice or {}).get("path")))
        except Exception:
            has_music = False

        try:
            dur_voice = float(duration_s) if duration_s else _ffprobe_duration(voice_path)
        except Exception:
            dur_voice = None
        if not dur_voice or dur_voice <= 0:
            return voice_path
        duration = float(dur_voice)
        dur_s = f"{duration:.3f}"

        # Voce: misura LUFS (serve al piano) se non fornita.
        vlufs = voice_lufs
        if has_music and vlufs is None:
            try:
                m = measure_loudness(voice_path)
                vlufs = float(m["lufs"]) if m else None
            except Exception:
                vlufs = None
        if vlufs is None:
            vlufs = -16.0

        # Piano: costruisci se assente (piatto se mancano le parole).
        plan = music_plan
        if has_music and not plan:
            try:
                from core.music_plan import build_music_plan as _bmp
                track = dict(music_choice or {})
                try:
                    words_flat = list(words or [])
                    if not words_flat:
                        for ch in (chunks or []):
                            try:
                                words_flat.extend(ch.get("words") or [])
                            except Exception:
                                continue
                    plan = _bmp(chunks, words_flat, duration, track, vlufs, None)
                except Exception:
                    plan = None
            except Exception:
                plan = None
        if has_music and plan is not None:
            try:
                plan = dict(plan)
                plan.setdefault("track_info", music_choice)
            except Exception:
                pass

        try:
            out = output_path or os.path.join(TEMP_DIR, "narration_mix.wav")
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        except Exception:
            return voice_path
        try:
            premaster = os.path.join(TEMP_DIR, "narration_premaster.wav")
        except Exception:
            return voice_path

        # --- Input: 0=voce, 1=musica (loop/trim), 2..=SFX lavfi ---
        cmd_inputs: list[str] = ["-i", voice_path]
        track_path = str((music_choice or {}).get("path")) if has_music else ""
        lead_trim = 0.0
        if has_music:
            try:
                lead_trim = float(((plan or {}).get("track_info") or {}).get("lead_silence", 0.0) or 0.0)
            except Exception:
                lead_trim = 0.0
            if lead_trim < 0.4:
                lead_trim = 0.0
            # Loop: ripeti abbastanza volte da coprire la durata (+margine fade).
            try:
                track_dur = max(1.0, float((music_choice or {}).get("duration", duration)))
            except Exception:
                track_dur = duration
            eff = max(1.0, track_dur - lead_trim)
            import math as _math
            n_loops = max(0, int(_math.ceil((duration + 1.0) / eff)) - 1)
            if lead_trim > 0:
                cmd_inputs += ["-ss", f"{lead_trim:.3f}"]
            if n_loops > 0:
                cmd_inputs += ["-stream_loop", str(min(n_loops, 16))]
            cmd_inputs += ["-i", track_path]
        for (_tm, kind) in events:
            cmd_inputs += ["-f", "lavfi", "-i", _SFX_LAVFI.get(kind, _SFX_LAVFI["pop"])]

        # --- Filtergraph ---
        fc: list[str] = []
        # Voce uniformata + asplit SOLO con musica (FIX bug: etichetta mai
        # consumata due volte; un'uscita asplit scollegata fa fallire ffmpeg).
        if has_music:
            fc.append(f"[0:a]{_UNIFORM},asplit=2[v_main][v_key]")
        else:
            fc.append(f"[0:a]{_UNIFORM}[v_main]")
        sfx_start = 2 if has_music else 1
        for i, (tm, kind) in enumerate(events):
            fc.append(_sfx_chain(sfx_start + i, kind, tm, vol))
        if has_music:
            mus_chain, mus_dbg = _music_chain(track_path, duration, plan, vlufs)
            fc.append(mus_chain)
            fc.append(_sidechain_filter())
            mix_ins = "[v_main][mus_d]" + "".join(f"[s{sfx_start + i}]" for i in range(len(events)))
            n_ins = 2 + len(events)
            fc.append(f"{mix_ins}amix=inputs={n_ins}:duration=longest:normalize=0:dropout_transition=0[mix0]")
        else:
            if events:
                mix_ins = "[v_main]" + "".join(f"[s{sfx_start + i}]" for i in range(len(events)))
                fc.append(f"{mix_ins}amix=inputs={len(events) + 1}:duration=longest:normalize=0:dropout_transition=0[mix0]")
            else:
                fc.append("[v_main]anull[mix0]")
        # Protezione picchi SFX + durata esatta voce.
        fc.append(f"[mix0]alimiter=limit=0.89:attack=7:release=100,atrim=0:{dur_s},asetpts=PTS-STARTPTS[pre]")
        filtergraph = ";".join(fc)

        try:
            target_i = float(_get_cfg("FINAL_LOUDNESS_LUFS", -14.0))
            target_tp = float(_get_cfg("FINAL_TRUE_PEAK_DB", -1.5))
        except Exception:
            target_i, target_tp = -14.0, -1.5

        # Passaggio 1: premaster WAV (no loudnorm).
        cmd1 = [ff, "-y"] + cmd_inputs + [
            "-filter_complex", filtergraph,
            "-map", "[pre]", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
            "-t", dur_s, premaster,
        ]
        ok, err = _run(cmd1)
        if not ok or not os.path.isfile(premaster):
            _log(f"Mix audio fallito ({err[:160]}), uso voce+SFX legacy.")
            try:
                legacy = mix_sfx_legacy(voice_path, chunks, None, sfx_volume_db)
                return legacy or voice_path
            except Exception:
                return voice_path

        # Stems debug: voce uniformata + musica processata (senza sidechain).
        if debug_stems_dir:
            try:
                _export_stems(ff, voice_path, track_path if has_music else None,
                              duration, dur_s, plan, vlufs, debug_stems_dir)
            except Exception:
                pass

        # Passaggio 2: misura premaster; passaggio 3: loudnorm lineare misurato.
        final_lufs, final_tp = None, None
        meas = measure_loudness(premaster)
        if meas and meas.get("measured"):
            m = meas["measured"]
            filt = (f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:"
                    f"measured_I={m['measured_I']:.2f}:measured_TP={m['measured_TP']:.2f}:"
                    f"measured_LRA={m['measured_LRA']:.2f}:measured_thresh={m['measured_thresh']:.2f}:"
                    f"offset={m['offset']:.2f}:linear=true")
            cmd2 = [ff, "-y", "-i", premaster, "-af", filt,
                    "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", "-t", dur_s, out]
            ok2, _ = _run(cmd2)
            if not ok2:
                meas = None
        if not (meas and meas.get("measured")):
            # Fallback: loudnorm singolo passaggio.
            filt1 = f"loudnorm=I={target_i}:TP={target_tp}:LRA=11"
            cmd2 = [ff, "-y", "-i", premaster, "-af", filt1,
                    "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", "-t", dur_s, out]
            ok2, _ = _run(cmd2)
            if not ok2:
                # Ultima rete: premaster così com'è.
                try:
                    shutil.copyfile(premaster, out)
                except Exception:
                    return voice_path
        try:
            if os.path.isfile(premaster) and not debug_stems_dir:
                os.remove(premaster)
        except OSError:
            pass

        # Valida durata (±0.05 s): altrimenti fallback voce+SFX senza musica.
        try:
            d_out = _ffprobe_duration(out)
            if d_out is None or abs(float(d_out) - duration) > 0.06:
                _log("Durata mix non valida, fallback a voce+SFX.")
                try:
                    legacy = mix_sfx_legacy(voice_path, chunks, None, sfx_volume_db)
                    return legacy or voice_path
                except Exception:
                    return voice_path
        except Exception:
            pass
        try:
            post = measure_loudness(out)
            if post:
                final_lufs, final_tp = post.get("lufs"), post.get("true_peak")
        except Exception:
            pass
        try:
            _LAST_STATS["final_lufs"] = final_lufs
            _LAST_STATS["final_tp"] = final_tp
        except Exception:
            pass
        return out
    except Exception:
        try:
            return voice_path
        except Exception:
            return ""


_LAST_STATS: dict = {"final_lufs": None, "final_tp": None}


def last_mix_stats() -> dict:
    """Ultime misure loudness del mix (per log/sidecar). Mai eccezioni."""
    try:
        return dict(_LAST_STATS)
    except Exception:
        return {}


def _export_stems(ff: str, voice_path: str, track_path: str | None, duration: float,
                  dur_s: str, plan: dict | None, vlufs: float, stems_dir: str) -> None:
    """Esporta stem debug: voice.wav, music_processed.wav (+ audio_debug.json dal chiamante)."""
    try:
        os.makedirs(stems_dir, exist_ok=True)
        cmd_v = [ff, "-y", "-i", voice_path, "-af", _UNIFORM,
                 "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                 "-t", dur_s, os.path.join(stems_dir, "voice.wav")]
        _run(cmd_v)
        if track_path and os.path.isfile(track_path):
            mus_chain, _ = _music_chain(track_path, duration, plan, vlufs)
            # Stessa catena senza sidechain (musica processata con inviluppo).
            cmd_m = [ff, "-y", "-i", track_path, "-filter_complex", mus_chain,
                     "-map", "[mus]", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                     "-t", dur_s, os.path.join(stems_dir, "music_processed.wav")]
            _run(cmd_m)
    except Exception:
        pass


def mix_sfx_legacy(
    narration_path: str,
    chunks: list[dict] | None = None,
    output_path: str | None = None,
    sfx_volume_db: float | None = None,
) -> str:
    """Mix voce+SFX in WAV (nessuna musica). Ritorna path o `narration_path`."""
    try:
        if not narration_path or not os.path.isfile(narration_path):
            return narration_path
        ff = _ffmpeg()
        if ff is None:
            return narration_path
        try:
            vol = float(sfx_volume_db) if sfx_volume_db is not None else float(SFX_VOLUME_DB)
        except Exception:
            vol = -15.0
        try:
            events = sfx_events_from_chunks(chunks)
        except Exception:
            events = []
        if not events:
            return narration_path
        try:
            dur = _ffprobe_duration(narration_path)
        except Exception:
            dur = None
        if not dur or dur <= 0:
            return narration_path
        dur_s = f"{float(dur):.3f}"
        try:
            out = output_path or os.path.join(TEMP_DIR, "narration_sfx.wav")
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        except Exception:
            return narration_path
        cmd_inputs: list[str] = ["-i", narration_path]
        for (_tm, kind) in events:
            cmd_inputs += ["-f", "lavfi", "-i", _SFX_LAVFI.get(kind, _SFX_LAVFI["pop"])]
        fc = [f"[0:a]{_UNIFORM}[v_main]"]
        for i, (tm, kind) in enumerate(events):
            fc.append(_sfx_chain(1 + i, kind, tm, vol))
        mix_ins = "[v_main]" + "".join(f"[s{1 + i}]" for i in range(len(events)))
        fc.append(f"{mix_ins}amix=inputs={len(events) + 1}:duration=longest:normalize=0:dropout_transition=0[mix0]")
        fc.append(f"[mix0]alimiter=limit=0.89:attack=7:release=100,atrim=0:{dur_s},asetpts=PTS-STARTPTS[pre]")
        cmd = [ff, "-y"] + cmd_inputs + [
            "-filter_complex", ";".join(fc),
            "-map", "[pre]", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
            "-t", dur_s, out,
        ]
        ok, _ = _run(cmd)
        if ok and os.path.isfile(out):
            return out
        return narration_path
    except Exception:
        try:
            return narration_path
        except Exception:
            return ""


def mix_sfx(
    narration_path: str,
    chunks: list[dict] | None = None,
    output_path: str | None = None,
    sfx_volume_db: float | None = None,
    bg_music_path: str | None = None,
    bg_ducking_db: float | None = None,
    music_plan: dict | None = None,
    words: list[dict] | None = None,
) -> str:
    """Mix voce + SFX (+ musica opzionale). Ritorna path audio finale.

    Firma retrocompatibile: i vecchi chiamanti `mix_sfx(voce, chunks)` restano
    invariati (voce+SFX in WAV). Con `bg_music_path` (o `music_plan`) delega al
    motore unico `mix_audio_with_music` (FIX: il vecchio ramo musica riusava
    etichette già consumate e puntava l'input sbagliato `[2:a]`).

    `bg_ducking_db` è mantenuto come alias deprecato: se impostato esplicitamente
    e gli offset MUSIC_* non sono in config, sposta tutti gli offset di sezione.
    """
    try:
        try:
            enabled = str(os.environ.get("ENABLE_AUTO_SFX", "1" if ENABLE_AUTO_SFX else "0")
                          ).strip().lower() not in ("0", "false", "no", "off", "")
        except Exception:
            enabled = bool(ENABLE_AUTO_SFX)
        ff = _ffmpeg()
        if not enabled or ff is None:
            return narration_path
        try:
            has_music = bool(bg_music_path) and os.path.isfile(str(bg_music_path))
        except Exception:
            has_music = False
        if has_music:
            # Alias deprecato BG_MUSIC_DUCKING_DB: applicato come shift uniforme
            # solo se l'utente lo ha personalizzato (default -12 = invariato).
            plan = music_plan
            try:
                duck = float(bg_ducking_db) if bg_ducking_db is not None else float(BG_MUSIC_DUCKING_DB)
            except Exception:
                duck = -12.0
            if plan is not None:
                try:
                    plan = dict(plan)
                except Exception:
                    plan = None
            choice = {"path": str(bg_music_path), "duration": None, "lufs": None}
            try:
                from core.music_selector import analyze_track as _an
                info = _an(str(bg_music_path))
                if info:
                    choice.update(info)
            except Exception:
                pass
            # Se il piano manca, costruiscilo qui (parole dai chunk).
            if plan is None:
                try:
                    from core.music_plan import build_music_plan as _bmp
                    wflat: list[dict] = list(words or [])
                    if not wflat:
                        for ch in (chunks or []):
                            try:
                                wflat.extend((ch or {}).get("words") or [])
                            except Exception:
                                continue
                    dur = _ffprobe_duration(narration_path)
                    meas = measure_loudness(narration_path)
                    vl = float(meas["lufs"]) if meas else -16.0
                    # Shift da alias deprecato: -12 default -> shift 0.
                    shift = 0.0
                    try:
                        if abs(float(duck) - (-12.0)) > 1e-9:
                            shift = float(duck) - (-12.0)
                    except Exception:
                        shift = 0.0
                    cfg_shift = None
                    if abs(shift) > 1e-9:
                        try:
                            cfg_shift = {"MUSIC_OFFSET_HOOK_LU": -17.0 + shift,
                                         "MUSIC_OFFSET_BODY_LU": -20.0 + shift,
                                         "MUSIC_OFFSET_CTA_LU": -18.0 + shift}
                        except Exception:
                            cfg_shift = None
                    plan = _bmp(chunks, wflat, float(dur or 10.0), choice, vl, cfg_shift)
                except Exception:
                    plan = None
            return mix_audio_with_music(narration_path, chunks, words, choice, plan,
                                        output_path, sfx_volume_db)
        # Nessuna musica: voce+SFX in WAV.
        if output_path and str(output_path).lower().endswith(".mp3"):
            try:
                output_path = str(output_path)[:-4] + ".wav"
            except Exception:
                output_path = None
        return mix_sfx_legacy(narration_path, chunks, output_path, sfx_volume_db)
    except Exception:
        try:
            return narration_path
        except Exception:
            return ""
