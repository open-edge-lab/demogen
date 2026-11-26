// audio.ts — Fase 2: audio renderizzato su GPU a blocchi (FBO RGBA32F, un texel
// per campione stereo) + scheduling dei chunk sul clock dell'AudioContext.
//
// Contratto shader audio (GLSL ES 3.00): la scena fornisce
//   void mainAudio(out vec4 o, in float t);   // o.x = L, o.y = R, t in secondi
// Il player fornisce header, uniform (iSampleRate, uBeat/uBeatPhase/uBar/BPM)
// e il main() che mappa gl_FragCoord -> indice campione.
//
// Scheduling: si renderizzano 2 chunk, poi si fissa l'istante di partenza `when`; il
// primo chunk parte con l'offset che porta esattamente al tempo richiesto (niente
// ritardo di mezzo chunk dopo un seek). Il resto del prebuffer viene renderizzato in
// background a fette (≤ maxRenderMsPerFrame) man mano che la coda si consuma; se la
// coda va in underrun si risincronizza sul clock invece di sovrapporre i chunk.
// Il clock audio (AudioContext.currentTime) è il master quando l'audio è attivo.

import { createProgram } from "./gl";

export const AUDIO_BLOCK_W = 256;
export const AUDIO_BLOCK_H = 64;
export const AUDIO_BLOCK_SAMPLES = AUDIO_BLOCK_W * AUDIO_BLOCK_H; // 16384

