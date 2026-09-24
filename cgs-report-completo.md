# CGS — Report Completo, Dettagliato e Ottimizzato per LLM

> **Scopo di questo documento:** permettere a **qualsiasi altro LLM** di comprendere al 100% funzionalità, struttura, logica, contratti dati, dipendenze e invarianti del progetto **CGS (Video Generator v2)** per applicare modifiche in maniera coerente senza regressioni.
> **Lingua:** Italiano. **Root progetto:** `C:\Users\thinkpad\Desktop\CGS` (repo git). **Piattaforma primaria:** Windows + Python + ffmpeg.
> **Stile video prodotto:** verticale 9:16 (1080x1920 @30fps), sfondo tinta unita premium, audio narrato, sottotitoli animati per-parola stile TikTok, personaggi 2D overlay, tipografia semantica per nicchia, struttura narrativa hook/corpo/CTA.

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
   - `Step 5.2`: Classificazione narrativa hook/corpo-a-beat/CTA (deterministica).
   - `Step 5.5-6.5 (parallelo x3)`: Piano personaggi + Estrazione keyword + Analisi tipografica.
   - `Step 6.8`: Layout Guard real-time anti-overlap.
   - `Step 7`: Rendering frame animati per-parola (Pillow + easing) o fallback PNG statici.
   - `Step 8`: Composizione video finale ffmpeg (micro-video per chunk + overlay unico) → `outputs/`.
   - Cleanup `temp/` dopo ogni video (isolamento bulk).

### 1.2 Stack tecnologico
- **GUI:** `tkinter` standard (no dipendenze esterne), `ScrolledText` per preview/log.
- **TTS:** `requests` → `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=...`
- **LLM + STT:** SDK `groq` (`Groq`, `chat.completions.create`, `audio.transcriptions.create`).
- **Imaging:** `Pillow` (`Image`, `ImageDraw`, `ImageFont`, `ImageColor.getrgb`).
- **Video/Audio:** binari esterni `ffmpeg` + `ffprobe` invocati via `subprocess` (obbligatori in PATH).
- **Config env:** `python-dotenv` (con fallback parser integrato se mancante).
- **NLP leggera:** `difflib.SequenceMatcher`, `re`, `hashlib.md5`, `colorsys`, `json`.
- **Concorrenza:** `threading.Thread` (GUI), `concurrent.futures.ThreadPoolExecutor` (parallelo pipeline/render/ffmpeg).
- **Asset:** `assets/characters/1.png..5.png`, `assets/fonts/*.ttf` (15 font committati + download on-demand).

### 1.3 Requisiti runtime
- `ffmpeg -version` e `ffprobe` in PATH. Senza → `VideoBuildError` esplicito.
- `pip install -r requirements.txt`: `requests>=2.31.0`, `groq>=0.9.0`, `Pillow>=10.0.0`, `python-dotenv>=1.0.0`.
- API keys in `.env` (root progetto, mai committato, vedi `.gitignore`) o variabili sistema. Comando verifica gratuita: `python config.py --check-keys`.
- Avvio: `python main.py`.

---

## 2. Struttura file completa (inventario esaustivo)

```
CGS/
├── main.py                    # GUI Tkinter + orchestratore pipeline bulk (582 righe)
├── config.py                  # Config centrale, env, multi-key, check-keys (359 righe)
├── requirements.txt           # 4 dipendenze
├── .env                       # Segreti reali (NON committare, in .gitignore)
├── .env.example               # Template documentato (112 righe)
├── README.md                  # Doc utente v2 (pipeline 10 step, setup, limiti)
├── .gitignore                 # .env, __pycache__/, *.pyc
├── cgs-report-completo.md     # Questo report
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
│   ├── text_animator.py       # Frame animati per-parola + typography + CTA card (2303 righe)
│   ├── video_builder.py       # ffmpeg finale + micro-clip (414 righe)
│   ├── character_selector.py  # Piano personaggi LLM + asset + resolve (996 righe)
│   ├── narrative_structure.py # Hook/beat/CTA deterministico (408 righe)
│   ├── text_tagger.py         # Nicchia + tagging base/impact/accent (659 righe)
│   ├── typography_presets.py  # 6 preset nicchia (232 righe)
│   ├── font_manager.py        # Download/cache font Google Fonts (416 righe)
│   ├── layout_presets.py      # 4 zone layout + geometria (291 righe)
│   ├── layout_guard.py        # Guard anti-overlap real-time (682 righe)
│   └── easing.py              # Curve Penner pure (101 righe)
├── assets/
│   ├── characters/1.png..5.png  # 5 pose (braccia incrociate, aperte, pollice, indica, mento)
│   └── fonts/*.ttf (15)         # Anton, BebasNeue, Caveat, Cinzel, Inter, LeagueSpartan, Montserrat, Nunito, OpenSans, Oswald, PatrickHand, PlayfairDisplay, Poppins, Roboto, SpaceMono
├── outputs/*.mp4 (11)         # Video finali (es. video_01_slug.mp4, output_video.mp4 legacy)
└── temp/                      # File temporanei (narration_*.mp3, subtitle_*.png, chunk_*_frame_*.png, chunk_*.mov, concat lists) — svuotata dopo ogni video
```

> **Nota README obsoleto:** descrive `core/renderer.py` + overlay per chunk come architettura v2 base; il codice attuale ha evoluto in `text_animator.py` + personaggi + tipografia + narrativa + guard. Il README resta valido per setup/env ma non per i nuovi sottosistemi.

---

## 3. Configurazione centrale (`config.py` + `.env`)

### 3.1 Caricamento env
- `BASE_DIR = dirname(abspath(__file__))`, `ENV_PATH = BASE_DIR/.env`.
- `_load_env_file()`: prima `dotenv.load_dotenv(ENV_PATH)` (env sistema ha precedenza), fallback parser manuale riga-per-riga (`KEY=valore`, strip quotes, supporta `export `, ignora commenti, non sovrascrive env esistenti).
- Helper: `_get_int`, `_get_float`, `_get_tuple("R,G,B,A")`, `_get_str_or_none`, `_get_str_list(*names)` (split virgola+a-capo, strip quotes/spazi, dedup preservando ordine), `_get_key_list` alias.
- `OUTPUT_DIR`, `TEMP_DIR` creati con `os.makedirs(exist_ok=True)` all'import.

