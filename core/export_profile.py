"""
Profilo di export centrale (P0 WS-E1 + WS-E2).

Unica fonte di verità per i parametri di encode video/audio: `video_builder.py`
e `video_composer.py` devono usare queste funzioni invece di comandi duplicati.
Logica pura e deterministica (niente I/O, testabile con `unittest`); l'unica
eccezione è `probe_encoder_support()` (I/O ffmpeg, con cache) usata per il
fallback silenzioso se `high`/`level` non sono supportati.

Profili: draft (bozze veloci) | standard (quotidiano) | final (default).
"""

from __future__ import annotations

import os
import shutil
import subprocess

# Preset x264 validi (whitelist estesa: include slow/slower per il profilo final).
PRESET_WHITELIST: tuple[str, ...] = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
)

PROFILES: dict[str, dict] = {
    "draft": {"preset": "ultrafast", "crf": 23,
              "uso": "bozze veloci"},
    "standard": {"preset": "medium", "crf": 18,
                 "uso": "uso quotidiano"},
    "final": {"preset": "slow", "crf": 17,
              "uso": "export finale"},
}

DEFAULT_QUALITY = "final"

# Valori di default (sovrascrivibili via config/env, vedi config.py).
_DEFAULTS: dict[str, str] = {
    "profile": "high",
    "level": "4.2",
    "maxrate": "16M",
    "bufsize": "32M",
    "tune": "",
    "crf": "17",
    "audio_bitrate": "192k",
    "audio_rate": "44100",
}


def _env_str(key: str, default: str = "") -> str:
    try:
        raw = os.environ.get(key)
        if raw is None:
            try:
                import config as _cfg
                val = getattr(_cfg, key, default)
                return str(val) if val is not None else default
            except Exception:
                return default
        return raw.strip()
    except Exception:
        return default


def normalize_quality(quality: str | None) -> str:
    """Normalizza il nome profilo (fallback 'final', mai eccezioni)."""
    try:
        q = str(quality or "").strip().lower()
    except Exception:
        return DEFAULT_QUALITY
    if q in PROFILES:
        return q
    # Alias CLI legacy.
    if q in ("bozza", "draft-fast"):
        return "draft"
    return DEFAULT_QUALITY


def get_export_profile(quality: str | None = None) -> dict:
    """Ritorna il profilo export {name, preset, crf, uso, ...}.

    Precedenza preset: EXPORT_PRESET (se impostato e valido) > FFMPEG_PRESET
    (solo se impostato esplicitamente nell'ambiente) > preset del profilo.
    Precedenza CRF: EXPORT_CRF (se impostato esplicitamente) > crf del profilo.
    Pura e deterministica (legge solo env/config, nessun I/O).
    """
    name = normalize_quality(quality or _env_str("EXPORT_QUALITY", DEFAULT_QUALITY))
    base = PROFILES[name]
    preset = str(base["preset"])
    crf = int(base["crf"])
    # Override esplicito EXPORT_PRESET (vuoto = dal profilo).
    exp_preset = _env_str("EXPORT_PRESET", "")
    if exp_preset and exp_preset in PRESET_WHITELIST:
        preset = exp_preset
    else:
        # Retrocompatibilità: FFMPEG_PRESET esplicito vince sul profilo.
        # (Solo env esplicito: il default di config "veryfast" NON deve
        # oscurare il profilo final/slow.)
        try:
            legacy = (os.environ.get("FFMPEG_PRESET", "") or "").strip()
        except Exception:
            legacy = ""
        if legacy and legacy in PRESET_WHITELIST:
            preset = legacy
    # Override esplicito EXPORT_CRF.
    try:
        if "EXPORT_CRF" in os.environ and str(os.environ.get("EXPORT_CRF", "")).strip():
            crf = max(0, min(51, int(str(os.environ["EXPORT_CRF"]).strip())))
    except (TypeError, ValueError):
        pass
    try:
        profile = _env_str("EXPORT_PROFILE", _DEFAULTS["profile"]) or _DEFAULTS["profile"]
        level = _env_str("EXPORT_LEVEL", _DEFAULTS["level"]) or _DEFAULTS["level"]
        maxrate = _env_str("EXPORT_MAXRATE", _DEFAULTS["maxrate"]) or _DEFAULTS["maxrate"]
        bufsize = _env_str("EXPORT_BUFSIZE", _DEFAULTS["bufsize"]) or _DEFAULTS["bufsize"]
        tune = _env_str("EXPORT_X264_TUNE", _DEFAULTS["tune"])
        audio_bitrate = _env_str("AUDIO_FINAL_BITRATE", _DEFAULTS["audio_bitrate"])
        audio_rate = _env_str("AUDIO_SAMPLE_RATE", _DEFAULTS["audio_rate"])
    except Exception:
        profile, level, maxrate, bufsize = "high", "4.2", "16M", "32M"
        tune, audio_bitrate, audio_rate = "", "192k", "44100"
    return {
        "name": name,
        "preset": preset,
        "crf": crf,
        "uso": base["uso"],
        "profile": profile,
        "level": level,
        "maxrate": maxrate,
        "bufsize": bufsize,
        "tune": tune,
        "audio_bitrate": audio_bitrate,
        "audio_rate": audio_rate,
    }


def color_convert_filter() -> str:
    """Filtro di conversione RGB→YUV con matrice BT.709 (WS-E2, punto critico).

    Va applicato come ULTIMO filtro video prima dell'encode: converte davvero
    con la matrice giusta invece di limitarsi a taggare (taggare senza
    convertire sposta i colori).
    """
    return (
        "scale=flags=bicubic+accurate_rnd+full_chroma_int"
        ":out_color_matrix=bt709:out_range=tv,format=yuv420p"
    )


