// Dead channel s1 — il monoscopio, poco prima di mezzanotte. La prima metà è pulita (l'immagine fissa
// viene da qui); poi i primi segni: la barra di ronzio, qualche scatto di sincronia, e due volte un
// volto che affiora appena nel quadro, per un istante.

// impulso morbido 0..1 attorno a c, largo w secondi
float dcBlip(float t, float c, float w) {
    return smoothstep(w, 0.0, abs(t - c));
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float ax = iResolution.x / iResolution.y;
    float px = 2.0 / iResolution.y;
    float inside;
    vec2 q = dcScreen(uv, px, inside);
    vec2 p = (q - 0.5) * vec2(ax, 1.0) * 2.0;
    float t = uSceneTime;
    float unrest = smoothstep(0.5, 1.0, uSceneProgress);   // 0 nella prima metà della scena
    p.x += dcTear(p.y, t, unrest * 0.3);
    // convergenza imperfetta verso i bordi: il rosso appena spostato (due valutazioni del monoscopio,
    // non tre: il costo della scena è quasi tutto lì)
    float mis = 0.002 + 0.004 * abs(p.x) / ax;
    float clock = DC_CLOCK0 + iTime;
    vec4 glyph;
    vec3 ink;
    vec4 g2;
    vec3 i2;
    vec3 col = dcCard(p, ax, px, clock, 0, 0.0, glyph, ink);
    col.r = dcCard(p + vec2(mis, 0.0), ax, px, clock, 0, 0.0, g2, i2).r;
    col = mix(col, ink, dcGlyph(p, glyph));
    // il volto: due apparizioni brevi e tenui nella seconda metà
    float seen = dcBlip(t, 15.2, 0.45) + 0.8 * dcBlip(t, 19.6, 0.35);
    if (seen > 0.0) {
        float g = dcGhost(p, px, t);
        col = mix(col, vec3(0.80, 0.88, 0.95), g * seen * 0.35);
    }
    col *= dcHum(q.y, t, unrest);
    col = dcTube(col, q, inside);
    fragColor = vec4(finalize(col, uv), 1.0);
}
