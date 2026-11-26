// Edge horizon: sfondo animato per la hero di openedge.consulting, nello stile del sito.
// - Cielo: fondo slate-950 con la griglia di puntini del CSS del sito (1 px bianco al 6% ogni 24 px),
//   qualche puntino "nodo" che pulsa piano (ciano, uno su quattro rosa) e onde di dati che salgono dal
//   pianeta accendendo i puntini. Nella zona del titolo restano quasi solo i puntini.
// - Pianeta: bordo di un pianeta ghiacciato in basso (come l'immagine della hero del sito), disegnato
//   come un progetto: meridiani ogni 15°, paralleli tratteggiati ogni 10°, una rete di nodi con impulsi
//   che corrono sugli archi.
// - Atmosfera: alone ciano sul bordo che vira al rosa verso destra (il gradiente ciano→rosa delle card).
// Loop di 128 s senza giunture: ogni moto dipende dalla fase P in [0,1) con frequenze intere; la
// superficie si ripete 4 volte in un giro e ruota di un quarto di giro per loop.

const float EH_PERIOD = 128.0;     // durata del loop: 64 battute a 120 BPM
const float EH_TAU = 6.28318530718;
const float EH_R = 1.3;            // raggio del pianeta in altezze dello schermo
const float EH_TOP = -0.22;        // y della cima dell'arco (uv.y va da -0.5 in basso a 0.5 in alto)
const float EH_TILES = 4.0;        // tessere della superficie in un giro (una tessera = 90°)
const vec3 EH_AXIS = vec3(0.0, 0.33036, 0.94386);  // asse di rotazione inclinato verso chi guarda
const vec3 EH_LIGHT = vec3(-0.22, 0.86, 0.46);     // luce dall'alto, un po' da sinistra
const float EH_GRID_ROWS = 37.5;   // righe della griglia di puntini: 24 px a 900 px d'altezza (CSS)

// Value noise periodico in x con periodo `per` celle: dopo una tessera la superficie torna identica.
float ehNoise(vec2 p, float per) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float x0 = mod(i.x, per);
    float x1 = mod(i.x + 1.0, per);
    float a = hash21(vec2(x0, i.y));
    float b = hash21(vec2(x1, i.y));
    float c = hash21(vec2(x0, i.y + 1.0));
    float d = hash21(vec2(x1, i.y + 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// fbm periodico in x (il periodo raddoppia con la frequenza). x = fbm in [0,1]; y = le ottave fini
// "a creste" (1 - |2v - 1|), la superficie increspata del ghiaccio.
vec2 ehFbm(vec2 p, float per) {
    float s = 0.0;
    float rd = 0.0;
    float a = 0.5;
    float norm = 0.0;
    float rnorm = 0.0;
    int oct = qOctaves(5);
    for (int i = 0; i < 5; i++) {
        if (i >= oct) break;
        float v = ehNoise(p, per);
        s += a * v;
        norm += a;
        if (i >= 2) {
            rd += a * (1.0 - abs(2.0 * v - 1.0));
            rnorm += a;
        }
        p = p * 2.0 + vec2(0.0, 5.17);
        per *= 2.0;
        a *= 0.55;
    }
    return vec2(s / norm, rnorm > 0.0 ? rd / rnorm : 0.5);
}

// Crateri: celle di Worley periodiche in x (`per` celle), al più un cratere per cella (circa una su
// tre), di raggio vario. Luce dall'alto dello schermo, cioè da latitudini minori (il polo dell'asse
// è sotto lo schermo): la parete interna in basso è illuminata, quella in alto in ombra.
// Ritorna la variazione di albedo (negativa = ombra).
float ehCraters(vec2 p, float per) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float shade = 0.0;
    // un cratere sporge nella cella vicina al più di 0.28: bastano le 2×2 celle dal lato di f
    vec2 side = step(0.5, f) * 2.0 - 1.0;
    for (int y = 0; y <= 1; y++) {
        for (int x = 0; x <= 1; x++) {
            vec2 o = vec2(float(x), float(y)) * side;
            vec2 key = vec2(mod(i.x + o.x, per), i.y + o.y);
            float h = hash21(key + 3.7);
            if (h > 0.34) continue;
            vec2 c = o + 0.5 + (vec2(hash21(key + 11.1), hash21(key + 23.9)) - 0.5) * 0.5;
            float r = 0.1 + 0.9 * h * h * 3.0;  // tanti piccoli, pochi grandi (r fino a ~0.4)
            r = min(r, 0.42);
            vec2 v = (f - c) / r;
            float d = length(v);
            if (d > 1.25) continue;
            float wall = 1.0 - smoothstep(0.55, 1.0, d);          // dentro il cratere
            float lip = 1.0 - smoothstep(0.0, 0.22, abs(d - 1.0)); // bordo rialzato
            float lit = v.y / max(d, 1e-3) * smoothstep(0.1, 0.6, d); // +1 parete in basso, -1 in alto
            shade += wall * lit * 0.28 + lip * (0.16 - 0.1 * lit) - wall * 0.06;
        }
    }
    return shade;
}

// distanza dal segmento ab (x) e parametro lungo il segmento (y)
vec2 ehSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float t = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return vec2(length(pa - ba * t), t);
}

