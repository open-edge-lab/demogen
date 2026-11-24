// Controllore di qualità adattivo + frame pacing.
// Scala la risoluzione interna (scale) e uQuality per restare dentro il budget
// 1000/target_fps; isteresi in risalita; ningún cambio nel primo secondo.

export interface QualityLimits {
  targetFps: number;
  minScale: number;
  bloom: boolean;
}

export const DEFAULT_LIMITS: QualityLimits = { targetFps: 60, minScale: 0.5, bloom: true };

export interface QualityState {
  scale: number;
  uQuality: number;
  bloom: boolean;
}

const SCALES = [1.0, 0.85, 0.7];
const QUALITIES = [1.0, 0.5, 0.0];

export class QualityController {
  scaleIdx = 0;
  qIdx = 0;
  bloom: boolean;
  private emaMs = 0;
  private frames = 0;
  private lastChangeMs = 0;
  private nowMs = 0;

  constructor(
    private limits: QualityLimits = DEFAULT_LIMITS,
    initialScale = 1.0,
  ) {
    this.bloom = limits.bloom;
    // Bristol: scala iniziale richiesta (es. eco) limita l'indice massimo
    while (this.scaleIdx < SCALES.length - 1 && SCALES[this.scaleIdx] > initialScale) this.scaleIdx++;
  }

  get state(): QualityState {
    const minScale = this.limits.minScale;
    const scale = Math.max(minScale, SCALES[Math.min(this.scaleIdx, SCALES.length - 1)]);
    return {
      scale,
      uQuality: QUALITIES[Math.min(this.qIdx, QUALITIES.length - 1)],
      bloom: this.bloom && this.limits.bloom,
    };
  }

  /** true se questo frame va renderizzato (frame pacing a target_fps). */
  shouldRender(nowMs: number): boolean {
    const budget = 1000 / this.limits.targetFps;
    if (nowMs - this.nowMs < budget - 1) return false;
    this.nowMs = nowMs;
    return true;
  }

  /** Aggiorna con il tempo dell'ultimo frame renderizzato (ms). */
  update(frameMs: number, nowMs: number): void {
    const a = 0.1;
    this.emaMs = this.emaMs === 0 ? frameMs : this.emaMs * (1 - a) + frameMs * a;
    this.frames++;
    if (nowMs - this.lastChangeMs < 1000) return; // niente cambi nel primo secondo
    if (this.frames < 30) return;
    const budget = 1000 / this.limits.targetFps;
    if (this.emaMs > budget * 1.15) {
      // scendi: prima la scala, poi uQuality, poi bloom
      if (this.scaleIdx < SCALES.length - 1) this.scaleIdx++;
      else if (SCALES[this.scaleIdx] > this.limits.minScale) this.scaleIdx = SCALES.length - 1;
      else if (this.qIdx < QUALITIES.length - 1) this.qIdx++;
      else if (this.bloom) this.bloom = false;
      this.frames = 0;
      this.lastChangeMs = nowMs;
    } else if (this.emaMs < budget * 0.7 && nowMs - this.lastChangeMs > 3000) {
      // risali con isteresi
      if (!this.bloom && this.limits.bloom) this.bloom = true;
      else if (this.qIdx > 0) this.qIdx--;
      else if (this.scaleIdx > 0) this.scaleIdx--;
      this.frames = 0;
      this.lastChangeMs = nowMs;
    }
  }
}
