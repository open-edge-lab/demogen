// Player: ciclo di vita load → compile → play realtime (rAF + clock), con
// controllore di qualità, frame pacing, profilo retro e gestione context loss.
// Il clock è l'AudioContext quando l'audio è attivo, altrimenti performance.now().

import { AudioEngine, buildAudioHeader, buildAudioFragment } from "./audio";
import { PlaybackClock } from "./clock";
import { Compositor, RenderEnv } from "./compositor";
import { DemoPayload, parsePayload, textByteLength, textToUniform } from "./format";
import { createGL, DemogenInfo, FBO, isSoftwareRenderer, rendererInfo } from "./gl";
import { BloomParams, Post } from "./post";
import { buildHeader, CompiledProgram, compileAll, detectMap, SceneDef } from "./programs";
import { DEFAULT_LIMITS, QualityController, QualityState } from "./quality";
import { stateAt, Timeline } from "./timeline";

export interface PlayerOptions {
  preserveDrawingBuffer?: boolean; // true nell'harness per capture via toDataURL
  autoPlay?: boolean;
  /** false: la dimensione del canvas la decide il chiamante (harness); default: segue il layout. */
  autoResize?: boolean;
  /** AudioContext già sbloccato da un gesto utente (es. il click del bundle). */
  audioContext?: AudioContext;
  /** Limite fotosensibilità (0..1) applicato a beatFlash e alle transizioni flash. */
  flashLimit?: number;
  /** Volume iniziale della musica 0..1 (default 1) e mute iniziale. */
  volume?: number;
  muted?: boolean;
  onReady?: () => void;
  onError?: (e: unknown) => void;
  onQualityChange?: (q: QualityState) => void;
}

/** Sotto il 10% di variazione di luminanza: un lampo che non conta come flash WCAG. */
export const SAFE_FLASH_LIMIT = 0.08;

/** uFlashLimit: pieno, salvo beat più veloci di 3/s (lampi oltre la soglia WCAG) o reduced-motion. */
export function flashLimitFor(bpm: number, reducedMotion: boolean, requested = 1): number {
  const lim = bpm / 60 > 3 || reducedMotion ? SAFE_FLASH_LIMIT : 1;
  return Math.max(0, Math.min(requested, lim));
}

export class Player {
  readonly gl: WebGL2RenderingContext;
  readonly durationS: number;
  audio: AudioEngine | null = null;
  compileMs = 0;
  private payload: DemoPayload;
  private compositor: Compositor | null = null;
  private post: Post | null = null;
  private quality: QualityController;
  private clock: PlaybackClock;
  private progs = new Map<string, CompiledProgram>();
  private text: Int32Array;
  private textLen: number;
  private flashLimit: number;
  private minScale: number;
  private rafId = 0;
  private lastFrameAt = 0;
  private lost = false;
  private disposed = false;
  private lastQuality: QualityState | null = null;
  private audioFrag = "";
  private floatFBO: { fbo: WebGLFramebuffer; tex: WebGLTexture; width: number; height: number } | null = null;
  private ro: ResizeObserver | null = null;
  private vol = 1;
  private mute = false;
  private readonly onWinResize = (): void => this.resize();
  private readonly onLost = (e: Event): void => {
    e.preventDefault();
    this.lost = true;
    this.stopLoop();
  };
  private readonly onRestored = (): void => {
    this.lost = false;
    void this.rebuild();
  };
  private readonly onGesture = (): void => {
    const a = this.audio;
    if (!a) return;
    void a.unlock().then(() => {
      if (!a.locked && this.clock.isPlaying) a.start(this.clock.raw());
    });
  };
  private gestureBound = false;

