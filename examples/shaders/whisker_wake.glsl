// whisker hunt, scena 1 "risveglio": la scena s1 di "Whisker Idle" con il gattino dritto.
// Nell'originale righe dello sprite, coda e ombra crescevano verso l'alto (y del fragCoord sale):
// il gatto era capovolto sotto la sua ombra. Qui si disegnano in fy = 146 - y, cioè ribaltati e
// appoggiati sul pavimento in basso; colori, palette e animazione sono quelli originali.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord;
    int ix = int(px.x);
    int fy = 146 - int(px.y);

    // palette a 16 colori: verde acqua per il vuoto, nero/arancione/bianco per lo sprite
    const vec3 pal[16] = vec3[16](
        vec3(0.004, 0.020, 0.030),
        vec3(0.010, 0.050, 0.060),
        vec3(0.016, 0.080, 0.100),
        vec3(0.030, 0.130, 0.150),
        vec3(0.050, 0.190, 0.210),
        vec3(0.000, 0.000, 0.000),
        vec3(0.850, 0.450, 0.100),
        vec3(0.920, 0.920, 0.880),
        vec3(0.008, 0.035, 0.045),
        vec3(0.040, 0.160, 0.180),
        vec3(0.070, 0.230, 0.250),
        vec3(0.700, 0.350, 0.080),
        vec3(0.950, 0.650, 0.250),
        vec3(0.750, 0.750, 0.720),
        vec3(0.020, 0.100, 0.120),
        vec3(0.060, 0.210, 0.230)
    );

    // entrata: lo sprite sale di UNA riga di pixel con easeOutCubic, a pixel interi
    float e = easeOutCubic(clamp(uSceneProgress * 5.0, 0.0, 1.0));
    int yOff = 1 - int(floor(e + 0.5));   // 1 (una riga più in basso) -> 0 (fermo)
    float vis = e;                        // comparsa a retino

    // sfondo: verde acqua scuro con una sfumatura verticale a retino
    float depth = clamp(px.y / res.y, 0.0, 1.0);
    vec3 col = (bayer4(px) < depth) ? pal[3] : pal[2];

    // granelli di polvere radi, ricollocati a ogni battuta (a scatti, mai sfumati)
    vec2 cell = floor(px / vec2(32.0, 24.0));
    float h = hash11(cell.x * 7.31 + cell.y * 113.7 + floor(uBar) * 17.13);
    vec2 sp = (cell + vec2(hash11(h + 1.0), hash11(h + 2.0))) * vec2(32.0, 24.0);
    if (h > 0.82 && length(px - (sp + vec2(0.5))) < 0.6 && fract(uBar) > 0.5) col = pal[4];

    bool show = bayer4(px) < vis;

    // ombra di 2 pixel sotto il gatto
    if (show && (fy == 120 || fy == 121) && ix >= 38 && ix <= 58) col = pal[1];

    // coda: appoggiata a terra, dopo un terzo della scena comincia a muoversi lenta verso l'alto
    float tt = wrapTime(uSceneTime, 0.9375); // 2 beat a 128 BPM
    float sw = (0.5 - 0.5 * cos(6.2831853 * tt)) * clamp(uSceneProgress * 2.0 - 0.6, 0.0, 1.0);
    int tj = 39 - ix; // segmento, 0 attaccato alla schiena
    if (show && tj >= 0 && tj <= 9) {
        int lift = int(floor(sw * 3.0 * (float(tj) / 9.0) + 0.5));
        int dy = fy - (118 + yOff - lift);
        if (dy >= 0 && dy < 2) col = pal[6];              // coda arancione, spessa 2 pixel
        else if (dy == -1 || dy == 2) col = pal[5];      // contorno nero
    }

    // gatto: bitmap 16x16 disegnata a mano, pixel 1:1, seduto di profilo
    const uint CAT[16] = uint[16](
        0u, 3120u, 3640u, 4088u, 4088u, 4088u, 4088u, 8184u,
        16380u, 16380u, 16382u, 16382u, 16382u, 16382u, 16380u, 8184u
    );
    int lx = ix - 40;
    int r = fy - 103 - yOff; // righe 0 (punta delle orecchie) .. 14 (base sul pavimento)
    if (show && lx >= 0 && lx < 16 && r >= 0 && r < 15) {
        int m0 = int((CAT[r] >> (15 - lx)) & 1u);
        if (m0 == 1) {
            int m1 = (lx < 15) ? int((CAT[r] >> (14 - lx)) & 1u) : 0;
            int m2 = (lx > 0)  ? int((CAT[r] >> (16 - lx)) & 1u) : 0;
            int m3 = (r < 15)  ? int((CAT[r + 1] >> (15 - lx)) & 1u) : 0;
            int m4 = (r > 0)   ? int((CAT[r - 1] >> (15 - lx)) & 1u) : 0;
            int interior = m1 * m2 * m3 * m4;
            // occhio: chiuso a scatti, all'incirca ogni 4 s
            bool blink = fract(uSceneTime * 0.25) < 0.1;
            if (lx == 11 && r == 4 && !blink) {
                col = pal[5]; // occhio aperto: un pixel nero
            } else if (interior == 1) {
                if (lx >= 9 && lx <= 12 && r >= 7 && r <= 12) col = pal[7]; // petto bianco
                else col = pal[6]; // pelo arancione
            } else {
                col = pal[5]; // contorno nero (bordo della maschera)
            }
        }
    }

    vec2 uv = pixUV(fragCoord, res);
    fragColor = vec4(retroFinalize(col, uv, fragCoord, pal, 16), 1.0);
}
