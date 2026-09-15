"""
Punto di ingresso dell'applicazione: interfaccia grafica Tkinter che
permette di caricare uno script testuale e generare un video con audio
narrato (ElevenLabs) e sottotitoli sincronizzati (Groq Whisper + Pillow),
composto sullo sfondo del tema tramite ffmpeg.

Pipeline eseguita in un thread separato per non bloccare la GUI:
  1. Lettura script (.txt)
  2. Generazione palette tema dal testo (Groq, sfondo/testo/keyword)
  3. Generazione audio (ElevenLabs)
  4. Trascrizione con timestamp parola-per-parola (Groq Whisper)
  5. Allineamento trascrizione allo script originale (corregge errori Whisper)
  6. Raggruppamento in chunk da 2-3 parole per enfasi (LLM + fallback)
  7. Estrazione parole chiave (Groq gpt-oss-120b) con colori del tema
  8. Rendering PNG dei sottotitoli (Pillow)
  9. Composizione video finale (ffmpeg)
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
from core.keywords import extract_keywords, KeywordError
from core.renderer import render_all_subtitles
from core.video_builder import build_video, cleanup_temp_files, VideoBuildError


class VideoGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Generator - v2")
        self.root.geometry("640x520")
        self.root.resizable(False, False)

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
            text="Carica uno script, genera audio + sottotitoli, esporta il video finale.",
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

        # --- Anteprima testo ---
        preview_label = tk.Label(self.root, text="Anteprima script:", anchor="w")
        preview_label.pack(fill="x", padx=20, pady=(15, 0))

        self.text_preview = scrolledtext.ScrolledText(
            self.root, height=10, wrap="word", font=("Segoe UI", 10)
        )
        self.text_preview.pack(fill="both", padx=20, pady=5, expand=False)

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

    def _on_load_script(self):
        path = filedialog.askopenfilename(
            title="Seleziona lo script",
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

        self.file_label.configure(text=os.path.basename(path), fg="#000000")

        self.text_preview.delete("1.0", "end")
        self.text_preview.insert("1.0", content)

    def _on_generate(self):
        script_text = self.text_preview.get("1.0", "end").strip()

        if not script_text:
            messagebox.showwarning("Script mancante", "Carica o scrivi uno script prima di generare il video.")
            return

        self._set_ui_busy(True)
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.configure(state="disabled")

        thread = threading.Thread(target=self._run_pipeline, args=(script_text,), daemon=True)
        thread.start()

    # ------------------------------------------------------------ Pipeline

    def _log_attempt(self, index: int, total: int, ok: bool, detail: str):
        """Mostra nel box di stato il ciclo delle chiavi (thread-safe)."""
        short = detail if len(detail) <= 180 else detail[:180] + "..."
        symbol = "✅" if ok else "⚠️"
        self._log(f"      {symbol} chiave {index}/{total}: {short}")

    def _run_pipeline(self, script_text: str):
        try:
            self._log("[1/8] Analisi tema dello script (Groq)...")
            theme = generate_theme(script_text, on_attempt=self._log_attempt)
            text_rgba = hex_to_rgba(theme["text_color"])
            self._log(
                f"      Tema: sfondo {theme['background_color']}, "
                f"testo {theme['text_color']}, "
                f"{len(theme['keyword_colors'])} colori keyword."
            )

            self._log("[2/8] Generazione audio con ElevenLabs...")
            audio_path = generate_audio(script_text, on_attempt=self._log_attempt)
            self._log(f"      Audio generato: {audio_path}")

            self._log("[3/8] Trascrizione audio con Groq Whisper...")
            words = transcribe_audio(audio_path, on_attempt=self._log_attempt)
            self._log(f"      Trascrizione completata: {len(words)} parole riconosciute.")

            self._log("[4/8] Allineamento trascrizione allo script originale...")
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

            self._log("[5/8] Raggruppamento per enfasi (2-3 parole)...")
            chunks = group_words_by_emphasis(words, on_attempt=self._log_attempt)
            self._log(f"      Creati {len(chunks)} blocchi di sottotitoli.")

            self._log("[6/8] Estrazione parole chiave (Groq gpt-oss-120b)...")
            try:
                keyword_colors = extract_keywords(
                    script_text,
                    on_attempt=self._log_attempt,
                    keyword_palette_hex=theme["keyword_colors"],
                )
                self._log(f"      Trovate {len(keyword_colors)} parole chiave: {', '.join(keyword_colors)}")
            except KeywordError as e:
                # Non blocca il video: si prosegue senza evidenziazioni.
                self._log(f"      ⚠️ Keyword saltate ({e}), proseguo senza evidenziazioni.")
                keyword_colors = {}

            self._log("[7/8] Rendering immagini sottotitoli (Pillow)...")
            enriched_chunks = render_all_subtitles(chunks, keyword_colors, text_rgba)
            self._log("      Immagini generate.")

            self._log("[8/8] Composizione video finale con ffmpeg...")
            output_path = build_video(
                audio_path, enriched_chunks,
                background_color=theme["background_color"],
            )
            self._log(f"      Video completato: {output_path}")

            cleanup_temp_files()
            self._log("File temporanei rimossi.")

            self._log("\n✅ Video generato con successo!")
            self.root.after(0, lambda: messagebox.showinfo(
                "Completato",
                f"Video generato con successo:\n{output_path}"
            ))

        except (TTSError, TranscriptionError, VideoBuildError) as e:
            self._log(f"\n❌ Errore: {e}")
            self.root.after(0, lambda: messagebox.showerror("Errore", str(e)))

        except Exception as e:
            tb = traceback.format_exc()
            self._log(f"\n❌ Errore inatteso: {e}\n{tb}")
            self.root.after(0, lambda: messagebox.showerror("Errore inatteso", str(e)))

        finally:
            self._set_ui_busy(False)


def main():
    root = tk.Tk()
    app = VideoGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
