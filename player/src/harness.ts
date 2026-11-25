// Harness (SOLO build di test/pipeline, mai distribuito): espone window.__demogen
// con load/capture/lumaSequence/profile/info. Render fuori da rAF, a tempi esatti.

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
  try {
    const p = parsePayload(payload);
    const canvas = ensureCanvas();
    const player = new Player(canvas, p, { preserveDrawingBuffer: true, autoPlay: false });
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

/** Per ogni frame: media RGB per cella di una griglia 8×8 (analisi flash WCAG). */
function cellSequence(opts: {
  t0: number;
  t1: number;
  fps: number;
  width: number;
  height: number;
}): number[][][] {
  if (!current) throw new Error("load() prima");
  const { player } = current;
  const gl = player.gl;
  const w = opts.width;
  const h = opts.height;
  setSize(w, h);
  const cells = 8;
  const buf = new Uint8Array(w * h * 4);
  const out: number[][][] = [];
  const n = Math.max(1, Math.round((opts.t1 - opts.t0) * opts.fps));
  const cw = w / cells;
  const ch = h / cells;
  for (let i = 0; i < n; i++) {
    const t = opts.t0 + (i / n) * (opts.t1 - opts.t0);
    player.renderFrameAt(t);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    const acc = new Float64Array(cells * cells * 3);
    const cnt = new Float64Array(cells * cells);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const idx = (y * w + x) * 4;
        const cx = Math.min(cells - 1, Math.floor(x / cw));
        const cy = Math.min(cells - 1, Math.floor(y / ch));
        const c = cy * cells + cx;
        acc[c * 3] += buf[idx];
        acc[c * 3 + 1] += buf[idx + 1];
        acc[c * 3 + 2] += buf[idx + 2];
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

/** ms per tempo (mediana su repeats), fuori da rAF, con fence+finish.
 *  Il timer query (EXT_disjoint_timer_query_webgl2) è opzionale: in headless
 *  il busy-wait sul risultato può bloccare, quindi di default si usa il fence. */
function profile(opts: {
  times: number[];
  width: number;
  height: number;
  repeats?: number;
  useTimerQuery?: boolean;
}): { method: string; samples: Record<number, number> } {
  if (!current) throw new Error("load() prima");
  const { player } = current;
  const gl = player.gl;
  setSize(opts.width, opts.height);
  const repeats = opts.repeats ?? 3;
  const ext = opts.useTimerQuery ? gl.getExtension("EXT_disjoint_timer_query_webgl2") : null;
  const samples: Record<number, number> = {};
  for (const t of opts.times) {
    const vals: number[] = [];
    for (let r = 0; r < repeats; r++) {
      let ms = 0;
      if (ext) {
        const q = gl.createQuery()!;
        gl.beginQuery(ext.TIME_ELAPSED_EXT, q);
        player.renderFrameAt(t);
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
          player.renderFrameAt(t);
          gl.finish();
          ms = performance.now() - t0;
        }
      } else {
        const t0 = performance.now();
        player.renderFrameAt(t);
        gl.finish();
        ms = performance.now() - t0;
      }
      vals.push(ms);
    }
    vals.sort((a, b) => a - b);
    samples[t] = vals[Math.floor(vals.length / 2)];
  }
  return { method: ext ? "timer_query" : "fence", samples };
}

function info(): DemogenInfo {
  const canvas = ensureCanvas();
  const gl = canvas.getContext("webgl2") ?? createGL(canvas);
  return rendererInfo(gl);
}

function state(tl: unknown, t: number): unknown {
  return stateAt(tl as never, t);
}

/** Fase 2: renderizza `blocks` blocchi audio a partire dal tempo t0 (secondi).
 *  Ritorna array di Float32Array stereo (interleaved L,R). */
function renderAudio(opts: { t0: number; blocks: number }): number[][] {
  if (!current) throw new Error("load() prima");
  const a = current.player.audio;
  if (!a) throw new Error("payload senza audio");
  const chunkDur = (256 * 64) / 44100; // AUDIO_BLOCK_SAMPLES / sampleRate (fallback 44100)
  const first = Math.floor(opts.t0 / (a.chunkDur || chunkDur));
  const out: number[][] = [];
  for (let i = 0; i < opts.blocks; i++) {
    out.push(Array.from(a.renderBlock(first + i)));
  }
  return out;
}

const api = { load, capture, cellSequence, stats, profile, info, state, renderAudio };
(window as unknown as { __demogen: typeof api }).__demogen = api;
