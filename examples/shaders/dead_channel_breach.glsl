// Dead channel s2 — l'intrusione. Qualcuno buca il segnale dall'interno: blocchi corrotti come in un
// datamosh, rosso e blu che si separano, scatti di sincronia, vuoti di segnale a ritmo di battuta, il
// quadro che scivola in verticale. La scritta in alto diventa INTRUSION, poi HACKED; righe di dump
// esadecimale salgono dal basso; il volto dell'entità (il fantasma nella macchina) affiora a blocchi.
// L'orologio arriva a mezzanotte mentre il tubo si spegne (riga, punto, buio).
// Sicurezza (WCAG 2.3.1, al più 3 flash al secondo per zona): i cambi grandi sono lenti e sommati restano
// sotto il limite (salti di sincronia e blocchi 1.5/s, scritta 2/s, vuoti di segnale ogni due battiti); quelli
// veloci sono piccoli (tremito di sincronia, tremolio di tutto il quadro sotto il 10% di luminanza).

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float ax = iResolution.x / iResolution.y;
    float px = 2.0 / iResolution.y;
    float t = uSceneTime;
    float pr = uSceneProgress;
    float amt = smoothstep(0.0, 0.75, pr);                      // l'intrusione cresce per tutta la scena
    // il quadro scivola in verticale (perdita del sincronismo verticale) a metà scena: uno schermo intero
    // in ~6.5 s con partenza e arrivo morbidi, al più 0.23 schermi al secondo (il monoscopio ha ~5 bande
    // chiare e scure per altezza: più veloce, ogni zona lampeggerebbe oltre 3 volte al secondo)
    float slip = smoothstep(0.36, 0.42, pr) * (1.0 - smoothstep(0.6, 0.66, pr));
    // la calma prima dello spegnimento: l'intrusione ha preso il controllo, il quadro si ferma su HACKED
    float calm = smoothstep(0.84, 0.88, pr);
    float glitch = amt * (1.0 - calm);
    // vuoto di segnale: al più uno ogni due battiti (0.75/s), per un terzo di battito; niente mentre il
    // quadro scivola (sommati facevano 3 flash al secondo al centro)
    float drop = step(1.0 - 0.6 * glitch, hash11(floor(uBeat * 0.5) + 0.37)) * step(fract(uBeat * 0.5), 0.17)
               * (1.0 - slip);
    float gain;
    float flatten;
    float inside;
    vec2 q0 = dcScreen(uv, px, inside);
    // spegnimento a fine scena, poi ~1 s di tubo spento: lo spegnimento e la riaccensione della scena dopo
    // cadono in secondi diversi (insieme facevano 3 flash al secondo al centro dello schermo)
    vec2 q = dcPower(q0, 1.0 - smoothstep(0.9, 0.95, pr), gain, flatten);
    float roll = fract(q.y + smoothstep(0.36, 0.66, pr));
    float blank = slip * smoothstep(0.0, 0.015, roll) * smoothstep(0.08, 0.065, roll);
    q.y = roll;
    q += dcBlocks(q, t, glitch * (1.0 - 0.7 * slip));
    vec2 p = (q - 0.5) * vec2(ax, 1.0) * 2.0;
    p.x += dcTear(p.y, t, (0.25 + 0.75 * glitch) * (1.0 - 0.7 * slip));   // mentre scivola, sincronia più calma
    float mis = 0.002 + 0.004 * abs(p.x) / ax + glitch * 0.012 * (0.5 + 0.5 * sin(t * 1.7));
    float clock = DC_CLOCK0 + iTime;
    // la scritta in alto: INTRUSION sempre più spesso, HACKED nell'ultimo terzo (cambia 2 volte al secondo)
    float hit = step(1.0 - 0.7 * amt, hash11(floor(t * 2.0) + 0.11));
    int id = calm > 0.0 ? 3 : (hit > 0.5 ? (pr > 0.66 ? 3 : 1) : 0);
    vec4 glyph;
    vec3 ink;
    vec4 g2;
    vec3 i2;
    vec3 col = dcCard(p, ax, px, clock, id, 0.0, glyph, ink);
    col.r = dcCard(p + vec2(mis, 0.0), ax, px, clock, id, 0.0, g2, i2).r;
    vec2 gp = p;                                                // dove vale la richiesta di glifo
    // il volto dell'entità, a blocchi come un segnale digitale rotto; nei vuoti si vede meglio
    vec2 pq = (floor(p * 22.0) + 0.5) / 22.0;
    float face = smoothstep(0.25, 0.85, pr) * (0.4 + 0.4 * drop);
    if (face > 0.0) {
        float g = dcGhost(pq, px * 4.0, t);
        col = mix(col, mix(vec3(0.75, 0.95, 1.0), DC_CYAN, 0.4), g * face * 0.55);
    }
    // dump esadecimale che sale dal basso nella seconda metà, su righe in ombra
    const float LH = 0.07;
    float rows = floor(smoothstep(0.45, 0.95, pr) * 9.0);
    float ty = p.y + 1.0;
    float row = floor(ty / LH);
    if (row < rows && ty > 0.0) {
        vec2 hp = vec2(p.x, mod(ty, LH));
        vec4 hx = dcHex(hp, vec2(-ax + 0.14, 0.012), 0.046, 38, row * 7.0 + floor(t * 2.0 + row));
        col = mix(col, col * 0.35, 0.8);
        ink *= 0.4;                                             // le scritte del monoscopio restano in ombra
        if (hx.w >= 0.0) {
            glyph = hx;
            gp = hp;
            ink = mix(DC_CYAN, vec3(0.4, 1.0, 0.6), 0.5);
        }
    }
    col = mix(col, ink, dcGlyph(gp, glyph));
    // neve: di fondo che sale, piena nei vuoti di segnale (luminanza media simile al quadro)
    float snow = dcSnow(q, t);
    col = mix(col, vec3(snow * 0.85 + 0.05), max(glitch * 0.2, drop * 0.85));
    col = mix(col, vec3(0.0), blank);
    col *= dcHum(q.y, t, 0.4 + 0.6 * glitch) * dcFlicker(t, glitch);
    col = mix(col, vec3(0.62), flatten) * gain;
    col = dcTube(col, q0, inside);
    fragColor = vec4(finalize(col, uv), 1.0);
}
