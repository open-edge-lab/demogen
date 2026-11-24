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
  const vs = gl.createShader(gl.VERTEX_SHADER)!;
  gl.shaderSource(vs, PASS_VERT);
  gl.compileShader(vs);
  const fs = gl.createShader(gl.FRAGMENT_SHADER)!;
  gl.shaderSource(fs, frag);
  gl.compileShader(fs);
  const p = gl.createProgram()!;
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)!);
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
    for (const [prog, names] of [
      [this.bright, ["uTex", "uThreshold"]],
      [this.blur, ["uTex", "uDir"]],
      [this.add, ["uTex", "uBloom", "uIntensity"]],
    ] as const) {
      for (const n of names) this.loc[`${prog}:${n}`] = gl.getUniformLocation(prog, n);
    }
  }

  /** Applica il bloom (se params non null) e blitta il risultato sul target corrente. */
  apply(sceneTex: WebGLTexture, outW: number, outH: number, params: BloomParams | null): void {
    const gl = this.gl;
    if (!params) {
      this.comp.blit(sceneTex, outW, outH);
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
    gl.uniform1i(this.loc[`${this.bright}:uTex`], 0);
    gl.uniform1f(this.loc[`${this.bright}:uThreshold`], params.threshold);
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
      gl.uniform1i(this.loc[`${this.blur}:uTex`], 0);
      gl.uniform2f(this.loc[`${this.blur}:uDir`], dir[0], dir[1]);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    // add sul framebuffer corrente (canvas o FBO di output)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, outW, outH);
    gl.useProgram(this.add);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, sceneTex);
    gl.uniform1i(this.loc[`${this.add}:uTex`], 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.halfA.tex);
    gl.uniform1i(this.loc[`${this.add}:uBloom`], 1);
    gl.uniform1f(this.loc[`${this.add}:uIntensity`], params.intensity);
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
