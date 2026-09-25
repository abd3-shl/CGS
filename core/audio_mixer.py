"""
Audio SFX Insertion Engine (Full Engine Upgrade — Fase 5).

Mixer audio indipendente: legge i flag `sfx_trigger` dal JSON arricchito
(Fase 1: `core/timestamp_enricher.py` o `styled_words` con is_hero) e inserisce
effetti sintetizzati offline ("pop" T3 hero, "whoosh" cambi posa/ENTRY,
"click" CTA card) sincronizzati al millisecondo, mixati a SFX_VOLUME_DB.

Ducking dinamico: se fornita una musica di sottofondo, applica
sidechaincompress guidata dalla voce (duck a BG_MUSIC_DUCKING_DB durante il
narrato, release nelle pause >0.5s). Senza musica, ritorna voce+SFX.

Tutto best-effort con fallback sicuro: se ffmpeg manca o fallisce, ritorna il
path della narrazione originale (pipeline mai bloccata). Nessun asset esterno:
SFX sintetizzati via `sine`/`anoisesrc` (offline, zero dipendenze).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

try:
    from config import BG_MUSIC_DUCKING_DB, ENABLE_AUTO_SFX, SFX_VOLUME_DB, TEMP_DIR
except Exception:  # config datata
    BG_MUSIC_DUCKING_DB = -12.0
    ENABLE_AUTO_SFX = True
    SFX_VOLUME_DB = -15.0
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")


def _ffmpeg() -> str | None:
    try:
        return shutil.which("ffmpeg")
    except Exception:
        return None


def sfx_events_from_chunks(chunks: list[dict] | None) -> list[tuple[float, str]]:
    """Estrae [(time_sec, kind)] dai chunk arricchiti (mai eccezioni).

    kind: "pop" (T3 hero / sfx_trigger), "whoosh" (ENTRY cambi posa/blocco),
    "click" (CTA card). Timestamp originali preservati (solo lettura).
    Deduplica eventi <80ms per evitare saturazione SFX.
    """
    events: list[tuple[float, str]] = []
    try:
        if not chunks:
            return events
        for ch in chunks:
            try:
                if not isinstance(ch, dict):
                    continue
                t = float(ch.get("start", 0.0))
                # Hero / sfx_trigger diretto (enricher o styled is_hero).
                hero = False
                try:
                    for s in (ch.get("styled_words") or []):
                        if isinstance(s, dict) and (bool(s.get("is_hero")) or bool(s.get("sfx_trigger"))):
                            hero = True
                            break
                    for w in (ch.get("words") or []):
                        if isinstance(w, dict) and bool(w.get("sfx_trigger")):
                            hero = True
                            break
                except Exception:
                    pass
                if hero:
                    events.append((max(0.0, t), "pop"))
                    continue
                # CTA card -> click discreto.
                try:
                    if bool(ch.get("cta_card")):
                        events.append((max(0.0, t), "click"))
                        continue
                except Exception:
                    pass
                # ENTRY macro-blocco -> whoosh morbido.
                try:
                    ev = ""
                    c = ch.get("character")
                    if isinstance(c, dict):
                        ev = str(c.get("event", "") or "").upper()
                    if not ev:
                        ev = str(ch.get("char_event", "") or "").upper()
                    if ev == "ENTRY":
                        events.append((max(0.0, t), "whoosh"))
                except Exception:
                    pass
            except Exception:
                continue
        # Deduplica <80ms (tiene il primo).
        events.sort(key=lambda e: e[0])
        dedup: list[tuple[float, str]] = []
        for tm, kind in events:
            if dedup and abs(tm - dedup[-1][0]) < 0.08:
                continue
            dedup.append((tm, kind))
        return dedup[:24]  # cap: max 24 SFX per video (no saturazione)
    except Exception:
        return []


def _sfx_filter(kind: str, at_sec: float, vol_db: float) -> str:
    """Filtro ffmpeg per un singolo SFX sintetizzato al tempo `at_sec`."""
    try:
        ms = max(0, int(round(float(at_sec) * 1000)))
        vol = max(-40.0, min(0.0, float(vol_db)))
    except Exception:
        ms, vol = 0, -15.0
    try:
        if kind == "pop":
            # Pop breve 880Hz, 90ms, attacco rapido.
            return f"sine=frequency=880:duration=0.09,volume={vol}dB,adelay={ms}|{ms}"
        if kind == "click":
            # Click secco 1400Hz, 50ms.
            return f"sine=frequency=1400:duration=0.05,volume={vol}dB,adelay={ms}|{ms}"
        # whoosh: rumore filtrato 0.25s con fade in/out.
        return (
            f"anoisesrc=color=white:duration=0.25:sample_rate=44100,"
            f"highpass=f=800,lowpass=f=6000,volume={vol - 3.0}dB,"
            f"afade=t=in:st=0:d=0.08,afade=t=out:st=0.17:d=0.08,adelay={ms}|{ms}"
        )
    except Exception:
        return f"sine=frequency=880:duration=0.09,volume=-15dB,adelay={ms}|{ms}"


def mix_sfx(
    narration_path: str,
    chunks: list[dict] | None = None,
    output_path: str | None = None,
    sfx_volume_db: float | None = None,
    bg_music_path: str | None = None,
    bg_ducking_db: float | None = None,
) -> str:
    """Mix voce + SFX (+ ducking musica opzionale). Ritorna path audio finale.

    - Se ENABLE_AUTO_SFX=0 o nessun evento o ffmpeg assente/fallito: ritorna
      `narration_path` invariato (fallback sicuro, mai blocca la pipeline).
    - SFX sincronizzati al ms via adelay + amix (un input per SFX, pesante ma
      cap 24 eventi; filter-graph pulito e isolato).
    - Ducking: sidechaincompress voce->musica (threshold ascolto, ratio 8,
      attack 20ms, release 400ms per risalita nelle pause >0.5s), musica a
      BG_MUSIC_DUCKING_DB sotto la voce.

    Args:
        narration_path: mp3 voce ElevenLabs (timestamps preservati).
        chunks: chunk arricchiti (start originali, solo lettura).
        output_path: file mix (default TEMP_DIR/narration_sfx.mp3).
        sfx_volume_db / bg_ducking_db: override (default da config).
        bg_music_path: musica opzionale (None = solo voce+SFX).
    """
    try:
        vol = float(sfx_volume_db) if sfx_volume_db is not None else float(SFX_VOLUME_DB)
    except Exception:
        vol = -15.0
    try:
        duck = float(bg_ducking_db) if bg_ducking_db is not None else float(BG_MUSIC_DUCKING_DB)
    except Exception:
        duck = -12.0
    try:
        enabled = str(os.environ.get("ENABLE_AUTO_SFX", "1" if ENABLE_AUTO_SFX else "0")).strip().lower() not in (
            "0", "false", "no", "off", "")
    except Exception:
        enabled = bool(ENABLE_AUTO_SFX)
    ff = _ffmpeg()
    if not enabled or ff is None:
        return narration_path
    try:
        if not narration_path or not os.path.isfile(narration_path):
            return narration_path
    except Exception:
        return narration_path
    try:
        events = sfx_events_from_chunks(chunks)
    except Exception:
        events = []
    try:
        has_music = bool(bg_music_path) and os.path.isfile(bg_music_path)
    except Exception:
        has_music = False
    if not events and not has_music:
        return narration_path  # niente da mixare: path originale (zero costo)
    try:
        out = output_path or os.path.join(TEMP_DIR, "narration_sfx.mp3")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    except Exception:
        return narration_path

    try:
        inputs = ["-i", narration_path]
        filters: list[str] = []
        # SFX sintetizzati come sorgenti lavfi.
        for i, (tm, kind) in enumerate(events):
            filters.append(f"{_sfx_filter(kind, tm, vol)}[s{i}]")
        if events:
            # Mix voce + SFX (normalize off: preserva livelli voce).
            mix_ins = "[0:a]" + "".join(f"[s{i}]" for i in range(len(events)))
            filters.append(f"{mix_ins}amix=inputs={len(events) + 1}:normalize=0[mix]")
            voice_label = "[mix]"
        else:
            voice_label = "[0:a]"
        if has_music:
            inputs += ["-i", str(bg_music_path)]
            # Musica a volume duck + sidechain sulla voce (release 400ms).
            filters.append(f"[{len(inputs) // 2}:a]volume={duck}dB[mus]")
            filters.append(
                f"[mus]{voice_label}sidechaincompress=threshold=0.02:ratio=8:"
                f"attack=20:release=400:makeup=1[ducked];"
                f"{voice_label}[ducked]amix=inputs=2:normalize=0[aout]"
            )
            out_label = "[aout]"
        else:
            out_label = voice_label
        # Sorgenti SFX come input lavfi separati (isolati, graph pulito).
        sfx_inputs: list[str] = []
        for tm, kind in events:
            if kind == "pop":
                sfx_inputs += ["-f", "lavfi", "-i", "sine=frequency=880:duration=0.09:sample_rate=44100"]
            elif kind == "click":
                sfx_inputs += ["-f", "lavfi", "-i", "sine=frequency=1400:duration=0.05:sample_rate=44100"]
            else:
                sfx_inputs += ["-f", "lavfi", "-i", "anoisesrc=color=white:duration=0.25:sample_rate=44100"]
        # Ricostruisci: gli adelay nei filtri presuppongono gli input lavfi in
        # ordine dopo voce/musica; per robustezza usa amix su stream reali:
        # qui i filtri sopra usano sorgenti inline? No: _sfx_filter e' pensato
        # per filter su input lavfi. Semplifica: usa aevalsrc-free path con
        # sine diretti + adelay come catene su ciascun input lavfi.
        cmd_inputs = ["-i", narration_path]
        if has_music:
            cmd_inputs += ["-i", str(bg_music_path)]
        cmd_inputs += sfx_inputs
        # Mappa: 0=voce, 1=musica? (se presente), poi SFX.
        fc_parts: list[str] = []
        sfx_start = 2 if has_music else 1
        for i, (tm, kind) in enumerate(events):
            idx = sfx_start + i
            ms = max(0, int(round(float(tm) * 1000)))
            if kind == "whoosh":
                fc_parts.append(
                    f"[{idx}:a]highpass=f=800,lowpass=f=6000,volume={vol - 3.0}dB,"
                    f"afade=t=in:st=0:d=0.08,afade=t=out:st=0.17:d=0.08,"
                    f"adelay={ms}|{ms},volume={vol}dB[s{i}]"
                )
            else:
                fc_parts.append(f"[{idx}:a]volume={vol}dB,adelay={ms}|{ms}[s{i}]")
        if events:
            mix_ins2 = "[0:a]" + "".join(f"[s{i}]" for i in range(len(events)))
            fc_parts.append(f"{mix_ins2}amix=inputs={len(events) + 1}:normalize=0[mix]")
            vlab = "[mix]"
        else:
            vlab = "[0:a]"
        if has_music:
            fc_parts.append(f"[1:a]volume={duck}dB[mus]")
            fc_parts.append(
                f"[mus]{vlab}sidechaincompress=threshold=0.02:ratio=8:"
                f"attack=20:release=400:makeup=1[ducked];"
                f"{vlab}[ducked]amix=inputs=2:normalize=0[aout]"
            )
            olab = "[aout]"
        else:
            olab = vlab
        cmd = [ff, "-y"] + cmd_inputs + [
            "-filter_complex", ";".join(fc_parts),
            "-map", olab, "-c:a", "libmp3lame", "-b:a", "192k", out,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.isfile(out):
            return out
        return narration_path
    except Exception:
        return narration_path
