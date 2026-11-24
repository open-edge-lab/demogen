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
