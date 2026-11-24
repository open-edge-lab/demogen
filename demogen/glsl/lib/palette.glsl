// palette.glsl — palette coseno (IQ): a + b*cos(2π(c*t+d)).

/// @fn cosPalette
/// palette coseno: t in [0,1] → colore.
vec3 cosPalette(float t, vec3 a, vec3 b, vec3 c, vec3 d) {
    return a + b * cos(6.28318530 * (c * t + d));
}
