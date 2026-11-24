# demogen — Piano di implementazione (v2: demo realtime per il web)

Strumento che genera **demo realtime in stile demoscene** a partire da un prompt testuale e le distribuisce come pacchetti di pochi KB, eseguiti nel browser da un **player JavaScript superleggero**. Ogni frame è il campione di una funzione `colore = f(x, y, t)` scritta in GLSL; l'audio è una funzione `campione = g(t)`, anch'essa in GLSL. Il sito trasferisce **codice, non video**: le immagini e il suono vengono generati in tempo reale dalla GPU di chi guarda.

Un orchestratore LLM (coding + vision) scrive gli shader, un oracolo matematico deriva e verifica le formule delicate, il **player web stesso** — pilotato in headless da Python tramite Playwright — compila, misura le prestazioni e cattura i frame, e un critico (vision + metriche numeriche) chiude il ciclo di feedback.

Supporto modelli: qualunque endpoint **OpenAI-compatible** (vLLM, llama.cpp server, LM Studio, Ollama, provider cloud) e **OpenRouter** come preset dedicato.

Piattaforme di sviluppo: **macOS (Apple Silicon)** e Linux. Il rendering passa sempre dal browser (su Mac: ANGLE → Metal), quindi nessuna dipendenza da OpenGL nativo.

---

## Cambiamenti rispetto alla v1

| Aspetto | v1 | v2 |
|---|---|---|
| Prodotto principale | `final.mp4` | `<nome>.demo` (payload) + `<nome>.html` standalone + player JS embeddabile |
| Renderer | moderngl offline in Python | **player WebGL2 in TypeScript**, unico renderer; Python lo pilota via Playwright |
| Dialetto shader | GLSL 330 core | **GLSL ES 3.00** (WebGL2, lo stesso di Shadertoy) |
| Qualità d'immagine | supersampling 4× + motion blur per accumulo | anti-aliasing analitico nello shader + qualità adattiva a runtime |
| Gate prestazioni | 400 ms/frame su keyframe in preview | **budget realtime p95 a risoluzione di riferimento su tutta la timeline**, transizioni incluse |
| Audio | GPU → WAV → mux | GPU nel browser al caricamento → WebAudio; **clock audio come riferimento** |
| Vincoli nuovi | — | dimensione del payload, tempo di compilazione shader, fotosensibilità (flash), compatibilità tra browser |
| Profili di rendering | — | `modern` (raymarching/SDF) e `retro` (2D old school a bassa risoluzione, palette, dithering), mescolabili per scena |
| Consumo | — | gate sul carico medio, frame pacing, modalità `eco` per gli embed, carico GPU stimato nel report |
| Avvio | — | audio progressivo (prebuffer + background), gate sul tempo al primo frame |
| MP4 | obiettivo | export opzionale (Fase 7) |

---

## 0. Istruzioni per Claude Code

- Lavora **una fase alla volta**, nell'ordine. Non iniziare una fase finché i criteri di accettazione della precedente non sono soddisfatti e i test passano.
- Alla fine di ogni fase: esegui `uv run pytest` e `npm test --workspace player`, esegui il comando demo indicato nella fase, aggiorna le checkbox di questo file, fai un commit con messaggio `phase N: <sintesi>`.
- **Nessuna chiamata API reale nei test** standard. I test che usano API vere sono marcati `@pytest.mark.live` ed esclusi di default.
- I test di prestazioni su GPU reale sono marcati `@pytest.mark.perf` ed esclusi in CI (la CI usa rendering software, dove i tempi non sono significativi).
- Le decisioni marcate **[DECISIONE]** sono vincolanti; se emerge un motivo tecnico per cambiarle, fermati e chiedi prima di procedere.
- I punti marcati **[VERIFICARE]** dipendono da dettagli esterni (browser, driver, API, versioni di librerie): verificali sul campo prima di costruirci sopra.
- Mantieni un `CLAUDE.md` nel repo con: comandi di build/test (Python e player), convenzioni, stato delle fasi.

---

## 1. Obiettivi e non-obiettivi

### Obiettivi v1
- `demogen generate "tunnel al neon che respira a 128 BPM, palette magenta/ciano, 60 secondi"` → produce in `out/`:
  - `neon-tunnel.demo` — payload (JSON + sorgenti GLSL), tipicamente 10–40 KB compresso;
  - `neon-tunnel.html` — file unico autosufficiente (player + payload), apribile anche offline;
  - `poster.webp` — immagine di fallback;
  - `report.md`.
