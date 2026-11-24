# CLAUDE.md — demogen

## Scopo (allineato con lo stakeholder)

Motore di rendering **realtime interno** (player WebGL2 nostro), dual-mode: GPU su macOS (ANGLE → Metal) e fallback CPU (SwiftShader). Il consumo di GPU e LLM è confinato alla fase di generazione (prompt → LLM scrive shader → motore renderizza → LLM con visione critica → itera). **Nessun output video nel primo step**; export MP4 e distribuzione web sono posticipati. Vedi `docs/piano-esecuzione.md` §0.

## Stato fasi

- [x] Fase 0 — ✅ M0: scheletro + spike player dual-mode + doctor (commit 73f8260)
- [x] Fase 1 — ✅ M1: player core realtime (timeline/compositor/post-bloom/quality/format/element), libreria GLSL `demogen/glsl/lib` (incl. retro + font 8x8 originale), preprocessor/treeshake(topologico)/minify, harness completo, CLI `play`/`bundle`/`probe`, demo M1 in `examples/` (4 scene, probe OK su GPU e CPU), golden su SwiftShader, player core 6761 B gzip, CI
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
- Play: `uv run demogen play <shader.glsl|timeline.json> [--gpu auto|hardware|swiftshader] [--headless]`
- Bundle: `uv run demogen bundle examples/timeline.json --out out` → `.demo` + `.html`
- Probe: `uv run demogen probe examples/timeline.json --gpu swiftshader|hardware` (PNG + ms in `out/`)
- Rigenera vettori timeline: `uv run python scripts/gen_vectors.py`

## Convenzioni

- Python 3.11+, uv, typer, pydantic v2; ruff line-length 100.
- Player TypeScript **zero dipendenze runtime**; build esbuild (`dist/`), test vitest.
- Shader: GLSL ES 3.00, contratto `mainImage(out vec4, in vec2)` con uniform `iResolution`/`iTime`; il player aggiunge header e `main()`.
- Nessuna chiamata API reale nei test standard (`@pytest.mark.live`); perf su GPU reale solo locale (`@pytest.mark.perf`).
- Le pagine pilotate da Playwright hanno la rete esterna bloccata (solo 127.0.0.1 servito).
- Al termine di ogni fase: test verdi, commit `phase N: <sintesi>`, aggiorna le checkbox qui e in `docs/piano-esecuzione.md`.
