# Esempio web del player demogen

La pagina usa il motore di rendering come **libreria** in una pagina web
standard: nessun build proprietary, solo un `<script type="module">`.

## Avvio

Dalla root del repo:

```bash
npm run build --workspace player     # genera player/dist/demogen-player.esm.js (+ .min.js + types)
python -m http.server 8000           # qualsiasi HTTP server statico va bene
# apri http://localhost:8000/examples/web/
```

> Serve un HTTP server: `fetch("./demo.demo.json")` non funziona da `file://`.

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
