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
- `whisker-hunt.html` — **"whisker hunt"**, pagina autonoma (player e payload dentro l'HTML, controlli,
  si apre con doppio click o dalla voce `cats` del menu): rifacimento a mano della demo generata "Whisker Idle" con gli stessi colori.
  Gattino che si sveglia; il gatto arancione del finale (stesso disegno e stessa misura in tutte le
  scene) seduto che vede arrivare una falena; la caccia (si acquatta scodinzolando, dimena il sedere,
  salta in avanti, si rimette composto e la guarda volare via in alto, poi si siede dove lo trova la
  dissolvenza); dissolvenza finale. Il gattone rosa della demo generata non c'è più. 8,75 s a 128 BPM,
  retro 320×180, gate flash verde, 0 blocker.
  Sorgenti: `examples/whisker_hunt.timeline.json` + `examples/whisker_common.glsl` +
  `examples/shaders/whisker_*.glsl`; rigenerabile con
  `uv run demogen bundle examples/whisker_hunt.timeline.json --out /tmp/x && cp /tmp/x/whisker-hunt.html examples/web/ && cp /tmp/x/whisker-hunt.demo examples/web/whisker-hunt.demo.json`

- `edge-horizon.html` — **"edge horizon"**, sfondo vivo per la hero di un sito nello stile di
  openedge.consulting (fondo slate-950, griglia di puntini al 6%, ciano #22D3EE e accenti rosa #EC4899):
  pianeta ghiacciato in basso disegnato come un progetto (meridiani, paralleli tratteggiati, rete di nodi
  con impulsi), onde di dati che accendono i puntini, alone che vira al rosa a destra. Loop di 128 s
  senza giunture, profilo modern, payload ~3,5 KB gzip inline; la pagina mette in pausa il player quando la
  hero esce dallo schermo o la scheda è nascosta e, con `prefers-reduced-motion: reduce`, mostra un
  fotogramma fermo (t = 40 s). Voce `horizon` del menu.
  Sorgenti: `examples/edge_horizon.timeline.json` + `examples/edge_horizon_common.glsl` +
  `examples/shaders/edge_horizon.glsl`. Per rigenerare il payload inline:
  ```bash
  uv run demogen bundle examples/edge_horizon.timeline.json --out out/eh
  uv run python -c "import re,pathlib as p; f=p.Path('examples/web/edge-horizon.html'); d=p.Path('out/eh/edge-horizon.demo').read_text(encoding='utf-8').strip(); f.write_text(re.sub(r'(<demogen-player id=\"hero-bg\"[^>]*>\s*<script type=\"application/json\">).*?(</script>)', lambda m: m[1]+d+m[2], f.read_text(encoding='utf-8'), count=1, flags=re.S), encoding='utf-8')"
  ```
  Per metterla in un sito: copiare `player/dist/demogen-player.min.js` e `edge-horizon.demo`, poi
  ```html
  <section class="hero" style="position:relative; overflow:hidden">
    <demogen-player id="hero-bg" src="/assets/edge-horizon.demo" autoplay aria-hidden="true"
                    style="position:absolute; inset:0; z-index:0; display:block; pointer-events:none"></demogen-player>
    <!-- contenuti della hero con position:relative; z-index:1 -->
  </section>
  <script src="/assets/demogen-player.min.js"></script>
  ```
  con lo script di pausa/riduci movimento in fondo a `edge-horizon.html` (con `src=` il payload arriva via
  `fetch`, quindi serve HTTP, non `file://`).
  Per il resto della pagina c'è la compagna `examples/edge_blueprint.timeline.json` (stesso style): la
  griglia di puntini da disegno tecnico, con un "+" ogni 5 puntini, che respira a onde lente; 30 fps,
  ~1,5 KB gzip. Va in un `<demogen-player>` con `position:fixed; inset:0; z-index:-1` subito dentro
  `<body>`, con le sezioni sopra semitrasparenti (sul sito: `bg-slate-900/50`, le altre trasparenti) e
  senza la griglia CSS, che ora disegna lo shader; si mette in pausa finché la hero copre lo schermo.

- `dead-channel.html` — **"dead channel"**, pagina autonoma (player e payload dentro l'HTML): un
  monoscopio anni '80 originale (canale "DEMOGEN TV", nessun marchio reale) su un tubo CRT curvo, che a
  mezzanotte viene bucato da un hacker. Quattro scene a 90 BPM, loop di 85 s senza giunture: il monoscopio
  (pulito nella prima metà: è anche l'immagine fissa), l'intrusione (blocchi corrotti, sincronia che salta,
  quadro che scivola, INTRUSION/HACKED, dump esadecimali, il volto dell'entità a blocchi, spegnimento del
  tubo), il segnale dirottato (città cyberpunk al neon sotto la pioggia, terminale che scorre, barra di
  UPLINK fino a HACKED) e il ritorno in palette neon fino al monoscopio di partenza. Profilo modern, bloom
  leggero, ~7,5 KB gzip, gate flash a 2/s (limite 3). Scanline, fosfori e zone plate svaniscono sotto i
  2 pixel (`detailFade`): a 1080p niente moiré, in uno still 8K si vedono tutti.
  Sorgenti: `examples/dead_channel.timeline.json` + `examples/dead_channel_common.glsl` +
  `examples/shaders/dead_channel_*.glsl`; rigenerabile con
  `uv run demogen bundle examples/dead_channel.timeline.json --out /tmp/x && cp /tmp/x/dead-channel.html examples/web/ && cp /tmp/x/dead-channel.demo examples/web/dead-channel.demo.json`;
  immagine 8K: `uv run demogen still examples/dead_channel.timeline.json --time 2 --width 7680 --height 4320 --spp 16 --gpu hardware`

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
