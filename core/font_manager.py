"""
Semantic Typography Engine v1 — Gestore asset e downloader automatico font.

- Mantiene e verifica la cartella `assets/fonts/`.
- `ensure_font_exists(font_name)` controlla .ttf/.otf locali, altrimenti
  scarica da Google Fonts (repo GitHub google/fonts, endpoint statico sicuro
  raw.githubusercontent.com) e salva in assets/fonts/.
- Fallback su font di sistema nativi (Arial, Impact, Times...) per evitare
  crash senza connessione.

Uso:
    from core.font_manager import FontManager, ensure_font_exists
    path = ensure_font_exists("Anton")
    manager = FontManager()
    paths = manager.ensure_preset_fonts("tech_ai")  # {"base": ..., "impact": ..., "accent": ...}
"""

import os
import re
from pathlib import Path

try:
    from config import BASE_DIR
except Exception:  # import isolato nei test
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONTS_DIR = Path(BASE_DIR) / "assets" / "fonts"

# Base raw sicura (GitHub google/fonts, mirror statico, niente API key).
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/google/fonts/main"
_GITHUB_RAW_ALT = "https://github.com/google/fonts/raw/main"

# Mappa normalizzata -> (sottocartella ofl, file) per i font dei preset.
# I file variable [wght] sono caricabili da Pillow (istanza default).
# URL-encodiamo le parentesi quadre (%5B/%5D).
_FONT_FILES: dict[str, tuple[str, str]] = {
    "inter": ("inter", "Inter%5Bopsz%2Cwght%5D.ttf"),
    "roboto": ("roboto", "Roboto%5Bwdth%2Cwght%5D.ttf"),
    "anton": ("anton", "Anton-Regular.ttf"),
    "impact": ("__system__", "impact.ttf"),  # font di sistema, non su Google Fonts
    "playfairdisplay": ("playfairdisplay", "PlayfairDisplay%5Bwght%5D.ttf"),
    "bebasneue": ("bebasneue", "BebasNeue-Regular.ttf"),
    "orbitron": ("orbitron", "Orbitron%5Bwght%5D.ttf"),
    "spacemono": ("spacemono", "SpaceMono-Regular.ttf"),
    "opensans": ("opensans", "OpenSans%5Bwdth%2Cwght%5D.ttf"),
    "oswald": ("oswald", "Oswald%5Bwght%5D.ttf"),
    "permanentmarker": ("permanentmarker", "PermanentMarker-Regular.ttf"),
    "poppins": ("poppins", "Poppins-Regular.ttf"),
    "lato": ("lato", "Lato-Regular.ttf"),
    "cinzel": ("cinzel", "Cinzel%5Bwght%5D.ttf"),
    "bodonimoda": ("bodonimoda", "BodoniModa%5Bopsz%2Cwght%5D.ttf"),
    "caveat": ("caveat", "Caveat%5Bwght%5D.ttf"),
    "pacifico": ("pacifico", "Pacifico-Regular.ttf"),
    "nunito": ("nunito", "Nunito%5Bwght%5D.ttf"),
    "leaguespartan": ("leaguespartan", "LeagueSpartan%5Bwght%5D.ttf"),
    "patrickhand": ("patrickhand", "PatrickHand-Regular.ttf"),
    "kalam": ("kalam", "Kalam-Regular.ttf"),
    "montserrat": ("montserrat", "Montserrat%5Bwght%5D.ttf"),
    "montserratblack": ("montserrat", "Montserrat%5Bwght%5D.ttf"),
    "pristina": ("__system__", "__missing__"),  # non open-source: fallback di sistema
    "editorsnote": ("__system__", "__missing__"),
}

# Font di sistema nativi per fallback (mai crash senza internet).
_SYSTEM_FALLBACKS: list[str] = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\timesbd.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]