  constructor(
    readonly canvas: HTMLCanvasElement,
    payload: DemoPayload,
    private opts: PlayerOptions = {},
  ) {
    this.gl = createGL(canvas, !!opts.preserveDrawingBuffer);
    this.payload = parsePayload(payload);
    const tl = this.payload.timeline as Timeline;
    this.durationS = stateAt(tl, 0).durationS; // la timeline è la verità, meta.duration_s solo indicativa
    this.clock = new PlaybackClock(() => performance.now(), this.durationS, !!this.payload.meta.loop);
    this.text = textToUniform(this.payload.text);
    this.textLen = textByteLength(this.payload.text);
    const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.flashLimit = flashLimitFor(tl.bpm, reduced, opts.flashLimit ?? 1);
    const q = this.payload.quality ?? {};
    this.minScale = q.min_scale ?? DEFAULT_LIMITS.minScale;
    this.quality = new QualityController({
      targetFps: q.target_fps ?? DEFAULT_LIMITS.targetFps,
      minScale: this.minScale,
      bloom: this.payload.post?.bloom !== undefined,
    });
    canvas.addEventListener("webglcontextlost", this.onLost);
    canvas.addEventListener("webglcontextrestored", this.onRestored);
    if (opts.autoResize !== false && typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(canvas);
      // il ResizeObserver non vede i cambi di devicePixelRatio (finestra spostata su un altro monitor)
      window.addEventListener("resize", this.onWinResize);
    }
    this.vol = opts.volume ?? 1;
    this.mute = !!opts.muted;
  }

  get info(): DemogenInfo {
    return rendererInfo(this.gl);
  }

  get softwareRenderer(): boolean {
    return isSoftwareRenderer(this.info.renderer);
  }

  get isPlaying(): boolean {
    return this.clock.isPlaying;
  }

  get bpm(): number {
    return this.payload.timeline.bpm;
  }

  /** Qualità minima della scala adattiva (pavimento perf: scala minima, uQuality 0, niente bloom). */
  floorQuality(): QualityState {
    return { scale: this.minScale, uQuality: 0, bloom: false };
  }

  /** Sorgente GLSL completa dello shader audio (per test/harness). */
  get audioFragment(): string {
    return this.audioFrag;
  }

  async load(): Promise<void> {
    const p = this.payload;
    const tl = p.timeline as Timeline;
    const scenes: SceneDef[] = tl.scenes.map((s) => {
      const profile = p.render.overrides?.[s.id] ?? p.render.profile;
      return { id: s.id, src: p.scenes[s.id], profile };
    });
    const headerFor = (s: SceneDef): string =>
      buildHeader({
        bpm: tl.bpm,
        retro: s.profile === "retro",
        withText: p.text !== undefined, // anche text:null dichiara uText (le scene scroller lo usano)
        hasMap: detectMap(s.src),
      });
    const t0 = performance.now();
    this.progs = await compileAll(this.gl, headerFor, { modern: p.common, retro: p.common }, scenes);
    this.compileMs = performance.now() - t0;
    this.compositor = new Compositor(this.gl, 640, 360);
    this.post = new Post(this.gl, this.compositor, 640, 360);
    // Fase 2: audio GPU (se il payload ha `audio`); sblocco su gesto utente (policy autoplay)
    if (p.audio) {
      // p.audio è self-contained (lib treeshaked + sorgente): no common video, niente doppioni
      this.audioFrag = buildAudioFragment(buildAudioHeader(tl.bpm), "", p.audio);
      // restore dopo context loss: si riusa lo stesso AudioContext (niente motori duplicati)
      const prev = this.audio?.releaseContext() ?? null;
      const ctx = prev?.ctx ?? this.opts.audioContext ?? null;
      this.audio = new AudioEngine(this.gl, this.audioFrag, tl.bpm, {
        prebufferS: 8,
        maxRenderMsPerFrame: 2,
        loopDurS: this.clock.loop ? this.durationS : 0,
        audioContext: ctx,
        ownsContext: prev ? prev.owned : false,
      });
      this.audio.setVolume(this.vol, this.mute);
      if (ctx) await this.audio.unlock();
      if (!this.gestureBound && typeof window !== "undefined") {
        window.addEventListener("pointerdown", this.onGesture);
        window.addEventListener("keydown", this.onGesture);
        this.gestureBound = true;
      }
    }
    if (this.opts.autoResize !== false) this.resize();
    if (this.opts.autoPlay !== false) this.play();
    this.opts.onReady?.();
  }

