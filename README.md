# demogen

![edge horizon: a single fragment shader rendered live in the browser by the demogen player](docs/img/edge-horizon.jpg)

[English](#english) · [Italiano](#italiano)

## English

**Offline** generator of realtime demoscene-style demos from a text prompt.

- The user types a prompt; an LLM writes the GLSL shaders (GLSL ES 3.00, `mainImage` contract).
- **Our own rendering engine** (a WebGL2 player) renders the demo in realtime: on macOS it uses the GPU (ANGLE → Metal), with a **CPU fallback** (SwiftShader) when no GPU is available.
- A vision LLM looks at the frames captured by the engine and iterates (critique → revision), after numeric gates (NaN, black frames, flicker, WCAG 2.3.1 flashes, perf, size).
- GPU and LLM usage is confined to the generation phase. No video output in the first step.

See `docs/demogen-piano-implementazione.md` (plan v2), `docs/piano-esecuzione.md` (roadmap) and
`docs/review-piano-correzione.md` (review and fixes); the design docs are in Italian.

### Setup

```bash
uv sync                              # Python environment (3.11+)
uv run playwright install chromium   # browser for the engine/harness
npm install                          # player workspace
npm run build                        # player build (player/dist/)
uv run demogen doctor                # checks the environment + GPU/CPU renderer
```

### Menu

```bash
npm run menu                           # interactive menu (Windows: also double click run.cmd; macOS/Linux: sh run.sh)
npm run menu -- --action list          # list of the entries, which also run without the menu
npm run menu -- --action kill --yes    # closes leftover processes (Playwright browsers, python, node)
npm run menu -- --setup                # uv sync before the menu
uv run demogen menu                    # the same menu, without the launcher
```

The whole app is in one menu styled like the generation panel (`demogen/menu.py`; the launcher
`scripts/run.mts`, TypeScript run by Node ≥ 22.18 without a build step, finds uv, creates the environment
if missing and starts it; it works the same on Windows, macOS and Linux). At the top: venv and player
status, today's and this month's LLM spending against the caps, the models of each role, the detected GPU
and leftover processes. Entries: generate (real LLM or `--fake`, with music and a per-run spending cap),
resume, plan, revise, music, report, open, preview; examples (main demo in realtime, the cat demo, play, inspect, bundle,
web pages);
setup, doctor, LLM config, spending caps, tests, calibrate; show and close demogen processes. Each entry
is tagged `[GPU]` (realtime rendering: choppy without a GPU), `[CPU]` (same speed with or without a GPU)
or `[CPU+]` (runs on CPU alone; a GPU speeds up the checks). With `--action` the questions take their
default and confirmations (spending, closing, opening the browser) are yes only with `--yes`. Ctrl+C
during a command goes back to the menu (the command gets time to save its state and close the browser).

### LLM configuration

```bash
uv run demogen init                  # creates demogen.yaml from the demogen/demo.yaml template
uv run demogen models check          # tries each role (text / vision / json) with a minimal call
```

`demogen.yaml` is in `.gitignore`: the OpenRouter key can live in `providers.openrouter.api_key`
(only there) or in an environment variable named by `api_key_env`. Roles: `orchestrator`,
`critic` (needs vision), `math`, `fixer`, `composer`. `pricing` holds prices per million tokens
(used when the provider does not return the cost).

**LLM spending caps** (`budget:` in `demogen.yaml`, or `demogen budget` / the Spending caps entry):

| key | meaning |
|---|---|
| `max_total_cost_usd` | maximum spending of one generation (also `--max-cost` on generate/resume/revise/music) |
| `max_daily_cost_usd` | maximum spending per day, across all generations (`null` = no cap) |
| `max_monthly_cost_usd` | maximum spending per month, across all generations |
| `max_calls_per_run` | maximum number of LLM calls in one generation |
| `max_wall_minutes` | maximum duration of one generation |

Before every call the maximum cost is estimated (prompt + `max_tokens`): if it would break a cap the
call is not made and the generation stops with the reason (when the scenes are ready, the bundle is
built from the best versions). Daily and monthly spending come from the local ledger
`<cache_dir>/spend.jsonl` (one line per paid call).

```bash
uv run demogen budget                                   # spending today, this month, per project, and the caps
uv run demogen budget --daily 3 --monthly 20 --calls 80 # sets the caps (0 = no cap)
```

### Generating a demo

```bash
uv run demogen generate "neon tunnel pulsing on the kick" --duration 30 --bpm 128 --project projects/tunnel
uv run demogen generate "plasma 8s" --project projects/t --fake      # fake LLM, no API calls
uv run demogen generate "..." --music "acid techno, four on the floor" # music driven by a prompt
uv run demogen generate "..." --no-music --max-cost 0.5              # silent demo, per-run spending cap
uv run demogen generate "..." --loop                                 # continuous loop (no flag: the prompt decides)
uv run demogen generate "..." --profile retro                        # retro style (320x180, 16-color palette) for every scene
uv run demogen generate "..." --review-plan                          # stops after the plan: read it, change it, then resume
uv run demogen plan projects/tunnel                                   # shows the plan: scenes, timing, palette
uv run demogen plan projects/tunnel --scene s1 --description "..."    # changes a scene yourself (also --title, --motion)
uv run demogen plan projects/tunnel --note "the cat is black"         # the LLM rewrites the plan with your note (one call)
uv run demogen play projects/tunnel --scene s2                        # preview of one scene, also during the generation
uv run demogen music projects/tunnel --prompt "slow synthwave"       # (re)composes only the soundtrack
uv run demogen resume projects/tunnel                                 # resumes without repeating the calls already made
uv run demogen revise projects/tunnel --scene s2 --note "less fog, more contrast on the kick"
uv run demogen report projects/tunnel                                 # prints report.md
```

The project holds `spec.json`, `style.glsl`, `scenes/<id>/vN.*` (sources, probes, critiques, oracle
math), `llm_calls/` (redacted logs), `state.json` (steps done, spending) and `out/` with
`<title>.demo` + a standalone `<title>.html`: click to start, then a control bar with Start/Pause,
Stop (back to the start), continuous Loop on/off, clickable position and time, and, when the demo has
music, mute and volume, remembered for the next visit (keys: space, S, L, M, up/down arrows). The page
follows the window: when it is resized the player adapts resolution and graphics, even while paused;
retro scenes (fixed internal resolution) keep their proportions with black bars. `resume`, `revise` and
`music` also accept `--fake`. The style (`--profile modern|retro`, default modern) is the user's choice and
applies to every scene: the LLM cannot change it scene by scene.

**Plan review and previews.** The first step writes the plan in `spec.json`: scenes (what you see, how it
moves), timing, palette, art direction. It is one cheap call; most of the cost comes later, while the
scenes are drawn and judged. With `--review-plan` (in the menu: "review the plan first", yes by default)
the generation stops there: `demogen plan` shows the plan, `--scene s1 --description/--title/--motion`
changes a scene without calling the LLM, `--note "..."` asks the LLM to rewrite the plan (the CLI flags
still win: duration, BPM, style, loop), and `demogen resume` draws it. The plan can change only before the
style step; afterwards a scene changes with `revise`. `demogen play <project> --scene s1 [--version N]`
plays one scene in a loop as it will look in the demo (project style, oracle functions, post-processing;
default: the best version so far, else the latest), also while the generation is running: it only reads
the project. The 16 frames the critic saw are in `scenes/<id>/vN.probe/contact.png`. In the menu: Plan
and Preview (which also offers to open the frame sheet).

![Frame sheet: 16 frames of a demo on one image, each with its time and bar](docs/img/whisker-hunt-contact.png)

*The frame sheet the critic judges: 16 frames spread over the demo, each with its time and bar (here
`demogen inspect` on `examples/whisker_hunt.timeline.json`).*

**Music.** After the shaders, the `composer` role writes the soundtrack (`mainAudio` in GLSL, on the
demo's BPM), driven by `--music` or, when missing, by the demo prompt. It is listened to automatically:
compilation, loudness, NaN, compute cost (≥ 10× realtime), strong hits on the rhythm grid, distortion,
silent bars; on a blocking problem the composer revises it. Versions in `audio/vN.*` with a
spectrogram; `--no-music` makes a silent demo.

In a terminal, `generate`, `resume` and `revise` show a live panel: steps S0–S9 with a progress bar,
each scene with phase, version, cost and score, the LLM calls in flight with their running time and the
credits spent against the cap. `--plain` (or redirected output, or `DEMOGEN_PLAIN=1`) keeps only the
text log.

**Perf.** Every scene is measured in multiples of a reference scene
(`demogen/critic/reference_scene.glsl`: a raymarched tunnel, 96 steps, normals, soft shadows), in the
same browser and at the same resolution, so the check also holds on SwiftShader. Above 4×
(`realtime.max_ref_ratio_p95`) the scene is blocking and the LLM has to lighten it; in the final bundle
the excess stays a warning in the report. With `--gpu hardware` the absolute ms budgets on the real GPU
apply as well; the fixed cost of a measurement (an empty scene with the same rendering: GPU sync and the
player's compositing, a few ms on some GPUs) is subtracted first, otherwise scaling it to the budget
resolution failed even an empty scene. The budgets are set for the development machine (Apple Silicon):
on a slower GPU a scene can be over budget there and still fine on the target. When a demo is slow the
player goes down to 1/4 of the resolution.

### Other commands

```bash
uv run demogen play examples/timeline.json        # realtime rendering in a window (also a single .glsl)
uv run demogen inspect examples/timeline.json     # metrics + gates + sheets in out/inspect_*/
uv run demogen bundle examples/timeline.json --out out   # .demo + .html from a hand-written timeline
uv run demogen probe examples/timeline.json --gpu swiftshader
uv run demogen calibrate --gpu hardware           # ms of the 4 example shaders (informational)
uv run demogen still examples/shaders/terrain.glsl --gpu hardware --width 7680 --height 4320 --spp 16
                                                  # experimental: one high-resolution PNG (tiles + sub-pixel samples)
```

Ready-made examples in `examples/web/` open with a double click, for instance `whisker-hunt.html`
(an orange pixel-art cat hunting a moth; also the `cats` menu entry), `penguin.html` and
`edge-horizon.html` (a live shader as the background of a website hero: dotted grid, icy planet drawn
as a blueprint, network pulses, 128 s seamless loop, paused off screen; also the `horizon` menu entry);
see `examples/web/README.md`. Its companion `examples/edge_blueprint.timeline.json` is the background of
the rest of the page: the technical-drawing dot grid with a "+" every 5 dots, breathing in slow waves
(fixed behind the sections, 30 fps, 1.5 KB gzip). `play` and `inspect` on a single shader of a timeline
use that timeline's common code, text and style.

![whisker hunt: an orange pixel-art kitten sitting on a dark teal background, with the player's control bar](docs/img/whisker-hunt.png)

*`whisker-hunt.html`: retro profile (320×180, scaled up without smoothing) and the control bar of the
standalone page. The picture at the top is `edge-horizon.html` full screen.*

### MCP server: an external agent writes the demo

`demogen mcp` turns demogen into a pure engine: an agent (Claude Code, Claude Desktop, any MCP client)
writes shaders, style and timeline as files, and demogen compiles, renders, measures and bundles them.
No LLM runs on the demogen side, so there are no keys and no spending.

| Tool | What it does |
|---|---|
| `guide` | workflow, file formats, the GLSL contract and the gates: the agent reads it first |
| `glsl_library` | the library functions a scene can call without defining them (`query` filters) |
| `validate` | compiles in the real player; errors come back as `file:line: message` |
| `render` | frames at the given times, returned as one image (PNGs saved under `out/mcp/`) |
| `render_still` | one high-resolution image (tiles + sub-pixel samples, bloom, image gates): preview and a 1:1 crop |
| `inspect` | the gates of the pipeline: NaN, black, flicker, loop seam, WCAG flashes, perf, size |
| `verify_math` | the math oracle: verified formulas (SDF, Lipschitz, period, easing) become GLSL |
| `bundle` | `.demo` payload + standalone `.html` |

```bash
uv run demogen mcp --root <project folder> [--gpu hardware|swiftshader]   # stdio
claude mcp add demogen -- uv --directory <demogen folder> run demogen mcp --root <project folder>
```

In this repository `.mcp.json` already declares the server for Claude Code (approve it once). Paths of
the tools are relative to `--root` (use an absolute path) and cannot leave it; demogen's `examples/` can
always be read. The browser opens at the first request and stays open (`--gpu hardware` falls back to
SwiftShader when there is no GPU). Also the `mcp` menu entry.

### Tests

```bash
uv run ruff check .
uv run pytest                        # browser tests are skipped only when Chromium is missing (they fail in CI)
npm run typecheck --workspace player
npm test --workspace player
```

Frame goldens: `DEMOGEN_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` regenerates them
(only after checking them by eye). `live`/`perf` tests are excluded by default.

## Italiano

Generatore **offline** di demo realtime stile demoscene da un prompt testuale.

- L'utente digita un prompt; un LLM scrive gli shader GLSL (GLSL ES 3.00, contratto `mainImage`).
- Il **motore di rendering creato da noi** (player WebGL2) renderizza la demo in realtime: su macOS sfrutta la GPU (ANGLE → Metal), con **fallback su CPU** (SwiftShader) quando la GPU non è disponibile.
- Un LLM con visione analizza i frame catturati dal motore e itera (critica → revisione), dopo gate numerici (NaN, nero, flicker, flash WCAG 2.3.1, perf, dimensione).
- Consumo GPU e LLM confinato alla fase di generazione. Nessun output video nel primo step.

Vedi `docs/demogen-piano-implementazione.md` (piano v2), `docs/piano-esecuzione.md` (roadmap) e
`docs/review-piano-correzione.md` (review e correzioni).

### Setup

```bash
uv sync                              # ambiente Python (3.11+)
uv run playwright install chromium   # browser per il motore/harness
npm install                          # workspace player
npm run build                        # build del player (player/dist/)
uv run demogen doctor                # verifica ambiente + renderer GPU/CPU
```

### Menu

```bash
npm run menu                           # menu interattivo (Windows: anche doppio click su run.cmd; macOS/Linux: sh run.sh)
npm run menu -- --action list          # elenco delle voci, eseguibili anche senza menu
npm run menu -- --action kill --yes    # chiude i processi rimasti aperti (browser di Playwright, python, node)
npm run menu -- --setup                # uv sync prima del menu
uv run demogen menu                    # lo stesso menu, senza il lanciatore
```

Tutta l'app è in un menu nello stile del pannello di generazione (`demogen/menu.py`; il lanciatore
`scripts/run.mts`, in TypeScript eseguito da Node ≥ 22.18 senza build, trova uv, crea l'ambiente se manca
e lo avvia; funziona uguale su Windows, macOS e Linux). In alto: stato di venv e player, spesa LLM di oggi e del
mese sui tetti, modelli dei ruoli, GPU rilevata, processi rimasti aperti. Voci: generate (LLM reale o
`--fake`, con musica e tetto di spesa del run), resume, plan, revise, music, report, open, preview; esempi (demo
principale in tempo reale, demo dei gatti, play, inspect, bundle, pagine web); setup, doctor, config LLM, spending caps,
test, calibrate; mostra e chiudi i processi di demogen. Ogni voce ha l'etichetta `[GPU]` (rendering in
tempo reale: senza GPU va a scatti), `[CPU]` (stessa velocità con o senza GPU) o `[CPU+]` (va anche
solo su CPU; la GPU accelera i controlli). Con `--action` le domande prendono il default e le conferme
(spesa, chiusura, apertura del browser) valgono sì solo con `--yes`. Ctrl+C durante un comando torna al
menu (il comando ha il tempo di salvare lo stato e chiudere il browser).

### Configurazione LLM

```bash
uv run demogen init                  # crea demogen.yaml dal template demogen/demo.yaml
uv run demogen models check          # prova ogni ruolo (testo / vision / json) con una chiamata minima
```

`demogen.yaml` è in `.gitignore`: la chiave OpenRouter può stare in `providers.openrouter.api_key`
(solo lì) oppure in una variabile d'ambiente indicata da `api_key_env`. Ruoli: `orchestrator`,
`critic` (serve vision), `math`, `fixer`, `composer`. In `pricing` i prezzi per milione di token
(usati se il provider non restituisce il costo).

**Tetti di consumo LLM** (`budget:` in `demogen.yaml`, oppure `demogen budget` / voce Spending caps):

| chiave | significato |
|---|---|
| `max_total_cost_usd` | spesa massima di una generazione (anche `--max-cost` su generate/resume/revise/music) |
| `max_daily_cost_usd` | spesa massima del giorno, sommando tutte le generazioni (`null` = nessun tetto) |
| `max_monthly_cost_usd` | spesa massima del mese, sommando tutte le generazioni |
| `max_calls_per_run` | numero massimo di chiamate LLM in una generazione |
| `max_wall_minutes` | durata massima di una generazione |

Prima di ogni chiamata si stima il costo massimo (prompt + `max_tokens`): se sforerebbe un tetto la
chiamata non parte e la generazione si ferma con il motivo (con le scene già pronte il bundle si fa con
le versioni migliori). La spesa di giorno e mese viene dal registro locale `<cache_dir>/spend.jsonl`
(una riga per chiamata pagata).

```bash
uv run demogen budget                                   # spesa di oggi, del mese, per progetto e tetti
uv run demogen budget --daily 3 --monthly 20 --calls 80 # imposta i tetti (0 = nessun tetto)
```

### Generare una demo

```bash
uv run demogen generate "tunnel neon che pulsa sul kick" --duration 30 --bpm 128 --project projects/tunnel
uv run demogen generate "plasma 8s" --project projects/t --fake      # LLM finto, nessuna API
uv run demogen generate "..." --music "acid techno, cassa dritta"    # musica guidata da un prompt
uv run demogen generate "..." --no-music --max-cost 0.5              # demo muta, tetto di spesa del run
uv run demogen generate "..." --loop                                 # loop continuo (senza flag: lo decide il prompt)
uv run demogen generate "..." --profile retro                        # stile retro (320x180, palette a 16 colori) per tutte le scene
uv run demogen generate "..." --review-plan                          # si ferma dopo il piano: lo leggi, lo cambi, poi resume
uv run demogen plan projects/tunnel                                   # mostra il piano: scene, tempi, palette
uv run demogen plan projects/tunnel --scene s1 --description "..."    # cambi tu una scena (anche --title, --motion)
uv run demogen plan projects/tunnel --note "il gatto è nero"          # l'LLM riscrive il piano con la tua nota (una chiamata)
uv run demogen play projects/tunnel --scene s2                        # anteprima di una scena, anche durante la generazione
uv run demogen music projects/tunnel --prompt "synthwave lenta"      # (ri)compone solo la colonna sonora
uv run demogen resume projects/tunnel                                 # riprende senza rifare le chiamate fatte
uv run demogen revise projects/tunnel --scene s2 --note "meno nebbia, più contrasto sul kick"
uv run demogen report projects/tunnel                                 # stampa report.md
```

Il progetto contiene `spec.json`, `style.glsl`, `scenes/<id>/vN.*` (sorgenti, probe, critiche,
math dell'oracolo), `llm_calls/` (log redatti), `state.json` (step fatti, spesa) e `out/` con
`<titolo>.demo` + `<titolo>.html` standalone: click per avviare, poi una barra di controlli con
Start/Pausa, Stop (torna all'inizio), Loop continuo on/off, posizione cliccabile e tempo, e se la
demo ha musica mute e volume, ricordati alla prossima apertura (tasti: spazio, S, L, M, frecce
su/giù). La pagina segue la finestra: ridimensionandola il player adatta risoluzione e grafica,
anche in pausa; le scene retro (risoluzione interna fissa) mantengono le proporzioni con bande nere.
`resume`, `revise` e `music` accettano anche `--fake`. Lo stile (`--profile modern|retro`, default modern) è
la scelta dell'utente e vale per tutte le scene: l'LLM non può cambiarlo scena per scena.

**Revisione del piano e anteprime.** Il primo passo scrive il piano in `spec.json`: scene (cosa si vede,
come si muove), tempi, palette, direzione artistica. È una chiamata economica; la maggior parte della
spesa arriva dopo, mentre le scene vengono disegnate e giudicate. Con `--review-plan` (nel menu: "review
the plan first", sì di default) la generazione si ferma lì: `demogen plan` mostra il piano, `--scene s1
--description/--title/--motion` cambia una scena senza chiamare l'LLM, `--note "..."` chiede all'LLM di
riscrivere il piano (i flag della CLI vincono comunque: durata, BPM, stile, loop) e `demogen resume` lo
disegna. Il piano si cambia solo prima del passo dello stile; dopo, una scena si cambia con `revise`.
`demogen play <progetto> --scene s1 [--version N]` mostra una scena in loop come apparirà nella demo
(stile del progetto, funzioni dell'oracolo, post-processing; di default la versione migliore finora,
altrimenti l'ultima), anche mentre la generazione è in corso: legge soltanto il progetto. I 16 fotogrammi
visti dal critico sono in `scenes/<id>/vN.probe/contact.png`. Nel menu: Plan e Preview (che propone anche
di aprire il foglio dei fotogrammi).

![Foglio dei fotogrammi: 16 fotogrammi di una demo in un'unica immagine, ciascuno con tempo e battuta](docs/img/whisker-hunt-contact.png)

*Il foglio dei fotogrammi che il critico giudica: 16 fotogrammi distribuiti sulla demo, ciascuno con tempo e
battuta (qui `demogen inspect` su `examples/whisker_hunt.timeline.json`).*

**Musica.** Dopo gli shader il ruolo `composer` scrive la colonna sonora (`mainAudio` in GLSL, sul
BPM della demo), guidata da `--music` o, se manca, dal prompt della demo. Viene ascoltata in
automatico: compilazione, volume, NaN, costo di calcolo (≥ 10× il tempo reale), colpi forti sulla
griglia ritmica, distorsione, battute mute; se c'è un problema bloccante il compositore la rivede.
Versioni in `audio/vN.*` con spettrogramma; `--no-music` fa una demo muta.

In un terminale `generate`, `resume` e `revise` mostrano un pannello dal vivo: passi S0–S9 con la
barra di avanzamento, ogni scena con fase, versione, costo e voto, le chiamate LLM in corso col tempo
che scorre e i crediti spesi sul tetto. `--plain` (o output rediretto, o `DEMOGEN_PLAIN=1`) lascia il
solo log testuale.

**Perf.** Ogni scena è misurata in multipli di una scena di riferimento
(`demogen/critic/reference_scene.glsl`: tunnel in raymarching, 96 passi, normali, soft shadow),
nello stesso browser e alla stessa risoluzione, quindi il controllo vale anche su SwiftShader.
Oltre 4× (`realtime.max_ref_ratio_p95`) la scena è bloccante e l'LLM deve alleggerirla; nel bundle
finale l'eccesso resta un avviso nel report. Con `--gpu hardware` valgono in più i budget in ms
assoluti sulla GPU reale; prima si toglie il costo fisso della misura (una scena vuota con la stessa resa:
sincronizzazione con la GPU e composizione del player, qualche ms su alcune GPU), che scalato alla
risoluzione del budget bocciava anche una scena vuota. I budget sono tarati sulla macchina di sviluppo
(Apple Silicon): su una GPU più lenta una scena può sforare lì e andare bene sul target. Il player, se una
demo è lenta, scende fino a 1/4 della risoluzione.

### Altri comandi

```bash
uv run demogen play examples/timeline.json        # rendering realtime in finestra (anche .glsl singolo)
uv run demogen inspect examples/timeline.json     # metriche + gate + fogli in out/inspect_*/
uv run demogen bundle examples/timeline.json --out out   # .demo + .html da una timeline scritta a mano
uv run demogen probe examples/timeline.json --gpu swiftshader
uv run demogen calibrate --gpu hardware           # ms dei 4 shader di esempio (informativo)
uv run demogen still examples/shaders/terrain.glsl --gpu hardware --width 7680 --height 4320 --spp 16
                                                  # sperimentale: un PNG ad alta risoluzione (tile + campioni sub-pixel)
```

Esempi pronti in `examples/web/`, da aprire con un doppio click: per esempio `whisker-hunt.html`
(un gatto arancione in pixel art caccia una falena; anche la voce `cats` del menu), `penguin.html` e
`edge-horizon.html` (uno shader vivo come sfondo della hero di un sito: griglia di puntini, pianeta
ghiacciato disegnato come un progetto, impulsi di rete, loop di 128 s senza giunture, in pausa fuori
schermo; anche la voce `horizon` del menu); vedi `examples/web/README.md`. La sua compagna
`examples/edge_blueprint.timeline.json` è lo sfondo del resto della pagina: la griglia di puntini da
disegno tecnico con un "+" ogni 5 puntini, che respira a onde lente (fissa dietro le sezioni, 30 fps,
1,5 KB gzip). `play` e `inspect` su un singolo shader di una timeline usano common, testo e
stile di quella timeline.

![whisker hunt: un gattino arancione in pixel art seduto su fondo verde petrolio scuro, con la barra dei controlli del player](docs/img/whisker-hunt.png)

*`whisker-hunt.html`: profilo retro (320×180, ingrandito senza sfumature) e la barra dei controlli della
pagina autonoma. L'immagine in cima è `edge-horizon.html` a tutto schermo.*

### Server MCP: la demo la scrive un agente esterno

`demogen mcp` fa di demogen un motore puro: un agente (Claude Code, Claude Desktop, qualunque client
MCP) scrive shader, style e timeline come file, e demogen li compila, li rende, li misura e ne fa il
bundle. Dal lato di demogen non gira nessun LLM, quindi niente chiavi e niente spesa.

| Strumento | Cosa fa |
|---|---|
| `guide` | flusso di lavoro, formato dei file, contratto GLSL e gate: l'agente la legge per prima |
| `glsl_library` | le funzioni della libreria che una scena può chiamare senza definirle (`query` filtra) |
| `validate` | compila nel player vero; gli errori tornano come `file:riga: messaggio` |
| `render` | fotogrammi ai tempi chiesti, in un'unica immagine (i PNG restano in `out/mcp/`) |
| `render_still` | un'immagine ad alta risoluzione (tile + campioni sub-pixel, bloom, gate): anteprima e ritaglio 1:1 |
| `inspect` | i gate della pipeline: NaN, nero, sfarfallio, giunta del loop, flash WCAG, perf, dimensione |
| `verify_math` | l'oracolo matematico: le formule verificate (SDF, Lipschitz, periodo, easing) diventano GLSL |
| `bundle` | payload `.demo` + `.html` autonomo |

```bash
uv run demogen mcp --root <cartella del progetto> [--gpu hardware|swiftshader]   # stdio
claude mcp add demogen -- uv --directory <cartella di demogen> run demogen mcp --root <cartella del progetto>
```

In questo repository `.mcp.json` dichiara già il server per Claude Code (va approvato una volta). I
percorsi degli strumenti sono relativi a `--root` (meglio un percorso assoluto) e non ne possono uscire;
gli `examples/` di demogen si leggono sempre. Il browser si apre alla prima richiesta e resta aperto
(`--gpu hardware` ripiega su SwiftShader se manca la GPU). Anche la voce `mcp` del menu.

### Test

```bash
uv run ruff check .
uv run pytest                        # i test con il browser vanno in skip solo se Chromium manca (in CI falliscono)
npm run typecheck --workspace player
npm test --workspace player
```

Golden dei frame: `DEMOGEN_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` li rigenera
(da fare solo dopo un controllo a vista). I test `live`/`perf` sono esclusi di default.
