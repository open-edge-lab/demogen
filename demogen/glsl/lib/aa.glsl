// aa.glsl — anti-aliasing analitico via fwidth.

/// @fn aaStep
/// smoothstep filtrato: bordo morbido di un pixel.
float aaStep(float edge, float x) {
    float w = fwidth(x) * 0.5;
    return smoothstep(edge - w, edge + w, x);
}

/// @fn aaSmoothstep
/// smoothstep con bordi filtrati.
float aaSmoothstep(float e0, float e1, float x) {
    float w = fwidth(x) * 0.5;
    return smoothstep(e0 - w, e1 + w, x);
}

/// @fn detailFade
/// 0..1: quanto mostrare un dettaglio periodico la cui lunghezza d'onda è `wavePx` pixel (1 sopra
/// 4 px, 0 sotto 2 px): righe fini, reticoli, maschere e ottave svaniscono invece di fare moiré, e
/// ricompaiono da sole a risoluzione più alta. Con coordinate p: detailFade(1.0 / (freq * fwidth(p.x))).
float detailFade(float wavePx) {
    return clamp(wavePx * 0.5 - 1.0, 0.0, 1.0);
}
