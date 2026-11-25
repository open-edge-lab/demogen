// chip_audio.glsl — colonna sonora 8bit di esempio per la demo audio_chip:
// kick ogni beat, hat sugli offbeat, snare sui beat 2 e 4 della barra,
// basso square con pattern di semitoni. Usa la libreria audio/chip.glsl.

void mainAudio(out vec4 o, in float t) {
    float beatDur = 60.0 / BPM;
    float beat = floor(t / beatDur);
    float phase = fract(t / beatDur);          // 0..1 dentro il beat
    float barPhase = fract(beat / 4.0);         // 0..1 dentro la barra
    float s = 0.0;
    s += chipKick(phase * beatDur);                              // ogni beat
    float off = fract(phase * 2.0);
    s += chipHat(off * beatDur * 0.5) * step(0.5, off);          // offbeat
    if (fract(barPhase * 2.0) >= 0.5) s += chipSnare(phase * beatDur); // beat 2 e 4
    float semi = mod(beat, 8.0) < 4.0 ? 0.0 : (mod(beat, 8.0) < 6.0 ? 7.0 : 12.0);
    s += chipBass(t, semi) * 0.8;
    s += chipArp(t, beatDur, 12.0, beat) * step(0.5, barPhase);  // arpeggio seconda metà barra
    s = tanh(s * 0.9); // soft clip: niente distorsione dura
    o = vec4(s, s, 0.0, 1.0);
}
