"""
Audio master P0 (WS-A): normalizzazione loudness e catena senza perdite.

Principio: decodifica una volta → lavora in float/WAV → UN SOLO encode lossy
(AAC nel mux finale dei builder). Nessun passaggio intermedio mp3.

Catena target:
    TTS mp3 → decode → voice_raw.wav (pcm_s16le 44.1k stereo)
    → [Pause Engine su WAV] → voice_edit.wav → [voice polish opzionale]
    → mix voce+SFX(+musica, float32) → alimiter → loudnorm 2-pass → master.wav
    → mux video: -c:a aac -b:a 192k (UNICO encode lossy)

Tutto best-effort e mai fatale (qualità): se fallisce → warning + ritorna
l'input. Funzioni pubbliche: `master_audio`, `measure_loudness`,
`decode_to_wav`, `voice_polish`, `post_encode_check`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess


def _cfg(key: str, default):
    try:
        import config as _c
        return getattr(_c, key, default)
    except Exception:
        return default


def _ffmpeg() -> str | None:
    try:
        return shutil.which("ffmpeg")
    except Exception:
        return None


def _ffprobe() -> str | None:
    try:
        return shutil.which("ffprobe")
    except Exception:
        return None


def _run(cmd: list[str], timeout: int = 300) -> tuple[bool, str, str]:
    """Esegue un comando (lista di argomenti, mai shell). Ritorna (ok, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout or "", res.stderr or ""
    except Exception as e:
        return False, "", str(e)[:500]


def _parse_loudnorm_json(stderr: str) -> dict | None:
    """Estrae il JSON loudnorm dallo stderr (gestisce output misto)."""
    try:
        start = stderr.find("{")
        end = stderr.rfind("}")
        if start < 0 or end <= start:
            return None
        return json.loads(stderr[start:end + 1])
    except Exception:
        return None


def measure_loudness(path: str) -> dict | None:
    """Misura LUFS integrati / true peak / LRA. Ritorna dict o None.

    {"lufs", "true_peak", "lra", "thresh", "measured": {...per il 2° passaggio}}.
    Mai eccezioni.
    """
    try:
        ff = _ffmpeg()
        if not ff or not path or not os.path.isfile(path):
            return None
        ok, _out, err = _run(
            [ff, "-hide_banner", "-i", path, "-filter_complex",
             "loudnorm=I=-24:TP=-2:LRA=11:print_format=json", "-f", "null", "-"],
            timeout=180,
        )
        data = _parse_loudnorm_json(err)
        if not data:
            return None
        out: dict = {}
        try:
            out["lufs"] = float(data.get("input_i"))
        except (TypeError, ValueError):
            return None
        for src, dst in (("input_tp", "true_peak"), ("input_lra", "lra"),
                         ("input_thresh", "thresh")):
            try:
                out[dst] = float(data.get(src))
            except (TypeError, ValueError):
                out[dst] = None
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


def decode_to_wav(src: str, dst: str, sample_rate: int | None = None) -> str:
    """Decodifica un audio qualsiasi in WAV pcm_s16le stereo. Ritorna dst o src.

    Best-effort: se fallisce ritorna `src` (il chiamante usa l'originale).
    """
    try:
        ff = _ffmpeg()
        if not ff or not src or not os.path.isfile(src):
            return src
        sr = int(sample_rate or _cfg("AUDIO_SAMPLE_RATE", 44100) or 44100)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        except Exception:
            return src
        ok, _, _ = _run(
            [ff, "-y", "-i", src, "-c:a", "pcm_s16le", "-ar", str(sr), "-ac", "2", dst],
            timeout=300,
        )
        if ok and os.path.isfile(dst):
            return dst
        return src
    except Exception:
        try:
            return src
        except Exception:
            return ""


def voice_polish(in_wav: str, out_wav: str) -> str:
    """Polish voce lieve: highpass 70Hz + compressione leggera. Ritorna out o in.

    `VOICE_POLISH=0` → nessuna modifica (ritorna in_wav). Non altera la durata.
    Best-effort: mai eccezioni.
    """
    try:
        enabled = int(_cfg("VOICE_POLISH", 1) or 0) != 0
    except Exception:
        enabled = True
    if not enabled:
        return in_wav
    try:
        ff = _ffmpeg()
        if not ff or not in_wav or not os.path.isfile(in_wav):
            return in_wav
        try:
            hp = max(20, min(300, int(_cfg("VOICE_HIGHPASS_HZ", 70) or 70)))
        except Exception:
            hp = 70
        filt = (
            f"highpass=f={hp},"
            "acompressor=threshold=-20dB:ratio=2:attack=10:release=120:makeup=1"
        )
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        except Exception:
            return in_wav
        ok, _, _ = _run(
            [ff, "-y", "-i", in_wav, "-af", filt,
             "-c:a", "pcm_s16le", "-ar", str(_cfg("AUDIO_SAMPLE_RATE", 44100) or 44100),
             "-ac", "2", out_wav],
            timeout=300,
        )
        if ok and os.path.isfile(out_wav):
            return out_wav
        return in_wav
    except Exception:
        try:
            return in_wav
        except Exception:
            return ""


def _uniform_filter() -> str:
    return "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"


def master_audio(
    in_wav: str,
    out_wav: str,
    target_lufs: float | None = None,
    true_peak: float | None = None,
    lra: float | None = None,
    two_pass: bool | None = None,
) -> str:
    """Normalizza `in_wav` a `out_wav` (WAV): alimiter + loudnorm 2-pass.

    1. Misura (print_format=json, parse dallo stderr).
    2. Applica con measured_* + linear=true (preserva rapporto voce/musica/SFX).
    3. Fallback: singolo passaggio dinamico; se anche questo fallisce → input.
    Best-effort: ritorna sempre un path valido (out o in). Mai eccezioni.
    """
    try:
        ti = float(target_lufs) if target_lufs is not None else float(_cfg("FINAL_LOUDNESS_LUFS", -14.0) or -14.0)
        tp = float(true_peak) if true_peak is not None else float(_cfg("FINAL_TRUE_PEAK_DB", -1.5) or -1.5)
        lra_v = float(lra) if lra is not None else float(_cfg("FINAL_LRA", 11.0) or 11.0)
    except Exception:
        ti, tp, lra_v = -14.0, -1.5, 11.0
    try:
        if two_pass is None:
            two_pass = int(_cfg("LOUDNORM_TWO_PASS", 1) or 0) != 0
    except Exception:
        two_pass = True if two_pass is None else bool(two_pass)
    try:
        ff = _ffmpeg()
        if not ff or not in_wav or not os.path.isfile(in_wav):
            return in_wav
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        except Exception:
            return in_wav
        base = f"{_uniform_filter()},alimiter=limit=0.89:level=0"
        if two_pass:
            meas = measure_loudness(in_wav)
            m = (meas or {}).get("measured")
            if m:
                filt = (
                    f"{base},loudnorm=I={ti}:TP={tp}:LRA={lra_v}:"
                    f"measured_I={m['measured_I']:.2f}:measured_TP={m['measured_TP']:.2f}:"
                    f"measured_LRA={m['measured_LRA']:.2f}:measured_thresh={m['measured_thresh']:.2f}:"
                    f"offset={m['offset']:.2f}:linear=true:print_format=summary"
                )
                ok, _, _ = _run(
                    [ff, "-y", "-i", in_wav, "-af", filt,
                     "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", out_wav],
                    timeout=300,
                )
                if ok and os.path.isfile(out_wav):
                    return out_wav
        # Fallback: singolo passaggio dinamico.
        filt1 = f"{base},loudnorm=I={ti}:TP={tp}:LRA={lra_v}"
        ok, _, _ = _run(
            [ff, "-y", "-i", in_wav, "-af", filt1,
             "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", out_wav],
            timeout=300,
        )
        if ok and os.path.isfile(out_wav):
            return out_wav
        return in_wav
    except Exception:
        try:
            return in_wav
        except Exception:
            return ""


def post_encode_check(
    final_mp4: str,
    master_wav: str,
    target_lufs: float | None = None,
    true_peak: float | None = None,
) -> dict:
    """Verifica LUFS/TP sull'mp4 finale; se TP > −1.0 dBTP chiede un re-master.

    Ritorna {"ok", "lufs", "true_peak", "lra", "need_remaster", "suggest_tp"}.
    L'AAC può introdurre overshoot (~1 dB): il chiamante (main.py) riesegue
    `master_audio` con true_peak ridotto UNA sola volta e rifà il mux.
    Mai eccezioni.
    """
    out: dict = {"ok": True, "lufs": None, "true_peak": None, "lra": None,
                 "need_remaster": False, "suggest_tp": None}
    try:
        m = measure_loudness(final_mp4)
        if not m:
            return out
        out["lufs"] = m.get("lufs")
        out["true_peak"] = m.get("true_peak")
        out["lra"] = m.get("lra")
        try:
            ti = float(target_lufs) if target_lufs is not None else float(_cfg("FINAL_LOUDNESS_LUFS", -14.0) or -14.0)
        except Exception:
            ti = -14.0
        try:
            lufs_ok = m.get("lufs") is not None and abs(float(m["lufs"]) - ti) <= 1.0
        except Exception:
            lufs_ok = True
        try:
            tp_ok = m.get("true_peak") is None or float(m["true_peak"]) <= -1.0
        except Exception:
            tp_ok = True
        out["ok"] = bool(lufs_ok and tp_ok)
        if not tp_ok:
            try:
                over = float(m["true_peak"]) - (-1.0)
                base_tp = float(true_peak) if true_peak is not None else float(_cfg("FINAL_TRUE_PEAK_DB", -1.5) or -1.5)
                out["suggest_tp"] = round(base_tp - over - 0.2, 2)
                out["need_remaster"] = True
            except Exception:
                pass
        return out
    except Exception:
        return out


def should_use_audio_master() -> bool:
    """Vero se il path P0 è attivo (AUDIO_MASTER_ENABLED=1). Mai eccezioni."""
    try:
        return int(_cfg("AUDIO_MASTER_ENABLED", 1) or 0) != 0
    except Exception:
        return True