// Rete di una tessera in coordinate di mappa (x: 0..1 la tessera, y: latitudine in tessere): 6 nodi
// e 7 archi. I nodi 6 e 7 sono i nodi 0 e 1 della tessera seguente e l'arco 7 è la copia dell'arco
// 0-1: così, spostando di una tessera i pixel all'inizio (x < 0.12), una sola chiamata vede anche
// l'arco 5-6 che attraversa il bordo.
const vec2 EH_NODE[8] = vec2[8](
    vec2(0.04, 0.32), vec2(0.19, 0.45), vec2(0.36, 0.30), vec2(0.53, 0.50),
    vec2(0.70, 0.36), vec2(0.86, 0.47), vec2(1.04, 0.32), vec2(1.19, 0.45));
const ivec2 EH_LINK[8] = ivec2[8](
    ivec2(0, 1), ivec2(1, 2), ivec2(2, 3), ivec2(3, 4), ivec2(4, 5), ivec2(5, 6), ivec2(1, 3), ivec2(6, 7));
const int EH_LINK_SRC[8] = int[8](0, 1, 2, 3, 4, 5, 6, 0);  // l'arco copia ha l'impulso dell'originale
const float EH_LINK_K[7] = float[7](5.0, 7.0, 6.0, 8.0, 5.0, 7.0, 6.0); // passaggi per loop (interi)
const int EH_PINK_LINK = 6;

// x = archi, y = impulsi, z = nodi, w = impulso rosa. pxm = unità di mappa per pixel.
vec4 ehNet(vec2 tp, float pxm, float P) {
    float lines = 0.0;
    float pulse = 0.0;
    float nodes = 0.0;
    float pink = 0.0;
    for (int i = 0; i < 8; i++) {
        vec2 a = EH_NODE[EH_LINK[i].x];
        vec2 b = EH_NODE[EH_LINK[i].y];
        vec2 st = ehSeg(tp, a, b);
        float dpx = st.x / pxm;
        if (dpx > 12.0) continue;  // lontano dall'arco: linea e impulso sono già zero
        lines = max(lines, 1.0 - smoothstep(0.3, 1.3, dpx));
        // testa dell'impulso lungo l'arco; oltre 1 è la pausa tra due passaggi
        int src = EH_LINK_SRC[i];
        float s = fract(EH_LINK_K[src] * P + float(src) * 0.137) * 1.6;
        float lenPx = length(b - a) / pxm;
        float behind = (s - st.y) * lenPx;  // px dietro la testa (negativo: davanti)
        float head = behind >= 0.0 ? exp(-behind / 28.0) : exp(behind / 3.0);
        float pl = head * exp(-dpx / 1.6) * smoothstep(0.0, 0.1, s) * (1.0 - smoothstep(1.0, 1.25, s));
        pulse = max(pulse, pl);
        if (src == EH_PINK_LINK) pink = max(pink, pl);
    }
    for (int i = 0; i < 8; i++) {
        float dpx = length(tp - EH_NODE[i]) / pxm;
        if (dpx > 30.0) continue;  // alone già sotto 0.001
        float breathe = 0.7 + 0.3 * sin(EH_TAU * (3.0 * P + float(i % 6) * 0.31)); // 6, 7 = copie di 0, 1
        nodes = max(nodes, ((1.0 - smoothstep(1.6, 2.6, dpx)) + exp(-dpx / 5.0) * 0.35) * breathe);
    }
    return vec4(lines, pulse, nodes, pink);
}

