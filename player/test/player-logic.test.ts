// Batch F: logica pura del player (clock, pacing, scala adattiva, formato, audio scheduling).

import { describe, expect, it } from "vitest";

import { chunkSchedule, decodePack16 } from "../src/audio";
import { PlaybackClock } from "../src/clock";
import { MAX_PAYLOAD_BYTES, parsePayload, textByteLength, textToUniform } from "../src/format";
import { flashLimitFor, SAFE_FLASH_LIMIT } from "../src/player";
import { buildHeader, detectMap } from "../src/programs";
import { QualityController } from "../src/quality";

describe("PlaybackClock", () => {
  it("pause conserva la posizione e play riprende da lì", () => {
    let now = 0;
    const c = new PlaybackClock(() => now, 10, false);
    c.play();
    now = 3000;
    expect(c.time()).toBeCloseTo(3);
    c.pause();
    now = 9000; // in pausa il tempo non scorre
    expect(c.time()).toBeCloseTo(3);
    c.play();
    now = 10000;
    expect(c.time()).toBeCloseTo(4);
  });

  it("con audio master la pausa salva il tempo audio", () => {
    let now = 0;
    const c = new PlaybackClock(() => now, 10, false);
    c.play();
    now = 1000;
    c.pause(2.5); // l'audio è avanti/indietro rispetto a performance.now: vince l'audio
    expect(c.time()).toBeCloseTo(2.5);
  });

  it("loop: modulo durata; senza loop: limitato e ended", () => {
    let now = 0;
    const loop = new PlaybackClock(() => now, 4, true);
    loop.play();
    now = 9500;
    expect(loop.time()).toBeCloseTo(1.5);
    expect(loop.ended()).toBe(false);
    const once = new PlaybackClock(() => now, 4, false);
    now = 0;
    once.play();
    now = 9500;
    expect(once.time()).toBe(4);
    expect(once.ended()).toBe(true);
  });

  it("seek", () => {
    let now = 0;
    const c = new PlaybackClock(() => now, 10, false);
    c.seek(7);
    c.play();
    now = 1000;
    expect(c.time()).toBeCloseTo(8);
    c.seek(99);
    expect(c.time()).toBe(10);
  });
});

describe("QualityController — pacing a refresh diversi", () => {
  for (const hz of [60, 75, 90, 120, 144]) {
    it(`${hz} Hz → ~60 fps renderizzati`, () => {
      const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: false });
      let rendered = 0;
      for (let i = 0; i < hz * 2; i++) if (qc.shouldRender((i * 1000) / hz)) rendered++;
      expect(rendered / 2).toBeGreaterThanOrEqual(hz === 75 ? 37 : 55); // 75 Hz: divisore intero più vicino
      expect(rendered / 2).toBeLessThanOrEqual(62);
    });
  }

  it("60 Hz con jitter non dimezza i frame", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: false });
    let rendered = 0;
    let t = 0;
    for (let i = 0; i < 120; i++) {
      t += 16.67 + (i % 2 ? 1.2 : -1.2);
      if (qc.shouldRender(t)) rendered++;
    }
    expect(rendered).toBeGreaterThanOrEqual(115);
  });
});

describe("QualityController — scala fino a minScale", () => {
  it("scende fino a minScale, poi uQuality, poi bloom", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: true });
    let now = 0;
    for (let i = 0; i < 2000; i++) {
      now += 40;
      qc.update(40, now);
    }
    expect(qc.state.scale).toBe(0.5);
    expect(qc.state.uQuality).toBe(0);
    expect(qc.state.bloom).toBe(false);
  });

  it("minScale non tra i gradini standard è comunque raggiunto", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.6, bloom: false });
    expect(qc.scales[qc.scales.length - 1]).toBe(0.6);
  });

  it("il primo secondo parte dal primo update, non da t=0", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: false });
    let now = 50000; // timestamp rAF lontano da 0
    for (let i = 0; i < 20; i++) {
      now += 33;
      qc.update(33, now); // ~660 ms dal primo update
    }
    expect(qc.state.scale).toBe(1);
  });
});

const BASE = {
  format: "demogen/1",
  meta: { title: "t", duration_s: 4, loop: false, bpm: 120, beats_per_bar: 4 },
  timeline: { bpm: 120, beats_per_bar: 4, scenes: [{ id: "s1", start_bar: 0, bars: 2, transition_in: "cut", transition_bars: 0 }] },
  common: "",
  scenes: { s1: "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }" },
  render: { profile: "modern" },
};

