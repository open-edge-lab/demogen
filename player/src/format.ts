// Parsing/validazione minima del payload .demo (la validazione completa è in Python).

import type { Profile } from "./programs";
import type { SceneSlot, Timeline } from "./timeline";

export interface DemoPayload {
  format: string;
  meta: {
    title: string;
    duration_s: number;
    loop: boolean;
    bpm: number;
    beats_per_bar: number;
  };
  timeline: Timeline & { scenes: SceneSlot[] };
  common: string;
  scenes: Record<string, string>;
  render: {
    profile: Profile;
    overrides?: Record<string, Profile>;
    retro?: { internal_resolution: [number, number]; upscale: string };
  };
  text?: string | null;
  post?: { bloom?: { threshold: number; intensity: number; radius: number } };
  quality?: { min_scale?: number; target_fps?: number };
  audio?: string; // Fase 2: sorgente GLSL con mainAudio(out vec4, in float t)
}

export const MAX_PAYLOAD_BYTES = 1024 * 1024;
export const MAX_SCENE_BYTES = 256 * 1024;

const TRANSITIONS = ["cut", "crossfade", "flash", "fade_black"];
const pos = (v: unknown): boolean => typeof v === "number" && Number.isFinite(v) && v > 0;
const own = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

export function parsePayload(json: unknown, rawBytes?: number): DemoPayload {
  const p = json as DemoPayload;
  if (!p || typeof p !== "object") throw new Error("Payload non è un oggetto");
  // il limite vale sempre: se il chiamante non conosce i byte grezzi, si misura il JSON
  const size = rawBytes ?? new TextEncoder().encode(JSON.stringify(json)).length;
  if (size > MAX_PAYLOAD_BYTES) {
    throw new Error(`Payload troppo grande: ${size} > ${MAX_PAYLOAD_BYTES} byte`);
  }
  if (p.format !== "demogen/1") throw new Error(`Formato non supportato: ${p.format}`);
  if (!p.meta || typeof p.meta.bpm !== "number" || typeof p.meta.duration_s !== "number") {
    throw new Error("meta mancante o invalido");
  }
  const tl = p.timeline;
  if (!tl || !Array.isArray(tl.scenes) || tl.scenes.length === 0) {
    throw new Error("timeline.scenes mancante");
  }
  if (!pos(tl.bpm) || !pos(tl.beats_per_bar)) throw new Error("timeline.bpm e beats_per_bar devono essere > 0");
  for (const s of tl.scenes) {
    if (typeof s.id !== "string" || typeof s.start_bar !== "number" || !pos(s.bars)) {
      throw new Error("SceneSlot invalido (id stringa, start_bar numero, bars > 0)");
    }
    if (s.transition_in !== undefined && !TRANSITIONS.includes(s.transition_in)) {
      throw new Error(`scena ${s.id}: transition_in invalido: ${s.transition_in}`);
    }
  }
  if (typeof p.common !== "string") throw new Error("common mancante");
  if (!p.scenes || typeof p.scenes !== "object") throw new Error("scenes mancante");
  for (const [id, src] of Object.entries(p.scenes)) {
    if (typeof src !== "string") throw new Error(`scena ${id} non è stringa`);
    if (new TextEncoder().encode(src).length > MAX_SCENE_BYTES) {
      throw new Error(`scena ${id} troppo grande`);
    }
  }
  for (const s of tl.scenes) {
    // hasOwnProperty, non `in`: "toString" o "constructor" non sono scene
    if (!own(p.scenes, s.id)) throw new Error(`scena ${s.id} senza sorgente in scenes`);
  }
  if (p.render?.profile !== "modern" && p.render?.profile !== "retro") {
    throw new Error("render.profile invalido");
  }
  if (p.text !== undefined && p.text !== null && typeof p.text !== "string") {
    throw new Error("text deve essere una stringa");
  }
  if (p.audio !== undefined) {
    if (typeof p.audio !== "string") throw new Error("audio deve essere una stringa GLSL");
    if (new TextEncoder().encode(p.audio).length > MAX_SCENE_BYTES) {
      throw new Error("audio troppo grande");
    }
  }
  return p;
}

export const MAX_TEXT_BYTES = 256;

/** Byte UTF-8 dello scroller (troncati a 256): font.glsl indicizza byte, non caratteri UTF-16. */
function textBytes(text: string | null | undefined): Uint8Array {
  if (!text) return new Uint8Array(0);
  return new TextEncoder().encode(text).subarray(0, MAX_TEXT_BYTES);
}

/** Lunghezza in byte dello scroller come la vede lo shader (uTextLen). */
export function textByteLength(text: string | null | undefined): number {
  return textBytes(text).length;
}

/** Codifica il testo dello scroller in uText[64] (4 byte per int, max 256 byte). */
export function textToUniform(text: string | null | undefined): Int32Array {
  const out = new Int32Array(64);
  const bytes = textBytes(text);
  for (let i = 0; i < bytes.length; i += 4) {
    let v = 0;
    for (let k = 0; k < 4 && i + k < bytes.length; k++) {
      v |= (bytes[i + k] & 0xff) << (8 * k);
    }
    out[(i / 4) | 0] = v | 0;
  }
  return out;
}
