"""
Palette tematica dinamica: analizza lo script con l'LLM Groq
(modello `GROQ_THEME_MODEL`, default `openai/gpt-oss-120b`, via Chat
Completions come in core/keywords.py) e genera una palette coerente
con il tema/tono dello script (sfondo, testo, colori keyword).

Tutti i colori viaggiano come hex string "#RRGGBB"; la conversione per
Pillow/ffmpeg avviene lato codice. Se la generazione fallisce, si usa
un default fisso (nero/bianco/palette storica): la pipeline non si blocca.
"""

import json
import re
from collections.abc import Callable

from groq import Groq

from config import (
    GROQ_API_KEYS,
    GROQ_THEME_MODEL,
    THEME_MIN_LUMINANCE_DIFF,
)
from core.keywords import _FALLBACK_PALETTE_HEX


class ThemeError(Exception):
    """Errore durante la generazione del tema (input non valido)."""
    pass


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_THEME: dict = {
    "background_color": "#000000",
    "text_color": "#FFFFFF",
    "keyword_colors": list(_FALLBACK_PALETTE_HEX),
}


def _default_theme() -> dict:
    """Copia profonda del default (la lista keyword non deve mai essere condivisa)."""
    return {
        "background_color": DEFAULT_THEME["background_color"],
        "text_color": DEFAULT_THEME["text_color"],
        "keyword_colors": list(DEFAULT_THEME["keyword_colors"]),
    }


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converte "#RRGGBB" in (R, G, B). Solleva ValueError se non valido."""
    if not HEX_RE.match(hex_color):
        raise ValueError(f"Colore hex non valido: {hex_color!r}")
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Converte "#RRGGBB" in (R, G, B, 255) per Pillow."""
    r, g, b = hex_to_rgb(hex_color)
    return (r, g, b, 255)


def _is_yellowish(hex_color: str) -> bool:
    """Vero per gialli/giallastri (vietati per le keyword: poco leggibili)."""
    r, g, b = hex_to_rgb(hex_color)
    return r > 200 and g > 150 and b < 120


def luminance(hex_color: str) -> float:
    """Luminanza percepita approssimata (WCAG-like), scala 0-255."""
    r, g, b = hex_to_rgb(hex_color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _validate_theme(raw: dict) -> dict:
    """Valida/corregge la palette dell'LLM (rete di sicurezza, vedi docstring modulo).

    - hex non validi: default sicuri (testo bianco, sfondo nero, keyword scartate);
    - contrasto testo/sfondo < soglia: forza bianco o nero (il più distante);
    - keyword a basso contrasto sullo sfondo o giallastre: scartate
      (il giallo su video è poco leggibile); se ne restano < 3,
      si integra dalla palette fallback storica.
    """
    bg = raw.get("background_color", "")
    text = raw.get("text_color", "")
    kws = raw.get("keyword_colors", [])

    if not isinstance(bg, str) or not HEX_RE.match(bg):
        bg = "#000000"
    if not isinstance(text, str) or not HEX_RE.match(text):
        text = "#FFFFFF"
    if not isinstance(kws, list):
        kws = []

    if abs(luminance(text) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
        text = "#FFFFFF" if abs(255 - luminance(bg)) >= abs(0 - luminance(bg)) else "#000000"

    clean_kws: list[str] = []
    for kw in kws:
        if not isinstance(kw, str) or not HEX_RE.match(kw):
            continue
        if _is_yellowish(kw):
            continue
        if abs(luminance(kw) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
            continue
        if kw not in clean_kws:
            clean_kws.append(kw)

    for fb in _FALLBACK_PALETTE_HEX:
        if len(clean_kws) >= 3:
            break
        if fb not in clean_kws and abs(luminance(fb) - luminance(bg)) >= THEME_MIN_LUMINANCE_DIFF:
            clean_kws.append(fb)

    return {"background_color": bg, "text_color": text, "keyword_colors": clean_kws}


def _parse_theme(content: str) -> dict | None:
    """Estrae il dict tema da una risposta JSON (robusto a fence markdown)."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def generate_theme(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> dict:
    """Analizza il tema dello script e genera una palette colori coerente.

    Usa `GROQ_THEME_MODEL` con rotazione delle chiavi in GROQ_API_KEYS.
    Non fallisce mai per errori API: in quel caso restituisce DEFAULT_THEME.

    Returns:
        {"background_color": "#RRGGBB", "text_color": "#RRGGBB",
         "keyword_colors": ["#RRGGBB", ...]}

    Raises:
        ThemeError: se lo script è vuoto.
    """
    if not script_text or not script_text.strip():
        raise ThemeError("Script vuoto: impossibile generare il tema.")

    if not GROQ_API_KEYS:
        return _default_theme()

    system = (
        "Sei un art director che sceglie palette colori per i sottotitoli di video brevi. "
        "Analizzi il tema dello script e rispondi SOLO con JSON valido, senza spiegazioni."
    )
    user = (
        "Genera una palette di colori in base al tema di questo script "
        "(es. horror: toni scuri e rossi; business: blu e grigi professionali; "
        "fitness: colori energici; motivazionale: toni caldi). "
        "NON usare sempre sfondo nero e testo bianco: varia la palette in base al tema. "
        "Regole: background_color e text_color devono avere contrasto alto "
        "(uno scuro e l'altro chiaro, mai simili); "
        "6-8 keyword_colors diversi tra loro, diversi dal text_color e leggibili "
        "sullo sfondo. Rispondi SOLO con questo JSON (colori hex #RRGGBB): "
        '{"background_color": "#RRGGBB", "text_color": "#RRGGBB", '
        '"keyword_colors": ["#RRGGBB", "#RRGGBB"]}\n\n'
        f"SCRIPT:\n{script_text}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model=GROQ_THEME_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            content = None
            if on_attempt is not None:
                on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
            continue
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: tema generato")
        break

    if content is None:
        return _default_theme()

    parsed = _parse_theme(content)
    if parsed is None:
        return _default_theme()
    return _validate_theme(parsed)
