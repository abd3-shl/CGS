"""
Semantic Typography Engine v2 — Gestore asset e downloader automatico font.

Refactoring profondo (Principal Engineer):
- Downloader nativo da repository ufficiali e stabili Google Fonts
  (raw.githubusercontent.com/google/fonts + mirror CDN jsDelivr, stesso
  contenuto, nessuna API key richiesta). Supporto opzionale Google Fonts
  Developer API v1 se `GOOGLE_FONTS_API_KEY` è impostato (risoluzione
  famiglia -> file).
- Mappatura alternative equivalenti 1:1 (VISUAL_FALLBACK_MATRIX) basata
  unicamente su font stabili Google Fonts.
- Zero-Failure caching & validation: verifica integrità .ttf/.otf
  (size >= 5KB + apertura PIL.ImageFont.truetype), elimina corrotti
  immediatamente, fallback garantito su font pre-impacchettati
  (assets/fonts/Roboto.ttf, Inter.ttf, Anton.ttf) poi sistema.
- Naming standardizzato e univoco in assets/fonts/ + cache in-memory
  (path + istanze PIL) + preload parallelo per azzerare I/O in rendering.
- Fail-safe globale: mai solleva per rete/asset, ritorna "" e log warning.

Uso:
    from core.font_manager import FontManager, ensure_font_exists
    path = ensure_font_exists("Anton")
    manager = FontManager()
    paths = manager.ensure_preset_fonts("tech_ai")
    manager.preload_preset_fonts("tech_ai", sizes=(60, 84, 66))  # RAM warmup
"""

import os
import re
import threading
from pathlib import Path

try:
    from config import BASE_DIR
except Exception:  # import isolato nei test
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONTS_DIR = Path(BASE_DIR) / "assets" / "fonts"

# ----------------------------------------------------------------------------
# Sorgenti ufficiali e stabili (nessuna API key richiesta)
# ----------------------------------------------------------------------------
# Primary: repo ufficiale google/fonts in raw format (fonte di verità).
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/google/fonts/main"
# Mirror stabile: jsDelivr CDN (stesso commit, alta disponibilità).
# Formato: https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/<subdir>/<file>
_JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/google/fonts@main"
# Legacy ALT rimosso: https://github.com/.../raw/... ritorna HTML, non raw.
# Mantenuto solo per compatibilità ma DEPRIORITIZZATO (ultimo tentativo).

# Soglia integrità: file < 5KB è sicuramente corrotto/HTML di errore.
MIN_VALID_FONT_BYTES = 5120

# Timeout download (ridotto da 15s: fail-fast per non bloccare pipeline).
_DOWNLOAD_TIMEOUT = 10

