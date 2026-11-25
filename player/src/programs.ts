// Assemblaggio e compilazione dei programmi shader: header + common + scena.
// Contratto (piano v2 §5.1): l'LLM scrive solo mainImage; il player fornisce
// header, uniform di sincronizzazione, definizioni e il main().

import { compileShader, VERT } from "./gl";

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
  /** true: la scena definisce `float map(vec3 p)` → forward declaration;
   *  "other": definisce map con un'altra firma (es. `vec2 map(vec3)`) → nessuna dichiarazione;
   *  false: nessuna map → default che ritorna 1e9. */
  hasMap: boolean | "other";
}

/** Come dichiarare map() per una scena (vedi HeaderOpts.hasMap); i commenti sono ignorati. */
export function detectMap(src: string): boolean | "other" {
  const code = src.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, " ");
  if (/\bfloat\s+map\s*\(\s*(?:in\s+)?vec3\b/.test(code)) return true;
  if (/\b\w+\s+map\s*\(/.test(code)) return "other";
  return false;
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
  opts.hasMap === true
    ? "// forward declaration: la scena definisce map() nel proprio corpo\nfloat map(vec3 p);"
    : opts.hasMap === "other"
      ? "// la scena definisce map() con una firma propria"
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

interface Pending {
  id: string;
  prog: WebGLProgram;
  fs: WebGLShader;
  src: string;
}

/**
 * Compila tutte le scene. Compile e link partono tutti insieme e gli esiti si leggono
 * solo alla fine: con KHR_parallel_shader_compile si interroga COMPLETION_STATUS_KHR
 * (niente freeze della pagina). Poi per ogni programma si verificano COMPILE_STATUS e
 * LINK_STATUS (un link fallito non deve passare come "ok" con frame neri), si
 * staccano e cancellano gli shader e solo allora si leggono le uniform.
 */
export function compileAll(
  gl: WebGL2RenderingContext,
  headerFor: (scene: SceneDef) => string,
  commonByProfile: Record<Profile, string>,
  scenes: SceneDef[],
  onProgress?: (done: number, total: number) => void,
): Promise<Map<string, CompiledProgram>> {
  const ext = gl.getExtension("KHR_parallel_shader_compile");
  const vs = compileShader(gl, gl.VERTEX_SHADER, VERT); // uno solo, condiviso
  const pending: Pending[] = [];
  for (const s of scenes) {
    const common = commonByProfile[s.profile] ?? commonByProfile.modern;
    const src = buildFragment(headerFor(s), common, s.src);
    const fs = gl.createShader(gl.FRAGMENT_SHADER);
    const prog = gl.createProgram();
    if (!fs || !prog) throw new Error("createShader/createProgram fallita");
    gl.shaderSource(fs, src);
    gl.compileShader(fs);
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    pending.push({ id: s.id, prog, fs, src });
  }

  const finish = (): Map<string, CompiledProgram> => {
    const out = new Map<string, CompiledProgram>();
    let err: Error | null = null;
    pending.forEach((p, i) => {
      if (!err && !gl.getShaderParameter(p.fs, gl.COMPILE_STATUS)) {
        err = new Error(`Errore compilazione shader:\n${gl.getShaderInfoLog(p.fs)}\n--- sorgente ---\n${p.src}`);
      } else if (!err && !gl.getProgramParameter(p.prog, gl.LINK_STATUS)) {
        err = new Error(`Errore di link (scena ${p.id}):\n${gl.getProgramInfoLog(p.prog)}`);
      }
      gl.detachShader(p.prog, vs);
      gl.detachShader(p.prog, p.fs);
      gl.deleteShader(p.fs);
      if (!err) {
        const loc: Record<string, WebGLUniformLocation | null> = {};
        for (const name of UNIFORMS) loc[name] = gl.getUniformLocation(p.prog, name);
        out.set(p.id, { prog: p.prog, loc });
        onProgress?.(i + 1, pending.length);
      }
    });
    gl.deleteShader(vs);
    if (err) {
      for (const p of pending) gl.deleteProgram(p.prog);
      throw err;
    }
    return out;
  };

  if (!ext) return Promise.resolve().then(finish);
  return new Promise((resolve, reject) => {
    const check = () => {
      const done = pending.every((p) => gl.getProgramParameter(p.prog, ext.COMPLETION_STATUS_KHR) === true);
      if (!done) return void setTimeout(check, 16);
      try {
        resolve(finish());
      } catch (e) {
        reject(e);
      }
    };
    check();
  });
}
