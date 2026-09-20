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
# Geometria soggetto (FASE 1/6): nessun ciclo di import (quel modulo importa
# solo config + layout_presets).
from core.character_geometry import get_subject_geometry, validate_pose_layout_pair
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


def _is_dense_text(text: str = "", n_words: int | None = None) -> bool:
    """Vero se il testo e' denso (REELS-FIX v5): >6 parole o >40 caratteri.

    Testi densi VIETANO center_standard (colonna split libera per il testo).
    Mai solleva.
    """
    try:
        if n_words is None:
            n_words = len(str(text or "").split())
        else:
            n_words = int(n_words)
    except Exception:
        n_words = 0
    try:
        n_chars = len(str(text or "").strip())
    except Exception:
        n_chars = 0
    try:
        return int(n_words) > 6 or int(n_chars) > 40
    except Exception:
        return False


def _preset_for_pose(pose: int, alternate: int = 0, chunk_text: str = "") -> str:
    """Preset deterministico (fallback e normalizzazione, fix posa larga).

    Posa 4 -> split alternati; posa 5 -> split; posa 2 (braccia aperte,
    676px misurati, quasi 2x le altre) -> SEMPRE center (in split coprirebbe
    la colonna testo); testi densi -> split alternati; posa 3 breve ->
    center; altre -> rotazione.
    """
    try:
        dense = _is_dense_text(chunk_text)
    except Exception:
        dense = False
    if pose == 4:
        return "layout_split_right" if alternate % 2 == 0 else "layout_split_left"
    if pose == 5:
        return "layout_split_left" if alternate % 2 == 0 else "layout_split_right"
    if pose == 2:
        return "layout_center_standard"
    if dense:
        # Testo lungo: colonna libera, alterna L/R per ritmo visivo.
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


# --- Anti-staticità v2: alternative semanticamente vicine per rotazione ---
# Quando una run identica supera 2 chunk, si ruota su alternative dello
# stesso registro (mai salti assurdi: assertivo<->aperto, domande<->aperto).
_POSE_ALTERNATIVES: dict[int, list[int]] = {
    1: [2, 4],
    2: [4, 1],
    3: [2, 1],
    4: [2, 1],
    5: [2, 4],
}

# Max chunk consecutivi con stessa identità (posa+layout) prima del ricambio.
# Calmi (anti-flicker): 3 body/hook (~4-6s con chunk da 2-3 parole), CTA +1.
# Override via config CHARACTER_MAX_CONSECUTIVE (default 3).
try:
    from config import CHARACTER_MAX_CONSECUTIVE as _CFG_MAX_CONSEC
    ANTI_STATIC_MAX_BODY = max(2, int(_CFG_MAX_CONSEC))
except Exception:
    ANTI_STATIC_MAX_BODY = 3
ANTI_STATIC_MAX_CTA = ANTI_STATIC_MAX_BODY + 1


def _alternate_split(preset: str, flip: int = 0) -> str:
    """Alterna split_left <-> split_right (ritmo visivo senza salti)."""
    if preset == "layout_split_left":
        return "layout_split_right"
    if preset == "layout_split_right":
        return "layout_split_left"
    # Da centro: alterna lati per dare movimento.
    return "layout_split_left" if flip % 2 == 0 else "layout_split_right"


def _dynamic_successor(pose: int, layout: str, index: int) -> tuple[int, str]:
    """Successore dinamico CALMO (B.2): preferisce cambio posa SENZA spostamento.

    Stessa scena = jump-cut netto (posa diversa, stesso layout): nessun
    slide_down/slide_up, il personaggio resta fisso e cambia espressione.
    Il cambio di layout (slide laterale) avviene solo 1 volta su 3 rotazioni
    o ai confini di beat. Rispetta: posa 4/5 sempre in split.
    """
    alts = _POSE_ALTERNATIVES.get(int(pose), [1, 2, 4])
    new_pose = alts[index % len(alts)]
    if new_pose == 2:
        # Posa larga: sempre center (mai split).
        return int(new_pose), "layout_center_standard"
    if new_pose in (4, 5):
        # Posa che indica/pensa: richiede split (scivola verso il lato).
        new_layout = _alternate_split(layout, index)
        if new_layout not in ("layout_split_left", "layout_split_right"):
            new_layout = "layout_split_left" if index % 2 == 0 else "layout_split_right"
    elif index % 3 == 0:
        # 1 rotazione su 3: cambio di lato fluido (slide_side).
        if layout in ("layout_split_left", "layout_split_right"):
            new_layout = _alternate_split(layout, index)
        else:
            new_layout = "layout_split_left" if index % 2 == 0 else "layout_split_right"
    else:
        # 2 rotazioni su 3: STESSO layout, solo posa (jump-cut, no movimento).
        new_layout = layout
    return int(new_pose), str(new_layout)


