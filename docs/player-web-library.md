# Player come libreria web (`@demogen/player`)

Il motore di rendering è una libreria TypeScript **zero dipendenze runtime**,
usabile in qualsiasi pagina web. Renderizza in realtime via WebGL2 sulla GPU
del visitatore (su Mac ANGLE→Metal; fallback CPU SwiftShader automatico se
WebGL2 manca): **nessun video, nessun consumo di banda dopo il load**.

## Build

```bash
npm run build --workspace player
# → player/dist/demogen-player.esm.js   (ESM, per <script type="module"> e bundler)
# → player/dist/demogen-player.min.js   (IIFE, globale `demogenPlayer`, per <script src>)
# → player/dist/types/index.d.ts        (tipi TypeScript)
```

`player/package.json` ha `exports`/`main`/`module`/`types`, quindi con un
bundler basta `import { Player } from "@demogen/player"`.

## Uso 1 — custom element (più semplice)

```html
<script type="module" src="./demogen-player.esm.js"></script>
<demogen-player src="./8bit.demo.json" autoplay style="width:320px;aspect-ratio:16/9"></demogen-player>
```

- `src` — URL di un payload `.demo` (JSON, tipicamente 2–12 KB gzip).
- inline: senza `src`, legge `<script type="application/json">` dentro il tag.
- attributi: `autoplay` (default on, `autoplay="none"` per disattivarlo), `loop`.

## Uso 2 — API programmatica

```html
<script type="module">
  import { Player, parsePayload, rendererInfo } from "./demogen-player.esm.js";
  const canvas = document.querySelector("#stage");
  const payload = parsePayload(await (await fetch("./8bit.demo.json")).json());
  const player = new Player(canvas, payload, { autoPlay: true });
  await player.load();
  console.log(rendererInfo(player.gl)); // diagnostics: renderer reale (es. SwiftShader = CPU)
  player.seek(4); player.pause(); player.play(); player.dispose();
</script>
```

## Embed 8bit stile sito (zero banda)

Vedi `examples/web/8bit.html`: un `<demogen-player>` 320×180 (profilo retro,
upscale nearest) dentro un frame CSS, payload `8bit.demo.json` di **2,5 KB gzip**.
Per mostrarlo nel tuo sito copia solo due file: `demogen-player.esm.js` e il
`.demo.json`, poi incolla il tag. Servire via HTTP (no `file://`, per la fetch).

## API esportata

| Export | Note |
| --- | --- |
| `Player` | `new Player(canvas, payload, opts)`; `load/play/pause/seek/dispose`, `gl`, `duration` |
| `DemogenPlayerElement` | custom element `<demogen-player>` (auto-registrato se c'è DOM) |
| `parsePayload` / `textToUniform` | validazione payload `.demo` |
| `stateAt` | stato timeline al tempo t (scene, transizioni, beat) |
| `QualityController` | quality adattiva (riduce la risoluzione interna se lento) |
| `rendererInfo` / `isSoftwareRenderer` | info GPU / detect CPU fallback |
| `buildHeader` / `buildFragment` | ricostruiscono il fragment shader (debug GLSL) |

Contratto GLSL degli shader: vedi `docs/api-libreria-glsl.md`.
Esempi completi: `examples/web/index.html` (demo M1 fullscreen) e
`examples/web/8bit.html` (embed 8bit per siti).
