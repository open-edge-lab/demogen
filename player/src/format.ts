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
  text?: string;
  post?: { bloom?: { threshold: number; intensity: number; radius: number } };
  quality?: { min_scale?: number; target_fps?: number };
  audio?: string; // Fase 2: sorgente GLSL con mainAudio(out vec4, in float t)
}

export const MAX_PAYLOAD_BYTES = 1024 * 1024;
export const MAX_SCENE_BYTES = 256 * 1024;

export function parsePayload(json: unknown, rawBytes?: number): DemoPayload {
  if (rawBytes !== undefined && rawBytes > MAX_PAYLOAD_BYTES) {
    throw new Error(`Payload troppo grande: ${rawBytes} > ${MAX_PAYLOAD_BYTES} byte`);
  }
  const p = json as DemoPayload;
  if (!p || typeof p !== "object") throw new Error("Payload non è un oggetto");
  if (p.format !== "demogen/1") throw new Error(`Formato non supportato: ${p.format}`);
  if (!p.meta || typeof p.meta.bpm !== "number" || typeof p.meta.duration_s !== "number") {
    throw new Error("meta mancante o invalido");
  }
  if (!p.timeline || !Array.isArray(p.timeline.scenes) || p.timeline.scenes.length === 0) {
    throw new Error("timeline.scenes mancante");
  }
  for (const s of p.timeline.scenes) {
    if (typeof s.id !== "string" || typeof s.start_bar !== "number" || typeof s.bars !== "number") {
      throw new Error("SceneSlot invalido");
    }
  }
  if (typeof p.common !== "string") throw new Error("common mancante");
  if (!p.scenes || typeof p.scenes !== "object") throw new Error("scenes mancante");
  for (const [id, src] of Object.entries(p.scenes)) {
    if (typeof src !== "string") throw new Error(`scena ${id} non è stringa`);
    if (new TextEncoder().encode(src).length > MAX_SCENE_BYTES) {
      throw new Error(`scena ${id} troppo grande`);
    }
    if (!(id in p.scenes)) throw new Error(`scena ${id} senza sorgente`);
  }
  for (const s of p.timeline.scenes) {
    if (!(s.id in p.scenes)) throw new Error(`scena ${s.id} senza sorgente in scenes`);
  }
  if (p.render?.profile !== "modern" && p.render?.profile !== "retro") {
    throw new Error("render.profile invalido");
  }
  if (p.audio !== undefined) {
    if (typeof p.audio !== "string") throw new Error("audio deve essere una stringa GLSL");
    if (new TextEncoder().encode(p.audio).length > MAX_SCENE_BYTES) {
      throw new Error("audio troppo grande");
    }
  }
  return p;
}

/** Codifica il testo dello scroller in uText[64] (4 caratteri ASCII per int). */
export function textToUniform(text: string | undefined): Int32Array {
  const out = new Int32Array(64);
  if (!text) return out;
  const bytes = new TextEncoder().encode(text.slice(0, 256));
  for (let i = 0; i < bytes.length; i += 4) {
    let v = 0;
    for (let k = 0; k < 4 && i + k < bytes.length; k++) {
      v |= (bytes[i + k] & 0xff) << (8 * k);
    }
    out[(i / 4) | 0] = v | 0;
  }
  return out;
}
