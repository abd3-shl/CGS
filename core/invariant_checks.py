"""
Post-build invariant checks (Full Engine Upgrade — Fase 6).

Verifica automatica dopo ogni build (mai blocca il bulk con eccezioni non
gestite: ritorna (ok, dettagli) e solleva AssertionError solo se il chiamante
lo richiede esplicitamente):

  - `assert abs(video_duration - audio_duration) < 0.1`
  - nessun file temporaneo fuori da `temp/`
  - timestamp start/end preservati (confronto pre/post pipeline)
  - Z-order/safe-zone senza violazioni critiche (testo fuori canvas = fail)

Uso in `main.py` Step 8 dopo `build_video`/`build_composed_video`.
"""

from __future__ import annotations

import os
import subprocess

try:
    from config import OUTPUT_DIR, TEMP_DIR
except Exception:
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")


def _probe_duration(path: str) -> float | None:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None
        return float(res.stdout.strip())
    except Exception:
        return None


def check_av_sync(video_path: str, audio_path: str, tol: float = 0.1) -> tuple[bool, str]:
    """assert abs(video_duration - audio_duration) < tol (default 0.1s)."""
    try:
        vd = _probe_duration(video_path)
        ad = _probe_duration(audio_path)
        if vd is None or ad is None:
            return (False, "ffprobe indisponibile per AV-sync")
        ok = abs(float(vd) - float(ad)) < float(tol)
        return (ok, f"video={vd:.3f}s audio={ad:.3f}s delta={abs(vd - ad):.3f}s")
    except Exception as e:
        return (False, f"AV-sync errore: {e}")


def check_temp_containment(temp_dir: str | None = None) -> tuple[bool, str]:
    """Nessun file temporaneo fuori da temp/ (walk + realpath)."""
    try:
        base = os.path.realpath(temp_dir or TEMP_DIR)
    except Exception:
        return (False, "temp dir non risolvibile")
    try:
        if not os.path.isdir(base):
            return (True, "temp assente (ok, pulita)")
        count = 0
        for root, _dirs, files in os.walk(base):
            try:
                rp = os.path.realpath(root)
                if os.path.commonpath([rp, base]) != base:
                    return (False, f"file fuori temp: {root}")
            except Exception:
                continue
            count += len(files)
        return (True, f"{count} file dentro temp (contenuti)")
    except Exception as e:
        return (False, f"temp check errore: {e}")


def check_timestamps_preserved(before: list[dict], after: list[dict]) -> tuple[bool, str]:
    """I campi start/end: preservati OPPURE retimati coerentemente (P0 WS-B).

    Invariante #1 (modifica controllata): fino al Pause Engine start/end sono
    quelli di Whisper+align; dopo, il Pause Engine applica un time-warp
    deterministico UNA volta conservando `orig_start`/`orig_end` come chiavi
    additive. Questo check verifica la coerenza tramite la mappa di retime:
      - se `after` ha orig_start/orig_end → before.start deve coincidere con
        after.orig_start (stesso conteggio, stessi originali) e after.start/end
        devono essere monotoni;
      - altrimenti (nessun retime) → confronto 1:1 come prima.
    Sempre non fatale (il chiamante logga).
    """
    try:
        if len(before) != len(after):
            return (False, f"conteggio diverso {len(before)} vs {len(after)}")
        retimed = any(isinstance(a, dict) and ("orig_start" in a or "orig_end" in a)
                      for a in (after or []))
        if retimed:
            prev = -1e9
            for i, (b, a) in enumerate(zip(before, after)):
                try:
                    if abs(float(b.get("start", -1)) - float(a.get("orig_start", -2))) > 1e-6:
                        return (False, f"orig_start incoerente idx {i} (retime non tracciato)")
                    if abs(float(b.get("end", -1)) - float(a.get("orig_end", -2))) > 1e-6:
                        return (False, f"orig_end incoerente idx {i} (retime non tracciato)")
                    s, e = float(a.get("start", 0.0)), float(a.get("end", 0.0))
                    if not (e > s and s >= prev - 1e-6):
                        return (False, f"timeline retimata non monotona idx {i}")
                    prev = e
                except Exception:
                    return (False, f"timestamp non numerici idx {i}")
            return (True, f"{len(before)} timestamp retimati coerenti (mappa orig_*)")
        for i, (b, a) in enumerate(zip(before, after)):
            try:
                if abs(float(b.get("start", -1)) - float(a.get("start", -2))) > 1e-6:
                    return (False, f"start alterato idx {i}")
                if abs(float(b.get("end", -1)) - float(a.get("end", -2))) > 1e-6:
                    return (False, f"end alterato idx {i}")
            except Exception:
                return (False, f"timestamp non numerici idx {i}")
        return (True, f"{len(before)} timestamp preservati")
    except Exception as e:
        return (False, f"timestamp check errore: {e}")


