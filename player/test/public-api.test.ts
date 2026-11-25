// Contratto dell'API pubblica esposta come libreria web (`src/index.ts`):
// se rinomini o rimuovi un export, il build ESM per pagine web si rompe.
import { describe, expect, it } from "vitest";

import * as api from "../src/index";

describe("API pubblica @demogen/player", () => {
  it("espone le classi e le funzioni stabile per l'uso in pagina web", () => {
    expect(typeof api.Player).toBe("function");
    expect(typeof api.DemogenPlayerElement).toBe("function");
    expect(typeof api.parsePayload).toBe("function");
    expect(typeof api.textToUniform).toBe("function");
    expect(typeof api.stateAt).toBe("function");
    expect(typeof api.QualityController).toBe("function");
    expect(typeof api.rendererInfo).toBe("function");
    expect(typeof api.isSoftwareRenderer).toBe("function");
    expect(typeof api.buildHeader).toBe("function");
    expect(typeof api.buildFragment).toBe("function");
  });

  it("registra il custom element <demogen-player> solo in ambiente browser", () => {
    // in node (vitest) customElements non esiste: il modulo non deve crashare
    expect(api.DemogenPlayerElement.observedAttributes).toContain("src");
  });
});

describe("audio engine (Fase 2)", () => {
  it("planChunkStarts: chunk consecutivi senza gap", async () => {
    const { planChunkStarts, AUDIO_BLOCK_SAMPLES } = await import("../src/audio");
    const chunkDur = AUDIO_BLOCK_SAMPLES / 44100;
    const starts = planChunkStarts(1.0, chunkDur, 4, 10.0);
    expect(starts).toHaveLength(4);
    for (let i = 1; i < starts.length; i++) {
      expect(starts[i] - starts[i - 1]).toBeCloseTo(chunkDur, 9);
    }
    expect(starts[0]).toBeCloseTo(10.0, 9);
  });

  it("buildAudioFragment include il mapping sample globale (niente gap tra chunk)", async () => {
    const { buildAudioFragment, buildAudioHeader } = await import("../src/audio");
    const frag = buildAudioFragment(buildAudioHeader(120), "", "void mainAudio(out vec4 o, in float t){ o=vec4(t); }");
    expect(frag).toContain("uBlockStart + idx");
    expect(frag).toContain("void mainAudio(out vec4 o, in float t);");
  });
});
