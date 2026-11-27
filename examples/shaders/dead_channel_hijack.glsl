// Dead channel s3 — il segnale dirottato, dopo mezzanotte. Il tubo si riaccende sulla neve e dal rumore
// affiora la trasmissione pirata: una città cyberpunk al neon sotto la pioggia, il volto dell'entità
// (il fantasma nella macchina) a curve di livello neon e tagliato a fette, un terminale che scorre dump
// esadecimali e messaggi ("ACCESS GRANTED", "SIGNAL HIJACKED"...) e la barra di UPLINK che si riempie
// fino a "HACKED".
// Sicurezza: la neve sale e scende lenta, le raffiche sono al più una ogni due battiti, i blocchi
// corrotti cambiano 1.5 volte al secondo e spostano contenuto, il tremolio veloce resta sotto il 10%.

// riga sottile: larghezza w in unità di colonna, mai sotto ~1.5 pixel (niente righe che sfarfallano)
float dcThin(float d, float w, float pxCol) {
    float ww = max(w, 1.5 * pxCol);
    return smoothstep(ww, 0.0, d) * min(1.0, w / ww);
}

// uno strato di torri: larghezza w, scorrimento off, cime tra h0 e h1. Ritorna la copertura e, in
// local, la posizione nella torre (x 0..1, id, altezza della cima)
float dcTowers(vec2 p, float w, float off, float h0, float h1, float px, out vec3 local) {
    float x = p.x / w + off;
    float id = floor(x);
    float fx = fract(x);
    float top = mix(h0, h1, hash11(id * 1.37 + w));
    local = vec3(fx, id, top);
    float side = min(fx - 0.06, 0.94 - fx) * w;                // distanza dal fianco, in unità
    return dcFill(p.y - top, px) * dcFill(-side, px);
}

// finestre di una torre: griglia accesa a caso (ambra o ciano), che cambia piano
vec3 dcWindows(vec2 p, vec3 local, float rows, float t) {
    vec2 cell = vec2(floor(local.x * 6.0), floor(p.y * rows));
    vec2 f = vec2(fract(local.x * 6.0), fract(p.y * rows));
    float h = hash21(cell + vec2(local.y * 13.0, 3.0));
    float on = step(0.62, h) * step(0.08, hash21(cell + vec2(local.y, floor(t * 0.5))));
    float box = step(0.25, f.x) * step(f.x, 0.75) * step(0.3, f.y) * step(f.y, 0.75);
    return box * on * mix(DC_AMBER, DC_CYAN, step(0.85, h)) * (0.55 + 0.45 * fract(h * 7.0));
}

// pioggia: righe oblique brevi che cadono, una colonna su tre
float dcRain(vec2 p, float px, float t) {
    vec2 r = vec2(p.x * 70.0 + p.y * 9.0, p.y * 2.5 + t * 6.0);
    float h = hash11(floor(r.x) + 0.5);
    float y = fract(r.y + h * 10.0);
    float streak = smoothstep(0.0, 0.04, y) * smoothstep(0.3, 0.05, y) * step(0.66, h);
    return streak * dcThin(abs(fract(r.x) - 0.5), 0.05, px * 70.0) * 0.5;
}

// la città: cielo viola con foschia magenta e tre strati di torri, insegne verticali al neon
vec3 dcCity(vec2 p, float px, float t) {
    vec3 col = mix(DC_NIGHT, vec3(0.42, 0.08, 0.36), smoothstep(0.6, -0.35, p.y));
    vec3 local;
    float far = dcTowers(p, 0.16, t * 0.010, -0.25, 0.18, px, local);
    col = mix(col, vec3(0.12, 0.05, 0.20) + 0.3 * dcWindows(p, local, 40.0, t), far);
    float mid = dcTowers(p, 0.27, t * 0.022 + 3.0, -0.45, 0.02, px, local);
    col = mix(col, vec3(0.06, 0.03, 0.11) + 0.8 * dcWindows(p, local, 30.0, t), mid);
    float near = dcTowers(p, 0.42, t * 0.045 + 7.0, -0.62, -0.22, px, local);
    vec3 nc = vec3(0.025, 0.02, 0.05) + dcWindows(p, local, 22.0, t);
    float sign = step(0.5, hash11(local.y * 3.1 + 1.0)) * step(0.14, local.x) * step(local.x, 0.24)
               * step(local.z - 0.36, p.y) * step(p.y, local.z - 0.06);
    float buzz = 0.7 + 0.3 * step(0.15, hash11(floor(t * 3.0) + local.y));
    nc = mix(nc, mix(DC_MAGENTA, DC_CYAN, step(0.5, hash11(local.y + 9.0))) * buzz, sign);
    col = mix(col, nc, near);
    return col + dcRain(p, px, t) * vec3(0.55, 0.6, 0.8);
}

