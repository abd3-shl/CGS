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
    CHARACTER_MAX_SAME_POSE,
    CHARACTER_MAX_SAME_SIDE,
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
try:
    from config import (
        CHARACTER_MIN_BLOCK_DURATION,
        CHARACTER_DISCONTINUOUS_MODE,
        CHARACTER_HOOK_VISIBLE,
        CHARACTER_CTA_VISIBLE,
        CHARACTER_BODY_VISIBLE_RATIO,
        CHARACTER_POSE_SIDE_MAP,
        get_pose_side_constraint,
    )
except Exception:
    CHARACTER_MIN_BLOCK_DURATION = 2.5
    CHARACTER_DISCONTINUOUS_MODE = 1
    CHARACTER_HOOK_VISIBLE = 1
    CHARACTER_CTA_VISIBLE = 1
    CHARACTER_BODY_VISIBLE_RATIO = 0.3
    CHARACTER_POSE_SIDE_MAP = {1: "any", 2: "center", 3: "center", 4: "left", 5: "split"}

    def get_pose_side_constraint(pose: int) -> str:  # type: ignore
        try:
            return CHARACTER_POSE_SIDE_MAP.get(int(pose), "any")
        except Exception:
            return "any"
from core.layout_presets import (
    MAX_PUNCH_INS_PER_VIDEO,
    VALID_LAYOUT_PRESETS,
    legacy_position,
    legacy_transition,
    normalize_preset,
    normalize_transition_in,
    preset_alternate_transition,
    preset_default_transition,
    preset_side,
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


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    from groq import Groq as _Groq
    client = _Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


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


_resolved_path_cache: dict[int, Path | None] = {}


def resolve_character_path(pose_number: int) -> Path | None:
    """Ritorna il percorso esistente per la posa, o None se assente (cachato)."""
    try:
        pose_i = int(pose_number)
    except (TypeError, ValueError):
        return None
    if pose_i in _resolved_path_cache:
        return _resolved_path_cache[pose_i]
    for p in _candidate_asset_paths(pose_number):
        try:
            if p.is_file():
                _resolved_path_cache[pose_i] = p
                return p
        except OSError:
            continue
    _resolved_path_cache[pose_i] = None
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


def _pose_allowed_layouts(pose: int) -> list[str]:
    """Layout ammessi per posa da CHARACTER_POSE_SIDE_MAP (mai eccezioni).

    - any    -> tutti (center + split entrambi i lati)
    - center -> solo layout_center_standard
    - left   -> solo layout_split_left (es. posa 4: indica verso destra, deve
      stare a sinistra per puntare verso il testo)
    - right  -> solo layout_split_right
    - split  -> entrambi gli split (alternabili)
    """
    try:
        constraint = get_pose_side_constraint(pose)
    except Exception:
        constraint = "any"
    try:
        c = str(constraint or "any").strip().lower()
    except Exception:
        c = "any"
    if c == "center":
        return ["layout_center_standard"]
    if c == "left":
        return ["layout_split_left"]
    if c == "right":
        return ["layout_split_right"]
    if c == "split":
        return ["layout_split_left", "layout_split_right"]
    return ["layout_center_standard", "layout_split_left", "layout_split_right"]


def _constrain_preset_for_pose(pose: int, preset: str, alternate: int = 0) -> str:
    """Forza il preset dentro i layout ammessi per posa (mai eccezioni).

    Se il preset e' gia' ammesso lo tiene; altrimenti usa il primo ammesso
    (o alterna tra i due split quando il vincolo e' 'split').
    """
    try:
        allowed = _pose_allowed_layouts(pose)
        if preset in allowed:
            return preset
        if len(allowed) == 2 and set(allowed) == {"layout_split_left", "layout_split_right"}:
            return allowed[int(alternate or 0) % 2]
        return allowed[0] if allowed else preset
    except Exception:
        return preset


def _preset_for_pose(pose: int, alternate: int = 0) -> str:
    """Preset deterministico per posa (fallback e normalizzazione).

    Rispetta CHARACTER_POSE_SIDE_MAP: posa 4 -> SEMPRE split_left (indica
    verso destra, deve stare a sinistra); posa 5 -> split alternati;
    posa 2/3 -> centro; altre -> rotazione standard/split.
    """
    try:
        allowed = _pose_allowed_layouts(pose)
    except Exception:
        allowed = ["layout_center_standard", "layout_split_left", "layout_split_right"]
    if len(allowed) == 1:
        return allowed[0]
    if len(allowed) == 2 and set(allowed) == {"layout_split_left", "layout_split_right"}:
        # Vincolo 'split' (es. posa 5): alterna i lati.
        return allowed[int(alternate or 0) % 2]
    # Vincolo 'any': rotazione standard (posa 1 versatile).
    try:
        if int(pose) == 4:
            # Rete di sicurezza se la mappa fosse 'any': comunque a sinistra.
            return "layout_split_left"
    except Exception:
        pass
    cycle = ["layout_center_standard", "layout_split_left", "layout_split_right"]
    return cycle[int(alternate or 0) % len(cycle)]


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
    """Blocchi deterministici per atto (stabilita' dove serve, ritmo altrove).

    - HOOK: primo chunk posa 1 + center_standard + slide_up; punch sul climax
      (ultimo chunk hook, zoom fluido in render, mai jump-cut secco).
      Transizioni pulite in ingresso.
    - CORPO: NESSUN lock di beat (il lock storico teneva la stessa identita'
      per ~3 chunk di fila rendendo il video statico). Il corpo resta dinamico:
      ogni chunk puo' cambiare posa/lato con morph fluido; la coerenza e'
      garantita dalle transizioni morbide + persistenza nei gap, non dalla
      staticita'. La varieta' ritmica e' forzata in _enforce_rhythm_variety.
    - CTA: TUTTI i chunk su un'unica identita' (forte: posa 3; debole: posa 2),
      center_standard, punch=False, scala 0.75, ingresso fade sul primo.
      Il personaggio resta pixel-identico fino alla dissolvenza finale
      (stessa stabilita' storica: il finale non deve mai tremare).
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
        # --- CORPO: nessun lock (dinamica ritmica, vedi _enforce_rhythm_variety).
        # Il vecchio lock per beat forzava la stessa identita' per ~3 chunk
        # consecutivi (video statico). Ora il corpo cambia posa/lato ogni 1-2
        # chunk con morph fluido: niente staticita', niente blink (persistenza
        # nei gap + morph da posizione precedente in text_animator).
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


def _side_of_layout(layout: str) -> str:
    """Lato 'left'/'right'/'center' di un preset (mai eccezioni)."""
    try:
        return preset_side(layout)
    except Exception:
        return "center"


def _pose_for_text(text: str, avoid: int = 0) -> int:
    """Posa semanticamente plausibile per il testo, evitando `avoid`.

    Priorita': '?' -> 5 (riflessione, split), cifre -> 4 (indica, split),
    '!' -> 3 (positivo/enfasi), altrimenti rotazione 1 -> 2 -> 4 -> 5
    (mai 2 in split: il chiamante forza center per posa 2).
    """
    try:
        t = str(text or "")
    except Exception:
        t = ""
    import re as _re
    if "?" in t:
        return 5 if avoid != 5 else 2
    if _re.search(r"\d", t):
        return 4 if avoid != 4 else 1
    if "!" in t:
        return 3 if avoid != 3 else 2
    for cand in (1, 2, 4, 5, 3):
        if cand != avoid:
            return cand
    return 2


def _layout_for_pose_side(pose: int, side: str, flip: int = 0) -> str:
    """Layout valido per posa+lato desiderati (rispetta CHARACTER_POSE_SIDE_MAP).

    - vincolo 'left' (posa 4: indica verso destra) -> SEMPRE split_left,
      ignora lato richiesto/flip (a destra indicherebbe fuori campo);
    - vincolo 'right' -> SEMPRE split_right;
    - vincolo 'center' (pose 2/3) -> SEMPRE center_standard;
    - vincolo 'split' (posa 5) -> split richiesto o alternato;
    - vincolo 'any' (posa 1) -> segue il lato richiesto.
    """
    try:
        pose_i = int(pose)
    except (TypeError, ValueError):
        pose_i = 1
    side = str(side or "center").lower()
    try:
        allowed = _pose_allowed_layouts(pose_i)
    except Exception:
        allowed = ["layout_center_standard", "layout_split_left", "layout_split_right"]
    if len(allowed) == 1:
        return allowed[0]
    if len(allowed) == 2 and set(allowed) == {"layout_split_left", "layout_split_right"}:
        if side in ("left", "right"):
            want = "layout_split_left" if side == "left" else "layout_split_right"
            if want in allowed:
                return want
        return allowed[int(flip or 0) % 2]
    if pose_i == 5:
        if side in ("left", "right"):
            return "layout_split_left" if side == "left" else "layout_split_right"
        return "layout_split_left" if flip % 2 == 0 else "layout_split_right"
    if pose_i in (2, 3):
        return "layout_center_standard"
    # posa 1: versatile, segue il lato richiesto
    if side == "left":
        return "layout_split_left"
    if side == "right":
        return "layout_split_right"
    return "layout_center_standard"


def _enforce_rhythm_variety(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Varieta' ritmica calma: mai >N identici di fila.

    Regole:
    - Mai piu' di CHARACTER_MAX_SAME_POSE (default 2) chunk consecutivi con la
      STESSA posa: al successivo si forza un'alternativa semanticamente
      plausibile (?/cifre/!/rotazione). In ogni caso mai la stessa immagine
      due volte di fila tra blocchi visibili (controllo in macro-blocchi).
    - Mai piu' di CHARACTER_MAX_SAME_SIDE (default 2) con lo STESSO lato
      (left/right/center): poi si alterna (center->split, split->lato
      opposto o centro in rotazione).
    - Transizioni: i center alternano slide_up / zoom_in (varieta' dolce senza
      movimenti laterali continui); gli split usano la direzionale naturale;
      mai 3 transizioni identiche di fila (la 3a diventa fade morbida).
    - Vincoli posa sempre rispettati (4->split, 2->center).
    - CTA card (cta_card=true) e CTA lock: esclusi (finale stabile intenzionale);
      hook primo chunk: preservato (posa 1 center).
    Non solleva mai; senza ruoli applica comunque ai chunk body-like.
    """
    try:
        if not plan or not chunks or len(plan) != len(chunks):
            return plan
        try:
            max_same_pose = max(1, int(CHARACTER_MAX_SAME_POSE))
        except Exception:
            max_same_pose = 2
        try:
            max_same_side = max(1, int(CHARACTER_MAX_SAME_SIDE))
        except Exception:
            max_same_side = 2
    except Exception:
        return plan
    try:
        # Indici CTA card / CTA (stabili): non toccare posa/lato.
        skip_idx: set[int] = set()
        hook_first: int | None = None
        for i, ch in enumerate(chunks):
            try:
                if isinstance(ch, dict) and bool(ch.get("cta_card")):
                    skip_idx.add(i)
                elif _chunk_role(ch) == "cta":
                    skip_idx.add(i)
                if _chunk_role(ch) == "hook" and hook_first is None:
                    hook_first = i
            except Exception:
                continue
        run_pose = 0
        last_pose: int | None = None
        run_side = 0
        last_side: str | None = None
        run_trans = 0
        last_trans: str | None = None
        side_cycle = ["center", "right", "left"]
        cycle_k = 0
        split_flip = 0
        for i in range(len(plan)):
            try:
                entry = plan[i]
                if not isinstance(entry, dict):
                    continue
                if i in skip_idx:
                    # Aggiorna i run senza forzare (il finale resta stabile ma
                    # non "contamina" il conteggio del corpo).
                    try:
                        last_pose = int(entry.get("pose", last_pose or 0)) or last_pose
                    except Exception:
                        pass
                    run_pose = 0
                    try:
                        last_side = _side_of_layout(str(entry.get("layout", last_side or "center")))
                    except Exception:
                        pass
                    run_side = 0
                    continue
                if hook_first is not None and i == hook_first:
                    try:
                        last_pose = int(entry.get("pose", 1))
                    except Exception:
                        last_pose = 1
                    run_pose = 1
                    try:
                        last_side = _side_of_layout(str(entry.get("layout", "layout_center_standard")))
                    except Exception:
                        last_side = "center"
                    run_side = 1
                    try:
                        last_trans = str(entry.get("transition_in", "slide_up"))
                    except Exception:
                        last_trans = "slide_up"
                    run_trans = 1
                    continue
                # --- Posa: conteggio run ---
                try:
                    cur_pose = int(entry.get("pose", 1))
                except (TypeError, ValueError):
                    cur_pose = 1
                if last_pose is not None and cur_pose == last_pose:
                    run_pose += 1
                else:
                    run_pose = 1
                    last_pose = cur_pose
                if run_pose > max_same_pose:
                    # Forza alternativa plausibile (mai uguale alla precedente).
                    try:
                        txt = str((chunks[i] or {}).get("text", ""))
                    except Exception:
                        txt = ""
                    new_pose = _pose_for_text(txt, avoid=cur_pose)
                    if new_pose == cur_pose:
                        new_pose = 2 if cur_pose != 2 else 1
                    entry["pose"] = new_pose
                    cur_pose = new_pose
                    last_pose = new_pose
                    run_pose = 1
                    # Layout coerente con la nuova posa (lato alternato).
                    try:
                        desired_side = side_cycle[cycle_k % len(side_cycle)]
                        cycle_k += 1
                        if _side_of_layout(str(entry.get("layout", ""))) == desired_side and desired_side in ("left", "right"):
                            desired_side = "left" if desired_side == "right" else "right"
                    except Exception:
                        desired_side = "center"
                    new_layout = _layout_for_pose_side(new_pose, desired_side, split_flip)
                    split_flip += 1
                    entry["layout"] = new_layout
                    entry["layout_preset"] = new_layout
                    try:
                        entry["position"] = legacy_position(new_layout)
                    except Exception:
                        pass
                # --- Lato: conteggio run (dopo eventuale fix posa) ---
                try:
                    cur_side = _side_of_layout(str(entry.get("layout", "layout_center_standard")))
                except Exception:
                    cur_side = "center"
                # Ripara vincoli posa da CHARACTER_POSE_SIDE_MAP
                # (posa 4 -> sempre split_left: indica verso destra, deve
                # stare a sinistra; posa 2 mai split).
                try:
                    _p = int(entry.get("pose", 1))
                except (TypeError, ValueError):
                    _p = 1
                try:
                    _allowed = _pose_allowed_layouts(_p)
                except Exception:
                    _allowed = ["layout_center_standard", "layout_split_left", "layout_split_right"]
                _cur_lay = str(entry.get("layout", "layout_center_standard"))
                if _cur_lay not in _allowed:
                    fixed = _constrain_preset_for_pose(_p, _cur_lay, split_flip)
                    split_flip += 1
                    entry["layout"] = fixed
                    entry["layout_preset"] = fixed
                    try:
                        entry["position"] = legacy_position(fixed)
                    except Exception:
                        pass
                    cur_side = _side_of_layout(fixed)
                elif _p == 2 and cur_side in ("left", "right"):
                    entry["layout"] = "layout_center_standard"
                    entry["layout_preset"] = "layout_center_standard"
                    try:
                        entry["position"] = legacy_position("layout_center_standard")
                    except Exception:
                        pass
                    cur_side = "center"
                elif _p == 5 and cur_side == "center":
                    fixed = _layout_for_pose_side(5, "left" if last_side != "left" else "right", split_flip)
                    split_flip += 1
                    entry["layout"] = fixed
                    entry["layout_preset"] = fixed
                    try:
                        entry["position"] = legacy_position(fixed)
                    except Exception:
                        pass
                    cur_side = _side_of_layout(fixed)
                if last_side is not None and cur_side == last_side:
                    run_side += 1
                else:
                    run_side = 1
                    last_side = cur_side
                if run_side > max_same_side:
                    # Alterna rispettando i vincoli posa (posa 4 bloccata a
                    # sinistra: lato fisso, si cambia posa non lato).
                    try:
                        _allowed_now = _pose_allowed_layouts(_p)
                    except Exception:
                        _allowed_now = ["layout_center_standard", "layout_split_left", "layout_split_right"]
                    if len(_allowed_now) == 1:
                        # Lato bloccato (es. posa 4 sempre left): cambia posa
                        # invece di forzare un lato vietato.
                        try:
                            txt2 = str((chunks[i] or {}).get("text", ""))
                        except Exception:
                            txt2 = ""
                        new_pose2 = _pose_for_text(txt2, avoid=_p)
                        if new_pose2 == _p or len(_pose_allowed_layouts(new_pose2)) == 1 and _side_of_layout(str(entry.get("layout", ""))) == _side_of_layout(_pose_allowed_layouts(new_pose2)[0]):
                            # Evita di restare sullo stesso lato bloccato.
                            for _cand in (1, 5, 3, 2):
                                if _cand != _p:
                                    new_pose2 = _cand
                                    break
                        entry["pose"] = new_pose2
                        _p = new_pose2
                        cur_pose = new_pose2
                        last_pose = new_pose2
                        run_pose = 1
                        new_layout = _layout_for_pose_side(_p, "center", split_flip)
                        split_flip += 1
                    elif cur_side == "center":
                        desired = "left" if (last_side != "left") else "right"
                        # Evita posa 2 in split: se posa 2, cambia posa prima.
                        if _p == 2:
                            entry["pose"] = 1
                            _p = 1
                            cur_pose = 1
                            last_pose = 1
                            run_pose = 1
                        new_layout = _layout_for_pose_side(_p, desired, split_flip)
                        split_flip += 1
                    elif cur_side == "left":
                        new_layout = _layout_for_pose_side(_p, "right", split_flip) if _p in (1, 5) else "layout_center_standard"
                        # Posa 4 resta a sinistra: _layout_for_pose_side la tiene
                        # comunque in split_left anche se richiesto 'right'.
                        try:
                            new_layout = _constrain_preset_for_pose(_p, new_layout, split_flip)
                        except Exception:
                            pass
                        split_flip += 1
                    else:  # right
                        new_layout = _layout_for_pose_side(_p, "left", split_flip) if _p in (1, 4, 5) else "layout_center_standard"
                        split_flip += 1
                    entry["layout"] = new_layout
                    entry["layout_preset"] = new_layout
                    try:
                        entry["position"] = legacy_position(new_layout)
                    except Exception:
                        pass
                    try:
                        last_side = _side_of_layout(new_layout)
                    except Exception:
                        pass
                    run_side = 1
                else:
                    last_side = cur_side
                # --- Transizioni: varieta' dolce ---
                try:
                    lay = str(entry.get("layout", "layout_center_standard"))
                except Exception:
                    lay = "layout_center_standard"
                try:
                    cur_trans = str(entry.get("transition_in", preset_default_transition(lay)))
                except Exception:
                    cur_trans = "fade"
                # Center: alterna slide_up / zoom_in (nessun movimento laterale
                # continuo); split: direzionale naturale.
                try:
                    _side_now = _side_of_layout(lay)
                except Exception:
                    _side_now = "center"
                if _side_now == "center" and cur_trans not in ("zoom_in", "slide_up", "fade"):
                    cur_trans = preset_default_transition(lay)
                    entry["transition_in"] = cur_trans
                    try:
                        entry["transition"] = legacy_transition(cur_trans)
                    except Exception:
                        pass
                if last_trans is not None and cur_trans == last_trans:
                    run_trans += 1
                else:
                    run_trans = 1
                    last_trans = cur_trans
                if run_trans >= 3:
                    # Terza identica di fila -> alternativa morbida.
                    if _side_now == "center":
                        alt = "zoom_in" if cur_trans != "zoom_in" else "slide_up"
                    else:
                        alt = "fade"
                    alt = normalize_transition_in(alt, lay)
                    entry["transition_in"] = alt
                    try:
                        entry["transition"] = legacy_transition(alt)
                    except Exception:
                        pass
                    last_trans = alt
                    run_trans = 1
                else:
                    last_trans = cur_trans
            except Exception:
                continue
    except Exception:
        pass
    return plan


def _finalize_character_plan(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Lock narrativi + varieta' ritmica + cap per atto + stabilizzazione macro-blocchi."""
    try:
        if any(_chunk_role(c) for c in (chunks or [])):
            locked = _apply_narrative_locks(plan, chunks)
            varied = _enforce_rhythm_variety(locked, chunks)
            capped = _cap_punch_ins_narrative(varied, chunks)
        else:
            capped = _cap_punch_ins(_enforce_rhythm_variety(plan, chunks))
    except Exception:
        try:
            capped = _cap_punch_ins(plan)
        except Exception:
            capped = list(plan or [])
    # Stabilizzazione macro-blocchi (Breath & Focus): posa/lato unici per
    # blocco >= MIN_DURATION, presenza discontinua Hook/CTA vs Body.
    try:
        return _apply_macro_block_stabilization(capped, chunks)
    except Exception:
        return capped


# -------------------------------------------------- Macro-blocchi stabili
# "Breath & Focus": niente flicker per-chunk, posa/lato bloccati per almeno
# CHARACTER_MIN_BLOCK_DURATION, personaggio visibile in Hook/CTA e nascosto
# nei beat intermedi. Ogni chunk arricchito porta anche:
#   chunk["character"] = {"visible", "pose", "pose_id", "side",
#                         "event", "block_id"}
# con event in {"ENTRY","SUSTAIN","EXIT","NONE"} e side in {"LEFT","RIGHT","CENTER"}.

_POSE_ID_MAP: dict[int, str] = {
    1: "pose_crossed",
    2: "pose_open",
    3: "pose_thumb",
    4: "pose_pointing",
    5: "pose_chin",
}


def _macro_role(chunk: dict | None, idx: int, n: int) -> str:
    """Ruolo narrativo per macro-blocchi (hook/body/cta, mai eccezioni)."""
    try:
        r = str((chunk or {}).get("narrative_role", "") or "").strip().lower()
        if r in ("hook", "body", "cta"):
            return r
    except Exception:
        pass
    try:
        if n <= 0:
            return "body"
        if n <= 3:
            if idx == 0:
                return "hook"
            if idx == n - 1:
                return "cta"
            return "body"
        if idx < 2:
            return "hook"
        if idx >= n - 2 and n > 6:
            return "cta"
        if idx == n - 1:
            return "cta"
        return "body"
    except Exception:
        return "body"


def _chunk_duration(chunk: dict | None, default: float = 0.8) -> float:
    """Durata chunk in secondi (end-start, fallback default, mai eccezioni)."""
    try:
        s = float((chunk or {}).get("start", 0.0))
        e = float((chunk or {}).get("end", s + default))
        d = e - s
        if d > 0.05 and d < 30.0:
            return float(d)
    except Exception:
        pass
    return float(default)


def _side_of_preset(preset: str) -> str:
    """Lato maiuscolo per preset (LEFT/RIGHT/CENTER, mai eccezioni)."""
    try:
        s = str(preset_side(preset) or "center").strip().lower()
    except Exception:
        s = "center"
    if s == "left":
        return "LEFT"
    if s == "right":
        return "RIGHT"
    return "CENTER"


def _pose_id_of(pose: int) -> str:
    """pose_id stringa per posa int (compat spec prompt)."""
    try:
        return _POSE_ID_MAP.get(int(pose), f"pose_{int(pose)}")
    except Exception:
        return "pose_1"


def _build_macro_time_blocks(chunks: list[dict], roles: list[str]) -> list[list[int]]:
    """Divide gli indici in blocchi temporali >= MIN_DURATION.

    Hook = un blocco unico, CTA = un blocco unico, Body = blocchi da almeno
    MIN_DURATION (l'eventuale resto corto viene fuso nell'ultimo blocco).
    """
    try:
        min_d = max(0.5, float(CHARACTER_MIN_BLOCK_DURATION))
    except Exception:
        min_d = 2.5
    n = len(chunks or [])
    hook_idx = [i for i, r in enumerate(roles) if r == "hook"]
    body_idx = [i for i, r in enumerate(roles) if r == "body"]
    cta_idx = [i for i, r in enumerate(roles) if r == "cta"]
    blocks: list[list[int]] = []
    if hook_idx:
        blocks.append(list(hook_idx))
    # Body a sezioni temporali.
    cur: list[int] = []
    cur_d = 0.0
    for i in body_idx:
        try:
            cur.append(i)
            cur_d += _chunk_duration(chunks[i] if i < n else None)
        except Exception:
            continue
        if cur_d >= min_d:
            blocks.append(list(cur))
            cur, cur_d = [], 0.0
    if cur:
        if blocks and blocks[-1] and roles[blocks[-1][0]] == "body":
            # Fondi il resto corto nell'ultimo blocco body (evita micro-blocchi).
            blocks[-1].extend(cur)
        else:
            blocks.append(list(cur))
    if cta_idx:
        blocks.append(list(cta_idx))
    if not blocks and n > 0:
        blocks = [list(range(n))]
    return blocks


def _select_block_pose_layout(
    block: list[int],
    plan_by_idx: dict[int, dict],
    fallback_pose: int = 1,
) -> tuple[int, str]:
    """Unica (posa, layout) per il blocco: prima voce valida, con vincoli posa.

    Vincoli da CHARACTER_POSE_SIDE_MAP: posa 2 mai in split (-> center),
    posa 4 sempre split_left (indica verso destra, sta a sinistra).
    """
    pose = fallback_pose
    preset = "layout_center_standard"
    try:
        first = block[0] if block else 0
        entry = plan_by_idx.get(int(first), {}) or {}
        try:
            pose = int(entry.get("pose", fallback_pose))
        except Exception:
            pose = fallback_pose
        pose = min(CHARACTER_POSE_COUNT, max(1, pose))
        raw = entry.get("layout", entry.get("layout_preset", preset))
        preset = normalize_preset(raw, _preset_for_pose(pose, int(first)))
    except Exception:
        pass
    try:
        preset = _constrain_preset_for_pose(pose, preset, int(block[0]) if block else 0)
        if pose == 5 and preset not in ("layout_split_left", "layout_split_right"):
            # Posa 5 predilige split ma tollera center se scelto dal regista.
            pass
    except Exception:
        pass
    return int(pose), str(preset)


def _apply_macro_block_stabilization(
    plan: list[dict],
    chunks: list[dict],
) -> list[dict]:
    """Macro-blocchi stabili con presenza discontinua (mai eccezioni).

    - Raggruppa per ruolo hook/body/cta + durata >= MIN_DURATION.
    - Visibilita': Hook/CTA secondo config, Body solo BODY_VISIBLE_RATIO
      (primi blocchi body); con DISCONTINUOUS_MODE=0 tutto visibile.
    - Ogni blocco visibile usa UNICA posa + UNICO lato (stabile per tutta
      l'apparizione, testo ancorato opposto). Tra blocchi visibili adiacenti
      si evita la ripetizione: posa diversa e, quando possibile, lato diverso
      (mai stessa immagine due volte di fila, niente lato fisso per troppo
      tempo). Con pose a lato obbligato (es. posa 4 sempre a sinistra) il
      lato puo' ripetersi, ma la posa cambia comunque.
    - Eventi: ENTRY (primo del blocco) / SUSTAIN (medi) / EXIT (ultimo).
    - Blocchi nascosti: visible=False, event=NONE, posa rimossa
      (resolve_chunk_layout -> None, nessun paste, testo centrale).
    Ritorna un NUOVO piano lungo quanto plan/chunks (o plan invariato se
    input degeneri). Mai lunghezze diverse.
    """
    try:
        n_plan = len(plan or [])
        n_chunks = len(chunks or [])
        n = min(n_plan, n_chunks)
        if n <= 0:
            return list(plan or [])
        try:
            discont = int(CHARACTER_DISCONTINUOUS_MODE) != 0
        except Exception:
            discont = True
        try:
            hook_vis = int(CHARACTER_HOOK_VISIBLE) != 0
        except Exception:
            hook_vis = True
        try:
            cta_vis = int(CHARACTER_CTA_VISIBLE) != 0
        except Exception:
            cta_vis = True
        try:
            body_ratio = float(CHARACTER_BODY_VISIBLE_RATIO)
            body_ratio = min(1.0, max(0.0, body_ratio))
        except Exception:
            body_ratio = 0.3
        roles = [_macro_role(chunks[i] if i < n_chunks else None, i, n) for i in range(n)]
        blocks = _build_macro_time_blocks(chunks[:n], roles)
        # Visibilita' per blocco.
        body_blocks = [b for b in blocks if b and roles[b[0]] == "body"]
        try:
            num_keep = int(round(len(body_blocks) * body_ratio)) if body_blocks else 0
        except Exception:
            num_keep = 0
        num_keep = max(0, min(len(body_blocks), num_keep))
        keep_body_ids = set()
        for k in range(num_keep):
            try:
                keep_body_ids.add(id(body_blocks[k]))
            except Exception:
                continue
        plan_by_idx: dict[int, dict] = {}
        for i in range(n):
            try:
                e = plan[i] if isinstance(plan[i], dict) else {}
                plan_by_idx[i] = dict(e)
            except Exception:
                plan_by_idx[i] = {}
        out: list[dict] = list(plan or [])
        block_id = 0
        # Ultima posa/lato visibili (attraversa i blocchi: niente ripetizioni
        # neppure a cavallo di un gap nascosto tra due apparizioni).
        prev_vis_pose: int | None = None
        prev_vis_side: str | None = None
        for b in blocks:
            block_id += 1
            if not b:
                continue
            try:
                role = roles[b[0]] if b[0] < len(roles) else "body"
            except Exception:
                role = "body"
            if not discont:
                visible = True
            elif role == "hook":
                visible = bool(hook_vis)
            elif role == "cta":
                visible = bool(cta_vis)
            else:
                visible = id(b) in keep_body_ids
            if visible:
                # Posa/lato unici per tutto il blocco (dal primo chunk).
                # No-repeat tra blocchi: se uguali al blocco visibile
                # precedente, cambia posa (e lato quando possibile).
                try:
                    fb = 1
                    if role == "cta":
                        fb = 3
                    elif role == "hook":
                        fb = 1
                except Exception:
                    fb = 1
                pose, preset = _select_block_pose_layout(b, plan_by_idx, fb)
                try:
                    if prev_vis_pose is not None and int(pose) == int(prev_vis_pose):
                        try:
                            btxt = " ".join(
                                str((chunks[ci] or {}).get("text", ""))
                                for ci in b if ci < len(chunks or []))
                        except Exception:
                            btxt = ""
                        alt = _pose_for_text(btxt, avoid=int(prev_vis_pose))
                        if alt == pose:
                            for _cand in (1, 2, 3, 4, 5):
                                if _cand != pose:
                                    alt = _cand
                                    break
                        pose = alt
                        preset = _constrain_preset_for_pose(
                            pose, _preset_for_pose(pose, int(b[0])), int(b[0]))
                except Exception:
                    pass
                try:
                    _side_now = _side_of_preset(preset)
                    if prev_vis_side is not None and _side_now == prev_vis_side:
                        # Prova un lato diverso con la stessa posa (solo se la
                        # posa lo permette: any/split). Altrimenti tieni il
                        # lato (obbligato) ma la posa e' comunque diversa.
                        for _ws in ("left", "right", "center"):
                            if _ws == prev_vis_side:
                                continue
                            try:
                                _cand_lay = _layout_for_pose_side(int(pose), _ws, int(b[0]))
                                if _side_of_preset(_cand_lay) != prev_vis_side:
                                    preset = _cand_lay
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
                side = _side_of_preset(preset)
                pose_id = _pose_id_of(pose)
                try:
                    first_entry = plan_by_idx.get(int(b[0]), {}) or {}
                    scale = float(first_entry.get("scale", 0.75))
                except Exception:
                    scale = 0.75
                try:
                    scale = min(CHARACTER_SCALE_MAX, max(CHARACTER_SCALE_MIN, scale))
                except Exception:
                    scale = 0.75
                for pos, ci in enumerate(b):
                    try:
                        if ci < 0 or ci >= len(out):
                            continue
                        base = dict(out[ci]) if isinstance(out[ci], dict) else {}
                        if pos == 0:
                            event = "ENTRY"
                        elif pos == len(b) - 1:
                            event = "EXIT" if len(b) > 1 else "ENTRY"
                        else:
                            event = "SUSTAIN"
                        trans = base.get("transition_in") or preset_default_transition(preset)
                        try:
                            trans = normalize_transition_in(trans, preset)
                        except Exception:
                            pass
                        base.update({
                            "chunk_index": int(ci),
                            "pose": int(pose),
                            "layout": str(preset),
                            "layout_preset": str(preset),
                            "punch_in": bool(base.get("punch_in", False)),
                            "transition_in": str(trans),
                            "position": legacy_position(preset),
                            "transition": legacy_transition(str(trans)),
                            "scale": float(scale),
                            "block_id": int(block_id),
                            "char_event": str(event),
                            "char_visible": True,
                            "character": {
                                "visible": True,
                                "pose": int(pose),
                                "pose_id": str(pose_id),
                                "side": str(side),
                                "event": str(event),
                                "block_id": int(block_id),
                            },
                        })
                        # CTA resta senza punch (stabile), hook/body invariati.
                        if role == "cta":
                            base["punch_in"] = False
                            try:
                                base["character"]["pose"] = int(pose)
                            except Exception:
                                pass
                        out[ci] = base
                        plan_by_idx[int(ci)] = dict(base)
                    except Exception:
                        continue
                prev_vis_pose, prev_vis_side = int(pose), str(side)
            else:
                # Blocco nascosto: pulito, solo testo (Breath & Focus).
                for ci in b:
                    try:
                        if ci < 0 or ci >= len(out):
                            continue
                        base = dict(out[ci]) if isinstance(out[ci], dict) else {}
                        base.update({
                            "chunk_index": int(ci),
                            "pose": None,
                            "layout": "layout_center_standard",
                            "layout_preset": "layout_center_standard",
                            "punch_in": False,
                            "transition_in": "fade",
                            "position": "bottom_center",
                            "transition": "fade",
                            "scale": 0.75,
                            "block_id": int(block_id),
                            "char_event": "NONE",
                            "char_visible": False,
                            "character": {
                                "visible": False,
                                "pose": None,
                                "pose_id": "",
                                "side": "CENTER",
                                "event": "NONE",
                                "block_id": int(block_id),
                            },
                        })
                        out[ci] = base
                        plan_by_idx[int(ci)] = dict(base)
                    except Exception:
                        continue
        return out
    except Exception:
        try:
            return list(plan or [])
        except Exception:
            return plan


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
    # dalla position legacy, altrimenti euristica per posa. I vincoli vengono
    # da CHARACTER_POSE_SIDE_MAP (posa 4 -> sempre split_left anche se l'LLM
    # propone split_right/center; posa 5 predilige i laterali).
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
    # Vincoli posa centralizzati (posa 4 sempre a sinistra, posa 2 mai split).
    try:
        preset = _constrain_preset_for_pose(pose, preset, chunk_index)
    except Exception:
        pass
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
    """Piano deterministico senza LLM (ritmo dinamico anti-staticita').

    - Primo chunk: posa 1, center_standard, slide_up.
    - Successivi: "?" -> posa 5 split, "!" -> posa 3 (+punch corpo, mai CTA),
      cifre -> posa 4 split_left (indica verso destra, sempre a sinistra),
      altrimenti rotazione dinamica
      1(center) -> 4(split_left) -> 2(center) -> 5(split_left) -> 1...
      Mai stessa posa/lato per piu' di 2 chunk (enforce in finalize).
    - Transizioni: center alternano slide_up/zoom_in, split direzionali con
      fade morbida ogni 3 chunk (ritmo coerente, mai frenetico).
    - Con ruoli narrativi: niente punch in CTA (finale stabile) e lock CTA /
      hook preservati in finalize (corpo sempre dinamico).
    - I punch_in sono limitati per atto (vedi _cap_punch_ins_narrative).
    """
    # Rotazione dinamica: alterna centro/split e tutte le pose (mai 3 uguali).
    # Posa 4 SEMPRE split_left (punta a destra -> sta a sinistra).
    cycle = [
        (1, "layout_center_standard"),
        (4, "layout_split_left"),
        (2, "layout_center_standard"),
        (5, "layout_split_left"),
        (1, "layout_split_right"),
        (4, "layout_split_left"),
        (3, "layout_center_standard"),
        (2, "layout_center_standard"),
    ]
    plan: list[dict] = []
    cycle_i = 0
    split_flip = 0
    import re as _re
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
                punch_in = True  # enfasi: zoom fluido (mai in CTA: stabile)
            elif "!" in text:
                pose = 3  # CTA/outro: posa giusta, senza stacco
            elif _re.search(r"\d", text):
                pose = 4  # dati/numeri: indica il testo
            else:
                pose, preset_guess = cycle[cycle_i % len(cycle)]
                cycle_i += 1
                # Evita 3 pose uguali anche prima del finalize (ritmo).
                if plan and len(plan) >= 2:
                    try:
                        if plan[-1].get("pose") == pose and plan[-2].get("pose") == pose:
                            pose = 2 if pose != 2 else 1
                    except Exception:
                        pass
                if pose == 4:
                    # Posa 4 indica verso destra -> SEMPRE a sinistra.
                    preset = "layout_split_left"
                elif pose == 5:
                    preset = "layout_split_left" if split_flip % 2 == 0 else "layout_split_right"
                    split_flip += 1
                else:
                    # Rispetta il lato suggerito dal ciclo ma con vincoli posa.
                    try:
                        _side_want = preset_side(preset_guess)
                    except Exception:
                        _side_want = "center"
                    preset = _layout_for_pose_side(pose, _side_want, i)
                try:
                    _s2 = preset_side(preset)
                except Exception:
                    _s2 = "center"
                if _s2 == "center":
                    _tr = "zoom_in" if (i % 4 == 2) else preset_default_transition(preset)
                else:
                    _tr = preset_default_transition(preset)
                if i % 5 == 4 and isinstance(_tr, str) and _tr.startswith("slide"):
                    _tr = "fade"
                _tr = normalize_transition_in(_tr, preset)
                plan.append({
                    "chunk_index": i,
                    "pose": pose,
                    "layout": preset,
                    "layout_preset": preset,
                    "punch_in": punch_in,
                    "transition_in": _tr,
                    "position": legacy_position(preset),
                    "transition": legacy_transition(_tr),
                    "scale": 0.75,
                })
                continue
            if pose == 4:
                # Posa 4 indica verso destra -> SEMPRE a sinistra.
                preset = "layout_split_left"
            elif pose == 5:
                preset = "layout_split_left" if split_flip % 2 == 0 else "layout_split_right"
                split_flip += 1
            else:
                preset = _preset_for_pose(pose, i)
            # Transizioni varie: center slide_up/zoom_in alternati, split
            # direzionali, fade morbida ogni 3 chunk (ritmo coerente).
            try:
                _s = preset_side(preset)
            except Exception:
                _s = "center"
            if _s == "center":
                transition_in = "zoom_in" if (i % 4 == 2) else preset_default_transition(preset)
            else:
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
    "Posa 4 (indicare verso la SUA sinistra = verso DESTRA dello spettatore): punti chiave, dati, numeri, keyword importanti.\n"
    "Posa 5 (mano al mento): domande, dubbi, problemi, riflessioni."
)

_LAYOUT_RULES = (
    "Layout disponibili (niente figura intera: mezzo busto/mezza figura, gambe fuori campo; "
    "personaggio e testo NON devono mai sovrapporsi):\n"
    "- layout_center_standard: mezza figura centrata in basso (125% larghezza), testo in ALTO (y 150-900).\n"
    "- layout_center_punch_in: PRIMO PIANO busto/testa (170% larghezza), testo nel terzo superiore con sfondo ad alto contrasto.\n"
    "- layout_split_left: personaggio a SINISTRA (130%, spalla fuori campo), testo a DESTRA (x 640-1000).\n"
    "- layout_split_right: personaggio a DESTRA (130%), testo a SINISTRA (x 80-420).\n"
    "REGOLA OBBLIGATORIA: con la Posa 4 (indica verso DESTRA dello spettatore) usa SEMPRE layout_split_left "
    "(personaggio a SINISTRA, testo a DESTRA): solo cosi' indica VERSO il testo. MAI layout_split_right "
    "o center con posa 4 (indicherebbe fuori campo, lontano dal testo).\n"
    "Con la Posa 5 (pensare) prediligi i layout laterali (split_left/split_right).\n"
    "Posa 2 (braccia aperte) SOLO in layout_center_standard (troppo larga per gli split).\n"
    "PUNCH-IN (zoom fluido di enfasi, NON jump-cut secco: il render lo anima in 0.6s): metti punch_in=true "
    "SOLO per frasi chiave/rivelazioni (picco hook), MAX 1-2 volte in TUTTO il video, MAI in CTA."
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
    import os as _os
    if _os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        if on_attempt is not None:
            try:
                on_attempt(0, 0, False, "PIPELINE_FAST=1: piano character deterministico")
            except Exception:
                pass
        return _fallback_plan(chunks)

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
            "SOLO sull'ultimo chunk hook (picco di attenzione, zoom fluido in render).\n"
            "- Chunk [CORPO]: RITMO CALMO. Cambia posa/lato ogni 1-2 chunk (MAI "
            "stessa posa o stesso lato per piu' di 2 chunk consecutivi). "
            "Alterna centro/sinistra/destra (es. centro -> split_left -> center, "
            "ma posa 4 SEMPRE split_left). Domande → posa 5 split, "
            "dati/numeri → posa 4 split_left OBBLIGATORIO, "
            "soluzioni/enfasi → posa 3 center, resto alterna con pertinenza.\n"
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
        "- RITMO CALMO ANTI-STATICITA': cambia posa/lato ogni 1-2 chunk; evita "
        "stessa posa due volte di fila e non restare troppo sullo stesso lato. "
        "Usa le pose 1-5 con pertinenza semantica e alterna i lati con passaggi "
        "dal centro (stabile, non frenetico).\n"
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
    # max_tokens dinamico: ~60 token/chunk + margine (evita 4096 fissi su video corti).
    _dyn_max = max(512, min(4096, 256 + n * 64))
    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=_dyn_max,
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
    if not isinstance(chunk, dict):
        return None
    # Presenza discontinua: visible=False => nessun personaggio (testo centrale).
    try:
        _ch = chunk.get("character") if isinstance(chunk.get("character"), dict) else None
        if _ch is not None and not bool(_ch.get("visible", True)):
            return None
        if chunk.get("char_visible") is False:
            return None
        if chunk.get("guard_hidden") is True:
            return None
    except Exception:
        pass
    if chunk.get("pose") is None:
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
    """Arricchisce i chunk con i metadati character + stabilizzazione macro-blocchi.

    Copia pose/layout/punch_in (+ alias) preservando i campi macro-blocco
    (block_id/char_event/char_visible/character) quando presenti nel piano.
    Alla fine ri-applica la stabilizzazione sugli arricchiti (idempotente):
    posa/lato unici per blocco, eventi ENTRY/SUSTAIN/EXIT/NONE, hidden senza
    posa. Se `plan` e' None/vuoto o la lunghezza non coincide, i chunk restano
    invariati. Non solleva mai.
    """
    if not plan or len(plan) != len(chunks):
        return chunks
    enriched: list[dict] = []
    for i, chunk in enumerate(chunks):
        try:
            entry = plan[i] if isinstance(plan[i], dict) else {}
            norm = _normalize_entry(entry, i, str((chunk or {}).get("text", "")))
            merged = {**chunk, **norm}
            # Preserva i campi macro-blocco dal piano stabilizzato.
            try:
                for _k in ("block_id", "char_event", "char_visible", "character"):
                    if _k in entry and _k not in (None,):
                        merged[_k] = entry[_k]
                # Hidden: il piano ha pose=None => applica hidden anche qui.
                if entry.get("pose") is None or (
                    isinstance(entry.get("character"), dict)
                    and not bool(entry["character"].get("visible", True))
                ):
                    merged["pose"] = None
                    if isinstance(entry.get("character"), dict):
                        merged["character"] = dict(entry["character"])
                    else:
                        merged["character"] = {
                            "visible": False, "pose": None, "pose_id": "",
                            "side": "CENTER", "event": "NONE",
                            "block_id": int(entry.get("block_id", 0) or 0),
                        }
                    merged["char_event"] = "NONE"
                    merged["char_visible"] = False
                    merged["layout"] = "layout_center_standard"
                    merged["layout_preset"] = "layout_center_standard"
            except Exception:
                pass
            enriched.append(merged)
        except (TypeError, ValueError, AttributeError):
            enriched.append({**chunk})
    # Ri-applica la stabilizzazione sugli arricchiti (garantisce posa unica
    # per blocco anche se il piano pre-stabilizzato e' stato ri-normalizzato).
    try:
        stabilized_plan = _apply_macro_block_stabilization(
            [
                {
                    "chunk_index": i,
                    "pose": (c.get("pose") if isinstance(c, dict) else None),
                    "layout": (c.get("layout") if isinstance(c, dict) else "layout_center_standard"),
                    "layout_preset": (c.get("layout_preset") if isinstance(c, dict) else "layout_center_standard"),
                    "punch_in": bool((c or {}).get("punch_in", False)),
                    "transition_in": (c.get("transition_in") if isinstance(c, dict) else "fade"),
                    "position": (c.get("position") if isinstance(c, dict) else "bottom_center"),
                    "transition": (c.get("transition") if isinstance(c, dict) else "fade"),
                    "scale": (c.get("scale") if isinstance(c, dict) else 0.75),
                    # Preserva eventuale character gia' presente per non perdere
                    # visible/block_id quando la posa e' ancora valida.
                    "character": ((c or {}).get("character") if isinstance(c, dict) else None),
                    "block_id": ((c or {}).get("block_id") if isinstance(c, dict) else None),
                    "char_event": ((c or {}).get("char_event") if isinstance(c, dict) else None),
                    "char_visible": ((c or {}).get("char_visible") if isinstance(c, dict) else None),
                }
                for i, c in enumerate(enriched)
            ],
            enriched,
        )
        out: list[dict] = []
        for i, c in enumerate(enriched):
            try:
                st = stabilized_plan[i] if i < len(stabilized_plan) and isinstance(stabilized_plan[i], dict) else {}
                merged2 = dict(c)
                for _k in (
                    "pose", "layout", "layout_preset", "punch_in",
                    "transition_in", "position", "transition", "scale",
                    "block_id", "char_event", "char_visible", "character",
                ):
                    if _k in st:
                        merged2[_k] = st[_k]
                out.append(merged2)
            except Exception:
                out.append(c)
        return out
    except Exception:
        return enriched
