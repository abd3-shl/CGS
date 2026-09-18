"""
Caricamento script in bulk: un file .txt può contenere più script.

Convenzione bulk: UNA riga = UNO script. Righe vuote ignorate.
Ogni script viene processato separatamente (tema/nicchia/voci/video propri),
quindi script diversi possono avere niche diverse in modo coerente.

Funzioni pure (senza GUI) per parsing + naming output, testabili e riusabili.
"""

import os
import re
from pathlib import Path


def parse_scripts(text: str, bulk_mode: bool) -> list[str]:
    """Divide il testo in script.

    - bulk_mode=False: tutto il testo (strippato) è UN solo script
      (comportamento storico, preserva newline interni).
    - bulk_mode=True: UNA riga non vuota = UNO script (strip per riga,
      righe vuote saltate, ordine preservato).

    Ritorna lista (possibilmente vuota). Non solleva mai.
    """
    try:
        raw = text or ""
    except Exception:
        return []
    if not bulk_mode:
        stripped = raw.strip()
        return [stripped] if stripped else []
    scripts: list[str] = []
    try:
        for line in raw.splitlines():
            s = line.strip()
            # Salta righe vuote; tollera BOM/whitespace invisibili.
            if not s:
                continue
            # Salta righe fatte solo di separatori (---, ***, ///)?
            # No: potrebbero essere script intenzionali. Tienile.
            scripts.append(s)
    except Exception:
        return []
    return scripts


def load_scripts_from_file(path: str, bulk_mode: bool) -> list[str]:
    """Legge un .txt (utf-8, fallback latin-1) e lo parsifica in script.

    Raises:
        OSError: file illeggibile.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # Se utf-8 fallisce, l'eccezione esce (il chiamante mostra il dialog).
    # NB: errors non tollerati qui per non silenziare file binari.
    return parse_scripts(content, bulk_mode)


def slugify(text: str, max_words: int = 5, max_len: int = 32) -> str:
    """Slug filesystem-safe dalle prime parole (minuscole, _ al posto di spazi)."""
    try:
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text or "")
    except Exception:
        words = []
    if not words:
        return "script"
    slug = "_".join(w.lower() for w in words[:max_words])
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    return (slug[:max_len] or "script")


def suggest_output_filename(
    index: int,
    script_text: str,
    total: int,
    output_dir: str | None = None,
    prefix: str = "video",
    ext: str = ".mp4",
) -> str:
    """Nome output unico per lo script i-esimo (1-based): video_03_slug.mp4.

    Se output_dir è fornita ed esiste già un file con quel nome, aggiunge
    un suffisso _1, _2... (evita sovrascritture nel bulk). Non crea file.
    """
    try:
        i = max(1, int(index))
    except (TypeError, ValueError):
        i = 1
    try:
        n = max(1, int(total))
    except (TypeError, ValueError):
        n = 1
    width = max(2, len(str(n)))
    slug = slugify(script_text)
    base = f"{prefix}_{i:0{width}d}_{slug}{ext}"
    if not output_dir:
        return base
    try:
        candidate = Path(output_dir) / base
        if not candidate.exists():
            return base
        stem = f"{prefix}_{i:0{width}d}_{slug}"
        k = 1
        while True:
            alt = f"{stem}_{k}{ext}"
            if not (Path(output_dir) / alt).exists():
                return alt
            k += 1
            if k > 999:
                return alt
    except OSError:
        return base


def preview_of(script: str, max_len: int = 80) -> str:
    """Anteprima corta per i log (tronca con ...)."""
    s = (script or "").strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."
