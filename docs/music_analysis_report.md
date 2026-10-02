# Report analisi — Background Music (Fase 1)

Data: 2026-10-02 · ffmpeg `2024-12-26-git-fe04b93afa` (gyan.dev full build) · `ffprobe` OK in PATH.

## 1. Pipeline audio attuale (codice reale letto)

- `main.py::_process_one_script`, step 8/8 (righe ~654-663): `_mix_audio = _mix_sfx(audio_path,
  enriched_chunks) or audio_path`, poi `build_composed_video(_mix_audio, ...)` con fallback a
  `build_video`. La musica non è mai passata: `bg_music_path` resta sempre `None`.
- `core/audio_mixer.py::mix_sfx(voce, chunks, sfx_volume_db=None, bg_music_path=None, ...)`:
  SFX sintetici via input lavfi (`sine`/`anoisesrc`) + `adelay` + `amix(normalize=0)`, cap 24 eventi,
  dedup < 80 ms. Output `libmp3lame 192k` in `TEMP_DIR/narration_sfx.mp3`.
- `config.py`: `ENABLE_AUTO_SFX=1`, `SFX_VOLUME_DB=-15.0`, `BG_MUSIC_DUCKING_DB=-12.0`.
  La semantica di `BG_MUSIC_DUCKING_DB` è ambigua: è il **gain statico applicato alla musica**,
  non la profondità di ducking (verrà tenuta come alias deprecato).
- Video builder/composer (`core/video_builder.py`, `core/video_composer.py`): mux `-map 1:a -c:a aac
  -b:a 192k -shortest`, durata video = durata audio, GOP 60, yuv420p, faststart.
- La trascrizione Whisper usa sempre la voce originale (`narration_NNN.mp3`): invariante da preservare.
- `fetch_music.py` (root, non `tools/`): provider freesound/openverse/eleven, manifest
  `assets/audio_licenses.json` (oggi **assente**: gli mp3 esistono ma senza attribuzione).
  `pick_music(niche, seed)` esiste ma non è mai chiamata. Nicchie preset: `business_finance`,
  `tech_ai`, `fitness_sport`, `lifestyle_vlog`, `educational`, `dark_motivational`.

## 2. Inventario `assets/music/` + misure `ffprobe` / `loudnorm` / `silencedetect` / `volumedetect`

Tutte le tracce: `mp3 stereo 44.1 kHz` (+ cover `mjpeg` embedded tranne `lucky_acoustic`).
Misure loudness con `loudnorm=I=-24:TP=-2:LRA=11:print_format=json`; silenzi con
`silencedetect=noise=-45dB:d=0.3`.

| Cartella | File | Durata | LUFS int. | True peak | LRA | mean/max vol | Silenzio testa/coda |
|---|---|---|---|---|---|---|---|
| business_finance | corporate_succes_ov8c29117a-65e.mp3 | 82.5 s | **−6.2** | **+0.99** | 0.6 | −9.1 / **0.0 dB** | nessuno ≥ 0.3 s |
| business_finance | uplifting_corporate_ov784e04b6-c23.mp3 | 82.5 s | −9.1 | −1.40 | 2.9 | −11.7 / −1.4 dB | coda 1.08 s (da 81.4 s) |
| dark_motivational | blissfully_trapped_in_solitude_ov91648711-fcf.mp3 | 205.1 s | −11.8 | −0.22 | 5.5 | −14.9 / −0.2 dB | **testa 6.32 s**, coda ~5.0 s |
| dark_motivational | dawning_of_darkness_ovc37c19bc-ebb.mp3 | 183.1 s | −14.7 | −1.09 | 11.0 | −17.5 / −1.1 dB | coda ~4.3 s (da 178.7 s) |
| dark_motivational | status_quo_ov1691990d-7e3.mp3 | 164.7 s | −15.1 | −0.10 | 11.2 | −16.3 / −0.1 dB | interno 0.69 s (164 s) |
| dark_motivational | the_mind_trap_part_1_ovaffd77a6-fdf.mp3 | 190.4 s | −9.7 | **+1.79** | 7.2 | −12.1 / **0.0 dB** | coda 2.8 s (da 187.6 s) |
| educational | at_last_calm_oved8f3329-f2d.mp3 | 177.2 s | −16.2 | −0.75 | 11.1 | −19.0 / −0.8 dB | coda ~2.5 s (da 174.6 s) |
| educational | corvois_calm_ov98f2e262-8fa.mp3 | 108.4 s | −14.6 | −0.96 | 3.6 | −16.9 / −1.0 dB | interno 0.70 s (107.7 s) |
| educational | vittoro_ov46610435-272.mp3 | 216.9 s | −14.2 | **+0.30** | 8.7 | −16.0 / **0.0 dB** | coda 2.27 s (da 214.6 s) |
| educational | wingspan_ov87e75668-f50.mp3 | 203.8 s | −12.7 | **+0.28** | 4.1 | −14.7 / **0.0 dB** | coda 2.65 s (da 201.1 s) |
| lifestyle_vlog | key_kida…_ov6fecbcdc-efe.mp3 | 214.2 s | −9.8 | **+1.10** | 10.4 | −12.6 / **0.0 dB** | pausa interna 0.46 s (26 s), coda 1.5 s |
| lifestyle_vlog | lucky_acoustic_ovea4ef155-35a.mp3 | 202.0 s | −17.6 | −0.14 | 4.1 | −19.9 / −0.1 dB | **testa 1.38 s**, coda 2.43 s |

## 3. Anomalie rilevate