def _identity_of(entry: dict) -> tuple:
    try:
        return (int(entry.get("pose", 0)), str(entry.get("layout", "")))
    except Exception:
        return (0, "")


def enforce_anti_static_plan(plan: list[dict], chunks: list[dict] | None = None) -> list[dict]:
    """Regola dell'Anti-Staticità v2 (calma): mai stessa (posa+layout) oltre il limite.

    - body/hook: max ANTI_STATIC_MAX_BODY (default 3, ~4-6s); CTA: +1.
    - Al superamento: rotazione su posa alternativa vicina + lato split
      alternato + transizione direzionale coerente (slide corta, mai full-travel
      sui cambi: niente salti da bordo a bordo).
    - I punch_in esistenti sono preservati (non aggiunti qui: cap dedicato).
    - Non solleva mai; ritorna lo stesso piano (modificato in place).
    """
    try:
        if not plan or len(plan) < 3:
            return plan
    except Exception:
        return plan
    try:
        for i in range(1, len(plan)):
            try:
                prev, cur = plan[i - 1], plan[i]
                if not isinstance(prev, dict) or not isinstance(cur, dict):
                    continue
                # Lunghezza run identica fino a i (guarda indietro).
                run = 1
                for k in range(i - 1, -1, -1):
                    try:
                        if _identity_of(plan[k]) == _identity_of(plan[k + 1]):
                            run += 1
                        else:
                            break
                    except Exception:
                        break
                    if run > 4:
                        break
                # Limite per atto (CTA tollerante).
                try:
                    role = str(((chunks[i] or {}) if chunks else {}).get("narrative_role", "body"))
                except Exception:
                    role = "body"
                limit = ANTI_STATIC_MAX_CTA if role == "cta" else ANTI_STATIC_MAX_BODY
                # run = n. consecutivi identici incluso il corrente.
                # Consentiti fino a `limit` (es. 3 identici ok), cambio dal successiva.
                if _identity_of(prev) != _identity_of(cur):
                    continue
                if run <= limit:
                    continue
                # Forza ricambio dinamico sul corrente.
                new_pose, new_layout = _dynamic_successor(
                    int(cur.get("pose", 1)), str(cur.get("layout", "layout_center_standard")), i)
                cur["pose"] = new_pose
                cur["layout"] = new_layout
                cur["layout_preset"] = new_layout
                try:
                    cur["transition_in"] = preset_default_transition(new_layout)
                    cur["position"] = legacy_position(new_layout)
                    cur["transition"] = legacy_transition(cur["transition_in"])
                except Exception:
                    pass
            except Exception:
                continue
    except Exception:
        pass
    return plan


def _is_narrative_boundary(chunks: list[dict] | None, index: int) -> bool:
    """Vero se tra chunk[index-1] e chunk[index] c'è un confine forte.

    Confini forti (unici punti dove uscita/ri-entrata è consentita):
    hook->corpo, corpo->CTA, oppure comparsa/scomparsa personaggio.
    Altrove il personaggio resta in scena (jump-cut o slide corta).
    """
    try:
        if not chunks or index <= 0 or index >= len(chunks):
            return False
        prev_role = str(((chunks[index - 1] or {}).get("narrative_role", "")))
        cur_role = str(((chunks[index] or {}).get("narrative_role", "")))
        if not prev_role or not cur_role:
            return False  # senza ruoli: nessun confine rilevabile
        return prev_role != cur_role
    except Exception:
        return False


