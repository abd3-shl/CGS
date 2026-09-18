"""
Character-Driven Overlay + Dynamic Layout: selezione dinamica dei personaggi 2D.

- `plan_character_layout(chunks, script_text, on_attempt=None)`: usa l'LLM Groq
  (stesso failover multi-key di core/keywords.py) per assegnare a OGNI chunk
  posa (1-5), `layout` (zona dello schermo, vedi core/layout_presets.py) e
  `punch_in` (bool, jump-cut di ingrandimento per le frasi chiave, max 2 per
  video). Se l'LLM fallisce o il JSON non e' valido, usa un fallback
  deterministico. Ogni voce resta retrocompatibile (layout_preset alias,
  transition_in derivata, position/transition/scale legacy).
- `resolve_chunk_layout(chunk)`: risolve i metadati effettivi di un chunk
  arricchito (preset -> geometria via layout_presets, oppure legacy v1).
- `load_character_original(pose_number)`: asset RGBA originale pulito e cachato
  (base per `calculate_character_transform` in core/renderer.py).
- `load_and_process_character_image(pose_number, target_height)`: legacy v1
  (scala su altezza), mantenuto per compatibilita'.
- `calculate_character_bbox(image_size, position_name, ...)`: posizionamento
  legacy v1 (mantenuto per compatibilita'; col preset si usa
  `core/renderer.calculate_character_transform`, width-based).

Mappatura pose (vedi prompt LLM):
  1 (braccia incrociate): presentazioni, hook, affermazioni di fatto.
  2 (braccia aperte):     spiegazioni aperte, concetti generali, accoglienza.
  3 (pollice in su):      soluzioni, conclusioni, cose positive, CTA.
  4 (indicare):           punti chiave, dati, numeri, keyword importanti
                          (SEMPRE con layout_split_left/right: indica il testo).
  5 (mano al mento):      domande, dubbi, problemi, riflessioni (prediligi split).
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
    MAX_PUNCH_INS_PER_VIDEO,
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


# Cache asset originali puliti: {pose: PIL.Image RGBA a dimensione nativa}.
_original_cache: dict[int, Image.Image] = {}


def _validate_pose(pose_number) -> int:
    """Valida la posa (solleva CharacterError se fuori range)."""
    try:
        pose = int(pose_number)
    except (TypeError, ValueError):
        raise CharacterError(f"Posa non valida: {pose_number!r}")
    if pose < 1 or pose > CHARACTER_POSE_COUNT:
        raise CharacterError(f"Posa {pose} fuori range 1..{CHARACTER_POSE_COUNT}")
    return pose


def load_character_original(pose_number: int) -> Image.Image:
    """Carica l'asset RGBA originale (pulito, dimensione nativa), cachato.

    Base per `core/renderer.calculate_character_transform` (scala width-based
    del sistema a zone). Ritorna una copia; l'originale resta in cache.

    Raises:
        CharacterError: posa fuori range, asset mancante o illeggibile.
    """
    pose = _validate_pose(pose_number)
    cached = _original_cache.get(pose)
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
    if img.size[0] <= 0 or img.size[1] <= 0:
        raise CharacterError(f"Dimensioni immagine non valide per posa {pose}: {img.size}")
    img = _remove_black_background(img)
    _original_cache[pose] = img
    return img.copy()


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
    pose = _validate_pose(pose_number)
    try:
        th = int(target_height)
    except (TypeError, ValueError):
        raise CharacterError(f"target_height non valido: {target_height!r}")
    if th <= 0:
        raise CharacterError(f"target_height deve essere > 0 (ricevuto {target_height!r})")

    cached = _image_cache.get((pose, th))
    if cached is not None:
        return cached.copy()

    img = load_character_original(pose)

    w, h = img.size
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
    """Svuota le cache immagini (originali + ridimensionate, utile nei test)."""
    _image_cache.clear()
    _original_cache.clear()


# ------------------------------------------------------------ Validazione piano

def _clamp_scale(value) -> float:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return 0.75
    return min(CHARACTER_SCALE_MAX, max(CHARACTER_SCALE_MIN, s))


def _preset_for_pose(pose: int, alternate: int = 0) -> str:
    """Preset deterministico per posa (fallback e normalizzazione).

    Posa 4 -> split alternati (indica il testo); posa 5 -> split laterali;
    posa 3 -> mezza figura centrale; altre -> rotazione standard/split.
    """
    if pose == 4:
        return "layout_split_right" if alternate % 2 == 0 else "layout_split_left"
    if pose == 5:
        return "layout_split_left" if alternate % 2 == 0 else "layout_split_right"
    if pose == 3:
        return "layout_center_standard"
    cycle = ["layout_center_standard", "layout_split_left", "layout_split_right"]
    return cycle[alternate % len(cycle)]


def _parse_punch_in(raw: dict) -> bool:
    """Estrae il flag punch-in (accetta `punch_in` o alias `punch`, truthy)."""
    if not isinstance(raw, dict):
        return False
    val = raw.get("punch_in", raw.get("punch", False))
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "si", "y")
    return bool(val)


def _cap_punch_ins(plan: list[dict], max_n: int = MAX_PUNCH_INS_PER_VIDEO) -> list[dict]:
    """Limita i punch-in a max_n per video (stacco enfasi raro e prezioso).

    Tiene gli ULTIMI max_n (rivelazioni/CTA finali) e spegne gli altri.
    Non solleva mai; ritorna lo stesso piano (modificato in place).
    """
    try:
        idx = [i for i, p in enumerate(plan) if isinstance(p, dict) and p.get("punch_in")]
    except Exception:
        return plan
    if len(idx) <= max_n:
        return plan
    for i in idx[:-max_n] if max_n > 0 else idx:
        try:
            plan[i]["punch_in"] = False
        except Exception:
            pass
    return plan


def _chunk_role(chunk: dict | None) -> str | None:
    """Ruolo narrativo del chunk ('hook'/'body'/'cta') o None se assente."""
    try:
        role = (chunk or {}).get("narrative_role")
        return role if role in ("hook", "body", "cta") else None
    except Exception:
        return None


def _apply_narrative_locks(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Blocchi deterministici per atto (stabilita' garantita anche se l'LLM varia).

    - HOOK: primo chunk posa 1 + center_standard + slide_up; punch sul climax
      (ultimo chunk hook). Transizioni pulite in ingresso.
    - CORPO: dentro ogni beat (stesso narrative_beat) UNA sola identita'
      (posa+layout del primo chunk del beat); i cambi avvengono solo ai
      confini di beat con slide piena (niente dissolvenze a meta' pensiero).
    - CTA: TUTTI i chunk su un'unica identita' (forte: posa 3; debole: posa 2),
      center_standard, punch=False, scala 0.75, ingresso fade sul primo.
      Il personaggio resta pixel-identico fino alla dissolvenza finale.
    Non solleva mai; senza ruoli sui chunk restituisce il piano invariato.
    """
    try:
        if not plan or not chunks or len(plan) != len(chunks):
            return plan
        if not any(_chunk_role(c) for c in chunks):
            return plan
    except Exception:
        return plan
    try:
        hook_idx = [i for i, c in enumerate(chunks) if _chunk_role(c) == "hook"]
        cta_idx = [i for i, c in enumerate(chunks) if _chunk_role(c) == "cta"]
        # --- HOOK ---
        if hook_idx:
            first = hook_idx[0]
            try:
                plan[first]["pose"] = 1
                plan[first]["layout"] = "layout_center_standard"
                plan[first]["layout_preset"] = "layout_center_standard"
                plan[first]["transition_in"] = "slide_up"
                plan[first]["position"] = legacy_position("layout_center_standard")
                plan[first]["transition"] = legacy_transition("slide_up")
            except Exception:
                pass
            if len(hook_idx) > 1:
                try:
                    plan[hook_idx[0]]["punch_in"] = False
                except Exception:
                    pass
            try:
                plan[hook_idx[-1]]["punch_in"] = True  # climax hook: stacco
            except Exception:
                pass
        # --- CORPO: lock per beat ---
        beats: dict[int, list[int]] = {}
        for i, c in enumerate(chunks):
            if _chunk_role(c) != "body":
                continue
            try:
                b = int((c or {}).get("narrative_beat", -1))
            except Exception:
                b = -1
            beats.setdefault(b, []).append(i)
        for beat in beats.values():
            if len(beat) < 2:
                continue
            try:
                ref = plan[beat[0]]
                ref_pose, ref_layout = ref.get("pose", 2), ref.get("layout", "layout_center_standard")
                ref_punch = bool(ref.get("punch_in", False))
            except Exception:
                continue
            for j in beat[1:]:
                try:
                    plan[j]["pose"] = ref_pose
                    plan[j]["layout"] = ref_layout
                    plan[j]["layout_preset"] = ref_layout
                    plan[j]["position"] = legacy_position(ref_layout)
                    plan[j]["punch_in"] = ref_punch
                    plan[j]["scale"] = ref.get("scale", 0.75)
                except Exception:
                    continue
        # --- CTA: lock totale ---
        # CTA forte (segnali d'azione) -> posa 3 celebrativa; outro debole
        # (finale senza segnali) -> posa 2 aperta, neutra su qualsiasi tono.
        if cta_idx:
            try:
                strong = str((chunks[cta_idx[0]] or {}).get("cta_strength", "strong")) == "strong"
            except Exception:
                strong = True
            pose = 3 if strong else 2
            for k, j in enumerate(cta_idx):
                try:
                    plan[j]["pose"] = pose
                    plan[j]["layout"] = "layout_center_standard"
                    plan[j]["layout_preset"] = "layout_center_standard"
                    plan[j]["punch_in"] = False
                    plan[j]["scale"] = 0.75
                    plan[j]["position"] = legacy_position("layout_center_standard")
                    plan[j]["transition_in"] = "fade" if k == 0 else plan[j].get("transition_in", "fade")
                    plan[j]["transition"] = legacy_transition(plan[j]["transition_in"])
                except Exception:
                    continue
    except Exception:
        pass
    return plan


