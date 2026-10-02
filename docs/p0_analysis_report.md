# P0 — Report di analisi (Fase 1)

Data: 2026-10-02 · CGS, Windows, Python 3.11.9, ffmpeg full build 2024-12-26 (libx264, loudnorm, noise, zoompan disponibili), Pillow 12.3.0.

## 1. Catena audio attuale

```
ElevenLabs (mp3_44100_128, via output_format) → TEMP_DIR/narration[_NNN].mp3
  → Whisper (legge mp3 originale — bene)
  → core/audio_mixer.mix_sfx(): voce mp3 + SFX lavfi → narration_sfx.wav (pcm_s16le 44.1k stereo, SOLO se SFX presenti, altrimenti resta mp3)
  → core/audio_mixer.mix_audio_with_music(): se musica → narration_mix.wav con alimiter + loudnorm 2-pass verso -14 LUFS/TP -1.5 (già esiste! ma SOLO nel ramo musica)
  → builder/composer: -c:a aac -b:a 192k (secondo encode lossy)
```

Generazioni lossy: **2** nel path default con SFX/musica (mp3 TTS → AAC finale; i WAV intermedi sono lossless quindi ok), **2** anche senza SFX (mp3 → AAC). Il WAV intermedio esiste già ma solo in alcuni rami.
Punti che assumono `.mp3`: `main.py:383` (`narration_{index:03d}.mp3`), `core/tts.py:52` default `narration.mp3`, `core/transcription.py:111` docstring, `core/audio_mixer.py:749` (converte output `.mp3`→`.wav`), `cgs-report-completo.md`, docs LLM, `fetch_music.py` (libreria musica, irrilevante).

Misura reale su `video_06_...mp4` (con musica? verosimilmente mix esistente): **input_i −23.69 LUFS** — il file finale NON è a −14: il ramo senza musica non fa loudnorm. Conferma il problema WS-A. True peak −6.17, LRA 1.3 (parlato, ok).

## 2. Catena video attuale

Comandi duplicati quasi identici in `video_builder.py:424-441` e `video_composer.py:251-268`:
`-c:v libx264 -preset <FFMPEG_PRESET=veryfast> -crf 20 -g 60 -keyint_min 30 -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 192k -shortest`.
Whitelist preset limitata a `ultrafast…medium` (manca slow/slower).

Micro-video per chunk: `build_chunk_clip` → `chunk_NNNN.mov` con **codec PNG lossless RGBA** (default pipeline, veloce) oppure `.webm` VP9 crf 18 (solo se estensione .webm richiesta — oggi mai usata di default). Quindi **nel path default: 0 generazioni lossy intermedie** (PNG lossless → x264 finale = 1 solo encode lossy). Nessuna azione di riduzione necessaria oltre al refactor E1; documentato come "nessuna azione" salvo il caso .webm legacy.

Path default reale: `main.py:667` prova `video_composer.build_composed_video` (con Ken Burns + dimmer, `ENABLE_DYNAMIC_BACKGROUNDS=1` default) e solo su eccezione ricade su `build_video` legacy. Quindi il composer è il path default.

## 3. Colore

Nessuna conversione esplicita: sorgenti RGB (`lavfi color=`, PNG overlay RGBA) convertite in YUV con matrice **implicita** di libx264/auto (BT.601 per SD / BT.709 per HD a discrezione del filtro `format`), nessun tag scritto.
Misura ffprobe su 2 video reali: `color_range=unknown, color_space=unknown, color_transfer=unknown, color_primaries=unknown`, `profile=High, level=40, pix_fmt=yuv420p`. Conferma: serve WS-E2 (conversione esplicita + tag).

## 4. Safe zone

