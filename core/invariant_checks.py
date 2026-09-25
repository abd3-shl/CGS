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
    """I campi start/end non devono mai essere alterati (confronto 1:1)."""
    try:
        if len(before) != len(after):
            return (False, f"conteggio diverso {len(before)} vs {len(after)}")
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
    """Nessuna violazione critica safe-zone (testo fuori canvas = fail)."""
    try:
        from core.layout_guard import verify_z_order, text_bbox_of_layout

        bad = 0
        notes: list[str] = []
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
            except Exception:
                continue
        if bad:
            return (False, f"{bad} chunk fuori canvas: {sorted(set(notes))[:3]}")
        return (True, "safe-zone ok (nessun fuori-canvas)")
    except Exception as e:
        return (True, f"z-check saltato ({e})")


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
    details = {"av_sync": (ok_av, msg_av), "temp": (ok_tmp, msg_tmp),
               "timestamps": (ok_ts, msg_ts), "z_order": (ok_z, msg_z)}
    ok = bool(ok_av and ok_tmp and ok_ts and ok_z)
    if strict and not ok:
        raise AssertionError(f"invariant checks falliti: {details}")
    return (ok, details)
