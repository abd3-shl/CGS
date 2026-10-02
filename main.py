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
from config import TEMP_DIR, OUTPUT_DIR, VIDEO_FPS, TEXT_ANIMATION_ENABLED, CHARACTER_ENABLED, TYPOGRAPHY_ENGINE_ENABLED, NARRATIVE_ENABLED, ENABLE_BG_MUSIC


def _parse_music_cli() -> dict:
    """Opzioni musica da CLI (headless e GUI): --no-music, --music-track, --music-category, --audio-debug."""
    opts: dict = {"no_music": False, "track": None, "category": None, "audio_debug": False}
    try:
        import sys as _sys
        args = list(_sys.argv[1:])
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--no-music":
                opts["no_music"] = True
            elif a == "--audio-debug":
                opts["audio_debug"] = True
            elif a.startswith("--music-track="):
                opts["track"] = a.split("=", 1)[1].strip() or None
            elif a == "--music-track" and i + 1 < len(args):
                i += 1
                opts["track"] = args[i].strip() or None
            elif a.startswith("--music-category="):
                opts["category"] = a.split("=", 1)[1].strip() or None
            elif a == "--music-category" and i + 1 < len(args):
                i += 1
                opts["category"] = args[i].strip() or None
            i += 1
    except Exception:
        pass
    try:
        if not opts["audio_debug"]:
            opts["audio_debug"] = str(os.environ.get("AUDIO_DEBUG", "")).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        pass
    return opts


def _write_audio_sidecar(output_filename: str, choice: dict | None, plan: dict | None,
                         on_log=None) -> str | None:
    """Sidecar `outputs/<video>.audio.json` con attribuzione + misure. Mai eccezioni."""
    try:
        import json as _json
        base = os.path.splitext(str(output_filename))[0] + ".audio.json"
        path = os.path.join(OUTPUT_DIR, base)
        stats: dict = {}
        try:
            from core.audio_mixer import last_mix_stats as _stats
            stats = _stats() or {}
        except Exception:
            stats = {}
        title = "sconosciuto"
        author = "sconosciuto"
        lic = "sconosciuta"
        page = ""
        track = None
        category = None
        try:
            if choice:
                track = os.path.basename(str(choice.get("path", ""))) or None
                category = choice.get("category")
                title = choice.get("title") or (os.path.splitext(track or "")[0] or title)
                author = choice.get("author", author)
                lic = choice.get("license", lic)
                page = choice.get("source_page", "") or ""
        except Exception:
            pass
        offs = {}
        try:
            offs = dict((plan or {}).get("offsets_lu", {}) or {})
        except Exception:
            offs = {}
        data = {
            "track": track,
            "category": category,
            "title": title,
            "author": author,
            "license": lic,
            "source_page": page,
            "attribution_text": f"Music: {title} by {author} ({lic})",
            "final_lufs": stats.get("final_lufs"),
            "true_peak": stats.get("final_tp"),
            "music_offset_lu": {"hook": offs.get("hook", -17), "body": offs.get("body", -20),
                                "cta": offs.get("cta", -18)},
            "track_gain_db": (plan or {}).get("track_gain_db"),
            "pause_count": (plan or {}).get("pause_count", 0),
            "hero_count": (plan or {}).get("hero_count", 0),
            "fade_in_s": (plan or {}).get("fade_in_s"),
            "fade_out_s": (plan or {}).get("fade_out_s"),
            "loop": bool((plan or {}).get("loop", False)),
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2, ensure_ascii=False)
        return path
    except Exception as e:
        try:
            if on_log:
                on_log(f"      ⚠️ Sidecar audio non scritto ({e}).")
        except Exception:
            pass
        return None