# Ruolo -> fallback di sistema preferito (look simile quando il download fallisce).
_ROLE_SYSTEM_PREFERENCE: dict[str, list[str]] = {
    "base": ["arial.ttf", "arialbd.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
    "impact": ["impact.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arial.ttf"],
    "accent": ["times.ttf", "timesbd.ttf", "georgia.ttf", "DejaVuSans.ttf", "arial.ttf"],
}


def _normalize_name(name: str) -> str:
    """Minuscole senza spazi/trattini/underscore (per match file e mappa URL)."""
    return re.sub(r"[\s\-_']+", "", (name or "").strip().lower())


def _candidate_local_names(font_name: str) -> list[str]:
    """Varianti di filename da cercare in assets/fonts/."""
    norm = _normalize_name(font_name)
    raw = (font_name or "").strip()
    compact_space = re.sub(r"\s+", "", raw)
    return [
        f"{raw}.ttf",
        f"{raw}.otf",
        f"{compact_space}.ttf",
        f"{compact_space}.otf",
        f"{norm}.ttf",
        f"{norm}.otf",
    ]


def _find_local_font(font_name: str, fonts_dir: Path) -> str | None:
    """Cerca un file .ttf/.otf corrispondente (case-insensitive, prefisso tollerato)."""
    try:
        if not fonts_dir.is_dir():
            return None
        files = [p for p in fonts_dir.iterdir() if p.is_file()]
    except OSError:
        return None
    norm = _normalize_name(font_name)
    # 1) match esatto tra i candidati (case-insensitive).
    lowered = {p.name.lower(): p for p in files}
    for cand in _candidate_local_names(font_name):
        hit = lowered.get(cand.lower())
        if hit is not None and hit.suffix.lower() in (".ttf", ".otf"):
            return str(hit)
    # 2) prefisso: es. "bebasneue-regular.ttf" per "Bebas Neue".
    for p in files:
        if p.suffix.lower() not in (".ttf", ".otf"):
            continue
        stem_norm = _normalize_name(p.stem)
        if stem_norm == norm or stem_norm.startswith(norm) or norm.startswith(stem_norm):
            return str(p)
    return None


def _find_system_font(prefer: list[str] | None = None) -> str | None:
    """Primo font di sistema esistente (preferenze opzionali per nome file)."""
    search_bases = [
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/System/Library/Fonts"),
    ]
    if prefer:
        for base in search_bases:
            for fname in prefer:
                try:
                    cand = base / fname
                    if cand.is_file():
                        return str(cand)
                except OSError:
                    continue
    for cand in _SYSTEM_FALLBACKS:
        try:
            if os.path.isfile(cand):
                return cand
        except OSError:
            continue
    return None


def _download_urls(font_name: str) -> list[str]:
    """URL candidate per il download (mappa nota + guess generici)."""
    norm = _normalize_name(font_name)
    urls: list[str] = []
    entry = _FONT_FILES.get(norm)
    if entry is not None:
        subdir, fname = entry
        if subdir != "__system__":
            urls.append(f"{_GITHUB_RAW_BASE}/ofl/{subdir}/{fname}")
            urls.append(f"{_GITHUB_RAW_ALT}/ofl/{subdir}/{fname}")
    else:
        # Guess generico: ofl/<norm>/<variants>. Prova Regular/Bold/variabile.
        family_variants = [
            f"{font_name.strip()}-Regular.ttf",
            f"{font_name.strip().replace(' ', '')}-Regular.ttf",
        ]
        for v in family_variants:
            safe = v.replace(" ", "%20")
            urls.append(f"{_GITHUB_RAW_BASE}/ofl/{norm}/{safe}")
        urls.append(f"{_GITHUB_RAW_BASE}/ofl/{norm}/{norm}-regular.ttf")
    return urls


def _download_to(font_name: str, dest: Path) -> bool:
    """Scarica il font al percorso dest. Ritorna True se riuscito e valido."""
    urls = _download_urls(font_name)
    if not urls:
        return False
    try:
        import requests
    except ImportError:
        return False
    for url in urls:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200 or not resp.content:
                continue
            # Sanity: un TTF/OTF valido è almeno qualche KB e inizia con head nota.
            content = resp.content
            if len(content) < 4096:
                continue
            magic = content[:4]
            if magic not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"wOFF"):
                # I TTF variable iniziano con 0x00010000; accetta anche sfnt generici.
                # Se magic ignoto ma size plausibile (>20KB), accetta comunque.
                if len(content) < 20000:
                    continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(content)
            # Verifica caricabile da Pillow prima di promuoverlo.
            try:
                from PIL import ImageFont
                ImageFont.truetype(str(tmp), 32)
            except Exception:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                continue
            try:
                tmp.replace(dest)
            except OSError:
                try:
                    dest.write_bytes(content)
                    tmp.unlink()
                except OSError:
                    continue
            return True
        except Exception:
            continue
    return False