### 3.2 Tabella variabili completa

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
| `TEXT_ANIMATION_ENTRY_DURATION` | `0.18` | `text_animator` | Entrata singola parola (s). |
| `TEXT_ANIMATION_EXIT_DURATION` | `0.15` | `text_animator` | Fade-out gruppo (s). |
| `KEYWORD_ENTRY_SCALE_FROM` | `0.7` | `text_animator` | Scala iniziale pop keyword →1.0. |
| `CHARACTER_ENABLED` | `1` | `main, renderer, animator` | `0`=nessun personaggio. |
| `CHARACTERS_DIR` | `BASE_DIR/assets/characters` | `character_selector` | Asset `1.jpg/.png` ecc. |
| `CHARACTER_VALID_POSITIONS/TRANSITIONS` | `bottom_center,.../slide_up,...` | `character_selector` | Vocabolario legacy (alias `CHARACTER_POSITIONS/TRANSITIONS`). |
| `CHARACTER_POSE_COUNT` | `5` | `character_selector` | Range pose 1..5. |
| `CHARACTER_SCALE_MIN/MAX` | `0.65/0.90` | `character_selector` | Clamp scala legacy. |
| `TYPOGRAPHY_ENGINE_ENABLED` | `1` | `main, animator, tagger` | `0`=path legacy singolo font. |
| `TYPOGRAPHY_BASE_FONT_SIZE` | `60` | `animator, presets` | Base prima di `font_scale` preset. |
| `TYPOGRAPHY_IMPACT_SCALE/ACCENT_SCALE` | `1.4/1.1` | `animator` | Moltiplicatori (clamp 1.2-1.6 / 1.0-1.3). |
| `TYPOGRAPHY_STROKE_WIDTH` | `0` | `animator` | Sempre 0 default (pulito). |
| `TYPOGRAPHY_SHADOW_ENABLED/OFFSET/FILL` | `0/(3,3)/(0,0,0,180)` | `animator` | Ombra OFF default. |
| `FONTS_DIR` | `BASE_DIR/assets/fonts` | `font_manager` | Cache font. |
| `NARRATIVE_ENABLED` | `1` | `main, narrative_structure` | `0`=pipeline piatta. |
| `NARRATIVE_HOOK_MAX_CHUNKS` | `3` | `narrative_structure` | Hook = prime 1-3 caption. |
| `NARRATIVE_CTA_MAX_CHUNKS` | `4` | `narrative_structure` | CTA = ultime 1-4 con segnali. |
| `NARRATIVE_CTA_CARD` | `1` | `narrative/animator` | Card karaoke persistente se CTA forte+breve. |
| `NARRATIVE_CTA_CARD_MAX_WORDS` | `14` | `narrative` | Soglia parole card. |
| `NARRATIVE_HOOK_ENTRY_MULT` | `0.7` | `narrative/animator` | Hook più scattante (0.3-1.0). |
| `NARRATIVE_HOOK_POP_FROM` | `0.55` | `narrative/animator` | Pop hook marcato (0.1-1.0). |
| `PIPELINE_FAST` | `0` | `emphasis, character, tagger` | `1`=salta LLM pesanti → euristiche istantanee (tema+keyword restano LLM). |
| `RENDER_PARALLEL` | `1` | `text_animator` | `1`=ThreadPool chunk + micro-video. |
| `FFMPEG_PRESET` | `veryfast` | `video_builder` | Whitelist `ultrafast..medium`, fallback veryfast. |
| `OUTPUT_DIR/TEMP_DIR` | `BASE_DIR/outputs/temp` | tutti | Override opzionale. |

### 3.3 `get_elevenlabs_voice_id(key_index, total_keys)` + `check_keys()`
- Risoluzione voce come da tabella sopra; solleva `ValueError` se lista ambigua (es. 2 voci per 3 chiavi).
- `check_keys() → int(bad)`: `GET /v1/user` ElevenLabs (mostra tier + `character_count/limit`) e `GET /v1/models` Groq (`Authorization: Bearer`), senza consumare crediti. Usato da `python config.py --check-keys`. Maschera chiavi `primi4...ultimi2`.

---

## 4. Entry-point e GUI (`main.py`)

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
6. **`[5.2/8]`** Se `NARRATIVE_ENABLED`: `classify_narrative(chunks, script, _log_attempt)` → `(sections, chunks_arricchiti)`. Log hook/body_beats/CTA+strength/mode. Else log disabilitata.
7. **`[5.5-6.5/8]` Parallelo x3 (ThreadPool max 3):** `plan_character_layout(chunks_base, script)` se `CHARACTER_ENABLED` + `extract_keywords(script, _log_attempt, theme[keyword_colors])` + `enrich_chunks_with_typography(chunks_base, script, None)` se `TYPOGRAPHY_ENGINE_ENABLED`. Raccolta con try separati (character/keyword/typo mai bloccanti). Log prime 10 voci character (`[HOOK] chunk i: posa X (layout+punch, transition)`), n keyword, nicchia, font paths (pre-warm via `_get_shared_font_manager().ensure_preset_fonts`), colori preset, conteggi base/impact/accent. Merge: `chunks = chunks_typo` se presente, poi `enrich_chunks_with_characters(chunks, character_plan)`.
8. **`[6.8/8]`** `build_realtime_plan(chunks)` + `apply_realtime_plans` → log `garantiti/corretti/hidden/intenzionali`.
9. **`[7/8]`** Se `TEXT_ANIMATION_ENABLED`: `render_all_chunks_animated(chunks, bg, text, keyword_colors, TEMP_DIR, VIDEO_FPS, on_chunk, typography_niche)` con log ogni 10 chunk; `except TextAnimationError` → fallback `render_all_subtitles(chunks, keyword_colors, text_rgba)`. Else statico diretto.
10. **`[8/8]`** `build_video(audio_path, enriched_chunks, output_filename, bg)` → ritorna path.

---

## 5. Moduli core in dettaglio

### 5.1 `core/script_loader.py` — parsing bulk puro, testabile
- `parse_scripts(text, bulk_mode)`: `False`→`[stripped]` o `[]`; `True`→`[strip(line) for line in splitlines() if strip]` (preserva ordine, tollera BOM via strip, mai solleva).
- `load_scripts_from_file(path, bulk_mode)`: `open utf-8` (no fallback latin-1 nel codice attuale) → `parse_scripts`. Solleva `OSError` se illeggibile.
- `slugify(text, max_words=5, max_len=32)`: regex `[A-Za-zÀ-ÖØ-öø-ÿ0-9]+`, lowercase, join `_`, strip non-`[a-z0-9_]`, fallback `"script"`.
- `suggest_output_filename(index, script, total, output_dir, prefix="video", ext=".mp4")`: `width=max(2,len(str(total)))`, `base=f"{prefix}_{i:0{width}d}_{slug}{ext}"`; se `output_dir` e file esiste → `_1,_2...` fino a 999. Non crea file.
- `preview_of(script, max_len=80)`: collapse whitespace + `...`.

### 5.2 `core/tts.py` — ElevenLabs
- **Endpoint:** `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={ELEVENLABS_OUTPUT_FORMAT}`, headers `xi-api-key, Content-Type: application/json`, body `{text, model_id, voice_settings:{stability:0.5, similarity_boost:0.75}}`, timeout 120s.
- **Firma:** `generate_audio(script_text, output_filename="narration.mp3", on_attempt=None) → abs path in TEMP_DIR`.
- **Failover:** loop chiavi in ordine con voci risolte `get_elevenlabs_voice_id`. `_RETRYABLE_STATUS={401,402,403,429,500,502,503,504}` + `404` solo se voci diverse (1:1). Su rete/retryable → `failures.append + on_attempt(False) + continue`. Su `400/404-voce-unica/422` → `raise TTSError(detail)` immediato (altra chiave non aiuterebbe). Se tutte falliscono → `TTSError("Tutte le N chiavi... | ".join(failures))`.
- **Validazioni:** script vuoto → `TTSError`; no keys → `TTSError`; `ValueError` voci → `TTSError`.
- **Eccezione:** `class TTSError(Exception)`.

