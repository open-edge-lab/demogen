// Edge blueprint: sfondo per le sezioni di openedge.consulting sotto la hero. Semplice: la griglia di
// puntini da disegno tecnico del sito (24 px), che respira.
// - due onde larghissime e lente, in direzioni diverse, gonfiano e schiariscono i puntini a zone
//   (verso un ciano leggero dove si sommano); tutto il foglio inspira ed espira ogni 16 s;
// - ogni 5 puntini un crocino "+" da disegno tecnico (come i "+" agli angoli delle card del sito),
//   che respira con loro.
// Unità = px CSS su uno schermo alto 900 px (fragCoord / (res.y / 900)): le misure seguono la pagina.
// Loop di 64 s senza giunture: ogni moto dipende da P in [0,1) con frequenze intere.

const float EB_PERIOD = 64.0;
const float EB_TAU = 6.28318530718;
const float EB_REF_H = 900.0;
const float EB_STEP = 24.0;   // passo dei puntini (come la griglia CSS del sito)
const float EB_CROSS = 5.0;   // un crocino ogni 5 puntini

// respiro 0..1 in un punto: due onde piane lente che si incrociano, per il respiro di tutto il foglio
float ebBreath(vec2 u, float P) {
    float a = dot(u, vec2(0.857, 0.514)) * 0.0055 - EB_TAU * 2.0 * P;
    float b = dot(u, vec2(-0.371, 0.928)) * 0.0081 + EB_TAU * 3.0 * P;
    float w = 0.5 + 0.25 * sin(a) + 0.25 * sin(b);
    float lungs = 0.8 + 0.2 * sin(EB_TAU * 4.0 * P);
    return clamp(w * w * lungs, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    float pu = EB_REF_H / res.y;                 // unità per pixel del canvas
    vec2 u = fragCoord * pu;                     // posizione in unità
    float P = loopT(iTime, EB_PERIOD);

    // cella del puntino più vicino (centrato nella cella, come radial-gradient del CSS)
    vec2 id = floor(u / EB_STEP);
    vec2 d = u - (id + 0.5) * EB_STEP;
    float br = ebBreath((id + 0.5) * EB_STEP, P);  // un valore per puntino: niente sfumature dentro

    // crocino ogni EB_CROSS puntini, altrimenti un puntino
    bool isCross = mod(id.x, EB_CROSS) == 0.0 && mod(id.y, EB_CROSS) == 0.0;
    float cov;
    if (isCross) {
        float arm = 3.5 + 1.5 * br;
        vec2 a = abs(d);
        float dist = min(max(a.x - arm, a.y), max(a.y - arm, a.x));   // distanza dalla croce
        cov = 1.0 - smoothstep(0.5 - 0.5 * pu, 0.5 + 0.5 * pu, dist);
    } else {
        float r = 0.85 + 0.6 * br;
        cov = 1.0 - smoothstep(r - 0.5 * pu, r + 0.5 * pu, length(d));
    }

    vec3 ink = mix(vec3(1.0), OE_CYAN300, 0.8 * br);
    float alpha = (isCross ? 0.12 : 0.07) + 0.28 * br;
    vec3 col = mix(OE_BG, ink, cov * alpha);
    fragColor = vec4(finalize(col, fragCoord / res), 1.0);
}
