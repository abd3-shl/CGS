"""
Character Frame Animator: ciclo di vita pulito per macro-blocchi stabili.

Stati per chunk (da core/character_selector.py):
  - "ENTRY":   primo chunk del macro-blocco visibile (slide-in 0.20s).
  - "SUSTAIN": chunk intermedi (solo idle sway a regime).
  - "EXIT":    ultimo chunk del macro-blocco (slide-out/drop 0.16s in coda).
  - "NONE":    chunk nascosto (visible=False, nessun layer).

L'oscillazione idle (sinusoidale) e' disaccoppiata dalle transizioni tramite
idle_weight: durante ENTRY/EXIT l'idle pesa 0->1 / 1->0 per evitare scatti.
Overhead <5ms/frame (solo math, nessuna allocazione Pillow qui).
"""

import math

try:
    from config import (
        CHARACTER_IDLE_AMP_Y,
        CHARACTER_IDLE_FREQ,
        CHARACTER_IDLE_TILT_DEG,
        CHARACTER_ENTRY_DURATION,
        CHARACTER_EXIT_DURATION,
    )
except Exception:  # import isolato / config datata
    CHARACTER_IDLE_AMP_Y = 4.0
    CHARACTER_IDLE_FREQ = 0.4
    CHARACTER_IDLE_TILT_DEG = 0.0
    CHARACTER_ENTRY_DURATION = 0.20
    CHARACTER_EXIT_DURATION = 0.16

from core.easing import ease_out_back, ease_in_cubic, clamp01

# Offset compositivi (coerenti con text_animator: entrata +300px, uscita +400px).
_ENTRY_SLIDE_Y = 300.0
_EXIT_DROP_Y = 400.0


class CharacterFrameAnimator:
    """Calcolo per-frame di (offset_y, rotation_deg, opacity)."""

    @staticmethod
    def get_frame_transform(
        event: str,
        frame_time: float,
        chunk_duration: float,
        global_frame_idx: int,
        fps: int = 30,
    ) -> tuple[float, float, float]:
        """
        Calcola (offset_y, rotation_deg, opacity) per il frame corrente.

        Args:
            event: "ENTRY" | "SUSTAIN" | "EXIT" | "NONE".
            frame_time: secondi dall'inizio del chunk (0..chunk_duration).
            chunk_duration: durata chunk in secondi (>0).
            global_frame_idx: indice frame globale (per fase idle continua).
            fps: frame rate (per convertire idx -> tempo).

        Returns:
            (offset_y px, rotation_deg, opacity 0..1). HIDDEN (NONE) ->
            (0, 0, 0) come segnale "non disegnare".
        """
        try:
            ev = str(event or "NONE").strip().upper()
        except Exception:
            ev = "NONE"
        if ev == "NONE":
            return 0.0, 0.0, 0.0
        try:
            ft = max(0.0, float(frame_time))
        except Exception:
            ft = 0.0
        try:
            dur = max(0.01, float(chunk_duration))
        except Exception:
            dur = 0.5
        try:
            fps_i = max(1, int(fps or 30))
        except Exception:
            fps_i = 30
        try:
            entry_d = max(0.05, float(CHARACTER_ENTRY_DURATION))
        except Exception:
            entry_d = 0.20
        try:
            exit_d = max(0.05, float(CHARACTER_EXIT_DURATION))
        except Exception:
            exit_d = 0.16

        offset_y = 0.0
        rotation_deg = 0.0
        opacity = 1.0

        # 1. Entry (inizio blocco): slide-in con overshoot premium.
        if ev == "ENTRY" and ft < entry_d:
            try:
                progress = ft / entry_d
                eased = ease_out_back(clamp01(progress))
                offset_y += _ENTRY_SLIDE_Y * (1.0 - eased)
                idle_weight = float(clamp01(progress))
            except Exception:
                idle_weight = 1.0
        # 2. Exit (fine blocco): drop rapido in coda al chunk.
        elif ev == "EXIT" and (dur - ft) < exit_d:
            try:
                remaining = max(0.0, dur - ft)
                progress = 1.0 - (remaining / exit_d)
                eased = ease_in_cubic(clamp01(progress))
                offset_y += _EXIT_DROP_Y * eased
                idle_weight = 1.0 - float(clamp01(progress))
            except Exception:
                idle_weight = 1.0
        else:
            idle_weight = 1.0

        # 3. Idle breathing leggero a regime (solo bob verticale delicato,
        # fase globale continua; tilt disabilitato di default: niente dondolio
        # laterale). Con tilt=0 ritorna sempre rotation 0 (nessuna rotazione).
        if idle_weight > 0.01:
            try:
                t = float(global_frame_idx) / float(fps_i)
                freq = max(0.05, float(CHARACTER_IDLE_FREQ))
                amp = max(0.0, float(CHARACTER_IDLE_AMP_Y))
                tilt = max(0.0, float(CHARACTER_IDLE_TILT_DEG))
                sway_y = math.sin(2 * math.pi * freq * t) * amp
                offset_y += sway_y * idle_weight
                if tilt > 1e-9:
                    sway_rot = math.cos(2 * math.pi * freq * t) * tilt
                    rotation_deg += sway_rot * idle_weight
            except Exception:
                pass

        return float(offset_y), float(rotation_deg), float(opacity)

    @staticmethod
    def event_of(chunk: dict | None) -> str:
        """Evento del chunk (ENTRY/SUSTAIN/EXIT/NONE, mai eccezioni)."""
        try:
            if not isinstance(chunk, dict):
                return "NONE"
            _ch = chunk.get("character")
            if isinstance(_ch, dict):
                if not bool(_ch.get("visible", True)):
                    return "NONE"
                _ev = str(_ch.get("event", "") or "").strip().upper()
                if _ev in ("ENTRY", "SUSTAIN", "EXIT", "NONE"):
                    return _ev
            _ev2 = str(chunk.get("char_event", "") or "").strip().upper()
            if _ev2 in ("ENTRY", "SUSTAIN", "EXIT", "NONE"):
                if _ev2 == "NONE":
                    return "NONE"
                if chunk.get("char_visible") is False or chunk.get("pose") is None:
                    return "NONE"
                return _ev2
            # Fallback: visibile senza evento -> SUSTAIN (regime).
            if chunk.get("pose") is None or chunk.get("char_visible") is False:
                return "NONE"
            return "SUSTAIN"
        except Exception:
            return "NONE"

    @staticmethod
    def is_visible(chunk: dict | None) -> bool:
        """Vero se il chunk deve mostrare il personaggio."""
        try:
            return CharacterFrameAnimator.event_of(chunk) != "NONE"
        except Exception:
            return False
