// post.glsl — tonemap, gamma, vignetta, grana deterministica.

/// @fn aces
/// tonemap approssimazione ACES (Narkowicz).
vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

/// @fn toSRGB
/// lineare → sRGB. I negativi (per esempio dopo grain) valgono 0: pow di un negativo è NaN sulle GPU
/// e mix con step non lo scarta (NaN × 0 = NaN).
vec3 toSRGB(vec3 c) {
    c = max(c, vec3(0.0));
    return mix(1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, c * 12.92, step(c, vec3(0.0031308)));
}

/// @fn vignette
vec3 vignette(vec3 c, vec2 uv, float strength) {
    float d = distance(uv, vec2(0.5));
    return c * (1.0 - strength * smoothstep(0.35, 0.85, d));
}

/// @fn grain
/// grana deterministica da iTime (no texture).
vec3 grain(vec3 c, vec2 fragCoord, float amount) {
    float g = hash21(fragCoord + fract(iTime) * 917.0);
    return c + (g - 0.5) * amount;
}