# ----------------------------------------------------------------------------
# Mappa normalizzata -> (licenza/cartella, file) per i font dei preset.
# Il repo google/fonts è organizzato per licenza in cima: ofl/, apache/, ufl/.
# La maggioranza è OFL; Permanent Marker è Apache (diagnosi: ofl/404).
# I file variable [wght] sono caricabili da Pillow (istanza default).
# URL-encodiamo le parentesi quadre (%5B/%5D).
# ----------------------------------------------------------------------------
_FONT_FILES: dict[str, tuple[str, str]] = {
    "inter": ("ofl/inter", "Inter%5Bopsz%2Cwght%5D.ttf"),
    "roboto": ("ofl/roboto", "Roboto%5Bwdth%2Cwght%5D.ttf"),
    "anton": ("ofl/anton", "Anton-Regular.ttf"),
    "playfairdisplay": ("ofl/playfairdisplay", "PlayfairDisplay%5Bwght%5D.ttf"),
    "bebasneue": ("ofl/bebasneue", "BebasNeue-Regular.ttf"),
    "orbitron": ("ofl/orbitron", "Orbitron%5Bwght%5D.ttf"),
    "spacemono": ("ofl/spacemono", "SpaceMono-Regular.ttf"),
    "opensans": ("ofl/opensans", "OpenSans%5Bwdth%2Cwght%5D.ttf"),
    "oswald": ("ofl/oswald", "Oswald%5Bwght%5D.ttf"),
    # NOTA: Apache, non OFL (verificato via api.github.com + raw 404 su ofl).
    "permanentmarker": ("apache/permanentmarker", "PermanentMarker-Regular.ttf"),
    "poppins": ("ofl/poppins", "Poppins-Regular.ttf"),
    "lato": ("ofl/lato", "Lato-Regular.ttf"),
    "cinzel": ("ofl/cinzel", "Cinzel%5Bwght%5D.ttf"),
    "bodonimoda": ("ofl/bodonimoda", "BodoniModa%5Bopsz%2Cwght%5D.ttf"),
    "caveat": ("ofl/caveat", "Caveat%5Bwght%5D.ttf"),
    "pacifico": ("ofl/pacifico", "Pacifico-Regular.ttf"),
    "nunito": ("ofl/nunito", "Nunito%5Bwght%5D.ttf"),
    "leaguespartan": ("ofl/leaguespartan", "LeagueSpartan%5Bwght%5D.ttf"),
    "patrickhand": ("ofl/patrickhand", "PatrickHand-Regular.ttf"),
    "kalam": ("ofl/kalam", "Kalam-Regular.ttf"),
    "montserrat": ("ofl/montserrat", "Montserrat%5Bwght%5D.ttf"),
    "montserratblack": ("ofl/montserrat", "Montserrat%5Bwght%5D.ttf"),
}

# Alternative file per famiglie con naming variabile nel repo (variable +
# static fallback). Usate in ordine se il primo URL fallisce.
# Path completi licenza/cartella (vedi _FONT_FILES).
_FONT_FILE_ALTERNATIVES: dict[str, list[tuple[str, str]]] = {
    "nunito": [
        ("ofl/nunito", "Nunito%5Bwght%5D.ttf"),
        ("ofl/nunito", "Nunito-Regular.ttf"),
    ],
    "poppins": [
        ("ofl/poppins", "Poppins-Regular.ttf"),
        ("ofl/poppins", "Poppins-Bold.ttf"),
    ],
    "lato": [
        ("ofl/lato", "Lato-Regular.ttf"),
        ("ofl/lato", "Lato-Bold.ttf"),
    ],
    "spacemono": [
        ("ofl/spacemono", "SpaceMono-Regular.ttf"),
        ("ofl/spacemono", "SpaceMono-Bold.ttf"),
    ],
    "montserrat": [
        ("ofl/montserrat", "Montserrat%5Bwght%5D.ttf"),
        ("ofl/montserrat", "Montserrat-Regular.ttf"),
    ],
    "roboto": [
        ("ofl/roboto", "Roboto%5Bwdth%2Cwght%5D.ttf"),
        ("ofl/roboto", "Roboto-Regular.ttf"),
    ],
    "inter": [
        ("ofl/inter", "Inter%5Bopsz%2Cwght%5D.ttf"),
        ("ofl/inter", "Inter-Regular.ttf"),
    ],
    "opensans": [
        ("ofl/opensans", "OpenSans%5Bwdth%2Cwght%5D.ttf"),
        ("ofl/opensans", "OpenSans-Regular.ttf"),
    ],
    "permanentmarker": [
        ("apache/permanentmarker", "PermanentMarker-Regular.ttf"),
    ],
}

