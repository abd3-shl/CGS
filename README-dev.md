# Report verifica posizionamento personaggi (FASE 0)

Data: 2026-09-20. Oggetto: personaggio a braccio teso renderizzato con l'asse
verticale sul bordo destro (~120% della larghezza frame, ~1290 px su 1080) e a
contatto col bordo inferiore. Verifica fatta sui file indicati, con misura
empirica sugli asset reali (`assets/characters/`: 5 PNG RGBA 768x1376).

## Risposte (con evidenza file:riga)

a) **Come viene calcolata la scala?** IPOTESI PARZIALMENTE FALSA.
   - Path legacy v1: solo su altezza (`core/character_selector.py:176-183`
     `character_target_height`: `canvas_h * scale` con scale in
     `[CHARACTER_SCALE_MIN, CHARACTER_SCALE_MAX]` = 0.65-0.90 di 1920;
     `core/character_selector.py:309-317` scala su `th/h`, la larghezza segue
     l'aspect). La larghezza non e' mai considerata qui.
   - Path preset (quello usato dal render): su LARGHEZZA
     (`core/renderer.py:713` `new_w = cw * preset_width_pct(...)` con
     `core/layout_presets.py:95-100` split 130%, center 125%, punch 170%, piu'
     `PUNCH_IN_FACTOR` 1.15x in `core/layout_presets.py:890-891`). Esiste un
     emergency autoscale solo per gli split (`core/renderer.py:716-728`,
     `core/layout_presets.py:636-691`, soglia 690 px), ma NESSUN tetto globale
     di larghezza: center 125% = 1350 px e punch fino a ~1614 px sono voluti
     ("presenza piena"). Misura empirica: posa 2 center punch = soggetto
     1366 px = 126% di W, `subj_x1=1223` (143 px oltre il margine) -> IPOTESI
     CONFERMATA nella sostanza (scala e ancoraggio ignorano la larghezza reale
     del soggetto nei center/punch).

b) **BBox immagine intera o contenuto visibile? Rimozione sfondo?**
   - Sfondo: `core/character_selector.py:188-231` `_remove_black_background`
     (pixel opachi con RGB < 15 -> trasparenti, numpy o fallback Pillow),
     applicata in `load_character_original` (`:277`). Maschera = canale alpha
     risultante. IPOTESI `.jpg` SENZA ALFA FALSA: gli asset sono `.png` con
     alpha reale (14-15k px neri opachi comunque rimossi per asset).
   - Legacy (`calculate_character_bbox`, `:134-173`): usa `image_size` intera.
   - Preset: ancoraggio sulla bbox VISIBILE ma da tabella hardcoded
     (`core/layout_presets.py:1099-1105` `POSE_VISIBLE_BBOX`,
     `:1124-1132`, `:492-522` + clamp `:525-569`), non misurata live.
     Il trim del layer e' stato rimosso di proposito (`core/renderer.py:786-790
     ` get_character_layer docstring: disallineava il paste di +368 px).

c) **bottom_*/side_*:** definiti SOLO nel legacy
   (`core/character_selector.py:154-168`: bottom_left `(40, H-h)`,
   bottom_right `(W-w-40, H-h)`, side_left `(-0.2*w, H-h-100)`,
   side_right `(W-0.8*w, H-h)`, bottom_center centrato; `x` negativo ammesso
   per scelta stilistica `:148-149`; `y<0 -> 0` se `h<=H` `:171-172`). Nel
   sistema a zone sono alias ai 4 preset
   (`core/layout_presets.py:81-87`, `:1003-1011`).

d) **Posa/layout indipendenti o accoppiati?** ACCOPPIATI (ipotesi indipendenza
   FALSA): prompt LLM con regole (`:1149-1169`), normalizzazione
   (`:938-1006`: posa 4/5 -> split, posa 2 -> center, densi -> split),
   lock narrativi, e garanzia finale `enforce_pose_layout_coherence`
   (`:867-917`). Se incompatibili, correzione SILENZIOSA (nessun log "layout
   corretto" prima di questa modifica).

e) **Punch-in prima o dopo? Clamp?** PRIMA: moltiplica `width_pct`
   (`layout_presets.py:890-891`) e la posizione deriva dal `new_w` punchato
   (`renderer.py:687-713`). Clamp X del visibile solo sugli split
   (`clamp_paste_visible_inside`); Y da headroom fisso + fallback bottom-anchor
   (`renderer.py:716-727`). `validate_character_bounds` (`renderer.py:68-127`)
   clampa solo Y (0-800) e dimensioni, MAI X. La faccia e' garantita solo da
   warning log (`verify_perfect_crop` / `verify_face_visible`), non da clamp.

f) **Transizioni clampate? Coordinate oltre W in ffmpeg?** Stato finale = stato
   stabile (offset 0 a progress 1 in
   `core/text_animator.py:1272-1323` e `:1326-1349`; full-travel parte da
   `-img_w`/`VIDEO_WIDTH` quindi il fuori-campo a meta' slide e' voluto).
   ffmpeg non vede mai coordinate negative (sempre `overlay=0:0` in
   `core/video_builder.py:558,670-674` su PNG full-canvas; il clipping avviene
   in Pillow con fallback crop in `renderer.py:611-632` e
   `text_animator.py:1436-1475`).

g) **Il layer conosce la zona sottotitoli?** SI, strutturalmente ma senza
   riposizionamento attivo: entrambi risolvono da `resolve_chunk_layout`
   (`character_selector.py:1347-1402`), safe area dinamiche a 40 px dal bbox
   reale (`renderer.py:910-956`, `text_animator.py:1207-1232`,
   `layout_presets.py:761-806`), invariante `verify_zero_overlap` controllata
   in `renderer.py:1097-1106` e `video_builder.py:63-134` (solo warning). Su
   overlap resta solo l'auto-fit del font, il personaggio non si sposta/riduce.

## Adattamenti al piano (ipotesi false)

1. Scala height-only falsa sul path preset -> il vincolo `CHARACTER_MAX_WIDTH_RATIO`
   e' applicato come TETTO sopra la scala preset (non al posto di essa).
2. Asset `.jpg` senza alfa falsi (sono `.png` con alpha) -> la misura usa
   l'alpha esistente + chiusura morfologica 3x3; niente soglia colore.
3. "Piedi al bordo" + "soggetto intero con margine" confliggono col look
   "presenza piena" (gambe fuori di 700-1300 px): il fondo puo' toccare H
   (voluto), testa/lati/faccia restano a margine 40 px.
4. Punch preset close-up incompatibile con soggetto-intero: resta il piu'
   grande ma cappato come gli altri (fattore effettivo loggato).
5. Transizioni full-travel e micro-idle (±5/±3 px) invariati: margine residuo
   minimo ~35 px durante l'idle, mai a riposo.

## Prova del bug (prima/dopo)

- `temp/debug_char/before_pose2_layout_center_standard_punch1.png`: posa 2,
  `px=-236, 1552x2781`, soggetto fino a x=1223 (fuori di 143 px).
- Dopo: `temp/debug_char/after_*.png` + `chunk_*.png` (CHARACTER_DEBUG=1):
  stesso caso a `761x1363`, soggetto `[206,717,875,1920]`, faccia integra,
  `visible_ratio=1.000`.
- `temp/proof_characters.mp4`: slideshow prima/dopo + sottotitoli reali
  (testo + personaggio) con 2 pose larghe.

## Note e limiti osservati (fuori scopo, non toccati)

- Il guard pre-esistente `Layout/words fuori sync` in
  `core/text_animator.py:1821` puo' scattare su parole lunghe in box split
  stretti (il pre-split REELS-FIX v5 cambia il conteggio: verificato a font 64
  con area 306 px, 9 parole -> 10 voci layout). Pipeline audio/trascrizione/
  tema/keyword non toccate.
- Il punch-in sulle pose vincolate e' spesso neutralizzato dal tetto
  larghezza (fattore effettivo 0.4-0.8 invece di 1.15x, loggato in `notes`):
  comportamento voluto da FASE 5 (il vincolo vince).
- Il micro-idle (±5/±3 px) puo' rosicchiare ~5 px del margine 40 durante la
  permanenza; a riposo senza idle i margini sono pieni.
- Con `CHARACTER_ENABLED=0` nulla cambia (early-return invariati).
