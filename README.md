# demogen

Generatore **offline** di demo realtime stile demoscene da un prompt testuale.

- L'utente digita un prompt; un LLM scrive gli shader GLSL (GLSL ES 3.00, contratto `mainImage`).
- Il **motore di rendering creato da noi** (player WebGL2) renderizza la demo in realtime: su macOS sfrutta la GPU (ANGLE → Metal), con **fallback su CPU** (SwiftShader) quando la GPU non è disponibile.
- Un LLM con visione analizza i frame catturati dal motore e itera (critica → revisione).
- Consumo GPU e LLM confinato alla fase di generazione. Nessun output video nel primo step.

 Vedi `docs/demogen-piano-implementazione.md` (piano v2) e `docs/piano-esecuzione.md` (roadmap di esecuzione).

## Setup

```bash
uv sync                              # ambiente Python
uv run playwright install chromium   # browser per il motore/harness
npm install                          # workspace player
npm run build                        # build del player (dist/)
```

## Comandi rapidi (Fase 0)

```bash
uv run demogen doctor                # verifica ambiente + renderer GPU/CPU
uv run python -m demogen.browser.spike   # cattura PNG e ms/frame in out/ (GPU + CPU)
uv run demogen play shader.glsl      # rendering realtime in finestra
uv run pytest                        # test Python
npm test --workspace player          # test TypeScript
```
