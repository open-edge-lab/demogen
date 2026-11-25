# demogen — Piano d'esecuzione (derivato da `demogen-piano-implementazione.md` v2)

## 0. Scopo allineato con lo stakeholder

`demogen` è uno strumento **offline** di generazione di demo stile demoscene:

1. l'utente digita un prompt;
2. un LLM scrive gli shader GLSL del "demoscene";
3. **il motore di rendering creato da noi** (player WebGL2) lo renderizza in **realtime** in una finestra locale;
4. un LLM con visione analizza i frame catturati dal motore, critica e si itera;
5. il consumo di GPU e di LLM è confinato alla fase di generazione.

**Requisiti del motore (primo step)**: rendering realtime su **macOS sfruttando la GPU** (ANGLE → Metal) e, quando la GPU non è disponibile, **fallback su CPU** (SwiftShader) — deve funzionare in entrambe le modalità, non fallire. **Nessun output video in questa fase**: l'export MP4 è posticipato e non è un obiettivo del primo step. Il player non è un prodotto web da distribuire ai visitatori: resta un componente interno della pipeline.

Punto di partenza: repo vuoto, solo il piano v2 in `docs/`. Piattaforme di sviluppo: macOS (Apple Silicon) e Linux. Nessun codice esistente.

Obiettivo di questo documento: trasformare le 8 fasi del piano v2 in un ordine di lavoro eseguibile, con dipendenze, milestone misurabili e decisioni da prendere. Non introduce nuovi vincoli: dove questo documento e il piano v2 differiscono, vince il piano v2.

---

## 1. Principi di esecuzione

1. **Una fase alla volta, nell'ordine del §20 del piano v2.** Non si inizia una fase finché i criteri di accettazione della precedente non sono soddisfatti e i test passano.
2. **Vertical slice presto.** Il player web è l'unico renderer (D5): è il componente che sblocca tutto il resto (probe, metriche, golden test, perf). Si costruisce per primo e si convalida con shader scritti a mano prima di coinvolgere任何 LLM.
3. **Gate numerici prima del critico LLM** (D10): le fasi 1–4 costruiscono l'infrastruttura di misura; solo la Fase 5 la usa con l'orchestratore.
4. **Nessuna chiamata API reale nei test standard** (`@pytest.mark.live` escluso di default); perf su GPU reale solo in locale (`@pytest.mark.perf`).
5. Ogni fase termina con: test verdi, demo command eseguitato, checkbox aggiornate, commit `phase N: <sintesi>`.

---

## 2. Grafo delle dipendenze

```
Fase 0 (scheletro + spike player/harness + doctor)
   │
   ├──▶ Fase 1 (player core, profili, libreria GLSL, preproc/treeshake/minify, harness, CLI play/bundle, CI)
   │        │
   │        ├──▶ Fase 2 (audio GPU + libreria audio + metriche audio)
   │        │
   │        ├──▶ Fase 4 (metriche video/perf, gate, sheets, inspect/calibrate)
   │        │
   │        └──▶ Fase 5 (orchestratore: pipeline S0–S9, prompt, E2E finto, CLI generate/resume/revise)
   │                 ▲
   └──▶ Fase 3 (livello LLM: config, provider, client, envelope, budget, models check) ─┘
                    │
                    └──▶ Fase 6 (oracolo matematico: safe_parse, verify, codegen, step S3)
                              │
   Fase 1+2+4+5 ────────────────┴──▶ Fase 7 (distribuzione web, qualità, accessibilità, export 64k/MP4/Shadertoy)
   Fase 8 (opzionale): size-coding, WebGPU, UI web, benchmark modelli — solo dopo Fase 7
```

Nota: la Fase 3 (livello LLM) è quasi indipendente dal player e può essere sviluppata in parallelo con le Fasi 1–2 una volta completata la Fase 0, ma la sequenza canonica resta 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7.

**Fuori dallo scopo dello step corrente** (restano nel piano v2 ma non sono obiettivi ora): distribuzione web del player (embed, `power`/`eco`, pausa fuori viewport), export MP4/Shadertoy, classe 64k, compatibilità multi-browser come prodotto.

---

## 3. Fasi, task e milestone

