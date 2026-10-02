#!/usr/bin/env python3
"""Report audio di un video CGS (verifica Background Music).

Uso:
    python tools/audio_report.py <video.mp4>
    python tools/audio_report.py <video.mp4> --stems voice.wav music_processed.wav --words words.json

Stampa: durata audio vs video, LUFS integrati, true peak, LRA, livello medio
nel primo secondo (fade-in) e negli ultimi 2 s (fade-out), eventuale clipping.
Con --stems confronta la musica nelle finestre di parlato e nelle pause
(atteso: +3..5 dB nelle pause >= 0.35 s). Solo stdlib + ffmpeg/ffprobe.
"""

import argparse
import json
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)


def probe_duration(path: str, stream: str | None = None) -> float | None:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    if stream:
        cmd = ["ffprobe", "-v", "error", "-select_streams", stream,
               "-show_entries", "stream=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path]
    rc, out, _ = _run(cmd)
    try:
        return float(out.strip()) if rc == 0 else None
    except ValueError:
        return None


def measure_loudness(path: str) -> dict:
    rc, _, err = _run(["ffmpeg", "-hide_banner", "-i", path, "-filter_complex",
                       "loudnorm=I=-24:TP=-2:LRA=11:print_format=json", "-f", "null", "-"])
    out = {"lufs": None, "true_peak": None, "lra": None}
    try:
        s, e = err.find("{"), err.rfind("}")
        d = json.loads(err[s:e + 1])
        out = {"lufs": float(d["input_i"]), "true_peak": float(d["input_tp"]),
               "lra": float(d["input_lra"])}
    except Exception:
        pass
    return out


def mean_volume(path: str, start: float, dur: float) -> float | None:
    rc, _, err = _run(["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                       "-i", path, "-af", "volumedetect", "-f", "null", "-"])
    for line in err.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split()[0])
            except ValueError:
                return None
    return None


def max_volume(path: str) -> tuple[float | None, float | None]:
    rc, _, err = _run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                       "volumedetect", "-f", "null", "-"])
    mean, mx = None, None
    for line in err.splitlines():
        try:
            if "mean_volume" in line:
                mean = float(line.split("mean_volume:")[1].strip().split()[0])
            elif "max_volume" in line:
                mx = float(line.split("max_volume:")[1].strip().split()[0])
        except ValueError:
            continue
    return mean, mx


def report(video: str) -> dict:
    print(f"Video: {video}")
    dv = probe_duration(video, "v:0")
    da = probe_duration(video, "a:0")
    print(f"  durata video: {dv if dv is not None else 'n.d.'} s")
    print(f"  durata audio: {da if da is not None else 'n.d.'} s")
    if dv is not None and da is not None:
        dd = abs(dv - da)
        print(f"  delta AV: {dd:.3f} s {'OK (<0.1s)' if dd < 0.1 else 'FAIL (>=0.1s)'}")
    loud = measure_loudness(video)
    print(f"  LUFS integrati: {loud['lufs']} (target -14 ±1)")
    print(f"  true peak: {loud['true_peak']} dBTP (limite <= -1.0)")
    print(f"  LRA: {loud['lra']}")
    mean, mx = max_volume(video)
    print(f"  volume medio: {mean} dB, massimo: {mx} dB")
    if mx is not None and mx >= -0.01:
        print("  ⚠️ possibile clipping (max ~0 dB)")
    else:
        print("  clipping: no")
    if da:
        v0 = mean_volume(video, 0.0, 1.0)
        v1 = mean_volume(video, max(0.0, da - 2.0), 2.0)
        print(f"  livello medio primi 1s (fade-in): {v0} dB")
        print(f"  livello medio ultimi 2s (fade-out): {v1} dB")
    return {"duration_v": dv, "duration_a": da, **loud}


def report_stems(music: str, words_path: str, pause_min: float = 0.35) -> None:
    try:
        words = json.loads(open(words_path, encoding="utf-8").read())
        if isinstance(words, dict):
            words = words.get("words", words.get("chunks", []))
    except Exception as e:
        print(f"words non leggibili: {e}")
        return
    try:
        ws = sorted(({"start": float(w["start"]), "end": float(w["end"])} for w in words
                     if isinstance(w, dict) and "start" in w and "end" in w),
                    key=lambda w: w["start"])
    except Exception as e:
        print(f"words non validi: {e}")
        return
    if len(ws) < 2:
        print("servono almeno 2 parole per pause/parlato.")
        return
    speech = ws[:10]
    pauses = []
    for a, b in zip(ws, ws[1:]):
        if b["start"] - a["end"] >= pause_min:
            pauses.append((a["end"], b["start"]))
    pauses = pauses[:10]
    print(f"Musica: {music} ({len(speech)} finestre parlato, {len(pauses)} pause)")
    sp = [v for w in speech for v in [mean_volume(music, w["start"], max(0.1, w["end"] - w["start"]))] if v is not None]
    pa = [v for s, e in pauses for v in [mean_volume(music, s, max(0.1, e - s))] if v is not None]
    ms = sum(sp) / len(sp) if sp else None
    mp = sum(pa) / len(pa) if pa else None
    print(f"  musica media nel parlato: {ms} dB")
    print(f"  musica media nelle pause: {mp} dB")
    if ms is not None and mp is not None:
        print(f"  delta pause-parlato: {mp - ms:+.1f} dB (atteso +3..+5)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="video mp4 da analizzare")
    ap.add_argument("--stems", nargs=2, metavar=("VOICE", "MUSIC"),
                    help="stem voice.wav e music_processed.wav (--audio-debug)")
    ap.add_argument("--words", help="JSON parole [{start,end}] per il confronto pause/parlato")
    a = ap.parse_args()
    report(a.video)
    if a.stems:
        _voice, music = a.stems
        if a.words:
            report_stems(music, a.words)
        else:
            print("(usa --words words.json per il confronto pause/parlato)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
