// audio/chip.glsl — synth 8bit per le colonne sonore demogen (Fase 2).
// Ogni funzione prende il tempo locale in secondi dall'onset dell'evento.
// Usabili dentro mainAudio(out vec4 o, in float t) insieme a iSampleRate/BPM.

/// @fn chipKick
/// kick 808: pitch drop esponenziale 150→45 Hz + click iniziale.
/// t = secondi dall'onset del beat.
float chipKick(float t) {
    float k = 30.0, f0 = 150.0, fi = 45.0;
    float ph = 6.28318530718 * (fi * t + (f0 - fi) / k * (1.0 - exp(-k * t)));
    float click = exp(-t * 90.0) * 0.5;
    return sin(ph) * exp(-t * 8.0) + click * sin(6.2831 * 1000.0 * t);
}

/// @fn chipHat
/// hi-hat chiuso: rumore bianco (hash per campione) con decadimento rápido.
float chipHat(float t) {
    float n = fract(sin(floor(t * iSampleRate) * 12.9898) * 43758.5453) * 2.0 - 1.0;
    return n * exp(-t * 50.0) * 0.22;
}

/// @fn chipSnare
/// snare: rumore + tono a 180 Hz, decadimento medio.
float chipSnare(float t) {
    float n = fract(sin(floor(t * iSampleRate) * 78.233) * 12543.123) * 2.0 - 1.0;
    return (n * exp(-t * 25.0) * 0.5 + sin(6.2831 * 180.0 * t) * exp(-t * 18.0) * 0.4);
}

/// @fn chipBass
/// basso square 8bit: f = 55 Hz * 2^(semi/12), onda quadra duty 50%.
float chipBass(float t, float semi) {
    float f = 55.0 * pow(2.0, semi / 12.0);
    float s = sin(6.28318530718 * f * t);
    return sign(s) * 0.30;
}

/// @fn chipArp
/// arpeggio triangle: 3 note per beat a ottava, pattern da `step` (0..7).
float chipArp(float t, float beatDur, float rootSemi, float step) {
    float n = mod(step, 4.0);
    float semi = rootSemi + n * 7.0 + (mod(step, 8.0) >= 4.0 ? 12.0 : 0.0);
    float f = 110.0 * pow(2.0, semi / 12.0);
    float lt = fract(t / beatDur) * beatDur;
    float tri = abs(fract(lt * f * 2.0) * 2.0 - 1.0) * 2.0 - 1.0;
    return tri * 0.18 * exp(-fract(t / beatDur) * 3.0);
}
