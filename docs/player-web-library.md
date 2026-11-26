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
- eventi: `demogen-ready` a player pronto; `demogen-error` (in `detail` l'errore, anche HTTP non 2xx)
  con l'attributo `data-error` sul tag. Spostare il tag nel DOM non crea un secondo player; rimuoverlo
  annulla il fetch in corso e libera tutto (`dispose`).

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

Opzioni di `new Player(canvas, payload, opts)`:

| Opzione | Default | Note |
| --- | --- | --- |
| `autoPlay` | `true` | parte dopo `load()` |
| `autoResize` | `true` | il buffer del canvas segue la dimensione CSS × devicePixelRatio (max 2) con un `ResizeObserver` (più `resize` della finestra per i cambi di devicePixelRatio); in pausa o a demo finita il frame corrente viene ridisegnato alla nuova dimensione; `false` se la dimensione la gestisci tu |
| `audioContext` | — | un `AudioContext` già creato e sbloccato **nel gesto utente** (click): senza, l'audio parte al primo click/tasto successivo |
| `flashLimit` | `1` | limite fotosensibilità (0..1) per `beatFlash` e le transizioni flash; il player lo abbassa comunque sotto soglia WCAG se i beat superano 3/s o con `prefers-reduced-motion` |
| `volume` / `muted` | `1` / `false` | volume iniziale della musica (0..1) e mute |
| `preserveDrawingBuffer` | `false` | serve solo per catturare frame con `toDataURL` |
| `onReady` / `onError` / `onQualityChange` | — | callback |

`pause()` conserva la posizione (con l'audio attivo, quella del clock audio); `play()` riprende da lì.
`stop()` mette in pausa e torna all'inizio (a schermo resta il primo frame). `setLoop(on)` attiva o
disattiva il loop continuo anche durante la riproduzione (l'audio riparte dalla stessa posizione);
`loop` e `ended` dicono lo stato. In loop il tempo (video e audio) è modulo durata; senza loop la demo
si ferma alla fine e `play()` riparte da capo. `seek(t)` in pausa ridisegna subito il frame.
`volume` (0..1) e `muted` si leggono e si impostano anche durante la riproduzione (rampa di 15 ms, niente
click); `hasAudio` dice se la demo ha una colonna sonora.

La pagina `.html` del bundle ha una barra di controlli (Start/Pausa, Stop, Loop on/off, posizione
cliccabile, tempo e, se c'è musica, mute e volume salvati in `localStorage`) che si nasconde mentre la
demo va e ricompare muovendo il mouse; tasti: spazio, S (stop), L (loop), M (mute), frecce su/giù
(volume ±10%). Il canvas occupa la finestra e la segue quando viene ridimensionata; le scene retro, a risoluzione interna
fissa, mantengono le proporzioni con bande nere invece di essere stirate. `dispose()` libera
programmi, FBO, listener,
`ResizeObserver` e audio (chiude l'`AudioContext` solo se l'ha creato il player).

## Embed 8bit stile sito (zero banda)

Vedi `examples/web/8bit.html`: un `<demogen-player>` 320×180 (profilo retro,
upscale nearest) dentro un frame CSS, payload `8bit.demo.json` di **2,5 KB gzip**.
Per mostrarlo nel tuo sito copia solo due file: `demogen-player.esm.js` e il
`.demo.json`, poi incolla il tag. Servire via HTTP (no `file://`, per la fetch).

## API esportata

| Export | Note |
| --- | --- |
| `Player` | `new Player(canvas, payload, opts)`; `load/play/pause/stop/seek/setLoop/dispose`, `isPlaying`, `loop`, `ended`, `volume`, `muted`, `hasAudio`, `currentTime()`, `gl`, `durationS` |
| `DemogenPlayerElement` | custom element `<demogen-player>` (auto-registrato se c'è DOM) |
| `parsePayload` / `textToUniform` / `textByteLength` | validazione payload `.demo` (max 1 MB, bpm/bars > 0); testo scroller in byte UTF-8 (max 256) |
| `PlaybackClock` | clock puro play/pause/seek/loop (usato dal player, testabile senza DOM) |
| `chunkSchedule` | chunk audio e offset per un tempo dato (scheduling del primo campione) |
| `stateAt` | stato timeline al tempo t (scene, transizioni, beat) |
| `QualityController` | quality adattiva (riduce la risoluzione interna se lento) |
| `rendererInfo` / `isSoftwareRenderer` | info GPU / detect CPU fallback |
| `buildHeader` / `buildFragment` | ricostruiscono il fragment shader (debug GLSL) |

Contratto GLSL degli shader: vedi `docs/api-libreria-glsl.md`.
Esempi completi: `examples/web/index.html` (demo M1 fullscreen) e
`examples/web/8bit.html` (embed 8bit per siti).