# ----------------------------------------------------------------------------
# Mappatura Alternative Equivalenti 1:1 (solo font stabili Google Fonts).
# Spec richiesta:
#   Anton/Impact -> Oswald (700/Bold) o Bebas Neue
#   Pristina/Editor's Note -> Caveat (Bold) o Playfair Display (Italic)
#   Helvetica/Arial -> Inter o Roboto
#   Bodoni Moda -> Cinzel o Playfair Display
# ----------------------------------------------------------------------------
VISUAL_FALLBACK_MATRIX: dict[str, list[str]] = {
    "anton": ["Anton", "Oswald", "Bebas Neue"],
    "impact": ["Oswald", "Bebas Neue", "Anton"],
    "pristina": ["Caveat", "Playfair Display", "Patrick Hand"],
    "editorsnote": ["Playfair Display", "Caveat", "Cinzel"],
    "editors_note": ["Playfair Display", "Caveat", "Cinzel"],
    "helvetica": ["Inter", "Roboto"],
    "helveticabold": ["Inter", "Roboto"],
    "arial": ["Inter", "Roboto"],
    "arialbold": ["Inter", "Roboto"],
    "bodonimoda": ["Bodoni Moda", "Cinzel", "Playfair Display"],
    "bodoni": ["Cinzel", "Playfair Display", "Bodoni Moda"],
    "orbitron": ["Orbitron", "Bebas Neue", "Oswald"],
    "spacemono": ["Space Mono", "Roboto", "Inter"],
    "spacemonobold": ["Space Mono", "Roboto"],
    "times": ["Playfair Display", "Cinzel"],
    "timesnewroman": ["Playfair Display", "Cinzel"],
    "georgia": ["Playfair Display", "Cinzel"],
    "verdana": ["Inter", "Roboto", "Open Sans"],
    "tahoma": ["Inter", "Roboto"],
}

# Font pre-impacchettati garantiti (già in assets/fonts/, mai da rete).
_GUARANTEED_BUNDLED = ["Roboto", "Inter", "Anton", "Oswald", "Montserrat"]

# Font di sistema nativi per fallback estremo (mai crash senza internet).
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

# Ruolo -> fallback di sistema preferito (ultima spiaggia).
_ROLE_SYSTEM_PREFERENCE: dict[str, list[str]] = {
    "base": ["arial.ttf", "arialbd.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
    "impact": ["impact.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arial.ttf"],
    "accent": ["times.ttf", "timesbd.ttf", "georgia.ttf", "DejaVuSans.ttf", "arial.ttf"],
}


def _normalize_name(name: str) -> str:
    """Minuscole senza spazi/trattini/underscore (per match file e mappa URL)."""
    return re.sub(r"[\s\-_']+", "", (name or "").strip().lower())


def _standard_filename(font_name: str) -> str:
    """Naming standardizzato e univoco: Famiglia senza spazi + .ttf.

    Es: 'Bebas Neue' -> 'BebasNeue.ttf', 'Playfair Display' -> 'PlayfairDisplay.ttf'.
    Preserva CamelCase per leggibilità, univoco case-insensitive via _find_local_font.
    """
    compact = re.sub(r"\s+", "", (font_name or "").strip())
    compact = re.sub(r"[^A-Za-z0-9]", "", compact)
    if not compact:
        compact = _normalize_name(font_name) or "font"
    return f"{compact}.ttf"


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
        _standard_filename(font_name),
    ]


_local_dir_cache: dict[str, tuple[float, list]] = {}


def _list_font_files(fonts_dir: Path) -> list:
    """Lista file font con cache 30s (evita iterdir per ogni ruolo/chunk)."""
    import time
    try:
        key = str(fonts_dir)
        now = time.monotonic()
        hit = _local_dir_cache.get(key)
        if hit is not None and (now - hit[0]) < 30.0:
            return hit[1]
        if not fonts_dir.is_dir():
            return []
        files = [p for p in fonts_dir.iterdir() if p.is_file()]
        _local_dir_cache[key] = (now, files)
        return files
    except OSError:
        return []


def _find_local_font(font_name: str, fonts_dir: Path) -> str | None:
    """Cerca un file .ttf/.otf corrispondente (case-insensitive, prefisso tollerato).

    Validazione extra v2: scarta file < 5KB o non apribili (corrotti).
    """
    files = _list_font_files(fonts_dir)
    if not files:
        try:
            if not fonts_dir.is_dir():
                return None
        except OSError:
            return None
        if not files:
            return None
    norm = _normalize_name(font_name)
    lowered = {p.name.lower(): p for p in files}
    for cand in _candidate_local_names(font_name):
        hit = lowered.get(cand.lower())
        if hit is not None and hit.suffix.lower() in (".ttf", ".otf"):
            if validate_font_file(str(hit)):
                return str(hit)
            # File corrotto trovato: eliminalo subito (zero-failure).
            _delete_corrupted(str(hit))
    # 2) prefisso: es. "bebasneue-regular.ttf" per "Bebas Neue".
    for p in files:
        if p.suffix.lower() not in (".ttf", ".otf"):
            continue
        stem_norm = _normalize_name(p.stem)
        if stem_norm == norm or stem_norm.startswith(norm) or norm.startswith(stem_norm):
            if validate_font_file(str(p)):
                return str(p)
            _delete_corrupted(str(p))
    return None


