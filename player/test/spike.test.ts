import { describe, expect, it } from "vitest";

import { buildFragment, isSoftwareRenderer } from "../src/spike";

describe("buildFragment", () => {
  it("aggiunge header ES 3.00, uniform e main al codice utente", () => {
    const user = "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }";
    const frag = buildFragment(user);
    expect(frag).toContain("#version 300 es");
    expect(frag).toContain("precision highp float;");
    expect(frag).toContain("uniform vec3 iResolution;");
    expect(frag).toContain("uniform float iTime;");
    expect(frag).toContain("mainImage(demogen_FragColor, gl_FragCoord.xy)");
    // forward declaration prima del main: in GLSL ES 3.00 serve
    expect(frag.indexOf("void mainImage(out vec4 fragColor, in vec2 fragCoord);")).toBeLessThan(
      frag.indexOf("void main()"),
    );
    expect(frag).toContain(user);
  });
});

describe("isSoftwareRenderer", () => {
  it("riconosce SwiftShader/llvmpipe come CPU", () => {
    expect(isSoftwareRenderer("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))")).toBe(true);
    expect(isSoftwareRenderer("llvmpipe (LLVM 17.0.6, 256 bits)")).toBe(true);
  });

  it("non marchia le GPU reali come software", () => {
    expect(isSoftwareRenderer("Apple M3 Pro")).toBe(false);
    expect(isSoftwareRenderer("NVIDIA GeForce RTX 4070")).toBe(false);
    expect(isSoftwareRenderer("Apple GPU")).toBe(false);
  });
});
