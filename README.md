# demogen

Generatore **offline** di demo realtime stile demoscene da un prompt testuale.

- L'utente digita un prompt; un LLM scrive gli shader GLSL (GLSL ES 3.00, contratto `mainImage`).
- Il **motore di rendering creato da noi** (player WebGL2) renderizza la demo in realtime: su macOS sfrutta la GPU (ANGLE → Metal), con **fallback su CPU** (SwiftShader) quando la GPU non è disponibile.
- Un LLM con visione analizza i frame catturati dal motore e itera (critica → revisione), dopo gate numerici (NaN, nero, flicker, flash WCAG 2.3.1, perf, dimensione).
- Consumo GPU e LLM confinato alla fase di generazione. Nessun output video nel primo step.

Vedi `docs/demogen-piano-implementazione.md` (piano v2), `docs/piano-esecuzione.md` (roadmap) e
`docs/review-piano-correzione.md` (review e correzioni).

## Setup

```bash
uv sync                              # ambiente Python (3.11+)
uv run playwright install chromium   # browser per il motore/harness
npm install                          # workspace player
npm run build                        # build del player (player/dist/)
uv run demogen doctor                # verifica ambiente + renderer GPU/CPU
```

## Configurazione LLM

```bash
uv run demogen init                  # crea demogen.yaml dal template demogen/demo.yaml
uv run demogen models check          # prova ogni ruolo (testo / vision / json) con una chiamata minima
```

`demogen.yaml` è in `.gitignore`: la chiave OpenRouter può stare in `providers.openrouter.api_key`
(solo lì) oppure in una variabile d'ambiente indicata da `api_key_env`. Ruoli: `orchestrator`,
`critic` (serve vision), `math`, `fixer`, `composer`. In `pricing` i prezzi per milione di token
(usati se il provider non restituisce il costo) e in `budget` il tetto di spesa e di tempo.

## Generare una demo

```bash
uv run demogen generate "tunnel neon che pulsa sul kick" --duration 30 --bpm 128 --project projects/tunnel
uv run demogen generate "plasma 8s" --project projects/t --fake      # LLM finto, nessuna API
uv run demogen resume projects/tunnel                                 # riprende senza rifare le chiamate fatte
uv run demogen revise projects/tunnel --scene s2 --note "meno nebbia, più contrasto sul kick"
uv run demogen report projects/tunnel                                 # stampa report.md
```

Il progetto contiene `spec.json`, `style.glsl`, `scenes/<id>/vN.*` (sorgenti, probe, critiche,
math dell'oracolo), `llm_calls/` (log redatti), `state.json` (step fatti, spesa) e `out/` con
`<titolo>.demo` + `<titolo>.html` standalone (click per avviare, spazio per pausa/play).
`resume` e `revise` accettano anche `--fake`. Con `--gpu hardware` i gate perf usano la GPU reale;
su SwiftShader (default) sono solo informativi.

## Altri comandi

```bash
uv run demogen play examples/timeline.json        # rendering realtime in finestra (anche .glsl singolo)
uv run demogen inspect examples/timeline.json     # metriche + gate + fogli in out/inspect_*/
uv run demogen bundle examples/timeline.json --out out   # .demo + .html da una timeline scritta a mano
uv run demogen probe examples/timeline.json --gpu swiftshader
uv run demogen calibrate --gpu hardware           # ms dei 4 shader di esempio (informativo)
```

## Test

```bash
uv run ruff check .
uv run pytest                        # i test con il browser vanno in skip solo se Chromium manca (in CI falliscono)
npm run typecheck --workspace player
npm test --workspace player
```

Golden dei frame: `DEMOGEN_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` li rigenera
(da fare solo dopo un controllo a vista). I test `live`/`perf` sono esclusi di default.