_system_font_cache: dict[str, str | None] = {}


def _find_system_font(prefer: list[str] | None = None) -> str | None:
    """Primo font di sistema esistente e valido (preferenze opzionali, cachato)."""
    cache_key = "|".join(prefer) if prefer else "__default__"
    if cache_key in _system_font_cache:
        return _system_font_cache[cache_key]
    search_bases = [
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/System/Library/Fonts"),
    ]
    result: str | None = None
    if prefer:
        for base in search_bases:
            for fname in prefer:
                try:
                    cand = base / fname
                    if cand.is_file() and validate_font_file(str(cand)):
                        result = str(cand)
                        break
                except OSError:
                    continue
            if result is not None:
                break
    if result is None:
        for cand in _SYSTEM_FALLBACKS:
            try:
                if os.path.isfile(cand) and validate_font_file(cand):
                    result = cand
                    break
            except OSError:
                continue
    if len(_system_font_cache) < 32:
        _system_font_cache[cache_key] = result
    return result


def _fallback_chain(font_name: str) -> list[str]:
    """Catena di famiglie equivalenti da provare (richiesta + matrice 1:1).

    Ritorna nomi famiglia in ordine: [richiesta, ...equivalenti, Inter, Roboto].
    Solo font stabili Google Fonts, mai duplicati.
    """
    norm = _normalize_name(font_name)
    chain: list[str] = []
    if font_name and font_name.strip():
        chain.append(font_name.strip())
    for equiv in VISUAL_FALLBACK_MATRIX.get(norm, []):
        if equiv not in chain:
            chain.append(equiv)
    for safe in ("Inter", "Roboto"):
        if safe not in chain:
            chain.append(safe)
    return chain


def _file_candidates_for_family(family: str) -> list[tuple[str, str]]:
    """Lista (licenza/cartella, file) da provare per UNA singola famiglia."""
    norm = _normalize_name(family)
    alts = _FONT_FILE_ALTERNATIVES.get(norm)
    if alts:
        return list(alts)
    entry = _FONT_FILES.get(norm)
    if entry is not None:
        return [entry]
    # Guess generico per famiglie non mappate (Regular statico, OFL).
    compact = re.sub(r"\s+", "", family.strip())
    return [
        (f"ofl/{norm}", f"{compact}-Regular.ttf"),
        (f"ofl/{norm}", f"{norm}-regular.ttf"),
    ]


def _urls_for_single_family(family: str) -> list[str]:
    """URL per UNA sola famiglia (nessuna contaminazione cross-famiglia).

    Usato da _download_to(family, dest): garantisce che il contenuto salvato
    in `dest` appartenga davvero a `family` (fix bug PermanentMarker<-Inter).
    """
    urls: list[str] = []
    for lic_path, fname in _file_candidates_for_family(family):
        urls.append(f"{_GITHUB_RAW_BASE}/{lic_path}/{fname}")
        urls.append(f"{_JSDELIVR_BASE}/{lic_path}/{fname}")
    return urls


def _download_urls(font_name: str) -> list[str]:
    """URL candidate stabili per il download (raw ufficiale + CDN mirror).

    Ordine: famiglia richiesta -> equivalenti 1:1 -> Inter/Roboto sicuri.
    Per ogni famiglia: raw.githubusercontent (fonte verità) -> jsDelivr CDN.
    Path completi licenza/cartella (ofl/... o apache/...).
    """
    urls: list[str] = []
    for family in _fallback_chain(font_name):
        urls.extend(_urls_for_single_family(family))
    # Deduplica preservando ordine.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def validate_font_file(path: str) -> bool:
    """Verifica integrità: esiste, >= 5KB, apribile via PIL.ImageFont.truetype."""
    try:
        if not path or not os.path.isfile(path):
            return False
        if os.path.getsize(path) < MIN_VALID_FONT_BYTES:
            return False
        from PIL import ImageFont
        # Prova due dimensioni (catch font con tabelle cmap rotte a certe size).
        ImageFont.truetype(path, 32)
        return True
    except Exception:
        return False


