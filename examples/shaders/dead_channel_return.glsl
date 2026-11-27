// Dead channel s4 — il ritorno. Il monoscopio riaffiora dalla neve, ma ancora in mano all'intrusione:
// palette neon, NO SIGNAL e HACKED nella fascia in alto, l'orologio a trattini, blocchi corrotti e righe
// che scattano che si spengono piano. Poi tutto si ricompone: DEMOGEN TV, i colori veri, e l'orologio
// che torna indietro e riparte da 23:59:10, fino alle 23:59:19 dell'inizio. Gli ultimi istanti sono
// identici al primo fotogramma della demo: il loop si chiude senza giunta.

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float ax = iResolution.x / iResolution.y;
    float px = 2.0 / iResolution.y;
    float t = uSceneTime;
    float pr = uSceneProgress;
    float amt = 1.0 - smoothstep(0.1, 0.8, pr);                // l'intrusione si spegne
    float neon = 1.0 - smoothstep(0.55, 0.92, pr);
    float inside;
    vec2 q0 = dcScreen(uv, px, inside);
    vec2 q = q0 + dcBlocks(q0, t, amt * 0.8);
    vec2 p = (q - 0.5) * vec2(ax, 1.0) * 2.0;
    p.x += dcTear(p.y, t, amt * 0.8);
    float mis = 0.002 + 0.004 * abs(p.x) / ax + amt * 0.01;   // a riposo uguale alla prima scena
    // orologio: trattini, poi l'ora che riparte da 23:59:10 e arriva a quella dell'inizio
    float clock = pr < 0.6 ? -1.0 : DC_CLOCK0 + (t - DC_SCENE);
    float flip = hash11(floor(t * 2.0) + 0.23);
    int id = pr < 0.4 ? (flip > 0.7 ? 3 : 2) : (pr < 0.72 ? (flip > 0.5 ? 2 : 0) : 0);
    vec4 glyph;
    vec3 ink;
    vec4 g2;
    vec3 i2;
    vec3 col = dcCard(p, ax, px, clock, id, neon, glyph, ink);
    col.r = dcCard(p + vec2(mis, 0.0), ax, px, clock, id, neon, g2, i2).r;
    col = mix(col, ink, dcGlyph(p, glyph));
    // l'entità se ne va: il volto a blocchi svanisce nella prima metà
    vec2 pq = (floor(p * 22.0) + 0.5) / 22.0;
    float gone = 1.0 - smoothstep(0.15, 0.5, pr);
    if (gone > 0.0) {
        float g = dcGhost(pq, px * 4.0, t);
        col = mix(col, mix(vec3(0.75, 0.95, 1.0), DC_MAGENTA, 0.3), g * 0.45 * gone);
    }
    // la neve del canale morto si dirada all'inizio; qualche vuoto di segnale finché dura l'intrusione
    float drop = step(1.0 - 0.4 * amt, hash11(floor(uBeat * 0.5) + 0.53)) * step(fract(uBeat * 0.5), 0.13);
    float snowAmt = max(0.85 * (1.0 - smoothstep(0.0, 0.22, pr)), drop * 0.8);
    col = mix(col, vec3(dcSnow(q, t) * 0.8 + 0.06), snowAmt);
    col *= dcHum(q0.y, t, amt) * dcFlicker(t, amt);
    col = dcTube(col, q0, inside);
    fragColor = vec4(finalize(col, uv), 1.0);
}
