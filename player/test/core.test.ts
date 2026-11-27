import { describe, expect, it } from "vitest";

import { isSoftwareRenderer } from "../src/gl";
import { buildFragment, buildHeader } from "../src/programs";

describe("buildHeader", () => {
  it("include uniform di sync, BPM e forward declaration di mainImage", () => {
    const h = buildHeader({ bpm: 128, retro: false, withText: true, hasMap: true });
    expect(h).toContain("#version 300 es");
    expect(h).toContain("uniform float uBeat;");
    expect(h).toContain("uniform highp int uText[64];");
    expect(h).toContain("#define BPM 128.0000");
    expect(h).not.toContain("PROFILE_RETRO");
    expect(h).toContain("void mainImage(out vec4 fragColor, in vec2 fragCoord);");
  });

  it("aggiunge PROFILE_RETRO solo per il profilo retro", () => {
    expect(buildHeader({ bpm: 120, retro: true, withText: false, hasMap: false })).toContain(
      "#define PROFILE_RETRO",
    );
    expect(buildHeader({ bpm: 120, retro: false, withText: false, hasMap: false })).not.toContain(
      "PROFILE_RETRO",
    );
  });

  it("map: forward declaration se la scena la definisce, default altrimenti", () => {
    const withMap = buildHeader({ bpm: 120, retro: false, withText: false, hasMap: true });
    expect(withMap).toContain("float map(vec3 p);");
    expect(withMap).not.toContain("return 1e9");
    const noMap = buildHeader({ bpm: 120, retro: false, withText: false, hasMap: false });
    expect(noMap).toContain("float map(vec3 p) { return 1e9; }");
  });
});

describe("buildFragment", () => {
  it("ordine: header, common, main, corpo utente", () => {
    const frag = buildFragment("H", "C", "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }");
    expect(frag.indexOf("H")).toBeLessThan(frag.indexOf("C"));
    expect(frag.indexOf("C")).toBeLessThan(frag.indexOf("void main()"));
    expect(frag.indexOf("void main()")).toBeLessThan(frag.indexOf("void mainImage(out vec4 c"));
    expect(frag).toContain("mainImage(demogen_FragColor, gl_FragCoord.xy + uJitter)");
  });
});

describe("isSoftwareRenderer", () => {
  it("riconosce SwiftShader/llvmpipe come CPU", () => {
    expect(isSoftwareRenderer("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))")).toBe(true);
    expect(isSoftwareRenderer("llvmpipe (LLVM 17.0.6, 256 bits)")).toBe(true);
  });
  it("non marchia le GPU reali come software", () => {
    expect(isSoftwareRenderer("Apple M3 Pro")).toBe(false);
    expect(isSoftwareRenderer("ANGLE (Intel, Intel(R) UHD Graphics 620, Direct3D11)")).toBe(false);
  });
});