class FontManager:
    """Gestore dei font del Semantic Typography Engine.

    Mantiene `assets/fonts/`, scarica i font mancanti e non solleva mai
    per assenza di rete: in quel caso ritorna un font di sistema.
    """

    def __init__(self, fonts_dir: str | Path | None = None):
        self.fonts_dir = Path(fonts_dir) if fonts_dir else FONTS_DIR
        try:
            self.fonts_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._cache: dict[str, str] = {}

    def ensure_font_exists(self, font_name: str) -> str:
        """Ritorna il percorso del font (locale, scaricato o fallback di sistema).

        Non solleva mai: se tutto fallisce, ritorna "" (il chiamante userà
        il font di default di Pillow / renderer.load_font).
        """
        key = _normalize_name(font_name or "")
        if not key:
            return _find_system_font() or ""
        if key in self._cache:
            cached = self._cache[key]
            try:
                if cached and os.path.isfile(cached):
                    return cached
            except OSError:
                pass
        # 1) locale
        try:
            hit = _find_local_font(font_name, self.fonts_dir)
        except Exception:
            hit = None
        if hit:
            self._cache[key] = hit
            return hit
        # 2) download (font di sistema puri saltano il download)
        entry = _FONT_FILES.get(key)
        dest = self.fonts_dir / f"{(font_name or '').strip().replace(' ', '') or key}.ttf"
        if entry is None or entry[0] != "__system__":
            try:
                if _download_to(font_name, dest):
                    self._cache[key] = str(dest)
                    return str(dest)
            except Exception:
                pass
            # Riprova: magari il download ha creato il file con altro nome.
            try:
                hit = _find_local_font(font_name, self.fonts_dir)
            except Exception:
                hit = None
            if hit:
                self._cache[key] = hit
                return hit
        # 3) fallback di sistema (per ruolo se riconoscibile, altrimenti generico)
        role_hint: list[str] | None = None
        lowered_raw = (font_name or "").lower()
        if any(k in lowered_raw for k in ("impact", "anton", "bebas", "oswald", "spartan", "orbitron", "cinzel")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["impact"]
        elif any(k in lowered_raw for k in ("hand", "marker", "caveat", "pacifico", "kalam", "playfair", "pristina", "note")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["accent"]
        else:
            role_hint = _ROLE_SYSTEM_PREFERENCE["base"]
        sys_font = _find_system_font(role_hint) or _find_system_font()
        result = sys_font or ""
        self._cache[key] = result
        return result

    def ensure_preset_fonts(self, niche_or_preset) -> dict[str, str]:
        """Assicura i 3 font del preset: {"base": path, "impact": path, "accent": path}.

        Accetta il nome nicchia ("tech_ai") o il dict preset da typography_presets.get_preset().
        Non solleva mai; i path possono essere "" (fallback Pillow a valle).
        """
        try:
            from core.typography_presets import get_preset
            preset = get_preset(niche_or_preset) if isinstance(niche_or_preset, str) else dict(niche_or_preset)
        except Exception:
            preset = {"fonts": {"base": [], "impact": [], "accent": []}}
        fonts = preset.get("fonts", {}) if isinstance(preset, dict) else {}
        out: dict[str, str] = {}
        for role in ("base", "impact", "accent"):
            candidates = fonts.get(role, []) if isinstance(fonts, dict) else []
            path = ""
            for cand in candidates if isinstance(candidates, list) else []:
                try:
                    path = self.ensure_font_exists(str(cand))
                except Exception:
                    path = ""
                if path and os.path.isfile(path):
                    break
            if not path:
                # Ultimo tentativo: fallback di sistema per ruolo.
                path = _find_system_font(_ROLE_SYSTEM_PREFERENCE.get(role)) or ""
            out[role] = path
        return out

    def load_font(self, font_name: str, size: int):
        """Carica il font PIL alla dimensione data (fallback mai bloccante)."""
        from PIL import ImageFont
        try:
            size_i = max(8, int(size))
        except (TypeError, ValueError):
            size_i = 60
        path = ""
        try:
            path = self.ensure_font_exists(font_name)
        except Exception:
            path = ""
        if path:
            try:
                return ImageFont.truetype(path, size_i)
            except Exception:
                pass
        # Fallback: renderer.load_font (rispetta SUBTITLE_FONT_PATH + sistema).
        try:
            from core.renderer import load_font as _load_font
            return _load_font(size_i)
        except Exception:
            pass
        return ImageFont.load_default()

    def clear_cache(self) -> None:
        self._cache.clear()


# Istanza condivisa + scorciatoie funzionali (spec: ensure_font_exists(font_name) -> str).
_default_manager = FontManager()


def ensure_font_exists(font_name: str) -> str:
    """Scorciatoia: assicura il font e ritorna il percorso (vedi FontManager)."""
    return _default_manager.ensure_font_exists(font_name)


def ensure_preset_fonts(niche_or_preset) -> dict[str, str]:
    """Scorciatoia: assicura i 3 font del preset."""
    return _default_manager.ensure_preset_fonts(niche_or_preset)
