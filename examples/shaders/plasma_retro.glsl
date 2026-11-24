// s4 — plasma retro con starfield e scroller di testo, profilo retro (320x180).
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = pixUV(fragCoord, iResolution.xy);
    float t = iTime;
    float pl = plasma2(uv + vec2(0.0, t * 0.05), t);
    vec3 col = cosPalette(pl * 0.5 + 0.5 + uBar * 0.02,
                          vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
    col += starfield(uv + vec2(t * 0.01, 0.0), t, 0.0) * 0.8;
    // scroller: il testo scorre da destra a sinistra a 40 px/s
    float speed = 40.0;
    float textW = float(uTextLen) * 8.0;
    float x0 = iResolution.x + 8.0 - mod(t * speed, textW + iResolution.x + 16.0);
    float cov = drawText(fragCoord, vec2(x0, iResolution.y - 20.0), 2.0);
    col = mix(col, vec3(1.0, 0.9, 0.2), cov * (0.7 + 0.3 * beatPulse(uBeatPhase, 8.0)));
    // copper bar in cima
    float bar = step(uv.y, 0.06 + 0.02 * beatPulse(uBeatPhase, 3.0));
    col = mix(col, vec3(0.9, 0.3, 0.1) * copperBar(uv, uBeatPhase, 5.0), bar);
    fragColor = vec4(finalize(col, uv), 1.0);
}
