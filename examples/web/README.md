# Esempio web del player demogen

La pagina usa il motore di rendering come **libreria** in una pagina web
standard: nessun build proprietary, solo un `<script type="module">`.

## Avvio

Le pagine funzionano **anche da `file://`** (doppio click sull'HTML): usano lo
script classico `player/dist/demogen-player.min.js` e il payload inline nel tag
(no `fetch`, no moduli ESM — entrambi bloccati da Chrome su `file://`).

```bash
npm run build --workspace player     # genera player/dist/ (esm + min.js + types)
# poi apri direttamente:
#   examples/web/8bit.html   → embed 8bit
#   examples/web/index.html  → demo M1 fullscreen
# In alternativa, via HTTP server (utile per la variante ESM con fetch):
#   python -m http.server 8000  →  http://localhost:8000/examples/web/
```

## File

- `index.html` — pagina demo: custom element `<demogen-player src="./demo.demo.json">`
  a schermo intero, con snippet commentati per payload inline e API programmatica.
- `demo.demo.json` — payload `.demo` generato da `examples/timeline.json`:
  `uv run demogen bundle examples/timeline.json --out /tmp/x && cp /tmp/x/*.demo examples/web/demo.demo.json`
- `8bit.html` — **embed 8bit stile sito** (come le animazioni pixelate di mistral.ai):
  canvas 320×180 profilo retro, payload `8bit.demo.json` di soli **2,5 KB gzip**,
  rendering realtime sulla GPU del visitatore → zero banda, zero video.
- `retro8bit.timeline.json` — spec usata per rigenerare `8bit.demo.json`:
  `uv run demogen bundle examples/web/retro8bit.timeline.json --name 8bit --out /tmp/x && cp /tmp/x/8bit.demo examples/web/8bit.demo.json`
- `penguin.html` — demo test **"penguin walk"**: pinguino pixel-art con camminata goffa
  che attraversa la scena, si ferma, salta gridando "HI!", e torna indietro in loop (16 s).
  Palette pastello, gate epilettico verde (`demogen inspect`: flash passed, 0 blocker).
  Sorgenti: `examples/penguin.timeline.json` + `examples/shaders/penguin_walk.glsl` +
  `examples/penguin_common.glsl`; payload `penguin.demo.json` (~3,3 KB gzip), rigenerabile con
  `uv run demogen bundle examples/penguin.timeline.json --out /tmp/x && cp /tmp/x/penguin-walk.demo examples/web/penguin.demo.json`

## API esportata (`@demogen/player`)

| Export | Uso |
| --- | --- |
| `Player` | `new Player(canvas, payload, opts)` → `load()`, `play()`, `pause()`, `seek(t)`, `dispose()` |
| `DemogenPlayerElement` | custom element `<demogen-player src="..." autoplay>` (si registra da solo) |
| `parsePayload(json)` | valida/normalizza un payload `.demo` |
| `rendererInfo(gl)`, `isSoftwareRenderer(gl)` | diagnostics GPU (utile per capire se stai usando SwiftShader/CPU) |
| `buildHeader`, `buildFragment` | ricostruiscono il fragment shader completo (utile per debug GLSL) |
| `stateAt(timeline, t)` | stato della timeline al tempo t (scene attiva, transizioni, beat) |
| `QualityController` | kate/adaptive quality (auto-riduzione risoluzione se lento) |

Vedi `docs/player-web-library.md` per i dettagli e `docs/api-libreria-glsl.md`
per il contratto GLSL che gli shader devono rispettare.
