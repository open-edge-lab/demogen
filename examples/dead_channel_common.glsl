// Style di "dead channel": un monoscopio anni '80 su un tubo CRT, e i disturbi che lo corrompono.
// Il monoscopio è originale, nello stile di quelli europei dell'epoca: reticolo di convergenza, cerchio
// centrale con barre colore, scala di grigi, reticoli di frequenza (multiburst), rampa, orologio, merli
// lungo i bordi e zone plate negli angoli. Nessun marchio reale: il canale è "DEMOGEN TV".
// Misure in unità dell'immagine (altezza 2, centro 0), mai in pixel: lo stesso fotogramma va dal player
// a bassa risoluzione fino a uno still 8K. I dettagli fini (zone plate, scanline, fosfori) svaniscono
// sotto i 2 pixel (detailFade) invece di fare moiré, e ricompaiono da soli a risoluzione più alta.
// Viene concatenato DOPO la libreria tree-shaked nel `common` del payload.

const float DC_TAU = 6.28318530718;
const float DC_CELL = 1.0 / 6.0;     // lato del quadretto del reticolo: 12 righe sull'altezza
const float DC_LINE = 0.0075;        // spessore delle righe bianche
const float DC_R = 0.84;             // raggio del cerchio centrale
const float DC_LINES = 288.0;        // righe di scansione sull'altezza (un semiquadro PAL)
const float DC_TRIADS = 640.0;       // terne di fosfori sulla larghezza dello schermo
const float DC_SCENE = 21.3333333;   // durata di una scena: 8 battute a 90 BPM
// ora del monoscopio all'inizio (23:59:19): la mezzanotte arriva mentre il tubo si spegne, ~2 s prima della
// fine della seconda scena
const float DC_CLOCK0 = 86400.0 - 2.0 * DC_SCENE + 2.2;

const vec3 DC_GRAY = vec3(0.42, 0.42, 0.40);
const vec3 DC_WHITE = vec3(0.92, 0.91, 0.86);
const vec3 DC_BLACK = vec3(0.04, 0.04, 0.05);
const vec3 DC_NIGHT = vec3(0.07, 0.04, 0.14);
const vec3 DC_MAGENTA = vec3(1.0, 0.18, 0.70);
const vec3 DC_CYAN = vec3(0.12, 0.92, 1.0);
const vec3 DC_VIOLET = vec3(0.48, 0.24, 0.95);
const vec3 DC_AMBER = vec3(1.0, 0.66, 0.20);

// barre colore al 75% (bianco, giallo, ciano, verde, magenta, rosso, blu, nero) e la loro versione neon
const vec3 DC_BARS[8] = vec3[8](
    vec3(0.75), vec3(0.75, 0.75, 0.0), vec3(0.0, 0.75, 0.75), vec3(0.0, 0.75, 0.0),
    vec3(0.75, 0.0, 0.75), vec3(0.75, 0.0, 0.0), vec3(0.0, 0.0, 0.75), DC_BLACK
);
const vec3 DC_NEON[8] = vec3[8](
    DC_WHITE, DC_AMBER, DC_CYAN, vec3(0.20, 0.55, 1.0),
    DC_MAGENTA, DC_VIOLET, vec3(0.30, 0.08, 0.45), DC_BLACK
);
// cicli per unità dei sei gruppi del multiburst
const float DC_BURST[6] = float[6](6.0, 10.0, 16.0, 26.0, 40.0, 64.0);

// palette a 16 colori: per convenzione con gli altri style (serve solo al ramo retro)
const vec3 PALETTE[16] = vec3[16](
    DC_BLACK, DC_GRAY, DC_WHITE,
    vec3(0.75), vec3(0.75, 0.75, 0.0), vec3(0.0, 0.75, 0.75), vec3(0.0, 0.75, 0.0),
    vec3(0.75, 0.0, 0.75), vec3(0.75, 0.0, 0.0), vec3(0.0, 0.0, 0.75),
    DC_MAGENTA, DC_CYAN, DC_VIOLET, DC_AMBER, DC_NIGHT, vec3(1.0)
);
const int PALETTE_N = 16;

// copertura 0..1 di una forma con distanza con segno d (negativa dentro), bordo sfumato su un pixel
float dcFill(float d, float px) {
    return clamp(0.5 - d / px, 0.0, 1.0);
}

