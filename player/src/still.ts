// Immagini fisse (SOLO harness, mai nel player distribuito): un tile dell'immagine intera con
// N campioni sub-pixel sommati in un FBO float. Ogni campione è un draw call breve seguito da
// una sincronizzazione: anche con migliaia di campioni nessun singolo comando tiene la GPU
// abbastanza a lungo da far scattare il watchdog (TDR di Windows, ~2 s) e perdere il contesto.

import { createProgram } from "./gl";
import type { DemoPayload } from "./format";
import type { Player } from "./player";
import { stateAt, Timeline } from "./timeline";

export interface StillTileOpts {
  t: number;
  /** Immagine intera (iResolution). */
  width: number;
  height: number;
  /** Angolo del tile in coordinate GL (origine in basso a sinistra) e sue dimensioni. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** Campioni per pixel (1 = centro del pixel, identico al frame realtime). */
  spp: number;
  /** uQuality: 1 = piena qualità realtime; oltre 1 qSteps/qOctaves crescono ancora. */
  quality: number;
}

export interface StillTile {
  /** RGB 8 bit, righe dal basso (ordine di readPixels), base64. */
  data: string;
  msTotal: number;
  msMax: number;
}

const ACC_FRAG = `#version 300 es
precision highp float;
uniform sampler2D uAcc;
uniform sampler2D uSample;
out vec4 o;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  o = texelFetch(uAcc, p, 0) + texelFetch(uSample, p, 0);
}
`;

/** Sequenza R2 (bassa discrepanza) in [-0.5, 0.5)²; il campione 0 è il centro del pixel. */
export function r2Jitter(k: number): [number, number] {
  const fr = (v: number): number => v - Math.floor(v);
  return [fr(0.5 + k * 0.7548776662466927) - 0.5, fr(0.5 + k * 0.5698402909980532) - 0.5];
}

/** Il profilo retro ha una risoluzione interna fissa: un'immagine grande non aggiunge niente. */
export function assertModernAt(p: DemoPayload, t: number): void {
  const st = stateAt(p.timeline as Timeline, t);
  for (const id of [st.sceneId, st.nextSceneId]) {
    if (id && (p.render.overrides?.[id] ?? p.render.profile) === "retro") {
      throw new Error(`scene ${id} uses the retro profile (fixed internal resolution): stills support modern scenes only`);
    }
  }
}

export function bytesToB64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
  }
  return btoa(bin);
}

interface FloatTarget {
  fbo: WebGLFramebuffer;
  tex: WebGLTexture;
}

function floatTarget(gl: WebGL2RenderingContext, w: number, h: number): FloatTarget {
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA32F, w, h);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  const fbo = gl.createFramebuffer()!;
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
    gl.deleteFramebuffer(fbo);
    gl.deleteTexture(tex);
    throw new Error("float FBO incomplete");
  }
  return { fbo, tex };
}

/** Renderizza un tile: somma di `spp` campioni jitterati, poi media → RGB 8 bit. */
export function renderStillTile(player: Player, payload: DemoPayload, o: StillTileOpts): StillTile {
  const gl = player.gl;
  if (!gl.getExtension("EXT_color_buffer_float")) throw new Error("EXT_color_buffer_float not available");
  assertModernAt(payload, o.t);
  const { w, h } = o;
  const spp = Math.max(1, Math.floor(o.spp));
  const q = { scale: 1, uQuality: o.quality, bloom: false };
  const prog = createProgram(gl, ACC_FRAG);
  const uAcc = gl.getUniformLocation(prog, "uAcc");
  const uSample = gl.getUniformLocation(prog, "uSample");
  let a = floatTarget(gl, w, h);
  let b = floatTarget(gl, w, h);
  const px = new Float32Array(4);
  try {
    gl.bindFramebuffer(gl.FRAMEBUFFER, a.fbo);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    let msTotal = 0;
    let msMax = 0;
    for (let k = 0; k < spp; k++) {
      const [jx, jy] = spp === 1 ? [0, 0] : r2Jitter(k);
      const t0 = performance.now();
      const sample = player.composeAt(o.t, w, h, q, [o.width, o.height], [o.x + jx, o.y + jy]);
      gl.bindFramebuffer(gl.FRAMEBUFFER, b.fbo);
      gl.viewport(0, 0, w, h);
      gl.useProgram(prog);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, a.tex);
      gl.uniform1i(uAcc, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, sample.tex);
      gl.uniform1i(uSample, 1);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      // via le texture dalle unità: il campione successivo scrive in quell'FBO
      gl.bindTexture(gl.TEXTURE_2D, null);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, null);
      // la lettura di un pixel aspetta la fine del lavoro: un comando alla volta sulla GPU
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.FLOAT, px);
      // contesto perso (watchdog): da qui ogni chiamata è un no-op e il tile verrebbe nero in silenzio
      if (gl.isContextLost()) throw new Error(`WebGL context lost at sample ${k + 1}/${spp} (GPU watchdog?): use a smaller tile`);
      const ms = performance.now() - t0;
      msTotal += ms;
      msMax = Math.max(msMax, ms);
      [a, b] = [b, a];
    }
    const sum = new Float32Array(w * h * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, a.fbo);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.FLOAT, sum);
    const rgb = new Uint8Array(w * h * 3);
    const inv = 255 / spp;
    for (let i = 0, j = 0; i < sum.length; i += 4, j += 3) {
      // il campione è già unorm 8 bit (FBO RGBA8 del compositor): la media sta in [0, 255]
      rgb[j] = Math.min(255, Math.round(sum[i] * inv));
      rgb[j + 1] = Math.min(255, Math.round(sum[i + 1] * inv));
      rgb[j + 2] = Math.min(255, Math.round(sum[i + 2] * inv));
    }
    return { data: bytesToB64(rgb), msTotal, msMax };
  } finally {
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.deleteProgram(prog);
    for (const ft of [a, b]) {
      gl.deleteFramebuffer(ft.fbo);
      gl.deleteTexture(ft.tex);
    }
  }
}
