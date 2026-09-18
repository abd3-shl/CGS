"""
Character-Driven Overlay + Dynamic Layout: selezione dinamica dei personaggi 2D.

- `plan_character_layout(chunks, script_text, on_attempt=None)`: usa l'LLM Groq
  (stesso failover multi-key di core/keywords.py) per assegnare a OGNI chunk
  posa (1-5), `layout_preset` (zona dello schermo, vedi core/layout_presets.py)
  e `transition_in`. Se l'LLM fallisce o il JSON non e' valido, usa un fallback
  deterministico. Ogni voce resta retrocompatibile con la v1 (position /
  transition / scale derivati dal preset).
- `resolve_chunk_layout(chunk)`: risolve i metadati effettivi di un chunk
  arricchito (preset -> geometria via layout_presets, oppure legacy v1).
- `load_and_process_character_image(pose_number, target_height)`: carica
  `assets/characters/{pose}.jpg` (.png/.jpeg accettati), rimuove lo sfondo
  nero opaco (RGB < (15,15,15) -> alpha 0) e ridimensiona mantenendo l'aspect
  ratio in base a `target_height`.
- `calculate_character_bbox(image_size, position_name, ...)`: posizionamento
  legacy v1 (mantenuto per compatibilita'; col preset si usa
  `layout_presets.layout_character_xy`).

Mappatura pose (vedi prompt LLM):
  1 (braccia incrociate): presentazioni, hook, affermazioni di fatto.
  2 (braccia aperte):     spiegazioni aperte, concetti generali, accoglienza.
  3 (pollice in su):      soluzioni, conclusioni, cose positive, CTA.
  4 (indicare):           punti chiave, dati, numeri, keyword importanti
                          (SEMPRE con layout_split_left/right: indica il testo).
  5 (mano al mento):      domande, dubbi, problemi, riflessioni.
"""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from config import (
    BASE_DIR,
    CHARACTERS_DIR,
    CHARACTER_POSE_COUNT,
    CHARACTER_SCALE_MAX,
    CHARACTER_SCALE_MIN,
    CHARACTER_VALID_POSITIONS,
    CHARACTER_VALID_TRANSITIONS,
    GROQ_API_KEYS,
    GROQ_LLM_MODEL,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from core.layout_presets import (
    VALID_LAYOUT_PRESETS,
    legacy_position,
    legacy_transition,
    normalize_preset,
    normalize_transition_in,
    preset_default_transition,
)

# Soglia sfondo nero opaco da rendere trasparente.
_BLACK_THRESHOLD = 15

# Cache immagini gia' processate: {(pose, target_height): PIL.Image RGBA}.
_image_cache: dict[tuple[int, int], Image.Image] = {}

# Estensioni accettate per gli asset (la spec cita .jpg, ma il repo puo'
# contenere .png con alpha gia' pronta: li supportiamo entrambi).
_ASSET_EXTENSIONS = (".jpg", ".jpeg", ".png")


class CharacterError(Exception):
    """Errore nella pianificazione/caricamento del personaggio."""
    pass


# ------------------------------------------------------------ Path resolution

def _candidate_asset_paths(pose_number: int) -> list[Path]:
    """Tutti i percorsi candidati per la posa, in ordine di preferenza."""
    names = [f"{pose_number}{ext}" for ext in _ASSET_EXTENSIONS]
    # Varianti maiuscole (es. 1.JPG) per filesystem case-sensitive.
    names += [f"{pose_number}{ext.upper()}" for ext in _ASSET_EXTENSIONS]
    candidates: list[Path] = []
    base_dirs = [Path(CHARACTERS_DIR)]
    # Fallback legacy: personaggi mai spostati da "Nuova cartella/characters".
    legacy = Path(BASE_DIR) / "Nuova cartella" / "characters"
    if legacy not in base_dirs:
        base_dirs.append(legacy)
    for d in base_dirs:
        for n in names:
            candidates.append(d / n)
    return candidates


def resolve_character_path(pose_number: int) -> Path | None:
    """Ritorna il percorso esistente per la posa, o None se assente."""
    for p in _candidate_asset_paths(pose_number):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


# ------------------------------------------------------------ BBox / posizionamento

def calculate_character_bbox(
    image_size: tuple[int, int],
    position_name: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int]:
    """Calcola l'angolo superiore-sinistro (x, y) del personaggio sul canvas.

    Args:
        image_size: (larghezza, altezza) dell'immagine personaggio gia' scalata.
        position_name: una di CHARACTER_VALID_POSITIONS (fallback: bottom_center).
        canvas_w/canvas_h: dimensioni canvas (default 1080x1920).

    Returns:
        (x, y) interi. x puo' essere negativo per side_left/side_right
        (personaggio parzialmente fuori campo, per scelta stilistica).
    """
    img_w, img_h = int(image_size[0]), int(image_size[1])
    pos = position_name if position_name in CHARACTER_VALID_POSITIONS else "bottom_center"

    if pos == "bottom_left":
        x = 40
        y = canvas_h - img_h
    elif pos == "bottom_right":
        x = canvas_w - img_w - 40
        y = canvas_h - img_h
    elif pos == "side_left":
        x = int(round(-img_w * 0.2))
        y = canvas_h - img_h - 100
    elif pos == "side_right":
        x = int(round(canvas_w - img_w * 0.8))
        y = canvas_h - img_h
    else:  # bottom_center (default)
        x = (canvas_w - img_w) // 2
        y = canvas_h - img_h

    # Il personaggio e' ancorato in basso: se piu' alto del canvas, taglia in alto.
    if y < 0 and img_h <= canvas_h:
        y = 0
    return (int(x), int(y))


def character_target_height(scale: float, canvas_h: int = VIDEO_HEIGHT) -> int:
    """Altezza target in px da una scala relativa (0.65-0.90 di 1920px)."""
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = CHARACTER_SCALE_MIN
    s = min(CHARACTER_SCALE_MAX, max(CHARACTER_SCALE_MIN, s))
    return max(1, int(round(canvas_h * s)))


# ------------------------------------------------------------ Trasparenza / asset

def _remove_black_background(img_rgba: Image.Image) -> Image.Image:
    """Rende trasparenti i pixel quasi-neri opachi (RGB < 15,15,15).

    Preserva l'alpha esistente: i pixel gia' trasparenti restano tali e i
    semi-trasparenti (bordi anti-aliased) non vengono toccati. Solo i pixel
    quasi-opachi (a >= 250) e quasi-neri diventano (0,0,0,0).
    Usa numpy se disponibile (veloce su ~1MP), altrimenti getdata puro.
    """
    if img_rgba.mode != "RGBA":
        img_rgba = img_rgba.convert("RGBA")
    try:
        import numpy as np  # type: ignore

        arr = np.array(img_rgba)  # (h, w, 4) uint8
        if arr.size == 0:
            return img_rgba
        opaque = arr[:, :, 3] >= 250
        black = (
            (arr[:, :, 0].astype(int) < _BLACK_THRESHOLD)
            & (arr[:, :, 1].astype(int) < _BLACK_THRESHOLD)
            & (arr[:, :, 2].astype(int) < _BLACK_THRESHOLD)
        )
        mask = opaque & black
        if bool(mask.any()):
            arr[mask] = (0, 0, 0, 0)
            return Image.fromarray(arr, mode="RGBA")
        return img_rgba
    except ImportError:
        pass
    # Fallback senza numpy: list-comprehension su getdata (~1s per 1MP, cachato).
    pixels = list(img_rgba.getdata())
    changed = False
    out = []
    for r, g, b, a in pixels:
        if a >= 250 and r < _BLACK_THRESHOLD and g < _BLACK_THRESHOLD and b < _BLACK_THRESHOLD:
            out.append((0, 0, 0, 0))
            changed = True
        else:
            out.append((r, g, b, a))
    if not changed:
        return img_rgba
    fresh = Image.new("RGBA", img_rgba.size, (0, 0, 0, 0))
    fresh.putdata(out)
    return fresh


def load_and_process_character_image(pose_number: int, target_height: int) -> Image.Image:
    """Carica, pulisce (sfondo nero -> trasparente) e ridimensiona la posa.

    Args:
        pose_number: intero 1..CHARACTER_POSE_COUNT (1.jpg ... 5.jpg).
        target_height: altezza desiderata in px (larghezza segue l'aspect ratio).

    Returns:
        Copia PIL.Image RGBA pronta per il paste con maschera.

    Raises:
        CharacterError: posa fuori range, asset mancante o immagine illeggibile.
    """
    try:
        pose = int(pose_number)
    except (TypeError, ValueError):
        raise CharacterError(f"Posa non valida: {pose_number!r}")
    if pose < 1 or pose > CHARACTER_POSE_COUNT:
        raise CharacterError(f"Posa {pose} fuori range 1..{CHARACTER_POSE_COUNT}")
    try:
        th = int(target_height)
    except (TypeError, ValueError):
        raise CharacterError(f"target_height non valido: {target_height!r}")
    if th <= 0:
        raise CharacterError(f"target_height deve essere > 0 (ricevuto {target_height!r})")

    cached = _image_cache.get((pose, th))
    if cached is not None:
        return cached.copy()

    path = resolve_character_path(pose)
    if path is None:
        searched = str(Path(CHARACTERS_DIR) / f"{pose}.jpg")
        raise CharacterError(
            f"Asset personaggio mancante per posa {pose}: cercato {searched} "
            f"(+ .png/.jpeg e fallback legacy). Verifica assets/characters/."
        )
    try:
        with Image.open(path) as opened:
            img = opened.convert("RGBA")
            img.load()
    except Exception as e:
        raise CharacterError(f"Impossibile leggere {path}: {e}")

    img = _remove_black_background(img)

    w, h = img.size
    if h <= 0 or w <= 0:
        raise CharacterError(f"Dimensioni immagine non valide per posa {pose}: {img.size}")
    if h != th:
        ratio = th / float(h)
        new_w = max(1, int(round(w * ratio)))
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:  # Pillow < 9.1
            resample = Image.LANCZOS
        img = img.resize((new_w, th), resample)

    _image_cache[(pose, th)] = img
    return img.copy()


def clear_character_cache() -> None:
    """Svuota la cache immagini (utile nei test)."""
    _image_cache.clear()


# ------------------------------------------------------------ Validazione piano

def _clamp_scale(value) -> float:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return 0.75
    return min(CHARACTER_SCALE_MAX, max(CHARACTER_SCALE_MIN, s))


def _preset_for_pose(pose: int, alternate: int = 0) -> str:
    """Preset deterministico per posa (fallback e normalizzazione).

    Posa 4 -> split alternati (indica il testo); posa 3 -> closeup d'enfasi;
    posa 5 -> figura intera con testo in alto; altre -> rotazione split/bottom.
    """
    if pose == 4:
        return "layout_split_right" if alternate % 2 == 0 else "layout_split_left"
    if pose == 3:
        return "layout_closeup_center"
    if pose == 5:
        return "layout_bottom_focus"
    cycle = ["layout_split_left", "layout_split_right", "layout_bottom_focus"]
    return cycle[alternate % len(cycle)]


def _normalize_entry(raw: dict, chunk_index: int, chunk_text: str = "") -> dict:
    """Normalizza una singola voce LLM in un piano valido (mai eccezioni).

    Schema nuovo: {"pose", "layout_preset", "transition_in"}; restano accettati
    i campi legacy v1 {"position", "transition"} (mappati sul preset piu'
    vicino). Ritorna sempre ENTRAMBI i vocabolari + scale (compatibilita'):
    {"chunk_index", "pose", "layout_preset", "transition_in",
     "position", "transition", "scale"}.
    """
    if not isinstance(raw, dict):
        raw = {}
    try:
        pose = int(raw.get("pose", 1))
    except (TypeError, ValueError):
        pose = 1
    pose = min(CHARACTER_POSE_COUNT, max(1, pose))

    # Preset: campo nuovo, altrimenti mappa dalla position legacy, altrimenti
    # euristica per posa (la posa 4 indica -> split anche se l'LLM sbaglia).
    preset_raw = raw.get("layout_preset", raw.get("layout"))
    if isinstance(preset_raw, str) and (
        preset_raw in VALID_LAYOUT_PRESETS
        or preset_raw in ("bottom_center", "bottom_left", "bottom_right", "side_left", "side_right")
    ):
        preset = normalize_preset(preset_raw, _preset_for_pose(pose, chunk_index))
    elif raw.get("position") is not None:
        preset = normalize_preset(raw.get("position"), _preset_for_pose(pose, chunk_index))
    else:
        preset = _preset_for_pose(pose, chunk_index)
    if pose == 4 and preset not in ("layout_split_left", "layout_split_right"):
        preset = _preset_for_pose(pose, chunk_index)

    transition_raw = raw.get("transition_in", raw.get("transition", None))
    if transition_raw is None:
        transition_raw = "slide_up" if chunk_index == 0 else preset_default_transition(preset)
    transition_in = normalize_transition_in(transition_raw, preset)

    scale = _clamp_scale(raw.get("scale", 0.75))
    return {
        "chunk_index": int(chunk_index),
        "pose": pose,
        "layout_preset": preset,
        "transition_in": transition_in,
        # Derivati legacy v1 (renderer/video vecchio stile + logging).
        "position": legacy_position(preset),
        "transition": legacy_transition(transition_in),
        "scale": scale,
    }


def _fallback_plan(chunks: list[dict]) -> list[dict]:
    """Piano deterministico senza LLM (sistema a zone + campi legacy).

    - Primo chunk: posa 1, layout_bottom_focus, slide_up, scala 0.75.
    - Successivi: "?" -> posa 5, "!" -> posa 3, altrimenti ciclo 1 -> 2 -> 4.
      Il preset segue la posa (posa 4 -> split alternati per indicare il testo).
    """
    cycle_poses = [1, 2, 4]
    plan: list[dict] = []
    cycle_i = 0
    split_flip = 0
    for i, chunk in enumerate(chunks):
        text = str((chunk or {}).get("text", ""))
        if i == 0:
            pose, preset, transition_in = 1, "layout_bottom_focus", "slide_up"
        else:
            if "?" in text:
                pose = 5
            elif "!" in text:
                pose = 3
            else:
                pose = cycle_poses[cycle_i % len(cycle_poses)]
                cycle_i += 1
            if pose == 4:
                preset = "layout_split_right" if split_flip % 2 == 0 else "layout_split_left"
                split_flip += 1
            else:
                preset = _preset_for_pose(pose, i)
            transition_in = preset_default_transition(preset)
            if i % 3 == 2 and transition_in.startswith("slide"):
                transition_in = "fade"  # ogni tanto un cambio morbido
        plan.append({
            "chunk_index": i,
            "pose": pose,
            "layout_preset": preset,
            "transition_in": transition_in,
            "position": legacy_position(preset),
            "transition": legacy_transition(transition_in),
            "scale": 0.75,
        })
    return plan


def _parse_plan(content: str, n: int) -> list[dict] | None:
    """Estrae il piano dalla risposta LLM. None se non valido.

    Accetta sia un array JSON bare `[...]` sia `{"layout": [...]}` (o
    `{"plan": [...]}` / `{"chunks": [...]}`), robusto a fence markdown.
    """
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Ultimo tentativo: il primo array JSON nel testo.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        for key in ("layout", "plan", "chunks", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return None
    if not isinstance(data, list) or not data:
        return None
    # Indicizza per chunk_index quando presente, altrimenti per ordine.
    by_index: dict[int, dict] = {}
    unordered: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        ci = entry.get("chunk_index", entry.get("index"))
        try:
            ci_int = int(ci)
        except (TypeError, ValueError):
            unordered.append(entry)
            continue
        if 0 <= ci_int < n and ci_int not in by_index:
            by_index[ci_int] = entry
        else:
            unordered.append(entry)
    # Riempie i buchi con le voci senza indice (in ordine).
    result: list[dict] = []
    it = iter(unordered)
    for i in range(n):
        if i in by_index:
            result.append(by_index[i])
        else:
            try:
                result.append(next(it))
            except StopIteration:
                return None  # voci insufficienti -> fallback completo
    # Voci extra ignorate; valida tipi base.
    for entry in result:
        if not isinstance(entry, dict):
            return None
    return result


# ------------------------------------------------------------ Pianificazione LLM

_POSE_RULES = (
    "Posa 1 (braccia incrociate): presentazioni, hook iniziali, affermazioni di fatto.\n"
    "Posa 2 (braccia aperte): spiegazioni aperte, concetti generali, accoglienza.\n"
    "Posa 3 (pollice in su): soluzioni, conclusioni, cose positive, call-to-action.\n"
    "Posa 4 (indicare): punti chiave, dati, numeri, keyword importanti.\n"
    "Posa 5 (mano al mento): domande, dubbi, problemi, riflessioni."
)

_LAYOUT_RULES = (
    "Layout disponibili (personaggio e testo NON devono mai sovrapporsi):\n"
    "- layout_split_left: personaggio grande a SINISTRA (h=1300px, spalla fuori campo), testo a DESTRA.\n"
    "- layout_split_right: personaggio grande a DESTRA (h=1300px), testo a SINISTRA.\n"
    "- layout_bottom_focus: figura intera in basso al centro (h=1000px), testo in ALTO (y 200-800).\n"
    "- layout_closeup_center: primo piano centrale massiccio (h=1600px), testo in BASSO su sfondo semi-trasparente.\n"
    "REGOLA OBBLIGATORIA: con la Posa 4 (indicare) usa SEMPRE layout_split_left o layout_split_right, "
    "scegliendo il lato in modo che il personaggio indichi verso il testo.\n"
    "Transizioni (transition_in): 'slide_from_left' / 'slide_from_right' per gli split laterali, "
    "'slide_up' per layout_bottom_focus, 'fade' per cambi morbidi o closeup, 'none' se preset e posa "
    "restano identici al chunk precedente."
)


def plan_character_layout(
    chunks: list[dict],
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Assegna a ogni chunk posa/layout_preset/transition_in del personaggio.

    Usa l'LLM Groq con rotazione delle chiavi (come core/keywords.py).
    Non solleva mai per errori API/validazione: in quel caso restituisce il
    fallback deterministico (vedi `_fallback_plan`).

    Args:
        chunks: lista chunk {"text", "start", "end", ...} (dall'emphasis grouping).
        script_text: script originale (contesto per il tono del discorso).
        on_attempt: callback (idx, totale, ok, dettaglio) per il logging GUI.

    Returns:
        Lista lunga quanto `chunks`, un dict per chunk:
        {"chunk_index": int, "pose": 1-5, "layout_preset": str,
         "transition_in": str, "position": str, "transition": str,
         "scale": 0.65-0.90} (gli ultimi tre sono derivati legacy v1).
    """
    if not chunks:
        return []

    if not GROQ_API_KEYS:
        if on_attempt is not None:
            try:
                on_attempt(0, 0, False, "nessuna GROQ_API_KEY: uso piano character deterministico")
            except Exception:
                pass
        return _fallback_plan(chunks)

    n = len(chunks)
    # Contesto compatto: indice + testo per chunk (i chunk sono da 2-3 parole,
    # quindi il prompt resta leggero anche con decine di chunk).
    lines = []
    for i, ch in enumerate(chunks):
        text = str((ch or {}).get("text", "")).strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "..."
        lines.append(f"{i}: {text}")
    chunk_block = "\n".join(lines)
    script_snippet = (script_text or "").strip().replace("\n", " ")
    if len(script_snippet) > 1500:
        script_snippet = script_snippet[:1500] + "..."

    system = (
        "Sei un regista che assegna un personaggio 2D ai sottotitoli di un video breve. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Analizza il tono di ogni chunk e assegna personaggio/layout/transizione.\n\n"
        "REGOLE POSE:\n" + _POSE_RULES + "\n\n"
        "REGOLE LAYOUT E REGIA:\n" + _LAYOUT_RULES + "\n"
        "- Cambia posa/layout SOLO quando il concetto o il tono cambia davvero: "
        "se il discorso e' continuo, mantieni stessa posa e stesso layout dei chunk "
        "precedenti (non cambiare ad ogni chunk di 2 parole).\n"
        "- Alterna i lati degli split (sinistra/destra) per dare ritmo visivo.\n\n"
        f"LAYOUT VALIDI: {', '.join(VALID_LAYOUT_PRESETS)}\n"
        "TRANSIZIONI VALIDE: slide_from_left, slide_from_right, slide_up, fade, none\n\n"
        f"SCRIPT (contesto):\n{script_snippet}\n\n"
        f"CHUNK ({n} totali, 'indice: testo'):\n{chunk_block}\n\n"
        "Rispondi SOLO con un array JSON con ESATTAMENTE "
        f"{n} oggetti in ordine di chunk_index, cosi': "
        '[{"chunk_index": 0, "pose": 4, '
        '"layout_preset": "layout_split_left", "transition_in": "slide_from_left"}]'
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            if on_attempt is not None:
                try:
                    on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
                except Exception:
                    pass
            content = None
            continue
        if on_attempt is not None:
            try:
                on_attempt(index, total, True, f"chiave {index}/{total}: layout character ricevuto")
            except Exception:
                pass
        break

    if content is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "LLM character fallito: uso piano deterministico")
            except Exception:
                pass
        return _fallback_plan(chunks)

    raw_entries = _parse_plan(content, n)
    if raw_entries is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "JSON character non valido: uso piano deterministico")
            except Exception:
                pass
        return _fallback_plan(chunks)

    plan = [
        _normalize_entry(entry, i, str((chunks[i] or {}).get("text", "")))
        for i, entry in enumerate(raw_entries)
    ]
    if on_attempt is not None:
        try:
            poses = ", ".join(
                f"chunk {p['chunk_index']}: posa {p['pose']} ({p['layout_preset']}, {p['transition_in']})"
                for p in plan[:8]
            )
            more = f" ... (+{len(plan) - 8})" if len(plan) > 8 else ""
            on_attempt(total, total, True, f"character plan: {poses}{more}")
        except Exception:
            pass
    return plan


def resolve_chunk_layout(chunk: dict) -> dict | None:
    """Risolve i metadati effettivi del personaggio per un chunk arricchito.

    Punto unico di verita' tra text engine e character engine: entrambi
    chiamano questa funzione, quindi non possono mai divergere (niente overlap).

    Returns:
        None se il chunk non ha personaggio, altrimenti
        {"pose": int, "use_preset": bool, "layout_preset": str,
         "transition_in": str, "position": str, "transition": str, "scale": float}.
        Con preset valido: il render usa altezza/XY/safe-area del preset.
        Senza preset (chunk legacy v1): altezza da scale, XY da position bbox.
    """
    if not isinstance(chunk, dict) or chunk.get("pose") is None:
        return None
    try:
        pose = int(chunk.get("pose"))
    except (TypeError, ValueError):
        return None
    if pose < 1 or pose > CHARACTER_POSE_COUNT:
        return None
    raw_preset = chunk.get("layout_preset", chunk.get("layout"))
    use_preset = isinstance(raw_preset, str) and raw_preset in VALID_LAYOUT_PRESETS
    if use_preset:
        preset = raw_preset
    else:
        # Chunk legacy v1 (solo position): mappa sul preset vicino ma il render
        # resta in modalita' legacy per non alterare il look esistente.
        preset = normalize_preset(chunk.get("position", "bottom_center"), "layout_bottom_focus")
    transition_in = normalize_transition_in(
        chunk.get("transition_in", chunk.get("transition")), preset
    )
    position = chunk.get("position") or legacy_position(preset)
    if position not in CHARACTER_VALID_POSITIONS:
        position = legacy_position(preset)
    try:
        scale = float(chunk.get("scale", 0.75))
    except (TypeError, ValueError):
        scale = 0.75
    scale = min(CHARACTER_SCALE_MAX, max(CHARACTER_SCALE_MIN, scale))
    return {
        "pose": pose,
        "use_preset": bool(use_preset),
        "layout_preset": preset,
        "transition_in": transition_in,
        "position": position,
        "transition": legacy_transition(transition_in),
        "scale": scale,
    }


def enrich_chunks_with_characters(
    chunks: list[dict],
    plan: list[dict] | None,
) -> list[dict]:
    """Arricchisce i chunk con i metadati character (preset + legacy v1).

    Copia pose/layout_preset/transition_in (+ position/transition/scale derivati).
    Se `plan` e' None/vuoto o la lunghezza non coincide, i chunk restano
    invariati (pipeline senza personaggio). Non solleva mai.
    """
    if not plan or len(plan) != len(chunks):
        return chunks
    enriched: list[dict] = []
    for i, chunk in enumerate(chunks):
        try:
            entry = plan[i] if isinstance(plan[i], dict) else {}
            norm = _normalize_entry(entry, i, str((chunk or {}).get("text", "")))
            enriched.append({**chunk, **norm})
        except (TypeError, ValueError, AttributeError):
            enriched.append({**chunk})
    return enriched