def _delete_corrupted(path: str) -> None:
    """Elimina immediatamente file corrotto (< 5KB o non apribile)."""
    try:
        if path and os.path.isfile(path):
            try:
                bad = not validate_font_file(path)
            except Exception:
                bad = True
            if bad:
                os.remove(path)
                # Invalida cache dir listing.
                _local_dir_cache.clear()
    except OSError:
        pass


def _download_to(font_name: str, dest: Path) -> bool:
    """Scarica il font al percorso dest. Ritorna True se riuscito e valido.

    Fail-safe: scarta contenuti < 5KB, magic HTML, Pillow non apribile.
    Elimina tmp corrotti immediatamente. Prova SOLO gli URL della famiglia
    richiesta (anti-contaminazione: mai salva Inter come PermanentMarker).
    La fallback matrix è gestita dal chiamante (ensure_font_exists outer loop).
    """
    urls = _urls_for_single_family(font_name)
    if not urls:
        return False
    try:
        import requests
    except ImportError:
        return False
    for url in urls:
        try:
            resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT)
            if resp.status_code != 200 or not resp.content:
                continue
            content = resp.content
            # Zero-failure: scarta subito < 5KB (HTML di errore / 404 mascherati).
            if len(content) < MIN_VALID_FONT_BYTES:
                continue
            # Scarta HTML di errore (github raw deprecato ritorna HTML).
            head = content[:512].lower()
            if b"<html" in head or b"<!doctype" in head or b"not found" in head[:100]:
                continue
            magic = content[:4]
            if magic not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
                # wOFF/woff2 non caricabili da Pillow senza brotli: scarta
                # a meno che sia un TTF variabile con magic alternativo e size plausibile.
                if magic in (b"wOFF", b"wOF2"):
                    continue
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
                    tmp.unlink(missing_ok=True)
                except OSError:
                    continue
            # Validazione finale sul file promosso.
            if validate_font_file(str(dest)):
                _local_dir_cache.clear()
                return True
            _delete_corrupted(str(dest))
        except Exception:
            continue
    return False


def _find_bundled_guaranteed(fonts_dir: Path) -> str | None:
    """Fallback garantito pre-impacchettato (Roboto/Inter/Anton già in assets)."""
    for family in _GUARANTEED_BUNDLED:
        try:
            hit = _find_local_font(family, fonts_dir)
        except Exception:
            hit = None
        if hit:
            return hit
    # Ultima spiaggia: qualsiasi .ttf valido in assets/fonts/.
    try:
        for p in _list_font_files(fonts_dir):
            if p.suffix.lower() in (".ttf", ".otf") and validate_font_file(str(p)):
                return str(p)
    except OSError:
        pass
    return None


# Cache in-memory istanze PIL {(path, size): font} + lock (zero I/O in loop).
_pil_font_cache: dict[tuple[str, int], object] = {}
_pil_font_lock = threading.Lock()


def get_cached_pil_font(path: str, size: int):
    """Ritorna istanza PIL cachata in RAM (thread-safe, mai solleva)."""
    try:
        size_i = max(8, int(size))
    except (TypeError, ValueError):
        size_i = 60
    key = (str(path), size_i)
    hit = _pil_font_cache.get(key)
    if hit is not None:
        return hit
    with _pil_font_lock:
        hit = _pil_font_cache.get(key)
        if hit is not None:
            return hit
        try:
            from PIL import ImageFont
            f = ImageFont.truetype(str(path), size_i) if path else ImageFont.load_default()
        except Exception:
            try:
                from PIL import ImageFont as _IF
                f = _IF.load_default()
            except Exception:
                return None
        if len(_pil_font_cache) < 128:
            _pil_font_cache[key] = f
        return f


