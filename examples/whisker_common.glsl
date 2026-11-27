// Style della demo "whisker hunt": palette, sfondo e finalize retro della demo generata "Whisker Idle",
// più il gatto arancione (lo stesso della dissolvenza) e la falena delle scene "idle" e "caccia".
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

// Palette a 16 colori: i 5 colori della direzione artistica più le sfumature di riempimento.
// Qui quantizza solo lo sfondo di "idle" e "caccia"; gatto e falena usano OC_PAL.
const vec3 PALETTE[16] = vec3[16](
    vec3(0.063, 0.063, 0.078), // 0  #101014 contorno / quasi nero
    vec3(0.078, 0.204, 0.231), // 1  #14343B sfondo verde acqua scuro
    vec3(0.180, 0.180, 0.220), // 2  #2E2E38 grigio scuro
    vec3(0.949, 0.918, 0.827), // 3  #F2EAD3 crema
    vec3(0.949, 0.651, 0.702), // 4  #F2A6B3 rosa
    vec3(0.110, 0.290, 0.320), // 5  verde acqua +1
    vec3(0.160, 0.400, 0.430), // 6  verde acqua +2 (retino)
    vec3(0.220, 0.510, 0.540), // 7  verde acqua +3
    vec3(0.090, 0.140, 0.160), // 8  ombra verde acqua
    vec3(0.130, 0.130, 0.160), // 9  grigio +1
    vec3(0.240, 0.240, 0.290), // 10 grigio +2
    vec3(0.850, 0.800, 0.690), // 11 ombra crema
    vec3(0.760, 0.500, 0.560), // 12 ombra rosa
    vec3(0.980, 0.960, 0.900), // 13 luce crema
    vec3(0.980, 0.850, 0.880), // 14 luce rosa
    vec3(0.055, 0.055, 0.066)  // 15 contorno più scuro
);

const int PALETTE_N = 16;

vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    col = aces(col);
    col = vignette(col, uv, 0.25);
    return toSRGB(col);
#endif
}

// ---------------------------------------------------------------- sfondo di "idle" e "caccia"
const vec3 WH_TEAL_D = vec3(0.145, 0.310, 0.314);
const vec3 WH_TEAL_L = vec3(0.220, 0.451, 0.455);
const vec3 WH_BLACK = vec3(0.031, 0.027, 0.039);
const float WH_FLOOR = 28.0; // y dei piedi, la stessa della dissolvenza (sotto c'è la linea del pavimento)

// Verde acqua con sfumatura verticale a retino e linea del pavimento.
vec3 floorBackground(vec2 px, vec2 res) {
    float v = clamp((px.y / res.y - 0.12) / 0.76, 0.0, 1.0);
    vec3 col = mix(WH_TEAL_D, WH_TEAL_L, step(bayer4(px), v));
    if (px.y >= WH_FLOOR - 3.0 && px.y < WH_FLOOR - 1.0) col = WH_BLACK * 0.7;
    return col;
}

// ---------------------------------------------------------------- gatto arancione
// Colori di whisker_fade.glsl. La palette comune non ha l'arancione (lo porterebbe sul rosa), quindi
// gatto e falena si quantizzano su questa e lo sfondo su PALETTE (vedi whiskerFinalize).
const vec3 OC_PAL[16] = vec3[16](
    vec3(0.02, 0.02, 0.04),  // 0 contorno nero
    vec3(0.85, 0.45, 0.12),  // 1 pelo arancione
    vec3(0.95, 0.85, 0.62),  // 2 crema
    vec3(0.16, 0.07, 0.05),  // 3 marrone scuro (occhi e strisce)
    vec3(0.02, 0.02, 0.04),  // 4..15 riempitivo (n = 8 tiene basso il retino della quantizzazione)
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04)
);

const float OC_CELL = 4.0;  // celle di 4 pixel come nella dissolvenza: da seduto è alto 56 px
const int OC_EAR = 1;       // l'orecchio destro scatta verso l'esterno
const int OC_AIR = 2;       // zampe sospese (in volo)
const int OC_BLINK = 4;     // occhi chiusi

