// easing.glsl — easing e helper sul beat (uBeatPhase, uFlashLimit).

/// @fn easeOutCubic
float easeOutCubic(float x) {
    float f = 1.0 - x;
    return 1.0 - f * f * f;
}

/// @fn beatPulse
/// impulso sul beat: 1 all'inizio del beat, decade esponenzialmente.
/// phase = uBeatPhase, k = decadimento.
float beatPulse(float phase, float k) {
    return exp(-k * phase);
}

/// @fn beatFlash
/// flash sul beat che rispetta uFlashLimit (fotosensibilità):
/// ampiezza scalata da uFlashLimit, mai a tutto schermo.
float beatFlash(float phase, float k) {
    return uFlashLimit * exp(-k * phase);
}
