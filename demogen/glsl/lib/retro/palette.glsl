// retro/palette.glsl — quantizzazione in palette fissa + dithering ordinato Bayer.
// La palette è un dato dello style: `const vec3 PALETTE[16]` + `const int PALETTE_N`.

/// @fn bayer4
/// matrice Bayer 4x4 in [0,1) dalla posizione pixel.
float bayer4(vec2 px) {
    int x = int(mod(px.x, 4.0));
    int y = int(mod(px.y, 4.0));
    int i = x + y * 4;
    // pattern 4x4 standard
    const int m[16] = int[16](0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5);
    return (float(m[i]) + 0.5) / 16.0;
}

/// @fn retroQuantize
/// colore più vicino nella palette (distanza RGB) + dithering Bayer 4x4.
vec3 retroQuantize(vec3 col, const vec3 pal[16], int n, vec2 px) {
    float d = bayer4(px) - 0.5;
    vec3 c = col + d * (1.0 / float(n));
    int best = 0;
    float bd = 1e9;
    for (int i = 0; i < 16; i++) {
        if (i >= n) break;
        vec3 diff = c - pal[i];
        float dd = dot(diff, diff);
        if (dd < bd) { bd = dd; best = i; }
    }
    return pal[best];
}

/// @fn retroFinalize
/// output finale per scena retro: quantizza col nella palette data e applica
/// vignetta leggera. Chiamare alla fine di mainImage in profilo retro.
vec3 retroFinalize(vec3 col, vec2 uv, vec2 fragCoord, const vec3 pal[16], int n) {
    vec3 q = retroQuantize(clamp(col, 0.0, 1.0), pal, n, fragCoord);
    float d = distance(uv, vec2(0.5));
    return q * (1.0 - 0.25 * smoothstep(0.45, 0.9, d));
}