### Fase 0 — Spike e scheletro (sblocca tutto)
**Task**
- Monorepo: `pyproject.toml` (uv, Python 3.11+), `package.json` con workspace `player`, `ruff`, `pytest`, `vitest`, `esbuild`, `CLAUDE.md` iniziale.
- Spike player TS: render realtime di uno shader Shadertoy (GLSL ES 3.00, `mainImage`/`iTime`/`iResolution`) su canvas WebGL2.
- **Spike dual-mode GPU/CPU**: lo stesso player deve girare (a) su Mac con GPU reale (ANGLE → Metal, browser headed) e (b) in CPU via SwiftShader (flag `--use-angle=swiftshader-webgl --enable-unsafe-swiftshader`). Rilevamento del renderer via `WEBGL_debug_renderer_info` → `UNMASKED_RENDERER_WEBGL` per distinguere "Apple GPU" da "SwiftShader"/"llvmpipe" e stampare la modalità attiva.
- Spike harness: Python + Playwright apre `harness.html` servito con `page.route` (rete esterna bloccata), compila uno shader, cattura un PNG, misura ms/frame fuori da rAF.
- `demogen doctor`: Node, browser Playwright, renderer visto da Chromium, estensioni WebGL2 (`EXT_color_buffer_float`, `KHR_parallel_shader_compile`, `EXT_disjoint_timer_query_webgl2`), `glslangValidator`, `ffmpeg` (opzionale).

**Verifiche [VERIFICARE] da chiudere qui**
- Flag per GPU reale in headless Chromium su macOS (ANGLE → Metal); fallback `perf_headed`.
- Flag SwiftShader su Linux CI (`--use-gl=angle --use-angle=swiftshader-webgl --enable-unsafe-swiftshader`).
- Throughput del trasferimento frame pagina → Python (alternative: `exposeBinding`, WebSocket loopback).
- Limite di contesti WebGL attivi per pagina.

**Milestone M0**: `demogen doctor` tutto verde; lo spike renderizza in realtime e salva un PNG **in entrambe le modalità**: GPU su Mac (renderer riportato = Apple GPU, non SwiftShader) e CPU (renderer = SwiftShader), con ms/frame e modalità aktive stampati. In CPU i gate realtime non si applicano: basta che renderizzi senza errori.

**Stato: ✅ M0 raggiunta.** Verifiche [VERIFICARE] risolte sul campo (Windows, Chromium 159): la **headless shell di Playwright usa sempre SwiftShader** — per la GPU reale in headless serve il full Chromium (`channel="chromium"`); renderer GPU reale = `ANGLE (…, Direct3D11 …)` su Windows, `ANGLE (Apple, Metal …)` su Mac. SwiftShader via `--use-angle=swiftshader-webgl --enable-unsafe-swiftshader` ok. Cattura frame via `toDataURL` (preserveDrawingBuffer) — throughput ok. Misura ms/frame in headless poco affidabile (valori ~0): in Fase 1 si usa `EXT_disjoint_timer_query_webgl2` (esposta) o fence. `glslangValidator`/`ffmpeg` mancanti su Windows: non bloccanti ora.

---

### Fase 1 — Player core, profili e libreria GLSL
**Task**
- Player TS: `gl`, `programs` (compilazione parallela), `timeline`, `compositor` (4 transizioni, anche cross-profilo), `post` (bloom opzionale + finalize), `quality` (adattivo, eco, frame pacing a target_fps), `format`, custom element `<demogen-player>`, context loss.
- Profilo `retro`: risoluzione interna fissa (320×180), upscale nearest a multipli interi, letterbox, `uText[64]` + `uTextLen`.
- `shared/vectors/`: parità timeline tra pytest e vitest.
- Python GLSL: `preprocessor.py`, `validator.py` (glslangValidator profilo ES 300), `treeshake.py`, `minify.py` (base), `docs.py` (riferimento API da `///`).
- Harness completo (`load`, `capture`, `lumaSequence`, `profile`, `renderAudio`, `info`) + `session.py`, `harness.py`, `serve.py`, `perf_lane.py`.
- Libreria GLSL §7 (video + `retro/`) con golden render via harness e test numerici su GPU.
- CLI: `demogen play shader.glsl --bpm 120 [--profile retro]`, `demogen bundle` base (shader + timeline JSON → `.demo` + `.html`).
- CI: limite dimensione player core (≤ 12 KB min+gzip), test unit, golden render su SwiftShader.

