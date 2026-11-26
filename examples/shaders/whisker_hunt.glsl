// whisker hunt, scena 3 "caccia": il gattone vede una falena, si acquatta a terra scodinzolando e
// dimenando il sedere, salta in avanti ad arco, atterra, si rimette composto e guarda in alto la
// falena che vola via. Stesso sprite, sfondo e colori della scena "idle"; tutto a scatti a 12 fps.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord.xy;
    int f = int(floor(uSceneTime * 12.0)); // 0..44: 2 battute a 128 BPM = 3,75 s

    // posa del fotogramma
    int k = 0;
    int tail = 0;
    int hip = 0;
    int headUp = 0;
    int flags = 0;
    ivec2 look = ivec2(-1, 0); // la falena è a sinistra
    float ox = 160.0;
    float oy = BC_FLOOR;
    const int WAG[4] = int[4](1, 3, 2, 0); // scodinzolo: alzata della coda a ogni fotogramma
    if (f < 6) {                 // seduto: ha visto la falena, l'orecchio scatta
        if (f >= 3) flags |= BC_EAR;
    } else if (f < 8) {          // si abbassa
        k = 1;
    } else if (f < 24) {         // a terra: scodinzola, poi dimena il sedere prima del balzo
        k = 2;
        tail = WAG[f % 4];
        if (f >= 16) hip = ((f / 2) % 2 == 0) ? -1 : 1;
    } else if (f < 30) {         // balzo in avanti ad arco, zampe sospese
        float s = float(f - 23) / 7.0;
        k = 2;
        tail = 3;
        flags |= BC_AIR;
        ox = floor(mix(160.0, 80.0, s));
        oy = BC_FLOOR + floor(36.0 * sin(3.14159265 * s));
    } else if (f < 32) {         // atterra acquattato dove c'era la falena
        k = 2;
        ox = 80.0;
        tail = 1;
        look = ivec2(-1, 1);
    } else if (f < 34) {         // si rialza
        k = 1;
        ox = 80.0;
        look = ivec2(-1, 1);
    } else {                     // composto, testa alta: segue la falena che vola via
        ox = 80.0;
        headUp = 1;
        look = ivec2(-1, 1);
        tail = int(round(sin(float(f - 34) * 0.6)));
    }

    ivec2 g = ivec2(floor((px - vec2(ox, oy)) / BC_CELL));
    int id = bigCatId(g, k, tail, hip, look, headUp, flags);
    vec3 col = bigCatColor(id, bigCatBackground(px, res));

    // falena crema: svolazza bassa a sinistra; appena il gatto salta scappa in alto a sinistra,
    // lontano dalla sua testa, e resta a svolazzare in alto mentre lui la guarda
    float mf = float(f);
    vec2 moth = vec2(72.0 + floor(4.0 * sin(mf * 0.9)), 58.0 + floor(5.0 * sin(mf * 0.55)));
    if (f >= 26) {
        float a = float(min(f, 31) - 25);
        float b = float(max(f - 31, 0));
        moth += vec2(-8.0 * a - 1.0 * b, 9.0 * a + 4.0 * b);
    }
    ivec2 q = ivec2(floor(px)) - ivec2(moth);
    bool wingsUp = (f % 2) == 0;
    bool body = q.x >= 0 && q.x <= 1 && q.y >= 0 && q.y <= 1;
    bool wing = (q.x == -2 || q.x == -1 || q.x == 2 || q.x == 3) &&
                (wingsUp ? (q.y == 1 || q.y == 2) : (q.y == -1 || q.y == 0));
    if (body || wing) col = BC_CREAM;

    fragColor = vec4(finalize(col, px / res), 1.0);
}