  private async rebuild(): Promise<void> {
    // dopo context loss le risorse GL sono perse: ricompila (l'AudioContext resta lo stesso)
    const wasPlaying = this.clock.isPlaying;
    this.clock.pause(this.audio?.now());
    this.audio?.stop();
    this.progs.clear();
    this.floatFBO = null;
    try {
      await this.load();
      if (wasPlaying && this.opts.autoPlay === false) this.play();
    } catch (e) {
      this.opts.onError?.(e);
    }
  }

  play(): void {
    if (this.clock.isPlaying || this.lost || this.disposed) return;
    if (this.opts.autoResize !== false) this.resize();
    if (!this.clock.loop && this.clock.ended()) this.clock.seek(0);
    this.clock.play();
    if (this.audio && !this.audio.locked) this.audio.start(this.clock.raw());
    this.lastFrameAt = 0;
    const loop = (now: number) => {
      if (!this.clock.isPlaying) return;
      this.rafId = requestAnimationFrame(loop);
      if (!this.quality.shouldRender(now)) return;
      const t0 = performance.now();
      this.renderFrameAt(this.currentTime());
      if (this.audio) this.audio.pump(2); // render audio in background, ≤ 2 ms/frame
      // durata del frame = intervallo tra frame renderizzati (include il lavoro GPU), min. il tempo CPU
      const cpuMs = performance.now() - t0;
      const frameMs = this.lastFrameAt ? Math.max(cpuMs, now - this.lastFrameAt) : cpuMs;
      this.lastFrameAt = now;
      this.quality.update(frameMs, now);
      const q = this.quality.state;
      if (JSON.stringify(q) !== JSON.stringify(this.lastQuality)) {
        this.lastQuality = q;
        this.opts.onQualityChange?.(q);
      }
      if (this.clock.ended(this.audio?.now())) this.pause(); // fine demo (senza loop)
    };
    this.rafId = requestAnimationFrame(loop);
  }

  pause(): void {
    // salva la posizione PRIMA di fermare l'audio (che è il clock master)
    this.clock.pause(this.audio?.now());
    this.stopLoop();
    this.audio?.stop();
  }

  private stopLoop(): void {
    cancelAnimationFrame(this.rafId);
    this.rafId = 0;
  }

  /** Ferma e torna all'inizio: a schermo resta il primo frame. */
  stop(): void {
    this.pause();
    this.seek(0);
  }

  get loop(): boolean {
    return this.clock.loop;
  }

  /** true quando la demo, senza loop, è arrivata alla fine (play() riparte dall'inizio). */
  get ended(): boolean {
    return this.clock.ended(this.audio?.now());
  }

  /** Loop continuo a fine demo; si può cambiare anche mentre suona (l'audio riparte dalla stessa posizione). */
  setLoop(on: boolean): void {
    if (on === this.clock.loop) return;
    const wasPlaying = this.clock.isPlaying;
    if (wasPlaying) this.pause();
    this.clock.setLoop(on);
    this.audio?.setLoopDur(on ? this.durationS : 0);
    if (wasPlaying) this.play();
  }

  seek(t: number): void {
    this.clock.seek(t);
    this.audio?.seek(this.clock.raw());
    // in pausa nessuno ridisegna: senza questo lo schermo resterebbe sul frame vecchio
    if (!this.clock.isPlaying && this.compositor && !this.lost && !this.disposed) this.renderFrameAt(this.currentTime());
  }

  currentTime(): number {
    return this.clock.time(this.audio?.now());
  }

