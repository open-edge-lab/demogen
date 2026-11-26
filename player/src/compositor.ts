// Compositor: render delle scene in FBO e blend delle transizioni
// (cut / crossfade / flash / fade_black), anche tra profili diversi.

import { createFBO, deleteFBO, FBO, resizeFBO, bindFullscreenTriangle } from "./gl";
import type { CompiledProgram } from "./programs";
import type { TimelineState, Transition } from "./timeline";

export interface RenderEnv {
  t: number;
  state: TimelineState;
  width: number; // risoluzione interna a cui renderizzare le scene
  height: number;
  uQuality: number;
  uFlashLimit: number;
  text: Int32Array;
  textLen: number;
}

const PASS_VERT = `#version 300 es
layout(location = 0) in vec2 aPos;
out vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const BLEND_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uTexA;
uniform sampler2D uTexB;
uniform float uAlpha;
uniform float uFlashLimit; // limite fotosensibilità del player (1 = pieno)
uniform int uMode; // 0=crossfade 1=flash 2=fade_black
in vec2 vUv;
out vec4 o;
void main() {
  vec4 a = texture(uTexA, vUv);
  vec4 b = texture(uTexB, vUv);
  if (uMode == 0) {
    o = mix(a, b, uAlpha);
  } else if (uMode == 1) {
    float w = sin(3.14159265 * uAlpha); // picco bianco a metà transizione
    o = mix(a, b, uAlpha) + vec4(vec3(w * 0.7 * uFlashLimit), 0.0);
  } else {
    float w = 1.0 - sin(3.14159265 * uAlpha); // va a nero a metà
    o = mix(a, b, uAlpha) * w;
  }
}
`;

