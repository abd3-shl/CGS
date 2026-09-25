# CGS — Report Completo, Dettagliato e Ottimizzato per LLM

> **Scopo di questo documento:** permettere a **qualsiasi altro LLM** di comprendere al 100% funzionalità, struttura, logica, contratti dati, dipendenze e invarianti del progetto **CGS (Video Generator v2)** per applicare modifiche in maniera coerente senza regressioni.
> **Lingua:** Italiano. **Root progetto:** `C:\Users\thinkpad\Desktop\CGS` (repo git). **Piattaforma primaria:** Windows + Python + ffmpeg.
> **Stile video prodotto:** verticale 9:16 (1080x1920 @30fps), sfondo tinta unita premium, audio narrato, sottotitoli animati per-parola stile TikTok, personaggi 2D overlay, tipografia semantica per nicchia, struttura narrativa hook/corpo/CTA.
> **Ultimo aggiornamento:** 25/09/2026 — allineato al codice reale (commit `61985b5 upgrade 24/09/26 1`). Sostituisce e aggiorna la versione precedente del report (463 righe).

---

## 1. Visione d'insieme e pipeline

### 1.1 Cosa fa il programma
1. L'utente carica uno script `.txt` dalla GUI Tkinter (`main.py`).
2. Modalità **singola**: tutto il testo = 1 script = 1 video. Modalità **bulk** (checkbox): ogni riga non vuota = 1 script indipendente = 1 video (es. 10 righe = 10 video).
3. Per **ogni singolo script** viene eseguita una pipeline a 8+ step (in thread separato per non bloccare la GUI):
   - `Step 1-2 (parallelo x2)`: Tema colori LLM (Groq) + Audio TTS (ElevenLabs).
   - `Step 3`: Trascrizione audio con timestamp parola-per-parola (Groq Whisper).
   - `Step 4`: Riallineamento trascrizione → script originale (tempi Whisper, parole script).
   - `Step 5`: Raggruppamento in chunk 2-3 parole per enfasi (LLM + fallback).
   - `Step 5.2`: Classificazione narrativa hook/corpo-a-beat/CTA (deterministica) + `assign_hero_flags` (1 parola hero T3 per video).
   - `Step 5.5-6.5 (parallelo x3)`: Piano personaggi + Estrazione keyword + Analisi tipografica (nicchia → tagging base/impact/accent + flag `is_hero`/`is_number`).
   - `Step 6.8`: Layout Guard real-time anti-overlap + ancoraggio macro-blocchi.
   - `Step 7`: Rendering frame animati per-parola Tier T0-T3 (Pillow + easing + idle breathing + morph + gap-hold tail) o fallback PNG statici.
   - `Step 8`: Composizione video finale ffmpeg (micro-video per chunk + overlay unico, finestre contigue anti-blink, GOP 60) → `outputs/`.
   - Cleanup `temp/` dopo ogni video (isolamento bulk).

### 1.2 Stack tecnologico
- **GUI:** `tkinter` standard (no dipendenze esterne), `ScrolledText` per preview/log.
- **TTS:** `requests` → `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...`
- **LLM + STT:** SDK `groq` (`Groq`, `chat.completions.create`, `audio.transcriptions.create`).
- **Imaging:** `Pillow` (`Image`, `ImageDraw`, `ImageFont`, `ImageColor.getrgb`, `ImageFont` variable axes per weight 600).
- **Video/Audio:** binari esterni `ffmpeg` + `ffprobe` invocati via `subprocess` (obbligatori in PATH).
- **Config env:** `python-dotenv` (con fallback parser integrato se mancante).
- **NLP leggera:** `difflib.SequenceMatcher`, `re`, `hashlib.md5`, `colorsys`, `json`.
- **Concorrenza:** `threading.Thread` (GUI), `concurrent.futures.ThreadPoolExecutor` (parallelo pipeline/render/ffmpeg).
- **Asset:** `assets/characters/1.png..5.png`, `assets/fonts/*.ttf` (15 font committati + download on-demand).
- **Novità architetturali rispetto al report precedente:** `core/character_animator.py` (ciclo vita ENTRY/SUSTAIN/EXIT/NONE), macro-blocchi stabili “Breath & Focus”, Tier T0-T3 con hero + numeri, `TYPOGRAPHY_BASE_WEIGHT=600`, `CHARACTER_POSE_SIDE_MAP` configurabile, gap-hold tail anti-blink, GOP 60/keyint 30.

### 1.3 Requisiti runtime
- `ffmpeg -version` e `ffprobe` in PATH. Senza → `VideoBuildError` esplicito.
- `pip install -r requirements.txt`: `requests>=2.31.0`, `groq>=0.9.0`, `Pillow>=10.0.0`, `python-dotenv>=1.0.0`.
- API keys in `.env` (root progetto, mai committato, vedi `.gitignore`) o variabili sistema. Comando verifica gratuita: `python config.py --check-keys`.
- Avvio: `python main.py`.

---

## 2. Struttura file completa (inventario esaustivo, conteggi reali)

```
CGS/
├── main.py                    # GUI Tkinter + orchestratore pipeline bulk (582 righe)
├── config.py                  # Config centrale, env, multi-key, pose-side-map, check-keys (483 righe)
├── requirements.txt           # 4 dipendenze
├── .env                       # Segreti reali (NON committare, in .gitignore)
├── .env.example               # Template documentato (tutte le nuove flag commentate)
├── README.md                  # Doc utente v2 (pipeline 10 step, setup, limiti) — parzialmente obsoleto, vedi nota sotto
├── .gitignore                 # .env, __pycache__/, *.pyc
├── cgs-report-completo.md     # Questo report (aggiornato 25/09/2026)
├── core/
│   ├── tts.py                 # TTS ElevenLabs multi-key failover (163 righe)
│   ├── transcription.py       # Whisper Groq word-timestamps + failover (185 righe)
│   ├── alignment.py           # Riallineamento difflib script↔trascrizione (120 righe)
│   ├── theme.py               # Palette premium LLM + validazione (438 righe)
│   ├── emphasis_grouping.py   # Chunk 2-3 parole LLM + fallback (211 righe)
│   ├── subtitle_grouping.py   # Grouping classico per frasi legacy (144 righe)
│   ├── keywords.py            # Keyword LLM + colori deterministici (215 righe)
│   ├── script_loader.py       # Parsing bulk + slug/naming output (123 righe)
│   ├── renderer.py            # PNG statici + layout/character core (672 righe)
│   ├── text_animator.py       # Frame animati Tier T0-T3 + character motion + CTA card (3323 righe, +1020 vs report prec.)
│   ├── video_builder.py       # ffmpeg finale + micro-clip + finestre contigue + GOP60 (468 righe, +54)
│   ├── character_selector.py  # Piano personaggi LLM + macro-blocchi Breath&Focus (2015 righe, +1019)
│   ├── character_animator.py  # NUOVO: ciclo vita ENTRY/SUSTAIN/EXIT/NONE + idle_weight (169 righe)
│   ├── narrative_structure.py # Hook/beat/CTA deterministico + assign_hero_flags (506 righe, +98)
│   ├── text_tagger.py         # Nicchia + tagging base/impact/accent + is_hero/is_number (690 righe, +31)
│   ├── typography_presets.py  # 6 preset nicchia + anim.pop_from per nicchia (254 righe, +22)
│   ├── font_manager.py        # Download/cache font Google Fonts + PermanentMarker (416 righe)
│   ├── layout_presets.py      # 4 zone layout + geometria + pose-side doc (319 righe, +28)
│   ├── layout_guard.py        # Guard anti-overlap + ancoraggio macro-blocchi (805 righe, +123)
│   └── easing.py              # Curve Penner + quad/in_out per character (135 righe, +34)
├── assets/
│   ├── characters/1.png..5.png  # 5 PNG 768x1376 con sfondo nero da pulire (~0.9-1.0 MB cad.)
│   └── fonts/*.ttf (15)         # Anton, BebasNeue, Caveat, Cinzel, Inter, LeagueSpartan, Montserrat, Nunito, OpenSans, Oswald, PatrickHand, PlayfairDisplay, Poppins, Roboto, SpaceMono
├── outputs/*.mp4 (20)         # Video finali (es. video_01_slug.mp4, output_video.mp4 legacy, serie stai_ancora...)
└── temp/                      # File temporanei (narration_*.mp3, subtitle_*.png, chunk_*_frame_*.png, chunk_*.mov, concat lists) — svuotata dopo ogni video
```

> **Nota README obsoleto:** descrive `core/renderer.py` + overlay per chunk come architettura v2 base; il codice attuale ha evoluto in `text_animator.py` Tier T0-T3 + personaggi macro-blocchi + tipografia + narrativa + guard + hero + gap-hold. Il README resta valido per setup/env ma non per i nuovi sottosistemi.
> **Nota refactor recenti (git log):** rimossi `core/character_geometry.py` (1171 righe, fuso in selector/renderer), `tests/test_character_layout.py` (285 righe), `README-dev.md` (117 righe), `assets/fonts/PermanentMarker.ttf` (ora scaricato on-demand via `_FONT_FILES["permanentmarker"]`). Commit principali: `a924cd0 upgrade 24/09/26` (+4311/-323, introduce character_animator + macro-blocchi + T0-T3 + guard anchoring), `38341ba upgrade -` (cleanup -6504 righe), `61985b5 upgrade 24/09/26 1` (fix pose-side + env doc).

---

## 3. Configurazione centrale (`config.py` + `.env`)

### 3.1 Caricamento env
- `BASE_DIR = dirname(abspath(__file__))`, `ENV_PATH = BASE_DIR/.env`.
- `_load_env_file()`: prima `dotenv.load_dotenv(ENV_PATH)` (env sistema ha precedenza), fallback parser manuale riga-per-riga (`KEY=valore`, strip quotes, supporta `export `, ignora commenti, non sovrascrive env esistenti, `utf-8-sig` per BOM).
- Helper: `_get_int`, `_get_float`, `_get_tuple("R,G,B,A")`, `_get_str_or_none`, `_get_str_list(*names)` (split virgola+a-capo, strip quotes/spazi, dedup preservando ordine), `_get_key_list` alias, `_get_pose_side_map(key,default)` (parser `1:any,2:center,...`, tollera `;`/newline, ignora voci malformate, mai solleva).
- `OUTPUT_DIR`, `TEMP_DIR` creati con `os.makedirs(exist_ok=True)` all'import.
- `get_pose_side_constraint(pose)` — mai solleva, ritorna `any` se ignota.
- `CHARACTER_POSE_SIDE_MAP` riempita con default `{1:any,2:center,3:center,4:left,5:split}` per pose 1..POSE_COUNT mancanti.

### 3.2 Tabella variabili completa (aggiornata)

