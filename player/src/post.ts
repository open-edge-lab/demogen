// Post-processing fisso del player: bloom opzionale (bright + blur separabile
// a 1/4 di risoluzione + add). Il finalize (tonemap/gamma) vive nello shader di
// scena tramite style/common, non qui.

import { createFBO, deleteFBO, FBO, resizeFBO } from "./gl";
import { Compositor } from "./compositor";

const PASS_VERT = `#version 300 es
layout(location = 0) in vec2 aPos;
out vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const BRIGHT_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uTex;
uniform float uThreshold;
in vec2 vUv;
out vec4 o;
void main() {
  vec3 c = texture(uTex, vUv).rgb;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  o = vec4(c * smoothstep(uThreshold, uThreshold + 0.25, l), 1.0);
}
`;

const BLUR_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uTex;
uniform vec2 uDir; // (1/w,0) oppure (0,1/h)
in vec2 vUv;
out vec4 o;
void main() {
  vec3 acc = texture(uTex, vUv).rgb * 0.227027;
  vec2 o1 = uDir * 1.3846153846, o2 = uDir * 3.2307692308;
  acc += (texture(uTex, vUv + o1).rgb + texture(uTex, vUv - o1).rgb) * 0.3162162162;
  acc += (texture(uTex, vUv + o2).rgb + texture(uTex, vUv - o2).rgb) * 0.0702702703;
  o = vec4(acc, 1.0);
}
`;

const ADD_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uTex;
uniform sampler2D uBloom;
uniform float uIntensity;
in vec2 vUv;
out vec4 o;
void main() {
  vec3 c = texture(uTex, vUv).rgb + texture(uBloom, vUv).rgb * uIntensity;
  o = vec4(c, 1.0);
}
`;

function makeProg(gl: WebGL2RenderingContext, frag: string): WebGLProgram {
  const sh = (type: number, src: string): WebGLShader => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error(`post: compile failed: ${log}`);
    }
    return s;
  };
  const vs = sh(gl.VERTEX_SHADER, PASS_VERT);
  let fs: WebGLShader;
  try {
    fs = sh(gl.FRAGMENT_SHADER, frag);
  } catch (e) {
    gl.deleteShader(vs);
    throw e;
  }
  const p = gl.createProgram()!;
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.linkProgram(p);
  const ok = gl.getProgramParameter(p, gl.LINK_STATUS);
  const log = ok ? "" : gl.getProgramInfoLog(p);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!ok) {
    gl.deleteProgram(p);
    throw new Error(`post: link failed: ${log}`);
  }
  return p;
}

export interface BloomParams {
  threshold: number;
  intensity: number;
}

export class Post {
  private bright: WebGLProgram;
  private blur: WebGLProgram;
  private add: WebGLProgram;
  private halfA: FBO;
  private halfB: FBO;
  private loc: Record<string, WebGLUniformLocation | null> = {};

  constructor(private gl: WebGL2RenderingContext, private comp: Compositor, w: number, h: number) {
    this.bright = makeProg(gl, BRIGHT_FRAG);
    this.blur = makeProg(gl, BLUR_FRAG);
    this.add = makeProg(gl, ADD_FRAG);
    this.halfA = createFBO(gl, Math.max(1, w >> 2), Math.max(1, h >> 2));
    this.halfB = createFBO(gl, Math.max(1, w >> 2), Math.max(1, h >> 2));
    // chiave per TAG di programma: `${prog}` varrebbe "[object WebGLProgram]" per tutti e tre
    for (const [tag, prog, names] of [
      ["b", this.bright, ["uTex", "uThreshold"]],
      ["r", this.blur, ["uTex", "uDir"]],
      ["a", this.add, ["uTex", "uBloom", "uIntensity"]],
    ] as const) {
      for (const n of names) this.loc[`${tag}:${n}`] = gl.getUniformLocation(prog, n);
    }
  }

  /** Applica il bloom (se params non null) e blitta il risultato sul target corrente, angolo in (x, y). */
  apply(sceneTex: WebGLTexture, outW: number, outH: number, params: BloomParams | null, x = 0, y = 0): void {
    const gl = this.gl;
    if (!params) {
      this.comp.blit(sceneTex, outW, outH, x, y);
      return;
    }
    resizeFBO(gl, this.halfA, Math.max(1, outW >> 2), Math.max(1, outH >> 2));
    resizeFBO(gl, this.halfB, this.halfA.width, this.halfA.height);
    // bright → halfA
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.halfA.fbo);
    gl.viewport(0, 0, this.halfA.width, this.halfA.height);
    gl.useProgram(this.bright);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, sceneTex);
    gl.uniform1i(this.loc[`b:uTex`], 0);
    gl.uniform1f(this.loc[`b:uThreshold`], params.threshold);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    // blur H: halfA → halfB, blur V: halfB → halfA
    for (const [src, dst, dir] of [
      [this.halfA, this.halfB, [1 / this.halfA.width, 0]],
      [this.halfB, this.halfA, [0, 1 / this.halfA.height]],
    ] as const) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
      gl.viewport(0, 0, dst.width, dst.height);
      gl.useProgram(this.blur);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, src.tex);
      gl.uniform1i(this.loc[`r:uTex`], 0);
      gl.uniform2f(this.loc[`r:uDir`], dir[0], dir[1]);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    // add sul framebuffer corrente (canvas o FBO di output)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(x, y, outW, outH);
    gl.useProgram(this.add);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, sceneTex);
    gl.uniform1i(this.loc[`a:uTex`], 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.halfA.tex);
    gl.uniform1i(this.loc[`a:uBloom`], 1);
    gl.uniform1f(this.loc[`a:uIntensity`], params.intensity);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.activeTexture(gl.TEXTURE0);
  }

  dispose(): void {
    deleteFBO(this.gl, this.halfA);
    deleteFBO(this.gl, this.halfB);
    this.gl.deleteProgram(this.bright);
    this.gl.deleteProgram(this.blur);
    this.gl.deleteProgram(this.add);
  }
}
