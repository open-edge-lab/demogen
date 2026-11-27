// whisker hunt, scena 4 "dissolvenza": la scena s3 di "Whisker Idle" con il gatto dritto.
// Nell'originale le celle crescevano verso il basso partendo da un pavimento in alto: gatto
// capovolto, appeso alla sua ombra. Qui pavimento, ombra e celle usano fy = 179 - y (ribaltati):
// il gatto sta in piedi sullo stesso pavimento di "idle" e "caccia". Colori e animazione originali;
// lo stesso gatto, con le pose da caccia, è orangeCat in whisker_common.glsl.

const vec3 PAL[16] = vec3[16](
    vec3(0.02, 0.02, 0.04),  // 0 contorno nero
    vec3(0.85, 0.45, 0.12),  // 1 pelo arancione
    vec3(0.95, 0.85, 0.62),  // 2 crema
    vec3(0.16, 0.07, 0.05),  // 3 marrone scuro (occhi e strisce)
    vec3(0.04, 0.13, 0.15),  // 4 sfondo verde acqua scuro
    vec3(0.08, 0.22, 0.24),  // 5 sfumatura verde acqua chiara
    vec3(0.02, 0.07, 0.08),  // 6 ombra sul pavimento
    vec3(0.06, 0.18, 0.20),  // 7 riempimento sotto il pavimento
    vec3(0.02, 0.02, 0.04),  // 8..15 riempitivo (non usati, gli indici 0..7 restano validi)
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04),
    vec3(0.02, 0.02, 0.04)
);

const int TB[8] = int[8](1, 2, 3, 5, 5, 4, 3, 1);

// pelo in una cella dello sprite (x a destra, y in alto dal pavimento)
bool catFur(ivec2 c, int earT, int tf) {
    // corpo
    if (c.y >= 0 && c.y <= 4 && c.x >= -5 && c.x <= 4) {
        if (c.y == 0 && (c.x < -3 || c.x > 2)) return false;
        return true;
    }
    // testa
    if (c.y >= 5 && c.y <= 10 && c.x >= -4 && c.x <= 3) return true;
    // orecchie (2x2 rastremate, guizzo a scatti)
    int ey = c.y - earT;
    if ((c.x == -4 && ey == 11) || (c.x == -3 && (ey == 11 || ey == 12))) return true;
    if ((c.x ==  2 && ey == 11) || (c.x ==  1 && (ey == 11 || ey == 12))) return true;
    // coda: 5 celle che salgono verso destra, altezza della base a scatti
    int tb = TB[tf];
    for (int i = 0; i < 5; i++) {
        int ty = tb + (i * i) / 4;
        if (c.x == 4 + i && c.y == ty) return true;
    }
    return false;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res  = iResolution.xy;
    vec2 uv   = pixUV(fragCoord, res);
    vec2 px   = fragCoord.xy;
    float fy  = res.y - 1.0 - px.y; // y ribaltata: il pavimento finisce in basso
    float ox     = 160.0;
    float floorY = 152.0;

    // idle a scatti (mai sotto il pixel)
    int  fr    = int(floor(uSceneTime * 8.0));
    int  earT  = ((fr % 24) == 13) ? 1 : 0;
    bool blink = ((fr % 32) == 15);

    // coda: l'indice scende da 7 a 0 durante la scena e si ferma sulla posa di partenza (tb = 1)
    int tf = 7 - min(int(uSceneProgress * 12.0), 7);

    // sfondo: verde acqua scuro con una sfumatura verticale a retino
    float sh  = step(bayer4(fragCoord), uv.y * 0.45);
    vec3  col = mix(PAL[4], PAL[5], sh);
    if (fy > floorY + 2.0) col = PAL[7];

    // ombra di 2 pixel sotto il gatto
    if (fy >= floorY && fy < floorY + 2.0 &&
        px.x > ox - 24.0 && px.x < ox + 38.0) {
        col = PAL[6];
    }

    // griglia dello sprite: celle di 4 pixel
    ivec2 c = ivec2(floor((px.x - ox) / 4.0),
                    floor((floorY - 1.0 - fy) / 4.0));
    if (c.x >= -13 && c.x <= 12 && c.y >= 0 && c.y <= 13) {
        if (catFur(c, earT, tf)) {
            // occhi (nel blink resta il pelo)
            if ((c.x == -2 || c.x == 1) && c.y == 8) {
                col = blink ? PAL[1] : PAL[3];
            } else if (c.x == 0 && c.y == 7) {
                col = PAL[2];                     // muso crema
            } else if (c.x >= -1 && c.x <= 2 && c.y >= 1 && c.y <= 4) {
                col = PAL[2];                     // petto crema
            } else if (c.y <= 4 && c.y > 0 && ((c.x + 5) % 3 == 0)) {
                col = PAL[3];                     // strisce sul corpo
            } else {
                col = PAL[1];                     // pelo arancione
            }
        } else {
            // contorno nero: cella vuota accanto al pelo
            ivec2 epx = ivec2(1, 0), epy = ivec2(0, 1);
            if (catFur(c + epx, earT, tf) || catFur(c - epx, earT, tf) ||
                catFur(c + epy, earT, tf) || catFur(c - epy, earT, tf)) {
                col = PAL[0];
            }
        }
    }

    // dissolvenza a nero a retino nell'ultimo terzo (a scatti, non sfumata)
    float f   = easeOutCubic(clamp((uSceneProgress - 0.6667) * 3.0, 0.0, 1.0));
    float dim = step(bayer4(fragCoord), 1.0 - f);
    col *= dim;

    fragColor = vec4(retroFinalize(col, uv, fragCoord, PAL, 8), 1.0);
}