def _render_mode() -> str:
    """Render-mode attivo: CLI --render-mode > env RENDER_MODE > 'full'.

    - full: rendering completo ffmpeg.
    - text_only: solo grafica testo (<5s, nessun ffmpeg pesante).
    - debug_safezones: box rossi UI Z=99 sopra il video.
    Mai eccezioni (fallback 'full').
    """
    try:
        import sys as _sys
        for i, a in enumerate(_sys.argv):
            if a.startswith("--render-mode="):
                v = a.split("=", 1)[1].strip().lower()
                if v in ("full", "text_only", "debug_safezones"):
                    return v
            elif a == "--render-mode" and i + 1 < len(_sys.argv):
                v = _sys.argv[i + 1].strip().lower()
                if v in ("full", "text_only", "debug_safezones"):
                    return v
    except Exception:
        pass
    try:
        v = (os.environ.get("RENDER_MODE", "full") or "full").strip().lower()
        return v if v in ("full", "text_only", "debug_safezones") else "full"
    except Exception:
        return "full"


class VideoGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Generator - v2")
        self.root.geometry("640x610")
        self.root.resizable(False, False)
        # Bulk: una riga non vuota = uno script = un video (default: singolo).
        self.bulk_mode = tk.BooleanVar(value=False)
        # Musica: default da config, override da GUI; history anti-ripetizione bulk.
        self.music_enabled = tk.BooleanVar(value=bool(ENABLE_BG_MUSIC))
        self.music_category = tk.StringVar(value="Auto")
        self._music_history: list[str] = []
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

        # --- Musica di sottofondo (default da ENABLE_BG_MUSIC) ---
        music_frame = tk.Frame(self.root)
        music_frame.pack(fill="x", padx=20, pady=(5, 0))

        self.music_check = tk.Checkbutton(
            music_frame,
            text="Musica di sottofondo",
            variable=self.music_enabled,
            font=("Segoe UI", 10),
        )
        self.music_check.pack(side="left")

        try:
            from core.typography_presets import VALID_NICHES as _NICHES
            _cats = ["Auto"] + [str(n) for n in _NICHES]
        except Exception:
            _cats = ["Auto"]
        self.music_menu = tk.OptionMenu(music_frame, self.music_category, *_cats)
        self.music_menu.pack(side="left", padx=10)

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
                    # Con --audio-debug i stem vengono mantenuti (nessuna pulizia).
                    try:
                        if not self._audio_debug_active():
                            cleanup_temp_files()
                        else:
                            self._log("      Stem/debug mantenuti in temp/ (--audio-debug).")
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

    # ------------------------------------------------------------ Musica

    def _music_enabled(self) -> bool:
        """Musica attiva? CLI --no-music > GUI checkbox > ENABLE_BG_MUSIC."""
        try:
            if _parse_music_cli().get("no_music"):
                return False
        except Exception:
            pass
        try:
            return bool(self.music_enabled.get())
        except Exception:
            pass
        try:
            return bool(ENABLE_BG_MUSIC)
        except Exception:
            return True

    def _music_overrides(self) -> tuple[str | None, str | None]:
        """(categoria, traccia forzata) da CLI > GUI. Mai eccezioni."""
        cat: str | None = None
        track: str | None = None
        try:
            cli = _parse_music_cli()
            cat = cli.get("category") or None
            track = cli.get("track") or None
        except Exception:
            pass
        if not cat:
            try:
                g = str(self.music_category.get() or "").strip()
                cat = g if g and g.lower() != "auto" else None
            except Exception:
                pass
        return cat, track

    def _audio_debug_active(self) -> bool:
        try:
            return bool(_parse_music_cli().get("audio_debug"))
        except Exception:
            return False

    def _select_music(self, tag: str, audio_path: str, chunks: list,
                      script_text: str, niche: str | None) -> tuple[dict | None, dict | None]:
        """Sceglie traccia + piano (best-effort). Ritorna (choice, plan) o (None, None)."""
        try:
            if _render_mode() == "text_only":
                return None, None
            if not self._music_enabled():
                return None, None
            from core.music_selector import choose_track
            from core.music_plan import build_music_plan
            from core.audio_mixer import _ffprobe_duration, measure_loudness
            cat_cli, forced = self._music_overrides()
            niche_eff = (cat_cli or niche or "").strip() or None
            dur = _ffprobe_duration(audio_path)
            vlufs = None
            try:
                m = measure_loudness(audio_path)
                vlufs = float(m["lufs"]) if m else None
            except Exception:
                vlufs = None
            try:
                history = list(getattr(self, "_music_history", None) or [])
            except Exception:
                history = []
            choice = choose_track(niche_eff, script_text, history, forced, dur, vlufs,
                                  on_log=lambda msg: self._log(f"      {msg}"))
            if not choice:
                self._log("      ⚠️ Musica non usata (nessuna traccia valida), proseguo con voce+SFX.")
                return None, None
            words_flat: list = []
            try:
                for ch in (chunks or []):
                    if isinstance(ch, dict):
                        words_flat.extend(ch.get("words") or [])
            except Exception:
                pass
            plan = build_music_plan(chunks, words_flat, float(dur or 10.0), choice,
                                    vlufs if vlufs is not None else -16.0, None)
            try:
                plan["track_info"] = choice
            except Exception:
                pass
            try:
                dur_t = float(choice.get("duration", 0.0) or 0.0)
                lufs_t = choice.get("lufs")
                lufs_s = f"{float(lufs_t):.1f} LUFS" if lufs_t is not None else "LUFS n.d."
                self._log(f"{tag}[8/8] Musica: {choice.get('category')}/{os.path.basename(str(choice.get('path', '')))} "
                          f"({dur_t:.0f}s, {lufs_s}) → gain {float(plan.get('track_gain_db', 0.0)):+.1f} dB")
            except Exception:
                pass
            return choice, plan
        except Exception as e:
            self._log(f"      ⚠️ Musica saltata ({e}), uso voce+SFX.")
            return None, None

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

        # --- Fase 1: arricchimento timestamp (tier/vfx/sfx, start/end invariati) ---
        try:
            _words_before = [dict(w) for w in words]
        except Exception:
            _words_before = []
        try:
            from core.timestamp_enricher import enrich_whisper_timestamps as _enrich_ts
            _enr = _enrich_ts(words)
            # Merge solo chiavi additive (timestamp originali mai sovrascritti).
            for _i, (_o, _e) in enumerate(zip(words, _enr)):
                try:
                    for _k in ("tier", "vfx_type", "sfx_trigger"):
                        if _k in _e:
                            _o[_k] = _e[_k]
                except Exception:
                    continue
        except Exception:
            pass

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

        self._log(f"{tag}[8/8] Composizione video finale (Ken Burns + SFX + mux atomico)...")
        try:
            _mode = _render_mode()
        except Exception:
            _mode = "full"
        # --- text_only: bypass ffmpeg pesante (debug grafica testo <5s) ---
        if _mode == "text_only":
            try:
                _first = None
                for _c in (enriched_chunks or []):
                    try:
                        _fps_c = (_c.get("frame_paths") or [])
                        if _fps_c:
                            _first = _fps_c[0]
                            break
                    except Exception:
                        continue
                self._log(f"      text_only: {sum(len(c.get('frames', [])) for c in enriched_chunks)} frame, primo={_first}")
                try:
                    from core.invariant_checks import check_temp_containment, check_timestamps_preserved
                    _ok_t, _msg_t = check_temp_containment()
                    self._log(f"      invariant temp: {_msg_t}")
                    try:
                        _flat_after = [w for _c in chunks for w in (_c.get("words") or [])]
                        _ok_ts, _msg_ts = check_timestamps_preserved(
                            [w for w in _words_before], _flat_after) if _words_before and _flat_after else (True, "skip")
                        self._log(f"      invariant timestamps: {_msg_ts}")
                    except Exception:
                        pass
                except Exception:
                    pass
                _preview = os.path.join(OUTPUT_DIR, output_filename.replace(".mp4", "_textonly.txt"))
                try:
                    with open(_preview, "w", encoding="utf-8") as _f:
                        _f.write(f"text_only preview: {len(enriched_chunks)} chunk\n")
                        if _first:
                            _f.write(f"primo frame: {_first}\n")
                except Exception:
                    pass
                return _preview
            except Exception as _e_to:
                self._log(f"      ⚠️ text_only fallito ({_e_to}), proseguo full.")
        # --- Mix audio best-effort (voce+SFX, + musica se abilitata) ---
        _mix_audio = audio_path
        _music_choice: dict | None = None
        _music_plan: dict | None = None
        try:
            _music_choice, _music_plan = self._select_music(
                tag, audio_path, enriched_chunks, script_text, typography_niche)
        except Exception as _e_mus:
            self._log(f"      ⚠️ Musica saltata ({_e_mus}), uso voce+SFX.")
            _music_choice, _music_plan = None, None
        try:
            if _music_choice:
                from core.audio_mixer import mix_audio_with_music, last_mix_stats
                _words_flat = [w for _c in (enriched_chunks or [])
                               for w in (((_c or {}).get("words")) or [])]
                _stems = None
                if self._audio_debug_active():
                    _stems = os.path.join(TEMP_DIR, f"audio_debug_{index:03d}")
                    try:
                        os.makedirs(_stems, exist_ok=True)
                    except Exception:
                        _stems = None
                _mix_audio = mix_audio_with_music(
                    audio_path, enriched_chunks, _words_flat,
                    _music_choice, _music_plan, None, None, None, None,
                    self._log, _stems) or audio_path
                if _mix_audio != audio_path:
                    try:
                        _hist = getattr(self, "_music_history", None)
                        if _hist is None:
                            _hist = self._music_history = []
                        _hist.append(os.path.basename(str(_music_choice.get("path", ""))))
                        from config import MUSIC_HISTORY_SIZE as _HS
                        del _hist[:-max(1, int(_HS))]
                    except Exception:
                        pass
                    try:
                        _st = last_mix_stats()
                        _off = (_music_plan or {}).get("offsets_lu", {}) or {}
                        self._log(
                            f"      Musica: hook {_off.get('hook', -17):+.0f} / "
                            f"body {_off.get('body', -20):+.0f} / cta {_off.get('cta', -18):+.0f} LU | "
                            f"{int((_music_plan or {}).get('pause_count', 0))} pause boost, "
                            f"{int((_music_plan or {}).get('hero_count', 0))} hero dip | "
                            f"fade-in {float((_music_plan or {}).get('fade_in_s', 0.8)):.1f}s / "
                            f"fade-out {float((_music_plan or {}).get('fade_out_s', 2.0)):.1f}s | "
                            f"loudness finale {(_st.get('final_lufs') if _st.get('final_lufs') is not None else '?')} LUFS, "
                            f"TP {(_st.get('final_tp') if _st.get('final_tp') is not None else '?')} dB")
                    except Exception:
                        self._log(f"      Audio mix con musica: {_mix_audio}")
                    if _stems:
                        try:
                            import json as _json
                            import shutil as _sh
                            _sh.copyfile(_mix_audio, os.path.join(_stems, "mix_final.wav"))
                            with open(os.path.join(_stems, "audio_debug.json"), "w", encoding="utf-8") as _f:
                                _json.dump({"track": _music_choice, "plan": _music_plan,
                                            "stats": last_mix_stats()}, _f, indent=2, ensure_ascii=False,
                                           default=str)
                            self._log(f"      Stem debug mantenuti in: {_stems}")
                        except Exception as _e_dbg:
                            self._log(f"      ⚠️ Stem debug non salvati ({_e_dbg}).")
                else:
                    self._log("      ⚠️ Mix musica fallito, uso voce originale.")
            else:
                from core.audio_mixer import mix_sfx as _mix_sfx
                _mix_audio = _mix_sfx(audio_path, enriched_chunks) or audio_path
                if _mix_audio != audio_path:
                    self._log(f"      Audio mix con SFX: {_mix_audio}")
        except Exception as _e_sfx:
            self._log(f"      ⚠️ SFX/musica saltati ({_e_sfx}), uso voce originale.")
            _mix_audio = audio_path
        # --- Sidecar di attribuzione (sempre, anche senza musica) ---
        try:
            _sidecar = _write_audio_sidecar(output_filename, _music_choice, _music_plan, self._log)
            if _sidecar:
                self._log(f"      Sidecar audio: {_sidecar}")
        except Exception:
            pass
        # --- Compose video (Ken Burns + dimmer + overlay, mux atomico) ---
        try:
            from core.video_composer import build_composed_video as _compose
            output_path = _compose(
                _mix_audio, enriched_chunks,
                output_filename=output_filename,
                background_color=theme["background_color"],
                debug_safezones=(_mode == "debug_safezones"),
            )
        except Exception:
            output_path = build_video(
                _mix_audio, enriched_chunks,
                output_filename=output_filename,
                background_color=theme["background_color"],
            )
        self._log(f"      Video completato: {output_path}")
        # --- Test di invariante post-build (assertion automatiche, non fatali) ---
        try:
            from core.invariant_checks import run_post_build_checks
            _flat_after = []
            try:
                for _c in chunks:
                    _flat_after.extend(_c.get("words") or [])
            except Exception:
                pass
            _ok, _det = run_post_build_checks(
                output_path, _mix_audio, enriched_chunks,
                _words_before or None, _flat_after or None, strict=False)
            for _k, (_o, _m) in _det.items():
                self._log(f"      invariant {_k}: {'OK' if _o else 'FAIL'} ({_m})")
            if not _ok:
                self._log("      ⚠️ Invarianti non tutti OK (video comunque valido, vedi sopra).")
        except Exception as _e_inv:
            self._log(f"      ⚠️ Invariant checks saltati ({_e_inv}).")
        return output_path


