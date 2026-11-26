# CLAUDE.md — demogen

## Scopo (allineato con lo stakeholder)

Motore di rendering **realtime interno** (player WebGL2 nostro), dual-mode: GPU su macOS (ANGLE → Metal) e fallback CPU (SwiftShader). Il consumo di GPU e LLM è confinato alla fase di generazione (prompt → LLM scrive shader → motore renderizza → LLM con visione critica → itera). **Nessun output video nel primo step**; export MP4 e distribuzione web sono posticipati. Vedi `docs/piano-esecuzione.md` §0.

## Stato fasi

- [x] Fase 0 — ✅ M0: scheletro + spike player dual-mode + doctor (commit 73f8260)
- [x] Fase 1 — ✅ M1: player core realtime, libreria GLSL, harness, CLI play/bundle/probe, demo M1, golden, CI (commit 301bd6c)
- [x] Fase 3 — ✅ M3 (CI): livello LLM completo — config, client, envelope/structured, capabilities, budget, `demogen init` + `models check` (commit 55267e3)
- [x] Fase 4 — ✅ M4: metriche video/perf/flash + gate numerici + sheets (contact/burst/diff/perf) + `demogen inspect`/`calibrate`; harness con stats float (NaN/Inf) e cellSequence; 10 test sintetici gate + E2E inspect; pytest 31/31
- [x] Fase 5 — ✅ M5 (CI): orchestratore S0–S9, prompt Jinja, FakeLLM `--fake`, CLI generate/resume/revise/report, E2E finto verde (~23 s)
- [x] Fase 2 — ✅ M2: audio GPU a blocchi (`player/src/audio.ts`) + chip.glsl + metrics_audio + gate onset; demo `examples/audio_chip.timeline.json` (onset err 1.5 ms)
- [x] Fase 6 — ✅ M6: oracolo matematico `demogen/math/` (safe_parse subprocess, verify sdf/lipschitz/period/easing, codegen GLSL), integrato in S2/S7/S9 via math_requests → `vN.math.glsl`
- [ ] Fase 7 — distribuzione/export (posticipata)
- [x] Fase 9 — ✅ server MCP (`demogen mcp`, `demogen/mcp_server.py`): un agente esterno scrive shader/style/timeline, demogen compila, rende, misura (gate) e fa il bundle; nessun LLM lato demogen

## Comandi

