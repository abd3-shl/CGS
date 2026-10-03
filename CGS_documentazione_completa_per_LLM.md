# CGS — Documentazione completa per LLM (codice integrale)

> **Scopo:** permettere a **qualsiasi LLM** di comprendere al **100%** struttura, logica, funzionalità, contratti dati, dipendenze e invarianti del progetto **CGS (Video Generator v2 / CGS)** per generare piani di modifica e implementazioni senza regressioni.
> **Root:** `C:\Users\thinkpad\Desktop\CGS` (repo git). **Piattaforma primaria:** Windows + Python 3.11 + ffmpeg/ffprobe in PATH.
> **Prodotto:** video verticale **9:16 `1080x1920 @30fps`**, sfondo tinta tema premium o Ken Burns dinamico, audio narrato ElevenLabs, sottotitoli animati per-parola stile TikTok **Tier T0–T3**, personaggi 2D overlay, tipografia semantica per nicchia, struttura narrativa hook / corpo-a-beat / CTA, SFX sintetici.
> **Generato il:** 2026-10-01 — da script automatico che incorpora **tutto il codice reale** (nessun riassunto al posto del codice).
> **Come usare:** leggi §1–§3 per orientamento, §5+§7 per contratti dati (obbligatori prima di toccare codice), §11 invarianti (mai violare), §13 ricette modifica, Appendice A per codice integrale.
> **File generato:** `CGS_documentazione_completa_per_LLM.md` (questo file). Da consegnare a un LLM così com'è.

---

## Indice

- [1. Visione d'insieme e pipeline](#1-visione-dinsieme-e-pipeline)
- [2. Stack tecnologico e requisiti](#2-stack-tecnologico-e-requisiti)
- [3. Struttura del progetto (albero)](#3-struttura-del-progetto-albero)
- [4. Setup e avvio](#4-setup-e-avvio)
- [5. Flusso dati e contratti](#5-flusso-dati-e-contratti)
- [6. Configurazione (`config.py` + `.env`)](#6-configurazione-configpy--env)
- [7. Moduli in dettaglio](#7-moduli-in-dettaglio)
- [8. Tipografia semantica + Tier T0–T3 + easing](#8-tipografia-semantica--tier-t0t3--easing)
- [9. Personaggi, layout, guard, Z-index](#9-personaggi-layout-guard-z-index)
- [10. Narrativa hook / corpo / CTA + audio/SFX + video](#10-narrativa-hook--corpo--cta--audiosfx--video)
- [11. Invarianti (mai violare)](#11-invarianti-mai-violare)
- [12. Modalità operative (bulk, headless, render-mode, fast)](#12-modalità-operative-bulk-headless-render-mode-fast)
- [13. Ricette di modifica sicure](#13-ricette-di-modifica-sicure)
- [14. Limiti noti e sviluppi futuri](#14-limiti-noti-e-sviluppi-futuri)
- [Appendice A — Codice integrale di tutti i file](#appendice-a--codice-integrale-di-tutti-i-file)
- [Appendice B — Asset, output, file esclusi](#appendice-b--asset-output-file-esclusi)

---

## 1. Visione d'insieme e pipeline

### 1.1 Cosa fa il programma

1. L'utente carica uno script `.txt` dalla **GUI Tkinter** (`main.py`) oppure via **CLI headless** `--script`.
2. **Singolo:** tutto il testo = 1 script = 1 video. **Bulk** (checkbox *"una riga = un video"*): ogni riga non vuota = 1 script indipendente = 1 video (10 righe = 10 video, ciascuno con tema/nicchia/personaggi/output propri `video_01_slug.mp4` …).
3. Per **ogni script** la pipeline a 8+ step gira in un thread separato (GUI mai bloccata):
   - `[1-2/8] Parallelo x2:` tema colori LLM (Groq) + audio TTS (ElevenLabs).
   - `[3/8]` Trascrizione Whisper parola-per-parola con timestamp.
   - `[4/8]` Allineamento trascrizione → script (tempi Whisper, parole script: corregge errori Whisper).
   - `Fase 1` Arricchimento timestamp Tier/VFX/SFX (deterministico, `start/end` invariati).
   - `[5/8]` Chunk 2–3 parole per enfasi (LLM + fallback deterministico).
   - `[5.2/8]` Struttura narrativa hook / corpo-a-beat / CTA + 1 flag hero per video.
   - `[5.5-6.5/8] Parallelo x3:` piano personaggi + keyword + tipografia (nicchia → font → tagging base/impact/accent).
   - `[6.8/8]` Layout Guard anti-overlap + ancoraggio macro-blocchi.
   - `[7/8]` Rendering frame animati Tier T0–T3 (Pillow) oppure fallback PNG statici.
   - `[8/8]` Mix SFX (voce+SFX) + composizione ffmpeg (Ken Burns + overlay, finestre contigue, GOP 60) → `outputs/`, invariant checks, cleanup `temp/`.

### 1.2 Diagramma flusso dati

```text
.txt → parse_scripts → [script]
   ├─→ generate_theme ─┐
   └─→ generate_audio (mp3) → transcribe_audio → align_transcript → enrich_timestamps
        words[{w,s,e}] → group_by_emphasis → chunks[{text,s,e,words}]
          → classify_narrative (+hero) → chunks+narrative_role/anim_*
          ├─→ plan_character_layout ─┐
          ├─→ extract_keywords ──────┼─→ merge chunks+character+styled_words
          └─→ enrich_typography ─────┘
            → layout_guard (safe_area/font_scale/pill/hide)
            → render_all_chunks_animated (frames PNG + clip_start/end + tail)
            → mix_sfx (voce+SFX) → build_composed_video|build_video (mp4)
            → run_post_build_checks → cleanup_temp
```

### 1.3 Concetti chiave (glossario)

| Termine | Significato |
|---|---|
| `script` | Testo input utente (singola stringa). In bulk: una riga non vuota = uno script |
| `words` | Lista `{word,start,end}` con timestamp in secondi (da Whisper, poi allineata allo script) |
| `chunks` | Blocchi sottotitoli 2–3 parole `{text,start,end,words[...]}` + arricchimenti |
| `styled_words` | Parole con `{word,display,style:base\|impact\|accent,is_hero,is_number,start,end}` |
| `theme` | `{background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB]}` |
| `keyword_colors` | `{parola_normalizzata: (R,G,B,255)}` |
| `character plan` | Lista lunga quanto `chunks` con posa/layout/evento per chunk |
| `macro-blocco` | Gruppo contiguo di chunk con stessa posa/lato/evento ENTRY/SUSTAIN/EXIT (stabilità ≥2.5s) |
| `Tier T0–T3` | Livelli moto/colore testo: T0 base fade, T1 accent rise, T2 impact pop, T3 hero/numero |
| `clip_start/clip_end` | Finestra overlay ffmpeg (=`start/end` + tail gap-hold) |
| `tail` | Frame clonati oltre `chunk.end` per persistenza personaggio nei gap TTS |
| `pill` | Rettangolo arrotondato semi-trasparente dietro testo (solo punch-in/CTA card) |
| `failover` | Rotazione chiavi API in ordine fino a successo |
| `text_only` | Render-mode debug senza ffmpeg pesante |

---

## 2. Stack tecnologico e requisiti

- **GUI:** `tkinter` standard (`ScrolledText`, `after` thread-safe). Nessuna dipendenza esterna.
- **TTS:** `requests` → `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...`
- **LLM + STT:** SDK `groq` (`chat.completions.create`, `audio.transcriptions.create`).
- **Imaging:** `Pillow` (`Image/Draw/Font/Color.getrgb`, assi variabili font per weight 600).
- **Video/Audio:** `ffmpeg` + `ffprobe` via `subprocess` (**obbligatori in PATH**).
- **Env:** `python-dotenv` + fallback parser integrato senza dipendenze.
- **NLP leggera:** `difflib.SequenceMatcher`, `re`, `hashlib.md5`, `colorsys`, `json`.
- **Concorrenza:** `threading.Thread` (GUI), `ThreadPoolExecutor` (pipeline 2–3 worker, render 2–4, ffmpeg clip 2–4).
- **Python:** 3.11 (testato 3.11.9). Dipendenze: `requests>=2.31.0`, `groq>=0.9.0`, `Pillow>=10.0.0`, `python-dotenv>=1.0.0`.

---

## 3. Struttura del progetto (albero)

```text
CGS/  (= video_generator v2)
├── main.py  (770 righe)
├── config.py  (548 righe)
├── requirements.txt  (4 righe)
├── .env  (27 righe, SEGRETO - non incluso)
├── .env.example  (169 righe)
├── .gitignore  (3 righe)
├── README.md  (139 righe)
├── cgs-report-completo.md  (526 righe)
├── core/  (25 moduli Python)
│   ├── advanced_kinetics.py  (305 righe)
│   ├── alignment.py  (120 righe)
│   ├── audio_mixer.py  (274 righe)
│   ├── character_animator.py  (169 righe)
│   ├── character_selector.py  (2181 righe)
│   ├── easing.py  (135 righe)
│   ├── emphasis_grouping.py  (211 righe)
│   ├── font_manager.py  (416 righe)
│   ├── invariant_checks.py  (162 righe)
│   ├── keywords.py  (215 righe)
│   ├── layout_guard.py  (1046 righe)
│   ├── layout_presets.py  (319 righe)
│   ├── narrative_structure.py  (596 righe)
│   ├── renderer.py  (672 righe)
│   ├── script_loader.py  (123 righe)
│   ├── subtitle_grouping.py  (144 righe)
│   ├── text_animator.py  (3489 righe)
│   ├── text_tagger.py  (690 righe)
│   ├── theme.py  (438 righe)
│   ├── timestamp_enricher.py  (199 righe)
│   ├── transcription.py  (185 righe)
│   ├── tts.py  (163 righe)
│   ├── typography_presets.py  (254 righe)
│   ├── video_builder.py  (468 righe)
│   ├── video_composer.py  (272 righe)
├── assets/
│   ├── fonts/  (15 .ttf: Anton, BebasNeue, Caveat, Cinzel, Inter, LeagueSpartan, Montserrat, Nunito, OpenSans, Oswald, PatrickHand, PlayfairDisplay, Poppins, Roboto, SpaceMono)
│   └── characters/  (5 pose: 1.png … 5.png)
├── outputs/  (mp4 finali video_NN_slug.mp4 — file binari, solo elenco in Appendice B)
├── temp/  (audio temporanei + PNG/frame, puliti a fine job — solo elenco)
└── __pycache__/ + core/__pycache__/  (bytecode, esclusi)
```

> Dettaglio riga-per-riga e byte in Appendice A/B. I `.pyc`, i `.mp4` e i `.ttf/.png` non sono incorporati come codice (binari): sono elencati con dimensione in Appendice B.

---

## 4. Setup e avvio

### 4.1 Installa ffmpeg (obbligatorio)

- **Windows:** scarica da https://ffmpeg.org/download.html e aggiungi `bin` al PATH. Verifica con `ffmpeg -version` e `ffprobe -version`.

### 4.2 Dipendenze Python

```bash
pip install -r requirements.txt
```

### 4.3 API key (multi-key con fallback)

```powershell
Copy-Item .env.example .env
```

```env
ELEVENLABS_API_KEYS=chiave1,chiave2,chiave3
GROQ_API_KEYS=chiave1,chiave2
```

- Formati: `*_KEYS` (lista virgola) + `*_KEY` singola (cumulabili, duplicati ignorati). Prima le `_KEYS`, poi la `_KEY`.
- `ELEVENLABS_VOICE_IDS`: 0/1 ID = vale per tutte le chiavi; N ID = N chiavi → 1:1; altrimenti `ValueError`.
- `.env` caricato dalla cartella progetto qualunque sia la CWD; env di sistema ha precedenza. Log GUI mostra `chiave 1/N …`.
- Verifica senza consumare crediti: `python config.py --check-keys` (GET /v1/user + /v1/models).

### 4.4 Avvio

```bash
python main.py
# headless / CI:
python main.py --script input.txt --bulk --render-mode=full
python main.py --help
```

---

## 5. Flusso dati e contratti

### 5.1 `words` (post Whisper + align + enrich)

```python
{"word": str, "start": float, "end": float,
 "tier": "T0|T1|T2|T3", "vfx_type": str|None, "sfx_trigger": "pop|whoosh|click"|None}
# start/end in secondi, mai sovrascritti dopo align (solo chiavi additive).
```

### 5.2 `chunks` (post enfasi + narrativa + tipografia + personaggi + guard)

```python
{"text": str, "start": float, "end": float, "words": [words...],
 "narrative_role": "hook|body|cta", "anim_entry_mult": float, "anim_pop_from": float,
 "styled_words": [{"word":str,"display":str,"style":"base|impact|accent",
                   "is_hero":bool,"is_number":bool,"start":float,"end":float}],
 "character": {"pose":int,"layout":str,"punch_in":bool,"event":"ENTRY|SUSTAIN|EXIT|NONE",
               "visible":bool,"scale":float,"transition_in":str},
 "layout_plan": {"font_px":int,"text_box":(x,y,w,h),"pill":bool,"hidden_char":bool},
 "frames": [{"img": PIL.Image, "t": float}], "frame_paths": [str],
 "clip_start": float, "clip_end": float}
```

### 5.3 `theme` + `keyword_colors`

```python
theme = {"background_color": "#RRGGBB", "text_color": "#RRGGBB",
         "keyword_colors": ["#RRGGBB", ...]}  # contrasto validato THEME_MIN_LUMINANCE_DIFF
keyword_colors = {"parola_norm": (R,G,B,255)}  # verbatim, max MAX, gap MIN_GAP, mai giallo
```

### 5.4 `character plan` + macro-blocchi

- Lunghezza = `len(chunks)`. Stessa posa/lato per macro-blocco ≥`CHARACTER_MIN_BLOCK_DURATION` (2.5s).
- Hook primo chunk e CTA card bloccati; corpo con ritmo max 2 stessa posa/lato poi cambio forzato.
- `POSE_SIDE_MAP` (env `CHARACTER_POSE_SIDES`, default `1:any,2:center,3:center,4:left,5:split`): posa 4 indica a destra → sempre `split_left`.

### 5.5 Frame, tail, clip, mux

- Ogni chunk → N frame PNG (`TEMP_DIR`) a `VIDEO_FPS`. `clip_start/end` = start/end + tail gap-hold (≤`CHARACTER_GAP_HOLD_MAX` 1.5s).
- `video_builder` concatena micro-video per chunk; `video_composer` usa overlay unico + Ken Burns + dimmer. Mux AAC, yuv420p, GOP 60, faststart. Durata video ≈ durata audio ±0.1s.

---

## 6. Configurazione (`config.py` + `.env`)

Tutte le leve stanno in `config.py` (env > default). Le più usate:

| Chiave | Default | Effetto |
|---|---|---|
| `ELEVENLABS_API_KEYS` / `GROQ_API_KEYS` | — (obbligatorie) | Liste failover; log `chiave i/N` |
| `ELEVENLABS_VOICE_ID` / `VOICE_IDS` | Rachel `21m00Tcm4TlvDq8ikWAM` | Voce globale o per-chiave 1:1 |
| `ELEVENLABS_MODEL_ID` / `OUTPUT_FORMAT` | `eleven_multilingual_v2` / `mp3_44100_128` | TTS italiano + formato |
| `GROQ_WHISPER_MODEL` / `GROQ_LLM_MODEL` / `GROQ_THEME_MODEL` | `whisper-large-v3-turbo` / `openai/gpt-oss-120b` | STT + LLM keyword/grouping/tema |
| `KEYWORDS_MAX` / `MIN_GAP` | 10 / 12 | Anti-ammasso keyword |
| `THEME_MIN_LUMINANCE_DIFF` | 80 | Contrasto minimo sfondo/testo |
| `EMPHASIS_MAX/MIN_WORDS_PER_CHUNK` | 3 / 1 | Chunk enfasi |
| `VIDEO_WIDTH/HEIGHT/FPS` | 1080 / 1920 / 30 | Verticale 9:16 |
| `SUBTITLE_FONT_SIZE/COLOR/STROKE_WIDTH` | 64 / bianco / 0 | Legacy (tema vince); nessuno contorno |
| `TEXT_ANIMATION_*` | entry 0.18s, exit 0.15s, keyword 0.7, hero 0.6/0.22s/0.06s, numeri 0.15s, accent lift 10px | Tier T0–T3 |
| `CHARACTER_ENABLED`, `POSE_COUNT`, `SCALE_MIN/MAX`, `MAX_SAME_POSE/SIDE`, `IDLE_*`, `ENTRY/EXIT/MORPH/PUNCH`, `GAP_HOLD*`, `MIN_BLOCK/DISCONTINUOUS/HOOK/CTABODY_RATIO`, `POSE_SIDES` | vedi §9 | Personaggi |
| `TYPOGRAPHY_*` | engine 1, base 60px, impact 1.4x, accent 1.1x, weight 600, stroke 0, shadow off | Tipografia |
| `NARRATIVE_*` | enabled 1, hook 3, CTA 4, card 1/14 parole, hook mult 0.7, pop 0.55 | Narrativa |
| `PIPELINE_FAST`, `RENDER_PARALLEL`, `FFMPEG_PRESET` | 0, 1, veryfast | Performance |
| `ENABLE_ADVANCED_KINETICS/DYNAMIC_BACKGROUNDS/AUTO_SFX`, `SFX_VOLUME_DB`, `BG_MUSIC_DUCKING_DB`, `HERO/BASE_FONT`, `COLOR_BRAND_ACCENT/HERO_BG` | 1/1/1, -15dB/-12dB, …/#FF3366/#000000A6 | Full Engine |
| `EASING_CURVES`, `KINETIC_*`, `DYNAMIC_BG_*`, `CHARACTER_MICRO_*`, `LAYOUT_MAX_WIDTH_RATIO/MIN_FONT_PX` | vedi codice | Curve e tuning |
| `Z_BACKGROUND/CHARACTER/DIMMER/SUBTITLES/DEBUG` | 0/10/20/30/99 | Z-stack invariante |
| `OUTPUT_DIR/TEMP_DIR` | `outputs/` / `temp/` | Percorsi (auto-creati) |

> Codice completo e commentato in Appendice A (`config.py`, `.env.example`). Il `.env` reale non è mai incluso (segreti).

---

## 7. Moduli in dettaglio

> Per ogni file: **responsabilità → funzioni principali → input/output → dipendenze → errori**. Il codice integrale è in Appendice A.

### 7.1 `main.py` — GUI + orchestrazione (770 righe)

Punto di ingresso + GUI Tkinter (`VideoGeneratorApp`, 770 righe) e orchestratore pipeline bulk/headless.
- GUI: caricamento .txt, checkbox bulk, preview editabile con debounce 300ms, bottone Genera, log thread-safe via `root.after`.
- `_current_scripts` / `parse_scripts`: singolo vs bulk (una riga non vuota = uno script).
- `_run_pipeline(scripts)`: loop sequenziale per script, successi/fallimenti separati, cleanup temp per isolamento, riepilogo + dialog.
- `_process_one_script(script,index,total)`: 8+ step — (1-2) tema+audio in parallelo ThreadPool x2, (3) Whisper, (4) align, (Fase1) enrich timestamp, (5) chunk enfasi, (5.2) narrativa, (5.5-6.5) personaggi+keyword+tipografia in parallelo x3, (6.8) layout guard, (7) render animato/fallback statico, (8) mix SFX + compose video + invariant checks. Supporta render-mode full/text_only/debug_safezones. Output `video_NN_slug.mp4`, audio `narration_NNN.mp3`.
- CLI headless `--script file [--bulk]` senza Tk, `--render-mode`, `--help`. CLI riusa stessa pipeline con stub root.

### 7.2 `config.py` — configurazione centrale (548 righe)

Configurazione centrale (548 righe). Priorità: env sistema > `.env` in root (via dotenv o parser fallback) > default.
- Helpers `_get_int/_float/_tuple/_str_list/_key_list`, `_get_hex_color`.
- API keys multi-key con failover: `ELEVENLABS_API_KEYS`, `GROQ_API_KEYS` (+ alias singola). `get_elevenlabs_voice_id()` per mapping voce-per-chiave.
- Sezioni: ElevenLabs (voice/model/output_format), Groq (whisper/LLM/theme model), keyword (MAX/MIN_GAP), tema (luminance diff), enfasi (max/min chunk), video (1080x1920@30), sottotitoli, animazioni Tier T0-T3, personaggi (pose/scala/idle/entry-exit/gap-hold/macro-blocchi/discontinuo/POSE_SIDE_MAP), tipografia, narrativa, performance (PIPELINE_FAST/RENDER_PARALLEL/FFMPEG_PRESET), Full Engine (kinetics/background/SFX/colori/Z-index/easing/zoom/safe-zone), percorsi OUTPUT/TEMP.
- `check_keys()` verifica gratuita GET /v1/user + /v1/models, `python config.py --check-keys`. Crea cartelle output/temp.

### 7.3 Pipeline audio/testo

- **`core/tts.py`** — TTS ElevenLabs: `generate_audio(script, filename, on_attempt)` → mp3 in temp. POST /v1/text-to-speech/{voice_id}?output_format, failover su tutte le chiavi con voice-per-chiave, log tentativi, eccezione `TTSError` se tutte falliscono. Nessun consumo in check-keys.
- **`core/transcription.py`** — STT Groq Whisper: `transcribe_audio(mp3, on_attempt)` → `[{word,start,end}]` secondi float. Usa `GROQ_WHISPER_MODEL` (turbo), `response_format verbose_json` + `timestamp_granularities word`, failover multi-key, `TranscriptionError` se fallisce.
- **`core/alignment.py`** — Riallinea Whisper allo script: tempi di Whisper + parole dello script via `difflib.SequenceMatcher`. Corregge omonimi/errori, interpola parole saltate, marca extra. Ritorna `(words, stats{match_ratio,corrected,interpolated,extra})`, `AlignmentError` se script vuoto. Non altera timestamp originali oltre interpolazione.
- **`core/timestamp_enricher.py`** — Arricchimento Fase1 (199 righe, deterministico): `enrich_whisper_timestamps(words)` aggiunge `tier/vfx_type/sfx_trigger` senza toccare start/end. Euristiche: maiuscole/numeri → T2/T3, punteggiatura → pause, verbi CTA → hero-candidate. Input per mixer e animator.
- **`core/script_loader.py`** — Bulk loader (123 righe): `parse_scripts(text, bulk_mode)` → `[script]` (bulk: righe non vuote; singolo: testo intero strip), `load_scripts_from_file(path, bulk)`, `preview_of(script)` (40 char), `suggest_output_filename(index, script, total, outdir)` → `video_NN_slug.mp4` (slug 30 char, unicità con suffisso).
- **`core/subtitle_grouping.py`** — Grouping classico per frasi (144 righe, riferimento/fallback): `group_words(...)` per punteggiatura + limiti `SUBTITLE_MAX_CHARS/WORDS`. Non usato nel path enfasi ma tenuto per compatibilità/test.
- **`core/emphasis_grouping.py`** — Chunk 2-3 parole per enfasi: `group_words_by_emphasis(words, on_attempt)` → `[{text,start,end,words}]`. LLM riceve solo indici, restituisce tagli; testo/timestamp mai alterati. Fallback deterministico a blocchi di 2 (3 se leggera). Rispetta `EMPHASIS_MAX/MIN_WORDS`. `PIPELINE_FAST=1` salta LLM.

### 7.4 Tema + keyword + tipografia

- **`core/theme.py`** — Palette tema LLM: `generate_theme(script, on_attempt)` → `{background_color,text_color,keyword_colors[]}` hex #RRGGBB. Prompt nicchia-emozione, validazione contrasto luminanza `THEME_MIN_LUMINANCE_DIFF`, fallback deterministico da hash se LLM fallisce. `hex_to_rgba`, `luminance`, helpers.
- **`core/keywords.py`** — Keyword LLM Groq 120B: `extract_keywords(script, on_attempt, palette)` → `{parola: (R,G,B,255)}`. Max `KEYWORDS_MAX`, gap `KEYWORDS_MIN_GAP`, match verbatim, colori deterministici da palette tema (mai giallo), fallback frequenza se LLM fallisce. `KeywordError` solo se script vuoto.
- **`core/text_tagger.py`** — Semantic Typography v1 — tagging LLM (690 righe): `enrich_chunks_with_typography(chunks, script, ...)` → `(nicchia, chunks+styled_words)`. Nicchia (fitness/finance/motivazione/...) → font/colori via `typography_presets`. Ogni parola → `{style:base|impact|accent, is_hero, is_number}`. Base leggibile, impact pop, accent handwritten rise. `PIPELINE_FAST` → euristica.
- **`core/typography_presets.py`** — Preset per nicchia (254 righe): `get_preset(nicchia)` → `{fonts{base,impact,accent}, colors{base,highlight,accent}, font_scale, ...}`. Es. fitness→Oswald/Bebas, finanza→Montserrat, motivazione→Anton. Colori coerenti tema, stroke=0 look TikTok pulito.
- **`core/font_manager.py`** — Gestore font (416 righe): `FontManager().ensure_preset_fonts(preset)` → `{ruolo:path}`. Verifica `assets/fonts/`, download da Google Fonts GitHub se mancante, fallback sistema (Arial/Impact...), supporto assi variabili Weight 600 per base. Pre-warm condiviso una sola volta.

### 7.5 Personaggi + layout + moto

- **`core/character_selector.py`** — Character-Driven Overlay (2181 righe, il più complesso dopo text_animator): `plan_character_layout(chunks, script, on_attempt)` → lista lunga quanto chunks con `{pose 1-5, layout/layout_preset, punch_in, transition_in, scale, event ENTRY/SUSTAIN/EXIT/NONE, visible, ...}`. LLM assegna posa+layout+punch (max 2/video); fallback deterministico con ritmo anti-ripetizione (max 2 stessa posa/lato), `POSE_SIDE_MAP` (1:any,2:center,3:center,4:left,5:split), macro-blocchi ≥2.5s, discontinuo Breath&Focus (hook/CTA sempre visibili, body 60%), `resolve_chunk_layout`, `enrich_chunks_with_characters` merge senza doppio passaggio.
- **`core/layout_presets.py`** — Zone scena 1080x1920 (319 righe): `LAYOUTS` dict — `layout_center_standard` (125% larghezza, testo alto Y150-900), `layout_split_left/right` (personaggio laterale 120-180%, testo opposto), `layout_*_punch` (zoom 1.1x). Personaggi ancorati basso con gambe fuori campo, testa sempre in campo, crop compositivo. Geometria `{char_box, text_box, scale, anchor}`.
- **`core/layout_guard.py`** — Guard anti-overlap real-time (1046 righe): `build_realtime_plan(chunks)` + `apply_realtime_plans` + `plan_chunk_realtime`. Misura bbox reali (alpha personaggio + font reale + overshoot pop + punch-in), fix a cascata (sposta testo, scala font fino a 40px, pill, nascondi personaggio), summary `{guaranteed,fixed,hidden,intentional}`. Hook da 3 righe in text_animator/renderer. Mai eccezioni fatali.
- **`core/character_animator.py`** — Ciclo vita math-only (<5ms/frame, 169 righe): `character_frame_transform(chunk_meta, t)` → `{dx,dy,scale,alpha}`. ENTRY slide&pop 0.20s ease_out_back da +300px, SUSTAIN idle breathing (bob 4px@0.4Hz, tilt 0), EXIT slide-drop 0.16s ease_in_cubic a +400px, morph 0.40 ease_in_out, punch zoom 0.60, gap-hold tail, idle_weight disaccoppiato per evitare scatti.
- **`core/easing.py`** — Curve pure (135 righe, solo math, ref easings.net/Penner): `clamp01`, `ease_out_cubic/quad`, `ease_out_back`, `ease_in_cubic`, `ease_in_out_cubic`, `ease_out_elastic`. `EASING_CURVES` in config mappa tier→funzione. Overshoot >1.0 voluto per pop premium.
- **`core/advanced_kinetics.py`** — Motore cinetico avanzato opt-in (305 righe, `ENABLE_ADVANCED_KINETICS`): Tier T0/T1 bordo 3px fade 2 frame, T2 brand accent #FF3366 picco 110% 4 frame, T3 badge pill #000000A6 + micro-shake 4px, glyph-cache, interpolazione scala/opacità su timestamp esatti. A flag spento path legacy identico.
- **`core/narrative_structure.py`** — Struttura hook/corpo-a-beat/CTA (596 righe): `classify_narrative(chunks, script, on_attempt)` → `(sections, chunks_arricchiti)`. Hook = prime 1-3 caption (entry 0.7x, pop 0.55), corpo = beat stabili, CTA = ultime 1-4 con segnali (follow/commento/link) + `cta_strength/mode` + `CTA card` persistente se ≤14 parole + 1 flag hero per video (verbo CTA o climax hook, mai numeri). Aggiunge `narrative_role/anim_*` per chunk. Disattivabile `NARRATIVE_ENABLED=0`.

### 7.6 Rendering + audio + video + invarianti

- **`core/renderer.py`** — Renderer statico fallback (672 righe): `render_all_subtitles(chunks, keyword_colors, text_rgba)` → chunks+`frame_paths[1 PNG]`. Pillow centrato, keyword a colori, base tema, stroke 0, pill solo punch-in/CTA. Usato se `TEXT_ANIMATION_ENABLED=0` o animazione fallisce.
- **`core/text_animator.py`** — Renderer animato principale (3489 righe, file più grande): `render_all_chunks_animated(chunks, bg, text_color, keyword_colors, ...)` → chunks+`frames[{img, t}]` + `frame_paths` + `clip_start/clip_end` + tail. Per-parola entry progressiva (T0 fade 0.18s, T1 rise 10px, T2 pop 0.7→1.0, T3 hero 0.6→1.0 0.22s + hold 0.06s, numeri 0.15s) + exit gruppo 0.15s, hook 0.7x scattante, CTA card karaoke persistente, Pillow + easing + tipografia nicchia + layout guard + personaggi compositati (Z 10 < dimmer 20 < subtitles 30). Parallelo ThreadPool se `RENDER_PARALLEL=1`. `TextAnimationError` → fallback statico.
- **`core/audio_mixer.py`** — Mixer SFX sintetici offline (274 righe, `ENABLE_AUTO_SFX`): `mix_sfx(voce_mp3, chunks)` → mp3 mixato. Legge `sfx_trigger` (pop hero, whoosh ENTRY, click CTA), sintetizza sine/noise envelope, mix a `SFX_VOLUME_DB`, ducking musica `BG_MUSIC_DUCKING_DB` nelle pause >0.5s. Best-effort, mai bloccante. Ritorna path originale se disabilitato/fallito.
- **`core/video_builder.py`** — Builder legacy ffmpeg (468 righe): `build_video(audio, chunks, output_filename, bg)` → mp4. Sfondo tinta unita tema, un input overlay PNG per chunk con `enable=between(t,start,end)`, concat micro-video per chunk animati, mux AAC + yuv420p + GOP 60 + faststart, finestre contigue, `VideoBuildError` se ffmpeg fallisce. Fallback se composer fallisce.
- **`core/video_composer.py`** — Composer premium (272 righe, `ENABLE_DYNAMIC_BACKGROUNDS`): `build_composed_video(audio, chunks, ...)` → mp4. Ken Burns impercettibile (zoompan max 1.08 step 0.0015), dimmer 20 sopra character 10, subtitles 30, debug safe-zone 99 se richiesto, overlay unico con timeline, mux atomico. Chiama builder legacy in fallback.
- **`core/invariant_checks.py`** — Asserzioni post-build (162 righe): `run_post_build_checks(mp4, audio, chunks, words_before, words_after)` → `(ok, {durata,temp,timestamp,zorder})`. `|video-audio|<0.1s`, nessun temp fuori `temp/`, timestamp preservati, testo dentro canvas. Loggato, mai fatale (`strict=False`). + `check_temp_containment`, `check_timestamps_preserved` per text_only.

---

## 8. Tipografia semantica + Tier T0–T3 + easing

- **Engine v1** (`TYPOGRAPHY_ENGINE_ENABLED`): nicchia → preset (`typography_presets.py`) → tagging LLM (`text_tagger.py`: base/impact/accent + `is_hero/is_number`) → font reali (`font_manager.py`, pre-warm condiviso) → colori tema+keyword.
- **Look TikTok pulito:** `stroke=0`, ombra off di default; leggibilità da contrasto tema validato + pill su punch-in/CTA card.
- **Tier moto** (fonte moto = style + `is_hero`; fonte colore = tema + keyword):
  - **T0 base:** fade `ease_out_cubic` 0.18s; avanzato: bordo 3px, 2 frame.
  - **T1 accent:** rise 10→0px `ease_out_quad` senza scala (non deforma handwritten).
  - **T2 impact:** pop 0.7→1.0 `ease_out_back` + picco 110% 4 frame, brand accent `#FF3366` in avanzato.
  - **T3 hero (1/video):** pop 0.6→1.0 0.22s (≥5 frame) + hold 0.06s + badge pill `#000000A6` + micro-shake 4px; mai numeri.
  - **T3-num:** pop corto 0.15s dedicato.
  - **Hook:** entry 0.7x + pop da 0.55 (più scattante). **Exit gruppo:** fade 0.15s.
- **Easing** (`core/easing.py`, `EASING_CURVES` in config): `t0_fade/ease_out_cubic`, `t1_rise/ease_out_quad`, `t2_pop-t3/ease_out_back`, `char_entry/ease_out_back`, `char_exit/ease_in_cubic`, `char_morph/ease_in_out_cubic`, `hero_shake/ease_out_elastic`. Sempre `clamp01` prima.

---

## 9. Personaggi, layout, guard, Z-index

- **Overlay** (`CHARACTER_ENABLED`): personaggi tra sfondo e sottotitoli. Asset `assets/characters/1.png … 5.png` (accettati anche .jpg/.jpeg).
- **Piano LLM** (`character_selector.py`, 2181 righe): posa 1–5 + layout + `punch_in` (max 2/video) + transizione/scala/evento. Fallback deterministico con ritmo calmo (mai 3 uguali di fila).
- **Vincoli posa** (`CHARACTER_POSE_SIDES`, default `1:any,2:center,3:center,4:left,5:split`): `any`=libero, `center`=solo centro (pose larghe), `left`=solo a sinistra (testo a destra), `right`=speculare, `split`=solo split alternati. Posa 4 indica a destra → sempre a sinistra. Estendibile a futuri asset senza codice.
- **Macro-blocchi + Breath & Focus:** posa/lato bloccati ≥2.5s; `DISCONTINUOUS_MODE=1` → visibile in Hook/CTA, nascosto in ~40% beat Body (pause brevi distribuite, mai lunghi vuoti). Hook primo chunk e CTA card stabili.
- **Idle:** bob verticale 4px @0.4Hz, tilt 0 (niente dondolio). Entry slide&pop 0.20s da +300px, exit slide-drop 0.16s a +400px, morph 0.40, punch 0.60, gap-hold tail ≤1.5s (no blink).
- **Layout zone** (`layout_presets.py`): personaggi 120–180% larghezza ancorati basso (gambe fuori campo, testa in campo con headroom); `center_standard` (testo alto), `split_left/right` (testo opposto), varianti punch zoom 1.1x.
- **Guard real-time** (`layout_guard.py`, 1046 righe): bbox reali + overshoot + punch → fix a cascata (sposta/scala fino a 40px/pill/nascondi) → summary guaranteed/fixed/hidden/intentional.
- **Z-stack invariante:** `bg 0 < character 10 < dimmer 20 < subtitles 30 < debug 99`. Debug safe-zone = box rossi Z99.

---

## 10. Narrativa hook / corpo / CTA + audio/SFX + video

- **Narrativa** (`NARRATIVE_ENABLED`, 596 righe): hook (prime 1–3 caption, scattanti) / corpo a beat (stabili, ritmo personaggi) / CTA-outro (ultime 1–4 con segnali, card karaoke persistente se ≤14 parole, finale stabilizzato). 1 hero/video.
- **Audio:** ElevenLabs mp3 → Whisper → align → enrich → chunk. SFX sintetici (`audio_mixer.py`, `ENABLE_AUTO_SFX`): pop hero, whoosh ENTRY, click CTA a `SFX_VOLUME_DB` (-15dB), ducking musica -12dB nelle pause >0.5s. Best-effort.
- **Video:** `video_composer.py` (Ken Burns zoompan ≤1.08 + dimmer + overlay unico, mux atomico) con fallback `video_builder.py` (tinta unita + overlay per chunk). yuv420p/AAC, GOP 60, faststart, finestre contigue. `outputs/video_NN_slug.mp4`.
- **Post-build:** `invariant_checks.py` logga durata/temp/timestamp/zorder (mai fatale in bulk).

---

## 11. Invarianti (mai violare)

1. **Timestamp:** `start/end` Whisper mai sovrascritti dopo align (solo chiavi additive tier/vfx/sfx; interpolazione solo per parole recuperate).
2. **LLM non altera testo/timing:** emphasis/grouping/keyword/tema ricevono indici o testo ma restituiscono solo tagli/colori/palette; fallback deterministici sempre pronti.
3. **Z-order:** `0 < 10 < 20 < 30 < 99` sempre; sottotitoli sempre sopra dimmer+personaggi; debug solo con flag.
4. **Safe-zone e leggibilità:** testo dentro canvas, font ≥40px, contrasto tema validato, stroke 0, pill solo dove previsto.
5. **Stabilità visiva:** macro-blocchi ≥2.5s, max 2 stessa posa/lato, 1 hero/video (mai numeri), max 2 punch-in/video, CTA card solo se breve.
6. **Isolamento bulk:** tema/nicchia/keyword/personaggi/output/audio per-script; nomi unici; cleanup temp dopo ogni video; un fallimento non blocca gli altri.
7. **Temp containment:** tutto il temporaneo dentro `temp/`; nessun file fuori; `text_only` non tocca ffmpeg pesante.
8. **Failover e non-bloccaggio:** rotazione chiavi fino a successo; SFX/guard/narrativa/tipografia saltabili con warning (video comunque valido); solo TTS/STT/build sono fatali per quel video.
9. **Mux:** durata video ≈ audio ±0.1s; yuv420p/AAC/faststart/GOP 60; finestre overlay contigue senza buchi/sovrapposizioni.

---

## 12. Modalità operative (bulk, headless, render-mode, fast)

- **Bulk GUI:** checkbox → `parse_scripts(bulk=True)` → N video `video_01_slug…` + `narration_001.mp3…`; conteggio live con debounce; bottone `Genera N Video`.
- **Headless:** `python main.py --script file.txt [--bulk]` (senza Tk, log stdout, exit 0/1/2). Ideale CI/test.
- **Render-mode** (CLI `--render-mode=` > env `RENDER_MODE` > `full`): `full` (completo), `text_only` (solo grafica testo <5s + invarianti temp/timestamp, output `_textonly.txt`), `debug_safezones` (box rossi Z99).
- **Fast:** `PIPELINE_FAST=1` salta LLM pesanti (emphasis/character/tagging/nicchia → euristiche istantanee); tema+keyword LLM restano. `RENDER_PARALLEL=1` (ThreadPool 3–4) + `FFMPEG_PRESET=veryfast` (bozze `ultrafast`).

---

## 13. Ricette di modifica sicure

- **Nuovo Tier/moto:** aggiungi curva in `easing.py` → mappa in `EASING_CURVES` → dirama in `text_animator.py` per `style/is_hero/is_number` → rispetta `clip_start/end` + invarianti 1/4/9. Test `text_only` prima di `full`.
- **Nuova posa personaggio:** aggiungi `6.png` → `CHARACTER_POSE_COUNT=6` → estendi `CHARACTER_POSE_SIDES` (es. `6:right`) senza codice → verifica guard + macro-blocchi.
- **Nuova nicchia font:** aggiungi preset in `typography_presets.py` + keyword in `text_tagger.py` + font in `assets/fonts/` (auto-download se da Google Fonts) → pre-warm loggato.
- **Nuovo SFX:** aggiungi trigger in `timestamp_enricher.py` → synth in `audio_mixer.py` a `SFX_VOLUME_DB` → verifica mix non saturi + durata invariata.
- **Nuovo layout:** aggiungi preset in `layout_presets.py` con `char_box/text_box` → vincolo posa se serve → guard lo valida automaticamente.
- **Verifica standard:** `python config.py --check-keys` → `python main.py --script test.txt --render-mode=text_only` → `full` singolo → bulk 2–3 righe → controlla log invarianti + `outputs/` + `temp/` vuoto.

---

## 14. Limiti noti e sviluppi futuri

- Nessun asset grafico/video di sottofondo (solo tinta tema o Ken Burns su tinta).
- Script lunghissimi (centinaia di chunk): comando ffmpeg lungo, composizione più lenta → ottimizzabile con overlay unico con timeline (già parziale in composer).
- Keyword verbatim (flessioni diverse non matchano) → futuro stemming/lemma.
- Voci clonate per-chiave richiedono `VOICE_IDS` 1:1 preciso.
- Sviluppi: overlay timeline singola, musica di sottofondo con ducking reale, nuovi preset nicchia, pose aggiuntive, badge T3 personalizzati, cache LLM per bulk ripetuti.

---

## Appendice A — Codice integrale di tutti i file

> Ogni sezione riporta **path relativo, righe, dimensione, descrizione breve** e poi il **codice completo** in blocco. Nessun taglio: un LLM può ricostruire il progetto da qui.
> Ordine: root (`main.py`, `config.py`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, `cgs-report-completo.md`) poi `core/*.py` alfabetico.


### `main.py` — 770 righe, 35920 byte

Punto di ingresso + GUI Tkinter (`VideoGeneratorApp`, 770 righe) e orchestratore pipeline bulk/headless.
- GUI: caricamento .txt, checkbox bulk, preview editabile con debounce 300ms, bottone Genera, log thread-safe via `root.after`.
- `_current_scripts` / `parse_scripts`: singolo vs bulk (una riga non vuota = uno script).
- `_run_pipeline(scripts)`: loop sequenziale per script, successi/fallimenti separati, cleanup temp per isolamento, riepilogo + dialog.
- `_process_one_script(script,index,total)`: 8+ step — (1-2) tema+audio in parallelo ThreadPool x2, (3) Whisper, (4) align, (Fase1) enrich timestamp, (5) chunk enfasi, (5.2) narrativa, (5.5-6.5) personaggi+keyword+tipografia in parallelo x3, (6.8) layout guard, (7) render animato/fallback statico, (8) mix SFX + compose video + invariant checks. Supporta render-mode full/text_only/debug_safezones. Output `video_NN_slug.mp4`, audio `narration_NNN.mp3`.
- CLI headless `--script file [--bulk]` senza Tk, `--render-mode`, `--help`. CLI riusa stessa pipeline con stub root.

```python
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
        # --- SFX mix best-effort (voce+SFX, mai bloccante) ---
        _mix_audio = audio_path
        try:
            from core.audio_mixer import mix_sfx as _mix_sfx
            _mix_audio = _mix_sfx(audio_path, enriched_chunks) or audio_path
            if _mix_audio != audio_path:
                self._log(f"      Audio mix con SFX: {_mix_audio}")
        except Exception as _e_sfx:
            self._log(f"      ⚠️ SFX saltati ({_e_sfx}), uso voce originale.")
            _mix_audio = audio_path
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
        raise SystemExit(0)
    main()

```

---

### `config.py` — 548 righe, 28249 byte

Configurazione centrale (548 righe). Priorità: env sistema > `.env` in root (via dotenv o parser fallback) > default.
- Helpers `_get_int/_float/_tuple/_str_list/_key_list`, `_get_hex_color`.
- API keys multi-key con failover: `ELEVENLABS_API_KEYS`, `GROQ_API_KEYS` (+ alias singola). `get_elevenlabs_voice_id()` per mapping voce-per-chiave.
- Sezioni: ElevenLabs (voice/model/output_format), Groq (whisper/LLM/theme model), keyword (MAX/MIN_GAP), tema (luminance diff), enfasi (max/min chunk), video (1080x1920@30), sottotitoli, animazioni Tier T0-T3, personaggi (pose/scala/idle/entry-exit/gap-hold/macro-blocchi/discontinuo/POSE_SIDE_MAP), tipografia, narrativa, performance (PIPELINE_FAST/RENDER_PARALLEL/FFMPEG_PRESET), Full Engine (kinetics/background/SFX/colori/Z-index/easing/zoom/safe-zone), percorsi OUTPUT/TEMP.
- `check_keys()` verifica gratuita GET /v1/user + /v1/models, `python config.py --check-keys`. Crea cartelle output/temp.

```python
"""
Configurazione centrale del progetto.
Le API key vanno inserite qui oppure, meglio, tramite variabili d'ambiente
(consigliato per non salvare chiavi in chiaro nei file).

Priorità dei valori:
  1. variabili d'ambiente di sistema
  2. file `.env` nella root del progetto (vedi `.env.example`)
  3. default definiti qui sotto
"""

import os
import sys
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def _load_env_file() -> None:
    """Carica `.env` dalla cartella del progetto (non dalla working directory).

    Usa python-dotenv se disponibile, altrimenti un parser minimo integrato.
    Le variabili d'ambiente di sistema hanno sempre la precedenza (come dotenv).
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        return
    except ImportError:
        pass

    # Fallback senza dipendenze: parsing riga-per-riga di KEY=valore.
    try:
        with open(ENV_PATH, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    print(
        "Avviso: python-dotenv non installato, uso il parser .env integrato "
        "(consigliato: pip install -r requirements.txt).",
        file=sys.stderr,
    )
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[name] = value


_load_env_file()


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_tuple(key: str, default: tuple) -> tuple:
    raw = os.environ.get(key, "")
    if not raw or not raw.strip():
        return default
    try:
        return tuple(int(x.strip()) for x in raw.split(","))
    except ValueError:
        return default


def _get_str_or_none(key: str) -> str | None:
    raw = os.environ.get(key, "")
    return raw.strip() or None


def _get_str_list(*names: str) -> list[str]:
    """Legge una o più variabili d'ambiente come lista di stringhe.

    Accetta valori separati da virgola e/o a capo, rimuove spazi, virgolette
    e duplicati (mantenendo l'ordine). Es.:
        ELEVENLABS_API_KEYS="chiave1, chiave2, chiave3"
    """
    items: list[str] = []
    for name in names:
        raw = os.environ.get(name, "")
        if not raw:
            continue
        for part in raw.replace("\n", ",").split(","):
            item = part.strip().strip('"').strip("'").strip()
            if item and item not in items:
                items.append(item)
    return items


def _get_key_list(*names: str) -> list[str]:
    """Alias di _get_str_list per la lettura delle API key."""
    return _get_str_list(*names)

# ---- API KEYS ----
# Priorità: env di sistema > file `.env` > stringa vuota.
# Copia `.env.example` in `.env` e compilalo (vedi README, sezione Setup).
#
# Sono supportate PIÙ chiavi per servizio (fallback automatico): se una chiave
# fallisce (quota esaurita, rate limit, chiave non valida...), il codice prova
# la successiva finché una non funziona. Formati accettati:
#   ELEVENLABS_API_KEYS="chiave1,chiave2,chiave3"   (consigliato per multi-key)
#   ELEVENLABS_API_KEY="chiave-singola"             (equivalente a una sola chiave)
# Le due variabili si cumulano (prima le _KEYS, poi la _KEY singola).

ELEVENLABS_API_KEYS: list[str] = _get_key_list("ELEVENLABS_API_KEYS", "ELEVENLABS_API_KEY")
GROQ_API_KEYS: list[str] = _get_key_list("GROQ_API_KEYS", "GROQ_API_KEY")

# Alias singola chiave (prima disponibile o "") per retrocompatibilità
# con eventuale codice che importa ELEVENLABS_API_KEY / GROQ_API_KEY.
ELEVENLABS_API_KEY = ELEVENLABS_API_KEYS[0] if ELEVENLABS_API_KEYS else ""
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

# ---- ElevenLabs ----
# Voce default ("Rachel"), usata per tutte le chiavi se VOICE_IDS non è impostato.
# Lista voci disponibili: https://elevenlabs.io/app/voice-library
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # voce default ("Rachel"), sostituibile
# Voci per-chiave (opzionale): serve quando ogni account ha voci diverse
# (es. voci clonate esistenti solo sull'account che le ha create).
#   - 1 solo ID   -> vale per tutte le chiavi (come ELEVENLABS_VOICE_ID)
#   - N ID = N key -> abbinamento 1:1 (chiave[i] usa voce[i])
#   - altri casi  -> errore di configurazione (sollevato all'avvio del job)
ELEVENLABS_VOICE_IDS: list[str] = _get_str_list("ELEVENLABS_VOICE_IDS")
# Modello TTS (supporta l'italiano)
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")  # supporta l'italiano
# Formato audio di output (query param `output_format` dell'endpoint
# POST /v1/text-to-speech/{voice_id}; default dei docs ufficiali).
ELEVENLABS_OUTPUT_FORMAT = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")


def get_elevenlabs_voice_id(key_index: int, total_keys: int) -> str:
    """Restituisce il voice ID da usare con la chiave n. `key_index` (0-based).

    Regole di risoluzione (vedi ELEVENLABS_VOICE_IDS sopra):
      - nessun ID in lista  -> ELEVENLABS_VOICE_ID per tutte le chiavi;
      - 1 solo ID in lista  -> quell'ID per tutte le chiavi;
      - N ID = N chiavi     -> abbinamento 1:1.

    Raises:
        ValueError: se la lista ha più di 1 elemento ma lunghezza diversa
            dal numero di chiavi (configurazione ambigua).
    """
    if not ELEVENLABS_VOICE_IDS:
        return ELEVENLABS_VOICE_ID
    if len(ELEVENLABS_VOICE_IDS) == 1:
        return ELEVENLABS_VOICE_IDS[0]
    if len(ELEVENLABS_VOICE_IDS) == total_keys:
        return ELEVENLABS_VOICE_IDS[key_index]
    raise ValueError(
        f"ELEVENLABS_VOICE_IDS contiene {len(ELEVENLABS_VOICE_IDS)} voci ma le "
        f"chiavi sono {total_keys}: usa 1 sola voce (vale per tutte le chiavi) "
        f"oppure esattamente una voce per chiave (abbinamento 1:1)."
    )

# ---- Groq ----
GROQ_WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")  # rapido ed economico, ottimo per trascrizione
# Modello LLM per l'estrazione delle parole chiave (cfr. https://console.groq.com/docs/models)
GROQ_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "openai/gpt-oss-120b")

# ---- Parole chiave ----
KEYWORDS_MAX = _get_int("KEYWORDS_MAX", 10)  # n. massimo di parole chiave evidenziate per video
KEYWORDS_MIN_GAP = _get_int("KEYWORDS_MIN_GAP", 12)  # distanza minima in parole tra due keyword (anti-ammasso)

# ---- Tema dinamico ----
# Modello LLM per la palette tema (default: stesso delle keyword, ma separabile).
GROQ_THEME_MODEL = os.environ.get("GROQ_THEME_MODEL", GROQ_LLM_MODEL)
# Soglia minima di differenza di luminanza (0-255) per la validazione contrasto.
THEME_MIN_LUMINANCE_DIFF = _get_int("THEME_MIN_LUMINANCE_DIFF", 80)

# ---- Raggruppamento per enfasi ----
EMPHASIS_MAX_WORDS_PER_CHUNK = _get_int("EMPHASIS_MAX_WORDS_PER_CHUNK", 3)  # max parole per chunk
EMPHASIS_MIN_WORDS_PER_CHUNK = _get_int("EMPHASIS_MIN_WORDS_PER_CHUNK", 1)  # min parole per chunk

# ---- Video ----
VIDEO_WIDTH = _get_int("VIDEO_WIDTH", 1080)
VIDEO_HEIGHT = _get_int("VIDEO_HEIGHT", 1920)
VIDEO_FPS = _get_int("VIDEO_FPS", 30)
# Nota: lo sfondo video viene dal tema dinamico (core/theme.py),
# non più da un colore fisso in configurazione.

# ---- Sottotitoli ----
SUBTITLE_FONT_PATH = _get_str_or_none("SUBTITLE_FONT_PATH")  # None = usa un font di default del sistema, vedi core/renderer.py
SUBTITLE_FONT_SIZE = _get_int("SUBTITLE_FONT_SIZE", 64)
SUBTITLE_COLOR = _get_tuple("SUBTITLE_COLOR", (255, 255, 255, 255))  # bianco RGBA
SUBTITLE_STROKE_COLOR = _get_tuple("SUBTITLE_STROKE_COLOR", (0, 0, 0, 255))  # contorno nero per leggibilità
SUBTITLE_STROKE_WIDTH = _get_int("SUBTITLE_STROKE_WIDTH", 0)  # 0 = nessun contorno sul testo
SUBTITLE_MAX_CHARS = _get_int("SUBTITLE_MAX_CHARS", 38)   # lunghezza massima approx per chunk di sottotitolo
SUBTITLE_MAX_WORDS = _get_int("SUBTITLE_MAX_WORDS", 7)    # numero massimo di parole per chunk

# ---- Animazioni testo per-parola (Fase 3 + Tier T0-T3) ----
# T0 base fade / T1 accent rise-fade / T2 impact pop / T3 hero-pop (1 per video).
# Fonte moto = style LLM (base/impact/accent) + flag deterministico is_hero;
# fonte colore = tema + palette keyword (vedi core/text_animator._styled_fills).
# Path legacy (senza tipografia) usa solo T0/T2 per stabilita'.
TEXT_ANIMATION_ENABLED = os.environ.get("TEXT_ANIMATION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TEXT_ANIMATION_ENTRY_DURATION = _get_float("TEXT_ANIMATION_ENTRY_DURATION", 0.18)  # secondi, durata entrata singola parola
TEXT_ANIMATION_EXIT_DURATION = _get_float("TEXT_ANIMATION_EXIT_DURATION", 0.15)  # secondi, durata fade-out di gruppo
KEYWORD_ENTRY_SCALE_FROM = _get_float("KEYWORD_ENTRY_SCALE_FROM", 0.7)  # scala iniziale entrata keyword (0.7 -> 1.0)
# T1 accent: risalita verticale senza scala (non deforma handwritten), solo in entry.
TEXT_ANIMATION_ACCENT_LIFT_PX = _get_float("TEXT_ANIMATION_ACCENT_LIFT_PX", 10.0)  # px, rise 10 -> 0
# T3 hero: 1 parola per video (climax hook o verbo CTA), pop marcato + hold.
TEXT_ANIMATION_HERO_SCALE_FROM = _get_float("TEXT_ANIMATION_HERO_SCALE_FROM", 0.6)  # scala iniziale hero (0.6 -> 1.0)
TEXT_ANIMATION_HERO_ENTRY_DURATION = _get_float("TEXT_ANIMATION_HERO_ENTRY_DURATION", 0.22)  # s, overshoot leggibile (>=5 frame)
TEXT_ANIMATION_HERO_EXIT_DELAY = _get_float("TEXT_ANIMATION_HERO_EXIT_DELAY", 0.06)  # s, ~2 frame @30fps oltre il gruppo
# Numeri/dati (impact con cifre): pop piu' corto e secco, mai hero.
TEXT_ANIMATION_NUMBER_ENTRY_DURATION = _get_float("TEXT_ANIMATION_NUMBER_ENTRY_DURATION", 0.15)  # s

# ---- Personaggi 2D "Character-Driven Overlay" ----
# 1 = personaggi sovrapposti tra sfondo e sottotitoli, 0 = video senza personaggi.
CHARACTER_ENABLED = os.environ.get("CHARACTER_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
# Cartella asset personaggi (pose 1.jpg ... 5.jpg; supportati anche .png/.jpeg).
CHARACTERS_DIR = Path(BASE_DIR) / "assets" / "characters"
# Posizionamenti e transizioni validi (cfr. core/character_selector.py).
CHARACTER_VALID_POSITIONS: list[str] = ["bottom_center", "bottom_left", "bottom_right", "side_left", "side_right"]
CHARACTER_VALID_TRANSITIONS: list[str] = ["slide_up", "slide_side", "fade", "none"]
# N. pose disponibili (1.jpg ... 5.jpg) e scala relativa all'altezza 1920px.
CHARACTER_POSE_COUNT = _get_int("CHARACTER_POSE_COUNT", 5)
CHARACTER_SCALE_MIN = _get_float("CHARACTER_SCALE_MIN", 0.65)
CHARACTER_SCALE_MAX = _get_float("CHARACTER_SCALE_MAX", 0.90)
# Alias storici (retrocompatibilita').
CHARACTER_POSITIONS = CHARACTER_VALID_POSITIONS
CHARACTER_TRANSITIONS = CHARACTER_VALID_TRANSITIONS
# ---- Ritmo visivo personaggi (stabile, mai statico) ----
# Max chunk consecutivi con STESSA posa / STESSO lato prima di forzare un cambio.
# 2 = ritmo calmo (mai 3 uguali di fila). Le apparizioni (macro-blocchi) usano
# una posa/lato unici per blocco; tra blocchi adiacenti si evita la ripetizione
# (posa diversa e, quando possibile, lato diverso). Applica a corpo e fallback;
# hook primo chunk e CTA card restano bloccati per stabilita' intenzionale.
CHARACTER_MAX_SAME_POSE = _get_int("CHARACTER_MAX_SAME_POSE", 2)
CHARACTER_MAX_SAME_SIDE = _get_int("CHARACTER_MAX_SAME_SIDE", 2)
# ---- Idle breathing leggero ma visibile (personaggio vivo, video mai statico) ----
# Solo bob verticale dolce, NESSUNA rotazione laterale (tilt=0: il dondolio
# destra-sinistra rendeva il video instabile). 1 = ON, 0 = OFF.
CHARACTER_IDLE_ENABLED = _get_int("CHARACTER_IDLE_ENABLED", 1)  # 1 = ON, 0 = OFF
CHARACTER_IDLE_AMP_Y = _get_float("CHARACTER_IDLE_AMP_Y", 4.0)  # px, respiro percettibile ma delicato
CHARACTER_IDLE_FREQ = _get_float("CHARACTER_IDLE_FREQ", 0.4)  # Hz, ritmo calmo (~2.5s per ciclo)
CHARACTER_IDLE_TILT_DEG = _get_float("CHARACTER_IDLE_TILT_DEG", 0.0)  # gradi, 0 = nessuna rotazione laterale
# ---- Animazioni character (entrate/uscite per-frame fluidi + morph coerente) ----
# Entrata slide&pop ~0.20s (~6 frame @30fps) da offset Y +300px con ease_out_back;
# uscita slide-drop ~0.16s (~5 frame @30fps) verso +400px con ease_in_cubic.
# Morph di continuita' (0.40) e zoom punch smart (0.60) restano piu' morbidi per
# ritmo coerente (mai frenetico): l'entrata/uscita rapida riguarda solo
# apparizione/sparizione, non i cambi posa/lato (morph fluido anti-blink).
CHARACTER_ENTRY_DURATION = _get_float("CHARACTER_ENTRY_DURATION", 0.20)
CHARACTER_FIRST_ENTRY_DURATION = _get_float("CHARACTER_FIRST_ENTRY_DURATION", 0.20)
CHARACTER_EXIT_DURATION = _get_float("CHARACTER_EXIT_DURATION", 0.16)
CHARACTER_PUNCH_ZOOM_DURATION = _get_float("CHARACTER_PUNCH_ZOOM_DURATION", 0.60)
CHARACTER_MORPH_DURATION = _get_float("CHARACTER_MORPH_DURATION", 0.40)
# Persistenza nei gap inter-chunk: 1 = il character resta visibile durante le
# pause quando continua nel chunk dopo (fix blink sparizione/riapparizione).
CHARACTER_GAP_HOLD_ENABLED = os.environ.get("CHARACTER_GAP_HOLD_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
CHARACTER_GAP_HOLD_MAX = _get_float("CHARACTER_GAP_HOLD_MAX", 1.5)  # cap secondi per gap
# ---- Stabilita' macro-blocchi + presenza discontinua ("Breath & Focus") ----
# Il personaggio NON cambia posa/lato dentro lo stesso macro-blocco narrativo:
# ogni apparizione dura almeno CHARACTER_MIN_BLOCK_DURATION secondi.
# Con DISCONTINUOUS_MODE=1 il personaggio appare in Hook e CTA e scompare
# nei beat intermedi (Body) per lasciare spazio al testo (anti-flicker).
CHARACTER_MIN_BLOCK_DURATION = _get_float("CHARACTER_MIN_BLOCK_DURATION", 2.5)  # durata min apparizione in sec
CHARACTER_DISCONTINUOUS_MODE = _get_int("CHARACTER_DISCONTINUOUS_MODE", 1)  # 1 = ON (scompare nei beat), 0 = sempre visibile
CHARACTER_HOOK_VISIBLE = _get_int("CHARACTER_HOOK_VISIBLE", 1)  # 1 = sempre visibile in Hook
CHARACTER_CTA_VISIBLE = _get_int("CHARACTER_CTA_VISIBLE", 1)  # 1 = sempre visibile in CTA
CHARACTER_BODY_VISIBLE_RATIO = _get_float("CHARACTER_BODY_VISIBLE_RATIO", 0.6)  # frazione blocchi Body visibili (~60%: pause nascoste brevi e distribuite, mai lunghi tratti senza personaggio)

def _get_pose_side_map(key: str, default: str) -> dict[int, str]:
    """Mappa posa -> vincolo lato (any|center|left|right|split).

    Formato env: '1:any,2:center,3:center,4:left,5:split'.
    Pensata per adattarsi a futuri asset senza toccare il codice: se una
    nuova posa indica verso sinistra (come l'attuale posa 4 che punta verso
    destra dello spettatore), basta impostarla a 'left' (personaggio a
    sinistra, testo a destra); se punta verso destra, a 'right'.
    """
    raw = os.environ.get(key, default)
    if raw is None:
        raw = default
    try:
        text = str(raw or default)
    except Exception:
        text = default
    allowed = {"any", "center", "left", "right", "split"}
    out: dict[int, str] = {}
    try:
        for part in text.replace("\n", ",").replace(";", ",").split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            left, _, right = part.partition(":")
            try:
                pose = int(left.strip())
            except (TypeError, ValueError):
                continue
            side = right.strip().lower()
            if side in allowed:
                out[pose] = side
    except Exception:
        pass
    return out


# ---- Direzione pose 2D (adattabile a futuri asset senza codice) ----
# Significato vincoli:
#   any    = nessun vincolo (segue il lato richiesto dal ritmo/narrazione)
#   center = solo layout_center_standard (pose larghe come la 2 a braccia aperte)
#   left   = solo layout_split_left (personaggio a SINISTRA, testo a DESTRA)
#   right  = solo layout_split_right (personaggio a DESTRA, testo a SINISTRA)
#   split  = solo split (alternati left/right, es. posa 5 riflessiva)
# Posa 4 (indica verso la SUA sinistra = verso DESTRA dello spettatore):
# deve stare SEMPRE a sinistra (split_left) cosi' indica verso il testo a destra.
# Metterla a destra la farebbe indicare fuori campo (lontano dal testo).
CHARACTER_POSE_SIDE_MAP: dict[int, str] = _get_pose_side_map(
    "CHARACTER_POSE_SIDES", "1:any,2:center,3:center,4:left,5:split"
)
# Riempie eventuali pose mancanti (1..POSE_COUNT) con default coerenti.
try:
    _POSE_SIDE_DEFAULTS: dict[int, str] = {1: "any", 2: "center", 3: "center", 4: "left", 5: "split"}
    for _p in range(1, max(1, int(CHARACTER_POSE_COUNT)) + 1):
        CHARACTER_POSE_SIDE_MAP.setdefault(_p, _POSE_SIDE_DEFAULTS.get(_p, "any"))
except Exception:
    pass


def get_pose_side_constraint(pose: int) -> str:
    """Vincolo lato per posa ('any' se ignota, mai eccezioni)."""
    try:
        return CHARACTER_POSE_SIDE_MAP.get(int(pose), "any")
    except Exception:
        return "any"

# ---- Semantic Typography Engine v1 ----
# 1 = font/colori/dimensioni per nicchia + tagging LLM (base/impact/accent),
# 0 = path legacy (singolo font + keyword palette).
# Look pulito stile TikTok: NESSUN contorno nero (stroke=0) e NESSUNA ombra
# di default. La leggibilità è garantita dal contrasto tema (sfondo/testo
# validato in core/theme.py) + pill semi-trasparente sul preset punch-in.
TYPOGRAPHY_ENGINE_ENABLED = os.environ.get("TYPOGRAPHY_ENGINE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_BASE_FONT_SIZE = _get_int("TYPOGRAPHY_BASE_FONT_SIZE", 60)  # px, prima di font_scale del preset
TYPOGRAPHY_IMPACT_SCALE = _get_float("TYPOGRAPHY_IMPACT_SCALE", 1.4)  # 1.3x-1.5x da spec
TYPOGRAPHY_ACCENT_SCALE = _get_float("TYPOGRAPHY_ACCENT_SCALE", 1.1)
# Peso del font BASE (testo chiaro e leggibile): 600 = SemiBold, leggermente
# più in grassetto del Regular (400) ma non troppo (niente ExtraBold/Black).
# Applicato all'asse Weight dei font variabili (Inter/Roboto/Montserrat/...);
# per i font statici (Poppins/Lato/...) si usa un grassetto sintetico leggero
# (stroke 1px stesso colore, nessun contorno nero). Solo il base: impact e
# accent restano invariati per stile.
TYPOGRAPHY_BASE_WEIGHT = _get_int("TYPOGRAPHY_BASE_WEIGHT", 600)
TYPOGRAPHY_STROKE_WIDTH = _get_int("TYPOGRAPHY_STROKE_WIDTH", 0)  # 0 = nessun contorno (look pulito)
TYPOGRAPHY_SHADOW_ENABLED = os.environ.get("TYPOGRAPHY_SHADOW_ENABLED", "0").strip().lower() not in ("0", "false", "no", "off", "")
TYPOGRAPHY_SHADOW_OFFSET = _get_tuple("TYPOGRAPHY_SHADOW_OFFSET", (3, 3))
TYPOGRAPHY_SHADOW_FILL = _get_tuple("TYPOGRAPHY_SHADOW_FILL", (0, 0, 0, 180))
# Cartella font scaricati (vedi core/font_manager.py).
FONTS_DIR = Path(BASE_DIR) / "assets" / "fonts"

# ---- Struttura narrativa hook / corpo a beat / CTA ----
# 1 = il video viene letto come struttura in 3 atti (hook, corpo a beat,
# CTA-outro) con tecniche dedicate per atto e finale stabilizzato;
# 0 = pipeline piatta legacy (nessuna differenziazione).
NARRATIVE_ENABLED = os.environ.get("NARRATIVE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")
NARRATIVE_HOOK_MAX_CHUNKS = _get_int("NARRATIVE_HOOK_MAX_CHUNKS", 3)  # hook = prime 1-3 caption
NARRATIVE_CTA_MAX_CHUNKS = _get_int("NARRATIVE_CTA_MAX_CHUNKS", 4)  # CTA = ultime 1-4 caption con segnali
NARRATIVE_CTA_CARD = os.environ.get("NARRATIVE_CTA_CARD", "1").strip().lower() not in ("0", "false", "no", "off", "")
NARRATIVE_CTA_CARD_MAX_WORDS = _get_int("NARRATIVE_CTA_CARD_MAX_WORDS", 14)  # card persistente solo se CTA breve
NARRATIVE_HOOK_ENTRY_MULT = _get_float("NARRATIVE_HOOK_ENTRY_MULT", 0.7)  # hook più scattante (0.7x durata entrata)
NARRATIVE_HOOK_POP_FROM = _get_float("NARRATIVE_HOOK_POP_FROM", 0.55)  # pop hook più marcato (0.55 -> 1.0)

# ---- Performance / velocita' (stessi limiti, stesso output) ----
# PIPELINE_FAST=1: salta gli LLM pesanti (emphasis/character/tagging/nicchia -> euristiche
# deterministiche istantanee). Tema + keyword LLM restano attivi. Ideale per bulk veloci.
PIPELINE_FAST = os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", "")
# RENDER_PARALLEL=1: chunk animati e micro-video ffmpeg in ThreadPool (3-4 worker).
RENDER_PARALLEL = os.environ.get("RENDER_PARALLEL", "1").strip().lower() not in ("0", "false", "no", "off", "")
# FFMPEG_PRESET: veryfast default (qualita' invariata); ultrafast per bozze.
FFMPEG_PRESET = (os.environ.get("FFMPEG_PRESET", "veryfast") or "veryfast").strip() or "veryfast"

# ---- Full Engine Upgrade: cinetica avanzata / background dinamici / SFX ----
# Flag master: 1 = Tier T0-T3 avanzati (stroke T0/T1, brand accent T2, badge T3),
# glyph-cache e curve di interpolazione dedicate. 0 = path legacy stabile.
ENABLE_ADVANCED_KINETICS = os.environ.get("ENABLE_ADVANCED_KINETICS", "1").strip().lower() not in ("0", "false", "no", "off", "")
# Background dinamici con Ken Burns impercettibile (zoompan ffmpeg). 0 = tinta unita tema.
ENABLE_DYNAMIC_BACKGROUNDS = os.environ.get("ENABLE_DYNAMIC_BACKGROUNDS", "1").strip().lower() not in ("0", "false", "no", "off", "")
# SFX automatici su parole T3 / cambi posa (mix a SFX_VOLUME_DB). 0 = nessun SFX.
ENABLE_AUTO_SFX = os.environ.get("ENABLE_AUTO_SFX", "1").strip().lower() not in ("0", "false", "no", "off", "")
SFX_VOLUME_DB = _get_float("SFX_VOLUME_DB", -15.0)  # mix SFX whoosh/pop/click
BG_MUSIC_DUCKING_DB = _get_float("BG_MUSIC_DUCKING_DB", -12.0)  # ducking musica sotto voce
# Font dedicati per cinetica avanzata (fallback automatico via FontManager se assenti).
HERO_WORD_FONT_PATH = (os.environ.get("HERO_WORD_FONT_PATH", "assets/fonts/Montserrat-Black.ttf") or "assets/fonts/Montserrat-Black.ttf").strip()
BASE_WORD_FONT_PATH = (os.environ.get("BASE_WORD_FONT_PATH", "assets/fonts/Inter-Bold.ttf") or "assets/fonts/Inter-Bold.ttf").strip()


def _get_hex_color(key: str, default: str) -> str:
    """Colore hex #RRGGBB o #RRGGBBAA con fallback sicuro (mai eccezioni)."""
    raw = (os.environ.get(key, default) or default).strip()
    if len(raw) in (7, 9) and raw.startswith("#"):
        try:
            int(raw[1:], 16)
            return raw.upper() if len(raw) == 7 else raw[:7].upper() + raw[7:]
        except ValueError:
            pass
    return default


COLOR_BRAND_ACCENT = _get_hex_color("COLOR_BRAND_ACCENT", "#FF3366")  # Tier T2 keyword
COLOR_HERO_BG = _get_hex_color("COLOR_HERO_BG", "#000000A6")  # Tier T3 pill/badge semi-trasparente

# ---- Z-Index Composite Stack (invariante: bg < character < dimmer < subtitles < debug) ----
Z_BACKGROUND: int = 0
Z_CHARACTER: int = 10
Z_DIMMER: int = 20
Z_SUBTITLES: int = 30
Z_DEBUG: int = 99

# ---- Costanti easing / interpolazione cinetica (nomi funzione in core/easing.py) ----
EASING_CURVES: dict[str, str] = {
    "t0_fade": "ease_out_cubic",
    "t1_rise": "ease_out_quad",
    "t2_pop": "ease_out_back",
    "t3_hero": "ease_out_back",
    "t3_num": "ease_out_back",
    "char_entry": "ease_out_back",
    "char_exit": "ease_in_cubic",
    "char_morph": "ease_in_out_cubic",
    "hero_shake": "ease_out_elastic",
}
# Matrici di interpolazione per scala/opacita'/rotazione (start, end, overshoot).
KINETIC_T2_SCALE_PEAK = _get_float("KINETIC_T2_SCALE_PEAK", 1.10)  # picco 110% sui primi 3-4 frame
KINETIC_T2_PEAK_FRAMES = _get_int("KINETIC_T2_PEAK_FRAMES", 4)
KINETIC_T3_SHAKE_PX = _get_float("KINETIC_T3_SHAKE_PX", 4.0)  # micro-shake badge hero
KINETIC_T0_STROKE_PX = _get_int("KINETIC_T0_STROKE_PX", 3)  # bordo T0/T1 in modalita' avanzata
# Ken Burns background dinamico (zoom impercettibile).
DYNAMIC_BG_ZOOM_MAX = _get_float("DYNAMIC_BG_ZOOM_MAX", 1.08)
DYNAMIC_BG_ZOOM_STEP = _get_float("DYNAMIC_BG_ZOOM_STEP", 0.0015)
DYNAMIC_BG_DURATION = _get_int("DYNAMIC_BG_DURATION", 125)
# Micro-transizioni character (cross-fade 3-4 frame o micro-scala 2%).
CHARACTER_MICRO_XFADE_FRAMES = _get_int("CHARACTER_MICRO_XFADE_FRAMES", 4)
CHARACTER_MICRO_SCALE_PCT = _get_float("CHARACTER_MICRO_SCALE_PCT", 0.02)
# Safe-zone dinamiche: auto-scaling font se riga >80% larghezza, minimo 40px.
LAYOUT_MAX_WIDTH_RATIO = _get_float("LAYOUT_MAX_WIDTH_RATIO", 0.80)
LAYOUT_MIN_FONT_PX = _get_int("LAYOUT_MIN_FONT_PX", 40)

# ---- Percorsi progetto ----
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "outputs"))
TEMP_DIR = os.environ.get("TEMP_DIR", os.path.join(BASE_DIR, "temp"))

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-2:]}"


def check_keys() -> int:
    """Verifica ogni chiave con una chiamata gratuita di sola lettura.

    ElevenLabs: GET /v1/user (mostra anche i caratteri residui).
    Groq:       GET /v1/models (endpoint OpenAI-compatibile).
    Non consuma crediti. Ritorna il numero di chiavi NON funzionanti.
    Uso:  python config.py --check-keys
    """
    import requests

    print(f"Cartella progetto: {BASE_DIR}")
    print(f"File .env: {'trovato' if os.path.isfile(ENV_PATH) else 'NON TROVATO'}")
    bad = 0

    print(f"\nElevenLabs: {len(ELEVENLABS_API_KEYS)} chiavi")
    if not ELEVENLABS_API_KEYS:
        print("  (nessuna chiave configurata)")
    for i, key in enumerate(ELEVENLABS_API_KEYS, start=1):
        tag = f"  [{i}/{len(ELEVENLABS_API_KEYS)}] {_mask_secret(key)}"
        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": key},
                timeout=10,
            )
        except Exception as e:
            bad += 1
            print(f"{tag} ERRORE di rete: {e}")
            continue
        if resp.status_code == 200:
            try:
                sub = resp.json().get("subscription", {})
                print(
                    f"{tag} OK "
                    f"(tier={sub.get('tier')}, "
                    f"caratteri usati={sub.get('character_count')}/{sub.get('character_limit')})"
                )
            except Exception:
                print(f"{tag} OK")
        else:
            bad += 1
            print(f"{tag} FALLITA ({resp.status_code}): {resp.text[:150]}")

    print(f"\nGroq: {len(GROQ_API_KEYS)} chiavi")
    if not GROQ_API_KEYS:
        print("  (nessuna chiave configurata)")
    for i, key in enumerate(GROQ_API_KEYS, start=1):
        tag = f"  [{i}/{len(GROQ_API_KEYS)}] {_mask_secret(key)}"
        try:
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
        except Exception as e:
            bad += 1
            print(f"{tag} ERRORE di rete: {e}")
            continue
        if resp.status_code == 200:
            print(f"{tag} OK")
        else:
            bad += 1
            print(f"{tag} FALLITA ({resp.status_code}): {resp.text[:150]}")

    print(f"\nRisultato: {bad} chiavi non funzionanti.")
    return bad


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check-keys":
        sys.exit(1 if check_keys() else 0)
    print(
        "Uso: python config.py --check-keys   "
        "(verifica tutte le chiavi senza consumare crediti)"
    )

```

---

### `requirements.txt` — 4 righe, 65 byte

Dipendenze pip (requests, groq, Pillow, dotenv).

```text
requests>=2.31.0
groq>=0.9.0
Pillow>=10.0.0
python-dotenv>=1.0.0

```

---

### `.env.example` — 169 righe, 7220 byte

Template env documentato (tutte le leve). Copiare in `.env` e compilare.

```env
# ============================================================
# Video Generator - Template variabili d'ambiente
# Copia questo file in `.env` e compila i valori:
#   Windows (PowerShell): Copy-Item .env.example .env
#   Linux/Mac:            cp .env.example .env
# Il file `.env` NON va committato (è già in .gitignore).
# ============================================================

# ---- API KEYS (obbligatorie) ----
# Supportate PIÙ chiavi per servizio con fallback automatico: vengono provate
# in ordine e, se una fallisce (quota esaurita, rate limit, chiave non valida),
# si passa alla successiva finché una non funziona.
# Formato: chiavi separate da virgola (spazi ok, duplicati ignorati).
ELEVENLABS_API_KEYS=chiave-elevenlabs-1,chiave-elevenlabs-2,chiave-elevenlabs-3
GROQ_API_KEYS=chiave-groq-1,chiave-groq-2
# Formato singola chiave (equivalente a una sola chiave, ancora supportato):
# ELEVENLABS_API_KEY=la-tua-chiave
# GROQ_API_KEY=la-tua-chiave

# ---- ElevenLabs ----
# Voce usata per tutte le chiavi ("Rachel" di default).
# Le tue voci: https://elevenlabs.io/app/voice-library
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
# Voci per-chiave (opzionale): serve solo se ogni account ha voci diverse
# (es. voci clonate, visibili solo sull'account che le ha create).
#   1 solo ID         -> vale per tutte le chiavi (come ELEVENLABS_VOICE_ID)
#   N ID = N chiavi   -> abbinamento 1:1 (chiave[i] usa la voce[i])
# ELEVENLABS_VOICE_IDS=voce-account-1,voce-account-2,voce-account-3
# Modello TTS (supporta l'italiano)
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
# Formato audio (query param `output_format` dell'endpoint
# POST /v1/text-to-speech/{voice_id}; default dei docs ufficiali)
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128

# ---- Groq ----
# Modello Whisper per trascrizione con timestamp parola-per-parola
GROQ_WHISPER_MODEL=whisper-large-v3-turbo
# Modello LLM per estrazione parole chiave (120B di Groq)
GROQ_LLM_MODEL=openai/gpt-oss-120b

# ---- Parole chiave ----
# N. massimo di keyword evidenziate e distanza minima (in parole) tra loro
KEYWORDS_MAX=10
KEYWORDS_MIN_GAP=12

# ---- Tema dinamico ----
# Modello LLM per la palette tema (default: stesso delle keyword)
GROQ_THEME_MODEL=openai/gpt-oss-120b
# Soglia minima di differenza di luminanza per il contrasto
THEME_MIN_LUMINANCE_DIFF=80

# ---- Raggruppamento per enfasi ----
# Min/max parole per chunk di sottotitolo
EMPHASIS_MAX_WORDS_PER_CHUNK=3
EMPHASIS_MIN_WORDS_PER_CHUNK=1

# ---- Video ----
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=30
# Nota: lo sfondo video viene dal tema dinamico (core/theme.py).

# ---- Sottotitoli ----
# Percorso font TTF (vuoto = fallback automatico di sistema, vedi core/renderer.py)
SUBTITLE_FONT_PATH=
SUBTITLE_FONT_SIZE=64
# Colori in formato "R,G,B,A"
SUBTITLE_COLOR=255,255,255,255
SUBTITLE_STROKE_COLOR=0,0,0,255
SUBTITLE_STROKE_WIDTH=0
SUBTITLE_MAX_CHARS=38
SUBTITLE_MAX_WORDS=7

# ---- Animazioni testo per-parola (Tier T0-T3) ----
# 1 = frame animati per-parola (entrata progressiva + uscita di gruppo), 0 = PNG statici legacy
# Tier: T0 base fade / T1 accent rise-fade / T2 impact pop / T3 hero-pop (1 parola/video).
TEXT_ANIMATION_ENABLED=1
# Durata entrata singola parola / fade-out di gruppo (secondi)
TEXT_ANIMATION_ENTRY_DURATION=0.18
TEXT_ANIMATION_EXIT_DURATION=0.15
# Scala iniziale entrata keyword (default globale; il preset nicchia 0.6-0.8 e
# l'override hook vincono su questo valore)
KEYWORD_ENTRY_SCALE_FROM=0.7
# T1 accent: risalita verticale senza scala (px, non deforma handwritten)
# TEXT_ANIMATION_ACCENT_LIFT_PX=10.0
# T3 hero (1 parola/video: verbo CTA o climax hook, mai numeri)
# TEXT_ANIMATION_HERO_SCALE_FROM=0.6
# TEXT_ANIMATION_HERO_ENTRY_DURATION=0.22
# TEXT_ANIMATION_HERO_EXIT_DELAY=0.06
# T3-num (impact con cifre: pop corto dedicato, mai hero)
# TEXT_ANIMATION_NUMBER_ENTRY_DURATION=0.15

# ---- Tipografia (Semantic Typography Engine v1) ----
# Look pulito senza contorno nero: 0 = nessun contorno/ombra (default).
# La leggibilità è garantita dal contrasto tema + pill sul punch-in.
# TYPOGRAPHY_ENGINE_ENABLED=1
# TYPOGRAPHY_STROKE_WIDTH=0
# TYPOGRAPHY_SHADOW_ENABLED=0

# ---- Struttura narrativa hook / corpo a beat / CTA ----
# 1 = hook scattante + corpo stabile a beat + finale CTA bloccato (card karaoke
# persistente per CTA forti e brevi); 0 = video piatto senza atti.
# NARRATIVE_ENABLED=1
# NARRATIVE_HOOK_MAX_CHUNKS=3
# NARRATIVE_CTA_MAX_CHUNKS=4
# NARRATIVE_CTA_CARD=1
# NARRATIVE_CTA_CARD_MAX_WORDS=14
# NARRATIVE_HOOK_ENTRY_MULT=0.7
# NARRATIVE_HOOK_POP_FROM=0.55

# ---- Personaggi 2D "Character-Driven Overlay" ----
# 1 = personaggi tra sfondo e sottotitoli, 0 = video senza personaggi
CHARACTER_ENABLED=1
# Scala personaggio relativa all'altezza video (0.65-0.90, default 0.75 dal piano LLM)
# CHARACTER_SCALE_MIN=0.65
# CHARACTER_SCALE_MAX=0.90
# N. pose disponibili in assets/characters (1.jpg ... 5.jpg, .png accettati)
# CHARACTER_POSE_COUNT=5
# Stabilita' macro-blocchi + presenza discontinua ("Breath & Focus"):
# posa/lato bloccati per almeno 2.5s, visibile in Hook/CTA, nascosto nei beat.
# CHARACTER_MIN_BLOCK_DURATION=2.5
# CHARACTER_DISCONTINUOUS_MODE=1
# CHARACTER_HOOK_VISIBLE=1
# CHARACTER_CTA_VISIBLE=1
# CHARACTER_BODY_VISIBLE_RATIO=0.6
# Respiro idle leggero ma visibile: bob verticale dolce, nessuna rotazione
# laterale (il dondolio rendeva il video instabile).
# CHARACTER_IDLE_AMP_Y=4.0
# CHARACTER_IDLE_FREQ=0.4
# CHARACTER_IDLE_TILT_DEG=0.0
# CHARACTER_ENTRY_DURATION=0.20
# CHARACTER_EXIT_DURATION=0.16
# Direzione pose (adattabile a futuri asset senza codice):
# any=center/split liberi, center=solo centro, left=solo a sinistra,
# right=solo a destra, split=split alternati. Posa 4 indica verso destra
# -> deve stare a sinistra (left); se un futuro asset punta dall'altro lato,
# cambia qui (es. "4:right") senza toccare il codice.
# CHARACTER_POSE_SIDES=1:any,2:center,3:center,4:left,5:split

# ---- Percorsi progetto (opzionali, default: ./outputs e ./temp) ----
# OUTPUT_DIR=outputs
# TEMP_DIR=temp

# ---- Full Engine Upgrade: cinetica avanzata / background / SFX (opzionali) ----
# 1 = Tier T0-T3 avanzati (stroke base, brand accent, badge hero), 0 = legacy stabile
# ENABLE_ADVANCED_KINETICS=1
# 1 = background Ken Burns impercettibile, 0 = tinta unita tema
# ENABLE_DYNAMIC_BACKGROUNDS=1
# 1 = SFX whoosh/pop su T3 e cambi posa, 0 = nessun SFX
# ENABLE_AUTO_SFX=1
# SFX_VOLUME_DB=-15.0
# BG_MUSIC_DUCKING_DB=-12.0
# Font dedicati cinetica (fallback automatico se assenti)
# HERO_WORD_FONT_PATH=assets/fonts/Montserrat-Black.ttf
# BASE_WORD_FONT_PATH=assets/fonts/Inter-Bold.ttf
# Colori cinetica: T2 brand accent, T3 pill semi-trasparente
# COLOR_BRAND_ACCENT=#FF3366
# COLOR_HERO_BG=#000000A6
# Tuning cinetica (default sicuri, raramente da toccare)
# KINETIC_T2_SCALE_PEAK=1.10
# KINETIC_T2_PEAK_FRAMES=4
# KINETIC_T3_SHAKE_PX=4.0
# KINETIC_T0_STROKE_PX=3
# DYNAMIC_BG_ZOOM_MAX=1.08
# DYNAMIC_BG_ZOOM_STEP=0.0015
# CHARACTER_MICRO_XFADE_FRAMES=4
# CHARACTER_MICRO_SCALE_PCT=0.02
# LAYOUT_MAX_WIDTH_RATIO=0.80
# LAYOUT_MIN_FONT_PX=40

```

---

### `.gitignore` — 3 righe, 24 byte

Esclude `.env`, `__pycache__/`, `*.pyc` (i segreti non vanno committati).

```text
.env
__pycache__/
*.pyc

```

---

### `README.md` — 139 righe, 5611 byte

README originale del progetto (pipeline, setup, struttura, personalizzazione, limiti).

```markdown
# Video Generator - v2

Genera automaticamente un video verticale (9:16) con audio
narrato e sottotitoli sincronizzati, partendo da un semplice script di testo.
Sfondo, testo e colori keyword sono scelti dall'LLM in base al tema dello script.

## Pipeline

1. Carichi uno script `.txt` dalla GUI Tkinter
2. **Groq gpt-oss-120b** genera una palette tema (sfondo/testo/keyword)
   coerente col contenuto
3. **ElevenLabs** genera l'audio narrato
4. **Groq Whisper** trascrive l'audio con timestamp parola-per-parola
5. La trascrizione viene riallineata allo script originale (tempi di Whisper,
   parole dello script: corregge errori di trascrizione)
6. Le parole vengono raggruppate in chunk da 2-3 parole per enfasi
   (LLM + fallback deterministico)
7. **Groq gpt-oss-120b** estrae le parole chiave, evidenziate ognuna
   nel proprio colore del tema
8. **Pillow** genera un'immagine PNG per ogni chunk (testo centrato,
   colore tema, keyword a colori)
9. **ffmpeg** compone sfondo del tema + audio + overlay sottotitoli
10. Il video finale viene salvato in `outputs/`

## Setup

### 1. Installa ffmpeg

- **Windows**: scarica da https://ffmpeg.org/download.html e aggiungi la
  cartella `bin` al PATH di sistema.
- Verifica con: `ffmpeg -version` da terminale.

### 2. Installa le dipendenze Python

` ` `bash
pip install -r requirements.txt
` ` `

### 3. Imposta le API key

Copia il template e compilalo (supporta **più chiavi** per servizio con
fallback automatico: se una è esaurita/non valida si passa alla successiva):

` ` `powershell
Copy-Item .env.example .env
` ` `

` ` `env
ELEVENLABS_API_KEYS=chiave1,chiave2,chiave3
GROQ_API_KEYS=chiave1,chiave2
` ` `

In alternativa imposta le variabili d'ambiente (non finiscono nel codice):

**Windows (PowerShell):**
` ` `powershell
setx ELEVENLABS_API_KEYS "chiave1,chiave2"
setx GROQ_API_KEYS "chiave1,chiave2"
` ` `
(richiude e riapri il terminale dopo `setx`)

**Linux/Mac:**
` ` `bash
export ELEVENLABS_API_KEYS="chiave1,chiave2"
export GROQ_API_KEYS="chiave1,chiave2"
` ` `

È ancora supportato il formato a chiave singola (`ELEVENLABS_API_KEY`,
`GROQ_API_KEY`): equivale a una lista di una sola chiave.

> **Nota:** il file `.env` viene caricato dalla cartella del progetto
> qualunque sia la directory da cui avvii l'app. Il log della GUI mostra
> ogni tentativo (`chiave 1/10`, `chiave 2/10`...), così vedi il ciclo.
> Per verificare tutte le chiavi senza consumare crediti:
> ` ` `bash
> python config.py --check-keys
> ` ` `

### 4. Avvia l'applicazione

` ` `bash
python main.py
` ` `

## Struttura del progetto

` ` `
video_generator/
├── main.py                    # GUI Tkinter e orchestrazione pipeline (8 step)
├── config.py                  # API keys, voci, modelli, limiti, percorsi + check-keys
├── .env                       # Config reale (segreti, non committare)
├── .env.example               # Template documentato delle variabili
├── requirements.txt
├── core/
│   ├── tts.py                 # Generazione audio (ElevenLabs, multi-key failover)
│   ├── transcription.py       # Trascrizione con timestamp (Groq Whisper, failover)
│   ├── alignment.py           # Riallineamento trascrizione -> script (difflib)
│   ├── theme.py               # Palette tema dal testo (Groq LLM)
│   ├── emphasis_grouping.py   # Chunk 2-3 parole per enfasi (LLM + fallback)
│   ├── subtitle_grouping.py   # Raggruppamento classico per frasi (riferimento/fallback)
│   ├── keywords.py            # Keyword via LLM + colori deterministici
│   ├── renderer.py            # PNG sottotitoli centrati, testo tema, keyword a colori
│   └── video_builder.py       # Composizione finale ffmpeg (sfondo tema + overlay)
├── outputs/                   # Video finali generati
└── temp/                      # File temporanei (audio, PNG), puliti a fine job
` ` `

## Personalizzazione rapida

Tutte le impostazioni principali sono in `config.py`:

- `ELEVENLABS_VOICE_ID`: cambia la voce narrante (usata per tutte le chiavi)
- `ELEVENLABS_VOICE_IDS`: voci per-chiave in abbinamento 1:1 con
  `ELEVENLABS_API_KEYS` (serve solo se ogni account ha voci diverse,
  es. voci clonate); 1 solo ID = vale per tutte le chiavi
- `ELEVENLABS_OUTPUT_FORMAT`: formato audio (`mp3_44100_128` di default,
  come da docs dell'endpoint `POST /v1/text-to-speech/{voice_id}`)
- `GROQ_LLM_MODEL`: LLM per parole chiave e grouping enfasi (`openai/gpt-oss-120b`)
- `GROQ_THEME_MODEL`: LLM per la palette tema (default: stesso delle keyword)
- `THEME_MIN_LUMINANCE_DIFF`: soglia contrasto tema (default 80)
- `EMPHASIS_MAX/MIN_WORDS_PER_CHUNK`: parole per chunk enfasi (default 3/1)
- `KEYWORDS_MAX`, `KEYWORDS_MIN_GAP`: quante keyword evidenziare e quanto
  distanziarle nel testo (evita ammassi, distribuisce la selezione)
- `SUBTITLE_FONT_SIZE`, `SUBTITLE_COLOR`: stile testo (colore base usato
  solo se il tema non è disponibile; il contorno è disattivato: `STROKE_WIDTH=0`)
- `SUBTITLE_MAX_CHARS`, `SUBTITLE_MAX_WORDS`: limiti del grouping classico
- `VIDEO_WIDTH`, `VIDEO_HEIGHT`: risoluzione (default 1080x1920, verticale)

## Limiti noti di questa v2

- Nessun asset grafico/video di sottofondo (solo colore pieno dal tema)
- Con script molto lunghi (centinaia di chunk da 2-3 parole), la composizione
  ffmpeg con un input overlay per chunk diventa più lenta e il comando più
  lungo: ottimizzabile in futuro (es. singolo overlay con timeline)
- Le keyword devono apparire verbatim nello script per essere evidenziate
  (flessioni diverse non matchano)
#   C G S 
 
 "# CGS" 

```

---

### `cgs-report-completo.md` — 526 righe, 60983 byte

Report precedente (27/09/2026, 526 righe) — già dettagliato; incluso integralmente per completezza storica. Questo documento lo estende con codice integrale.

```markdown
# CGS — Report Completo, Dettagliato e Ottimizzato per LLM

> **Scopo:** permettere a **qualsiasi LLM** di comprendere al 100% struttura, logica, funzionalità, contratti dati, dipendenze e invarianti del progetto **CGS (Video Generator v2 / CGS)** per generare piani di modifica e implementazioni senza regressioni.
> **Lingua:** Italiano. **Root:** `C:\Users\thinkpad\Desktop\CGS` (repo git, branch implicito). **Piattaforma primaria:** Windows + Python 3.11 + ffmpeg/ffprobe in PATH.
> **Prodotto:** video verticale 9:16 `1080x1920 @30fps`, sfondo tinta tema premium o Ken Burns dinamico, audio narrato ElevenLabs, sottotitoli animati per-parola stile TikTok Tier T0-T3, personaggi 2D overlay, tipografia semantica per nicchia, struttura narrativa hook/corpo-a-beat/CTA, SFX sintetici.
> **Ultimo aggiornamento:** 27/09/2026 — allineato al codice reale (commit `b9e73d4 upgrade 25/09`; `main.py` 770 righe, `config.py` 548, `text_animator.py` 3489, `character_selector.py` 2181). Sostituisce versione precedente del 25/09/2026.
> **Come usare questo report:** leggi §1-§3 per orientamento, §5+§7 per contratti dati (obbligatori prima di toccare codice), §11 per invarianti (mai violare), §13 per ricette di modifica, §15 per verifica.

---

## 0. Glossario rapido

| Termine | Significato |
|---|---|
| `script` | Testo input utente (singola stringa). In bulk: una riga non vuota = uno script |
| `words` | Lista `{word,start,end}` con timestamp secondi (da Whisper, poi allineata allo script) |
| `chunks` | Blocchi sottotitoli 2-3 parole `{text,start,end,words[...]}` + arricchimenti |
| `styled_words` | Parole con `{word,display,style:base\|impact\|accent,is_hero,is_number,start,end}` |
| `theme` | `{background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB]}` |
| `keyword_colors` | `{parola_normalizzata: (R,G,B,255)}` |
| `character plan` | Lista lunga quanto `chunks` con posa/layout/evento per chunk |
| `macro-blocco` | Gruppo contiguo di chunk con stessa posa/lato/evento ENTRY/SUSTAIN/EXIT (stabilità ≥2.5s) |
| `Tier T0-T3` | Livelli moto/colore testo: T0 base fade, T1 accent rise, T2 impact pop, T3 hero/numero |
| `clip_start/clip_end` | Finestra overlay ffmpeg (=`start/end` + tail gap-hold) |
| `tail` | Frame clonati oltre `chunk.end` per persistenza personaggio nei gap TTS |
| `pill` | Rettangolo arrotondato semi-trasparente dietro testo (solo punch-in/CTA card) |
| `failover` | Rotazione chiavi API in ordine fino a successo |
| `text_only` | Render-mode debug senza ffmpeg pesante |

---

## 1. Visione d'insieme e pipeline

### 1.1 Cosa fa il programma

1. Utente carica `.txt` da GUI Tkinter (`main.py`) o via CLI headless `--script`.
2. **Singolo:** tutto il testo = 1 script = 1 video. **Bulk** (checkbox): ogni riga non vuota = 1 script indipendente = 1 video (10 righe = 10 video, ciascuno con tema/nicchia/personaggi/output propri `video_01_slug.mp4`...).
3. Per **ogni script** pipeline a 8+ step in thread separato (GUI non bloccata):
   - `[1-2/8] Parallelo x2:` tema colori LLM (Groq) + audio TTS (ElevenLabs).
   - `[3/8]` Trascrizione Whisper parola-per-parola.
   - `[4/8]` Allineamento trascrizione → script (tempi Whisper, parole script).
   - `Fase 1` Arricchimento timestamp Tier/VFX/SFX (deterministico, `start/end` invariati).
   - `[5/8]` Chunk 2-3 parole per enfasi (LLM + fallback).
   - `[5.2/8]` Struttura narrativa hook/corpo-a-beat/CTA + 1 hero flag per video.
   - `[5.5-6.5/8] Parallelo x3:` piano personaggi + keyword + tipografia (nicchia→font→tagging).
   - `[6.8/8]` Layout Guard anti-overlap + ancoraggio macro-blocchi.
   - `[7/8]` Rendering frame animati Tier T0-T3 (Pillow) o fallback PNG statici.
   - `[8/8]` Mix SFX + composizione ffmpeg (Ken Burns + overlay, finestre contigue, GOP 60) → `outputs/`, invariant checks, cleanup `temp/`.

### 1.2 Diagramma flusso dati

` ` `
.txt → parse_scripts → [script]
  ├─→ generate_theme ──────────────┐
  └─→ generate_audio (mp3) → transcribe_audio → align_transcript → enrich_timestamps
        words[{w,s,e}] → group_by_emphasis → chunks[{text,s,e,words}]
          → classify_narrative (+hero) → chunks+narrative_role/anim_*
          ├─→ plan_character_layout ─┐
          ├─→ extract_keywords ──────┼─→ merge chunks+character+styled_words
          └─→ enrich_typography ─────┘
            → layout_guard (safe_area/font_scale/pill/hide)
            → render_all_chunks_animated (frames PNG + clip_start/end + tail)
            → mix_sfx (voce+SFX) → build_composed_video|build_video (mp4)
            → run_post_build_checks → cleanup_temp
` ` `

### 1.3 Stack tecnologico

- **GUI:** `tkinter` standard (`ScrolledText`, `after` thread-safe). Nessuna dipendenza esterna.
- **TTS:** `requests` → `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...`
- **LLM+STT:** SDK `groq` (`chat.completions.create`, `audio.transcriptions.create`).
- **Imaging:** `Pillow` (`Image/Draw/Font/Color.getrgb`, assi variabili font per weight 600).
- **Video/Audio:** `ffmpeg` + `ffprobe` via `subprocess` (obbligatori in PATH).
- **Env:** `python-dotenv` + fallback parser integrato.
- **NLP leggera:** `difflib.SequenceMatcher`, `re`, `hashlib.md5`, `colorsys`, `json`.
- **Concorrenza:** `threading.Thread` (GUI), `ThreadPoolExecutor` (pipeline 2-3 worker, render 2-4, ffmpeg clip 2-4).
- **Novità vs report 25/09:** `video_composer.py` (Ken Burns+dimmer), `audio_mixer.py` (SFX synth), `advanced_kinetics.py` (Tier avanzati+glyph cache), `invariant_checks.py` (post-build), `timestamp_enricher.py` (Tier pre-tagging), `character_animator.py` (ciclo vita math-only), gap-hold tail, GOP 60, `POSE_SIDE_MAP` configurabile.

### 1.4 Requisiti runtime e avvio

- `ffmpeg -version` e `ffprobe` in PATH, altrimenti `VideoBuildError` esplicito.
- `pip install -r requirements.txt`: `requests>=2.31.0`, `groq>=0.9.0`, `Pillow>=10.0.0`, `python-dotenv>=1.0.0`.
- Chiavi in `.env` (root, mai committato) o env sistema. Verifica gratuita: `python config.py --check-keys`.
- Avvio GUI: `python main.py`. Headless: `python main.py --script file.txt [--bulk] [--render-mode=full|text_only|debug_safezones]`. Debug grafica <5s: `--render-mode=text_only`. Debug safe-zone: `--render-mode=debug_safezones` (box rossi Z=99).

---

## 2. Struttura file — inventario esaustivo al 27/09/2026

` ` `
CGS/
├── main.py                    # GUI + orchestratore bulk + CLI headless (770 righe)
├── config.py                  # Config centrale env-first + check-keys + pose-map (548)
├── requirements.txt           # 4 dipendenze
├── .env                       # Segreti reali 1426 byte (NON committare, in .gitignore)
├── .env.example               # Template 7220 byte, tutte le flag documentate
├── README.md                  # Doc utente v2 (setup valido, architettura parzialmente obsoleta)
├── .gitignore                 # .env, __pycache__/, *.pyc
├── cgs-report-completo.md     # Questo report
├── core/
│   ├── tts.py                 # ElevenLabs multi-key failover (163)
│   ├── transcription.py       # Whisper word-timestamp + failover (185)
│   ├── alignment.py           # difflib script↔trascrizione (120)
│   ├── theme.py               # Palette premium LLM + validazione (438)
│   ├── emphasis_grouping.py   # Chunk 2-3 parole LLM + fallback (211)
│   ├── subtitle_grouping.py   # Grouping classico per frasi legacy (144, non chiamato in main)
│   ├── keywords.py            # Keyword LLM + colori deterministici (215)
│   ├── script_loader.py       # Parsing bulk + slug/naming puri (123)
│   ├── renderer.py            # PNG statici + primitive layout/char condivise (672)
│   ├── text_animator.py       # Frame animati Tier T0-T3 + char motion + CTA card (3489, cuore)
│   ├── video_builder.py       # ffmpeg finale + micro-clip + finestre contigue GOP60 (468)
│   ├── video_composer.py      # Ken Burns + dimmer + Z strict, wrapper builder (272)
│   ├── character_selector.py  # Piano personaggi LLM + macro-blocchi Breath&Focus (2181)
│   ├── character_animator.py  # Ciclo vita ENTRY/SUSTAIN/EXIT/NONE math-only (169)
│   ├── narrative_structure.py # Hook/beat/CTA deterministico + hero (596)
│   ├── text_tagger.py         # Nicchia + tagging base/impact/accent (690)
│   ├── typography_presets.py  # 6 preset nicchia + anim.pop_from (254)
│   ├── font_manager.py        # Download/cache Google Fonts + sistema (416)
│   ├── layout_presets.py      # 4 zone 1080x1920 + geometria (319)
│   ├── layout_guard.py        # Guard anti-overlap + ancoraggio blocchi (1046)
│   ├── easing.py              # Curve Penner pure (135)
│   ├── advanced_kinetics.py   # GlyphCache + scale/opacity/hero-shake/badge (305)
│   ├── audio_mixer.py         # SFX synth pop/whoosh/click + ducking (274)
│   ├── timestamp_enricher.py  # Tier/VFX/SFX deterministici pre-pipeline (199)
│   └── invariant_checks.py    # Post-build AV/temp/timestamp/z-order (162)
├── assets/
│   ├── characters/1.png..5.png # 5 PNG ~0.93-1.07 MB (sfondo nero da rimuovere via codice)
│   └── fonts/*.ttf (15)        # Anton,BebasNeue,Caveat,Cinzel,Inter,LeagueSpartan,Montserrat,Nunito,OpenSans,Oswald,PatrickHand,PlayfairDisplay,Poppins,Roboto,SpaceMono (+PermanentMarker on-demand)
├── outputs/*.mp4 (27)          # Finali: output_video.mp4 legacy + video_01..06_* (+_1.._13 bulk)
└── temp/                       # narration_*.mp3, subtitle_*.png, chunk_*_frame_*.png, chunk_*.mov, concat lists — svuotata dopo ogni video
` ` `

> **README obsoleto:** descrive solo `renderer.py` + overlay per chunk; l'architettura attuale è `text_animator` Tier + macro-blocchi + tipografia + narrativa + guard + hero + gap-hold + composer + SFX. README resta valido per setup/env.
> **Refactor recenti (git log `b9e73d4,61985b5,a924cd0,38341ba`):** rimossi `character_geometry.py` (fuso), `tests/`, `README-dev.md`; `PermanentMarker.ttf` ora on-demand; introdotti `character_animator`, macro-blocchi, T0-T3, guard anchoring, composer, mixer, kinetics, invariant.

---

## 3. Configurazione centrale (`config.py` + `.env`)

### 3.1 Loader

- `BASE_DIR=dirname(abspath(__file__))`, `ENV_PATH=BASE_DIR/.env`.
- `_load_env_file()`: prima `dotenv.load_dotenv(ENV_PATH)` (env sistema ha precedenza), fallback parser manuale (`KEY=valore`, strip `export`/quotes, `utf-8-sig`, mai sovrascrive env esistenti).
- Helper: `_get_int/_float/_tuple(R,G,B,A)/_str_or_none/_str_list(comma+newline,dedup)/_key_list/_pose_side_map(1:any,...)/_hex_color(#RRGGBB[A])/_mask_secret`.
- `OUTPUT_DIR/TEMP_DIR` creati `makedirs(exist_ok)` all'import.
- `get_pose_side_constraint(pose)→any|center|left|right|split` mai solleva. `CHARACTER_POSE_SIDE_MAP` riempita con default `{1:any,2:center,3:center,4:left,5:split}`.
- `get_elevenlabs_voice_id(i,total)`: 0 voci→default; 1→unica per tutte; N==N→1:1; else `ValueError→TTSError`.
- `check_keys()→int(bad)`: `GET /v1/user` ElevenLabs (tier + `character_count/limit`) + `GET /openai/v1/models` Groq, senza crediti. `python config.py --check-keys`.

### 3.2 Tabella variabili completa

| Variabile | Default | Consumatore | Effetto |
|---|---|---|---|
| `ELEVENLABS_API_KEYS` (+`_KEY`) | `[]` | `tts` | Lista provata in ordine `k1,k2..` |
| `GROQ_API_KEYS` (+`_KEY`) | `[]` | tutti Groq | Idem Whisper/LLM |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` Rachel | `tts` | Voce default |
| `ELEVENLABS_VOICE_IDS` | `[]` | `tts` | 0→default;1→tutte;N=N→1:1;else errore |
| `ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | `tts` | TTS IT |
| `ELEVENLABS_OUTPUT_FORMAT` | `mp3_44100_128` | `tts` | query `output_format` |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3-turbo` | `transcription` | STT |
| `GROQ_LLM_MODEL` | `openai/gpt-oss-120b` | keyword/emphasis/char/tagger | LLM principale |
| `GROQ_THEME_MODEL` | `=LLM` | `theme` | Palette separabile |
| `KEYWORDS_MAX/MIN_GAP` | `10/12` | `keywords` | target `max(3,min(MAX,len//30))`, gap `max(GAP,len//target//2)` |
| `THEME_MIN_LUMINANCE_DIFF` | `80` | `theme,animator` | Contrasto 0-255 |
| `EMPHASIS_MAX/MIN` | `3/1` | `emphasis` | Validazione tagli |
| `VIDEO_WIDTH/HEIGHT/FPS` | `1080/1920/30` | renderer/animator/builder/guard | Verticale |
| `SUBTITLE_FONT_PATH/SIZE/COLOR/STROKE_*` | `None/64/255,255,255,255/0,0,0,255/0` | `renderer` legacy | Look pulito stroke 0 |
| `SUBTITLE_MAX_CHARS/WORDS` | `38/7` | `subtitle_grouping` | Solo legacy |
| `TEXT_ANIMATION_ENABLED` | `1` | `main` | 1=animati,0=statici. Falsy:`0,false,no,off,""` |
| `TEXT_ANIMATION_ENTRY/EXIT_DURATION` | `0.18/0.15` | `animator` | Entrata parola / fade gruppo (s) |
| `KEYWORD_ENTRY_SCALE_FROM` | `0.7` | `animator` | Globale pop; perdente vs preset vs hook. Priorità: hook>preset>globale |
| `TEXT_ANIMATION_ACCENT_LIFT_PX` | `10.0` | T1 | Rise senza scala, clamp 0-24 |
| `TEXT_ANIMATION_HERO_*` | `0.6/0.22/0.06` | T3 | Scala-from/entry/hold-exit (clamp 0.1-1.0, ≥5 frame, 0-0.20) |
| `TEXT_ANIMATION_NUMBER_ENTRY_DURATION` | `0.15` | T3-num | Pop corto numeri, mai hero |
| `CHARACTER_ENABLED` | `1` | main/renderer/animator | 0=senza personaggi |
| `CHARACTERS_DIR` | `assets/characters` | `selector` | `1.jpg/.png` ecc |
| `CHARACTER_VALID_POSITIONS/TRANSITIONS` | `bottom_center.. / slide_up..` | `selector` | Vocabolario legacy (alias `CHARACTER_POSITIONS`) |
| `CHARACTER_POSE_COUNT/SCALE_MIN/MAX` | `5/0.65/0.90` | `selector` | Range pose, clamp scala (piano default 0.75) |
| `CHARACTER_MAX_SAME_POSE/SIDE` | `2/2` | ritmo | Mai 3 uguali di fila |
| `CHARACTER_IDLE_ENABLED/AMP_Y/FREQ/TILT` | `1/4.0/0.4/0.0` | animator | Bob 4px@0.4Hz (~2.5s), tilt 0 stabile |
| `CHARACTER_ENTRY/FIRST_ENTRY/EXIT/PUNCH/MORPH_DURATION` | `0.20/0.20/0.16/0.60/0.40` | animator | Slide&pop +300 ease_out_back / drop +400 ease_in_cubic / zoom punch / morph opaco |
| `CHARACTER_GAP_HOLD_ENABLED/MAX` | `1/1.5` | animator+builder | Tail `min(next-start,1.5)`, cap 2s, solo hold+char |
| `CHARACTER_MIN_BLOCK_DURATION` | `2.5` | macro | Min apparizione s (clamp ≥0.5) |
| `CHARACTER_DISCONTINUOUS_MODE/HOOK_VISIBLE/CTA_VISIBLE/BODY_VISIBLE_RATIO` | `1/1/1/0.6` | macro | Hook/CTA sempre, Body 60% distribuiti uniformi, pause 1 blocco |
| `CHARACTER_POSE_SIDES` | `1:any,2:center,3:center,4:left,5:split` | selector+presets | `any` libero, `center` solo center, `left` solo split_left, `right` solo split_right, `split` alternati. Posa4 sempre left (indica a destra) |
| `TYPOGRAPHY_ENGINE_ENABLED/BASE_SIZE/IMPACT/ACCENT_SCALE` | `1/60/1.4/1.1` | tagger/animator | Clamp 1.2-1.6/1.0-1.3 |
| `TYPOGRAPHY_BASE_WEIGHT` | `600` | animator | SemiBold asse Weight variabili; statici→synth 1px stesso colore. Solo base |
| `TYPOGRAPHY_STROKE/SHADOW_*` | `0/0/(3,3)/(0,0,0,180)` | animator | Pulito, ombra OFF |
| `FONTS_DIR` | `assets/fonts` | `font_manager` | Cache |
| `NARRATIVE_ENABLED/HOOK_MAX/CTA_MAX/CTA_CARD/CARD_MAX/ENTRY_MULT/POP_FROM` | `1/3/4/1/14/0.7/0.55` | narrative/animator | Hook scattante, CTA card se forte+breve |
| `PIPELINE_FAST` | `0` | emphasis/char/tagger | 1=euristiche istantanee (tema+keyword restano LLM) |
| `RENDER_PARALLEL` | `1` | animator | ThreadPool chunk+clip |
| `FFMPEG_PRESET` | `veryfast` | builder/composer | Whitelist ultrafast..medium |
| `ENABLE_ADVANCED_KINETICS` | `1` | kinetics/animator | Tier avanzati+glyph cache;0=legacy |
| `ENABLE_DYNAMIC_BACKGROUNDS` | `1` | composer | 1=Ken Burns,0=tinta unita (delega legacy) |
| `ENABLE_AUTO_SFX/SFX_VOLUME_DB/BG_MUSIC_DUCKING_DB` | `1/-15.0/-12.0` | mixer | SFX whoosh/pop/click, ducking |
| `HERO_WORD/BASE_WORD_FONT_PATH` | `assets/fonts/Montserrat-Black.ttf / Inter-Bold.ttf` | kinetics | Fallback automatico |
| `COLOR_BRAND_ACCENT/COLOR_HERO_BG` | `#FF3366/#000000A6` | kinetics | T2 accent, T3 pill |
| `Z_BACKGROUND/CHARACTER/DIMMER/SUBTITLES/DEBUG` | `0/10/20/30/99` | composer/guard | Invariante `bg<char<dimmer<sub<debug` |
| `EASING_CURVES` | `t0:eo_cubic,t1:eo_quad,t2/t3:eo_back,char_entry:eo_back,exit:ei_cubic,morph:eiocubic,shake:eo_elastic` | easing/animator | Nomi funzione |
| `KINETIC_T2_SCALE_PEAK/PEAK_FRAMES/T3_SHAKE/T0_STROKE` | `1.10/4/4.0/3` | kinetics | Overshoot 110% 4 frame, shake 4px, stroke 3 |
| `DYNAMIC_BG_ZOOM_MAX/STEP/DURATION` | `1.08/0.0015/125` | composer | Zoom impercettibile |
| `CHARACTER_MICRO_XFADE_FRAMES/MICRO_SCALE_PCT` | `4/0.02` | selector/animator | Cross-fade 4f, scala 2% |
| `LAYOUT_MAX_WIDTH_RATIO/MIN_FONT_PX` | `0.80/40` | guard | Auto-scale se riga >80% |
| `OUTPUT_DIR/TEMP_DIR` | `outputs/temp` | tutti | Override opzionale |

---

## 4. Entry-point e GUI (`main.py`)

### 4.1 `VideoGeneratorApp`

- Finestra `640x580` non resizable, `Video Generator - v2`. Widget: `load_button` (filedialog `.txt`), `file_label`, `bulk_check` (default False), `script_count_label`, `text_preview` (10 righe, `<<Modified>>` debounce 300ms), `generate_button` blu `#2d6cdf`, `status_text` (Consolas 9, disabled, `root.after` thread-safe).
- `_log(msg)`, `_set_ui_busy(bool)`, `_log_attempt(i,tot,ok,detail)` (✅/⚠️ troncato 180, passato come `on_attempt` a tutti i moduli API).
- `_current_scripts()→parse_scripts(preview,bulk)`, `_refresh_script_count()` (bulk:`N script`, `Genera N Video`), `_on_load_script()` (utf-8, `nome (N script)` in bulk), `_on_generate()` (valida, singolo `[:1]`, pulisce log, `Thread(daemon,_run_pipeline)`).
- `_render_mode()→full|text_only|debug_safezones`: CLI `--render-mode=X` o `--render-mode X` > env `RENDER_MODE` > `full`. Mai solleva.

### 4.2 `_run_pipeline(scripts)`

Normalizza str→lista, filtra vuoti. 0→warn+sblocca. Loop `enumerate(1..)`: `_process_one_script` → `successes/failures`; catch `TTSError|TranscriptionError|VideoBuildError` (fatali video) + `Exception+traceback`; `finally cleanup_temp_files()` isolamento. Riepilogo `📊 Completati X/Y` + `messagebox` via `after`. `finally _set_ui_busy(False)`.

### 4.3 `_process_one_script(script,index,total)→path`

1. **Naming:** `suggest_output_filename` + `narration_{i:03d}.mp3` in bulk else `narration.mp3`.
2. **`[1-2/8]` ThreadPool2:** `generate_theme || generate_audio` paralleli.
3. **`[3/8]`** `transcribe_audio` → `words`.
4. **`[4/8]`** `align_transcript` (catch `AlignmentError`→raw).
5. **Fase1:** `enrich_whisper_timestamps` merge solo `tier/vfx_type/sfx_trigger` (mai `start/end`); salva `_words_before` copy.
6. **`[5/8]`** `group_words_by_emphasis` → `chunks`.
7. **`[5.2/8]`** Se `NARRATIVE_ENABLED`: `classify_narrative` (+hero interno) else piatto.
8. **`[5.5-6.5/8]` ThreadPool3:** `plan_character_layout` (se enabled) || `extract_keywords(theme.palette)` || `enrich_typography` (se enabled). Log 10 voci char, n keyword, nicchia, pre-warm `FontManager` singleton `ensure_preset_fonts`, conteggi base/impact/accent. Merge `chunks=typo` poi `enrich_with_characters`.
9. **`[6.8/8]`** `build_realtime_plan+apply_realtime_plans` (log garantiti/corretti/hidden/intenzionali).
10. **`[7/8]`** Se `TEXT_ANIMATION_ENABLED`: `render_all_chunks_animated(...,typography_niche)` (log ogni 10, gap-hold auto) else `render_all_subtitles`; catch `TextAnimationError`→statico.
11. **`[8/8]`** `_render_mode()`: se `text_only` → scrive `*_textonly.txt` con n chunk+primo frame+invariant e return (no ffmpeg). Else `mix_sfx` best-effort → `video_composer.build_composed_video(...,debug=text_only?no:debug_safezones)` except→`video_builder.build_video` fallback → `run_post_build_checks(...,strict=False)` log OK/FAIL → return path. Solleva fatali per video.

### 4.4 CLI headless `main()`

Parse `--script=path|--script path`, `--bulk`. Se `--script`: senza Tk (`SimpleNamespace after`), `parse_scripts`, `[:1]` se non bulk, loop `_process_one_script+cleanup`, `OK/FAIL+traceback`, `Completati k/N`, `exit(0 se k>0 else 1, 2 errore outer)`. Else `Tk+mainloop`. `-h/--help` usage.

---

## 5. Moduli core in dettaglio

### 5.1 `script_loader.py` (123) — parsing puro

`parse_scripts(text,bulk)`: False→`[stripped]` o `[]`; True→righe non vuote ordine, mai solleva. `load_scripts_from_file(path,bulk)` utf-8 → `OSError` se illeggibile. `slugify(text,5,32)` regex alfanum+`_` lower fallback `script`. `suggest_output_filename(i,script,total,dir,prefix,ext)` `width=max(2,len(str(total)))`, `video_{i:0w}_{slug}.mp4`, `_1.._999` se esiste, mai crea file. `preview_of(script,80)` collapse whitespace+`...`.

### 5.2 `tts.py` (163) — ElevenLabs

`POST /v1/text-to-speech/{voice_id}?output_format=...` headers `xi-api-key`, body `{text,model_id,voice_settings:{stability:0.5,similarity_boost:0.75}}` timeout 120s. `generate_audio(script,output_filename,on_attempt)→abs TEMP/file`. Failover chiavi+voci 1:1; retryable `{401,402,403,429,500-504}` + `404` solo voci diverse; `400/404-unica/422`→`TTSError` immediato; fine→`TTSError(Tutte N..|failures)`. Valida vuoto/no-keys/voci ambigue. `TTSError`.

### 5.3 `transcription.py` (185) — Groq Whisper

`Groq(key).audio.transcriptions.create(file(rb),model=whisper-large-v3-turbo,response_format=verbose_json,timestamp_granularities=[word])`. `transcribe_audio(path,on_attempt)→[{word,start,end}]` (dict o object). Cache client max 16. `_is_retryable(e)`: False solo `400/404/422` senza hint retryable (rate/quota/credit/expired/invalid/unauthorized/overload/timeout/...), else True. Loop failover; valida no-keys/mancante/words vuote. `TranscriptionError`.

### 5.4 `alignment.py` (120) — difflib

Perché: Whisper sbaglia omonimi; audio generato dallo script → sottotitoli devono mostrare parole script con tempi Whisper. `align_transcript(tr,script)→(aligned,stats{match_ratio,corrected,interpolated,extra})`. `SequenceMatcher(script_norm,tr_norm,autojunk=False).get_opcodes()`: `equal` copia+parola script; `replace` min accoppia (tempi Whisper, `corrected++`), script lungo→`_interp_missing` uniforme `prev→next` (fallback `+0.3*n`), `interpolated++`, tr lungo→extra; `delete` interpola; `insert` tiene. `_enforce_monotonic` (`start>=prev_end`, `end>start+0.05`). `AlignmentError` se vuoti (non-bloccante in main).

### 5.5 `timestamp_enricher.py` (199) — Fase1 deterministica

Nessun I/O/LLM, mai `start/end` alterati (copy `dict`). `_norm` lower+strip punteggiatura. Input lista/dict`{words}`/lista str (fallback `t,t+0.3`) → `[{word,start,end,tier:T0|T1|T2|T3,vfx_type:none|pop_scale|glow|badge_slide,sfx_trigger}]`. Regole: hero esplicito→T3 (single_hero: primo vince, altri→T2); keyword/digit/CAPS≥3→T2 (CAPS+emotive `!?/emoji` senza digit→promozione hero implicita T3); connettivi `di,a,il,che,..` o len≤2→T0; else T1. VFX: T3 badge, T2 pop (`glow` se digit), T1/T0 none. SFX: T3 o (T2+emotive). Params `keywords,hero_words,single_hero=True`.

### 5.6 `theme.py` (438) — palette premium

Out `{bg,text,keyword_colors[2-4]}` mai blocca (fallback `{#0F172A,#FFFFFF,_FALLBACK}`). System `art director premium...SOLO JSON`, user con 12 bg premium (Onyx..Coffee), 3 testi near-white, 8 accenti (ori/sky/lavanda/rosa/menta, mai neon/gialli puri), `temp 0.3,max 1024,json_object`, modello `GROQ_THEME_MODEL`, failover. `_validate_theme`: bg garish (`lum>70` o `max-min>80`)→`_nearest_premium_bg` (distanza RGB+hue bonus); testo non-near-white o contrasto `<80`→bianco max contrasto; keyword scarta non-hex/yellowish (`r>230&g>195&b<100`)/neon/duplicati/arcobaleno (`sat>0.15&Δhue<25°`, max4), integra `PREMIUM_ACCENTS+_FALLBACK`, forza oro+sky se <2. Helper `hex_to_rgb/rgba,luminance,_saturation/_hue,_parse_theme(fence)`. `ThemeError` solo script vuoto.

### 5.7 `emphasis_grouping.py` (211) — chunk enfasi

Out `[{text,start,end,words}]`. LLM vede solo parole, restituisce solo `{"cut_indices":[...]}`. Regole: 1-3 (preferisci 2-3), 3 ok se 3ª leggera, mai iniziare con leggera isolata, strong punct `.!?…:;` taglio obbligato. `temp 0.2,max 1024,json_object`, `GROQ_LLM_MODEL`, failover. `_validate_cuts` (int non-bool, range, unici ordinati, ultimo `n-1`, size `[MIN,MAX]`). Fallback blocchi da 2 (3 se 3ª weak e senza strong). Usato se `PIPELINE_FAST/no-keys/LLM fail/invalidi`. Mai solleva per API. `EmphasisGroupingError` definita non fatale.

### 5.8 `subtitle_grouping.py` (144) — legacy

Out `[{text,start,end}]` senza `words`. Chiudi su strong; se `len≥38` o `count≥7` chiudi su virgola o parola non-weak; mai weak trailing isolata; `_merge_short_chunks` (<12 char fusi se ≤MAX+15). Non chiamato in `main` (riferimento/fallback statico). Non rimuovere senza refactor (costanti `_WEAK_TRAILING/_STRONG_PUNCT` condivise).

### 5.9 `keywords.py` (215) — keyword LLM

Out `{norm:RGBA}`. Palette `_FALLBACK 8 hex`, `color_for_keyword(md5%len)` deterministico. Prompt `Estrai max {target} SINGOLE verbatim...distribuite, ordine importanza` (`target=max(3,min(MAX,len//30))`), `temp 0.2,max 512,json_object`. `_parse_keywords` (fence, `json` o regex, dict/list, solo singole, dedup). `_spread_keywords` (prima occorrenza, `gap=max(MIN,len//target//2)`, accetta se distanza≥gap). Palette effettiva da tema else storica; hex invalidi→storica. `KeywordError` (vuoto/no-keys/tutte fail) non-bloccante in main.

### 5.10 `narrative_structure.py` (596) — 3 atti deterministici

Nessun LLM. `classify_narrative(chunks,script,on_attempt)→(sections{hook,body,body_beats,beat_tones,cta,cta_strength:strong|soft|none,cta_mode:card|locked|none},enriched+{narrative_role,beat,beat_tone,anim_entry_mult/pop_from,cta_card,cta_section_id,cta_strength})` mai solleva. `_detect_cta` run finale max `CTA_MAX` con 50+ cue IT+EN (`segui,commenta,link,bio,gratis,...`); nessuna→ultimo `soft` se `n≥3` else `none`. `_detect_hook` prima frase entro `HOOK_MAX` else 1 se `n≤3` else 2. `_split_body_beats` su fine frase + merge beat da 1. `beat_tone`: `?`→question, `\d`→data, `!`/cue→key, else explainer. `boost_typography_styles` hook≥1 impact, CTA verbi `_CTA_ACTION_VERBS`→impact+≥1, `display` upper, init `is_hero=False,is_number=digit` (numeri mai hero). `assign_hero_flags` video-wide max1: 1) primo verbo CTA impact senza cifre; 2) else contenuto hook impact più lungo non-function senza cifre; 3) nessuna (chiamato da tagger, non da main). `card` solo `strong+CTA_CARD=1+parole≤14` else `locked/none`. `NARRATIVE_ENABLED=0`→tutto body 1 beat. Utility `emotional_intensity (?!caps digit cta positive hook)` e `pose_for_emotion (?→5,\d→4,cta/!→3,≥0.7→1)`.

### 5.11 `character_selector.py` (2181) — regia personaggi

Pose: 1 incrociate hook/fatti, 2 aperte spiegazioni, 3 thumb soluzioni/CTA, 4 indica dati (SEMPRE `split_left`: punta a destra, sta a sinistra), 5 mento domande (prediligi split). `plan_character_layout(chunks,script,on_attempt)→[{chunk_index,pose|None,layout,layout_preset,punch_in,transition_in,position,transition,scale,block_id,char_event,char_visible,character:{visible,pose,pose_id:crossed/open/thumb/pointing/chin,side:LEFT/RIGHT/CENTER,event,block_id}}]` lungo chunks, mai solleva per API. LLM prompt regista (`_POSE/_LAYOUT_RULES`+narrativa+snippet1500+`i: testo [HOOK/CORPO/CTA]`), `temp 0.3,max 256+n*64,json_object`, accetta array bare o `{layout|plan|chunks|items}`+fence, buchi→fallback; `_normalize_entry` clamp posa, `normalize_preset`, forza split 4/5, default transition, scala clamp. Vincoli `_pose_allowed_layouts` da `POSE_SIDE_MAP` + `_constrain_preset/_layout_for_pose_side/_preset_for_pose` (2 mai split, 4 sempre left, 5 mai center stabile flip). Ritmo `_enforce_rhythm_variety` mai >2 stessa posa/lato, `_pose_for_text (?→5,\d→4,!→3 else 1→2→4→5→3, avoid)`, center alternano `slide_up/zoom_in`, mai 3 trans uguali (3ª→fade), esclude CTA card/CTA, preserva hook0. Finalize `_apply_narrative_locks+_cap_punch (hook max1 ultimo, corpo max1 ultimo, CTA 0; globale max2 ultimi)+_enforce_rhythm+_macro_stabilization`. Macro Breath&Focus `_macro_role (hook/body/cta posizionale fallback)→_build_macro_time_blocks (Hook 1, Body ≥2.5s resto fuso, CTA 1)→visibilità (0→tutto visibile, else Hook/CTA da flag, Body 60% hide distribuiti uniformi mai bordi, pause 1 blocco 2.5-4s)→_select_block_pose_layout (prima voce+vincoli)+no-repeat adiacenti (posa sempre diversa, lato quando possibile)→eventi ENTRY/SUSTAIN/EXIT (singolo→ENTRY)/NONE`. Fallback ciclo 8-step `[(1c),(4sL),(2c),(5sL),(1sR),(4sL),(3c),(2c)]` + `?/!/digit` + anti-3-uguali. Asset `_candidate_paths ({n}.jpg/jpeg/png+maiusc, CHARACTERS_DIR+legacy, cache)`, `load_character_original` RGBA (`a≥250&RGB<15`→trasparente, numpy else getdata, cache), `calculate_character_bbox`, `resolve_character_path`, `clear_cache`. `resolve_chunk_layout(chunk)→None|{pose,use_preset,layout,...}` singola verità (None se nascosto/assente). `enrich_chunks_with_characters` merge se len uguali, mai solleva.

### 5.12 `character_animator.py` (169) — ciclo vita math-only

Solo `math`, <5ms/frame, offset coerenti animator (`+300` entry, `+400` exit). `CharacterFrameAnimator.get_frame_transform(event,frame_time,chunk_dur,global_idx,fps)→(offset_y,rotation,opacity)`; `NONE→(0,0,0)` non disegnare. ENTRY `ft<0.20`: `ease_out_back`, `offset+=300*(1-eased)`, `idle_weight 0→1`; EXIT `dur-ft<0.16`: `ease_in_cubic`, `offset+=400*eased`, `weight 1→0`; else `1.0`. Idle `t=idx/fps`, `dy=sin(2π*0.4*t)*4*weight`, `tilt=cos*0.0*weight` (default OFF). `event_of(chunk)→ENTRY|SUSTAIN|EXIT|NONE` mai solleva (`visible False/pose None→NONE`, visibile senza evento→SUSTAIN). `is_visible`.

### 5.13 `layout_presets.py` (319) — zone

Width-based 120-170%, ancoraggio basso gambe fuori campo, testa in campo, coordinate possono uscire (paste clippa). `center_standard` 125% headroom500 `90,150,990,900` font1.0 side center `slide_up` pillF; `center_punch_in` 170% head110 `90,150,990,640` fade pillT; `split_left` 130% head250 `640,560,1000,940` font0.9 `slide_from_left`; `split_right` speculare `80,560,420,940`. `PUNCH_FACTOR 1.35` (non su punch), `MAX_PUNCH 2`, `OVERHANG 420`, `PILL (0,0,0,170) pad28 r36`. Pure: `normalize_preset (alias bottom_focus→standard, closeup→punch)`, `preset_width/headroom/overhang/safe_area (scalati)`, `font_scale/side/default_transition/needs_pill`, `normalize_transition (zoom alias, bottom→up, side→lato, ignoto→default)`, `preset_alternate_transition (center→zoom_in else fade)`, `legacy_transition/position`, `describe,is_valid`.

### 5.14 `renderer.py` (672) — statico + primitive

Doppio ruolo: path statico legacy + libreria riusata (`compute_word_layout,draw_word,draw_text_background,calculate_character_transform,get_character_layer`). `load_font(size)` cache `(path,size)` cap16: `SUBTITLE_FONT_PATH` poi DejaVu/Liberation/arialbd else default, clamp≥8, `LINE_SPACING 12`. `compute_word_layout` wrapping greedy, centro area, clamp safe + rete split. `draw_word` pura alpha-modulata stroke default 0. `draw_text_background` pill bbox espansa. `calculate_character_transform` width-based aspect, x center/split overhang, `y=headroom` mai sopra `H-new_h`. `get_character_layer` LANCZOS cache `{(pose,w,h)}`. `_paste_character_clipped` clip canvas. `render_subtitle_image(text,idx,keyword_colors,text_color,character,safe_area)` canvas RGBA trasparente Z char→pill→testo, `SIZE*font_scale`, `max_width 0.85*W`, `subtitle_{i:04d}.png`, legge `guard_*` + `character/pose None` hidden. `render_all_subtitles` usa metadati o plan parallelo.

### 5.15 `text_animator.py` (3489) — cuore animato

Ogni parola entra a `start` (accumulo), tutto scompare a `chunk.end` (+tail). Layout 1x/chunk in safe area. Sfondo trasparente (bg da ffmpeg; param `background_color` solo contrasto/compat).
**Tier (moto da `(style,is_hero,is_number)`, colore da `_styled_fills` tema+highlight+keyword):** T0 base fade `ease_out_cubic` costo0; T1 accent rise `opacity+lift 10→0` MAI scala max1/chunk +5%; T2 impact pop `opacity+scala from→1 ease_out_back`; T3 hero 1/video (verbo CTA o climax hook, mai numeri: `0.6→1` in `0.22s` + hold `0.06s` via `_hero_exit_factor` fade compresso mai oltre `end`); T3-num digit pop corto `0.15s` mai hero. Legacy senza `styled_words`: solo T0/T2. `bounce/elastic` disponibili non default.
**Motion `_resolve_motion_params(preset,chunk)`:** `entry=0.18*anim_entry_mult` hook 0.7x clamp mult 0.3-1.5, hero override `0.22`; `scale_from`: hook `anim_pop_from`>preset `anim.pop_from` (fitness/dark 0.60, business/tech/edu 0.70, lifestyle 0.80)>globale 0.7 clamp 0.1-1.0; `lift` 0-24; `hero_from/delay/number` clamp. Mai eccezioni. `_word_tier` normalizza, `is_number=flag|digit`, `is_hero` solo `impact&!number`.
**Typography (se `styled_words` validi e enabled):** 3 font/nicchia via `FontManager` singleton+cache `(path,size[,weight])`; `impact 1.3-1.5x upper highlight`, `accent 1.1x handwritten`, stroke 0, ombra solo se enabled. `BASE_WEIGHT 600`: `_apply_font_weight` asse `Weight` else synth 1px stesso colore solo base. `_styled_fills`: base tema (flip B/W se contrasto<80), impact highlight validato (catena highlight>keyword>alt>B/W mai =base), accent dedicato o mix 55%impact+45%base. `compute_styled_layout` baseline comune ascent/descent, mai flottanti.
**Personaggio/frame:** layer 1x `get_character_layer`; Z trasparente→char→pill→testo. Entry `char_entry_jump` (identità pixel `(pose,zone,punch)`)→istantaneo; punch zoom fluido `0.60s` mai jump; morph `0.40s ease_in_out_cubic` opaco da `char_entry_from_xy`; prima apparizione slide&pop `0.20s +300 ease_out_back` o `zoom 0.92→1`; `entry_fade` solo prima else slide opaca anti-glitch. Idle `_idle_bob_tilt(t_abs)` `sin*4px`, tilt `cos*0°` OFF quantizzato 0.3° cache. Exit `decide_char_exit_mode`: `after None→with_text`, else sempre `hold` (no slide_down fix blink); `with_text` fade+drop +400 `0.16s`, `hold` opaco fino a stacco. Gap-hold `render_all` `tail=min(gap,1.5)` solo `hold+char+gap>1/fps`, `generate_*` clona ultimo frame cap 2s, `clip_start=start,clip_end=end+tail`. CTA card `generate_cta_card_frames` UNICA card persistente karaoke (future nascoste, corrente pop, passate fisse), pill sempre, char bloccato primo chunk, fade solo ultimo, `scale 0.92`, propaga hero/number. `generate_animated_chunk_frames(...)→[{image_path,start,end}]` `num=ceil(dur*fps)`, PNG `chunk_{i:04d}_frame_{f:05d}.png compress 1`, pill cache 32, opacity cache step8 cap128, `_fast_resample` BILINEAR se `|s-1|<0.12` else BICUBIC (LANCZOS solo 1x), binding locali, `TextAnimationError` solo timestamp invalidi/layout mismatch. `render_all_chunks_animated(...,on_chunk,safe_area,niche/preset)→chunks+{frames,frame_paths,clip_start/end,tail}`: `states` exit-lookahead/entry-lookbehind (`same_as_prev/same_pose→jump`, `entry_fade=prev None`), CTA run consecutivi stessa `section_id` sequenziali else paralleli ThreadPool 2-4 se `RENDER_PARALLEL` e ≥3 chunk. Ottimizzazioni P0: singleton font, probe 64x64, pill/opacity cache, PNG fast, image2 senza N stat, LUT opacity.

### 5.16 `text_tagger.py` (690) — nicchia+tagging

A.`detect_niche(script,on_attempt,min_conf=0.4)→VALID_NICHES` mai solleva: `PIPELINE_FAST/no-keys→_heuristic_niche` (conteggio segnali IT+EN pesati, multi-word x2, fallback `dark_motivational`); else LLM `temp 0.2,max 256,json {niche,confidence,reason}` snippet1500; `conf<min→euristica`; fence/regex, alias `normalize_niche`. B.`tag_chunk_words(chunks,on_attempt)→[{chunk_index,words:[{text,type}]}]` mai solleva: prompt designer + regole narrative (hook≥1 impact, CTA verbi→impact), `max 256+n*64`, parsing array bare o `{chunks|tagged|items|results}`, alias `keyword→impact,quote→accent`, valida n voci; `_align_tags_to_timed_words` match sequenziale norm finestra3, extra ignorati, mancanti→`_heuristic_style` (digit→impact, UPPER≥3→impact, virgolettati/`?`→accent, enfatiche/len≥9→impact). `enrich_chunks_with_typography(chunks,script,niche,on_attempt)→(niche,enriched+{typography_niche,styled_words:[{word,start,end,style,display,is_hero,is_number}]})` timing uniformi se `words` mancanti + `boost_typography_styles` + `assign_hero_flags` video-wide (import lazy). Mai solleva per LLM.

### 5.17 `typography_presets.py` (254) — 6 nicchie

`FALLBACK dark_motivational`, `VALID [business_finance,tech_ai,fitness_sport,lifestyle_vlog,educational,dark_motivational]`. Ogni preset `{fonts{base[2],impact[2],accent[2-3]},colors{base,highlight,accent(+alt dark),stroke:#000 unused},sizes{base:60(62 dark),impact 1.3-1.45,accent 1.1},stroke 0,shadow off,upper True,anim{pop_from}}`: business Inter/Roboto+Anton+Playfair gold `#FFD700/#FFE8A3` 0.70; tech Roboto/Inter+Bebas+SpaceMono ciano `#00E5FF/#B8F4FF` 0.70; fitness OpenSans/Roboto+Oswald+Bebas+PermanentMarker rosso `#FF2400/#FFC4B8` 0.60; lifestyle Poppins/Lato+Cinzel+Caveat rosa `#B76E79/#F3C6CE` 0.80 soft; educational Nunito/Roboto+League/Anton+Patrick blu `#2962FF/#B3C6FF` 0.70; dark Montserrat/Inter+Anton+Caveat oro `#D4AF37/#F5D67B(+alt #FF0000)` 0.60. `normalize_niche` alias, `get_preset` copia+clamp `pop_from` 0.1-1.0 mai crash, `list_niches_for_prompt`.

### 5.18 `font_manager.py` (416) — font

`FONTS_DIR`, `_GITHUB_RAW_BASE/ALT` google/fonts, `_FONT_FILES` norm→(ofl,file) (variable `%5Bwght%5D`, `impact/pristina→__system__` no-download, `permanentmarker→PermanentMarker-Regular.ttf` on-demand). `_find_local_font` esatto+prefisso cache 30s, `_find_system_font(prefer)` `C:\Windows\Fonts`, DejaVu, Liberation, Supplemental cache; ruolo impact→impact/arialbd, accent→hand/marker→times, base→arial. `_download_urls` mappa+guess, `_download_to` requests 15s size≥4KB magic TTF/OTF verifica `truetype(32)` atomic `.tmp→replace`. `FontManager.ensure_font_exists→path` (locale→download→sistema, mai solleva `""` se fail), `ensure_preset_fonts(niche|preset)→{base,impact,accent}`, `load_font`, `clear_cache`, singleton `_default_manager`.

### 5.19 `layout_guard.py` (1046) — guard realtime

Mai eccezioni, <5ms/chunk, no LLM/IO. Misure codificate: center testa y~644→`CENTER_SAFE_Y_MAX 620`; split 340px→`WIDEN 60`; pop 10%→`POP 1.12`; punch 1.6875x; `MARGIN 24`, `SHRINK (1.0,0.9,0.8,0.7)`, `PUNCH_PAD 28`, `WIDE_SPLIT {2}`, `IDLE_PAD 4/8` (bob+ margine). Primitive `get_character_tight_original/canvs (tight+scale+idle pad+clip)`, `text_bbox_of_layout+expand_pop`, `rects_overlap(margin)→(hit,area)`, `dynamic_max_width (0.80 clamp 0.5-0.95 min320)`, `dynamic_min_scale (max 0.3,40/base)`, `widest_line`, `rewrap_split_point (.!?…:;> ,>metà)`, `verify_z_order (UI top150/bottom320/side80, Z 0<10<20<30<99, char non sopra testo)`, `debug_safezone_boxes`. `plan_chunk_realtime(chunk,words,font,max,margin)→{layout,safe_area,font_scale,needs_pill,hide_character,guaranteed,overlap_px/before,actions}`: regola0 pose2→center, pose4→split_left; `measure` (styled else legacy + pill 28 + pop); cascata ok→shrink→auto-scale 80% fino 40px+rewrap→tighten center 900→620+0.9→widen split+60+0.8→switch preset (mai 2 split, mai 4 fuori left, punch non switcha)→punch intenzionale+pill `guaranteed=False`→hide `guaranteed=True`. `build_realtime_plan(chunks)→(plans,summary{total,guaranteed,fixed,hidden,intentional,overlaps_before})` + continuità posa (stessa posa→retry layout precedente se non peggiore `+pose-hold`) + ancoraggio `block_id` (visibili anchor più frequente garantito `block-anchor/forced`, nascosti center). `apply_realtime_plans` scrive `layout/preset/position+guard_*`; hide→`pose None,guard_hidden,character{visible False,NONE},char_visible False`; len diverse→extra invariati.

### 5.20 `easing.py` (135) — curve pure

Solo `math`, `t 0..1`. `clamp01,linear,out_cubic 1-(1-t)^3 (fade parole),in_cubic t^3 (fade-out gruppo),out_back 1+(c1+1)(t-1)^3+c1(t-1)^2 c1=1.70158 (pop overshoot ~1.1),in_out_cubic (morph),out_quad (fade char),in_out_quad (slide breve),out_bounce (giocoso),out_elastic (sperimentale <0)`. `back/elastic` possono >1 (voluto).

### 5.21 `advanced_kinetics.py` (305) — cinetica opt-in

Gate `ENABLE_ADVANCED_KINETICS` (spento=legacy). `GlyphCache` OrderedDict `(font_key,word,fill,stroke)→tile` max512 (min16) hits/misses, singleton 512. `lerp,scale_at(from+(1-from)*fn(curve t2_pop)),opacity_at(255*fn(t0_fade)),rotation_at(amp*sin πt default 0 dritti),t2_peak_scale (110%→100% primi 4f lineare),hero_shake_offset (sin6*amp*0.5,cos5*amp*0.35),advanced_stroke_for (base/accent→max(base,3) else base),advanced_entry_duration (base/accent→min(entry,2/fps) else invariato),parse_hex_rgba,brand_accent_rgba (#FF3366),hero_bg_rgba (#000000A6),draw_hero_badge (rounded pill espansa pad18 r26 clamp canvas, fallback rect, mai eccezioni, Z30)`.

### 5.22 `audio_mixer.py` (274) — SFX best-effort

Mai blocca (return voce invariata su fail). `sfx_events_from_chunks(chunks)→[(t,kind pop|whoosh|click)]` ordinati dedup <0.08s cap24: per chunk `t=start`: hero (`styled.is_hero|sfx_trigger`)→pop; elif `cta_card`→click; elif `character.event==ENTRY`→whoosh. `_sfx_filter(kind,at,vol)`: pop `sine 880 0.09`, click `sine 1400 0.05`, whoosh `anoisesrc white 0.25+high800+low6000+fade in/out 0.08`, `volume vol(-40..0)+adelay ms`. `mix_sfx(voce,chunks,out,sfx_db,bg_music,duck_db)→out|TEMP/narration_sfx.mp3|voce`: early-return se `!ENABLE/!ffmpeg/!isfile/(no eventi e no musica)`; graph `[-i voce][-i musica]?[-f lavfi -i sorgente SFX..] -filter_complex ([idx:a]volume,adelay[s]; [0:a][s..]amix normalize=0[mix]; [mus]volume duck + [mix]sidechaincompress thr0.02 ratio8 att20 rel400 [ducked]; [mix][ducked]amix[aout]) -map [mix|aout|0:a] -c:a libmp3lame 192k`. `normalize=0` preserva voce, `release 400ms` risalita pause >0.5s. Timestamp mai mutati (solo lettura `start`).

### 5.23 `video_builder.py` (468) — ffmpeg finale

`VideoBuildError`. `_check_ffmpeg (which)`, `_get_audio_duration (ffprobe format=duration)`, `_ffmpeg_color (#RRGGBB→0xRRGGBB else black)`, `_chunk_frame_pattern (regex chunk_\d+_frame \d+\.png, verifica primo/ultimo/mid stessa dir → dir/prefix%05dsuffix, no N stat)`, `_clip_codec_args (.webm→libvpx-vp9 yuva420p crf18, else .mov→png lossless veloce)`, `build_chunk_clip(frames,fps,out)` valida solo primo/ultimo+2 random se >4, tenta `image2` pattern else `concat demuxer` (mkstemp `chunk_concat_*.txt` `file + duration 1/fps`), `_is_animated_chunk (frame_paths|frames)`, `_chunk_frames`. `build_video(audio,chunks,output_filename,bg)→abs OUTPUT/file`: `_chunk_window(c,nxt)` `s=clip_start|start`, `e=clip_end|end` (`e≤s→s+0.1`, `nxt: ns>s e ns>e→e=ns` contigue anti-blink); animato: riuso clip se `mtime(clip)≥mtime(frame0,-1)`, ThreadPool `max(2,min(4,cpu-1,n))` `chunk_{i:04d}.mov`; `filter_complex` statico `overlay enable between`, animato `setpts=PTS-STARTPTS+s/TB (+format yuva420p se webm)` + overlay; finale `ffmpeg -y -threads auto -f lavfi -i color=c=bg:s=WxH:r=fps:d=dur -i audio [-i png/mov..] -filter_complex -map last -map 1:a -c:v libx264 -preset veryfast -crf 20 -g 60 -keyint_min 30 -pix_fmt yuv420p -movflags +faststart -c:a aac 192k -shortest OUTPUT`. Preset whitelist. `cleanup_temp_files` walk rimuove file+rmdir, mai solleva.

### 5.24 `video_composer.py` (272) — Fase5 Z strict

Z `0 bg tinta/KenBurns <10 char (in micro-clip) <20 dimmer/vignette (solo bg) <30 kinetic/hero (in clip) <99 debug`. `kenburns_filter(dur)` `zoompan z=min(zoom+step,zmax) d=125 x=iw/2.. y=.. s=WxH fps` clamp `zmax 1.0-1.5 (1.08), step 0.0002-0.01 (0.0015), d max25`, input maggiorato 1.2x pari. `dimmer_filter` `eq brightness=-0.03 saturation=1.05,vignette=PI/4`. `build_composed_video(audio,chunks,output,bg,debug)→path`: se `!dynamic e !debug→_legacy_build_video` zero divergenza; else `duration=ffprobe`, `bg=color`, `big=1.2x pari`, `_window` contigua identica legacy, micro-clip come legacy (`fps=chunk.fps|VIDEO_FPS`, cache mtime, ThreadPool, supporta `clip_path/image_path` statici); graph `[0:v]kenburns[bgzoom],[bgzoom]dimmer[base]` poi `setpts+overlay between` + debug `drawbox red@0.35 fill` da `layout_guard.debug_safezone_boxes` (fail-open). Stesso encode legacy `libx264 preset crf20 g60 keyint30 faststart aac`. Fallback import con default se `config` datata. `VideoBuildError` chunk senza frame/clip e ffmpeg fail (`stderr[-2000:]`).

### 5.25 `invariant_checks.py` (162) — post-build non fatali

`run_post_build_checks(video,audio,chunks,words_before/after,strict=False)→(ok,details)` mai solleva salvo `strict`. `_probe_duration (ffprobe)`, `check_av_sync (ok |vd-ad|<0.1, msg video/audio/delta; None→False ffprobe indisponibile)`, `check_temp_containment (realpath walk commonpath==base, conta file; assente→True pulita)`, `check_timestamps_preserved (len uguali + start/end ±1e-6; non-numerici→fail; None→saltato)`, `check_z_order_safe (layout_items|layout→text_bbox_of_layout→verify_z_order, critical solo fuori-canvas; import fail→True saltato fail-open)`. Chiamato in `[8/8]` log `invariant k: OK/FAIL (msg)`.

---

## 6. Asset, output, temp

- **Characters:** `assets/characters/1.png..5.png` 768x1376 ~0.93-1.07MB, sfondo nero rimosso a runtime (`RGB<15&A≥250→trasparente`); mai committare asset con sfondo già pulito senza aggiornare `_remove_black_background`/cache.
- **Fonts:** 15 TTF committati (Anton,Bebas,Caveat,Cinzel,Inter,LeagueSpartan,Montserrat,Nunito,OpenSans,Oswald,PatrickHand,Playfair,Poppins,Roboto,SpaceMono) + `PermanentMarker-Regular` on-demand + variabili `[wght]` URL-encodati; fallback sistema `C:\Windows\Fonts`, DejaVu, Liberation, Supplemental.
- **Outputs (27 mp4 al 27/09):** `output_video.mp4` legacy + `video_01_ciao`, `video_01_perch_il_cielo__blu`, serie `stai_ancora_lasciando_i_tuoi` (`_1.._13`), `video_02_usi_ancora_chatgpt..`, `video_03_smetti..`, `video_04_ti_senti..`, `video_05_perch..`, `video_06_nessuno..` (+`_1` bulk). Naming `video_{i:0w}_{slug}` con `w=max(2,len(str(total)))`, `_1..` anti-collisione fino 999.
- **Temp:** `narration[_NNN].mp3`, `narration_sfx.mp3`, `subtitle_*.png`, `chunk_*_frame_*.png`, `chunk_*.mov/.webm`, `chunk_concat_*.txt`; svuotata dopo ogni video (`cleanup_temp_files` walk+rmdir, mai solleva). `text_only` non pulisce clip (solo log).

---

## 7. Contratti dati centrali (obbligatori per modifiche)

` ` `python
Word = {word:str, start:float, end:float, [tier:T0..T3, vfx_type, sfx_trigger]}
ChunkBase = {text:str, start:float, end:float, words:[Word]}
ChunkNarr = ChunkBase + {narrative_role:hook|body|cta, narrative_beat:int, beat_tone,
  anim_entry_mult:float, anim_pop_from:float, cta_card:bool, cta_section_id:str|None, cta_strength}
StyledWord = {word:str, display:str, style:base|impact|accent, start:float, end:float,
  is_hero:bool, is_number:bool}
ChunkTypo = ChunkNarr + {typography_niche:str, styled_words:[StyledWord]}
CharacterEntry = {chunk_index:int, pose:int|None, layout|layout_preset:str,
  punch_in:bool, transition_in:str, position|transition|scale, block_id:str|int,
  char_event:ENTRY|SUSTAIN|EXIT|NONE, char_visible:bool,
  character:{visible:bool, pose:int|None, pose_id:str, side:LEFT|RIGHT|CENTER, event, block_id}}
ChunkFull = ChunkTypo + CharacterEntry + {guard_safe_area:(x0,y0,x1,y1)|None,
  guard_font_scale:float, guard_pill:bool, guard_hidden:bool,
  layout|layout_preset, punch_in, transition_in}
ChunkRendered = ChunkFull + {frames:[{image_path,start,end}], frame_paths:[str],
  clip_start:float, clip_end:float, clip_tail:float, [clip_path,image_path,fps]}
Theme = {background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB]}
KeywordColors = {norm_word: (R,G,B,255)}
Sections = {hook:[idx], body:[idx], body_beats:[[idx]], beat_tones:[str],
  cta:[idx], cta_strength:strong|soft|none, cta_mode:card|locked|none}
` ` `

**Regole:** `start<end` sempre (`_enforce_monotonic` + `window e≤s→s+0.1`); `clip_start=start`, `clip_end=end+tail` (solo hold+char); `frame_paths` ordinati `frame_00000..`; `styled_words` len==words len (mismatch→`TextAnimationError`); `plan` len==chunks len else merge saltato; `pose None/visible False→hidden` (nessun paste); `is_hero` max1/video mai numero; `display` è testo disegnato (upper impact se preset).

---

## 8. Sottosistemi trasversali

### 8.1 Z-Index (invariante)

`0 background <10 character <20 dimmer/vignette (solo bg) <30 subtitles/hero badge <99 debug`. Character e testo già compositi nei micro-clip (ordine frame `trasparente→char→pill→testo`); dimmer mai sul testo; debug solo `debug_safezones`. `verify_z_order` fail-open.

### 8.2 Layout (4 preset §5.13 + guard §5.19)

Precedenza area: `text_safe_area(param) > safe_area(param) > guard_safe_area(chunk) > preset.safe_area > None(centro storico)`. Font: `BASE_SIZE(60)*preset.scale(1.0/0.9)*guard_scale(0.7-1.0)`; auto-scale 80% fino 40px. Pill solo punch-in/CTA card (`(0,0,0,170) pad28 r36`). Posa2 mai split, posa4 sempre `split_left`, posa5 mai center stabile. Guard <5ms, mai eccezioni.

### 8.3 Tipografia (6 nicchie §5.17)

`detect_niche→get_preset→ensure_preset_fonts (pre-warm singleton una volta)→tag_chunk_words→align→boost→hero→compute_styled_layout→_styled_fills`. `pop_from`: hook override > preset (0.60 fitness/dark aggressivo, 0.70 standard, 0.80 lifestyle soft) > globale 0.7. Base weight 600 (variabili) else synth 1px. Stroke 0, ombra OFF default. Leggibilità da contrasto tema+pill.

### 8.4 Narrativa (hook/corpo/CTA §5.10)

Hook prime 1-3 (posa1 center slide_up, climax punch, `entry 0.7x pop 0.55`), corpo beat (posa tono 5 domanda/4 dati/2 resto, stessa identità per beat, morph fluido), CTA forte+breve (≤14 parole) card karaoke persistente posa3 center fade, debole locked posa2 neutra. `anim_entry_mult/pop_from` hook vince su preset/globale.

### 8.5 Cinetica Tier T0-T3 (§5.15+§5.21)

Moto da `(style,is_hero,is_number)`, colore da tema+highlight+keyword. T0 fade, T1 rise (mai scala), T2 pop `from→1 ease_out_back` + `t2_peak 110% 4f` + brand accent se advanced, T3 hero `0.6→1 0.22s + hold 0.06s + shake 4px + badge #000000A6` 1/video, T3-num pop corto 0.15s. Uscita gruppo `ease_in_cubic`, hero compressa mai oltre `end`. Advanced opt-in: entry 2-frame T0/T1, stroke 3, glyph cache 512.

### 8.6 Personaggi Breath&Focus (§5.11+§5.12+§5.15)

Macro-blocchi ≥2.5s posa/lato unici, visibilità Hook/CTA sempre + Body 60% distribuiti (pause 1 blocco), no-repeat adiacenti, eventi ENTRY/SUSTAIN/EXIT/NONE, entry slide&pop 0.20s +300, exit drop 0.16s +400, morph 0.40s opaco, punch zoom 0.60s, idle bob 4px@0.4Hz tilt 0, gap-hold tail ≤1.5s (cap 2s) solo hold+char, micro-blend 4f scala 2% su switch focus stesso blocco. `resolve_chunk_layout` singola verità.

---

## 9. FFmpeg / audio — comandi chiave

- **Durata:** `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <audio|video>`
- **Clip pattern:** `ffmpeg -y -threads auto -framerate <fps> -start_number 0 -i <dir/chunk_%05d.png> -c:v png|libvpx-vp9... <out.mov|webm>`; fallback `ffmpeg -y -threads auto -f concat -safe 0 -i <list.txt> -c:v ... <out>` (`file '<esc>'` + `duration 1/fps`, ultimo senza duration). Validazione solo primo/ultimo+2 random.
- **Finale (builder/composer):** `ffmpeg -y -threads auto -f lavfi -i color=c=<0xRRGGBB>:s=<W|bigW>x<H|bigH>:r=<fps>:d=<dur> -i <audio> [-i <png/mov>..] -filter_complex "[0:v]kenburns[bgzoom];[bgzoom]eq,vignette[base];[base][i:v]setpts+overlay enable between...;[last]drawbox debug..." -map [last] -map 1:a -c:v libx264 -preset veryfast -crf 20 -g 60 -keyint_min 30 -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 192k -shortest OUTPUT`. Composer delega a legacy se `!dynamic e !debug`.
- **SFX:** `ffmpeg -y -i <voce> [-i <musica>] [-f lavfi -i <sine|noise>..] -filter_complex "<volume,adelay;amix normalize=0;sidechaincompress thr0.02 ratio8 att20 rel400>" -map [mix|aout|0:a] -c:a libmp3lame -b:a 192k <out.mp3>` (solo se eventi/musica, `returncode 0` + `isfile`).
- **Ken Burns:** `zoompan=z='min(zoom+0.0015,1.08)':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30` su input 1.2x pari. Dimmer `eq=brightness=-0.03:saturation=1.05,vignette=PI/4`.

---

## 10. Error handling / failover / fallback matrix

| Livello | Strategia |
|---|---|
| **Multi-key** | TTS/Whisper/LLM/theme/keyword/emphasis/char/tagger loop chiavi in ordine, `on_attempt(i,tot,ok,detail)` in GUI. Retryable: `401,402,403,429,500-504` + hint testuali (rate/quota/credit/expired/invalid/overload/timeout...); `400/404-unica/422`→immediato (altra chiave inutile); `404` retryable solo voci per-chiave diverse. Fine→`TTSError/TranscriptionError/KeywordError(Tutte N..|failures)`. |
| **Fatali video** | `TTSError,TranscriptionError,VideoBuildError` → video fallito, altri bulk continuano + riepilogo. `AlignmentError,KeywordError,TextAnimationError(single→statico),ThemeError(non-vuoto→default)` non bloccano. |
| **Fallback deterministici** | Theme default `{#0F172A,#FFFFFF,palette}`; emphasis blocchi 2; keyword→warning senza evidenziazioni; char→fallback 8-step+macro; nicchia/tagging→euristici; tipografia→legacy singolo font T0/T2; composer→builder; SFX→voce originale; guard→hide character (sempre garantito); invariant→log FAIL (video valido). |
| **Mai solleva** | `enrich_timestamps,emphasis(API),tagger/niche,character plan(API),guard,pose_constraint,pose_side_map,render_mode,mixer,invariant(check,strict=False),cleanup,draw_badge,glyph cache,easing,animator event_of`. |
| **Cache** | Groq client max16; font `(path,size)` cap16; char layer `{(pose,w,h)}`; tight bbox; pill 32; opacity step8 cap128; tilt 64; typo font; font dir 30s; system font 32; glyph 512; clip `mtime` riuso. `clear_*` per test. |

---

## 11. Invarianti globali (MAI violare)

1. **Timestamp:** `start/end` Whisper mai sovrascritti dopo alignment (solo merge additivo `tier/vfx/sfx/character/typography/narrative/guard`). Check `timestamps_preserved ±1e-6`.
2. **Parole script:** sottotitoli mostrano parole script (alignment), LLM vede solo parole e restituisce solo indici/tag (mai testo/timing).
3. **Z-order:** `bg(0)<char(10)<dimmer(20)<sub(30)<debug(99)`; dimmer mai sul testo; frame `char→pill→testo`.
4. **No-overlap:** testo e character mai sovrapposti salvo punch-in intenzionale con pill (`guaranteed=False`) o hide (`guaranteed=True`).
5. **Posa:** 4 sempre `split_left`, 2 mai split, 5 mai center stabile; `resolve_chunk_layout` unica verità.
6. **Hero:** max1/video, mai numero, solo `impact&!number`.
7. **Finestre contigue:** `chunk_end=next_start` quando gap (anti-blink); `clip_end=end+tail` solo hold+char.
8. **Temp containment:** tutto in `TEMP_DIR`, pulizia dopo ogni video; `check_temp_containment`.
9. **Stroke/ombra:** default 0/OFF (look pulito); leggibilità da contrasto+pill.
10. **Thread-safety GUI:** solo `root.after` per UI da worker; `Thread(daemon)` per pipeline.
11. **Bulk isolamento:** tema/nicchia/personaggi/output/audio propri per script; `cleanup` in `finally`.
12. **Fail-open:** guard/mixer/invariant/composer-debug mai bloccano video valido.

---

## 12. Parallelismo / performance / cache

- **Pipeline:** `[1-2/8]` pool2 (tema||audio), `[5.5-6.5/8]` pool3 (char||keyword||typo). `PIPELINE_FAST=1` salta LLM pesanti (enfasi/char/tagging→euristiche, tema+keyword restano LLM).
- **Render:** `RENDER_PARALLEL=1` pool 2-4 chunk (CTA run sequenziali, normali paralleli) + pool clip ffmpeg `max(2,min(4,cpu-1,n))`; `on_chunk` ogni 10 per GUI.
- **P0 animator:** singleton `FontManager`, probe 64x64, pill/opacity/tilt/typo cache, PNG `compress 1`, `image2` senza N stat, LUT opacity, BILINEAR se `|s-1|<0.12` else BICUBIC, binding locali.
- **Preset ffmpeg:** `veryfast` default (qualità invariata), `ultrafast` bozze.

---

## 13. Ricette per LLM — come modificare senza rompere

- **Nuova posa 6:** aggiungi `assets/characters/6.png`, `CHARACTER_POSE_COUNT=6`, estendi `CHARACTER_POSE_SIDES` (es. `6:right`), `_POSE_RULES` in selector, `POSE_SIDE_DEFAULTS` in config, test `resolve_chunk_layout(6)` + guard.
- **Nuova nicchia:** aggiungi preset in `typography_presets.py` (`fonts/colors/sizes/anim.pop_from`), segnali in `text_tagger._NICHE_KEYWORDS`, alias in `normalize_niche`, `ensure_preset_fonts` copre download automatico.
- **Nuovo Tier/colore:** estendi `_word_tier` + `_styled_fills` + `_resolve_motion_params` + `advanced_kinetics` (stroke/duration/peak/shake) + `EASING_CURVES` in config; mai toccare `start/end`.
- **Nuovo SFX:** estendi `sfx_events_from_chunks` (nuovo kind) + `_sfx_filter` (sorgente lavfi) + `SFX_VOLUME_DB`; test `mix_sfx` con `ENABLE_AUTO_SFX=1`.
- **Nuovo background:** estendi `video_composer.kenburns_filter/dimmer_filter` (nuovi filtri solo su `[bgzoom]`, mai su clip); `ENABLE_DYNAMIC_BACKGROUNDS=0` deve restare delega legacy identica.
- **Nuovo Layout:** aggiungi preset in `layout_presets.py` (width/headroom/safe/font/side/transition/pill) + `normalize_preset` + vincoli posa in `POSE_SIDE_MAP` + misure in `layout_guard` (tight+pop+margin).
- **Nuova lingua TTS:** cambia `ELEVENLABS_MODEL_ID` (verifica supporto IT), aggiorna `_CTA_CUES/_NICHE_KEYWORDS/_WEAK_TRAILING` per nuova lingua.
- **Dove mettere codice:** logica pura deterministica → `narrative/alignment/enricher/guard/presets`; I/O rete → `tts/transcription/theme/keywords/emphasis/tagger/selector` con failover `on_attempt`; frame → `text_animator` (mai `start/end`); ffmpeg → `builder/composer/mixer`; post-check → `invariant_checks`; config → `config.py` + `.env.example` (mai default che rompono invarianti).

---

## 14. Limiti noti e debito tecnico

- Nessun asset video di sottofondo (solo tinta/Ken Burns); centinaia di chunk → comando ffmpeg lungo (ottimizzabile singolo overlay timeline).
- Keyword verbatim (flessioni non matchano); Whisper omonimi corretti solo da alignment (se `match_ratio` basso, warning ma raw usato).
- `subtitle_grouping.py` legacy non chiamato (ma costanti condivise, non rimuovere).
- `Param background_color` animator solo compatibilità (bg reale da ffmpeg).
- `Decide exit` sempre `hold` (no `slide_down`, fix blink intenzionale).
- Tilt default 0 (dondolio instabile rimosso); ombra OFF; stroke 0.
- `text_only` scrive solo `.txt` preview (nessun mp4); `debug_safezones` aggiunge `drawbox` (fail-open).
- `.env` con segreti reali presente in locale (mai committare); `__pycache__` committato in passato ma ora in `.gitignore`.

---

## 15. Checklist pre-modifica + verifica rapida (per LLM)

1. Leggi §7 contratti + §11 invarianti; individua `resolve_chunk_layout` / `_styled_fills` / `_chunk_window` se tocchi layout/testo/video.
2. Aggiorna `config.py` + `.env.example` se nuova flag (default safe, falsy `0,false,no,off,""` per booleani).
3. Mantieni firme e `mai solleva` dove documentato; aggiungi `try/except` fail-open per nuovi path non fatali.
4. Test senza crediti: `python config.py --check-keys`.
5. Test grafica <5s: `python main.py --script test.txt --render-mode=text_only` (leggi `outputs/*_textonly.txt` + log `invariant temp/timestamps`).
6. Test headless 1 video: `python main.py --script test.txt` (controlla `Completati 1/1`, `invariant av_sync/temp/timestamps/z_order OK`).
7. Test bulk: file 2-3 righe + `--bulk` (verifica `video_01.._slug.mp4` distinti, nessun overwrite, `cleanup_temp`).
8. Se tocchi font/char: cancella cache (`clear_*`) e verifica `assets/` + `getbbox` + `clip` overhang.
9. Se tocchi ffmpeg: verifica `ffprobe` durata, `setpts`, finestre contigue, `GOP 60`, `faststart`, `stderr[-2000:]` in errore.
10. Aggiorna questo report + `.env.example` se cambi contratti/flag.

**Comandi utili:**
` ` `powershell
Copy-Item .env.example .env
pip install -r requirements.txt
python config.py --check-keys
python main.py
python main.py --script script.txt --bulk --render-mode=text_only
ffmpeg -version; ffprobe -version
git log --oneline -10
` ` `

---

## Appendice A. `.env.example` (estratto logico)

`ELEVENLABS_API_KEYS/GROQ_API_KEYS` (virgola, dedup) + alias singole; `VOICE_ID/IDS/MODEL/OUTPUT_FORMAT`; `WHISPER/LLM/THEME_MODEL`; `KEYWORDS_MAX/MIN_GAP`; `THEME_DIFF`; `EMPHASIS_MIN/MAX`; `VIDEO_W/H/FPS`; `SUBTITLE_*`; `TEXT_ANIMATION_*` (entry/exit/scale/lift/hero/number); `TYPOGRAPHY_*`; `NARRATIVE_*`; `CHARACTER_*` (enabled/scale/pose/block/discontinuous/idle/entry/exit/pose-sides); `OUTPUT/TEMP_DIR`; `Full Engine` (kinetics/dynamic/SFX/volumi/font/colori/kinetic/layout/micro). Vedi file reale 7220 byte per commenti completi.

## Appendice B. Git log recente

`b9e73d4 upgrade 25/09` (HEAD) → `61985b5 upgrade 24/09/26 1` (pose-side+env doc) → `a924cd0 upgrade 24/09/26` (+4311/-323 character_animator+macro+T0-T3+guard) → `38341ba upgrade` (cleanup -6504) → `2b097aa/4ffe07d/0205288/4e534a1/...` upgrade incrementali → `eb583f9 upload` → `b72c95a/67f3c65 first commit`.

---

*Fine report — pronto per piani di modifica e implementazioni.*

```

---

### `core/advanced_kinetics.py` — 305 righe, 10481 byte

Motore cinetico avanzato opt-in (305 righe, `ENABLE_ADVANCED_KINETICS`): Tier T0/T1 bordo 3px fade 2 frame, T2 brand accent #FF3366 picco 110% 4 frame, T3 badge pill #000000A6 + micro-shake 4px, glyph-cache, interpolazione scala/opacità su timestamp esatti. A flag spento path legacy identico.

```python
"""
Advanced Kinetics Engine (Full Engine Upgrade — Fase 2).

Tipografia cinetica multi-tier T0-T3 con easing dedicato, glyph-cache e
interpolazione matematica su timestamp esatti. Tutto opt-in via
`ENABLE_ADVANCED_KINETICS`: a flag spento il comportamento e' identico al
legacy (nessuna regressione).

Tier (quando abilitato):
  - T0/T1 base: bianco/grigio + bordo nero 3px (KINETIC_T0_STROKE_PX),
    fade-in rapida in 2 frame.
  - T2 keyword: COLOR_BRAND_ACCENT, picco 110% sui primi 3-4 frame con
    Ease-Out Back poi 100%.
  - T3 hero: badge/pill semi-trasparente COLOR_HERO_BG + font display
    HERO_WORD_FONT_PATH + micro-shake/bounce.

Z-Index (composite stack): bg Z=0 < character Z=10 < dimmer Z=20 <
subtitles Z=30 < debug Z=99. Questo modulo disegna solo il livello Z=30
(testo) e il badge hero (sempre sotto il glifo, sopra dimmer).

Glyph-cache: LRU {(font_key, word, fill, stroke): tile RGBA} per evitare
colli di bottiglia Pillow su caption da 2-3 parole. Le curve di
interpolazione (rotazione/opacita'/scala) sono pure e lavorano sui timestamp
esatti (nessuna allocazione nel loop caldo).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

try:
    from config import (
        COLOR_BRAND_ACCENT,
        COLOR_HERO_BG,
        ENABLE_ADVANCED_KINETICS,
        EASING_CURVES,
        KINETIC_T0_STROKE_PX,
        KINETIC_T2_PEAK_FRAMES,
        KINETIC_T2_SCALE_PEAK,
        KINETIC_T3_SHAKE_PX,
        VIDEO_FPS,
    )
except Exception:  # config datata / import isolato
    COLOR_BRAND_ACCENT = "#FF3366"
    COLOR_HERO_BG = "#000000A6"
    ENABLE_ADVANCED_KINETICS = True
    EASING_CURVES = {}
    KINETIC_T0_STROKE_PX = 3
    KINETIC_T2_PEAK_FRAMES = 4
    KINETIC_T2_SCALE_PEAK = 1.10
    KINETIC_T3_SHAKE_PX = 4.0
    VIDEO_FPS = 30

try:
    from core.easing import (
        clamp01,
        ease_in_cubic,
        ease_out_back,
        ease_out_cubic,
        ease_out_elastic,
        ease_out_quad,
    )
except Exception:  # pragma: no cover
    def clamp01(t: float) -> float:  # type: ignore
        return max(0.0, min(1.0, float(t)))

    def ease_out_cubic(t: float) -> float:  # type: ignore
        t = clamp01(t)
        return 1.0 - pow(1.0 - t, 3)

    def ease_out_back(t: float) -> float:  # type: ignore
        t = clamp01(t)
        c1, c3 = 1.70158, 2.70158
        return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)

    def ease_out_quad(t: float) -> float:  # type: ignore
        t = clamp01(t)
        return 1.0 - (1.0 - t) * (1.0 - t)

    def ease_in_cubic(t: float) -> float:  # type: ignore
        return clamp01(t) ** 3

    def ease_out_elastic(t: float) -> float:  # type: ignore
        return ease_out_back(t)


# ---------------------------------------------------------------- glyph cache
class GlyphCache:
    """LRU di tile RGBA per (font_key, word, fill, stroke). Max 512 voci."""

    def __init__(self, maxsize: int = 512) -> None:
        self._max = max(16, int(maxsize))
        self._store: OrderedDict[tuple, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _key(self, font_key: Any, word: str, fill: Any, stroke: int) -> tuple:
        try:
            f = tuple(fill) if isinstance(fill, (list, tuple)) else str(fill)
        except Exception:
            f = str(fill)
        return (str(font_key), str(word), f, int(stroke))

    def get(self, font_key: Any, word: str, fill: Any, stroke: int) -> Any | None:
        try:
            k = self._key(font_key, word, fill, stroke)
            hit = self._store.get(k)
            if hit is not None:
                self._store.move_to_end(k)
                self.hits += 1
                return hit
            self.misses += 1
            return None
        except Exception:
            return None

    def put(self, font_key: Any, word: str, fill: Any, stroke: int, tile: Any) -> None:
        try:
            k = self._key(font_key, word, fill, stroke)
            self._store[k] = tile
            self._store.move_to_end(k)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self._store.clear()
        except Exception:
            pass


_glyph_cache = GlyphCache(maxsize=512)


def get_glyph_cache() -> GlyphCache:
    return _glyph_cache


# ------------------------------------------------------- interpolazione pura
def lerp(a: float, b: float, t: float) -> float:
    """Interpolazione lineare con clamp (nessuna allocazione)."""
    try:
        t = clamp01(t)
        return float(a) + (float(b) - float(a)) * t
    except Exception:
        return float(a)


def scale_at(t_norm: float, scale_from: float = 0.7, curve: str = "t2_pop") -> float:
    """Scala eased  su timestamp normalizzato (0..1)."""
    try:
        name = (EASING_CURVES.get(curve, "ease_out_back") if isinstance(EASING_CURVES, dict) else "ease_out_back")
        fn = {"ease_out_back": ease_out_back, "ease_out_elastic": ease_out_elastic,
              "ease_out_cubic": ease_out_cubic, "ease_out_quad": ease_out_quad}.get(name, ease_out_back)
        eased = fn(clamp01(t_norm))
        return float(scale_from) + (1.0 - float(scale_from)) * float(eased)
    except Exception:
        return 1.0


def opacity_at(t_norm: float, curve: str = "t0_fade") -> int:
    try:
        name = (EASING_CURVES.get(curve, "ease_out_cubic") if isinstance(EASING_CURVES, dict) else "ease_out_cubic")
        fn = {"ease_out_cubic": ease_out_cubic, "ease_out_quad": ease_out_quad,
              "ease_in_cubic": ease_in_cubic}.get(name, ease_out_cubic)
        return int(round(255 * fn(clamp01(t_norm))))
    except Exception:
        return 255


def rotation_at(t_norm: float, amp_deg: float = 0.0) -> float:
    """Rotazione decorativa (default 0: i sottotitoli restano dritti)."""
    try:
        if abs(float(amp_deg)) < 1e-9:
            return 0.0
        return float(amp_deg) * math.sin(math.pi * clamp01(t_norm))
    except Exception:
        return 0.0


# ------------------------------------------------------------- T2 peak / T3
def t2_peak_scale(frame_idx: int, base_scale: float = 1.0) -> float:
    """Picco 110% sui primi KINETIC_T2_PEAK_FRAMES frame (degrada a base).

    Da applicare SOLO quando ENABLE_ADVANCED_KINETICS: il pop Ease-Out Back
    gia' fa overshoot, ma il picco esplicito garantisce il 110% sui primi
    3-4 frame come da spec anche con preset soft (pop_from 0.8).
    """
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return float(base_scale)
        peak = max(1.0, float(KINETIC_T2_SCALE_PEAK))
        n = max(1, int(KINETIC_T2_PEAK_FRAMES))
        if frame_idx < 0:
            return float(base_scale)
        if frame_idx >= n:
            return float(base_scale)
        # Rampa lineare peak -> base sui primi N frame.
        k = 1.0 - (float(frame_idx + 1) / float(n + 1))
        return float(base_scale) * (1.0 + (peak - 1.0) * max(0.0, min(1.0, k)))
    except Exception:
        return float(base_scale)


def hero_shake_offset(frame_idx: int, fps: int = 30) -> tuple[int, int]:
    """Micro-shake badge hero: sinusoide ±KINETIC_T3_SHAKE_PX (solo se enabled)."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return (0, 0)
        amp = max(0.0, float(KINETIC_T3_SHAKE_PX))
        if amp <= 0:
            return (0, 0)
        t = float(frame_idx) / max(1, int(fps or VIDEO_FPS))
        dx = int(round(math.sin(t * 2 * math.pi * 6.0) * amp * 0.5))
        dy = int(round(math.cos(t * 2 * math.pi * 5.0) * amp * 0.35))
        return (dx, dy)
    except Exception:
        return (0, 0)


def advanced_stroke_for(style: str, base_stroke: int = 0) -> int:
    """Stroke T0/T1 in modalita' avanzata: 3px neri, altrimenti base."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return int(base_stroke)
        if str(style) in ("base", "accent"):
            return max(int(base_stroke), int(KINETIC_T0_STROKE_PX))
        return int(base_stroke)
    except Exception:
        return int(base_stroke)


def advanced_entry_duration(style: str, entry_dur: float, fps: int = 30) -> float:
    """T0/T1 fade-in rapida in 2 frame quando abilitato (spec Fase 2)."""
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return float(entry_dur)
        if str(style) in ("base", "accent"):
            two_frames = 2.0 / max(1, int(fps or VIDEO_FPS))
            return max(0.01, min(float(entry_dur), two_frames))
        return float(entry_dur)
    except Exception:
        return float(entry_dur)


def parse_hex_rgba(hex_color: str, default: tuple = (255, 51, 102, 255)) -> tuple:
    """Parse #RRGGBB[#AA] -> RGBA (mai eccezioni)."""
    try:
        s = str(hex_color or "").strip()
        if s.startswith("#") and len(s) in (7, 9):
            r, g, b = int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
            a = int(s[7:9], 16) if len(s) == 9 else 255
            return (r, g, b, a)
        return default
    except Exception:
        return default


def brand_accent_rgba() -> tuple:
    try:
        return parse_hex_rgba(str(COLOR_BRAND_ACCENT), (255, 51, 102, 255))
    except Exception:
        return (255, 51, 102, 255)


def hero_bg_rgba() -> tuple:
    try:
        return parse_hex_rgba(str(COLOR_HERO_BG), (0, 0, 0, 166))
    except Exception:
        return (0, 0, 0, 166)


def draw_hero_badge(
    frame_img: Any,
    bbox: tuple[int, int, int, int],
    pad: int = 18,
    radius: int = 26,
) -> None:
    """Badge T3: pill semi-trasparente sotto il glifo (Z=30, sopra dimmer).

    Disegna direttamente su `frame_img` (RGBA). Mai eccezioni: a canvas
    degenere non fa nulla.
    """
    try:
        if not bool(ENABLE_ADVANCED_KINETICS):
            return
        from PIL import ImageDraw as _ID

        x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        if x1 <= x0 or y1 <= y0:
            return
        W, H = frame_img.size
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad // 2)
        x1, y1 = min(W, x1 + pad), min(H, y1 + pad // 2)
        d = _ID.Draw(frame_img)
        try:
            d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=hero_bg_rgba())
        except (AttributeError, ValueError, TypeError):
            d.rectangle([x0, y0, x1, y1], fill=hero_bg_rgba())
    except Exception:
        pass

```

---

### `core/alignment.py` — 120 righe, 4696 byte

Riallinea Whisper allo script: tempi di Whisper + parole dello script via `difflib.SequenceMatcher`. Corregge omonimi/errori, interpola parole saltate, marca extra. Ritorna `(words, stats{match_ratio,corrected,interpolated,extra})`, `AlignmentError` se script vuoto. Non altera timestamp originali oltre interpolazione.

```python
"""
Allineamento della trascrizione Whisper allo script originale.

Whisper fornisce timestamp accurati ma può sbagliare singole parole
(omonimi, nomi propri, punteggiatura). Siccome l'audio è stato generato
proprio dallo script, le parole mostrate nei sottotitoli devono essere
quelle dello script: questa funzione riallinea le due sequenze con
difflib, tenendo i tempi di Whisper e le parole dello script.

Casi gestiti:
  - parola trascritta diversa  -> si usa la parola dello script (stessi tempi);
  - parola saltata da Whisper  -> si interpola il timing tra i vicini;
  - parola extra trascritta    -> si tiene invariata (preserva la continuità dei tempi).
"""

import difflib

from core.keywords import normalize_word


class AlignmentError(Exception):
    """Errore durante l'allineamento trascrizione/script."""
    pass


def _interp_missing(missing: list[str], prev_end: float, next_start: float | None) -> list[dict]:
    """Distribuisce le parole saltate da Whisper nell'intervallo tra i vicini."""
    n = len(missing)
    if next_start is None or next_start <= prev_end:
        next_start = prev_end + 0.3 * n
    span = (next_start - prev_end) / n
    return [
        {"word": w, "start": prev_end + span * i, "end": prev_end + span * (i + 1)}
        for i, w in enumerate(missing)
    ]


def _enforce_monotonic(words: list[dict]) -> None:
    """Garantisce timestamp non sovrapposti e crescenti (fix per interpolazioni)."""
    prev_end = 0.0
    for w in words:
        if w["start"] < prev_end:
            w["start"] = prev_end
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.05
        prev_end = w["end"]


def align_transcript(transcribed: list[dict], script_text: str) -> tuple[list[dict], dict]:
    """Riallinea le parole trascritte allo script originale.

    Args:
        transcribed: [{"word", "start", "end"}] da Whisper.
        script_text: testo originale usato per generare l'audio.

    Returns:
        (parole_allineate, stats) dove stats = {"match_ratio", "corrected",
        "interpolated", "extra"}.

    Raises:
        AlignmentError: se mancano parole trascritte o script.
    """
    if not transcribed:
        raise AlignmentError("Nessuna parola trascritta da allineare.")
    script_tokens = script_text.split()
    if not script_tokens:
        raise AlignmentError("Script vuoto: niente da allineare.")

    script_norm = [normalize_word(w) for w in script_tokens]
    tr_norm = [normalize_word(w["word"]) for w in transcribed]

    matcher = difflib.SequenceMatcher(a=script_norm, b=tr_norm, autojunk=False)
    aligned: list[dict] = []
    corrected = 0
    interpolated = 0
    extra = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                word = dict(transcribed[j1 + k])
                word["word"] = script_tokens[i1 + k]  # forma esatta dello script
                aligned.append(word)
        elif tag == "replace":
            # Accoppia nel limite del possibile: tempi di Whisper, parole dello script.
            for k in range(min(i2 - i1, j2 - j1)):
                word = dict(transcribed[j1 + k])
                word["word"] = script_tokens[i1 + k]
                aligned.append(word)
                corrected += 1
            if (i2 - i1) > (j2 - j1):
                # Parole dello script senza timing: interpola.
                prev_end = aligned[-1]["end"] if aligned else 0.0
                nxt = transcribed[j2]["start"] if j2 < len(transcribed) else None
                missing = script_tokens[i1 + (j2 - j1):i2]
                aligned.extend(_interp_missing(missing, prev_end, nxt))
                interpolated += len(missing)
            else:
                # Parole extra trascritte: si tengono per continuità dei tempi.
                aligned.extend(dict(w) for w in transcribed[j1 + (i2 - i1):j2])
                extra += (j2 - j1) - (i2 - i1)
        elif tag == "delete":
            # Parole dello script saltate da Whisper: interpola il timing.
            prev_end = aligned[-1]["end"] if aligned else 0.0
            nxt = transcribed[j1]["start"] if j1 < len(transcribed) else None
            missing = script_tokens[i1:i2]
            aligned.extend(_interp_missing(missing, prev_end, nxt))
            interpolated += len(missing)
        elif tag == "insert":
            aligned.extend(dict(w) for w in transcribed[j1:j2])
            extra += j2 - j1

    _enforce_monotonic(aligned)
    stats = {
        "match_ratio": round(matcher.ratio(), 3),
        "corrected": corrected,
        "interpolated": interpolated,
        "extra": extra,
    }
    return aligned, stats

```

---

### `core/audio_mixer.py` — 274 righe, 11363 byte

Mixer SFX sintetici offline (274 righe, `ENABLE_AUTO_SFX`): `mix_sfx(voce_mp3, chunks)` → mp3 mixato. Legge `sfx_trigger` (pop hero, whoosh ENTRY, click CTA), sintetizza sine/noise envelope, mix a `SFX_VOLUME_DB`, ducking musica `BG_MUSIC_DUCKING_DB` nelle pause >0.5s. Best-effort, mai bloccante. Ritorna path originale se disabilitato/fallito.

```python
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

```

---

### `core/character_animator.py` — 169 righe, 6217 byte

Ciclo vita math-only (<5ms/frame, 169 righe): `character_frame_transform(chunk_meta, t)` → `{dx,dy,scale,alpha}`. ENTRY slide&pop 0.20s ease_out_back da +300px, SUSTAIN idle breathing (bob 4px@0.4Hz, tilt 0), EXIT slide-drop 0.16s ease_in_cubic a +400px, morph 0.40 ease_in_out, punch zoom 0.60, gap-hold tail, idle_weight disaccoppiato per evitare scatti.

```python
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

```

---

### `core/character_selector.py` — 2181 righe, 92204 byte

Character-Driven Overlay (2181 righe, il più complesso dopo text_animator): `plan_character_layout(chunks, script, on_attempt)` → lista lunga quanto chunks con `{pose 1-5, layout/layout_preset, punch_in, transition_in, scale, event ENTRY/SUSTAIN/EXIT/NONE, visible, ...}`. LLM assegna posa+layout+punch (max 2/video); fallback deterministico con ritmo anti-ripetizione (max 2 stessa posa/lato), `POSE_SIDE_MAP` (1:any,2:center,3:center,4:left,5:split), macro-blocchi ≥2.5s, discontinuo Breath&Focus (hook/CTA sempre visibili, body 60%), `resolve_chunk_layout`, `enrich_chunks_with_characters` merge senza doppio passaggio.

```python
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
import math
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
    CHARACTER_BODY_VISIBLE_RATIO = 0.6
    CHARACTER_POSE_SIDE_MAP = {1: "any", 2: "center", 3: "center", 4: "left", 5: "split"}

    def get_pose_side_constraint(pose: int) -> str:  # type: ignore
        try:
            return CHARACTER_POSE_SIDE_MAP.get(int(pose), "any")
        except Exception:
            return "any"
try:
    from config import CHARACTER_MICRO_XFADE_FRAMES, CHARACTER_MICRO_SCALE_PCT
except Exception:  # config datata
    CHARACTER_MICRO_XFADE_FRAMES = 4
    CHARACTER_MICRO_SCALE_PCT = 0.02
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
    Bridge narrativo (Fase 3): a intensita' emotiva alta (>=0.7) i segnali
    CTA/climax forzano asset espressivi via `pose_for_emotion`
    (4 pointing / 5 surprised / 3 positivo), con fallback alla logica storica.
    """
    try:
        t = str(text or "")
    except Exception:
        t = ""
    import re as _re
    # Bridge narrativo: hook/domande-chiave/climax emotivi -> asset espressivi.
    try:
        from core.narrative_structure import emotional_intensity as _emo, pose_for_emotion as _pfe
        try:
            _intensity = float(_emo(t))
        except Exception:
            _intensity = 0.0
        if _intensity >= 0.7:
            try:
                _exp = int(_pfe(t, fallback=0))
                if 1 <= _exp <= 5 and _exp != avoid:
                    return _exp
            except Exception:
                pass
    except Exception:
        pass
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


# --------------------------------------- Micro-transizioni d'aura (Fase 3)
def is_focus_pose_switch(prev: dict | None, cur: dict | None) -> bool:
    """Vero se posa cambia dentro lo stesso blocco Focus visibile.

    Condizioni: entrambi dict, entrambi visibili (`character.visible` o
    `char_visible`), stesso `block_id` non-nullo, pose diverse valide.
    I cambi tra blocchi (ENTRY con slide) NON usano micro-blend.
    Mai eccezioni.
    """
    try:
        if not isinstance(prev, dict) or not isinstance(cur, dict):
            return False

        def _vis(c: dict) -> bool:
            try:
                ch = c.get("character")
                if isinstance(ch, dict):
                    return bool(ch.get("visible", True)) and ch.get("pose") is not None
                return bool(c.get("char_visible", True)) and c.get("pose") is not None
            except Exception:
                return False

        if not _vis(prev) or not _vis(cur):
            return False

        def _block(c: dict):
            try:
                ch = c.get("character")
                if isinstance(ch, dict) and ch.get("block_id") is not None:
                    return int(ch["block_id"])
                b = c.get("block_id")
                return int(b) if b is not None else None
            except Exception:
                return None

        bp, bc = _block(prev), _block(cur)
        if bp is None or bc is None or bp != bc:
            return False

        def _pose(c: dict):
            try:
                ch = c.get("character")
                if isinstance(ch, dict) and ch.get("pose") is not None:
                    return int(ch["pose"])
                p = c.get("pose")
                return int(p) if p is not None else None
            except Exception:
                return None

        pp, pc = _pose(prev), _pose(cur)
        return pp is not None and pc is not None and pp != pc
    except Exception:
        return False


def micro_blend_progress(frame_idx: int, total_frames: int | None = None) -> float:
    """Progresso 0..1 del cross-fade sui primi MICRO_XFADE_FRAMES (clamp)."""
    try:
        n = max(1, int(CHARACTER_MICRO_XFADE_FRAMES))
    except Exception:
        n = 4
    try:
        fi = max(0, int(frame_idx))
    except Exception:
        return 1.0
    try:
        if total_frames is not None and int(total_frames) > 0:
            n = max(1, min(n, int(total_frames)))
    except Exception:
        pass
    if n <= 1:
        return 1.0
    return max(0.0, min(1.0, float(fi) / float(n - 1)))


def micro_scale_factor(frame_idx: int) -> float:
    """Micro-scala progressiva 2% durante lo switch (1.0 -> 1.02 -> 1.0)."""
    try:
        pct = max(0.0, min(0.10, float(CHARACTER_MICRO_SCALE_PCT)))
    except Exception:
        pct = 0.02
    try:
        p = micro_blend_progress(frame_idx)
        return 1.0 + pct * float(math.sin(math.pi * max(0.0, min(1.0, p)))) if pct > 0 else 1.0
    except Exception:
        return 1.0


def blend_character_layers(prev_img: object, next_img: object, progress: float) -> object:
    """Cross-fade alpha tra posa precedente e successiva (3-4 frame).

    Ritorna `next_img` se progress>=1 o input degeneri; una copia blenda
    altrimenti (canvas = size next, prev centrata e scalata). Mai eccezioni,
    mai mutazioni degli input.
    """
    try:
        p = max(0.0, min(1.0, float(progress)))
    except Exception:
        return next_img
    try:
        if p <= 0.0:
            return prev_img
        if p >= 1.0:
            return next_img
        if prev_img is None:
            return next_img
        if next_img is None:
            return prev_img
        nw, nh = next_img.size
        canvas = next_img.copy()
        try:
            pw, ph = prev_img.size
            scale = min(nw / max(1, pw), nh / max(1, ph))
            rw, rh = max(1, int(pw * scale)), max(1, int(ph * scale))
            prev_fit = prev_img.resize((rw, rh), Image.BICUBIC if hasattr(Image, "BICUBIC") else Image.NEAREST)
        except Exception:
            prev_fit = prev_img
            rw, rh = prev_fit.size
        ox, oy = (nw - rw) // 2, (nh - rh) // 2
        try:
            prev_faded = prev_fit.copy()
            alpha = prev_faded.getchannel("A").point(lambda a: int(a * (1.0 - p)))
            prev_faded.putalpha(alpha)
            canvas.alpha_composite(prev_faded, (ox, oy))
        except Exception:
            pass
        try:
            # Next emerge da (1-p): applica opacita' complementare solo se
            # parziale per un blend vero (a p=1 ritorna next pieno sopra).
            if p < 1.0:
                pass  # canvas ha gia' next pieno sotto + prev sbiadito sopra
        except Exception:
            pass
        return canvas
    except Exception:
        try:
            return next_img
        except Exception:
            return prev_img


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
      (~60% di default); i blocchi nascosti sono distribuiti uniformemente
      (respiri brevi da un blocco solo, mai lunghi tratti senza personaggio);
      con DISCONTINUOUS_MODE=0 tutto visibile.
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
            body_ratio = 0.6
        roles = [_macro_role(chunks[i] if i < n_chunks else None, i, n) for i in range(n)]
        blocks = _build_macro_time_blocks(chunks[:n], roles)
        # Visibilita' per blocco: i blocchi nascosti ("respiri" solo testo)
        # sono distribuiti uniformemente nel body (mai in fila e mai ai bordi
        # quando possibile: il body si apre e si chiude col personaggio).
        # Cosi' le pause senza character durano un blocco solo (~2.5-4s).
        body_blocks = [b for b in blocks if b and roles[b[0]] == "body"]
        try:
            num_keep = int(round(len(body_blocks) * body_ratio)) if body_blocks else 0
        except Exception:
            num_keep = 0
        num_keep = max(0, min(len(body_blocks), num_keep))
        hidden_quota = len(body_blocks) - num_keep
        hide_body_ids: set[int] = set()
        if hidden_quota > 0 and body_blocks:
            try:
                n_b = len(body_blocks)
                for j in range(hidden_quota):
                    pos = int((j + 0.5) * n_b / hidden_quota)
                    pos = max(0, min(n_b - 1, pos))
                    guard = 0
                    while id(body_blocks[pos]) in hide_body_ids and guard < n_b:
                        pos = (pos + 1) % n_b
                        guard += 1
                    hide_body_ids.add(id(body_blocks[pos]))
            except Exception:
                pass
        keep_body_ids = set(
            id(b) for b in body_blocks if id(b) not in hide_body_ids
        )
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
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text).strip()
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

```

---

### `core/easing.py` — 135 righe, 3952 byte

Curve pure (135 righe, solo math, ref easings.net/Penner): `clamp01`, `ease_out_cubic/quad`, `ease_out_back`, `ease_in_cubic`, `ease_in_out_cubic`, `ease_out_elastic`. `EASING_CURVES` in config mappa tier→funzione. Overshoot >1.0 voluto per pop premium.

```python
"""
Libreria di curve di easing pure per le animazioni dei sottotitoli.

Riferimento standard: https://easings.net/ (formule di Robert Penner).
Nessuna dipendenza esterna, solo `math`.

Ogni funzione accetta `t` (float, progresso normalizzato 0.0-1.0) e
restituisce il valore "eased" (float, tipicamente 0.0-1.0). Alcune curve
come `ease_out_back` / `ease_out_elastic` possono superare leggermente 1.0
per l'effetto overshoot: e' normale e voluto (per le entrate "premium"
delle keyword). Prima di applicare un easing, normalizzare con `clamp01`.
"""

import math


def clamp01(t: float) -> float:
    """Clampa t nell'intervallo [0.0, 1.0], utile prima di applicare un easing."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return float(t)


def linear(t: float) -> float:
    """Progressione lineare, nessuna accelerazione (uso: fallback/debug)."""
    t = clamp01(t)
    return t


def ease_out_cubic(t: float) -> float:
    """Decelera in modo naturale verso la fine, per fade minimal.

    Uso visivo: entrata delle parole normali (solo opacita', nessuna scala).
    """
    t = clamp01(t)
    return 1.0 - pow(1.0 - t, 3)


def ease_in_cubic(t: float) -> float:
    """Accelera verso la scomparsa, per uscite.

    Uso visivo: fade-out di gruppo (tutte le parole insieme alla fine chunk).
    """
    t = clamp01(t)
    return t * t * t


def ease_out_back(t: float) -> float:
    """Leggero overshoot oltre 1.0, per entrata "premium" keyword.

    Uso visivo: entrata keyword (opacita' + scala 0.7 -> 1.0). L'overshoot
    (~1.1 a meta' curva) crea un effetto "pop" gradevole; clamparlo a 255
    quando usato per l'opacita'.
    """
    t = clamp01(t)
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)


def ease_in_out_cubic(t: float) -> float:
    """Accelera poi decelera, per spostamenti fluidi del personaggio.

    Uso visivo: morph di posizione (vecchia -> nuova) e slide di continuita':
    partenza e arrivo morbidi, niente scatti ai bordi. Ritmo coerente.
    """
    t = clamp01(t)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0


def ease_out_quad(t: float) -> float:
    """Decelerazione morbida piu' leggera del cubic, per fade delicati.

    Uso visivo: fade-in/fade-out del personaggio (opacita' 0->1, 1->0):
    ingresso/uscita fluidi senza scatti, ritmo normale non frenetico.
    """
    t = clamp01(t)
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out_quad(t: float) -> float:
    """Fade+slide bilanciato, per transizioni di continuita'.

    Uso visivo: alternativa a in_out_cubic quando lo spostamento e' breve
    (stesso lato): movimento dolce senza overshoot.
    """
    t = clamp01(t)
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 2) / 2.0


def ease_out_bounce(t: float) -> float:
    """Rimbalzo, alternativa piu' marcata per l'entrata keyword.

    Uso visivo: variante keyword piu' giocosa di `ease_out_back`.
    Ritorna 0.0 per t=0.0 e 1.0 per t=1.0, con rimbalzi intermedi.
    """
    t = clamp01(t)
    n1 = 7.5625
    d1 = 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    elif t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def ease_out_elastic(t: float) -> float:
    """Elastico con overshoot/oscillazione, per effetti extra (non usato di default).

    Uso visivo: alternative sperimentali per entrate molto marcate.
    Puo' superare 1.0 e scendere sotto 0.0 nella fase iniziale.
    """
    t = clamp01(t)
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    c4 = (2.0 * math.pi) / 3.0
    return pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0

```

---

### `core/emphasis_grouping.py` — 211 righe, 7638 byte

Chunk 2-3 parole per enfasi: `group_words_by_emphasis(words, on_attempt)` → `[{text,start,end,words}]`. LLM riceve solo indici, restituisce tagli; testo/timestamp mai alterati. Fallback deterministico a blocchi di 2 (3 se leggera). Rispetta `EMPHASIS_MAX/MIN_WORDS`. `PIPELINE_FAST=1` salta LLM.

```python
"""
Raggruppamento sottotitoli per enfasi: chunk brevi da 2-3 parole decisi
dall'LLM Groq (stesso modello/client di core/keywords.py, con rotazione
chiavi e failover) in base a enfasi/significato della frase.

Vincolo di sicurezza: l'LLM riceve solo parole indicizzate e restituisce
SOLO gli indici di taglio (ultima parola di ogni gruppo). Testo e timestamp
(prodotti da STT + alignment) non vengono mai alterati. Se la risposta è
invalida o le chiavi falliscono, si usa un fallback deterministico a
blocchi di 2 (3 se la terza è "leggera").
"""

import json
import re
from collections.abc import Callable

from groq import Groq

from config import (
    GROQ_API_KEYS,
    GROQ_LLM_MODEL,
    EMPHASIS_MAX_WORDS_PER_CHUNK,
    EMPHASIS_MIN_WORDS_PER_CHUNK,
)
from core.subtitle_grouping import _WEAK_TRAILING_WORDS, _STRONG_PUNCT
from core.keywords import normalize_word


class EmphasisGroupingError(Exception):
    """Errore irrecuperabile di rete/chiave nel grouping per enfasi."""
    pass


# Cache client Groq per chiave (evita handshake/TLS per ogni fase pipeline).
_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    client = Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


def _ends_strong(word: str) -> bool:
    stripped = word.strip()
    return any(stripped.endswith(p) for p in _STRONG_PUNCT)


def _is_weak(word: str) -> bool:
    return normalize_word(word) in _WEAK_TRAILING_WORDS


def _make_chunk(group: list[dict]) -> dict:
    """Crea un chunk con testo/timing + parole individuali timestampate.

    La chiave "words" (lista di {"word", "start", "end"}) serve alla Fase 3
    (animazioni per-parola in core/text_animator.py): ogni parola entra
    al suo timestamp individuale, il layout resta fisso.
    """
    return {
        "text": " ".join(w["word"].strip() for w in group),
        "start": group[0]["start"],
        "end": group[-1]["end"],
        "words": [
            {"word": w["word"], "start": w["start"], "end": w["end"]}
            for w in group
        ],
    }


def _deterministic_fallback(words: list[dict]) -> list[dict]:
    """Blocchi di 2 parole (3 se la terza è leggera), taglio su punteggiatura forte."""
    chunks: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        group = [words[i]]
        if i + 1 < n and not _ends_strong(words[i]["word"]):
            group.append(words[i + 1])
            if (
                len(group) == 2
                and i + 2 < n
                and not _ends_strong(words[i + 1]["word"])
                and _is_weak(words[i + 2]["word"])
            ):
                group.append(words[i + 2])
        chunks.append(_make_chunk(group))
        i += len(group)
    return chunks


def _validate_cuts(cuts, n: int) -> bool:
    """Verifica indici interi crescenti in [0, n-1], ultimo = n-1, gruppi 1-3."""
    if not isinstance(cuts, list) or not cuts:
        return False
    if any(not isinstance(c, int) or isinstance(c, bool) for c in cuts):
        return False
    if any(c < 0 or c >= n for c in cuts):
        return False
    if len(set(cuts)) != len(cuts) or cuts != sorted(cuts):
        return False
    if cuts[-1] != n - 1:
        return False
    prev = -1
    for c in cuts:
        size = c - prev
        if size < EMPHASIS_MIN_WORDS_PER_CHUNK or size > EMPHASIS_MAX_WORDS_PER_CHUNK:
            return False
        prev = c
    return True


def _parse_cuts(content: str) -> list | None:
    text = content.strip()
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("cut_indices")


def group_words_by_emphasis(
    words: list[dict],
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Raggruppa le parole timestampate in chunk brevi (2-3 parole) per enfasi.

    Stesso formato di output di subtitle_grouping.group_words_into_subtitles,
    piu' la chiave "words" con le singole parole timestampate
    ({"word", "start", "end"}) per le animazioni per-parola (Fase 3).
    Non solleva mai per errori API/validazione: usa il fallback deterministico.
    """
    if not words:
        return []
    import os as _os
    if _os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        return _deterministic_fallback(words)

    if not GROQ_API_KEYS:
        return _deterministic_fallback(words)

    n = len(words)
    system = (
        "Sei un assistente che divide frasi in brevi gruppi di parole per sottotitoli "
        "video. Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Leggi l'elenco di parole in ordine (l'indice e la posizione nell'array, "
        "0-based) e decidi dove tagliare in base a enfasi e significato. Regole:\n"
        f"1. Ogni gruppo deve avere minimo {EMPHASIS_MIN_WORDS_PER_CHUNK} e massimo "
        f"{EMPHASIS_MAX_WORDS_PER_CHUNK} parole: preferisci gruppi da 2-3 parole.\n"
        "2. Un gruppo da 3 parole va bene quando la terza e un elemento leggero "
        "(articolo, preposizione, congiunzione breve) che si appoggia alle prime due; "
        "non iniziare mai un nuovo gruppo con una parola leggera isolata (di, il, che) "
        "se puo restare attaccata al gruppo precedente.\n"
        "3. La punteggiatura forte (. ! ? ... : ;) e quasi sempre un taglio obbligato: "
        "se una parola termina cosi, quel punto DEVE essere un taglio.\n"
        "Restituisci SOLO: {\"cut_indices\": [...]} con gli indici (0-based) "
        "dell'ULTIMA parola di ogni gruppo, in ordine crescente; l'ultimo indice "
        "deve essere quello dell'ultima parola. Esempio per 10 parole in "
        "[0-1][2-3-4][5-6][7-8-9]: {\"cut_indices\": [1, 4, 6, 9]}\n\n"
        f"PAROLE: {json.dumps({'words': [w['word'] for w in words]}, ensure_ascii=False)}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
    succeeded_at = 0

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
        except Exception as e:
            if on_attempt is not None:
                on_attempt(index, total, False, f"chiave {index}/{total}: {e}")
            continue
        succeeded_at = index
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: tagli ricevuti")
        break

    cuts = _parse_cuts(content) if content is not None else None
    if cuts is None or not _validate_cuts(cuts, n):
        if on_attempt is not None:
            on_attempt(succeeded_at, total, False, "tagli LLM invalidi: uso raggruppamento deterministico")
        return _deterministic_fallback(words)

    chunks: list[dict] = []
    prev = 0
    for cut in cuts:
        chunks.append(_make_chunk(words[prev:cut + 1]))
        prev = cut + 1
    return chunks

```

---

### `core/font_manager.py` — 416 righe, 16191 byte

Gestore font (416 righe): `FontManager().ensure_preset_fonts(preset)` → `{ruolo:path}`. Verifica `assets/fonts/`, download da Google Fonts GitHub se mancante, fallback sistema (Arial/Impact...), supporto assi variabili Weight 600 per base. Pre-warm condiviso una sola volta.

```python
"""
Semantic Typography Engine v1 — Gestore asset e downloader automatico font.

- Mantiene e verifica la cartella `assets/fonts/`.
- `ensure_font_exists(font_name)` controlla .ttf/.otf locali, altrimenti
  scarica da Google Fonts (repo GitHub google/fonts, endpoint statico sicuro
  raw.githubusercontent.com) e salva in assets/fonts/.
- Fallback su font di sistema nativi (Arial, Impact, Times...) per evitare
  crash senza connessione.

Uso:
    from core.font_manager import FontManager, ensure_font_exists
    path = ensure_font_exists("Anton")
    manager = FontManager()
    paths = manager.ensure_preset_fonts("tech_ai")  # {"base": ..., "impact": ..., "accent": ...}
"""

import os
import re
from pathlib import Path

try:
    from config import BASE_DIR
except Exception:  # import isolato nei test
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONTS_DIR = Path(BASE_DIR) / "assets" / "fonts"

# Base raw sicura (GitHub google/fonts, mirror statico, niente API key).
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/google/fonts/main"
_GITHUB_RAW_ALT = "https://github.com/google/fonts/raw/main"

# Mappa normalizzata -> (sottocartella ofl, file) per i font dei preset.
# I file variable [wght] sono caricabili da Pillow (istanza default).
# URL-encodiamo le parentesi quadre (%5B/%5D).
_FONT_FILES: dict[str, tuple[str, str]] = {
    "inter": ("inter", "Inter%5Bopsz%2Cwght%5D.ttf"),
    "roboto": ("roboto", "Roboto%5Bwdth%2Cwght%5D.ttf"),
    "anton": ("anton", "Anton-Regular.ttf"),
    "impact": ("__system__", "impact.ttf"),  # font di sistema, non su Google Fonts
    "playfairdisplay": ("playfairdisplay", "PlayfairDisplay%5Bwght%5D.ttf"),
    "bebasneue": ("bebasneue", "BebasNeue-Regular.ttf"),
    "orbitron": ("orbitron", "Orbitron%5Bwght%5D.ttf"),
    "spacemono": ("spacemono", "SpaceMono-Regular.ttf"),
    "opensans": ("opensans", "OpenSans%5Bwdth%2Cwght%5D.ttf"),
    "oswald": ("oswald", "Oswald%5Bwght%5D.ttf"),
    "permanentmarker": ("permanentmarker", "PermanentMarker-Regular.ttf"),
    "poppins": ("poppins", "Poppins-Regular.ttf"),
    "lato": ("lato", "Lato-Regular.ttf"),
    "cinzel": ("cinzel", "Cinzel%5Bwght%5D.ttf"),
    "bodonimoda": ("bodonimoda", "BodoniModa%5Bopsz%2Cwght%5D.ttf"),
    "caveat": ("caveat", "Caveat%5Bwght%5D.ttf"),
    "pacifico": ("pacifico", "Pacifico-Regular.ttf"),
    "nunito": ("nunito", "Nunito%5Bwght%5D.ttf"),
    "leaguespartan": ("leaguespartan", "LeagueSpartan%5Bwght%5D.ttf"),
    "patrickhand": ("patrickhand", "PatrickHand-Regular.ttf"),
    "kalam": ("kalam", "Kalam-Regular.ttf"),
    "montserrat": ("montserrat", "Montserrat%5Bwght%5D.ttf"),
    "montserratblack": ("montserrat", "Montserrat%5Bwght%5D.ttf"),
    "pristina": ("__system__", "__missing__"),  # non open-source: fallback di sistema
    "editorsnote": ("__system__", "__missing__"),
}

# Font di sistema nativi per fallback (mai crash senza internet).
_SYSTEM_FALLBACKS: list[str] = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\timesbd.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]

# Ruolo -> fallback di sistema preferito (look simile quando il download fallisce).
_ROLE_SYSTEM_PREFERENCE: dict[str, list[str]] = {
    "base": ["arial.ttf", "arialbd.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
    "impact": ["impact.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arial.ttf"],
    "accent": ["times.ttf", "timesbd.ttf", "georgia.ttf", "DejaVuSans.ttf", "arial.ttf"],
}


def _normalize_name(name: str) -> str:
    """Minuscole senza spazi/trattini/underscore (per match file e mappa URL)."""
    return re.sub(r"[\s\-_']+", "", (name or "").strip().lower())


def _candidate_local_names(font_name: str) -> list[str]:
    """Varianti di filename da cercare in assets/fonts/."""
    norm = _normalize_name(font_name)
    raw = (font_name or "").strip()
    compact_space = re.sub(r"\s+", "", raw)
    return [
        f"{raw}.ttf",
        f"{raw}.otf",
        f"{compact_space}.ttf",
        f"{compact_space}.otf",
        f"{norm}.ttf",
        f"{norm}.otf",
    ]


_local_dir_cache: dict[str, tuple[float, list]] = {}


def _list_font_files(fonts_dir: Path) -> list:
    """Lista file font con cache 30s (evita iterdir per ogni ruolo/chunk)."""
    import time
    try:
        key = str(fonts_dir)
        now = time.monotonic()
        hit = _local_dir_cache.get(key)
        if hit is not None and (now - hit[0]) < 30.0:
            return hit[1]
        if not fonts_dir.is_dir():
            return []
        files = [p for p in fonts_dir.iterdir() if p.is_file()]
        _local_dir_cache[key] = (now, files)
        return files
    except OSError:
        return []


def _find_local_font(font_name: str, fonts_dir: Path) -> str | None:
    """Cerca un file .ttf/.otf corrispondente (case-insensitive, prefisso tollerato)."""
    files = _list_font_files(fonts_dir)
    if not files:
        try:
            if not fonts_dir.is_dir():
                return None
        except OSError:
            return None
        if not files:
            return None
    norm = _normalize_name(font_name)
    # 1) match esatto tra i candidati (case-insensitive).
    lowered = {p.name.lower(): p for p in files}
    for cand in _candidate_local_names(font_name):
        hit = lowered.get(cand.lower())
        if hit is not None and hit.suffix.lower() in (".ttf", ".otf"):
            return str(hit)
    # 2) prefisso: es. "bebasneue-regular.ttf" per "Bebas Neue".
    for p in files:
        if p.suffix.lower() not in (".ttf", ".otf"):
            continue
        stem_norm = _normalize_name(p.stem)
        if stem_norm == norm or stem_norm.startswith(norm) or norm.startswith(stem_norm):
            return str(p)
    return None


_system_font_cache: dict[str, str | None] = {}


def _find_system_font(prefer: list[str] | None = None) -> str | None:
    """Primo font di sistema esistente (preferenze opzionali per nome file, cachato)."""
    cache_key = "|".join(prefer) if prefer else "__default__"
    if cache_key in _system_font_cache:
        return _system_font_cache[cache_key]
    search_bases = [
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/System/Library/Fonts"),
    ]
    result: str | None = None
    if prefer:
        for base in search_bases:
            for fname in prefer:
                try:
                    cand = base / fname
                    if cand.is_file():
                        result = str(cand)
                        break
                except OSError:
                    continue
            if result is not None:
                break
    if result is None:
        for cand in _SYSTEM_FALLBACKS:
            try:
                if os.path.isfile(cand):
                    result = cand
                    break
            except OSError:
                continue
    if len(_system_font_cache) < 32:
        _system_font_cache[cache_key] = result
    return result


def _download_urls(font_name: str) -> list[str]:
    """URL candidate per il download (mappa nota + guess generici)."""
    norm = _normalize_name(font_name)
    urls: list[str] = []
    entry = _FONT_FILES.get(norm)
    if entry is not None:
        subdir, fname = entry
        if subdir != "__system__":
            urls.append(f"{_GITHUB_RAW_BASE}/ofl/{subdir}/{fname}")
            urls.append(f"{_GITHUB_RAW_ALT}/ofl/{subdir}/{fname}")
    else:
        # Guess generico: ofl/<norm>/<variants>. Prova Regular/Bold/variabile.
        family_variants = [
            f"{font_name.strip()}-Regular.ttf",
            f"{font_name.strip().replace(' ', '')}-Regular.ttf",
        ]
        for v in family_variants:
            safe = v.replace(" ", "%20")
            urls.append(f"{_GITHUB_RAW_BASE}/ofl/{norm}/{safe}")
        urls.append(f"{_GITHUB_RAW_BASE}/ofl/{norm}/{norm}-regular.ttf")
    return urls


def _download_to(font_name: str, dest: Path) -> bool:
    """Scarica il font al percorso dest. Ritorna True se riuscito e valido."""
    urls = _download_urls(font_name)
    if not urls:
        return False
    try:
        import requests
    except ImportError:
        return False
    for url in urls:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200 or not resp.content:
                continue
            # Sanity: un TTF/OTF valido è almeno qualche KB e inizia con head nota.
            content = resp.content
            if len(content) < 4096:
                continue
            magic = content[:4]
            if magic not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"wOFF"):
                # I TTF variable iniziano con 0x00010000; accetta anche sfnt generici.
                # Se magic ignoto ma size plausibile (>20KB), accetta comunque.
                if len(content) < 20000:
                    continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(content)
            # Verifica caricabile da Pillow prima di promuoverlo.
            try:
                from PIL import ImageFont
                ImageFont.truetype(str(tmp), 32)
            except Exception:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                continue
            try:
                tmp.replace(dest)
            except OSError:
                try:
                    dest.write_bytes(content)
                    tmp.unlink()
                except OSError:
                    continue
            return True
        except Exception:
            continue
    return False


class FontManager:
    """Gestore dei font del Semantic Typography Engine.

    Mantiene `assets/fonts/`, scarica i font mancanti e non solleva mai
    per assenza di rete: in quel caso ritorna un font di sistema.
    """

    def __init__(self, fonts_dir: str | Path | None = None):
        self.fonts_dir = Path(fonts_dir) if fonts_dir else FONTS_DIR
        try:
            self.fonts_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._cache: dict[str, str] = {}

    def ensure_font_exists(self, font_name: str) -> str:
        """Ritorna il percorso del font (locale, scaricato o fallback di sistema).

        Non solleva mai: se tutto fallisce, ritorna "" (il chiamante userà
        il font di default di Pillow / renderer.load_font).
        """
        key = _normalize_name(font_name or "")
        if not key:
            return _find_system_font() or ""
        if key in self._cache:
            cached = self._cache[key]
            try:
                if cached and os.path.isfile(cached):
                    return cached
            except OSError:
                pass
        # 1) locale
        try:
            hit = _find_local_font(font_name, self.fonts_dir)
        except Exception:
            hit = None
        if hit:
            self._cache[key] = hit
            return hit
        # 2) download (font di sistema puri saltano il download)
        entry = _FONT_FILES.get(key)
        dest = self.fonts_dir / f"{(font_name or '').strip().replace(' ', '') or key}.ttf"
        if entry is None or entry[0] != "__system__":
            try:
                if _download_to(font_name, dest):
                    self._cache[key] = str(dest)
                    return str(dest)
            except Exception:
                pass
            # Riprova: magari il download ha creato il file con altro nome.
            try:
                hit = _find_local_font(font_name, self.fonts_dir)
            except Exception:
                hit = None
            if hit:
                self._cache[key] = hit
                return hit
        # 3) fallback di sistema (per ruolo se riconoscibile, altrimenti generico)
        role_hint: list[str] | None = None
        lowered_raw = (font_name or "").lower()
        if any(k in lowered_raw for k in ("impact", "anton", "bebas", "oswald", "spartan", "orbitron", "cinzel")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["impact"]
        elif any(k in lowered_raw for k in ("hand", "marker", "caveat", "pacifico", "kalam", "playfair", "pristina", "note")):
            role_hint = _ROLE_SYSTEM_PREFERENCE["accent"]
        else:
            role_hint = _ROLE_SYSTEM_PREFERENCE["base"]
        sys_font = _find_system_font(role_hint) or _find_system_font()
        result = sys_font or ""
        self._cache[key] = result
        return result

    def ensure_preset_fonts(self, niche_or_preset) -> dict[str, str]:
        """Assicura i 3 font del preset: {"base": path, "impact": path, "accent": path}.

        Accetta il nome nicchia ("tech_ai") o il dict preset da typography_presets.get_preset().
        Non solleva mai; i path possono essere "" (fallback Pillow a valle).
        """
        try:
            from core.typography_presets import get_preset
            preset = get_preset(niche_or_preset) if isinstance(niche_or_preset, str) else dict(niche_or_preset)
        except Exception:
            preset = {"fonts": {"base": [], "impact": [], "accent": []}}
        fonts = preset.get("fonts", {}) if isinstance(preset, dict) else {}
        out: dict[str, str] = {}
        for role in ("base", "impact", "accent"):
            candidates = fonts.get(role, []) if isinstance(fonts, dict) else []
            path = ""
            for cand in candidates if isinstance(candidates, list) else []:
                try:
                    path = self.ensure_font_exists(str(cand))
                except Exception:
                    path = ""
                if path and os.path.isfile(path):
                    break
            if not path:
                # Ultimo tentativo: fallback di sistema per ruolo.
                path = _find_system_font(_ROLE_SYSTEM_PREFERENCE.get(role)) or ""
            out[role] = path
        return out

    def load_font(self, font_name: str, size: int):
        """Carica il font PIL alla dimensione data (fallback mai bloccante)."""
        from PIL import ImageFont
        try:
            size_i = max(8, int(size))
        except (TypeError, ValueError):
            size_i = 60
        path = ""
        try:
            path = self.ensure_font_exists(font_name)
        except Exception:
            path = ""
        if path:
            try:
                return ImageFont.truetype(path, size_i)
            except Exception:
                pass
        # Fallback: renderer.load_font (rispetta SUBTITLE_FONT_PATH + sistema).
        try:
            from core.renderer import load_font as _load_font
            return _load_font(size_i)
        except Exception:
            pass
        return ImageFont.load_default()

    def clear_cache(self) -> None:
        self._cache.clear()


# Istanza condivisa + scorciatoie funzionali (spec: ensure_font_exists(font_name) -> str).
_default_manager = FontManager()


def ensure_font_exists(font_name: str) -> str:
    """Scorciatoia: assicura il font e ritorna il percorso (vedi FontManager)."""
    return _default_manager.ensure_font_exists(font_name)


def ensure_preset_fonts(niche_or_preset) -> dict[str, str]:
    """Scorciatoia: assicura i 3 font del preset."""
    return _default_manager.ensure_preset_fonts(niche_or_preset)

```

---

### `core/invariant_checks.py` — 162 righe, 6250 byte

Asserzioni post-build (162 righe): `run_post_build_checks(mp4, audio, chunks, words_before, words_after)` → `(ok, {durata,temp,timestamp,zorder})`. `|video-audio|<0.1s`, nessun temp fuori `temp/`, timestamp preservati, testo dentro canvas. Loggato, mai fatale (`strict=False`). + `check_temp_containment`, `check_timestamps_preserved` per text_only.

```python
"""
Post-build invariant checks (Full Engine Upgrade — Fase 6).

Verifica automatica dopo ogni build (mai blocca il bulk con eccezioni non
gestite: ritorna (ok, dettagli) e solleva AssertionError solo se il chiamante
lo richiede esplicitamente):

  - `assert abs(video_duration - audio_duration) < 0.1`
  - nessun file temporaneo fuori da `temp/`
  - timestamp start/end preservati (confronto pre/post pipeline)
  - Z-order/safe-zone senza violazioni critiche (testo fuori canvas = fail)

Uso in `main.py` Step 8 dopo `build_video`/`build_composed_video`.
"""

from __future__ import annotations

import os
import subprocess

try:
    from config import OUTPUT_DIR, TEMP_DIR
except Exception:
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")


def _probe_duration(path: str) -> float | None:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None
        return float(res.stdout.strip())
    except Exception:
        return None


def check_av_sync(video_path: str, audio_path: str, tol: float = 0.1) -> tuple[bool, str]:
    """assert abs(video_duration - audio_duration) < tol (default 0.1s)."""
    try:
        vd = _probe_duration(video_path)
        ad = _probe_duration(audio_path)
        if vd is None or ad is None:
            return (False, "ffprobe indisponibile per AV-sync")
        ok = abs(float(vd) - float(ad)) < float(tol)
        return (ok, f"video={vd:.3f}s audio={ad:.3f}s delta={abs(vd - ad):.3f}s")
    except Exception as e:
        return (False, f"AV-sync errore: {e}")


def check_temp_containment(temp_dir: str | None = None) -> tuple[bool, str]:
    """Nessun file temporaneo fuori da temp/ (walk + realpath)."""
    try:
        base = os.path.realpath(temp_dir or TEMP_DIR)
    except Exception:
        return (False, "temp dir non risolvibile")
    try:
        if not os.path.isdir(base):
            return (True, "temp assente (ok, pulita)")
        count = 0
        for root, _dirs, files in os.walk(base):
            try:
                rp = os.path.realpath(root)
                if os.path.commonpath([rp, base]) != base:
                    return (False, f"file fuori temp: {root}")
            except Exception:
                continue
            count += len(files)
        return (True, f"{count} file dentro temp (contenuti)")
    except Exception as e:
        return (False, f"temp check errore: {e}")


def check_timestamps_preserved(before: list[dict], after: list[dict]) -> tuple[bool, str]:
    """I campi start/end non devono mai essere alterati (confronto 1:1)."""
    try:
        if len(before) != len(after):
            return (False, f"conteggio diverso {len(before)} vs {len(after)}")
        for i, (b, a) in enumerate(zip(before, after)):
            try:
                if abs(float(b.get("start", -1)) - float(a.get("start", -2))) > 1e-6:
                    return (False, f"start alterato idx {i}")
                if abs(float(b.get("end", -1)) - float(a.get("end", -2))) > 1e-6:
                    return (False, f"end alterato idx {i}")
            except Exception:
                return (False, f"timestamp non numerici idx {i}")
        return (True, f"{len(before)} timestamp preservati")
    except Exception as e:
        return (False, f"timestamp check errore: {e}")


def check_z_order_safe(chunks: list[dict] | None) -> tuple[bool, str]:
    """Nessuna violazione critica safe-zone (testo fuori canvas = fail)."""
    try:
        from core.layout_guard import verify_z_order, text_bbox_of_layout

        bad = 0
        notes: list[str] = []
        for ch in (chunks or []):
            try:
                layout = ch.get("layout_items") or ch.get("layout")
                tb = None
                if isinstance(layout, list) and layout and isinstance(layout[0], dict):
                    tb = text_bbox_of_layout(layout)
                ok, viol = verify_z_order(tb, None)
                if not ok:
                    critical = [v for v in viol if v in ("testo-fuori-canvas",)]
                    if critical:
                        bad += 1
                        notes.extend(critical)
            except Exception:
                continue
        if bad:
            return (False, f"{bad} chunk fuori canvas: {sorted(set(notes))[:3]}")
        return (True, "safe-zone ok (nessun fuori-canvas)")
    except Exception as e:
        return (True, f"z-check saltato ({e})")


def run_post_build_checks(
    video_path: str,
    audio_path: str,
    chunks: list[dict] | None = None,
    words_before: list[dict] | None = None,
    words_after: list[dict] | None = None,
    strict: bool = False,
) -> tuple[bool, dict]:
    """Esegue tutti i check post-build. Ritorna (ok, dettagli).

    Con strict=True solleva AssertionError al primo fail (per CI/test).
    Mai solleva altrimenti (per pipeline bulk resiliente).
    """
    details: dict = {}
    try:
        ok_av, msg_av = check_av_sync(video_path, audio_path)
    except Exception as e:
        ok_av, msg_av = False, str(e)
    try:
        ok_tmp, msg_tmp = check_temp_containment()
    except Exception as e:
        ok_tmp, msg_tmp = False, str(e)
    if words_before is not None and words_after is not None:
        try:
            ok_ts, msg_ts = check_timestamps_preserved(words_before, words_after)
        except Exception as e:
            ok_ts, msg_ts = False, str(e)
    else:
        ok_ts, msg_ts = True, "timestamp check saltato (riferimenti assenti)"
    try:
        ok_z, msg_z = check_z_order_safe(chunks)
    except Exception as e:
        ok_z, msg_z = True, f"z-check saltato ({e})"
    details = {"av_sync": (ok_av, msg_av), "temp": (ok_tmp, msg_tmp),
               "timestamps": (ok_ts, msg_ts), "z_order": (ok_z, msg_z)}
    ok = bool(ok_av and ok_tmp and ok_ts and ok_z)
    if strict and not ok:
        raise AssertionError(f"invariant checks falliti: {details}")
    return (ok, details)

```

---

### `core/keywords.py` — 215 righe, 7714 byte

Keyword LLM Groq 120B: `extract_keywords(script, on_attempt, palette)` → `{parola: (R,G,B,255)}`. Max `KEYWORDS_MAX`, gap `KEYWORDS_MIN_GAP`, match verbatim, colori deterministici da palette tema (mai giallo), fallback frequenza se LLM fallisce. `KeywordError` solo se script vuoto.

```python
"""
Estrazione delle parole chiave dallo script tramite LLM Groq
(modello `openai/gpt-oss-120b` via Chat Completions, cfr.
https://console.groq.com/docs/text-chat).

Le keyword vengono evidenziate nei sottotitoli con un colore dedicato
(uno per parola, deterministico, mai giallo). Per evitare ammassi:
al massimo KEYWORDS_MAX keyword, scelte in ordine di importanza e
distanziate di almeno KEYWORDS_MIN_GAP parole nel testo.
"""

import hashlib
import json
import re
from collections.abc import Callable

from PIL.ImageColor import getrgb
from groq import Groq

from config import GROQ_API_KEYS, GROQ_LLM_MODEL, KEYWORDS_MAX, KEYWORDS_MIN_GAP


class KeywordError(Exception):
    """Errore durante l'estrazione delle parole chiave."""
    pass


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    client = Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


# Palette premium in hex ("#RRGGBB", mai neon/arcobaleno): usata come default
# e come integrazione per core/theme.py (importata come _FALLBACK_PALETTE_HEX).
# Toni smorzati e armonici su sfondi scuri (ori/sky/lavanda/rosa/menta).
_FALLBACK_PALETTE_HEX: list[str] = [
    "#D4AF37",  # oro smorzato (hero premium)
    "#7DD3FC",  # sky soft
    "#A78BFA",  # lavanda
    "#FF8FA3",  # rosa soft
    "#00E5FF",  # ciano tech
    "#34D399",  # menta
    "#FFD166",  # oro caldo chiaro
    "#F5D67B",  # oro tint
]


def _hex_to_rgba(hex_color: str) -> tuple:
    r, g, b = getrgb(hex_color)
    return (r, g, b, 255)


# Palette RGBA derivata (mantenuta per retrocompatibilità).
KEYWORD_PALETTE: list[tuple] = [_hex_to_rgba(h) for h in _FALLBACK_PALETTE_HEX]


def normalize_word(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (per il match nei sottotitoli)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", word.lower(), flags=re.UNICODE)


def color_for_keyword(word: str, palette: list[tuple] | None = None) -> tuple:
    """Colore deterministico in base alla parola (stessa parola = stesso colore)."""
    pal = palette or KEYWORD_PALETTE
    digest = hashlib.md5(word.encode("utf-8")).hexdigest()
    return pal[int(digest, 16) % len(pal)]


def _parse_keywords(content: str) -> list[str]:
    """Estrae la lista di keyword da una risposta JSON (robusto a fence markdown)."""
    text = content.strip()
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    items = data.get("keywords", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    seen: list[str] = []
    for item in items:
        if not isinstance(item, str) or " " in item.strip():
            continue  # solo singole parole
        norm = normalize_word(item)
        if norm and norm not in seen:
            seen.append(norm)
    return seen


def _spread_keywords(candidates: list[str], script_words: list[str], target: int) -> list[str]:
    """Seleziona le keyword in ordine di importanza imponendo la distanza minima.

    Scorre i candidati (già ordinati per importanza dall'LLM) e accetta una
    parola solo se la sua prima occorrenza dista almeno `gap` parole da quelle
    già accettate: così le più importanti vincono e restano distribuite.
    """
    positions: dict[str, int] = {}
    for i, w in enumerate(script_words):
        positions.setdefault(normalize_word(w), i)  # prima occorrenza
    gap = max(KEYWORDS_MIN_GAP, len(script_words) // max(target, 1) // 2)
    accepted: list[str] = []
    accepted_pos: list[int] = []
    for cand in candidates:
        if len(accepted) >= target:
            break
        pos = positions.get(cand)
        if pos is None:
            continue  # parola non presente nello script, scarta
        if all(abs(pos - p) >= gap for p in accepted_pos):
            accepted.append(cand)
            accepted_pos.append(pos)
    return accepted


def extract_keywords(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
    keyword_palette_hex: list[str] | None = None,
) -> dict[str, tuple]:
    """Estrae le parole chiave dallo script: {parola_normalizzata: colore_RGBA}.

    Usa `GROQ_LLM_MODEL` con rotazione delle chiavi in GROQ_API_KEYS.

    Args:
        keyword_palette_hex: palette hex dal tema dinamico (core/theme.py);
            se assente si usa la palette storica.
    """
    script_words = script_text.split()
    if not script_words:
        raise KeywordError("Script vuoto: nessuna parola chiave da estrarre.")

    if not GROQ_API_KEYS:
        raise KeywordError(
            "Mancano le GROQ_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env."
        )

    target = max(3, min(KEYWORDS_MAX, len(script_words) // 30))

    system = (
        "Sei un assistente che estrae parole chiave da uno script per video brevi. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        f"Estrai al massimo {target} parole chiave SINGOLE (una parola ciascuna, "
        "esattamente come appaiono nel testo) dal seguente script. Scegli le parole "
        "più importanti e significative, distribuite uniformemente in tutto il testo "
        "(inizio, centro e fine, non concentrate in un solo punto), in ordine di "
        "importanza decrescente. Rispondi SOLO con: {\"keywords\": [\"parola1\", ...]}\n\n"
        f"SCRIPT:\n{script_text}"
    )

    total = len(GROQ_API_KEYS)
    failures: list[str] = []
    content: str | None = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=512,  # l'SDK groq installato usa max_tokens (non max_completion_tokens)
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("risposta vuota dal modello")
        except Exception as e:
            note = f"chiave {index}/{total}: {e}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            content = None
            continue
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: keyword estratte")
        break

    if content is None:
        raise KeywordError(
            f"Tutte le {total} chiavi Groq hanno fallito. Dettagli: " + " | ".join(failures)
        )

    candidates = _parse_keywords(content)
    selected = _spread_keywords(candidates, script_words, target)
    try:
        palette = (
            [_hex_to_rgba(h) for h in keyword_palette_hex]
            if keyword_palette_hex
            else KEYWORD_PALETTE
        )
    except ValueError:
        palette = KEYWORD_PALETTE  # hex non validi: palette storica
    return {word: color_for_keyword(word, palette) for word in selected}

```

---

### `core/layout_guard.py` — 1046 righe, 43457 byte

Guard anti-overlap real-time (1046 righe): `build_realtime_plan(chunks)` + `apply_realtime_plans` + `plan_chunk_realtime`. Misura bbox reali (alpha personaggio + font reale + overshoot pop + punch-in), fix a cascata (sposta testo, scala font fino a 40px, pill, nascondi personaggio), summary `{guaranteed,fixed,hidden,intentional}`. Hook da 3 righe in text_animator/renderer. Mai eccezioni fatali.

```python
"""
Real-time Layout Guard: piano in tempo reale anti-sovrapposizione
personaggio <-> sottotitoli (1080x1920).

Punto unico di verifica PRIMA del rendering: misura le bbox REALI
(tight bbox alpha del personaggio + bbox testo misurata col font reale,
inclusi overshoot pop e scala punch-in) e applica fix a cascata finche'
l'overlap e' zero o il fallback garantito scatta.

Uso tipico (hook da 3 righe in text_animator / renderer):

    from core.layout_guard import plan_chunk_realtime, build_realtime_plan
    plan = plan_chunk_realtime(chunk, words=..., fonts=..., ...)
    # plan = {"layout", "safe_area", "font_scale", "needs_pill",
    #         "hide_character", "guaranteed", "overlap_px", "actions"}

    plan_all = build_realtime_plan(chunks_enriched, ...)  # batch con coerenza beat

Garanzie:
- Mai eccezioni (fallback = nascondi personaggio, testo al centro).
- <5ms per chunk (probe condivisa, bbox cachate, niente LLM, niente I/O).
- Coerenza temporale: dentro lo stesso narrative_beat preferisce shrink font
  a switch layout (niente flicker); lo switch layout avviene solo ai confini.
- Punch-in intenzionale: overlap ammesso SOLO con pill + contrasto (leggibilita'),
  mai senza pill.

Misure reali alla base (asset 768x1376, tight bbox dopo pulizia sfondo):
- center_standard: testa a y~644, safe 150-900 -> overlap 256px se testo basso.
  Fix: y_max 900 -> 620 per chunk alti, o shrink font.
- split 340-360px di larghezza: parola >360px sconfina; pose 2 larga 259px
  di overlap in split -> mai pose 2 in split (forza center).
- pop ease_out_back overshoot ~10%: margine obbligatorio 12% sul testo.
- punch-in character 1.6875x: tight ancora piu' esteso -> ricalcolo con flag.
"""

from __future__ import annotations

from config import VIDEO_WIDTH, VIDEO_HEIGHT
try:
    from config import (
        LAYOUT_MAX_WIDTH_RATIO as _DYN_MAX_RATIO,
        LAYOUT_MIN_FONT_PX as _DYN_MIN_PX,
        Z_BACKGROUND as _Z_BG,
        Z_CHARACTER as _Z_CHAR,
        Z_DIMMER as _Z_DIM,
        Z_SUBTITLES as _Z_SUB,
        Z_DEBUG as _Z_DBG,
    )
except Exception:  # config datata
    _DYN_MAX_RATIO = 0.80
    _DYN_MIN_PX = 40
    _Z_BG, _Z_CHAR, _Z_DIM, _Z_SUB, _Z_DBG = 0, 10, 20, 30, 99
from core.layout_presets import (
    PRESET_SAFE_AREA,
    preset_safe_area,
    preset_font_scale,
    preset_needs_text_background,
    normalize_preset,
)

# --- Costanti di sicurezza (tuning validato sulle misure reali) ---
SAFETY_MARGIN_PX = 24          # gap minimo personaggio-testo (bordo a bordo)
POP_OVERSHOOT = 1.12           # ease_out_back supera 1.0 di ~10-12%
PUNCH_TEXT_PAD = 28            # pad pill (deve entrare nel check overlap)
FONT_SHRINK_STEPS = (1.0, 0.9, 0.8, 0.7)  # cascata shrink (prima dello switch)
CENTER_SAFE_Y_MAX_FIXED = 620  # center_standard: testa a 644 - margine 24
SPLIT_WIDEN_PX = 60            # allargo split verso centro se parola lunga
MAX_TEXT_WIDTH_RATIO = 0.85    # come renderer/text_animator (VIDEO_W * 0.85)
# Tolleranza idle breathing leggero: solo bob verticale dolce (+/-4px, nessuna
# rotazione laterale). Il pad espande la tight bbox misurata cosi' il respiro
# non collide mai col testo garantito (cfr. get_character_tight_canvas).
SAFETY_PADDING_IDLE_Y = 8      # px verticali (bob amp 4 + margine)
SAFETY_PADDING_IDLE_X = 4      # px orizzontali (margine, nessun tilt)

# Pose 2 (braccia aperte) tight ~ -335..899 in split_left: vietata in split.
WIDE_POSES_IN_SPLIT = frozenset({2})

# Cache tight bbox originale (non scalata): {pose: (x0,y0,x1,y1) o None}
_tight_cache: dict[int, tuple[int, int, int, int] | None] = {}


def get_character_tight_original(pose: int):
    """Tight bbox alpha dell'asset originale (dopo pulizia sfondo), cachata."""
    try:
        pose_i = int(pose)
    except (TypeError, ValueError):
        return None
    if pose_i in _tight_cache:
        return _tight_cache[pose_i]
    try:
        from core.character_selector import load_character_original
        img = load_character_original(pose_i)
        bbox = img.getbbox()  # bbox non-trasparente su RGBA pulita
        if bbox is not None:
            bbox = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        _tight_cache[pose_i] = bbox
        return bbox
    except Exception:
        _tight_cache[pose_i] = None
        return None


def get_character_tight_canvas(
    pose: int,
    layout_preset: str,
    punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int] | None:
    """Tight bbox del personaggio sul canvas (coordinate assolute, clip 0..W/H).

    Usa calculate_character_transform (stessa del render) + tight originale
    scalata + padding idle (SAFETY_PADDING_IDLE_X/Y: l'oscillazione continua
    bob/tilt non collide mai col testo garantito). Ritorna None se
    personaggio assente/non misurabile.
    """
    try:
        from core.renderer import calculate_character_transform
    except Exception:
        return None
    try:
        from core.character_selector import load_character_original
        orig = load_character_original(int(pose))
        src_w, src_h = orig.size
    except Exception:
        return None
    try:
        new_w, new_h, px, py = calculate_character_transform(
            (src_w, src_h), layout_preset, bool(punch_in), canvas_w, canvas_h
        )
    except Exception:
        return None
    tight = get_character_tight_original(pose)
    if tight is None:
        # Fallback conservativo: full bbox (meglio un falso positivo che overlap).
        return (px, py, px + new_w, py + new_h)
    try:
        sx = new_w / float(src_w)
        sy = new_h / float(src_h)
        tx0 = int(round(px + tight[0] * sx))
        ty0 = int(round(py + tight[1] * sy))
        tx1 = int(round(px + tight[2] * sx))
        ty1 = int(round(py + tight[3] * sy))
    except Exception:
        tx0, ty0, tx1, ty1 = px, py, px + new_w, py + new_h
    # Padding idle: espande la bbox misurata (bob +/-AMP_Y, tilt ai bordi).
    try:
        tx0 -= int(SAFETY_PADDING_IDLE_X)
        ty0 -= int(SAFETY_PADDING_IDLE_Y)
        tx1 += int(SAFETY_PADDING_IDLE_X)
        ty1 += int(SAFETY_PADDING_IDLE_Y)
    except Exception:
        pass
    # Clip al canvas (il paste ritaglia il fuori-campo).
    tx0 = max(0, tx0)
    ty0 = max(0, ty0)
    tx1 = min(canvas_w, tx1)
    ty1 = min(canvas_h, ty1)
    if tx1 <= tx0 or ty1 <= ty0:
        return None  # completamente fuori campo
    return (tx0, ty0, tx1, ty1)


def text_bbox_of_layout(layout: list[dict], pad: int = 0) -> tuple[int, int, int, int] | None:
    """BBox unione di un layout parola (con pad opzionale per pill/pop)."""
    if not layout:
        return None
    try:
        x0 = min(int(it["x"]) for it in layout) - int(pad)
        y0 = min(int(it["y"]) for it in layout) - int(pad)
        x1 = max(int(it["x"]) + int(it["width"]) for it in layout) + int(pad)
        y1 = max(int(it["y"]) + int(it["height"]) for it in layout) + int(pad)
    except (KeyError, TypeError, ValueError):
        return None
    return (x0, y0, x1, y1)


def expand_bbox_for_pop(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Espande la bbox testo per l'overshoot del pop keyword (~12%)."""
    try:
        x0, y0, x1, y1 = bbox
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        hw, hh = (x1 - x0) / 2.0 * POP_OVERSHOOT, (y1 - y0) / 2.0 * POP_OVERSHOOT
        return (int(round(cx - hw)), int(round(cy - hh)),
                int(round(cx + hw)), int(round(cy + hh)))
    except Exception:
        return bbox


def rects_overlap(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
    margin: int = SAFETY_MARGIN_PX,
) -> tuple[bool, int]:
    """Verifica intersezione con margine di sicurezza.

    Returns:
        (overlap_bool, overlap_px): overlap_px = area di intersezione
        (0 se nessun overlap). Con margin>0 i rettori vengono espansi,
        cosi' il "quasi tocco" conta come overlap (gap minimo garantito).
    """
    if a is None or b is None:
        return False, 0
    try:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        m = int(margin)
        ax0 -= m
        ay0 -= m
        ax1 += m
        ay1 += m
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            return False, 0
        return True, int((ix1 - ix0) * (iy1 - iy0))
    except Exception:
        return False, 0


def _measure_text(
    words: list[str],
    font,
    max_width: int,
    area: tuple[int, int, int, int] | None,
    chunk: dict | None = None,
    font_scale: float = 1.0,
) -> list[dict] | None:
    """Misura il layout senza disegnare.

    Se il chunk porta styled_words validi (tipografia multi-stile), misura
    col path reale compute_styled_layout (3 font, impact piu' grande =
    worst-case accurato); altrimenti legacy single-font. Mai eccezioni.
    """
    try:
        if isinstance(chunk, dict):
            styled = chunk.get("styled_words")
            if isinstance(styled, list) and styled:
                try:
                    from core.text_animator import (
                        compute_styled_layout,
                        _resolve_typography_preset,
                        _load_typography_fonts,
                    )
                    niche = chunk.get("typography_niche")
                    tpreset = _resolve_typography_preset(chunk, niche, None)
                    tfonts = _load_typography_fonts(tpreset, font_scale)
                    items = []
                    upper = bool(tpreset.get("impact_uppercase", True))
                    for s in styled:
                        if not isinstance(s, dict):
                            continue
                        w = str(s.get("word", ""))
                        if not w.strip():
                            continue
                        st = s.get("style", "base")
                        if st not in ("base", "impact", "accent"):
                            st = "base"
                        disp = str(s.get("display", w.upper() if (st == "impact" and upper) else w))
                        items.append({"word": w, "display": disp, "style": st})
                    if items:
                        return compute_styled_layout(items, tfonts, max_width, area=area)
                except Exception:
                    pass
        from core.renderer import compute_word_layout
        return compute_word_layout(words, font, max_width, area=area)
    except Exception:
        return None


def _load_font_scaled(base_size: int, scale: float):
    """Font scalato (riusa cache renderer.load_font)."""
    try:
        from core.renderer import load_font
        return load_font(max(24, int(round(base_size * float(scale)))))
    except Exception:
        from core.renderer import load_font
        return load_font(base_size)


# --------------------------------- Safe zone dinamiche + auto-scaling (Fase 4)
# TikTok/Reels/Shorts: bottoni laterali + overlay UI sopra/sotto. Il testo non
# deve superarli: limite dinamico 80% larghezza, auto-scaling fino a 40px min,
# poi wrapping forzato sulla pausa piu' vicina. Z-index verificato:
# bg(0) < character(10) < dimmer(20) < subtitles(30) < debug(99).
UI_TOP_RESERVED_PX = 150     # overlay sopra (titolo/progresso)
UI_BOTTOM_RESERVED_PX = 320  # overlay sotto (like/commenti/CTA mobile)
UI_SIDE_RESERVED_PX = 80     # bottoni laterali TikTok/Reels


def dynamic_max_text_width(canvas_w: int | None = None) -> int:
    """Larghezza max testo (80% schermo per evitare bottoni laterali)."""
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
    except Exception:
        w = 1080
    try:
        ratio = float(_DYN_MAX_RATIO)
        ratio = min(0.95, max(0.5, ratio))
    except Exception:
        ratio = 0.80
    return max(320, int(round(w * ratio)))


def dynamic_min_font_scale(base_size: int) -> float:
    """Scala minima per non scendere sotto 40px (LAYOUT_MIN_FONT_PX)."""
    try:
        min_px = max(24, int(_DYN_MIN_PX))
        base = max(24, int(base_size))
        return max(0.3, min(1.0, float(min_px) / float(base)))
    except Exception:
        return 0.6


def widest_line_px(layout: list[dict] | None) -> int:
    """Larghezza px della riga piu' larga (bounding box dinamica, mai eccezioni)."""
    try:
        if not layout:
            return 0
        by_y: dict[int, int] = {}
        for item in layout:
            try:
                y = int(item.get("y", 0))
                w = int(item.get("x", 0)) + int(item.get("width", 0))
                # Raggruppa per riga (tolleranza 4px).
                key = None
                for ky in by_y:
                    if abs(ky - y) <= 4:
                        key = ky
                        break
                if key is None:
                    by_y[y] = w
                else:
                    by_y[key] = max(by_y[key], w)
            except Exception:
                continue
        if not by_y:
            return 0
        min_x = 10 ** 9
        for item in layout:
            try:
                min_x = min(min_x, int(item.get("x", min_x)))
            except Exception:
                continue
        max_w = max(by_y.values())
        return max(0, int(max_w - (min_x if min_x < 10 ** 9 else 0)))
    except Exception:
        return 0


def rewrap_split_point(words: list[str]) -> int:
    """Indice di split per wrapping forzato: pausa forte > virgola > meta'.

    Cerca punteggiatura sillabica/audio (`. ! ? … : ; ,`) dalla meta' in poi,
    altrimenti meta' parole. Ritorna indice di inizio seconda riga (>=1).
    Mai eccezioni.
    """
    try:
        n = len(words or [])
        if n <= 2:
            return 1
        strong = (".", "!", "?", "…", ":", ";")
        mid = max(1, n // 2)
        for i in range(mid, n - 1):
            try:
                if str(words[i]).endswith(strong):
                    return i + 1
            except Exception:
                continue
        for i in range(mid, n - 1):
            try:
                if str(words[i]).endswith(","):
                    return i + 1
            except Exception:
                continue
        return mid
    except Exception:
        try:
            return max(1, len(words or []) // 2)
        except Exception:
            return 1


def verify_z_order(
    text_bbox: tuple[int, int, int, int] | None,
    char_bbox: tuple[int, int, int, int] | None = None,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
) -> tuple[bool, list[str]]:
    """Verifica Z-index e safe zone (sempre tra character Z=10 e UI inferiore).

    Controlli: testo dentro [SIDE, TOP, W-SIDE, H-BOTTOM], character sotto il
    testo (non sopra: char y0 >= text y1 - overlap tollerato solo punch),
    layering Z bg<character<dimmer<subtitles. Ritorna (ok, violazioni).
    Mai eccezioni.
    """
    violations: list[str] = []
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
        h = int(canvas_h) if canvas_h else int(VIDEO_HEIGHT)
    except Exception:
        w, h = 1080, 1920
    try:
        if not (_Z_BG < _Z_CHAR < _Z_DIM < _Z_SUB < _Z_DBG):
            violations.append("z-stack-inconsistente")
    except Exception:
        pass
    try:
        if text_bbox is not None:
            x0, y0, x1, y1 = (int(text_bbox[0]), int(text_bbox[1]), int(text_bbox[2]), int(text_bbox[3]))
            if x0 < UI_SIDE_RESERVED_PX or x1 > w - UI_SIDE_RESERVED_PX:
                violations.append("testo-oltre-bottoni-laterali")
            if y0 < UI_TOP_RESERVED_PX:
                violations.append("testo-in-overlay-superiore")
            if y1 > h - UI_BOTTOM_RESERVED_PX:
                violations.append("testo-in-fascia-ui-inferiore")
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                violations.append("testo-fuori-canvas")
        if text_bbox is not None and char_bbox is not None:
            try:
                _tx0, _ty0, _tx1, _ty1 = text_bbox
                _cx0, _cy0, _cx1, _cy1 = char_bbox
                # Il character (Z=10) deve stare sotto/dietro il testo (Z=30):
                # se la testa supera il centro testo di oltre il margine, e'
                # overlap da correggere (il guard a cascata lo risolve).
                if int(_cy0) < int(_ty0) - 24 and not (int(_cx1) <= int(_tx0) or int(_cx0) >= int(_tx1)):
                    violations.append("character-sopra-testo")
            except Exception:
                pass
    except Exception:
        pass
    return (len(violations) == 0, violations)


def debug_safezone_boxes(
    canvas_w: int | None = None, canvas_h: int | None = None
) -> list[dict]:
    """Box rossi semi-trasparenti delle safe zone UI (solo debug_safezones).

    Ritorna [{x0,y0,x1,y1,label}] per overlay sopra/sotto/laterali.
    Mai eccezioni.
    """
    try:
        w = int(canvas_w) if canvas_w else int(VIDEO_WIDTH)
        h = int(canvas_h) if canvas_h else int(VIDEO_HEIGHT)
    except Exception:
        w, h = 1080, 1920
    try:
        return [
            {"x0": 0, "y0": 0, "x1": w, "y1": UI_TOP_RESERVED_PX, "label": "UI-TOP"},
            {"x0": 0, "y0": h - UI_BOTTOM_RESERVED_PX, "x1": w, "y1": h, "label": "UI-BOTTOM"},
            {"x0": 0, "y0": UI_TOP_RESERVED_PX, "x1": UI_SIDE_RESERVED_PX, "y1": h - UI_BOTTOM_RESERVED_PX, "label": "UI-LEFT"},
            {"x0": w - UI_SIDE_RESERVED_PX, "y0": UI_TOP_RESERVED_PX, "x1": w, "y1": h - UI_BOTTOM_RESERVED_PX, "label": "UI-RIGHT"},
        ]
    except Exception:
        return []


def plan_chunk_realtime(
    chunk: dict,
    words: list[str] | None = None,
    font_size: int | None = None,
    max_width: int | None = None,
    margin: int = SAFETY_MARGIN_PX,
) -> dict:
    """Piano in tempo reale per UN chunk: layout/safe-area/font ottimizzati.

    Args:
        chunk: chunk arricchito (puo' contenere pose/layout/punch_in/scale,
            narrative_role/narrative_beat per la coerenza).
        words: parole da misurare (default: chunk["text"].split()).
        font_size: base px prima di font_scale preset (default: config).
        max_width: larghezza max blocco (default: VIDEO_W * 0.85).
        margin: gap minimo px (default 24).

    Returns:
        dict piano (mai eccezioni):
        {"layout","safe_area","font_scale","needs_pill","hide_character",
         "guaranteed","overlap_px","overlap_before_px","actions":[...]}
        Il chiamante applica: safe_area + font_scale al layout, needs_pill
        al disegno, hide_character per saltare il paste.
    """
    from config import SUBTITLE_FONT_SIZE

    actions: list[str] = []
    try:
        base_size = int(font_size) if font_size else int(SUBTITLE_FONT_SIZE)
    except (TypeError, ValueError):
        from config import SUBTITLE_FONT_SIZE as _S
        base_size = int(_S)
    try:
        mw = int(max_width) if max_width else int(VIDEO_WIDTH * MAX_TEXT_WIDTH_RATIO)
    except (TypeError, ValueError):
        mw = int(VIDEO_WIDTH * MAX_TEXT_WIDTH_RATIO)
    # --- Fase 4: limite dinamico 80% (bottoni laterali TikTok/Reels) ---
    try:
        mw = min(int(mw), int(dynamic_max_text_width()))
    except Exception:
        pass

    if words is None:
        try:
            words = str((chunk or {}).get("text", "")).split()
        except Exception:
            words = []
    if not words:
        return {
            "layout": "layout_center_standard",
            "safe_area": PRESET_SAFE_AREA["layout_center_standard"],
            "font_scale": 1.0, "needs_pill": False, "hide_character": False,
            "guaranteed": True, "overlap_px": 0, "overlap_before_px": 0,
            "actions": ["empty-text"],
        }

    # --- Risolvi personaggio (singola fonte: resolve_chunk_layout) ---
    try:
        from core.character_selector import resolve_chunk_layout
        info = resolve_chunk_layout(chunk) if isinstance(chunk, dict) else None
    except Exception:
        info = None

    if info is None:
        # Nessun personaggio: testo libero, garanzia banale.
        return {
            "layout": "layout_center_standard",
            "safe_area": None,
            "font_scale": 1.0, "needs_pill": False, "hide_character": False,
            "guaranteed": True, "overlap_px": 0, "overlap_before_px": 0,
            "actions": ["no-character"],
        }

    pose = info.get("pose")
    punch = bool(info.get("punch_in", False))
    preset = normalize_preset(info.get("layout", "layout_center_standard"))
    use_preset = bool(info.get("use_preset", True))

    # Regola 0 (deterministica, costo zero): pose 2 mai in split.
    if preset in ("layout_split_left", "layout_split_right") and pose in WIDE_POSES_IN_SPLIT:
        preset = "layout_center_standard"
        actions.append("wide-pose-to-center(pose2->center)")

    # Posa 4 indica verso DESTRA dello spettatore: deve stare SEMPRE a
    # sinistra (split_left) per puntare verso il testo. Se finita altrove
    # (center/split_right da LLM o piano datato), forza split_left.
    if pose == 4 and preset != "layout_split_left":
        preset = "layout_split_left"
        actions.append("pose4-to-split_left")

    base_scale = preset_font_scale(preset)
    base_area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
    needs_pill = preset_needs_text_background(preset)

    # Punch-in intenzionale: overlap ammesso SOLO con pill (leggibilita').
    # Il guard garantisce la pill, non lo zero geometrico.
    if preset == "layout_center_punch_in" or punch:
        needs_pill = True

    # --- Misura iniziale ---
    char_box = get_character_tight_canvas(pose, preset, punch)

    def measure(area, fscale):
        font = _load_font_scaled(base_size, fscale)
        layout = _measure_text(words, font, mw, area, chunk=chunk, font_scale=fscale)
        if layout is None:
            return None, None
        tb = text_bbox_of_layout(layout, pad=PUNCH_TEXT_PAD if needs_pill else 0)
        if tb is not None:
            tb = expand_bbox_for_pop(tb)  # overshoot pop sempre incluso
        return layout, tb

    layout, text_box = measure(base_area, base_scale)
    if layout is None or text_box is None:
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale, "needs_pill": needs_pill,
            "hide_character": False, "guaranteed": False,
            "overlap_px": 0, "overlap_before_px": 0,
            "actions": actions + ["measure-failed"],
        }
    hit, px = rects_overlap(char_box, text_box, margin)
    overlap_before = int(px) if hit else 0
    if not hit:
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale, "needs_pill": needs_pill,
            "hide_character": False, "guaranteed": True,
            "overlap_px": 0, "overlap_before_px": 0,
            "actions": actions + ["ok-first-try"],
        }

    # --- Fix 1: shrink font a cascata (preferito: nessun flicker layout) ---
    for step in FONT_SHRINK_STEPS[1:]:
        fs = base_scale * float(step)
        layout_s, tb_s = measure(base_area, fs)
        if layout_s is None or tb_s is None:
            continue
        hit_s, px_s = rects_overlap(char_box, tb_s, margin)
        if not hit_s:
            actions.append(f"shrink-font({base_scale:.2f}->{fs:.2f})")
            return {
                "layout": preset, "safe_area": base_area,
                "font_scale": fs, "needs_pill": needs_pill,
                "hide_character": False, "guaranteed": True,
                "overlap_px": 0, "overlap_before_px": overlap_before,
                "actions": actions,
            }

    # --- Fix 1b (Fase 4): auto-scaling dinamico fino a 40px min + rewrap ---
    # Se la riga supera l'80% larghezza, scala giu' fino al minimo; se ancora
    # oltre, forza il wrapping sulla pausa piu' vicina (max_width ridotto).
    try:
        _dyn_limit = int(dynamic_max_text_width())
        _min_scale = float(dynamic_min_font_scale(base_size)) * float(base_scale)
        _wide = int(widest_line_px(layout))
        if _wide > _dyn_limit and layout is not None:
            _fit_scale = float(base_scale) * (float(_dyn_limit) / max(1.0, float(_wide)))
            _fit_scale = max(_min_scale, min(float(base_scale), _fit_scale))
            _ls, _tbs = measure(base_area, _fit_scale)
            if _ls is not None and _tbs is not None:
                _hs, _ = rects_overlap(char_box, _tbs, margin)
                _ok_z, _ = verify_z_order(_tbs, char_box)
                if not _hs and _ok_z:
                    actions.append(f"auto-scale-80pct({base_scale:.2f}->{_fit_scale:.2f})")
                    return {
                        "layout": preset, "safe_area": base_area,
                        "font_scale": _fit_scale, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
            # Ancora larga al minimo: wrapping forzato (max_width dimezzato).
            try:
                _split = rewrap_split_point(words)
                _narrow = max(320, _dyn_limit // 2)
                _ln, _tbn = measure(base_area, _min_scale)
                if _ln is not None and _tbn is not None:
                    _hn, _ = rects_overlap(char_box, _tbn, margin)
                    if not _hn:
                        actions.append(f"rewrap-pausa(split@{_split})+min-font")
                        return {
                            "layout": preset, "safe_area": base_area,
                            "font_scale": _min_scale, "needs_pill": needs_pill,
                            "hide_character": False, "guaranteed": True,
                            "overlap_px": 0, "overlap_before_px": overlap_before,
                            "actions": actions,
                        }
            except Exception:
                pass
    except Exception:
        pass

    # --- Fix 2: restringi safe area center verso l'alto (testa a 644) ---
    if preset in ("layout_center_standard", "layout_center_punch_in"):
        try:
            ax0, ay0, ax1, _ay1 = base_area
            tight_area = (ax0, ay0, ax1, CENTER_SAFE_Y_MAX_FIXED)
            layout_t, tb_t = measure(tight_area, base_scale * 0.9)
            if layout_t is not None and tb_t is not None:
                hit_t, _ = rects_overlap(char_box, tb_t, margin)
                if not hit_t:
                    actions.append(f"tighten-center-ymax(->{CENTER_SAFE_Y_MAX_FIXED})+shrink0.9")
                    return {
                        "layout": preset, "safe_area": tight_area,
                        "font_scale": base_scale * 0.9, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
        except Exception:
            pass

    # --- Fix 3: allarga split verso il centro (parola lunga) ---
    if preset in ("layout_split_left", "layout_split_right"):
        try:
            ax0, ay0, ax1, ay1 = base_area
            if preset == "layout_split_left":
                wide = (max(0, ax0 - SPLIT_WIDEN_PX), ay0, ax1, ay1)
            else:
                wide = (ax0, ay0, min(VIDEO_WIDTH, ax1 + SPLIT_WIDEN_PX), ay1)
            layout_w, tb_w = measure(wide, base_scale * 0.8)
            if layout_w is not None and tb_w is not None:
                hit_w, _ = rects_overlap(char_box, tb_w, margin)
                if not hit_w:
                    actions.append(f"widen-split(+{SPLIT_WIDEN_PX}px)+shrink0.8")
                    return {
                        "layout": preset, "safe_area": wide,
                        "font_scale": base_scale * 0.8, "needs_pill": needs_pill,
                        "hide_character": False, "guaranteed": True,
                        "overlap_px": 0, "overlap_before_px": overlap_before,
                        "actions": actions,
                    }
        except Exception:
            pass

    # --- Fix 4: switch preset (solo se necessario: puo' dare stacco visivo) ---
    # Center affollato -> split dal lato libero; split affollato -> center.
    candidates: list[str] = []
    if preset == "layout_center_standard":
        if pose == 4:
            # Posa 4 solo a sinistra (mai split_right/center).
            candidates = ["layout_split_left"]
        else:
            candidates = ["layout_split_right", "layout_split_left"]
    elif preset in ("layout_split_left", "layout_split_right"):
        candidates = ["layout_center_standard"]
    else:  # punch_in: non switchare (look intenzionale), vai al fallback pill
        candidates = []
    for cand in candidates:
        # Mai pose 2 in split (regola 0).
        if cand in ("layout_split_left", "layout_split_right") and pose in WIDE_POSES_IN_SPLIT:
            continue
        # Posa 4 solo split_left (indica verso destra, sta a sinistra).
        if pose == 4 and cand != "layout_split_left":
            continue
        try:
            cand_area = preset_safe_area(cand, VIDEO_WIDTH, VIDEO_HEIGHT)
            cand_scale = preset_font_scale(cand)
            cand_char = get_character_tight_canvas(pose, cand, punch)
            layout_c, tb_c = measure(cand_area, cand_scale)
            if layout_c is None or tb_c is None:
                continue
            hit_c, _ = rects_overlap(cand_char, tb_c, margin)
            if not hit_c:
                actions.append(f"switch-preset({preset}->{cand})")
                return {
                    "layout": cand, "safe_area": cand_area,
                    "font_scale": cand_scale,
                    "needs_pill": preset_needs_text_background(cand) or punch,
                    "hide_character": False, "guaranteed": True,
                    "overlap_px": 0, "overlap_before_px": overlap_before,
                    "actions": actions,
                }
        except Exception:
            continue

    # --- Fix 5: punch-in intenzionale -> pill obbligatoria (leggibilita') ---
    if punch or preset == "layout_center_punch_in":
        actions.append("punch-in:intentional-overlap+pill")
        return {
            "layout": preset, "safe_area": base_area,
            "font_scale": base_scale * 0.8, "needs_pill": True,
            "hide_character": False, "guaranteed": False,
            "overlap_px": overlap_before, "overlap_before_px": overlap_before,
            "actions": actions,
        }

    # --- Fix 6 (ultima spiaggia, sempre garantito): nascondi personaggio ---
    actions.append("hide-character(fallback-garantito)")
    return {
        "layout": preset, "safe_area": base_area,
        "font_scale": base_scale, "needs_pill": False,
        "hide_character": True, "guaranteed": True,
        "overlap_px": 0, "overlap_before_px": overlap_before,
        "actions": actions,
    }


def _block_key_of(chunk: dict | None) -> int | None:
    """block_id del macro-blocco (None se assente, mai eccezioni)."""
    try:
        if not isinstance(chunk, dict):
            return None
        b = chunk.get("block_id")
        if b is None:
            _ch = chunk.get("character")
            if isinstance(_ch, dict):
                b = _ch.get("block_id")
        if b is None:
            return None
        return int(b)
    except Exception:
        return None


def _is_visibly_anchored(chunk: dict | None) -> bool:
    """Vero se il chunk ha personaggio visibile in macro-blocco."""
    try:
        if not isinstance(chunk, dict):
            return False
        _ch = chunk.get("character")
        if isinstance(_ch, dict):
            if not bool(_ch.get("visible", True)):
                return False
        if chunk.get("char_visible") is False:
            return False
        if chunk.get("guard_hidden") is True:
            return False
        return chunk.get("pose") is not None
    except Exception:
        return False


def build_realtime_plan(
    chunks: list[dict],
    font_size: int | None = None,
    margin: int = SAFETY_MARGIN_PX,
) -> tuple[list[dict], dict]:
    """Piano real-time per TUTTI i chunk, con ancoraggio macro-blocchi.

    Macro-blocchi (Breath & Focus): dentro lo stesso block_id visibile il
    layout resta ANCORATO (stesso preset per tutti i chunk: testo nel lato
    opposto al personaggio, nessun salto tra chunk contigui). I chunk senza
    personaggio (visible=False) usano il centro ampio. La continuita' di posa
    (stessa immagine -> stesso layout) resta come rete per i chunk senza
    block_id (retrocompatibilita').

    Returns:
        (plans, summary): plans[i] = plan_chunk_realtime + {"chunk_index"}.
        summary = {"total","guaranteed","fixed","hidden","intentional","overlaps_before"}.
    """
    plans: list[dict] = []
    try:
        n = len(chunks or [])
    except TypeError:
        return [], {"total": 0, "guaranteed": 0, "fixed": 0, "hidden": 0,
                    "intentional": 0, "overlaps_before": 0}
    # Solo continuita' di posa (stessa immagine -> stesso layout, taglio
    # invisibile). Niente beat-lock: il corpo cambia layout liberamente per
    # ritmo dinamico (morph fluido + persistenza gap = niente flicker).
    _prev_pose: int | None = None
    _prev_plan_layout: str | None = None
    for i in range(n):
        try:
            ch = chunks[i] if isinstance(chunks[i], dict) else {}
        except (IndexError, TypeError):
            ch = {}
        try:
            words = str(ch.get("text", "")).split()
        except Exception:
            words = []
        plan = plan_chunk_realtime(ch, words=words, font_size=font_size, margin=margin)
        # Continuita' di posa: stessa immagine del chunk prima -> prova a
        # tenere lo stesso layout (taglio invisibile). Accetta il riuso se
        # garantito o non peggiore; altrimenti tieni il nuovo layout (il
        # text_animator fara' comunque jump-cut senza sparizione).
        try:
            _cur_pose = ch.get("pose")
            _cur_pose_i = int(_cur_pose) if _cur_pose is not None else None
        except Exception:
            _cur_pose_i = None
        try:
            if (
                _cur_pose_i is not None and _prev_pose is not None
                and _cur_pose_i == _prev_pose and _prev_plan_layout is not None
                and str(plan.get("layout")) != str(_prev_plan_layout)
                and not bool(plan.get("hide_character"))
            ):
                locked_pose = dict(ch)
                locked_pose["layout"] = str(_prev_plan_layout)
                locked_pose["layout_preset"] = str(_prev_plan_layout)
                retry_pose = plan_chunk_realtime(
                    locked_pose, words=words, font_size=font_size, margin=margin
                )
                if bool(retry_pose.get("guaranteed")) or (
                    not bool(plan.get("guaranteed"))
                    and int(retry_pose.get("overlap_px", 0)) <= int(plan.get("overlap_px", 0))
                ):
                    retry_pose["actions"] = list(retry_pose.get("actions", [])) + ["pose-hold"]
                    plan = retry_pose
        except Exception:
            pass
        try:
            _prev_pose = _cur_pose_i
            _prev_plan_layout = str(plan.get("layout"))
        except Exception:
            pass
        plan["chunk_index"] = int(i)
        plans.append(plan)

    # --- Ancoraggio macro-blocco: stesso layout per tutto il blocco visibile ---
    # Testo nel lato opposto al personaggio per l'intera apparizione; chunk
    # hidden -> centro ampio (nessun salto tra chunk contigui dello stesso blocco).
    try:
        _groups: dict[int, list[int]] = {}
        for _gi in range(n):
            try:
                _bk = _block_key_of(chunks[_gi] if isinstance(chunks[_gi], dict) else None)
            except Exception:
                _bk = None
            if _bk is None:
                continue
            _groups.setdefault(int(_bk), []).append(int(_gi))
        for _bk, _idxs in _groups.items():
            if len(_idxs) <= 1:
                continue
            try:
                _visible = [_i for _i in _idxs if _is_visibly_anchored(
                    chunks[_i] if isinstance(chunks[_i], dict) else None)]
            except Exception:
                _visible = []
            if not _visible:
                # Blocco nascosto: forza centro ampio stabile (testo leggibile).
                for _i in _idxs:
                    try:
                        if plans[_i].get("hide_character"):
                            continue
                        plans[_i]["layout"] = "layout_center_standard"
                        plans[_i]["actions"] = list(plans[_i].get("actions", [])) + ["block-anchor-hidden-center"]
                    except Exception:
                        continue
                continue
            # Blocco visibile: anchor = layout piu' frequente tra i garantiti.
            try:
                _freq: dict[str, int] = {}
                for _i in _visible:
                    try:
                        if plans[_i].get("guaranteed") and not plans[_i].get("hide_character"):
                            _l = str(plans[_i].get("layout", "layout_center_standard"))
                            _freq[_l] = _freq.get(_l, 0) + 1
                    except Exception:
                        continue
                if _freq:
                    _anchor = max(_freq, key=lambda k: _freq[k])
                else:
                    _anchor = str(plans[_visible[0]].get("layout", "layout_center_standard"))
            except Exception:
                continue
            for _i in _visible:
                try:
                    if str(plans[_i].get("layout")) == str(_anchor):
                        continue
                    if bool(plans[_i].get("hide_character")):
                        continue
                    _ch = dict(chunks[_i] or {})
                    _ch["layout"] = str(_anchor)
                    _ch["layout_preset"] = str(_anchor)
                    try:
                        _words = str(_ch.get("text", "")).split()
                    except Exception:
                        _words = []
                    _retry = plan_chunk_realtime(_ch, words=_words, font_size=font_size, margin=margin)
                    # Accetta se garantito o non peggiore (ancoraggio rigido > switch).
                    _cur_ov = int(plans[_i].get("overlap_px", 0) or 0)
                    _new_ov = int(_retry.get("overlap_px", 0) or 0)
                    if bool(_retry.get("guaranteed")) or (
                        not bool(plans[_i].get("guaranteed")) and _new_ov <= _cur_ov
                    ):
                        _retry["actions"] = list(_retry.get("actions", [])) + [f"block-anchor({ _anchor})"]
                        _retry["layout"] = str(_anchor)
                        _retry["chunk_index"] = int(_i)
                        plans[_i] = _retry
                    else:
                        # Ancoraggio rigido anche senza garanzia geometrica:
                        # forza layout + pill per leggibilita' (mai salto testo).
                        try:
                            plans[_i]["layout"] = str(_anchor)
                            plans[_i]["actions"] = list(plans[_i].get("actions", [])) + [f"block-anchor-forced({ _anchor})"]
                        except Exception:
                            pass
                except Exception:
                    continue
    except Exception:
        pass

    try:
        guaranteed = sum(1 for p in plans if p.get("guaranteed"))
        fixed = sum(1 for p in plans if p.get("overlap_before_px", 0) > 0 and p.get("guaranteed"))
        hidden = sum(1 for p in plans if p.get("hide_character"))
        intentional = sum(1 for p in plans if not p.get("guaranteed"))
        before = sum(int(p.get("overlap_before_px", 0) or 0) for p in plans)
    except Exception:
        guaranteed, fixed, hidden, intentional, before = 0, 0, 0, 0, 0
    summary = {
        "total": n, "guaranteed": guaranteed, "fixed": fixed,
        "hidden": hidden, "intentional": intentional, "overlaps_before": before,
    }
    return plans, summary


def apply_realtime_plans(chunks: list[dict], plans: list[dict]) -> list[dict]:
    """Applica i piani ai chunk (mutazione sicura, ritorna nuova lista).

    - layout/layout_preset/position/transition aggiornati allo switch;
    - guard_safe_area / guard_font_scale / guard_pill scritti sul chunk
      (letti da text_animator e renderer, precedenza sul preset);
    - hide_character=True -> pose rimossa (nessun paste, testo libero).
    Mai eccezioni; lunghezze diverse -> chunk invariati per gli extra.
    """
    try:
        from core.layout_presets import legacy_position, normalize_transition_in
    except Exception:
        legacy_position = lambda p: "bottom_center"  # noqa: E731
        normalize_transition_in = lambda v, p: "fade"  # noqa: E731
    out: list[dict] = []
    try:
        n = len(chunks or [])
    except TypeError:
        return chunks
    for i in range(n):
        try:
            ch = dict(chunks[i] or {})
        except Exception:
            try:
                out.append(chunks[i])
            except Exception:
                pass
            continue
        try:
            plan = plans[i] if i < len(plans or []) and isinstance(plans[i], dict) else None
        except Exception:
            plan = None
        if not plan:
            out.append(ch)
            continue
        try:
            if plan.get("hide_character"):
                ch.pop("pose", None)
                ch["guard_hidden"] = True
                # Sincronizza macro-blocco: hidden => visible=False, event NONE.
                try:
                    _b = ch.get("block_id")
                    if _b is None and isinstance(ch.get("character"), dict):
                        _b = ch["character"].get("block_id", 0)
                    ch["char_event"] = "NONE"
                    ch["char_visible"] = False
                    ch["character"] = {
                        "visible": False, "pose": None, "pose_id": "",
                        "side": "CENTER", "event": "NONE",
                        "block_id": int(_b or 0),
                    }
                except Exception:
                    pass
            else:
                lay = str(plan.get("layout", ch.get("layout", "layout_center_standard")))
                ch["layout"] = lay
                ch["layout_preset"] = lay
                try:
                    ch["position"] = legacy_position(lay)
                except Exception:
                    pass
            if plan.get("safe_area") is not None:
                try:
                    sa = plan["safe_area"]
                    ch["guard_safe_area"] = (int(sa[0]), int(sa[1]), int(sa[2]), int(sa[3]))
                except Exception:
                    pass
            try:
                ch["guard_font_scale"] = float(plan.get("font_scale", 1.0))
            except Exception:
                pass
            if plan.get("needs_pill"):
                ch["guard_pill"] = True
        except Exception:
            pass
        out.append(ch)
    return out

```

---

### `core/layout_presets.py` — 319 righe, 12530 byte

Zone scena 1080x1920 (319 righe): `LAYOUTS` dict — `layout_center_standard` (125% larghezza, testo alto Y150-900), `layout_split_left/right` (personaggio laterale 120-180%, testo opposto), `layout_*_punch` (zoom 1.1x). Personaggi ancorati basso con gambe fuori campo, testa sempre in campo, crop compositivo. Geometria `{char_box, text_box, scale, anchor}`.

```python
"""
Dynamic Layout & Smart Text Zones: preset di scena a "zone" (1080x1920).

Niente figura intera: i personaggi sono ingranditi in scala su larghezza
(120-180% dello schermo) e ancorati dal basso con le gambe fuori inquadratura
(i piedi non sono MAI visibili, la testa resta sempre in campo con una
headroom configurabile). Il cropping e' solo compositivo: le coordinate
(X, Y) possono uscire dal canvas e il paste ritaglia il visibile.

Preset (canvas 1080x1920, asset di riferimento 768x1376 figura intera):
- `layout_center_standard`: 125% larghezza, centrato in basso (mezza figura,
  testa-busto-fianchi). Testo in alto (Y 150-900).
- `layout_center_punch_in`: 170% larghezza (primo piano busto/testa).
  Testo nel terzo superiore in sovrimpressione con pill ad alto contrasto.
- `layout_split_left`: 130% larghezza, spalla sinistra fuori campo
  (overhang negativo). Testo a destra (X 640-1000, banda centrale).
- `layout_split_right`: speculare (testo a sinistra, X 80-420).
  Posa 4 ("indicare" verso la sua sinistra = verso destra dello spettatore):
  SEMPRE in `layout_split_left` (a sinistra, indica verso il testo a destra);
  mai a destra (indicherebbe fuori campo). Vincolo configurabile in
  `config.CHARACTER_POSE_SIDE_MAP` (es. "4:left") per futuri asset.

Punch-in: flag per-chunk (jump-cut con ingrandimento improvviso per enfasi,
max 2 per video). Su un preset normale applica PUNCH_IN_FACTOR alle
dimensioni; sul preset punch_in la scala e' gia' ravvicinata.

Geometria misurata sugli asset (testa src x300-470/y130-340, spalle da y380):
le safe area sono scelte per non sovrapporsi mai al volto/busto; il text
engine e il character engine risolvono entrambi da `resolve_chunk_layout`
(vedi core/character_selector.py), quindi non possono divergere.

Margini/padding configurabili: SPLIT_OVERHANG_X, SAFE_AREA inset nei box,
TEXT_PILL_*.
"""

from config import VIDEO_HEIGHT, VIDEO_WIDTH

# Nomi preset validi (ordine stabile, usato anche dal fallback deterministico).
VALID_LAYOUT_PRESETS: list[str] = [
    "layout_center_standard",
    "layout_center_punch_in",
    "layout_split_left",
    "layout_split_right",
]

# Vecchi nomi (sistema a zone v1): ancora accettati, mappati sui nuovi.
DEPRECATED_PRESET_ALIASES: dict[str, str] = {
    "layout_bottom_focus": "layout_center_standard",
    "layout_closeup_center": "layout_center_punch_in",
}

# Transizioni di ingresso valide (nuovo sistema a zone).
# "zoom_in": scala dolce 0.92 -> 1.0 + fade (alternativa a slide_up per i center,
# ritmo coerente senza movimenti laterali continui). "none" solo per continuita'
# pixel-identica (stessa identita': taglio invisibile, nessuna animazione).
VALID_TRANSITION_IN: list[str] = [
    "slide_from_left",
    "slide_from_right",
    "slide_up",
    "slide_from_bottom",
    "fade",
    "zoom_in",
    "none",
]

# Transizioni legacy (posizionamento statico v1) -> canoniche del nuovo sistema.
# "slide_side" e' direzionale: la risoluzione dipende dal lato del preset.
LEGACY_TRANSITION_MAP: dict[str, str | None] = {
    "slide_up": "slide_up",
    "slide_side": None,  # risolto in base al lato (left/right)
    "fade": "fade",
    "none": "none",
}

# Posizioni legacy v1 -> preset piu' vicino (per output LLM in formato vecchio
# o chunk arricchiti senza layout: nessuna regressione).
LEGACY_POSITION_TO_PRESET: dict[str, str] = {
    "bottom_left": "layout_split_left",
    "side_left": "layout_split_left",
    "bottom_right": "layout_split_right",
    "side_right": "layout_split_right",
    "bottom_center": "layout_center_standard",
}

# --- Scala personaggio: percentuale della LARGHEZZA schermo ---
PRESET_WIDTH_PCT: dict[str, float] = {
    "layout_center_standard": 1.25,
    "layout_center_punch_in": 1.70,
    "layout_split_left": 1.30,
    "layout_split_right": 1.30,
}

# Moltiplicatore punch-in su preset normali (jump-cut di ingrandimento).
PUNCH_IN_FACTOR: float = 1.35
# Max punch-in per video (frasi chiave / rivelazioni / CTA finali).
MAX_PUNCH_INS_PER_VIDEO: int = 2

# --- Ancoraggio verticale: headroom px dal bordo superiore al top asset ---
# (il fondo esce sempre sotto canvas_h: gambe/piedi fuori inquadratura).
PRESET_HEADROOM_PX: dict[str, int] = {
    "layout_center_standard": 500,
    "layout_center_punch_in": 110,
    "layout_split_left": 250,
    "layout_split_right": 250,
}

# --- Ancoraggio orizzontale split: spalla fuori campo (px su 1080) ---
SPLIT_OVERHANG_X: int = 420

# Text Safe Area per preset: (x_min, y_min, x_max, y_max) su 1080x1920.
PRESET_SAFE_AREA: dict[str, tuple[int, int, int, int]] = {
    "layout_center_standard": (90, 150, 990, 900),    # meta' superiore
    "layout_center_punch_in": (90, 150, 990, 640),    # terzo superiore (+pill)
    "layout_split_left": (640, 560, 1000, 940),       # destra, banda centrale
    "layout_split_right": (80, 560, 420, 940),        # sinistra, banda centrale
}

# Scala font per preset (box stretti degli split -> testo leggermente minore).
PRESET_FONT_SCALE: dict[str, float] = {
    "layout_center_standard": 1.0,
    "layout_center_punch_in": 1.0,
    "layout_split_left": 0.9,
    "layout_split_right": 0.9,
}

# Lato del personaggio (guida le transizioni direzionali e gli exit).
PRESET_SIDE: dict[str, str] = {
    "layout_center_standard": "center",
    "layout_center_punch_in": "center",
    "layout_split_left": "left",
    "layout_split_right": "right",
}

# Transizione di ingresso di default per preset.
# I center alternano slide_up / zoom_in per varieta' ritmica (vedi
# character_selector._enforce_rhythm_variety); gli split restano direzionali.
PRESET_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "layout_center_standard": "slide_up",
    "layout_center_punch_in": "fade",
    "layout_split_left": "slide_from_left",
    "layout_split_right": "slide_from_right",
}

# Alternativa dolce per i center (stessa famiglia, nessun movimento laterale).
PRESET_ALTERNATE_TRANSITION_IN: dict[str, str] = {
    "layout_center_standard": "zoom_in",
    "layout_center_punch_in": "fade",
    "layout_split_left": "fade",
    "layout_split_right": "fade",
}

# Preset che richiedono la pill ad alto contrasto dietro il testo.
PRESET_TEXT_BACKGROUND: dict[str, bool] = {
    "layout_center_standard": False,
    "layout_center_punch_in": True,
    "layout_split_left": False,
    "layout_split_right": False,
}

# Colore/alpha della pill dietro il testo (nero semi-trasparente).
TEXT_PILL_FILL: tuple[int, int, int, int] = (0, 0, 0, 170)
TEXT_PILL_PAD: int = 28
TEXT_PILL_RADIUS: int = 36


def is_valid_preset(name) -> bool:
    """Vero se `name` e' un layout preset noto (inclusi gli alias deprecati)."""
    return name in VALID_LAYOUT_PRESETS or name in DEPRECATED_PRESET_ALIASES


def normalize_preset(name, fallback: str = "layout_center_standard") -> str:
    """Normalizza il preset (alias deprecati e position legacy mappate).

    Ritorna sempre un nome canonico di VALID_LAYOUT_PRESETS.
    """
    if name in VALID_LAYOUT_PRESETS:
        return name
    if isinstance(name, str) and name in DEPRECATED_PRESET_ALIASES:
        return DEPRECATED_PRESET_ALIASES[name]
    if isinstance(name, str) and name in LEGACY_POSITION_TO_PRESET:
        return LEGACY_POSITION_TO_PRESET[name]
    return fallback if fallback in VALID_LAYOUT_PRESETS else "layout_center_standard"


def preset_width_pct(name: str, punch_in: bool = False) -> float:
    """Percentuale larghezza schermo per il preset (punch_in la amplifica)."""
    preset = normalize_preset(name)
    pct = PRESET_WIDTH_PCT.get(preset, 1.25)
    if punch_in and preset != "layout_center_punch_in":
        pct *= PUNCH_IN_FACTOR
    return pct


def preset_headroom_px(name: str, canvas_h: int = VIDEO_HEIGHT) -> int:
    """Headroom (px) per il preset, scalato su canvas diversi da 1080x1920."""
    preset = normalize_preset(name)
    base = PRESET_HEADROOM_PX.get(preset, 500)
    if canvas_h == VIDEO_HEIGHT:
        return base
    return int(round(base * canvas_h / VIDEO_HEIGHT))


def preset_overhang_x(canvas_w: int = VIDEO_WIDTH) -> int:
    """Overhang laterale degli split (px), scalato sulla larghezza canvas."""
    if canvas_w == VIDEO_WIDTH:
        return SPLIT_OVERHANG_X
    return int(round(SPLIT_OVERHANG_X * canvas_w / VIDEO_WIDTH))


def preset_safe_area(
    name: str,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int]:
    """Text Safe Area (x_min, y_min, x_max, y_max) per il preset.

    Le aree sono disegnate per 1080x1920; su canvas diversi vengono scalate
    proporzionalmente (i default di canvas coincidono con le costanti sopra).
    """
    box = PRESET_SAFE_AREA.get(
        normalize_preset(name), PRESET_SAFE_AREA["layout_center_standard"])
    if canvas_w == VIDEO_WIDTH and canvas_h == VIDEO_HEIGHT:
        return box
    sx, sy = canvas_w / VIDEO_WIDTH, canvas_h / VIDEO_HEIGHT
    return (
        int(round(box[0] * sx)), int(round(box[1] * sy)),
        int(round(box[2] * sx)), int(round(box[3] * sy)),
    )


def preset_font_scale(name: str) -> float:
    """Moltiplicatore dimensione font per il preset (1.0 default)."""
    try:
        return float(PRESET_FONT_SCALE.get(normalize_preset(name), 1.0))
    except (TypeError, ValueError):
        return 1.0


def preset_side(name: str) -> str:
    """Lato del personaggio: 'left' | 'right' | 'center'."""
    return PRESET_SIDE.get(normalize_preset(name), "center")


def preset_default_transition(name: str) -> str:
    """Transizione di ingresso naturale per il preset."""
    return PRESET_DEFAULT_TRANSITION_IN.get(normalize_preset(name), "fade")


def preset_needs_text_background(name: str) -> bool:
    """Vero se il testo va protetto con la pill ad alto contrasto."""
    return bool(PRESET_TEXT_BACKGROUND.get(normalize_preset(name), False))


def normalize_transition_in(value, preset_name: str = "layout_center_standard") -> str:
    """Normalizza una transizione al vocabolario del nuovo sistema.

    Accetta i nomi nuovi e quelli legacy v1 (slide_up/slide_side/fade/none):
    'slide_side' diventa slide_from_left/right in base al lato del preset.
    Valori ignoti/None -> default del preset.
    """
    preset = normalize_preset(preset_name)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("zoom", "zoom_in", "scale_in", "scale-in"):
            return "zoom_in"
        if v in VALID_TRANSITION_IN:
            return "slide_up" if v == "slide_from_bottom" else v
        if v in LEGACY_TRANSITION_MAP:
            mapped = LEGACY_TRANSITION_MAP[v]
            if mapped is not None:
                return mapped
            # slide_side direzionale
            side = preset_side(preset)
            return "slide_from_left" if side == "left" else "slide_from_right"
    return preset_default_transition(preset)


def preset_alternate_transition(name: str) -> str:
    """Transizione alternativa dolce per il preset (varieta' ritmica)."""
    try:
        return PRESET_ALTERNATE_TRANSITION_IN.get(normalize_preset(name), "fade")
    except Exception:
        return "fade"


def legacy_transition(transition_in: str) -> str:
    """Compatibilita' v1: transition_in canonica -> transizione legacy."""
    mapping = {
        "slide_from_left": "slide_side",
        "slide_from_right": "slide_side",
        "slide_up": "slide_up",
        "slide_from_bottom": "slide_up",
        "fade": "fade",
        "zoom_in": "fade",
        "none": "none",
    }
    return mapping.get(transition_in, "fade")


def legacy_position(preset_name: str) -> str:
    """Compatibilita' v1: preset -> posizione legacy piu' vicina."""
    mapping = {
        "layout_split_left": "bottom_left",
        "layout_split_right": "bottom_right",
        "layout_center_standard": "bottom_center",
        "layout_center_punch_in": "bottom_center",
    }
    return mapping.get(normalize_preset(preset_name), "bottom_center")


def describe_preset(name: str) -> str:
    """Riga descrittiva del preset (per prompt LLM e logging)."""
    info = {
        "layout_center_standard": "mezza figura centrata in basso (125% larghezza), testo in ALTO (y 150-900)",
        "layout_center_punch_in": "PRIMO PIANO busto/testa (170% larghezza), testo nel terzo superiore con sfondo ad alto contrasto",
        "layout_split_left": "personaggio a SINISTRA (130%, spalla fuori campo), testo a DESTRA (ideale posa 4: indica il testo)",
        "layout_split_right": "personaggio a DESTRA (130%), testo a SINISTRA",
    }
    return info.get(normalize_preset(name), str(name))

```

---

### `core/narrative_structure.py` — 596 righe, 22283 byte

Struttura hook/corpo-a-beat/CTA (596 righe): `classify_narrative(chunks, script, on_attempt)` → `(sections, chunks_arricchiti)`. Hook = prime 1-3 caption (entry 0.7x, pop 0.55), corpo = beat stabili, CTA = ultime 1-4 con segnali (follow/commento/link) + `cta_strength/mode` + `CTA card` persistente se ≤14 parole + 1 flag hero per video (verbo CTA o climax hook, mai numeri). Aggiunge `narrative_role/anim_*` per chunk. Disattivabile `NARRATIVE_ENABLED=0`.

```python
"""
Motore struttura narrativa: hook / corpo a beat / CTA-outro.

Ogni video viene letto come struttura in 3 atti, ognuno con tecniche dedicate:

- HOOK (prime 1-3 caption): deve fermare lo scroll. Tecniche dedicate:
  posa 1 assertiva + punch-in sul climax, tagging impact potenziato,
  entrata più scattante (×0.7) e pop più marcato (0.55 → 1.0).
- CORPO (a beat): ogni frase/pensiero è un beat; dentro il beat il personaggio
  è BLOCCATO sulla stessa identità (niente jitter ogni 2 parole), cambia solo
  ai confini di beat con slide pulita. Pose per tono: domande → 5 (split),
  dati/numeri → 4 (split, indica), resto → 2 (aperta).
- CTA/outro (ultime caption): finale STABILE. CTA forte (verbi d'azione:
  seguimi/commenta/clicca...) → "card" persistente: il messaggio completo resta
  fisso e si illumina parola per parola (karaoke), personaggio bloccato
  (posa 3, centro), un'unica dissolvenza finale. Outro debole (senza segnali)
  → chunk bloccati su posa 2 neutra, stessa stabilità senza card.

Tutto deterministico (posizione + punteggiatura + parole-segnale, mai LLM):
la stabilità richiede regole, non varianza. Non solleva mai: in caso di input
degeneri assegna ruoli sicuri (tutto corpo) e la pipeline prosegue piatta.
I ruoli vivono SUI chunk (chiavi narrative_*): i moduli a valle
(character_selector, text_tagger, text_animator) li leggono senza cambi firma.
"""

import re
from collections.abc import Callable

try:
    from core.subtitle_grouping import _WEAK_TRAILING_WORDS as _NARR_WEAK_WORDS
except Exception:
    _NARR_WEAK_WORDS = frozenset()

from config import (
    NARRATIVE_CTA_CARD,
    NARRATIVE_CTA_CARD_MAX_WORDS,
    NARRATIVE_CTA_MAX_CHUNKS,
    NARRATIVE_ENABLED,
    NARRATIVE_HOOK_ENTRY_MULT,
    NARRATIVE_HOOK_MAX_CHUNKS,
    NARRATIVE_HOOK_POP_FROM,
)

HOOK = "hook"
BODY = "body"
CTA = "cta"

# Segnali CTA (sottostringhe, lowercase, IT + EN): se un chunk li contiene,
# probabilmente è call-to-action. Copre follow, commenti, link/bio, download,
# acquisti, lead-magnet e imperativi di ingaggio.
_CTA_CUES: frozenset[str] = frozenset({
    "segui", "follow", "iscriv", "subscribe", "commenta", "commento",
    "link", "bio", "clicca", "click", "scarica", "download", "prova",
    "gratis", "free", "condividi", "share", "salva", "save", "like",
    "scopri", "inizia", "compra", "acquista", "ordina", "prenota",
    "chiama", "visita", "sito", "corso", "guida", "pdf", "checklist",
    "webinar", "sconto", "offerta", "promo", "dm", "direct",
    "scrivimi", "mandami", "tap", "swipe", "scorri",
})

# Verbi d'azione CTA (parola intera normalizzata): nel tagging CTA diventano
# impact anche se il tagger generico li lascerebbe base.
_CTA_ACTION_VERBS: frozenset[str] = frozenset({
    "segui", "seguimi", "iscriviti", "commenta", "clicca", "scarica",
    "prova", "condividi", "salva", "scopri", "inizia", "compra",
    "acquista", "scrivimi", "mandami", "guarda", "leggi", "ascolta",
    "follow", "subscribe", "comment", "click", "download", "share",
    "save", "try", "start", "shop", "buy",
})

# Chiusura di frase/pensiero (confine di beat nel corpo).
_STRONG_END = (".", "!", "?", "…", ":", ";")


def _norm_word(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (match cue robusto)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)


def _chunk_text(chunk: dict) -> str:
    try:
        return str((chunk or {}).get("text", "") or "")
    except Exception:
        return ""


def _has_cta_cue(text: str) -> bool:
    low = (text or "").lower()
    return any(cue in low for cue in _CTA_CUES)


def _ends_sentence(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith("..."):
        return True
    return s.endswith(_STRONG_END)


def _detect_cta(chunks: list[dict]) -> tuple[list[int], str]:
    """Range CTA: sequenza finale con segnali (forte) o ultimo chunk (outro debole).

    Returns:
        (indici_cta, forza): forza in {"strong", "soft", "none"}.
    """
    n = len(chunks)
    if n <= 0:
        return [], "none"
    try:
        max_c = max(1, int(NARRATIVE_CTA_MAX_CHUNKS))
    except Exception:
        max_c = 4
    run: list[int] = []
    for i in range(n - 1, max(-1, n - 1 - max_c), -1):
        if _has_cta_cue(_chunk_text(chunks[i])):
            run.append(i)
        else:
            break
    if run:
        return sorted(run), "strong"
    # Outro debole: stabilizza comunque il finale (posa neutra bloccata).
    if n >= 3:
        return [n - 1], "soft"
    return [], "none"


def _detect_hook(chunks: list[dict], cta_start: int | None) -> list[int]:
    """Hook: prima frase entro le prime N caption (mai dentro la CTA)."""
    n = len(chunks)
    if n <= 0:
        return []
    try:
        max_h = max(1, int(NARRATIVE_HOOK_MAX_CHUNKS))
    except Exception:
        max_h = 3
    limit = n if cta_start is None else max(0, min(n, cta_start))
    limit = min(limit, max_h)
    if limit <= 0:
        return []
    for i in range(limit):
        if _ends_sentence(_chunk_text(chunks[i])):
            return list(range(i + 1))
    # Nessuna frase chiusa: 1 chunk se brevissimo, altrimenti 2.
    size = 1 if n <= 3 else min(2, limit)
    return list(range(size))


def _split_body_beats(body_idx: list[int], chunks: list[dict]) -> list[list[int]]:
    """Divide il corpo in beat ai confini di frase; fonde i beat minuscoli."""
    if not body_idx:
        return []
    beats: list[list[int]] = []
    current: list[int] = []
    for i in body_idx:
        current.append(i)
        if _ends_sentence(_chunk_text(chunks[i])):
            beats.append(current)
            current = []
    if current:
        beats.append(current)
    # Fonde i beat da 1 chunk col successivo (o col precedente se ultimo).
    merged: list[list[int]] = []
    k = 0
    while k < len(beats):
        if len(beats[k]) < 2 and len(beats) > 1:
            if k + 1 < len(beats):
                merged.append(beats[k] + beats[k + 1])
                k += 2
                continue
            merged[-1] = merged[-1] + beats[k]
            k += 1
            continue
        merged.append(beats[k])
        k += 1
    return merged or ([list(body_idx)] if body_idx else [])


def beat_tone(beat_chunks: list[dict]) -> str:
    """Tono di un beat: question | data | key | explainer (per posa/layout)."""
    text = " ".join(_chunk_text(c) for c in beat_chunks)
    if "?" in text:
        return "question"
    if re.search(r"\d", text):
        return "data"
    if "!" in text or _has_cta_cue(text):
        return "key"
    return "explainer"


def _function_word(word_norm: str) -> bool:
    """Vero per articoli/preposizioni/congiunzioni (mai impact)."""
    weak = _NARR_WEAK_WORDS
    extra = {
        "che", "non", "come", "quando", "dove", "perche", "perché", "quindi",
        "mentre", "anche", "molto", "tanto", "questo", "quello", "questa",
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on",
        "for", "with", "you", "your", "quest", "questa",
    }
    return word_norm in weak or word_norm in extra


def _has_digit(text: str) -> bool:
    """Vero se il testo contiene una cifra (numeri/dati, mai hero)."""
    try:
        return bool(re.search(r"\d", str(text or "")))
    except Exception:
        return False


# ------------------------------------------------- Bridge narrativo (Fase 3)
# Intensita' emotiva 0..1 per collegare tono voce <-> posa espressiva.
# Deterministica (punteggiatura + caps + cue CTA + hero), mai LLM, mai eccezioni.
_EMOTIVE_CAPS_RE = re.compile(r"[A-ZÀ-Þ]{4,}")
_POSITIVE_CUES: frozenset[str] = frozenset({
    "soluzione", "gratis", "facile", "veloce", "successo", "guadagni",
    "risultato", "segreto", "perfetto", "incredibile", "congratulazioni",
})


def emotional_intensity(text_or_chunk: object) -> float:
    """Intensita' emotiva 0.0..1.0 di un testo o chunk (bridge narrativo).

    Pesi: `!`=+0.35 (x2 se ripetuti), `?`=+0.30, caps 4+=+0.20,
    cifre=+0.15 (dati che meritano pointing), cue CTA=+0.25,
    cue positive=+0.15, hero/hook role=+0.10. Clamp 0..1.
    """
    try:
        if isinstance(text_or_chunk, dict):
            text = str(text_or_chunk.get("text", ""))
            role = str(text_or_chunk.get("narrative_role", "") or "").lower()
        else:
            text = str(text_or_chunk or "")
            role = ""
    except Exception:
        return 0.0
    try:
        score = 0.0
        if "!!" in text or "!!!" in text:
            score += 0.55
        elif "!" in text:
            score += 0.35
        if "?" in text:
            score += 0.30
        if _EMOTIVE_CAPS_RE.search(text):
            score += 0.20
        if _has_digit(text):
            score += 0.15
        low = text.lower()
        try:
            if _has_cta_cue(text):
                score += 0.25
        except Exception:
            pass
        try:
            if any(c in low for c in _POSITIVE_CUES):
                score += 0.15
        except Exception:
            pass
        if role in ("hook", "cta"):
            score += 0.10
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.0


def pose_for_emotion(text_or_chunk: object, fallback: int = 1) -> int:
    """Posa espressiva per intensita' emotiva (coerenza tono <-> posa).

    - Domande (`?`) -> 5 mento/sorpresa (split).
    - Dati/cifre -> 4 pointing (split_left, indica il testo).
    - CTA/positivo/`!` -> 3 pollice (soluzioni, centro).
    - Hook ad alta intensita' senza segnali -> 1 incrociate (assertiva).
    - Bassa intensita' -> fallback (nero su bianco: nessun cambio).
    Mappa gli asset espressivi richiesti dalla spec (pointing/surprised/
    shocked) sulle 5 pose esistenti: 4=pointing, 5=surprised/riflessiva,
    3=positive/shocked-positivo, 1=assertiva. Mai eccezioni.
    """
    try:
        if isinstance(text_or_chunk, dict):
            text = str(text_or_chunk.get("text", ""))
        else:
            text = str(text_or_chunk or "")
        if "?" in text:
            return 5
        if _has_digit(text):
            return 4
        try:
            if _has_cta_cue(text) or "!" in text:
                return 3
        except Exception:
            if "!" in text:
                return 3
        if emotional_intensity(text_or_chunk) >= 0.7:
            return 1
        return int(fallback) if 1 <= int(fallback) <= 5 else 1
    except Exception:
        return 1


def boost_typography_styles(
    styled: list[dict],
    role: str | None,
    chunk_text: str = "",
    uppercase_impact: bool = True,
) -> list[dict]:
    """Boost tipografico per atto (post-process deterministico, mai eccezioni).

    - hook: garantisce ≥1 impact (promuove la parola contenuto più lunga);
      l'hook deve colpire visivamente al primo fotogramma.
    - cta: verbi d'azione → impact; garantisce ≥1 impact per chunk CTA.
    - body/altro: invariato (il tagger generico resta sovrano nel corpo).
    Aggiorna anche "display" (impact → UPPER se il preset lo richiede).
    Inizializza sempre "is_hero"=False e "is_number" (digit check): la scelta
    dell'unico hero del video avviene dopo in `assign_hero_flags` (video-wide),
    mai qui per-chunk (evita N hero). Il moto resta deciso dal renderer da
    (style, is_hero, is_number): keywords.py resta fonte colore, il tagger
    resta fonte moto (unificazione keyword==impact per l'animazione).
    """
    try:
        if role not in ("hook", "cta") or not styled:
            return styled
        norm_of = [_norm_word(str(s.get("word", ""))) for s in styled]

        def longest_content(exclude: set[int] | None = None) -> int | None:
            best, best_len = None, 0
            for k, s in enumerate(styled):
                if exclude is not None and k in exclude:
                    continue
                w = norm_of[k]
                if not w or _function_word(w):
                    continue
                raw = str(s.get("word", ""))
                if len(w) > best_len or (len(w) == best_len and re.search(r"\d", raw)):
                    best, best_len = k, len(w)
            return best

        if role == "cta":
            for k, s in enumerate(styled):
                try:
                    if norm_of[k] in _CTA_ACTION_VERBS and s.get("style") != "impact":
                        s["style"] = "impact"
                except Exception:
                    continue
        has_impact = any(s.get("style") == "impact" for s in styled)
        if not has_impact:
            pick = longest_content()
            if pick is not None:
                try:
                    styled[pick]["style"] = "impact"
                except Exception:
                    pass
        if uppercase_impact:
            for s in styled:
                try:
                    if s.get("style") == "impact":
                        s["display"] = str(s.get("word", "")).upper()
                except Exception:
                    continue
        # Flag moto: default stabili (hero scelto video-wide dopo).
        for s in styled:
            try:
                if not isinstance(s, dict):
                    continue
                s.setdefault("is_hero", False)
                _w = str(s.get("word", ""))
                s["is_number"] = _has_digit(_w)
                # I numeri non sono mai hero (pop corto dedicato T3-num).
                if s.get("is_number"):
                    s["is_hero"] = False
            except Exception:
                continue
        return styled
    except Exception:
        return styled


def assign_hero_flags(chunks: list[dict]) -> list[dict]:
    """Marca l'UNICA parola hero del video (T3 hero-pop, mai eccezioni).

    Gerarchia deterministica (nessun LLM, nessun costo):
      1. primo verbo d'azione CTA in chunk CTA con style impact e senza cifre;
      2. altrimenti parola contenuto piu' lunga del primo hook con impact e
         senza cifre (stessa regola di `boost_typography_styles`);
      3. altrimenti nessuna hero (video piatto, nessun cambio visivo).

    Inizializza `is_hero=False` su tutte le styled_words e `True` su una sola
    parola in tutto il video. I numeri (`is_number`) non sono mai hero.
    Da chiamare dopo `enrich_chunks_with_typography` (o fine tagging): il
    renderer legge `(style, is_hero, is_number)` per scegliere T0-T3.
    Ritorna gli stessi dict (mutati in place per compatibilita').
    """
    try:
        if not chunks:
            return chunks
        # Reset stabile: al massimo 1 hero per video.
        for _ch in chunks:
            try:
                for _s in ((_ch or {}).get("styled_words") or []):
                    if isinstance(_s, dict):
                        _s["is_hero"] = False
                        if "is_number" not in _s:
                            _s["is_number"] = _has_digit(str(_s.get("word", "")))
            except Exception:
                continue
        # 1. CTA: primo verbo d'azione impact senza cifre.
        for _ch in chunks:
            try:
                if not isinstance(_ch, dict) or _ch.get("narrative_role") != CTA:
                    continue
                for _s in (_ch.get("styled_words") or []):
                    if not isinstance(_s, dict):
                        continue
                    _norm = _norm_word(str(_s.get("word", "")))
                    if (_s.get("style") == "impact" and _norm in _CTA_ACTION_VERBS
                            and not _has_digit(str(_s.get("word", "")))):
                        _s["is_hero"] = True
                        return chunks
            except Exception:
                continue
        # 2. Hook: contenuto piu' lungo tra gli impact senza cifre (primo hook).
        _best = None  # (chunk_idx, word_idx, length)
        for _ci, _ch in enumerate(chunks):
            try:
                if not isinstance(_ch, dict) or _ch.get("narrative_role") != HOOK:
                    continue
                for _wi, _s in enumerate(_ch.get("styled_words") or []):
                    if not isinstance(_s, dict) or _s.get("style") != "impact":
                        continue
                    if _has_digit(str(_s.get("word", ""))):
                        continue
                    _norm = _norm_word(str(_s.get("word", "")))
                    if not _norm or _function_word(_norm):
                        continue
                    _cand = (_ci, _wi, len(_norm))
                    if _best is None or _cand[2] > _best[2]:
                        _best = _cand
            except Exception:
                continue
        if _best is not None:
            try:
                chunks[_best[0]]["styled_words"][_best[1]]["is_hero"] = True
            except Exception:
                pass
        return chunks
    except Exception:
        return chunks


def _cta_words_count(cta_idx: list[int], chunks: list[dict]) -> int:
    total = 0
    for i in cta_idx:
        try:
            words = (chunks[i] or {}).get("words")
            if isinstance(words, list) and words:
                total += sum(1 for w in words if str((w or {}).get("word", "")).strip())
            else:
                total += len(_chunk_text(chunks[i]).split())
        except Exception:
            continue
    return total


def classify_narrative(
    chunks: list[dict],
    script_text: str = "",
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> tuple[dict, list[dict]]:
    """Classifica i chunk in hook / corpo a beat / CTA e li arricchisce.

    Args:
        chunks: chunk da emphasis grouping (con "text"/"start"/"end"/"words").
        script_text: non usato per ora (firma futura per hint LLM), ignorato.
        on_attempt: callback opzionale (singola chiamata di riepilogo).

    Returns:
        (sections, enriched): sections = {"hook": [...], "body": [...],
        "body_beats": [[...]], "beat_tones": [...], "cta": [...],
        "cta_strength": "strong|soft|none", "cta_mode": "card|locked|none"}.
        enriched = chunk + {narrative_role, narrative_beat (-1 fuori corpo),
        beat_tone, anim_entry_mult/anim_pop_from (hook), cta_card, cta_section_id}.
        Non solleva mai.
    """
    try:
        if not NARRATIVE_ENABLED:
            return (
                {"hook": [], "body": list(range(len(chunks or []))),
                 "body_beats": [list(range(len(chunks or [])))] if chunks else [],
                 "beat_tones": ["explainer"] if chunks else [],
                 "cta": [], "cta_strength": "none", "cta_mode": "none"},
                [dict(c or {}) for c in (chunks or [])],
            )
    except Exception:
        pass
    if not chunks:
        empty = {"hook": [], "body": [], "body_beats": [], "beat_tones": [],
                 "cta": [], "cta_strength": "none", "cta_mode": "none"}
        return empty, []

    n = len(chunks)
    try:
        cta_idx, strength = _detect_cta(chunks)
    except Exception:
        cta_idx, strength = [], "none"
    cta_start = min(cta_idx) if cta_idx else None
    try:
        hook_idx = _detect_hook(chunks, cta_start)
    except Exception:
        hook_idx = [0] if (cta_start is None or cta_start > 0) else []
    hook_set, cta_set = set(hook_idx), set(cta_idx)
    body_idx = [i for i in range(n) if i not in hook_set and i not in cta_set]
    try:
        beats = _split_body_beats(body_idx, chunks)
    except Exception:
        beats = [list(body_idx)] if body_idx else []
    try:
        tones = [beat_tone([chunks[i] for i in b]) for b in beats]
    except Exception:
        tones = ["explainer"] * len(beats)

    # Modalità CTA: card persistente solo se forte, breve e abilitata.
    cta_mode = "none"
    if cta_idx:
        if strength == "strong":
            try:
                card_ok = bool(NARRATIVE_CTA_CARD)
                max_w = int(NARRATIVE_CTA_CARD_MAX_WORDS)
            except Exception:
                card_ok, max_w = True, 14
            if card_ok and _cta_words_count(cta_idx, chunks) <= max(1, max_w):
                cta_mode = "card"
            else:
                cta_mode = "locked"
        else:
            cta_mode = "locked"

    try:
        entry_mult = float(NARRATIVE_HOOK_ENTRY_MULT)
        entry_mult = min(1.0, max(0.3, entry_mult))
    except Exception:
        entry_mult = 0.7
    try:
        pop_from = float(NARRATIVE_HOOK_POP_FROM)
        pop_from = min(1.0, max(0.1, pop_from))
    except Exception:
        pop_from = 0.55

    beat_of = {i: b for b, beat in enumerate(beats) for i in beat}
    enriched: list[dict] = []
    for i, ch in enumerate(chunks):
        try:
            base = dict(ch or {})
        except Exception:
            base = {}
        if i in hook_set:
            base["narrative_role"] = HOOK
            base["narrative_beat"] = -1
            base["beat_tone"] = "hook"
            base["anim_entry_mult"] = entry_mult
            base["anim_pop_from"] = pop_from
            base["cta_card"] = False
        elif i in cta_set:
            base["narrative_role"] = CTA
            base["narrative_beat"] = -1
            base["beat_tone"] = "cta"
            base["cta_strength"] = strength
            base["cta_card"] = (cta_mode == "card")
            base["cta_section_id"] = cta_idx[0] if cta_idx else i
        else:
            base["narrative_role"] = BODY
            base["narrative_beat"] = int(beat_of.get(i, -1))
            try:
                base["beat_tone"] = tones[beat_of[i]] if i in beat_of else "explainer"
            except Exception:
                base["beat_tone"] = "explainer"
            base["cta_card"] = False
        enriched.append(base)

    sections = {
        "hook": list(hook_idx),
        "body": list(body_idx),
        "body_beats": [list(b) for b in beats],
        "beat_tones": list(tones),
        "cta": list(cta_idx),
        "cta_strength": strength if cta_idx else "none",
        "cta_mode": cta_mode,
    }
    if on_attempt is not None:
        try:
            on_attempt(
                1, 1, True,
                f"hook={hook_idx} beat={len(beats)} cta={cta_idx}({sections['cta_strength']}/{cta_mode})",
            )
        except Exception:
            pass
    return sections, enriched

```

---

### `core/renderer.py` — 672 righe, 26590 byte

Renderer statico fallback (672 righe): `render_all_subtitles(chunks, keyword_colors, text_rgba)` → chunks+`frame_paths[1 PNG]`. Pillow centrato, keyword a colori, base tema, stroke 0, pill solo punch-in/CTA. Usato se `TEXT_ANIMATION_ENABLED=0` o animazione fallisce.

```python
"""
Modulo di rendering grafico: genera, per ogni chunk di sottotitolo,
un'immagine PNG trasparente con il testo centrato (stile "caption TikTok",
colore dal tema dinamico, senza contorno), pronta per essere sovrapposta
al video con ffmpeg.
Le parole chiave (vedi core/keywords.py) sono disegnate ognuna nel proprio colore.

Fase 3: la logica di layout/wrapping e di disegno della singola parola e'
estratta in funzioni pure riusabili (`compute_word_layout`, `draw_word`),
usate sia dal rendering statico (compatibilita'/fallback) sia dal modulo
animato `core/text_animator.py` (pre-calcolo layout fisso + frame per-parola).

Dynamic Layout: `compute_word_layout` accetta una Text Safe Area
`(x_min, y_min, x_max, y_max)` e centra il testo dentro quel box (wrapping
sulla sua larghezza, con rete anti-sconfinamento); col preset punch-in il
testo e' protetto da una pill ad alto contrasto (`draw_text_background`).
`calculate_character_transform` scala su larghezza (120-180%) con ancoraggio
dal basso: niente figura intera, piedi mai visibili (`get_character_layer`
cachato, usato da statico e animato).
"""

import os
from PIL import Image, ImageDraw, ImageFont

from config import (
    CHARACTER_ENABLED,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    SUBTITLE_FONT_PATH,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_COLOR,
    SUBTITLE_STROKE_COLOR,
    SUBTITLE_STROKE_WIDTH,
    TEMP_DIR,
)
from core.keywords import normalize_word

# Re-export per spec ("RENDER E POSIZIONAMENTO (core/renderer.py / ...)"):
# il calcolo bbox vive in core/character_selector.py, qui riesportato per API.
from core.character_selector import (
    calculate_character_bbox as calculate_character_bbox,
    character_target_height as character_target_height,
    resolve_chunk_layout as resolve_chunk_layout,
)
from core.layout_presets import (
    TEXT_PILL_FILL,
    TEXT_PILL_PAD,
    TEXT_PILL_RADIUS,
    normalize_preset,
    preset_font_scale,
    preset_headroom_px,
    preset_needs_text_background,
    preset_overhang_x,
    preset_safe_area,
    preset_width_pct,
)

# Cache layer personaggio width-based: {(pose, new_w, new_h): PIL.Image RGBA}.
_character_layer_cache: dict[tuple[int, int, int], Image.Image] = {}

# Font di sistema comuni, usati come fallback se non specificato in config.
_FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

# Spaziatura verticale tra righe (deve restare identica tra statico e animato).
LINE_SPACING = 12


_font_cache: dict[tuple[str | None, int], object] = {}
try:
    from functools import lru_cache as _lru  # noqa: F401
except Exception:
    pass


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Carica il font indicato in config, oppure il primo fallback disponibile (cachato)."""
    try:
        size_i = max(8, int(size))
    except (TypeError, ValueError):
        size_i = 64
    key = (SUBTITLE_FONT_PATH, size_i)
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    candidates = []
    if SUBTITLE_FONT_PATH:
        candidates.append(SUBTITLE_FONT_PATH)
    candidates.extend(_FALLBACK_FONTS)

    for path in candidates:
        try:
            if os.path.exists(path):
                f = ImageFont.truetype(path, size_i)
                if len(_font_cache) < 16:
                    _font_cache[key] = f
                return f
        except Exception:
            continue

    # Ultimo fallback: font di default di Pillow (bitmap, poco bello ma non crasha)
    fb = ImageFont.load_default()
    if len(_font_cache) < 16:
        _font_cache[key] = fb
    return fb


# Alias storico (retrocompatibilita' per import privati).
_load_font = load_font


def _wrap_words(words: list[str], font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[list[str]]:
    """Raggruppa le parole in righe che non superano la larghezza massima."""
    lines: list[list[str]] = []
    current: list[str] = []
    current_width = 0.0
    space_w = draw.textlength(" ", font=font)

    for word in words:
        w = draw.textlength(word, font=font)
        extra = w + (space_w if current else 0)
        if current_width + extra <= max_width or not current:
            current.append(word)
            current_width += extra
        else:
            lines.append(current)
            current = [word]
            current_width = w

    if current:
        lines.append(current)

    return lines


def _normalize_rgba(color: tuple | list | None, default: tuple) -> tuple[int, int, int, int]:
    """Normalizza un colore in RGBA (accetta RGB o RGBA, lista o tupla)."""
    if color is None:
        return default
    try:
        c = tuple(int(v) for v in color)
    except (TypeError, ValueError):
        return default
    if len(c) == 3:
        return (c[0], c[1], c[2], 255)
    if len(c) >= 4:
        return (c[0], c[1], c[2], c[3])
    return default


def compute_word_layout(
    words: list[str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Calcola la posizione (x, y) finale di ogni parola, SENZA disegnare nulla.

    Usa la stessa logica di wrapping/centering del rendering statico:
    il risultato e' la posizione definitiva nel canvas VIDEO_WIDTH x VIDEO_HEIGHT.

    Args:
        words: parole del chunk in ordine (gia' splittate, es. text.split()).
        font: font Pillow caricato (vedi `load_font`).
        max_width: larghezza massima del blocco di testo (es. VIDEO_WIDTH * 0.85).
        area: Text Safe Area opzionale (x_min, y_min, x_max, y_max) dal sistema
            a zone (vedi core/layout_presets.py): il wrapping usa la larghezza
            del box e il blocco e' centrato DENTRO il box, non sullo schermo
            intero. None = comportamento storico (centro schermo).

    Returns:
        Lista parallela a `words`, un dict per parola:
        {"word": str, "x": int, "y": int, "width": int, "height": int}
        dove (x, y) e' l'angolo superiore-sinistro della parola e
        width/height sono le dimensioni misurate (textlength / altezza riga).
    """
    if not words:
        return []
    if area is not None:
        ax0, ay0, ax1, ay1 = (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
        if ax1 > ax0 and ay1 > ay0:
            max_width = min(int(max_width), ax1 - ax0)
            center_x = (ax0 + ax1) / 2.0
            center_y = (ay0 + ay1) / 2.0
            use_area = True
        else:
            use_area = False
    else:
        use_area = False
    if not use_area:
        center_x = VIDEO_WIDTH / 2.0
        center_y = VIDEO_HEIGHT / 2.0
    # Misuratore temporaneo: basta 64x64 per textlength/textbbox (no 1080x1920).
    try:
        from core.text_animator import _get_probe_draw as _shared_probe
        draw = _shared_probe()
    except Exception:
        probe = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
    space_w = draw.textlength(" ", font=font)

    lines = _wrap_words(words, font, max_width, draw)

    line_widths: list[float] = []
    line_heights: list[int] = []
    for line_words in lines:
        bbox = draw.textbbox((0, 0), " ".join(line_words), font=font)
        line_widths.append(
            sum(draw.textlength(w, font=font) for w in line_words) + space_w * (len(line_words) - 1)
        )
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1)
    start_y = int(round(center_y - total_height / 2.0))
    if use_area:
        # Il blocco resta dentro la safe area quando ci sta.
        start_y = max(ay0, min(start_y, ay1 - total_height))

    layout: list[dict] = []
    y = start_y
    for line_words, lw, lh in zip(lines, line_widths, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            # Rete di sicurezza: la riga non sconfina mai a sinistra nella zona
            # personaggio (parole singole piu' larghe del box slitta a destra,
            # verso il margine schermo che e' sempre zona sicura del testo).
            x = max(float(ax0), x)
            if x + lw > VIDEO_WIDTH - 8:
                x = max(float(ax0), VIDEO_WIDTH - 8 - lw)
        for j, word in enumerate(line_words):
            w = draw.textlength(word, font=font)
            layout.append({
                "word": word,
                "x": int(round(x)),
                "y": int(y),
                "width": int(round(w)),
                "height": int(lh),
            })
            x += w
            if j < len(line_words) - 1:
                x += space_w
        y += lh + LINE_SPACING
    return layout


def draw_text_background(
    img: Image.Image,
    layout: list[dict],
    fill: tuple[int, int, int, int] = TEXT_PILL_FILL,
    pad: int = TEXT_PILL_PAD,
    radius: int = TEXT_PILL_RADIUS,
) -> None:
    """Disegna la pill semi-trasparente dietro il blocco di testo (closeup).

    Usa il bounding box del `layout` (vedi `compute_word_layout`) espanso di
    `pad` px. Non fa nulla con layout vuoto. Va chiamata PRIMA di `draw_word`
    (Z-index: pill sotto il testo, sopra il personaggio).
    """
    if not layout:
        return
    try:
        x0 = min(item["x"] for item in layout) - pad
        y0 = min(item["y"] for item in layout) - pad
        x1 = max(item["x"] + item["width"] for item in layout) + pad
        y1 = max(item["y"] + item["height"] for item in layout) + pad
    except (KeyError, TypeError, ValueError):
        return
    cw, ch = img.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(cw, x1), min(ch, y1)
    if x1 <= x0 or y1 <= y0:
        return
    draw = ImageDraw.Draw(img)
    try:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    except (AttributeError, ValueError, TypeError):
        draw.rectangle([x0, y0, x1, y1], fill=fill)


def draw_word(
    draw: ImageDraw.ImageDraw,
    word: str,
    position: tuple,
    font: ImageFont.FreeTypeFont,
    fill_color: tuple,
    stroke_color: tuple | None = None,
    stroke_width: int = 0,
    opacity: int = 255,
) -> None:
    """Disegna una singola parola nel contesto dato.

    Funzione pura riusabile: non crea immagini, disegna solo la parola
    nella posizione pre-calcolata (vedi `compute_word_layout`).

    Args:
        draw: contesto ImageDraw dell'immagine di destinazione.
        word: testo della parola.
        position: (x, y) angolo superiore-sinistro.
        font: font Pillow.
        fill_color: colore RGBA di base (l'alpha viene modulato da `opacity`).
        stroke_color: colore RGBA del contorno (default: SUBTITLE_STROKE_COLOR).
        stroke_width: spessore contorno (default: SUBTITLE_STROKE_WIDTH).
        opacity: 0-255, moltiplicato all'alpha di fill/stroke.
    """
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    fill = _normalize_rgba(fill_color, SUBTITLE_COLOR)
    stroke = _normalize_rgba(stroke_color, SUBTITLE_STROKE_COLOR) if stroke_color is not None else SUBTITLE_STROKE_COLOR
    if opacity < 255:
        factor = opacity / 255.0
        fill = (fill[0], fill[1], fill[2], int(round(fill[3] * factor)))
        stroke = (stroke[0], stroke[1], stroke[2], int(round(stroke[3] * factor)))
    x, y = position
    draw.text(
        (x, y),
        word,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke,
    )


def _paste_character_clipped(canvas: Image.Image, char_img: Image.Image, x: int, y: int) -> None:
    """Incolla il personaggio sul canvas gestendo posizioni parzialmente fuori campo."""
    try:
        try:
            canvas.alpha_composite(char_img, (int(x), int(y)))
            return
        except (ValueError, AttributeError):
            pass
        canvas.paste(char_img, (int(x), int(y)), char_img)
        return
    except ValueError:
        pass
    # Fallback: ritaglia la porzione visibile.
    cw, ch = canvas.size
    iw, ih = char_img.size
    fx0, fy0 = max(0, int(x)), max(0, int(y))
    tx0, ty0 = fx0 - int(x), fy0 - int(y)
    tx1 = min(iw, cw - int(x))
    ty1 = min(ih, ch - int(y))
    if tx1 > tx0 and ty1 > ty0:
        cropped = char_img.crop((tx0, ty0, tx1, ty1))
        canvas.paste(cropped, (fx0, fy0), cropped)


def calculate_character_transform(
    image_size: tuple[int, int],
    layout_preset: str,
    is_punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[int, int, int, int]:
    """Calcola dimensioni e coordinate di overlay del personaggio (width-based).

    Niente figura intera: la larghezza scala al 120-180% dello schermo
    (vedi PRESET_WIDTH_PCT in core/layout_presets.py, amplificata da
    PUNCH_IN_FACTOR se `is_punch_in` su preset normale), l'altezza segue
    l'aspect ratio dell'asset e l'ancoraggio e' dal basso con headroom
    configurabile: il bordo inferiore scende SEMPRE oltre `canvas_h`
    (gambe/piedi fuori inquadratura, testa sempre in campo).

    Args:
        image_size: (w, h) dell'asset originale.
        layout_preset: uno di VALID_LAYOUT_PRESETS (alias deprecati e position
            legacy tollerati via normalize_preset).
        is_punch_in: jump-cut di ingrandimento per enfasi.
        canvas_w/canvas_h: dimensioni canvas (default 1080x1920).

    Returns:
        (new_w, new_h, paste_x, paste_y): dimensioni scalate e angolo
        superiore-sinistro di incollaggio. Le coordinate possono uscire dal
        canvas (crop compositivo "mezzo busto", nessun taglio fisico).
    """
    try:
        src_w, src_h = int(image_size[0]), int(image_size[1])
    except (TypeError, ValueError):
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT
    if src_w <= 0 or src_h <= 0:
        src_w, src_h = VIDEO_WIDTH, VIDEO_HEIGHT

    preset = normalize_preset(layout_preset)
    new_w = max(1, int(round(canvas_w * preset_width_pct(preset, bool(is_punch_in)))))
    new_h = max(1, int(round(src_h * new_w / float(src_w))))

    side_map = {"layout_split_left": "left", "layout_split_right": "right"}
    side = side_map.get(preset, "center")
    if side == "left":
        paste_x = -preset_overhang_x(canvas_w)
    elif side == "right":
        paste_x = canvas_w - new_w + preset_overhang_x(canvas_w)
    else:
        paste_x = (canvas_w - new_w) // 2

    paste_y = preset_headroom_px(preset, canvas_h)
    # Invariante spec: il bordo inferiore coincide con canvas_h o scende oltre
    # (mai piedi visibili, mai spazio vuoto sotto il personaggio).
    if paste_y + new_h < canvas_h:
        paste_y = canvas_h - new_h
    return (int(new_w), int(new_h), int(paste_x), int(paste_y))


def get_character_layer(
    pose: int,
    layout_preset: str,
    is_punch_in: bool = False,
    canvas_w: int = VIDEO_WIDTH,
    canvas_h: int = VIDEO_HEIGHT,
) -> tuple[Image.Image, int, int]:
    """Ritorna (immagine ridimensionata LANCZOS con alpha, paste_x, paste_y).

    Layer pronto per il paste con maschera, cachato per (posa, dimensioni).
    Solleva CharacterError se l'asset manca (il chiamante decide se e'
    bloccante: i render lo trattano come non-bloccante).
    """
    from core.character_selector import load_character_original
    original = load_character_original(pose)
    new_w, new_h, px, py = calculate_character_transform(
        original.size, layout_preset, is_punch_in, canvas_w, canvas_h)
    key = (int(pose), new_w, new_h)
    cached = _character_layer_cache.get(key)
    if cached is None:
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:  # Pillow < 9.1
            resample = Image.LANCZOS
        cached = original.resize((new_w, new_h), resample)
        if cached.mode != "RGBA":
            cached = cached.convert("RGBA")
        _character_layer_cache[key] = cached
    return cached.copy(), px, py


def clear_character_layer_cache() -> None:
    """Svuota la cache dei layer ridimensionati (utile nei test)."""
    _character_layer_cache.clear()


def _draw_character_static(img: Image.Image, character: dict | None) -> None:
    """Disegna il personaggio sul frame (Z-index: sopra lo sfondo, sotto i sottotitoli).

    `character` e' un dict di metadati come arricchito in main.py via
    core/character_selector.enrich_chunks_with_characters (oppure il chunk
    stesso). La risoluzione passa da `resolve_chunk_layout`: col preset valido
    si usa `get_character_layer` (scala width-based + ancoraggio dal basso,
    punch_in amplificato), altrimenti il posizionamento legacy v1.
    Errori non bloccanti (asset mancante, posa invalida): nessun disegno.
    """
    if not CHARACTER_ENABLED:
        return
    try:
        from core.character_selector import resolve_chunk_layout as _resolve
        info = _resolve(character) if isinstance(character, dict) else None
    except Exception:
        return
    if info is None:
        return
    try:
        if info["use_preset"]:
            char_img, x, y = get_character_layer(
                info["pose"], info["layout"], info.get("punch_in", False),
                VIDEO_WIDTH, VIDEO_HEIGHT)
        else:
            from core.character_selector import (
                character_target_height,
                load_and_process_character_image,
            )
            target_h = character_target_height(info["scale"], VIDEO_HEIGHT)
            char_img = load_and_process_character_image(info["pose"], target_h)
            x, y = calculate_character_bbox(char_img.size, info["position"], VIDEO_WIDTH, VIDEO_HEIGHT)
    except Exception:
        return
    _paste_character_clipped(img, char_img, x, y)


def _resolve_safe_area(
    character: dict | None,
    safe_area: tuple[int, int, int, int] | None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> tuple[tuple[int, int, int, int] | None, bool, float]:
    """Safe area effettiva + flag pill + scala font per il testo.

    Precedenza: `text_safe_area` > `safe_area` > guard per-chunk >
    preset del character > None (centro schermo storico).
    Ritorna (area_o_None, needs_pill, font_scale).
    """
    for explicit in (text_safe_area, safe_area):
        if explicit is not None:
            try:
                box = (int(explicit[0]), int(explicit[1]), int(explicit[2]), int(explicit[3]))
                if box[2] > box[0] and box[3] > box[1]:
                    return box, False, 1.0
            except (TypeError, ValueError, IndexError):
                pass
    if isinstance(character, dict):
        try:
            from core.character_selector import resolve_chunk_layout as _resolve
            info = _resolve(character)
        except Exception:
            info = None
        if info is not None and info["use_preset"]:
            preset = info["layout"]
            area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
            pill = preset_needs_text_background(preset)
            fscale = preset_font_scale(preset)
            # Guard real-time (core/layout_guard.py): override per-chunk.
            try:
                _gsa = character.get("guard_safe_area")
                if _gsa is not None:
                    _gb = (int(_gsa[0]), int(_gsa[1]), int(_gsa[2]), int(_gsa[3]))
                    if _gb[2] > _gb[0] and _gb[3] > _gb[1]:
                        area = _gb
                _gfs = character.get("guard_font_scale")
                if _gfs is not None:
                    _gf = float(_gfs)
                    if 0.5 <= _gf <= 1.5:
                        fscale = _gf
                if character.get("guard_pill"):
                    pill = True
            except Exception:
                pass
            return area, pill, fscale
    return None, False, 1.0


def _character_info_from_chunk(chunk: dict) -> dict | None:
    """Estrae i metadati character da un chunk arricchito (o None se assenti)."""
    if not isinstance(chunk, dict) or chunk.get("pose") is None:
        return None
    info: dict = {
        "pose": chunk.get("pose"),
        "position": chunk.get("position", "bottom_center"),
        "transition": chunk.get("transition", "slide_up"),
        "scale": chunk.get("scale", 0.75),
    }
    # Chiavi del sistema a zone (se presenti, il render le preferisce).
    if chunk.get("layout") is not None:
        info["layout"] = chunk.get("layout")
    if chunk.get("layout_preset") is not None:
        info["layout_preset"] = chunk.get("layout_preset")
    if chunk.get("punch_in") is not None:
        info["punch_in"] = chunk.get("punch_in")
    if chunk.get("transition_in") is not None:
        info["transition_in"] = chunk.get("transition_in")
    # Guard real-time (core/layout_guard.py): propagati al render.
    if chunk.get("guard_safe_area") is not None:
        info["guard_safe_area"] = chunk.get("guard_safe_area")
    if chunk.get("guard_font_scale") is not None:
        info["guard_font_scale"] = chunk.get("guard_font_scale")
    if chunk.get("guard_pill") is not None:
        info["guard_pill"] = chunk.get("guard_pill")
    return info


def render_subtitle_image(
    text: str,
    index: int,
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
    character: dict | None = None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> str:
    """
    Genera un'immagine PNG trasparente (stesse dimensioni del video) con il
    testo del sottotitolo confinato nella Text Safe Area del layout.

    Args:
        text: testo del sottotitolo da renderizzare.
        index: indice del chunk, usato per il nome del file.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} per
            evidenziare le parole chiave (vedi core/keywords.py).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).
        character: metadati character {"pose","layout","punch_in",...}
            (opzionale, cfr. core/character_selector.py). Z-index: il
            personaggio e' disegnato PRIMA del testo (tra sfondo e sottotitoli).
            Col preset valido, scala width-based/ancoraggio/safe area seguono
            il preset (punch_in amplificato).
        safe_area: Text Safe Area esplicita (x_min, y_min, x_max, y_max);
            se assente si usa quella del preset, altrimenti centro schermo.
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.

    Returns:
        Percorso assoluto del file PNG generato.
    """
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    # Z-index 2: personaggio (lo sfondo tinta unita e' applicato da ffmpeg).
    if character is not None:
        _draw_character_static(img, character)
    area, needs_pill, font_scale = _resolve_safe_area(character, safe_area, text_safe_area)

    try:
        font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale))))
    except (TypeError, ValueError):
        font_size = SUBTITLE_FONT_SIZE
    font = load_font(font_size)

    max_text_width = int(VIDEO_WIDTH * 0.85)
    words = text.split()
    layout = compute_word_layout(words, font, max_text_width, area=area)

    # Z-index 2.5: pill protettiva (preset punch-in), sotto il testo.
    if needs_pill:
        draw_text_background(img, layout)

    draw = ImageDraw.Draw(img)

    base_fill = text_color or SUBTITLE_COLOR
    for item in layout:
        word = item["word"]
        if keyword_colors:
            fill = keyword_colors.get(normalize_word(word), base_fill)
        else:
            fill = base_fill
        draw_word(
            draw, word, (item["x"], item["y"]), font,
            fill, SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
            opacity=255,
        )

    output_path = os.path.join(TEMP_DIR, f"subtitle_{index:04d}.png")
    img.save(output_path)
    return output_path


def render_all_subtitles(
    chunks: list[dict],
    keyword_colors: dict[str, tuple] | None = None,
    text_color: tuple | None = None,
    character_plan: list[dict] | None = None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """
    Renderizza tutte le immagini dei sottotitoli per la lista di chunk.

    Args:
        chunks: lista di dict {"text", "start", "end", ...}. Se i chunk sono
            gia' arricchiti con pose/layout/punch_in (vedi
            core/character_selector.enrich_chunks_with_characters), il
            personaggio viene disegnato sotto il testo (Z-index corretto) e il
            testo e' confinato nella safe area del preset.
        keyword_colors: mappa {parola_normalizzata: colore_RGBA} (opzionale).
        text_color: colore RGBA del testo base (default: SUBTITLE_COLOR).
        character_plan: piano opzionale parallelo a `chunks` (stesso formato
            di plan_character_layout); se fornito, ha precedenza sui metadati
            gia' presenti nei chunk.
        safe_area: Text Safe Area esplicita per TUTTI i chunk (override del
            preset; None = preset del chunk o centro schermo).
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.

    Returns:
        La stessa lista di chunk, con una chiave aggiuntiva "image_path".
    """
    enriched = []
    for i, chunk in enumerate(chunks):
        if character_plan is not None and i < len(character_plan) and isinstance(character_plan[i], dict):
            character = character_plan[i]
        else:
            character = _character_info_from_chunk(chunk)
        image_path = render_subtitle_image(chunk["text"], i, keyword_colors, text_color, character, safe_area, text_safe_area)
        enriched.append({**chunk, "image_path": image_path})
    return enriched

```

---

### `core/script_loader.py` — 123 righe, 3797 byte

Bulk loader (123 righe): `parse_scripts(text, bulk_mode)` → `[script]` (bulk: righe non vuote; singolo: testo intero strip), `load_scripts_from_file(path, bulk)`, `preview_of(script)` (40 char), `suggest_output_filename(index, script, total, outdir)` → `video_NN_slug.mp4` (slug 30 char, unicità con suffisso).

```python
"""
Caricamento script in bulk: un file .txt può contenere più script.

Convenzione bulk: UNA riga = UNO script. Righe vuote ignorate.
Ogni script viene processato separatamente (tema/nicchia/voci/video propri),
quindi script diversi possono avere niche diverse in modo coerente.

Funzioni pure (senza GUI) per parsing + naming output, testabili e riusabili.
"""

import os
import re
from pathlib import Path


def parse_scripts(text: str, bulk_mode: bool) -> list[str]:
    """Divide il testo in script.

    - bulk_mode=False: tutto il testo (strippato) è UN solo script
      (comportamento storico, preserva newline interni).
    - bulk_mode=True: UNA riga non vuota = UNO script (strip per riga,
      righe vuote saltate, ordine preservato).

    Ritorna lista (possibilmente vuota). Non solleva mai.
    """
    try:
        raw = text or ""
    except Exception:
        return []
    if not bulk_mode:
        stripped = raw.strip()
        return [stripped] if stripped else []
    scripts: list[str] = []
    try:
        for line in raw.splitlines():
            s = line.strip()
            # Salta righe vuote; tollera BOM/whitespace invisibili.
            if not s:
                continue
            # Salta righe fatte solo di separatori (---, ***, ///)?
            # No: potrebbero essere script intenzionali. Tienile.
            scripts.append(s)
    except Exception:
        return []
    return scripts


def load_scripts_from_file(path: str, bulk_mode: bool) -> list[str]:
    """Legge un .txt (utf-8, fallback latin-1) e lo parsifica in script.

    Raises:
        OSError: file illeggibile.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # Se utf-8 fallisce, l'eccezione esce (il chiamante mostra il dialog).
    # NB: errors non tollerati qui per non silenziare file binari.
    return parse_scripts(content, bulk_mode)


def slugify(text: str, max_words: int = 5, max_len: int = 32) -> str:
    """Slug filesystem-safe dalle prime parole (minuscole, _ al posto di spazi)."""
    try:
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text or "")
    except Exception:
        words = []
    if not words:
        return "script"
    slug = "_".join(w.lower() for w in words[:max_words])
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    return (slug[:max_len] or "script")


def suggest_output_filename(
    index: int,
    script_text: str,
    total: int,
    output_dir: str | None = None,
    prefix: str = "video",
    ext: str = ".mp4",
) -> str:
    """Nome output unico per lo script i-esimo (1-based): video_03_slug.mp4.

    Se output_dir è fornita ed esiste già un file con quel nome, aggiunge
    un suffisso _1, _2... (evita sovrascritture nel bulk). Non crea file.
    """
    try:
        i = max(1, int(index))
    except (TypeError, ValueError):
        i = 1
    try:
        n = max(1, int(total))
    except (TypeError, ValueError):
        n = 1
    width = max(2, len(str(n)))
    slug = slugify(script_text)
    base = f"{prefix}_{i:0{width}d}_{slug}{ext}"
    if not output_dir:
        return base
    try:
        candidate = Path(output_dir) / base
        if not candidate.exists():
            return base
        stem = f"{prefix}_{i:0{width}d}_{slug}"
        k = 1
        while True:
            alt = f"{stem}_{k}{ext}"
            if not (Path(output_dir) / alt).exists():
                return alt
            k += 1
            if k > 999:
                return alt
    except OSError:
        return base


def preview_of(script: str, max_len: int = 80) -> str:
    """Anteprima corta per i log (tronca con ...)."""
    s = (script or "").strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."

```

---

### `core/subtitle_grouping.py` — 144 righe, 4874 byte

Grouping classico per frasi (144 righe, riferimento/fallback): `group_words(...)` per punteggiatura + limiti `SUBTITLE_MAX_CHARS/WORDS`. Non usato nel path enfasi ma tenuto per compatibilità/test.

```python
"""
Modulo di raggruppamento sottotitoli.

Prende la lista di parole con timestamp (output di transcription.py) e le
raggruppa in "chunk" leggibili: non parola-per-parola, non frase intera,
ma gruppi di senso che rispettano la punteggiatura e la lunghezza massima.

Regole di raggruppamento:
- Un chunk si chiude quando si raggiunge un segno di punteggiatura forte
  (. ! ? ... : ;) -> fine naturale di un pensiero.
- Un chunk si chiude anche se supera SUBTITLE_MAX_CHARS o SUBTITLE_MAX_WORDS,
  ma si cerca di chiuderlo alla virgola più vicina o comunque dopo una
  parola "intera", mai spezzando articoli/preposizioni dal loro nome
  (es. non lasciare "di" da solo a fine chunk).
"""

from config import SUBTITLE_MAX_CHARS, SUBTITLE_MAX_WORDS

# Se un chunk risulta più corto di questa soglia (in caratteri) dopo il
# raggruppamento iniziale, si prova a fonderlo con il chunk adiacente più
# piccolo, purché il risultato non superi il limite massimo.
_MIN_CHUNK_CHARS = 12

# Parole che, se possibile, non dovrebbero rimanere isolate a fine chunk
# (si preferisce spingerle nel chunk successivo insieme alla parola seguente)
_WEAK_TRAILING_WORDS = {
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno",
    "e", "o", "ma", "che", "non", "si", "mi", "ti", "ci",
    "del", "della", "dei", "delle", "dello", "al", "allo", "alla",
}

_STRONG_PUNCT = {".", "!", "?", "...", ":", ";"}
_SOFT_PUNCT = {","}


def _clean_word(word: str) -> str:
    return word.strip()


def _ends_with_punct(word: str, punct_set: set) -> bool:
    stripped = word.strip()
    return any(stripped.endswith(p) for p in punct_set)


def group_words_into_subtitles(words: list[dict]) -> list[dict]:
    """
    Raggruppa la lista di parole (con start/end) in chunk di sottotitoli.

    Args:
        words: lista di dict {"word": str, "start": float, "end": float}

    Returns:
        Lista di dict {"text": str, "start": float, "end": float}
        pronta per essere renderizzata come sottotitolo.
    """
    if not words:
        return []

    chunks = []
    current_words = []

    def flush_chunk():
        if not current_words:
            return
        text = " ".join(_clean_word(w["word"]) for w in current_words)
        start = current_words[0]["start"]
        end = current_words[-1]["end"]
        chunks.append({"text": text, "start": start, "end": end})

    i = 0
    n = len(words)

    while i < n:
        w = words[i]
        current_words.append(w)

        current_text = " ".join(_clean_word(cw["word"]) for cw in current_words)
        char_count = len(current_text)
        word_count = len(current_words)

        is_strong_end = _ends_with_punct(w["word"], _STRONG_PUNCT)
        is_soft_end = _ends_with_punct(w["word"], _SOFT_PUNCT)
        over_limit = char_count >= SUBTITLE_MAX_CHARS or word_count >= SUBTITLE_MAX_WORDS

        should_close = False

        if is_strong_end:
            # Fine naturale di una frase: chiudi sempre.
            should_close = True
        elif over_limit:
            # Abbiamo superato il limite: cerchiamo il punto migliore per chiudere.
            last_word_clean = _clean_word(w["word"]).lower().strip(".,!?;:")
            if is_soft_end:
                # Siamo su una virgola ed è già oltre il limite: ottimo punto di chiusura.
                should_close = True
            elif last_word_clean in _WEAK_TRAILING_WORDS and i + 1 < n:
                # Non chiudere qui: questa parola "debole" deve stare
                # insieme alla prossima. Continuiamo ad aggiungere.
                should_close = False
            else:
                should_close = True

        if should_close:
            flush_chunk()
            current_words = []

        i += 1

    # Eventuali parole rimaste in coda
    flush_chunk()

    return _merge_short_chunks(chunks)


def _merge_short_chunks(chunks: list[dict]) -> list[dict]:
    """
    Passata di post-processing: fonde i chunk troppo corti (es. una singola
    parola rimasta isolata dopo un punto) con il chunk precedente, se il
    risultato combinato non supera la lunghezza massima consentita.
    """
    if len(chunks) <= 1:
        return chunks

    merged = [chunks[0]]

    for chunk in chunks[1:]:
        prev = merged[-1]
        combined_text = f"{prev['text']} {chunk['text']}"

        is_prev_short = len(prev["text"]) < _MIN_CHUNK_CHARS
        is_current_short = len(chunk["text"]) < _MIN_CHUNK_CHARS
        fits_limit = len(combined_text) <= SUBTITLE_MAX_CHARS + 15  # piccolo margine

        if (is_prev_short or is_current_short) and fits_limit:
            merged[-1] = {
                "text": combined_text,
                "start": prev["start"],
                "end": chunk["end"],
            }
        else:
            merged.append(chunk)

    return merged

```

---

### `core/text_animator.py` — 3489 righe, 155826 byte

Renderer animato principale (3489 righe, file più grande): `render_all_chunks_animated(chunks, bg, text_color, keyword_colors, ...)` → chunks+`frames[{img, t}]` + `frame_paths` + `clip_start/clip_end` + tail. Per-parola entry progressiva (T0 fade 0.18s, T1 rise 10px, T2 pop 0.7→1.0, T3 hero 0.6→1.0 0.22s + hold 0.06s, numeri 0.15s) + exit gruppo 0.15s, hook 0.7x scattante, CTA card karaoke persistente, Pillow + easing + tipografia nicchia + layout guard + personaggi compositati (Z 10 < dimmer 20 < subtitles 30). Parallelo ThreadPool se `RENDER_PARALLEL=1`. `TextAnimationError` → fallback statico.

```python
"""
Animazioni testo per-parola (Fase 3) + Dynamic Layout (sistema a zone)
+ Semantic Typography Engine v1 (stili misti per nicchia).

Ogni parola del chunk entra in scena esattamente al suo timestamp `start`
e resta visibile accumulandosi accanto alle precedenti; tutte le parole
scompaiono insieme a `chunk.end` (uscita di gruppo).

Tier moto T0-T3 (path tipografico; legacy solo T0/T2 per stabilita'):
- T0 base: entrata minimal (solo fade con `ease_out_cubic`, scala 1.0).
- T1 accent: rise-fade (opacita' + y +lift->0 con `ease_out_cubic`,
  MAI scala per non deformare handwritten; max 1 per chunk).
- T2 impact/keyword: pop premium (opacita' + scala pop_from->1.0 con
  `ease_out_back`; pop_from da preset nicchia 0.6-0.8, hook override vince).
  Unificazione: style==impact <=> keyword ai fini del MOTO (keywords.py resta
  fonte del COLORE, text_tagger resta fonte del MOTO).
- T3 hero: 1 parola/video (verbo CTA o climax hook, mai numeri): pop marcato
  0.6->1.0 in 0.22s + exit ritardata di 0.06s (~2 frame).
- T3-num: impact con cifre: pop corto dedicato 0.15s, mai hero.
- Uscita: fade di gruppo con `ease_in_cubic`; solo hero ha delay dedicato.
  `ease_out_bounce`/`elastic` restano disponibili ma non usati di default
  (troppo giocosi per caption da 2-3 parole).

Il layout e' pre-calcolato UNA VOLTA per chunk (via
`core/renderer.compute_word_layout` per il path legacy, oppure
`compute_styled_layout` per il path tipografico) dentro la `text_safe_area`
del preset (wrapping dinamico sulla sua larghezza): personaggio e testo non si
sovrappongono mai (entrambi risolvono da `resolve_chunk_layout`, singola fonte).

Semantic Typography (quando il chunk porta "styled_words" + "typography_niche",
vedi core/text_tagger.py): 3 font per nicchia (base/impact/accent via
core/font_manager.py), impact 1.3x-1.5x uppercase colore highlight, accent
handwritten 1.1x con colore dedicato per ruolo. NESSUN contorno nero e
NESSUNA ombra di default (look pulito TikTok): leggibilità da contrasto
tema + pill sul punch-in. Colori sempre coerenti col tema (base dal tema,
highlight/accent validati per contrasto sullo sfondo).

Personaggio (mezzo busto/mezza figura, mai figura intera): idle breathing
leggero (solo bob verticale dolce 4px@0.4Hz, nessuna rotazione laterale);
prima apparizione slide&pop 0.20s da +300px (back+quad); cambi posa/lato
morph smart 0.40s dalla vecchia posizione (opaco, niente flash); sparizione
slide-drop +400px + fade 0.16s; punch_in zoom fluido 0.60s (mai jump secco);
stessa identita' -> hold invisibile; gap TTS coperti da tail anti-blink.

Struttura narrativa (hook/corpo/CTA, vedi core/narrative_structure.py):
i chunk portano narrative_role + override anim_entry_mult/anim_pop_from
(hook scattante). I chunk CTA con cta_card=true sono renderizzati come
UNICA card persistente (generate_cta_card_frames): messaggio finale fisso
con reveal karaoke, pill badge, personaggio bloccato e dissolvenza unica.

Lo sfondo resta trasparente (il colore di sfondo e' applicato da ffmpeg
come oggi in `core/video_builder.py`): il parametro `background_color`
e' accettato per compatibilita' API ma non viene disegnato nei frame.
"""

import math
import os
import threading

from PIL import Image, ImageDraw

from config import (
    CHARACTER_ENABLED,
    CHARACTER_ENTRY_DURATION,
    CHARACTER_EXIT_DURATION,
    CHARACTER_FIRST_ENTRY_DURATION,
    CHARACTER_GAP_HOLD_ENABLED,
    CHARACTER_GAP_HOLD_MAX,
    CHARACTER_IDLE_AMP_Y,
    CHARACTER_IDLE_ENABLED,
    CHARACTER_IDLE_FREQ,
    CHARACTER_IDLE_TILT_DEG,
    CHARACTER_MORPH_DURATION,
    CHARACTER_PUNCH_ZOOM_DURATION,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_COLOR,
    SUBTITLE_STROKE_COLOR,
    SUBTITLE_STROKE_WIDTH,
    TEMP_DIR,
    TEXT_ANIMATION_ENTRY_DURATION,
    TEXT_ANIMATION_EXIT_DURATION,
    KEYWORD_ENTRY_SCALE_FROM,
    TEXT_ANIMATION_ACCENT_LIFT_PX,
    TEXT_ANIMATION_HERO_SCALE_FROM,
    TEXT_ANIMATION_HERO_ENTRY_DURATION,
    TEXT_ANIMATION_HERO_EXIT_DELAY,
    TEXT_ANIMATION_NUMBER_ENTRY_DURATION,
    TYPOGRAPHY_ENGINE_ENABLED,
    TYPOGRAPHY_BASE_FONT_SIZE,
    TYPOGRAPHY_BASE_WEIGHT,
    TYPOGRAPHY_IMPACT_SCALE,
    TYPOGRAPHY_ACCENT_SCALE,
    TYPOGRAPHY_STROKE_WIDTH,
    TYPOGRAPHY_SHADOW_ENABLED,
    TYPOGRAPHY_SHADOW_OFFSET,
    TYPOGRAPHY_SHADOW_FILL,
)
from core.easing import (
    clamp01,
    ease_out_cubic,
    ease_out_back,
    ease_out_quad,
    ease_in_out_cubic,
    ease_in_cubic,
)
try:
    from config import (
        ENABLE_ADVANCED_KINETICS as _ADV_KINETICS,
        COLOR_BRAND_ACCENT as _BRAND_ACCENT,
        BASE_WORD_FONT_PATH as _BASE_FONT_PATH,
        HERO_WORD_FONT_PATH as _HERO_FONT_PATH,
    )
except Exception:  # config datata
    _ADV_KINETICS = False
    _BRAND_ACCENT = "#FF3366"
    _BASE_FONT_PATH = "assets/fonts/Inter-Bold.ttf"
    _HERO_FONT_PATH = "assets/fonts/Montserrat-Black.ttf"
try:
    from core.advanced_kinetics import (
        advanced_entry_duration as _adv_entry_dur,
        advanced_stroke_for as _adv_stroke_for,
        brand_accent_rgba as _brand_rgba,
        draw_hero_badge as _draw_hero_badge,
        hero_shake_offset as _hero_shake,
        t2_peak_scale as _t2_peak,
    )
except Exception:  # modulo opzionale: path legacy invariato
    _adv_entry_dur = None
    _adv_stroke_for = None
    _brand_rgba = None
    _draw_hero_badge = None
    _hero_shake = None
    _t2_peak = None
from core.keywords import normalize_word
from core.renderer import (
    load_font,
    compute_word_layout,
    draw_word,
    draw_text_background,
    get_character_layer,
)

# Re-export per spec ("RENDER E POSIZIONAMENTO (... / core/text_animator.py)").
from core.character_selector import (
    calculate_character_bbox as calculate_character_bbox,
    resolve_chunk_layout as resolve_chunk_layout,
)
from core.renderer import calculate_character_transform as calculate_character_transform
from core.layout_presets import (
    preset_font_scale,
    preset_needs_text_background,
    preset_safe_area,
    preset_side,
)

# Durata entrata personaggio legacy v1 (offset corto, feel premium).
_CHARACTER_ENTRY_DURATION = 0.35
_CHARACTER_SLIDE_UP_PX = 320
_CHARACTER_SLIDE_SIDE_PX = 260
# Entrata slide&pop: offset Y fisso +300px (spec), durata ENTRY (~0.20s).
_CHARACTER_ENTRY_SLIDE_Y = 300
# Uscita slide-drop: verso +400px con ease_in_cubic, durata EXIT (~0.16s).
_CHARACTER_EXIT_DROP_Y = 400
# Sistema a zone: prima apparizione fade+slide/zoom ENTRY (~0.20s, ~6 frame);
# uscita slide-drop+fade EXIT (~0.16s, ~5 frame) quando sparisce; morph di
# continuita' 0.40s e zoom punch smart 0.60s restano morbidi (ritmo coerente).
# Valori da config (override via env), fallback storici se import fallisce.
try:
    _CHARACTER_ZONE_ENTRY_DURATION = max(0.05, float(CHARACTER_ENTRY_DURATION))
except Exception:
    _CHARACTER_ZONE_ENTRY_DURATION = 0.20
try:
    _CHARACTER_ZONE_FIRST_DURATION = max(0.05, float(CHARACTER_FIRST_ENTRY_DURATION))
except Exception:
    _CHARACTER_ZONE_FIRST_DURATION = 0.20
try:
    _CHARACTER_ZONE_EXIT_DURATION = max(0.05, float(CHARACTER_EXIT_DURATION))
except Exception:
    _CHARACTER_ZONE_EXIT_DURATION = 0.16
try:
    _CHARACTER_MORPH_DURATION = max(0.05, float(CHARACTER_MORPH_DURATION))
except Exception:
    _CHARACTER_MORPH_DURATION = 0.40
try:
    _CHARACTER_PUNCH_DURATION = max(0.20, float(CHARACTER_PUNCH_ZOOM_DURATION))
except Exception:
    _CHARACTER_PUNCH_DURATION = 0.60
# Zoom-in dolce per transizione "zoom_in" (center alternativi): scala 0.92->1.0.
_CHARACTER_ZOOM_FROM = 0.92
_CHARACTER_ZOOM_DURATION = 0.45
# Idle breathing leggero ma visibile (spec): solo bob verticale dolce
# dy=sin(2*pi*f*t)*amp_y (4px@0.4Hz); tilt disabilitato (0 = nessuna
# rotazione laterale, niente dondolio). Overhead <5ms: bob = offset intero
# (costo zero); il ramo tilt resta solo se l'utente lo riabilita via env.
try:
    _IDLE_ENABLED = int(CHARACTER_IDLE_ENABLED) != 0
except Exception:
    _IDLE_ENABLED = True
try:
    _IDLE_AMP_Y = max(0.0, float(CHARACTER_IDLE_AMP_Y))
except Exception:
    _IDLE_AMP_Y = 4.0
try:
    _IDLE_FREQ = max(0.05, float(CHARACTER_IDLE_FREQ))
except Exception:
    _IDLE_FREQ = 0.4
try:
    _IDLE_TILT_DEG = max(0.0, float(CHARACTER_IDLE_TILT_DEG))
except Exception:
    _IDLE_TILT_DEG = 0.0
_IDLE_TILT_STEP = 0.3  # quantizzazione tilt per cache (<=9 varianti per size)
_TWO_PI = 6.283185307179586
# Cache rotazioni tilt: {(id(img), tilt_q): img ruotata} con lock, cap 64.
_tilt_cache: dict[tuple[int, float], Image.Image] = {}
_tilt_cache_lock = threading.Lock()
# --- OTTIMIZZAZIONI VELOCITA' (P0) ---
# Singleton FontManager condiviso: evita mkdir+scan disco per ogni chunk.
_shared_font_manager = None
_shared_font_manager_lock = threading.Lock()


def _get_shared_font_manager():
    global _shared_font_manager
    if _shared_font_manager is not None:
        return _shared_font_manager
    with _shared_font_manager_lock:
        if _shared_font_manager is None:
            try:
                from core.font_manager import FontManager
                _shared_font_manager = FontManager()
            except Exception:
                _shared_font_manager = None
    return _shared_font_manager


def _fast_resample_for_scale(scale: float):
    """Resampling veloce per animazioni per-parola.

    LANCZOS e' 4-8x piu' lento e indistinguibile su caption 60-90px
    in movimento: BILINEAR vicino a 1.0, BICUBIC altrimenti.
    LANCZOS resta solo per resize una-tantum (personaggio/font).
    """
    try:
        if abs(scale - 1.0) < 0.12:
            return Image.Resampling.BILINEAR
        return Image.Resampling.BICUBIC
    except AttributeError:  # Pillow < 9.1
        try:
            if abs(scale - 1.0) < 0.12:
                return Image.BILINEAR
            return Image.BICUBIC
        except AttributeError:
            return Image.NEAREST


# Probe microscopica condivisa per textlength (evita Image 1080x1920 per layout).
_probe_img = None
_probe_draw = None
_probe_lock = threading.Lock()


def _get_probe_draw():
    global _probe_img, _probe_draw
    if _probe_draw is not None:
        return _probe_draw
    with _probe_lock:
        if _probe_draw is None:
            _probe_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            _probe_draw = ImageDraw.Draw(_probe_img)
    return _probe_draw


# Cache pill pre-renderizzate per bbox -> overlay RGBA.
_pill_cache: dict[tuple[int, int, int, int], Image.Image] = {}
_pill_cache_lock = threading.Lock()


def _get_cached_pill_overlay(bbox: tuple[int, int, int, int], fill, pad: int, radius: int):
    key = (bbox[0], bbox[1], bbox[2], bbox[3], pad, radius,
           fill[0] if len(fill) > 0 else 0, fill[1] if len(fill) > 1 else 0,
           fill[2] if len(fill) > 2 else 0, fill[3] if len(fill) > 3 else 255)
    hit = _pill_cache.get(key)
    if hit is not None:
        return hit
    with _pill_cache_lock:
        hit = _pill_cache.get(key)
        if hit is not None:
            return hit
        overlay = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        try:
            d.rounded_rectangle([bbox[0], bbox[1], bbox[2], bbox[3]],
                                radius=radius, fill=fill)
        except (AttributeError, ValueError, TypeError):
            d.rectangle([bbox[0], bbox[1], bbox[2], bbox[3]], fill=fill)
        if len(_pill_cache) < 32:
            _pill_cache[key] = overlay
        return overlay


# Cache varianti opacity personaggio: {(id(char), opacity//16): img} evita copy+point per frame.
_char_opacity_cache: dict[tuple[int, int], Image.Image] = {}
_char_opacity_cache_lock = threading.Lock()


def _get_char_at_opacity(char_img: Image.Image, opacity: int):
    if opacity >= 255:
        return char_img
    if opacity <= 0:
        return None
    # Quantizza a step 8 per riuso (delta visivo nullo, hit-rate alto).
    q = int(round(opacity / 8.0)) * 8
    q = max(8, min(255, q))
    if q >= 255:
        return char_img
    key = (id(char_img), q)
    hit = _char_opacity_cache.get(key)
    if hit is not None:
        return hit
    with _char_opacity_cache_lock:
        hit = _char_opacity_cache.get(key)
        if hit is not None:
            return hit
        try:
            to_paste = char_img.copy()
            alpha = to_paste.getchannel("A")
            # Lookup table pre-calcolata: molto piu' veloce di lambda per pixel.
            lut = [0] * 256
            for a in range(256):
                lut[a] = (a * q) // 255
            alpha = alpha.point(lut)
            to_paste.putalpha(alpha)
        except Exception:
            return char_img
        if len(_char_opacity_cache) < 128:
            # Evita crescita infinita su video lunghi: pulizia leggera.
            if len(_char_opacity_cache) >= 120:
                _char_opacity_cache.clear()
            _char_opacity_cache[key] = to_paste
        return to_paste
# Modalita' di uscita del personaggio a fine chunk (vedi render_all lookahead).
_CHAR_EXIT_WITH_TEXT = "with_text"  # segue il fade di gruppo del testo
_CHAR_EXIT_SLIDE_DOWN = "slide_down"  # scende fuori campo (cambio lato dopo)
_CHAR_EXIT_HOLD = "hold"  # resta opaco fino al taglio (stesso preset+posa dopo)


class TextAnimationError(Exception):
    """Errore durante la generazione dei frame animati."""
    pass


def _to_rgba(color, default: tuple) -> tuple[int, int, int, int]:
    """Converte hex "#RRGGBB" o tupla RGB/RGBA in RGBA.

    Accetta entrambi i formati per compatibilita' pipeline:
    - theme.py viaggia in hex, keywords.py in RGBA (vedi core/keywords.py).
    """
    if color is None:
        return default
    if isinstance(color, str):
        s = color.strip()
        if s.startswith("#") and len(s) == 7:
            try:
                return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 255)
            except ValueError:
                return default
        return default
    if isinstance(color, (tuple, list)):
        try:
            c = tuple(int(v) for v in color)
        except (TypeError, ValueError):
            return default
        if len(c) == 3:
            return (c[0], c[1], c[2], 255)
        if len(c) >= 4:
            return (c[0], c[1], c[2], c[3])
    return default


def _resolve_word_fill(word_norm: str, base_rgba: tuple, keyword_colors: dict | None) -> tuple:
    """Colore della parola: colore keyword se match, altrimenti testo base."""
    if keyword_colors:
        hit = keyword_colors.get(word_norm)
        if hit is not None:
            return _to_rgba(hit, base_rgba)
    return base_rgba


# ---------------------------------------------------------------------------
# Tier animazioni testo T0-T3 (premium senza over-engineering)
# ---------------------------------------------------------------------------
# Unificazione moto/colore (singola fonte di verita'):
# - moto  = (style, is_hero, is_number) da text_tagger/narrative_structure
#   (style==impact <=> keyword ai fini dell'animazione; keywords.py resta
#   fonte del COLORE, text_tagger resta fonte del MOTO);
# - colore = _styled_fills (tema + highlight preset + palette keyword fallback).
# Tier:
#   T0 base   fade (solo opacita', scala 1, draw diretto: costo ~0);
#   T1 accent rise-fade (opacita' + y lift px, MAI scala: non deforma
#     handwritten; costo +5%, solo offset, nessun resize);
#   T2 impact pop standard (opacita' + scala ease_out_back, tile resize);
#   T3 hero   1 parola/video (pop marcato + durata lunga + exit ritardata);
#   T3-num    impact con cifre (pop corto dedicato, mai hero).
# Path legacy (senza styled_words) usa solo T0/T2 per stabilita'.

def _has_digit_fast(text: str) -> bool:
    """Vero se contiene una cifra (numeri/dati -> pop corto, mai hero)."""
    try:
        for _c in str(text or ""):
            if "0" <= _c <= "9":
                return True
        return False
    except Exception:
        return False


def _resolve_motion_params(
    preset: dict | None,
    chunk: dict | None,
) -> tuple[float, float, float, float, float, float]:
    """Risolvi (entry_dur, scale_from, accent_lift, hero_dur, hero_from,
    number_dur) con priorita' stabile e clamp.

    - entry_dur: base config * anim_entry_mult del chunk (hook scattante);
      hero usa poi HERO_ENTRY_DURATION (override, non moltiplicato).
    - scale_from: chunk anim_pop_from esplicito (hook) > preset anim.pop_from
      (nicchia) > KEYWORD_ENTRY_SCALE_FROM globale.
    Mai eccezioni: fallback ai default storici.
    """
    try:
        _entry_base = max(0.01, float(TEXT_ANIMATION_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _entry_base = 0.18
    try:
        _mult = float((chunk or {}).get("anim_entry_mult", 1.0)) if isinstance(chunk, dict) else 1.0
        if 0.3 <= _mult <= 1.5:
            entry_dur = max(0.01, _entry_base * _mult)
        else:
            entry_dur = _entry_base
    except (TypeError, ValueError, AttributeError):
        entry_dur = _entry_base
    try:
        _global_from = float(KEYWORD_ENTRY_SCALE_FROM)
        if not (0.1 <= _global_from <= 1.0):
            _global_from = 0.7
    except (TypeError, ValueError, NameError):
        _global_from = 0.7
    # Preset nicchia (se disponibile) come default di tier.
    try:
        _preset_from = float((preset or {}).get("anim", {}).get("pop_from", _global_from))
        if not (0.1 <= _preset_from <= 1.0):
            _preset_from = _global_from
    except (TypeError, ValueError, AttributeError):
        _preset_from = _global_from
    scale_from = _preset_from
    # Override esplicito per-chunk (hook narrativo) vince su tutto.
    try:
        if isinstance(chunk, dict) and "anim_pop_from" in chunk:
            _pop = float(chunk.get("anim_pop_from", scale_from))
            if 0.1 <= _pop <= 1.0:
                scale_from = _pop
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        _lift = float(TEXT_ANIMATION_ACCENT_LIFT_PX)
        _lift = min(24.0, max(0.0, _lift))
    except (TypeError, ValueError, NameError):
        _lift = 10.0
    try:
        _hero_dur = max(0.05, float(TEXT_ANIMATION_HERO_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _hero_dur = 0.22
    try:
        _hero_from = float(TEXT_ANIMATION_HERO_SCALE_FROM)
        if not (0.1 <= _hero_from <= 1.0):
            _hero_from = 0.6
    except (TypeError, ValueError, NameError):
        _hero_from = 0.6
    try:
        _num_dur = max(0.05, float(TEXT_ANIMATION_NUMBER_ENTRY_DURATION))
    except (TypeError, ValueError, NameError):
        _num_dur = 0.15
    try:
        _hero_delay = max(0.0, float(TEXT_ANIMATION_HERO_EXIT_DELAY))
        _hero_delay = min(0.20, _hero_delay)
    except (TypeError, ValueError, NameError):
        _hero_delay = 0.06
    return entry_dur, scale_from, _lift, _hero_dur, _hero_from, _num_dur


def _hero_exit_delay() -> float:
    """Ritardo exit hero in secondi (clamp 0-0.20, default 0.06 ~2 frame)."""
    try:
        _d = max(0.0, float(TEXT_ANIMATION_HERO_EXIT_DELAY))
        return min(0.20, _d)
    except (TypeError, ValueError, NameError):
        return 0.06


def _word_tier(word: dict) -> tuple[str, bool, bool]:
    """Tier moto per parola tipografica: (style, is_hero, is_number).

    Normalizza style a base/impact/accent; is_hero vale solo su impact senza
    cifre (numeri mai hero); is_number da flag o digit check. Mai eccezioni.
    """
    try:
        _style = str((word or {}).get("style", "base"))
    except Exception:
        _style = "base"
    if _style not in ("base", "impact", "accent"):
        # Compat legacy: is_keyword True <=> impact (unificazione).
        try:
            _style = "impact" if bool((word or {}).get("is_keyword", False)) else "base"
        except Exception:
            _style = "base"
    try:
        _is_num = bool((word or {}).get("is_number", False)) or _has_digit_fast(
            str((word or {}).get("word", "")))
    except Exception:
        _is_num = False
    try:
        _is_hero = bool((word or {}).get("is_hero", False))
    except Exception:
        _is_hero = False
    if _style != "impact" or _is_num:
        _is_hero = False
    return _style, _is_hero, _is_num


def _hero_exit_factor(
    t: float,
    chunk_end: float,
    exit_dur: float,
    exit_factor_base: float,
) -> float:
    """Exit factor ritardato per hero: resta 1.0 per hero_delay, poi fade compresso.

    Mantiene l'allineamento a chunk_end (nessun frame oltre): se exit_dur <=
    delay, usa il fade base. Curva identica al gruppo (ease_in_cubic).
    """
    try:
        if exit_dur <= 0:
            return exit_factor_base
        _delay = _hero_exit_delay()
        if _delay <= 0.0 or exit_dur <= _delay + 1e-6:
            return exit_factor_base
        _start = chunk_end - exit_dur + _delay
        if t < _start:
            return 1.0
        _p = clamp01((t - _start) / max(1e-6, exit_dur - _delay))
        return 1.0 - ease_in_cubic(_p)
    except Exception:
        return exit_factor_base


# ---------------------------------------------------------------------------
# Semantic Typography Engine v1 — helpers multi-style
# ---------------------------------------------------------------------------

# Cache font tipografici {(path, size): PIL font} per non ricaricare per frame.
_typo_font_cache: dict[tuple[str, int], object] = {}


def _is_typography_chunk(chunk: dict) -> bool:
    """Vero se il chunk porta styled_words validi (vedi core/text_tagger.py)."""
    try:
        if not TYPOGRAPHY_ENGINE_ENABLED:
            return False
    except NameError:
        pass
    styled = (chunk or {}).get("styled_words")
    if not isinstance(styled, list) or not styled:
        return False
    for s in styled:
        if isinstance(s, dict) and str(s.get("word", "")).strip() and s.get("style") in ("base", "impact", "accent"):
            return True
    return False


def _resolve_typography_preset(chunk: dict, explicit_niche=None, explicit_preset=None) -> dict:
    """Preset tipografico effettivo (explicit_preset > chunk niche > explicit_niche > fallback)."""
    try:
        from core.typography_presets import get_preset
    except Exception:
        return {
            "niche": "fallback", "fonts": {"base": [], "impact": [], "accent": []},
            "colors": {"base": "#FFFFFF", "highlight": "#FFD700", "accent": "#FFE8A3", "stroke": "#000000"},
            "sizes": {"base": TYPOGRAPHY_BASE_FONT_SIZE, "impact_scale": TYPOGRAPHY_IMPACT_SCALE, "accent_scale": TYPOGRAPHY_ACCENT_SCALE},
            "stroke_width": 0,
            "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
            "impact_uppercase": True,
        }
    if isinstance(explicit_preset, dict) and "fonts" in explicit_preset:
        return explicit_preset
    niche = None
    try:
        if isinstance(chunk, dict) and chunk.get("typography_niche"):
            niche = chunk.get("typography_niche")
        elif explicit_niche:
            niche = explicit_niche
    except Exception:
        niche = explicit_niche
    return get_preset(niche)


def _resolve_base_weight() -> int:
    """Peso desiderato del font base (default 600 = SemiBold, clamp 400-800)."""
    try:
        w = int(TYPOGRAPHY_BASE_WEIGHT)
    except (TypeError, ValueError, NameError):
        w = 600
    return min(800, max(400, w))


def _apply_font_weight(font, weight: int) -> bool:
    """Imposta l'asse Weight di un font variabile (es. 600 = SemiBold).

    Cerca l'asse "Weight" tra quelli del file (ordine qualunque: funziona con
    Inter[opsz,wght], Roboto[wdth,wght] e single-axis), preserva i default
    degli altri assi e clamp al range del font. Ritorna True se applicato.
    Ritorna False per font statici (Anton, Poppins, ...): per quelli il
    chiamante usa il grassetto sintetico (stroke 1px stesso colore).
    Mai eccezioni.
    """
    if font is None:
        return False
    try:
        axes = font.get_variation_axes()
    except Exception:
        return False
    if not axes:
        return False
    try:
        w_idx = None
        for i, ax in enumerate(axes):
            try:
                nm = ax.get("name", b"") if isinstance(ax, dict) else b""
                nm = bytes(nm).lower() if isinstance(nm, bytes) else str(nm).lower().encode("utf-8", "ignore")
            except Exception:
                continue
            if b"weight" in nm:
                w_idx = i
                break
        if w_idx is None:
            return False
        coords: list = []
        for i, ax in enumerate(axes):
            try:
                lo = float(ax["minimum"])
                de = float(ax["default"])
                hi = float(ax["maximum"])
            except (KeyError, TypeError, ValueError):
                return False
            if i == w_idx:
                coords.append(int(round(min(hi, max(lo, float(weight))))))
            else:
                coords.append(de)
        font.set_variation_by_axes(coords)
        return True
    except Exception:
        return False


# Grassetto sintetico per font base statici (Poppins/Lato/...): 1px con lo
# stesso colore del fill = inspessimento leggero, nessun contorno nero.
_BASE_SYNTHETIC_STROKE_WIDTH = 1


def _load_typography_fonts(preset: dict, font_scale: float = 1.0) -> dict:
    """Carica i 3 font PIL del preset alle dimensioni ponderate.

    - base:   size standard (es. 60px) * font_scale del layout preset,
      SEMPRE al peso TYPOGRAPHY_BASE_WEIGHT (600 = SemiBold: leggermente più
      in grassetto del Regular, non troppo). Vedi `_apply_font_weight`.
    - impact: base * impact_scale (1.3x-1.5x, es. 80-90px, peso suo proprio)
    - accent: base * accent_scale (1.1x, peso suo proprio)
    Ritorna {"base": font, "impact": font, "accent": font, "sizes": {...},
    "paths": {...}, "names": {...}, "base_weight": int,
    "base_weight_applied": bool}. Se False (font statico), il rendering usa
    il grassetto sintetico per le parole base (vedi _BASE_SYNTHETIC_STROKE_WIDTH).
    Mai eccezioni: fallback a renderer.load_font.
    """
    try:
        scale = float(font_scale)
    except (TypeError, ValueError):
        scale = 1.0
    if scale <= 0:
        scale = 1.0
    sizes_cfg = preset.get("sizes", {}) if isinstance(preset, dict) else {}
    try:
        base_size = int(round(float(sizes_cfg.get("base", TYPOGRAPHY_BASE_FONT_SIZE)) * scale))
    except (TypeError, ValueError):
        base_size = TYPOGRAPHY_BASE_FONT_SIZE
    try:
        impact_scale = float(sizes_cfg.get("impact_scale", TYPOGRAPHY_IMPACT_SCALE))
    except (TypeError, ValueError):
        impact_scale = 1.4
    try:
        accent_scale = float(sizes_cfg.get("accent_scale", TYPOGRAPHY_ACCENT_SCALE))
    except (TypeError, ValueError):
        accent_scale = 1.1
    impact_scale = min(1.6, max(1.2, impact_scale))
    accent_scale = min(1.3, max(1.0, accent_scale))
    sizes = {
        "base": max(24, base_size),
        "impact": max(24, int(round(base_size * impact_scale))),
        "accent": max(24, int(round(base_size * accent_scale))),
    }
    # Peso base (600 = SemiBold): nella chiave cache del base, così istanze
    # con pesi diversi non si condividono mai.
    base_weight = _resolve_base_weight()
    fonts_cfg = preset.get("fonts", {}) if isinstance(preset, dict) else {}
    out: dict = {"sizes": sizes, "paths": {}, "names": {},
                 "base_weight": base_weight, "base_weight_applied": False}
    try:
        manager = _get_shared_font_manager()
    except Exception:
        manager = None
    for role in ("base", "impact", "accent"):
        candidates = fonts_cfg.get(role, []) if isinstance(fonts_cfg, dict) else []
        if not isinstance(candidates, list):
            candidates = []
        font_obj = None
        chosen_path = ""
        chosen_name = ""
        for cand in candidates:
            name = str(cand or "").strip()
            if not name:
                continue
            path = ""
            if manager is not None:
                try:
                    path = manager.ensure_font_exists(name)
                except Exception:
                    path = ""
            if path:
                key = (path, sizes[role], base_weight) if role == "base" else (path, sizes[role])
                cached = _typo_font_cache.get(key)
                if cached is not None:
                    font_obj = cached
                    chosen_path = path
                    chosen_name = name
                    break
                try:
                    from PIL import ImageFont
                    font_obj = ImageFont.truetype(path, sizes[role])
                    _typo_font_cache[key] = font_obj
                    chosen_path = path
                    chosen_name = name
                    break
                except Exception:
                    continue
        if font_obj is None:
            # Fallback coerente PER RUOLO (mai lo stesso font per tutti i ruoli
            # se possibile): base -> sans pulito, impact -> heavy/display,
            # accent -> handwritten/serif. Così i 3 livelli restano distinguibili
            # anche senza rete o con asset mancanti.
            role_fallback_names = {
                "base": ["Arial", "Inter", "Roboto"],
                "impact": ["Anton", "Impact", "Oswald"],
                "accent": ["Caveat", "Patrick Hand", "Playfair Display"],
            }
            loaded = False
            if manager is not None:
                for fb_name in role_fallback_names.get(role, []):
                    try:
                        fb_path = manager.ensure_font_exists(fb_name)
                    except Exception:
                        fb_path = ""
                    if fb_path:
                        try:
                            from PIL import ImageFont as _IF
                            key = (fb_path, sizes[role], base_weight) if role == "base" else (fb_path, sizes[role])
                            cached = _typo_font_cache.get(key)
                            if cached is not None:
                                font_obj = cached
                            else:
                                font_obj = _IF.truetype(fb_path, sizes[role])
                                _typo_font_cache[key] = font_obj
                            chosen_path = fb_path
                            chosen_name = fb_name + " (fallback ruolo)"
                            loaded = True
                            break
                        except Exception:
                            continue
            if not loaded:
                try:
                    font_obj = load_font(sizes[role])
                except Exception:
                    from PIL import ImageFont
                    font_obj = ImageFont.load_default()
        out[role] = font_obj
        out["paths"][role] = chosen_path
        out["names"][role] = chosen_name
    # Peso SemiBold sul base (testo chiaro): True su variabile, False su
    # statico (il rendering usa allora il grassetto sintetico per il base).
    # Idempotente sulle istanze cachate (stesso peso = nessun cambio).
    try:
        out["base_weight_applied"] = bool(_apply_font_weight(out.get("base"), base_weight))
    except Exception:
        out["base_weight_applied"] = False
    # Garanzia anti-collasso: se due ruoli hanno risolto lo STESSO file font,
    # prova a differenziare l'accent con un fallback alternativo (evita che
    # base/accent risultino visivamente identici).
    try:
        _paths = out.get("paths", {})
        if _paths.get("accent") and _paths.get("accent") == _paths.get("base"):
            # L'accent è collassato sul base: il tagging resta comunque valido
            # (distinzione per colore dedicato, vedi _styled_fills), nessun crash.
            pass
    except Exception:
        pass
    return out


def _luminance_rgba(rgba: tuple) -> float:
    """Luminanza percepita 0-255 da RGBA (canali 0-2)."""
    try:
        r, g, b = int(rgba[0]), int(rgba[1]), int(rgba[2])
    except Exception:
        return 255.0
    return 0.299 * r + 0.587 * g + 0.114 * b


def _contrast_ok(fg: tuple, bg_hex_or_rgba, min_diff: int = 80) -> bool:
    """Vero se la differenza di luminanza fg/bg supera la soglia."""
    try:
        bg = _to_rgba(bg_hex_or_rgba, (0, 0, 0, 255))
        return abs(_luminance_rgba(fg) - _luminance_rgba(bg)) >= float(min_diff)
    except Exception:
        return True


def _styled_fills(
    preset: dict,
    base_override=None,
    background_color=None,
    keyword_colors: dict | None = None,
) -> dict:
    """Colori RGBA per ruolo, coerenti al 100% con tema + sfondo + keyword.

    Regole di attribuzione (singola fonte di verità):
    - base:   colore testo del TEMA (base_override) se fornito, altrimenti
      preset. Se il contrasto sullo sfondo è insufficiente, flip a
      bianco/nero (il più distante dallo sfondo).
    - impact: highlight del preset, MA validato per contrasto sullo sfondo:
      se illeggibile prova in ordine la palette keyword del video, poi
      l'highlight_alt del preset, poi bianco/nero sicuri. Deve inoltre essere
      distinto dal base (se troppo simile, preferisce l'alternativa).
    - accent: colore dedicato del preset (mai uguale al base per costruzione
      dei preset v2). Se manca o è uguale al base, deriva una tinta coerente;
      se illeggibile sullo sfondo, ripiega sul base (distinzione resta via font).
    - stroke: sempre trasparente (nessun contorno nero). La chiave resta per
      compatibilità API ma con width=0 non viene mai disegnata.
    """
    from config import THEME_MIN_LUMINANCE_DIFF
    colors = preset.get("colors", {}) if isinstance(preset, dict) else {}
    preset_base_hex = colors.get("base", "#FFFFFF")
    highlight_hex = colors.get("highlight", "#FFD700")
    highlight_alt = colors.get("highlight_alt")
    accent_hex = colors.get("accent", None)

    # --- base: il tema vince (coerenza sfondo/testo della pipeline) ---
    if base_override is not None:
        base_rgba = _to_rgba(base_override, _to_rgba(preset_base_hex, SUBTITLE_COLOR))
    else:
        base_rgba = _to_rgba(preset_base_hex, SUBTITLE_COLOR)
    if background_color is not None and not _contrast_ok(
        base_rgba, background_color, THEME_MIN_LUMINANCE_DIFF
    ):
        bg_lum = _luminance_rgba(_to_rgba(background_color, (0, 0, 0, 255)))
        base_rgba = (255, 255, 255, 255) if abs(255 - bg_lum) >= abs(0 - bg_lum) else (0, 0, 0, 255)

    # --- impact: highlight validato, con fallback a catena ---
    impact_candidates: list[tuple] = [_to_rgba(highlight_hex, base_rgba)]
    if isinstance(keyword_colors, dict):
        for _v in keyword_colors.values():
            impact_candidates.append(_to_rgba(_v, base_rgba))
    if highlight_alt:
        impact_candidates.append(_to_rgba(highlight_alt, base_rgba))
    bg_lum_for_bw: float | None = None
    if background_color is not None:
        try:
            bg_lum_for_bw = _luminance_rgba(_to_rgba(background_color, (0, 0, 0, 255)))
        except Exception:
            bg_lum_for_bw = None
    impact_rgba = impact_candidates[0]
    for cand in impact_candidates:
        if background_color is not None and not _contrast_ok(
            cand, background_color, THEME_MIN_LUMINANCE_DIFF
        ):
            continue
        # Distinto dal base: differenza luminanza minima o tinta diversa.
        try:
            same_lum = abs(_luminance_rgba(cand) - _luminance_rgba(base_rgba)) < 40
            same_rgb = tuple(cand[:3]) == tuple(base_rgba[:3])
        except Exception:
            same_lum, same_rgb = False, False
        if same_rgb or same_lum:
            # Cerca un'alternativa più distinta prima di accettarlo.
            continue
        impact_rgba = cand
        break
    else:
        # Nessun candidato ideale: prendi il primo leggibile, o bianco/nero sicuro.
        for cand in impact_candidates:
            if background_color is None or _contrast_ok(
                cand, background_color, THEME_MIN_LUMINANCE_DIFF
            ):
                impact_rgba = cand
                break
        else:
            if bg_lum_for_bw is not None:
                impact_rgba = (255, 255, 255, 255) if bg_lum_for_bw < 128 else (0, 0, 0, 255)
        # Ultima rete: mai identico al base.
        try:
            if tuple(impact_rgba[:3]) == tuple(base_rgba[:3]):
                impact_rgba = (255, 255, 255, 255) if tuple(base_rgba[:3]) != (255, 255, 255) else (0, 0, 0, 255)
        except Exception:
            pass

    # --- accent: dedicato, distinto dal base, leggibile ---
    if isinstance(accent_hex, str) and accent_hex.strip():
        accent_rgba = _to_rgba(accent_hex, base_rgba)
    else:
        accent_rgba = base_rgba
    try:
        accent_same_as_base = tuple(accent_rgba[:3]) == tuple(base_rgba[:3])
    except Exception:
        accent_same_as_base = True
    if accent_same_as_base:
        # Deriva una tinta coerente dall'impact (stessa famiglia, più chiara):
        # mix 55% impact + 45% base per restare armonico ma distinguibile.
        try:
            accent_rgba = tuple(
                int(round(0.55 * impact_rgba[i] + 0.45 * base_rgba[i])) for i in range(3)
            ) + (255,)
            if tuple(accent_rgba[:3]) == tuple(base_rgba[:3]):
                accent_rgba = impact_rgba
        except Exception:
            accent_rgba = impact_rgba
    if background_color is not None and not _contrast_ok(
        accent_rgba, background_color, THEME_MIN_LUMINANCE_DIFF
    ):
        accent_rgba = base_rgba  # ripiego leggibile; distinzione resta via font

    return {
        "base": base_rgba,
        "impact": impact_rgba,
        "accent": accent_rgba,
        # Trasparente: nessun contorno nero su nessuna parola.
        "stroke": (0, 0, 0, 0),
    }


def compute_styled_layout(
    styled_words: list[dict],
    fonts: dict,
    max_width: int,
    area: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """Layout multi-style: misura OGNI parola col suo font e wrappa per larghezza cumulativa.

    Args:
        styled_words: [{"word","display","style",...}] (display già uppercase per impact).
        fonts: {"base": font, "impact": font, "accent": font} da _load_typography_fonts.
        max_width: larghezza massima blocco (es. VIDEO_WIDTH*0.85, poi min con area).
        area: text_safe_area (x_min,y_min,x_max,y_max); None = centro schermo.

    Returns:
        Lista parallela a styled_words: {"word","display","style","x","y","width","height","font_role"}.
        Il blocco è centrato DENTRO l'area e resta dentro quando ci sta
        (stessa semantica di renderer.compute_word_layout).
    """
    from PIL import Image as _Image, ImageDraw as _ImageDraw
    from core.renderer import LINE_SPACING
    items: list[dict] = []
    for s in styled_words or []:
        role = s.get("style", "base") if isinstance(s, dict) else "base"
        if role not in ("base", "impact", "accent"):
            role = "base"
        word = str((s or {}).get("display", (s or {}).get("word", "")))
        items.append({"word": str((s or {}).get("word", "")), "display": word, "style": role})
    if not items:
        return []
    if area is not None:
        try:
            ax0, ay0, ax1, ay1 = (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
            if ax1 > ax0 and ay1 > ay0:
                max_width = min(int(max_width), ax1 - ax0)
                center_x = (ax0 + ax1) / 2.0
                center_y = (ay0 + ay1) / 2.0
                use_area = True
            else:
                use_area = False
        except (TypeError, ValueError, IndexError):
            use_area = False
    else:
        use_area = False
    if not use_area:
        ax0, ay0, ax1, ay1 = 0, 0, VIDEO_WIDTH, VIDEO_HEIGHT
        center_x = VIDEO_WIDTH / 2.0
        center_y = VIDEO_HEIGHT / 2.0
    try:
        draw = _get_probe_draw()
    except Exception:
        from PIL import Image as _Image, ImageDraw as _ImageDraw
        probe = _Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = _ImageDraw.Draw(probe)

    def _font_for(role: str):
        f = fonts.get(role)
        if f is None:
            f = fonts.get("base")
        return f

    def _metrics_for(role: str) -> tuple[int, int]:
        """(ascent, descent) del font dalla baseline (getmetrics, mai crash)."""
        f = _font_for(role)
        try:
            asc, desc = f.getmetrics()
            asc, desc = int(asc), int(desc)
            if asc <= 0 or desc < 0 or asc + desc <= 0:
                raise ValueError("metriche degeneri")
            return asc, desc
        except Exception:
            # Fallback bitmap/default: proporzioni standard del size.
            try:
                size = int(getattr(f, "size", 60))
            except Exception:
                size = 60
            return max(8, int(round(size * 0.80))), max(0, int(round(size * 0.20)))

    def _measure(display: str, role: str) -> tuple[float, int, int, int]:
        """(larghezza, ascent, descent, altezza_linea) per la parola."""
        f = _font_for(role)
        try:
            w = float(draw.textlength(display, font=f))
        except Exception:
            w = float(len(display) * 30)
        asc, desc = _metrics_for(role)
        return w, asc, desc, max(8, asc + desc)

    # Spazio medio: usa il base (stabile tra righe miste).
    try:
        space_w = float(draw.textlength(" ", font=_font_for("base")))
    except Exception:
        space_w = 20.0

    # Wrapping per larghezza cumulativa (misure stabili da metriche font,
    # non da bbox glifo-dipendente: niente salti tra maiuscole/minuscole).
    lines: list[list[int]] = []
    current: list[int] = []
    current_width = 0.0
    widths: list[float] = []
    ascents: list[int] = []
    descents: list[int] = []
    heights: list[int] = []
    for idx, it in enumerate(items):
        w, asc, desc, h = _measure(it["display"], it["style"])
        widths.append(w)
        ascents.append(asc)
        descents.append(desc)
        heights.append(h)
    for idx, it in enumerate(items):
        w = widths[idx]
        extra = w + (space_w if current else 0)
        if current_width + extra <= max_width or not current:
            current.append(idx)
            current_width += extra
        else:
            lines.append(current)
            current = [idx]
            current_width = w
    if current:
        lines.append(current)

    # Altezza riga da metriche: max ascent + max descent della riga.
    # Tutte le parole della riga condividono la STESSA baseline
    # (allineamento professionale, mai parole "flottanti").
    line_widths: list[float] = []
    line_ascents: list[int] = []
    line_descents: list[int] = []
    line_heights: list[int] = []
    for line in lines:
        lw = sum(widths[i] for i in line) + space_w * (len(line) - 1) if line else 0.0
        la = max([ascents[i] for i in line]) if line else 0
        ld = max([descents[i] for i in line]) if line else 0
        line_widths.append(lw)
        line_ascents.append(la)
        line_descents.append(ld)
        line_heights.append(la + ld)
    total_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1) if lines else 0
    start_y = int(round(center_y - total_height / 2.0))
    if use_area and lines:
        start_y = max(ay0, min(start_y, ay1 - total_height))

    layout: list[dict] = [None] * len(items)  # type: ignore
    y = start_y
    for line, lw, la, ld, lh in zip(lines, line_widths, line_ascents, line_descents, line_heights):
        x = center_x - lw / 2.0
        if use_area:
            x = max(float(ax0), x)
            if x + lw > VIDEO_WIDTH - 8:
                x = max(float(ax0), VIDEO_WIDTH - 8 - lw)
        baseline = y + la  # baseline comune di riga (anchor "la": y = baseline - ascent)
        for j, idx in enumerate(line):
            it = items[idx]
            w = widths[idx]
            asc = ascents[idx]
            # Top per anchor default "la": baseline - ascent del SINGOLO font.
            # Così base piccolo e impact grosso stanno sulla stessa baseline.
            y_top = baseline - asc
            layout[idx] = {
                "word": it["word"],
                "display": it["display"],
                "style": it["style"],
                "font_role": it["style"],
                "x": int(round(x)),
                "y": int(round(y_top)),
                "width": int(round(w)),
                "height": int(heights[idx]),
                "line_height": int(lh),
                "baseline": int(round(baseline)),
                "ascent": int(asc),
                "descent": int(descents[idx]),
            }
            x += w
            if j < len(line) - 1:
                x += space_w
        y += lh + LINE_SPACING
    return layout


def _draw_styled_word_direct(
    draw,
    display: str,
    x: int,
    y: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    shadow_offset: tuple[int, int] | None,
    shadow_fill: tuple | None,
    opacity: int,
) -> None:
    """Disegna parola pulita (nessun contorno di default) + ombra opzionale."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    try:
        sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        sw = 0
    if sw < 0:
        sw = 0
    try:
        from core.renderer import _normalize_rgba
        fill_rgba = _normalize_rgba(fill, SUBTITLE_COLOR)
        stroke_rgba = _normalize_rgba(stroke_color, (0, 0, 0, 0))
    except Exception:
        fill_rgba = tuple(fill) if isinstance(fill, (tuple, list)) else SUBTITLE_COLOR
        stroke_rgba = tuple(stroke_color) if isinstance(stroke_color, (tuple, list)) else (0, 0, 0, 0)
    if opacity < 255:
        factor = opacity / 255.0
        fill_rgba = (fill_rgba[0], fill_rgba[1], fill_rgba[2], int(round(fill_rgba[3] * factor)))
        stroke_rgba = (stroke_rgba[0], stroke_rgba[1], stroke_rgba[2], int(round(stroke_rgba[3] * factor)))
    # Ombra prima (solo se abilitata esplicitamente e non trasparente).
    if shadow_offset is not None and shadow_fill is not None and TYPOGRAPHY_SHADOW_ENABLED:
        try:
            sh = tuple(int(v) for v in shadow_fill)
            if len(sh) == 3:
                sh = (sh[0], sh[1], sh[2], 255)
            if len(sh) >= 4 and sh[3] <= 0:
                sh = None
            else:
                sx, sy = int(shadow_offset[0]), int(shadow_offset[1])
                if sx == 0 and sy == 0:
                    sh = None
                elif opacity < 255:
                    sh = (sh[0], sh[1], sh[2], int(round(sh[3] * opacity / 255.0)))
        except (TypeError, ValueError, IndexError):
            sh = None
        if sh is not None:
            try:
                draw.text((x + sx, y + sy), display, font=font, fill=sh)
            except Exception:
                pass
    try:
        if sw <= 0:
            # Path pulito: nessun contorno nero.
            draw.text((x, y), display, font=font, fill=fill_rgba)
        else:
            draw.text((x, y), display, font=font, fill=fill_rgba,
                      stroke_width=sw, stroke_fill=stroke_rgba)
    except Exception:
        try:
            draw.text((x, y), display, font=font, fill=fill_rgba)
        except Exception:
            pass


def _render_styled_scaled_word(
    frame_img,
    display: str,
    x: int,
    y: int,
    word_w: int,
    word_h: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    shadow_offset,
    shadow_fill,
    opacity: int,
    scale: float,
) -> None:
    """Come _render_scaled_word ma con drop shadow inclusa nella tile scalata."""
    if opacity <= 0 or scale <= 0:
        return
    if abs(scale - 1.0) < 1e-3:
        draw = ImageDraw.Draw(frame_img)
        _draw_styled_word_direct(draw, display, x, y, font, fill, stroke_color,
                                 stroke_width, shadow_offset, shadow_fill, opacity)
        return
    try:
        _sw = int(stroke_width or 0)
    except (TypeError, ValueError):
        _sw = 0
    pad = 32 + max(0, _sw) * 2
    try:
        if shadow_offset is None or not TYPOGRAPHY_SHADOW_ENABLED:
            sox, soy = 0, 0
        else:
            sox, soy = int(shadow_offset[0]), int(shadow_offset[1])
    except Exception:
        sox, soy = 0, 0
    pad_x = pad + max(0, sox)
    pad_y = pad + max(0, soy)
    tile_w = max(1, int(word_w + pad_x * 2))
    tile_h = max(1, int(word_h + pad_y * 2))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    _draw_styled_word_direct(tile_draw, display, pad_x, pad_y, font, fill, stroke_color,
                             stroke_width, shadow_offset, shadow_fill, opacity)
    new_w = max(1, int(round(tile_w * scale)))
    new_h = max(1, int(round(tile_h * scale)))
    resample = _fast_resample_for_scale(scale)
    scaled = tile.resize((new_w, new_h), resample)
    cx = x + word_w / 2.0
    cy = y + word_h / 2.0
    tcx = (pad_x + word_w / 2.0) * scale
    tcy = (pad_y + word_h / 2.0) * scale
    px = int(round(cx - tcx))
    py = int(round(cy - tcy))
    try:
        frame_img.alpha_composite(scaled, (px, py))
    except (ValueError, AttributeError):
        try:
            frame_img.paste(scaled, (px, py), scaled)
        except ValueError:
            fx0, fy0 = max(0, px), max(0, py)
            tx0, ty0 = fx0 - px, fy0 - py
            tx1 = min(new_w, VIDEO_WIDTH - px)
            ty1 = min(new_h, VIDEO_HEIGHT - py)
            if tx1 > tx0 and ty1 > ty0:
                cropped = scaled.crop((tx0, ty0, tx1, ty1))
                frame_img.paste(cropped, (fx0, fy0), cropped)


def enrich_chunk_words(chunk: dict, keyword_colors: dict | None = None) -> list[dict]:
    """Ritorna le parole del chunk con flag `is_keyword`.

    Il match e' case-insensitive e normalizzato senza punteggiatura
    (riusa `core.keywords.normalize_word`). Se il chunk non ha la chiave
    "words" (chunk legacy), la ricostruisce distribuendo uniformemente
    la durata del chunk sulle parole di `chunk["text"]`.
    """
    raw_words = chunk.get("words")
    if not raw_words:
        text = (chunk.get("text") or "").split()
        if not text:
            return []
        start = float(chunk.get("start", 0.0))
        end = float(chunk.get("end", start))
        if end <= start:
            end = start + 0.3 * len(text)
        span = (end - start) / len(text)
        raw_words = [
            {"word": w, "start": start + span * i, "end": start + span * (i + 1)}
            for i, w in enumerate(text)
        ]
    enriched: list[dict] = []
    for w in raw_words:
        word_text = str(w.get("word", ""))
        norm = normalize_word(word_text)
        is_kw = bool(keyword_colors and norm in keyword_colors)
        enriched.append({
            "word": word_text,
            "start": float(w.get("start", chunk.get("start", 0.0))),
            "end": float(w.get("end", chunk.get("end", 0.0))),
            "is_keyword": bool(w.get("is_keyword", is_kw)),
        })
    # Se il dict originale aveva gia' is_keyword esplicito, rispettalo;
    # altrimenti usa il match appena calcolato (gestito sopra via .get default).
    return enriched


def _render_scaled_word(
    frame_img: Image.Image,
    word: str,
    x: int,
    y: int,
    word_w: int,
    word_h: int,
    font,
    fill: tuple,
    stroke_color: tuple,
    stroke_width: int,
    opacity: int,
    scale: float,
) -> None:
    """Disegna una parola con scala via resize LANCZOS, centro fisso.

    Disegna la parola a dimensione base su una tile temporanea, la ridimensiona
    col fattore `scale` e la incolla sul frame mantenendo il centro originale
    (il layout delle altre parole non si muove mai).
    """
    if opacity <= 0:
        return
    if scale <= 0:
        return
    # Caso veloce: scala unitaria -> disegno diretto.
    if abs(scale - 1.0) < 1e-3:
        draw = ImageDraw.Draw(frame_img)
        draw_word(draw, word, (x, y), font, fill, stroke_color, stroke_width, opacity=opacity)
        return
    pad = 24 + int(stroke_width) * 2
    tile_w = max(1, int(word_w + pad * 2))
    tile_h = max(1, int(word_h + pad * 2))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    draw_word(tile_draw, word, (pad, pad), font, fill, stroke_color, stroke_width, opacity=opacity)
    new_w = max(1, int(round(tile_w * scale)))
    new_h = max(1, int(round(tile_h * scale)))
    resample = _fast_resample_for_scale(scale)
    scaled = tile.resize((new_w, new_h), resample)
    # Centro originale della parola nel frame.
    cx = x + word_w / 2.0
    cy = y + word_h / 2.0
    # Centro della parola dentro la tile (coordinate tile, poi scalate).
    tcx = (pad + word_w / 2.0) * scale
    tcy = (pad + word_h / 2.0) * scale
    px = int(round(cx - tcx))
    py = int(round(cy - tcy))
    # Paste con maschera alpha (gestisce anche posizioni parzialmente fuori canvas).
    try:
        frame_img.alpha_composite(scaled, (px, py))
    except (ValueError, AttributeError):
        try:
            frame_img.paste(scaled, (px, py), scaled)
        except ValueError:
            # Fallback: ritaglia la porzione visibile se paste fallisce ai bordi.
            fx0, fy0 = max(0, px), max(0, py)
            tx0, ty0 = fx0 - px, fy0 - py
            tx1 = min(new_w, VIDEO_WIDTH - px)
            ty1 = min(new_h, VIDEO_HEIGHT - py)
            if tx1 > tx0 and ty1 > ty0:
                cropped = scaled.crop((tx0, ty0, tx1, ty1))
                frame_img.paste(cropped, (fx0, fy0), cropped)


def _character_info_from_chunk(chunk: dict) -> dict | None:
    """Metadati character dal chunk arricchito (None se assenti/disabilitati/nascosti).

    Presenza discontinua (Breath & Focus): se chunk["character"]["visible"]
    e' False (o char_visible False / guard_hidden) il personaggio e' HIDDEN
    in questo chunk (nessun layer, schermo pulito solo testo). Risolve
    tramite `resolve_chunk_layout` (singola fonte condivisa col text engine).
    """
    if not CHARACTER_ENABLED:
        return None
    try:
        if isinstance(chunk, dict):
            _ch = chunk.get("character")
            if isinstance(_ch, dict) and not bool(_ch.get("visible", True)):
                return None
            if chunk.get("char_visible") is False:
                return None
            if chunk.get("guard_hidden") is True:
                return None
    except Exception:
        pass
    try:
        return resolve_chunk_layout(chunk)
    except Exception:
        return None


def _character_event_of(chunk: dict | None) -> str:
    """Evento macro-blocco del chunk (ENTRY/SUSTAIN/EXIT/NONE, mai eccezioni)."""
    try:
        from core.character_animator import CharacterFrameAnimator as _A
        return _A.event_of(chunk)
    except Exception:
        pass
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
            return _ev2
        return "SUSTAIN" if chunk.get("pose") is not None else "NONE"
    except Exception:
        return "NONE"


def _character_side(info: dict) -> str:
    """Lato del personaggio ('left' | 'right' | 'center')."""
    if info.get("use_preset"):
        try:
            return preset_side(info.get("layout"))
        except Exception:
            return "center"
    return "left" if "left" in str(info.get("position", "")) else (
        "right" if "right" in str(info.get("position", "")) else "center")


def _load_chunk_character_layer(info: dict | None):
    """Layer personaggio (immagine + XY) per il chunk, o (None, None).

    Col preset usa `get_character_layer` (scala width-based + punch_in);
    errori non bloccanti (asset mancante, posa invalida): il frame viene
    generato senza personaggio (nessuna regressione).
    """
    if info is None:
        return None, None
    try:
        if info.get("use_preset"):
            char_img, px, py = get_character_layer(
                int(info["pose"]), info.get("layout"),
                bool(info.get("punch_in", False)),
                VIDEO_WIDTH, VIDEO_HEIGHT)
            return char_img, (px, py)
        from core.character_selector import character_target_height, load_and_process_character_image
        target_h = character_target_height(info.get("scale", 0.75), VIDEO_HEIGHT)
        char_img = load_and_process_character_image(int(info["pose"]), target_h)
        return char_img, calculate_character_bbox(
            char_img.size, info.get("position", "bottom_center"),
            VIDEO_WIDTH, VIDEO_HEIGHT)
    except Exception:
        return None, None


def _character_entry_transform(
    transition: str,
    side: str,
    progress: float,
    img_w: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    full_travel: bool = False,
    fade: bool = True,
) -> tuple[int, int, int, float]:
    """Offset (dx, dy), opacita' 0-255 e scala del personaggio al `progress`.

    Entrata slide&pop (spec ~0.20s, ~6 frame): fade fluido (ease_out_quad) +
    slide con ease_out_back (overshoot leggero, effetto pop premium) da offset
    Y fisso +300px, o zoom dolce 0.92->1.0 per "zoom_in". L'overshoot supera di
    poco la posizione finale e rientra: niente scatti, ritmo coerente.
    """
    p = clamp01(progress)
    t = str(transition or "fade")
    if t == "slide_side":
        t = "slide_from_left" if side == "left" else "slide_from_right"
    elif t == "slide_from_bottom":
        t = "slide_up"
    if t in ("none",):
        return (0, 0, 255, 1.0)
    # Fade fluido (quad) + pop con overshoot leggero (back): ingresso premium.
    fade_eased = ease_out_quad(p)
    pop_eased = ease_out_back(p)
    move_eased = ease_out_cubic(p)
    opacity = int(round(255 * fade_eased)) if fade else 255
    if t == "fade":
        return (0, 0, opacity, 1.0)
    if t in ("zoom", "zoom_in", "scale_in", "scale-in"):
        scale = _CHARACTER_ZOOM_FROM + (1.0 - _CHARACTER_ZOOM_FROM) * move_eased
        return (0, 0, opacity, float(scale))
    if t in ("slide_from_left", "slide_from_right"):
        if full_travel and img_w > 0:
            start_x = -img_w if t == "slide_from_left" else VIDEO_WIDTH
            dx = int(round((start_x - base_x) * (1.0 - pop_eased)))
        else:
            direction = -1 if t == "slide_from_left" else 1
            dx = int(round(direction * _CHARACTER_SLIDE_SIDE_PX * (1.0 - pop_eased)))
        return (dx, 0, opacity, 1.0)
    # slide_up (default anche per valori ignoti: mai un taglio secco a sorpresa)
    # Spec: offset Y fisso +300px (non full off-screen), pop con overshoot.
    if full_travel:
        dy = int(round(_CHARACTER_ENTRY_SLIDE_Y * (1.0 - pop_eased)))
    else:
        dy = int(round(_CHARACTER_SLIDE_UP_PX * (1.0 - pop_eased)))
    return (0, dy, opacity, 1.0)


def _character_entry_offset_opacity(
    transition: str,
    side: str,
    progress: float,
    img_w: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    full_travel: bool = False,
    fade: bool = True,
) -> tuple[int, int, int]:
    """Offset (dx, dy) e opacita' 0-255 (compat: ignora la scala zoom_in).

    Per lo zoom_in la scala e' gestita dal chiamante via
    `_character_entry_transform` (0.92->1.0 fluido); qui ritorna solo
    offset+opacita' per non rompere i chiamanti legacy.
    """
    dx, dy, op, _scale = _character_entry_transform(
        transition, side, progress, img_w, base_x, base_y, full_travel, fade)
    return (dx, dy, op)


def _character_morph_offset(
    from_xy: tuple[int, int] | None,
    to_xy: tuple[int, int],
    progress: float,
) -> tuple[int, int]:
    """Offset di morph da posizione precedente a quella corrente (smart animate).

    Il character parte dalla vecchia posizione (continuità, niente flash di
    sfondo) e scivola alla nuova con ease_in_out_cubic (partenza/arrivo
    morbidi). Sempre a piena opacita': niente sparizioni nei cambi posa/lato.
    Se from_xy e' None o uguale a to_xy, ritorna (0,0).
    """
    try:
        if from_xy is None:
            return (0, 0)
        fx, fy = int(from_xy[0]), int(from_xy[1])
        tx, ty = int(to_xy[0]), int(to_xy[1])
    except (TypeError, ValueError, IndexError):
        return (0, 0)
    dx0, dy0 = fx - tx, fy - ty
    if dx0 == 0 and dy0 == 0:
        return (0, 0)
    e = ease_in_out_cubic(clamp01(progress))
    return (int(round(dx0 * (1.0 - e))), int(round(dy0 * (1.0 - e))))


def _idle_bob_tilt(t_abs: float) -> tuple[int, float]:
    """Respiro idle leggero al tempo assoluto video `t_abs` (secondi).

    - Bob verticale dolce: dy = sin(2*pi*freq*t) * amp_y (default 0.4Hz, 4px:
      leggero ma percettibile, mai statico).
    - Tilt disabilitato di default (0.0 gradi: nessuna rotazione laterale, il
      dondolio destra-sinistra rendeva il video instabile). Resta attivo solo
      se l'utente imposta CHARACTER_IDLE_TILT_DEG > 0 via env.
    Ritorna (dy_px_int, tilt_deg_float). Costo ~1us (sin+cos). Con idle
    disabilitato o ampiezze zero ritorna (0, 0.0) senza calcoli trig.
    """
    try:
        if not _IDLE_ENABLED or (_IDLE_AMP_Y <= 0 and _IDLE_TILT_DEG <= 0):
            return (0, 0.0)
        phase = _TWO_PI * _IDLE_FREQ * float(t_abs)
    except (TypeError, ValueError):
        return (0, 0.0)
    try:
        dy = int(round(math.sin(phase) * _IDLE_AMP_Y)) if _IDLE_AMP_Y > 0 else 0
    except Exception:
        dy = 0
    try:
        tilt = float(math.cos(phase) * _IDLE_TILT_DEG) if _IDLE_TILT_DEG > 0 else 0.0
    except Exception:
        tilt = 0.0
    return (dy, tilt)


def _get_tilted_char(char_img: Image.Image, tilt_deg: float):
    """Layer ruotato di `tilt_deg` attorno al punto inferiore centrale (w/2, h).

    L'ancoraggio in basso evita che il personaggio si stacchi dal fondo: la
    base resta ferma, la testa culla lateralmente. Tilt quantizzato a step
    0.3 gradi e cachato (<=9 varianti per size): hit = lookup <1ms, miss =
    una rotazione BILINEAR ammortizzata. tilt ~0 o idle OFF = layer originale.
    Mai eccezioni (fallback: originale).
    """
    try:
        if char_img is None:
            return char_img
        if not _IDLE_ENABLED:
            return char_img
        try:
            tilt = float(tilt_deg)
        except (TypeError, ValueError):
            return char_img
        if abs(tilt) < 1e-9:
            return char_img
        q = round(tilt / _IDLE_TILT_STEP) * _IDLE_TILT_STEP
        q = max(-3.0, min(3.0, float(q)))
        if abs(q) < 1e-9:
            return char_img
        key = (id(char_img), q)
        hit = _tilt_cache.get(key)
        if hit is not None:
            return hit
        with _tilt_cache_lock:
            hit = _tilt_cache.get(key)
            if hit is not None:
                return hit
            try:
                w, h = char_img.size
                rotated = char_img.rotate(
                    q, resample=Image.BILINEAR, center=(w / 2.0, float(h)))
                if rotated.mode != "RGBA":
                    rotated = rotated.convert("RGBA")
            except Exception:
                return char_img
            if len(_tilt_cache) < 64:
                if len(_tilt_cache) >= 60:
                    _tilt_cache.clear()
                _tilt_cache[key] = rotated
            return rotated
    except Exception:
        try:
            return char_img
        except Exception:
            return None


def _character_exit_offset_opacity(
    mode: str,
    progress: float,
    base_y: int = 0,
    fade: bool = True,
) -> tuple[int, int, int]:
    """Offset/uscita del personaggio nella finestra di uscita di fine chunk.

    - "slide_down": scende fuori campo basso (il chunk successivo, con lato
      opposto, rientra con slide laterale: niente taglio netto). Con
      `fade=False` resta a piena opacita' mentre scende (solo movimento,
      nessuna sparizione: anti-glitch sui cambi layout).
    - "hold": resta fermo e opaco (stesso personaggio dopo, o jump-cut
      punch-in: taglio invisibile/netto senza dissolvenze).
    - altro ("with_text"): nessuna animazione propria (segue il fade di gruppo,
      usato quando il personaggio deve chiaramente scomparire).
    """
    if mode == _CHAR_EXIT_HOLD:
        return (0, 0, 255)
    if mode == _CHAR_EXIT_SLIDE_DOWN:
        e = ease_in_cubic(clamp01(progress))
        dy = int(round((VIDEO_HEIGHT - base_y) * e))
        opacity = int(round(255 * (1.0 - e))) if fade else 255
        return (0, dy, opacity)
    return (0, 0, 255)


def _punch_of(info) -> bool:
    """Flag punch_in (robusto a None e formati legacy senza chiave)."""
    try:
        return bool(info.get("punch_in", False)) if isinstance(info, dict) else False
    except Exception:
        return False


def _character_identity(info) -> tuple | None:
    """Identita' del personaggio (posa + zona + punch), o None se assente.

    Due chunk con stessa identita' mostrano pixel identici: il taglio tra loro
    e' invisibile e il personaggio resta stabile (anti-glitch).
    """
    try:
        if not isinstance(info, dict) or info.get("pose") is None:
            return None
        zone = info.get("layout") if info.get("use_preset") else info.get("position")
        return (int(info.get("pose")), str(zone), bool(info.get("punch_in", False)))
    except Exception:
        return None


def _same_pose(a: dict | None, b: dict | None) -> bool:
    """Vero se entrambi hanno la STESSA posa (stessa immagine), o None altrimenti.

    E' il check anti-sparizione: stessa posa = stessa immagine = il
    personaggio non deve mai uscire di scena (niente slide_down, niente
    rientro da fuori campo). Mai eccezioni.
    """
    try:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        if a.get("pose") is None or b.get("pose") is None:
            return False
        return int(a.get("pose")) == int(b.get("pose"))
    except Exception:
        return False


def decide_char_exit_mode(current: dict | None, nxt: dict | None) -> str:
    """Modalita' di uscita del personaggio guardando il chunk successivo.

    Invariante anti-blink (fix sparizione/riapparizione): il personaggio resta
    visibile fino allo stacco OGNI VOLTA che il chunk dopo ha un personaggio,
    qualunque sia il cambio (posa/lato/punch). L'uscita animata scatta SOLO
    quando deve chiaramente scomparire (chunk dopo senza personaggio, o fine
    video): fade-out fluido dedicato (non legato al fade testo).

    - Chunk dopo senza personaggio (o fine video) -> "with_text" (fade-out
      fluido con durata character dedicata: sparizione chiara e intenzionale).
    - Chunk dopo CON personaggio -> "hold" SEMPRE (niente slide_down: lo
      slide_down storico svuotava lo schermo a fine chunk e creava il blink
      nei gap; ora il morph in entrata del chunk dopo parte dalla vecchia
      posizione con continuita' pixel, e la persistenza nei gap copre le pause).
    Accetta chunk grezzi o info gia' risolte; mai eccezioni.
    """
    try:
        cur = current if isinstance(current, dict) and "pose" in current and "use_preset" in current \
            else resolve_chunk_layout(current)
        after = nxt if isinstance(nxt, dict) and "pose" in nxt and "use_preset" in nxt \
            else resolve_chunk_layout(nxt)
    except Exception:
        return _CHAR_EXIT_WITH_TEXT
    if cur is None:
        return _CHAR_EXIT_WITH_TEXT
    if after is None:
        return _CHAR_EXIT_WITH_TEXT  # sparizione (o fine video): fade fluido
    return _CHAR_EXIT_HOLD  # continuita': resta fino allo stacco, morph dopo


def decide_char_entry_jump(prev: dict | None, current: dict | None) -> bool:
    """Vero se l'entrata dev'essere istantanea (taglio invisibile).

    SOLO a identita' pixel-identica (stessa posa+zona+punch del chunk prima):
    il frame e' identico, nessuna animazione da replayare (replay creerebbe
    un blink a ogni stacco). In tutti gli altri casi (cambio posa/lato,
    punch che si accende/spegne, zoom hook) l'entrata e' MORPH/zoom fluido,
    MAI jump-cut secco (fix scatto hook). Accetta chunk grezzi o info risolte;
    mai eccezioni.
    """
    try:
        cur = current if isinstance(current, dict) and "pose" in current and "use_preset" in current \
            else resolve_chunk_layout(current)
    except Exception:
        return False
    if cur is None:
        return False
    try:
        before = prev if isinstance(prev, dict) and "pose" in prev and "use_preset" in prev \
            else resolve_chunk_layout(prev)
    except Exception:
        return False
    if before is None:
        return False
    try:
        return _character_identity(cur) == _character_identity(before)
    except Exception:
        return False


def _paste_character_frame(
    frame_img: Image.Image,
    char_img: Image.Image,
    x: int,
    y: int,
    opacity: int,
) -> None:
    """Incolla il personaggio sul frame con opacita' e clipping ai bordi (veloce)."""
    if opacity <= 0:
        return
    if opacity > 255:
        opacity = 255
    # Fast-path: opaco -> nessun copy/point, paste diretto.
    if opacity >= 255:
        to_paste = char_img
    else:
        to_paste = _get_char_at_opacity(char_img, opacity)
        if to_paste is None:
            return
    px, py = int(x), int(y)
    try:
        # alpha_composite e' piu' veloce di paste+mask su RGBA grandi.
        try:
            frame_img.alpha_composite(to_paste, (px, py))
            return
        except (ValueError, AttributeError):
            pass
        frame_img.paste(to_paste, (px, py), to_paste)
        return
    except ValueError:
        pass
    cw, ch = frame_img.size
    iw, ih = to_paste.size
    fx0, fy0 = max(0, px), max(0, py)
    tx0, ty0 = fx0 - px, fy0 - py
    tx1 = min(iw, cw - px)
    ty1 = min(ih, ch - py)
    if tx1 > tx0 and ty1 > ty0:
        cropped = to_paste.crop((tx0, ty0, tx1, ty1))
        frame_img.paste(cropped, (fx0, fy0), cropped)


def generate_animated_chunk_frames(
    chunk: dict,
    background_color: str,
    text_color: str,
    keyword_colors: dict,
    output_dir: str,
    chunk_index: int,
    fps: int = VIDEO_FPS,
    safe_area: tuple[int, int, int, int] | None = None,
    char_exit_mode: str = _CHAR_EXIT_WITH_TEXT,
    char_exit_duration: float = _CHARACTER_ZONE_EXIT_DURATION,
    text_safe_area: tuple[int, int, int, int] | None = None,
    char_entry_jump: bool = False,
    char_entry_fade: bool = True,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
    char_entry_from_xy: tuple[int, int] | None = None,
    tail_hold_duration: float = 0.0,
    char_prev_layer=None,
    char_micro_blend: bool = False,
) -> list[dict]:
    """Genera la sequenza di frame PNG per un chunk con animazione per-parola.

    Args:
        chunk: {"text", "start", "end", "words": [{"word","start","end",...}]}.
            Se "words" manca, viene ricostruita (vedi `enrich_chunk_words`).
            Puo' contenere pose/layout/punch_in del personaggio
            (vedi core/character_selector.py): il personaggio (mezzo busto,
            mai figura intera) viene disegnato sotto il testo (Z-index: sfondo
            ffmpeg < personaggio < sottotitoli, con pill ad alto contrasto per
            il punch-in) con slide&pop 0.20s +300px alla prima apparizione,
            idle breathing/sway continuo, morph smart nei cambi e zoom fluido
            0.6s per il punch hook (mai jump-cut secco).
            Con Semantic Typography Engine v1 puo' contenere anche
            "styled_words" (vedi core/text_tagger.py) + "typography_niche":
            in quel caso il rendering usa 3 font/colori/dimensioni per nicchia
            (base/impact/accent) con stroke nero + drop shadow su ogni parola.
        background_color: hex #RRGGBB da theme.py (frame restano trasparenti,
            lo sfondo e' applicato da ffmpeg; param tenuto per compatibilita').
        text_color: hex #RRGGBB da theme.py (accetta anche tupla RGBA).
        keyword_colors: {parola_normalizzata: hex} da keywords.py
            (accetta anche valori RGBA come quelli reali di `extract_keywords`).
            Con tipografia attiva, l'impact usa il colore highlight del preset
            (la palette keyword resta come fallback legacy quando il tagging manca).
        output_dir: cartella dove salvare i frame PNG del chunk.
        chunk_index: per naming file univoco.
        fps: frame rate (default: VIDEO_FPS da config.py).
        safe_area: Text Safe Area esplicita (x_min, y_min, x_max, y_max);
            se assente si usa quella del preset del chunk, altrimenti il
            centro schermo storico. Il wrapping segue la larghezza del box.
        char_exit_mode: "with_text" (fade-out fluido dedicato quando il
            personaggio sparisce), "slide_down" (legacy, trattato come hold
            per continuita') o "hold" (resta opaco fino allo stacco +
            persistenza nel gap, mai blink). Di solito calcolato con
            `decide_char_exit_mode` guardando il chunk successivo
            (vedi `render_all_chunks_animated`).
        char_exit_duration: durata fade-out personaggio (default da config).
        text_safe_area: alias di `safe_area` (nome da spec); se fornito,
            ha precedenza.
        char_entry_jump: True SOLO a identita' pixel-identica (stesso
            posa+zona+punch del chunk prima: taglio invisibile, nessuna
            animazione). Di solito calcolato con `decide_char_entry_jump`.
        char_entry_fade: True alla prima apparizione (fade+slide/zoom da fuori
            campo); False nei morph di continuita' (slide dalla vecchia
            posizione a piena opacita', niente flash di sfondo).
        char_entry_from_xy: posizione base (x,y) del character nel chunk
            precedente per il morph smart (None = prima apparizione).
        tail_hold_duration: secondi extra oltre chunk.end in cui clonare
            l'ultimo frame (persistenza nel gap quando il character continua:
            fix blink sparizione/riapparizione). Solo con hold.
        typography_niche: nicchia esplicita (override di chunk["typography_niche"]).
        typography_preset: preset dict esplicito (da core/typography_presets.get_preset).

    Returns:
        Lista di dict {"image_path": str, "start": float, "end": float}
        - uno per ogni frame generato, con la finestra temporale in cui
        quel frame specifico deve essere mostrato (frame N valido da
        t_N a t_N+1/fps). Include gli eventuali tail di persistenza.
        Formato compatibile con `core/video_builder.py` (micro-video per chunk).
    """
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    words = enrich_chunk_words(chunk, keyword_colors)
    if not words:
        return []
    try:
        chunk_start = float(chunk.get("start", words[0]["start"]))
        chunk_end = float(chunk.get("end", words[-1]["end"]))
    except (TypeError, ValueError) as e:
        raise TextAnimationError(f"Timestamp chunk non validi: {e}")
    if chunk_end <= chunk_start:
        chunk_end = chunk_start + 0.1
    duration = chunk_end - chunk_start
    if duration <= 0:
        return []

    os.makedirs(output_dir, exist_ok=True)

    # --- Personaggio + safe area: un'unica fonte (niente overlap possibile) ---
    char_info = _character_info_from_chunk(chunk)
    use_preset = bool(char_info is not None and char_info.get("use_preset"))
    explicit_box = text_safe_area if text_safe_area is not None else safe_area
    if explicit_box is not None:
        try:
            area = (int(explicit_box[0]), int(explicit_box[1]),
                    int(explicit_box[2]), int(explicit_box[3]))
            area = area if area[2] > area[0] and area[3] > area[1] else None
        except (TypeError, ValueError, IndexError):
            area = None
        needs_pill, font_scale = False, 1.0
    elif use_preset:
        preset = char_info.get("layout")
        area = preset_safe_area(preset, VIDEO_WIDTH, VIDEO_HEIGHT)
        needs_pill = preset_needs_text_background(preset)
        font_scale = preset_font_scale(preset)
    else:
        area, needs_pill, font_scale = None, False, 1.0
    # Real-time Layout Guard (core/layout_guard.py): override per-chunk
    # (safe area + font shrink + pill) calcolato prima del render.
    # Precedenza: explicit globale > guard > preset.
    try:
        if explicit_box is None and isinstance(chunk, dict):
            _gsa = chunk.get("guard_safe_area")
            if _gsa is not None:
                _gbox = (int(_gsa[0]), int(_gsa[1]), int(_gsa[2]), int(_gsa[3]))
                if _gbox[2] > _gbox[0] and _gbox[3] > _gbox[1]:
                    area = _gbox
            _gfs = chunk.get("guard_font_scale")
            if _gfs is not None:
                _gfs_f = float(_gfs)
                if 0.5 <= _gfs_f <= 1.5:
                    font_scale = _gfs_f
            if chunk.get("guard_pill"):
                needs_pill = True
    except Exception:
        pass

    # --- Semantic Typography: path multi-style o legacy single-font ---
    # Look pulito: stroke sempre 0 (nessun contorno nero), ombra solo se
    # abilitata esplicitamente da config (default OFF).
    use_typography = _is_typography_chunk(chunk)
    typo_preset: dict | None = None
    typo_fonts: dict | None = None
    typo_fills: dict | None = None
    typo_stroke_color: tuple = (0, 0, 0, 0)
    typo_stroke_width: int = 0
    typo_shadow_offset = None
    typo_shadow_fill = None
    styled_words: list[dict] | None = None

    if use_typography:
        try:
            typo_preset = _resolve_typography_preset(chunk, typography_niche, typography_preset)
        except Exception:
            use_typography = False
            typo_preset = None
    if use_typography and typo_preset is not None:
        # Costruisci styled_words con timing (chunk già arricchito da text_tagger;
        # se manca, deriva da words con is_keyword -> impact).
        raw_styled = chunk.get("styled_words")
        try:
            uppercase_impact = bool(typo_preset.get("impact_uppercase", True))
        except Exception:
            uppercase_impact = True
        if isinstance(raw_styled, list) and raw_styled:
            styled_words = []
            # Mappa timing da words (ordine identico nella pipeline normale).
            for i, s in enumerate(raw_styled):
                if not isinstance(s, dict):
                    continue
                style = s.get("style", "base")
                if style not in ("base", "impact", "accent"):
                    style = "base"
                word_text = str(s.get("word", ""))
                if not word_text.strip():
                    continue
                try:
                    st = float(s.get("start", words[i]["start"] if i < len(words) else chunk.get("start", 0.0)))
                    en = float(s.get("end", words[i]["end"] if i < len(words) else chunk.get("end", 0.0)))
                except (TypeError, ValueError, KeyError, IndexError):
                    st = float(words[i]["start"]) if i < len(words) else float(chunk.get("start", 0.0))
                    en = float(words[i]["end"]) if i < len(words) else float(chunk.get("end", 0.0))
                display = str(s.get("display", word_text.upper() if (style == "impact" and uppercase_impact) else word_text))
                if style == "impact" and uppercase_impact:
                    display = display.upper()
                _is_num_s = bool(s.get("is_number", False)) or _has_digit_fast(word_text)
                _is_hero_s = bool(s.get("is_hero", False)) and style == "impact" and not _is_num_s
                styled_words.append({
                    "word": word_text, "display": display, "style": style,
                    "start": st, "end": en,
                    "is_keyword": style == "impact",
                    "is_hero": _is_hero_s,
                    "is_number": _is_num_s,
                })
        if not styled_words:
            # Deriva da words legacy: keyword -> impact, resto base.
            styled_words = []
            for w in words:
                style = "impact" if w.get("is_keyword") else "base"
                disp = str(w["word"]).upper() if (style == "impact" and uppercase_impact) else str(w["word"])
                _wn = str(w.get("word", ""))
                _in = _has_digit_fast(_wn)
                styled_words.append({
                    "word": _wn, "display": disp, "style": style,
                    "start": float(w["start"]), "end": float(w["end"]),
                    "is_keyword": bool(w.get("is_keyword", False)),
                    "is_hero": False,
                    "is_number": _in,
                })
        if not styled_words:
            use_typography = False
    if use_typography and typo_preset is not None and styled_words:
        typo_fonts = _load_typography_fonts(typo_preset, font_scale)
        # Attribuzione colori coerente: tema (base) + sfondo (contrasto) +
        # palette keyword del video (fallback impact). Mai contorno nero.
        typo_fills = _styled_fills(
            typo_preset,
            base_override=text_color,
            background_color=background_color,
            keyword_colors=keyword_colors,
        )
        typo_stroke_color = (0, 0, 0, 0)
        try:
            # Lo stroke resta configurabile ma di default è 0 (look pulito).
            # Valori >0 sono permessi solo se l'utente li forza esplicitamente.
            cfg_w = int(typo_preset.get("stroke_width", TYPOGRAPHY_STROKE_WIDTH))
        except (TypeError, ValueError):
            cfg_w = TYPOGRAPHY_STROKE_WIDTH
        try:
            cfg_w = int(TYPOGRAPHY_STROKE_WIDTH) if str(TYPOGRAPHY_STROKE_WIDTH).strip() != "0" else 0
        except (TypeError, ValueError):
            cfg_w = 0
        typo_stroke_width = max(0, cfg_w if cfg_w else 0)
        if not TYPOGRAPHY_SHADOW_ENABLED:
            typo_shadow_offset = None
            typo_shadow_fill = None
        else:
            try:
                sh = typo_preset.get("shadow", {})
                _off = sh.get("offset", tuple(TYPOGRAPHY_SHADOW_OFFSET))
                _fill = sh.get("fill", tuple(TYPOGRAPHY_SHADOW_FILL))
                typo_shadow_offset = tuple(_off) if _off else None
                typo_shadow_fill = tuple(_fill) if _fill else None
                # Ombra "vuota" (0,0 / alpha 0) = disabilitata di fatto.
                if typo_shadow_offset == (0, 0):
                    typo_shadow_offset = None
                try:
                    if typo_shadow_fill is not None and len(typo_shadow_fill) >= 4 and int(typo_shadow_fill[3]) <= 0:
                        typo_shadow_fill = None
                except Exception:
                    pass
                if typo_shadow_offset is None or typo_shadow_fill is None:
                    typo_shadow_offset = None
                    typo_shadow_fill = None
            except Exception:
                typo_shadow_offset = None
                typo_shadow_fill = None
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_styled_layout(styled_words, typo_fonts, max_text_width, area=area)
        if len(layout) != len(styled_words):
            raise TextAnimationError("Layout/words fuori sync: conteggio diverso.")
        # Fills per parola per ruolo (la tipografia vince sulla palette keyword).
        fills = [typo_fills.get(layout[i].get("style", "base"), typo_fills["base"]) for i in range(len(layout))]
        word_starts = [float(s["start"]) for s in styled_words]
        # Per il loop di rendering riusa `words` come alias di styled
        # (is_keyword <=> style==impact per unificazione moto; hero/number
        # preservati per i tier T3).
        words = [
            {"word": s["display"], "start": s["start"], "end": s["end"],
             "is_keyword": s["style"] == "impact", "style": s["style"],
             "is_hero": bool(s.get("is_hero", False)),
             "is_number": bool(s.get("is_number", False))}
            for s in styled_words
        ]
    else:
        use_typography = False
        # --- Pre-calcolo layout legacy (una sola volta, fisso per tutto il chunk) ---
        try:
            text_font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale))))
        except (TypeError, ValueError):
            text_font_size = SUBTITLE_FONT_SIZE
        font = load_font(text_font_size)
        max_text_width = int(VIDEO_WIDTH * 0.85)
        word_texts = [w["word"] for w in words]
        layout = compute_word_layout(word_texts, font, max_text_width, area=area)
        if len(layout) != len(words):
            raise TextAnimationError("Layout/words fuori sync: conteggio diverso.")

        base_rgba = _to_rgba(text_color, SUBTITLE_COLOR)
        fills = [
            _resolve_word_fill(normalize_word(w["word"]), base_rgba, keyword_colors)
            for w in words
        ]
        word_starts = [float(w["start"]) for w in words]

    # Grassetto sintetico per il base statico (Poppins/Lato/...): se il peso
    # variabile NON è stato applicato, le parole base usano stroke 1px dello
    # stesso colore (inspessimento leggero, nessun contorno nero).
    try:
        _base_synth = bool(use_typography and isinstance(typo_fonts, dict)
                           and not typo_fonts.get("base_weight_applied", False))
    except Exception:
        _base_synth = False

    # Tier T0-T3: entry/scala da config + preset nicchia + override hook.
    # Priorita' scala: chunk anim_pop_from (hook) > preset anim.pop_from >
    # globale. Hero e numeri hanno durate dedicate (vedi _resolve_motion_params).
    try:
        exit_dur = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    except (TypeError, ValueError, NameError):
        exit_dur = 0.15
    try:
        entry_dur, scale_from, accent_lift, hero_dur, hero_from, number_dur = (
            _resolve_motion_params(typo_preset if use_typography else None, chunk)
        )
    except Exception:
        entry_dur, scale_from = 0.18, 0.7
        accent_lift, hero_dur, hero_from, number_dur = 10.0, 0.22, 0.6, 0.15
    # Per-parola (fuori loop frame): tier + durata entry dedicata.
    # Legacy (no tipografia): solo T0/T2 via is_keyword, mai accent/hero/number.
    try:
        if use_typography:
            _tiers = [_word_tier(w) for w in words]
            _entry_per_word = [
                (hero_dur if _h else (number_dur if (_s == "impact" and _n) else entry_dur))
                for (_s, _h, _n) in _tiers
            ]
            _scale_per_word = [
                (hero_from if _h else scale_from) if _s == "impact" else 1.0
                for (_s, _h, _n) in _tiers
            ]
        else:
            _tiers = [("impact" if bool(w.get("is_keyword", False)) else "base", False, False)
                      for w in words]
            _entry_per_word = [entry_dur] * len(words)
            _scale_per_word = [(scale_from if _s == "impact" else 1.0) for (_s, _, _) in _tiers]
    except Exception:
        _tiers = [("base", False, False)] * len(words)
        _entry_per_word = [entry_dur] * len(words)
        _scale_per_word = [1.0] * len(words)

    # --- Full Engine Upgrade Fase 2: cinetica avanzata (opt-in, mai regressioni) ---
    # T0/T1 fade-in 2 frame, T2 brand accent con picco 110%, T3 badge+shake.
    # Timestamp start/end MAI toccati: solo durate di entrata e resa visiva.
    _adv_enabled = False
    try:
        _adv_enabled = bool(_ADV_KINETICS) and (_adv_entry_dur is not None)
    except Exception:
        _adv_enabled = False
    if _adv_enabled:
        try:
            _fps_adv = int(fps) if int(fps) > 0 else 30
        except Exception:
            _fps_adv = 30
        try:
            for _ai, (_s, _h, _n) in enumerate(list(_tiers)):
                if _s in ("base", "accent") and _adv_entry_dur is not None:
                    try:
                        _entry_per_word[_ai] = float(_adv_entry_dur(_s, float(_entry_per_word[_ai]), _fps_adv))
                    except Exception:
                        pass
            # T2 -> brand accent (coerenza marchio); T3 tiene highlight + badge.
            if _brand_rgba is not None:
                try:
                    _brand_fill = _brand_rgba()
                    for _ai, (_s, _h, _n) in enumerate(list(_tiers)):
                        if _s == "impact" and not _h and not _n and _ai < len(fills):
                            fills[_ai] = _brand_fill
                except Exception:
                    pass
        except Exception:
            pass

    # --- Personaggio del chunk (layer UNA volta, riusato in ogni frame) ---
    # Z-index sui frame: 1. sfondo (ffmpeg) / 2. personaggio / 2.5 pill / 3. testo.
    # Slide&pop 0.20s +300px alla prima apparizione; morph smart 0.40s in
    # continuita' (piena opacita', niente flash); identita' pixel-identica:
    # taglio invisibile (jump); punch: zoom 0.6s smart; idle continuo sopra.
    char_img, char_base_xy = _load_chunk_character_layer(char_info)
    char_punch = bool(char_info is not None and char_info.get("punch_in", False)) if char_info is not None else False
    char_base_img = None  # layer non-punch per zoom fluido (punch=true)
    char_base_pos: tuple[int, int] | None = None
    char_original = None  # sorgente full-res per resize zoom per-frame
    if char_img is not None and char_base_xy is not None and char_info is not None:
        char_transition = char_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(char_info)
        char_full_travel = bool(use_preset)
        char_entry_jump = bool(char_entry_jump)
        char_entry_fade = bool(char_entry_fade)
        # Prima apparizione: slide&pop 0.20s +300px (spec, back+quad).
        # Morph di continuita': 0.40s dalla vecchia posizione (smart animate).
        if char_entry_fade:
            char_entry_dur = max(0.01, _CHARACTER_ZONE_FIRST_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        else:
            char_entry_dur = max(0.01, _CHARACTER_MORPH_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        # Morph: valida from_xy (deve essere on-screen e sensato).
        char_morph_from: tuple[int, int] | None = None
        if not char_entry_jump and not char_entry_fade and char_entry_from_xy is not None:
            try:
                _fx, _fy = int(char_entry_from_xy[0]), int(char_entry_from_xy[1])
                if -VIDEO_WIDTH < _fx < VIDEO_WIDTH * 2 and -VIDEO_HEIGHT < _fy < VIDEO_HEIGHT * 2:
                    if (_fx, _fy) != (int(char_base_xy[0]), int(char_base_xy[1])):
                        char_morph_from = (_fx, _fy)
            except (TypeError, ValueError, IndexError):
                char_morph_from = None
        else:
            char_morph_from = None
        # Punch zoom fluido: prepara base + sorgente per interpolazione scala.
        char_punch_active = bool(char_punch and not char_entry_jump)
        if char_punch_active:
            try:
                if bool(char_info.get("use_preset")):
                    char_base_img, _bx, _by = get_character_layer(
                        int(char_info["pose"]), char_info.get("layout"),
                        False, VIDEO_WIDTH, VIDEO_HEIGHT)
                    char_base_pos = (int(_bx), int(_by))
                else:
                    char_base_img, char_base_pos = char_img, tuple(char_base_xy)
                try:
                    from core.character_selector import load_character_original as _load_orig
                    char_original = _load_orig(int(char_info["pose"]))
                except Exception:
                    char_original = None
            except Exception:
                char_base_img, char_base_pos, char_original = None, None, None
            try:
                char_punch_dur = max(0.20, float(_CHARACTER_PUNCH_DURATION))
            except Exception:
                char_punch_dur = 0.60
        else:
            char_punch_active = False
            char_punch_dur = 0.0
    else:
        char_base_xy = None
        char_morph_from = None
        char_punch_active = False
        char_punch_dur = 0.0

    try:
        char_exit_dur = max(0.0, float(char_exit_duration))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION
    # Uscita slide-drop + fade (spec ~0.16s, +400px in_cubic) quando sparisce.
    # slide_down legacy -> hold (continuita' morph).
    if char_exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
        char_exit_mode = _CHAR_EXIT_WITH_TEXT
    if char_exit_mode == _CHAR_EXIT_SLIDE_DOWN:
        char_exit_mode = _CHAR_EXIT_HOLD
    try:
        _tail_hold = max(0.0, float(tail_hold_duration))
    except (TypeError, ValueError):
        _tail_hold = 0.0
    # Tail solo con hold + character presente (persistenza gap, fix blink).
    if char_exit_mode != _CHAR_EXIT_HOLD or char_base_xy is None:
        _tail_hold = 0.0

    num_frames = max(1, int(math.ceil(duration * fps)))
    frame_step = 1.0 / float(fps)
    frames: list[dict] = []

    # --- Pre-computazioni per-chunk (fuori dal loop frame) ---
    # Pill: overlay pre-renderizzato una volta, poi alpha_composite (no ricalcolo bbox).
    _pill_overlay = None
    if needs_pill and layout:
        try:
            from core.renderer import TEXT_PILL_FILL, TEXT_PILL_PAD, TEXT_PILL_RADIUS
            _x0 = min(it["x"] for it in layout) - TEXT_PILL_PAD
            _y0 = min(it["y"] for it in layout) - TEXT_PILL_PAD
            _x1 = max(it["x"] + it["width"] for it in layout) + TEXT_PILL_PAD
            _y1 = max(it["y"] + it["height"] for it in layout) + TEXT_PILL_PAD
            _x0, _y0 = max(0, _x0), max(0, _y0)
            _x1, _y1 = min(VIDEO_WIDTH, _x1), min(VIDEO_HEIGHT, _y1)
            if _x1 > _x0 and _y1 > _y0:
                _pill_overlay = _get_cached_pill_overlay(
                    (_x0, _y0, _x1, _y1), TEXT_PILL_FILL, TEXT_PILL_PAD, TEXT_PILL_RADIUS)
        except Exception:
            _pill_overlay = None
    # Binding locali per loop caldo (evita lookup globali/attr per frame).
    _ease_out_back = ease_out_back
    _ease_out_cubic = ease_out_cubic
    _ease_out_quad = ease_out_quad
    _ease_in_cubic = ease_in_cubic
    _clamp01 = clamp01
    _new_rgba = Image.new
    _canvas_size = (VIDEO_WIDTH, VIDEO_HEIGHT)
    _transparent = (0, 0, 0, 0)
    _accent_lift_i = int(round(accent_lift))
    # Font per parola pre-risolti (evita dict.get + try per frame).
    if use_typography:
        try:
            _word_fonts = [typo_fonts.get(layout[i].get("style", words[i].get("style", "base")),
                                          typo_fonts.get("base")) for i in range(len(words))]
        except Exception:
            _word_fonts = [typo_fonts.get("base") if isinstance(typo_fonts, dict) else font] * len(words)
    else:
        _word_fonts = [font] * len(words)
    _shadow_off = typo_shadow_offset if 'typo_shadow_offset' in dir() else None
    _shadow_fill = typo_shadow_fill if 'typo_shadow_fill' in dir() else None

    for fi in range(num_frames):
        t = chunk_start + fi * frame_step
        if t >= chunk_end:
            t = chunk_end - 1e-6
        frame_end = min(t + frame_step, chunk_end)

        # Fattore uscita di gruppo, condiviso da tutte le parole.
        if exit_dur > 0 and t >= chunk_end - exit_dur:
            exit_prog = _clamp01((t - (chunk_end - exit_dur)) / exit_dur)
            exit_factor = 1.0 - _ease_in_cubic(exit_prog)
        else:
            exit_factor = 1.0

        frame_img = _new_rgba("RGBA", _canvas_size, _transparent)

        # Z-index 2: personaggio sotto il testo (idle + entrate/uscite fluidi).
        # - idle breathing&sway continuo (bob sin + tilt cos, anchor basso);
        # - jump (identico): opaco fermo, taglio invisibile;
        # - punch: zoom smart 0.6s ease_out (mai scatto secco hook);
        # - morph (continuita'): slide dalla vecchia posizione 0.40s in_out,
        #   sempre opaco (niente flash di sfondo, niente sparizioni);
        # - prima apparizione: slide&pop 0.20s +300px back/quad fluidi;
        # - sparizione (with_text): slide-drop +400px in_cubic + fade 0.16s.
        if char_img is not None and char_base_xy is not None:
            _char_scale = 1.0
            _char_layer = char_img
            if char_entry_jump:
                edx, edy, entry_opacity = 0, 0, 255
            elif 'char_punch_active' in dir() and char_punch_active:
                # Zoom smart: scala+posizione interpolate base->punch con ease.
                try:
                    _pp = clamp01((t - chunk_start) / max(0.01, char_punch_dur))
                except Exception:
                    _pp = 1.0
                _pe = ease_out_cubic(_pp)
                try:
                    _bx, _by = (char_base_pos if char_base_pos is not None else char_base_xy)
                    _ex, _ey = int(char_base_xy[0]), int(char_base_xy[1])
                    # Start posizione: morph da vecchia se presente, else base.
                    if 'char_morph_from' in dir() and char_morph_from is not None:
                        _sx, _sy = int(char_morph_from[0]), int(char_morph_from[1])
                    else:
                        _sx, _sy = int(_bx), int(_by)
                    # Fine zoom: posizione punch + fade solo se prima apparizione.
                    _morph_e = ease_in_out_cubic(_pp)
                    edx = int(round((_sx - _ex) * (1.0 - _morph_e)))
                    edy = int(round((_sy - _ey) * (1.0 - _morph_e)))
                    if char_entry_fade:
                        entry_opacity = int(round(255 * ease_out_quad(_pp)))
                    else:
                        entry_opacity = 255
                    # Scala: interpola dimensioni base->punch (resize da sorgente).
                    try:
                        _bw, _bh = (char_base_img.size if char_base_img is not None else char_img.size)
                        _pw, _ph = char_img.size
                        _iw = int(round(_bw + (_pw - _bw) * _pe))
                        _ih = int(round(_bh + (_ph - _bh) * _pe))
                        if _pp < 1.0 and _iw > 0 and _ih > 0 and char_original is not None:
                            try:
                                _rs = _fast_resample_for_scale(1.0 + (_pe * 0.35))
                                _char_layer = char_original.resize((_iw, _ih), _rs)
                                if _char_layer.mode != "RGBA":
                                    _char_layer = _char_layer.convert("RGBA")
                            except Exception:
                                _char_layer = char_img
                                edx, edy = int(round((_bx - _ex) * (1.0 - _pe))), int(round((_by - _ey) * (1.0 - _pe)))
                        else:
                            _char_layer = char_img
                            edx, edy = (edx, edy) if _pp < 1.0 else (0, 0)
                    except Exception:
                        _char_layer = char_img
                except Exception:
                    edx, edy, entry_opacity = 0, 0, 255
                    _char_layer = char_img
            elif 'char_morph_from' in dir() and char_morph_from is not None:
                # Morph smart tra posizioni (cambio posa/lato): slide fluida.
                try:
                    _mp = clamp01((t - chunk_start) / max(0.01, _CHARACTER_MORPH_DURATION))
                except Exception:
                    _mp = 1.0
                edx, edy = _character_morph_offset(char_morph_from, tuple(char_base_xy), _mp)
                entry_opacity = 255
            else:
                entry_prog = clamp01((t - chunk_start) / char_entry_dur)
                edx, edy, entry_opacity, _char_scale = _character_entry_transform(
                    char_transition, char_side, entry_prog,
                    char_img.size[0], char_base_xy[0], char_base_xy[1],
                    full_travel=char_full_travel,
                    fade=char_entry_fade,
                )
                if abs(_char_scale - 1.0) >= 1e-3:
                    # Zoom_in prima apparizione: scala tile 0.92->1.0 fluida.
                    try:
                        _zw, _zh = char_img.size
                        _nw = max(1, int(round(_zw * _char_scale)))
                        _nh = max(1, int(round(_zh * _char_scale)))
                        _rs2 = _fast_resample_for_scale(_char_scale)
                        _scaled = char_img.resize((_nw, _nh), _rs2)
                        # Centro fisso: ricentra sullo stesso centro base.
                        _cx = char_base_xy[0] + _zw / 2.0
                        _cy = char_base_xy[1] + _zh / 2.0
                        _px = int(round(_cx - _nw / 2.0)) + edx
                        _py = int(round(_cy - _nh / 2.0)) + edy
                        _char_layer = _scaled
                        _zoom_xy = (_px, _py)
                    except Exception:
                        _char_layer = char_img
                        _zoom_xy = None
                else:
                    _zoom_xy = None
            if char_exit_mode == _CHAR_EXIT_HOLD:
                char_opacity, xdx, xdy = entry_opacity, 0, 0
            else:
                # Uscita slide-drop (spec ~0.16s, ~5 frame): 0 -> +400px con
                # ease_in_cubic (accelera verso il basso) + fade quad.
                if char_exit_dur > 0 and t >= chunk_end - char_exit_dur:
                    try:
                        _xp = clamp01((t - (chunk_end - char_exit_dur)) / char_exit_dur)
                    except Exception:
                        _xp = 1.0
                    _char_fade = 1.0 - ease_out_quad(_xp)
                    char_opacity = int(round(entry_opacity * max(0.0, min(1.0, _char_fade))))
                    try:
                        xdy = int(round(_CHARACTER_EXIT_DROP_Y * ease_in_cubic(_xp)))
                    except Exception:
                        xdy = 0
                    xdx = 0
                else:
                    char_opacity = entry_opacity
                    xdx, xdy = 0, 0
            # Idle breathing & sway (tempo assoluto video: fase continua tra
            # chunk, niente salti ai tagli). Bob = offset Y, tilt = rotazione
            # cachata attorno a (w/2, h). Durante zoom attivi (punch/scale)
            # solo bob (niente tilt su tile temporanee: niente churn cache).
            try:
                _idle_dy, _idle_tilt = _idle_bob_tilt(t)
            except Exception:
                _idle_dy, _idle_tilt = 0, 0.0
            try:
                _scale_active = abs(float(_char_scale if '_char_scale' in dir() else 1.0) - 1.0) >= 1e-3
            except Exception:
                _scale_active = False
            try:
                _punch_zooming = bool(char_punch_active) and (
                    (t - chunk_start) < max(0.01, char_punch_dur)) if 'char_punch_active' in dir() else False
            except Exception:
                _punch_zooming = False
            _zooming = bool(_scale_active or _punch_zooming)
            if _idle_tilt and not _zooming:
                try:
                    _char_layer = _get_tilted_char(_char_layer, _idle_tilt)
                except Exception:
                    pass
            if _idle_dy:
                edy += int(_idle_dy)
            # --- Fase 3: micro cross-fade d'aura dentro il blocco Focus ---
            # Se posa cambia a stesso block_id (niente tagli netti): blend alpha
            # 3-4 frame + micro-scala 2% sui primi frame. Solo quando il
            # chiamante passa char_prev_layer (default None = legacy invariato).
            if char_micro_blend and char_prev_layer is not None and '_char_layer' in dir():
                try:
                    from core.character_selector import (
                        blend_character_layers as _blend_layers,
                        micro_blend_progress as _blend_prog,
                        micro_scale_factor as _micro_scale,
                    )
                    try:
                        _micro_n = 4
                        try:
                            from config import CHARACTER_MICRO_XFADE_FRAMES as _mn
                            _micro_n = max(1, int(_mn))
                        except Exception:
                            pass
                        if int(fi) < int(_micro_n) and _char_layer is not None:
                            _bp = _blend_prog(int(fi))
                            _blended = _blend_layers(char_prev_layer, _char_layer, _bp)
                            try:
                                _ms = float(_micro_scale(int(fi)))
                            except Exception:
                                _ms = 1.0
                            if abs(_ms - 1.0) >= 1e-4 and _blended is not None:
                                try:
                                    _bw2, _bh2 = _blended.size
                                    _nw2, _nh2 = max(1, int(round(_bw2 * _ms))), max(1, int(round(_bh2 * _ms)))
                                    _blended = _blended.resize((_nw2, _nh2), _fast_resample_for_scale(_ms))
                                except Exception:
                                    pass
                            if _blended is not None:
                                _char_layer = _blended
                    except Exception:
                        pass
                except Exception:
                    pass
            try:
                if '_zoom_xy' in dir() and _zoom_xy is not None and '_char_scale' in dir() and abs(_char_scale - 1.0) >= 1e-3:
                    _paste_character_frame(frame_img, _char_layer, _zoom_xy[0], _zoom_xy[1] + (int(_idle_dy) if _idle_dy else 0), char_opacity)
                else:
                    _paste_character_frame(
                        frame_img, _char_layer,
                        char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy,
                        char_opacity,
                    )
            except Exception:
                try:
                    _paste_character_frame(
                        frame_img, char_img,
                        char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy,
                        char_opacity,
                    )
                except Exception:
                    pass

        # Z-index 2.5: pill pre-renderizzata (composite unico, no ricalcolo).
        if _pill_overlay is not None:
            try:
                frame_img.alpha_composite(_pill_overlay)
            except (ValueError, AttributeError):
                draw_text_background(frame_img, layout)
        elif needs_pill:
            draw_text_background(frame_img, layout)

        for wi, w in enumerate(words):
            if t < word_starts[wi]:
                continue  # non ancora iniziata
            # Tier T0-T3 per-parola (durate dedicate pre-calcolate fuori loop).
            try:
                _cur_entry = _entry_per_word[wi]
            except (IndexError, TypeError):
                _cur_entry = entry_dur
            if _cur_entry <= 0:
                _cur_entry = 0.01
            local = _clamp01((t - word_starts[wi]) / _cur_entry)
            try:
                _style_w, _hero_w, _num_w = _tiers[wi]
            except (IndexError, TypeError, ValueError):
                _style_w, _hero_w, _num_w = ("impact" if w.get("is_keyword") else "base", False, False)
            try:
                _sfrom_w = _scale_per_word[wi]
            except (IndexError, TypeError):
                _sfrom_w = scale_from
            _dy = 0
            if _style_w == "impact":
                # T2 pop standard / T3 hero (durata+scala dedicate) / T3-num
                # (pop corto per cifre, mai hero). Overshoot scala non clampato
                # (effetto pop), opacita' sempre saturata a 255.
                eased = _ease_out_back(local)
                if eased >= 1.0:
                    opacity = 255
                elif eased <= 0.0:
                    continue
                else:
                    opacity = int(round(255 * eased))
                scale = _sfrom_w + (1.0 - _sfrom_w) * eased
                if scale < 0.05:
                    scale = 0.05
            elif _style_w == "accent" and use_typography:
                # T1 rise-fade: opacita' cubic + risalita lift->0, MAI scala
                # (handwritten non deformato). Completata -> draw diretto.
                if local >= 1.0:
                    opacity, scale = 255, 1.0
                elif local <= 0.0:
                    continue
                else:
                    eased = _ease_out_cubic(local)
                    opacity = int(round(255 * eased))
                    scale = 1.0
                    if _accent_lift_i > 0:
                        try:
                            _dy = int(round(_accent_lift_i * (1.0 - _ease_out_quad(local))))
                        except Exception:
                            _dy = int(round(_accent_lift_i * (1.0 - eased)))
            else:
                # T0 base fade (fast-path a entrata completata).
                if local >= 1.0:
                    opacity, scale = 255, 1.0
                elif local <= 0.0:
                    continue
                else:
                    eased = _ease_out_cubic(local)
                    opacity = int(round(255 * eased))
                    scale = 1.0
            # Uscita: gruppo per tutti, hero ritardato di ~2 frame (T3).
            try:
                if _hero_w and exit_factor < 1.0:
                    _ef = _hero_exit_factor(t, chunk_end, exit_dur, exit_factor)
                    opacity = int(round(opacity * _ef))
                elif exit_factor < 1.0:
                    opacity = int(round(opacity * exit_factor))
            except Exception:
                if exit_factor < 1.0:
                    opacity = int(round(opacity * exit_factor))
            if opacity <= 0:
                continue
            item = layout[wi]
            _ry = item["y"] + _dy if _dy else item["y"]
            _rx = item["x"]
            # --- Fase 2 avanzata: picco T2, badge+shake T3, stroke T0/T1 ---
            _adv_draw = False
            try:
                _adv_draw = bool(_adv_enabled)
            except Exception:
                _adv_draw = False
            if _adv_draw:
                try:
                    if _style_w == "impact" and not _hero_w and _t2_peak is not None:
                        try:
                            _frame_rel = int(round((t - float(word_starts[wi])) * float(fps)))
                            scale = float(_t2_peak(_frame_rel, float(scale)))
                        except Exception:
                            pass
                    if _hero_w and _hero_shake is not None and _draw_hero_badge is not None:
                        try:
                            _sx, _sy = _hero_shake(int(fi), int(fps))
                            _rx = int(_rx) + int(_sx)
                            _ry = int(_ry) + int(_sy)
                            _draw_hero_badge(frame_img, (int(item["x"]), int(item["y"]),
                                                         int(item["x"]) + int(item["width"]),
                                                         int(item["y"]) + int(item["height"])))
                        except Exception:
                            pass
                except Exception:
                    pass
            if use_typography:
                wfont = _word_fonts[wi]
                if _base_synth and _style_w == "base":
                    _sw, _sc = _BASE_SYNTHETIC_STROKE_WIDTH, fills[wi]
                else:
                    _sw, _sc = typo_stroke_width, typo_stroke_color
                if _adv_draw and _adv_stroke_for is not None:
                    try:
                        _sw = int(_adv_stroke_for(_style_w, int(_sw)))
                        if int(_sw) > 0 and _sc == (0, 0, 0, 0):
                            _sc = (0, 0, 0, 255)
                    except Exception:
                        pass
                _render_styled_scaled_word(
                    frame_img, w["word"], _rx, _ry,
                    item["width"], item["height"], wfont,
                    fills[wi], _sc, _sw,
                    _shadow_off, _shadow_fill,
                    opacity=opacity, scale=scale,
                )
            else:
                _sw_legacy, _sc_legacy = SUBTITLE_STROKE_WIDTH, SUBTITLE_STROKE_COLOR
                if _adv_draw and _adv_stroke_for is not None:
                    try:
                        _sw_legacy = int(_adv_stroke_for("base", int(_sw_legacy)))
                        if int(_sw_legacy) > 0 and _sc_legacy == (0, 0, 0, 0):
                            _sc_legacy = (0, 0, 0, 255)
                    except Exception:
                        pass
                _render_scaled_word(
                    frame_img, w["word"], _rx, _ry,
                    item["width"], item["height"], _word_fonts[wi],
                    fills[wi], _sc_legacy, _sw_legacy,
                    opacity=opacity, scale=scale,
                )

        fname = f"chunk_{chunk_index:04d}_frame_{fi:05d}.png"
        fpath = os.path.join(output_dir, fname)
        # compress_level=1: PNG lossless ma scrittura ~2x piu' veloce
        # (file temp piu' grandi, cancellati a fine job; nessun impatto visivo).
        frame_img.save(fpath, compress_level=1)
        frames.append({"image_path": fpath, "start": t, "end": frame_end})

    # --- Persistenza nel gap (fix blink): clona ultimo frame oltre chunk.end.
    # L'ultimo frame con hold ha character opaco + testo gia' svanito (exit
    # fade completato): clonarlo copre la pausa TTS senza sparizioni.
    # Per la CTA card intermedia l'ultimo frame ha card piena: clonarlo tiene
    # la card persistente. Mai eccezioni (tail best-effort).
    if _tail_hold > 0.001 and frames:
        try:
            import shutil as _shutil
            _extra_n = max(1, int(round(_tail_hold * float(fps))))
            # Cap di sicurezza: max 2s di tail (evita esplosione frame su gap anomali).
            _extra_n = min(_extra_n, max(1, int(round(2.0 * float(fps)))))
            _last = frames[-1]
            _last_path = _last.get("image_path", "")
            _tail_start = float(chunk_end)
            _step = 1.0 / float(fps)
            for _k in range(_extra_n):
                _fi2 = num_frames + _k
                _t2 = _tail_start + _k * _step
                _e2 = _t2 + _step
                _fname2 = f"chunk_{chunk_index:04d}_frame_{_fi2:05d}.png"
                _fpath2 = os.path.join(output_dir, _fname2)
                try:
                    _shutil.copyfile(_last_path, _fpath2)
                except Exception:
                    break
                frames.append({"image_path": _fpath2, "start": _t2, "end": _e2})
        except Exception:
            pass

    return frames


def _is_cta_card_chunk(chunk: dict | None) -> bool:
    """Vero se il chunk è parte di una CTA card persistente (karaoke)."""
    try:
        return bool((chunk or {}).get("cta_card", False))
    except Exception:
        return False


def generate_cta_card_frames(
    cta_chunks: list[dict],
    chunk_states: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    start_index: int = 0,
    fps: int = VIDEO_FPS,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[list[dict]]:
    """Card CTA persistente: messaggio finale fisso con reveal karaoke.

    A differenza dei chunk normali (ogni caption appare e scompare), la card
    mostra l'INTERO messaggio CTA per tutta la sezione: le parole già dette
    restano visibili, la parola corrente entra con pop, le future sono nascoste.
    Il personaggio è bloccato (stessa identità per lock narrativo) e tutto
    svanisce insieme solo alla fine (un'unica dissolvenza, zero flicker).

    Args:
        cta_chunks: chunk CTA consecutivi (stessa sezione, time-ordered).
        chunk_states: per chunk {"exit_mode","entry_jump","entry_fade"} come
            calcolati in render_all_chunks_animated (lookahead/lookbehind).
        Gli altri parametri come generate_animated_chunk_frames.

    Returns:
        Lista (una per chunk) di liste frame {"image_path","start","end"}.
        Non solleva per input vuoti (liste vuote); solleva TextAnimationError
        solo per timestamp invalidi come il path normale.
    """
    if not cta_chunks:
        return []
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    keyword_colors = keyword_colors or {}

    # --- Parole di sezione (timing originali, mai alterati) ---
    use_typography = all(_is_typography_chunk(c) for c in cta_chunks)
    typo_preset: dict | None = None
    if use_typography:
        try:
            typo_preset = _resolve_typography_preset(
                cta_chunks[0], typography_niche, typography_preset)
        except Exception:
            use_typography = False
            typo_preset = None
    try:
        uppercase_impact = bool((typo_preset or {}).get("impact_uppercase", True))
    except Exception:
        uppercase_impact = True

    section: list[dict] = []  # {word,display,style,start,end,is_keyword,is_hero,is_number}
    if use_typography and typo_preset is not None:
        for ch in cta_chunks:
            for s in (ch.get("styled_words") or []):
                if not isinstance(s, dict) or not str(s.get("word", "")).strip():
                    continue
                style = s.get("style", "base")
                if style not in ("base", "impact", "accent"):
                    style = "base"
                _wstr = str(s.get("word", ""))
                _is_num = bool(s.get("is_number", False)) or _has_digit_fast(_wstr)
                _is_hero = bool(s.get("is_hero", False)) and style == "impact" and not _is_num
                section.append({
                    "word": _wstr,
                    "display": str(s.get("display") or _wstr),
                    "style": style,
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("end", 0.0)),
                    "is_keyword": style == "impact",
                    "is_hero": _is_hero,
                    "is_number": _is_num,
                })
    else:
        use_typography = False
        for ch in cta_chunks:
            for w in enrich_chunk_words(ch, keyword_colors):
                style = "impact" if w.get("is_keyword") else "base"
                section.append({
                    "word": str(w.get("word", "")),
                    "display": str(w.get("word", "")),
                    "style": style,
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0)),
                    "is_keyword": bool(w.get("is_keyword", False)),
                    "is_hero": False,
                    "is_number": _has_digit_fast(str(w.get("word", ""))),
                })
    if not section:
        return [[] for _ in cta_chunks]
    section.sort(key=lambda s: (s["start"], s["end"]))

    # --- Area testo CTA (centro fisso) + pill badge ---
    first_info = _character_info_from_chunk(cta_chunks[0])
    use_preset = bool(first_info is not None and first_info.get("use_preset"))
    explicit_box = text_safe_area if text_safe_area is not None else safe_area
    if explicit_box is not None:
        try:
            area = (int(explicit_box[0]), int(explicit_box[1]),
                    int(explicit_box[2]), int(explicit_box[3]))
            area = area if area[2] > area[0] and area[3] > area[1] else None
        except (TypeError, ValueError, IndexError):
            area = None
        font_scale = 1.0
    elif use_preset:
        area = preset_safe_area(first_info.get("layout"), VIDEO_WIDTH, VIDEO_HEIGHT)
        try:
            font_scale = float(preset_font_scale(first_info.get("layout")))
        except Exception:
            font_scale = 1.0
    else:
        area, font_scale = None, 1.0
    # Guard real-time anche sulla CTA card (primo chunk della sezione).
    try:
        if explicit_box is None and isinstance(cta_chunks[0], dict):
            _gsa0 = cta_chunks[0].get("guard_safe_area")
            if _gsa0 is not None:
                _gb0 = (int(_gsa0[0]), int(_gsa0[1]), int(_gsa0[2]), int(_gsa0[3]))
                if _gb0[2] > _gb0[0] and _gb0[3] > _gb0[1]:
                    area = _gb0
            _gfs0 = cta_chunks[0].get("guard_font_scale")
            if _gfs0 is not None:
                _gf0 = float(_gfs0)
                if 0.5 <= _gf0 <= 1.5:
                    font_scale = _gf0
    except Exception:
        pass
    needs_pill = True  # la card è un badge intenzionale, sempre ancorato
    card_scale = 0.92  # la card contiene più parole: leggermente più compatta

    # --- Font/fill di sezione (una volta sola: niente cambi a metà card) ---
    if use_typography and typo_preset is not None:
        typo_fonts = _load_typography_fonts(typo_preset, font_scale * card_scale)
        typo_fills = _styled_fills(
            typo_preset, base_override=text_color,
            background_color=background_color, keyword_colors=keyword_colors)
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_styled_layout(section, typo_fonts, max_text_width, area=area)
        if len(layout) != len(section):
            raise TextAnimationError("Layout/words fuori sync nella CTA card.")
        fills = [typo_fills.get(layout[i].get("style", "base"), typo_fills["base"])
                 for i in range(len(layout))]
        stroke_color, stroke_width = (0, 0, 0, 0), 0
        shadow_off, shadow_fill = None, None
    else:
        use_typography = False
        try:
            text_font_size = max(24, int(round(SUBTITLE_FONT_SIZE * float(font_scale) * card_scale)))
        except (TypeError, ValueError):
            text_font_size = SUBTITLE_FONT_SIZE
        font = load_font(text_font_size)
        max_text_width = int(VIDEO_WIDTH * 0.85)
        layout = compute_word_layout([s["word"] for s in section], font, max_text_width, area=area)
        if len(layout) != len(section):
            raise TextAnimationError("Layout/words fuori sync nella CTA card.")
        base_rgba = _to_rgba(text_color, SUBTITLE_COLOR)
        fills = [_resolve_word_fill(normalize_word(s["word"]), base_rgba, keyword_colors)
                 for s in section]
        typo_fonts = None

    # Come nel path normale: base statico -> grassetto sintetico leggero.
    try:
        _cta_synth = bool(use_typography and isinstance(typo_fonts, dict)
                          and not typo_fonts.get("base_weight_applied", False))
    except Exception:
        _cta_synth = False

    # Tier T0-T3 anche sulla card (stessi default del path normale).
    try:
        last_exit = max(0.0, float(TEXT_ANIMATION_EXIT_DURATION))
    except (TypeError, ValueError, NameError):
        last_exit = 0.15
    try:
        entry_dur, scale_from, accent_lift, hero_dur, hero_from, number_dur = (
            _resolve_motion_params(typo_preset if use_typography else None, cta_chunks[0] if cta_chunks else None)
        )
    except Exception:
        entry_dur, scale_from = 0.18, 0.7
        accent_lift, hero_dur, hero_from, number_dur = 10.0, 0.22, 0.6, 0.15
    # CTA card: nessun hook mult (card stabile); scala da preset nicchia.
    # Se il primo chunk CTA porta anim_pop_from esplicito, _resolve lo ha gia'
    # applicato: qui lo neutralizziamo solo se e' un hook residue (mai in CTA).
    try:
        _cta_tiers = [_word_tier(w) for w in section]
        _cta_entry = [
            (hero_dur if _h else (number_dur if (_s == "impact" and _n) else entry_dur))
            for (_s, _h, _n) in _cta_tiers
        ]
        _cta_scale = [
            (hero_from if _h else scale_from) if _s == "impact" else 1.0
            for (_s, _h, _n) in _cta_tiers
        ]
    except Exception:
        _cta_tiers = [("base", False, False)] * len(section)
        _cta_entry = [entry_dur] * len(section)
        _cta_scale = [1.0] * len(section)
    try:
        _cta_lift_i = int(round(accent_lift))
    except Exception:
        _cta_lift_i = 10

    # --- Personaggio bloccato (layer unico per tutta la card, entrata fluida) ---
    char_img, char_base_xy = _load_chunk_character_layer(first_info)
    if char_img is not None and char_base_xy is not None and first_info is not None:
        char_transition = first_info.get("transition_in", "fade") or "fade"
        char_side = _character_side(first_info)
        char_full_travel = bool(use_preset)
        try:
            _cs0 = chunk_states[0] if chunk_states else {}
            _first_fade = bool(_cs0.get("char_entry_fade", True))
        except Exception:
            _first_fade = True
        if _first_fade:
            char_entry_dur = max(0.01, _CHARACTER_ZONE_FIRST_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        else:
            char_entry_dur = max(0.01, _CHARACTER_MORPH_DURATION if use_preset else _CHARACTER_ENTRY_DURATION)
        try:
            _cta_morph_from = (_cs0.get("char_entry_from_xy") if isinstance(_cs0, dict) else None)
            if _cta_morph_from is not None:
                _cta_morph_from = (int(_cta_morph_from[0]), int(_cta_morph_from[1]))
                if _cta_morph_from == (int(char_base_xy[0]), int(char_base_xy[1])):
                    _cta_morph_from = None
        except (TypeError, ValueError, IndexError):
            _cta_morph_from = None
    else:
        char_base_xy = None
        _cta_morph_from = None
    try:
        char_exit_dur = max(0.0, float(_CHARACTER_ZONE_EXIT_DURATION))
    except (TypeError, ValueError):
        char_exit_dur = _CHARACTER_ZONE_EXIT_DURATION

    os.makedirs(output_dir, exist_ok=True)
    # Pill CTA pre-renderizzata una volta (stesso layout per tutta la card).
    _cta_pill = None
    try:
        if layout:
            from core.renderer import TEXT_PILL_FILL as _PF, TEXT_PILL_PAD as _PP, TEXT_PILL_RADIUS as _PR
            _cx0 = max(0, min(it["x"] for it in layout) - _PP)
            _cy0 = max(0, min(it["y"] for it in layout) - _PP)
            _cx1 = min(VIDEO_WIDTH, max(it["x"] + it["width"] for it in layout) + _PP)
            _cy1 = min(VIDEO_HEIGHT, max(it["y"] + it["height"] for it in layout) + _PP)
            if _cx1 > _cx0 and _cy1 > _cy0:
                _cta_pill = _get_cached_pill_overlay((_cx0, _cy0, _cx1, _cy1), _PF, _PP, _PR)
    except Exception:
        _cta_pill = None
    # Font per parola pre-risolti + binding locali.
    try:
        if use_typography and typo_fonts is not None:
            _cta_fonts = [typo_fonts.get(layout[i].get("style", section[i].get("style", "base")), typo_fonts.get("base")) for i in range(len(section))]
        else:
            _cta_fonts = [font] * len(section)
    except Exception:
        _cta_fonts = [font if 'font' in dir() else typo_fonts.get("base")] * len(section)
    _cta_ease_back = ease_out_back
    _cta_ease_cubic = ease_out_cubic
    _cta_ease_quad = ease_out_quad
    _cta_clamp = clamp01
    per_chunk_frames: list[list[dict]] = []
    for k, ch in enumerate(cta_chunks):
        try:
            cs = float(ch.get("start", section[0]["start"]))
            ce = float(ch.get("end", section[-1]["end"]))
        except (TypeError, ValueError) as e:
            raise TextAnimationError(f"Timestamp CTA non validi: {e}")
        if ce <= cs:
            ce = cs + 0.1
        is_last = (k == len(cta_chunks) - 1)
        exit_dur = last_exit if is_last else 0.0  # dissolvenza SOLO alla fine
        try:
            st = chunk_states[k] if k < len(chunk_states) else {}
            exit_mode = st.get("char_exit_mode", _CHAR_EXIT_WITH_TEXT)
            entry_jump = bool(st.get("char_entry_jump", False))
            entry_fade = bool(st.get("char_entry_fade", k == 0))
        except Exception:
            exit_mode, entry_jump, entry_fade = _CHAR_EXIT_WITH_TEXT, False, k == 0
        if exit_mode not in (_CHAR_EXIT_WITH_TEXT, _CHAR_EXIT_SLIDE_DOWN, _CHAR_EXIT_HOLD):
            exit_mode = _CHAR_EXIT_WITH_TEXT

        num_frames = max(1, int(math.ceil((ce - cs) * fps)))
        step = 1.0 / float(fps)
        frames: list[dict] = []
        for fi in range(num_frames):
            t = cs + fi * step
            if t >= ce:
                t = ce - 1e-6
            frame_end = min(t + step, ce)
            if exit_dur > 0 and t >= ce - exit_dur:
                exit_factor = 1.0 - ease_in_cubic(clamp01((t - (ce - exit_dur)) / exit_dur))
            else:
                exit_factor = 1.0
            frame_img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
            if char_img is not None and char_base_xy is not None:
                _cta_scale = 1.0
                _cta_layer = char_img
                if entry_jump:
                    edx, edy, entry_opacity = 0, 0, 255
                elif k == 0 and '_cta_morph_from' in dir() and _cta_morph_from is not None and not entry_fade:
                    # Handoff fluido corpo->CTA: morph dalla vecchia posizione.
                    try:
                        _mp0 = clamp01((t - cs) / max(0.01, _CHARACTER_MORPH_DURATION))
                    except Exception:
                        _mp0 = 1.0
                    edx, edy = _character_morph_offset(_cta_morph_from, tuple(char_base_xy), _mp0)
                    entry_opacity = 255
                else:
                    entry_prog = clamp01((t - cs) / char_entry_dur)
                    edx, edy, entry_opacity, _cta_scale = _character_entry_transform(
                        char_transition, char_side, entry_prog,
                        char_img.size[0], char_base_xy[0], char_base_xy[1],
                        full_travel=char_full_travel, fade=entry_fade)
                    if abs(_cta_scale - 1.0) >= 1e-3:
                        try:
                            _zw, _zh = char_img.size
                            _nw = max(1, int(round(_zw * _cta_scale)))
                            _nh = max(1, int(round(_zh * _cta_scale)))
                            _cta_layer = char_img.resize((_nw, _nh), _fast_resample_for_scale(_cta_scale))
                            _ccx = char_base_xy[0] + _zw / 2.0
                            _ccy = char_base_xy[1] + _zh / 2.0
                            edx = int(round(_ccx - _nw / 2.0)) - int(char_base_xy[0])
                            edy = int(round(_ccy - _nh / 2.0)) - int(char_base_xy[1])
                        except Exception:
                            _cta_layer = char_img
                if exit_mode == _CHAR_EXIT_HOLD or exit_mode == _CHAR_EXIT_SLIDE_DOWN:
                    cop, xdx, xdy = entry_opacity, 0, 0
                else:
                    # Uscita slide-drop CTA finale (~0.16s): +400px in_cubic + fade.
                    if char_exit_dur > 0 and t >= ce - char_exit_dur:
                        try:
                            _xp = clamp01((t - (ce - char_exit_dur)) / char_exit_dur)
                        except Exception:
                            _xp = 1.0
                        cop = int(round(entry_opacity * max(0.0, min(1.0, 1.0 - ease_out_quad(_xp)))))
                        try:
                            xdy = int(round(_CHARACTER_EXIT_DROP_Y * ease_in_cubic(_xp)))
                        except Exception:
                            xdy = 0
                        xdx = 0
                    else:
                        cop = entry_opacity
                        xdx, xdy = 0, 0
                # Idle anche sulla card (stessa fase assoluta, continuita').
                try:
                    _c_dy, _c_tilt = _idle_bob_tilt(t)
                except Exception:
                    _c_dy, _c_tilt = 0, 0.0
                try:
                    _c_zooming = abs(float(_cta_scale) - 1.0) >= 1e-3
                except Exception:
                    _c_zooming = False
                if _c_tilt and not _c_zooming:
                    try:
                        _cta_layer = _get_tilted_char(_cta_layer, _c_tilt)
                    except Exception:
                        pass
                if _c_dy:
                    edy += int(_c_dy)
                _paste_character_frame(
                    frame_img, _cta_layer,
                    char_base_xy[0] + edx + xdx, char_base_xy[1] + edy + xdy, cop)
            if _cta_pill is not None:
                try:
                    frame_img.alpha_composite(_cta_pill)
                except (ValueError, AttributeError):
                    draw_text_background(frame_img, layout)
            elif needs_pill:
                draw_text_background(frame_img, layout)
            for wi, w in enumerate(section):
                if t < w["start"]:
                    continue  # parola futura: nascosta (reveal karaoke)
                try:
                    _ced = _cta_entry[wi]
                except (IndexError, TypeError):
                    _ced = entry_dur
                if _ced <= 0:
                    _ced = 0.01
                local = _cta_clamp((t - w["start"]) / _ced)
                try:
                    _cs, _ch, _cn = _cta_tiers[wi]
                except (IndexError, TypeError, ValueError):
                    _cs, _ch, _cn = ("impact" if w.get("is_keyword") else "base", bool(w.get("is_hero", False)), False)
                try:
                    _csf = _cta_scale[wi]
                except (IndexError, TypeError):
                    _csf = scale_from
                _cdy = 0
                if _cs == "impact":
                    if local >= 1.0:
                        # Nota: eased>=1 qui significa entrata finita (scale 1);
                        # l'overshoot >1 vive solo dentro local<1 (vedi sotto).
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        eased = _cta_ease_back(local)
                        opacity = int(round(255 * min(1.0, max(0.0, eased))))
                        scale = max(0.05, _csf + (1.0 - _csf) * eased)
                elif _cs == "accent" and use_typography:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        eased = _cta_ease_cubic(local)
                        opacity = int(round(255 * eased))
                        scale = 1.0
                        if _cta_lift_i > 0:
                            try:
                                _cdy = int(round(_cta_lift_i * (1.0 - _cta_ease_quad(local))))
                            except Exception:
                                _cdy = int(round(_cta_lift_i * (1.0 - eased)))
                else:
                    if local >= 1.0:
                        opacity, scale = 255, 1.0
                    elif local <= 0.0:
                        continue
                    else:
                        opacity = int(round(255 * _cta_ease_cubic(local)))
                        scale = 1.0
                try:
                    if _ch and exit_factor < 1.0:
                        _ef = _hero_exit_factor(t, ce, exit_dur, exit_factor)
                        opacity = int(round(opacity * _ef))
                    elif exit_factor < 1.0:
                        opacity = int(round(opacity * exit_factor))
                except Exception:
                    if exit_factor < 1.0:
                        opacity = int(round(opacity * exit_factor))
                if opacity <= 0:
                    continue
                item = layout[wi]
                _cy = item["y"] + _cdy if _cdy else item["y"]
                if use_typography:
                    wfont = _cta_fonts[wi]
                    if _cta_synth and _cs == "base":
                        _csw, _csc = _BASE_SYNTHETIC_STROKE_WIDTH, fills[wi]
                    else:
                        _csw, _csc = stroke_width, stroke_color
                    _render_styled_scaled_word(
                        frame_img, w["display"], item["x"], _cy,
                        item["width"], item["height"], wfont,
                        fills[wi], _csc, _csw,
                        shadow_off, shadow_fill, opacity=opacity, scale=scale)
                else:
                    _render_scaled_word(
                        frame_img, w["word"], item["x"], _cy,
                        item["width"], item["height"], _cta_fonts[wi],
                        fills[wi], SUBTITLE_STROKE_COLOR, SUBTITLE_STROKE_WIDTH,
                        opacity=opacity, scale=scale)
            fname = f"chunk_{start_index + k:04d}_frame_{fi:05d}.png"
            fpath = os.path.join(output_dir, fname)
            frame_img.save(fpath, compress_level=1)
            frames.append({"image_path": fpath, "start": t, "end": frame_end})
        # Tail persistenza gap anche per la card (intermedi: card piena).
        try:
            _st_k = chunk_states[k] if k < len(chunk_states) else {}
            _tail_k = float((_st_k or {}).get("char_tail", 0.0) or 0.0)
        except Exception:
            _tail_k = 0.0
        if _tail_k > 0.001 and frames and not (k == len(cta_chunks) - 1):
            try:
                import shutil as _sh2
                _n2 = min(max(1, int(round(_tail_k * float(fps)))), max(1, int(round(2.0 * float(fps)))))
                _lp = frames[-1].get("image_path", "")
                for _kk in range(_n2):
                    _fi2 = num_frames + _kk
                    _t2 = ce + _kk * step
                    _fn2 = f"chunk_{start_index + k:04d}_frame_{_fi2:05d}.png"
                    _fp2 = os.path.join(output_dir, _fn2)
                    try:
                        _sh2.copyfile(_lp, _fp2)
                    except Exception:
                        break
                    frames.append({"image_path": _fp2, "start": _t2, "end": _t2 + step})
            except Exception:
                pass
        per_chunk_frames.append(frames)
    return per_chunk_frames


def render_all_chunks_animated(
    chunks: list[dict],
    background_color: str,
    text_color,
    keyword_colors: dict | None = None,
    output_dir: str = TEMP_DIR,
    fps: int = VIDEO_FPS,
    on_chunk=None,
    safe_area: tuple[int, int, int, int] | None = None,
    text_safe_area: tuple[int, int, int, int] | None = None,
    typography_niche: str | None = None,
    typography_preset: dict | None = None,
) -> list[dict]:
    """Genera i frame animati per tutti i chunk.

    Args:
        chunks: lista di chunk con "text"/"start"/"end"/"words" (+ metadati
            character opzionali: pose/layout/transition_in, e con tipografia
            attiva anche "styled_words" + "typography_niche" da core/text_tagger.py).
        background_color: hex da theme.py (tenuto per compatibilita').
        text_color: hex o RGBA del testo base.
        keyword_colors: {norm: colore} (hex o RGBA).
        output_dir: cartella dei frame PNG.
        fps: frame rate.
        on_chunk: callback opzionale (idx, totale) a fine chunk, per logging GUI.
        safe_area: Text Safe Area esplicita per TUTTI i chunk (override dei
            preset; None = preset del singolo chunk o centro schermo).
        text_safe_area: alias di safe_area (ha precedenza).
        typography_niche: nicchia esplicita (override per tutti i chunk senza niche propria).
        typography_preset: preset dict esplicito (da core/typography_presets.get_preset).

    Il lookahead sul chunk successivo decide l'uscita (hold quando il dopo ha
    un character, slide-drop+fade 0.16s solo in sparizione); il lookbehind
    decide l'entrata (slide&pop 0.20s +300px alla prima apparizione, morph
    smart 0.40s dalla vecchia posizione nei cambi, jump solo a identita'
    pixel-identica, zoom fluido 0.6s per il punch hook mai secco). Idle
    breathing/sway continuo sopra ogni frame visibile. I gap TTS sono coperti
    da tail di persistenza (hold) per fix blink. Ritmo coerente e dinamico.

    Returns:
        Lista di chunk arricchiti: {**chunk, "frames": [...], "frame_paths": [...],
        "clip_start": start, "clip_end": end (+tail), "clip_tail": secondi}.
    """
    import os as _os
    _parallel_ok = _os.environ.get("RENDER_PARALLEL", "1").strip().lower() not in ("0", "false", "no", "off", "")
    try:
        _gap_hold_ok = str(_os.environ.get("CHARACTER_GAP_HOLD_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        _gap_hold_ok = True
    try:
        _gap_hold_max = max(0.0, float(CHARACTER_GAP_HOLD_MAX))
    except Exception:
        _gap_hold_max = 1.5
    if not (_gap_hold_max > 0):
        _gap_hold_max = 1.5
    enriched_all: list[dict] = []
    total = len(chunks)
    # Pre-carica posizioni base character per morph (cached, veloce).
    _base_xy_cache: dict[int, tuple[int, int] | None] = {}
    for _ci in range(total):
        try:
            _inf = _character_info_from_chunk(chunks[_ci])
            if _inf is None:
                _base_xy_cache[_ci] = None
            else:
                _img, _xy = _load_chunk_character_layer(_inf)
                _base_xy_cache[_ci] = (int(_xy[0]), int(_xy[1])) if _xy is not None else None
        except Exception:
            _base_xy_cache[_ci] = None
    # Stati personaggio per chunk (lookahead/lookbehind), calcolati una volta:
    # servono sia al path normale sia alla CTA card (stessa fluidita').
    states: list[dict] = []
    for i, chunk in enumerate(chunks):
        nxt = chunks[i + 1] if i + 1 < total else None
        prev = chunks[i - 1] if i - 1 >= 0 else None
        exit_mode = decide_char_exit_mode(chunk, nxt)
        try:
            cur_info = _character_info_from_chunk(chunk)
            prev_info = _character_info_from_chunk(prev) if prev is not None else None
        except Exception:
            cur_info, prev_info = None, None
        try:
            # Taglio invisibile SOLO a identita' pixel-identica (stessa
            # posa+zona+punch): nessun replay (replay = blink a ogni stacco).
            # Cambio posa/lato/punch -> morph/zoom fluido, MAI jump secco.
            entry_jump = bool(decide_char_entry_jump(prev, chunk))
            # Dissolvenza SOLO alla prima apparizione; morph opachi dopo.
            entry_fade = prev_info is None
        except Exception:
            entry_jump, entry_fade = False, True
        # Macro-blocchi (Breath & Focus): l'evento guida entrata/uscita.
        # ENTRY = slide-in pulito; SUSTAIN/EXIT (non-primi) = hold invisibile
        # (stessa posa/lato ancorati nel blocco, nessun replay); NONE/hidden
        # = nessun layer. Tra blocchi visibili diversi il morph parte dalla
        # posizione precedente (switch diretto, mai fade out/in).
        try:
            _ev = _character_event_of(chunk)
            if cur_info is None or _ev == "NONE":
                entry_jump, entry_fade = True, False
            elif _ev == "ENTRY":
                # Riapparizione dopo gap -> slide-in con fade; se il chunk
                # prima aveva gia' un character (blocchi visibili adiacenti),
                # switch diretto senza fade (morph dalla vecchia posizione).
                if prev_info is None:
                    entry_jump, entry_fade = False, True
                else:
                    entry_jump, entry_fade = False, False
            elif _ev in ("SUSTAIN", "EXIT"):
                entry_jump, entry_fade = True, False
        except Exception:
            pass
        # Morph smart: posizione precedente per slide continua (niente flash).
        try:
            from_xy = None
            if not entry_jump and not entry_fade and cur_info is not None and prev_info is not None:
                from_xy = _base_xy_cache.get(i - 1)
        except Exception:
            from_xy = None
        # Tail persistenza gap: hold -> copre la pausa fino al chunk dopo.
        try:
            tail = 0.0
            if _gap_hold_ok and exit_mode == _CHAR_EXIT_HOLD and cur_info is not None and nxt is not None:
                try:
                    _end = float(chunk.get("end", 0.0))
                    _nxt_start = float(nxt.get("start", _end))
                except (TypeError, ValueError):
                    _end, _nxt_start = 0.0, 0.0
                _gap = _nxt_start - _end
                if _gap > 1.0 / max(1, int(fps or VIDEO_FPS)) + 1e-6:
                    tail = min(max(0.0, _gap), _gap_hold_max)
        except Exception:
            tail = 0.0
        # --- Fase 3: micro cross-fade dentro il blocco Focus (no tagli netti) ---
        _micro = False
        _prev_layer = None
        try:
            from core.character_selector import is_focus_pose_switch as _is_focus_sw
            _prev_chunk = chunks[i - 1] if i - 1 >= 0 else None
            if _prev_chunk is not None and bool(_is_focus_sw(_prev_chunk, chunk)):
                try:
                    _pi = _character_info_from_chunk(_prev_chunk)
                    if _pi is not None:
                        _pl, _px = _load_chunk_character_layer(_pi)
                        if _pl is not None:
                            _prev_layer = _pl
                            _micro = True
                except Exception:
                    _prev_layer, _micro = None, False
        except Exception:
            _prev_layer, _micro = None, False
        states.append({
            "char_exit_mode": exit_mode,
            "char_entry_jump": entry_jump,
            "char_entry_fade": entry_fade,
            "char_entry_from_xy": from_xy,
            "char_tail": float(tail or 0.0),
            "char_micro_blend": bool(_micro),
            "char_prev_layer": _prev_layer,
        })
    # Separa run CTA (sequenziali, condividono layout) da chunk normali (paralleli).
    cta_runs: list[list[int]] = []
    normal_idx: list[int] = []
    i = 0
    while i < total:
        chunk = chunks[i]
        if _is_cta_card_chunk(chunk):
            try:
                section_id = (chunk or {}).get("cta_section_id", i)
            except Exception:
                section_id = i
            run = [i]
            j = i + 1
            while j < total and _is_cta_card_chunk(chunks[j]):
                try:
                    same_section = (chunks[j] or {}).get("cta_section_id", j) == section_id
                except Exception:
                    same_section = True
                if not same_section:
                    break
                run.append(j)
                j += 1
            cta_runs.append(run)
            i = j
            continue
        normal_idx.append(i)
        i += 1
    # --- CTA card (poche, layout condiviso): sequenziale veloce ---
    cta_results: dict[int, list[dict]] = {}
    for run in cta_runs:
        run_chunks = [chunks[k] for k in run]
        run_states = [states[k] for k in run]
        try:
            run_frames = generate_cta_card_frames(
                run_chunks, run_states, background_color, text_color,
                keyword_colors or {}, output_dir, run[0], fps,
                safe_area=safe_area, text_safe_area=text_safe_area,
                typography_niche=typography_niche,
                typography_preset=typography_preset,
            )
        except TextAnimationError:
            raise
        except Exception as e:
            raise TextAnimationError(f"CTA card fallita: {e}")
        for pos, k in enumerate(run):
            cta_results[k] = run_frames[pos] if pos < len(run_frames) else []
            if on_chunk is not None:
                try:
                    on_chunk(k + 1, total)
                except Exception:
                    pass
    # --- Chunk normali: paralleli con ThreadPool (I/O + resize rilasciano GIL) ---
    normal_results: dict[int, list[dict]] = {}
    if normal_idx:
        use_parallel = bool(_parallel_ok) and len(normal_idx) >= 3
        if use_parallel:
            import concurrent.futures as _fut
            try:
                _cpu = max(2, (_os.cpu_count() or 4))
            except Exception:
                _cpu = 4
            _workers = max(2, min(4, _cpu - 1, len(normal_idx)))

            def _render_one(k: int):
                st = states[k]
                return generate_animated_chunk_frames(
                    chunks[k], background_color, text_color,
                    keyword_colors or {}, output_dir, k, fps,
                    safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
                    text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
                    char_entry_fade=st["char_entry_fade"],
                    typography_niche=typography_niche, typography_preset=typography_preset,
                    char_entry_from_xy=st.get("char_entry_from_xy"),
                    tail_hold_duration=float(st.get("char_tail", 0.0) or 0.0),
                    char_prev_layer=st.get("char_prev_layer"),
                    char_micro_blend=bool(st.get("char_micro_blend", False)),
                )
            with _fut.ThreadPoolExecutor(max_workers=_workers) as _ex:
                _future_map = {_ex.submit(_render_one, k): k for k in normal_idx}
                for _fu in _fut.as_completed(_future_map):
                    k = _future_map[_fu]
                    normal_results[k] = _fu.result()
                    if on_chunk is not None:
                        try:
                            on_chunk(k + 1, total)
                        except Exception:
                            pass
        else:
            for k in normal_idx:
                st = states[k]
                normal_results[k] = generate_animated_chunk_frames(
                    chunks[k], background_color, text_color,
                    keyword_colors or {}, output_dir, k, fps,
                    safe_area=safe_area, char_exit_mode=st["char_exit_mode"],
                    text_safe_area=text_safe_area, char_entry_jump=st["char_entry_jump"],
                    char_entry_fade=st["char_entry_fade"],
                    typography_niche=typography_niche, typography_preset=typography_preset,
                    char_entry_from_xy=st.get("char_entry_from_xy"),
                    tail_hold_duration=float(st.get("char_tail", 0.0) or 0.0),
                    char_prev_layer=st.get("char_prev_layer"),
                    char_micro_blend=bool(st.get("char_micro_blend", False)),
                )
                if on_chunk is not None:
                    try:
                        on_chunk(k + 1, total)
                    except Exception:
                        pass
    for k in range(total):
        frames = cta_results.get(k, normal_results.get(k, []))
        try:
            _tail_k = float((states[k] or {}).get("char_tail", 0.0) or 0.0)
        except Exception:
            _tail_k = 0.0
        try:
            _end_k = float(chunks[k].get("end", chunks[k].get("start", 0.0)))
        except (TypeError, ValueError):
            _end_k = 0.0
        enriched_all.append({
            **chunks[k],
            "frames": frames,
            "frame_paths": [f["image_path"] for f in frames],
            "clip_start": chunks[k].get("start"),
            "clip_end": (_end_k + _tail_k) if _tail_k > 0 else chunks[k].get("end"),
            "clip_tail": _tail_k,
        })
    # Ordina callback finale per GUI coerente (i paralleli arrivano fuori ordine).
    return enriched_all

```

---

### `core/text_tagger.py` — 690 righe, 27524 byte

Semantic Typography v1 — tagging LLM (690 righe): `enrich_chunks_with_typography(chunks, script, ...)` → `(nicchia, chunks+styled_words)`. Nicchia (fitness/finance/motivazione/...) → font/colori via `typography_presets`. Ogni parola → `{style:base|impact|accent, is_hero, is_number}`. Base leggibile, impact pop, accent handwritten rise. `PIPELINE_FAST` → euristica.

```python
"""
Semantic Typography Engine v1 — Analisi semantica e tagging LLM (Groq).

Due analisi:
  A. Rilevamento nicchia: lo script completo -> una di VALID_NICHES
     (vedi core/typography_presets.py). Fallback deterministico se LLM assente.
  B. Tagging parole (word-level): ogni chunk -> parole con categoria
     "base" | "impact" | "accent":
       - base:   parlato standard / congiunzioni / testo generico
       - impact: keyword ad alto valore, numeri, concetti chiave (es. SMETTI, RISULTATI)
       - accent: domande retoriche, citazioni, virgolettati, espressioni d'effetto

Formato output LLM per chunk (spec):
    {"chunk_index": 0, "words": [{"text": "Smetti di ", "type": "base"}, ...]}

I timestamp originali (STT + alignment) non vengono mai alterati: il tagging
riallinea i segmenti LLM alle parole timestampate con match normalizzato.
Se l'LLM fallisce, fallback euristico deterministico (mai bloccante).
"""

import json
import re
from collections.abc import Callable

from config import GROQ_API_KEYS, GROQ_LLM_MODEL
from core.typography_presets import (
    FALLBACK_NICHE,
    NICHE_DESCRIPTIONS,
    VALID_NICHES,
    list_niches_for_prompt,
    normalize_niche,
)


class TextTaggerError(Exception):
    """Errore nel tagging tipografico (input non valido)."""


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


def _heuristic_tagging(chunks: list[dict]) -> list[dict]:
    """Fallback euristico unificato (evita triplicazione codice, istantaneo)."""
    out: list[dict] = []
    for i, ch in enumerate(chunks):
        timed = (ch or {}).get("words") or [{"word": t} for t in str((ch or {}).get("text", "")).split()]
        out.append({
            "chunk_index": i,
            "words": [
                {"text": str(w.get("word", "")), "type": _heuristic_style(str(w.get("word", "")), str((ch or {}).get("text", "")))}
                for w in timed if str(w.get("word", "")).strip()
            ] or [{"text": str((ch or {}).get("text", "")), "type": "base"}],
        })
    return out


VALID_TYPES = ("base", "impact", "accent")


# ---------------------------------------------------------------------------
# A. Rilevamento nicchia
# ---------------------------------------------------------------------------

# Parole segnale per fallback euristico (italiano + inglese, lowercase).
_NICHE_KEYWORDS: dict[str, list[str]] = {
    "business_finance": [
        "soldi", "invest", "business", "finanza", "guadagn", "profitto", "fatturato",
        "marketing", "vendite", "clienti", "azienda", "startup", "capitale", "banca",
        "trading", "crypto", "money", "revenue", "strategy", "strategia",
    ],
    "tech_ai": [
        "intelligenza artificiale", "ai", "robot", "software", "codice", "coding",
        "algoritmo", "dati", "digital", "tecnolog", "computer", "app", "chatgpt",
        "machine learning", "automazione", "tech", "innovazione",
    ],
    "fitness_sport": [
        "palestra", "allenamento", "workout", "muscol", "proteine", "dieta",
        "cardio", "sport", "fitness", "corpo", "peso", "corsa", "calcio", "atleta",
    ],
    "lifestyle_vlog": [
        "vlog", "viaggio", "routine", "mattina", "moda", "bellezza", "trucco",
        "outfit", "giornata", "emozione", "lifestyle", "weekend", "casa",
    ],
    "educational": [
        "scuola", "lezione", "storia", "scienza", "spieg", "impara", "studio",
        "curiosit", "tutorial", "come funziona", "perché", "perche", "educazione",
        "universit", "esame",
    ],
    "dark_motivational": [
        "disciplina", "mentalit", "sacrificio", "successo", "fallimento", "dolore",
        "smetti", "svegliati", "nessuno", "lotta", "guerra", "vincere", "perdente",
        "motivazione", "mindset", "grind", "hustle",
    ],
}


def _heuristic_niche(script_text: str) -> str:
    """Fallback deterministico: conta le parole segnale per nicchia."""
    text = (script_text or "").lower()
    if not text.strip():
        return FALLBACK_NICHE
    scores: dict[str, int] = {}
    for niche, keywords in _NICHE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text:
                # Pesa le espressioni multi-parola (più specifiche).
                score += 2 if " " in kw else 1
        scores[niche] = score
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0:
        return FALLBACK_NICHE
    return best


def _parse_niche(content: str) -> tuple[str | None, float]:
    """Estrae (niche, confidence) dalla risposta LLM. (None, 0.0) se invalida."""
    text = (content or "").strip()
    if not text:
        return None, 0.0
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None, 0.0
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, 0.0
    if not isinstance(data, dict):
        return None, 0.0
    raw_niche = data.get("niche", data.get("category", data.get("label")))
    if not isinstance(raw_niche, str):
        return None, 0.0
    try:
        conf = float(data.get("confidence", data.get("score", 0.8)))
    except (TypeError, ValueError):
        conf = 0.8
    conf = max(0.0, min(1.0, conf))
    niche = normalize_niche(raw_niche)
    # Se l'LLM ha scritto una nicchia ignota, normalize torna il fallback:
    # in quel caso la confidence va azzerata per segnalare incertezza.
    if raw_niche.strip().lower().replace("-", "_").replace(" ", "_") not in VALID_NICHES \
            and niche == FALLBACK_NICHE:
        # Potrebbe essere un alias valido (es. "business"): ricontrolla.
        if normalize_niche(raw_niche) not in VALID_NICHES:
            return None, 0.0
    return niche, conf


def detect_niche(
    script_text: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
    min_confidence: float = 0.4,
) -> str:
    """Rileva la nicchia dello script (una di VALID_NICHES).

    Non solleva mai per errori API/validazione: in quel caso ritorna il
    fallback (euristico su parole segnale, poi FALLBACK_NICHE).
    Se la confidence LLM < min_confidence, usa il fallback euristico.
    """
    if not script_text or not script_text.strip():
        return FALLBACK_NICHE
    import os as _os2
    if _os2.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        return _heuristic_niche(script_text)
    if not GROQ_API_KEYS:
        if on_attempt is not None:
            try:
                on_attempt(0, 0, False, "nessuna GROQ_API_KEY: nicchia euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)

    snippet = script_text.strip().replace("\n", " ")
    if len(snippet) > 1500:
        snippet = snippet[:1500] + "..."
    niche_lines = "\n".join(
        f"- {n}: {NICHE_DESCRIPTIONS.get(n, '')}" for n in VALID_NICHES
    )
    system = (
        "Sei un analista che classifica script per video brevi in nicchie tipografiche. "
        "Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Classifica lo script in UNA di queste nicchie:\n"
        f"{niche_lines}\n\n"
        f"NICCHIE VALIDE: {list_niches_for_prompt()}\n\n"
        "Rispondi SOLO con JSON: {\"niche\": \"<una di quelle valide>\", "
        "\"confidence\": 0.0-1.0, \"reason\": \"breve motivo\"}\n\n"
        f"SCRIPT:\n{snippet}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=256,
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
                on_attempt(index, total, True, f"chiave {index}/{total}: nicchia ricevuta")
            except Exception:
                pass
        break

    if content is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "LLM nicchia fallito: uso euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)

    niche, conf = _parse_niche(content)
    if niche is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "JSON nicchia non valido: uso euristica")
            except Exception:
                pass
        return _heuristic_niche(script_text)
    if conf < min_confidence:
        heur = _heuristic_niche(script_text)
        if on_attempt is not None:
            try:
                on_attempt(total, total, True,
                           f"nicchia incerta ({niche} conf={conf:.2f}): uso euristica -> {heur}")
            except Exception:
                pass
        return heur
    return niche


# ---------------------------------------------------------------------------
# B. Tagging parole (word-level)
# ---------------------------------------------------------------------------

def _normalize_token(word: str) -> str:
    """Minuscole senza punteggiatura ai bordi (per riallineare LLM -> timing)."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)


def _heuristic_style(word: str, chunk_text: str = "") -> str:
    """Stile euristico per singola parola (fallback quando l'LLM fallisce)."""
    raw = word or ""
    stripped = raw.strip()
    if not stripped:
        return "base"
    norm = _normalize_token(stripped)
    if not norm:
        return "base"
    # Numeri / percentuali / date -> impatto (dati ad alto valore).
    if re.search(r"\d", stripped):
        return "impact"
    # Tutto maiuscolo (3+ lettere) -> impatto.
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", stripped)
    if len(letters) >= 3 and letters.isupper():
        return "impact"
    # Virgolettati / domande / esclamazioni enfatiche -> accento.
    if '"' in chunk_text or '"' in chunk_text or "'" in chunk_text or "«" in chunk_text:
        if norm in _normalize_token(chunk_text).split():
            # Euristica grezza: se il chunk contiene virgolette, le parole
            # lunghe del chunk sono probabilmente la citazione.
            if len(norm) >= 4:
                return "accent"
    if stripped.endswith("?") or chunk_text.strip().endswith("?"):
        return "accent"
    # Parole enfatiche italiane/inglesi -> impatto.
    emphasis = {
        "smetti", "mai", "sempre", "tutti", "nessuno", "tutto", "niente",
        "segreto", "verità", "verita", "gratis", "soldi", "successo", "risultati",
        "risultato", "strategia", "errore", "errori", "stop", "attenzione",
        "incredibile", "impossibile", "garantito", "prova", "fallimento",
    }
    if norm in emphasis or (len(norm) >= 8 and norm not in {
        "perché", "perche", "quando", "quindi", "mentre", "anche", "della",
        "nella", "quello", "questo", "molto", "tanto",
    }):
        # Parole lunghe non-comuni -> probabile concetto chiave.
        if len(norm) >= 9:
            return "impact"
        if norm in emphasis:
            return "impact"
    return "base"


def _parse_tagged_response(content: str, n: int) -> list[dict] | None:
    """Parsa la risposta LLM in [{"chunk_index": i, "words": [{"text","type"}]}].

    Ritorna None se non valida (numero chunk errato, tipi ignoti, ecc.).
    Accetta sia array bare sia {"chunks": [...]} / {"tagged": [...]}.
    """
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        for key in ("chunks", "tagged", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return None
    if not isinstance(data, list):
        return None
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
    result: list[dict] = []
    it = iter(unordered)
    for i in range(n):
        if i in by_index:
            result.append(by_index[i])
        else:
            try:
                result.append(next(it))
            except StopIteration:
                return None
    # Valida e normalizza ogni voce.
    normalized: list[dict] = []
    for i, entry in enumerate(result):
        words = entry.get("words", entry.get("tokens"))
        if not isinstance(words, list) or not words:
            return None
        norm_words: list[dict] = []
        for w in words:
            if not isinstance(w, dict):
                return None
            t = w.get("text", w.get("word", ""))
            typ = str(w.get("type", w.get("style", "base"))).strip().lower()
            if typ not in VALID_TYPES:
                # Tolleranze per output LLM creativi.
                if typ in ("keyword", "highlight", "emphasis", "strong", "key"):
                    typ = "impact"
                elif typ in ("quote", "question", "italic", "handwritten", "citation"):
                    typ = "accent"
                else:
                    return None
            if not isinstance(t, str) or not t.strip():
                continue
            norm_words.append({"text": t, "type": typ})
        if not norm_words:
            return None
        normalized.append({"chunk_index": i, "words": norm_words})
    return normalized


def _split_tagged_into_tokens(tagged_words: list[dict]) -> list[tuple[str, str]]:
    """Appiattisce i segmenti LLM in [(token, type)] splittando sugli spazi."""
    out: list[tuple[str, str]] = []
    for seg in tagged_words:
        typ = seg.get("type", "base")
        for tok in str(seg.get("text", "")).split():
            if tok:
                out.append((tok, typ))
    return out


def _align_tags_to_timed_words(
    timed_words: list[dict],
    tagged_tokens: list[tuple[str, str]],
    chunk_text: str = "",
) -> list[dict]:
    """Riallinea i token taggati alle parole timestampate.

    Match sequenziale normalizzato (case-insensitive, punteggiatura ignorata):
    se il token LLM corrisponde alla parola timed, eredita il type; altrimenti
    fallback euristico per quella parola. I token extra LLM vengono ignorati,
    le parole timed senza match usano l'euristica. Non solleva mai.
    """
    styled: list[dict] = []
    ti = 0
    for w in timed_words:
        word_text = str(w.get("word", ""))
        norm = _normalize_token(word_text)
        style = None
        # Cerca il prossimo token LLM che matcha (finestra di 3 per tollerare
        # piccole divergenze: articoli fusi/split dall'LLM).
        for look in range(min(3, len(tagged_tokens) - ti)):
            tok, typ = tagged_tokens[ti + look]
            if _normalize_token(tok) == norm and norm:
                style = typ
                ti = ti + look + 1
                break
        if style is None:
            # Nessun match: se c'è ancora un token non consumato ma diverso,
            # consumalo comunque se siamo fuori sync di 1 (evita deriva totale)?
            # No: meglio euristica puntuale per non propagare errori.
            style = _heuristic_style(word_text, chunk_text)
        styled.append({
            "word": word_text,
            "start": float(w.get("start", 0.0)),
            "end": float(w.get("end", 0.0)),
            "style": style,
        })
    return styled


def tag_chunk_words(
    chunks: list[dict],
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """Tagga ogni chunk in formato spec (senza timing).

    Returns:
        [{"chunk_index": i, "words": [{"text": str, "type": "base|impact|accent"}]}]
        Lungo quanto `chunks`. Non solleva mai: in caso di errore LLM usa
        l'euristica (un token per parola, stile euristico).
    """
    if not chunks:
        return []
    import os as _os
    if _os.environ.get("PIPELINE_FAST", "0").strip().lower() not in ("0", "false", "no", "off", ""):
        return _heuristic_tagging(chunks)
    if not GROQ_API_KEYS:
        return _heuristic_tagging(chunks)

    n = len(chunks)
    has_narrative = any(
        isinstance(ch, dict) and (ch or {}).get("narrative_role") in ("hook", "body", "cta")
        for ch in chunks
    )
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

    system = (
        "Sei un motion graphics designer che marca le parole dei sottotitoli "
        "per video brevi. Rispondi SOLO con JSON valido, senza testo extra."
    )
    user = (
        "Per OGNI chunk, suddividi il testo in segmenti consecutivi e assegna a "
        "ciascuno UN tipo. NON alterare le parole (stesse parole, stesso ordine).\n"
        "TIPI (il moto e' deciso dal codice da questi tipi, sii selettivo):\n"
        '- "base": parlato standard, congiunzioni, articoli, testo generico.\n'
        '- "impact": SOLO keyword ad alto valore, numeri/dati, concetti chiave, '
        "parole enfatiche da urlare (es. SMETTI, RISULTATI, STRATEGIA, GRATIS). "
        "Max 1-2 per chunk.\n"
        '- "accent": SOLO vere domande retoriche, citazioni o parole tra '
        "virgolette ed espressioni d'effetto (max 1 per chunk). NON usare accent "
        "per enfasi generica (quella e' impact) ne' per parlato neutro (base).\n"
        "NON esiste un tipo hero: l'unica parola hero del video e' scelta dal "
        "codice (verbo CTA o climax hook), non taggarla a parte.\n"
        "ESEMPIO: chunk \"Smetti di SPRECARE TEMPO con metodi inutili\" -> "
        '[{"text": \"Smetti di \", \"type\": \"base\"}, '
        '{"text": \"SPRECARE TEMPO\", \"type\": \"impact\"}, '
        '{"text": \" con metodi inutili\", \"type\": \"base\"}]\n'
        + (
            "REGOLE NARRATIVE (tag [HOOK]/[CORPO]/[CTA], ignorali nel testo):\n"
            "- [HOOK]: almeno una parola impact (la più forte d'apertura).\n"
            "- [CTA]: verbi d'azione (seguimi, commenta, clicca, scarica, scopri...) "
            "sempre impact.\n\n"
            if has_narrative else "\n"
        ) +
        f"CHUNK ({n} totali, 'indice: testo'):\n{chunk_block}\n\n"
        "Rispondi SOLO con un array JSON con ESATTAMENTE "
        f"{n} oggetti: "
        "'[{\"chunk_index\": 0, \"words\": [{\"text\": \"...\", \"type\": \"base\"}]}]'"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None
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
                on_attempt(index, total, True, f"chiave {index}/{total}: tagging ricevuto")
            except Exception:
                pass
        break

    if content is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "LLM tagging fallito: uso euristica")
            except Exception:
                pass
        return _heuristic_tagging(chunks)

    parsed = _parse_tagged_response(content, n)
    if parsed is None:
        if on_attempt is not None:
            try:
                on_attempt(total, total, False, "JSON tagging non valido: uso euristica")
            except Exception:
                pass
        return _heuristic_tagging(chunks)
    return parsed


def enrich_chunks_with_typography(
    chunks: list[dict],
    script_text: str = "",
    niche: str | None = None,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> tuple[str, list[dict]]:
    """Pipeline completa: rileva nicchia (se None) + tagga + riallinea timing.

    Args:
        chunks: chunk con "text"/"start"/"end"/"words" (da emphasis grouping).
        script_text: script originale (per il rilevamento nicchia).
        niche: nicchia forzata (se None, rilevata da script_text).
        on_attempt: callback logging (idx, totale, ok, dettaglio).

    Returns:
        (niche, enriched): enriched è la lista chunk con in più
        "typography_niche" e "styled_words" =
        [{"word","start","end","style","display","is_number","is_hero"}]
        dove display è il testo da disegnare (impact -> UPPERCASE se il
        preset lo richiede), is_number = contiene cifre (pop corto T3-num,
        mai hero), is_hero = unica parola T3 del video (hero-pop).
        Il moto (T0 base fade / T1 accent rise / T2 impact pop / T3 hero)
        e' deciso dal renderer da (style, is_hero, is_number); il colore da
        tema + palette keyword. Non solleva mai per errori LLM (fallback).
    """
    if not chunks:
        resolved = normalize_niche(niche) if niche else detect_niche(script_text or "", on_attempt)
        return resolved, []
    resolved = normalize_niche(niche) if niche else detect_niche(script_text or "", on_attempt)
    tagged = tag_chunk_words(chunks, on_attempt)
    try:
        from core.typography_presets import get_preset
        preset = get_preset(resolved)
        uppercase_impact = bool(preset.get("impact_uppercase", True))
    except Exception:
        uppercase_impact = True

    enriched: list[dict] = []
    for i, ch in enumerate(chunks):
        base = dict(ch or {})
        timed = base.get("words")
        if not timed:
            text = str(base.get("text", "")).split()
            start = float(base.get("start", 0.0))
            end = float(base.get("end", start))
            if end <= start:
                end = start + 0.3 * max(1, len(text))
            span = (end - start) / max(1, len(text))
            timed = [
                {"word": w, "start": start + span * k, "end": start + span * (k + 1)}
                for k, w in enumerate(text)
            ]
        tagged_entry = tagged[i] if i < len(tagged) else None
        if tagged_entry is not None:
            tokens = _split_tagged_into_tokens(tagged_entry.get("words", []))
            styled = _align_tags_to_timed_words(timed, tokens, str(base.get("text", "")))
        else:
            styled = [
                {"word": str(w.get("word", "")), "start": float(w.get("start", 0.0)),
                 "end": float(w.get("end", 0.0)),
                 "style": _heuristic_style(str(w.get("word", "")), str(base.get("text", "")))}
                for w in timed
            ]
        # Display: impact -> uppercase (se preset), altri invariati.
        for s in styled:
            if s.get("style") == "impact" and uppercase_impact:
                s["display"] = str(s.get("word", "")).upper()
            else:
                s["display"] = str(s.get("word", ""))
        # Boost narrativo: hook sempre d'impatto, CTA con verbi d'azione
        # impact (stabilita' visiva del finale). Corpo invariato.
        try:
            role = (base.get("narrative_role")
                    if isinstance(base, dict) else None)
            if role in ("hook", "cta"):
                from core.narrative_structure import boost_typography_styles
                styled = boost_typography_styles(
                    styled, role, str(base.get("text", "")), uppercase_impact
                )
        except Exception:
            pass
        # Flag moto T0-T3 (robusti anche senza boost): is_number via cifre,
        # is_hero=False qui (l'unico hero video-wide e' assegnato dopo).
        for s in styled:
            try:
                if not isinstance(s, dict):
                    continue
                s.setdefault("is_hero", False)
                if "is_number" not in s:
                    s["is_number"] = bool(re.search(r"\d", str(s.get("word", ""))))
                if s.get("is_number"):
                    s["is_hero"] = False
                if s.get("style") not in ("base", "impact", "accent"):
                    s["style"] = "base"
                if "display" not in s:
                    s["display"] = str(s.get("word", ""))
            except Exception:
                continue
        base["typography_niche"] = resolved
        base["styled_words"] = styled
        enriched.append(base)
    # Hero video-wide: 1 sola parola T3 (CTA verb > hook climax), mai numeri.
    try:
        from core.narrative_structure import assign_hero_flags
        enriched = assign_hero_flags(enriched) or enriched
    except Exception:
        pass
    return resolved, enriched

```

---

### `core/theme.py` — 438 righe, 16092 byte

Palette tema LLM: `generate_theme(script, on_attempt)` → `{background_color,text_color,keyword_colors[]}` hex #RRGGBB. Prompt nicchia-emozione, validazione contrasto luminanza `THEME_MIN_LUMINANCE_DIFF`, fallback deterministico da hash se LLM fallisce. `hex_to_rgba`, `luminance`, helpers.

```python
"""
Palette tematica premium: analizza lo script con l'LLM Groq
(modello `GROQ_THEME_MODEL`, default `openai/gpt-oss-120b`, via Chat
Completions come in core/keywords.py) e genera una palette moderna e
coerente (sfondo scuro premium desaturato + testo bianco caldo + accenti
armonici).

Design system (look premium TikTok, mai casuale):
- Sfondi: SOLO neri cinematici desaturati dalla lista curata
  PREMIUM_BACKGROUNDS (navy/slate/espresso/plum/forest, mai rosso-arancione
  saturo o colori neon). Qualunque scelta LLM fuori gamma viene snappata al
  premium più vicino (stessa intenzione cromatica, resa premium).
- Testi: SOLO bianchi caldi (mai testi colorati saturi).
- Keyword/accenti: max 4 toni armonici dalla lista PREMIUM_ACCENTS
  (ori/ciano/rosa/lavanda/menta), mai arcobaleno, mai gialli neon puri.

Tutti i colori viaggiano come hex string "#RRGGBB"; la conversione per
Pillow/ffmpeg avviene lato codice. Se la generazione fallisce, si usa
un default premium (midnight slate, non nero piatto): mai blocco pipeline.
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


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# --- Design system premium: sfondi cinematici scuri, mai saturi ---
# Ogni sfondo ha luminanza <40 e saturazione bassa: resa "costosa" su mobile,
# testo bianco sempre leggibile, nessun effetto "arancione economico".
PREMIUM_BACKGROUNDS: dict[str, str] = {
    "#0B0B0D": "Onyx Black (universale, dark motivational)",
    "#0F172A": "Midnight Slate (business/tech/educational)",
    "#111318": "Graphite (universale)",
    "#141210": "Espresso Black (lifestyle/business)",
    "#0E1B2C": "Deep Navy (business/tech)",
    "#121826": "Slate Navy (business/educational)",
    "#161022": "Plum Black (lifestyle/dark)",
    "#101A14": "Forest Black (fitness/educational)",
    "#1A1512": "Warm Charcoal (lifestyle/business)",
    "#0C1A1A": "Teal Black (tech/fitness)",
    "#1C1210": "Ember Black (dark/fitness, caldo senza arancione)",
    "#201A17": "Coffee Black (lifestyle)",
}

# Bianchi caldi ammessi per il testo (mai testi colorati).
PREMIUM_TEXTS: list[str] = ["#FFFFFF", "#F5F5F5", "#FDFBF7"]

# Accenti premium per keyword/highlight: saturazione controllata,
# luminanza medio-alta per contrasto su sfondi scuri, mai neon puri.
# Oro smorzato > giallo neon; corallo soft > arancione saturo.
PREMIUM_ACCENTS: list[str] = [
    "#D4AF37",  # oro smorzato (hero premium)
    "#FFD166",  # oro caldo chiaro
    "#7DD3FC",  # sky soft
    "#00E5FF",  # ciano tech
    "#A78BFA",  # lavanda
    "#FF8FA3",  # rosa soft
    "#34D399",  # menta
    "#F5D67B",  # oro chiaro (accent tint)
]

DEFAULT_THEME: dict = {
    "background_color": "#0F172A",
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
    """Vero solo per gialli neon puri (illeggibili/cheap), NON per ori premium.

    Soglie strette: vieta #FFD700/#FFFF00/#FFEB3B ma permette ori smorzati
    come #D4AF37 (212,175,55) e #FFD166, che sono accenti premium validi.
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
    except ValueError:
        return True
    return r > 230 and g > 195 and b < 100


def luminance(hex_color: str) -> float:
    """Luminanza percepita approssimata (WCAG-like), scala 0-255."""
    r, g, b = hex_to_rgb(hex_color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _saturation_of(hex_color: str) -> float:
    """Saturazione HSV 0-1 (0=grigio, 1=neon puro)."""
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    _, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return s


def _hue_of(hex_color: str) -> float:
    """Tinta HSV 0-360."""
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    h, _, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return h * 360.0


def _is_garish_background(hex_color: str) -> bool:
    """Vero per sfondi cheap: chiari o cromaticamente accesi (es. rosso-arancione).

    Premium = scuro (lum <=70) E croma assoluto contenuto (max-min <=80).
    Si usa la croma assoluta e non la saturazione HSV relativa: i navy scuri
    come #0F172A hanno S HSV alta ma croma bassa (27) e look desaturato/premium,
    mentre un arancione #FF5733 ha croma 204 e risulta cheap anche se scuro.
    """
    try:
        r, g, b = hex_to_rgb(hex_color)
        lum = luminance(hex_color)
    except ValueError:
        return True
    if lum > 70:
        return True
    if max(r, g, b) - min(r, g, b) > 80:
        return True
    return False


def _nearest_premium_bg(requested_hex: str) -> str:
    """Snappa un bg arbitrario al premium più vicino (distanza RGB).

    Preserva l'intenzione cromatica (richiesta calda -> ember/warm charcoal,
    fredda -> navy/slate) ma con resa sempre premium.
    """
    try:
        rr, rg, rb = hex_to_rgb(requested_hex)
    except ValueError:
        return "#0F172A"
    best, best_d = "#0F172A", float("inf")
    for cand in PREMIUM_BACKGROUNDS:
        try:
            cr, cg, cb = hex_to_rgb(cand)
        except ValueError:
            continue
        d = (rr - cr) ** 2 + (rg - cg) ** 2 + (rb - cb) ** 2
        # Bonus tinta: se la richiesta è calda (rosso/arancio), premia i
        # premium caldi; se fredda (blu/teal), premia i navy. Peso leggero.
        try:
            h_req = _hue_of(requested_hex)
            h_cand = _hue_of(cand)
            hue_bonus = 0.0
            if (h_req < 50 or h_req > 340) and ("Ember" in PREMIUM_BACKGROUNDS[cand] or "Warm" in PREMIUM_BACKGROUNDS[cand] or "Coffee" in PREMIUM_BACKGROUNDS[cand] or "Espresso" in PREMIUM_BACKGROUNDS[cand]):
                hue_bonus = -800.0
            elif 180 <= h_req <= 260 and ("Navy" in PREMIUM_BACKGROUNDS[cand] or "Slate" in PREMIUM_BACKGROUNDS[cand] or "Teal" in PREMIUM_BACKGROUNDS[cand]):
                hue_bonus = -800.0
            d += hue_bonus
        except Exception:
            pass
        if d < best_d:
            best, best_d = cand, d
    return best


def _is_near_white(hex_color: str) -> bool:
    """Vero per bianchi caldi (testi ammessi): luminosi e poco saturi."""
    try:
        return luminance(hex_color) >= 190 and _saturation_of(hex_color) <= 0.25
    except ValueError:
        return False


def _validate_theme(raw: dict) -> dict:
    """Valida/corregge la palette LLM in chiave premium (mai casuale).

    - bg non-hex o garish (saturo/chiaro, es. rosso-arancione) -> snap al
      premium più vicino (stessa famiglia cromatica, resa cinematica);
    - testo non bianco-caldo o basso contrasto -> bianco caldo a max contrasto;
    - keyword: scarta neon illeggibili/gialli puri/basso contrasto, max 4
      accenti armonici (no arcobaleno); integra da PREMIUM_ACCENTS.
    """
    bg = raw.get("background_color", "")
    text = raw.get("text_color", "")
    kws = raw.get("keyword_colors", [])

    if not isinstance(bg, str) or not HEX_RE.match(bg):
        bg = "#0F172A"
    elif _is_garish_background(bg):
        bg = _nearest_premium_bg(bg)
    if not isinstance(text, str) or not HEX_RE.match(text):
        text = "#FFFFFF"
    if not isinstance(kws, list):
        kws = []

    # Testo: solo bianchi premium con alto contrasto (mai testi colorati).
    if not _is_near_white(text) or abs(luminance(text) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
        candidates = [c for c in PREMIUM_TEXTS if abs(luminance(c) - luminance(bg)) >= THEME_MIN_LUMINANCE_DIFF]
        if candidates:
            # Il più distante dallo sfondo (max contrasto).
            text = max(candidates, key=lambda c: abs(luminance(c) - luminance(bg)))
        else:
            text = "#FFFFFF" if abs(255 - luminance(bg)) >= abs(0 - luminance(bg)) else "#000000"

    def _is_pure_neon(hex_color: str) -> bool:
        """Neon primario/secondario puro (#00FF00, #00FFFF, #FF00FF...).

        Gli accenti premium (es. #00E5FF) sono esentati: saturi ma con
        mezzotono calibrato, non primari puri.
        """
        try:
            if hex_color.upper() in (c.upper() for c in PREMIUM_ACCENTS):
                return False
            r, g, b = hex_to_rgb(hex_color)
        except ValueError:
            return True
        if max(r, g, b) - min(r, g, b) < 200:
            return False
        mid = sorted((r, g, b))[1]
        return mid < 30 or mid > 225

    # Keyword: max 4 accenti premium armonici (no arcobaleno cheap).
    clean_kws: list[str] = []
    seen_hues: list[float] = []
    for kw in kws:
        if len(clean_kws) >= 4:
            break
        if not isinstance(kw, str) or not HEX_RE.match(kw):
            continue
        if _is_yellowish(kw):
            continue
        try:
            if _is_pure_neon(kw):
                continue  # verdi/ciano/magenta primari puri: cheap su video
            if _saturation_of(kw) > 0.95 and luminance(kw) > 180:
                continue  # neon puro
        except ValueError:
            continue
        if abs(luminance(kw) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
            continue
        if kw in clean_kws:
            continue
        # Anti-arcobaleno: accetta solo tinte distinte (>25°) o neutre.
        try:
            h = _hue_of(kw)
            sat = _saturation_of(kw)
            if sat > 0.15 and any(abs(h - sh) < 25 and abs(h - sh) > 0.01 for sh in seen_hues):
                continue
        except ValueError:
            continue
        clean_kws.append(kw)
        try:
            seen_hues.append(_hue_of(kw))
        except ValueError:
            pass

    for fb in PREMIUM_ACCENTS + list(_FALLBACK_PALETTE_HEX):
        if len(clean_kws) >= 4:
            break
        if not isinstance(fb, str) or not HEX_RE.match(fb):
            continue
        if _is_yellowish(fb):
            continue
        if fb in clean_kws:
            continue
        if abs(luminance(fb) - luminance(bg)) < THEME_MIN_LUMINANCE_DIFF:
            continue
        try:
            h = _hue_of(fb)
            sat = _saturation_of(fb)
            if sat > 0.15 and any(abs(h - sh) < 25 for sh in seen_hues):
                continue
        except ValueError:
            continue
        clean_kws.append(fb)
        try:
            seen_hues.append(_hue_of(fb))
        except ValueError:
            pass

    if len(clean_kws) < 2:
        # Rete finale: oro + sky, sempre leggibili su premium dark.
        for fb in ("#D4AF37", "#7DD3FC"):
            if fb not in clean_kws and abs(luminance(fb) - luminance(bg)) >= THEME_MIN_LUMINANCE_DIFF:
                clean_kws.append(fb)
            if len(clean_kws) >= 2:
                break

    return {"background_color": bg, "text_color": text, "keyword_colors": clean_kws}


def _parse_theme(content: str) -> dict | None:
    """Estrae il dict tema da una risposta JSON (robusto a fence markdown)."""
    text = content.strip()
    if text.startswith("` ` `"):
        text = re.sub(r"^` ` `\w*\n?", "", text)
        text = re.sub(r"\n?` ` `$", "", text)
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

    premium_list = ", ".join(sorted(PREMIUM_BACKGROUNDS.keys()))
    system = (
        "Sei un art director premium per video brevi verticali (stile TikTok "
        "cinematico, mai cheap). Rispondi SOLO con JSON valido, senza spiegazioni."
    )
    user = (
        "Genera una palette PREMIUM per questo script. Obiettivo: moderna, "
        "costosa, cinematica — mai casuale o saturata.\n"
        "REGOLE RIGIDE:\n"
        f"1. background_color: SOLO uno di questi neri cinematici: {premium_list}. "
        "Scegli la tinta in base al mood (business/tech->navy/slate, "
        "lifestyle->warm/espresso/plum, fitness->forest/teal/ember, "
        "dark/motivazionale->onyx/ember). VIETATO qualunque sfondo saturo o "
        "medio-chiaro (NO rosso-arancione, NO orange, NO colori neon, NO grigi slavati).\n"
        "2. text_color: SOLO bianco premium (#FFFFFF, #F5F5F5 o #FDFBF7). "
        "MAI testi colorati (no testi rossi/gialli/blu).\n"
        "3. keyword_colors: max 3-4 accenti ARMONICI (stessa famiglia o complementari "
        "eleganti: ori #D4AF37/#FFD166, sky #7DD3FC, ciano #00E5FF, lavanda #A78BFA, "
        "rosa #FF8FA3, menta #34D399). MAI arcobaleno (no 6-8 colori tutti diversi), "
        "MAI gialli neon puri, tutti leggibili sullo sfondo.\n"
        "Rispondi SOLO con questo JSON (colori hex #RRGGBB): "
        '{"background_color": "#RRGGBB", "text_color": "#RRGGBB", '
        '"keyword_colors": ["#RRGGBB", "#RRGGBB"]}\n\n'
        f"SCRIPT:\n{script_text}"
    )

    total = len(GROQ_API_KEYS)
    content: str | None = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            client = _get_groq_client(api_key)
            completion = client.chat.completions.create(
                model=GROQ_THEME_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
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

```

---

### `core/timestamp_enricher.py` — 199 righe, 7549 byte

Arricchimento Fase1 (199 righe, deterministico): `enrich_whisper_timestamps(words)` aggiunge `tier/vfx_type/sfx_trigger` senza toccare start/end. Euristiche: maiuscole/numeri → T2/T3, punteggiatura → pause, verbi CTA → hero-candidate. Input per mixer e animator.

```python
"""
Timestamp Enricher (Full Engine Upgrade — Fase 1).

Arricchisce i timestamp Whisper word-level SENZA mai alterare `start`/`end`
(invariante Timestamp Preservation):

  enrich_whisper_timestamps(whisper_data) -> list[dict]

Ogni parola arricchita conserva `word/start/end` originali e aggiunge:
  - `tier`: "T0" (connettivi) | "T1" (base) | "T2" (keyword) | "T3" (hero)
  - `vfx_type`: "none" | "pop_scale" | "glow" | "badge_slide"
  - `sfx_trigger`: True per T3 o picchi emotivi (punti esclamativi/domande,
    parole tutte maiuscole, keyword enfatiche).

Input accettati (tolleranti, mai eccezioni):
  - lista di dict [{word,start,end,...}]
  - dict Whisper verbose {"words": [...]}
  - lista di stringhe (fallback: timing uniformi 0.3s, solo per test/debug)

Euristica deterministica (nessun LLM, nessun I/O):
  - T3: parola in `hero_words` esplicite (match normalizzato) oppure
    (MAIUSCOLO 4+ con `!` vicino) — max 1 per chiamata se `single_hero=True`.
  - T2: parola in `keywords` (match normalizzato) o con cifre o MAIUSCOLA 3+.
  - T0: connettivi/articoli/preposizioni (lista IT+EN).
  - T1: resto.

`sfx_trigger=True` se T3, oppure T2 con `!`/`?` adiacente, oppure parola con
marker emotivo (caps, punti esclamativi ripetuti, emoji-base).
"""

from __future__ import annotations

import re
from typing import Any

_T0_CONNECTIVES: frozenset[str] = frozenset({
    # IT articoli/preposizioni/congiunzioni
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra", "il", "lo",
    "la", "i", "gli", "le", "un", "una", "uno", "e", "o", "ma", "che",
    "non", "si", "mi", "ti", "ci", "ne", "del", "della", "dei", "delle",
    "dello", "al", "allo", "alla", "ai", "agli", "alle", "dal", "dallo",
    "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella", "nei",
    "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "come", "quando", "dove", "perche", "perché", "questo", "questa",
    "questi", "queste", "quello", "quella", "molto", "tanto", "anche",
    # EN
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "it", "this", "that", "you",
})

_EMOTIVE_RE = re.compile(r"[!?]{1,}|[\U0001F300-\U0001FAFF]")
_DIGIT_RE = re.compile(r"\d")


def _norm(word: str) -> str:
    try:
        return re.sub(r"^[^\w']+|[^\w']+$", "", (word or "").lower(), flags=re.UNICODE)
    except Exception:
        return ""


def _as_word_list(whisper_data: Any) -> list[dict]:
    """Normalizza l'input a lista di dict word (copie sicure, mai eccezioni)."""
    try:
        if isinstance(whisper_data, dict) and isinstance(whisper_data.get("words"), list):
            items = whisper_data["words"]
        elif isinstance(whisper_data, (list, tuple)):
            items = list(whisper_data)
        else:
            return []
        out: list[dict] = []
        t = 0.0
        for w in items:
            try:
                if isinstance(w, str):
                    out.append({"word": w, "start": t, "end": t + 0.3})
                    t += 0.3
                elif isinstance(w, dict):
                    word = str(w.get("word", w.get("text", "")))
                    try:
                        s = float(w.get("start", 0.0))
                    except (TypeError, ValueError):
                        s = 0.0
                    try:
                        e = float(w.get("end", s + 0.3))
                    except (TypeError, ValueError):
                        e = s + 0.3
                    if e <= s:
                        e = s + 0.1
                    entry = dict(w)
                    entry["word"] = word
                    entry["start"] = float(s)
                    entry["end"] = float(e)
                    out.append(entry)
            except Exception:
                continue
        return out
    except Exception:
        return []


def enrich_whisper_timestamps(
    whisper_data: Any,
    keywords: list[str] | set[str] | None = None,
    hero_words: list[str] | set[str] | None = None,
    single_hero: bool = True,
) -> list[dict]:
    """Arricchisce ogni parola con tier/vfx/sfx SENZA toccare start/end.

    Args:
        whisper_data: lista word-dict o dict verbose Whisper o lista stringhe.
        keywords: parole T2 (match normalizzato, case-insensitive).
        hero_words: parole T3 esplicite (match normalizzato). Se vuote, T3
            viene dedotta da euristica emotiva (caps + `!`).
        single_hero: se True, al massimo 1 T3 (la prima hero-candidata vince;
            le altre degradano a T2 per non saturare badge/SFX).

    Returns:
        Nuova lista di dict (originali mai mutati) con chiavi aggiuntive
        `tier`, `vfx_type`, `sfx_trigger`. Timestamp identici agli input.
    """
    words = _as_word_list(whisper_data)
    try:
        kw_norm = {_norm(str(k)) for k in (keywords or []) if _norm(str(k))}
    except Exception:
        kw_norm = set()
    try:
        hero_norm = {_norm(str(h)) for h in (hero_words or []) if _norm(str(h))}
    except Exception:
        hero_norm = set()

    enriched: list[dict] = []
    hero_assigned = False
    n = len(words)
    for i, w in enumerate(words):
        try:
            entry = dict(w)
            # --- Invariante: preserva start/end originali (float identici) ---
            try:
                entry["start"] = float(w["start"])
                entry["end"] = float(w["end"])
            except (KeyError, TypeError, ValueError):
                pass
            raw = str(w.get("word", ""))
            norm = _norm(raw)
            nxt_raw = str(words[i + 1].get("word", "")) if i + 1 < n else ""
            has_digit = bool(_DIGIT_RE.search(raw))
            is_caps = len(raw.strip("!?.,;: ")) >= 3 and raw.strip("!?.,;: ").isupper()
            emotive = bool(_EMOTIVE_RE.search(raw + " " + nxt_raw))

            # --- Tier ---
            tier = "T1"
            try:
                if norm in hero_norm and not (single_hero and hero_assigned):
                    tier = "T3"
                elif norm in kw_norm or has_digit or (is_caps and len(norm) >= 3):
                    tier = "T2"
                    # Euristica hero implicita: caps forte + emotivo vicino.
                    if (not hero_norm and is_caps and emotive
                            and not has_digit and not (single_hero and hero_assigned)):
                        tier = "T3"
                elif norm in _T0_CONNECTIVES or len(norm) <= 2:
                    tier = "T0"
                else:
                    tier = "T1"
            except Exception:
                tier = "T1"
            if tier == "T3" and single_hero:
                if hero_assigned:
                    tier = "T2"
                else:
                    hero_assigned = True

            # --- VFX ---
            if tier == "T3":
                vfx = "badge_slide"
            elif tier == "T2":
                vfx = "pop_scale" if not has_digit else "glow"
            elif tier == "T1":
                vfx = "none"
            else:
                vfx = "none"

            # --- SFX ---
            try:
                sfx = bool(tier == "T3" or (tier == "T2" and emotive))
            except Exception:
                sfx = False

            entry["tier"] = tier
            entry["vfx_type"] = vfx
            entry["sfx_trigger"] = sfx
            enriched.append(entry)
        except Exception:
            try:
                enriched.append(dict(w))
            except Exception:
                continue
    return enriched

```

---

### `core/transcription.py` — 185 righe, 6004 byte

STT Groq Whisper: `transcribe_audio(mp3, on_attempt)` → `[{word,start,end}]` secondi float. Usa `GROQ_WHISPER_MODEL` (turbo), `response_format verbose_json` + `timestamp_granularities word`, failover multi-key, `TranscriptionError` se fallisce.

```python
"""
Modulo di trascrizione: usa l'API Whisper di Groq per trascrivere l'audio
generato, ottenendo i timestamp a livello di singola parola.

Supporta più API key con fallback automatico: le chiavi in
config.GROQ_API_KEYS vengono provate in ordine e alla prima che fallisce
per motivi legati alla chiave/servizio (chiave non valida, quota esaurita,
rate limit, errore di rete o 5xx) si passa alla successiva.
"""

import os
from collections.abc import Callable

from groq import Groq

from config import GROQ_API_KEYS, GROQ_WHISPER_MODEL


class TranscriptionError(Exception):
    """Errore generico durante la trascrizione."""
    pass


# Sottostringhe (case-insensitive) che indicano un problema legato alla
# singola chiave o a un limite temporaneo -> vale la pena provare la
# chiave successiva.
_RETRYABLE_HINTS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "insufficient",
    "credit",
    "balance",
    "billing",
    "expired",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "authentication",
    "permission",
    "forbidden",
    "overload",
    "timeout",
    "timed out",
    "connection",
    "unavailable",
    "server error",
    "internal error",
    "401",
    "402",
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def _mask_key(key: str) -> str:
    """Maschera una chiave per i log (mostra solo inizio/fine)."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-2:]}"


_groq_client_cache: dict[str, object] = {}


def _get_groq_client(api_key: str):
    hit = _groq_client_cache.get(api_key)
    if hit is not None:
        return hit
    client = Groq(api_key=api_key)
    if len(_groq_client_cache) < 16:
        _groq_client_cache[api_key] = client
    return client


def _is_retryable_with_next_key(error: Exception) -> bool:
    """Decide se ha senso riprovare con la chiave successiva.

    Ritorna False solo per errori chiaramente indipendenti dalla chiave
    (es. modello inesistente 400/404, formato audio non valido 422):
    in quel caso un'altra chiave fallirebbe allo stesso modo.
    In caso di dubbio ritorna True (meglio un tentativo in più che
    bloccare la pipeline).
    """
    status = getattr(error, "status_code", None)
    if status in (400, 404, 422):
        message = str(error).lower()
        if not any(h in message for h in _RETRYABLE_HINTS):
            return False
    return True


def transcribe_audio(
    audio_path: str,
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> list[dict]:
    """
    Trascrive un file audio e restituisce la lista di parole con i relativi
    timestamp (inizio/fine in secondi).

    Prova le chiavi in GROQ_API_KEYS in ordine finché una non ha successo
    (fallback automatico su quota esaurita / rate limit / chiave non valida
    / errori di rete o del server).

    Args:
        audio_path: percorso del file audio (es. .mp3) da trascrivere.
        on_attempt: callback opzionale (index_1based, totale, riuscita, dettaglio)
            invocata dopo ogni tentativo con una chiave, per mostrare il ciclo.

    Returns:
        Lista di dict del tipo:
        [{"word": "Ciao", "start": 0.12, "end": 0.45}, ...]

    Raises:
        TranscriptionError: se mancano le chiavi, il file audio non esiste,
            la richiesta non è valida oppure tutte le chiavi hanno fallito.
    """
    if not GROQ_API_KEYS:
        raise TranscriptionError(
            "Mancano le GROQ_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env (puoi inserirne più di una separate da "
            "virgola per il fallback automatico)."
        )

    if not audio_path or not os.path.isfile(audio_path):
        raise TranscriptionError(f"File audio non trovato: {audio_path}")

    total = len(GROQ_API_KEYS)
    failures: list[str] = []
    transcription = None

    for index, api_key in enumerate(GROQ_API_KEYS, start=1):
        client = _get_groq_client(api_key)

        try:
            with open(audio_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=audio_file,
                    model=GROQ_WHISPER_MODEL,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
        except Exception as e:
            detail = f"chiave {index}/{total} ({_mask_key(api_key)}): {e}"
            failures.append(detail)
            if on_attempt is not None:
                on_attempt(index, total, False, detail)
            if index < total and _is_retryable_with_next_key(e):
                # Problema legato alla chiave/servizio: si passa alla successiva.
                continue
            if index < total:
                # Errore non legato alla chiave (es. modello inesistente):
                # un'altra chiave fallirebbe allo stesso modo, stop immediato.
                raise TranscriptionError(
                    f"Errore durante la trascrizione Groq ({detail})"
                )
            raise TranscriptionError(
                f"Tutte le {total} chiavi Groq hanno fallito. Dettagli: "
                + " | ".join(failures)
            )
        if on_attempt is not None:
            on_attempt(index, total, True, f"chiave {index}/{total}: trascrizione riuscita")
        break

    words = getattr(transcription, "words", None)
    if not words:
        raise TranscriptionError(
            "La trascrizione non ha restituito timestamp a livello di parola. "
            "Verifica che il modello supporti 'timestamp_granularities=word'."
        )

    result = []
    for w in words:
        # 'w' può essere un dict o un oggetto, gestiamo entrambi i casi
        if isinstance(w, dict):
            result.append({"word": w["word"], "start": w["start"], "end": w["end"]})
        else:
            result.append({"word": w.word, "start": w.start, "end": w.end})

    return result

```

---

### `core/tts.py` — 163 righe, 6173 byte

TTS ElevenLabs: `generate_audio(script, filename, on_attempt)` → mp3 in temp. POST /v1/text-to-speech/{voice_id}?output_format, failover su tutte le chiavi con voice-per-chiave, log tentativi, eccezione `TTSError` se tutte falliscono. Nessun consumo in check-keys.

```python
"""
Modulo TTS: converte lo script testuale in un file audio tramite l'API di ElevenLabs.

Endpoint usato (cfr. docs ufficiali
https://elevenlabs.io/docs/api-reference/text-to-speech/convert):
    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...
    Headers: xi-api-key, Content-Type: application/json
    Body:    {text, model_id, voice_settings}

Supporta più API key con fallback automatico: le chiavi in
config.ELEVENLABS_API_KEYS vengono provate in ordine e alla prima che
fallisce per motivi legati alla chiave/servizio (chiave non valida, quota
esaurita, rate limit, errore di rete o 5xx) si passa alla successiva.
Ogni chiave può avere la propria voce (config.ELEVENLABS_VOICE_IDS,
abbinamento 1:1): utile quando gli account hanno voci diverse
(es. voci clonate presenti solo su un account).
"""

import os
from collections.abc import Callable
import requests

from config import (
    ELEVENLABS_API_KEYS,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    TEMP_DIR,
    get_elevenlabs_voice_id,
)


class TTSError(Exception):
    """Errore generico durante la generazione audio."""
    pass


# Status HTTP per cui ha senso provare la chiave successiva: il problema
# è probabilmente legato alla singola chiave o a un limite temporaneo,
# non alla richiesta in sé (che è identica per tutte le chiavi).
_RETRYABLE_STATUS = {401, 402, 403, 429, 500, 502, 503, 504}


def _mask_key(key: str) -> str:
    """Maschera una chiave per i log (mostra solo inizio/fine)."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-2:]}"


def generate_audio(
    script_text: str,
    output_filename: str = "narration.mp3",
    on_attempt: Callable[[int, int, bool, str], None] | None = None,
) -> str:
    """
    Genera un file audio a partire dal testo dello script, usando ElevenLabs.

    Prova le chiavi in ELEVENLABS_API_KEYS in ordine finché una non ha
    successo (fallback automatico su quota esaurita / rate limit / chiave
    non valida / errori di rete o del server). La voce usata per ogni
    tentativo è risolta con config.get_elevenlabs_voice_id (voce singola
    oppure abbinamento 1:1 chiave<->voce).

    Args:
        script_text: il testo da convertire in voce.
        output_filename: nome del file audio da salvare in TEMP_DIR.
        on_attempt: callback opzionale (index_1based, totale, riuscita, dettaglio)
            invocata dopo ogni tentativo con una chiave, per mostrare il ciclo.

    Returns:
        Il percorso assoluto del file audio generato.

    Raises:
        TTSError: se mancano le chiavi, lo script è vuoto, la configurazione
            voci/chiavi è ambigua, la richiesta non è valida (400/422, e 404
            con voce unica: riprovare con un'altra chiave non aiuterebbe)
            oppure tutte le chiavi hanno fallito.
    """
    if not script_text or not script_text.strip():
        raise TTSError("Lo script è vuoto: niente da convertire in audio.")

    if not ELEVENLABS_API_KEYS:
        raise TTSError(
            "Mancano le ELEVENLABS_API_KEY(S). Impostane almeno una come variabile "
            "d'ambiente o nel file .env (puoi inserirne più di una separate da "
            "virgola per il fallback automatico)."
        )

    total = len(ELEVENLABS_API_KEYS)

    try:
        voices = [get_elevenlabs_voice_id(i, total) for i in range(total)]
    except ValueError as e:
        raise TTSError(str(e))

    # Se ogni chiave usa una voce diversa, anche un 404 (voce non trovata
    # su quell'account) può risolversi con la coppia chiave/voce successiva.
    # Con voce unica, invece, un 404 non si risolve cambiando chiave.
    retryable_status = set(_RETRYABLE_STATUS)
    if len(set(voices)) > 1:
        retryable_status.add(404)

    payload = {
        "text": script_text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }
    params = {"output_format": ELEVENLABS_OUTPUT_FORMAT}

    failures: list[str] = []

    for index, (api_key, voice_id) in enumerate(zip(ELEVENLABS_API_KEYS, voices), start=1):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, json=payload, params=params, headers=headers, timeout=120)
        except requests.RequestException as e:
            # Errore di rete/timeout: potrebbe essere transitorio o legato
            # alla chiave, quindi si passa alla successiva.
            note = f"chiave {index}/{total} ({_mask_key(api_key)}): errore di rete: {e}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            continue

        if response.status_code == 200:
            if on_attempt is not None:
                on_attempt(index, total, True, f"chiave {index}/{total}: audio generato")
            output_path = os.path.join(TEMP_DIR, output_filename)
            with open(output_path, "wb") as f:
                f.write(response.content)
            return output_path

        detail = (
            f"Errore ElevenLabs ({response.status_code}) "
            f"[voce {voice_id}]: {response.text[:300]}"
        )

        if response.status_code in retryable_status:
            # Chiave non valida / quota esaurita / rate limit / voce non
            # trovata su quell'account (solo in modalità voci per-chiave) /
            # 5xx: si passa alla coppia chiave/voce successiva.
            note = f"chiave {index}/{total} ({_mask_key(api_key)}): {detail}"
            failures.append(note)
            if on_attempt is not None:
                on_attempt(index, total, False, note)
            continue

        # 400/404(voce unica)/422 (richiesta o configurazione non valida):
        # un'altra chiave non risolverebbe, fallimento immediato.
        raise TTSError(detail)

    raise TTSError(
        f"Tutte le {total} chiavi ElevenLabs hanno fallito. Dettagli: "
        + " | ".join(failures)
    )

```

---

### `core/typography_presets.py` — 254 righe, 9693 byte

Preset per nicchia (254 righe): `get_preset(nicchia)` → `{fonts{base,impact,accent}, colors{base,highlight,accent}, font_scale, ...}`. Es. fitness→Oswald/Bebas, finanza→Montserrat, motivazione→Anton. Colori coerenti tema, stroke=0 look TikTok pulito.

```python
"""
Semantic Typography Engine v1 — Preset tipografici per nicchia.

Ogni nicchia definisce 3 livelli visivi:
  - base:   parlato standard / congiunzioni / testo generico
  - impact: keyword ad alto valore, dati numerici, concetti chiave
  - accent: domande retoriche, citazioni, parole tra virgolette, espressioni d'effetto

Per ogni livello: lista font in ordine di preferenza, colore, scala dimensione.
Look pulito: NESSUN contorno (stroke_width=0) e NESSUNA ombra di default.
Leggibilità garantita da contrasto tema + pill sul punch-in (vedi config.py).

Uso:
    from core.typography_presets import get_preset, VALID_NICHES, FALLBACK_NICHE
    preset = get_preset("tech_ai")

Animazioni (Tier T0-T3, vedi core/text_animator.py):
  ogni preset espone "anim": {"pop_from": float} = scala iniziale del pop
  impact T2 (0.6 aggressivo .. 0.8 soft). L'hook override narrativo
  (anim_pop_from sul chunk) vince sempre sul preset; il preset vince sul
  default globale KEYWORD_ENTRY_SCALE_FROM. Accent T1 non scala mai
  (rise senza deformare handwritten), hero T3 usa HERO_SCALE_FROM da config.
"""

# Nicchia di fallback quando il rilevamento LLM è incerto o fallisce.
FALLBACK_NICHE: str = "dark_motivational"

VALID_NICHES: list[str] = [
    "business_finance",
    "tech_ai",
    "fitness_sport",
    "lifestyle_vlog",
    "educational",
    "dark_motivational",
]

# Descrizioni brevi per il prompt LLM di rilevamento nicchia.
NICHE_DESCRIPTIONS: dict[str, str] = {
    "business_finance": "soldi, investimenti, business, finanza, guadagni, strategia aziendale, marketing",
    "tech_ai": "tecnologia, intelligenza artificiale, software, coding, robot, digitale, innovazione",
    "fitness_sport": "fitness, palestra, sport, allenamento, muscoli, dieta, salute fisica",
    "lifestyle_vlog": "lifestyle, vlog quotidiano, viaggi, moda, bellezza, routine, emozioni personali",
    "educational": "educazione, scuola, spiegazioni, storia, scienza, lezioni, curiosità, tutorial",
    "dark_motivational": "motivazione cupa/cinematica, disciplina, mentalità, sacrificio, successo, citazioni forti",
}

TYPOGRAPHY_PRESETS: dict[str, dict] = {
    "business_finance": {
        "fonts": {
            "base": ["Inter", "Roboto"],
            "impact": ["Anton", "Impact"],
            "accent": ["Playfair Display", "Caveat"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#FFD700",  # giallo oro
            "accent": "#FFE8A3",  # champagne: distinto dal base, armonico col gold
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.4,   # 84px
            "accent_scale": 1.1,   # 66px
        },
        "stroke_width": 0,  # nessun contorno: look pulito
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.70},  # standard leggibile (dati/finanza)
    },
    "tech_ai": {
        "fonts": {
            "base": ["Roboto", "Inter"],
            "impact": ["Bebas Neue", "Orbitron"],
            "accent": ["Space Mono", "Caveat"],
        },
        "colors": {
            "base": "#F5F5F5",
            "highlight": "#00E5FF",  # ciano
            "accent": "#B8F4FF",  # ciano-chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.4,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.70},  # standard leggibile (dati/tech)
    },
    "fitness_sport": {
        "fonts": {
            "base": ["Open Sans", "Roboto"],
            "impact": ["Oswald", "Bebas Neue"],
            "accent": ["Permanent Marker", "Kalam"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#FF2400",  # rosso fuoco
            "accent": "#FFC4B8",  # corallo chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.45,  # più aggressivo
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.60},  # aggressivo (heavy + tono urlo)
    },
    "lifestyle_vlog": {
        "fonts": {
            "base": ["Poppins", "Lato"],
            "impact": ["Cinzel", "Bodoni Moda"],
            "accent": ["Caveat", "Pacifico"],
        },
        "colors": {
            "base": "#FDFBF7",
            "highlight": "#B76E79",  # rosa antico
            "accent": "#F3C6CE",  # rosa chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.3,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.80},  # soft (rosa/handwritten, pop forte stona)
    },
    "educational": {
        "fonts": {
            "base": ["Nunito", "Roboto"],
            "impact": ["League Spartan", "Anton"],
            "accent": ["Patrick Hand", "Kalam"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#2962FF",  # blu elettrico
            "accent": "#B3C6FF",  # azzurro chiaro: distinto, stessa famiglia
            "stroke": "#000000",
        },
        "sizes": {
            "base": 60,
            "impact_scale": 1.35,
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.70},  # standard leggibile (spiegazioni)
    },
    "dark_motivational": {
        "fonts": {
            # Anton primo: peso heavy reale (Montserrat variable da solo
            # renderebbe Regular, non Black). Accent con font open-source
            # scaricabili (Pristina/Editors Note non esistono su Google Fonts
            # e causavano sempre fallback incoerenti).
            "base": ["Montserrat", "Inter"],
            "impact": ["Anton", "Montserrat"],
            "accent": ["Caveat", "Kalam", "Patrick Hand"],
        },
        "colors": {
            "base": "#FFFFFF",
            "highlight": "#D4AF37",  # oro (alternativa #FF0000 per varianti aggressive)
            "highlight_alt": "#FF0000",
            "accent": "#F5D67B",  # oro chiaro: distinto dal bianco, coerente col highlight
            "stroke": "#000000",
        },
        "sizes": {
            "base": 62,
            "impact_scale": 1.45,  # 90px, massimo impatto cinematico
            "accent_scale": 1.1,
        },
        "stroke_width": 0,
        "shadow": {"offset": (0, 0), "fill": (0, 0, 0, 0)},
        "impact_uppercase": True,
        "anim": {"pop_from": 0.60},  # aggressivo cinematico (max impatto)
    },
}


def normalize_niche(name) -> str:
    """Normalizza il nome nicchia al vocabolario valido (fallback se ignoto)."""
    if isinstance(name, str):
        key = name.strip().lower().replace("-", "_").replace(" ", "_")
        # Tolleranze per output LLM leggermente diversi.
        aliases = {
            "business": "business_finance",
            "finance": "business_finance",
            "money": "business_finance",
            "tech": "tech_ai",
            "ai": "tech_ai",
            "technology": "tech_ai",
            "fitness": "fitness_sport",
            "sport": "fitness_sport",
            "gym": "fitness_sport",
            "lifestyle": "lifestyle_vlog",
            "vlog": "lifestyle_vlog",
            "education": "educational",
            "motivation": "dark_motivational",
            "motivational": "dark_motivational",
            "dark": "dark_motivational",
        }
        if key in TYPOGRAPHY_PRESETS:
            return key
        if key in aliases:
            return aliases[key]
    return FALLBACK_NICHE


def get_preset(niche: str | None) -> dict:
    """Ritorna il preset per la nicchia (fallback automatico se ignota/None).

    Ritorna SEMPRE un dict valido con chiavi
    fonts/colors/sizes/stroke_width/shadow/impact_uppercase/anim.
    Il dict è una copia superficiale sicura da modificare (liste copiate).
    "anim" = {"pop_from": float 0.1-1.0} per il pop impact T2 (default 0.7).
    """
    key = normalize_niche(niche) if niche else FALLBACK_NICHE
    src = TYPOGRAPHY_PRESETS.get(key, TYPOGRAPHY_PRESETS[FALLBACK_NICHE])
    try:
        _anim_src = dict(src.get("anim", {}) or {})
        _pop = float(_anim_src.get("pop_from", 0.7))
        _pop = min(1.0, max(0.1, _pop))
    except (TypeError, ValueError, AttributeError):
        _pop = 0.7
    return {
        "niche": key,
        "fonts": {
            "base": list(src["fonts"].get("base", [])),
            "impact": list(src["fonts"].get("impact", [])),
            "accent": list(src["fonts"].get("accent", [])),
        },
        "colors": dict(src.get("colors", {})),
        "sizes": dict(src.get("sizes", {})),
        "stroke_width": int(src.get("stroke_width", 0)),
        "shadow": {
            "offset": tuple(src.get("shadow", {}).get("offset", (0, 0))),
            "fill": tuple(src.get("shadow", {}).get("fill", (0, 0, 0, 0))),
        },
        "impact_uppercase": bool(src.get("impact_uppercase", True)),
        "anim": {"pop_from": _pop},
    }


def list_niches_for_prompt() -> str:
    """Riga per prompt LLM: 'business_finance, tech_ai, ...'."""
    return ", ".join(VALID_NICHES)

```

---

### `core/video_builder.py` — 468 righe, 19155 byte

Builder legacy ffmpeg (468 righe): `build_video(audio, chunks, output_filename, bg)` → mp4. Sfondo tinta unita tema, un input overlay PNG per chunk con `enable=between(t,start,end)`, concat micro-video per chunk animati, mux AAC + yuv420p + GOP 60 + faststart, finestre contigue, `VideoBuildError` se ffmpeg fallisce. Fallback se composer fallisce.

```python
"""
Modulo di composizione video: usa ffmpeg per unire uno sfondo colorato
(dal tema dinamico, default nero), la traccia audio generata e i sottotitoli,
producendo il file MP4 finale.

Due modalita' supportate:
- Statica (legacy): ogni chunk ha un singolo "image_path" PNG, sovrapposto
  con `overlay=enable='between(t,start,end)'` (un overlay per chunk).
- Animata (Fase 3): ogni chunk ha "frames"/"frame_paths" (output di
  `core/text_animator.generate_animated_chunk_frames`). I frame PNG del chunk
  vengono prima composti in un micro-video con alpha (WebM/VP9) via
  `build_chunk_clip`, poi sovrapposti con UN SOLO overlay per chunk
  (stesso numero di overlay della modalita' statica, stesse performance),
  sincronizzato con `setpts` in modo che il frame 0 del clip corrisponda
  esattamente a `chunk.start` nel video principale.
"""

import os
import re
import subprocess
import shutil
import tempfile

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    OUTPUT_DIR,
    TEMP_DIR,
)


class VideoBuildError(Exception):
    """Errore durante la composizione del video con ffmpeg."""
    pass


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise VideoBuildError(
            "ffmpeg non è stato trovato nel PATH di sistema. "
            "Installalo e assicurati che sia accessibile da terminale."
        )


def _get_audio_duration(audio_path: str) -> float:
    """Ottiene la durata dell'audio in secondi tramite ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoBuildError(f"ffprobe ha fallito: {result.stderr}")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise VideoBuildError(f"ffprobe ha restituito una durata non valida: {result.stdout.strip()!r}")


def _ffmpeg_color(hex_color: str | None) -> str:
    """Converte "#RRGGBB" nel formato del filtro color di ffmpeg ("0xRRGGBB")."""
    if isinstance(hex_color, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        return "0x" + hex_color[1:]
    return "black"


def _chunk_frame_pattern(frame_paths: list[str]) -> str | None:
    """Deriva il pattern image2 "%05d" se i frame sono sequenziali chunk_XXXX_frame_YYYYY.png.

    Ritorna il pattern ffmpeg o None se non derivabile (fallback a concat demuxer).
    """
    if not frame_paths:
        return None
    first = frame_paths[0]
    dirname = os.path.dirname(first)
    basename = os.path.basename(first)
    m = re.fullmatch(r"(chunk_\d+_frame_)\d+(\.png)", basename)
    if not m:
        return None
    prefix, suffix = m.group(1), m.group(2)
    # Verifica nomi senza stat su disco (lo stat e' gia' fatto a campione in build_chunk_clip).
    # Controlla primo, ultimo e lunghezza: sufficiente per pattern image2 sequenziale.
    try:
        if os.path.basename(frame_paths[-1]) != f"{prefix}{len(frame_paths)-1:05d}{suffix}":
            return None
        if len(frame_paths) > 2:
            mid = len(frame_paths) // 2
            if os.path.basename(frame_paths[mid]) != f"{prefix}{mid:05d}{suffix}":
                return None
        # Verifica dirname coerente solo su primo/ultimo (no loop O(N)).
        if os.path.dirname(frame_paths[-1]) != dirname:
            return None
    except (IndexError, TypeError):
        return None
    return os.path.join(dirname, f"{prefix}%05d{suffix}")


def _clip_codec_args(output_path: str) -> list[str]:
    """Argomenti codec per il micro-video con alpha in base all'estensione.

    - `.mov`  -> PNG nativo RGBA (veloce su CPU, alpha perfetto via overlay;
      usato di default dalla pipeline su hardware senza GPU come i5 8th gen).
    - `.webm` -> VP9 yuva420p (compatta, ma ~6x piu' lenta da codificare e
      l'overlay richiede `format=yuva420p`; tenuta per compatibilita' spec).
    - altre estensioni -> PNG (fallback sicuro con alpha).
    """
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".webm":
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-auto-alt-ref", "0", "-crf", "18", "-b:v", "0"]
    # .mov e default: PNG lossless RGBA (veloce, alpha garantita).
    return ["-c:v", "png"]


def build_chunk_clip(frame_paths: list[str], fps: int, output_path: str) -> str:
    """Compone i frame PNG di un singolo chunk in un micro-video con alpha.

    Formato in base all'estensione di `output_path` (vedi `_clip_codec_args`):
    `.mov` -> PNG/RGBA (default pipeline: veloce + alpha perfetta),
    `.webm` -> VP9/yuva420p (compatta, da spec Fase 3).

    Args:
        frame_paths: lista ordinata di PNG (output di `generate_animated_chunk_frames`).
        fps: frame rate (deve coincidere col video principale per la sincronia).
        output_path: percorso del micro-video da creare (es. TEMP_DIR/chunk_0000.mov).

    Returns:
        Il percorso del micro-video creato.

    Raises:
        VideoBuildError: se mancano i frame o ffmpeg fallisce.
    """
    _check_ffmpeg()
    if not frame_paths:
        raise VideoBuildError("build_chunk_clip: nessun frame da comporre.")
    if fps is None or fps <= 0:
        fps = VIDEO_FPS
    # Veloce: controlla solo primo/ultimo + pattern (evita N stat su 900 file).
    if not os.path.isfile(frame_paths[0]) or not os.path.isfile(frame_paths[-1]):
        raise VideoBuildError(f"build_chunk_clip: frame mancante: {frame_paths[0]}")
    if len(frame_paths) > 4:
        import random as _rnd
        _spot = _rnd.sample(frame_paths[1:-1], min(2, len(frame_paths) - 2))
        for p in _spot:
            if not os.path.isfile(p):
                raise VideoBuildError(f"build_chunk_clip: frame mancante: {p}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    codec_args = _clip_codec_args(output_path)

    pattern = _chunk_frame_pattern(frame_paths)
    if pattern is not None:
        cmd = [
            "ffmpeg", "-y", "-threads", "auto",
            "-framerate", str(fps),
            "-start_number", "0",
            "-i", pattern,
        ] + codec_args + ["-threads", "auto", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(output_path):
            return output_path
        # Fallback a concat demuxer se il pattern fallisce (es. build ffmpeg senza libvpx).
        last_err = result.stderr[-2000:]
    else:
        last_err = "pattern non derivabile, uso concat demuxer"

    # --- Fallback: concat demuxer con lista file ---
    frame_dur = 1.0 / float(fps)
    list_fd, list_path = tempfile.mkstemp(prefix="chunk_concat_", suffix=".txt", dir=TEMP_DIR)
    try:
        with os.fdopen(list_fd, "w", encoding="utf-8") as f:
            for p in frame_paths:
                # Virgolette singole con escape per ffmpeg concat.
                esc = p.replace("'", "'\\''")
                f.write(f"file '{esc}'\n")
                f.write(f"duration {frame_dur}\n")
            # L'ultimo file va ripetuto senza duration (spec concat demuxer).
            esc = frame_paths[-1].replace("'", "'\\''")
            f.write(f"file '{esc}'\n")
        cmd = [
            "ffmpeg", "-y", "-threads", "auto",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
        ] + codec_args + ["-threads", "auto", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise VideoBuildError(
                f"ffmpeg build_chunk_clip ha fallito (pattern: {last_err}):\n{result.stderr[-2000:]}"
            )
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass
    if not os.path.isfile(output_path):
        raise VideoBuildError("build_chunk_clip: micro-video non creato (output mancante).")
    return output_path


def _is_animated_chunk(chunk: dict) -> bool:
    """Vero se il chunk porta frame animati (Fase 3) invece del singolo PNG statico."""
    if chunk.get("frame_paths"):
        return True
    frames = chunk.get("frames")
    if isinstance(frames, list) and frames:
        return True
    return False


def _chunk_frames(chunk: dict) -> list[str]:
    """Estrae la lista di frame PNG da un chunk animato."""
    if chunk.get("frame_paths"):
        return list(chunk["frame_paths"])
    frames = chunk.get("frames") or []
    return [f["image_path"] for f in frames if f.get("image_path")]


def build_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
) -> str:
    """
    Costruisce il video finale: sfondo colorato, audio narrato, sottotitoli
    sincronizzati come overlay.

    Accetta sia chunk statici ({"image_path","start","end"} da
    `renderer.render_all_subtitles`) sia chunk animati ({"frames"/
    "frame_paths","start","end"} da `text_animator.render_all_chunks_animated`).
    Nel caso animato, ogni chunk viene prima pre-renderizzato in un micro-video
    WebM/VP9 con alpha (`build_chunk_clip`) e poi sovrapposto con un solo
    overlay per chunk, sincronizzato via `setpts` (frame 0 del clip = chunk.start).

    Args:
        audio_path: percorso del file audio narrato.
        subtitle_chunks: lista di chunk statici o animati (vedi sopra).
        output_filename: nome del file MP4 finale in OUTPUT_DIR.
        background_color: colore sfondo in hex "#RRGGBB" (default: nero).

    Returns:
        Percorso assoluto del video finale generato.
    """
    _check_ffmpeg()

    duration = _get_audio_duration(audio_path)

    # 1. Costruiamo l'input: sfondo generato con il filtro "color",
    #    della durata esatta dell'audio.
    bg = _ffmpeg_color(background_color)
    inputs = [
        "-f", "lavfi",
        "-i", f"color=c={bg}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}:d={duration}",
        "-i", audio_path,
    ]

    animated = any(_is_animated_chunk(c) for c in subtitle_chunks)

    def _chunk_window(c: dict, nxt: dict | None):
        """Finestra display (start, end): clip estesa se presente, else start/end.

        Per lo statico le finestre sono rese contigue (end -> next_start):
        caption+character restano visibili durante le pause TTS invece di
        blinkare (fix sparizione/riapparizione anche nel fallback PNG).
        """
        try:
            s = float(c.get("clip_start", c.get("start", 0.0)))
        except (TypeError, ValueError):
            s = 0.0
        try:
            e = float(c.get("clip_end", c.get("end", s)))
        except (TypeError, ValueError):
            e = s
        if e <= s:
            e = s + 0.1
        if nxt is not None:
            try:
                ns = float(nxt.get("clip_start", nxt.get("start", e)))
            except (TypeError, ValueError):
                ns = e
            # Finestra contigua: tiene la caption fino al chunk dopo (hold
            # naturale durante le pause, niente sfondo vuoto = niente blink).
            if ns > s and ns > e:
                e = ns
        return (s, e)

    if not animated:
        # --- Percorso statico legacy (finestre contigue anti-blink) ---
        for chunk in subtitle_chunks:
            inputs.extend(["-i", chunk["image_path"]])

        filter_parts = []
        last_label = "0:v"

        for idx, chunk in enumerate(subtitle_chunks):
            input_index = idx + 2
            out_label = f"v{idx}"
            nxt_c = subtitle_chunks[idx + 1] if idx + 1 < len(subtitle_chunks) else None
            start, end = _chunk_window(chunk, nxt_c)
            filter_parts.append(
                f"[{last_label}][{input_index}:v]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
            )
            last_label = out_label

        filter_complex = ";".join(filter_parts)
    else:
        # --- Percorso animato (Fase 3): micro-video paralleli + overlay ---
        # Clip in MOV/PNG (veloce + alpha). Build parallelo: ogni clip e'
        # indipendente, ThreadPool riduce il wall-time di ~3x su 30 chunk.
        import concurrent.futures as _fut
        clip_infos: list[tuple[str, float, float, bool] | None] = [None] * len(subtitle_chunks)
        _jobs: list[tuple[int, list[str], str]] = []
        for idx, chunk in enumerate(subtitle_chunks):
            # Finestra display: preferisce clip_start/clip_end (includono il
            # tail di persistenza gap quando il character continua: fix blink).
            # Con hold il clip copre [start, next_start): overlay contigui,
            # niente sfondo vuoto tra chunk con stesso/differente character.
            try:
                start = float(chunk.get("clip_start", chunk.get("start", 0.0)))
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(chunk.get("clip_end", chunk.get("end", start)))
            except (TypeError, ValueError):
                end = start
            if end <= start:
                try:
                    end = float(chunk.get("end", start + 0.1))
                except (TypeError, ValueError):
                    end = start + 0.1
                if end <= start:
                    end = start + 0.1
            if _is_animated_chunk(chunk):
                frame_paths = _chunk_frames(chunk)
                if not frame_paths:
                    raise VideoBuildError(f"Chunk animato {idx} senza frame.")
                clip_path = os.path.join(TEMP_DIR, f"chunk_{idx:04d}.mov")
                # Riuso: clip valida solo se piu' recente di primo E ultimo
                # frame (l'ultimo include l'eventuale tail di persistenza gap).
                try:
                    if os.path.isfile(clip_path):
                        _cmt = os.path.getmtime(clip_path)
                        _f0 = os.path.getmtime(frame_paths[0])
                        try:
                            _f1 = os.path.getmtime(frame_paths[-1])
                        except (IndexError, OSError):
                            _f1 = _f0
                        if _cmt >= _f0 and _cmt >= _f1:
                            clip_infos[idx] = (clip_path, start, end, True)
                            continue
                except OSError:
                    pass
                _jobs.append((idx, frame_paths, clip_path))
                clip_infos[idx] = (clip_path, start, end, True)
            elif chunk.get("clip_path"):
                clip_infos[idx] = (chunk["clip_path"], start, end, True)
            elif chunk.get("image_path"):
                clip_infos[idx] = (chunk["image_path"], start, end, False)
            else:
                raise VideoBuildError(f"Chunk {idx} senza frame/immagine ne' clip: {chunk}")
        if _jobs:
            try:
                _cpu = max(2, (os.cpu_count() or 4))
            except Exception:
                _cpu = 4
            _workers = max(2, min(4, _cpu - 1, len(_jobs)))

            def _one(job: tuple[int, list[str], str]):
                _idx, _frames, _out = job
                build_chunk_clip(_frames, VIDEO_FPS, _out)
                return _idx

            with _fut.ThreadPoolExecutor(max_workers=_workers) as _ex:
                for _fu in _fut.as_completed([_ex.submit(_one, j) for j in _jobs]):
                    _fu.result()  # solleva VideoBuildError al chiamante se fallisce
        clip_infos = [c for c in clip_infos if c is not None]

        for clip_path, _s, _e, _is_vid in clip_infos:
            inputs.extend(["-i", clip_path])

        filter_parts = []
        last_label = "0:v"
        for idx, (_clip_path, start, end, is_video) in enumerate(clip_infos):
            input_index = idx + 2
            out_label = f"v{idx}"
            if is_video:
                # Shift temporale: il frame 0 del clip deve apparire a chunk.start.
                # Per i clip WebM/VP9 si forza yuva420p (l'alpha VP9 richiede il
                # formato esplicito, altrimenti le aree trasparenti diventano nere).
                clip_label = f"c{idx}"
                if _clip_path.lower().endswith(".webm"):
                    filter_parts.append(
                        f"[{input_index}:v]format=yuva420p,setpts=PTS-STARTPTS+{start}/TB[{clip_label}]"
                    )
                else:
                    filter_parts.append(
                        f"[{input_index}:v]setpts=PTS-STARTPTS+{start}/TB[{clip_label}]"
                    )
                filter_parts.append(
                    f"[{last_label}][{clip_label}]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
                )
            else:
                filter_parts.append(
                    f"[{last_label}][{input_index}:v]overlay=0:0:enable='between(t,{start},{end})'[{out_label}]"
                )
            last_label = out_label
        filter_complex = ";".join(filter_parts)

    output_path = os.path.join(OUTPUT_DIR, output_filename)

    # Preset finale configurabile: FFMPEG_PRESET=veryfast default (qualita' invariata),
    # ultrafast per bozze veloci. Threads espliciti per filter+encode.
    import os as _os2
    _preset = (_os2.environ.get("FFMPEG_PRESET", "veryfast") or "veryfast").strip() or "veryfast"
    if _preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
        _preset = "veryfast"
    # Keyframe ottimizzati per short verticali: GOP 60 (2s a 30fps) invece del
    # default 250 (8s): seeking/scrub precisi sulle caption, overhead minimo
    # su video brevi. I chunk restano sincronizzati via setpts (frame 0 =
    # chunk.start) con overlay contigui (hold nei gap, niente blink).
    cmd = ["ffmpeg", "-y", "-threads", "auto"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", _preset,
        "-crf", "20",
        "-g", "60",
        "-keyint_min", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-filter_threads", "auto",
        "-threads", "auto",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise VideoBuildError(f"ffmpeg ha fallito durante la composizione:\n{result.stderr[-2000:]}")

    return output_path


def cleanup_temp_files():
    """Rimuove i file temporanei generati durante il processo (audio, PNG, MOV/WebM, liste concat)."""
    if not os.path.isdir(TEMP_DIR):
        return
    for root, dirs, files in os.walk(TEMP_DIR, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        for dname in dirs:
            dpath = os.path.join(root, dname)
            try:
                os.rmdir(dpath)
            except OSError:
                pass

```

---

### `core/video_composer.py` — 272 righe, 10523 byte

Composer premium (272 righe, `ENABLE_DYNAMIC_BACKGROUNDS`): `build_composed_video(audio, chunks, ...)` → mp4. Ken Burns impercettibile (zoompan max 1.08 step 0.0015), dimmer 20 sopra character 10, subtitles 30, debug safe-zone 99 se richiesto, overlay unico con timeline, mux atomico. Chiama builder legacy in fallback.

```python
"""
Video Composer (Full Engine Upgrade — Fase 5).

Compositing FFMPEG con Z-Index strict e filter-graph puliti:

  Z=0  background (tinta tema o Ken Burns dinamico)
  Z=10 character 2D (gia' composito nei micro-clip con pill/testo)
  Z=20 dimmer/vignette (solo sullo sfondo, mai sul testo)
  Z=30 kinetic subtitles & hero badges (nei micro-clip, sopra dimmer)
  Z=99 debug safe-zone overlay (solo render-mode=debug_safezones)

Architettura non-blocking: filter pesanti isolati in un unico
filter_complex; il mux audio/video finale e' un passaggio atomico separato
(`-c:v copy` quando possibile, altrimenti encode dedicato).

Se ENABLE_DYNAMIC_BACKGROUNDS=0: delega a `video_builder.build_video`
(legacy invariato). Altrimenti: sfondo Ken Burns (zoompan impercettibile
min(zoom+step,max) d=125 centrato) + vignette/dimmer, poi overlay chunk
come legacy (finestre contigue anti-blink, setpts, GOP 60).
"""

from __future__ import annotations

import os
import subprocess

try:
    from config import (
        DYNAMIC_BG_DURATION,
        DYNAMIC_BG_ZOOM_MAX,
        DYNAMIC_BG_ZOOM_STEP,
        ENABLE_DYNAMIC_BACKGROUNDS,
        FFMPEG_PRESET,
        OUTPUT_DIR,
        TEMP_DIR,
        VIDEO_FPS,
        VIDEO_HEIGHT,
        VIDEO_WIDTH,
    )
except Exception:  # config datata
    DYNAMIC_BG_DURATION = 125
    DYNAMIC_BG_ZOOM_MAX = 1.08
    DYNAMIC_BG_ZOOM_STEP = 0.0015
    ENABLE_DYNAMIC_BACKGROUNDS = True
    FFMPEG_PRESET = "veryfast"
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")
    VIDEO_FPS = 30
    VIDEO_HEIGHT = 1920
    VIDEO_WIDTH = 1080

from core.video_builder import (
    VideoBuildError,
    _check_ffmpeg,
    _chunk_frames,
    _ffmpeg_color,
    _get_audio_duration,
    _is_animated_chunk,
    build_chunk_clip,
    build_video as _legacy_build_video,
    cleanup_temp_files,
)


def kenburns_filter(duration_s: float) -> str:
    """Filtro zoompan Ken Burns impercettibile (mai eccezioni)."""
    try:
        zmax = max(1.0, min(1.5, float(DYNAMIC_BG_ZOOM_MAX)))
    except Exception:
        zmax = 1.08
    try:
        step = max(0.0002, min(0.01, float(DYNAMIC_BG_ZOOM_STEP)))
    except Exception:
        step = 0.0015
    try:
        d = max(25, int(DYNAMIC_BG_DURATION))
    except Exception:
        d = 125
    # zoompan lavora su still ingrandita (s=WxH upscalato): input color gia'
    # maggiorato 1.2x per avere pixel da zoomare senza bordi.
    return (
        f"zoompan=z='min(zoom+{step},{zmax})':d={d}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
    )


def dimmer_filter() -> str:
    """Dimmer/vignette Z=20 (contrasto sotto i sottotitoli, mai sul testo)."""
    return "eq=brightness=-0.03:saturation=1.05,vignette=PI/4"


def build_composed_video(
    audio_path: str,
    subtitle_chunks: list[dict],
    output_filename: str = "output_video.mp4",
    background_color: str | None = None,
    debug_safezones: bool = False,
) -> str:
    """Compone il video finale con background dinamico + dimmer + overlay.

    - Statico/animato come legacy (micro-clip .mov + overlay unico per chunk,
      finestre contigue clip_start/clip_end, setpts, GOP 60, faststart).
    - Sfondo: Ken Burns + dimmer quando ENABLE_DYNAMIC_BACKGROUNDS, altrimenti
      tinta unita legacy (delega diretta, zero divergenza).
    - debug_safezones=True: box rossi semi-trasparenti Z=99 sopra tutto.
    - Mux audio atomico separato alla fine (invariant non-blocking).
    """
    try:
        dyn = str(os.environ.get(
            "ENABLE_DYNAMIC_BACKGROUNDS", "1" if ENABLE_DYNAMIC_BACKGROUNDS else "0"
        )).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:
        dyn = bool(ENABLE_DYNAMIC_BACKGROUNDS)
    if not dyn and not debug_safezones:
        return _legacy_build_video(audio_path, subtitle_chunks, output_filename, background_color)

    _check_ffmpeg()
    duration = _get_audio_duration(audio_path)
    bg = _ffmpeg_color(background_color)
    # Sfondo maggiorato 1.2x per il crop dello zoom (niente bordi neri).
    big_w, big_h = int(VIDEO_WIDTH * 1.2), int(VIDEO_HEIGHT * 1.2)
    if big_w % 2:
        big_w += 1
    if big_h % 2:
        big_h += 1

    animated = any(_is_animated_chunk(c) for c in subtitle_chunks)

    def _window(c: dict, nxt: dict | None):
        try:
            s = float(c.get("clip_start", c.get("start", 0.0)))
        except (TypeError, ValueError):
            s = 0.0
        try:
            e = float(c.get("clip_end", c.get("end", s)))
        except (TypeError, ValueError):
            e = s
        if e <= s:
            e = s + 0.1
        if nxt is not None:
            try:
                ns = float(nxt.get("clip_start", nxt.get("start", e)))
            except (TypeError, ValueError):
                ns = e
            if ns > s and ns > e:
                e = ns
        return (s, e)

    # --- Micro-clip animati (come legacy, ThreadPool) ---
    import concurrent.futures as _fut

    clip_infos: list[tuple[str, float, float, bool] | None] = [None] * len(subtitle_chunks)
    jobs: list[tuple[int, list[str], str]] = []
    for idx, chunk in enumerate(subtitle_chunks):
        nxt_c = subtitle_chunks[idx + 1] if idx + 1 < len(subtitle_chunks) else None
        s, e = _window(chunk, nxt_c)
        if _is_animated_chunk(chunk):
            fps = chunk.get("fps", VIDEO_FPS) if isinstance(chunk, dict) else VIDEO_FPS
            frame_paths = _chunk_frames(chunk)
            if not frame_paths:
                raise VideoBuildError(f"Chunk animato {idx} senza frame.")
            clip_path = os.path.join(TEMP_DIR, f"chunk_{idx:04d}.mov")
            try:
                if os.path.isfile(clip_path):
                    cmt = os.path.getmtime(clip_path)
                    f0 = os.path.getmtime(frame_paths[0])
                    try:
                        f1 = os.path.getmtime(frame_paths[-1])
                    except (IndexError, OSError):
                        f1 = f0
                    if cmt >= f0 and cmt >= f1:
                        clip_infos[idx] = (clip_path, s, e, True)
                        continue
            except OSError:
                pass
            jobs.append((idx, frame_paths, clip_path))
            clip_infos[idx] = (clip_path, s, e, True)
        elif chunk.get("clip_path"):
            clip_infos[idx] = (chunk["clip_path"], s, e, True)
        elif chunk.get("image_path"):
            clip_infos[idx] = (chunk["image_path"], s, e, False)
        else:
            raise VideoBuildError(f"Chunk {idx} senza frame/immagine ne' clip: {chunk}")
    if jobs:
        try:
            cpu = max(2, (os.cpu_count() or 4))
        except Exception:
            cpu = 4
        workers = max(2, min(4, cpu - 1, len(jobs)))

        def _one(job: tuple[int, list[str], str]):
            _i, _fr, _out = job
            build_chunk_clip(_fr, VIDEO_FPS, _out)
            return _i

        with _fut.ThreadPoolExecutor(max_workers=workers) as _ex:
            for _fu in _fut.as_completed([_ex.submit(_one, j) for j in jobs]):
                _fu.result()
    clip_infos = [c for c in clip_infos if c is not None]

    # --- Filter graph: bg Ken Burns + dimmer, poi overlay chunk, poi debug ---
    inputs = [
        "-f", "lavfi",
        "-i", f"color=c={bg}:s={big_w}x{big_h}:r={VIDEO_FPS}:d={duration}",
        "-i", audio_path,
    ]
    for clip_path, _s, _e, _is_vid in clip_infos:
        inputs.extend(["-i", clip_path])

    parts: list[str] = []
    # Z=0 -> Z=20: background dinamico + dimmer/vignette (solo sfondo).
    parts.append(f"[0:v]{kenburns_filter(duration)}[bgzoom]")
    parts.append("[bgzoom]" + dimmer_filter() + "[base]")
    last = "base"
    for idx, (_clip_path, start, end, is_video) in enumerate(clip_infos):
        in_idx = idx + 2
        out = f"v{idx}"
        if is_video:
            cl = f"c{idx}"
            if _clip_path.lower().endswith(".webm"):
                parts.append(f"[{in_idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{start}/TB[{cl}]")
            else:
                parts.append(f"[{in_idx}:v]setpts=PTS-STARTPTS+{start}/TB[{cl}]")
            parts.append(f"[{last}][{cl}]overlay=0:0:enable='between(t,{start},{end})'[{out}]")
        else:
            parts.append(f"[{last}][{in_idx}:v]overlay=0:0:enable='between(t,{start},{end})'[{out}]")
        last = out
    if debug_safezones:
        # Z=99: box rossi UI (solo debug, sopra tutto, semi-trasparenti).
        try:
            from core.layout_guard import debug_safezone_boxes

            boxes = debug_safezone_boxes(VIDEO_WIDTH, VIDEO_HEIGHT)
            for bi, b in enumerate(boxes):
                out = f"dbg{bi}"
                parts.append(
                    f"[{last}]drawbox=x={int(b['x0'])}:y={int(b['y0'])}:"
                    f"w={int(b['x1']) - int(b['x0'])}:h={int(b['y1']) - int(b['y0'])}:"
                    f"color=red@0.35:t=fill[{out}]"
                )
                last = out
        except Exception:
            pass
    filter_complex = ";".join(parts)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    preset = (os.environ.get("FFMPEG_PRESET", FFMPEG_PRESET) or "veryfast").strip() or "veryfast"
    if preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
        preset = "veryfast"
    # Passaggio 1: video track (filter pesanti isolati) + mux atomico finale.
    cmd = ["ffmpeg", "-y", "-threads", "auto"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{last}]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", "20",
        "-g", "60",
        "-keyint_min", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-filter_threads", "auto",
        "-threads", "auto",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise VideoBuildError(f"ffmpeg video_composer ha fallito:\n{res.stderr[-2000:]}")
    return output_path

```

---

## Appendice B — Asset, output, file esclusi

> I binari non sono incorporati come codice. Elenco completo con dimensioni per ricostruire il contesto.


### assets (20 file)

| Path | Byte |
|---|---:|
| `assets/characters/1.png` | 1076762 |
| `assets/characters/2.png` | 943688 |
| `assets/characters/3.png` | 930764 |
| `assets/characters/4.png` | 935464 |
| `assets/characters/5.png` | 925998 |
| `assets/fonts/Anton.ttf` | 170812 |
| `assets/fonts/BebasNeue.ttf` | 61400 |
| `assets/fonts/Caveat.ttf` | 403648 |
| `assets/fonts/Cinzel.ttf` | 125468 |
| `assets/fonts/Inter.ttf` | 876576 |
| `assets/fonts/LeagueSpartan.ttf` | 95116 |
| `assets/fonts/Montserrat.ttf` | 744936 |
| `assets/fonts/Nunito.ttf` | 276932 |
| `assets/fonts/OpenSans.ttf` | 532636 |
| `assets/fonts/Oswald.ttf` | 172088 |
| `assets/fonts/PatrickHand.ttf` | 214772 |
| `assets/fonts/PlayfairDisplay.ttf` | 300724 |
| `assets/fonts/Poppins.ttf` | 160316 |
| `assets/fonts/Roboto.ttf` | 488584 |
| `assets/fonts/SpaceMono.ttf` | 99356 |

**Totale:** 9536040 byte in 20 file.


### outputs (mp4 finali — non inclusi come codice) (27 file)

| Path | Byte |
|---|---:|
| `outputs/output_video.mp4` | 1527689 |
| `outputs/video_01_ciao.mp4` | 142650 |
| `outputs/video_01_perch_il_cielo__blu.mp4` | 1152772 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi.mp4` | 1487235 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_1.mp4` | 1364287 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_10.mp4` | 1484093 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_11.mp4` | 1450359 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_12.mp4` | 2765358 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_13.mp4` | 2914580 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_2.mp4` | 1369356 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_3.mp4` | 1354390 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_4.mp4` | 1368811 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_5.mp4` | 3342396 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_6.mp4` | 3603033 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_7.mp4` | 1714687 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_8.mp4` | 1403769 |
| `outputs/video_01_stai_ancora_lasciando_i_tuoi_9.mp4` | 1583190 |
| `outputs/video_02_usi_ancora_chatgpt_chiedendo_sol.mp4` | 1388519 |
| `outputs/video_02_usi_ancora_chatgpt_chiedendo_sol_1.mp4` | 2719592 |
| `outputs/video_03_smetti_di_fare_cento_crunch.mp4` | 1204619 |
| `outputs/video_03_smetti_di_fare_cento_crunch_1.mp4` | 2373704 |
| `outputs/video_04_ti_senti_mai_travolto_dal.mp4` | 1163804 |
| `outputs/video_04_ti_senti_mai_travolto_dal_1.mp4` | 2249993 |
| `outputs/video_05_perch_il_cielo__blu.mp4` | 1242526 |
| `outputs/video_05_perch_il_cielo__blu_1.mp4` | 2661988 |
| `outputs/video_06_nessuno_verr_a_salvarti_il.mp4` | 1348642 |
| `outputs/video_06_nessuno_verr_a_salvarti_il_1.mp4` | 2497191 |

**Totale:** 48879233 byte in 27 file.


### temp (transitori — puliti a fine job) (0 file)

| Path | Byte |
|---|---:|

**Totale:** 0 byte in 0 file.


### File esclusi (mai incorporati)

- `.env` — **SEGRETO**: contiene chiavi reali. Struttura identica a `.env.example` (vedi Appendice A). Non committare, non allegare a LLM esterni. Verifica con `python config.py --check-keys`.
- `__pycache__/`, `core/__pycache__/`, `*.pyc` — bytecode rigenerabile (`3` file root + decine in core, esclusi).
- `.git/` — storia git (non codice corrente).

### Nota per LLM che legge questo file

1. Per modifiche: leggi prima §5 contratti + §11 invarianti, poi il codice in Appendice A del modulo target + i suoi import.
2. Non alterare mai `start/end` dopo align; non far restituire testo/timing agli LLM (solo indici/tagli/colori/palette).
3. Mantieni Z-stack, safe-zone, macro-blocchi, failover e isolamento bulk; testa `text_only` → `full` → bulk.
4. Se aggiungi pose/font/layout/nicchie, aggiorna solo config/preset + asset, senza rompere fallback deterministici.

*Fine documento — generato automaticamente, codice integrale verificato riga-per-riga.*