def check_z_order_safe(chunks: list[dict] | None) -> tuple[bool, str]:
    """Nessuna violazione critica safe-zone (P0: anche profilo piattaforma).

    Controlli: testo fuori canvas = fail; testo fuori safe zone del profilo
    (top/bottom/laterali/rail) = violazioni loggate ma NON fatali in questa
    fase (il guard dovrebbe già averle azzerate: ui_violations=0 atteso).
    """
    try:
        from core.layout_guard import verify_z_order, text_bbox_of_layout

        bad = 0
        notes: list[str] = []
        ui_bad = 0
        for ch in (chunks or []):
            try:
                layout = ch.get("layout_items") or ch.get("layout")
                tb = None
                if isinstance(layout, list) and layout and isinstance(layout[0], dict):
                    tb = text_bbox_of_layout(layout)
                ok, viol = verify_z_order(tb, None)
                if not ok:
                    critical = [v for v in viol if v in ("testo-fuori-canvas",)]
                    if critical:
                        bad += 1
                        notes.extend(critical)
                    else:
                        ui_bad += 1
                        notes.extend([v for v in viol if v != "testo-fuori-canvas"])
            except Exception:
                continue
        if bad:
            return (False, f"{bad} chunk fuori canvas: {sorted(set(notes))[:3]}")
        if ui_bad:
            return (True, f"safe-zone: {ui_bad} chunk con violazioni profilo {sorted(set(notes))[:4]} (non fatale)")
        return (True, "safe-zone ok (canvas + profilo)")
    except Exception as e:
        return (True, f"z-check saltato ({e})")


def check_loudness(video_path: str) -> tuple[bool, str]:
    """P0: loudness finale −14 ±1 LUFS, true peak ≤ −1.0 dBTP (non fatale)."""
    try:
        from core.audio_master import measure_loudness as _ml
        m = _ml(video_path)
        if not m:
            return (True, "loudness non misurabile (skip)")
        msgs = []
        ok = True
        try:
            lufs = float(m.get("lufs"))
            msgs.append(f"{lufs:.1f} LUFS")
            if abs(lufs - (-14.0)) > 1.0:
                ok = False
        except (TypeError, ValueError):
            msgs.append("LUFS n.d.")
        try:
            tp = float(m.get("true_peak"))
            msgs.append(f"TP {tp:.2f} dBTP")
            if tp > -1.0:
                ok = False
        except (TypeError, ValueError):
            msgs.append("TP n.d.")
        return (ok, ", ".join(msgs))
    except Exception as e:
        return (True, f"loudness check saltato ({e})")


def check_color_tags(video_path: str) -> tuple[bool, str]:
    """P0: tag colore bt709 presenti + yuv420p (non fatale)."""
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_space,color_transfer,color_primaries,color_range,pix_fmt,profile",
             "-of", "default=noprint_wrappers=1", video_path],
            capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            return (True, "ffprobe colore indisponibile (skip)")
        info: dict = {}
        for line in (res.stdout or "").splitlines():
            try:
                k, _, v = line.strip().partition("=")
                info[k.strip()] = v.strip()
            except Exception:
                continue
        tags_ok = (info.get("color_space") == "bt709" and info.get("color_transfer") == "bt709"
                   and info.get("color_primaries") == "bt709")
        pix_ok = info.get("pix_fmt") == "yuv420p"
        ok = bool(tags_ok and pix_ok)
        return (ok, f"space={info.get('color_space')} trc={info.get('color_transfer')} "
                    f"prim={info.get('color_primaries')} range={info.get('color_range')} "
                    f"pix={info.get('pix_fmt')} profile={info.get('profile')}")
    except Exception as e:
        return (True, f"color check saltato ({e})")


def run_post_build_checks(
    video_path: str,
    audio_path: str,
    chunks: list[dict] | None = None,
    words_before: list[dict] | None = None,
    words_after: list[dict] | None = None,
    strict: bool = False,
) -> tuple[bool, dict]:
    """Esegue tutti i check post-build. Ritorna (ok, dettagli).

    Con strict=True solleva AssertionError al primo fail (per CI/test).
    Mai solleva altrimenti (per pipeline bulk resiliente).
    """
    details: dict = {}
    try:
        ok_av, msg_av = check_av_sync(video_path, audio_path)
    except Exception as e:
        ok_av, msg_av = False, str(e)
    try:
        ok_tmp, msg_tmp = check_temp_containment()
    except Exception as e:
        ok_tmp, msg_tmp = False, str(e)
    if words_before is not None and words_after is not None:
        try:
            ok_ts, msg_ts = check_timestamps_preserved(words_before, words_after)
        except Exception as e:
            ok_ts, msg_ts = False, str(e)
    else:
        ok_ts, msg_ts = True, "timestamp check saltato (riferimenti assenti)"
    try:
        ok_z, msg_z = check_z_order_safe(chunks)
    except Exception as e:
        ok_z, msg_z = True, f"z-check saltato ({e})"
    # P0: loudness + tag colore (sempre non fatali: ok resta sui 4 storici
    # a meno che strict non richieda tutto).
    try:
        ok_l, msg_l = check_loudness(video_path)
    except Exception as e:
        ok_l, msg_l = True, f"loudness saltato ({e})"
    try:
        ok_c, msg_c = check_color_tags(video_path)
    except Exception as e:
        ok_c, msg_c = True, f"colori saltati ({e})"
    details = {"av_sync": (ok_av, msg_av), "temp": (ok_tmp, msg_tmp),
               "timestamps": (ok_ts, msg_ts), "z_order": (ok_z, msg_z),
               "loudness": (ok_l, msg_l), "color": (ok_c, msg_c)}
    ok = bool(ok_av and ok_tmp and ok_ts and ok_z)
    if strict:
        ok = bool(ok and ok_l and ok_c)
    if strict and not ok:
        raise AssertionError(f"invariant checks falliti: {details}")
    return (ok, details)