// il volto dell'entità: curve di livello neon dell'ovale, occhi e bocca come fessure accese, tagliato
// a fette orizzontali che scattano. Ritorna il colore da sommare
vec3 dcEntity(vec2 p, float px, float t, float amt) {
    vec2 c = p - vec2(-0.62, 0.08);
    float slice = floor(c.y * 26.0);
    float h = hash21(vec2(slice, floor(t * 5.0)));
    c.x += step(0.82, h) * (h - 0.9) * 0.5 * amt;
    c /= 0.85;
    vec2 w = vec2(fbmPx(c * 3.0 + vec2(0.0, t * 0.4), px * 3.0), fbmPx(c * 3.0 + vec2(9.1, -t * 0.3), px * 3.0));
    vec2 q = c + 0.03 * w;
    float head = length(q / vec2(0.46, 0.60)) - 1.0;
    float inHead = smoothstep(0.05, -0.05, head);
    float lv = abs(fract(head * 9.0 - t * 0.6) - 0.5) / 9.0 * 0.85 * 0.6;   // distanza dalla curva, in unità
    float lines = dcFill(lv - 0.0035, px) * inHead;
    float rim = dcFill(abs(head) * 0.28 - 0.004, px);
    vec2 e = vec2(abs(q.x), q.y) - vec2(0.17, 0.10);
    float eyes = dcFill(length(e / vec2(1.0, 0.25)) - 0.08, px);
    float mouth = dcFill(length((q - vec2(0.0, -0.30)) / vec2(1.0, 0.18)) - 0.13, px) * 0.8;
    vec3 col = DC_MAGENTA * (lines * 0.55 + rim * 0.9) + vec3(0.8, 1.0, 1.0) * (eyes + mouth);
    return col * (0.55 + 0.45 * sin(t * 1.3 + c.y * 4.0) * sin(t * 0.7)) + DC_VIOLET * 0.12 * inHead;
}

// scritta allineata a sinistra da o (angolo basso-sx), al più `shown` caratteri (battitura): richiesta
// di glifo, come tutto il testo dello style
vec4 dcTextL(vec2 p, vec2 o, float gh, int n, int s[16], int shown) {
    int k = min(n, shown);
    return dcText(p, o + vec2(float(k) * gh * 0.5, gh * 0.5), gh, k, s);
}

// una riga del terminale: dump esadecimale o uno degli otto messaggi, scelti dall'indice della riga
vec4 dcLine(vec2 p, vec2 o, float gh, float line, int shown) {
    float h = hash11(line * 0.618 + 0.3);
    if (h < 0.55) return dcHex(p, o, gh, min(26, shown), line);
    int m = int(fract(h * 7.31) * 8.0);
    int s[16] = int[16](78, 79, 32, 84, 82, 65, 67, 69, 32, 32, 32, 32, 32, 32, 32, 32);   // NO TRACE
    int n = 8;
    if (m == 0) { s = int[16](65, 67, 67, 69, 83, 83, 32, 71, 82, 65, 78, 84, 69, 68, 32, 32); n = 14; }
    if (m == 1) { s = int[16](83, 89, 83, 84, 69, 77, 32, 66, 82, 69, 65, 67, 72, 32, 32, 32); n = 13; }
    if (m == 2) { s = int[16](82, 79, 79, 84, 32, 65, 67, 67, 69, 83, 83, 32, 32, 32, 32, 32); n = 11; }
    if (m == 3) { s = int[16](85, 80, 76, 73, 78, 75, 32, 79, 80, 69, 78, 32, 32, 32, 32, 32); n = 11; }
    if (m == 4) { s = int[16](83, 73, 71, 78, 65, 76, 32, 72, 73, 74, 65, 67, 75, 69, 68, 32); n = 15; }
    if (m == 5) { s = int[16](72, 69, 76, 76, 79, 32, 87, 79, 82, 76, 68, 32, 32, 32, 32, 32); n = 11; }
    if (m == 6) { s = int[16](87, 69, 32, 83, 69, 69, 32, 89, 79, 85, 32, 32, 32, 32, 32, 32); n = 10; }
    return dcTextL(p, o, gh, n, s, shown);
}