| Variabile | Default | Modulo consumatore | Effetto |
|---|---|---|---|
| `ELEVENLABS_API_KEYS` (+ alias `ELEVENLABS_API_KEY`) | `[]` | `tts.py`, `config.check_keys` | Lista chiavi provate in ordine. Formato `k1,k2,k3`. |
| `GROQ_API_KEYS` (+ alias `GROQ_API_KEY`) | `[]` | tutti i moduli Groq | Idem per Whisper/LLM. |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` (Rachel) | `tts.py` via `get_elevenlabs_voice_id` | Voce default tutte le chiavi. |
| `ELEVENLABS_VOICE_IDS` | `[]` | `tts.py` | 0=len→default; 1=vale per tutte; N=N→1:1 chiave:voce; altro→`ValueError`→`TTSError`. |
| `ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | `tts.py` | Modello TTS (supporta IT). |
| `ELEVENLABS_OUTPUT_FORMAT` | `mp3_44100_128` | `tts.py` | Query param `output_format`. |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3-turbo` | `transcription.py` | Modello STT. |
| `GROQ_LLM_MODEL` | `openai/gpt-oss-120b` | `keywords, emphasis, character, tagger` | LLM keyword/grouping/character/tagging. |
| `GROQ_THEME_MODEL` | =`GROQ_LLM_MODEL` | `theme.py` | LLM palette (separabile). |
| `KEYWORDS_MAX` | `10` | `keywords.py` | Tetto keyword; target effettivo `max(3,min(MAX,len//30))`. |
| `KEYWORDS_MIN_GAP` | `12` | `keywords.py` | Gap minimo parole; effettivo `max(GAP, len//target//2)`. |
| `THEME_MIN_LUMINANCE_DIFF` | `80` | `theme.py`, `text_animator._styled_fills` | Soglia contrasto luminanza 0-255. |
| `EMPHASIS_MAX_WORDS_PER_CHUNK` | `3` | `emphasis_grouping` | Validazione tagli LLM. |
| `EMPHASIS_MIN_WORDS_PER_CHUNK` | `1` | `emphasis_grouping` | Idem. |
| `VIDEO_WIDTH/HEIGHT/FPS` | `1080/1920/30` | `renderer, animator, video_builder, guard, presets` | Risoluzione verticale + fps. |
| `SUBTITLE_FONT_PATH` | `None` | `renderer.load_font` | TTF esplicito o fallback sistema. |
| `SUBTITLE_FONT_SIZE` | `64` | `renderer` legacy | Base prima di `font_scale` preset. |
| `SUBTITLE_COLOR/STROKE_COLOR/STROKE_WIDTH` | `255,255,255,255` / `0,0,0,255` / `0` | `renderer, animator` legacy | Look pulito: stroke 0, no contorno. |
| `SUBTITLE_MAX_CHARS/MAX_WORDS` | `38/7` | `subtitle_grouping` legacy | Solo grouping classico. |
| `TEXT_ANIMATION_ENABLED` | `1` | `main.py` | `1`=frame animati, `0`=PNG statici. Valori falsy: `0,false,no,off,""`. |
| `TEXT_ANIMATION_ENTRY_DURATION` | `0.18` | `text_animator._resolve_motion_params` | Entrata singola parola (s), moltiplicata da `anim_entry_mult` hook (clamp 0.3-1.5). |
| `TEXT_ANIMATION_EXIT_DURATION` | `0.15` | `text_animator` | Fade-out gruppo (s). |
| `KEYWORD_ENTRY_SCALE_FROM` | `0.7` | `text_animator` | Default globale pop keyword; perdente vs preset `anim.pop_from` vs override hook `anim_pop_from`. Priorità: hook > preset > globale. |
| `TEXT_ANIMATION_ACCENT_LIFT_PX` **(NUOVO)** | `10.0` | `text_animator` T1 | Rise accent senza scala (px, clamp 0-24). Non deforma handwritten. |
| `TEXT_ANIMATION_HERO_SCALE_FROM` **(NUOVO)** | `0.6` | `text_animator` T3 | Scala iniziale hero (0.6→1.0, clamp 0.1-1.0). |
| `TEXT_ANIMATION_HERO_ENTRY_DURATION` **(NUOVO)** | `0.22` | `text_animator` T3 | Durata hero (≥5 frame, override non moltiplicato). |
| `TEXT_ANIMATION_HERO_EXIT_DELAY` **(NUOVO)** | `0.06` | `text_animator._hero_exit_factor` | Hold hero oltre gruppo (~2 frame, clamp 0-0.20, fade compresso senza sforare `chunk.end`). |
| `TEXT_ANIMATION_NUMBER_ENTRY_DURATION` **(NUOVO)** | `0.15` | `text_animator` T3-num | Pop corto numeri/dati, mai hero. |
| `CHARACTER_ENABLED` | `1` | `main, renderer, animator` | `0`=nessun personaggio. |
| `CHARACTERS_DIR` | `BASE_DIR/assets/characters` | `character_selector` | Asset `1.jpg/.png` ecc. |
| `CHARACTER_VALID_POSITIONS/TRANSITIONS` | `bottom_center,.../slide_up,...` | `character_selector` | Vocabolario legacy (alias `CHARACTER_POSITIONS/TRANSITIONS`). |
| `CHARACTER_POSE_COUNT` | `5` | `character_selector` | Range pose 1..5. |
| `CHARACTER_SCALE_MIN/MAX` | `0.65/0.90` | `character_selector` | Clamp scala (default piano 0.75). |
| `CHARACTER_MAX_SAME_POSE/SIDE` **(NUOVO)** | `2/2` | `character_selector._enforce_rhythm_variety` | Mai >2 chunk consecutivi stessa posa/stesso lato; poi forza alternativa plausibile. |
| `CHARACTER_IDLE_ENABLED/AMP_Y/FREQ/TILT_DEG` **(NUOVO)** | `1/4.0/0.4/0.0` | `text_animator._idle_bob_tilt`, `character_animator` | Bob verticale dolce 4px@0.4Hz (~2.5s/ciclo); tilt 0 = nessuna rotazione laterale (stabilità). |
| `CHARACTER_ENTRY_DURATION` **(NUOVO)** | `0.20` | `animator` | Slide&pop entrata +300px `ease_out_back` (~6 frame). |
| `CHARACTER_FIRST_ENTRY_DURATION` **(NUOVO)** | `0.20` | `animator` | Prima apparizione (stessa durata, fade+slide/zoom). |
| `CHARACTER_EXIT_DURATION` **(NUOVO)** | `0.16` | `animator` | Slide-drop +400px + fade `ease_in_cubic` (~5 frame). |
| `CHARACTER_PUNCH_ZOOM_DURATION` **(NUOVO)** | `0.60` | `animator` | Zoom punch fluido (mai jump secco). |
| `CHARACTER_MORPH_DURATION` **(NUOVO)** | `0.40` | `animator` | Morph cambi posa/lato opaco `ease_in_out_cubic` (anti-blink). |
| `CHARACTER_GAP_HOLD_ENABLED/MAX` **(NUOVO)** | `1/1.5` | `animator render_all`, `video_builder` | Persistenza nei gap TTS: tail clonato `t_N`, `clip_end=min(next_start, end+GAP_MAX)`; overlay contigui anti-blink. Cap tail 2s. |
| `CHARACTER_MIN_BLOCK_DURATION` **(NUOVO)** | `2.5` | `character_selector._build_macro_time_blocks` | Durata minima apparizione (s, clamp ≥0.5). Resto body corto fuso nell'ultimo blocco. |
| `CHARACTER_DISCONTINUOUS_MODE` **(NUOVO)** | `1` | `macro stabilization` | 1=presenza discontinua (Hook/CTA visibili, Body ~60%), 0=sempre visibile. |
| `CHARACTER_HOOK_VISIBLE/CTA_VISIBLE` **(NUOVO)** | `1/1` | `macro stabilization` | Forza visibilità Hook/CTA. |
| `CHARACTER_BODY_VISIBLE_RATIO` **(NUOVO)** | `0.6` | `macro stabilization` | Frazione blocchi Body visibili; nascosti distribuiti uniformemente `(j+0.5)*n/quota`, 1 blocco solo (~2.5-4s), mai bordi quando possibile. |
| `CHARACTER_POSE_SIDES` → `CHARACTER_POSE_SIDE_MAP` **(NUOVO)** | `1:any,2:center,3:center,4:left,5:split` | `selector + presets` | Vincoli lato per posa senza toccare codice. `any`=libero, `center`=solo center, `left`=solo split_left, `right`=solo split_right, `split`=alternati. Posa4 sempre left (indica verso destra, sta a sinistra). |
| `TYPOGRAPHY_ENGINE_ENABLED` | `1` | `main, animator, tagger` | `0`=path legacy singolo font. |
| `TYPOGRAPHY_BASE_FONT_SIZE` | `60` | `animator, presets` | Base prima di `font_scale` preset (dark 62). |
| `TYPOGRAPHY_BASE_WEIGHT` **(NUOVO)** | `600` | `animator._apply_font_weight` | SemiBold asse Weight variable (Inter/Roboto/Montserrat); statici → grassetto sintetico leggero 1px stesso colore. Solo base, impact/accent invariati. |
| `TYPOGRAPHY_IMPACT_SCALE/ACCENT_SCALE` | `1.4/1.1` | `animator` | Moltiplicatori (clamp 1.2-1.6 / 1.0-1.3, preset 1.3-1.45). |
| `TYPOGRAPHY_STROKE_WIDTH` | `0` | `animator` | Sempre 0 default (pulito). |
| `TYPOGRAPHY_SHADOW_ENABLED/OFFSET/FILL` | `0/(3,3)/(0,0,0,180)` | `animator` | Ombra OFF default. |
| `FONTS_DIR` | `BASE_DIR/assets/fonts` | `font_manager` | Cache font. |
| `NARRATIVE_ENABLED` | `1` | `main, narrative_structure` | `0`=pipeline piatta. |
| `NARRATIVE_HOOK_MAX_CHUNKS` | `3` | `narrative_structure` | Hook = prime 1-3 caption. |
| `NARRATIVE_CTA_MAX_CHUNKS` | `4` | `narrative_structure` | CTA = ultime 1-4 con segnali. |
| `NARRATIVE_CTA_CARD` | `1` | `narrative/animator` | Card karaoke persistente se CTA forte+breve. |
| `NARRATIVE_CTA_CARD_MAX_WORDS` | `14` | `narrative` | Soglia parole card. |
| `NARRATIVE_HOOK_ENTRY_MULT` | `0.7` | `narrative/animator` | Hook più scattante (0.3-1.0). |
| `NARRATIVE_HOOK_POP_FROM` | `0.55` | `narrative/animator` | Pop hook marcato (0.1-1.0, vince su preset/globale). |
| `PIPELINE_FAST` | `0` | `emphasis, character, tagger` | `1`=salta LLM pesanti → euristiche istantanee (tema+keyword restano LLM). |
| `RENDER_PARALLEL` | `1` | `text_animator` | `1`=ThreadPool chunk + micro-video. |
| `FFMPEG_PRESET` | `veryfast` | `video_builder` | Whitelist `ultrafast..medium`, fallback veryfast. |
| `OUTPUT_DIR/TEMP_DIR` | `BASE_DIR/outputs/temp` | tutti | Override opzionale. |

### 3.3 `get_elevenlabs_voice_id(key_index, total_keys)` + `check_keys()` + `get_pose_side_constraint()`
- Risoluzione voce come da tabella sopra; solleva `ValueError` se lista ambigua (es. 2 voci per 3 chiavi).
- `check_keys() → int(bad)`: `GET /v1/user` ElevenLabs (mostra tier + `character_count/limit`) e `GET /v1/models` Groq (`Authorization: Bearer`), senza consumare crediti. Usato da `python config.py --check-keys`. Maschera chiavi `primi4...ultimi2`.
- `get_pose_side_constraint(pose) → any|center|left|right|split`, mai solleva.

---

## 4. Entry-point e GUI (`main.py`, 582 righe)

### 4.1 Classe `VideoGeneratorApp(root: tk.Tk)`
- Finestra `640x580`, non resizable, titolo `Video Generator - v2`.
- Widget: `load_button` (filedialog `.txt`), `file_label`, `bulk_check` (BooleanVar default False), `script_count_label`, `text_preview` (ScrolledText 10 righe, bind `<<Modified>>` con debounce 300ms → `_refresh_script_count`), `generate_button` (blu `#2d6cdf`), `status_text` (ScrolledText Consolas 9, disabled, thread-safe via `root.after(0,append)`).
- `_set_ui_busy(busy)`: disabilita bottoni durante job.
- `_log_attempt(index,total,ok,detail)`: mostra ciclo chiavi (`✅ chiave 1/10...`, troncato 180 char). Passata come `on_attempt` a tutti i moduli API.

### 4.2 Script handling (delega a `script_loader`)
- `_current_scripts() → list[str]`: `parse_scripts(preview_text, bulk_mode)`.
- `_refresh_script_count()`: aggiorna `N script`, label preview, testo bottone (`Genera N Video`).
- `_on_load_script()`: `open(path,utf-8)`, inserisce in preview, aggiorna conteggio (in bulk mostra `nome (N script)`).
- `_on_generate()`: valida non-vuoti, in singolo tronca a `[:1]`, pulisce log, lancia `threading.Thread(daemon=True, target=_run_pipeline)`.

### 4.3 `_run_pipeline(scripts: str|list[str])` — orchestratore bulk
- Normalizza a lista, filtra `strip()` vuoti. Se 0 → warn + sblocca UI.
- Loop `enumerate(scripts,1)`: chiama `_process_one_script`, accumula `successes/failures`, `try/except TTSError|TranscriptionError|VideoBuildError` (fatali per quel video) + `except Exception` con traceback. `finally: cleanup_temp_files()` per isolamento.
- Riepilogo log `📊 Completati X/Y` + `messagebox` (info/warning/error) via `root.after` (thread-safe). `finally: _set_ui_busy(False)`.

### 4.4 `_process_one_script(script_text, index, total) → str(output_path)` — pipeline singolo
Dettaglio esatto con log `[X/8]`:
1. **Naming:** `suggest_output_filename(index,script,total,OUTPUT_DIR)` + `narration_{index:03d}.mp3` in bulk else `narration.mp3`.
2. **`[1-2/8]` Parallelo x2 (ThreadPool max 2):** `generate_theme(script, _log_attempt)` + `generate_audio(script, audio_filename, _log_attempt)`. Log sfondo/testo/n keyword + path audio.
3. **`[3/8]`** `transcribe_audio(audio_path, _log_attempt)` → `words: [{word,start,end}]`.
4. **`[4/8]`** `align_transcript(words, script)` con try `AlignmentError` → fallback trascrizione raw. Log `match_ratio%, corrette, recuperate, extra`.
5. **`[5/8]`** `group_words_by_emphasis(words, _log_attempt)` → `chunks: [{text,start,end,words:[{word,start,end}]}]`.
6. **`[5.2/8]`** Se `NARRATIVE_ENABLED`: `classify_narrative(chunks, script, _log_attempt)` → `(sections, chunks_arricchiti)` con `assign_hero_flags` interno via tagger (1 hero/video). Log hook/body_beats/CTA+strength/mode. Else log disabilitata.
7. **`[5.5-6.5/8]` Parallelo x3 (ThreadPool max 3):** `plan_character_layout(chunks_base, script)` se `CHARACTER_ENABLED` (ora con macro-blocchi + `character` dict) + `extract_keywords(script, _log_attempt, theme[keyword_colors])` + `enrich_chunks_with_typography(chunks_base, script, None)` se `TYPOGRAPHY_ENGINE_ENABLED` (ora con `is_hero`/`is_number`). Raccolta con try separati (mai bloccanti). Log prime 10 voci character (`[HOOK] chunk i: posa X (layout+punch, transition)`), n keyword, nicchia, font paths (pre-warm via `_get_shared_font_manager().ensure_preset_fonts` — singleton, no istanza per chunk), colori preset, conteggi base/impact/accent. Merge: `chunks = chunks_typo` se presente, poi `enrich_chunks_with_characters(chunks, character_plan)`.
8. **`[6.8/8]`** `build_realtime_plan(chunks)` + `apply_realtime_plans` → log `garantiti/corretti/hidden/intenzionali` + `overlaps_before` interno.
9. **`[7/8]`** Se `TEXT_ANIMATION_ENABLED`: `render_all_chunks_animated(chunks, bg, text, keyword_colors, TEMP_DIR, VIDEO_FPS, on_chunk, typography_niche)` con log ogni 10 chunk e gap-hold tail automatico (`clip_start/clip_end`); `except TextAnimationError` → fallback `render_all_subtitles(chunks, keyword_colors, text_rgba)`. Else statico diretto.
10. **`[8/8]`** `build_video(audio_path, enriched_chunks, output_filename, bg)` → ritorna path (finestre contigue, GOP 60).

---

## 5. Moduli core in dettaglio

### 5.1 `core/script_loader.py` — parsing bulk puro, testabile (123 righe)
- `parse_scripts(text, bulk_mode)`: `False`→`[stripped]` o `[]`; `True`→`[strip(line) for line in splitlines() if strip]` (preserva ordine, tollera BOM via strip, mai solleva).
- `load_scripts_from_file(path, bulk_mode)`: `open utf-8` (no fallback latin-1 nel codice attuale) → `parse_scripts`. Solleva `OSError` se illeggibile.
- `slugify(text, max_words=5, max_len=32)`: regex `[A-Za-zÀ-ÖØ-öø-ÿ0-9]+`, lowercase, join `_`, strip non-`[a-z0-9_]`, fallback `"script"`.
- `suggest_output_filename(index, script, total, output_dir, prefix="video", ext=".mp4")`: `width=max(2,len(str(total)))`, `base=f"{prefix}_{i:0{width}d}_{slug}{ext}"`; se `output_dir` e file esiste → `_1,_2...` fino a 999. Non crea file.
- `preview_of(script, max_len=80)`: collapse whitespace + `...`.

### 5.2 `core/tts.py` — ElevenLabs (163 righe)
- **Endpoint:** `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={ELEVENLABS_OUTPUT_FORMAT}`, headers `xi-api-key, Content-Type: application/json`, body `{text, model_id, voice_settings:{stability:0.5, similarity_boost:0.75}}`, timeout 120s.
- **Firma:** `generate_audio(script_text, output_filename="narration.mp3", on_attempt=None) → abs path in TEMP_DIR`.
- **Failover:** loop chiavi in ordine con voci risolte `get_elevenlabs_voice_id`. `_RETRYABLE_STATUS={401,402,403,429,500,502,503,504}` + `404` solo se voci diverse (1:1). Su rete/retryable → `failures.append + on_attempt(False) + continue`. Su `400/404-voce-unica/422` → `raise TTSError(detail)` immediato. Se tutte falliscono → `TTSError("Tutte le N chiavi... | ".join(failures))`.
- **Validazioni:** script vuoto → `TTSError`; no keys → `TTSError`; `ValueError` voci → `TTSError`.
- **Eccezione:** `class TTSError(Exception)`.

### 5.3 `core/transcription.py` — Groq Whisper (185 righe)
- **Chiamata:** `Groq(api_key).audio.transcriptions.create(file=open(rb), model=GROQ_WHISPER_MODEL, response_format="verbose_json", timestamp_granularities=["word"])`.
- **Firma:** `transcribe_audio(audio_path, on_attempt=None) → [{word,start,end}]` (gestisce sia dict sia oggetti SDK).
- **Cache client:** `_groq_client_cache: dict[key,obj]` max 16.
- **`_is_retryable_with_next_key(e)`:** `False` solo se `status_code in (400,404,422)` E messaggio senza hint retryable; altrimenti `True`. Hint include `rate limit, quota, credit, billing, expired, invalid api key, unauthorized, overload, timeout, connection, unavailable, server error + 401/402/403/429/500/502/503/504`.
- **Loop:** su eccezione → `on_attempt(False)` + `continue` se retryable e non ultima, else `raise TranscriptionError` immediato o aggregato. Su successo → `on_attempt(True)` + `break`.
- **Validazioni:** no keys, file mancante, `words` vuote → `TranscriptionError`.
- **Eccezione:** `class TranscriptionError(Exception)`.

### 5.4 `core/alignment.py` — difflib script↔trascrizione (120 righe)
- **Perché:** Whisper sbaglia omonimi/nomi/punteggiatura; l'audio è generato dallo script quindi i sottotitoli devono mostrare parole script con tempi Whisper.
- **Firma:** `align_transcript(transcribed, script_text) → (aligned, stats)` con `stats={match_ratio (ratio() arrotondato 3), corrected, interpolated, extra}`.
- **Algoritmo:** `script_tokens=split()`, `normalize_word` da keywords (lower + strip punteggiatura bordi), `SequenceMatcher(a=script_norm, b=tr_norm, autojunk=False).get_opcodes()`:
  - `equal`: copia dict trascritto ma `word=script_tokens` esatta.
  - `replace`: accoppia `min(len)` (tempi Whisper, parole script, `corrected+=`), se script più lungo → `_interp_missing` (distribuisce uniformemente `prev_end→next_start`, fallback `prev_end+0.3*n`), `interpolated+=`; se trascritto più lungo → tiene extra, `extra+=`.
  - `delete`: interpola. `insert`: tiene.
- **`_enforce_monotonic`:** garantisce `start>=prev_end`, `end>start` (+0.05 se degenere).
- **Eccezione:** `class AlignmentError` se input vuoti. Chiamante la tratta come non-bloccante.

### 5.5 `core/theme.py` — palette premium LLM (438 righe)
- **Output:** `{background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB...]}`. Mai blocca: fallback `DEFAULT_THEME={#0F172A,#FFFFFF, _FALLBACK_PALETTE_HEX}`.
- **Design system:** `PREMIUM_BACKGROUNDS` 12 neri cinematici; `PREMIUM_TEXTS=[#FFFFFF,#F5F5F5,#FDFBF7]`; `PREMIUM_ACCENTS` 8 ori/sky/ciano/lavanda/rosa/menta (mai gialli neon puri).
- **Prompt:** system `art director premium... SOLO JSON`, user con regole rigide + `SCRIPT`. `temperature=0.3, max_tokens=1024, response_format={"type":"json_object"}`, modello `GROQ_THEME_MODEL`, loop chiavi con `on_attempt`.
- **Validazione `_validate_theme(raw)`:** bg garish → `_nearest_premium_bg`; testo non-near-white o basso contrasto → bianco max contrasto; keyword: scarta non-hex/yellowish/neon/duplicati/anti-arcobaleno (tinte >25°), max 4, integra da `PREMIUM_ACCENTS+_FALLBACK`, rete oro+sky se <2.
- **Helper:** `hex_to_rgb/rgba`, `luminance`, `_saturation_of/_hue_of`, `_parse_theme` (strip fence).
- **Eccezione:** `class ThemeError` solo per script vuoto.

### 5.6 `core/emphasis_grouping.py` — chunk 2-3 parole (211 righe)
- **Output:** `[{text,start,end,words:[{word,start,end}]}]`.
- **LLM:** riceve SOLO parole indicizzate, restituisce SOLO `{"cut_indices":[...]}`. Regole: 1-3 parole (preferisci 2-3), 3 ok se terza leggera, mai iniziare con leggera isolata, punteggiatura forte = taglio obbligato. `temperature=0.2, max_tokens=1024, json_object`, modello `GROQ_LLM_MODEL`, loop chiavi.
- **Validazione `_validate_cuts`:** lista non-vuota, int (no bool), range, unici+ordinati, ultimo=`n-1`, size in `[MIN,MAX]`.
- **Fallback `_deterministic_fallback`:** blocchi da 2 (3 se terza `_is_weak` e senza strong punct), taglio su `_ends_strong`. Usato se `PIPELINE_FAST=1`, no keys, LLM fallisce o tagli invalidi.
- **Mai solleva** per API; `class EmphasisGroupingError` definita ma non fatale.

### 5.7 `core/subtitle_grouping.py` — legacy per frasi (144 righe)
- **Output:** `[{text,start,end}]` (senza `words`).
- **Regole:** chiudi su strong punct; se `len>=38` o `count>=7` chiudi su virgola o dopo parola intera (no weak trailing isolata). Post-process `_merge_short_chunks` (<12 char fusi se ≤MAX+15).
- **Uso attuale:** non chiamato in `main.py`, ma fornisce costanti condivise. Non rimuovere senza refactor.

### 5.8 `core/keywords.py` — keyword LLM (215 righe)
- **Output:** `{parola_normalizzata: colore_RGBA}`.
- **Palette:** `_FALLBACK_PALETTE_HEX` 8 hex premium, `color_for_keyword(word,palette)` deterministico `md5(word)%len`.
- **Prompt:** `Estrai al massimo {target} parole SINGOLE esattamente come appaiono...` con `target=max(3,min(MAX,len//30))`. `temperature=0.2, max_tokens=512, json_object`.
- **Parsing `_parse_keywords`:** strip fence, `json.loads`, fallback regex; solo singole parole, `normalize_word`, dedup.
- **Spread `_spread_keywords`:** accetta in ordine importanza solo se distanza `>=gap` (`gap=max(MIN_GAP, len//target//2)`). Scarta non-verbatim (limite noto).
- **Palette effettiva:** se `keyword_palette_hex` dal tema → `_hex_to_rgba`, else storica; su hex invalidi → storica.
- **Errori:** `class KeywordError`. Non-bloccante per chiamante.

### 5.9 `core/narrative_structure.py` — 3 atti + hero (506 righe, +98)
- **Filosofia:** tutto deterministico (posizione+punteggiatura+segnali, mai LLM).
- **Firma:** `classify_narrative(chunks, script_text="", on_attempt=None) → (sections, enriched)` dove `sections={hook, body, body_beats, beat_tones, cta, cta_strength: strong|soft|none, cta_mode: card|locked|none}`, `enriched=chunk+{narrative_role, narrative_beat, beat_tone, anim_entry_mult/anim_pop_from, cta_card, cta_section_id, cta_strength}`. Mai solleva.
- **Rilevamento:** `_detect_cta` = sequenza finale max `CTA_MAX` con `_CTA_CUES` (50+ IT+EN). Se nessuna → ultimo chunk `soft` se `n>=3`, else `none`. `_detect_hook` = prima frase entro `HOOK_MAX`; se nessuna → 1 chunk se `n<=3` else 2. `_split_body_beats` su strong end + merge beat da 1 chunk. `beat_tone`: `question` se `?`, `data` se `\d`, `key` se `!`/cue, else `explainer`.
- **`boost_typography_styles(styled, role, ...)`:** hook garantisce ≥1 impact; CTA verbi `_CTA_ACTION_VERBS` → impact + ≥1; aggiorna `display` uppercase. Inizializza sempre `is_hero=False` e `is_number` via `_has_digit`; numeri mai hero.
- **`assign_hero_flags(chunks)` (NUOVO, video-wide, max 1 hero/video):** reset `is_hero=False` ovunque + `is_number` via digit; 1) CTA: primo verbo d'azione impact senza cifre → hero; 2) else hook: contenuto impact più lungo non-function-word senza cifre → hero. Chiamato da `text_tagger.enrich_chunks_with_typography` dopo il boost (vedi §5.14), non direttamente da `main.py`. Renderer legge `(style,is_hero,is_number)` per T0-T3.
- **CTA card mode:** `card` solo se `strong` + `CTA_CARD=1` + parole totali `<=CTA_CARD_MAX_WORDS(14)`, else `locked`/`none`.
- **Se `NARRATIVE_ENABLED=0`:** tutto body, 1 beat unico.

### 5.10 `core/character_selector.py` — personaggi 2D + macro-blocchi Breath & Focus (2015 righe, +1019)
- **Pose semantica:** 1 incrociate (hook/fatti), 2 aperte (spiegazioni), 3 pollice (soluzioni/CTA), 4 indica (dati/keyword, SEMPRE split_left: punta a destra, sta a sinistra), 5 mento (domande, prediligi split).
- **Firma principale:** `plan_character_layout(chunks, script_text, on_attempt=None) → [{chunk_index, pose|None, layout, layout_preset, punch_in, transition_in, position, transition, scale, block_id, char_event, char_visible, character:{visible,pose,pose_id,side,event,block_id}}]` lungo quanto chunks. Mai solleva per API (fallback). `pose=None` = nascosto (testo centrale).
- **LLM:** prompt regista con `_POSE_RULES+_LAYOUT_RULES` + regole narrative + snippet 1500 char + `indice: testo` (tag `[HOOK]/[CORPO]/[CTA]`). `temperature=0.3, max_tokens=max(512,min(4096,256+n*64)), json_object`. Accetta array bare o `{layout|plan|chunks|items}` + fence; buchi → fallback. `_normalize_entry` clamp posa, `normalize_preset`, forza split posa4/5, `transition_in` default, scala clamp. `_parse_punch_in` tollerante.
- **Vincoli posa centralizzati (NUOVO):** `_pose_allowed_layouts(pose)` da `get_pose_side_constraint` + `_constrain_preset_for_pose(pose,preset,alternate)` + `_layout_for_pose_side(pose,side,flip)` + `_preset_for_pose`. Posa2 mai split, posa4 sempre `split_left`, posa5 mai center stabile (flip left/right).
- **Ritmo calmo (NUOVO, `_enforce_rhythm_variety`):** mai >`MAX_SAME_POSE(2)` stessa posa né >`MAX_SAME_SIDE(2)` stesso lato; forza `_pose_for_text(txt,avoid)` + layout alternato `side_cycle=[center,right,left]`; center alternano `slide_up/zoom_in` (no laterale continuo), split direzionali; mai 3 transizioni identiche (3a→`fade`/`zoom_in`); ripara vincoli side-map; esclude CTA card/CTA e preserva hook primo chunk.
- **Finalize:** `_apply_narrative_locks` + `_cap_punch_ins_narrative` (hook max1 ultimo, corpo max1 ultimo, CTA 0) o `_cap_punch_ins` globale max 2 (tiene ultimi) → `_enforce_rhythm_variety` → `_apply_macro_block_stabilization`.
- **Macro-blocchi stabili “Breath & Focus” (NUOVO, §§984-1393):** `_macro_role` (hook/body/cta con fallback posizionale) → `_build_macro_time_blocks` (Hook 1 blocco, Body blocchi ≥`MIN_BLOCK_DURATION(2.5s)`, resto corto fuso, CTA 1 blocco) → visibilità: `DISCONTINUOUS_MODE=0` tutto visibile, else Hook/CTA da flag, Body `BODY_VISIBLE_RATIO(0.6)` con `hide_body_ids` distribuiti uniformemente (mai lunghi tratti senza personaggio, pause 1 blocco ~2.5-4s) → `_select_block_pose_layout` (unica posa+layout dal primo chunk, con vincoli) + no-repeat tra blocchi visibili adiacenti (posa diversa sempre, lato diverso quando la posa lo permette) → eventi `ENTRY` (primo) / `SUSTAIN` (medi) / `EXIT` (ultimo, o ENTRY se blocco singolo) / `NONE` (nascosto). Ogni voce porta `character={visible,pose,pose_id: pose_crossed/open/thumb/pointing/chin, side: LEFT/RIGHT/CENTER, event, block_id}` + alias piatti `char_event/char_visible/block_id` per `character_animator`/`layout_guard`/`text_animator`.
- **Fallback `_fallback_plan`:** ciclo dinamico 8-step `[(1,center),(4,split_left),(2,center),(5,split_left),(1,split_right),(4,split_left),(3,center),(2,center)]` + `?`→5, `!`→3+punch (mai CTA), cifre→4 split_left; mai 3 uguali (via finalize).
- **Asset:** `_candidate_asset_paths` (`{n}.jpg/.jpeg/.png` + maiuscole, `CHARACTERS_DIR` + legacy `Nuova cartella/characters` cachato), `load_character_original` RGBA pulita (`_remove_black_background`: `a>=250 & RGB<15` → trasparenti, numpy else getdata, cachata), `load_and_process_character_image` legacy, `character_target_height` clamp, `calculate_character_bbox` legacy, `resolve_character_path`, `clear_character_cache`.
- **`resolve_chunk_layout(chunk) → None|{pose,use_preset,layout,layout_preset,punch_in,transition_in,position,transition,scale}`:** singola fonte di verità (None se nascosto/assente). `use_preset` vero solo se layout valido (+2 deprecati tollerati).
- **`enrich_chunks_with_characters(chunks,plan)`:** merge se lunghezze coincidono (copia anche `character/block_id/char_event/char_visible`), else invariati. Mai solleva.

### 5.11 `core/layout_presets.py` — zone 1080x1920 (319 righe, +28)
- **4 preset:** `layout_center_standard` (125% larghezza, mezza figura basso, testo alto `90,150,990,900`), `layout_center_punch_in` (170% primo piano, testo terzo superiore `90,150,990,640` + pill), `layout_split_left` (130% sinistra overhang, testo destra `640,560,1000,940`), `layout_split_right` (speculare `80,560,420,940`). Niente figura intera: scala su larghezza, ancoraggio dal basso con headroom (500/110/250px), fondo sempre oltre canvas.
- **Costanti:** `PRESET_WIDTH_PCT`, `PUNCH_IN_FACTOR=1.35`, `MAX_PUNCH_INS_PER_VIDEO=2`, `PRESET_HEADROOM_PX`, `SPLIT_OVERHANG_X=420`, `PRESET_SAFE_AREA`, `PRESET_FONT_SCALE (1.0/1.0/0.9/0.9)`, `PRESET_SIDE`, `PRESET_DEFAULT_TRANSITION_IN`, `PRESET_TEXT_BACKGROUND (solo punch_in=True)`, `TEXT_PILL_FILL=(0,0,0,170), PAD=28, RADIUS=36`.
- **Funzioni pure:** `normalize_preset` (alias deprecati + legacy), `preset_width_pct (con punch)`, `preset_headroom_px/overhang_x/safe_area` (scalati), `preset_font_scale/side/default_transition/needs_text_background`, `normalize_transition_in`, `preset_alternate_transition` (center slide_up↔zoom_in per varietà), `legacy_transition/position`, `describe_preset`, `is_valid_preset`.
- **Novità doc:** riferimento a `config.CHARACTER_POSE_SIDE_MAP` per futuri asset (cambiare lato posa via env senza codice).

### 5.12 `core/renderer.py` — rendering statico + primitive condivise (672 righe)
- **Ruolo doppio:** path statico legacy + libreria layout/disegno riusata dall'animato (`compute_word_layout`, `draw_word`, `draw_text_background`, `calculate_character_transform`, `get_character_layer`).
- **Font:** `load_font(size)` cachato `(path,size)`: `SUBTITLE_FONT_PATH` poi `DejaVu/Liberation/arialbd/Arial Bold`, else `load_default()`. `LINE_SPACING=12`.
- **`compute_word_layout(words,font,max_width,area=None)`:** wrapping `_wrap_words`, centro in area, clamp safe area + rete anti-sconfinamento split. Usa probe 64x64 da animator.
- **`draw_word`:** pura, modula alpha per opacity, `stroke_width` default 0.
- **`draw_text_background`:** pill dietro bbox espansa.
- **`calculate_character_transform(image_size,preset,is_punch_in,canvas)`:** width-based, aspect preservato, x centrato/split overhang, y=headroom ma mai sopra `canvas_h-new_h`.
- **`get_character_layer(pose,preset,punch,canvas)`:** resize LANCZOS + cache `{(pose,w,h)}`. `clear_character_layer_cache()` per test.
- **`_paste_character_clipped`:** paste con clip canvas (overhang oltre bordi senza eccezioni).
- **`render_subtitle_image(text,index,keyword_colors,text_color,character,safe_area,text_safe_area)`:** canvas RGBA trasparente, Z-index personaggio→pill→testo, font `SUBTITLE_FONT_SIZE*font_scale`, `max_width=0.85*W`, colori keyword via `normalize_word`. Salva `subtitle_{index:04d}.png`. Legge `guard_safe_area/guard_font_scale/guard_pill` con precedenza + `character` dict / `pose=None` (hidden → nessun paste).
- **`render_all_subtitles(...)`:** usa metadati character se già arricchiti, else `character_plan` parallelo.

### 5.13 `core/text_animator.py` — animazioni Tier T0-T3 (3323 righe, +1020, cuore del progetto)
- **Concetto:** ogni parola entra al suo `start` (accumulo) e tutto scompare a `chunk.end` (+ tail gap-hold). Normali/base: solo fade `ease_out_cubic`. Keyword/impact: opacity+scala con `ease_out_back`. Uscita gruppo: fade `ease_in_cubic`. Layout pre-calcolato UNA volta per chunk dentro safe area. Sfondo sempre trasparente (bg da ffmpeg; param `background_color` solo per contrasto/compat).
- **Tier T0-T3 (unificazione moto/colore):** moto da `(style,is_hero,is_number)` (tagger/narrative; `is_keyword` legacy ⇒ impact), colore da `_styled_fills` (tema + highlight preset + palette keyword). T0 base fade diretto (~costo 0); T1 accent rise-fade (`opacity + y lift→0`, MAI scala, max 1/chunk, costo +5%); T2 impact pop (`opacity+scala pop_from→1.0 ease_out_back`); T3 hero 1 parola/video (verbo CTA o climax hook, mai numeri: pop `0.6→1.0` in `0.22s` + exit ritardata `0.06s` via `_hero_exit_factor`, fade compresso senza sforare `chunk.end`); T3-num impact con cifre (pop corto `0.15s`, mai hero). Legacy senza `styled_words`: solo T0/T2. `ease_out_bounce/elastic` disponibili ma non default (troppo giocosi).
- **`_resolve_motion_params(preset,chunk)`:** priorità stabile `entry_dur = base*anim_entry_mult` (hook 0.7x, clamp mult 0.3-1.5) con hero override `HERO_ENTRY_DURATION`; `scale_from = hook anim_pop_from > preset anim.pop_from > KEYWORD_ENTRY_SCALE_FROM` (clamp 0.1-1.0); `accent_lift` clamp 0-24; `hero_from/hero_delay/number_dur` clamp. Mai eccezioni.
- **`_word_tier(word)`:** normalizza style, `is_number` da flag o digit, `is_hero` solo se `style==impact` e non numero. Mai eccezioni.
- **Typography path (se `styled_words` validi e `ENGINE_ENABLED`):** 3 font per nicchia via `FontManager` (`_load_typography_fonts` con cache `_typo_font_cache`, chiavi `(path,size[,weight])` per base), `impact 1.3-1.5x uppercase highlight`, `accent 1.1x handwritten`, stroke 0, ombra solo se enabled. **`TYPOGRAPHY_BASE_WEIGHT=600` (NUOVO):** `_resolve_base_weight` + `_apply_font_weight` (asse `Weight` via `set_variation_by_axes`, cerca asse con `weight` nel nome, clamp min/max font); statici → grassetto sintetico leggero 1px stesso colore in `_draw_styled_word_direct/_render_styled_scaled_word` (solo base, mai impact/accent). Colori `_styled_fills`: base=tema (flip bianco/nero se basso contrasto), impact=highlight validato (fallback palette→highlight_alt→bianco/nero, mai uguale a base), accent=dedicato o mix 55% impact+45% base. Layout `compute_styled_layout` (baseline comune via ascent/descent, niente flottanti).
- **Legacy path:** singolo font, `compute_word_layout`, fills keyword else base.
- **Personaggio per frame (NUOVO ciclo vita):** layer caricato UNA volta (`_load_chunk_character_layer`), Z-index sfondo<character<pill<testo. Entrata slide&pop `0.20s` da `+300px` (`ease_out_back` + `_ease_out_quad`, `_CHARACTER_ZONE_ENTRY/FIRST_DURATION` da config) o legacy `0.35s/320px`; `char_entry_jump` (punch toggle) = istantaneo; `char_entry_fade` solo prima apparizione else slide a piena opacità (anti-glitch). Morph continuità `0.40s` da vecchia posizione (`_character_morph_offset` + `ease_in_out_cubic`, opaco, niente flash). Uscita via `decide_char_exit_mode(cur,nxt)`: `with_text` (fade gruppo), `hold` (stesso/posa/punch/legacy → resta fino a stacco + gap-hold tail), `slide_down` (solo cambio lato split+posa diversa, piena opacità). `decide_char_entry_jump(prev,cur)` solo su punch toggle. Punch zoom fluido `0.60s` (mai jump). Idle breathing `_idle_bob_tilt(t_abs)` (bob `sin(2π·0.4·t)*4px`, tilt `cos*0.0°`, quantizzato step 0.3° per cache, disabilitabile via `IDLE_ENABLED`; `character_animator` come reference math-only). Tilt applicato solo se non zooming (`_get_tilted_char` con expand+cache). `_paste_character_frame` con clip.
- **Gap-hold tail anti-blink (NUOVO):** `render_all_chunks_animated` calcola per chunk `tail = min(next_start-end, GAP_HOLD_MAX=1.5)` solo se `GAP_HOLD_ENABLED` e `exit_mode==hold` e character presente; `generate_animated_chunk_frames(..., tail_hold_duration)` clona `t_N` per `round(tail*fps)` frame (cap 2s) e setta `clip_start=start, clip_end=end+tail`. `video_builder` usa `clip_start/clip_end` per overlay contigui (niente sfondo vuoto, niente blink). Solo hold+character (persistenza gap), mai su with_text/slide_down.
- **Narrativa:** `anim_entry_mult/anim_pop_from` hook applicati a `entry_dur/scale_from`; hero via `is_hero` (CTA verbo o climax hook).
- **CTA card `generate_cta_card_frames`:** intera sezione come UNICA card persistente: layout/fill/font UNA volta su tutte le parole ordinate per start, reveal karaoke (future nascoste, corrente pop, passate fisse), pill badge sempre, personaggio bloccato su primo chunk, dissolvenza SOLO su ultimo (`exit_dur=0` intermedi), `card_scale=0.92`, propaga `is_hero/is_number`.
- **`generate_animated_chunk_frames(chunk,bg,text_color,keyword_colors,output_dir,chunk_index,fps,safe_area,char_exit_mode,...,typography_niche/preset) → [{image_path,start,end}]`:** `num_frames=ceil(duration*fps)`, `frame_step=1/fps`, pill cache (max 32), opacity cache quantizzata step 8 (max 128, clear a 120), `_fast_resample_for_scale` (BILINEAR se |scale-1|<0.12 else BICUBIC; LANCZOS solo resize una-tantum), binding locali loop caldo, PNG `compress_level=1`. Solleva `TextAnimationError` solo per timestamp invalidi/layout fuori sync; altri CTA wrappati.
- **`render_all_chunks_animated(chunks,bg,text_color,keyword_colors,output_dir,fps,on_chunk,safe_area,typography_niche/preset) → chunks+{frames,frame_paths,clip_start,clip_end}`:** calcola `states` (exit lookahead, entry lookbehind con `same_as_prev/same_pose` → jump, `entry_fade=prev is None`), separa run CTA consecutivi stessa `cta_section_id` (sequenziali) da normali (paralleli ThreadPool 2-4 worker se `RENDER_PARALLEL=1` e `>=3` chunk, `on_chunk` per GUI). Gap-hold tail come sopra.
- **Ottimizzazioni P0:** singleton `_shared_font_manager`, probe 64x64 thread-safe, pill/opacity cache, PNG fast, pattern image2 senza stat N, LUT opacity pre-calcolata.

### 5.14 `core/text_tagger.py` — nicchia + tagging LLM (690 righe, +31)
- **A. `detect_niche(script, on_attempt, min_confidence=0.4) → niche in VALID_NICHES`:** mai solleva (fallback euristico). Se `PIPELINE_FAST` o no keys → `_heuristic_niche` (conteggio segnali IT+EN pesati, multi-parola x2, fallback `dark_motivational`). Else LLM (`temperature=0.2, max_tokens=256, json {niche,confidence,reason}` su snippet 1500 char). Se confidence<min → euristica. Parsing fence/regex, alias via `normalize_niche`.
- **B. `tag_chunk_words(chunks, on_attempt) → [{chunk_index, words:[{text,type:base|impact|accent}]}]`:** mai solleva (euristica). Prompt designer + regole narrative (hook ≥1 impact, CTA verbi → impact). `max_tokens=max(512,min(4096,256+n*64))`. Parsing `chunks/tagged/items/results` o array bare, alias (`keyword→impact, quote→accent`), valida n voci. Riallineamento `_align_tags_to_timed_words` (match sequenziale normalizzato finestra 3, extra ignorati, mancanti → `_heuristic_style`: numeri→impact, maiuscolo 3+→impact, virgolettati/domande→accent, enfatiche/lunghe≥9→impact).
- **`enrich_chunks_with_typography(chunks,script,niche,on_attempt) → (niche, enriched)`:** `enriched=chunk+{typography_niche, styled_words:[{word,start,end,style,display,is_hero,is_number}]}` con timing uniformi se `words` mancanti + `boost_typography_styles` + **`assign_hero_flags(enriched)` (NUOVO, import lazy da narrative_structure, video-wide 1 hero)**. Inizializza `is_number` via regex `\d` e `is_hero=False` prima dell'hero (numeri mai hero). Mai solleva per LLM.

### 5.15 `core/typography_presets.py` — 6 nicchie (254 righe, +22)
- `FALLBACK_NICHE=dark_motivational`, `VALID_NICHES=[business_finance, tech_ai, fitness_sport, lifestyle_vlog, educational, dark_motivational]`.
- Ogni preset: `fonts{base:[2],impact:[2],accent:[2-3]}`, `colors{base,highlight,accent(+highlight_alt solo dark),stroke:#000000 inutilizzato}`, `sizes{base:60 (62 dark), impact_scale:1.3-1.45, accent_scale:1.1}`, `stroke_width:0, shadow off, impact_uppercase:True`, **`anim:{pop_from}` (NUOVO):** fitness `0.60` aggressivo, dark `0.60` cinematico, business/tech/educational `0.70` standard, lifestyle `0.80` soft (pop forte stona su rosa/handwritten). Hook override vince su preset, preset vince su globale.
  - business: Inter/Roboto + Anton/Impact + Playfair/Caveat, gold #FFD700/champagne #FFE8A3.
  - tech_ai: Roboto/Inter + Bebas/Orbitron + SpaceMono/Caveat, ciano #00E5FF/#B8F4FF.
  - fitness: OpenSans/Roboto + Oswald/Bebas + PermanentMarker/Kalam, rosso #FF2400/corallo #FFC4B8.
  - lifestyle: Poppins/Lato + Cinzel/Bodoni + Caveat/Pacifico, rosa #B76E79/#F3C6CE.
  - educational: Nunito/Roboto + League/Anton + Patrick/Kalam, blu #2962FF/#B3C6FF.
  - dark: Montserrat/Inter + Anton/Montserrat + Caveat/Kalam/Patrick (fix open-source: no Pristina/Editors Note che causavano fallback incoerenti), oro #D4AF37/#F5D67B (+alt #FF0000).
- `normalize_niche` (alias), `get_preset` (copia sicura + clamp `pop_from` 0.1-1.0, mai crash), `list_niches_for_prompt`.

### 5.16 `core/font_manager.py` — asset font (416 righe)
- `FONTS_DIR=BASE_DIR/assets/fonts`, `_GITHUB_RAW_BASE/_ALT` (google/fonts main), `_FONT_FILES` mappa norm→(ofl_subdir,file) (variable `[wght]` URL-encodati `%5B/%5D`; `impact/pristina/editorsnote` → `__system__` no-download; **`permanentmarker` → `PermanentMarker-Regular.ttf` (NUOVO, scaricato on-demand, non più committato)**).
- `_find_local_font` (match esatto case-insensitive + prefisso, cache dir 30s), `_find_system_font(prefer)` (cerca `C:\Windows\Fonts`, DejaVu, Liberation, Supplemental, cachato; per ruolo: impact→impact/arialbd, accent→hand/marker/caveat→times/georgia, base→arial), `_download_urls` (mappa + guess generici), `_download_to` (requests 15s, sanity size≥4KB + magic TTF/OTF, verifica `ImageFont.truetype(tmp,32)` prima di promuovere, atomic `.tmp→replace`).
- `class FontManager(fonts_dir)`: `ensure_font_exists(name)→path` (locale→download→sistema, mai solleva, `""` se tutto fallisce), `ensure_preset_fonts(niche|preset)→{base,impact,accent}`, `load_font(name,size)` (fallback `renderer.load_font` poi `load_default`), `clear_cache`. Singleton `_default_manager` + scorciatoie.

### 5.17 `core/layout_guard.py` — guard real-time + ancoraggio blocchi (805 righe, +123)
- **Garanzia:** mai eccezioni (fallback nascondi personaggio), niente LLM/I-O (solo probe/cache), <5ms/chunk.
- **Misure reali codificate:** center testa y~644 → `CENTER_SAFE_Y_MAX_FIXED=620`; split 340-360px → `SPLIT_WIDEN_PX=60`; pop overshoot 10% → `POP_OVERSHOOT=1.12`; punch char 1.6875x; `SAFETY_MARGIN_PX=24`, `FONT_SHRINK_STEPS=(1.0,0.9,0.8,0.7)`, `PUNCH_TEXT_PAD=28`, `WIDE_POSES_IN_SPLIT={2}` (pose2 mai split); **`SAFETY_PADDING_IDLE_X/Y=4/8px` (NUOVO: bob amp 4 + margine per idle continuo, applicato in `get_character_tight_canvas`)**.
- **Primitive:** `get_character_tight_original(pose)` (getbbox alpha cachata), `get_character_tight_canvas(pose,preset,punch)` (transform + tight scalata + padding idle, clip canvas), `text_bbox_of_layout(layout,pad)` + `expand_bbox_for_pop`, `rects_overlap(a,b,margin)→(bool,area)`.
- **`plan_chunk_realtime(chunk,words,font_size,max_width,margin) → {layout,safe_area,font_scale,needs_pill,hide_character,guaranteed,overlap_px,overlap_before_px,actions}`:** regola0 pose2→center, posa4→split_right→corretto a split_left via side-map (il guard rispetta i vincoli posa); misura iniziale (styled else legacy); se ok → garantito; else cascata: shrink font → tighten center ymax 620+shrink0.9 → widen split+shrink0.8 → switch preset (center↔split, mai pose2 split, posa4 solo split) → punch intenzionale (pill obbligatoria, `guaranteed=False`) → hide character (sempre garantito).
- **`build_realtime_plan(chunks,...)→(plans,summary{total,guaranteed,fixed,hidden,intentional,overlaps_before})`:** continuità posa (stessa immagine → riusa layout precedente, tag `pose-hold`) + **ancoraggio macro-blocco (NUOVO):** `_block_key_of` (block_id da `character` o piatto) + `_is_visibly_anchored` (visible + non-hidden); dentro stesso `block_id` visibile → stesso layout (anchor = più frequente tra garantiti, retry con `plan_chunk_realtime`, fallback `block-anchor-forced` + pill anche senza garanzia geometrica: mai salto testo); blocchi nascosti → `layout_center_standard` stabile (`block-anchor-hidden-center`). Niente più beat-lock (corpo cambia layout liberamente, morph+gap-hold evitano flicker).
- **`apply_realtime_plans(chunks,plans)→new list`:** aggiorna layout/position + `guard_safe_area/guard_font_scale/guard_pill` (precedenza in animator/renderer) o `pose` rimossa + `guard_hidden` + sync macro-blocco `char_event=NONE/char_visible=False/character={visible:False,...}` se hide. Mai solleva.

### 5.18 `core/easing.py` — curve pure (135 righe, +34, math only)
- `clamp01(t)`, `linear`, `ease_out_cubic (1-(1-t)^3)` per fade normali/T0, `ease_in_cubic (t^3)` per uscite, `ease_out_back (c1=1.70158, overshoot ~1.1)` per pop keyword/T2/T3, `ease_out_bounce` giocosa (non default), `ease_out_elastic` sperimentale.
- **NUOVO:** `ease_in_out_cubic` (morph posizione vecchia→nuova, slide continuità, partenza/arrivo morbidi), `ease_out_quad (1-(1-t)²)` (fade-in/out personaggio delicato), `ease_in_out_quad` (transizioni brevi stesso lato, senza overshoot). Tutte `t→eased`, overshoot voluto per keyword (clamp opacity a 255).

### 5.19 `core/video_builder.py` — ffmpeg (468 righe, +54)
- **Statico legacy:** ogni `image_path` come `-i`, `filter_complex` catena `overlay=0:0:enable='between(t,start,end)'` con **finestre contigue (NUOVO, `_chunk_window`):** `end→next_start` (caption+character restano visibili nelle pause TTS, fix blink anche nel fallback PNG).
- **Animato:** ogni chunk con `frame_paths/frames` → `build_chunk_clip(frame_paths,fps,TEMP_DIR/chunk_{idx:04d}.mov)` (`.mov→png` RGBA veloce default su i5 8th gen senza GPU, `.webm→libvpx-VP9 yuva420p crf18` per compat spec, pattern `image2 %05d` con fallback concat demuxer `file+duration`, riuso se clip più recente di primo+ultimo frame + spot-check 2 random, ThreadPool 2-4 worker) poi `overlay` con `setpts=PTS-STARTPTS+start/TB` (frame0=chunk.start) + `format=yuva420p` solo webm. **Finestra display (NUOVO):** preferisce `clip_start/clip_end` (includono tail gap-hold), overlay contigui, niente sfondo vuoto.
- **`build_video(audio_path,chunks,output_filename,background_color)→abs in OUTPUT_DIR`:** `ffprobe duration`, input `color=c=0xRRGGBB:s=1080x1920:r=30:d=duration` + audio, encode `libx264 preset {FFMPEG_PRESET whitelist} crf20 pix_fmt yuv420p faststart + aac 192k shortest`, `filter_threads+threads auto`, **`-g 60 -keyint_min 30` (NUOVO: GOP 2s@30fps per seeking/scrub precisi sulle caption, overhead minimo su short; default ffmpeg 250=8s troppo largo)**. `_ffmpeg_color` fallback `black`. Errori `VideoBuildError` con ultimi 2000 char stderr.
- **`cleanup_temp_files()`:** walk `TEMP_DIR` rimuove file + rmdir vuote (mai solleva oltre OSError ignorato).

### 5.20 `core/character_animator.py` — NUOVO (169 righe, reference math-only)
- **Scopo:** ciclo di vita pulito per macro-blocchi stabili, disaccoppiato dal rendering Pillow (overhead <5ms/frame, solo math, nessuna allocazione). Usato come spec/isolato; `text_animator` implementa la stessa logica con paste reale.
- **Stati:** `ENTRY` (primo chunk blocco visibile, slide-in 0.20s da `+300px` con `ease_out_back`), `SUSTAIN` (intermedi, solo idle), `EXIT` (ultimo chunk, slide-drop `+400px` con `ease_in_cubic` in coda `0.16s`), `NONE` (nascosto, `(0,0,0)` = non disegnare).
- **`CharacterFrameAnimator.get_frame_transform(event,frame_time,chunk_duration,global_frame_idx,fps=30) → (offset_y,rotation_deg,opacity)`:** `idle_weight` 0→1 in ENTRY e 1→0 in EXIT (evita scatti tra transizione e respiro); idle `sin(2π·freq·t)*amp` + `cos*tilt` con fase globale continua (`global_frame_idx/fps`), `freq/amp/tilt` da config con clamp/fallback (`0.4Hz/4px/0.0°`); tilt=0 → sempre rotation 0. Mai solleva (fallback `0.5s/30fps/0.20/0.16`).
- **`event_of(chunk)`:** legge `character={visible,event}` poi `char_event/char_visible/pose` legacy, fallback `SUSTAIN` se visibile senza evento, `NONE` se `pose is None` o `char_visible is False` o non-dict. Mai solleva.
- **`is_visible(chunk)`:** `event_of != NONE`. Costanti `_ENTRY_SLIDE_Y=300.0`, `_EXIT_DROP_Y=400.0` coerenti con `text_animator`.

---

## 6. Modelli dati (contratti tra moduli — NON rompere)

### 6.1 `word: {word:str, start:float, end:float, [is_keyword:bool, style:base|impact|accent, is_hero:bool, is_number:bool]}`
Prodotto da Whisper → riallineato (parole script) → arricchito con keyword/typography. Timestamp secondi, monotonically crescenti dopo alignment. `is_hero` max 1/video (impact senza cifre), `is_number` se contiene `\d` (mai hero).

### 6.2 `chunk` evoluzione
1. Dopo emphasis: `{text:str, start:float (primo word.start), end:float (ultimo word.end), words:[word]}`.
2. Dopo narrativa: `+{narrative_role: hook|body|cta, narrative_beat:int, beat_tone, anim_entry_mult, anim_pop_from, cta_card:bool, cta_section_id, cta_strength}`.
3. Dopo tipografia: `+{typography_niche:str, styled_words:[{word,start,end,style,display,is_hero,is_number}]}` (display=UPPER per impact se preset; `is_hero` assegnato video-wide da `assign_hero_flags`, `is_number` via digit).
4. Dopo character: `+{chunk_index, pose:int|None (None=nascosto), layout:preset, layout_preset:alias, punch_in:bool, transition_in, position:legacy, transition:legacy, scale:float, block_id:int, char_event: ENTRY|SUSTAIN|EXIT|NONE, char_visible:bool, character:{visible:bool, pose:int|None, pose_id:str, side:LEFT|RIGHT|CENTER, event, block_id}}`.
5. Dopo guard: `+{guard_safe_area:(x0,y0,x1,y1), guard_font_scale:float, guard_pill:bool, [guard_hidden]}` + possibile `layout` switchato/ancorato (`block-anchor...` in `actions`) / `pose` rimossa + sync `character.visible=False`.
6. Dopo render animato: `+{frames:[{image_path,start,end}], frame_paths:[str], clip_start, clip_end (end+tail gap-hold)}`. Dopo statico: `+{image_path:str}`.

### 6.3 Altri contratti
- `theme: {background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB x2-4]}`.
- `keyword_colors_map: {norm_word: (R,G,B,A)}` — chiavi normalizzate `lower+strip punct`.
- `character_plan[i] ↔ chunks[i]` 1:1 per indice; se lunghezze diverse → nessun arricchimento.
- `sections: {hook:[idx], body:[idx], body_beats:[[idx]], beat_tones:[...], cta:[idx], cta_strength, cta_mode}`.
- `preset.anim = {pop_from: 0.6-0.8}` per T2; priorità pop: `chunk.anim_pop_from (hook) > preset > KEYWORD_ENTRY_SCALE_FROM`.
- Frame PNG: `chunk_{idx:04d}_frame_{fi:05d}.png`, finestra `[t, t+1/fps)` + tail clonato. Micro-clip: `chunk_{idx:04d}.mov` (o `.webm`). Audio bulk: `narration_{idx:03d}.mp3`.

---

## 7. Concorrenza, cache e performance

- **GUI:** 1 thread main Tk + 1 worker daemon per batch (mai blocca UI; log via `after`).
- **Pipeline:** ThreadPool x2 (tema+audio) e x3 (character+keyword+typo) in `main.py`; ThreadPool render chunk (2-4 worker) + micro-video ffmpeg (2-4, `max(2,min(4,cpu-1,len))`) se `RENDER_PARALLEL=1` e `>=3` chunk; CTA card sempre sequenziale (layout condiviso).
- **Cache:** Groq client per chiave (max16) in ogni modulo; `_font_cache` renderer, `_typo_font_cache` con chiavi `(path,size[,weight])`, `_character_layer_cache {(pose,w,h)}`, `_image_cache+_original_cache`, `_resolved_path_cache`, `_tight_cache` guard, `_pill_cache` (32), `_char_opacity_cache` (128 con clear a 120, step 8, LUT pre-calcolata), `_local_dir_cache` 30s, `_system_font_cache` (32), tilt cache quantizzata 0.3° (≤9 varianti), singleton `FontManager` condiviso (`_get_shared_font_manager`, pre-warm una volta in `main.py`).
- **Fast path:** `PIPELINE_FAST=1` (euristiche), `compress_level=1` PNG, BILINEAR/BICUBIC per scale animate (LANCZOS solo resize una-tantum), probe 64px, pattern image2 senza stat N (solo primo/ultimo + 2 random), `FFMPEG_PRESET=ultrafast` per bozze, clip riuso via mtime.
- **Thread-safety:** lock per singleton/probe/pill/opacity/tilt; Pillow `Image` non condivise tra thread (copie per layer); `character_animator` math-only senza lock.

---

## 8. Error handling e logging

- **Fatali per singolo video (non bloccano bulk):** `TTSError` (audio), `TranscriptionError` (STT), `VideoBuildError` (ffmpeg). Altri `Exception` catturati con traceback.
- **Non-bloccanti (fallback + proseguono):** theme→default, emphasis/character/tagging/nicchia→deterministico, alignment→raw, keyword→nessuna evidenziazione, animazione→statico, guard→hide, asset mancante→no character (`pose=None`, testo centrale), font→sistema (`""` → `load_default`), hero→nessun hero (video senza T3), gap-hold→0 tail, macro-blocchi→plan invariato.
- **Logging:** `on_attempt(index,total,ok,detail)` propagata ovunque per ciclo chiavi; `_log` GUI thread-safe; riepilogo bulk con conteggi + dialog. Character log prime 10 voci con ruolo `[HOOK]/[CORPO]/[CTA]` + punch; guard log `garantiti/corretti/hidden/intenzionali`; render log ogni 10 chunk.
- **Validazioni input:** script vuoto, audio mancante, timestamp degeneri (`end<=start` → +0.1), layout/words fuori sync → `TextAnimationError`; `pop_from`/`mult`/`weight`/`pose-side` clampati con fallback storici (mai crash per env malformato).

---

## 9. Asset, output, env file

- **Characters:** 5 PNG (`1.png` 1076762B, `2.png` 943688B, `3.png` 930764B, `4.png` 935464B, `5.png` 925998B; 768x1376 figura intera con sfondo nero da pulire via `_remove_black_background`). Pose 1-5 come §5.10 + vincoli `POSE_SIDE_MAP`. Aggiungere posa 6 → aggiornare `CHARACTER_POSE_COUNT`, `_POSE_RULES`, `_POSE_ID_MAP`, `_preset_for_pose`, `_pose_allowed_layouts`, `_POSE_SIDE_DEFAULTS`, asset file.
- **Fonts:** 15 TTF committati (Anton, BebasNeue, Caveat, Cinzel, Inter, LeagueSpartan, Montserrat, Nunito, OpenSans, Oswald, PatrickHand, PlayfairDisplay, Poppins, Roboto, SpaceMono) coprono quasi tutti i preset; mancanti (Impact di sistema, Orbitron/Bodoni variabili, PermanentMarker, Pacifico, Kalam, Lato) scaricati on-demand via `font_manager` (PermanentMarker non più committato). Non cancellare senza test offline.
- **Outputs:** 20 mp4 attuali (da `output_video.mp4` legacy 1.5MB a serie `video_01_stai_ancora...` 1.3-3.6MB + `video_02..06` per nicchia). Naming bulk `video_{i:0{width}d}_{slug}[_k].mp4` (width da totale, slug 5 parole/32 char). Legacy singolo `output_video.mp4` ancora default in `build_video` ma `main.py` usa sempre suggest. Outputs committati appesantiscono repo — valutare gitignore futuro.
- **Temp:** mai committare (gitignore copre solo `.env/__pycache__`, ma temp/output sono runtime).
- **`.env`:** mai committare; `.env.example` è la spec (ora documenta tutte le nuove flag Tier/character/typography come commentate opzionali + `CHARACTER_POSE_SIDES`). `config.py --check-keys` per verifica senza crediti.

---

## 10. Invarianti critici per futuri LLM (leggere prima di modificare)

1. **Timestamp immutabili dopo alignment:** LLM (emphasis/character/tagging/keyword/theme) non devono mai alterare `start/end`; solo indici/tag/colori/layout. `text_animator` assume `layout==words` per conteggio. Il tail gap-hold clona `t_N`, non sposta `end` semantico (solo `clip_end`).
2. **Single source layout:** testo e personaggio risolvono entrambi da `resolve_chunk_layout` + `layout_presets` + `layout_guard`. Non duplicare geometria. L'ancoraggio macro-blocco (`block-anchor`) vince sullo switch singolo.
3. **Z-index:** ffmpeg bg < personaggio < pill < testo. Non invertire.
4. **Punch-in raro:** max 2/video (o hook1+corpo1, CTA 0 via `_cap_punch_ins_narrative`). Non aumentare senza aggiornare cap + guard.
5. **Contrasto:** ogni colore testo/keyword deve superare `THEME_MIN_LUMINANCE_DIFF` sullo sfondo. Validare come `theme.py`/`_styled_fills` (incluso highlight/accent preset + flip base).
6. **Keyword verbatim:** devono esistere `normalize_word` nello script, altrimenti scartate. Non fare fuzzy senza aggiornare renderer match.
7. **Bulk isolamento:** nomi audio/clip/frame per indice; `cleanup_temp_files` dopo ogni video. Non usare nomi fissi condivisi.
8. **Fallback mai crash:** ogni nuovo LLM deve avere fallback deterministico + `try/except` nel chiamante `main.py`. Ogni nuova env deve avere clamp/fallback (vedi `_resolve_motion_params`, `_get_pose_side_map`, `_resolve_base_weight`).
9. **1080x1920 assumption:** safe area/headroom/overhang scalano, ma testare canvas diversi esplicitamente. Il padding idle (4/8px) scala con la tight bbox.
10. **FFMPEG sync:** `fps` clip == `VIDEO_FPS`, `setpts` obbligatorio, `format=yuva420p` solo webm, overlay contigui via `clip_start/clip_end`, GOP 60/keyint_min 30 per short. Non cambiare codec/GOP senza test alpha + seeking.
11. **Hero unico e mai numero (NUOVO):** max 1 `is_hero=True` per video, solo `style==impact` senza cifre; numeri (`is_number`) usano T3-num corto, mai hero. Non assegnare hero in tagger senza passare da `assign_hero_flags` (video-wide).
12. **Macro-blocco stabile (NUOVO):** dentro stesso `block_id` visibile stessa posa+stesso lato+stesso layout (testo opposto al personaggio); tra blocchi visibili adiacenti posa diversa (lato diverso quando possibile); nascosti = `pose=None` + `layout_center_standard` + `character.visible=False`. Non cambiare posa/lato per-chunk dentro un blocco.
13. **Pose-side vincolato (NUOVO):** posa4 sempre `split_left`, posa2 mai split, posa5 mai center stabile. Modificare lati via `CHARACTER_POSE_SIDES` env, non hardcodando in selector/guard/animator.
14. **Gap-hold solo hold+character (NUOVO):** tail solo se `exit_mode==hold` e character presente e `GAP_HOLD_ENABLED`, cap `GAP_HOLD_MAX=1.5s` (frame cap 2s). Non estendere a with_text/slide_down (blink intenzionale/stacco).
15. **Pop priority (NUOVO):** `anim_pop_from (hook) > preset anim.pop_from > KEYWORD_ENTRY_SCALE_FROM`. Non invertire senza A/B visivo. Accent mai scala (rise only), base mai scala (fade only).
16. **Idle senza tilt (NUOVO):** `CHARACTER_IDLE_TILT_DEG=0` default; tilt >0 solo via env esplicito (il dondolio laterale rendeva il video instabile). Bob 4px@0.4Hz con `idle_weight` 0→1/1→0 in ENTRY/EXIT.

---

## 11. Come modificare in sicurezza (ricette)

- **Nuova nicchia:** aggiungi in `VALID_NICHES+NICHE_DESCRIPTIONS+TYPOGRAPHY_PRESETS+_NICHE_KEYWORDS (tagger)`, mappa in `_FONT_FILES` + committa o testa download, verifica `_styled_fills` contrasto, aggiungi `anim.pop_from` (0.6 aggressivo / 0.7 standard / 0.8 soft) e testa T2 vs hook override.
- **Nuovo preset layout:** aggiungi in `VALID_LAYOUT_PRESETS+PRESET_*` (width/headroom/safe/font/side/transition/pill), aggiorna `_preset_for_pose`, `normalize_preset`, `preset_alternate_transition`, `layout_guard` regole (wide pose, tighten/widen, padding idle), prompt `_LAYOUT_RULES`, `describe_preset`.
- **Nuova easing:** aggiungi pura in `easing.py` (`t→float`, usa `clamp01`), referenzia in animator/character_animator con flag config (non cambiare default pop senza A/B visivo). Per character usare `in_out_cubic` (morph) o `out_quad` (fade), mai `back/bounce` (overshoot solo testo).
- **Nuovo segnale CTA:** aggiungi lower in `_CTA_CUES` (sottostringa) o `_CTA_ACTION_VERBS` (parola intera, diventa anche hero T3 se impact senza cifre) + test `_detect_cta` con `CTA_MAX=4` e `_cta_words_count` per card (max 14 parole).
- **Nuova voce TTS:** usa `ELEVENLABS_VOICE_IDS` 1:1, non hardcodare ID in `tts.py`.
- **Nuova posa 2D (es. posa 6):** aggiungi asset `6.png/.jpg`, aggiorna `CHARACTER_POSE_COUNT`, `_POSE_RULES` prompt, `_POSE_ID_MAP`, `_preset_for_pose`/`_pose_allowed_layouts`, `_POSE_SIDE_DEFAULTS` + documenta in `.env.example` (`CHARACTER_POSE_SIDES`), testa `_remove_black_background` + `get_character_tight_*` + guard (pose larga → mai split se necessario).
- **Tuning Breath & Focus:** `CHARACTER_MIN_BLOCK_DURATION` (stabilità vs ritmo), `BODY_VISIBLE_RATIO` (0.6 default: pause brevi distribuite; 1.0 = sempre visibile; 0.0 = solo Hook/CTA), `DISCONTINUOUS_MODE=0` per disabilitare tutto, `HOOK/CTA_VISIBLE` per forzare bordi. Mai modificare `_build_macro_time_blocks` senza aggiornare guard anchoring (`_block_key_of`).
- **Tuning T0-T3:** `ENTRY_DURATION` (base), `HOOK_ENTRY_MULT/POP_FROM` (hook scattante), `ACCENT_LIFT_PX` (rise, mai scala), `HERO_*` (solo 1 parola, mai numeri), `NUMBER_ENTRY_DURATION` (dati secchi). Priorità pop documentata in §6.3.
- **Tuning character motion:** `ENTRY/EXIT` (apparizione/sparizione rapida), `MORPH` (cambi posa/lato fluidi, mai <0.2s o blinka), `PUNCH_ZOOM` (enfasi morbida, mai jump), `IDLE_AMP/FREQ` (vivo ma calmo; tilt resta 0), `GAP_HOLD_MAX` (persistenza pause, mai >2s o frame esplodono).
- **Debug tipico:** `TEXT_ANIMATION_ENABLED=0` per isolare ffmpeg; `CHARACTER_ENABLED=0` per isolare overlap; `NARRATIVE_ENABLED=0` per isolare lock/hero; `PIPELINE_FAST=1` per bulk veloci; `RENDER_PARALLEL=0` per stacktrace ordinati; `DISCONTINUOUS_MODE=0` per isolare Breath&Focus; `IDLE_ENABLED=0` per isolare breathing; `GAP_HOLD_ENABLED=0` per isolare blink.

---

## 12. Limiti noti e debito tecnico (aggiornato)

- Nessun background video/grafico (solo tinta unita tema) — da README.
- Script lunghi (centinaia chunk) → comando ffmpeg lungo (1 overlay/chunk) + encode clip N — mitigato con ThreadPool 2-4 worker + riuso clip via mtime + pattern image2, ma timeline unica resta ottimizzazione futura (da README).
- Keyword solo verbatim (no stemming/embedding).
- Outputs committati (20 mp4, ~30MB) appesantiscono repo; temp pulita ma output no — valutare gitignore futuro o LFS.
- `subtitle_grouping.py` legacy non usato direttamente (ma costanti condivise) — non rimuovere senza refactor.
- `EmphasisGroupingError` definita mai sollevata (fallback silenzioso) — ok ma documentato.
- Font `Pristina/Editors Note/Impact` mappati a `__system__/__missing__` (non open-source) — restano fallback sistema; `PermanentMarker` ora on-demand (non committato) per fitness accent.
- README pipeline 10 step non aggiornato a narrativa/tipografia/guard/CTA card/hero/macro-blocchi/gap-hold/GOP — usare questo report come fonte verità.
- Rimosso `core/character_geometry.py` (fuso), `tests/` (nessun test automatico attivo — regressioni solo manuali via `PIPELINE_FAST` + video campione), `README-dev.md`.
- `character_animator.py` è reference math-only isolato (non ancora innestato nel paste reale di `text_animator.py`, che duplica la logica con Pillow) — futura unificazione per evitare divergenza ENTRY/EXIT/idle.

---

## 13. Setup rapido (per verifica)

```powershell
# 1. ffmpeg in PATH
ffmpeg -version
# 2. dipendenze
pip install -r requirements.txt
# 3. env
Copy-Item .env.example .env
# compila ELEVENLABS_API_KEYS, GROQ_API_KEYS
python config.py --check-keys
# 4. avvio
python main.py
# bulk: spunta "una riga = un video", carica .txt, Genera N Video → outputs/
# tuning rapido: PIPELINE_FAST=1 per bozze, FFMPEG_PRESET=ultrafast per bozze,
# DISCONTINUOUS_MODE=0 per personaggio sempre visibile, TEXT_ANIMATION_ENABLED=0 per statico
```

---

## 14. Glossario rapido (aggiornato)

- **Chunk:** 2-3 parole con timing, unità sottotitolo/animazione.
- **Beat:** frase/pensiero nel corpo (1+ chunk), unità stabilità personaggio (legacy; ora i macro-blocchi raggruppano più beat per durata ≥2.5s).
- **Macro-blocco:** apparizione stabile (Hook 1 blocco, Body a sezioni ≥2.5s, CTA 1 blocco) con unica posa+lato+layout ed eventi ENTRY/SUSTAIN/EXIT; unità Breath & Focus.
- **ENTRY/SUSTAIN/EXIT/NONE:** ciclo vita character per chunk (entrata slide&pop / regime idle / uscita slide-drop / nascosto).
- **Breath & Focus:** presenza discontinua (visibile Hook/CTA + ~60% Body, pause 1 blocco solo testo) + stabilità (no flicker per-chunk).
- **Gap-hold tail:** persistenza `hold` nei gap TTS (`clip_end` oltre `end`, frame `t_N` clonati, overlay contigui anti-blink).
- **Punch-in:** jump-cut ingrandimento per enfasi (stacco camera, no transizione morbida; ora zoom fluido 0.60s, max 2/video, mai CTA).
- **Morph:** cambio posa/lato opaco fluido 0.40s (anti-blink, niente flash).
- **Idle breathing:** bob verticale 4px@0.4Hz (vivo ma calmo, tilt 0).
- **Safe area:** box testo garantito senza overlap personaggio (con padding idle).
- **Pill:** rettangolo arrotondato semi-trasparente dietro testo (contrasto punch-in/CTA, cache max 32).
- **Card CTA:** messaggio finale persistente con reveal karaoke.
- **Impact/accent/base:** livelli tipografici (urlato/handwritten/normale) = Tier T2/T1/T0.
- **Hero T3:** 1 parola/video (verbo CTA o climax hook, mai numeri), pop marcato + hold.
- **T3-num:** impact con cifre, pop corto dedicato, mai hero.
- **Tight bbox:** box alpha reale personaggio (non full asset) + padding idle.
- **Pose-side constraint:** vincolo lato per posa (`any|center|left|right|split` da `CHARACTER_POSE_SIDES`).
- **Block-anchor:** layout unico per tutto il macro-blocco visibile (testo opposto al personaggio, nessun salto).
- **GOP 60:** keyframe ogni 2s per seeking preciso sulle caption (vs default 250).

---

## 15. Changelog rispetto al report precedente (ottimizzazioni apportate)

- **NUOVO `core/character_animator.py` (169 righe):** `CharacterFrameAnimator` math-only con `idle_weight`, offset +300/-400px, `event_of/is_visible` dual-read (`character` dict + legacy). Spec per macro-blocchi.
- **`character_selector.py` 996→2015 righe:** macro-blocchi Breath & Focus (`_macro_role`, `_build_macro_time_blocks`, `_select_block_pose_layout`, `_apply_macro_block_stabilization` con `character` dict + `pose_id/side/event/block_id`), ritmo calmo (`_enforce_rhythm_variety` con `MAX_SAME_*`, `side_cycle`, transizioni alternate), vincoli posa centralizzati (`POSE_SIDE_MAP`), fallback ciclo 8-step dinamico, no-repeat tra blocchi, CTA senza punch.
- **`text_animator.py` 2303→3323 righe:** Tier T0-T3 completi (`_resolve_motion_params` con priorità hook>preset>globale, `_word_tier`, `_hero_exit_factor`), `TYPOGRAPHY_BASE_WEIGHT=600` (`_resolve_base_weight`, `_apply_font_weight` variable-axis + sintetico), gap-hold tail (`tail_hold_duration`, `clip_start/clip_end`), morph 0.40s + punch zoom 0.60s + idle tilt quantizzato, CTA card con hero/number, `is_hero/is_number` ovunque.
- **`narrative_structure.py` 408→506 + `text_tagger.py` 659→690:** `assign_hero_flags` video-wide (CTA verbo → hook contenuto lungo, numeri esclusi, function-word escluse), `is_number` via digit in boost + enrich, chiamata lazy da tagger.
- **`typography_presets.py` 232→254:** `anim.pop_from` per nicchia (0.6/0.7/0.8), dark accent open-source fix.
- **`layout_guard.py` 682→805:** ancoraggio macro-blocchi (`block-anchor`, `pose-hold`, `block-anchor-hidden-center`, forzato + pill), padding idle 4/8px, niente beat-lock.
- **`layout_presets.py` 291→319:** `preset_alternate_transition`, doc pose-side-map.
- **`easing.py` 101→135:** `ease_in_out_cubic` (morph), `ease_out_quad` (fade character), `ease_in_out_quad` (continuità breve).
- **`video_builder.py` 414→468:** finestre contigue anti-blink (statico+animato), riuso clip mtime + spot-check, ThreadPool `min(4,cpu-1)`, GOP 60/keyint_min 30, `filter_threads` auto.
- **`config.py` 359→483 + `.env.example`:** 20+ nuove variabili (Tier hero/number/accent, ritmo, idle, entry/exit/morph/punch, gap-hold, macro-blocchi, pose-side-map, base weight) tutte clampate con fallback, documentate come opzionali commentate.
- **`font_manager.py`:** `permanentmarker` on-demand, heuristic hand/marker, `__system__` handling stabile.
- **Cleanup repo:** rimossi `character_geometry.py` (1171), `tests/`, `README-dev.md`, `PermanentMarker.ttf` committato; outputs 11→20 mp4; `main.py` pre-warm singleton font manager.

---

## 16. Full Engine Upgrade (Fasi 1-6, 25/09/2026)

Z-Index strict: bg Z=0 < character Z=10 < dimmer Z=20 < subtitles Z=30 < debug Z=99 (`config.Z_*`). Timestamp `start/end` mai alterati (verificato da `invariant_checks`).

- **Fase 1 — config + `core/timestamp_enricher.py` (NUOVO):** `ENABLE_ADVANCED_KINETICS / ENABLE_DYNAMIC_BACKGROUNDS / ENABLE_AUTO_SFX (=1)`, `SFX_VOLUME_DB (-15)`, `BG_MUSIC_DUCKING_DB (-12)`, `HERO/BASE_WORD_FONT_PATH`, `COLOR_BRAND_ACCENT (#FF3366)`, `COLOR_HERO_BG (#000000A6)`, `EASING_CURVES` + `KINETIC_*` (T2 peak 1.10/4f, T3 shake 4px, T0 stroke 3px), `DYNAMIC_BG_*` (zoom max 1.08 step 0.0015 d=125), `CHARACTER_MICRO_*` (xfade 4f, scala 2%), `LAYOUT_MAX_WIDTH_RATIO (0.80)` / `LAYOUT_MIN_FONT_PX (40)`. `enrich_whisper_timestamps(data, keywords, hero_words, single_hero)` → tier T0-T3 + vfx (`none/pop_scale/glow/badge_slide`) + `sfx_trigger`, copie nuove (originali mai mutati), chiamato in `main.py` dopo alignment (merge solo chiavi additive).
- **Fase 2 — `core/advanced_kinetics.py` (NUOVO) + hook `text_animator.py`:** `GlyphCache` LRU 512, `lerp/scale_at/opacity_at/rotation_at`, `t2_peak_scale` (110% primi 3-4f), `hero_shake_offset` (sinusoide ±4px), `advanced_stroke_for` (T0/T1 3px neri solo se enabled), `advanced_entry_duration` (T0/T1 2 frame), `brand_accent_rgba/hero_bg_rgba`, `draw_hero_badge` (pill sotto glifo Z=30). Hook: entry T0/T1 clampate + fill T2→brand accent (T3 tiene highlight+badge) prima del loop; per-frame badge+shake e peak applicati; a flag spento path legacy invariato.
- **Fase 3 — character micro-transizioni + bridge:** `narrative_structure.emotional_intensity` (0..1 da !/?/caps/cifre/CTA/positive/hook) + `pose_for_emotion` (5 domande/surprised, 4 dati/pointing, 3 CTA/positivo, 1 hook intenso); `_pose_for_text` con override espressivo se intensità ≥0.7. `character_selector.is_focus_pose_switch / micro_blend_progress / micro_scale_factor / blend_character_layers` (cross-fade alpha 3-4f + micro-scala sin 2%, mai muta input); `text_animator.generate_animated_chunk_frames(..., char_prev_layer, char_micro_blend)` + `render_all` passa il layer precedente quando stesso `block_id` visibile e posa diversa (macro-blocchi già locking posa/blocco; ENTRY tra blocchi resta slide, mai blend).
- **Fase 4 — `layout_guard.py` dinamico:** `dynamic_max_text_width` (80% per bottoni laterali), `dynamic_min_font_scale` (min 40px), `widest_line_px` (bbox per riga), `rewrap_split_point` (pausa forte→virgola→metà), `verify_z_order` (testo in [80,150,W-80,H-320], character Z=10 dietro testo Z=30, stack coerente), `debug_safezone_boxes` (4 box rossi). `plan_chunk_realtime`: `mw=min(0.85W, 80%)` + Fix 1b auto-scale-to-min + rewrap forzato; mai eccezioni.
- **Fase 5 — `core/audio_mixer.py` + `core/video_composer.py` (NUOVI):** mixer SFX sintetizzati offline (`pop` 880Hz T3, `click` 1400Hz CTA, `whoosh` rumore filtrato ENTRY, adelay al ms, amix, cap 24 eventi, dedup 80ms) a `SFX_VOLUME_DB`, ducking sidechain voce→musica (`threshold 0.02, ratio 8, attack 20ms, release 400ms` per risalita pause >0.5s) a `BG_MUSIC_DUCKING_DB`; fallback voce originale se disabilitato/fallito. Composer: Ken Burns `zoompan(min(zoom+step,max),d=125,centered)` su color 1.2x + `eq+vignette` Z=20 solo sfondo, poi overlay chunk contigui come legacy (setpts, GOP 60), debug Z=99 opzionale; delega legacy se dinamico spento; mux audio atomico separato.
- **Fase 6 — `main.py` CLI + `core/invariant_checks.py` (NUOVO):** `--render-mode=full|text_only|debug_safezones` (CLI>env>full), `--script file [--bulk]` headless senza Tk, `--help`. `text_only`: solo grafica testo (frame+preview txt, nessun ffmpeg pesante <5s). Step 8: mix SFX best-effort → compose (debug flag) → `run_post_build_checks` (AV-sync <0.1s, temp containment, timestamp preservation, z-order fuori-canvas) loggati, non fatali. `main.py` resta GUI di default ed eseguibile dopo ogni fase.

---

*Fine report — generato da analisi esaustiva di tutti i 20 file .py + asset + config + git log al 25/09/2026. Per dubbi, rileggere §10 prima di ogni modifica.*