vec3 ehSky(vec2 fragCoord, vec2 uv, vec2 res, float P, float dEdge) {
    vec3 col = OE_BG;
    // griglia di puntini del sito: le misure sono in px CSS (cella 24, punto di raggio 1)
    float cell = res.y / EH_GRID_ROWS;          // lato della cella in pixel del canvas
    float css = 24.0 / cell;                    // px CSS per pixel del canvas
    vec2 id = floor(fragCoord / cell);
    float dCss = length(fract(fragCoord / cell) - 0.5) * 24.0;

    // zona del titolo: effetti attenuati, restano i puntini
    float quiet = smoothstep(0.55, 1.15, length((uv - vec2(0.0, 0.07)) / vec2(0.62, 0.24)));
    float fx = mix(0.3, 1.0, quiet);

    // onde di dati: un anello ogni 16 s sale dal bordo del pianeta e accende i puntini
    float front = fract(8.0 * P) * 1.25;
    float dw = (dEdge - front) / 0.03;
    float wave = 0.0;
    if (abs(dw) < 4.0) {
        float life = 1.0 - front / 1.25;
        wave = exp(-dw * dw) * life * life * smoothstep(0.0, 0.08, front) * fx;
    }

    float dotR = 1.0 + 0.6 * wave;
    float dotA = clamp((dotR - dCss) / css + 0.5, 0.0, 1.0);
    col = mix(col, vec3(1.0), 0.06 * dotA);
    col = mix(col, OE_CYAN300, 0.32 * wave * dotA);

    // nodi: ~1,6% dei puntini pulsa piano, uno su quattro in rosa
    float h = hash21(id + 0.5);
    if (h < 0.016) {
        float h2 = hash21(id + 17.31);
        float k = 2.0 + floor(h2 * 5.0);        // pulsazioni per loop (intere)
        float beat = pow(0.5 + 0.5 * sin(EH_TAU * (k * P + h2)), 6.0);
        vec3 nodeCol = h2 < 0.25 ? OE_PINK400 : OE_CYAN;
        float core = clamp((1.6 - dCss) / css + 0.5, 0.0, 1.0);
        float halo = exp(-dCss / 4.0) * 0.2;
        col = mix(col, nodeCol, clamp(core * 0.6 + halo, 0.0, 1.0) * beat * fx);
    }

    // atmosfera: alone ciano sul bordo, verso destra vira al rosa; respira piano
    float d = max(dEdge, 0.0);
    float side = clamp(uv.x / (0.5 * res.x / res.y), -1.0, 1.0);
    vec3 atm = mix(OE_SKY, OE_CYAN, exp(-d * 40.0));
    atm = mix(atm, OE_PINK, smoothstep(0.15, 1.0, side) * 0.45);
    float breath = 1.0 + 0.08 * sin(EH_TAU * 2.0 * P);
    col += atm * (exp(-d * 22.0) * 0.40 + exp(-d * 6.0) * 0.045) * breath;
    return col;
}

