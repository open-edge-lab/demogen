// Style hand-written per la demo M1: palette 16 colori (tema magenta/ciano) + finalize.
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

const vec3 PALETTE[16] = vec3[16](
    vec3(0.02, 0.02, 0.05), vec3(0.05, 0.05, 0.12), vec3(0.10, 0.08, 0.25),
    vec3(0.20, 0.10, 0.40), vec3(0.45, 0.15, 0.65), vec3(0.75, 0.20, 0.75),
    vec3(0.95, 0.30, 0.65), vec3(1.00, 0.55, 0.45), vec3(1.00, 0.75, 0.30),
    vec3(1.00, 0.90, 0.45), vec3(0.55, 0.95, 0.45), vec3(0.20, 0.85, 0.55),
    vec3(0.10, 0.75, 0.85), vec3(0.15, 0.45, 0.95), vec3(0.45, 0.35, 1.00),
    vec3(0.95, 0.95, 1.00)
);
const int PALETTE_N = 16;

vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    col = aces(col);
    col = vignette(col, uv, 0.30);
    col = grain(col, gl_FragCoord.xy, 0.015);
    return toSRGB(col);
#endif
}
