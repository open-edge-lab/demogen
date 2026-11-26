// Clock di riproduzione puro (testabile senza DOM): play/pause/seek con offset
// conservato in pausa, tempo audio come master quando disponibile, loop/clamp.

export class PlaybackClock {
  private playing = false;
  private startMs = 0;
  private offsetS = 0;

  constructor(
    private now: () => number,
    readonly durationS: number,
    private loopOn: boolean,
  ) {}

  get isPlaying(): boolean {
    return this.playing;
  }

  get loop(): boolean {
    return this.loopOn;
  }

  /** Attiva/disattiva il loop conservando la posizione visibile (senza audio master: il player
   *  ferma l'audio prima di chiamarlo). */
  setLoop(on: boolean): void {
    const t = this.time();
    this.loopOn = on;
    this.seek(t);
  }

  play(): void {
    if (this.playing) return;
    this.startMs = this.now() - this.offsetS * 1000;
    this.playing = true;
  }

  /** Ferma il clock conservando la posizione (con l'audio master, la sua). */
  pause(audioTime?: number | null): void {
    if (!this.playing) return;
    this.offsetS = this.raw(audioTime);
    this.playing = false;
  }

  seek(t: number): void {
    this.offsetS = this.loopOn ? Math.max(0, t) : Math.max(0, Math.min(this.durationS, t));
    this.startMs = this.now() - this.offsetS * 1000;
  }

  /** Secondi dall'inizio, senza wrap (il tempo audio, se c'è, è il master). */
  raw(audioTime?: number | null): number {
    if (!this.playing) return this.offsetS;
    if (audioTime !== undefined && audioTime !== null) return audioTime;
    return (this.now() - this.startMs) / 1000; // startMs incorpora già l'offset
  }

  /** Tempo di demo: modulo durata in loop, altrimenti limitato a [0, durata]. */
  time(audioTime?: number | null): number {
    return this.wrap(this.raw(audioTime));
  }

  wrap(t: number): number {
    const d = this.durationS;
    if (this.loopOn && d > 0) return ((t % d) + d) % d;
    return Math.max(0, Math.min(d, t));
  }

  /** true se la demo (senza loop) è arrivata alla fine. */
  ended(audioTime?: number | null): boolean {
    return !this.loopOn && this.raw(audioTime) >= this.durationS;
  }
}