### 5.3 `core/transcription.py` — Groq Whisper
- **Chiamata:** `Groq(api_key).audio.transcriptions.create(file=open(rb), model=GROQ_WHISPER_MODEL, response_format="verbose_json", timestamp_granularities=["word"])`.
- **Firma:** `transcribe_audio(audio_path, on_attempt=None) → [{word,start,end}]` (gestisce sia dict sia oggetti SDK).
- **Cache client:** `_groq_client_cache: dict[key,obj]` max 16.
- **`_is_retryable_with_next_key(e)`:** `False` solo se `status_code in (400,404,422)` E messaggio senza hint retryable; altrimenti `True` (meglio un tentativo in più). Hint include `rate limit, quota, credit, billing, expired, invalid api key, unauthorized, overload, timeout, connection, unavailable, server error + 401/402/403/429/500/502/503/504`.
- **Loop:** su eccezione → `on_attempt(False)` + `continue` se retryable e non ultima, else `raise TranscriptionError` immediato (non-chiave) o aggregato (ultima). Su successo → `on_attempt(True)` + `break`.
- **Validazioni:** no keys, file mancante, `words` vuote → `TranscriptionError`.
- **Eccezione:** `class TranscriptionError(Exception)`.

### 5.4 `core/alignment.py` — difflib script↔trascrizione
- **Perché:** Whisper sbaglia omonimi/nomi/punteggiatura; l'audio è generato dallo script quindi i sottotitoli devono mostrare parole script con tempi Whisper.
- **Firma:** `align_transcript(transcribed, script_text) → (aligned, stats)` con `stats={match_ratio (ratio() arrotondato 3), corrected, interpolated, extra}`.
- **Algoritmo:** `script_tokens=split()`, `normalize_word` da keywords (lower + strip punteggiatura bordi), `SequenceMatcher(a=script_norm, b=tr_norm, autojunk=False).get_opcodes()`:
  - `equal`: copia dict trascritto ma `word=script_tokens` esatta.
  - `replace`: accoppia `min(len)` (tempi Whisper, parole script, `corrected+=`), se script più lungo → `_interp_missing` (distribuisce uniformemente `prev_end→next_start`, fallback `prev_end+0.3*n`), `interpolated+=`; se trascritto più lungo → tiene extra per continuità, `extra+=`.
  - `delete` (saltata da Whisper): interpola. `insert` (extra): tiene.
- **`_enforce_monotonic`:** garantisce `start>=prev_end`, `end>start` (+0.05 se degenere).
- **Eccezione:** `class AlignmentError` se input vuoti. Chiamante la tratta come non-bloccante.

