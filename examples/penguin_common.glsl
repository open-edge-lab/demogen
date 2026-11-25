// Style per la demo "penguin walk": palette 16 colori PASTELLO (niente psichedelia,
// niente flash — safe per epilessia) + finalize retro.
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

const vec3 PALETTE[16] = vec3[16](
    vec3(0.055, 0.078, 0.125),  // 0  nero-blu (corpo pinguino)
    vec3(0.137, 0.188, 0.290),  // 1  blu scuro
    vec3(0.239, 0.353, 0.502),  // 2  blu medio
    vec3(0.596, 0.757, 0.851),  // 3  azzurro pastello
    vec3(0.878, 0.984, 0.988),  // 4  bianco ghiaccio
    vec3(1.00, 1.00, 1.00),     // 5  bianco (pancia/nuvole)
    vec3(1.00, 0.839, 0.647),   // 6  arancione pastello (becco/zampe)
    vec3(1.00, 0.706, 0.635),   // 7  pesca
    vec3(0.741, 0.878, 0.996),  // 8  cielo pastello
    vec3(0.635, 0.824, 1.00),   // 9  azzurro cielo
    vec3(0.804, 0.706, 0.859),  // 10 lilla pastello
    vec3(1.00, 0.784, 0.867),   // 11 rosa chiaro
    vec3(0.796, 0.988, 0.749),  // 12 verde pastello
    vec3(0.608, 0.965, 1.00),   // 13 ciano pastello
    vec3(0.992, 1.00, 0.714),   // 14 giallo pastello (sole)
    vec3(0.933, 0.933, 0.933)   // 15 grigio chiaro
);

const int PALETTE_N = 16;

vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    col = aces(col);
    col = vignette(col, uv, 0.22);
    col = grain(col, gl_FragCoord.xy, 0.008);
    return toSRGB(col);
#endif
}