  private makeEnv(t: number, w: number, h: number, q: QualityState): RenderEnv {
    const tl = this.payload.timeline as Timeline;
    const tw = this.clock.wrap(t);
    return {
      t: tw,
      state: stateAt(tl, tw),
      width: w,
      height: h,
      uQuality: q.uQuality,
      uFlashLimit: this.flashLimit,
      text: this.text,
      textLen: this.textLen,
    };
  }

  /** Renderizza un frame al tempo t (deterministico, usato anche dall'harness). */
  renderFrameAt(t: number, forceQuality?: QualityState): QualityState {
    if (!this.compositor || !this.post) throw new Error("load() before renderFrameAt");
    const p = this.payload;
    const q = forceQuality ?? this.quality.state;
    const tw = this.clock.wrap(t); // stesso tempo (con loop) per profilo, stato e uniform
    const sceneProfile = p.render.overrides?.[stateAt(p.timeline as Timeline, tw).sceneId] ?? p.render.profile;
    const retroRes = p.render.retro?.internal_resolution ?? [320, 180];
    const cw = this.canvas.width;
    const ch = this.canvas.height;
    const retro = sceneProfile === "retro";
    const w = retro ? retroRes[0] : Math.max(1, Math.round(cw * q.scale));
    const h = retro ? retroRes[1] : Math.max(1, Math.round(ch * q.scale));
    const { fbo } = this.compositor.render(this.makeEnv(tw, w, h, q), this.progs);
    // blit sul canvas: retro con filtro nearest (pixel netti), modern lineare — impostato a OGNI frame,
    // perché gli FBO sono condivisi tra scene di profili diversi
    const gl = this.gl;
    const filter = retro ? gl.NEAREST : gl.LINEAR;
    gl.bindTexture(gl.TEXTURE_2D, fbo.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    // retro: risoluzione interna fissa, quindi sul canvas si mantengono le proporzioni con bande nere
    // (stirata, in una finestra verticale lo sprite diventava alto e stretto)
    let vw = cw;
    let vh = ch;
    if (retro) {
      const s = Math.min(cw / w, ch / h);
      vw = Math.round(w * s);
      vh = Math.round(h * s);
      if (vw < cw || vh < ch) {
        gl.clearColor(0, 0, 0, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);
      }
    }
    const vx = (cw - vw) >> 1;
    const vy = (ch - vh) >> 1;
    const bloom: BloomParams | null = q.bloom && p.post?.bloom
      ? { threshold: p.post.bloom.threshold, intensity: p.post.bloom.intensity }
      : null;
    if (bloom) this.post.apply(fbo.tex, vw, vh, bloom, vx, vy);
    else this.compositor.blit(fbo.tex, vw, vh, vx, vy);
    return q;
  }

  /** Composizione a tempo t in un FBO w×h, senza blit né bloom: immagini fisse a tile
   *  (`res` = immagine intera, `jitter` = angolo del tile + offset sub-pixel). */
  composeAt(t: number, w: number, h: number, q: QualityState, res?: [number, number],
            jitter?: [number, number]): FBO {
    if (!this.compositor) throw new Error("load() before composeAt");
    return this.compositor.render({ ...this.makeEnv(t, w, h, q), res, jitter }, this.progs).fbo;
  }

  /** Adegua il buffer del canvas alla sua dimensione CSS × devicePixelRatio (max 2). */
  resize(): void {
    const dpr = Math.min((typeof window !== "undefined" && window.devicePixelRatio) || 1, 2);
    const w = Math.max(1, Math.floor(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.floor(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
      // cambiare width/height svuota il canvas: in pausa (o a demo finita) si ridisegna subito il
      // fotogramma corrente alla nuova dimensione; in riproduzione ci pensa il frame successivo
      if (!this.clock.isPlaying && this.compositor && !this.lost && !this.disposed) {
        this.renderFrameAt(this.currentTime());
      }
    }
  }

  /** Volume della musica 0..1. */
  get volume(): number {
    return this.vol;
  }

  set volume(v: number) {
    this.vol = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 1));
    this.audio?.setVolume(this.vol, this.mute);
  }

  get muted(): boolean {
    return this.mute;
  }

  set muted(m: boolean) {
    this.mute = m;
    this.audio?.setVolume(this.vol, m);
  }

  /** true se la demo ha una colonna sonora. */
  get hasAudio(): boolean {
    return !!this.payload.audio;
  }

  captureDataURL(t: number): string {
    if (this.opts.autoResize !== false) this.resize();
    this.renderFrameAt(t);
    this.gl.finish();
    return this.canvas.toDataURL("image/png");
  }

  /**
   * Statistiche float della scena a tempo t: renderizza in FBO RGBA32F
   * (EXT_color_buffer_float) e legge NaN/Inf/luma — prima della quantizzazione.
   */
  sceneStats(t: number, width?: number, height?: number): Record<string, number> {
    if (!this.compositor) throw new Error("load() before sceneStats");
    const gl = this.gl;
    const ext = gl.getExtension("EXT_color_buffer_float");
    const w = width ?? this.canvas.width;
    const h = height ?? this.canvas.height;
    const tw = this.clock.wrap(t);
    const st = stateAt(this.payload.timeline as Timeline, tw);
    const cp = this.progs.get(st.sceneId);
    if (!cp) throw new Error(`scene ${st.sceneId} not compiled`);
    if (!ext) {
      return { nan_ratio: 0, inf_ratio: 0, luma_mean: 0, float_path: 0 };
    }
    if (!this.floatFBO) {
      const tex = gl.createTexture()!;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, w, h, 0, gl.RGBA, gl.FLOAT, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      const fbo = gl.createFramebuffer()!;
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      this.floatFBO = { fbo, tex, width: w, height: h };
    } else if (this.floatFBO.width !== w || this.floatFBO.height !== h) {
      gl.bindTexture(gl.TEXTURE_2D, this.floatFBO.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, w, h, 0, gl.RGBA, gl.FLOAT, null);
      this.floatFBO.width = w;
      this.floatFBO.height = h;
    }
    const env = this.makeEnv(tw, w, h, { scale: 1, uQuality: 1, bloom: false });
    this.compositor.drawScene(this.floatFBO as never, cp, env);
    const buf = new Float32Array(w * h * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.floatFBO.fbo);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.FLOAT, buf);
    let nan = 0;
    let inf = 0;
    let sum = 0;
    const n = w * h;
    for (let i = 0; i < n; i++) {
      const r = buf[i * 4];
      const g = buf[i * 4 + 1];
      const b = buf[i * 4 + 2];
      if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) nan++;
      else if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) inf++;
      else sum += 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { nan_ratio: nan / n, inf_ratio: inf / n, luma_mean: sum / n, float_path: 1 };
  }

  /** Libera tutto: loop, listener, ResizeObserver, programmi, FBO, VBO, audio (AudioContext incluso). */
  dispose(): void {
    if (this.disposed) return;
    this.pause();
    this.disposed = true;
    this.ro?.disconnect();
    this.ro = null;
    if (typeof window !== "undefined") window.removeEventListener("resize", this.onWinResize);
    this.canvas.removeEventListener("webglcontextlost", this.onLost);
    this.canvas.removeEventListener("webglcontextrestored", this.onRestored);
    if (this.gestureBound) {
      window.removeEventListener("pointerdown", this.onGesture);
      window.removeEventListener("keydown", this.onGesture);
      this.gestureBound = false;
    }
    const gl = this.gl;
    for (const cp of this.progs.values()) gl.deleteProgram(cp.prog);
    this.progs.clear();
    if (this.floatFBO) {
      gl.deleteFramebuffer(this.floatFBO.fbo);
      gl.deleteTexture(this.floatFBO.tex);
      this.floatFBO = null;
    }
    this.compositor?.dispose();
    this.post?.dispose();
    this.compositor = null;
    this.post = null;
    this.audio?.dispose();
    this.audio = null;
  }
}