const clone = (): Record<string, any> => JSON.parse(JSON.stringify(BASE));

describe("parsePayload — validazione", () => {
  it("accetta il payload base", () => {
    expect(() => parsePayload(clone())).not.toThrow();
  });

  it("limite di 1 MB anche senza rawBytes", () => {
    const p = clone();
    p.common = "x".repeat(MAX_PAYLOAD_BYTES + 10);
    expect(() => parsePayload(p)).toThrow(/troppo grande/);
  });

  it("timeline.bpm, beats_per_bar e bars devono essere > 0", () => {
    for (const mut of [
      (p: any) => { p.timeline.bpm = 0; },
      (p: any) => { delete p.timeline.bpm; },
      (p: any) => { p.timeline.beats_per_bar = -1; },
      (p: any) => { p.timeline.scenes[0].bars = 0; },
    ]) {
      const p = clone();
      mut(p);
      expect(() => parsePayload(p)).toThrow();
    }
  });

  it("transition_in valido", () => {
    const p = clone();
    p.timeline.scenes[0].transition_in = "wipe";
    expect(() => parsePayload(p)).toThrow(/transition_in/);
  });

  it("id di scena che sono chiavi del prototipo non passano", () => {
    const p = clone();
    p.timeline.scenes[0].id = "toString";
    expect(() => parsePayload(p)).toThrow(/senza sorgente/);
  });

  it("text deve essere stringa (null ammesso)", () => {
    const p = clone();
    p.text = 42;
    expect(() => parsePayload(p)).toThrow(/text/);
    const q = clone();
    q.text = null;
    expect(() => parsePayload(q)).not.toThrow();
  });
});

describe("testo dello scroller in byte", () => {
  it("lunghezza in byte UTF-8, troncata a 256", () => {
    expect(textByteLength("ciao")).toBe(4);
    expect(textByteLength("è")).toBe(2); // 1 carattere UTF-16, 2 byte
    expect(textByteLength("é".repeat(200))).toBe(256);
    expect(textByteLength(null)).toBe(0);
  });

  it("i byte oltre 256 non finiscono nell'uniform", () => {
    const u = textToUniform("é".repeat(200)); // 400 byte → 256
    expect(u.length).toBe(64);
    expect(u[63]).not.toBe(0);
  });
});

describe("audio", () => {
  it("chunkSchedule: chunk e offset del tempo richiesto", () => {
    const d = 16384 / 44100;
    const s = chunkSchedule(d * 3 + 0.1, d);
    expect(s.chunkIndex).toBe(3);
    expect(s.offset).toBeCloseTo(0.1, 9);
    expect(chunkSchedule(0, d)).toEqual({ chunkIndex: 0, offset: 0 });
  });

  it("decodePack16 inverte la codifica a 16 bit", () => {
    for (const x of [-1, -0.5, 0, 0.25, 0.999]) {
      const u = Math.round((x * 0.5 + 0.5) * 65535);
      expect(decodePack16(u & 0xff, u >> 8)).toBeCloseTo(x, 4);
    }
  });
});

describe("map() e header", () => {
  it("detectMap a tre stati, commenti ignorati", () => {
    expect(detectMap("float map(vec3 p){ return length(p)-1.0; }")).toBe(true);
    expect(detectMap("vec2 map(vec3 p){ return vec2(0.0); }")).toBe("other");
    expect(detectMap("// float map(vec3 p) commentata\nvoid mainImage(out vec4 c, in vec2 p){}")).toBe(false);
  });

  it("con una map di firma diversa l'header non dichiara float map", () => {
    const h = buildHeader({ bpm: 120, retro: false, withText: false, hasMap: "other" });
    expect(h).not.toContain("float map(vec3 p)");
  });
});

describe("flashLimitFor", () => {
  it("pieno a tempi normali, sotto soglia oltre 3 beat/s o con reduced-motion", () => {
    expect(flashLimitFor(120, false)).toBe(1);
    expect(flashLimitFor(200, false)).toBe(SAFE_FLASH_LIMIT);
    expect(flashLimitFor(120, true)).toBe(SAFE_FLASH_LIMIT);
    expect(flashLimitFor(120, false, 0.5)).toBe(0.5);
  });
});