def _cap_punch_ins_narrative(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Cap punch-in per atto: hook max 1 (climax), corpo max 1 (ultimo), CTA 0.

    Lo stacco resta raro e prezioso, e il finale non ha mai salti di scala
    (causa n.1 del flicker CTA). Senza ruoli, delega al cap globale storico.
    """
    try:
        if not any(_chunk_role(c) for c in (chunks or [])):
            return _cap_punch_ins(plan)
    except Exception:
        return _cap_punch_ins(plan)
    try:
        hook_idx = [i for i, c in enumerate(chunks) if _chunk_role(c) == "hook"]
        body_idx = [i for i, c in enumerate(chunks) if _chunk_role(c) == "body"]
        cta_idx = [i for i, c in enumerate(chunks) if _chunk_role(c) == "cta"]
        for j in cta_idx:
            try:
                plan[j]["punch_in"] = False
            except Exception:
                pass
        if hook_idx:
            for j in hook_idx[:-1]:
                try:
                    plan[j]["punch_in"] = False
                except Exception:
                    pass
        body_punch = [j for j in body_idx
                      if isinstance(plan[j], dict) and plan[j].get("punch_in")]
        for j in body_punch[:-1]:
            try:
                plan[j]["punch_in"] = False
            except Exception:
                pass
    except Exception:
        pass
    return plan


def _finalize_character_plan(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Lock narrativi + cap per atto (o cap globale legacy senza ruoli)."""
    try:
        if any(_chunk_role(c) for c in (chunks or [])):
            return _cap_punch_ins_narrative(_apply_narrative_locks(plan, chunks), chunks)
    except Exception:
        pass
    return _cap_punch_ins(plan)


def _normalize_entry(raw: dict, chunk_index: int, chunk_text: str = "") -> dict:
    """Normalizza una singola voce LLM in un piano valido (mai eccezioni).

    Schema: {"pose", "layout", "punch_in"}; restano accettati "layout_preset"
    (alias), i campi legacy v1 {"position", "transition"} (mappati sul preset
    piu' vicino) e "transition_in" esplicito. Ritorna SEMPRE il vocabolario
    completo (compatibilita'):
    {"chunk_index", "pose", "layout", "layout_preset", "punch_in",
     "transition_in", "position", "transition", "scale"}.
    """
    if not isinstance(raw, dict):
        raw = {}
    try:
        pose = int(raw.get("pose", 1))
    except (TypeError, ValueError):
        pose = 1
    pose = min(CHARACTER_POSE_COUNT, max(1, pose))

    # Layout: campo nuovo "layout", alias "layout_preset", altrimenti mappa
    # dalla position legacy, altrimenti euristica per posa (la posa 4 indica
    # -> split anche se l'LLM sbaglia; la posa 5 predilige i laterali).
    layout_raw = raw.get("layout", raw.get("layout_preset"))
    if isinstance(layout_raw, str) and (
        layout_raw in VALID_LAYOUT_PRESETS
        or layout_raw in ("bottom_center", "bottom_left", "bottom_right", "side_left", "side_right")
        or layout_raw in ("layout_bottom_focus", "layout_closeup_center")
    ):
        preset = normalize_preset(layout_raw, _preset_for_pose(pose, chunk_index))
    elif raw.get("position") is not None:
        preset = normalize_preset(raw.get("position"), _preset_for_pose(pose, chunk_index))
    else:
        preset = _preset_for_pose(pose, chunk_index)
    if pose == 4 and preset not in ("layout_split_left", "layout_split_right"):
        preset = _preset_for_pose(pose, chunk_index)
    if pose == 5 and preset not in ("layout_split_left", "layout_split_right"):
        preset = _preset_for_pose(pose, chunk_index)

    transition_raw = raw.get("transition_in", raw.get("transition", None))
    if transition_raw is None:
        transition_raw = "slide_up" if chunk_index == 0 else preset_default_transition(preset)
    transition_in = normalize_transition_in(transition_raw, preset)

    scale = _clamp_scale(raw.get("scale", 0.75))
    return {
        "chunk_index": int(chunk_index),
        "pose": pose,
        "layout": preset,
        "layout_preset": preset,  # alias (compatibilita' sistema a zone v1)
        "punch_in": _parse_punch_in(raw),
        "transition_in": transition_in,
        # Derivati legacy v1 (renderer/video vecchio stile + logging).
        "position": legacy_position(preset),
        "transition": legacy_transition(transition_in),
        "scale": scale,
    }


def _fallback_plan(chunks: list[dict]) -> list[dict]:
    """Piano deterministico senza LLM (sistema a zone + punch-in + legacy).

    - Primo chunk: posa 1, layout_center_standard, slide_up, scala 0.75.
    - Successivi: "?" -> posa 5 (split), "!" -> posa 3 + punch_in (enfasi),
      altrimenti ciclo 1 -> 2 -> 4 (posa 4 -> split alternati per indicare).
    - Con ruoli narrativi: niente punch in CTA (finale stabile) e lock
      per atto applicati in finalize (vedi _apply_narrative_locks).
    - I punch_in sono limitati per atto (vedi _cap_punch_ins_narrative).
    """
    cycle_poses = [1, 2, 4]
    plan: list[dict] = []
    cycle_i = 0
    split_flip = 0
    for i, chunk in enumerate(chunks):
        text = str((chunk or {}).get("text", ""))
        punch_in = False
        is_cta = _chunk_role(chunk) == "cta"
        if i == 0:
            pose, preset, transition_in = 1, "layout_center_standard", "slide_up"
        else:
            if "?" in text:
                pose = 5
            elif "!" in text and not is_cta:
                pose = 3
                punch_in = True  # enfasi: jump-cut (mai in CTA: stabile)
            elif "!" in text:
                pose = 3  # CTA/outro: posa giusta, senza stacco
            else:
                pose = cycle_poses[cycle_i % len(cycle_poses)]
                cycle_i += 1
            if pose == 4:
                preset = "layout_split_right" if split_flip % 2 == 0 else "layout_split_left"
                split_flip += 1
            elif pose == 5:
                preset = "layout_split_left" if split_flip % 2 == 0 else "layout_split_right"
                split_flip += 1
            else:
                preset = _preset_for_pose(pose, i)
            transition_in = preset_default_transition(preset)
            if i % 3 == 2 and transition_in.startswith("slide"):
                transition_in = "fade"  # ogni tanto un cambio morbido
        plan.append({
            "chunk_index": i,
            "pose": pose,
            "layout": preset,
            "layout_preset": preset,
            "punch_in": punch_in,
            "transition_in": transition_in,
            "position": legacy_position(preset),
            "transition": legacy_transition(transition_in),
            "scale": 0.75,
        })
    return _finalize_character_plan(plan, chunks)


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
    "Layout disponibili (niente figura intera: mezzo busto/mezza figura, gambe fuori campo; "
    "personaggio e testo NON devono mai sovrapporsi):\n"
    "- layout_center_standard: mezza figura centrata in basso (125% larghezza), testo in ALTO (y 150-900).\n"
    "- layout_center_punch_in: PRIMO PIANO busto/testa (170% larghezza), testo nel terzo superiore con sfondo ad alto contrasto.\n"
    "- layout_split_left: personaggio a SINISTRA (130%, spalla fuori campo), testo a DESTRA (x 640-1000).\n"
    "- layout_split_right: personaggio a DESTRA (130%), testo a SINISTRA (x 80-420).\n"
    "REGOLA OBBLIGATORIA: con la Posa 4 (indicare) usa SEMPRE layout_split_left o layout_split_right, "
    "scegliendo il lato in modo che il personaggio indichi verso il testo.\n"
    "Con la Posa 5 (pensare) prediligi i layout laterali (split_left/split_right).\n"
    "PUNCH-IN (jump-cut con ingrandimento improvviso, stacco di camera televisivo): metti punch_in=true "
    "SOLO per frasi chiave, rivelazioni o call to action finali, MAX 1-2 volte in TUTTO il video."
)