1. **Cartelle vuote**: `tech_ai/` e `fitness_sport/` non esistono → fallback obbligatorio
   (default `dark_motivational`). Nessuna cartella sotto i 30 s: durate 82–217 s, tutte ≥ 30 s OK.
2. **Livelli molto diversi**: LUFS integrati da −6.2 a −17.6 (Δ ≈ 11 LU) → normalizzazione
   per-traccia indispensabile (gain relativo alla voce, come da spec §4.2).
3. **True peak > −1 dBTP** su 5 tracce (fino a +1.79) e `max_volume 0.0 dB` (clip digitale) su 5 tracce:
   confermano `alimiter` + `loudnorm` finale, mai gain fisso cieco.
4. **Silenzi di testa**: `blissfully…` 6.32 s (!), `lucky_acoustic` 1.38 s → vanno saltati con
   `areset`-style trim (`-ss`/`adelay`-free: si usa `atrim=start=lead`) o almeno compensati, altrimenti
   l'hook parte senza musica. Code con fade-out naturale 1–5 s: l'`afade` di 2 s va applicata
   sulla durata video, non sulla coda naturale.
5. **Nomi file**: uno supera ~60 caratteri (`key_kida_amp_eddie_feat_icd_dugang_kadasig_acoustic_…`,
   74 char) — OK su Windows/NTFS, ma da quotare sempre come argomento lista (mai shell).
   Nessun carattere problematico (solo `[a-z0-9_.]`), estensioni tutte `.mp3`.
6. **Cover embedded mjpeg** in 11/12 file: innocua (stream `mjpeg` ignorato con `-map 0:a`), ma
   `ffprobe format=duration` resta affidabile; le misure usano sempre `0:a`.
7. **`assets/audio_licenses.json` assente** → sidecar con `author/license = "sconosciuto"` finché
   `fetch_music.py` non rigenera il manifest; il selettore deve tollerarlo.
8. **Tipi mancanti**: nessuna `.wav/.ogg/.m4a/.flac` oggi, ma il selettore le accetterà comunque.

## 4. Bug/rischi confermati nel mixer attuale (`core/audio_mixer.py`)

1. **Doppio consumo di etichetta** (`[mus]`/`voice_label` riusate in `sidechaincompress` + `amix`,
   righe ~208-213 e ~256-261): in ffmpeg un'etichetta di output non può essere consumata due volte —
   il ramo musica **fallirebbe sempre** se mai chiamato (oggi mai chiamato → bug latente).
   Correzione: `asplit` sulla voce (`[v_main]`/`[v_key]`), come da blueprint §4.4.
2. **Indice input musica errato**: `f"[{len(inputs) // 2}:a]"` con `inputs = ["-i", voce, "-i",
   musica]` → `len//2 = 2` → `[2:a]` inesistente (corretto: `[1:a]`). Il secondo blocco di codice
   morto (righe 231+) usa `[1:a]` giusto ma duplica tutta la costruzione: rimuovere il primo ramo morto.
3. **Musica mai ripetuta/tagliata**: nessun `atrim`/`-t`/`aloop` → con `-shortest` assente nel mixer
   (c'è solo nei builder) l'output avrebbe durata imprevedibile. Correzione: `atrim=0:{dur}` +
   loop con `acrossfade` 2 s quando la traccia è più corta.
4. **Catena lossy tripla** voce(mp3) → mix(mp3) → AAC: intermedi in `pcm_s16le WAV 44.1 kHz stereo`.
5. **Nessuna uniformazione**: voce mono/44.1k vs musica stereo/44.1k vs SFX lavfi → prefisso
   `aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo` su ogni ingresso.
6. **Sidechain troppo aggressiva** (`threshold=0.02:ratio=8`): pompa udibile. Nuovo default
   `threshold=0.04:ratio=2.5:attack=15:release=450` come ducking residuo fine sopra l'inviluppo
   deterministico.
7. `BG_MUSIC_DUCKING_DB` resta come **alias deprecato**: se impostato e `MUSIC_*_OFFSET` no,
   il suo valore sposta tutti gli offset di sezione.

## 5. Decisioni implementative (default spec confermati, con 2 aggiustamenti)

- Offset sezioni invariati: hook −17 / body −20 / CTA −18 LU; pause +4 dB (≥ 0.35 s);
  hero dip −4 dB/0.35 s; fade-in 0.8 s / fade-out 2.0 s `qsin`; video < 8 s → fade 0.4/1.0 s, no hero dip.
- **Aggiustamento A** — `lead_silence` misurato: la musica viene trimmata dal silenzio iniziale
  (`atrim=start=lead_silence`) prima del loop/fade, così l'hook ha subito energia. Soglia: solo se
  `lead_silence ≥ 0.4 s` (evita micro-tagli su attacchi morbidi voluti).
- **Aggiustamento B** — preferenza tracce: a parità di condizioni si preferisce la traccia con
  `|track_lufs − voice_lufs| minore` dopo il filtro durata, così il `track_gain_db` resta piccolo
  (±6 dB tipici) e si evita di amplificare rumore di fondo su tracce quiete come `lucky_acoustic`.
- Cache analisi in `assets/music/_analysis.json` (chiave `relpath + size + mtime`); il selettore
  ignora file/cartelle che iniziano con `_` (quindi la cache stessa) e non-audio.
- Sidechain solo residua (2–4 dB); loudnorm finale a due passaggi verso **−14 LUFS / TP −1.5** con
  fallback a un passaggio; validazione durata ±0.05 s con fallback a voce+SFX.
