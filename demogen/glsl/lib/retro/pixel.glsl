// retro/pixel.glsl — coordinate pixel-perfect alla risoluzione interna (PROFILE_RETRO).

/// @fn pixUV
/// uv normalizzato [0,1] allineato ai pixel della risoluzione interna.
vec2 pixUV(vec2 fragCoord, vec2 res) {
    return (floor(fragCoord) + 0.5) / res;
}

/// @fn scanline
/// scanline CRT leggero: 1 sulle righe pari (usa solo se non in modalità eco).
float scanline(vec2 fragCoord, float strength) {
    return 1.0 - strength * (0.5 + 0.5 * sin(fragCoord.y * 3.14159265));
}
