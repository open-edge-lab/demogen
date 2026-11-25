// audio.ts — Fase 2: audio renderizzato su GPU a blocchi (FBO RGBA32F, un texel
// per campione stereo) + scheduling dei chunk sul clock dell'AudioContext.
//
// Contratto shader audio (GLSL ES 3.00): la scena fornisce
//   void mainAudio(out vec4 o, in float t);   // o.x = L, o.y = R, t in secondi
// Il player fornisce header, uniform (iSampleRate, uBeat/uBeatPhase/uBar/BPM)
// e il main() che mappa gl_FragCoord -> indice campione.
//
// Scheduling: prebuffer di `prebufferS` secondi, poi render in background a
// fette (≤ maxRenderMsPerFrame per frame) man mano che la coda si consuma.
// Il clock audio (AudioContext.currentTime) è il master quando l'audio è attivo.

import { createProgram } from "./gl";

export const AUDIO_BLOCK_W = 256;
export const AUDIO_BLOCK_H = 64;
export const AUDIO_BLOCK_SAMPLES = AUDIO_BLOCK_W * AUDIO_BLOCK_H; // 16384

export interface AudioEngineOptions {
  prebufferS?: number; // default 8
  maxRenderMsPerFrame?: number; // default 2
}

export function buildAudioHeader(bpm: number): string {
  return `#version 300 es
precision highp float;
precision highp int;
uniform float iSampleRate;
uniform float iTime;
uniform float uBeat;
uniform float uBeatPhase;
uniform float uBar;
uniform float uBpm;
uniform float uBlockW;
uniform float uBlockStart; // indice del primo campione del blocco (in sample)
uniform highp int uText[64];
uniform int uTextLen;
#define BPM ${bpm.toFixed(4)}
void mainAudio(out vec4 o, in float t);
`;
}

const AUDIO_MAIN = `
out vec4 demogen_AudioOut;
void main() {
  float idx = floor(gl_FragCoord.y) * uBlockW + floor(gl_FragCoord.x);
  float t = (uBlockStart + idx) / iSampleRate; // tempo globale: niente gap tra chunk
  vec4 o;
  mainAudio(o, t);
  demogen_AudioOut = vec4(o.x, o.y, 0.0, 1.0);
}
`;

export function buildAudioFragment(header: string, common: string, sceneSrc: string): string {
  return header + common + AUDIO_MAIN + "\n" + sceneSrc;
}

/** Piano degli start dei chunk: consecutivi, senza gap. */
export function planChunkStarts(t0: number, chunkDur: number, n: number, firstStart: number): number[] {
  const firstChunk = Math.floor(t0 / chunkDur);
  return Array.from({ length: n }, (_, i) => firstStart + i * chunkDur);
}

export class AudioEngine {
  readonly gl: WebGL2RenderingContext;
  private prog: WebGLProgram;
  private loc: Record<string, WebGLUniformLocation | null>;
  private fbo: WebGLFramebuffer;
  private tex: WebGLTexture;
  private floatFBO = true;
  private vao: WebGLVertexArrayObject;
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private sources: AudioBufferSourceNode[] = [];
  private queue: { buffer: AudioBuffer; startAt: number; chunkIndex: number }[] = [];
  private nextChunkIndex = 0;
  private nextStartAt = 0;
  private running = false;
  private t0 = 0;
  private startCtxTime = 0; // ctx.currentTime all'avvio
  private sampleRate = 44100;
  private prebufferS: number;
  private maxMs: number;
  private pumpTimer: ReturnType<typeof setInterval> | null = null;