// Cella dello sprite, x a destra e y in alto, (0,0) = cella a terra: 0 vuoto, 1 pelo, 2 crema,
// 3 marrone. Da seduto è il gatto di whisker_fade.glsl cella per cella.
//   k     acquattamento: 0 seduto, 1 a metà, 2 a terra (corpo basso e anche allargate)
//   tb    altezza della base della coda in celle
//   hip   spostamento orizzontale di corpo e coda (dimenare il sedere); la testa resta ferma
//   look  spostamento degli occhi (x verso destra, y verso l'alto)
int orangeCat(ivec2 c, int k, int tb, int hip, ivec2 look, int flags) {
    const int TOP[3] = int[3](4, 3, 1); // ultima riga del corpo
    int top = TOP[k];
    int wide = k == 2 ? 1 : 0;
    ivec2 b = c - ivec2(hip, 0);
    int id = 0;
    // corpo (la riga a terra è più stretta) e coda: 5 celle che salgono verso destra
    bool fur = b.y >= 0 && b.y <= top && b.x >= -5 - wide && b.x <= 4 + wide &&
               !(b.y == 0 && (b.x < -3 - wide || b.x > 2 + wide));
    for (int i = 0; i < 5; i++) {
        if (b.x == 4 + wide + i && b.y == tb + (i * i) / 4) fur = true;
    }
    // colori per posizione, come nella dissolvenza: petto crema, strisce anche sulla coda
    if (fur) {
        bool band = b.y >= 1 && b.y <= top;
        if (band && b.x >= -1 && b.x <= 2) id = 2;
        else if (band && (b.x + 6) % 3 == 1) id = 3;
        else id = 1;
    }
    // zampe anteriori sospese durante il salto
    if ((flags & OC_AIR) != 0 && c.y == -1 && (c.x == -3 || c.x == -2 || c.x == 1 || c.x == 2)) id = 1;
    // testa appoggiata sul corpo, con occhi (chiusi = pelo) e muso
    int hb = top + 1;
    if (c.y >= hb && c.y <= hb + 5 && c.x >= -4 && c.x <= 3) {
        id = 1;
        if (c.y == hb + 3 + look.y && (c.x == -2 + look.x || c.x == 1 + look.x)) id = (flags & OC_BLINK) != 0 ? 1 : 3;
        else if (c.x == 0 && c.y == hb + 2) id = 2;
    }
    // orecchie: a terra si aprono verso l'esterno, il guizzo apre solo la destra
    int ey = c.y - hb - 6;
    int tipL = k == 2 ? -4 : -3;
    int tipR = (k == 2 || (flags & OC_EAR) != 0) ? 2 : 1;
    if (ey == 0 && (c.x == -4 || c.x == -3 || c.x == 1 || c.x == 2)) id = 1;
    if (ey == 1 && (c.x == tipL || c.x == tipR)) id = 1;
    return id;
}

// Indice in OC_PAL del pixel px per il gatto con i piedi in o, oppure -1 (sfondo). Le celle vuote che
// toccano il pelo fanno il contorno nero; a terra niente contorno sotto i piedi, come nella
// dissolvenza. Fuori dal riquadro dello sprite (contorno compreso), cioè quasi ovunque, non lo si
// interroga affatto.
int orangeCatPixel(vec2 px, vec2 o, int k, int tb, int hip, ivec2 look, int flags) {
    ivec2 g = ivec2(floor((px - o) / OC_CELL));
    if (g.x < -8 || g.x > 11 || g.y < -2 || g.y > 14) return -1;
    int id = orangeCat(g, k, tb, hip, look, flags);
    if (id > 0) return id;
    if (g.y < 0 && (flags & OC_AIR) == 0) return -1;
    if (orangeCat(g + ivec2(1, 0), k, tb, hip, look, flags) > 0 ||
        orangeCat(g - ivec2(1, 0), k, tb, hip, look, flags) > 0 ||
        orangeCat(g + ivec2(0, 1), k, tb, hip, look, flags) > 0 ||
        orangeCat(g - ivec2(0, 1), k, tb, hip, look, flags) > 0) return 0;
    return -1;
}

// ---------------------------------------------------------------- falena
// Falena crema di 6x4 pixel con il corpo 2x2 in pos; le ali battono a ogni fotogramma.
bool mothAt(vec2 px, vec2 pos, bool wingsUp) {
    ivec2 q = ivec2(floor(px)) - ivec2(pos);
    bool body = q.x >= 0 && q.x <= 1 && q.y >= 0 && q.y <= 1;
    bool wing = (q.x == -2 || q.x == -1 || q.x == 2 || q.x == 3) &&
                (wingsUp ? (q.y == 1 || q.y == 2) : (q.y == -1 || q.y == 0));
    return body || wing;
}

// Pixel finale: idx >= 0 è un colore di OC_PAL (gatto o falena), -1 lo sfondo bg su PALETTE.
// Gatto e sfondo passano dalla stessa vignettatura retro.
vec3 whiskerFinalize(vec3 bg, int idx, vec2 fragCoord, vec2 res) {
    vec2 uv = fragCoord / res;
    return idx >= 0 ? retroFinalize(OC_PAL[idx], uv, fragCoord, OC_PAL, 8) : finalize(bg, uv);
}
