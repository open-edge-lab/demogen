// noise.glsl — value/gradient noise, fbm, ridged. Le ottave scalano con uQuality.

/// @fn vnoise
/// value noise 2D in [-1,1].
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 2.0 - 1.0;
}

/// @fn gnoise
/// gradient noise 2D in [-1,1].
float gnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    vec2 ga = vec2(hash21(i) * 2.0 - 1.0, hash21(i + 7.13) * 2.0 - 1.0);
    vec2 gb = vec2(hash21(i + vec2(1.0, 0.0)) * 2.0 - 1.0, hash21(i + vec2(1.0, 7.13)) * 2.0 - 1.0);
    vec2 gc = vec2(hash21(i + vec2(0.0, 1.0)) * 2.0 - 1.0, hash21(i + vec2(7.13, 1.0)) * 2.0 - 1.0);
    vec2 gd = vec2(hash21(i + vec2(1.0, 1.0)) * 2.0 - 1.0, hash21(i + 13.7) * 2.0 - 1.0);
    float a = dot(ga, f);
    float b = dot(gb, f - vec2(1.0, 0.0));
    float c = dot(gc, f - vec2(0.0, 1.0));
    float d = dot(gd, f - vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

/// @fn fbm
/// fractal Brownian motion 2D in [-1,1]; ottave scalate da uQuality (qOctaves).
float fbm(vec2 p) {
    float amp = 0.5;
    float sum = 0.0;
    float norm = 0.0;
    int oct = qOctaves(6);
    for (int i = 0; i < 8; i++) {
        if (i >= oct) break;
        sum += amp * vnoise(p);
        norm += amp;
        p = p * 2.03 + vec2(11.7, 5.1);
        amp *= 0.5;
    }
    return sum / norm;
}

/// @fn ridged
/// ridged multifractal 2D in [0,1]-ish.
float ridged(vec2 p) {
    float amp = 0.5;
    float sum = 0.0;
    float norm = 0.0;
    int oct = qOctaves(5);
    for (int i = 0; i < 8; i++) {
        if (i >= oct) break;
        sum += amp * (1.0 - abs(vnoise(p)));
        norm += amp;
        p = p * 2.11 + vec2(3.7, 9.2);
        amp *= 0.5;
    }
    return sum / norm;
}