- Python: `uv sync`, test `uv run pytest`, CLI `uv run demogen <cmd>`
- Browser Playwright: `uv run playwright install chromium`
- Player: `npm install`, build `npm run build`, test `npm test --workspace player`
- Spike: `uv run python -m demogen.browser.spike` (PNG + ms/frame in `out/`)
- Doctor: `uv run demogen doctor`
- LLM: `uv run demogen init` (crea `demogen.yaml`, gitignored, dal template `demogen/demo.yaml`; chiave in `api_key` o env `api_key_env`), `uv run demogen models check` (tabella ruoli; live, manuale)
- Play: `uv run demogen play <shader.glsl|timeline.json> [--gpu auto|hardware|swiftshader] [--headless]`
- Bundle: `uv run demogen bundle examples/timeline.json --out out` → `.demo` + `.html`
- Probe: `uv run demogen probe examples/timeline.json --gpu swiftshader|hardware` (PNG + ms in `out/`)
- Inspect: `uv run demogen inspect examples/timeline.json --gpu swiftshader` (metriche+gate+fogli in `out/inspect_*/`)
- Calibrate: `uv run demogen calibrate --gpu hardware` (ms dei 4 shader examples → `out/calibrate.json`)
- Generate (pipeline LLM completa): `uv run demogen generate "<prompt>" --project projects/x [--fake] [--duration 30] [--bpm 120] [--profile modern|retro] [--gpu hardware|swiftshader] [--music "<prompt musica>" | --no-music] [--max-cost USD] [--loop | --no-loop] [--review-plan]` → `out/*.demo|*.html` + `report.md`; `resume <progetto> [--fake]` (niente chiamate già fatte), `revise <progetto> --scene s1 --note "nota" [--fake]` (versione max+1), `music <progetto> [--prompt "..."] [--fake]` (colonna sonora: ruolo `composer`, `demogen/orchestrator/music.py`, step SM, `audio/vN.*`), `report <progetto>`; `--review-plan` si ferma dopo S0 (`state["paused"]="plan"`), `plan <progetto> [--scene s1 --title/--description/--motion | --note "..." [--fake]]` mostra e cambia il piano finché S1 non è fatto (`demogen/orchestrator/plan.py`, nota → `s0_replan`), poi `resume`; anteprima di una scena: `play <progetto> --scene s1 [--version N]` (`demogen/orchestrator/preview.py`, sola lettura, va anche a generazione in corso); lo stile (`--profile`) è dell'utente e vale per tutte le scene (`apply_request` toglie gli override per scena dell'LLM); in un terminale pannello dal vivo (`demogen/dashboard.py`, eventi da `demogen/progress.py`), `--plain` per il log semplice. Perf: gate relativo alla scena di riferimento (`demogen/critic/perf_ref.py`, max 4×), valido anche su SwiftShader
- Menu: `npm run menu` (Windows: anche doppio click su `run.cmd`; macOS/Linux: `sh run.sh`) avvia `demogen menu` (`demogen/menu.py`, stile del pannello): tutta l'app (generate/resume/plan/revise/music/report/preview, esempi, setup/test/config, tetti di spesa, processi); `--action <nome> [--yes]` senza menu (`--action list`), `--setup` per `uv sync`. Il lanciatore è `scripts/run.mts` (Node ≥ 22.18 esegue il TypeScript senza build; `npm run typecheck:scripts`)
- MCP: `uv run demogen mcp --root <progetto> [--gpu hardware|swiftshader]` (stdio; strumenti guide/glsl_library/validate/render/inspect/verify_math/bundle; percorsi confinati in `--root`, risultati in `<root>/out/mcp/`); `.mcp.json` lo dichiara per Claude Code; misure e gate condivisi con la CLI in `demogen/engine.py`
- Tetti di consumo LLM: `budget:` in `demogen.yaml` (`max_total_cost_usd` per run, `max_daily_cost_usd`, `max_monthly_cost_usd` su tutte le generazioni dal registro `<cache_dir>/spend.jsonl`, `max_calls_per_run`, `max_wall_minutes`); `uv run demogen budget [--daily 3 --monthly 20 --calls 80 --run 1]` mostra la spesa e li imposta
- Testi visibili all'utente (CLI, pannello, menu, report, pagina del player, messaggi all'LLM) in **inglese**; commenti, docstring e guide in italiano. Il `README.md` ha due sezioni, English sopra e Italiano sotto: ogni modifica va fatta in entrambe
- Libreria web: il player è esportato da `player/src/index.ts` — build ESM/IIFE/types con `npm run build --workspace player`; esempi in `examples/web/` (`index.html` demo, `8bit.html` embed 8bit zero-banda); doc `docs/player-web-library.md`
- Rigenera vettori timeline: `uv run python scripts/gen_vectors.py`

## Convenzioni

- Python 3.11+, uv, typer, pydantic v2; ruff line-length 120.
- Player TypeScript **zero dipendenze runtime**; build esbuild (`dist/`), test vitest.
- Shader: GLSL ES 3.00, contratto `mainImage(out vec4, in vec2)` con uniform `iResolution`/`iTime`; il player aggiunge header e `main()`.
- Nessuna chiamata API reale nei test standard (`@pytest.mark.live`); perf su GPU reale solo locale (`@pytest.mark.perf`).
- Le pagine pilotate da Playwright hanno la rete esterna bloccata (solo 127.0.0.1 servito).
- Al termine di ogni fase: test verdi, commit `phase N: <sintesi>`, aggiorna le checkbox qui e in `docs/piano-esecuzione.md`.
- Repo remoto: `origin` = https://github.com/open-edge-lab/demogen.git (pubblico). **Mai committare file sensibili**: `.gitignore` esclude `demogen.yaml` (config locale con chiave), `.env*`, `*.pem/key/p12/pfx`, `id_rsa*`, `secrets/`, `*credentials*`, `llm_calls/`, `*.log`. Prima di ogni push scansiona la history per pattern di chiavi (`sk-…`, `ghp_…`, `AKIA…`, `BEGIN … PRIVATE KEY`).