def main():
    import sys as _sys
    # CLI: --render-mode=full|text_only|debug_safezones (default full, GUI).
    # Headless opzionale: --script path [--bulk] per batch senza Tk.
    _script = None
    _bulk = False
    try:
        for i, _a in enumerate(_sys.argv[1:], start=1):
            if _a.startswith("--script="):
                _script = _a.split("=", 1)[1]
            elif _a == "--script" and i < len(_sys.argv) - 1:
                _script = _sys.argv[i + 1]
            elif _a == "--bulk":
                _bulk = True
    except Exception:
        pass
    if _script:
        # Headless: un file, N video, log su stdout (CI/test rapidi).
        import traceback as _tb
        from core.script_loader import parse_scripts, load_scripts_from_file
        try:
            with open(_script, "r", encoding="utf-8") as _f:
                _text = _f.read()
            _scripts = parse_scripts(_text, bulk_mode=_bulk)
            if not _bulk:
                _scripts = _scripts[:1]
            print(f"CGS headless: {_scripts.__len__()} script (mode={_render_mode()})")
            # Riutilizza la pipeline senza GUI (log minimi).
            import types as _types
            _root = _types.SimpleNamespace(after=lambda ms, fn, *a: fn(*a))
            app = VideoGeneratorApp.__new__(VideoGeneratorApp)
            app.root = _root
            app.bulk_mode = _types.SimpleNamespace(get=lambda: _bulk)
            app._refresh_job = None
            app._music_history = []
            # Headless: nessuna widget GUI (checkbox/categoria assenti -> default da
            # config; override solo da CLI --no-music/--music-track/--music-category).
            app._log = print
            app._log_attempt = lambda i, t, ok, d: print(f"   {'OK' if ok else '..'} chiave {i}/{t}: {d[:120]}")
            app._set_ui_busy = lambda b: None
            from core.script_loader import preview_of as _pv
            _ok = 0
            for _idx, _s in enumerate(_scripts, start=1):
                try:
                    _p = app._process_one_script(_s, _idx, len(_scripts))
                    print(f"OK [{_idx}] {_p}")
                    _ok += 1
                except Exception as _e:
                    print(f"FAIL [{_idx}] {_e}")
                    _tb.print_exc()
                try:
                    if not app._audio_debug_active():
                        cleanup_temp_files()
                except Exception:
                    pass
            print(f"Completati {_ok}/{len(_scripts)}")
            _sys.exit(0 if _ok else 1)
        except Exception as _e:
            print(f"Headless errore: {_e}")
            _tb.print_exc()
            _sys.exit(2)
        return
    root = tk.Tk()
    app = VideoGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    import sys as _sys2
    if any(a in ("-h", "--help") for a in _sys2.argv[1:]):
        print("Uso: python main.py [--render-mode=full|text_only|debug_safezones] [--script file.txt [--bulk]]")
        print("  GUI default; --script esegue headless senza Tk.")
        print("  --no-music: nessun sottofondo (voce+SFX). --music-track=<path>: traccia forzata.")
        print("  --music-category=<nicchia>: categoria forzata. --audio-debug: stem+JSON in temp/ (mantenuti).")
        raise SystemExit(0)
    main()