### 5.5 `core/theme.py` — palette premium LLM
- **Output:** `{background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB...]}`. Mai blocca: fallback `DEFAULT_THEME={#0F172A,#FFFFFF, _FALLBACK_PALETTE_HEX}`.
- **Design system:** `PREMIUM_BACKGROUNDS` 12 neri cinematici (Onyx, Midnight Slate, Graphite, Espresso, Deep Navy, Slate Navy, Plum Black, Forest Black, Warm Charcoal, Teal Black, Ember Black, Coffee Black); `PREMIUM_TEXTS=[#FFFFFF,#F5F5F5,#FDFBF7]`; `PREMIUM_ACCENTS` 8 ori/sky/ciano/lavanda/rosa/menta (mai gialli neon puri).
- **Prompt:** system `art director premium... SOLO JSON`, user con regole rigide (bg solo da lista, testo solo bianco, keyword max 3-4 armonici, vietati saturi/neon/arcobaleno) + `SCRIPT`. `temperature=0.3, max_tokens=1024, response_format={"type":"json_object"}`, modello `GROQ_THEME_MODEL`, loop chiavi con `on_attempt`.
- **Validazione `_validate_theme(raw)`:**
  - bg non-hex o `_is_garish_background` (lum>70 o croma max-min>80) → `_nearest_premium_bg` (distanza RGB + bonus tinta calda/fredda -800).
  - testo non-`_is_near_white` (lum>=190 e sat<=0.25) o contrasto `<THEME_MIN_LUMINANCE_DIFF` → bianco a max contrasto.
  - keyword: scarta non-hex, `_is_yellowish` (`r>230,g>195,b<100` — vieta #FFD700/#FFFF00 ma permette ori #D4AF37/#FFD166), `_is_pure_neon`, `sat>0.95 & lum>180`, basso contrasto, duplicati, anti-arcobaleno (tinte distinte >25° o neutre sat<=0.15); max 4; integra da `PREMIUM_ACCENTS+_FALLBACK_PALETTE_HEX`; rete finale oro+sky se <2.
- **Helper:** `hex_to_rgb/rgba`, `luminance` (0.299r+0.587g+0.114b), `_saturation_of/_hue_of` (colorsys HSV), `_parse_theme` (strip fence markdown ```).
- **Eccezione:** `class ThemeError` solo per script vuoto.

### 5.6 `core/emphasis_grouping.py` — chunk 2-3 parole
- **Output:** `[{text,start,end,words:[{word,start,end}]}]` — stessa forma di subtitle_grouping + chiave `words` per animazioni.
- **LLM:** riceve SOLO parole indicizzate (sicurezza: testo/timestamp non alterabili), restituisce SOLO `{"cut_indices":[...]}` (ultima parola di ogni gruppo). Prompt con regole: 1-3 parole (preferisci 2-3), 3 ok se terza leggera (articolo/preposizione), mai iniziare gruppo con leggera isolata, punteggiatura forte `. ! ? ... : ;` = taglio obbligato. `temperature=0.2, max_tokens=1024, json_object`, modello `GROQ_LLM_MODEL`, loop chiavi.
- **Validazione `_validate_cuts(cuts,n)`:** lista non-vuota, int (no bool), range `[0,n-1]`, unici + ordinati, ultimo=`n-1`, size gruppo in `[MIN,MAX]` da config.
- **Fallback `_deterministic_fallback`:** blocchi da 2 (3 se terza `_is_weak` = in `_WEAK_TRAILING_WORDS` e senza strong punct), taglio su `_ends_strong`. Usato se `PIPELINE_FAST=1`, no keys, LLM fallisce o tagli invalidi (con `on_attempt(succeeded_at,total,False,"tagli LLM invalidi...")`).
- **Mai solleva** per errori API (ritorna fallback); `class EmphasisGroupingError` definita ma non usata come fatale.
- **Dipendenze:** importa `_WEAK_TRAILING_WORDS,_STRONG_PUNCT` da subtitle_grouping, `normalize_word` da keywords.

### 5.7 `core/subtitle_grouping.py` — legacy per frasi (riferimento/fallback)
- **Output:** `[{text,start,end}]` (senza `words`).
- **Regole:** chiudi su strong punct (`. ! ? ... : ;`); se `len>=SUBTITLE_MAX_CHARS(38)` o `count>=SUBTITLE_MAX_WORDS(7)` chiudi su virgola o dopo parola intera (non lasciare weak trailing `di,a,da,in,con,su,per,tra,fra,il,lo,la,i,gli,le,un,una,uno,e,o,ma,che,non,si,mi,ti,ci,del,della,dei,delle,dello,al,allo,alla` isolata a fine chunk).
- **Post-process `_merge_short_chunks`:** fonde chunk `<12 char` con adiacente se combinato `<=MAX+15`.
- **Uso attuale:** non chiamato direttamente in `main.py` (sostituito da emphasis), ma fornisce costanti condivise + path concettuale alternativo. **Non rimuovere** senza aggiornare import emphasis/narrative.

### 5.8 `core/keywords.py` — keyword LLM
- **Output:** `{parola_normalizzata: colore_RGBA}`.
- **Palette:** `_FALLBACK_PALETTE_HEX` 8 hex premium (importata da theme come default/integrazione), `KEYWORD_PALETTE` derivata RGBA, `color_for_keyword(word,palette)` deterministico `md5(word)%len(pal)` (stessa parola=sempre stesso colore).
- **Prompt:** `Estrai al massimo {target} parole SINGOLE esattamente come appaiono, distribuite inizio/centro/fine, ordine importanza → {"keywords":[...]}`. `target=max(3,min(KEYWORDS_MAX,len//30))`. `temperature=0.2, max_tokens=512, json_object`.
- **Parsing `_parse_keywords`:** strip fence, `json.loads`, fallback regex `\[.*?\]`; accetta dict con `keywords` o lista bare; solo singole parole (no spazi), `normalize_word`, dedup.
- **Spread `_spread_keywords(candidates, script_words, target)`:** accetta in ordine importanza solo se `pos PrimaOccorrenza` dista `>=gap` da accettate (`gap=max(MIN_GAP, len//target//2)`). Scarta parole non verbatim nello script (flessioni diverse non matchano — limite noto).
- **Palette effettiva:** se `keyword_palette_hex` (dal tema) fornita → converti `_hex_to_rgba` (via `PIL.ImageColor.getrgb`), else storica; su hex invalidi → storica.
- **Errori:** `class KeywordError` (script vuoto, no keys, tutte fallite). Chiamante la tratta come non-bloccante (prosegue senza evidenziazioni).

### 5.9 `core/narrative_structure.py` — 3 atti deterministico
- **Filosofia:** tutto deterministico (posizione+punteggiatura+segnali, mai LLM) per stabilità.
- **Firma:** `classify_narrative(chunks, script_text="", on_attempt=None) → (sections, enriched)` dove `sections={hook:[idx], body:[idx], body_beats:[[idx]], beat_tones:[...], cta:[idx], cta_strength: strong|soft|none, cta_mode: card|locked|none}`, `enriched=chunk+{narrative_role:hook|body|cta, narrative_beat:int(-1 fuori corpo), beat_tone, anim_entry_mult/anim_pop_from (solo hook), cta_card:bool, cta_section_id, cta_strength}`. Mai solleva.
- **Rilevamento:** `_detect_cta` = sequenza finale (max `NARRATIVE_CTA_MAX_CHUNKS`) con `_CTA_CUES` (50+ sottostringhe IT+EN: segui,follow,iscriv,commenta,link,bio,clicca,scarica,gratis,condividi,salva,like,scopri,compra,sconto,dm,scrivimi,tap,swipe...). Se nessuna → se `n>=3` ultimo chunk `soft` (outro debole stabilizzato), else `none`. `_detect_hook` = prima frase entro `HOOK_MAX` (mai dentro CTA); se nessuna frase chiusa → 1 chunk se `n<=3` else 2. `_split_body_beats` = split su `_STRONG_END (. ! ? …, :, ;)` + merge beat da 1 chunk.
- **`beat_tone(beat_chunks)`:** `question` se `?`, `data` se `\d`, `key` se `!` o cue, else `explainer`.
- **`boost_typography_styles(styled, role, ...)`:** hook garantisce ≥1 impact (parola contenuto più lunga, no function words); cta verbi `_CTA_ACTION_VERBS` (seguimi,iscriviti,commenta...) → impact + garantisce ≥1; aggiorna `display` uppercase se richiesto.
- **CTA card mode:** `card` solo se `strong` + `NARRATIVE_CTA_CARD=1` + parole totali `<=CTA_CARD_MAX_WORDS(14)`, else `locked` (bloccato senza card) o `none`.
- **Se `NARRATIVE_ENABLED=0`:** ritorna tutto body, 1 beat unico.

### 5.10 `core/character_selector.py` — personaggi 2D + Dynamic Layout
- **Pose semantica:** 1 braccia incrociate (hook/fatti), 2 aperte (spiegazioni), 3 pollice (soluzioni/CTA), 4 indica (dati/keyword, SEMPRE split), 5 mento (domande, prediligi split).
- **Firma principale:** `plan_character_layout(chunks, script_text, on_attempt=None) → [{chunk_index, pose:1-5, layout:preset, layout_preset:alias, punch_in:bool, transition_in, position:legacy, transition:legacy, scale:0.65-0.90}]` lungo quanto chunks. Mai solleva per API (fallback).
- **LLM:** prompt regista con `_POSE_RULES+_LAYOUT_RULES` + regole narrative se chunk hanno ruoli (hook posa1+climax punch, corpo 1 identità per beat, CTA posa3 center no-punch) + `LAYOUT VALIDI` + snippet script 1500 char + `indice: testo` (tag `[HOOK]/[CORPO]/[CTA]` se presenti). `temperature=0.3, max_tokens=max(512,min(4096,256+n*64)), json_object`. Accetta array bare o `{layout|plan|chunks|items:[...]}` + fence; indicizza per `chunk_index` else ordine; buchi → fallback completo.
- **Normalizzazione `_normalize_entry`:** clamp posa, preset via `normalize_preset` (alias+legacy tollerati), forza split per posa 4/5 se errati, `transition_in` default `slide_up` se primo else `preset_default_transition`, scala clamp.
- **Fallback `_fallback_plan`:** primo chunk posa1 center slide_up; poi `?`→5, `!`→3+punch (mai in CTA), else ciclo `[1,2,4]` (4/5→split alternati); ogni 3° slide→fade. Rispetta `PIPELINE_FAST=1` e no-keys.
- **Finalize:** `_apply_narrative_locks` (hook primo posa1 center, climax punch; corpo lock per beat su primo; CTA lock totale posa3/2 center no-punch scala 0.75) + `_cap_punch_ins_narrative` (hook max1 ultimo, corpo max1 ultimo, CTA 0) o `_cap_punch_ins` globale max `MAX_PUNCH_INS_PER_VIDEO=2` (tiene ultimi).
- **Asset:** `_candidate_asset_paths(pose)` cerca `{n}.jpg/.jpeg/.png + maiuscole` in `CHARACTERS_DIR` + fallback legacy `Nuova cartella/characters` (cachato). `load_character_original(pose)` → RGBA pulita (`_remove_black_background`: pixel opachi `a>=250` e `RGB<15` → trasparenti, via numpy se disponibile else getdata, cachata). `load_and_process_character_image(pose,target_h)` legacy scala su altezza (cachata). `character_target_height(scale)` clamp 0.65-0.90*1920. `calculate_character_bbox(size,position)` legacy bottom/side (mantenuto per compat; col preset usare `renderer.calculate_character_transform`).
- **`resolve_chunk_layout(chunk) → None|{pose,use_preset,layout,layout_preset,punch_in,transition_in,position,transition,scale}`:** singola fonte di verità per text+character engine (niente divergenza → niente overlap sistemico). `use_preset` vero solo se layout in `VALID_LAYOUT_PRESETS` (+2 deprecati tollerati).
- **`enrich_chunks_with_characters(chunks,plan)`:** merge se lunghezze coincidono, else invariati. Mai solleva.

### 5.11 `core/layout_presets.py` — zone 1080x1920
- **4 preset:** `layout_center_standard` (125% larghezza, mezza figura basso, testo alto `90,150,990,900`), `layout_center_punch_in` (170% primo piano, testo terzo superiore `90,150,990,640` + pill), `layout_split_left` (130% sinistra overhang, testo destra `640,560,1000,940`), `layout_split_right` (speculare `80,560,420,940`). Niente figura intera: scala su larghezza, ancoraggio dal basso con headroom (500/110/250px), fondo sempre oltre canvas (piedi mai visibili).
- **Costanti:** `PRESET_WIDTH_PCT`, `PUNCH_IN_FACTOR=1.35` (su preset normali), `MAX_PUNCH_INS_PER_VIDEO=2`, `PRESET_HEADROOM_PX`, `SPLIT_OVERHANG_X=420`, `PRESET_SAFE_AREA`, `PRESET_FONT_SCALE (1.0/1.0/0.9/0.9)`, `PRESET_SIDE`, `PRESET_DEFAULT_TRANSITION_IN`, `PRESET_TEXT_BACKGROUND (solo punch_in=True)`, `TEXT_PILL_FILL=(0,0,0,170), PAD=28, RADIUS=36`.
- **Funzioni pure:** `normalize_preset` (alias deprecati `bottom_focus→standard, closeup→punch_in` + legacy `bottom_left→split_left` ecc.), `preset_width_pct (con punch)`, `preset_headroom_px/overhang_x/safe_area` (scalati su canvas diversi), `preset_font_scale/side/default_transition/needs_text_background`, `normalize_transition_in` (legacy `slide_side→left/right` per lato, `slide_from_bottom→slide_up`), `legacy_transition/position` (compat v1), `describe_preset`.

### 5.12 `core/renderer.py` — rendering statico + primitive condivise
- **Ruolo doppio:** path statico legacy + libreria layout/disegno riusata dall'animato (`compute_word_layout`, `draw_word`, `draw_text_background`, `calculate_character_transform`, `get_character_layer`).
- **Font:** `load_font(size)` (alias `_load_font`) cachato `(path,size)`: `SUBTITLE_FONT_PATH` poi fallback `DejaVu/Liberation/arialbd/Arial Bold`, else `ImageFont.load_default()`. `LINE_SPACING=12` identico statico/animato.
- **`compute_word_layout(words,font,max_width,area=None) → [{word,x,y,width,height}]`:** wrapping `_wrap_words` (textlength), centro in area (default schermo intero), clamp dentro safe area + rete anti-sconfinamento split (`x=max(ax0)`, shift se `>VIDEO_W-8`). Usa probe condivisa 64x64 da animator per velocità.
- **`draw_word(draw,word,position,font,fill,stroke,stroke_width,opacity)`:** pura, modula alpha per opacity, `stroke_width` default 0.
- **`draw_text_background(img,layout,fill/pad/radius)`:** pill dietro bbox layout espansa.
- **`calculate_character_transform(image_size,preset,is_punch_in,canvas) → (new_w,new_h,paste_x,paste_y)`:** width-based (`canvas_w*pct`), aspect preservato, x centrato o split con overhang, y=headroom ma mai sopra `canvas_h-new_h` (bordo inferiore sempre a/oltre fondo).
- **`get_character_layer(pose,preset,punch,canvas) → (img_copy,paste_x,paste_y)`:** resize LANCZOS + cache `{(pose,w,h)}`. `clear_character_layer_cache()` per test.
- **`render_subtitle_image(text,index,keyword_colors,text_color,character,safe_area,text_safe_area) → abs PNG`:** canvas RGBA trasparente 1080x1920, Z-index personaggio→pill→testo, font size `SUBTITLE_FONT_SIZE*font_scale` (da preset/guard), `max_width=VIDEO_W*0.85`, colori keyword via `normalize_word` match else base. Salva `TEMP_DIR/subtitle_{index:04d}.png`.
- **`render_all_subtitles(chunks,keyword_colors,text_color,character_plan,safe_area...) → chunks+image_path`:** se chunk già arricchiti usa metadati character, else `character_plan` parallelo se fornito.

### 5.13 `core/text_animator.py` — animazioni (cuore 2303 righe)
- **Concetto:** ogni parola entra al suo `start` (accumulo) e tutto scompare a `chunk.end`. Normali/base: solo fade `ease_out_cubic`. Keyword/impact: opacity+scala `scale_from→1.0` con `ease_out_back` (pop premium; `ease_out_bounce` disponibile ma non default). Uscita gruppo: fade `ease_in_cubic`. Layout pre-calcolato UNA volta per chunk dentro safe area (wrapping dinamico). Sfondo sempre trasparente (bg applicato da ffmpeg; param `background_color` solo per contrasto colori/compat).
- **Typography path (se chunk ha `styled_words` validi e `TYPOGRAPHY_ENGINE_ENABLED`):** 3 font per nicchia via `FontManager` (`_load_typography_fonts` con cache `_typo_font_cache`), `impact 1.3-1.5x uppercase highlight`, `accent 1.1x handwritten`, stroke sempre trasparente, ombra solo se `TYPOGRAPHY_SHADOW_ENABLED=1`. Colori `_styled_fills(preset, base_override=text_color tema, background_color, keyword_colors)`: base=tema (flip bianco/nero se basso contrasto), impact=highlight validato (fallback palette keyword→highlight_alt→bianco/nero, mai uguale a base), accent=dedicato o mix 55% impact+45% base se collassato. Layout `compute_styled_layout` (misura ogni parola col suo font, baseline comune per riga via ascent/descent `getmetrics`, niente parole flottanti).
- **Legacy path:** singolo font `load_font(SUBTITLE_FONT_SIZE*font_scale)`, `compute_word_layout`, fills keyword else base.
- **Personaggio per frame:** layer caricato UNA volta (`_load_chunk_character_layer`), Z-index sfondo<character<pill<testo. Entrata slide rapida 0.2s da fuori campo (`_character_entry_offset_opacity` full_travel se preset) o legacy 0.35s/320px; `char_entry_jump` (punch cambia o stessa identità/posa) = istantaneo; `char_entry_fade` solo prima apparizione (prev None) else slide a piena opacità (anti-glitch). Uscita via `decide_char_exit_mode(cur,nxt)`: `with_text` (fade gruppo, sparizione chiara), `hold` (stesso/posa/punch cambia/legacy → resta fino a stacco), `slide_down` (solo cambio lato split + posa diversa, a piena opacità). `decide_char_entry_jump(prev,cur)` solo su punch toggle.
- **Narrativa:** chunk portano `anim_entry_mult/anim_pop_from` (hook 0.7x/0.55) applicati a `entry_dur/scale_from`.
- **CTA card `generate_cta_card_frames(cta_chunks,states,...)`:** intera sezione come UNICA card persistente: layout/fill/font calcolati UNA volta su tutte le parole ordinate per start, reveal karaoke (future nascoste, corrente pop, passate fisse), pill badge sempre, personaggio bloccato su primo chunk, dissolvenza SOLO su ultimo chunk (`exit_dur=0` per intermedi). `card_scale=0.92`.
- **`generate_animated_chunk_frames(chunk,bg,text_color,keyword_colors,output_dir,chunk_index,fps,safe_area,char_exit_mode,...,typography_niche/preset) → [{image_path,start,end}]`:** `num_frames=ceil(duration*fps)`, `frame_step=1/fps`, pill pre-renderizzata cachata (`_get_cached_pill_overlay` max 32), cache opacity character quantizzata step 8 (`_get_char_at_opacity` max 128), resample veloce (`_fast_resample_for_scale`: BILINEAR se |scale-1|<0.12 else BICUBIC; LANCZOS solo resize una-tantum), binding locali per loop caldo, salvataggio `chunk_{idx:04d}_frame_{fi:05d}.png` con `compress_level=1` (veloce, lossless, temp più grandi ma cancellati).
- **`render_all_chunks_animated(chunks,bg,text_color,keyword_colors,output_dir,fps,on_chunk,safe_area,typography_niche/preset) → chunks+{frames,frame_paths,clip_start,clip_end}`:** calcola `states` (exit via lookahead, entry via lookbehind con `same_as_prev/same_pose` → jump, `entry_fade=prev is None`), separa run CTA consecutivi stessa `cta_section_id` (sequenziali) da normali (paralleli ThreadPool 2-4 worker se `RENDER_PARALLEL=1` e `>=3` chunk, `on_chunk` per GUI). Solleva `TextAnimationError` solo per timestamp invalidi/layout fuori sync; altri errori CTA wrappati.
- **Ottimizzazioni P0:** singleton `_shared_font_manager` (evita mkdir+scan per chunk), probe 64x64 condivisa thread-safe, pill/opacity cache, PNG fast.

### 5.14 `core/text_tagger.py` — nicchia + tagging LLM
- **A. `detect_niche(script, on_attempt, min_confidence=0.4) → niche in VALID_NICHES`:** mai solleva (fallback euristico). Se `PIPELINE_FAST` o no keys → `_heuristic_niche` (conteggio segnali IT+EN pesati, espressioni multi-parola x2, fallback `dark_motivational`). Else LLM (`temperature=0.2, max_tokens=256, json {niche,confidence,reason}` su snippet 1500 char). Se confidence<min → euristica. Parsing tollerante fence/regex, alias via `normalize_niche`.
- **B. `tag_chunk_words(chunks, on_attempt) → [{chunk_index, words:[{text,type:base|impact|accent}]}]`:** mai solleva (euristica). Prompt designer con tipologia (base standard, impact keyword/numeri/enfatiche, accent domande/citazioni) + esempio + regole narrative (hook ≥1 impact, CTA verbi → impact). `max_tokens=max(512,min(4096,256+n*64))`. Parsing accetta `chunks/tagged/items/results` o array bare, tollera alias (`keyword→impact, quote→accent`), valida n voci. Riallineamento `_align_tags_to_timed_words` (match sequenziale normalizzato con finestra 3, extra ignorati, mancanti → `_heuristic_style`: numeri→impact, maiuscolo 3+→impact, virgolettati/domande→accent, enfatiche/lunghe≥9→impact).
- **`enrich_chunks_with_typography(chunks,script,niche,on_attempt) → (niche, enriched)`:** `enriched=chunk+{typography_niche, styled_words:[{word,start,end,style,display (impact→UPPER se preset)}]}` con timing ricostruiti uniformemente se `words` mancanti + `boost_typography_styles` per hook/cta. Mai solleva per LLM.

### 5.15 `core/typography_presets.py` — 6 nicchie
- `FALLBACK_NICHE=dark_motivational`, `VALID_NICHES=[business_finance, tech_ai, fitness_sport, lifestyle_vlog, educational, dark_motivational]`.
- Ogni preset: `fonts{base:[2],impact:[2],accent:[2-3]}`, `colors{base,highlight,accent(+highlight_alt solo dark),stroke:#000000 inutilizzato}`, `sizes{base:60 (62 dark), impact_scale:1.3-1.45, accent_scale:1.1}`, `stroke_width:0, shadow off, impact_uppercase:True`.
  - business: Inter/Roboto + Anton/Impact + Playfair/Caveat, gold #FFD700/champagne #FFE8A3.
  - tech_ai: Roboto/Inter + Bebas/Orbitron + SpaceMono/Caveat, ciano #00E5FF/#B8F4FF.
  - fitness: OpenSans/Roboto + Oswald/Bebas + Marker/Kalam, rosso #FF2400/corallo #FFC4B8.
  - lifestyle: Poppins/Lato + Cinzel/Bodoni + Caveat/Pacifico, rosa #B76E79/#F3C6CE.
  - educational: Nunito/Roboto + League/Anton + Patrick/Kalam, blu #2962FF/#B3C6FF.
  - dark: Montserrat/Inter + Anton/Montserrat + Caveat/Kalam/Patrick, oro #D4AF37/#F5D67B (+alt #FF0000).
- `normalize_niche` (alias business→finance, tech→ai, gym→fitness, vlog→lifestyle, education→educational, motivation→dark), `get_preset` (copia sicura, mai crash), `list_niches_for_prompt`.

### 5.16 `core/font_manager.py` — asset font
- `FONTS_DIR=BASE_DIR/assets/fonts`, `_GITHUB_RAW_BASE/_ALT` (google/fonts main), `_FONT_FILES` mappa norm→(ofl_subdir,file) (variable `[wght]` URL-encodati `%5B/%5D`; `impact/pristina/editorsnote` → `__system__` no-download).
- `_find_local_font` (match esatto case-insensitive + prefisso, cache dir 30s), `_find_system_font(prefer)` (cerca `C:\Windows\Fonts`, DejaVu, Liberation, Supplemental, cachato), `_download_urls` (mappa + guess generici), `_download_to` (requests 15s, sanity size≥4KB + magic TTF/OTF, verifica `ImageFont.truetype(tmp,32)` prima di promuovere, atomic via `.tmp→replace`).
- `class FontManager(fonts_dir)`: `ensure_font_exists(name)→path` (locale→download→sistema per ruolo: impact→impact/arialbd, accent→times/georgia, base→arial; mai solleva, `""` se tutto fallisce), `ensure_preset_fonts(niche|preset)→{base,impact,accent}`, `load_font(name,size)` (fallback `renderer.load_font` poi `load_default`), `clear_cache`. Singleton `_default_manager` + scorciatoie `ensure_font_exists/ensure_preset_fonts`.

### 5.17 `core/layout_guard.py` — guard real-time (<5ms/chunk)
- **Garanzia:** mai eccezioni (fallback nascondi personaggio), niente LLM/I-O (solo probe/cache).
- **Misure reali codificate:** center testa y~644 → `CENTER_SAFE_Y_MAX_FIXED=620`; split 340-360px → `SPLIT_WIDEN_PX=60`; pop overshoot 10% → `POP_OVERSHOOT=1.12`; punch char 1.6875x; `SAFETY_MARGIN_PX=24`, `FONT_SHRINK_STEPS=(1.0,0.9,0.8,0.7)`, `PUNCH_TEXT_PAD=28`, `WIDE_POSES_IN_SPLIT={2}` (pose2 mai split).
- **Primitive:** `get_character_tight_original(pose)` (getbbox alpha cachata), `get_character_tight_canvas(pose,preset,punch)` (transform + tight scalata, clip canvas), `text_bbox_of_layout(layout,pad)` + `expand_bbox_for_pop`, `rects_overlap(a,b,margin)→(bool,area)` (espande con margine).
- **`plan_chunk_realtime(chunk,words,font_size,max_width,margin) → {layout,safe_area,font_scale,needs_pill,hide_character,guaranteed,overlap_px,overlap_before_px,actions}`:** regola0 pose2→center, posa4→split_right; misura iniziale (styled se tipografico else legacy); se ok → garantito; else cascata: shrink font → tighten center ymax 620+shrink0.9 → widen split+shrink0.8 → switch preset (center↔split, mai pose2 split, posa4 solo split) → punch intenzionale (pill obbligatoria, `guaranteed=False`) → hide character (sempre garantito).
- **`build_realtime_plan(chunks,...)→(plans,summary{total,guaranteed,fixed,hidden,intentional,overlaps_before})`:** coerenza beat (dentro stesso `narrative_beat` preferisce shrink a switch, tag `beat-lock`) + continuità posa (stessa immagine → riusa layout precedente, tag `pose-hold`).
- **`apply_realtime_plans(chunks,plans)→new list`:** aggiorna layout/position + `guard_safe_area/guard_font_scale/guard_pill` (letti da animator/renderer con precedenza) o `pose` rimossa + `guard_hidden` se hide. Mai solleva.

### 5.18 `core/easing.py` — curve pure (math only)
- `clamp01(t)`, `linear`, `ease_out_cubic (1-(1-t)^3)` per fade normali, `ease_in_cubic (t^3)` per uscite, `ease_out_back (c1=1.70158, overshoot ~1.1)` per pop keyword, `ease_out_bounce` variante giocosa, `ease_out_elastic` sperimentale. Tutte `t→eased`, overshoot voluto per keyword (clamp opacity a 255).

### 5.19 `core/video_builder.py` — ffmpeg
- **Statico legacy:** ogni `image_path` come `-i`, `filter_complex` catena `overlay=0:0:enable='between(t,start,end)'`.
- **Animato:** ogni chunk con `frame_paths/frames` → `build_chunk_clip(frame_paths,fps,TEMP_DIR/chunk_{idx:04d}.mov)` (codec `.mov→png` RGBA veloce default, `.webm→libvpx-vP9 yuva420p crf18`, pattern `image2 %05d` con fallback concat demuxer `file+duration`, riuso se clip più recente dei frame, check primo/ultimo+2 random, ThreadPool 2-4 worker) poi `overlay` con `setpts=PTS-STARTPTS+start/TB` (frame0=chunk.start) + `format=yuva420p` solo per webm.
- **`build_video(audio_path,chunks,output_filename,background_color)→abs in OUTPUT_DIR`:** `ffprobe -show_entries format=duration` per durata, input `color=c=0xRRGGBB:s=1080x1920:r=30:d=duration` + audio, encode `libx264 preset {FFMPEG_PRESET whitelist} crf20 pix_fmt yuv420p faststart + aac 192k shortest`, `filter_threads+threads auto`. `_ffmpeg_color` fallback `black` se hex invalido. `_check_ffmpeg` se `which` nullo. Errori `VideoBuildError` con ultimi 2000 char stderr.
- **`cleanup_temp_files()`:** walk `TEMP_DIR` rimuove file + rmdir vuote (mai solleva oltre OSError ignorato).

---

## 6. Modelli dati (contratti tra moduli — NON rompere)

### 6.1 `word: {word:str, start:float, end:float, [is_keyword:bool, style:base|impact|accent]}`
Prodotto da Whisper → riallineato (parole script) → arricchito con keyword/typography. Timestamp secondi, monotonically crescenti dopo alignment.

### 6.2 `chunk` evoluzione
1. Dopo emphasis: `{text:str, start:float (primo word.start), end:float (ultimo word.end), words:[word]}`.
2. Dopo narrativa: `+{narrative_role, narrative_beat:int, beat_tone, anim_entry_mult, anim_pop_from, cta_card:bool, cta_section_id, cta_strength}`.
3. Dopo tipografia: `+{typography_niche:str, styled_words:[{word,start,end,style,display}]}` (display=UPPER per impact se preset).
4. Dopo character: `+{chunk_index, pose:int, layout:preset, layout_preset:alias, punch_in:bool, transition_in, position:legacy, transition:legacy, scale:float}`.
5. Dopo guard: `+{guard_safe_area:(x0,y0,x1,y1), guard_font_scale:float, guard_pill:bool, [guard_hidden]}` + possibile `layout` switchato / `pose` rimossa.
6. Dopo render animato: `+{frames:[{image_path,start,end}], frame_paths:[str], clip_start, clip_end}`. Dopo statico: `+{image_path:str}`.

### 6.3 Altri contratti
- `theme: {background_color:#RRGGBB, text_color:#RRGGBB, keyword_colors:[#RRGGBB x2-4]}`.
- `keyword_colors_map: {norm_word: (R,G,B,A)}` — chiavi normalizzate `lower+strip punct`.
- `character_plan[i] ↔ chunks[i]` 1:1 per indice; se lunghezze diverse → nessun arricchimento.
- `sections: {hook:[idx], body:[idx], body_beats:[[idx]], beat_tones:[...], cta:[idx], cta_strength, cta_mode}`.
- Frame PNG: `chunk_{idx:04d}_frame_{fi:05d}.png`, finestra `[t, t+1/fps)`. Micro-clip: `chunk_{idx:04d}.mov`. Audio bulk: `narration_{idx:03d}.mp3`.

---

## 7. Concorrenza, cache e performance

- **GUI:** 1 thread main Tk + 1 worker daemon per batch (mai blocca UI; log via `after`).
- **Pipeline:** ThreadPool x2 (tema+audio) e x3 (character+keyword+typo) in `main.py`; ThreadPool render chunk (2-4 worker) + micro-video ffmpeg (2-4) se `RENDER_PARALLEL=1` e `>=3` chunk; CTA card sempre sequenziale (layout condiviso).
- **Cache:** Groq client per chiave (max16) in ogni modulo; `_font_cache` renderer (16), `_typo_font_cache` illimitata ma chiavi `(path,size)`, `_character_layer_cache`, `_image_cache+_original_cache`, `_resolved_path_cache`, `_tight_cache` guard, `_pill_cache` (32), `_char_opacity_cache` (128 con clear a 120), `_local_dir_cache` 30s, `_system_font_cache` (32), singleton `FontManager`.
- **Fast path:** `PIPELINE_FAST=1` (euristiche), `compress_level=1` PNG, BILINEAR/BICUBIC per scale animate, probe 64px, pattern image2 senza stat N, `FFMPEG_PRESET=ultrafast` per bozze.
- **Thread-safety:** lock per singleton/probe/pill/opacity; Pillow `Image` non condivise tra thread (copie per layer).

---

## 8. Error handling e logging

- **Fatali per singolo video (non bloccano bulk):** `TTSError` (audio), `TranscriptionError` (STT), `VideoBuildError` (ffmpeg). Altri `Exception` catturati con traceback.
- **Non-bloccanti (fallback + proseguono):** theme→default, emphasis/character/tagging/nicchia→deterministico, alignment→raw, keyword→nessuna evidenziazione, animazione→statico, guard→hide, asset mancante→no character, font→sistema.
- **Logging:** `on_attempt(index,total,ok,detail)` propagata ovunque per ciclo chiavi; `_log` GUI thread-safe; riepilogo bulk con conteggi + dialog.
- **Validazioni input:** script vuoto, audio mancante, timestamp degeneri (`end<=start` → +0.1), layout/words fuori sync → `TextAnimationError`.

---

## 9. Asset, output, env file

- **Characters:** 5 PNG (768x1376 figura intera con sfondo nero da pulire). Pose 1-5 come §5.10. Aggiungere posa 6 → aggiornare `CHARACTER_POSE_COUNT`, `_POSE_RULES`, `_preset_for_pose`, asset file.
- **Fonts:** 15 TTF committati coprono quasi tutti i preset (mancano es. Impact di sistema, Orbitron/Bodoni variabili scaricati on-demand). Non cancellare senza test offline.
- **Outputs:** naming bulk `video_{i:0{width}d}_{slug}[_k].mp4` (width da totale, slug 5 parole/32 char). Legacy singolo `output_video.mp4` ancora citato in `build_video` default ma `main.py` usa sempre suggest.
- **Temp:** mai committare (gitignore copre solo `.env/__pycache__`, ma temp/output sono runtime; outputs contiene esempi committati — valutare gitignore futuro).
- **`.env`:** mai committare; `.env.example` è la spec. `config.py --check-keys` per verifica senza crediti.

---

## 10. Invarianti critici per futuri LLM (leggere prima di modificare)

1. **Timestamp immutabili dopo alignment:** LLM (emphasis/character/tagging/keyword/theme) non devono mai alterare `start/end`; solo indici/tag/colori/layout. `text_animator` assume `layout==words` per conteggio.
2. **Single source layout:** testo e personaggio risolvono entrambi da `resolve_chunk_layout` + `layout_presets` + `layout_guard`. Non duplicare geometria.
3. **Z-index:** ffmpeg bg < personaggio < pill < testo. Non invertire.
4. **Punch-in raro:** max 2/video (o hook1+corpo1, CTA 0). Non aumentare senza aggiornare cap + guard.
5. **Contrasto:** ogni colore testo/keyword deve superare `THEME_MIN_LUMINANCE_DIFF` sullo sfondo. Validare come `theme.py`/`_styled_fills`.
6. **Keyword verbatim:** devono esistere `normalize_word` nello script, altrimenti scartate. Non fare fuzzy senza aggiornare renderer match.
7. **Bulk isolamento:** nomi audio/clip/frame per indice; `cleanup_temp_files` dopo ogni video. Non usare nomi fissi condivisi.
8. **Fallback mai crash:** ogni nuovo LLM deve avere fallback deterministico + `try/except` nel chiamante `main.py`.
9. **1080x1920 assumption:** safe area/headroom/overhang scalano, ma testare canvas diversi esplicitamente.
10. **FFMPEG sync:** `fps` clip == `VIDEO_FPS`, `setpts` obbligatorio, `format=yuva420p` solo webm. Non cambiare codec senza test alpha.

---

## 11. Come modificare in sicurezza (ricette)

- **Nuova nicchia:** aggiungi in `VALID_NICHES+NICHE_DESCRIPTIONS+TYPOGRAPHY_PRESETS+_NICHE_KEYWORDS (tagger)`, mappa in `_FONT_FILES` + committa o testa download, verifica `_styled_fills` contrasto.
- **Nuovo preset layout:** aggiungi in `VALID_LAYOUT_PRESETS+PRESET_*` (width/headroom/safe/font/side/transition/pill), aggiorna `_preset_for_pose`, `normalize_preset`, `layout_guard` regole (wide pose, tighten/widen), prompt `_LAYOUT_RULES`.
- **Nuova easing:** aggiungi pura in `easing.py` (`t→float`, usa `clamp01`), referenzia in animator con flag config (non cambiare default pop senza A/B visivo).
- **Nuovo segnale CTA:** aggiungi lower in `_CTA_CUES` (sottostringa) o `_CTA_ACTION_VERBS` (parola intera) + test `_detect_cta` con `CTA_MAX=4`.
- **Nuova voce TTS:** usa `ELEVENLABS_VOICE_IDS` 1:1, non hardcodare ID in `tts.py`.
- **Debug tipico:** `TEXT_ANIMATION_ENABLED=0` per isolare ffmpeg; `CHARACTER_ENABLED=0` per isolare overlap; `NARRATIVE_ENABLED=0` per isolare lock; `PIPELINE_FAST=1` per bulk veloci; `RENDER_PARALLEL=0` per stacktrace ordinati.

---

## 12. Limiti noti e debito tecnico

- Nessun background video/grafico (solo tinta unita tema) — da README.
- Script lunghi (centinaia chunk) → comando ffmpeg lungo (1 overlay/chunk) + encode clip N — ottimizzabile con timeline unica (da README).
- Keyword solo verbatim (no stemming/embedding).
- Outputs committati (11 mp4) appesantiscono repo; temp pulita ma output no.
- `subtitle_grouping.py` legacy non usato direttamente (ma costanti condivise) — non rimuovere senza refactor.
- `EmphasisGroupingError` definita mai sollevata (fallback silenzioso) — ok ma documentato.
- Font `Pristina/Editors Note` mappati a `__system__/__missing__` (non open-source) — restano fallback sistema.
- README pipeline 10 step non aggiornato a narrativa/tipografia/guard/CTA card.

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
```

---

## 14. Glossario rapido

- **Chunk:** 2-3 parole con timing, unità sottotitolo/animazione.
- **Beat:** frase/pensiero nel corpo (1+ chunk), unità stabilità personaggio.
- **Punch-in:** jump-cut ingrandimento per enfasi (stacco camera, no transizione morbida).
- **Safe area:** box testo garantito senza overlap personaggio.
- **Pill:** rettangolo arrotondato semi-trasparente dietro testo (contrasto punch-in/CTA).
- **Card CTA:** messaggio finale persistente con reveal karaoke.
- **Impact/accent/base:** livelli tipografici (urlato/handwritten/normale).
- **Tight bbox:** box alpha reale personaggio (non full asset).

---

*Fine report — generato da analisi esaustiva di tutti i 21 file .py + asset + config. Per dubbi, rileggere §10 prima di ogni modifica.*
