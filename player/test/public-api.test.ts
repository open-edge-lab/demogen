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