const BLIT_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uTex;
in vec2 vUv;
out vec4 o;
void main() { o = texture(uTex, vUv); }
`;

function transitionMode(tr: Transition): number {
  return tr === "crossfade" ? 0 : tr === "flash" ? 1 : 2;
}

function makeProg(gl: WebGL2RenderingContext, vert: string, frag: string): WebGLProgram {
  const vs = gl.createShader(gl.VERTEX_SHADER)!;
  gl.shaderSource(vs, vert);
  gl.compileShader(vs);
  if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(vs)!);
  const fs = gl.createShader(gl.FRAGMENT_SHADER)!;
  gl.shaderSource(fs, frag);
  gl.compileShader(fs);
  if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(fs)!);
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
    throw new Error(log ?? "link failed");
  }
  return p;
}

export class Compositor {
  private fboA: FBO;
  private fboB: FBO;
  private fboC: FBO;
  private blendProg: WebGLProgram;
  private blitProg: WebGLProgram;
  private locBlend: Record<string, WebGLUniformLocation | null>;
  private locBlit: Record<string, WebGLUniformLocation | null>;
  private vbo: WebGLBuffer | null;

  constructor(private gl: WebGL2RenderingContext, w: number, h: number) {
    this.fboA = createFBO(gl, w, h);
    this.fboB = createFBO(gl, w, h);
    this.fboC = createFBO(gl, w, h);
    this.blendProg = makeProg(gl, PASS_VERT, BLEND_FRAG);
    this.blitProg = makeProg(gl, PASS_VERT, BLIT_FRAG);
    this.locBlend = {
      uTexA: gl.getUniformLocation(this.blendProg, "uTexA"),
      uTexB: gl.getUniformLocation(this.blendProg, "uTexB"),
      uAlpha: gl.getUniformLocation(this.blendProg, "uAlpha"),
      uFlashLimit: gl.getUniformLocation(this.blendProg, "uFlashLimit"),
      uMode: gl.getUniformLocation(this.blendProg, "uMode"),
    };
    this.locBlit = { uTex: gl.getUniformLocation(this.blitProg, "uTex") };
    this.vbo = bindFullscreenTriangle(gl);
  }

  private ensureSize(w: number, h: number): void {
    resizeFBO(this.gl, this.fboA, w, h);
    resizeFBO(this.gl, this.fboB, w, h);
    resizeFBO(this.gl, this.fboC, w, h);
  }

  /** Disegna una scena nell'FBO. */
  drawScene(target: FBO, cp: CompiledProgram, env: RenderEnv): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    gl.viewport(0, 0, target.width, target.height);
    gl.useProgram(cp.prog);
    const L = cp.loc;
    gl.uniform3f(L.iResolution, target.width, target.height, 1);
    gl.uniform1f(L.iTime, env.t);
    gl.uniform1f(L.uSceneTime, env.state.sceneTime);
    gl.uniform1f(L.uSceneProgress, env.state.sceneProgress);
    gl.uniform1f(L.uBeat, env.state.beat);
    gl.uniform1f(L.uBeatPhase, env.state.beat - Math.floor(env.state.beat));
    gl.uniform1f(L.uBar, env.state.bar);
    gl.uniform1f(L.uQuality, env.uQuality);
    gl.uniform1f(L.uFlashLimit, env.uFlashLimit);
    gl.uniform2f(L.uJitter, 0, 0);
    if (L.uText) gl.uniform1iv(L.uText, env.text);
    if (L.uTextLen) gl.uniform1i(L.uTextLen, env.textLen);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  /**
   * Renderizza lo stato corrente. Ritorna l'FBO con il risultato e il numero di
   * scene disegnate (1 per cut, 2 durante una transizione).
   */
  render(env: RenderEnv, progByScene: Map<string, CompiledProgram>): { fbo: FBO; drawn: number } {
    const st = env.state;
    const cur = progByScene.get(st.sceneId);
    if (!cur) throw new Error(`scene ${st.sceneId} not compiled`);
    this.ensureSize(env.width, env.height);
    const hasTransition =
      st.transition !== "cut" && st.prevSceneId !== null && st.nextSceneId !== null;
    if (!hasTransition) {
      this.drawScene(this.fboA, cur, env);
      return { fbo: this.fboA, drawn: 1 };
    }
    // stateAt rende sempre attiva la scena USCENTE: quella entrante è nextSceneId, col suo tempo
    const otherId = st.nextSceneId!;
    const other = progByScene.get(otherId);
    if (!other) throw new Error(`scene ${otherId} not compiled`);
    this.drawScene(this.fboA, cur, env);
    const incoming: TimelineState = {
      ...st,
      sceneId: otherId,
      sceneTime: st.nextSceneTime ?? 0,
      sceneProgress: 0,
    };
    this.drawScene(this.fboB, other, { ...env, state: incoming });
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fboC.fbo);
    gl.viewport(0, 0, this.fboC.width, this.fboC.height);
    gl.useProgram(this.blendProg);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.fboA.tex);
    gl.uniform1i(this.locBlend.uTexA, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.fboB.tex);
    gl.uniform1i(this.locBlend.uTexB, 1);
    gl.uniform1f(this.locBlend.uAlpha, st.alpha);
    gl.uniform1f(this.locBlend.uFlashLimit, env.uFlashLimit);
    gl.uniform1i(this.locBlend.uMode, transitionMode(st.transition));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    return { fbo: this.fboC, drawn: 2 };
  }

  /** Blit di una texture sul framebuffer corrente (canvas o FBO), a w×h con l'angolo in (x, y). */
  blit(tex: WebGLTexture, w: number, h: number, x = 0, y = 0): void {
    const gl = this.gl;
    gl.viewport(x, y, w, h);
    gl.useProgram(this.blitProg);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.uniform1i(this.locBlit.uTex, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  dispose(): void {
    deleteFBO(this.gl, this.fboA);
    deleteFBO(this.gl, this.fboB);
    deleteFBO(this.gl, this.fboC);
    this.gl.deleteProgram(this.blendProg);
    this.gl.deleteProgram(this.blitProg);
    if (this.vbo) this.gl.deleteBuffer(this.vbo);
    this.vbo = null;
  }
}
