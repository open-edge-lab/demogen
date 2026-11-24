// Player: ciclo di vita load → compile → play realtime (rAF + clock), con
// controllore di qualità, frame pacing, profilo retro e gestione context loss.
// Audio in Fase 2: per ora il clock è performance.now().

import { Compositor, RenderEnv } from "./compositor";
import { parsePayload, textToUniform, DemoPayload } from "./format";
import { createGL, rendererInfo, DemogenInfo, isSoftwareRenderer } from "./gl";
import { Post, BloomParams } from "./post";
import { compileAll, SceneDef } from "./programs";
import { QualityController, QualityState, DEFAULT_LIMITS } from "./quality";
import { stateAt, Timeline } from "./timeline";

export interface PlayerOptions {
  preserveDrawingBuffer?: boolean; // true nell'harness per capture via toDataURL
  autoPlay?: boolean;
  onReady?: () => void;
  onError?: (e: unknown) => void;
  onQualityChange?: (q: QualityState) => void;
}

export class Player {
  readonly gl: WebGL2RenderingContext;
  private payload: DemoPayload;
  private compositor!: Compositor;
  private post!: Post;
  private quality: QualityController;
  private progs = new Map<string, import("./programs").CompiledProgram>();
  private text: Int32Array;
  private playing = false;
  private rafId = 0;
  private startMs = 0;
  private offsetS = 0;
  private lost = false;
  private lastQuality: QualityState | null = null;
  private internalW = 0;
  private internalH = 0;

  constructor(
    readonly canvas: HTMLCanvasElement,
    payload: DemoPayload,
    private opts: PlayerOptions = {},
  ) {
    this.gl = createGL(canvas);
    if (opts.preserveDrawingBuffer) {
      // ricrea con preserve (l'harness cattura via toDataURL)
      const gl2 = canvas.getContext("webgl2", {
        antialias: false, alpha: false, depth: false, stencil: false,
        powerPreference: "high-performance", preserveDrawingBuffer: true,
      });
      if (gl2) (this as { gl: WebGL2RenderingContext }).gl = gl2;
    }
    this.payload = parsePayload(payload);
    this.text = textToUniform(this.payload.text);
    const q = this.payload.quality ?? {};
    this.quality = new QualityController({
      targetFps: q.target_fps ?? DEFAULT_LIMITS.targetFps,
      minScale: q.min_scale ?? DEFAULT_LIMITS.minScale,
      bloom: this.payload.post?.bloom !== undefined,
    });
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.lost = true;
      this.playing = false;
    });
    canvas.addEventListener("webglcontextrestored", () => {
      this.lost = false;
      void this.rebuild();
    });
  }

  get info(): DemogenInfo {
    return rendererInfo(this.gl);
  }

  get softwareRenderer(): boolean {
    return isSoftwareRenderer(this.info.renderer);
  }

  get durationS(): number {
    return this.payload.meta.duration_s;
  }

  async load(): Promise<void> {
    const p = this.payload;
    const tl = p.timeline as Timeline;
    const scenes: SceneDef[] = tl.scenes.map((s) => {
      const profile = p.render.overrides?.[s.id] ?? p.render.profile;
      return { id: s.id, src: p.scenes[s.id], profile };
    });
    const common = p.common;
    const headerFor = (s: SceneDef): string =>
      buildHeaderStr({
        bpm: tl.bpm,
        retro: s.profile === "retro",
        withText: p.text !== undefined,
        hasMap: /\bfloat\s+map\s*\(/.test(s.src),
      });
    const t0 = performance.now();
    const compiled = await compileAll(
      this.gl,
      headerFor,
      { modern: common, retro: common },
      scenes,
    );
    const all = compiled;
    this.progs = all;
    this.compileMs = performance.now() - t0;
    this.compositor = new Compositor(this.gl, 640, 360);
    this.post = new Post(this.gl, this.compositor, 640, 360);
    if (this.opts.autoPlay !== false) this.play();
    this.opts.onReady?.();
  }

  compileMs = 0;

  private async rebuild(): Promise<void> {
    // dopo context loss: ricompila tutto
    this.progs.clear();
    await this.load();
  }

  play(): void {
    if (this.playing || this.lost) return;
    this.playing = true;
    this.startMs = performance.now() - this.offsetS * 1000;
    const loop = (now: number) => {
      if (!this.playing) return;
      this.rafId = requestAnimationFrame(loop);
      if (!this.quality.shouldRender(now)) return;
      const t0 = performance.now();
      this.renderFrameAt(this.currentTime());
      const frameMs = performance.now() - t0;
      this.quality.update(frameMs, now);
      const q = this.quality.state;
      if (JSON.stringify(q) !== JSON.stringify(this.lastQuality)) {
        this.lastQuality = q;
        this.opts.onQualityChange?.(q);
      }
    };
    this.rafId = requestAnimationFrame(loop);
  }

  pause(): void {
    this.playing = false;
    cancelAnimationFrame(this.rafId);
  }

  seek(t: number): void {
    this.offsetS = Math.max(0, Math.min(this.durationS, t));
    this.startMs = performance.now() - this.offsetS * 1000;
  }

  currentTime(): number {
    return this.offsetS + (performance.now() - this.startMs) / 1000;
  }

  /** Renderizza un frame al tempo t (deterministico, usato anche dall'harness). */
  renderFrameAt(t: number, forceQuality?: QualityState): QualityState {
    const p = this.payload;
    const tl = p.timeline as Timeline;
    const st = stateAt(tl, p.meta.loop ? t % this.durationS : Math.min(t, this.durationS));
    const q = forceQuality ?? this.quality.state;
    const sceneProfile =
      p.render.overrides?.[st.sceneId] ?? p.render.profile;
    const retroRes = p.render.retro?.internal_resolution ?? [320, 180];
    const cw = this.canvas.width;
    const ch = this.canvas.height;
    const w = sceneProfile === "retro" ? retroRes[0] : Math.max(1, Math.round(cw * q.scale));
    const h = sceneProfile === "retro" ? retroRes[1] : Math.max(1, Math.round(ch * q.scale));
    const env: RenderEnv = {
      t,
      state: st,
      width: w,
      height: h,
      uQuality: q.uQuality,
      uFlashLimit: 1,
      text: this.text,
      textLen: p.text ? Math.min(256, p.text.length) : 0,
    };
    const { fbo } = this.compositor.render(env, this.progs);
    // blit sul canvas: per retro texture con filtro nearest (pixel netti)
    const gl = this.gl;
    if (sceneProfile === "retro") {
      gl.bindTexture(gl.TEXTURE_2D, fbo.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    const bloom: BloomParams | null = q.bloom && p.post?.bloom
      ? { threshold: p.post.bloom.threshold, intensity: p.post.bloom.intensity }
      : null;
    if (bloom) {
      // bloom su FBO a scala, poi blit sul canvas
      this.post.apply(fbo.tex, cw, ch, bloom);
    } else {
      this.compositor.blit(fbo.tex, cw, ch);
    }
    return q;
  }

  resize(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.floor(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  captureDataURL(t: number): string {
    this.resize();
    this.renderFrameAt(t);
    this.gl.finish();
    return this.canvas.toDataURL("image/png");
  }

  dispose(): void {
    this.pause();
    this.compositor?.dispose();
    this.post?.dispose();
  }
}

// import locale per evitare dipendenza circolare in cima
import { buildHeader as buildHeaderStr } from "./programs";
