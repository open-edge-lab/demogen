// Harness (SOLO build di test/pipeline, mai distribuito): espone window.__demogen
// con load/capture/lumaSequence/profile/info. Render fuori da rAF, a tempi esatti.

import { AudioEngine } from "./audio";
import { Player } from "./player";
import { parsePayload } from "./format";
import { createGL, rendererInfo, DemogenInfo } from "./gl";
import { stateAt } from "./timeline";

interface HarnessPlayer {
  player: Player;
  canvas: HTMLCanvasElement;
}

let current: HarnessPlayer | null = null;

function ensureCanvas(): HTMLCanvasElement {
  let c = document.getElementById("c") as HTMLCanvasElement | null;
  if (!c) {
    c = document.createElement("canvas");
    c.id = "c";
    document.body.appendChild(c);
  }
  return c;
}

async function load(payload: unknown): Promise<{ ok: boolean; errors: string[]; compile_ms: number }> {
  const errors: string[] = [];
  // un solo player alla volta: il precedente libera programmi, FBO, listener e audio
  current?.player.dispose();
  current = null;
  try {
    const p = parsePayload(payload);
    const canvas = ensureCanvas();
    // autoResize false: la dimensione la decide setSize (capture/profile a w×h esatti)
    const player = new Player(canvas, p, { preserveDrawingBuffer: true, autoPlay: false, autoResize: false });
    const t0 = performance.now();
    await player.load();
    current = { player, canvas };
    return { ok: true, errors, compile_ms: player.compileMs || performance.now() - t0 };
  } catch (e) {
    errors.push(String(e));
    return { ok: false, errors, compile_ms: 0 };
  }
}

function setSize(w: number, h: number): void {
  if (!current) throw new Error("load() prima");
  current.canvas.width = w;
  current.canvas.height = h;
}

function capture(opts: { times: number[]; width: number; height: number }): string[] {
  if (!current) throw new Error("load() prima");
  setSize(opts.width, opts.height);
  return opts.times.map((t) => current!.player.captureDataURL(t));
}