def enforce_min_dwell_time(plan: list[dict], chunks: list[dict] | None = None,
                           min_seconds: float = 3.0) -> list[dict]:
    """Minimum Dwell Time (B.2): ogni permanenza dura almeno `min_seconds`.

    Elimina l'effetto stroboscopico: nessuna apparizione a ritmo di singola
    parola/chunk breve. Le run identiche più corte del minimo vengono fuse
    con la run precedente (estensione: il personaggio resta, non lampeggia),
    SALVO ai confini narrativi forti dove il cambio è sempre libero.
    Non solleva mai; ritorna lo stesso piano (modificato in place).
    """
    try:
        if not plan or not chunks or len(plan) != len(chunks) or len(plan) < 2:
            return plan
    except Exception:
        return plan
    try:
        try:
            from config import CHARACTER_MIN_DWELL_SECONDS as _CFG_DWELL
            limit_s = float(min_seconds if min_seconds else _CFG_DWELL)
        except Exception:
            limit_s = float(min_seconds or 3.0)
        if limit_s <= 0:
            return plan
    except Exception:
        return plan
    try:
        # Identifica run identiche [start, end] con durata in secondi.
        n = len(plan)
        run_start = 0
        for i in range(1, n + 1):
            boundary = (i == n) or (_identity_of(plan[i]) != _identity_of(plan[run_start]))
            if not boundary:
                continue
            # Run [run_start, i): calcola durata da chunk start/end.
            try:
                rs = float((chunks[run_start] or {}).get("start", 0.0))
                ce = float((chunks[i - 1] or {}).get("end", rs))
                dur = max(0.0, ce - rs)
            except Exception:
                dur = 99.0
            if dur < limit_s and run_start > 0 and (i - run_start) >= 1:
                # Run troppo breve e non è la prima: fonde col precedente,
                # salvo confine narrativo forte al suo inizio (cambio libero).
                if not _is_narrative_boundary(chunks, run_start):
                    try:
                        ref = plan[run_start - 1]
                        for j in range(run_start, i):
                            plan[j]["pose"] = ref.get("pose", 2)
                            plan[j]["layout"] = ref.get("layout", "layout_center_standard")
                            plan[j]["layout_preset"] = plan[j]["layout"]
                            plan[j]["position"] = legacy_position(plan[j]["layout"])
                            plan[j]["punch_in"] = False
                            try:
                                plan[j]["transition_in"] = preset_default_transition(plan[j]["layout"])
                                plan[j]["transition"] = legacy_transition(plan[j]["transition_in"])
                            except Exception:
                                pass
                    except Exception:
                        pass
            run_start = i
    except Exception:
        pass
    return plan


