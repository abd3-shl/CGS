"""P0 WS-F: report misurabile di un video exportato.

Uso:
    python tools/export_report.py <video.mp4> [--platform=universal] [--out=report.json]

Stampa e salva JSON con: container/codec/profile/level/pix_fmt/tag colore/
bitrate video/GOP, audio (LUFS/TP/LRA/codec/bitrate/sample rate), durata
video vs audio, faststart, violazioni safe zone (se metadati disponibili).
Mai eccezioni fatali (exit 0 con campi null se non misurabile).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout or "", res.stderr or ""
    except Exception as e:
        return 99, "", str(e)


def _ffprobe_streams(path: str) -> dict:
    out: dict = {"video": {}, "audio": {}, "format": {}}
    try:
        code, so, _se = _run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", path,
        ])
        if code != 0:
            return out
        data = json.loads(so)
        for st in data.get("streams", []):
            if st.get("codec_type") == "video" and not out["video"]:
                out["video"] = {
                    "codec": st.get("codec_name"),
                    "profile": st.get("profile"),
                    "level": st.get("level"),
                    "pix_fmt": st.get("pix_fmt"),
                    "width": st.get("width"),
                    "height": st.get("height"),
                    "color_space": st.get("color_space"),
                    "color_primaries": st.get("color_primaries"),
                    "color_transfer": st.get("color_transfer"),
                    "color_range": st.get("color_range"),
                    "bitrate": st.get("bit_rate"),
                    "avg_frame_rate": st.get("avg_frame_rate"),
                    "nb_frames": st.get("nb_frames"),
                }
            if st.get("codec_type") == "audio" and not out["audio"]:
                out["audio"] = {
                    "codec": st.get("codec_name"),
                    "profile": st.get("profile"),
                    "bitrate": st.get("bit_rate"),
                    "sample_rate": st.get("sample_rate"),
                    "channels": st.get("channels"),
                }
        fmt = data.get("format", {})
        out["format"] = {
            "container": fmt.get("format_name"),
            "duration": fmt.get("duration"),
            "bitrate": fmt.get("bit_rate"),
            "faststart": None,  # sotto
        }
    except Exception:
        pass
    return out


def _check_faststart(path: str) -> bool | None:
    """moov prima di mdat (atomo all'inizio)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8 * 1024 * 1024)
        moov = head.find(b"moov")
        mdat = head.find(b"mdat")
        if moov < 0:
            return None
        if mdat < 0:
            return True
        return moov < mdat
    except Exception:
        return None


def _gop_size(path: str) -> int | None:
    """Distanza media tra keyframe (da skip_frame nokey)."""
    try:
        code, so, _se = _run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "packet=flags", "-of", "csv", path,
        ], timeout=180)
        if code != 0 or not so.strip():
            return None
        dists = []
        last = None
        for i, line in enumerate(so.splitlines()):
            if ",K" in line or line.strip().endswith(",K") or ",K," in line or "K" in line.split(",")[-1:]:
                if last is not None:
                    dists.append(i - last)
                last = i
        if len(dists) < 1:
            return None
        return int(round(sum(dists) / len(dists)))
    except Exception:
        return None


def _loudness(path: str) -> dict:
    out: dict = {"lufs": None, "true_peak": None, "lra": None}
    try:
        code, _so, se = _run([
            "ffmpeg", "-hide_banner", "-i", path, "-filter_complex",
            "loudnorm=I=-24:TP=-2:LRA=11:print_format=json", "-f", "null", "-",
        ], timeout=300)
        start, end = se.find("{"), se.rfind("}")
        if start < 0 or end <= start:
            return out
        data = json.loads(se[start:end + 1])
        for src, dst in (("input_i", "lufs"), ("input_tp", "true_peak"), ("input_lra", "lra")):
            try:
                out[dst] = float(data.get(src))
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    return out


def _durations(path: str) -> dict:
    out: dict = {"video": None, "audio": None, "delta": None}
    for stream, key in (("v:0", "video"), ("a:0", "audio")):
        try:
            code, so, _se = _run([
                "ffprobe", "-v", "error", "-select_streams", stream,
                "-show_entries", "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1", path,
            ])
            if code == 0 and so.strip():
                out[key] = float(so.strip())
        except Exception:
            pass
    try:
        if out["video"] is not None and out["audio"] is not None:
            out["delta"] = abs(float(out["video"]) - float(out["audio"]))
    except Exception:
        pass
    return out


