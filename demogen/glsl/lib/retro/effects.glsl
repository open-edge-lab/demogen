// retro/effects.glsl — effetti 2D classici leggeri (pochi pixel, poche op/pixel).

/// @fn plasma2
/// plasma 2D classico in [-1,1].
float plasma2(vec2 uv, float t) {
    float v = sin(uv.x * 4.0 + t)
            + sin(uv.y * 5.0 - t * 1.3)
            + sin((uv.x + uv.y) * 3.0 + t * 0.7)
            + sin(length(uv - 0.5) * 6.0 - t * 1.7);
    return v * 0.25;
}

/// @fn starfield
/// starfield 2D: hash della cella → posizione e luminosità della stella.
vec3 starfield(vec2 uv, float t, float speed) {
    vec2 g = floor(uv * 24.0);
    vec2 f = fract(uv * 24.0);
    float h = hash21(g);
    vec2 star = vec2(hash21(g + 1.7), hash21(g + 9.2));
    // le stelle si muovono dolcemente nel tempo
    star += 0.1 * vec2(sin(t * (0.3 + h) + h * 40.0), cos(t * (0.2 + h) + h * 31.0));
    float d = length(f - star);
    float tw = 0.5 + 0.5 * sin(t * (2.0 + 6.0 * h) + h * 100.0);
    float lum = smoothstep(0.08, 0.0, d) * (0.4 + 0.6 * tw) * step(0.75, h);
    return vec3(lum);
}

/// @fn copperBar
/// barra rame/raster verticale che oscilla col beat.
float copperBar(vec2 uv, float phase, float k) {
    float y = uv.y * 8.0 + beatPulse(phase, k) * 2.0;
    return 0.5 + 0.5 * sin(y * 3.14159265);
}
