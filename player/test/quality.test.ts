import { describe, expect, it } from "vitest";

import { QualityController } from "../src/quality";

describe("QualityController — frame pacing", () => {
  it("limita il frame rate a target_fps", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: false });
    let rendered = 0;
    for (let ms = 0; ms < 1000; ms += 1) {
      if (qc.shouldRender(ms)) rendered++;
    }
    // 1000ms a 60fps → ~60 frame (tolleranza per il bordo)
    expect(rendered).toBeGreaterThanOrEqual(58);
    expect(rendered).toBeLessThanOrEqual(62);
  });
});

describe("QualityController — adattamento", () => {
  it("scala giù sotto pressione e non cambia nel primo secondo", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: true });
    // frame lenti (30ms > budget 16.7ms): dopo 30 frame e >1s deve scendere
    let now = 0;
    for (let i = 0; i < 40; i++) {
      now += 33;
      qc.update(33, now);
    }
    expect(qc.state.scale).toBeLessThan(1.0);
  });

  it("non scende entro il primo secondo anche con frame lenti", () => {
    const qc = new QualityController({ targetFps: 60, minScale: 0.5, bloom: true });
    let now = 0;
    for (let i = 0; i < 40; i++) {
      now += 33; // ~1.3s totale, ma i cambi sono bloccati fino a 1000ms
      qc.update(33, now);
    }
    // a 1000ms può cambiare al più una volta; verifichiamo che non sia sceso subito
    const qc2 = new QualityController({ targetFps: 60, minScale: 0.5, bloom: true });
    let now2 = 0;
    for (let i = 0; i < 20; i++) { // ~660ms < 1s
      now2 += 33;
      qc2.update(33, now2);
    }
    expect(qc2.state.scale).toBe(1.0);
    expect(qc.state.uQuality).toBeLessThanOrEqual(1.0);
  });

  it("in eco (target 30fps) il pacing dimezza i frame", () => {
    const qc = new QualityController({ targetFps: 30, minScale: 0.5, bloom: false });
    let rendered = 0;
    for (let ms = 0; ms < 1000; ms += 1) if (qc.shouldRender(ms)) rendered++;
    expect(rendered).toBeGreaterThanOrEqual(28);
    expect(rendered).toBeLessThanOrEqual(32);
  });
});