def color_tag_args(enabled: bool | None = None) -> list[str]:
    """Tag colore BT.709 per l'mp4 (da usare insieme a color_convert_filter).

    NOTA di compatibilità (misurata su ffmpeg full build 2024-12-26):
    `-color_trc`/`-color_primaries` NON vengono propagati nel VUI di libx264
    (restano `unknown`), mentre `-x264-params colorprim/transfer/colormatrix`
    sì. Si usano entrambi: i flag generici per il container, gli x264-params
    come effettivi (verificato con ffprobe: tutti e quattro a bt709/tv).
    """
    try:
        if enabled is None:
            raw = _env_str("EXPORT_COLOR_TAGS", "1")
            enabled = raw.strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        enabled = True
    if not enabled:
        return []
    return [
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709",
    ]


def grain_filter(strength: int | None = None) -> str:
    """Filtro grain leggero per il SOLO fondo (WS-E2).

    `noise=alls=5:allf=t+u` dopo Ken Burns/eq/vignette e prima dell'overlay:
    contrasta banding dei gradienti e conserva dettaglio dopo la ricompressione.
    Mai su testo/personaggio (ramo background separato). "" se 0/off.
    """
    try:
        if strength is None:
            strength = int(float(_env_str("EXPORT_GRAIN_STRENGTH", "5") or "5"))
        strength = max(0, min(30, int(strength)))
    except (TypeError, ValueError):
        strength = 5
    if strength <= 0:
        return ""
    return f"noise=alls={strength}:allf=t+u"


def build_video_encode_args(
    profile: dict | None = None,
    fps: int = 30,
    capabilities: dict | None = None,
) -> list[str]:
    """Argomenti di encode condivisi da builder e composer (lista, no shell).

    Include: libx264 preset/crf/profile/level, yuv420p, maxrate/bufsize,
    GOP 60, tag colore BT.709, AAC 192k, faststart. `fps` accettato per
    compatibilità API (il GOP è fisso a 60 = 2s a 30fps).
    `capabilities` = {"high": bool, "level": bool} per il fallback silenzioso
    (None = tutto supportato).
    """
    prof = dict(profile) if isinstance(profile, dict) else get_export_profile()
    preset = str(prof.get("preset", "slow"))
    if preset not in PRESET_WHITELIST:
        preset = "slow"
    try:
        crf = max(0, min(51, int(prof.get("crf", 17))))
    except (TypeError, ValueError):
        crf = 17
    caps = capabilities or {"high": True, "level": True}
    args: list[str] = [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
    ]
    if caps.get("high", True) and str(prof.get("profile", "high") or "high").strip():
        args += ["-profile:v", str(prof.get("profile", "high")).strip()]
    if caps.get("level", True) and str(prof.get("level", "4.2") or "4.2").strip():
        args += ["-level", str(prof.get("level", "4.2")).strip()]
    args += [
        "-pix_fmt", "yuv420p",
        "-maxrate", str(prof.get("maxrate", "16M")),
        "-bufsize", str(prof.get("bufsize", "32M")),
        "-g", "60",
        "-keyint_min", "30",
        "-movflags", "+faststart",
    ]
    try:
        tune = str(prof.get("tune", "") or "").strip()
    except Exception:
        tune = ""
    if tune:
        args += ["-tune", tune]
    args += color_tag_args()
    args += [
        "-c:a", "aac",
        "-b:a", str(prof.get("audio_bitrate", "192k")),
        "-ar", str(prof.get("audio_rate", "44100")),
        "-shortest",
    ]
    return args


def legacy_encode_args() -> list[str]:
    """Argomenti pre-P0 (crf 20 + FFMPEG_PRESET config, nessun tag colore).

    Usati quando EXPORT_ENABLED=0: risultato equivalente al comportamento
    precedente.
    """
    try:
        import config as _cfg
        preset = str(getattr(_cfg, "FFMPEG_PRESET", "veryfast") or "veryfast").strip()
    except Exception:
        preset = "veryfast"
    if preset not in PRESET_WHITELIST:
        preset = "veryfast"
    return [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", "20",
        "-g", "60",
        "-keyint_min", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
    ]


# --- I/O: probe capacità encoder (con cache) ---

_caps_cache: dict | None = None


def probe_encoder_support() -> dict:
    """Verifica supporto `high`/`level` di libx264 (I/O, cachato, mai eccezioni).

    Ritorna {"high": bool, "level": bool}. Se ffmpeg manca o il probe fallisce,
    ritorna tutto True (il fallback avviene comunque in modo silenzioso: gli
    argomenti non supportati fanno fallire l'encode e i builder ritentano
    in legacy — vedi video_builder).
    """
    global _caps_cache
    if _caps_cache is not None:
        return dict(_caps_cache)
    caps = {"high": True, "level": True}
    try:
        ff = shutil.which("ffmpeg")
        if ff is None:
            _caps_cache = caps
            return dict(caps)
        res = subprocess.run(
            [ff, "-hide_banner", "-h", "encoder=libx264"],
            capture_output=True, text=True, timeout=30,
        )
        out = (res.stdout or "") + (res.stderr or "")
        # Euristica: se l'help elenca i profili, high è supportato.
        if "high" not in out.lower():
            caps["high"] = False
        if "-level" not in out:
            caps["level"] = False
    except Exception:
        pass
    _caps_cache = caps
    return dict(caps)


def should_use_export_profile() -> bool:
    """Vero se il path P0 è attivo (EXPORT_ENABLED=1, mai eccezioni)."""
    try:
        raw = _env_str("EXPORT_ENABLED", "1")
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        return True
