# CLAUDE.md — demogen

## Scopo (allineato con lo stakeholder)

Motore di rendering **realtime interno** (player WebGL2 nostro), dual-mode: GPU su macOS (ANGLE → Metal) e fallback CPU (SwiftShader). Il consumo di GPU e LLM è confinato alla fase di generazione (prompt → LLM scrive shader → motore renderizza → LLM con visione critica → itera). **Nessun output video nel primo step**; export MP4 e distribuzione web sono posticipati. Vedi `docs/piano-esecuzione.md` §0.

## Stato fasi

- [x] Fase 0 — ✅ M0: scheletro monorepo + spike player WebGL2 dual-mode (GPU reale via full Chromium `channel="chromium"`, CPU via SwiftShader) + harness Playwright + `demogen doctor` + spike PNG/ms in `out/`
- [ ] Fase 1 — player core realtime (profili, libreria GLSL, harness, CLI play)
- [ ] Fase 2 — audio
- [ ] Fase 3 — livello LLM
- [ ] Fase 4 — metriche e gate
- [ ] Fase 5 — orchestratore (pipeline completa)
- [ ] Fase 6 — oracolo matematico
- [ ] Fase 7 — distribuzione/export (posticipata)

## Comandi

- Python: `uv sync`, test `uv run pytest`, CLI `uv run demogen <cmd>`
- Browser Playwright: `uv run playwright install chromium`
- Player: `npm install`, build `npm run build`, test `npm test --workspace player`
- Spike: `uv run python -m demogen.browser.spike` (PNG + ms/frame in `out/`)
- Doctor: `uv run demogen doctor`
- Play: `uv run demogen play <shader.glsl> [--gpu auto|hardware|swiftshader] [--headless]`

## Convenzioni

- Python 3.11+, uv, typer, pydantic v2; ruff line-length 100.
- Player TypeScript **zero dipendenze runtime**; build esbuild (`dist/`), test vitest.
- Shader: GLSL ES 3.00, contratto `mainImage(out vec4, in vec2)` con uniform `iResolution`/`iTime`; il player aggiunge header e `main()`.
- Nessuna chiamata API reale nei test standard (`@pytest.mark.live`); perf su GPU reale solo locale (`@pytest.mark.perf`).
- Le pagine pilotate da Playwright hanno la rete esterna bloccata (solo 127.0.0.1 servito).
- Al termine di ogni fase: test verdi, commit `phase N: <sintesi>`, aggiorna le checkbox qui e in `docs/piano-esecuzione.md`.