def _apply_narrative_locks(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Blocchi deterministici REELS-FIX v5 (pacing + testi lunghi in split).

    - HOOK breve: posa 1 center; HOOK denso (>6 parole/>40 char): split
      alternati L/R (mai center con blocco alto).
    - CORPO: rotazione ogni 3 chunk; densi sempre split alternati per beat.
    - CTA breve: posa 3/2 center; CTA densa: split fisso (stesso lato).
    Non solleva mai; senza ruoli restituisce il piano invariato.
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
        # --- HOOK REELS-FIX v5: breve=center, denso=split alternato ---
        if hook_idx:
            _hflip = 0
            for k, j in enumerate(hook_idx):
                try:
                    try:
                        _htxt = str((chunks[j] or {}).get("text", ""))
                        _hdense = _is_dense_text(_htxt)
                    except Exception:
                        _hdense, _htxt = False, ""
                    plan[j]["pose"] = 1
                    if _hdense:
                        _hlay = "layout_split_left" if _hflip % 2 == 0 else "layout_split_right"
                        _hflip += 1
                    else:
                        _hlay = "layout_center_standard"
                    plan[j]["layout"] = _hlay
                    plan[j]["layout_preset"] = _hlay
                    plan[j]["scale"] = 0.75
                    plan[j]["position"] = legacy_position(_hlay)
                    if k == 0:
                        plan[j]["transition_in"] = "slide_up" if _hlay == "layout_center_standard" else preset_default_transition(_hlay)
                    else:
                        # Chunk hook successivi: nessun ri-ingresso (resta in scena).
                        plan[j]["transition_in"] = "none"
                    plan[j]["transition"] = legacy_transition(plan[j]["transition_in"])
                    plan[j]["punch_in"] = (j == hook_idx[-1] and len(hook_idx) > 1 and not _hdense)
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
            # v2 dinamico: coerenza di registro per beat ma variazione ogni 2
            # chunk (mai sticker oltre ~3-4s). Coppie: [0,1] identici, [2,3]
            # variati su alternativa vicina + lato split alternato.
            try:
                ref = plan[beat[0]]
                ref_pose = ref.get("pose", 2)
                ref_layout = ref.get("layout", "layout_center_standard")
                ref_punch = bool(ref.get("punch_in", False))
                ref_scale = ref.get("scale", 0.75)
            except Exception:
                continue
            for pos_in_beat, j in enumerate(beat[1:], start=1):
                try:
                    # Rotazione calma ogni 3 chunk (pos 3,6...): permanenza più
                    # lunga, niente cambi frenetici dentro lo stesso pensiero.
                    if pos_in_beat % ANTI_STATIC_MAX_BODY == 0:
                        dyn_pose, dyn_layout = _dynamic_successor(
                            int(ref_pose), str(ref_layout), j)
                        plan[j]["pose"] = dyn_pose
                        plan[j]["layout"] = dyn_layout
                        plan[j]["layout_preset"] = dyn_layout
                        plan[j]["position"] = legacy_position(dyn_layout)
                        try:
                            plan[j]["transition_in"] = preset_default_transition(dyn_layout)
                            plan[j]["transition"] = legacy_transition(plan[j]["transition_in"])
                        except Exception:
                            pass
                        plan[j]["punch_in"] = False  # variazione, non stacco
                        plan[j]["scale"] = ref_scale
                    else:
                        plan[j]["pose"] = ref_pose
                        # Posa 2 larga mai in split anche per coerenza beat.
                        if int(ref_pose) == 2 and str(ref_layout) in (
                                "layout_split_left", "layout_split_right"):
                            plan[j]["layout"] = "layout_center_standard"
                            plan[j]["layout_preset"] = "layout_center_standard"
                            plan[j]["position"] = legacy_position(
                                "layout_center_standard")
                        else:
                            plan[j]["layout"] = ref_layout
                            plan[j]["layout_preset"] = ref_layout
                            plan[j]["position"] = legacy_position(ref_layout)
                        plan[j]["punch_in"] = ref_punch
                        plan[j]["scale"] = ref_scale
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
            # CTA densa: split fisso, MA posa 2 (larga) sempre center.
            try:
                _cta_txt = " ".join(str((chunks[j] or {}).get("text", "")) for j in cta_idx)
                _cta_dense = _is_dense_text(_cta_txt, sum(len(str((chunks[j] or {}).get("text", "")).split()) for j in cta_idx))
            except Exception:
                _cta_dense = False
            if pose == 2:
                _cta_lay = "layout_center_standard"
            else:
                _cta_lay = "layout_split_right" if _cta_dense else "layout_center_standard"
            for k, j in enumerate(cta_idx):
                try:
                    plan[j]["pose"] = pose
                    plan[j]["layout"] = _cta_lay
                    plan[j]["layout_preset"] = _cta_lay
                    plan[j]["punch_in"] = False
                    plan[j]["scale"] = 0.75
                    plan[j]["position"] = legacy_position(_cta_lay)
                    # CTA: entra e RESTA fisso fino alla fine.
                    plan[j]["transition_in"] = "fade" if k == 0 else "none"
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


def preload_character_assets(poses: tuple[int, ...] | list[int] | None = None) -> int:
    """Warmup RAM: precarica gli asset originali puliti per le pose richieste.

    Da chiamare UNA volta a inizio pipeline (prima del rendering) per
    azzerare I/O disco in loop frame. Ritorna n. pose precaricate.
    Mai solleva (asset mancanti saltati con warning).
    """
    if poses is None:
        try:
            poses = list(range(1, int(CHARACTER_POSE_COUNT) + 1))
        except Exception:
            poses = [1, 2, 3, 4, 5]
    ok = 0
    for p in poses:
        try:
            load_character_original(int(p))
            ok += 1
        except Exception as e:
            try:
                print(f"[character] warning: posa {p} non precaricata ({e})")
            except Exception:
                pass
    # Warmup geometria (FASE 1): misura il soggetto una sola volta per asset
    # (bbox visibile, centro visivo, faccia) e tienila in cache RAM.
    try:
        for p in poses:
            try:
                get_subject_geometry(int(p))
            except Exception as e:
                try:
                    print(f"[character] warning: geometria posa {p} saltata ({e})")
                except Exception:
                    pass
    except Exception:
        pass
    return ok


def enforce_pose_layout_coherence(plan: list[dict]) -> list[dict]:
    """Garanzia finale posa/layout (mai solleva, in place).

    - Posa 2 (larga 676px) SEMPRE center (in split coprirebbe il testo).
    - Posa 4/5 SEMPRE split (indicano/pensano verso il testo).
    - Pass di validazione geometrica (FASE 6): la coppia posa/layout viene
      ricontrollata sulla larghezza reale del soggetto (pose larghe/braccio
      teso solo al centro); se non ammessa usa il layout ammesso piu' vicino
      per direzione e logga "layout corretto" (vedi character_geometry).
    Chiamata per ULTIMA in finalize: nessun lock a valle puo' reintrodurre
    combo vietate (era il buco che metteva la posa 2 a destra tagliata).
    """
    try:
        _flip = 0
        for i, entry in enumerate(plan or []):
            try:
                if not isinstance(entry, dict):
                    continue
                pose = int(entry.get("pose", 1))
                lay = str(entry.get("layout", "layout_center_standard"))
            except Exception:
                continue
            try:
                if pose == 2 and lay in ("layout_split_left", "layout_split_right",
                                         "layout_center_punch_in"):
                    entry["layout"] = "layout_center_standard"
                    entry["layout_preset"] = "layout_center_standard"
                    try:
                        entry["position"] = legacy_position("layout_center_standard")
                        entry["transition_in"] = preset_default_transition(
                            "layout_center_standard")
                        entry["transition"] = legacy_transition(entry["transition_in"])
                    except Exception:
                        pass
                elif pose in (4, 5) and lay not in ("layout_split_left",
                                                     "layout_split_right"):
                    _nl = "layout_split_left" if _flip % 2 == 0 else "layout_split_right"
                    _flip += 1
                    entry["layout"] = _nl
                    entry["layout_preset"] = _nl
                    try:
                        entry["position"] = legacy_position(_nl)
                        entry["transition_in"] = preset_default_transition(_nl)
                        entry["transition"] = legacy_transition(entry["transition_in"])
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass
    # Pass geometrico FASE 6 sul layout risultante (anche legacy): valida la
    # coppia sulla larghezza reale del soggetto e corregge al vicino per
    # direzione con log "layout corretto". Mantiene le regole esistenti
    # (MAX_CONSECUTIVE, dwell, full-travel gestiti a monte: qui solo coerenza).
    try:
        for entry in plan or []:
            try:
                if not isinstance(entry, dict):
                    continue
                pose = int(entry.get("pose", 1))
                lay = str(entry.get("layout", entry.get("layout_preset",
                                                        "layout_center_standard")))
            except Exception:
                continue
            try:
                fixed, changed = validate_pose_layout_pair(pose, lay)
                if changed and isinstance(fixed, str) and fixed != lay:
                    entry["layout"] = fixed
                    entry["layout_preset"] = fixed
                    try:
                        entry["position"] = legacy_position(fixed)
                        entry["transition_in"] = preset_default_transition(fixed)
                        entry["transition"] = legacy_transition(
                            entry["transition_in"])
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass
    return plan


def _finalize_character_plan(plan: list[dict], chunks: list[dict]) -> list[dict]:
    """Lock narrativi + cap per atto + anti-statico + dwell + coerenza pose."""
    try:
        if any(_chunk_role(c) for c in (chunks or [])):
            locked = _apply_narrative_locks(plan, chunks)
            capped = _cap_punch_ins_narrative(locked, chunks)
            calm = enforce_anti_static_plan(capped, chunks)
            try:
                from config import CHARACTER_MIN_DWELL_SECONDS as _DWELL
                dwell = float(_DWELL)
            except Exception:
                dwell = 3.0
            return enforce_pose_layout_coherence(
                enforce_min_dwell_time(calm, chunks, dwell))
    except Exception:
        pass
    try:
        calm = enforce_anti_static_plan(_cap_punch_ins(plan), chunks)
        try:
            from config import CHARACTER_MIN_DWELL_SECONDS as _DWELL2
            dwell2 = float(_DWELL2)
        except Exception:
            dwell2 = 3.0
        # Dwell anche senza ruoli narrativi (solo se i chunk hanno timing).
        try:
            has_timing = any(isinstance(c, dict) and "start" in c and "end" in c
                              for c in (chunks or []))
        except Exception:
            has_timing = False
        if has_timing:
            return enforce_pose_layout_coherence(
                enforce_min_dwell_time(calm, chunks, dwell2))
        return enforce_pose_layout_coherence(calm)
    except Exception:
        return enforce_pose_layout_coherence(_cap_punch_ins(plan))


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

    # Layout REELS-FIX v5: testi densi forzano split (mai center), pose 4/5
    # sempre split anche se l'LLM sbaglia.
    try:
        _dense_here = _is_dense_text(chunk_text)
    except Exception:
        _dense_here = False
    layout_raw = raw.get("layout", raw.get("layout_preset"))
    if isinstance(layout_raw, str) and (
        layout_raw in VALID_LAYOUT_PRESETS
        or layout_raw in ("bottom_center", "bottom_left", "bottom_right", "side_left", "side_right")
        or layout_raw in ("layout_bottom_focus", "layout_closeup_center")
    ):
        preset = normalize_preset(layout_raw, _preset_for_pose(pose, chunk_index, chunk_text))
    elif raw.get("position") is not None:
        preset = normalize_preset(raw.get("position"), _preset_for_pose(pose, chunk_index, chunk_text))
    else:
        preset = _preset_for_pose(pose, chunk_index, chunk_text)
    if pose == 4 and preset not in ("layout_split_left", "layout_split_right"):
        preset = _preset_for_pose(pose, chunk_index, chunk_text)
    if pose == 5 and preset not in ("layout_split_left", "layout_split_right"):
        preset = _preset_for_pose(pose, chunk_index, chunk_text)
    if pose == 2 and preset not in ("layout_center_standard", "layout_center_punch_in"):
        # Posa 2 larga (676px): solo center, mai split (coprirebbe il testo).
        preset = "layout_center_standard"
    if _dense_here and preset in ("layout_center_standard", "layout_center_punch_in") and pose not in (2, 3):
        # Fallback automatico Center->Split per testi lunghi (catena v5).
        try:
            from core.layout_presets import fallback_preset_for_overflow as _fb
            preset = _fb(preset, len(str(chunk_text or "")),
                         len(str(chunk_text or "").split()))
        except Exception:
            preset = _preset_for_pose(pose, chunk_index, chunk_text)

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
    """Piano deterministico REELS-FIX v5 (ritmo Reels, testi lunghi in split).

    - Primo chunk breve: posa 1 center; se denso (>6 parole/>40 char): split.
    - Successivi: "?" -> posa 5 split, "!" -> posa 3 + punch (no CTA),
      altrimenti ciclo 1->2->4; densi sempre split alternati L/R.
    - Lock narrativi a valle (vedi _apply_narrative_locks) rispettano i densi.
    """
    cycle_poses = [1, 2, 4]
    plan: list[dict] = []
    cycle_i = 0
    split_flip = 0
    for i, chunk in enumerate(chunks):
        text = str((chunk or {}).get("text", ""))
        punch_in = False
        is_cta = _chunk_role(chunk) == "cta"
        try:
            dense = _is_dense_text(text)
        except Exception:
            dense = False
        if i == 0:
            if dense:
                pose = 1
                preset = "layout_split_right" if split_flip % 2 == 0 else "layout_split_left"
                split_flip += 1
                transition_in = preset_default_transition(preset)
            else:
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
            elif pose == 2:
                # Posa larga: sempre center (mai split).
                preset = "layout_center_standard"
            elif dense:
                # Testo lungo: forza split alternato, mai center.
                preset = "layout_split_left" if split_flip % 2 == 0 else "layout_split_right"
                split_flip += 1
                punch_in = False
            else:
                preset = _preset_for_pose(pose, i, text)
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
    "Layout disponibili v8 (presenza piena come commit di riferimento, "
    "personaggio e testo MAI sovrapposti, gutter 80px):\n"
    "- layout_center_standard: figura naturale centrata (125%, top Y~500, testa-busto-fianchi), testo SOLO fascia alta Y[140,490] X[90,990]. Obbligatorio per posa 2 (larga); vietato se testo denso con altre pose.\n"
    "- layout_center_punch_in: PRIMO PIANO (170%, zoom 1.15x), testo fascia alta Y[140,620] con pill.\n"
    "- layout_split_left: personaggio a SINISTRA (130% presenza piena, bbox visibile dentro [20,1060], volto SEMPRE integro), testo a DESTRA Y[320,1250] dinamico fino a 40px dal personaggio. MAI con posa 2.\n"
    "- layout_split_right: personaggio a DESTRA (130% presenza piena, bbox visibile dentro [20,1060], volto SEMPRE integro), testo a SINISTRA Y[320,1250] dinamico fino a 40px dal personaggio. MAI con posa 2.\n"
    "REGOLA POSA 2 (braccia aperte, larghissima): usa SEMPRE layout_center_standard.\n"
    "REGOLA DENSITA': se il chunk ha >6 parole o >40 caratteri FORZA split_left/split_right (alterna i lati ogni 2-3 chunk), MAI center.\n"
    "REGOLA OBBLIGATORIA: con la Posa 4 (indicare) usa SEMPRE split, scegliendo il lato in modo che indichi verso il testo.\n"
    "Con la Posa 5 (pensare) prediligi split.\n"
    "PUNCH-IN (jump-cut 1.15x): punch_in=true SOLO per frasi chiave, MAX 1-2 volte in TUTTO il video."
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
    # Contesto compatto: indice + testo + conteggi (guida split su lunghi).
    lines = []
    for i, ch in enumerate(chunks):
        text = str((ch or {}).get("text", "")).strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "..."
        try:
            _nw = len(str((ch or {}).get("text", "")).split())
            _nc = len(str((ch or {}).get("text", "")).strip())
        except Exception:
            _nw, _nc = 0, 0
        _len_tag = f"({_nw}w,{_nc}ch)"
        if has_narrative and isinstance(ch, dict):
            role = str(ch.get("narrative_role", "body"))
            tag = {"hook": "HOOK", "body": "CORPO", "cta": "CTA"}.get(role, "CORPO")
            lines.append(f"{i} [{tag}]{_len_tag}: {text}")
        else:
            lines.append(f"{i} {_len_tag}: {text}")
    chunk_block = "\n".join(lines)
    script_snippet = (script_text or "").strip().replace("\n", " ")
    if len(script_snippet) > 1500:
        script_snippet = script_snippet[:1500] + "..."

    narrative_rules = ""
    if has_narrative:
        narrative_rules = (
            "\nREGOLE NARRATIVE REELS-FIX v5 (hook/corpo/CTA + densita'):\n"
            "- Chunk [HOOK] breve (<=6w,<=40ch): posa 1 center; HOOK denso: posa 1 split (alterna L/R); punch_in=true "
            "SOLO sull'ultimo hook breve.\n"
            "- Chunk [CORPO]: DINAMISMO CALMO ogni 3 chunk; testi densi SEMPRE split alternati L/R ogni 2-3 chunk "
            "(lato opposto libero per il testo). Domande → posa 5 split, dati → posa 4 split.\n"
            "- Chunk [CTA] breve: posa 3 center; CTA densa: posa 3 split fisso; punch_in=false SEMPRE.\n"
        )
    system = (
        "Sei un regista che assegna un personaggio 2D ai sottotitoli di un video breve. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Analizza il tono di ogni chunk e assegna personaggio/layout/punch-in.\n\n"
        "REGOLE POSE:\n" + _POSE_RULES + "\n\n"
        "REGOLE LAYOUT E REGIA:\n" + _LAYOUT_RULES + "\n"
        "- REGOLA ANTI-STATICITÀ CALMA: mantieni stessa posa+layout per 2-3 chunk "
        "di fila (~4-6s), poi ruota con transizione morbida. MAI cambiare a ogni "
        "chunk: la frenesia rovina il video. Ritmo 10/10 = calmo ma vivo.\n"
        "- Alterna i lati degli split solo ai confini di frase/beat, non a ogni chunk.\n"
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


# ---------------------------------------------------------------------------
# Timeline Manager v3 — Continuity Engine (spec §1+§2)
# ---------------------------------------------------------------------------
# La causa dei "flash neri" e' il render per-chunk isolato: ogni chunk ricrea
# la clip del character (fade/entry da zero) e il video_builder sovrappone
# N micro-clip con `between(t,start,end)`, lasciando gap tra end[N] e
# start[N+1] dove nessun overlay e' attivo (solo sfondo -> blink nero).
# Il Timeline Manager raggruppa chunk consecutivi con stessa identita'
# (posa+layout+punch) in SEGMENTI CONTINUI: il character vive su una traccia
# unica da segment.start a segment.end senza fade-out/in, reset alpha o
# riposizionamento ai confini interni (es. 0.0-2.0 + 2.0-4.5 -> 0.0-4.5).

TIMELINE_MIN_DWELL_SECONDS: float = 3.0
TIMELINE_SLIDE_X_DURATION: float = 0.30
# Gap oltre il quale uno stacco visivo totale e' reale (slide_up consentito).
TIMELINE_GAP_THRESHOLD: float = 0.40


def timeline_identity_of(chunk: dict | None) -> tuple | None:
    """Identita' visiva (posa, layout, punch) o None se senza character."""
    try:
        if not isinstance(chunk, dict) or chunk.get("pose") is None:
            return None
        info = resolve_chunk_layout(chunk)
        if info is None:
            return None
        zone = info.get("layout") if info.get("use_preset") else info.get("position")
        return (int(info.get("pose")), str(zone), bool(info.get("punch_in", False)))
    except Exception:
        return None


def build_continuous_timeline(chunks: list[dict]) -> list[dict]:
    """Raggruppa chunk arricchiti in segmenti continui per identita' (mai solleva).

    Ogni segmento: {"pose","layout","punch_in","use_preset","start","end",
    "chunk_indices": [...], "entry": "slide_up|slide_x|jump",
    "exit": "hold|slide_down|fade_out", "side_from"/"side_to": ...}.
    Chunk senza character -> segmento `{"pose": None, "gap": True}` (testo
    fullscreen: il character resta nascosto, nessun blink).
    Confini interni allo stesso segmento NON devono mai generare fade o
    riposizionamento (canale alpha persistente, spec §1).
    """
    try:
        if not chunks:
            return []
    except Exception:
        return []
    segments: list[dict] = []
    try:
        for i, ch in enumerate(chunks):
            try:
                start = float((ch or {}).get("start", 0.0))
                end = float((ch or {}).get("end", start))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            ident = timeline_identity_of(ch)
            try:
                info = resolve_chunk_layout(ch) if ident is not None else None
            except Exception:
                info = None
            if ident is None:
                # Gap fullscreen: chiude il segmento precedente.
                segments.append({
                    "pose": None, "layout": None, "punch_in": False,
                    "use_preset": False, "start": start, "end": end,
                    "chunk_indices": [i], "gap": True,
                    "entry": "none", "exit": "none",
                })
                continue
            if segments and not segments[-1].get("gap") and \
                    (segments[-1].get("identity") == ident) and \
                    start <= segments[-1]["end"] + TIMELINE_GAP_THRESHOLD + 1e-6:
                # Stessa identita' -> estendi senza interruzione (State Machine).
                prev = segments[-1]
                prev["end"] = max(float(prev["end"]), end)
                prev["chunk_indices"].append(i)
                continue
            segments.append({
                "pose": ident[0], "layout": ident[1], "punch_in": ident[2],
                "identity": ident,
                "use_preset": bool(info.get("use_preset")) if info else False,
                "start": start, "end": end,
                "chunk_indices": [i], "gap": False,
                "entry": "slide_up" if i == 0 else "jump",
                "exit": "hold",
            })
        # Policy entry/exit (spec §2): slide_up SOLO inizio o dopo gap/stacco;
        # slide_down SOLO verso fullscreen/CTA; intermedi = jump-cut + slide X.
        for s_idx, seg in enumerate(segments):
            if seg.get("gap"):
                continue
            prev_real = next(
                (s for s in reversed(segments[:s_idx]) if not s.get("gap")), None)
            next_real = next(
                (s for s in segments[s_idx + 1:] if not s.get("gap")), None)
            if prev_real is None:
                seg["entry"] = "slide_up"  # Hook iniziale
            elif seg["start"] - float(prev_real["end"]) > TIMELINE_GAP_THRESHOLD:
                seg["entry"] = "slide_up"  # stacco visivo totale reale
            elif prev_real.get("layout") != seg.get("layout"):
                seg["entry"] = "slide_x"  # scivolamento laterale 0.3s out_cubic
            else:
                seg["entry"] = "jump"  # stessa coordinata, taglio netto TV
            if next_real is None:
                seg["exit"] = "fade_out" if seg.get("punch_in") else "hold"
            else:
                seg["exit"] = "hold"  # mai slide_down intermedio
                # slide_down solo se il prossimo e' gap fullscreen (CTA testo).
                nxt_is_gap = (s_idx + 1 < len(segments)
                              and segments[s_idx + 1].get("gap"))
                if nxt_is_gap:
                    seg["exit"] = "slide_down"
    except Exception:
        pass
    return segments


def enforce_timeline_dwell(segments: list[dict],
                           min_seconds: float = TIMELINE_MIN_DWELL_SECONDS,
                           chunks: list[dict] | None = None) -> list[dict]:
    """Minimum Dwell Time 3.0s su segmenti (spec §2, mai solleva).

    I segmenti piu' corti del minimo vengono fusi col precedente (il character
    resta a schermo, nessun appari/scompari <3s), SALVO confine narrativo forte
    (hook->body, body->CTA) dove il cambio resta libero. Ritorna stessa lista.
    """
    try:
        if not segments or len(segments) < 2:
            return segments
        try:
            limit = float(min_seconds)
        except (TypeError, ValueError):
            limit = TIMELINE_MIN_DWELL_SECONDS
        if limit <= 0:
            return segments
    except Exception:
        return segments
    try:
        i = 1
        while i < len(segments):
            try:
                cur = segments[i]
                if cur.get("gap"):
                    i += 1
                    continue
                dur = float(cur["end"]) - float(cur["start"])
                if dur >= limit:
                    i += 1
                    continue
                # Confine narrativo forte? -> cambio libero, non fondere.
                boundary = False
                try:
                    if chunks is not None and cur.get("chunk_indices"):
                        first_idx = int(cur["chunk_indices"][0])
                        boundary = _is_narrative_boundary(chunks, first_idx)
                except Exception:
                    boundary = False
                if boundary:
                    i += 1
                    continue
                # Fondi col segmento reale precedente (estendi identità prev).
                prev_idx = i - 1
                while prev_idx >= 0 and segments[prev_idx].get("gap"):
                    prev_idx -= 1
                if prev_idx < 0:
                    i += 1
                    continue
                prev = segments[prev_idx]
                # Il character del prev persiste su tutta la durata del cur:
                # sposta i chunk_indices e allunga end (merge visivo).
                prev["end"] = max(float(prev["end"]), float(cur["end"]))
                prev["chunk_indices"] = list(prev.get("chunk_indices", [])) + \
                    list(cur.get("chunk_indices", []))
                prev["exit"] = cur.get("exit", prev.get("exit"))
                del segments[i]
                # Non avanzare: ricontrolla il segmento fuso/accorpato.
            except Exception:
                i += 1
    except Exception:
        pass
    return segments


def get_timeline_for_chunks(chunks: list[dict],
                            min_dwell: float | None = None) -> list[dict]:
    """Entry-point unico: timeline continua + dwell enforcement (fail-safe).

    Usato da text_animator/video_builder per la traccia character persistente.
    Se `min_dwell` e' None usa config.CHARACTER_MIN_DWELL_SECONDS o 3.0s.
    """
    try:
        segments = build_continuous_timeline(chunks or [])
    except Exception:
        return []
    try:
        if min_dwell is None:
            try:
                from config import CHARACTER_MIN_DWELL_SECONDS as _DW
                min_dwell = float(_DW)
            except Exception:
                min_dwell = TIMELINE_MIN_DWELL_SECONDS
        return enforce_timeline_dwell(segments, float(min_dwell), chunks)
    except Exception:
        return segments
