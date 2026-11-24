// Spike del motore demogen: rendering WebGL2 di uno shader stile Shadertoy.
// Contratto (stabile dalla Fase 1): GLSL ES 3.00, l'utente scrive solo
//   void mainImage(out vec4 fragColor, in vec2 fragCoord)
// e il player fornisce header, uniform iResolution/iTime e il main().

export interface DemogenInfo {
  webgl2: boolean;
  renderer: string;
  vendor: string;
  version: string;
  extensions: string[];
  maxTextureSize: number;
}

const VERT = `#version 300 es
layout(location = 0) in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG_HEADER = `#version 300 es
precision highp float;
precision highp int;
uniform vec3 iResolution;
uniform float iTime;
void mainImage(out vec4 fragColor, in vec2 fragCoord);
`;

const FRAG_MAIN = `
out vec4 demogen_FragColor;
void main() { mainImage(demogen_FragColor, gl_FragCoord.xy); }
`;

/** Compone il fragment shader completo: header + main + codice utente. */
export function buildFragment(userFrag: string): string {
  return FRAG_HEADER + FRAG_MAIN + "\n" + userFrag;
}

/** Riconosce un renderer software (CPU) dal nome. */
export function isSoftwareRenderer(name: string): boolean {
  const n = name.toLowerCase();
  return (
    n.includes("swiftshader") ||
    n.includes("llvmpipe") ||
    n.includes("softpipe") ||
    n.includes("software")
  );
}

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type);
  if (!sh) throw new Error("createShader fallita");
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`Errore di compilazione shader:\n${log}\n--- sorgente ---\n${src}`);
  }
  return sh;
}

export class SpikePlayer {
  readonly gl: WebGL2RenderingContext;
  private prog: WebGLProgram;
  private locRes: WebGLUniformLocation | null;
  private locTime: WebGLUniformLocation | null;
  readonly start = performance.now();

  constructor(readonly canvas: HTMLCanvasElement, userFrag: string) {
    const gl = canvas.getContext("webgl2", {
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
      // spike: true per catturare via toDataURL; in Fase 1 false + readPixels
      preserveDrawingBuffer: true,
    });
    if (!gl) throw new Error("WebGL2 non disponibile in questo browser");
    this.gl = gl;

    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, buildFragment(userFrag));
    const prog = gl.createProgram();
    if (!prog) throw new Error("createProgram fallita");
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error(`Errore di link:\n${gl.getProgramInfoLog(prog)}`);
    }
    this.prog = prog;
    this.locRes = gl.getUniformLocation(prog, "iResolution");
    this.locTime = gl.getUniformLocation(prog, "iTime");

    const vbo = gl.createBuffer();
    if (!vbo) throw new Error("createBuffer fallita");
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    // triangolo fullscreen
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.useProgram(prog);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.resize();
  }

  resize(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.floor(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
  }

  /** Renderizza un frame al tempo t (secondi). Fuori da rAF è deterministico. */
  renderAt(t: number): void {
    const gl = this.gl;
    gl.useProgram(this.prog);
    gl.uniform3f(this.locRes, this.canvas.width, this.canvas.height, 1);
    gl.uniform1f(this.locTime, t);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
}

/** Informazioni sul contesto: renderer (anche unmasked), vendor, estensioni, limiti. */
export function info(gl: WebGL2RenderingContext): DemogenInfo {
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  const renderer = ext
    ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL))
    : String(gl.getParameter(gl.RENDERER));
  const vendor = ext
    ? String(gl.getParameter(ext.UNMASKED_VENDOR_WEBGL))
    : String(gl.getParameter(gl.VENDOR));
  return {
    webgl2: true,
    renderer,
    vendor,
    version: String(gl.getParameter(gl.VERSION)),
    extensions: gl.getSupportedExtensions() ?? [],
    maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
  };
}

export interface Harness {
  info(): DemogenInfo;
  renderAt(t: number): void;
  /** Data URL PNG del frame al tempo t. */
  capture(t: number): string;
  /** ms mediani per tempo, fuori da rAF (deterministico). */
  profile(times: number[], repeats?: number): Record<number, number>;
}

/** Installa window.__demogen: API di pilotaggio via Playwright (solo build di test). */
export function installHarness(player: SpikePlayer): Harness {
  const gl = player.gl;
  return {
    info: () => info(gl),
    renderAt: (t: number) => player.renderAt(t),
    capture: (t: number) => {
      player.resize();
      player.renderAt(t);
      gl.finish();
      return player.canvas.toDataURL("image/png");
    },
    profile: (times: number[], repeats = 3) => {
      // batch di draw: la singola draw può stare sotto la risoluzione del timer
      const BATCH = 10;
      const out: Record<number, number> = {};
      for (const t of times) {
        const samples: number[] = [];
        for (let i = 0; i < repeats; i++) {
          const t0 = performance.now();
          for (let k = 0; k < BATCH; k++) player.renderAt(t);
          gl.finish();
          samples.push((performance.now() - t0) / BATCH);
        }
        samples.sort((a, b) => a - b);
        out[t] = samples[Math.floor(samples.length / 2)];
      }
      return out;
    },
  };
}