def plan_character_layout(
    chunks: list[dict],
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Assegna a ogni chunk posa/layout/punch_in del personaggio.

    Usa l'LLM Groq con rotazione delle chiavi (come core/keywords.py).
    Non solleva mai per errori API/validazione: in quel caso restituisce il
    fallback deterministico (vedi `_fallback_plan`).

    Args:
        chunks: lista chunk {"text", "start", "end", ...} (dall'emphasis grouping).
        script_text: script originale (contesto per il tono del discorso).
        on_attempt: callback (idx, totale, ok, dettaglio) per il logging GUI.

    Returns:
        Lista lunga quanto `chunks`, un dict per chunk:
        {"chunk_index": int, "pose": 1-5, "layout": str, "punch_in": bool,
         "layout_preset": str, "transition_in": str, "position": str,
         "transition": str, "scale": 0.65-0.90} (dopo "punch_in" sono alias
        e derivati per compatibilita'; i punch_in sono limitati a max 2).
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
    # Ruoli narrativi (se classificati a monte): guidano regia dedicata per atto
    # e stabilizzano il finale (i lock deterministici a valle li garantiscono
    # anche se l'LLM li ignora).
    has_narrative = any(
        isinstance(ch, dict) and ch.get("narrative_role") in ("hook", "body", "cta")
        for ch in chunks
    )
    # Contesto compatto: indice + testo per chunk (i chunk sono da 2-3 parole,
    # quindi il prompt resta leggero anche con decine di chunk).
    lines = []
    for i, ch in enumerate(chunks):
        text = str((ch or {}).get("text", "")).strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "..."
        if has_narrative and isinstance(ch, dict):
            role = str(ch.get("narrative_role", "body"))
            tag = {"hook": "HOOK", "body": "CORPO", "cta": "CTA"}.get(role, "CORPO")
            lines.append(f"{i} [{tag}]: {text}")
        else:
            lines.append(f"{i}: {text}")
    chunk_block = "\n".join(lines)
    script_snippet = (script_text or "").strip().replace("\n", " ")
    if len(script_snippet) > 1500:
        script_snippet = script_snippet[:1500] + "..."

    narrative_rules = ""
    if has_narrative:
        narrative_rules = (
            "\nREGOLE NARRATIVE (hook/corpo/CTA, tag [HOOK]/[CORPO]/[CTA]):\n"
            "- Chunk [HOOK]: posa 1 assertiva, layout_center_standard; punch_in=true "
            "SOLO sull'ultimo chunk hook (picco di attenzione).\n"
            "- Chunk [CORPO]: UNA sola identità per beat (stessa posa+layout per "
            "tutti i chunk dello stesso pensiero); cambia solo ai confini di beat. "
            "Domande → posa 5 split, dati/numeri → posa 4 split, resto → posa 2.\n"
            "- Chunk [CTA]: posa 3, layout_center_standard, punch_in=false SEMPRE "
            "(il finale deve restare perfettamente stabile, niente stacchi).\n"
        )
    system = (
        "Sei un regista che assegna un personaggio 2D ai sottotitoli di un video breve. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Analizza il tono di ogni chunk e assegna personaggio/layout/punch-in.\n\n"
        "REGOLE POSE:\n" + _POSE_RULES + "\n\n"
        "REGOLE LAYOUT E REGIA:\n" + _LAYOUT_RULES + "\n"
        "- Cambia posa/layout SOLO quando il concetto o il tono cambia davvero: "
        "se il discorso e' continuo, mantieni stessa posa e stesso layout dei chunk "
        "precedenti (non cambiare ad ogni chunk di 2 parole).\n"
        "- Alterna i lati degli split (sinistra/destra) per dare ritmo visivo.\n"
        + narrative_rules + "\n"
        f"LAYOUT VALIDI: {', '.join(VALID_LAYOUT_PRESETS)}\n\n"
        f"SCRIPT (contesto):\n{script_snippet}\n\n"
        f"CHUNK ({n} totali, 'indice: testo'):\n{chunk_block}\n\n"
        "Rispondi SOLO con un array JSON con ESATTAMENTE "
        f"{n} oggetti in ordine di chunk_index, cosi': "
        '[{"chunk_index": 0, "pose": 1, '
        '"layout": "layout_split_right", "punch_in": false}]'
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

    plan = _finalize_character_plan([
        _normalize_entry(entry, i, str((chunks[i] or {}).get("text", "")))
        for i, entry in enumerate(raw_entries)
    ], chunks)
    if on_attempt is not None:
        try:
            poses = ", ".join(
                f"chunk {p['chunk_index']}: posa {p['pose']} ({p['layout']}"
                f"{' +PUNCH' if p['punch_in'] else ''})"
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
        {"pose": int, "use_preset": bool, "layout": str, "layout_preset": str,
         "punch_in": bool, "transition_in": str, "position": str,
         "transition": str, "scale": float}.
        Con preset valido: il render usa scala width-based/ancoraggio/safe-area
        del preset (punch_in amplifica). Senza preset (chunk legacy v1):
        altezza da scale, XY da position bbox.
    """
    if not isinstance(chunk, dict) or chunk.get("pose") is None:
        return None
    try:
        pose = int(chunk.get("pose"))
    except (TypeError, ValueError):
        return None
    if pose < 1 or pose > CHARACTER_POSE_COUNT:
        return None
    raw_preset = chunk.get("layout", chunk.get("layout_preset"))
    use_preset = isinstance(raw_preset, str) and (
        raw_preset in VALID_LAYOUT_PRESETS
        or raw_preset in ("layout_bottom_focus", "layout_closeup_center")
    )
    if use_preset:
        preset = normalize_preset(raw_preset)
    else:
        # Chunk legacy v1 (solo position): mappa sul preset vicino ma il render
        # resta in modalita' legacy per non alterare il look esistente.
        preset = normalize_preset(chunk.get("position", "bottom_center"), "layout_center_standard")
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
        "layout": preset,
        "layout_preset": preset,  # alias (compatibilita' sistema a zone v1)
        "punch_in": _parse_punch_in(chunk),
        "transition_in": transition_in,
        "position": position,
        "transition": legacy_transition(transition_in),
        "scale": scale,
    }


def enrich_chunks_with_characters(
    chunks: list[dict],
    plan: list[dict] | None,
) -> list[dict]:
    """Arricchisce i chunk con i metadati character (layout/punch_in + alias).

    Copia pose/layout/punch_in (+ layout_preset alias, transition_in derivata,
    position/transition/scale legacy). Se `plan` e' None/vuoto o la lunghezza
    non coincide, i chunk restano invariati (pipeline senza personaggio).
    Non solleva mai.
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