// distanza con segno da un rettangolo di centro c e semilati hs
float dcBox(vec2 p, vec2 c, vec2 hs) {
    vec2 d = abs(p - c) - hs;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

// Testo. Le funzioni di testo non disegnano: dicono quale glifo cade in questo pixel, come richiesta
// (angolo basso-sx, scala, codice ASCII; codice -1 = niente), e la scena lo disegna UNA volta sola con
// dcGlyph. Ogni chiamata a drawGlyph si porta dietro la tabella del font, e ANGLE→D3D ne incolla una copia
// per ogni punto di chiamata: con sei scritte per scena la compilazione superava il gate.
const vec4 DC_NOGLYPH = vec4(0.0, 0.0, 1.0, -1.0);

// scritta di n caratteri ASCII (al più 16) centrata in c, glifi alti gh (font 8x8 della libreria)
vec4 dcText(vec2 p, vec2 c, float gh, int n, int s[16]) {
    float sc = gh / 8.0;
    vec2 o = c - vec2(float(n) * gh * 0.5, gh * 0.5);
    vec2 rel = (p - o) / sc;
    if (rel.x < 0.0 || rel.y < 0.0 || rel.y >= 8.0) return DC_NOGLYPH;
    int i = int(rel.x / 8.0);
    if (i >= n) return DC_NOGLYPH;
    return vec4(o + vec2(float(i) * gh, 0.0), sc, float(s[i]));
}

// il glifo richiesto (0/1 di copertura): l'unico punto di chiamata del font in una scena
float dcGlyph(vec2 p, vec4 g) {
    return g.w < 0.0 ? 0.0 : drawGlyph(p, g.xy, g.z, int(g.w));
}

// scritta della fascia in alto: 0 = DEMOGEN TV, 1 = INTRUSION, 2 = NO SIGNAL, 3 = HACKED
vec4 dcId(vec2 p, vec2 c, float gh, int sel) {
    int s[16] = int[16](68, 69, 77, 79, 71, 69, 78, 32, 84, 86, 32, 32, 32, 32, 32, 32);
    int n = 10;
    if (sel == 1) { s = int[16](73, 78, 84, 82, 85, 83, 73, 79, 78, 32, 32, 32, 32, 32, 32, 32); n = 9; }
    if (sel == 2) { s = int[16](78, 79, 32, 83, 73, 71, 78, 65, 76, 32, 32, 32, 32, 32, 32, 32); n = 9; }
    if (sel == 3) { s = int[16](72, 65, 67, 75, 69, 68, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32); n = 6; }
    return dcText(p, c, gh, n, s);
}

// orologio HH:MM:SS dei secondi del giorno t; t < 0 = trattini (orologio impazzito)
vec4 dcClock(vec2 p, vec2 c, float gh, float t) {
    float s = wrapTime(floor(max(t, 0.0)), 86400.0);
    int h = int(s / 3600.0);
    int m = int(mod(s, 3600.0) / 60.0);
    int x = int(mod(s, 60.0));
    int str[16] = int[16](48 + h / 10, 48 + h % 10, 58, 48 + m / 10, 48 + m % 10, 58,
                          48 + x / 10, 48 + x % 10, 32, 32, 32, 32, 32, 32, 32, 32);
    if (t < 0.0) str = int[16](45, 45, 58, 45, 45, 58, 45, 45, 32, 32, 32, 32, 32, 32, 32, 32);
    return dcText(p, c, gh, 8, str);
}

// riga di dump esadecimale ("3F A9 0C ..."): n caratteri da sinistra in o (angolo basso-sx), glifi alti
// gh, cifre da un hash di seed; le cifre cambiano quando cambia seed
vec4 dcHex(vec2 p, vec2 o, float gh, int n, float seed) {
    float sc = gh / 8.0;
    vec2 rel = (p - o) / sc;
    if (rel.x < 0.0 || rel.y < 0.0 || rel.y >= 8.0) return DC_NOGLYPH;
    int i = int(rel.x / 8.0);
    if (i >= n || i % 3 == 2) return DC_NOGLYPH;
    int d = int(hash21(vec2(float(i), seed)) * 16.0);
    return vec4(o + vec2(float(i) * gh, 0.0), sc, float(d < 10 ? 48 + d : 55 + d));
}

// zone plate: anelli con la frequenza che cresce col raggio, fino a ~430 cicli per unità sul bordo.
// Gli anelli più fitti di 2 pixel sfumano nel grigio medio: a 1080p se ne vede la metà interna, in 4K
// quasi tutti, in 8K tutti netti.
float dcZonePlate(vec2 d, float rad, float px) {
    const float K = 350.0;                       // fase = K (r/rad)²
    float r = length(d) / rad;
    float cyc = K * r / (3.14159265 * rad);      // cicli per unità alla distanza r
    return 0.5 + 0.5 * cos(K * r * r) * detailFade(1.0 / max(cyc * px, 1e-6));
}

// il monoscopio. p: coordinate dell'immagine (altezza da -1 a 1), ax = mezza larghezza, px = unità per
// pixel, clock = ora mostrata (secondi, < 0 = trattini), idSel = scritta in alto, neon 0..1 = palette
// cyberpunk della scena del ritorno. Le scritte escono come richiesta di glifo (glyph) con il loro colore
// (ink): la scena le disegna con dcGlyph
vec3 dcCard(vec2 p, float ax, float px, float clock, int idSel, float neon, out vec4 glyph, out vec3 glyphInk) {
    glyph = DC_NOGLYPH;
    glyphInk = vec3(1.0);
    vec3 ink = mix(DC_WHITE, DC_CYAN, neon);
    vec3 col = mix(DC_GRAY, DC_NIGHT * 1.6, neon);
    // reticolo di convergenza: righe a multipli del quadretto, una passa per il centro
    vec2 g = abs(fract(p / DC_CELL + 0.5) - 0.5) * DC_CELL;
    col = mix(col, ink, max(dcFill(g.x - DC_LINE * 0.5, px), dcFill(g.y - DC_LINE * 0.5, px)));
    // merli bianchi e neri lungo i bordi
    if (ax - abs(p.x) < DC_CELL * 0.5 || 1.0 - abs(p.y) < DC_CELL * 0.5) {
        vec2 cell = floor(p / DC_CELL);
        col = mix(DC_BLACK, ink, mod(cell.x + cell.y, 2.0));
    }
    // zone plate nei quattro angoli
    const float ZR = 0.26;
    vec2 zd = abs(p) - vec2(ax - 0.46, 0.60);
    float zl = length(zd);
    if (zl < ZR + DC_LINE) {
        vec3 zp = vec3(dcZonePlate(zd, ZR, px)) * mix(vec3(1.0), DC_MAGENTA, neon * 0.7);
        col = mix(col, zp, dcFill(zl - ZR, px));
        col = mix(col, ink, dcFill(abs(zl - ZR) - DC_LINE * 0.5, px));
    }
    // cerchio centrale con le sue fasce (dove non c'è una fascia il reticolo continua)
    float r = length(p);
    if (r < DC_R + DC_LINE) {
        vec3 c = col;
        float x = p.x;
        float y = p.y;
        float u = clamp((x + DC_R) / (2.0 * DC_R), 0.0, 0.9999);   // 0..1 sulla larghezza del cerchio
        if (y > 0.5 && y < 0.6667) {
            float box = dcFill(dcBox(p, vec2(0.0, 0.5833), vec2(0.46, 0.0833 - DC_LINE * 0.5)), px);
            c = mix(c, DC_BLACK, box);
            glyph = dcId(p, vec2(0.0, 0.5833), 0.09, idSel);
            glyphInk = ink;
        } else if (y > 0.25 && y <= 0.5) {
            int i = int(u * 8.0);
            c = mix(DC_BARS[i], DC_NEON[i], neon);
        } else if (y > 0.0833 && y <= 0.25) {
            c = vec3(mix(0.05, 0.92, floor(u * 6.0) / 5.0));
            c = mix(c, c * DC_VIOLET * 1.6, neon * 0.6);
        } else if (y > -0.0833 && y <= 0.0833) {
            c = DC_BLACK;
            c = mix(c, ink, dcFill(abs(y) - DC_LINE * 0.5, px));                          // riga orizzontale
            c = mix(c, ink, dcFill(abs(x) - DC_LINE * 0.5, px) * step(abs(y), 0.06));     // croce al centro
        } else if (y > -0.3333 && y <= -0.0833) {
            int i = int(u * 6.0);
            float f = DC_BURST[i];
            float v = 0.5 + 0.5 * cos(DC_TAU * f * x) * detailFade(1.0 / (f * px));
            c = mix(DC_BLACK, mix(DC_WHITE, DC_CYAN, neon), v);
        } else if (y > -0.5 && y <= -0.3333) {
            c = mix(DC_BLACK, mix(DC_WHITE, DC_MAGENTA, neon), u);
        } else if (y > -0.6667 && y <= -0.5) {
            float box = dcFill(dcBox(p, vec2(0.0, -0.5833), vec2(0.40, 0.0833 - DC_LINE * 0.5)), px);
            c = mix(c, DC_BLACK, box);
            glyph = dcClock(p, vec2(0.0, -0.5833), 0.09, clock);
            glyphInk = mix(DC_WHITE, DC_AMBER, neon);
        }
        col = mix(col, c, dcFill(r - DC_R, px));
        col = mix(col, ink, dcFill(abs(r - DC_R) - DC_LINE * 0.5, px));
    }
    return col;
}

// curvatura del tubo: uv dell'immagine → uv sullo schermo; inside = copertura dello schermo (angoli
// arrotondati, bordo sfumato su un pixel)
vec2 dcScreen(vec2 uv, float px, out float inside) {
    vec2 c = uv * 2.0 - 1.0;
    c *= 1.0 + vec2(0.030, 0.045) * (c.yx * c.yx);
    vec2 d = abs(c) - vec2(0.93);
    inside = dcFill(length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - 0.07, px);
    return c * 0.5 + 0.5;
}

// una striscia di fosforo dell'aperture grille, centrata in c (frazione della terna)
float dcStripe(float ph, float c) {
    return 0.3 + 0.7 * (1.0 - smoothstep(0.09, 0.2, abs(fract(ph - c + 0.5) - 0.5)));
}

// il tubo: scanline (il fascio si allarga sul chiaro) e fosfori, solo dove sono larghi più di 2 pixel;
// vignetta; cornice di plastica scura appena illuminata dallo schermo
vec3 dcTube(vec3 col, vec2 q, float inside) {
    float s = 0.5 + 0.5 * cos(DC_TAU * q.y * DC_LINES);
    float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
    float scan = mix(0.72 + 0.56 * s, 1.0, lum * 0.4);
    col *= mix(1.0, scan, detailFade(iResolution.y / DC_LINES));
    float ph = fract(q.x * DC_TRIADS);
    vec3 m = vec3(dcStripe(ph, 1.0 / 6.0), dcStripe(ph, 0.5), dcStripe(ph, 5.0 / 6.0)) / 0.56;
    col *= mix(vec3(1.0), m, 0.85 * detailFade(iResolution.x / DC_TRIADS * 0.5));
    vec2 cq = q * 2.0 - 1.0;
    col *= mix(1.08, 0.7, smoothstep(0.3, 1.7, dot(cq, cq)));
    vec2 out2 = max(abs(cq) - 1.0, 0.0);
    vec3 bezel = vec3(0.05, 0.048, 0.056) + vec3(0.05, 0.06, 0.07) * exp(-length(out2) * 18.0);
    return mix(bezel, col, inside);
}

// --- disturbi (amt 0..1) ---

// perdita di sincronia orizzontale: un tremito veloce ma piccolo (12 Hz, al più 0.02 unità: sposta i
// bordi senza cambiare la luminanza media di una zona), salti grandi di bande di righe solo 1.5 volte al
// secondo (un flash WCAG è una coppia su-giù: così meno di uno al secondo per zona) e un'ondulazione lenta
float dcTear(float y, float t, float amt) {
    float band = floor(y * 36.0);
    float fast = floor(t * 12.0);
    float slow = floor(t * 1.5);
    float jitter = (hash21(vec2(band, fast)) - 0.5) * 0.04 * step(0.6, hash21(vec2(band + 3.0, fast)));
    float h = hash21(vec2(band, slow + 101.0));
    float jump = step(1.0 - 0.2 * amt, h) * (hash21(vec2(band + 7.0, slow)) - 0.5) * 0.3;
    float wave = sin(y * 9.0 + t * 2.3) * 0.012 + sin(y * 31.0 - t * 5.1) * 0.005;
    return amt * (jitter + jump + wave);
}

// corruzione a blocchi (datamosh): in una parte dei blocchi lo schermo mostra un altro punto del quadro.
// Ritorna lo spostamento da sommare alle coordinate; i blocchi cambiano 1.5 volte al secondo (meno di un
// flash al secondo per zona) e spostano il contenuto invece di accendere colori pieni
vec2 dcBlocks(vec2 q, float t, float amt) {
    vec2 cell = floor(q * vec2(24.0, 14.0));
    float tick = floor(t * 1.5);
    float h = hash21(cell + vec2(tick * 7.0, tick * 3.0));
    if (h > 0.22 * amt) return vec2(0.0);
    vec2 r = vec2(hash21(cell + vec2(tick, 19.0)), hash21(cell + vec2(31.0, tick))) - 0.5;
    return r * vec2(0.35, 0.12);
}

// neve del canale vuoto: rumore per riga di scansione, a grana orizzontale corta, 30 volte al secondo.
// Dove un granello è più piccolo di ~2 pixel la neve sfuma nella sua media (detailFade), come la vede
// l'occhio: senza, a bassa risoluzione ogni pixel pescava un granello a caso e la luminanza di una zona
// saltava a ogni fotogramma (per la misura dei flash, renderizzata a 128x72, erano lampi veri)
float dcSnow(vec2 q, float t) {
    // granelli di ~3 pixel alle risoluzioni alte (in uno still 8K la neve resta fine), mai più grossi
    // della griglia di base a quelle basse
    vec2 cells = max(vec2(DC_TRIADS * 0.75, DC_LINES), floor(iResolution.xy / 3.0));
    vec2 cell = floor(q * cells);
    float fr = floor(t * 30.0);
    float grainPx = min(iResolution.x / cells.x, iResolution.y / cells.y);
    return mix(0.5, hash21(cell + vec2(fr * 17.0, fr * 29.0)), detailFade(2.0 * grainPx));
}

// barra di ronzio che sale lenta (luminanza -9% al massimo: sotto la soglia di un flash)
float dcHum(float y, float t, float amt) {
    float b = fract(y * 0.5 - t * 0.12);
    return 1.0 - amt * 0.09 * smoothstep(0.0, 0.25, b) * smoothstep(0.6, 0.25, b);
}

// tremolio veloce di tutto il quadro: al più -4.5% del valore mostrato, che anche sui bianchi resta sotto
// il 10% di luminanza lineare (la soglia di un flash WCAG) a qualunque ritmo
float dcFlicker(float t, float amt) {
    return 1.0 - amt * 0.045 * hash11(floor(t * 24.0) + 0.5);
}

// il volto nel rumore: ovale chiaro con orbite e bocca scure, contorni che sfrangiano col rumore
// (fbmPx: in uno still ad alta risoluzione il volto si sfalda in dettagli sempre più fini)
float dcGhost(vec2 p, float px, float t) {
    vec2 w = vec2(fbmPx(p * 3.0 + vec2(0.0, t * 0.4), px * 3.0), fbmPx(p * 3.0 + vec2(9.1, -t * 0.3), px * 3.0));
    vec2 q = p + 0.05 * w;
    float head = length(q / vec2(0.46, 0.60)) - 1.0;
    float eyes = min(length((vec2(abs(q.x), q.y) - vec2(0.17, 0.10)) / vec2(0.10, 0.06)),
                     length((q - vec2(0.0, -0.30)) / vec2(0.15, 0.045))) - 1.0;
    float face = smoothstep(0.2, -0.45, head) * (0.75 + 0.25 * w.x);
    return face * smoothstep(-0.6, 0.35, eyes);
}

// accensione/spegnimento del tubo: k = 1 quadro pieno, 0.5 una riga orizzontale, 0 spento. Ritorna le
// uv da campionare; gain = luminosità (la stessa energia in un'area più piccola: la riga è più chiara);
// flatten = quanto appiattire il quadro sul grigio del fascio prima di schiacciarlo (schiacciato con le sue
// bande, ogni zona vedeva passare chiaro e scuro molte volte in un secondo: lampi)
vec2 dcPower(vec2 q, float k, out float gain, out float flatten) {
    flatten = 1.0 - smoothstep(0.86, 0.98, k);
    float sy = max(clamp(k * 2.0 - 1.0, 0.0, 1.0), 0.006);
    float sx = max(clamp(k * 2.0, 0.0, 1.0), 0.003);
    vec2 c = (q - 0.5) / vec2(sx, sy);
    float on = smoothstep(0.0, 0.06, k) * step(abs(c.x), 0.5) * step(abs(c.y), 0.5);
    gain = on * (1.0 + 0.9 * (1.0 - sy));
    return c + 0.5;
}

vec3 finalize(vec3 col, vec2 uv) {
#ifdef PROFILE_RETRO
    return retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N);
#else
    // dither fisso di mezzo livello a 8 bit, dal pixel dell'immagine intera (non di gl_FragCoord, che
    // in uno still a tile ripeterebbe lo stesso motivo in ogni tile)
    float d = hash21(floor(uv * iResolution.xy)) - 0.5;
    return clamp(col + d / 255.0, 0.0, 1.0);
#endif
}
