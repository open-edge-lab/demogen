// Style della demo "whisker hunt": lo stesso della demo generata "Whisker Idle" (palette, sfondo,
// finalize retro), più il gattone condiviso dalle scene "idle" e "caccia".
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

// Palette a 16 colori: i 5 colori della direzione artistica più le sfumature di riempimento.
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

// ---------------------------------------------------------------- gattone (scene "idle" e "caccia")
// Sprite a celle in vista frontale. Celle con y verso l'alto, (0,0) = cella a terra sotto il centro
// del corpo. Restituisce 0 vuoto, 1 nero, 2 pelo, 3 crema, 4 rosa (senza contorno: lo aggiunge
// bigCatId guardando le celle vicine). Corpo, pancia, coda e colori sono quelli del gattone della
// demo originale; la testa, che lì usciva dall'inquadratura, è disegnata da gatto (orecchie a
// triangolo con l'interno rosa, naso e bocca) e appoggiata sul corpo.
//   k       acquattamento a scatti: 0 seduto, 1 a metà, 2 a terra
//   tail    alzata della coda in celle (scodinzolare = valori che cambiano a ogni fotogramma)
//   hip     spostamento orizzontale di corpo e coda in celle (dimenare il sedere)
//   look    spostamento delle pupille in celle (x verso destra, y verso l'alto)
//   headUp  testa alzata di N celle (guarda in alto)
//   flags   bit 0 orecchio destro piegato, bit 1 occhi chiusi, bit 2 zampe sospese (in volo)
const int BC_EAR = 1;
const int BC_BLINK = 2;
const int BC_AIR = 4;

// mezza larghezza della testa per riga, dal mento (dy = -5) alla fronte (dy = +5)
const int BC_HEAD[11] = int[11](2, 4, 5, 5, 5, 5, 5, 5, 5, 4, 3);

int bigCatFill(ivec2 c, int k, int tail, int hip, ivec2 look, int headUp, int flags) {
    int id = 0;
    ivec2 b = c - ivec2(hip, 0);
    int bodyTop = 6 - k;
    int bodyHalf = 6 + k / 2;
    // coda: catena di celle che sale dal fianco destro
    if (b.x >= bodyHalf + 1 && b.x <= bodyHalf + 6) {
        int i = b.x - bodyHalf - 1;
        if (b.y == 3 - k + i / 2 + tail) id = 2;
    }
    // corpo: largo sulle anche, più stretto verso le spalle, angoli smussati
    if (b.y >= 0 && b.y <= bodyTop) {
        int hw = bodyHalf - max(0, b.y - 2) / 2;
        if (abs(b.x) <= hw) id = (abs(b.x) == hw && (b.y == 0 || b.y == bodyTop)) ? 0 : 2;
    }
    // pancia crema e, in basso, le due zampe anteriori separate da una riga nera
    if (abs(b.x) <= 3 && b.y >= 0 && b.y <= 3 - k) id = (b.y == 0 && b.x == 0) ? 1 : 3;
    // zampe sospese durante il salto
    if ((flags & BC_AIR) != 0 && b.y == -1 && (abs(b.x) == 2 || abs(b.x) == 3)) id = 2;
    // testa appoggiata sul corpo
    int hy = 11 - 2 * k + headUp;
    int dy = c.y - hy;
    if (dy >= -5 && dy <= 5 && abs(c.x) <= BC_HEAD[dy + 5]) id = 2;
    // orecchie a triangolo sugli angoli della testa (più aperte quando è a terra); il guizzo
    // piega la destra verso l'esterno
    int ey = dy - 5; // 0..2 sopra la fronte
    int ax = abs(c.x);
    bool right = c.x > 0;
    int lean = (k == 2 || ((flags & BC_EAR) != 0 && right)) ? 1 : 0;
    if (ey >= 0 && ey <= 2 && ax >= 2 + ey + lean && ax <= 5 + lean) id = 2;
    // interno rosa delle orecchie
    if ((ey == 0 && (ax == 3 + lean || ax == 4 + lean)) || (ey == 1 && ax == 4 + lean)) id = 4;
    // occhi (chiusi = pelo); muso crema con il naso nero (un naso rosa, quantizzato, sparirebbe
    // nel pelo e due bocche nere sembrerebbero un grugno)
    if (dy == 1 + look.y && abs(c.x - look.x) == 2) id = (flags & BC_BLINK) != 0 ? 2 : 1;
    if (ax <= 1 && (dy == -1 || dy == -2)) id = (c.x == 0 && dy == -1) ? 1 : 3;
    return id;
}

// Id della cella con il contorno nero: una cella piena che tocca una vuota diventa nera.
int bigCatId(ivec2 c, int k, int tail, int hip, ivec2 look, int headUp, int flags) {
    int id = bigCatFill(c, k, tail, hip, look, headUp, flags);
    if (id == 0) return 0;
    if (bigCatFill(c + ivec2(1, 0), k, tail, hip, look, headUp, flags) == 0 ||
        bigCatFill(c - ivec2(1, 0), k, tail, hip, look, headUp, flags) == 0 ||
        bigCatFill(c + ivec2(0, 1), k, tail, hip, look, headUp, flags) == 0 ||
        bigCatFill(c - ivec2(0, 1), k, tail, hip, look, headUp, flags) == 0) return 1;
    return id;
}

// Colori del gattone e del suo sfondo (gli stessi della scena originale, quantizzati da finalize).
const vec3 BC_TEAL_D = vec3(0.145, 0.310, 0.314);
const vec3 BC_TEAL_L = vec3(0.220, 0.451, 0.455);
const vec3 BC_BLACK = vec3(0.031, 0.027, 0.039);
const vec3 BC_FUR = vec3(0.878, 0.522, 0.125);
const vec3 BC_CREAM = vec3(0.976, 0.902, 0.729);
// il rosa del naso originale (0.949, 0.443, 0.545) finiva sulla stessa voce della palette del pelo:
// qui il rosa #F2A6B3 della palette, che resta distinto (interno delle orecchie)
const vec3 BC_PINK = vec3(0.949, 0.651, 0.702);
const float BC_CELL = 7.0;   // lato di una cella in pixel interni: il gattone seduto è alto 133 px
const float BC_FLOOR = 28.0; // y dei piedi (il pavimento è la riga appena sotto)

// Sfondo delle scene del gattone: verde acqua con sfumatura verticale a retino e linea del pavimento.
vec3 bigCatBackground(vec2 px, vec2 res) {
    float v = clamp((px.y / res.y - 0.12) / 0.76, 0.0, 1.0);
    vec3 col = mix(BC_TEAL_D, BC_TEAL_L, step(bayer4(px), v));
    if (px.y >= BC_FLOOR - 3.0 && px.y < BC_FLOOR - 1.0) col = BC_BLACK * 0.7;
    return col;
}

vec3 bigCatColor(int id, vec3 col) {
    if (id == 1) return BC_BLACK;
    if (id == 2) return BC_FUR;
    if (id == 3) return BC_CREAM;
    if (id == 4) return BC_PINK;
    return col;
}