**Verifiche [VERIFICARE]**: precisione codifica audio 16 bit (in Fase 2), `outputLatency` browser, comportamento ANGLE→D3D su Windows (bench manuale in Fase 7).

**Milestone M1**: demo con 4 shader scritti a mano (tunnel, frattale IFS, terreno, plasma retro con scroller) + transizioni, renderizzata in realtime dal motore nostro: 60 fps a 1080p su Mac con GPU (ANGLE → Metal); in modalità CPU (SwiftShader) renderizza comunque senza errori (fps ridotti accettati — il gate realtime vale solo in GPU). Golden test verdi su SwiftShader; player core ≤ 12 KB gzip. Gli embed web (`examples/embed`, eco mode) **non sono obiettivo di questo step**.

**Stato: ✅ M1 raggiunta.** Player core 6761 B gzip (budget 12288). Demo M1 (`examples/timeline.json`, 4 scene, 64 s, bpm 120): compila in Chromium (52 ms CPU / 2,1 s GPU ANGLE→D3D per 4 programmi raymarching), probe OK in **entrambe** le modalità — SwiftShader (4 frame non neri, scene distinte) e GPU reale Intel UHD 620 (0,7–2,0 ms/frame a 960×540 → 60 fps @1080p plausibili; Mac Apple Silicon da verificare sul campo). Bundle: `out/demogen-m1.demo` 3,8 KB gzip + `out/demogen-m1.html` standalone 32,7 KB. Parità timeline Python↔TS su 25 vettori condivisi. CI GitHub Actions (uv+npm+playwright+ruff+pytest+vitest+size gate). Bug trovati e fissati: hash hex >2³¹ overflow su ANGLE (costanti <2³¹), treeshake con ordine topologico (self-loop escluso), forward declaration condizionale di `map`, busy-wait timer query → fence di default.

---

