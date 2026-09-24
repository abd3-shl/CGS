"""
Punto di ingresso dell'applicazione: interfaccia grafica Tkinter che
permette di caricare uno o più script testuali e generare un video per
script con audio narrato (ElevenLabs) e sottotitoli animati per-parola
(Groq Whisper + Pillow), composto sullo sfondo del tema tramite ffmpeg.

Bulk: se la checkbox "una riga = un video" è attiva, ogni riga non vuota
del .txt è uno script indipendente (10 righe = 10 video, ciascuno con
tema/nicchia/personaggi propri e output dedicato video_01_slug.mp4...).
Altrimenti tutto il testo è un singolo script (comportamento storico).

Pipeline per SINGOLO script (eseguita in sequenza per ogni script del batch,
in un thread separato per non bloccare la GUI):
  1. Lettura script (.txt)
  2. Generazione palette tema dal testo (Groq, sfondo/testo/keyword)
  3. Generazione audio (ElevenLabs, file dedicato narration_XXX.mp3 nel bulk)
  4. Trascrizione con timestamp parola-per-parola (Groq Whisper)
  5. Allineamento trascrizione allo script originale (corregge errori Whisper)
  5.5 Pianificazione personaggi 2D (Groq + fallback deterministico, non bloccante)
  6. Raggruppamento in chunk da 2-3 parole per enfasi (LLM + fallback)
  7. Estrazione parole chiave (Groq gpt-oss-120b) con colori del tema
  6.5 Analisi tipografica (Semantic Typography Engine v1: nicchia -> font -> tagging base/impact/accent)
  8. Rendering frame animati per-parola (Pillow + easing + multi-style tipografico, Fase 3)
  9. Composizione video finale (ffmpeg: micro-video per chunk + overlay unico)
"""

import os
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from core.tts import generate_audio, TTSError
from core.transcription import transcribe_audio, TranscriptionError
from core.alignment import align_transcript, AlignmentError
from core.theme import generate_theme, hex_to_rgba
from core.emphasis_grouping import group_words_by_emphasis
from core.character_selector import (
    enrich_chunks_with_characters,
    plan_character_layout,
)
from core.keywords import extract_keywords, KeywordError
from core.narrative_structure import classify_narrative
from core.renderer import render_all_subtitles
from core.text_animator import render_all_chunks_animated, TextAnimationError
from core.video_builder import build_video, cleanup_temp_files, VideoBuildError
from config import TEMP_DIR, OUTPUT_DIR, VIDEO_FPS, TEXT_ANIMATION_ENABLED, CHARACTER_ENABLED, TYPOGRAPHY_ENGINE_ENABLED, NARRATIVE_ENABLED


class VideoGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Generator - v2")
        self.root.geometry("640x580")
        self.root.resizable(False, False)
        # Bulk: una riga non vuota = uno script = un video (default: singolo).
        self.bulk_mode = tk.BooleanVar(value=False)
        self._refresh_job: str | None = None

        self._build_ui()

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        title_label = tk.Label(
            self.root, text="Generatore Video Automatico",
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=(15, 5))

        subtitle_label = tk.Label(
            self.root,
            text="Carica uno script (o più script in bulk), genera audio + sottotitoli, esporta i video.",
            font=("Segoe UI", 10),
            fg="#555555",
        )
        subtitle_label.pack(pady=(0, 15))

        # --- Sezione caricamento file ---
        load_frame = tk.Frame(self.root)
        load_frame.pack(pady=5, fill="x", padx=20)

        self.load_button = tk.Button(
            load_frame, text="Carica script (.txt)",
            command=self._on_load_script, width=22, height=1
        )
        self.load_button.pack(side="left")

        self.file_label = tk.Label(load_frame, text="Nessun file caricato", fg="#777777")
        self.file_label.pack(side="left", padx=10)

        # --- Modalità bulk: una riga = uno script = un video ---
        bulk_frame = tk.Frame(self.root)
        bulk_frame.pack(fill="x", padx=20, pady=(5, 0))

        self.bulk_check = tk.Checkbutton(
            bulk_frame,
            text="Bulk: una riga = un video",
            variable=self.bulk_mode,
            command=self._on_bulk_toggle,
            font=("Segoe UI", 10),
        )
        self.bulk_check.pack(side="left")

        self.script_count_label = tk.Label(
            bulk_frame, text="", fg="#2d6cdf", font=("Segoe UI", 9, "bold")
        )
        self.script_count_label.pack(side="left", padx=10)

        # --- Anteprima testo ---
        self.preview_label = tk.Label(self.root, text="Anteprima script:", anchor="w")
        self.preview_label.pack(fill="x", padx=20, pady=(15, 0))

        self.text_preview = scrolledtext.ScrolledText(
            self.root, height=10, wrap="word", font=("Segoe UI", 10)
        )
        self.text_preview.pack(fill="both", padx=20, pady=5, expand=False)
        # Aggiorna conteggio bulk anche quando l'utente digita/incolla a mano.
        try:
            self.text_preview.bind("<<Modified>>", self._on_preview_modified)
        except Exception:
            pass

        # --- Bottone generazione ---
        self.generate_button = tk.Button(
            self.root, text="Genera Video", command=self._on_generate,
            width=25, height=2, bg="#2d6cdf", fg="white", font=("Segoe UI", 10, "bold")
        )
        self.generate_button.pack(pady=15)

        # --- Log di stato ---
        status_label = tk.Label(self.root, text="Stato:", anchor="w")
        status_label.pack(fill="x", padx=20)

        self.status_text = scrolledtext.ScrolledText(
            self.root, height=8, wrap="word", font=("Consolas", 9), state="disabled"
        )
        self.status_text.pack(fill="both", padx=20, pady=(5, 15), expand=False)

    # ------------------------------------------------------------ Helpers

    def _log(self, message: str):
        """Scrive una riga nel box di stato, thread-safe rispetto alla mainloop."""
        def append():
            self.status_text.configure(state="normal")
            self.status_text.insert("end", message + "\n")
            self.status_text.see("end")
            self.status_text.configure(state="disabled")
        self.root.after(0, append)

    def _set_ui_busy(self, busy: bool):
        def apply():
            state = "disabled" if busy else "normal"
            self.generate_button.configure(state=state)
            self.load_button.configure(state=state)
        self.root.after(0, apply)

    # ------------------------------------------------------------ Actions

    def _current_scripts(self) -> list[str]:
        """Script correnti dall'anteprima secondo la modalità (bulk o singolo)."""
        from core.script_loader import parse_scripts
        try:
            bulk = bool(self.bulk_mode.get())
        except Exception:
            bulk = False
        text = self.text_preview.get("1.0", "end")
        return parse_scripts(text, bulk_mode=bulk)

    def _refresh_script_count(self):
        """Aggiorna conteggio script + label bottone (thread-safe se da GUI)."""
        try:
            scripts = self._current_scripts()
            bulk = bool(self.bulk_mode.get())
        except Exception:
            return
        n = len(scripts)
        if bulk:
            count_txt = f"{n} script" if n != 1 else "1 script"
            self.script_count_label.configure(text=count_txt)
            self.preview_label.configure(text="Anteprima script (una riga = un video):")
            btn_txt = f"Genera {n} Video" if n > 1 else "Genera Video"
            self.generate_button.configure(text=btn_txt)
        else:
            self.script_count_label.configure(text="")
            self.preview_label.configure(text="Anteprima script:")
            self.generate_button.configure(text="Genera Video")

    def _on_bulk_toggle(self):
        self._refresh_script_count()

    def _on_preview_modified(self, event=None):
        """Handler <<Modified>> del preview: refresh conteggio senza loop (debounce 300ms)."""
        try:
            self.text_preview.tk.call(self.text_preview._w, "edit", "modified", 0)
        except Exception:
            pass
        # Debounce: evita parse_scripts a ogni battitura durante digitazione/incolla.
        try:
            if self._refresh_job is not None:
                try:
                    self.root.after_cancel(self._refresh_job)
                except Exception:
                    pass
            self._refresh_job = self.root.after(300, self._refresh_script_count)
        except Exception:
            try:
                self._refresh_script_count()
            except Exception:
                pass

    def _on_load_script(self):
        path = filedialog.askopenfilename(
            title="Seleziona lo script (.txt: una riga = uno script in bulk)",
            filetypes=[("File di testo", "*.txt")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("Errore lettura file", str(e))
            return

        from core.script_loader import parse_scripts
        try:
            bulk = bool(self.bulk_mode.get())
        except Exception:
            bulk = False
        n = len(parse_scripts(content, bulk_mode=bulk))
        if bulk:
            self.file_label.configure(text=f"{os.path.basename(path)} ({n} script)", fg="#000000")
        else:
            self.file_label.configure(text=os.path.basename(path), fg="#000000")

        self.text_preview.delete("1.0", "end")
        self.text_preview.insert("1.0", content)
        self._refresh_script_count()

    def _on_generate(self):
        scripts = self._current_scripts()

        if not scripts:
            messagebox.showwarning("Script mancante", "Carica o scrivi uno script prima di generare il video.")
            return

        try:
            bulk = bool(self.bulk_mode.get())
        except Exception:
            bulk = False
        # In singolo, un solo video; in bulk, uno per riga (già filtrate).
        if not bulk:
            scripts = scripts[:1]

        self._set_ui_busy(True)
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.configure(state="disabled")

        thread = threading.Thread(target=self._run_pipeline, args=(scripts,), daemon=True)
        thread.start()

    # ------------------------------------------------------------ Pipeline

    def _log_attempt(self, index: int, total: int, ok: bool, detail: str):
        """Mostra nel box di stato il ciclo delle chiavi (thread-safe)."""
        short = detail if len(detail) <= 180 else detail[:180] + "..."
        symbol = "✅" if ok else "⚠️"
        self._log(f"      {symbol} chiave {index}/{total}: {short}")

    def _run_pipeline(self, scripts: str | list[str]):
        """Orchestratore bulk: uno script = un video, processati separatamente.

        Accetta una stringa singola (retrocompatibilità) o una lista di script.
        Ogni script ha pipeline indipendente (tema/nicchia/personaggi/video propri):
        un errore su uno script non blocca gli altri. Alla fine riepilogo + dialog.
        """
        from core.script_loader import preview_of
        if isinstance(scripts, str):
            scripts = [scripts]
        # Filtra vuoti (sicurezza: la GUI già filtra, ma il metodo resta robusto).
        try:
            scripts = [s for s in scripts if isinstance(s, str) and s.strip()]
        except Exception:
            scripts = []
        total = len(scripts)
        if total == 0:
            self._log("❌ Nessuno script valido da processare.")
            self.root.after(0, lambda: messagebox.showwarning(
                "Script mancante", "Carica o scrivi uno script prima di generare il video."))
            self._set_ui_busy(False)
            return
        if total > 1:
            self._log(f"📦 Modalità bulk: {total} script (una riga = un video), processo separato per ciascuno.")

        successes: list[tuple[int, str]] = []
        failures: list[tuple[int, str]] = []
        try:
            for idx, script_text in enumerate(scripts, start=1):
                if total > 1:
                    self._log(f"\n===== Video {idx}/{total}: \"{preview_of(script_text)}\" =====")
                try:
                    output_path = self._process_one_script(script_text, idx, total)
                    successes.append((idx, output_path))
                    self._log(f"✅ Video {idx}/{total} completato: {output_path}")
                except (TTSError, TranscriptionError, VideoBuildError) as e:
                    err_msg = str(e)
                    failures.append((idx, err_msg))
                    self._log(f"\n❌ Video {idx}/{total} fallito: {err_msg}")
                except Exception as e:
                    tb = traceback.format_exc()
                    err_msg = str(e)
                    failures.append((idx, err_msg))
                    self._log(f"\n❌ Video {idx}/{total} errore inatteso: {err_msg}\n{tb}")
                finally:
                    # Isolamento temp tra video: evita collisioni chunk/audio e spreco disco.
                    try:
                        cleanup_temp_files()
                    except Exception:
                        pass
            # --- Riepilogo batch ---
            self._log(f"\n📊 Completati {len(successes)}/{total} video.")
            for idx, path in successes:
                self._log(f"      ✅ [{idx}] {path}")
            for idx, err in failures:
                short = err if len(err) <= 200 else err[:200] + "..."
                self._log(f"      ❌ [{idx}] {short}")
            if successes and not failures:
                done_msg = f"Video generati con successo: {len(successes)}\n" + "\n".join(p for _, p in successes)
                self.root.after(0, lambda msg=done_msg: messagebox.showinfo("Completato", msg))
            elif successes and failures:
                summary = (f"Completati {len(successes)}/{total}.\n\nOK:\n"
                           + "\n".join(p for _, p in successes)
                           + "\n\nFalliti:\n"
                           + "\n".join(f"[{i}] {e[:150]}" for i, e in failures))
                self.root.after(0, lambda msg=summary: messagebox.showwarning("Completato con errori", msg))
            else:
                msg = "Tutti i video sono falliti:\n" + "\n".join(f"[{i}] {e[:200]}" for i, e in failures)
                self.root.after(0, lambda m=msg: messagebox.showerror("Errore", m))
        finally:
            self._set_ui_busy(False)

    def _process_one_script(self, script_text: str, index: int = 1, total: int = 1) -> str:
        """Pipeline completa per UN singolo script. Ritorna il path del video.

        Ogni script ha tema/nicchia/keyword/personaggi propri (coerenza per nicchia).
        Output e audio hanno nomi unici per indice (nessuna sovrascrittura nel bulk).
        Solleva TTSError/TranscriptionError/VideoBuildError (fatali per questo video).
        """
        from core.script_loader import suggest_output_filename
        tag = f"[Video {index}/{total}] " if total > 1 else ""
        output_filename = suggest_output_filename(index, script_text, total, OUTPUT_DIR)
        audio_filename = f"narration_{index:03d}.mp3" if total > 1 else "narration.mp3"

        self._log(f"{tag}[1-2/8] Tema Groq + audio ElevenLabs in parallelo...")
        import concurrent.futures as _fut
        with _fut.ThreadPoolExecutor(max_workers=2) as _ex:
            _f_theme = _ex.submit(generate_theme, script_text, self._log_attempt)
            _f_audio = _ex.submit(generate_audio, script_text, audio_filename, self._log_attempt)
            theme = _f_theme.result()
            audio_path = _f_audio.result()
        text_rgba = hex_to_rgba(theme["text_color"])
        self._log(
            f"      Tema: sfondo {theme['background_color']}, "
            f"testo {theme['text_color']}, "
            f"{len(theme['keyword_colors'])} colori keyword."
        )
        self._log(f"      Audio generato: {audio_path}")

        self._log(f"{tag}[3/8] Trascrizione audio con Groq Whisper...")
        words = transcribe_audio(audio_path, on_attempt=self._log_attempt)
        self._log(f"      Trascrizione completata: {len(words)} parole riconosciute.")

        self._log(f"{tag}[4/8] Allineamento trascrizione allo script originale...")
        try:
            words, align_stats = align_transcript(words, script_text)
            self._log(
                f"      Corrispondenza {align_stats['match_ratio'] * 100:.0f}%: "
                f"{align_stats['corrected']} corrette, "
                f"{align_stats['interpolated']} recuperate, "
                f"{align_stats['extra']} extra."
            )
        except AlignmentError as e:
            self._log(f"      ⚠️ Allineamento saltato ({e}), uso la trascrizione così com'è.")

        self._log(f"{tag}[5/8] Raggruppamento per enfasi (2-3 parole)...")
        chunks = group_words_by_emphasis(words, on_attempt=self._log_attempt)
        self._log(f"      Creati {len(chunks)} blocchi di sottotitoli.")

        self._log(f"{tag}[5.2/8] Struttura narrativa (hook / corpo a beat / CTA)...")
        narrative_sections: dict = {}
        if NARRATIVE_ENABLED:
            try:
                narrative_sections, chunks = classify_narrative(
                    chunks, script_text, on_attempt=self._log_attempt
                )
                beats = narrative_sections.get("body_beats", [])
                self._log(
                    f"      Hook: {narrative_sections.get('hook', [])} | "
                    f"Corpo: {len(beats)} beat "
                    f"{[len(b) for b in beats] if beats else []} | "
                    f"CTA: {narrative_sections.get('cta', [])} "
                    f"({narrative_sections.get('cta_strength', 'none')}/"
                    f"{narrative_sections.get('cta_mode', 'none')})"
                )
            except Exception as e_narr:
                self._log(f"      ⚠️ Struttura narrativa saltata ({e_narr}), video piatto.")
                narrative_sections = {}
        else:
            self._log("      Struttura narrativa disabilitata (NARRATIVE_ENABLED=0).")

        self._log(f"{tag}[5.5-6.5/8] Personaggi + keyword + tipografia in parallelo...")
        import concurrent.futures as _fut2
        chunks_base = [dict(c) for c in chunks]
        _char_future = None
        _kw_future = None
        _typo_future = None
        with _fut2.ThreadPoolExecutor(max_workers=3) as _ex2:
            if CHARACTER_ENABLED:
                _char_future = _ex2.submit(plan_character_layout, chunks_base, script_text, self._log_attempt)
            else:
                self._log("      Personaggi disabilitati (CHARACTER_ENABLED=0).")
            _kw_future = _ex2.submit(extract_keywords, script_text, self._log_attempt, theme["keyword_colors"])
            if TYPOGRAPHY_ENGINE_ENABLED:
                from core.text_tagger import enrich_chunks_with_typography as _enrich_typo
                _typo_future = _ex2.submit(_enrich_typo, chunks_base, script_text, None, self._log_attempt)
            # --- Raccogli personaggi ---
            character_plan = []
            if _char_future is not None:
                try:
                    character_plan = _char_future.result()
                except Exception as e:
                    self._log(f"      ⚠️ Personaggi saltati ({e}), proseguo senza overlay.")
                    character_plan = []
                if character_plan:
                    for entry in character_plan[:10]:
                        punch = " +PUNCH-IN" if entry.get("punch_in") else ""
                        try:
                            _role = str((chunks_base[entry['chunk_index']] or {}).get("narrative_role", ""))
                            _tag = f"[{_role.upper()}] " if _role in ("hook", "body", "cta") else ""
                        except Exception:
                            _tag = ""
                        self._log(
                            f"      {_tag}chunk {entry['chunk_index']}: posa {entry['pose']} "
                            f"({entry.get('layout', entry.get('layout_preset', entry.get('position')))}"
                            f"{punch}, {entry.get('transition_in', entry.get('transition'))})"
                        )
                    if len(character_plan) > 10:
                        self._log(f"      ... (+{len(character_plan) - 10} chunk)")
            # --- Raccogli keyword ---
            try:
                keyword_colors = _kw_future.result() if _kw_future is not None else {}
                self._log(f"      Trovate {len(keyword_colors)} parole chiave: {', '.join(keyword_colors)}")
            except KeywordError as e:
                self._log(f"      ⚠️ Keyword saltate ({e}), proseguo senza evidenziazioni.")
                keyword_colors = {}
            except Exception as e:
                self._log(f"      ⚠️ Keyword saltate ({e}), proseguo senza evidenziazioni.")
                keyword_colors = {}
            # --- Raccogli tipografia ---
            typography_niche: str | None = None
            chunks_typo = None
            if _typo_future is not None:
                try:
                    typography_niche, chunks_typo = _typo_future.result()
                    self._log(f"      Nicchia identificata: {typography_niche}")
                except Exception as e_typo:
                    self._log(f"      ⚠️ Tipografia saltata ({e_typo}), proseguo con rendering legacy.")
                    typography_niche, chunks_typo = None, None
            else:
                if not TYPOGRAPHY_ENGINE_ENABLED:
                    self._log("      Tipografia disabilitata (TYPOGRAPHY_ENGINE_ENABLED=0).")
        # --- Merge: tipografia (base) + personaggi (overlay) senza doppi passaggi ---
        if chunks_typo is not None:
            chunks = chunks_typo
            try:
                from core.typography_presets import get_preset as _get_preset
                from core.font_manager import FontManager as _FM
                _preset = _get_preset(typography_niche)
                # Pre-warm font una sola volta con manager condiviso (no istanza per chunk).
                try:
                    from core.text_animator import _get_shared_font_manager
                    _fm_shared = _get_shared_font_manager()
                    if _fm_shared is not None:
                        _paths = _fm_shared.ensure_preset_fonts(_preset)
                    else:
                        _paths = _FM().ensure_preset_fonts(_preset)
                except Exception:
                    _paths = {}
                for _role in ("base", "impact", "accent"):
                    _p = (_paths or {}).get(_role, "")
                    _name = _preset["fonts"].get(_role, ["?"])[0] if _preset["fonts"].get(_role) else "?"
                    self._log(f"      Font { _role} ({_name}): {_p if _p else '(fallback di sistema)'}")
                self._log(
                    f"      Colori: base {_preset['colors'].get('base')}, "
                    f"highlight {_preset['colors'].get('highlight')}, "
                    f"accent {_preset['colors'].get('accent')} "
                    f"(contorno: nessuno, stroke=0)"
                )
            except Exception as e_font:
                self._log(f"      ⚠️ Font scaricati/caricati con fallback ({e_font}).")
            try:
                _counts = {"base": 0, "impact": 0, "accent": 0}
                for _ch in chunks:
                    for _w in (_ch.get("styled_words") or []):
                        _st = _w.get("style", "base")
                        if _st in _counts:
                            _counts[_st] += 1
                self._log(
                    f"      Tagging parole completato: "
                    f"{_counts['base']} base, {_counts['impact']} impact, "
                    f"{_counts['accent']} accent ({len(chunks)} chunk)."
                )
            except Exception:
                self._log("      Tagging parole completato.")
        if character_plan:
            try:
                chunks = enrich_chunks_with_characters(chunks, character_plan)
            except Exception:
                pass

        self._log(f"{tag}[6.8/8] Layout guard real-time (anti-overlap personaggio/testo)...")
        try:
            from core.layout_guard import build_realtime_plan, apply_realtime_plans
            _plans, _summary = build_realtime_plan(chunks)
            chunks = apply_realtime_plans(chunks, _plans)
            self._log(
                f"      Guard: {_summary.get('guaranteed', 0)}/{_summary.get('total', 0)} garantiti, "
                f"{_summary.get('fixed', 0)} corretti, "
                f"{_summary.get('hidden', 0)} senza personaggio, "
                f"{_summary.get('intentional', 0)} punch-in intenzionali."
            )
        except Exception as e_guard:
            self._log(f"      ⚠️ Layout guard saltato ({e_guard}), rendering senza correzioni.")

        self._log(f"{tag}[7/8] Rendering sottotitoli animati per-parola (Pillow+easing)...")
        if TEXT_ANIMATION_ENABLED:
            try:
                def _on_chunk_done(done: int, total: int):
                    # Log leggero ogni 10 chunk per non spammare la GUI.
                    if done == 1 or done == total or done % 10 == 0:
                        self._log(f"      ... chunk animato {done}/{total}")
                enriched_chunks = render_all_chunks_animated(
                    chunks,
                    background_color=theme["background_color"],
                    text_color=theme["text_color"],
                    keyword_colors=keyword_colors,
                    output_dir=TEMP_DIR,
                    fps=VIDEO_FPS,
                    on_chunk=_on_chunk_done,
                    typography_niche=typography_niche,
                )
                total_frames = sum(len(c.get("frames", [])) for c in enriched_chunks)
                self._log(f"      Frame animati generati: {total_frames} ({len(enriched_chunks)} chunk).")
            except TextAnimationError as e:
                self._log(f"      ⚠️ Animazione fallita ({e}), fallback a PNG statici.")
                enriched_chunks = render_all_subtitles(chunks, keyword_colors, text_rgba)
                self._log("      Immagini statiche generate (fallback).")
        else:
            enriched_chunks = render_all_subtitles(chunks, keyword_colors, text_rgba)
            self._log("      Immagini statiche generate (animazioni disabilitate).")

        self._log(f"{tag}[8/8] Composizione video finale con ffmpeg (micro-video + overlay)...")
        output_path = build_video(
            audio_path, enriched_chunks,
            output_filename=output_filename,
            background_color=theme["background_color"],
        )
        self._log(f"      Video completato: {output_path}")
        return output_path


def main():
    root = tk.Tk()
    app = VideoGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
