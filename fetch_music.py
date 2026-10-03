#!/usr/bin/env python3
"""
tools/fetch_music.py - scarica musica e SFX utilizzabili commercialmente per CGS.

Struttura creata:
  assets/music/<nicchia>/*.mp3    (musica strumentale per nicchia)
  assets/sfx/<categoria>/*.mp3    (effetti sonori)
  assets/audio_licenses.json      (manifest: autore, licenza, URL -> serve per attribuzione/prova)

Provider:
  freesound   FREESOUND_API_KEY (gratis, https://freesound.org/apiv2/apply)
  openverse   nessuna chiave (anonimo, rate limit basso)
  eleven      ELEVENLABS_API_KEY(S): genera SFX/musica con AI (consuma crediti, verifica i termini del tuo piano)

Uso:
  python tools/fetch_music.py                          # tutto, freesound+openverse, 2 tracce per query
  python tools/fetch_music.py --kind music --category dark_motivational --per-query 3
  python tools/fetch_music.py --kind sfx --provider eleven --per-query 1
  python tools/fetch_music.py --list

Integrazione in main.py (dove oggi chiami _mix_sfx):
  from tools.fetch_music import pick_music
  _mix_audio = _mix_sfx(audio_path, enriched_chunks, bg_music_path=pick_music(typography_niche))

NOTA: non ho potuto testare le chiamate di rete in questo ambiente. Prova prima con --per-query 1.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"
SFX_DIR = ROOT / "assets" / "sfx"
MANIFEST = ROOT / "assets" / "audio_licenses.json"
AUDIO_EXT = (".mp3", ".wav", ".ogg", ".m4a", ".flac")

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# Nomi cartella = nicchie dei preset tipografici di CGS.
MUSIC = {
    "business_finance": {
        "queries": ["corporate uplifting", "business background", "motivational corporate", "minimal tech corporate"],
        "ai": "Instrumental corporate background, 105 BPM, soft piano, light percussion, confident, no vocals",
    },
    "tech_ai": {
        "queries": ["futuristic electronic", "technology ambient", "synthwave instrumental", "digital minimal"],
        "ai": "Instrumental futuristic electronic, 110 BPM, arpeggiated synths, clean beat, no vocals",
    },
    "fitness_sport": {
        "queries": ["workout energetic", "hard trap instrumental", "sport motivation electronic", "gym drive"],
        "ai": "Instrumental high energy workout, 140 BPM, punchy drums, heavy bass, no vocals",
    },
    "lifestyle_vlog": {
        "queries": ["lofi chill", "happy acoustic", "chill pop instrumental", "summer vlog"],
        "ai": "Instrumental lofi chill beat, 85 BPM, warm keys, vinyl texture, relaxed, no vocals",
    },
    "educational": {
        "queries": ["calm piano", "soft ambient learning", "minimal inspiring", "light curious"],
        "ai": "Instrumental calm piano and soft pads, 90 BPM, gentle and curious, no vocals",
    },
    "dark_motivational": {
        "queries": ["dark cinematic", "dark trap instrumental", "dark ambient pulse", "epic slow cinematic", "deep bass dark"],
        "ai": "Instrumental dark cinematic hip hop, 80 BPM, deep 808 bass, brooding pads, tense, no vocals",
    },
}

SFX = {
    "whoosh": {"queries": ["whoosh", "swoosh transition"], "ai": "short fast whoosh transition", "dur": 1.0},
    "impact": {"queries": ["cinematic impact hit", "bass drop hit"], "ai": "deep cinematic impact hit with short tail", "dur": 1.5},
    "riser": {"queries": ["riser build up", "tension riser"], "ai": "tension riser building up", "dur": 3.0},
    "pop": {"queries": ["pop ui", "bubble pop"], "ai": "clean soft pop UI sound", "dur": 0.5},
    "click": {"queries": ["ui click", "button click"], "ai": "crisp UI click", "dur": 0.5},
    "glitch": {"queries": ["glitch short", "digital glitch"], "ai": "short digital glitch", "dur": 0.8},
    "ding": {"queries": ["notification ding", "success chime"], "ai": "bright notification ding", "dur": 1.0},
    "typing": {"queries": ["keyboard typing", "typewriter"], "ai": "fast keyboard typing", "dur": 2.0},
    "cash": {"queries": ["cash register", "coins"], "ai": "cash register cha-ching", "dur": 1.5},
}


# ---------------------------------------------------------------- utilita'
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "track"


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def _license_ok(lic: str) -> bool:
    """Scarta licenze non commerciali / non derivative."""
    l = (lic or "").lower()
    return not any(x in l for x in ("by-nc", "/nc", "noncommercial", "non-commercial", "-nd", "/nd/"))


def _download(url: str, dest: Path, headers: dict | None = None) -> bool:
    try:
        r = requests.get(url, headers=headers, timeout=90, stream=True)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return dest.stat().st_size > 10_000
    except Exception as e:
        print(f"    ! download fallito: {e}")
        if dest.exists():
            dest.unlink()
        return False


def _eleven_keys() -> list[str]:
    raw = os.environ.get("ELEVENLABS_API_KEYS", "") + "," + os.environ.get("ELEVENLABS_API_KEY", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


# ---------------------------------------------------------------- provider (ricerca)
def search_freesound(query, n, min_s, max_s):
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        return []
    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query": query, "token": key, "page_size": n * 4, "sort": "rating_desc",
            "filter": f'license:("Creative Commons 0" OR "Attribution") duration:[{min_s} TO {max_s}]',
            "fields": "id,name,username,license,duration,previews,url",
        },
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        url = (it.get("previews") or {}).get("preview-hq-mp3")
        if url and _license_ok(it.get("license", "")):
            out.append({"id": f"fs{it['id']}", "title": it["name"], "author": it["username"],
                        "license": it["license"], "page": it["url"], "audio": url, "ext": ".mp3",
                        "source": "freesound"})
    return out[:n]


def search_openverse(query, n, min_s, max_s, category="music"):
    r = requests.get(
        "https://api.openverse.org/v1/audio/",
        params={"q": query, "license_type": "commercial", "category": category, "page_size": 20},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        dur = (it.get("duration") or 0) / 1000.0
        if dur and not (min_s <= dur <= max_s):
            continue
        lic = f"{it.get('license', '')} {it.get('license_version', '')}".strip()
        if not it.get("url") or not _license_ok(lic):
            continue
        ext = os.path.splitext(it["url"].split("?")[0])[1].lower()
        out.append({"id": f"ov{it['id'][:12]}", "title": it.get("title") or "track",
                    "author": it.get("creator") or "unknown", "license": lic,
                    "page": it.get("foreign_landing_url", ""), "audio": it["url"],
                    "ext": ext if ext in AUDIO_EXT else ".mp3", "source": "openverse"})
    return out[:n]


def eleven_generate(kind, prompt, seconds):
    """Genera audio con ElevenLabs. Ritorna bytes o None. Verifica i parametri sui docs ufficiali."""
    for key in _eleven_keys():
        try:
            if kind == "sfx":
                r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
                                  headers={"xi-api-key": key},
                                  json={"text": prompt, "duration_seconds": seconds, "prompt_influence": 0.5},
                                  timeout=120)
            else:
                r = requests.post("https://api.elevenlabs.io/v1/music",
                                  headers={"xi-api-key": key},
                                  json={"prompt": prompt, "music_length_ms": int(seconds * 1000),
                                        "force_instrumental": True},
                                  timeout=300)
            if r.status_code == 200 and len(r.content) > 5000:
                return r.content
            print(f"    ! ElevenLabs {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"    ! ElevenLabs errore: {e}")
    return None


# ---------------------------------------------------------------- orchestrazione
def _fetch_group(kind, name, cfg, providers, per_query, manifest):
    base = (MUSIC_DIR if kind == "music" else SFX_DIR) / name
    min_s, max_s = (45, 240) if kind == "music" else (0.2, 6)
    got = 0
    for q in cfg["queries"]:
        for prov in providers:
            if prov == "eleven":
                continue
            try:
                if prov == "freesound":
                    items = search_freesound(q, per_query, min_s, max_s)
                else:
                    items = search_openverse(q, per_query, min_s, max_s,
                                             "music" if kind == "music" else "sound_effect")
            except Exception as e:
                print(f"  ! {prov} '{q}': {e}")
                continue
            for it in items:
                dest = base / f"{_slug(it['title'])}_{it['id']}{it['ext']}"
                key = str(dest.relative_to(ROOT)).replace("\\", "/")
                if dest.exists() or key in manifest:
                    continue
                print(f"  + [{prov}] {it['title']} ({it['license']})")
                if _download(it["audio"], dest):
                    manifest[key] = {k: it[k] for k in ("title", "author", "license", "page", "source")}
                    manifest[key]["category"] = f"{kind}/{name}"
                    got += 1
            time.sleep(0.5)
    return got


def _generate_ai(kind, name, cfg, n, manifest):
    base = (MUSIC_DIR if kind == "music" else SFX_DIR) / name
    dur = 45 if kind == "music" else cfg.get("dur", 1.5)
    for i in range(n):
        data = eleven_generate(kind, cfg["ai"], dur)
        if not data:
            return
        dest = base / f"ai_{_slug(name)}_{int(time.time())}_{i}.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        key = str(dest.relative_to(ROOT)).replace("\\", "/")
        manifest[key] = {"title": cfg["ai"][:60], "author": "ElevenLabs AI", "license": "AI-generated (verifica piano)",
                         "page": "", "source": "eleven", "category": f"{kind}/{name}"}
        print(f"  + [eleven] {dest.name}")


def pick_music(niche: str | None, seed: int | None = None) -> str | None:
    """Ritorna un brano casuale per la nicchia (o None). Da passare a mix_sfx(bg_music_path=...)."""
    folder = MUSIC_DIR / (niche or "")
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT]
    if not files:
        return None
    rnd = random.Random(seed) if seed is not None else random
    return str(rnd.choice(files))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["music", "sfx", "all"], default="all")
    ap.add_argument("--category", help="nome categoria (es. dark_motivational, whoosh)")
    ap.add_argument("--provider", default="freesound,openverse", help="freesound,openverse,eleven")
    ap.add_argument("--per-query", type=int, default=2)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        print("MUSIC:", ", ".join(MUSIC))
        print("SFX:  ", ", ".join(SFX))
        return 0

    providers = [p.strip() for p in a.provider.split(",") if p.strip()]
    manifest = _load_manifest()
    total = 0
    jobs = []
    if a.kind in ("music", "all"):
        jobs += [("music", n, c) for n, c in MUSIC.items()]
    if a.kind in ("sfx", "all"):
        jobs += [("sfx", n, c) for n, c in SFX.items()]
    for kind, name, cfg in jobs:
        if a.category and a.category != name:
            continue
        print(f"[{kind}/{name}]")
        total += _fetch_group(kind, name, cfg, providers, a.per_query, manifest)
        if "eleven" in providers:
            _generate_ai(kind, name, cfg, a.per_query, manifest)
        _save_manifest(manifest)
    print(f"Fatto. Nuovi file: {total}. Manifest: {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
