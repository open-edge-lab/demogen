// Sito statico per GitHub Pages: le pagine di examples/web con accanto il player compilato e una galleria come
// pagina iniziale. Nel repo le pagine caricano ../../player/dist/ (si aprono con doppio click dopo la build); qui
// quel percorso diventa player/, così sul sito il player ha un indirizzo stabile da usare negli embed.
//
//   npm run build && npm run site          ->  out/site/  (lo pubblica .github/workflows/pages.yml)
//   node scripts/build-site.mts <cartella> ->  altra cartella di uscita
//
// Solo sintassi TypeScript "cancellabile" (Node >= 22.18 la esegue senza build), come scripts/run.mts.

import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const WEB = join(ROOT, "examples", "web");
const DIST = join(ROOT, "player", "dist");
const OUT = resolve(ROOT, process.argv[2] ?? join("out", "site"));
const REPO_URL = "https://github.com/open-edge-lab/demogen";

/** Una pagina della galleria: file nel sito, titolo e descrizione (testi visibili: inglese). */
interface Card {
  file: string;
  source: string;
  title: string;
  text: string;
  tag: string;
}

// In ordine di vetrina. examples/web/index.html (la demo M1) nel sito diventa m1.html: index è la galleria.
const CARDS: Card[] = [
  {
    file: "dead-channel.html", source: "dead-channel.html", title: "dead channel", tag: "modern · 85 s loop",
    text: "An 80s test card on a CRT gets hacked: block glitches and hex dumps, a hijacked broadcast, then the slow return.",
  },
  {
    file: "whisker-hunt.html", source: "whisker-hunt.html", title: "whisker hunt", tag: "retro 320×180",
    text: "An orange pixel-art cat wakes up, spots a moth and goes hunting.",
  },
  {
    file: "edge-horizon.html", source: "edge-horizon.html", title: "edge horizon", tag: "website hero · 128 s loop",
    text: "A live shader as the background of a website hero: dotted grid, an icy planet drawn as a blueprint, network pulses.",
  },
  {
    file: "penguin.html", source: "penguin.html", title: "penguin walk", tag: "retro · pastel",
    text: "A pixel-art penguin waddles across the screen, stops, jumps shouting \"HI!\" and walks back.",
  },
  {
    file: "8bit.html", source: "8bit.html", title: "8-bit embed", tag: "2.5 KB gzip",
    text: "A 320×180 embed for websites: the whole animation is a 2.5 KB payload rendered by the visitor's GPU, no video.",
  },
  {
    file: "m1.html", source: "index.html", title: "demo M1", tag: "modern · 64 s",
    text: "The first milestone demo, full screen: tunnel, IFS fractal, terrain and a retro plasma.",
  },
];

// File di examples/web che restano fuori dal sito (sorgenti e documentazione, non pagine).
const SKIP = new Set(["README.md", "retro8bit.timeline.json"]);
const PLAYER_FILES = ["demogen-player.min.js", "demogen-player.esm.js"];
const DIST_REF = "../../player/dist/";

