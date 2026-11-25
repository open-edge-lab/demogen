// Clock di riproduzione puro (testabile senza DOM): play/pause/seek con offset
// conservato in pausa, tempo audio come master quando disponibile, loop/clamp.

export class PlaybackClock {
  private playing = false;
  private startMs = 0;
  private offsetS = 0;

  constructor(
    private now: () => number,
    readonly durationS: number,
    readonly loop: boolean,
  ) {}

  get isPlaying(): boolean {
    return this.playing;
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
    this.offsetS = this.loop ? Math.max(0, t) : Math.max(0, Math.min(this.durationS, t));
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
    if (this.loop && d > 0) return ((t % d) + d) % d;
    return Math.max(0, Math.min(d, t));
  }

  /** true se la demo (senza loop) è arrivata alla fine. */
  ended(audioTime?: number | null): boolean {
    return !this.loop && this.raw(audioTime) >= this.durationS;
  }
}
