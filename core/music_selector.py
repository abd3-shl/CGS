"""
Selettore tracce musicali (Background Music — Fase 2).

I/O isolato qui: scansione libreria, analisi ffmpeg/ffprobe con cache,
scelta deterministica per script con history anti-ripetizione.
Logica pura (piano keyframe) in `core/music_plan.py`.

Tutto best-effort: mai eccezioni verso la pipeline (ritorna None = niente musica).
Commenti e log in italiano, identificatori in inglese (convenzione repo).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

try:
    from config import (
        MUSIC_DIR as _CFG_MUSIC_DIR,
        MUSIC_FALLBACK_CATEGORY as _CFG_FALLBACK,
        MUSIC_MIN_TRACK_S as _CFG_MIN_S,
        MUSIC_HISTORY_SIZE as _CFG_HIST,
    )
except Exception:  # config datata
    _CFG_MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "music")
    _CFG_FALLBACK = "dark_motivational"
    _CFG_MIN_S = 30.0
    _CFG_HIST = 3

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".flac")
CACHE_NAME = "_analysis.json"
MANIFEST_NAME = "audio_licenses.json"


def _music_root(music_dir: str | Path | None = None) -> Path:
    try:
        base = Path(music_dir) if music_dir else Path(_CFG_MUSIC_DIR)
    except Exception:
        base = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "music"))
    return base


def scan_library(music_dir: str | Path | None = None) -> dict[str, list[str]]:
    """Scansiona le cartelle per nicchia. Ignora file/cartelle `_`-prefixed e non audio.

    Ritorna {nicchia: [path_assoluti ordinati]}. Mai eccezioni ({} se assente).
    """
    out: dict[str, list[str]] = {}
    try:
        root = _music_root(music_dir)
    except Exception:
        return out
    try:
        if not root.is_dir():
            return out
        for cat in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                if cat.name.startswith("_"):
                    continue
                tracks: list[str] = []
                for f in sorted(cat.iterdir()):
                    try:
                        if not f.is_file() or f.name.startswith("_"):
                            continue
                        if f.suffix.lower() not in AUDIO_EXTS:
                            continue
                        tracks.append(str(f))
                    except Exception:
                        continue
                if tracks:
                    out[cat.name] = tracks
            except Exception:
                continue
    except Exception:
        return out
    return out


def _probe_duration(path: str) -> float | None:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode != 0:
            return None
        return float(res.stdout.strip())
    except Exception:
        return None


def _probe_format(path: str) -> dict:
    """Sample rate / canali dello stream audio (best-effort)."""
    info: dict = {"sample_rate": None, "channels": None, "codec": None}
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,sample_rate,channels",
             "-of", "default=noprint_wrappers=1", path],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode != 0:
            return info
        for line in res.stdout.splitlines():
            try:
                k, _, v = line.strip().partition("=")
                if k in info and v:
                    info[k] = int(v) if k in ("sample_rate", "channels") else v
            except Exception:
                continue
    except Exception:
        pass
    return info


def _measure_loudness(path: str) -> dict:
    """Misura LUFS/TP/LRA con loudnorm a due stadi di misura (solo misura, `-f null`)."""
    out: dict = {"lufs": None, "true_peak": None, "lra": None}
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-filter_complex",
             "loudnorm=I=-24:TP=-2:LRA=11:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        err = res.stderr or ""
        start = err.find("{")
        end = err.rfind("}")
        if start < 0 or end <= start:
            return out
        data = json.loads(err[start:end + 1])
        try:
            out["lufs"] = float(data.get("input_i")) if data.get("input_i") is not None else None
        except (TypeError, ValueError):
            pass
        try:
            out["true_peak"] = float(data.get("input_tp")) if data.get("input_tp") is not None else None
        except (TypeError, ValueError):
            pass
        try:
            out["lra"] = float(data.get("input_lra")) if data.get("input_lra") is not None else None
        except (TypeError, ValueError):
            pass
    except Exception:
        pass
    return out


def _measure_silence_edges(path: str) -> dict:
    """Rileva silenzio iniziale/finale (soglia -45 dB, min 0.3 s)."""
    out: dict = {"lead_silence": 0.0, "tail_silence": 0.0}
    try:
        dur = _probe_duration(path)
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-af",
             "silencedetect=noise=-45dB:d=0.3", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        starts: list[float] = []
        ends: list[tuple[float, float]] = []  # (end, duration)
        for line in (res.stderr or "").splitlines():
            try:
                if "silence_start:" in line:
                    starts.append(float(line.split("silence_start:")[1].split()[0]))
                elif "silence_end:" in line:
                    tail = line.split("silence_end:")[1]
                    end_s = float(tail.split("|")[0].strip().split()[0])
                    dur_s = 0.0
                    if "silence_duration:" in line:
                        dur_s = float(line.split("silence_duration:")[1].strip().split()[0])
                    ends.append((end_s, dur_s))
            except Exception:
                continue
        if starts and starts[0] <= 0.01 and ends:
            try:
                out["lead_silence"] = round(max(0.0, ends[0][1]), 3)
            except Exception:
                pass
        if dur and starts and ends:
            try:
                last_start = starts[-1]
                last_end, last_dur = ends[-1]
                # Coda silenziosa se l'ultimo silenzio arriva quasi a fine file.
                if abs(last_end - dur) < 0.6:
                    out["tail_silence"] = round(max(0.0, last_dur), 3)
                elif dur - last_start < 0.6:
                    out["tail_silence"] = round(max(0.0, dur - last_start), 3)
            except Exception:
                pass
    except Exception:
        pass
    return out


def _cache_path(music_dir: str | Path | None = None) -> Path:
    return _music_root(music_dir) / CACHE_NAME


def _load_cache(music_dir: str | Path | None = None) -> dict:
    try:
        p = _cache_path(music_dir)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(data: dict, music_dir: str | Path | None = None) -> None:
    try:
        p = _cache_path(music_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def analyze_track(path: str, music_dir: str | Path | None = None) -> dict | None:
    """Analizza una traccia (con cache `_analysis.json` su path+size+mtime).

    Ritorna {path, duration, lufs, true_peak, lra, lead_silence, tail_silence,
    sample_rate, channels, codec, valid} o None se illeggibile. Mai eccezioni.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return None
        try:
            st = p.stat()
            key = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            key = str(p)
        cache = _load_cache(music_dir)
        if isinstance(cache, dict) and key in cache and isinstance(cache[key], dict):
            hit = dict(cache[key])
            hit["path"] = str(p)
            return hit
        duration = _probe_duration(str(p))
        if not duration or duration <= 0:
            return None
        fmt = _probe_format(str(p))
        loud = _measure_loudness(str(p))
        edges = _measure_silence_edges(str(p))
        info: dict = {
            "path": str(p),
            "duration": round(float(duration), 3),
            "lufs": loud.get("lufs"),
            "true_peak": loud.get("true_peak"),
            "lra": loud.get("lra"),
            "lead_silence": float(edges.get("lead_silence", 0.0) or 0.0),
            "tail_silence": float(edges.get("tail_silence", 0.0) or 0.0),
            "sample_rate": fmt.get("sample_rate"),
            "channels": fmt.get("channels"),
            "codec": fmt.get("codec"),
            "valid": True,
        }
        try:
            cache[key] = {k: v for k, v in info.items() if k != "path"}
            # Limita crescita cache: tieni al max 200 voci.
            if len(cache) > 200:
                for k in list(cache.keys())[: len(cache) - 200]:
                    cache.pop(k, None)
            _save_cache(cache, music_dir)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _read_manifest(music_dir: str | Path | None = None) -> dict:
    try:
        mp = _music_root(music_dir).parent / MANIFEST_NAME
        if mp.is_file():
            data = json.loads(mp.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def license_for(path: str, music_dir: str | Path | None = None) -> dict:
    """Autore/licenza dal manifest `audio_licenses.json` (se esiste). Mai eccezioni."""
    try:
        manifest = _read_manifest(music_dir)
        if not manifest:
            return {}
        rel = None
        try:
            rel = str(Path(path).relative_to(Path(_music_root(music_dir).parent))).replace("\\", "/")
        except Exception:
            rel = None
        for key in (rel, str(path), Path(path).name):
            try:
                if key and key in manifest and isinstance(manifest[key], dict):
                    m = manifest[key]
                    return {
                        "title": m.get("title", Path(path).stem),
                        "author": m.get("author", "sconosciuto"),
                        "license": m.get("license", "sconosciuta"),
                        "source_page": m.get("page", ""),
                        "category": m.get("category", ""),
                    }
            except Exception:
                continue
    except Exception:
        pass
    return {}


def _script_seed(script: str | None) -> int:
    try:
        return int(hashlib.md5((script or "").encode("utf-8")).hexdigest()[:8], 16)
    except Exception:
        return 0


def choose_track(
    niche: str | None,
    script: str | None = None,
    history: list[str] | None = None,
    forced_path: str | None = None,
    duration_s: float | None = None,
    voice_lufs: float | None = None,
    music_dir: str | Path | None = None,
    min_track_s: float | None = None,
    fallback_category: str | None = None,
    history_size: int | None = None,
    on_log=None,
) -> dict | None:
    """Sceglie la traccia per uno script. Ritorna dict traccia+licenza o None.

    Priorità: forzata → cartella nicchia → fallback configurabile → None.
    Deterministica per script (seed md5), evita le ultime N della history,
    preferisce durata ≥ video+fade e (a parità) LUFS vicini alla voce.
    Mai eccezioni.
    """
    try:
        def _log(msg: str):
            try:
                if on_log:
                    on_log(msg)
            except Exception:
                pass

        try:
            min_s = float(min_track_s) if min_track_s is not None else float(_CFG_MIN_S)
        except Exception:
            min_s = 30.0
        try:
            fb = (fallback_category or _CFG_FALLBACK or "dark_motivational").strip()
        except Exception:
            fb = "dark_motivational"
        try:
            hsize = int(history_size) if history_size is not None else int(_CFG_HIST)
        except Exception:
            hsize = 3
        hist = [str(h) for h in (history or []) if h][-max(0, hsize):] if hsize > 0 else []

        # 1. Traccia forzata (CLI/config): valida e analizza, ignora il resto.
        if forced_path:
            try:
                if Path(str(forced_path)).is_file():
                    info = analyze_track(str(forced_path), music_dir)
                    if info and float(info.get("duration", 0.0)) >= min_s:
                        info.update(license_for(str(forced_path), music_dir))
                        info["category"] = info.get("category") or Path(str(forced_path)).parent.name
                        _log(f"Musica forzata: {Path(str(forced_path)).name}")
                        return info
                    _log(f"Traccia forzata non valida/corta, fallback auto: {forced_path}")
            except Exception:
                pass

        lib = scan_library(music_dir)
        if not lib:
            return None
        candidates: list[str] = []
        category = ""
        try:
            niche_key = (niche or "").strip()
        except Exception:
            niche_key = ""
        if niche_key and niche_key in lib:
            candidates = list(lib[niche_key])
            category = niche_key
        if not candidates and fb in lib:
            candidates = list(lib[fb])
            category = fb
            if niche_key and niche_key != fb:
                _log(f"Cartella musica '{niche_key}' vuota/assente, uso fallback '{fb}'.")
        if not candidates:
            # Ultima spiaggia: prima categoria non vuota in ordine alfabetico.
            for k in sorted(lib.keys()):
                if lib[k]:
                    candidates = list(lib[k])
                    category = k
                    break
        if not candidates:
            return None

        # 2. Analizza (cache) e filtra per durata minima.
        analyzed: list[dict] = []
        for c in candidates:
            try:
                info = analyze_track(c, music_dir)
                if info and float(info.get("duration", 0.0)) >= min_s:
                    analyzed.append(info)
            except Exception:
                continue
        if not analyzed:
            _log(f"Nessuna traccia valida (≥ {min_s:.0f}s) in '{category}'.")
            return None

        # 3. Anti-ripetizione: escludi le ultime N, salvo restarne senza.
        fresh = [a for a in analyzed if a.get("path") not in hist and Path(a["path"]).name not in hist]
        pool = fresh or analyzed

        # 4. Preferisci durata ≥ video + fade (evita loop); a parità, LUFS vicini alla voce.
        try:
            need = float(duration_s) + 2.0 if duration_s else 0.0
        except Exception:
            need = 0.0
        long_enough = [a for a in pool if float(a.get("duration", 0.0)) >= need] if need > 0 else []
        pool2 = long_enough or sorted(pool, key=lambda a: float(a.get("duration", 0.0)), reverse=True)[: max(1, len(pool) // 2 + 1)]
        if voice_lufs is not None:
            try:
                vl = float(voice_lufs)
                pool2 = sorted(pool2, key=lambda a: abs(float(a.get("lufs", vl) or vl) - vl))
            except Exception:
                pass
        if not pool2:
            pool2 = pool

        # 5. Scelta deterministica per script dentro il pool ordinato.
        seed = _script_seed(script)
        idx = seed % len(pool2)
        chosen = pool2[idx]
        chosen = dict(chosen)
        chosen.update(license_for(chosen.get("path", ""), music_dir))
        chosen["category"] = category
        chosen["loop"] = bool(need > 0 and float(chosen.get("duration", 0.0)) < need)
        return chosen
    except Exception:
        return None