// il terminale: pannello scuro con bordo ciano, righe che scorrono verso l'alto e l'ultima che si
// scrive un carattere alla volta. Ritorna (colore, copertura del pannello) e la richiesta di glifo
vec4 dcTerminal(vec2 p, float px, float t, out vec4 glyph) {
    const vec2 C = vec2(0.86, 0.12);
    const vec2 HS = vec2(0.74, 0.6);
    const float LH = 0.075;
    const float RATE = 2.2;                                     // righe al secondo
    glyph = DC_NOGLYPH;
    float box = dcBox(p, C, HS);
    float panel = dcFill(box, px);
    vec3 col = vec3(0.01, 0.03, 0.04);
    col = mix(col, DC_CYAN, dcFill(abs(box) - 0.004, px));
    vec2 o = vec2(C.x - HS.x + 0.06, C.y + HS.y - 0.05);         // in alto a sinistra del testo
    float r = floor((o.y - p.y) / LH);                          // riga visiva, 0 in alto
    if (r >= 0.0 && r < 15.0 && box < -0.02) {
        float line = floor(t * RATE) - 14.0 + r;
        int shown = r == 14.0 ? int(fract(t * RATE) * 30.0) : 30;
        glyph = dcLine(p, vec2(o.x, o.y - (r + 1.0) * LH + 0.014), 0.045, line, shown);
        float cursor = r == 14.0 ? step(0.5, fract(t * 2.0)) : 0.0;
        col += DC_CYAN * 0.06 * cursor * step(o.y - (r + 1.0) * LH + 0.014, p.y);
    }
    return vec4(col, panel * 0.92);
}

// barra di UPLINK in basso: etichetta, blocchi che si riempiono con k, poi HACKED che pulsa piano.
// Le due scritte escono come richiesta di glifo (glyph, ink)
vec3 dcUplink(vec2 p, float px, float k, float t, vec3 col, out vec4 glyph, out vec3 ink) {
    const float Y = -0.8;
    float band = dcFill(abs(p.y - Y) - 0.07, px);
    col = mix(col, DC_BLACK, band * 0.88);
    float bx = (p.x + 1.05) / 2.1;                              // 0..1 lungo la barra
    float cell = floor(bx * 40.0);
    float seg = step(0.0, bx) * step(bx, 1.0) * step(0.15, fract(bx * 40.0)) * dcFill(abs(p.y - Y) - 0.025, px);
    col = mix(col, mix(vec3(0.12, 0.05, 0.16), DC_MAGENTA, step(cell, floor(k * 40.0))), seg * band);
    glyph = dcTextL(p, vec2(-1.45, Y - 0.025), 0.05, 6, int[16](85, 80, 76, 73, 78, 75, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32), 6);
    ink = DC_WHITE * band;
    if (p.x > 1.0 && k > 0.999) {
        glyph = dcTextL(p, vec2(1.18, Y - 0.025), 0.05, 6, int[16](72, 65, 67, 75, 69, 68, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32), 6);
        ink = mix(col, DC_MAGENTA, band * (0.6 + 0.4 * sin(t * 4.0)));
    }
    return col;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float ax = iResolution.x / iResolution.y;
    float px = 2.0 / iResolution.y;
    float t = uSceneTime;
    float pr = uSceneProgress;
    float gain;
    float flatten;
    float inside;
    vec2 q0 = dcScreen(uv, px, inside);
    vec2 q = dcPower(q0, smoothstep(0.02, 0.07, pr), gain, flatten);   // il tubo si riaccende dopo un attimo di buio
    q += dcBlocks(q, t, 0.6);
    vec2 p = (q - 0.5) * vec2(ax, 1.0) * 2.0;
    p.x += dcTear(p.y, t, 0.35);
    vec3 col = dcCity(p, px, t);
    col += 1.6 * dcEntity(p, px, t, 1.0) * smoothstep(0.1, 0.3, pr);
    float show = smoothstep(0.15, 0.3, pr);
    vec4 gT;
    vec4 term = dcTerminal(p, px, t, gT);
    col = mix(col, term.rgb, term.a * show);
    vec4 gU;
    vec3 inkU;
    col = dcUplink(p, px, smoothstep(0.2, 0.9, pr), t, col, gU, inkU);
    // un solo glifo per pixel: il terminale o la barra
    vec3 inkT = mix(col, mix(vec3(0.35, 1.0, 0.75), DC_CYAN, 0.4), show);
    col = mix(col, gT.w >= 0.0 ? inkT : inkU, dcGlyph(p, gT.w >= 0.0 ? gT : gU));
    // il segnale va e viene: la scena affiora dalla neve, che sale e scende lenta con raffiche brevi
    // (al più una per battuta) e alla fine torna a coprire tutto
    float signal = 0.55 + 0.25 * sin(t * 0.9) + 0.15 * sin(t * 2.3 + 1.0);
    float gust = step(0.75, hash11(floor(uBeat * 0.5) + 0.71)) * step(fract(uBeat * 0.5), 0.12);
    float snowAmt = mix(0.9, clamp(0.55 - signal * 0.5 + gust * 0.35, 0.08, 0.5), smoothstep(0.05, 0.3, pr));
    snowAmt = mix(snowAmt, 0.9, smoothstep(0.9, 1.0, pr));
    col = mix(col, vec3(dcSnow(q, t) * 0.8 + 0.06), snowAmt);
    col *= dcHum(q.y, t, 0.6) * dcFlicker(t, 0.8);
    col = mix(col, vec3(0.62), flatten) * gain;
    col = dcTube(col, q0, inside);
    fragColor = vec4(finalize(col, uv), 1.0);
}