// n: normale sulla sfera; m: coordinate di mappa; g, gw: reticolo e sua larghezza di pixel;
// pxm: unità di mappa per pixel (le derivate arrivano da fuori: qui siamo dentro un ramo)
vec3 ehPlanet(vec3 n, vec2 m, vec2 g, vec2 gw, float pxm, vec2 uv, float P) {
    // superficie ghiacciata: 4 celle di base per tessera, periodica sulla tessera
    vec2 fb = ehFbm(m * 4.0 + vec2(0.0, 7.0), 4.0);
    float maria = smoothstep(0.36, 0.64, fb.x);    // macchie chiare e scure dai bordi netti
    float crinkle = smoothstep(0.55, 0.95, fb.y);  // increspature chiare
    float albedo = 0.2 + 0.5 * maria + 0.3 * crinkle;
    // crateri, come la luna ghiacciata dell'immagine del sito
    albedo = clamp(albedo + ehCraters(m * vec2(12.0, 15.0), 12.0), 0.0, 1.0);
    vec3 ice = mix(vec3(0.05, 0.10, 0.17), vec3(0.50, 0.68, 0.79), albedo);
    // brina verso il bordo: più chiara e fredda, come nell'immagine del sito
    ice = mix(ice, vec3(0.68, 0.82, 0.90), pow(1.0 - n.z, 1.5) * 0.4 * smoothstep(0.2, 0.7, albedo));
    float diff = max(dot(n, normalize(EH_LIGHT)), 0.0);
    vec3 col = ice * (0.25 + 0.8 * diff);
    // verso il basso dello schermo più scuro e più blu
    col *= mix(vec3(0.45, 0.62, 0.85), vec3(1.0), smoothstep(-0.5, -0.27, uv.y));

    // reticolo del progetto: meridiani continui, paralleli tratteggiati
    vec2 gd = abs(fract(g + 0.5) - 0.5) / max(gw, vec2(1e-5));
    float mer = 1.0 - smoothstep(0.2, 1.1, gd.x);
    float par = (1.0 - smoothstep(0.2, 1.1, gd.y)) * step(0.4, fract(g.x * 4.0));
    float moire = 1.0 - smoothstep(0.12, 0.35, max(gw.x, gw.y)); // al bordo le linee si addensano
    col = mix(col, OE_CYAN300, max(mer, par) * moire * 0.2);

    // rete di nodi; all'inizio della tessera si guarda la copia, che vede anche l'arco 5-6
    vec2 tp = vec2(fract(m.x), m.y);
    if (tp.x < 0.12) tp.x += 1.0;
    // i nodi stanno fra le latitudini 0.30 e 0.50: fuori da questa fascia (più un margine) niente rete
    vec4 net = abs(tp.y - 0.4) < 0.1 + 30.0 * pxm ? ehNet(tp, pxm, P) : vec4(0.0);
    float fade = smoothstep(0.02, 0.2, n.z);  // di scorcio, vicino al bordo, la rete si spegne
    col = mix(col, OE_CYAN, net.x * 0.30 * fade);
    col = mix(col, OE_CYAN300, clamp(net.z, 0.0, 1.0) * 0.75 * fade);
    vec3 pc = mix(OE_CYAN300, OE_PINK400, clamp(net.w / max(net.y, 1e-4), 0.0, 1.0));
    col += pc * net.y * 0.85 * fade;

    // bordo interno luminoso (atmosfera vista di taglio)
    float rim = 1.0 - n.z;
    col += OE_CYAN * pow(rim, 6.0) * 0.55 + OE_SKY * pow(rim, 2.5) * 0.10;
    return col;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 uv = (fragCoord - 0.5 * res) / res.y;
    float P = loopT(iTime, EH_PERIOD);

    // geometria del pianeta e derivate, calcolate per tutti i pixel fuori dai rami
    vec2 q = uv - vec2(0.0, EH_TOP - EH_R);
    float dEdge = length(q) - EH_R;  // > 0 nel cielo, in altezze dello schermo
    vec3 n = vec3(q, sqrt(max(EH_R * EH_R - dot(q, q), 0.0))) / EH_R;
    float lat = asin(clamp(dot(n, EH_AXIS), -1.0, 1.0));
    float lon = atan(n.x, dot(n, vec3(0.0, EH_AXIS.z, -EH_AXIS.y)));
    float tileA = EH_TAU / EH_TILES;
    vec2 m = vec2(lon / tileA - P, lat / tileA);  // una tessera per loop
    vec2 g = m * vec2(6.0, 9.0);                   // meridiani ogni 15°, paralleli ogni 10°
    vec2 gw = fwidth(g);
    float pxm = length(fwidth(m)) * 0.6;

    vec3 col = ehSky(fragCoord, uv, res, P, dEdge);
    float inside = clamp(0.5 - dEdge * res.y, 0.0, 1.0);
    if (inside > 0.0) col = mix(col, ehPlanet(n, m, g, gw, pxm, uv, P), inside);
    fragColor = vec4(finalize(col, fragCoord / res), 1.0);
}