Valori reali oggi: `UI_TOP_RESERVED_PX=150`, `UI_BOTTOM_RESERVED_PX=320`, `UI_SIDE_RESERVED_PX=80` (layout_guard.py:286-288). `PRESET_SAFE_AREA` per layout (presets: center `(90,150,990,900)`, punch-in `(90,150,990,640)`, split_left `(640,560,1000,940)` larghezza utile **360 px**, split_right `(80,560,420,940)` larghezza **340 px`). `CENTER_SAFE_Y_MAX_FIXED=620`. `MAX_TEXT_WIDTH_RATIO=0.85` (guard) + `LAYOUT_MAX_WIDTH_RATIO=0.80` + `dynamic_max_text_width()` 80% reale. `MARGIN`/`SAFETY_MARGIN_PX=24`, `PADDING` pill 28.
CTA card: `generate_cta_card_frames` in text_animator.py:2721, layout centrato su tutte le parole CTA, `card_scale=0.92`, personaggio bloccato — posizionata al centro area, NON esplicitamente sopra il bottom 420 (rischio con universal). Da vincolare in WS-C.
Uso: guard (`verify_z_order`, `debug_safezone_boxes`, `plan_chunk_realtime`), presets (`preset_safe_area`), renderer (`_resolve_safe_area`), animator (safe area per chunk), invariant_checks (`check_z_order_safe` → solo fuori-canvas = fail, resto ignorato). `debug_safezones` disegna 4 box (top/bottom/left/right) senza rail né cover-safe.

Gap WS-C: bottom 320 < 420 richiesti; laterali 80 < 120; nessuna rail destra; nessuno split con larghezza ≥520 px (360/340 attuali → da allargare o documentare deroga con font ridotto).

## 5. Tipografia

`TYPOGRAPHY_BASE_FONT_SIZE=60` (config), `SUBTITLE_FONT_SIZE=64` (renderer statico — disallineati di 4px). Preset nicchia: `sizes.base` 60 (62 dark_motivational), impact_scale 1.3–1.45, accent_scale 1.1. `TYPOGRAPHY_IMPACT_SCALE=1.4`, `ACCENT=1.1` (fallback). `LAYOUT_MIN_FONT_PX=40`. `max width` = `VIDEO_W*0.85` poi min con safe-area (renderer + animator coerenti).
Stroke/ombra effettivi: **CONTRADDIZIONE trovata**. Documentato "stroke=0, no ombra" (config TYPOGRAPHY_STROKE_WIDTH=0, SHADOW_ENABLED=0, SUBTITLE_STROKE_WIDTH=0). MA con `ENABLE_ADVANCED_KINETICS=1` (default), `advanced_stroke_for()` forza **stroke 3px** (`KINETIC_T0_STROKE_PX=3`) su T0/T1 base+accent (text_animator usa `_adv_stroke_for` — da verificare nel codice di chiamata, ma la funzione esiste ed è importata). Quindi oggi: base/accent hanno bordo 3px in modalità avanzata, impact/hero no (o badge). Verità: look NON uniformemente pulito. WS-D deve riconciliare: livello 0 = nessun effetto (spegne anche il bordo avanzato su sfondo piatto), livelli 1-3 = effetti adattivi.

## 6. Scaling testo nel pop (T2/T3)

**Bitmap resize confermato**: `_render_scaled_word` e `_render_styled_scaled_word` disegnano la parola a dimensione base su tile e fanno `tile.resize(scale)` con BILINEAR/BICUBIC (`_fast_resample_for_scale`). Il glifo NON è ridisegnato alla dimensione finale → leggera sfocatura durante il pop (pochi frame, ma stroke/ombra ne risentono). Fix WS-D: render a scala quantizzata (step 2%, cache) — da implementare come `render_word_at_scale()` con cache font per dimensione.

## 7. TTS

Payload attuale: `{text, model_id, voice_settings:{stability 0.5, similarity_boost 0.75}}` — mancano style/speed/speaker_boost. Gestione errori: failover chiavi su status retryable {401,402,403,429,5xx} (+404 solo voci per-chiave); 400/422 = TTSError immediato (corretto, ma va esteso il downgrade voice_settings prima di fallire).
Scelta nicchia: `detect_niche` (LLM + fallback euristico `_heuristic_niche` su keyword, istantaneo con PIPELINE_FAST) esiste in `text_tagger.py` ed è **chiamabile prima del TTS** (pura sul testo, nessuna dipendenza da audio). Oggi però la pipeline chiama tema+audio in parallelo (step 1-2) e la nicchia solo dopo (step 5.5-6.5) → WS-B deve anticipare `detect_niche(script)` prima di `generate_audio` e passare i profili. Nessuna chiamata LLM aggiuntiva se si riusa `_heuristic_niche` o il risultato LLM poi riusato a valle.

## 8. Baseline misurata (2 video reali)

| Video | LUFS int. | True peak | LRA | v-bitrate | profilo/level/pix_fmt | colore |
|---|---|---|---|---|---|---|
| video_06_nessuno… (15.1s) | −23.69 | −6.17 | 1.30 | 524 kbps | High/4.0/yuv420p | nessun tag |
| video_01_ciao (1.25s) | n.d. (breve) | n.d. | n.d. | 732 kbps | High/yuv420p | nessun tag |
| audio AAC finale | — | — | — | 169 kbps | AAC LC 44.1k | — |

Pause/gap da timestamp: non misurabili senza trascrizione salvata; il Pause Engine loggherà le statistiche dai prossimi run. Silenzi head/tail voce: da misurare con `silencedetect` sui prossimi WAV (tipico ElevenLabs: head ~0.1-0.3s, tail ~0.3-0.8s).

## Decisioni conseguenti

- E1: unico modulo export, preset final slow/crf17; intermedi già lossless → nessuna azione oltre refactor.
- A: `audio_master.py` come stadio finale condiviso; `audio_mixer.py` esiste già con loudnorm solo nel ramo musica → il mixer chiamerà `master_audio()`, riusando `FINAL_LOUDNESS_LUFS/FINAL_TRUE_PEAK_DB`.
- B: nicchia via `_heuristic_niche`/detect prima del TTS; voice_settings con capability-map + downgrade.
- C: `safe_zones.py` con 4 profili; guard/presets/renderer/animator derivano da lì; split 360px < 520 → deroga documentata (font 0.9 + guard) senza cambiare geometria personaggi.
- D: base 60→84, minimo 40→56; legibility.py + probe; fix resize→redraw quantizzato.
- E2: `scale=...out_color_matrix=bt709...` + tag; grain `noise=alls=5` solo bg.
- F: `tools/export_report.py` + unittest + invariant non fatali.