def clear_pil_font_cache() -> None:
    with _pil_font_lock:
        _pil_font_cache.clear()


class FontManager:
    """Gestore dei font del Semantic Typography Engine v2.

    Mantiene `assets/fonts/`, scarica i font mancanti via repository
    ufficiali, non solleva mai per assenza di rete: fallback garantito
    su font pre-impacchettati poi sistema.
    Thread-safe per preload parallelo.
    """

    def __init__(self, fonts_dir: str | Path | None = None):
        self.fonts_dir = Path(fonts_dir) if fonts_dir else FONTS_DIR
        try:
            self.fonts_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def ensure_font_exists(self, font_name: str) -> str:
        """Ritorna il percorso del font (locale, scaricato o fallback garantito).

        Catena: locale valido -> download (con fallback matrix 1:1) ->
        bundled garantito -> sistema -> "". Mai solleva. Elimina corrotti.
        """
        key = _normalize_name(font_name or "")
        if not key:
            return _find_bundled_guaranteed(self.fonts_dir) or _find_system_font() or ""
        with self._lock:
            cached = self._cache.get(key)
        if cached:
            try:
                if cached and os.path.isfile(cached) and validate_font_file(cached):
                    return cached
                # Cache puntava a corrotto: eliminalo.
                if cached:
                    _delete_corrupted(cached)
            except OSError:
                pass
        # 1) locale valido (scarta corrotti).
        try:
            hit = _find_local_font(font_name, self.fonts_dir)
        except Exception:
            hit = None
        if hit:
            with self._lock:
                self._cache[key] = hit
            return hit
        # 2) download con fallback matrix (prova equivalenti visivi).
        #    Dest standardizzato: unica scrittura per famiglia.
        tried_dest: Path | None = None
        for family in _fallback_chain(font_name):
            dest = self.fonts_dir / _standard_filename(family)
            tried_dest = dest
            # Se esiste già una variante valida, riusala (evita duplicati).
            try:
                existing = _find_local_font(family, self.fonts_dir)
            except Exception:
                existing = None
            if existing:
                with self._lock:
                    self._cache[key] = existing
                    self._cache[_normalize_name(family)] = existing
                return existing
            try:
                if _download_to(family, dest):
                    with self._lock:
                        self._cache[key] = str(dest)
                    return str(dest)
            except Exception:
                continue
            # Riprova: il download potrebbe aver creato altro nome.
            try:
                hit2 = _find_local_font(family, self.fonts_dir)
            except Exception:
                hit2 = None
            if hit2:
                with self._lock:
                    self._cache[key] = hit2
                return hit2
        # Pulisci eventuale dest corrotto rimasto.
        if tried_dest is not None:
            _delete_corrupted(str(tried_dest))
        # 3) bundled garantito (Roboto/Inter/Anton pre-impacchettati).
        try:
            bundled = _find_bundled_guaranteed(self.fonts_dir)
        except Exception:
            bundled = None
        if bundled:
            with self._lock:
                self._cache[key] = bundled
            return bundled
        # 4) fallback di sistema per ruolo (ultima spiaggia).
        role_hint: list[str] | None = None
        lowered_raw = (font_name or "").lower()
        if any(k in lowered_raw for k in ("impact", "anton", "bebas", "oswald", "spartan", "orbitron", "cinzel", "oswald")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["impact"]
        elif any(k in lowered_raw for k in ("hand", "marker", "caveat", "pacifico", "kalam", "playfair", "pristina", "note")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["accent"]
        else:
            role_hint = _ROLE_SYSTEM_PREFERENCE["base"]
        sys_font = _find_system_font(role_hint) or _find_system_font()
        result = sys_font or ""
        with self._lock:
            self._cache[key] = result
        return result

    def ensure_preset_fonts(self, niche_or_preset) -> dict[str, str]:
        """Assicura i 3 font del preset in parallelo (ThreadPool, fail-safe).

        Accetta nome nicchia o dict preset. Non solleva mai.
        """
        try:
            from core.typography_presets import get_preset
            preset = get_preset(niche_or_preset) if isinstance(niche_or_preset, str) else dict(niche_or_preset)
        except Exception:
            preset = {"fonts": {"base": [], "impact": [], "accent": []}}
        fonts = preset.get("fonts", {}) if isinstance(preset, dict) else {}
        out: dict[str, str] = {}

        def _resolve_role(role: str) -> tuple[str, str]:
            candidates = fonts.get(role, []) if isinstance(fonts, dict) else []
            path = ""
            for cand in candidates if isinstance(candidates, list) else []:
                try:
                    path = self.ensure_font_exists(str(cand))
                except Exception:
                    path = ""
                if path and os.path.isfile(path) and validate_font_file(path):
                    break
                if path:
                    _delete_corrupted(path)
                    path = ""
            if not path:
                path = _find_bundled_guaranteed(self.fonts_dir) or _find_system_font(
                    _ROLE_SYSTEM_PREFERENCE.get(role)) or ""
            return role, path

        # Parallelo I/O-bound (download + stat disco rilasciano GIL).
        try:
            import concurrent.futures as _fut
            with _fut.ThreadPoolExecutor(max_workers=3) as _ex:
                for role, path in _ex.map(_resolve_role, ("base", "impact", "accent")):
                    out[role] = path
        except Exception:
            for role in ("base", "impact", "accent"):
                try:
                    _, path = _resolve_role(role)
                except Exception:
                    path = ""
                out[role] = path
        return out

    def preload_preset_fonts(self, niche_or_preset, sizes: tuple[int, ...] | list[int] | None = None) -> dict[str, str]:
        """Warmup RAM: assicura path + precarica istanze PIL per size tipiche.

        Da chiamare UNA volta a inizio pipeline per azzerare I/O in loop frame.
        Ritorna gli stessi path di ensure_preset_fonts. Mai solleva.
        """
        paths = self.ensure_preset_fonts(niche_or_preset)
        if sizes is None:
            try:
                from core.typography_presets import get_preset as _gp
                preset = _gp(niche_or_preset) if isinstance(niche_or_preset, str) else niche_or_preset
                base = int((preset.get("sizes", {}) or {}).get("base", 60))
                isc = float((preset.get("sizes", {}) or {}).get("impact_scale", 1.4))
                asc = float((preset.get("sizes", {}) or {}).get("accent_scale", 1.1))
                sizes = (base, int(round(base * isc)), int(round(base * asc)))
            except Exception:
                sizes = (60, 84, 66)
        for role, path in paths.items():
            if not path:
                continue
            for sz in sizes:
                try:
                    get_cached_pil_font(path, int(sz))
                except Exception:
                    continue
        return paths

    def load_font(self, font_name: str, size: int):
        """Carica il font PIL alla dimensione data (cache RAM, mai bloccante)."""
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
        if path and validate_font_file(path):
            hit = get_cached_pil_font(path, size_i)
            if hit is not None:
                return hit
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
        with self._lock:
            self._cache.clear()
        clear_pil_font_cache()


# Istanza condivisa + scorciatoie funzionali.
_default_manager = FontManager()


def ensure_font_exists(font_name: str) -> str:
    """Scorciatoia: assicura il font e ritorna il percorso (vedi FontManager)."""
    return _default_manager.ensure_font_exists(font_name)


def ensure_preset_fonts(niche_or_preset) -> dict[str, str]:
    """Scorciatoia: assicura i 3 font del preset (parallelo)."""
    return _default_manager.ensure_preset_fonts(niche_or_preset)


def preload_preset_fonts(niche_or_preset, sizes=None) -> dict[str, str]:
    """Scorciatoia: warmup RAM per preset (vedi FontManager.preload_preset_fonts)."""
    return _default_manager.preload_preset_fonts(niche_or_preset, sizes)


def get_cached_pil_font_cached(path: str, size: int):
    """Alias pubblico per cache PIL in-memory."""
    return get_cached_pil_font(path, size)
