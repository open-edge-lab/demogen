import { describe, expect, it } from "vitest";

import { parsePayload, textToUniform, MAX_PAYLOAD_BYTES } from "../src/format";

const basePayload = {
  format: "demogen/1",
  meta: { title: "t", duration_s: 8, loop: false, bpm: 120, beats_per_bar: 4 },
  timeline: {
    bpm: 120,
    beats_per_bar: 4,
    scenes: [{ id: "s1", start_bar: 0, bars: 4, transition_in: "cut", transition_bars: 0 }],
  },
  common: "",
  scenes: { s1: "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }" },
  render: { profile: "modern" },
};

describe("parsePayload", () => {
  it("accetta un payload valido", () => {
    const p = parsePayload(basePayload);
    expect(p.meta.bpm).toBe(120);
  });

  it("rifiuta formati sconosciuti", () => {
    expect(() => parsePayload({ ...basePayload, format: "demogen/2" })).toThrow(/Unsupported format/);
  });

  it("rifiuta scena senza sorgente", () => {
    expect(() =>
      parsePayload({ ...basePayload, scenes: {} }),
    ).toThrow(/has no source/);
  });

  it("rifiuta payload oltre il limite", () => {
    expect(() => parsePayload(basePayload, MAX_PAYLOAD_BYTES + 1)).toThrow(/too large/);
  });
});

describe("textToUniform", () => {
  it("compatta 4 caratteri ASCII per int (little-endian)", () => {
    const u = textToUniform("AB");
    // 'A'=0x41, 'B'=0x42 → 0x4241
    expect(u[0]).toBe(0x4241);
    expect(u[1]).toBe(0);
  });

  it("tronca a 256 caratteri e gestisce stringa vuota", () => {
    expect(textToUniform("").every((v) => v === 0)).toBe(true);
    const long = "x".repeat(300);
    const u = textToUniform(long);
    expect(u[63]).not.toBe(0); // 256 caratteri = 64 int pieni
  });
});
