// Style delle scene "edge horizon" (sfondo della hero di openedge.consulting) e "edge blueprint"
// (sfondo delle sezioni sotto): i colori del sito (Tailwind slate/cyan/sky/pink) e il finalize.
// La scena compone in sRGB come fa il CSS del sito, così il fondo e la griglia di puntini combaciano
// con il resto della pagina: niente aces/vignette/toSRGB, che sposterebbero o scurirebbero il fondo
// (#020617 ha luma 0.025, appena sopra la soglia 0.02 del gate "nero").
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

const vec3 OE_BG = vec3(2.0, 6.0, 23.0) / 255.0;          // #020617 slate-950 (fondo del sito)
const vec3 OE_SLATE900 = vec3(15.0, 23.0, 42.0) / 255.0;  // #0F172A
const vec3 OE_SLATE800 = vec3(30.0, 41.0, 59.0) / 255.0;  // #1E293B
const vec3 OE_SLATE400 = vec3(148.0, 163.0, 184.0) / 255.0; // #94A3B8 (tratteggi del sito)
const vec3 OE_CYAN300 = vec3(103.0, 232.0, 249.0) / 255.0; // #67E8F9
const vec3 OE_CYAN = vec3(34.0, 211.0, 238.0) / 255.0;    // #22D3EE cyan-400 (primario)
const vec3 OE_CYAN500 = vec3(6.0, 182.0, 212.0) / 255.0;  // #06B6D4 (bottoni)
const vec3 OE_SKY = vec3(14.0, 165.0, 233.0) / 255.0;     // #0EA5E9 sky-500 (alone)
const vec3 OE_PINK = vec3(236.0, 72.0, 153.0) / 255.0;    // #EC4899 pink-500 (accento)
const vec3 OE_PINK400 = vec3(244.0, 114.0, 182.0) / 255.0; // #F472B6

// Palette a 16 colori del sito: serve solo al ramo retro (retroFinalize), per convenzione con gli
// altri style.
const vec3 PALETTE[16] = vec3[16](
    OE_BG, OE_SLATE900, OE_SLATE800,
    vec3(51.0, 65.0, 85.0) / 255.0,     // #334155 slate-700
    vec3(71.0, 85.0, 105.0) / 255.0,    // #475569 slate-600
    OE_SLATE400,
    vec3(203.0, 213.0, 225.0) / 255.0,  // #CBD5E1 slate-300
    vec3(22.0, 78.0, 99.0) / 255.0,     // #164E63 cyan-900
    vec3(14.0, 116.0, 144.0) / 255.0,   // #0E7490 cyan-700
    OE_CYAN500, OE_CYAN, OE_CYAN300, OE_SKY, OE_PINK, OE_PINK400,
    vec3(1.0)
);
const int PALETTE_N = 16;

vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    // dither fisso di mezzo livello a 8 bit contro le bande degli aloni sul fondo scuro (fisso nel
    // tempo: niente sfarfallio, niente salto al giro del loop)
    float d = hash21(gl_FragCoord.xy) - 0.5;
    return clamp(col + d / 255.0, 0.0, 1.0);
#endif
}