### Fase 2 — Audio
**Stato: ✅ M2 raggiunta.** Player: `player/src/audio.ts` — render GPU a blocchi (FBO WxH, un texel per campione stereo; RGBA32F con `EXT_color_buffer_float`, fallback RGBA8 16-bit), prebuffer 8 s, pump in background ≤ 2 ms/frame, scheduling chunk consecutivi sul clock `AudioContext` (clock master audio), sblocco al gesto (click/tasto), seek con re-render. Contratto: `mainAudio(out vec4 o, in float t)` + header con `iSampleRate/uBeat/uBeatPhase/uBar/BPM/uBlockStart`. Libreria `demogen/glsl/lib/audio/chip.glsl` (kick 808 pitch-drop, hat, snare, bass square, arp). Metriche: `critic/metrics_audio.py` (spettrogramma PNG con griglia beat, spectral-flux onset, onset vs beat grid) + gate in `run_gates` (clip, onset err > 5 ms) + `inspect` le mostra. Test: continuità sinusoide 440 Hz su 3 chunk GPU (no gap), FFT chip (kick/bass < 200 Hz dominanti, hat > 5 kHz), onset sintetico err < 5 ms, planChunkStarts; inspect E2E su `examples/audio_chip.timeline.json`: **onset err 1.50 ms, 0 issue**. Demo esempio: `examples/audio_chip.timeline.json` (video plasma retro + chip audio).
**Task**
- `audio.ts`: render GPU a blocchi (RGBA8 16 bit; float via `EXT_color_buffer_float` nell'harness), prebuffer `audio.prebuffer_s` + resto in background (≤ 2 ms/frame), scheduling chunk su clock `AudioContext`, clock audio master, sblocco al gesto, seek con render sincrono del chunk mancante.
- Libreria audio §7 (`osc`, `env`, `drums`, `music`, `chip`) con test su FFT, inviluppi, duty cycle.
- `metrics_audio.py` + spettrogramma con griglia di battute.
- Test scheduling: ~~`OfflineAudioContext`~~ non implementato. Copertura reale (review 2026-11-25): continuità tra chunk sul render GPU (harness), `chunkSchedule` puro (vitest: chunk + offset del primo campione), fallback RGBA8 ≈ float (errore < 1e-4).

**Verifiche [VERIFICARE]**: assenza di click/gap tra chunk (alternativa: AudioWorklet con codice fisso del player); supporto `outputLatency` per browser.

**Milestone M2**: demo con audio; kick allineato al `beatPulse` visivo; errore onset vs griglia < 5 ms; prebuffer 8 s entro `max_render_ms_prebuffer`; nessuna discontinuità tra chunk; sync A/V verificata a mano (pagina lampo+beep).

---

### Fase 3 — Livello LLM
**Task**
- `config.py` + `demogen init` (crea `demogen.yaml` dal template `demogen/demo.yaml`).
- `providers.py` (openai_compatible + openrouter), `client.py` (sync/async, retry backoff+jitter, logging con redazione chiavi, usage/costo), `capabilities.py` con cache 24 h, `envelope.py`, `structured.py` (3 livelli + loop riparazione max 2), `budget.py`.
- `demogen models check`.
- Test con server finto OpenAI-compatible + fixture registrate: risposte valide, JSON malformato, GLSL senza recinto, 429 con retry, timeout.

**Verifiche [VERIFICARE]**: nomi dei campi del catalogo `GET /api/v1/models` di OpenRouter (input modes, parametri); come l'SDK `openai` espone campi extra di `usage` (costo OpenRouter).

**Milestone M3**: test verdi in CI; `models check` (live, manuale) funzionante su OpenRouter e su endpoint locale.

**Stato: ✅ M3 (parte CI) raggiunta.** Livello LLM completo e testato con server OpenAI-compatible finto (nessuna chiamata reale in CI): `config.py` (YAML+env, pydantic, `inherit` ruoli), `providers.py` (openai_compatible/openrouter), `client.py` (retry backoff+jitter su 429/5xx/timeout, log JSON con redazione chiavi/immagini, costo da usage extra o tabella prezzi, `achat` async), `envelope.py` (```json + ```glsl), `structured.py` (3 livelli: json_schema strict → json_object → envelope, con loop di riparazione max 2), `capabilities.py` (catalogo OpenRouter con cache 24 h; default prudente sugli endpoint generici), `budget.py` (costo stimato pre-chiamata, stop anticipato). CLI: `demogen init`, `demogen models check` (testa testo/vision/json_schema per ruolo). Test: 12/12 verdi (valida, JSON malformato+riparazione, 429 con retry, timeout, budget, capabilities+cache, redazione log, init, models check). `models check` live su OpenRouter/locale resta **manuale** (`@pytest.mark.live`).

---

### Fase 4 — Metriche, gate e materiale per il critico
**Task**
- `metrics_video.py`, `metrics_perf.py`, `flash.py` (WCAG 2.3.1), `gates.py` (§12.5), `sheets.py` (contact sheet, burst strip, heatmap, grafico perf, spettrogramma).
- Test sintetici con esito atteso: nero, NaN, flicker, strobo 10 Hz, flash rosso, shader pesante, carico medio alto, cicli annidati, payload fuori limite.
- `demogen inspect <shader|file.demo>`, `demogen calibrate`.

**Verifiche [VERIFICARE]**: approssimazione del gate flash vs WCAG 2.3.1 (confronto con strumento di riferimento su clip di prova).

**Aggiornamento review 2026-11-25 (Batch E).** Il gate flash di M4 non seguiva WCAG (media in sRGB, 25% dello schermo, ogni transizione contata come flash, 8 fps sui primi 6 s → aliasing). Ora: celle 16×16 linearizzate per pixel, transizioni con isteresi 0,1 e stato scuro < 0,8, flash = coppia di transizioni opposte, fallisce se un'area ≥ 2,8% dello schermo (25% di 10°; approssimazione conservativa: celle anche non contigue) lampeggia più di 3 volte in una finestra mobile di 1 s; rosso contato a coppie; 30 fps su tutta la scena (S5), su tutta la demo con le transizioni (S9) e in `inspect`. Il flicker "z>4" (impossibile con ≤16 campioni) è sostituito da uno score di oscillazione su raffiche di frame consecutivi; `loop_seam` confronta t = dur−1/fps con t = 0. Perf: su SwiftShader i gate sono `info`, su GPU si misura alla risoluzione del budget (altrimenti scala per rapporto di pixel). `calibrate.json` resta **informativo**: nessun gate lo legge (manca una scala di riferimento affidabile).

**Milestone M4**: i casi sintetici sono classificati correttamente dai gate; `inspect` stampa metriche, perf con carico stimato, avvio, flash, dimensioni e salva i fogli.

**Stato: ✅ M4 raggiunta.** `demogen/critic/`: `metrics_video` (NaN/Inf da FBO RGBA32F via harness `stats`, nero/bianco, luma, entropia, colorfulness Hasler–Süsstrunk, flicker z>4, loop_seam), `metrics_perf` (p50/p95/max/mean, pavimento, gpu_load_est, hotspot), `flash` (WCAG 2.3.1 su cellSequence 8×8 RGB: flash ≥0.1 luma relativa su ≥25% celle, finestre 1 s, flash rossi R/(R+G+B)≥0.8), `gates` (soglie da config: blocker/major/minor), `sheets` (contact sheet, burst strip, heatmap diff, grafico perf — Pillow), `critic.py` (chiamata LLM vision, usada in Fase 5). Harness esteso: `stats` (FBO float) e `cellSequence`. CLI: `demogen inspect <glsl|timeline.json|demo> --gpu swiftshader|hardware` (report in `out/inspect_*/`: contact/burst/diff/perf.png + metrics.json + issues.json) e `demogen calibrate` (4 shader examples su GPU reale → `out/calibrate.json`). Test: 10 sintetici (nero→major, NaN→blocker, strobo 10 Hz→blocker flash, flash rosso→blocker, p95→blocker, mean alto→major consumo, payload grande→major, compilazione lenta→major, loop_seam) + E2E inspect su M1 senza blocker. pytest 31/31, vitest 18/18, ruff pulito. Player core 7237 B gzip (< 12 KB).

---

### Fase 5 — Orchestratore v1 (senza oracolo)
**Stato: ✅ M5 (CI) raggiunta.** Pipeline S0–S9 con macchina a stati + `state.json` resume (`orchestrator/pipeline.py`, `steps.py`, `selection.py`), template prompt Jinja in `llm/prompts/` (system_contract, brief/style, scene modern/retro, revise, fixer, critic_scene), `FakeLLM` per `--fake`, project store + `report.md`, CLI `generate/resume/revise/report`. E2E finto verde: `generate --fake` → `.demo` 8 s che compila nell'harness e passa i gate senza blocker (~23 s). Smoke live con LLM reale resta manuale (`@pytest.mark.live`, `demogen models check`). Nota: architettura "codemode" — l'LLM genera il codice GLSL, il motore nostro lo esegue, un LLM con visione riverifica i frame e itera (S6–S8 + `revise`).
**Task**
- `spec/models.py` completo (pydantic v2, §9).
- `pipeline.py`: macchina a stati S0–S9, `state.json`, resume idempotente; step S0, S1, S2, S4–S9; selezione best con anti-regressione e penalità perf.
  - *Review 2026-11-25 (Batch D)*: in M5 il resume NON era idempotente (S4–S7 marcati dopo la prima scena, log sovrascritti) e il budget non veniva mai applicato. Ora: richiesta salvata prima di S0, scene marcate una per una, artefatti riusati (S5/S6/S7), log che non si sovrascrivono, spesa in `state.json` a ogni step, `BudgetExceeded` → bundle con le best attuali (`state["stopped"]`), "accept" solo senza blocker, S9 fallisce con blocker. Verificato da test (resume dopo crash = solo le chiamate mancanti; resume a progetto completo = 0 chiamate).
- Template prompt §17 (tranne `math`), varianti modern/retro e modern/chip; prefisso stabile cacheable.
- Parallelismo: `asyncio` + `llm_concurrency`, pool pagine per catture, perf lane serializzato.
- `report.md`; CLI `generate`, `resume`, `revise`, `report`.
- E2E con LLM finto deterministico (fixture) → `.demo` di 8 s che passa i gate nell'harness.

**Milestone M5**: E2E finto verde in CI; smoke live (`@pytest.mark.live`, manuale) con prompt modern e retro di `examples/prompts/`: demo 30–60 s realtime entro budget, payload entro limite, costo entro budget.

---

### Fase 6 — Oracolo matematico
**Stato: ✅ M6 raggiunta.** `demogen/math/`: `safe_parse.py` (whitelist AST + eval in subprocess con RLIMIT_AS/CPU e timeout; cross-platform, su Windows solo timeout), `verify.py` (claim numerici: sdf via |grad f|≈1 + segno, lipschitz, periodic_path, easing, identity), `codegen.py` (AST safe → GLSL ES 3.00 deterministico, funzioni vettoriali → vec2/vec3), `oracle.py` (accepted/rejected con reason). Integrazione: `ShaderSubmission.math_requests` → S2/S7 `run_oracle_for` salva `vN.math.glsl` (solo accepted) e lo concatena in S4/S5/S9 (`with_math`). Prompt: sezione "Math oracle" in scene modern/retro. Test: 29 unit (parse malevoli rifiutati, claim veri/falsi, codegen, oracle E2E) + E2E fake con math_request vero (accettato, nel .demo) e falso (rifiutato).
**Task**
- `safe_parse.py`: whitelist token, subprocess con timeout 5 s + watchdog RSS (psutil, macOS), test di rifiuto (`__import__`, attributi, lambda, stringhe).
  - *Review 2026-11-25 (Batch C/G)*: in M6 il watchdog psutil non esisteva (solo RLIMIT su POSIX, timeout 10 s). Ora: `python -I -c` (niente import dalla cartella corrente), watchdog psutil su RSS (processo + figli, 512 MB) e tempo (5 s) **su tutti gli OS**, parametri del claim limitati (samples ≤ 4096, tol ≤ 1e-2), arità controllata, nomi riservati GLSL rifiutati, semantica Python allineata a GLSL (mod floored, smoothstep, pow con base negativa indefinito, `**` solo con esponente 2..4).
- `verify.py`: tutti i tipi di claim (§11.2) con test veri/falsi noti.
  - *Review*: ora lega tutte le variabili (SDF 3D verificabili), richiede ≥ 90% di punti valutati, Lipschitz su coppie vicine, segno della SDF verificato sul bordo del dominio (e su `inside`).
- `codegen.py`: ~~sympy~~ AST safe → GLSL ES normalizzato (float letterali, no conversioni implicite). sympy non è mai stato usato ed è stato rimosso dalle dipendenze. `%` → `mod()`, `atan2` → `atan(y, x)`, funzioni vettoriali con due vettori, firma nell'ordine di `inputs`; ogni costrutto è compilato nel browser in un test.
- Step S3 e integrazione nel prompt orchestratore.

**Milestone M6**: E2E finto con `math_requests` include snippet verificato che compila in tutti i motori; claim falsi tutti rifiutati.
*Precisazione (review)*: "tutti" vale per le classi verificate dai test (SDF senza regione negativa o invertita, gradiente ≠ 1, Lipschitz oltre il bound o senza punti valutati, periodo sbagliato, easing non 0→1, identità false); la verifica è statistica su punti campionati, non una dimostrazione.

---

### Fase 7 — Distribuzione web e qualità
**Task**
- Taratura qualità adattiva (isteresi, frame time simulati + shader pesanti artificiali).
- Accessibilità: `reduce-flashes`, `prefers-reduced-motion`, controlli tastiera, gate flash su demo intera.
- Fallback poster, UI errore, modulo `bench` + `demogen perf import`.
- Gate compatibilità motori in S9; modalità loop con verifica `loop_seam`; classe 64k (bootstrap autoestraente con `DecompressionStream`).
- `export-shadertoy`, `export-mp4` (ffmpeg), critica finale demo intera + revisione mirata.

**Verifiche [VERIFICARE]**: overhead `DecompressionStream` e alternative di codifica per la classe 64k; tempi di compilazione ANGLE→D3D su Windows (bench manuale); limite contesti WebGL per pagina.

**Milestone M7**: demo moderna 60 s, 4 scene, transizioni, audio: 60 fps su macchina di sviluppo, ≥ 50 fps con qualità adattiva su portatile Windows medio (bench manuale); demo retro ≥ 60 fps su telefono datato (bench manuale); HTML standalone ≤ 64 KiB; ok su Chromium/WebKit/Firefox; gate flash verificato.

---

### Fase 8 — Opzionale (dopo M7)
Size-coding 8k/4k, backend WebGPU, UI web locale, benchmark modelli, tier mobile, interattività. Solo se richiesta esplicitamente.

---

## 4. Decisioni aperte da chiudere (dal §23 del piano v2) — proposte di default

| Decisione | Proposta di default da confermare |
|---|---|
| Lingua prompt di sistema | Inglese (il prompt utente può essere in qualsiasi lingua) |
| Durata massima v1 | 120 s |
| Dispositivo di riferimento per il budget | Macchina di sviluppo (Apple Silicon), da tarare con `demogen calibrate` e bench reali |
| Mobile | Best effort in v1; garantito solo per il profilo retro |
| Default `power` / `autoplay` negli embed | `power="auto"`, `autoplay="visual"` |
| Soglia `accept` del critico | Media pesata ≥ 7 e nessuna issue blocker/major |
| Licenza | Da scegliere prima della Fase 5 (MIT consigliata per player/libreria; verificare che la libreria GLSL sia tutta originale) |
| Distribuzione player | Self-hosting in v1, URL versionati; CDN pubblico in Fase 7+ |

Queste decisioni vanno confermate con lo stakeholder **prima di iniziare la Fase 5** (come richiesto dal piano v2); le prime due (lingua, durata) servono già in Fase 0 per `demogen init`.

---

## 5. Rischi principali e dove si affrontano

| Rischio | Fase dove si mitiga |
|---|---|
| GPU reale non raggiungibile in headless su macOS | Fase 0 (spike + doctor) — blocca tutto se non risolto |
| Transfer frame pagina→Python lento | Fase 0 (misura throughput, alternative exposeBinding/WebSocket) |
| Click/gap nello scheduling audio a chunk | Fase 2: primo chunk con offset, risincronizzazione sugli underrun, continuità testata sul render GPU (OfflineAudioContext non usato); fallback AudioWorklet a codice fisso |
| Campi OpenRouter/SDK openai non come atteso | Fase 3 (models check + cache; fallback config manuale) |
| Gate flash non allineato a WCAG 2.3.1 | Fase 4 + review Batch E (coppie di transizioni, area 2,8%, 30 fps, luce lineare); resta il confronto con uno strumento di riferimento (PEAT/Harding) |
| Compilazione lenta ANGLE→D3D su Windows | Fase 1 convenzioni sui cicli; Fase 7 bench manuale Windows |
| Costi LLM che esplodono | Fase 3 `budget.py` + Fase 5 stop con migliore versione (effettivo solo dalla review Batch D: prima il budget non arrivava ai client) |
| Differenze cross-browser del GLSL | Fase 1 golden test + Fase 7 gate compatibilità 3 motori |

---

## 6. Strategia di test (riepilogo operativo)

- CI (Linux, SwiftShader): unit Python, unit TS (vitest), golden render con tolleranza, compat Chromium/WebKit/Firefox, dimensione player, LLM con server finto, E2E finto.
- Locale macOS (GPU reale): `@pytest.mark.perf` per profili perf e calibrazione; `@pytest.mark.live` solo manuali.
- Fixture LLM: registrate con `DEMOGEN_RECORD=1`, ripulite da chiavi/header prima del commit.

---

## 7. Prossimi passi immediati (Fase 0)

1. Creare lo scheletro del monorepo (`pyproject.toml`, `package.json` workspace `player`, `CLAUDE.md`, config ruff/pytest/vitest/esbuild).
2. Spike player: un TS minimo che renderizza uno shader Shadertoy su WebGL2.
3. Spike harness: Playwright + `page.route` → compila, cattura PNG, misura ms/frame.
4. `demogen doctor` con le verifiche [VERIFICARE] della Fase 0.
5. Criterio di uscita M0: doctor verde + spike PNG + renderer GPU Apple su Mac.
