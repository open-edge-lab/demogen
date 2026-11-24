// Assemblaggio e compilazione dei programmi shader: header + common + scena.
// Contratto (piano v2 §5.1): l'LLM scrive solo mainImage; il player fornisce
// header, uniform di sincronizzazione, definizioni e il main().

import { compileShader, createProgram, VERT } from "./gl";

export type Profile = "modern" | "retro";

export interface SceneDef {
  id: string;
  src: string; // corpo di mainImage
  profile: Profile; // profilo effettivo (demo + override)
}

export interface HeaderOpts {
  bpm: number;
  retro: boolean;
  withText: boolean;
  /** true se la scena definisce `float map(vec3 p)` (raymarching). */
  hasMap: boolean;
}

export function buildHeader(opts: HeaderOpts): string {
  return `#version 300 es
precision highp float;
precision highp int;
uniform vec3  iResolution;
uniform float iTime;
uniform float uSceneTime;
uniform float uSceneProgress;
uniform float uBeat;
uniform float uBeatPhase;
uniform float uBar;
uniform float uQuality;
uniform float uFlashLimit;
uniform vec2  uJitter;
${opts.withText ? "uniform highp int uText[64];\nuniform int uTextLen;\n" : ""}
#define BPM ${opts.bpm.toFixed(4)}
${opts.retro ? "#define PROFILE_RETRO\n" : ""}
void mainImage(out vec4 fragColor, in vec2 fragCoord);
${
  opts.hasMap
    ? "// forward declaration: la scena definisce map() nel proprio corpo\nfloat map(vec3 p);"
    : "// default: nessun SDF (le scene senza raymarching non toccano map)\nfloat map(vec3 p) { return 1e9; }"
}
`;
}

const MAIN = `
out vec4 demogen_FragColor;
void main() { mainImage(demogen_FragColor, gl_FragCoord.xy); }
`;

export function buildFragment(header: string, common: string, sceneSrc: string): string {
  return header + common + MAIN + "\n" + sceneSrc;
}

export interface CompiledProgram {
  prog: WebGLProgram;
  loc: Record<string, WebGLUniformLocation | null>;
}

const UNIFORMS = [
  "iResolution",
  "iTime",
  "uSceneTime",
  "uSceneProgress",
  "uBeat",
  "uBeatPhase",
  "uBar",
  "uQuality",
  "uFlashLimit",
  "uJitter",
  "uText",
  "uTextLen",
];

export function linkScene(
  gl: WebGL2RenderingContext,
  header: string,
  common: string,
  sceneSrc: string,
): CompiledProgram {
  const prog = createProgram(gl, buildFragment(header, common, sceneSrc));
  const loc: Record<string, WebGLUniformLocation | null> = {};
  for (const name of UNIFORMS) loc[name] = gl.getUniformLocation(prog, name);
  return { prog, loc };
}

/**
 * Compila tutte le scene; se KHR_parallel_shader_compile è presente, interroga
 * COMPLETION_STATUS_KHR finché tutti non sono pronti (niente freeze della pagina).
 */
export function compileAll(
  gl: WebGL2RenderingContext,
  headerFor: (scene: SceneDef) => string,
  commonByProfile: Record<Profile, string>,
  scenes: SceneDef[],
  onProgress?: (done: number, total: number) => void,
): Promise<Map<string, CompiledProgram>> {
  const ext = gl.getExtension("KHR_parallel_shader_compile");
  const out = new Map<string, CompiledProgram>();
  const progs: WebGLProgram[] = [];
  for (const s of scenes) {
    const common = commonByProfile[s.profile] ?? commonByProfile.modern;
    // compila in due fasi: crea e compila i sorgenti, poi linka (come fa il browser)
    const src = buildFragment(headerFor(s), common, s.src);
    const vs = compileShader(gl, gl.VERTEX_SHADER, VERT);
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, src);
    const prog = gl.createProgram();
    if (!prog) throw new Error("createProgram fallita");
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    progs.push(prog);
    const loc: Record<string, WebGLUniformLocation | null> = {};
    for (const name of UNIFORMS) loc[name] = gl.getUniformLocation(prog, name);
    out.set(s.id, { prog, loc });
    onProgress?.(out.size, scenes.length);
  }
  if (!ext) return Promise.resolve(out);
  return new Promise((resolve) => {
    const check = () => {
      let done = true;
      for (const p of progs) {
        if (gl.getProgramParameter(p, ext.COMPLETION_STATUS_KHR) !== true) done = false;
      }
      if (done) resolve(out);
      else setTimeout(check, 16);
    };
    check();
  });
}