def build_report(video_path: str, platform: str = "universal") -> dict:
    rep: dict = {"video": video_path, "platform": platform, "checks": {}}
    streams = _ffprobe_streams(video_path)
    rep.update(streams)
    v = streams.get("video", {})
    loud = _loudness(video_path)
    rep["audio"].update(loud)
    rep["durations"] = _durations(video_path)
    rep["format"]["faststart"] = _check_faststart(video_path)
    rep["video"]["gop_avg"] = _gop_size(video_path)
    # Checks con soglie P0.
    checks: dict = {}
    try:
        checks["codec_h264_high"] = (v.get("codec") == "h264" and str(v.get("profile")).lower() == "high")
        checks["pix_yuv420p"] = (v.get("pix_fmt") == "yuv420p")
        checks["color_bt709"] = (v.get("color_space") == "bt709" and v.get("color_transfer") == "bt709"
                                 and v.get("color_primaries") == "bt709" and v.get("color_range") == "tv")
        checks["gop_60"] = (rep["video"].get("gop_avg") in (None,) or abs(int(rep["video"].get("gop_avg") or 60) - 60) <= 5)
        if rep["video"].get("gop_avg") is None:
            checks["gop_60"] = None
        lufs = loud.get("lufs")
        checks["loudness_-14_+-1"] = (abs(float(lufs) - (-14.0)) <= 1.0) if lufs is not None else None
        tp = loud.get("true_peak")
        checks["true_peak_<=-1"] = (float(tp) <= -1.0) if tp is not None else None
        d = rep["durations"].get("delta")
        checks["av_sync_<0.1"] = (float(d) < 0.1) if d is not None else None
        checks["faststart"] = rep["format"].get("faststart")
        checks["audio_aac_44100"] = (rep["audio"].get("codec") == "aac"
                                     and str(rep["audio"].get("sample_rate")) == "44100")
    except Exception:
        pass
    rep["checks"] = checks
    # Safe zone: violazioni solo se forniti metadati layout via --layout-json.
    rep["ui_violations"] = None
    return rep


def main(argv: list[str]) -> int:
    video = None
    platform = "universal"
    out_path = None
    layout_json = None
    for a in argv[1:]:
        if a.startswith("--platform="):
            v = a.split("=", 1)[1].strip().lower()
            if v in ("universal", "tiktok", "reels", "shorts"):
                platform = v
        elif a.startswith("--out="):
            out_path = a.split("=", 1)[1].strip() or None
        elif a.startswith("--layout-json="):
            layout_json = a.split("=", 1)[1].strip() or None
        elif not a.startswith("--") and video is None:
            video = a
    if not video or not os.path.isfile(video):
        print(f"Uso: python tools/export_report.py <video.mp4> [--platform=...] [--out=report.json] [--layout-json=chunks.json]")
        return 2
    rep = build_report(video, platform)
    # Metadati layout opzionali: bbox testo → violazioni profilo.
    if layout_json and os.path.isfile(layout_json):
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from core.safe_zones import get_profile, rect_violations
            data = json.load(open(layout_json, encoding="utf-8"))
            chunks = data if isinstance(data, list) else data.get("chunks", [])
            prof = get_profile(platform)
            viols = []
            for ch in chunks:
                tb = ch.get("text_bbox")
                if tb:
                    for v in rect_violations(tuple(tb), prof):
                        viols.append({"chunk": ch.get("index"), "violation": v})
            rep["ui_violations"] = viols
            rep["checks"]["ui_violations_0"] = (len(viols) == 0)
        except Exception as e:
            rep["ui_violations"] = f"non calcolabili ({e})"
    if out_path is None:
        base = os.path.splitext(video)[0] + ".export_report.json"
        out_path = base
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"(report non salvato: {e})")
    # Stampa compatta.
    print(f"Video: {video}  piattaforma: {platform}")
    v = rep.get("video", {})
    print(f"  video: {v.get('codec')} {v.get('profile')} {v.get('width')}x{v.get('height')} "
          f"{v.get('pix_fmt')} br={v.get('bitrate')} gop~{v.get('gop_avg')}")
    print(f"  colore: space={v.get('color_space')} trc={v.get('color_transfer')} "
          f"prim={v.get('color_primaries')} range={v.get('color_range')}")
    a = rep.get("audio", {})
    print(f"  audio: {a.get('codec')} {a.get('sample_rate')}Hz br={a.get('bitrate')} | "
          f"{a.get('lufs')} LUFS, TP {a.get('true_peak')} dBTP, LRA {a.get('lra')}")
    d = rep.get("durations", {})
    print(f"  durate: video={d.get('video')} audio={d.get('audio')} delta={d.get('delta')} | "
          f"faststart={rep.get('format', {}).get('faststart')}")
    print("  checks:")
    for k, val in rep.get("checks", {}).items():
        mark = "OK " if val is True else ("FAIL" if val is False else "n.d.")
        print(f"    [{mark}] {k}")
    if isinstance(rep.get("ui_violations"), list):
        print(f"  ui_violations: {len(rep['ui_violations'])}")
    print(f"Report salvato: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