- **Esecuzione realtime nel browser**: 60 fps a 1080p sulla macchina di sviluppo con margine di sicurezza (§13), degradazione adattiva su GPU più deboli.
- **Due profili di rendering**: `modern` (raymarching, SDF, fbm: l'estetica delle intro moderne) e `retro` (effetti 2D old school a 320×180 con palette e dithering, leggerissimo), anche mescolabili per scena (§14).
- **Consumo contenuto**: gate sul carico medio della GPU, frame rate limitato al target anche sugli schermi a 120 Hz, modalità `eco` per le demo inserite nelle pagine, stima del carico nel report.
- **Avvio rapido**: primo frame entro ~1,5 s sulla macchina di sviluppo; l'audio oltre i primi secondi si calcola in background mentre la demo è già partita.
- **Embedding** in qualunque sito: `<demogen-player src="x.demo">`, un solo script del player condiviso da tutte le demo della pagina.
- **Peso**: player core ≤ 12 KB min+gzip; payload tipico ≤ 48 KB gzip; classe 64k (HTML standalone ≤ 64 KiB su disco) raggiungibile.
- Interamente procedurale: nessuna texture, nessun asset esterno, nessun modello generativo di immagini/video.
- **Tempo puro**: ogni frame dipende solo da `t` → seek, loop, scrub e sincronia col beat gratuiti; nessuno stato tra frame.
- Iterazione automatica: scrittura → compilazione → probe → critica → revisione, con budget controllato (iterazioni, costo, tempo).
- Riproducibilità: stesso payload → stessa immagine per ogni `t` (a meno di differenze tra GPU).
- Progetto persistente e riprendibile; revisione mirata di una scena con nota testuale.
- Ruoli LLM configurabili indipendentemente (modello, provider, parametri).

### Non-obiettivi v1
- Video come prodotto principale (l'export MP4 è opzionale, Fase 7).
- Vincoli 4k/8k stile size-coding (Fase 8).
- Backend WebGPU (Fase 8).
- Multipass arbitrario o buffer di feedback scritti dall'LLM.
- Mobile come target garantito (best effort tramite qualità adattiva).
- **Esecuzione di codice JavaScript o Python generato da LLM**, in qualunque punto (vietata per design, vedi D11 e §18).

---

## 2. Decisioni architetturali

| # | Decisione | Motivazione |
|---|---|---|
| D1 | **[DECISIONE]** Orchestrazione come **macchina a stati esplicita in Python**, non come agente LLM libero con tool calling | Deterministica, debuggabile, funziona anche con modelli senza tool calling, budget controllabile per step |
| D2 | **[DECISIONE]** Uno **shader per scena** + una libreria GLSL comune pre-testata + uno `style.glsl` condiviso; transizioni e post-processing gestiti dal player | Contesti piccoli per l'LLM, iterazione indipendente e parallelizzabile per scena, coerenza visiva, meno errori grazie a funzioni già verificate |
| D3 | **[DECISIONE]** Contratto shader **compatibile Shadertoy in GLSL ES 3.00** (`mainImage`, `iTime`, `iResolution`) + uniform di sincronizzazione e qualità; **niente `iFrame`/`iTimeDelta`** | I modelli conoscono bene il formato; in realtime l'aspetto non deve dipendere dal frame rate |
| D4 | **[DECISIONE]** Audio come **shader GLSL** (`mainSound`), renderizzato su GPU dal player al caricamento e riprodotto con WebAudio; il clock audio pilota il tempo video | Tutto resta "funzione del tempo", nessun codice generato eseguito fuori dalla GPU, sincronia esatta |
| D5 | **[DECISIONE]** **Il player web è l'unico renderer.** Anteprime, metriche, golden test, misure di prestazioni ed export usano lo stesso codice che gira sui siti; Python lo pilota con Playwright | Ciò che si testa è ciò che si distribuisce; nessuna divergenza tra dialetti GLSL; nessuna dipendenza da OpenGL nativo (deprecato su macOS) |
| D6 | **[DECISIONE]** Python 3.11+ con `uv`, CLI `typer`, schemi `pydantic` v2, client LLM con SDK `openai` (`base_url`); player in **TypeScript senza dipendenze runtime**, build `esbuild`, test `vitest` + Playwright | Un solo client per tutti i provider compatibili; player minimo e verificabile |
| D7 | **[DECISIONE]** **WebGL2** come API grafica del player v1; WebGPU come backend futuro dietro la stessa interfaccia interna | WebGPU è ora supportato nei browser principali ma con copertura ancora incompleta (Linux, parte di Android, Mac Intel su Firefox); GLSL ES 3.00 è il dialetto più noto ai modelli; player più piccolo |
| D8 | **[DECISIONE]** Il codice GLSL viaggia **fuori dal JSON** nelle risposte LLM, in blocchi recintati; i metadati in un blocco JSON separato ("envelope") | Evita gli errori di escaping del GLSL dentro stringhe JSON |
| D9 | **[DECISIONE]** Critico idealmente **diverso** dall'orchestratore (configurabile) | Riduce l'auto-valutazione indulgente |
| D10 | **[DECISIONE]** Gate tecnici numerici **prima** del critico LLM (compilazione, NaN, nero, prestazioni, tempo di compilazione, flash, dimensione) | Scarta i fallimenti ovvi senza spendere chiamate vision |
| D11 | **[DECISIONE]** **Il player è codice fisso, le demo sono dati.** Il formato `.demo` contiene solo JSON e sorgenti GLSL; il player non esegue mai JS proveniente dal payload (niente `eval`, `Function`, import dinamici) ed è compatibile con CSP rigide | Ospitare demo = ospitare shader, validati dal browser (ANGLE) e protetti dal watchdog GPU; il player è scritto e testato una volta, non generato per ogni demo |
| D12 | **[DECISIONE]** **Tempo puro + qualità adattiva**: ogni scena è funzione di `(fragCoord, t, uQuality)`; il player regola risoluzione interna e `uQuality` per mantenere il frame rate | Seek/loop/scrub gratuiti; una sola demo si adatta a GPU molto diverse |
| D13 | **[DECISIONE]** Due **profili di rendering**, `modern` e `retro`, scelti per demo con override per scena, ciascuno con il proprio budget di prestazioni | Il retro recupera l'estetica e la leggerezza delle demo classiche (pochi pixel, poche operazioni per pixel) e gira anche su dispositivi deboli |
| D14 | **[DECISIONE]** **Il budget di prestazioni è anche un budget energetico**: si misurano p95 e media, il frame rate è limitato al target, negli embed il default è `power="auto"` (eco fuori dallo schermo intero) | Ogni visione ricalcola tutto sulla GPU del visitatore: il costo va contenuto per batteria e calore |

---

## 3. Architettura

### 3.1 Pipeline di generazione (macchina di sviluppo)

```
prompt utente
     │
     ▼
┌──────────────┐   DemoSpec (JSON)     ┌──────────────┐
│ S0 BRIEF     │──────────────────────▶│ S1 STYLE     │── style.glsl + post.json + art_direction.md
└──────────────┘                       └──────────────┘
                                              │
              ┌───────────────────────────────┴──────────── per ogni scena (parallelo sulle chiamate LLM)
              ▼
┌──────────────┐  math_requests   ┌──────────────┐
│ S2 DRAFT     │─────────────────▶│ S3 MATH      │── oracolo LLM → verifica SymPy → codegen GLSL ES
│ (orchestr.)  │◀─────────────────│              │
└──────────────┘   snippet GLSL   └──────────────┘
       │
       ▼
┌──────────────┐  errori mappati  ┌──────────────┐
│ S4 COMPILE   │─────────────────▶│ FIXER (LLM)  │   glslang (ES) + compilazione reale in Chromium
└──────────────┘◀─────────────────└──────────────┘   max N tentativi
       │ ok
       ▼
┌──────────────┐   player headless (Playwright)
│ S5 PROBE     │── keyframe + burst, profilo prestazioni su tutta la scena,
└──────────────┘   tempo di compilazione, statistiche float, analisi flash
       │ gate ok
       ▼
┌──────────────┐   CriticReport
│ S6 CRITIQUE  │── contact sheet + burst + heatmap + metriche → vision LLM
└──────────────┘
       │ revise                       accept / budget esaurito
       ▼                                      │
┌──────────────┐                              │
│ S7 REVISE    │── torna a S4                 │
└──────────────┘                              ▼
                                   ┌──────────────────────┐
                                   │ S8 AUDIO (ciclo      │
                                   │ analogo, spettrogramma│
                                   │ al critico)          │
                                   └──────────────────────┘
                                              │
                                              ▼
                                   ┌──────────────────────┐
                                   │ S9 BUNDLE            │── tree-shaking, minify, .demo, .html,
                                   │                      │   probe demo intera (transizioni),
                                   │                      │   compat browser, poster, dimensioni
                                   └──────────────────────┘
                                              │ (opzionale)
                                              ▼
                                   ┌──────────────────────┐
                                   │ S10 EXPORT MP4       │── cattura offline + ffmpeg
                                   └──────────────────────┘
```

### 3.2 Esecuzione su un sito web (macchina del visitatore)

```
pagina HTML
 ├─ <script type="module" src="demogen-player.min.js">   ≈ 10 KB gz, in cache tra demo e pagine
 └─ <demogen-player src="neon-tunnel.demo">              ≈ 10–40 KB gz
        │
        ├─ fetch + validazione payload
        ├─ compilazione programmi (parallela se KHR_parallel_shader_compile)
        ├─ render audio su GPU: prebuffer dei primi secondi, poi il resto in background
        └─ ciclo rAF (limitato a target_fps):
                       t = clock audio
                       → uniform di sync dalla timeline
                       → draw scena (o due scene + blend durante una transizione)
                         alla risoluzione interna (fissa e nearest per il profilo retro)
                       → post (bloom opzionale + finalize)
                       → canvas
                       └─ controllore qualità: scala di risoluzione, uQuality, modalità eco
```

### 3.3 Ruoli LLM

| Ruolo | Capacità richieste | Uso |
|---|---|---|
| `orchestrator` | coding forte; vision consigliata | brief → spec, stile, bozza e revisione shader, richieste matematiche |
| `critic` | **vision obbligatoria** (fallback degradato senza) | valuta contact sheet, burst, spettrogramma + metriche |
| `math` | ragionamento matematico; solo testo va bene | derivazioni: SDF, bound di Lipschitz, curve periodiche, intersezioni |
| `fixer` | coding veloce ed economico | correzione errori di compilazione (inclusi errori specifici di un browser) |
| `composer` | coding; può coincidere con `orchestrator` | shader audio `mainSound` |

Tutti i ruoli possono puntare allo stesso modello. Nessun nome di modello è hardcoded: si sceglie in configurazione.

---

## 4. Struttura del repository

Monorepo: Python (`uv`) per orchestrazione e verifica, TypeScript (`npm` workspaces) per il player.

```
demogen/
├── pyproject.toml
├── package.json                  # workspace npm: player
├── README.md
├── CLAUDE.md
├── demogen.example.yaml
├── demogen/                      # Python
│   ├── __init__.py
│   ├── cli.py                    # typer: init, doctor, models, generate, resume, revise,
│   │                             #        play, bundle, inspect, calibrate, perf, report,
│   │                             #        export-mp4, export-shadertoy
│   ├── config.py                 # YAML + env, validazione pydantic
│   ├── llm/
│   │   ├── client.py             # wrapper SDK openai: retry, timeout, logging, usage
│   │   ├── providers.py          # preset openai_compatible / openrouter
│   │   ├── capabilities.py       # rilevamento vision / json_schema (auto o da config)
│   │   ├── envelope.py           # parsing risposta: blocco JSON + blocchi ```glsl
│   │   ├── structured.py         # strategia a livelli + loop di riparazione
│   │   ├── budget.py             # costo/token/tempo, stop anticipato
│   │   └── prompts/              # template Jinja2 per ruolo (*.md.j2)
│   ├── spec/
│   │   └── models.py             # DemoSpec, Timeline, ShaderSubmission, PerfProfile, ...
│   ├── orchestrator/
│   │   ├── pipeline.py           # macchina a stati, state.json, resume
│   │   ├── steps/                # brief, style, draft, math, compile, probe,
│   │   │                         # critique, revise, audio, bundle, export
│   │   └── selection.py          # versione migliore, anti-regressione, penalità perf
│   ├── glsl/
│   │   ├── lib/                  # libreria GLSL ES pre-testata (§7)
│   │   ├── docs.py               # /// doc-comment → riferimento API per i prompt
│   │   ├── preprocessor.py       # header ES, #include, #define, mappa righe
│   │   ├── treeshake.py          # grafo delle chiamate: solo funzioni raggiunte
│   │   ├── minify.py             # minificazione base; minificatore esterno opzionale
│   │   └── validator.py          # glslangValidator (profilo ES 300)
│   ├── browser/
│   │   ├── session.py            # Playwright: avvio, flag GPU/SwiftShader, riavvio su crash
│   │   ├── harness.py            # API Python verso window.__demogen
│   │   ├── serve.py              # file serviti con page.route, rete esterna bloccata
│   │   └── perf_lane.py          # lock globale: una sola misura di prestazioni alla volta
│   ├── bundle/
│   │   ├── format.py             # schema .demo (pydantic) + versione del formato
│   │   ├── build.py              # payload, HTML standalone, bootstrap 64k, poster
│   │   └── sizes.py              # raw / gzip / brotli
│   ├── math_oracle/
│   │   ├── oracle.py             # chiamata LLM ruolo math
│   │   ├── safe_parse.py         # parsing con whitelist, in subprocess
│   │   ├── verify.py             # verifiche simboliche + numeriche
│   │   └── codegen.py            # sympy → GLSL ES (letterali float, firma richiesta)
│   ├── critic/
│   │   ├── metrics_video.py
│   │   ├── metrics_audio.py
│   │   ├── metrics_perf.py       # profilo, percentili, hotspot
│   │   ├── flash.py              # analisi fotosensibilità
│   │   ├── gates.py              # soglie tecniche
│   │   ├── sheets.py             # contact sheet, burst strip, heatmap, spettrogramma, grafico perf
│   │   └── critic.py             # chiamata LLM ruolo critic
│   ├── export/
│   │   └── mp4.py                # opzionale: cattura offline + ffmpeg
│   └── project/
│       ├── store.py              # layout cartella progetto, versioni, artefatti
│       └── report.py             # report.md finale
├── player/                       # TypeScript, zero dipendenze runtime
│   ├── package.json
│   ├── src/
│   │   ├── index.ts              # export pubblici
│   │   ├── element.ts            # custom element <demogen-player>
│   │   ├── player.ts             # ciclo di vita: load → compile → audio → play
│   │   ├── gl.ts                 # contesto WebGL2, triangolo fullscreen, FBO, context loss
│   │   ├── programs.ts           # header + common + scena, compilazione parallela
│   │   ├── timeline.ts           # uniform di sync (semantica identica a demogen/spec)
│   │   ├── compositor.ts         # transizioni cut / crossfade / flash / fade_black
│   │   ├── post.ts               # catena post fissa: bloom opzionale + finalize
│   │   ├── audio.ts              # render GPU a blocchi, decodifica, WebAudio, clock
│   │   ├── quality.ts            # controllore adattivo
│   │   ├── format.ts             # parsing/validazione minima del payload
│   │   ├── bench.ts              # modulo separato, caricato solo con ?bench
│   │   └── harness.ts            # SOLO build di test: cattura, profiling, statistiche float
│   ├── test/                     # vitest
│   ├── harness.html
│   └── dist/                     # demogen-player.min.js, demogen-bench.min.js, demogen-harness.js
├── shared/
│   └── vectors/                  # vettori di test timeline/uniform usati da pytest e vitest
├── tests/
│   ├── fixtures/                 # shader di riferimento, risposte LLM registrate
│   └── ...
└── examples/
    ├── prompts/                  # prompt di esempio per smoke test
    └── embed/                    # pagina con più demo embeddate
```

---

## 5. Contratti

### 5.1 Shader video (scena)

L'LLM scrive **solo** il corpo; il player aggiunge header, uniform, libreria e `main()`. Lo stesso assemblaggio avviene in Python (preprocessore) per validazione e mappa righe.

```glsl
// Fornito dal player (non scritto dall'LLM):
//   #version 300 es
//   precision highp float;
//   precision highp int;
//   uniform vec3  iResolution;     // (w, h, 1) della risoluzione interna corrente
//   uniform float iTime;           // secondi dall'inizio della demo
//   uniform float uSceneTime;      // secondi dall'inizio della scena
//   uniform float uSceneProgress;  // 0..1 nella scena
//   uniform float uBeat;           // battiti (float) dall'inizio della demo
//   uniform float uBeatPhase;      // fract(uBeat)
//   uniform float uBar;            // battute (float)
//   uniform float uQuality;        // 0 = minima, 1 = piena (continua)
//   uniform float uFlashLimit;     // 1 = normale, < 1 con reduce-flashes
//   uniform vec2  uJitter;         // 0 in realtime; usato solo dall'export offline
//   uniform highp int uText[64];   // solo se il payload ha "text": 4 caratteri ASCII per intero
//   uniform int   uTextLen;
//   #define BPM <dal DemoSpec>
//   #define PROFILE_RETRO          // solo per le scene con profilo retro
//   <common: libreria (solo funzioni raggiunte) + style.glsl>
//   out vec4 demogen_FragColor;
//   void main() { mainImage(demogen_FragColor, gl_FragCoord.xy); }

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    // scritto dall'LLM
}
```

Regole imposte nel prompt e verificate dove possibile (tokenizzazione del sorgente, compilazione):
- Non disponibili: `iMouse`, `iDate`, `iChannel*`, `iFrame`, `iTimeDelta`, texture di qualunque tipo.
- **Letterali float sempre con punto decimale** (`1.0`, non `1`): GLSL ES non fa conversioni implicite int → float.
- Hash solo dalla libreria (interi, niente `fract(sin(...))`).
- Ogni ciclo ha un limite costante (`MAX_STEPS`) e un'uscita anticipata legata alla qualità:
  `int n = qSteps(MAX_STEPS); for (int i = 0; i < MAX_STEPS; i++) { if (i >= n) break; ... }`.
- Niente cicli annidati profondi né array locali grandi: gonfiano il tempo di compilazione su alcuni backend (ANGLE → D3D su Windows).
- Anti-aliasing analitico dove serve (helper `aa.glsl` basati su `fwidth`).
- Lampi e strobo solo tramite gli helper della libreria che rispettano `uFlashLimit`.
- Output in spazio display (sRGB) tramite `finalize()` di `style.glsl`.
- Il tempo che entra nelle funzioni periodiche va "avvolto" (helper `time.glsl`) per evitare perdita di precisione fp32.
- **Profilo retro**: `iResolution` è la risoluzione interna fissa (es. 320×180) e `fragCoord` è in pixel di quella risoluzione; colore finale tramite `retroFinalize()` (quantizzazione in palette + dithering); niente raymarching pesante (§14).

### 5.2 Shader audio

```glsl
// Fornito dal player: #version 300 es, precisioni, #define BPM, SAMPLE_RATE, DURATION, lib/audio/*
vec2 mainSound(int samp, float time) {
    // scritto dall'LLM; ritorna (L, R) in [-1, 1]
}
```

Rendering nel player:
- Texture larga 4096 px; il pixel `(x, y)` calcola il campione `i = y*4096 + x`, `time = i / SAMPLE_RATE`.
- **Percorso universale RGBA8**: L e R codificati a 16 bit ciascuno (byte alto/basso), come fa Shadertoy; nessuna estensione richiesta. **[VERIFICARE]** dithering e precisione della codifica.
- **Percorso float** (`RG32F`, richiede `EXT_color_buffer_float`): usato dall'harness per misurare clipping, DC e NaN prima della quantizzazione.
- Render **a blocchi** (es. 4096×32 righe per draw) per non bloccare la scheda né il watchdog GPU; evento `progress`.
- **Audio progressivo**: prima della partenza si calcolano solo i primi `prebuffer_s` secondi (campo `audio_opts` del payload, copiato da `audio.prebuffer_s` della configurazione); il resto si calcola in background a fette di tempo per frame (≤ 2 ms per frame) e si accoda in chunk da `chunk_s` secondi programmati sul clock di `AudioContext`, con almeno due chunk di anticipo sul punto di riproduzione. Un seek oltre la parte calcolata provoca il render sincrono del chunk necessario.
- Sample rate fisso 48 kHz; il browser ricampiona verso la frequenza del dispositivo.
- Durata massima v1: 120 s (≈ 5,8 M campioni; `AudioBuffer` stereo float32 ≈ 46 MB).

Effetti con memoria (delay, eco, riverbero) si ottengono ricalcolando la funzione a tempi passati, `sum_k g^k * f(t - k*d)`; la libreria fornisce helper con un numero di tap limitato.

### 5.3 Formato `.demo`

JSON UTF-8. Sul web viene servito compresso dal server (gzip/brotli) oppure inserito inline nella pagina.

```json
{
  "format": "demogen/1",
  "player_min": "1.0.0",
  "meta": { "title": "Neon Tunnel", "duration_s": 60.0, "loop": false,
            "bpm": 128.0, "beats_per_bar": 4 },
  "timeline": [
    { "id": "s1", "start_bar": 0, "bars": 8, "transition_in": "cut", "transition_bars": 0 },
    { "id": "s2", "start_bar": 8, "bars": 8, "transition_in": "crossfade", "transition_bars": 1 }
  ],
  "common": "/* libreria (solo funzioni raggiunte) + style.glsl, minificati */",
  "scenes": { "s1": "void mainImage(out vec4 c, in vec2 p){...}", "s2": "..." },
  "render": { "profile": "modern", "overrides": { "s3": "retro" },
              "retro": { "internal_resolution": [320, 180], "upscale": "nearest" } },
  "text": "GREETINGS TO EVERYONE STILL WRITING CODE FOR FUN",
  "post": { "bloom": { "threshold": 0.8, "intensity": 0.6, "radius": 4 } },
  "audio": "vec2 mainSound(int samp, float time){...}",
  "audio_opts": { "prebuffer_s": 8, "chunk_s": 4 },
  "quality": { "min_scale": 0.5, "target_fps": 60 },
  "poster": "poster.webp"
}
```

Regole:
- Nessun campo viene interpretato come codice tranne le stringhe GLSL, che vanno solo al compilatore shader.
- Validazione completa in Python (pydantic); validazione minima nel player (tipi, campi obbligatori, limiti di dimensione).
- Campi sconosciuti ignorati; `format` con major diverso → errore esplicito.
- Ogni programma = header + `common` + scena; `common` compare una sola volta nel payload.

### 5.4 API del player (embed)

```html
<script type="module" src="/js/demogen-player.min.js"></script>

<demogen-player src="/demos/neon-tunnel.demo"
                autoplay="visual"
                quality="auto"
                power="auto"
                loop controls reduce-flashes>
</demogen-player>
```

- `autoplay`: `none` | `visual` (parte senza audio quando è visibile, audio al primo gesto dell'utente, per via delle politiche di autoplay) | `full` (solo dove consentito).
- `quality`: `auto` | `low` | `medium` | `high`.
- `power`: `auto` (default: eco fuori dallo schermo intero, piena qualità in schermo intero) | `eco` | `full` (§13.3).
- Payload inline in alternativa a `src`: `<demogen-player><script type="application/json">{…}</script></demogen-player>`.
- API JS: `play()`, `pause()`, `seek(t)`, `currentTime`, `duration`; eventi `ready`, `progress` (compilazione/audio), `qualitychange`, `error`, `ended`.
- Pausa automatica fuori viewport (`IntersectionObserver`) e a scheda nascosta.
- `prefers-reduced-motion`: nessun autoplay, `reduce-flashes` attivo.
- Fallback al poster (ed eventuale link a un MP4) se: WebGL2 assente, renderer software rilevato (es. SwiftShader), contesto perso ripetutamente, frame rate insufficiente anche alla qualità minima.
- I browser limitano il numero di contesti WebGL attivi per pagina **[VERIFICARE limite attuale]**: il player rilascia il contesto quando esce dal viewport e lo ricrea al rientro.

### 5.5 Harness (solo pipeline e test)

`demogen-harness.js` è una build separata, mai distribuita. Espone `window.__demogen`:

| Metodo | Risultato |
|---|---|
| `load(payload)` | `{ok, errors: [{program, line, msg}], compile_ms: {per programma}}` |
| `capture({times, width, height, spp?})` | PNG (base64) per tempo + statistiche float (NaN, Inf, istogramma luma) calcolate su FBO `RGBA32F` |
| `lumaSequence({t0, t1, fps, width, height})` | luminanza media per cella di una griglia, per ogni frame (analisi flash) |
| `profile({times, width, height, quality, repeats})` | ms per tempo; GPU time con `EXT_disjoint_timer_query_webgl2` se esposta, altrimenti fence + `performance.now()` |
| `renderAudio({float: true})` | campioni Float32 (base64) + tempo di render |
| `info()` | renderer (anche "unmasked" se disponibile), estensioni, limiti |

La cattura e il profiling avvengono **fuori da rAF** (niente cap di vsync), a tempi esatti, quindi in modo deterministico. **[VERIFICARE]** throughput del trasferimento di frame tra pagina e Python; in alternativa `expose_binding` o WebSocket su loopback.

### 5.6 Envelope di risposta LLM [D8]

Ogni risposta che contiene codice ha questa forma:

````
```json
{ "scene_id": "s2", "notes": "...", "math_requests": [], "perf_tier": "medium" }
```

```glsl
void mainImage(out vec4 fragColor, in vec2 fragCoord) { ... }
```
````

`envelope.py` estrae il primo blocco `json` e i blocchi `glsl`, valida il JSON con pydantic e, in caso di errore, avvia il loop di riparazione (§8.4).

---

## 6. Player web

### 6.1 Budget di dimensione
- `demogen-player.min.js` (core: elemento, contesto, programmi, timeline, compositor, post, audio, qualità, formato) **≤ 12 KB min+gzip**, controllato in CI (metafile di esbuild + gzip).
- `bench` e `harness` sono moduli separati e non pesano sul core.
- Nessuna dipendenza runtime, nessun framework.

### 6.2 Ciclo di vita
1. `fetch` del payload (o lettura inline) → validazione minima.
2. Contesto WebGL2 con `antialias: false`, `alpha: false`, `powerPreference: "high-performance"`, `preserveDrawingBuffer: false`.
3. Rilevamento renderer software → fallback poster (le prestazioni sarebbero inaccettabili).
4. Compilazione di tutti i programmi in parallelo (`KHR_parallel_shader_compile` se disponibile, polling dello stato di completamento) mentre si mostra un indicatore minimale.
5. Render del prebuffer audio (`prebuffer_s` secondi) → primo chunk pronto.
6. `ready` → riproduzione secondo `autoplay`; il resto dell'audio prosegue in background (§5.2).

Il tempo dal payload in memoria al primo frame è misurato dalla pipeline e soggetto a gate (`realtime.max_first_frame_ms`).

### 6.3 Ciclo di frame
- `t` = clock audio quando l'audio suona (`AudioContext.currentTime` meno l'istante di avvio, compensando `outputLatency` dove disponibile **[VERIFICARE supporto per browser]**), altrimenti `performance.now()`.
- Scena attiva e progress dalla timeline (`timeline.ts`, semantica identica alla Python, verificata da `shared/vectors/`).
- Draw della scena in un FBO alla scala corrente → post → blit sul canvas. A scala 1 senza bloom si renderizza direttamente sul canvas.
- Transizioni: `crossfade` e `flash` renderizzano **entrambe** le scene in due FBO e le fondono (costo doppio per la durata della transizione, misurato dal gate); `fade_black` e `cut` costano una scena.
- Profilo retro: la scena si renderizza alla risoluzione interna fissa e si ingrandisce con filtro nearest, a multipli interi quando possibile (§14.2).
- **Frame pacing**: al massimo `target_fps` frame al secondo; sugli schermi a 120 Hz i callback rAF in eccesso vengono saltati in base al tempo trascorso.

### 6.4 Post-processing fisso
- `finalize()` di `style.glsl` (tonemap, gamma, vignetta, grana deterministica da `iTime`) dentro lo shader di scena.
- Bloom opzionale nel player (downsample/upsample a pochi livelli), parametri in `post` del payload. È codice del player, non dell'LLM; si disattiva automaticamente ai livelli di qualità più bassi.

### 6.5 Controllore di qualità
- Media mobile esponenziale del tempo di frame su ~30 frame; budget = `1000 / target_fps`.
- Discesa: scala 1.0 → 0.85 → 0.7 → `min_scale`, poi `uQuality` 1 → 0.5 → 0, poi bloom off.
- Risalita con isteresi dopo alcuni secondi stabili; nessun cambio nel primo secondo.
- `quality` diverso da `auto` blocca il livello.
- Modalità eco (`power="eco"`, o `auto` fuori dallo schermo intero): `target_fps` 30, scala massima 0.75, bloom e CRT spenti; il controllore lavora dentro questi limiti.
- Se anche il livello minimo non regge → evento `qualitychange` con `insufficient: true` e fallback configurabile (poster o continua a frame rate ridotto).

### 6.6 Robustezza
- `webglcontextlost` → stop, attesa del ripristino, ricompilazione; due perdite in 30 s → fallback poster con messaggio.
- Errori di compilazione → evento `error` con log + poster.
- Limiti: payload ≤ 1 MB, sorgente per programma ≤ 256 KB.

### 6.7 Accessibilità e fotosensibilità
- La pipeline garantisce un **gate flash** sulla demo intera (§12.4).
- `reduce-flashes`: `uFlashLimit` ridotto (gli helper di lampo della libreria scalano l'ampiezza) e transizioni `flash` sostituite da `crossfade`.
- Controlli opzionali (`controls`): play/pausa, audio, schermo intero. Tastiera accessibile.

### 6.8 HTML standalone
- Player minificato inline + payload inline; avvio al click (sblocca anche l'audio), schermo intero opzionale.
- Nessuna richiesta di rete; funziona da `file://`.
- Classe 64k: bootstrap minimo inline + payload compresso decompresso con `DecompressionStream` **[VERIFICARE overhead della codifica e alternative più compatte]**.

---

## 7. Libreria GLSL (ES 3.00)

Scritta a mano (o generata e poi **testata**), documentata con doc-comment `///` da cui `docs.py` produce un riferimento API in markdown iniettato nei prompt. Nel bundle entra solo ciò che la demo usa (tree-shaking, §15).

| File | Contenuto |
|---|---|
| `hash.glsl` | hash interi (PCG 2D/3D/4D), conversione a float [0,1) |
| `noise.glsl` | value noise, gradient noise, simplex 2D/3D, `fbm`, `ridged`, domain warp; varianti con numero di ottave scalato da `uQuality` |
| `sdf.glsl` | primitive (sfera, box, round box, toro, capsula, cilindro, ottaedro, piano); operatori booleani; `smin`/`smax` polinomiali; **fattore di Lipschitz documentato** per ciascuna |
| `domain.glsl` | ripetizione infinita e limitata, specchio, ripetizione polare, twist, bend (con nota: non 1-Lipschitz, richiedono scala del passo) |
| `raymarch.glsl` | marcia con `stepScale` e `qSteps`, normale (tecnica del tetraedro), soft shadow e AO con costo scalato da `uQuality`, bounding volume (sfera/box) per uscita anticipata |
| `camera.glsl` | matrice lookAt, orbit, ray da `fragCoord` (con `uJitter`, usato solo dall'export offline) |
| `palette.glsl` | palette coseno `a + b*cos(2π(c*t + d))` + preset |
| `easing.glsl` | easing standard, `beatPulse(phase, k) = exp(-k*phase)`, `beatFlash` (rispetta `uFlashLimit`), helper per loop periodici |
| `aa.glsl` | `smoothstep` filtrati con `fwidth`, pattern filtrati (linee, griglie, scacchiera) |
| `quality.glsl` | `qSteps`, `qOctaves`, `qEnable` (attiva una feature solo sopra una soglia di qualità) |
| `post.glsl` | tonemap (approssimazione ACES, Reinhard), gamma, vignetta, grana deterministica da `iTime`, aberrazione cromatica |
| `time.glsl` | avvolgimento del tempo per frequenze date, helper loop di periodo T |
| `retro/pixel.glsl` | coordinate pixel-perfect alla risoluzione interna, scanline/CRT leggero |
| `retro/palette.glsl` | palette fisse definite nello stile (fino a 32 colori), colore più vicino, dithering ordinato Bayer 4×4/8×8, `retroFinalize()` |
| `retro/effects.glsl` | plasma, tunnel polare, rotozoom, raster/copper bar, starfield 2D/3D, fuoco, twister, sine scroller |
| `retro/font.glsl` | font bitmap 8×8 **originale** (96 caratteri ASCII) in costanti `uvec2`; lettura del testo da `uText` |
| `audio/osc.glsl` | sinusoide, saw/square con anti-aliasing approssimato, noise da hash |
| `audio/env.glsl` | ADSR, decadimenti, sidechain sul beat |
| `audio/drums.glsl` | kick, snare, hi-hat sintetici |
| `audio/music.glsl` | nota → frequenza, scale, sequencer a pattern, helper eco multi-tap |
| `audio/chip.glsl` | chiptune: impulso con duty cycle variabile, triangolo a gradini, noise tipo LFSR, arpeggi rapidi, vibrato |

Convenzioni:
- Ogni funzione è preceduta da `/// @fn <nome>` e dalla documentazione; nessuna variabile globale mutabile; le dipendenze si deducono dagli identificatori usati (serve al tree-shaking).
- Font e palette disegnati da zero, non copiati da ROM o materiali di sistemi storici, per evitare problemi di licenza.
- Ogni funzione ha almeno un test: golden render tollerante oppure test numerico eseguito su GPU (uno shader di test scrive i valori in un FBO float letto dall'harness).
- Compatibilità con ANGLE su D3D (Windows): niente cicli annidati con limiti grandi, niente indicizzazione dinamica di array grandi.

---

## 8. Livello LLM

### 8.1 Configurazione (`demogen.yaml`)

```yaml
providers:
  openrouter:
    type: openrouter                     # preset: base_url https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    headers:                             # opzionali, attribuzione app
      HTTP-Referer: https://example.local/demogen
      X-Title: demogen
  local:
    type: openai_compatible
    base_url: http://localhost:8000/v1
    api_key_env: LOCAL_API_KEY           # può essere un valore fittizio

roles:
  orchestrator:
    provider: openrouter
    model: "<id-modello>"
    temperature: 0.7
    max_tokens: 16000
    vision: auto                         # auto | true | false
    json_schema: auto                    # auto | true | false
    timeout_s: 600
    extra_body: {}                       # pass-through (es. parametri di reasoning)
  critic:   { provider: openrouter, model: "<id-modello-vision>", temperature: 0.2, vision: true }
  math:     { provider: openrouter, model: "<id-modello-math>",   temperature: 0.1 }
  fixer:    { provider: local,      model: "<id-modello-veloce>", temperature: 0.0 }
  composer: { inherit: orchestrator }

pricing:                                 # usato solo se il provider non restituisce il costo
  "<id-modello>": { prompt_per_mtok: 0.0, completion_per_mtok: 0.0 }

budget:
  max_iterations_per_scene: 4
  max_fix_attempts: 3
  max_total_cost_usd: 5.0
  max_wall_minutes: 60
  llm_concurrency: 4

browser:
  engine: chromium                       # motore per probe e misure
  compat_engines: [chromium, webkit, firefox]
  headless: true
  gpu: auto                              # auto | hardware | swiftshader
  perf_headed: false                     # finestra visibile per le misure, se l'headless non usa la GPU
  capture_pages: 2                       # pagine in parallelo per le catture (le misure perf sono serializzate)
  swiftshader_flags: ["--use-gl=angle", "--use-angle=swiftshader-webgl", "--enable-unsafe-swiftshader"]

realtime:
  target_fps: 60
  floor_ratio: 0.4                       # p95 a qualità minima ≤ floor_ratio × budget_ms_p95
  max_compile_ms_scene: 400
  max_compile_ms_total: 1500
  max_first_frame_ms: 1500               # payload in memoria → primo frame (compilazione + prebuffer audio)
  profile_step_s: 0.25                   # passo di campionamento della timeline per il profilo perf

profiles:
  modern:
    reference_resolution: [1920, 1080]   # risoluzione su cui si misura il budget
    budget_ms_p95: 6.0                   # misurato sulla macchina di sviluppo
    budget_ms_mean: 4.0                  # carico medio → stima del consumo
  retro:
    internal_resolution: [320, 180]      # risoluzione fissa di rendering
    upscale: nearest                     # a multipli interi quando possibile
    palette_size: 16
    dither: bayer4                       # none | bayer4 | bayer8
    budget_ms_p95: 1.0
    budget_ms_mean: 0.5

power:
  default_embed: auto                    # auto = eco fuori dallo schermo intero, full in schermo intero
  eco: { target_fps: 30, max_scale: 0.75, bloom: false, crt: false }

preview: { width: 480, height: 270, keyframes: 16, bursts: 3, burst_len: 6, fps: 60 }

bundle:
  size_class: standard                   # standard | 64k (Fase 7) | 8k | 4k (Fase 8)
  max_payload_gz_kb: 48
  minify: basic                          # basic | aggressive (minificatore esterno)
  poster: { width: 1280, height: 720, format: webp }

audio:
  sample_rate: 48000
  headroom_dbfs: -1.0
  prebuffer_s: 8                         # secondi calcolati prima di partire
  chunk_s: 4                             # il resto, a blocchi, in background
  max_render_ms_prebuffer: 800

safety:
  flash_max_per_s: 3
  red_flash: true

export_mp4:                              # opzionale (Fase 7)
  width: 1920
  height: 1080
  fps: 60
  supersample: 4
  motion_blur_samples: 4
  shutter: 0.5
  encoder: { codec: libx264, crf: 18, preset: slow, pix_fmt: yuv420p }
```

Le chiavi API arrivano **solo** da variabili d'ambiente e non vengono mai scritte nei log.

### 8.2 Provider

- `openai_compatible`: `OpenAI(base_url=..., api_key=...)` dall'SDK ufficiale; chat completions standard.
- `openrouter`: stesso client con `base_url="https://openrouter.ai/api/v1"` e header opzionali di attribuzione. OpenRouter restituisce nell'oggetto `usage` anche il **costo** della richiesta; va letto se presente. **[VERIFICARE]** come l'SDK `openai` espone campi extra di `usage` (accesso via `model_extra` o JSON grezzo).
- Immagini: content part `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`.
- Prompt caching: contratto shader e riferimento API della libreria vanno in un **prefisso stabile** del prompt, così i provider che lo supportano lo mettono in cache.

### 8.3 Rilevamento capacità

- `vision: auto` / `json_schema: auto` su OpenRouter: interrogare `GET /api/v1/models` e leggere dal record del modello modalità di input e parametri supportati. **[VERIFICARE]** i nomi esatti dei campi sulla risposta reale; cache su disco per 24 h.
- `auto` su `openai_compatible` generico: non rilevabile in modo affidabile → default prudente (`vision: false`, `json_schema: false`) con avviso; l'utente imposta i flag.
- `demogen models check`: per ogni ruolo fa una chiamata minima (testo; immagine 64×64 se vision; schema JSON banale se json_schema) e stampa una tabella con esito, latenza, costo.

### 8.4 Output strutturato (a livelli)

1. `response_format: {type: json_schema, strict: true}` se supportato.
2. `response_format: {type: json_object}` se supportato.
3. Schema descritto nel prompt + estrazione dell'envelope.

In ogni caso: validazione pydantic. Se fallisce, si rimanda al modello l'errore di validazione con l'output precedente (max 2 riparazioni), poi lo step fallisce con errore esplicito.

### 8.5 Client

- Retry con backoff esponenziale e jitter su 429/5xx/timeout (max 4).
- Log di ogni chiamata in `project/llm_calls/NNNN_<ruolo>_<step>.json`: messaggi (immagini sostituite da riferimenti a file), risposta grezza, usage, costo, latenza, modello effettivamente servito.
- `budget.py`: prima di ogni chiamata stima il costo massimo (`max_tokens` × prezzo); se sforerebbe il budget, lo step termina con la migliore versione disponibile.
- Chiamate per scene diverse in parallelo con `asyncio` (`AsyncOpenAI`), concorrenza `budget.llm_concurrency`. Le catture nel browser usano un pool di `browser.capture_pages` pagine; le **misure di prestazioni passano da un lock unico** (`perf_lane.py`), perché più carichi GPU contemporanei falserebbero i tempi.

---

## 9. Dati (pydantic)

```python
RenderProfile = Literal["modern", "retro"]
PerfTier = Literal["light", "medium", "heavy"]

class Timeline(BaseModel):
    bpm: float
    beats_per_bar: int = 4
    scenes: list["SceneSlot"]          # ordinate, contigue

class SceneSlot(BaseModel):
    id: str                            # "s1", "s2", ...
    start_bar: float
    bars: float
    transition_in: Literal["cut", "crossfade", "flash", "fade_black"] = "cut"
    transition_bars: float = 0.0

class SceneBrief(BaseModel):
    id: str
    title: str
    description: str                   # cosa si vede
    motion: str                        # come si muove, legame col beat
    techniques: list[str]              # es. ["raymarch", "domain_repeat", "fbm"] o ["plasma", "scroller"]
    camera: str
    profile: RenderProfile | None = None   # override del profilo della demo
    perf_tier: PerfTier = "medium"

class DemoSpec(BaseModel):
    title: str
    prompt: str
    duration_s: float                  # derivata dalla timeline, verificata
    loop: bool = False
    profile: RenderProfile = "modern"
    timeline: Timeline
    scenes: list[SceneBrief]
    art_direction: str
    palette_hint: list[str]            # colori esadecimali
    audio_brief: str
    text: str | None = None            # testo per scroller (retro), max 256 caratteri ASCII stampabili
    avoid: list[str] = []              # cliché da evitare

class MathRequest(BaseModel):
    id: str
    kind: Literal["sdf", "lipschitz", "intersection", "periodic_path",
                  "easing", "parametric_curve", "attractor_params", "fourier", "other"]
    description: str
    inputs: dict[str, str]             # variabili e tipi GLSL attesi
    output_signature: str              # es. "float sdTwistedGyroid(vec3 p, float k)"

class ShaderSubmission(BaseModel):     # metadati dell'envelope; il GLSL a parte
    scene_id: str
    notes: str
    math_requests: list[MathRequest] = []
    perf_tier: PerfTier = "medium"
    quality_knobs: list[str] = []      # cosa scala con uQuality (es. "MAX_STEPS", "ottave fbm")

class Claim(BaseModel):
    type: Literal["identity", "periodic", "lipschitz_bound", "eikonal", "range", "sign"]
    expr: str
    params: dict[str, str] = {}

class MathResult(BaseModel):
    request_id: str
    variables: list[str]
    assumptions: list[str]
    expressions: dict[str, str]        # sintassi SymPy
    claims: list[Claim]
    derivation: str
    verified: bool = False             # impostato dal verificatore, non dal modello
    checks: list[dict] = []
    glsl: str | None = None            # generato da codegen dopo la verifica

class Issue(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    source: Literal["gate", "critic", "user"]
    at_s: float | None
    description: str
    suggested_fix: str

class CriticReport(BaseModel):
    scores: dict[str, int]             # 1..10: brief, composition, color, motion, technical, originality
    issues: list[Issue]
    verdict: Literal["accept", "revise"]
    summary: str

class PerfSample(BaseModel):
    t: float
    ms: float

class PerfProfile(BaseModel):
    scene_id: str                      # "demo" per il profilo della demo intera
    profile: RenderProfile
    resolution: tuple[int, int]
    method: Literal["timer_query", "fence"]
    gpu: str
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float
    floor_p95_ms: float                # min_scale + uQuality 0
    gpu_load_est: float                # mean_ms / (1000 / target_fps)
    gpu_load_eco_est: float            # stessa stima in modalità eco
    hotspots: list[PerfSample]         # istanti peggiori

class StartupProfile(BaseModel):
    compile_ms: dict[str, float]
    compile_total_ms: float
    audio_prebuffer_ms: float
    first_frame_ms: float

class FlashReport(BaseModel):
    max_flashes_per_s: float
    red_flash_events: int
    windows: list[tuple[float, float]] # intervalli oltre soglia

class BundleReport(BaseModel):
    payload: dict[str, int]            # raw, gzip, brotli
    html: dict[str, int]
    player_core_gz: int
    compat: dict[str, Literal["ok", "fail", "skipped"]]
    minify_check: bool                 # render minificato ≈ non minificato
```

---

## 10. Pipeline (dettaglio degli step)

Ogni step legge e scrive artefatti nella cartella progetto e aggiorna `state.json`; un'interruzione si riprende con `demogen resume`.

| Step | Input | Output | Note |
|---|---|---|---|
| S0 BRIEF | prompt + flag CLI | `spec.json` | i flag CLI (durata, BPM, loop, profilo) prevalgono sul modello; il modello sceglie il profilo se il prompt lo suggerisce ("stile Amiga" → `retro`); validazione di coerenza (durata = battute × battiti per battuta × 60 / BPM); durata ≤ 120 s; con `--interactive` mostra lo spec e chiede conferma |
| S1 STYLE | spec | `style.glsl`, `post.json`, `art_direction.md` | costanti di palette, parametri di post, `finalize(col, uv)` (modern) o `retroFinalize` con palette e dithering (retro); compilato e provato su una scena di test |
| S2 DRAFT | spec, brief scena, stile, API libreria | `scenes/<id>/vN.glsl` + `vN.meta.json` | prompt con tecniche del profilo, budget di prestazioni, convenzioni `uQuality`, regole GLSL ES, lista anti-cliché |
| S3 MATH | `math_requests` | `math/<req>.json` | oracolo → verifica → codegen; gli snippet verificati vanno in `scenes/<id>/math.glsl`, poi S2 riceve un turno di revisione; i risultati non verificati vengono scartati con motivazione (o accettati con avviso se `math.allow_unverified: true`) |
| S4 COMPILE | shader | esito | 1) `glslangValidator` con header ES 300 (veloce); 2) compilazione reale in Chromium via harness; errori rimappati alle righe del sorgente LLM; FIXER con le righe incriminate ± 5 di contesto; max `max_fix_attempts` |
| S5 PROBE | shader compilato | `vN.probe/` | catture: 16 keyframe + 3 burst da 6 frame a 60 fps nei momenti di massimo `uBeatPhase`, a risoluzione preview; statistiche float; nel perf lane: tempo di compilazione, profilo su tutta la scena ogni `profile_step_s` a qualità piena e al pavimento; sequenza di luminanza per il gate flash; gate (§12.5) |
| S6 CRITIQUE | contact sheet, burst strip, heatmap differenze, metriche, brief | `vN.critique.json` | se il ruolo critic non ha vision: critica degradata solo sulle metriche, con avviso nel report |
| S7 REVISE | shader, critica, issue dei gate, storico sintetico | `vN+1.glsl` | il modello vede le issue ordinate per gravità, gli hotspot di prestazioni (istanti e ms), i punteggi delle versioni precedenti |
| — selezione | storico versioni | `best.json` | punteggio = media pesata dei punteggi del critico, penalità per gate falliti e per carico medio vicino al budget; se una revisione peggiora di > 1 punto si riparte dalla migliore (anti-regressione) |
| S8 AUDIO | spec, timeline | `audio/vN.glsl`, `audio.wav`, `spectrogram.png` | compile → render float nell'harness → metriche (incluso tempo di prebuffer) → critica (spettrogramma con griglia di battute al critico vision) → revisione |
| S9 BUNDLE | best di ogni scena + audio | `out/<nome>.demo`, `out/<nome>.html`, `out/poster.webp`, `out/sizes.json`, `report.md` | tree-shaking → minify → payload; probe della **demo intera** (transizioni incluse, profilo perf, avvio, flash, `loop_seam`); confronto render minificato/non minificato; compilazione nei `compat_engines`; HTML standalone; poster (keyframe con punteggio migliore); dimensioni |
| S10 EXPORT MP4 | bundle | `out/<nome>.mp4` | opzionale (`demogen export-mp4`): cattura offline a tempi esatti con supersampling (`uJitter`) e motion blur, pipe rawvideo a ffmpeg, mux dell'audio |

### Comandi
- `demogen generate "<prompt>" [--profile modern|retro] [--duration 60] [--bpm 128] [--loop] [--interactive]`
- `demogen resume <progetto>`
- `demogen revise <progetto> --scene s2 --note "meno nebbia, più contrasto sul kick"`: nuova versione della scena con la nota come issue di massima priorità, ripete S4–S7 per un massimo di iterazioni configurabile, poi ri-esegue S9.
- `demogen revise <progetto> --audio --note "..."`: analogo per l'audio.
- `demogen play <shader.glsl|progetto|file.demo> [--profile retro] [--bench]`: server locale su `127.0.0.1` con hot reload; `--bench` stampa il profilo di prestazioni.
- `demogen perf import <progetto> <bench.json>`: registra il bench di un dispositivo reale (§13.6).
- `demogen bundle`, `demogen inspect`, `demogen calibrate`, `demogen export-mp4`, `demogen export-shadertoy`, `demogen report`, `demogen doctor`, `demogen models check`, `demogen init`.

---

## 11. Oracolo matematico

### 11.1 Flusso
1. L'orchestratore emette `MathRequest` quando serve una formula non banale (SDF di una forma insolita, deformazione con bound di Lipschitz, traiettoria camera chiusa, parametri di un attrattore che resti in regione visibile).
2. Il ruolo `math` risponde con `MathResult` in sintassi SymPy, dichiarando **claim verificabili**.
3. `verify.py` controlla i claim; `verified` è deciso **solo** dal verificatore.
4. `codegen.py` traduce con `sympy.printing.glsl.glsl_code`, incapsula nella firma richiesta e **normalizza per GLSL ES**: letterali numerici sempre float (`pow(x, 2)` → `pow(x, 2.0)`), nessuna conversione implicita, solo funzioni disponibili in ES 3.00.

Un bound di Lipschitz corretto ha anche un effetto sulle prestazioni: permette il passo di raymarching più lungo possibile senza artefatti.

### 11.2 Verifiche
| Claim | Verifica simbolica | Verifica numerica |
|---|---|---|
| `identity` (a = b) | `simplify(a - b) == 0` | 10.000 punti casuali nel dominio, errore massimo < 1e-6 relativo |
| `periodic` (periodo T) | `simplify(f(t+T) - f(t)) == 0` | campionamento su [0, 3T] |
| `lipschitz_bound` (L) | — | stima di sup ‖∇f‖ su campioni casuali + ottimizzazione locale dai punti peggiori; deve risultare ≤ L |
| `eikonal` (SDF esatta) | — | ‖∇d‖ ≈ 1 entro tolleranza su campioni lontani dalle singolarità |
| `sign` | — | segno corretto su punti interni/esterni forniti dal modello e su punti di controllo generati |
| `range` | — | valori entro l'intervallo dichiarato su campioni |

### 11.3 Sicurezza del parsing
- Le espressioni sono **testo non fidato**. Prima di qualunque parsing: tokenizzazione con whitelist (numeri, operatori aritmetici, parentesi tonde, virgole, nomi di variabili dichiarate, funzioni ammesse: `sin cos tan exp log sqrt abs Max Min atan2 floor pi`…); rifiuto di underscore doppi, apici, punti seguiti da identificatori, parentesi quadre/graffe.
- Parsing e valutazione in un **subprocess** con timeout (5 s) e limite di memoria. Su macOS `RLIMIT_AS`/`RLIMIT_DATA` non sono affidabili: il limite si applica con un watchdog sulla RSS (`psutil`) che uccide il processo.
- `lambdify` solo su espressioni già parsate e validate, nello stesso subprocess.

---

## 12. Critico e metriche

### 12.1 Metriche video (`metrics.json`)
- `nan_ratio`, `inf_ratio` (dall'FBO float prima della quantizzazione).
- `black_ratio` (luma < 0,02), `white_ratio` (luma > 0,98).
- `luma_mean`, `luma_std`, entropia dell'istogramma.
- `colorfulness` (metrica di Hasler–Süsstrunk).
- Temporali (sui burst): differenza assoluta media tra frame consecutivi; picchi (z-score > 4) per individuare flicker o tagli involontari.
- `loop_seam` (se `loop: true`): differenza tra frame iniziale e frame a t = durata.
- Solo retro con palette imposta: frazione di pixel che cadono nella palette.

### 12.2 Metriche audio
- Picco, RMS (dBFS), rapporto di clipping, offset DC, rapporto di silenzio (dal percorso float).
- Centroide spettrale nel tempo.
- Allineamento alla griglia: onset da spectral flux (solo numpy), distanza media dagli istanti di battito attesi.
- Tempo di render del prebuffer (`audio.prebuffer_s`) e dell'intera traccia.

### 12.3 Metriche di prestazioni e avvio
- Per scena e per la demo intera: p50, p95, max, **media**, pavimento (p95 a `min_scale` e `uQuality` 0), hotspot (istanti peggiori).
- **Carico GPU stimato** = `mean_ms / (1000 / target_fps)` sulla macchina di sviluppo, e la stessa stima in modalità eco (costo proporzionale ai pixel: `mean_ms × max_scale² / (1000 / 30)`). È la base della stima di consumo nel report.
- Durante le transizioni `crossfade`/`flash` si misura il costo combinato delle due scene.
- Avvio: tempo di compilazione per programma e totale, tempo di prebuffer audio, tempo al primo frame.

### 12.4 Analisi flash (fotosensibilità)
- Input: `lumaSequence` a 60 fps su tutta la demo, a bassa risoluzione (es. 160×90), con luminanza media per cella di una griglia 8×8; `uFlashLimit = 1` (caso peggiore).
- Luminanza relativa da sRGB linearizzato (coefficienti Rec. 709).
- Un **flash** è una coppia di variazioni opposte di luminanza relativa ≥ 0,1 in cui lo stato più scuro è < 0,8, su un insieme di celle che copre ≥ 25% dello schermo.
- Il gate fallisce se in una finestra di 1 s ci sono più di `safety.flash_max_per_s` flash, o se ci sono flash rossi saturi (transizioni verso rosso con R/(R+G+B) ≥ 0,8 contate allo stesso modo).
- **[VERIFICARE]** l'approssimazione rispetto alle definizioni di WCAG 2.3.1; se possibile, confronto con uno strumento di riferimento su clip di prova.

### 12.5 Gate tecnici (prima del critico)
| Gate | Soglia di default | Quando | Esito se fallisce |
|---|---|---|---|
| compilazione Chromium | ok | S4 | FIXER |
| `nan_ratio + inf_ratio` | 0 | S5 | issue `blocker` generata dal tool |
| `black_ratio` medio | < 0,9 | S5 | `major` |
| perf p95 (qualità piena, risoluzione del profilo) | ≤ `profiles.<p>.budget_ms_p95` | S5, S9 | `blocker` con hotspot |
| perf media | ≤ `profiles.<p>.budget_ms_mean` | S5, S9 | `major` (consumo) |
| perf pavimento | ≤ `realtime.floor_ratio × budget_ms_p95` | S5 | `major`: la qualità adattiva non ha margine |
| compilazione per scena | ≤ `realtime.max_compile_ms_scene` | S5 | `major` con suggerimenti (cicli, unrolling) |
| context lost / timeout | — | S5 | `blocker` "shader troppo pesante o ciclo non limitato" |
| flash | ≤ `safety.flash_max_per_s`, nessun flash rosso | S5, S9 | `blocker` |
| clipping audio | < 0,1 % | S8 | revisione audio |
| prebuffer audio | ≤ `audio.max_render_ms_prebuffer` | S8 | `major` |
| compilazione totale | ≤ `realtime.max_compile_ms_total` | S9 | `major` sulla scena più costosa |
| primo frame | ≤ `realtime.max_first_frame_ms` | S9 | `major` |
| payload gzip | ≤ `bundle.max_payload_gz_kb` | S9 | minify aggressivo, poi issue di riduzione |
| compatibilità motori | tutti ok | S9 | FIXER con il log del motore |
| render minificato vs non minificato | differenza entro tolleranza | S9 | bug del minificatore: fallback a minify base |
| palette (solo retro, se imposta) | ≥ 99% dei pixel in palette | S5 | `minor` |

### 12.6 Materiale per il critico
- **Contact sheet**: griglia 4×4 dei keyframe con timestamp e battuta sovrimpressi (Pillow), ~1536 px di lato lungo. Per il retro i frame vengono ingranditi nearest, così il critico vede i pixel.
- **Burst strip**: 3 righe × 6 frame consecutivi, per giudicare il moto.
- **Heatmap differenze**: |frame[i+1] − frame[i]| per un burst, per evidenziare flicker e aliasing temporale.
- **Spettrogramma** (audio) con griglia di battute.
- Metriche in JSON + brief della scena + art direction. Le prestazioni non vanno al critico: sono gate numerici e materiale per la revisione.

Rubrica nel prompt: punteggi 1–10 con definizioni ancorate; issue sempre con timestamp e fix proposto in termini di parametri o tecniche (non codice); `accept` solo se nessuna issue `blocker`/`major` e media ≥ soglia configurabile (default 7).

---

## 13. Prestazioni realtime ed energia

### 13.1 Il budget è anche un budget energetico
Ogni visione ricalcola tutto sulla GPU di chi guarda. Uno shader che usa 6 ms su 16,7 tiene la GPU occupata circa al 35%; la decodifica di un video usa invece un blocco hardware dedicato che consuma pochissimo. Per questo si misurano sia il p95 (fluidità) sia la **media** (consumo), il frame rate è limitato al target e negli embed il default è la modalità eco fuori dallo schermo intero.

### 13.2 Misura
- L'harness renderizza fuori da rAF a risoluzione di riferimento, per ogni istante campionato, `repeats` volte (mediana), scartando i frame di riscaldamento.
- Tempo GPU con `EXT_disjoint_timer_query_webgl2` quando esposta; altrimenti fence (`fenceSync` + `clientWaitSync`) e `performance.now()`.
- Una sola misura alla volta (`perf_lane`), nessun altro carico GPU dalla pipeline.
- macOS: Chromium di Playwright in headless deve usare la GPU reale (ANGLE → Metal). **[VERIFICARE]** flag e comportamento; se l'headless ricade su rendering software, usare `browser.perf_headed: true`.
- CI Linux: SwiftShader (flag in `browser.swiftshader_flags`, perché il fallback automatico a SwiftShader è deprecato in Chromium); i tempi non sono significativi e i gate perf sono disattivati.

### 13.3 Frame pacing e modalità eco
- Il player renderizza al massimo `target_fps`: sugli schermi a 120 Hz rAF arriva al doppio della frequenza, e senza limite il consumo raddoppierebbe. I callback in eccesso vengono saltati in base al tempo trascorso.
- `power="eco"`: 30 fps, scala massima 0.75, bloom e CRT spenti. `power="auto"` (default degli embed): eco fuori dallo schermo intero, piena qualità in schermo intero. `power="full"`: sempre piena.
- Pausa fuori viewport e a scheda nascosta (§5.4).

### 13.4 Hotspot e suggerimenti per la revisione
Quando un gate perf fallisce, la issue contiene gli istanti peggiori (con `uSceneTime`) e un catalogo di rimedi: bounding volume e uscita anticipata per il cielo, `MAX_STEPS` più basso con `qSteps`, meno ottave di fbm in lontananza, overstepping/relaxation nel raymarching, soft shadow e AO solo sopra una soglia di qualità, `stepScale` corretto dal bound di Lipschitz.

### 13.5 Tempo di compilazione
Su Windows ANGLE traduce in HLSL e usa il compilatore D3D, che può essere molto più lento che su Mac per shader grandi con cicli **[VERIFICARE su una macchina Windows]**. Mitigazioni: gate sul tempo di compilazione, convenzioni sui cicli (§5.1), compilazione parallela durante il caricamento, bench manuale su Windows in Fase 7.

### 13.6 Taratura
- `demogen calibrate`: misura i quattro shader di esempio della Fase 1 e salva i tempi della macchina di sviluppo, per scegliere i budget e confrontare macchine diverse.
- Bench su dispositivi reali: `demo.html?bench` carica il modulo `bench` (separato dal core), esegue la demo a tempi fissi e produce un JSON con GPU e p95/media per scena; `demogen perf import <file.json>` lo registra nel progetto e nel report.

---

## 14. Profilo `retro`

### 14.1 Scopo
Recuperare l'estetica e soprattutto la **leggerezza** delle demo classiche: pochi pixel, poche operazioni per pixel, palette limitata. A 320×180 i pixel sono circa 36 volte meno che a 1080p, e gli effetti 2D costano pochissimo per pixel: una demo retro deve girare fluida anche su telefoni di qualche anno fa e rientra comodamente nella modalità eco.

### 14.2 Rendering nel player
- La scena si renderizza alla **risoluzione interna fissa** (`profiles.retro.internal_resolution`, default 320×180; 320×200 con letterbox per il 4:3).
- Ingrandimento con filtro **nearest**, a multipli interi quando possibile (bande nere per il resto), quindi pixel netti.
- Colore finale tramite `retroFinalize()`: quantizzazione nella palette dello stile + dithering ordinato (Bayer).
- CRT/scanline opzionali, leggeri, spenti in eco.
- La qualità adattiva agisce poco (la risoluzione interna non scende); `uQuality` resta disponibile per gli effetti più costosi.

### 14.3 Repertorio (libreria `retro/`)
Plasma, tunnel polare, rotozoom, raster/copper bar, starfield 2D e 3D, fuoco, twister, sine scroller con font bitmap. Il 3D è ammesso solo in forma leggera (`perf_tier: light`, pochi passi), ad esempio vector ball o solidi flat-shaded.

### 14.4 Testo dello scroller
- Il testo è un **dato** del payload (`text`, max 256 caratteri ASCII stampabili), non codice.
- Il player lo passa come `uniform highp int uText[64]` (4 caratteri per intero) + `uTextLen`; `retro/font.glsl` lo legge.
- Caratteri fuori dall'intervallo ASCII stampabile vengono sostituiti dal tool prima del bundle.

### 14.5 Audio
Il composer per il profilo retro usa `audio/chip.glsl` (impulso con duty cycle, triangolo a gradini, noise tipo LFSR, arpeggi): sonorità chiptune, coerente con l'immagine e leggera da calcolare.

### 14.6 Demo miste
Il profilo si sceglie per demo con override per scena. Nelle transizioni tra profili diversi il compositor porta entrambe le scene alla risoluzione di uscita (nearest per il retro) prima di fonderle. Esempio: intro retro, sviluppo moderno, chiusura retro con scroller dei saluti.

### 14.7 Anti-cliché specifici
Plasma arcobaleno generico a tutto schermo, scroller sinusoidale senza variazioni, copper bar come unico effetto, palette arcobaleno senza direzione artistica.

---

## 15. Dimensione

### 15.1 Catena di riduzione
1. **Preprocessore**: espansione degli include, header escluso (lo aggiunge il player).
2. **Tree-shaking** (`treeshake.py`): grafo delle chiamate a partire da scene e `style.glsl`; nel `common` entrano solo le funzioni raggiungibili, con le relative costanti e macro. È possibile senza un parser GLSL completo perché la libreria segue le convenzioni del §7.
3. **Minify base**: rimozione di commenti e spazi, accorciamento dei letterali (`1.0` → `1.`, `0.5` → `.5`).
4. **Minify aggressivo** (opzionale): minificatore esterno con rinomina degli identificatori **[VERIFICARE disponibilità su macOS/Linux e licenza]**.
5. Verifica: il render del bundle minificato deve coincidere, entro tolleranza, con quello non minificato.

### 15.2 Classi di dimensione
| Classe | Vincolo | Quando |
|---|---|---|
| `standard` | payload gzip ≤ `bundle.max_payload_gz_kb`; dimensioni sempre riportate | v1 |
| `64k` | HTML standalone ≤ 64 KiB su disco, con bootstrap autoestraente | Fase 7 |
| `8k` / `4k` | size-coding: shader unico, synth compatto, packer JS | Fase 8 |

### 15.3 Costo marginale sul web
Il player si scarica una volta ed è in cache per tutte le demo e le pagine; ogni demo aggiuntiva costa solo il suo payload compresso (tipicamente 10–40 KB, meno per il retro). Un minuto di video a 1080p pesa decine di MB.

---

## 16. Cartella progetto

```
projects/2026-11-24_neon-tunnel/
├── state.json
├── spec.json
├── style.glsl
├── post.json
├── art_direction.md
├── scenes/
│   └── s1/
│       ├── v1.glsl  v1.meta.json  v1.critique.json
│       ├── v1.probe/  contact.png  burst.png  diff.png  metrics.json
│       │              perf.json  perf.png  flash.json  startup.json
│       ├── math.glsl
│       └── best.json            # puntatore alla versione scelta + punteggio
├── audio/
│   ├── v1.glsl  audio.wav  spectrogram.png  metrics.json  v1.critique.json
├── math/
│   └── req_001.json  result_001.json
├── perf/
│   └── devices/                 # bench importati da dispositivi reali
├── llm_calls/
├── out/
│   ├── neon-tunnel.demo
│   ├── neon-tunnel.html
│   ├── poster.webp
│   ├── sizes.json
│   └── neon-tunnel.mp4          # solo con export-mp4
└── report.md                    # iterazioni, punteggi, costi, modelli, tempi,
                                 # prestazioni, carico GPU stimato, dimensioni
```

---

## 17. Prompt (template)

Tutti in `demogen/llm/prompts/*.md.j2`, versionati, con test che verificano il rendering dei template. Il contratto e il riferimento API stanno in un prefisso stabile (caching).

- **orchestrator_brief**: dal prompt utente al `DemoSpec`; scene distinte con progressione (introduzione, sviluppo, climax, chiusura), legame esplicito col beat, scelta motivata del profilo, `perf_tier` per scena, lista `avoid`; per il retro, eventuale `text` dello scroller.
- **orchestrator_style**: `style.glsl` + `post.json` + art direction; vincoli su palette e post; per il retro, palette di `palette_size` colori e dithering.
- **orchestrator_scene** (varianti `modern` e `retro`): ruolo; contratto shader (§5.1); regole GLSL ES (letterali float, niente conversioni implicite, cicli con `qSteps`); riferimento API della libreria (da `docs.py`); repertorio di tecniche del profilo; **budget di prestazioni** in ms e cosa scalare con `uQuality`; regole sui lampi (`beatFlash`, niente strobo a tutto schermo oltre 3 Hz); lista anti-cliché (modern: sfere raymarched su piano a scacchi, terreno fbm generico con nebbia, tunnel infinito senza variazioni, palette arcobaleno; retro: §14.7); quando emettere `math_requests`; formato envelope.
- **orchestrator_revise**: shader attuale, critica, issue dei gate con hotspot, punteggi storici; "modifica il minimo necessario per risolvere le issue in ordine di gravità".
- **fixer**: errori mappati (anche specifici di un motore) e righe di contesto; restituisce lo shader completo corretto, nessuna modifica creativa.
- **critic_scene / critic_audio**: rubrica, materiale (§12.6), formato `CriticReport`; "non scrivere codice".
- **math**: rigore; sintassi SymPy; assunzioni esplicite; claim verificabili obbligatori; nessun GLSL.
- **composer** (varianti `modern` e `chip`): contratto `mainSound`, API audio della libreria, timeline, linee guida di mix (headroom, bassi mono, niente DC), costo di calcolo contenuto (il prebuffer ha un budget).

---

## 18. Sicurezza e robustezza

- **Nessun codice generato da LLM eseguito come JS o Python.** Gli unici artefatti eseguiti sono GLSL (compilato dal browser, che lo valida con ANGLE nel processo GPU isolato) ed espressioni SymPy filtrate da whitelist in un subprocess.
- Il player non usa `eval`, `Function` né import dinamici dal payload; è compatibile con CSP senza `unsafe-eval`. Limiti di dimensione su payload e sorgenti (§6.6).
- L'harness non viene mai distribuito; le pagine pilotate da Playwright hanno **la rete esterna bloccata** (`page.route` serve solo i file del progetto e rifiuta tutto il resto).
- Hang GPU: il watchdog del browser provoca la perdita del contesto → l'harness la segnala → gate; timeout di Playwright → il browser viene chiuso e riavviato.
- Testo dello scroller: solo ASCII stampabile, lunghezza limitata, passato come interi.
- Chiavi API solo da env; redazione automatica di header `Authorization` e di stringhe simili a chiavi nei log.
- Nomi di progetto normalizzati (solo `[a-z0-9-_]`), nessun path traversal.
- Contenuto dei log LLM trattato come dato: nessuna istruzione letta da lì viene eseguita.
- `demogen play` ascolta solo su `127.0.0.1`.

---

## 19. Piattaforme di sviluppo

- **macOS (Apple Silicon)**, piattaforma principale: `uv`, Node LTS, browser di Playwright (`uv run playwright install chromium webkit firefox`), `glslang` (Homebrew). `ffmpeg` serve solo per `export-mp4`. Il rendering passa da ANGLE → Metal, quindi la deprecazione di OpenGL su macOS non riguarda il progetto. WebKit di Playwright dà un'indicazione sul comportamento di Safari.
- **Linux**: stessi requisiti; in CI Chromium con SwiftShader (`browser.swiftshader_flags`), solo test funzionali e golden render.
- **Windows**: non è piattaforma di sviluppo in v1, ma è una parte importante del pubblico web; si verifica con il bench manuale (§13.6), con attenzione ai tempi di compilazione (§13.5).
- Il multiprocessing su macOS usa `spawn`: il subprocess SymPy e le sessioni browser vengono creati nel processo figlio, mai ereditati.

---

## 20. Fasi di implementazione

### Fase 0 — Spike e scheletro
- [ ] Monorepo: `uv` + `pyproject.toml`, `package.json` con workspace `player`, `ruff`, `pytest`, `vitest`, `esbuild`, `CLAUDE.md`.
- [ ] Spike player: TypeScript minimo che renderizza uno shader Shadertoy su canvas WebGL2 con `iTime`.
- [ ] Spike harness: Python + Playwright apre `harness.html` servito con `page.route`, compila uno shader, cattura un frame PNG, misura ms/frame fuori da rAF. Su Mac (GPU reale) e su Linux (SwiftShader). **[VERIFICARE]** flag per la GPU in headless su macOS, flag SwiftShader su Linux, throughput del trasferimento di frame.
- [ ] `demogen doctor`: Node, browser di Playwright, renderer visto da Chromium (GPU reale o software), estensioni WebGL2 rilevanti (`EXT_color_buffer_float`, `KHR_parallel_shader_compile`, `EXT_disjoint_timer_query_webgl2`), `glslangValidator`, `ffmpeg` (opzionale).
- **Accettazione**: `demogen doctor` tutto verde; `uv run python -m demogen.browser.spike` salva un PNG e stampa ms/frame; su Mac il renderer riportato è la GPU Apple, non SwiftShader.

### Fase 1 — Player core, profili e libreria GLSL
- [ ] Player: `gl`, `programs` (compilazione parallela), `timeline`, `compositor` (quattro transizioni, anche tra profili diversi), `post` (finalize + bloom), `quality` (adattivo, eco, frame pacing), `format`, `element`, gestione della perdita di contesto.
- [ ] Profilo retro nel player: risoluzione interna fissa, upscale nearest a multipli interi, letterbox, `uText`.
- [ ] Vettori condivisi della timeline in `shared/vectors/`: parità tra pytest e vitest.
- [ ] `preprocessor.py`, `validator.py` (ES), `treeshake.py`, `minify.py` (base).
- [ ] Harness (`load`, `capture`, `lumaSequence`, `profile`, `info`) + lato Python `session`, `harness`, `serve`, `perf_lane`.
- [ ] Libreria §7 (parte video, inclusa `retro/`) con test: golden render via harness con tolleranza, test numerici su GPU.
- [ ] `docs.py` genera il riferimento API.
- [ ] CLI: `demogen play shader.glsl --bpm 120 [--profile retro]`, `demogen bundle` (da shader + timeline JSON → `.demo` + `.html`).
- [ ] CI: limite di dimensione del player core.
- **Accettazione**: quattro shader scritti a mano (tunnel, frattale IFS, terreno, plasma retro con scroller) assemblati in una demo con transizioni; 60 fps a 1080p sulla macchina di sviluppo; in eco 30 fps con carico misurato ridotto; golden test verdi su SwiftShader; player core ≤ 12 KB gzip; pagina `examples/embed` con tre demo senza scatti durante lo scroll.

### Fase 2 — Audio
- [ ] `audio.ts`: render GPU a blocchi (RGBA8 16 bit; float nell'harness), prebuffer di `audio.prebuffer_s` secondi e resto in background a fette di tempo per frame (≤ 2 ms per frame), scheduling di chunk consecutivi sul clock di `AudioContext` **[VERIFICARE assenza di click/gap; alternativa: AudioWorklet con codice fisso del player]**, clock audio master, `outputLatency`, sblocco al gesto, seek (render sincrono del chunk mancante).
- [ ] Libreria audio §7, incluso `chip.glsl`, con test (fondamentale misurata via FFT, inviluppi, duty cycle).
- [ ] `metrics_audio.py` e spettrogramma con griglia di battute.
- [ ] Test della logica di scheduling con `OfflineAudioContext` (sinusoide continua attraverso i confini dei chunk, nessuna discontinuità).
- **Accettazione**: demo con audio in cui il kick è allineato al `beatPulse` visivo; errore tra onset e griglia < 5 ms nel dominio dei dati; prebuffer di 8 s entro `max_render_ms_prebuffer` sulla macchina di sviluppo; nessuna discontinuità tra chunk; sincronia A/V verificata a mano con una pagina lampo+beep.

### Fase 3 — Livello LLM
- [ ] `config.py` + `demogen init` (scrive `demogen.example.yaml`).
- [ ] `providers.py`, `client.py` (sync e async), retry, logging, redazione.
- [ ] `capabilities.py` con cache; **[VERIFICARE]** campi del catalogo OpenRouter sulla risposta reale.
- [ ] `envelope.py`, `structured.py` con i tre livelli e il loop di riparazione.
- [ ] `budget.py` con costo da `usage` (OpenRouter) o da tabella prezzi.
- [ ] `demogen models check`.
- [ ] Test con server finto OpenAI-compatible (es. `respx` o una piccola app FastAPI) e fixture registrate: risposte valide, JSON malformato, GLSL senza recinto, 429 con retry, timeout.
- **Accettazione**: test verdi; `demogen models check` (live, manuale) funziona su OpenRouter e su un endpoint locale.

### Fase 4 — Metriche, gate e materiale per il critico
- [ ] `metrics_video.py`, `metrics_perf.py`, `flash.py`, `gates.py`, `sheets.py` (contact sheet, burst strip, heatmap, grafico ms/tempo con linea di budget).
- [ ] Test sintetici con esito atteso: nero, NaN, flicker alternato, strobo a 10 Hz (gate flash), flash rosso, shader pesante (gate perf), carico medio alto con p95 nel budget (gate consumo), cicli annidati (gate compilazione), payload fuori limite.
- [ ] `demogen inspect <shader|file.demo>`, `demogen calibrate`.
- **Accettazione**: i casi sintetici sono classificati correttamente dai gate; `inspect` stampa metriche, profilo perf con carico stimato, avvio, flash e dimensioni, e salva i fogli.

### Fase 5 — Orchestratore v1 (senza oracolo matematico)
- [ ] `spec/models.py` completo.
- [ ] `pipeline.py`: macchina a stati, `state.json`, resume idempotente.
- [ ] Step S0, S1, S2, S4–S9; selezione della versione migliore con penalità perf e anti-regressione.
- [ ] Template prompt §17 (tranne `math`), con le varianti modern/retro e modern/chip.
- [ ] Parallelismo: chiamate LLM concorrenti, catture in un pool di pagine, misure perf serializzate.
- [ ] `report.md`: iterazioni, punteggi, costi, modelli, tempi, prestazioni, carico GPU stimato (normale ed eco), dimensioni.
- [ ] CLI: `generate`, `resume`, `revise`, `report`.
- [ ] Test end-to-end con LLM finto deterministico (risposte registrate) che produce una `.demo` di 8 s che passa i gate nell'harness.
- **Accettazione**: E2E finto verde; smoke test live (`@pytest.mark.live`, manuale) con un prompt moderno e uno retro di `examples/prompts/`: demo di 30–60 s, realtime sulla macchina di sviluppo entro budget, payload entro limite, costo entro budget.

### Fase 6 — Oracolo matematico
- [ ] `safe_parse.py` con whitelist e subprocess (watchdog RSS su macOS); test di rifiuto di input malevoli (`__import__`, attributi, lambda, stringhe).
- [ ] `verify.py` per tutti i tipi di claim; test con claim veri e falsi noti (SDF del toro esatta vs versione con errore di segno; periodo sbagliato; bound di Lipschitz sottostimato per un twist).
- [ ] `codegen.py` con normalizzazione GLSL ES + inserimento in `math.glsl` della scena.
- [ ] Step S3 e integrazione nel prompt orchestratore.
- **Accettazione**: in un E2E finto la scena con `math_requests` include uno snippet verificato e compila in tutti i motori; i claim falsi dei test vengono rifiutati tutti.

### Fase 7 — Distribuzione web e qualità
- [ ] Taratura della qualità adattiva (isteresi; test con frame time simulati e con shader artificialmente pesanti).
- [ ] Accessibilità: `reduce-flashes`, `prefers-reduced-motion`, controlli da tastiera, gate flash sulla demo intera.
- [ ] Fallback al poster, UI d'errore, modulo `bench` + `demogen perf import`.
- [ ] Gate di compatibilità dei motori in S9.
- [ ] Modalità loop: vincoli di periodicità nel prompt e verifica `loop_seam`.
- [ ] Classe 64k: bootstrap autoestraente.
- [ ] `demogen export-shadertoy`: scene unite in un solo shader con dispatch temporale; audio nel tab Sound.
- [ ] `demogen export-mp4`: cattura offline con supersampling e motion blur, pipe a ffmpeg.
- [ ] Critica finale della demo intera (contact sheet globale) con eventuale revisione mirata di una scena.
- **Accettazione**: una demo moderna di 60 s con 4 scene, transizioni e audio: 60 fps sulla macchina di sviluppo e ≥ 50 fps con qualità adattiva su un portatile Windows di fascia media (bench manuale); una demo retro ≥ 60 fps su un telefono di qualche anno fa (bench manuale); HTML standalone ≤ 64 KiB; compatibilità ok in Chromium, WebKit e Firefox; gate flash verificato.

### Fase 8 — Opzionale
- [ ] Size-coding 8k/4k: shader unico, synth compatto, packer JS **[VERIFICARE strumenti e licenze]**.
- [ ] Backend WebGPU dietro la stessa interfaccia interna del player.
- [ ] UI web locale (galleria progetti, player, cronologia versioni, revisione con nota).
- [ ] Benchmark di modelli: stesso set di prompt, confronto di punteggi del critico, costi, tempi e prestazioni delle demo per combinazione di ruoli.
- [ ] Tier mobile con budget dedicato.
- [ ] Interattività: mouse/touch come uniform, con comportamento deterministico quando non c'è input.

---

## 21. Strategia di test

| Livello | Cosa | Dove |
|---|---|---|
| Unit Python | preprocessore, mappa righe, tree-shaking, minify, envelope, structured, budget, metriche, flash, verificatore, parser sicuro, formato `.demo` | CI |
| Unit TypeScript | timeline (vettori condivisi), parsing del payload, controllore di qualità (frame time simulati), frame pacing, codifica audio a 16 bit, scheduling dei chunk (`OfflineAudioContext`) | CI (vitest) |
| Render | golden image con tolleranza via harness, test numerici su GPU, NaN, perdita di contesto | CI con SwiftShader |
| Compatibilità | compilazione in Chromium, WebKit, Firefox | CI (software) + locale |
| Prestazioni | profilo con GPU reale, calibrazione | solo locale, `-m perf` |
| Dimensione | player core gzip, payload di esempio | CI |
| LLM | server finto + fixture registrate, scenari d'errore | CI |
| E2E finto | pipeline completa con risposte deterministiche | CI |
| Live | `models check`, smoke `generate` con budget minimo | manuale, `-m live` |

Le fixture LLM si registrano da sessioni reali (`DEMOGEN_RECORD=1`) e si ripuliscono da chiavi e header prima del commit.

---

## 22. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| GPU dei visitatori molto più deboli della macchina di sviluppo | budget prudenti, gate sul pavimento, qualità adattiva, profilo retro, bench su dispositivi reali, fallback al poster |
| Consumo e calore su portatili e telefoni | gate sul carico medio, frame pacing, eco di default negli embed, pausa fuori viewport |
| Compilazione lenta su Windows (ANGLE → D3D) | gate sul tempo di compilazione, convenzioni sui cicli, compilazione parallela, bench manuale |
| Differenze tra motori e GPU (precisione, casi limite come `pow` con base negativa o `normalize` di vettori nulli) | gate di compatibilità, helper sicuri in libreria, golden test con tolleranza |
| Fotosensibilità | gate flash, `reduce-flashes`, `prefers-reduced-motion` |
| Politiche di autoplay | partenza senza audio, audio al primo gesto |
| Limite di contesti WebGL per pagina | rilascio del contesto fuori viewport |
| Avvio lento (compilazione + audio) | prebuffer breve, audio progressivo, gate sul primo frame |
| Misure perf in headless non rappresentative | perf lane serializzato, opzione `perf_headed`, calibrazione |
| Renderer software sul dispositivo del visitatore | rilevamento e fallback al poster |
| Output visivi da cliché | lista `avoid` nello spec, anti-cliché per profilo nel prompt, punteggio `originality` |
| Critico indulgente | modello diverso dall'orchestratore, rubrica ancorata, gate numerici indipendenti |
| Il moto non si giudica da frame statici | burst strip, heatmap, metriche temporali |
| Costi e tempi LLM che esplodono con modelli che ragionano a lungo | budget per step, `max_tokens` per ruolo, prefisso cacheable, stop con la migliore versione |
| Divergenze tra provider OpenAI-compatible | output strutturato a livelli, envelope, `models check` |
| Precisione fp32 su durate lunghe | helper di avvolgimento del tempo, regola nel contratto |
| Strumenti esterni (minificatore, packer) con licenze incompatibili | uso opzionale, verifica della licenza prima dell'integrazione |
| Materiale ispirato a sistemi storici (font, palette) | disegnati da zero, nessuna copia da ROM |

---

## 23. Decisioni aperte (da chiudere prima della Fase 5)

- Lingua dei prompt di sistema (inglese consigliato per la qualità del codice; il prompt utente può essere in qualunque lingua).
- Durata massima supportata in v1 (proposta: 120 s).
- Dispositivo di riferimento per il budget realtime e corrispondenza con le misure sulla macchina di sviluppo (da tarare con i primi bench su dispositivi reali).
- Mobile: tier garantito o best effort (proposta: best effort in v1, garantito per il profilo retro).
- Default di `power` negli embed (proposta: `auto`) e di `autoplay` (proposta: `visual`).
- Soglia di `accept` del critico e pesi del punteggio complessivo, inclusa la penalità di prestazioni.
- Licenza del progetto, della libreria GLSL e del player (attenzione a non copiare funzioni da fonti con licenze incompatibili: riscriverle o citarle correttamente).
- Distribuzione del player: CDN pubblico o self-hosting, schema di versionamento degli URL.