function fail(msg: string): never {
  console.error(`build-site: ${msg}`);
  process.exit(1);
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function main(): void {
  for (const f of PLAYER_FILES) {
    if (!existsSync(join(DIST, f))) fail(`player/dist/${f} missing: run npm run build first`);
  }
  for (const c of CARDS) {
    if (!existsSync(join(WEB, c.source))) fail(`examples/web/${c.source} missing (listed in CARDS)`);
  }

  // svuota la cartella senza toglierla: su Windows una cartella aperta (un server di prova, Esplora file) non si
  // può cancellare, il suo contenuto sì
  mkdirSync(OUT, { recursive: true });
  for (const name of readdirSync(OUT)) rmSync(join(OUT, name), { recursive: true, force: true });
  mkdirSync(join(OUT, "player"), { recursive: true });
  for (const f of PLAYER_FILES) copyFileSync(join(DIST, f), join(OUT, "player", f));

  const renamed = new Map(CARDS.map((c) => [c.source, c.file]));
  const extra: Card[] = [];
  for (const name of readdirSync(WEB)) {
    if (SKIP.has(name)) continue;
    const target = renamed.get(name) ?? name;
    if (!name.endsWith(".html")) {
      copyFileSync(join(WEB, name), join(OUT, target));
      continue;
    }
    const html = readFileSync(join(WEB, name), "utf8").split(DIST_REF).join("player/");
    if (html.includes("../../")) fail(`examples/web/${name} still points outside examples/web after the rewrite`);
    writeFileSync(join(OUT, target), html, "utf8");
    // una pagina nuova non ancora in CARDS compare comunque, in fondo, con il titolo dell'HTML
    if (!renamed.has(name)) {
      const title = /<title>([^<]*)<\/title>/.exec(html)?.[1]?.trim() || name;
      extra.push({ file: name, source: name, title, text: "", tag: "" });
    }
  }

  writeFileSync(join(OUT, "index.html"), gallery([...CARDS, ...extra]), "utf8");
  console.log(`build-site: ${CARDS.length + extra.length} pages + gallery -> ${OUT}`);
}

function gallery(cards: Card[]): string {
  const items = cards
    .map((c) => `      <a class="card" href="${escapeHtml(c.file)}">
        <span class="tag">${escapeHtml(c.tag)}</span>
        <h2>${escapeHtml(c.title)}</h2>
        <p>${escapeHtml(c.text)}</p>
      </a>`)
    .join("\n");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>demogen · live demos</title>
  <link rel="icon" href="data:,">
  <meta name="description" content="Realtime demoscene-style demos rendered live in your browser by the demogen WebGL2 player.">
  <style>
    :root { color-scheme: dark; --bg: #0b0b12; --card: #151521; --line: #2a2a3d; --text: #e8e6f0; --dim: #9a97ad; --accent: #b98cff; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
    main { max-width: 1040px; margin: 0 auto; padding: 56px 24px 72px; }
    h1 { margin: 0; font-size: 2.4rem; letter-spacing: -0.02em; }
    .lead { margin: 8px 0 32px; color: var(--dim); max-width: 60ch; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 16px; }
    .card { display: block; padding: 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--card);
            color: inherit; text-decoration: none; transition: border-color .15s, transform .15s; }
    .card:hover, .card:focus-visible { border-color: var(--accent); transform: translateY(-2px); outline: none; }
    .card h2 { margin: 6px 0 6px; font-size: 1.25rem; }
    .card p { margin: 0; color: var(--dim); font-size: .95rem; }
    .tag { color: var(--accent); font: 12px/1 ui-monospace, "Cascadia Code", Menlo, monospace; text-transform: uppercase; letter-spacing: .06em; }
    footer { margin-top: 40px; color: var(--dim); font-size: .9rem; }
    footer a { color: var(--accent); }
    code { font: .9em ui-monospace, "Cascadia Code", Menlo, monospace; color: var(--text); }
    @media (prefers-reduced-motion: reduce) { .card { transition: none; } .card:hover { transform: none; } }
  </style>
</head>
<body>
  <main>
    <h1>demogen</h1>
    <p class="lead">Realtime demoscene-style demos. Each page is a few kilobytes of GLSL rendered live by the
      demogen WebGL2 player on your GPU: no video files. Some pages contain flickering and glitch effects.</p>
    <section class="grid">
${items}
    </section>
    <footer>
      <p>Source, generator and docs: <a href="${REPO_URL}">${REPO_URL.replace("https://", "")}</a>.
        Player for your own pages: <code>player/demogen-player.min.js</code> (classic script) or
        <code>player/demogen-player.esm.js</code> (ES module) from this site.</p>
    </footer>
  </main>
</body>
</html>
`;
}

main();
