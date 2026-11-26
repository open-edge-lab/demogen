// Controllore di qualità adattivo + frame pacing.
// Scala la risoluzione interna (scale) e uQuality per restare dentro il budget
// 1000/target_fps; isteresi in risalita; nessun cambio nel primo secondo.

export interface QualityLimits {
  targetFps: number;
  minScale: number;
  bloom: boolean;
}

export const DEFAULT_LIMITS: QualityLimits = { targetFps: 60, minScale: 0.25, bloom: true };

export interface QualityState {
  scale: number;
  uQuality: number;
  bloom: boolean;
}

const BASE_SCALES = [1.0, 0.85, 0.7, 0.5, 0.35];
const QUALITIES = [1.0, 0.5, 0.0];

export class QualityController {
  scaleIdx = 0;
  qIdx = 0;
  bloom: boolean;
  /** Scala della risoluzione interna, dalla piena fino a minScale (incluso). */
  readonly scales: number[];
  private emaMs = 0;
  private frames = 0;
  private lastChangeMs: number | null = null;
  private next = -1; // istante (ms) dal quale il prossimo frame può partire

  constructor(
    private limits: QualityLimits = DEFAULT_LIMITS,
    initialScale = 1.0,
  ) {
    this.bloom = limits.bloom;
    const min = Math.min(1, Math.max(0.1, limits.minScale));
    this.scales = BASE_SCALES.filter((s) => s > min + 1e-6).concat([min]);
    // scala iniziale richiesta (es. eco) limita l'indice di partenza
    while (this.scaleIdx < this.scales.length - 1 && this.scales[this.scaleIdx] > initialScale) this.scaleIdx++;
  }

  get state(): QualityState {
    return {
      scale: this.scales[this.scaleIdx],
      uQuality: QUALITIES[this.qIdx],
      bloom: this.bloom && this.limits.bloom,
    };
  }

  /** true se questo frame va renderizzato (frame pacing a target_fps, qualsiasi refresh del display).
   *  Accumulatore: a 75/90/144 Hz si resta a ~target_fps invece di scendere a metà refresh. */
  shouldRender(nowMs: number): boolean {
    const budget = 1000 / this.limits.targetFps;
    if (this.next < 0) {
      this.next = nowMs + budget;
      return true;
    }
    if (nowMs < this.next - 2) return false; // 2 ms di tolleranza al jitter di rAF
    this.next += budget;
    if (nowMs - this.next > budget) this.next = nowMs + budget; // dopo uno stallo: riallinea
    return true;
  }

  /** Aggiorna con la durata dell'ultimo frame renderizzato (ms) — intervallo tra frame, non solo CPU. */
  update(frameMs: number, nowMs: number): void {
    const a = 0.1;
    this.emaMs = this.emaMs === 0 ? frameMs : this.emaMs * (1 - a) + frameMs * a;
    this.frames++;
    if (this.lastChangeMs === null) this.lastChangeMs = nowMs; // il "primo secondo" parte qui
    if (nowMs - this.lastChangeMs < 1000) return;
    if (this.frames < 30) return;
    const budget = 1000 / this.limits.targetFps;
    if (this.emaMs > budget * 1.15) {
      // scendi: prima la scala (fino a minScale), poi uQuality, poi bloom
      if (this.scaleIdx < this.scales.length - 1) this.scaleIdx++;
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