  constructor(
    gl: WebGL2RenderingContext,
    audioFragSrc: string,
    private bpm: number,
    opts: AudioEngineOptions = {},
  ) {
    this.gl = gl;
    this.prebufferS = opts.prebufferS ?? 8;
    this.maxMs = opts.maxRenderMsPerFrame ?? 2;
    this.prog = createProgram(gl, audioFragSrc);
    this.loc = {};
    for (const n of ["iSampleRate", "iTime", "uBeat", "uBeatPhase", "uBar", "uBpm", "uBlockW", "uBlockStart"]) {
      this.loc[n] = gl.getUniformLocation(this.prog, n);
    }
    // FBO blocco: texture WxH, un texel per campione. RGBA32F se l'estensione
    // c'è (float nell'harness), altrimenti fallback RGBA8 (16 bit per canale).
    this.floatFBO = !!gl.getExtension("EXT_color_buffer_float");
    this.tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texStorage2D(
      gl.TEXTURE_2D, 1,
      this.floatFBO ? gl.RGBA32F : gl.RGBA8,
      AUDIO_BLOCK_W, AUDIO_BLOCK_H,
    );
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this.fbo = gl.createFramebuffer()!;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
      throw new Error("FBO audio non completo");
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.vao = gl.createVertexArray()!;
    gl.bindVertexArray(this.vao);
    const vb = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, vb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  get chunkDur(): number {
    return AUDIO_BLOCK_SAMPLES / this.sampleRate;
  }

  /** Renderizza un blocco (sincrono) -> Float32Array stereo interleaved [L,R,...]. Usato da harness e seek. */
  renderBlock(chunkIndex: number): Float32Array {
    const gl = this.gl;
    const t0 = chunkIndex * this.chunkDur;
    const beatDur = 60 / this.bpm;
    const beat = Math.floor(t0 / beatDur);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.viewport(0, 0, AUDIO_BLOCK_W, AUDIO_BLOCK_H);
    gl.useProgram(this.prog);
    gl.uniform1f(this.loc.iSampleRate, this.sampleRate);
    gl.uniform1f(this.loc.iTime, t0);
    gl.uniform1f(this.loc.uBeat, beat);
    gl.uniform1f(this.loc.uBeatPhase, (t0 / beatDur) % 1);
    gl.uniform1f(this.loc.uBar, beat / 4);
    gl.uniform1f(this.loc.uBpm, this.bpm);
    gl.uniform1f(this.loc.uBlockW, AUDIO_BLOCK_W);
    gl.uniform1f(this.loc.uBlockStart, chunkIndex * AUDIO_BLOCK_SAMPLES);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    const out = new Float32Array(AUDIO_BLOCK_SAMPLES * 2);
    if (this.floatFBO) {
      const px = new Float32Array(AUDIO_BLOCK_SAMPLES * 4);
      gl.readPixels(0, 0, AUDIO_BLOCK_W, AUDIO_BLOCK_H, gl.RGBA, gl.FLOAT, px);
      for (let i = 0; i < AUDIO_BLOCK_SAMPLES; i++) {
        out[2 * i] = px[4 * i];
        out[2 * i + 1] = px[4 * i + 1];
      }
    } else {
      // fallback RGBA8: 16 bit per canale (due byte per campione in R+G)
      const px = new Uint8Array(AUDIO_BLOCK_SAMPLES * 4);
      gl.readPixels(0, 0, AUDIO_BLOCK_W, AUDIO_BLOCK_H, gl.RGBA, gl.UNSIGNED_BYTE, px);
      for (let i = 0; i < AUDIO_BLOCK_SAMPLES; i++) {
        const l = ((px[4 * i + 1] << 8) | px[4 * i]) / 32768.0 - 1.0;
        const r = ((px[4 * i + 3] << 8) | px[4 * i + 2]) / 32768.0 - 1.0;
        out[2 * i] = l;
        out[2 * i + 1] = r;
      }
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return out;
  }

  /** Crea/resume l'AudioContext: DEVE essere chiamato dentro un gesto utente. */
  async unlock(): Promise<void> {
    if (!this.ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.sampleRate = this.ctx.sampleRate;
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.9;
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state !== "running") await this.ctx.resume();
  }

  get locked(): boolean {
    return !this.ctx || this.ctx.state !== "running";
  }

  /** Avvia lo scheduling dal tempo t0 (secondi). */
  start(t0: number): void {
    if (!this.ctx || this.running) return;
    this.running = true;
    this.t0 = t0;
    this.startCtxTime = this.ctx.currentTime;
    this.nextChunkIndex = Math.floor(t0 / this.chunkDur);
    this.nextStartAt = this.ctx.currentTime + 0.08;
    // prebuffer
    const nPre = Math.max(1, Math.round(this.prebufferS / this.chunkDur));
    for (let i = 0; i < nPre; i++) this.scheduleNext();
    this.pumpTimer = setInterval(() => this.pump(this.maxMs), 25);
  }

  stop(): void {
    this.running = false;
    if (this.pumpTimer) clearInterval(this.pumpTimer);
    this.pumpTimer = null;
    for (const s of this.sources) {
      try { s.stop(); } catch { /* già fermo */ }
      s.disconnect();
    }
    this.sources = [];
    this.queue = [];
  }

  seek(t: number): void {
    if (!this.ctx) return;
    const wasRunning = this.running;
    this.stop();
    if (wasRunning) this.start(t);
  }

  /** Clock master in secondi (audio), oppure null se audio non attivo. */
  now(): number | null {
    if (!this.ctx || !this.running) return null;
    return this.t0 + (this.ctx.currentTime - this.startCtxTime);
  }

  private scheduleNext(): void {
    if (!this.ctx || !this.master) return;
    const data = this.renderBlock(this.nextChunkIndex);
    const buf = this.ctx.createBuffer(2, AUDIO_BLOCK_SAMPLES, this.sampleRate);
    buf.copyToChannel(data.subarray(0, AUDIO_BLOCK_SAMPLES * 2).filter((_, i) => i % 2 === 0), 0);
    buf.copyToChannel(data.filter((_, i) => i % 2 === 1), 1);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.master);
    src.start(this.nextStartAt);
    this.sources.push(src);
    this.queue.push({ buffer: buf, startAt: this.nextStartAt, chunkIndex: this.nextChunkIndex });
    this.nextStartAt += this.chunkDur;
    this.nextChunkIndex++;
    // tieni la coda corta
    while (this.queue.length > 0 && this.queue[0].startAt < this.ctx.currentTime - 1) {
      this.queue.shift();
    }
    if (this.sources.length > 64) {
      const old = this.sources.splice(0, this.sources.length - 64);
      for (const s of old) { try { s.disconnect(); } catch { /* noop */ } }
    }
  }

  /** Renderizza chunk in background fino a deadline (ms). Ritorna quanti ne ha fatti. */
  pump(deadlineMs: number): number {
    if (!this.ctx || !this.running) return 0;
    const deadline = performance.now() + deadlineMs;
    let n = 0;
    while (this.nextStartAt - this.ctx.currentTime < Math.max(0.5, this.prebufferS * 0.5)) {
      if (performance.now() >= deadline) break;
      this.scheduleNext();
      n++;
    }
    return n;
  }

  /** Tempo corrente dal clock audio (master), o performance.now fallback. */
  currentTime(perfNowMs: number, perfStartMs: number, offsetS: number): number {
    const a = this.now();
    if (a !== null) return a;
    return offsetS + (perfNowMs - perfStartMs) / 1000;
  }
}