// sRGB 8 bit → lineare [0,1]: la media per cella va fatta in luce lineare (WCAG), non in sRGB
const SRGB_TO_LINEAR = new Float64Array(256);
for (let i = 0; i < 256; i++) {
  const c = i / 255;
  SRGB_TO_LINEAR[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** Come cellSequence ma in un unico blob Float32 base64 (N×celle×3): migliaia di piccoli
 *  array annidati costano molto più del render nella serializzazione verso Playwright. */
function cellSequenceB64(opts: {
  t0: number;
  t1: number;
  fps: number;
  width: number;
  height: number;
  grid?: number;
}): { frames: number; cells: number; data: string } {
  const seq = cellSequence(opts);
  const cells = seq.length ? seq[0].length : 0;
  const f32 = new Float32Array(seq.length * cells * 3);
  let k = 0;
  for (const frame of seq) for (const c of frame) { f32[k++] = c[0]; f32[k++] = c[1]; f32[k++] = c[2]; }
  const bytes = new Uint8Array(f32.buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
  }
  return { frames: seq.length, cells, data: btoa(bin) };
}

/** Per ogni frame (a t0 + i/fps): RGB LINEARE medio per cella di una griglia grid×grid (flash WCAG). */
function cellSequence(opts: {
  t0: number;
  t1: number;
  fps: number;
  width: number;
  height: number;
  grid?: number;
}): number[][][] {
  if (!current) throw new Error("load() prima");
  const { player } = current;
  const gl = player.gl;
  const w = opts.width;
  const h = opts.height;
  setSize(w, h);
  const cells = Math.max(1, Math.floor(opts.grid ?? 16));
  const buf = new Uint8Array(w * h * 4);
  const out: number[][][] = [];
  const n = Math.max(1, Math.round((opts.t1 - opts.t0) * opts.fps));
  const cw = w / cells;
  const ch = h / cells;
  for (let i = 0; i < n; i++) {
    const t = opts.t0 + i / opts.fps;
    player.renderFrameAt(t);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    const acc = new Float64Array(cells * cells * 3);
    const cnt = new Float64Array(cells * cells);
    for (let y = 0; y < h; y++) {
      const cy = Math.min(cells - 1, Math.floor(y / ch));
      for (let x = 0; x < w; x++) {
        const idx = (y * w + x) * 4;
        const c = cy * cells + Math.min(cells - 1, Math.floor(x / cw));
        acc[c * 3] += SRGB_TO_LINEAR[buf[idx]];
        acc[c * 3 + 1] += SRGB_TO_LINEAR[buf[idx + 1]];
        acc[c * 3 + 2] += SRGB_TO_LINEAR[buf[idx + 2]];
        cnt[c]++;
      }
    }
    const frame: number[][] = [];
    for (let c = 0; c < cells * cells; c++) {
      const k = cnt[c] || 1;
      frame.push([acc[c * 3] / k, acc[c * 3 + 1] / k, acc[c * 3 + 2] / k]);
    }
    out.push(frame);
  }
  return out;
}

/** Statistiche float (NaN/Inf/luma) per tempo, su FBO RGBA32F. */
function stats(opts: { times: number[]; width: number; height: number }): Record<number, unknown>[] {
  if (!current) throw new Error("load() prima");
  setSize(opts.width, opts.height);
  return opts.times.map((t) => current!.player.sceneStats(t, opts.width, opts.height));
}

// gl.finish() NON attende la GPU in Chromium (misurava 0,1 ms per frame da 2,5 s su SwiftShader):
// la lettura di un pixel invece deve per forza aspettare la fine del render.
const SYNC_PX = new Uint8Array(4);
function syncGPU(gl: WebGL2RenderingContext): void {
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, SYNC_PX);
}

/** ms per tempo (mediana su repeats), fuori da rAF, sincronizzati con la lettura di un pixel.
 *  Il timer query (EXT_disjoint_timer_query_webgl2) è opzionale: in headless
 *  il busy-wait sul risultato può bloccare, quindi di default si usa il fence. */
function profile(opts: {
  times: number[];
  width: number;
  height: number;
  repeats?: number;
  useTimerQuery?: boolean;
  /** true: misura alla qualità minima (pavimento della scala adattiva). */
  floor?: boolean;
}): { method: string; samples: Record<number, number> } {
  if (!current) throw new Error("load() prima");
  const { player } = current;
  const gl = player.gl;
  setSize(opts.width, opts.height);
  const repeats = opts.repeats ?? 3;
  const fq = opts.floor ? player.floorQuality() : undefined;
  const ext = opts.useTimerQuery ? gl.getExtension("EXT_disjoint_timer_query_webgl2") : null;
  const samples: Record<number, number> = {};
  for (const t of opts.times) {
    const vals: number[] = [];
    for (let r = 0; r < repeats; r++) {
      let ms = 0;
      if (ext) {
        const q = gl.createQuery()!;
        gl.beginQuery(ext.TIME_ELAPSED_EXT, q);
        player.renderFrameAt(t, fq);
        gl.endQuery(ext.TIME_ELAPSED_EXT);
        // poll limitato: se il risultato non arriva, si butta la query
        let avail = false;
        for (let i = 0; i < 100000 && !avail; i++) {
          avail = gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE) === true;
        }
        if (avail) {
          const disjoint = gl.getParameter(ext.GPU_DISJOINT_EXT);
          if (!disjoint) {
            ms = (gl.getQueryParameter(q, gl.QUERY_RESULT) as number) / 1e6;
          }
        }
        gl.deleteQuery(q);
        if (ms === 0) {
          // fallback fence
          const t0 = performance.now();
          player.renderFrameAt(t, fq);
          syncGPU(gl);
          ms = performance.now() - t0;
        }
      } else {
        const t0 = performance.now();
        player.renderFrameAt(t, fq);
        syncGPU(gl);
        ms = performance.now() - t0;
      }
      vals.push(ms);
    }
    vals.sort((a, b) => a - b);
    samples[t] = vals[Math.floor(vals.length / 2)];
  }
  return { method: ext ? "timer_query" : "readpixels", samples };
}

function info(): DemogenInfo {
  if (current) return current.player.info;
  // primo contesto del canvas: con preserveDrawingBuffer, come lo vorrà il Player (gli
  // attributi valgono solo alla prima getContext)
  return rendererInfo(createGL(ensureCanvas(), true));
}

function state(tl: unknown, t: number): unknown {
  return stateAt(tl as never, t);
}

/** Fase 2: renderizza `blocks` blocchi audio a partire dal tempo t0 (secondi).
 *  Ritorna array di Float32Array stereo (interleaved L,R). */
function renderAudio(opts: { t0: number; blocks: number; pack8?: boolean }): number[][] {
  if (!current) throw new Error("load() prima");
  const { player } = current;
  let a = player.audio;
  if (!a) throw new Error("payload senza audio");
  // pack8: engine temporaneo col fallback RGBA8 forzato (test del percorso senza float FBO)
  const tmp = opts.pack8 ? new AudioEngine(player.gl, player.audioFragment, player.bpm, { forcePack8: true }) : null;
  if (tmp) a = tmp;
  const first = Math.floor(opts.t0 / a.chunkDur);
  const out: number[][] = [];
  try {
    for (let i = 0; i < opts.blocks; i++) out.push(Array.from(a.renderBlock(first + i)));
  } finally {
    tmp?.dispose();
  }
  return out;
}

const api = { load, capture, cellSequence, cellSequenceB64, stats, profile, info, state, renderAudio };
(window as unknown as { __demogen: typeof api }).__demogen = api;