export interface AudioEngineOptions {
  prebufferS?: number; // default 8
  maxRenderMsPerFrame?: number; // default 2
  /** > 0: la demo è in loop di questa durata (s); il tempo dello shader audio è modulo durata. */
  loopDurS?: number;
  /** AudioContext già creato/sbloccato da un gesto utente (es. il click del bundle). */
  audioContext?: AudioContext | null;
  /** true se questo engine deve chiudere l'AudioContext in dispose (default: solo se lo crea lui). */
  ownsContext?: boolean;
  /** Test: forza il fallback RGBA8 (16 bit per canale) anche con EXT_color_buffer_float. */
  forcePack8?: boolean;
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
uniform float uBlockStart; // indice del primo campione del blocco (in sample, già modulo loop)
uniform float uLoopDur; // > 0: durata del loop in secondi
uniform highp int uText[64];
uniform int uTextLen;
#define BPM ${bpm.toFixed(4)}
void mainAudio(out vec4 o, in float t);
`;
}

const AUDIO_MAIN = `
out vec4 demogen_AudioOut;
#ifdef DEMOGEN_AUDIO_PACK8
// fallback senza float render target: 16 bit per canale su due byte (L in RG, R in BA)
vec2 demogen_pack16(float x) {
  float u = floor(clamp(x * 0.5 + 0.5, 0.0, 1.0) * 65535.0 + 0.5);
  float hi = floor(u / 256.0);
  return vec2(u - hi * 256.0, hi) / 255.0;
}
#endif
void main() {
  float idx = floor(gl_FragCoord.y) * uBlockW + floor(gl_FragCoord.x);
  float t = (uBlockStart + idx) / iSampleRate; // tempo globale: niente gap tra chunk
  if (uLoopDur > 0.0) t = mod(t, uLoopDur);
  vec4 o;
  mainAudio(o, t);
#ifdef DEMOGEN_AUDIO_PACK8
  demogen_AudioOut = vec4(demogen_pack16(o.x), demogen_pack16(o.y));
#else
  demogen_AudioOut = vec4(o.x, o.y, 0.0, 1.0);
#endif
}
`;

export function buildAudioFragment(header: string, common: string, sceneSrc: string): string {
  return header + common + AUDIO_MAIN + "\n" + sceneSrc;
}

/** Decodifica un campione dal fallback RGBA8 (due byte, little endian) in [-1, 1]. */
export function decodePack16(lo: number, hi: number): number {
  return ((hi << 8) | lo) / 65535 * 2 - 1;
}

/** Piano degli start dei chunk: consecutivi, senza gap. */
export function planChunkStarts(t0: number, chunkDur: number, n: number, firstStart: number): number[] {
  return Array.from({ length: n }, (_, i) => firstStart + i * chunkDur);
}

/** Chunk che contiene il tempo audio t e offset (s) di t dentro il chunk. */
export function chunkSchedule(t: number, chunkDur: number): { chunkIndex: number; offset: number } {
  const chunkIndex = Math.floor(Math.max(0, t) / chunkDur);
  return { chunkIndex, offset: Math.max(0, t) - chunkIndex * chunkDur };
}

export class AudioEngine {
  readonly gl: WebGL2RenderingContext;
  private prog: WebGLProgram;
  private loc: Record<string, WebGLUniformLocation | null>;
  private fbo: WebGLFramebuffer;
  private tex: WebGLTexture;
  private floatFBO = true;
  private vao: WebGLVertexArrayObject;
  private vbo: WebGLBuffer;
  private ctx: AudioContext | null;
  private ownsCtx: boolean;
  private master: GainNode | null = null;
  private vol = 1;
  private mute = false;
  private sources: AudioBufferSourceNode[] = [];
  private nextChunkIndex = 0;
  private nextStartAt = 0;
  private running = false;
  private t0 = 0;
  private startCtxTime = 0; // ctx.currentTime in cui il tempo audio vale t0
  private sampleRate = 44100;
  private prebufferS: number;
  private maxMs: number;
  private loopDurS: number;
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
    this.loopDurS = opts.loopDurS ?? 0;
    this.ctx = opts.audioContext ?? null;
    this.ownsCtx = opts.ownsContext ?? false;
    if (this.ctx) this.sampleRate = this.ctx.sampleRate;
    // FBO blocco: texture WxH, un texel per campione. RGBA32F se l'estensione
    // c'è (float nell'harness), altrimenti fallback RGBA8 (16 bit per canale).
    this.floatFBO = !opts.forcePack8 && !!gl.getExtension("EXT_color_buffer_float");
    const src = this.floatFBO ? audioFragSrc : audioFragSrc.replace(/^(#version[^\n]*\n)/, "$1#define DEMOGEN_AUDIO_PACK8\n");
    this.prog = createProgram(gl, src);
    this.loc = {};
    for (const n of ["iSampleRate", "iTime", "uBeat", "uBeatPhase", "uBar", "uBpm", "uBlockW", "uBlockStart", "uLoopDur"]) {
      this.loc[n] = gl.getUniformLocation(this.prog, n);
    }
    this.tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texStorage2D(gl.TEXTURE_2D, 1, this.floatFBO ? gl.RGBA32F : gl.RGBA8, AUDIO_BLOCK_W, AUDIO_BLOCK_H);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this.fbo = gl.createFramebuffer()!;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
      throw new Error("incomplete audio FBO");
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.vao = gl.createVertexArray()!;
    gl.bindVertexArray(this.vao);
    this.vbo = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  /** Durata del loop in secondi (0 = niente loop): vale dai blocchi renderizzati dopo. */
  setLoopDur(s: number): void {
    this.loopDurS = Math.max(0, s);
  }

  get sampleRateHz(): number {
    return this.sampleRate;
  }

  get chunkDur(): number {
    return AUDIO_BLOCK_SAMPLES / this.sampleRate;
  }

  /** Renderizza un blocco (sincrono) -> Float32Array stereo interleaved [L,R,...]. Usato da harness e seek. */
  renderBlock(chunkIndex: number): Float32Array {
    const gl = this.gl;
    let start = chunkIndex * AUDIO_BLOCK_SAMPLES;
    if (this.loopDurS > 0) {
      // modulo in JS (double): il float dello shader non perde precisione dopo minuti di loop
      start %= Math.max(1, Math.round(this.loopDurS * this.sampleRate));
    }
    const t0 = start / this.sampleRate;
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
    gl.uniform1f(this.loc.uBlockStart, start);
    gl.uniform1f(this.loc.uLoopDur, this.loopDurS);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    const out = new Float32Array(AUDIO_BLOCK_SAMPLES * 2);
    if (this.floatFBO) {
      const px = new Float32Array(AUDIO_BLOCK_SAMPLES * 4);
      gl.readPixels(0, 0, AUDIO_BLOCK_W, AUDIO_BLOCK_H, gl.RGBA, gl.FLOAT, px);
      for (let i = 0; i < AUDIO_BLOCK_SAMPLES; i++) {
        out[2 * i] = px[4 * i];
        out[2 * i + 1] = px[4 * i + 1];
      }
    } else {
      const px = new Uint8Array(AUDIO_BLOCK_SAMPLES * 4);
      gl.readPixels(0, 0, AUDIO_BLOCK_W, AUDIO_BLOCK_H, gl.RGBA, gl.UNSIGNED_BYTE, px);
      for (let i = 0; i < AUDIO_BLOCK_SAMPLES; i++) {
        out[2 * i] = decodePack16(px[4 * i], px[4 * i + 1]);
        out[2 * i + 1] = decodePack16(px[4 * i + 2], px[4 * i + 3]);
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
      this.ownsCtx = true;
      this.sampleRate = this.ctx.sampleRate;
    }
    if (!this.master) {
      this.master = this.ctx.createGain();
      this.master.gain.value = this.gainValue();
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state !== "running") await this.ctx.resume();
  }

  /** Volume 0..1 e mute: rampa di 15 ms sul guadagno master (niente click). Valgono anche prima dello sblocco. */
  setVolume(v: number, muted = this.mute): void {
    this.vol = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 1));
    this.mute = muted;
    if (this.master && this.ctx) this.master.gain.setTargetAtTime(this.gainValue(), this.ctx.currentTime, 0.015);
  }

  private gainValue(): number {
    return this.mute ? 0 : 0.9 * this.vol; // 0.9: margine sotto il clip a volume pieno
  }

  get locked(): boolean {
    return !this.ctx || this.ctx.state !== "running";
  }

  /** Avvia lo scheduling dal tempo t0 (secondi), allineato al campione. */
  start(t0: number): void {
    if (!this.ctx || !this.master || this.running) return;
    this.running = true;
    this.t0 = t0;
    const { chunkIndex, offset } = chunkSchedule(t0, this.chunkDur);
    // prima il render (sincrono), POI si fissa l'istante: il primo chunk non parte nel passato
    const first = [this.makeBuffer(chunkIndex), this.makeBuffer(chunkIndex + 1)];
    const when = this.ctx.currentTime + 0.03;
    this.startCtxTime = when;
    this.play(first[0], when, offset);
    this.nextStartAt = when + this.chunkDur - offset;
    this.play(first[1], this.nextStartAt, 0);
    this.nextStartAt += this.chunkDur;
    this.nextChunkIndex = chunkIndex + 2;
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
  }

  seek(t: number): void {
    if (!this.ctx) return;
    const wasRunning = this.running;
    this.stop();
    if (wasRunning) this.start(t);
  }

  /** Clock master in secondi (audio), oppure null se audio non attivo. Mai prima di t0. */
  now(): number | null {
    if (!this.ctx || !this.running) return null;
    return this.t0 + Math.max(0, this.ctx.currentTime - this.startCtxTime);
  }

  private makeBuffer(chunkIndex: number): AudioBuffer {
    const data = this.renderBlock(chunkIndex);
    const buf = this.ctx!.createBuffer(2, AUDIO_BLOCK_SAMPLES, this.sampleRate);
    const l = new Float32Array(AUDIO_BLOCK_SAMPLES);
    const r = new Float32Array(AUDIO_BLOCK_SAMPLES);
    for (let i = 0; i < AUDIO_BLOCK_SAMPLES; i++) {
      l[i] = data[2 * i];
      r[i] = data[2 * i + 1];
    }
    buf.copyToChannel(l, 0);
    buf.copyToChannel(r, 1);
    return buf;
  }

  private play(buf: AudioBuffer, when: number, offset: number): void {
    const src = this.ctx!.createBufferSource();
    src.buffer = buf;
    src.connect(this.master!);
    src.start(when, offset);
    this.sources.push(src);
    src.onended = () => {
      const i = this.sources.indexOf(src);
      if (i >= 0) this.sources.splice(i, 1);
      src.disconnect();
    };
  }

  private scheduleNext(): void {
    if (!this.ctx || !this.master) return;
    const ctx = this.ctx;
    if (this.nextStartAt < ctx.currentTime + 0.01) {
      // underrun: il chunk successivo partirebbe nel passato e si sovrapporrebbe.
      // Risincronizza sul clock (che resta il master): salta al chunk del tempo audio di `when`.
      const when = ctx.currentTime + 0.03;
      const { chunkIndex, offset } = chunkSchedule(this.t0 + (when - this.startCtxTime), this.chunkDur);
      this.play(this.makeBuffer(chunkIndex), when, offset);
      this.nextStartAt = when + this.chunkDur - offset;
      this.nextChunkIndex = chunkIndex + 1;
      return;
    }
    this.play(this.makeBuffer(this.nextChunkIndex), this.nextStartAt, 0);
    this.nextStartAt += this.chunkDur;
    this.nextChunkIndex++;
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

  /** Stacca l'AudioContext (restore dopo context loss): il nuovo engine lo riusa. */
  releaseContext(): { ctx: AudioContext; owned: boolean } | null {
    this.stop();
    const ctx = this.ctx;
    if (!ctx) return null;
    const owned = this.ownsCtx;
    this.ctx = null;
    this.ownsCtx = false;
    this.master?.disconnect();
    this.master = null;
    return { ctx, owned };
  }

  dispose(): void {
    this.stop();
    this.master?.disconnect();
    this.master = null;
    if (this.ctx && this.ownsCtx) void this.ctx.close().catch(() => undefined);
    this.ctx = null;
    const gl = this.gl;
    gl.deleteProgram(this.prog);
    gl.deleteFramebuffer(this.fbo);
    gl.deleteTexture(this.tex);
    gl.deleteVertexArray(this.vao);
    gl.deleteBuffer(this.vbo);
  }
}
