// s2 — frattale IFS 2D (fold), profilo modern.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    vec2 p = uv * 1.5;
    float t = iTime;
    float acc = 0.0;
    int n = qSteps(24);
    for (int i = 0; i < 32; i++) {
        if (i >= n) break;
        p = abs(p) / (dot(p, p) + 0.3) - vec2(0.8 + 0.05 * sin(t * 0.7), 0.05 * cos(t * 0.5));
        acc += exp(-4.0 * abs(dot(p, p) - 0.2));
    }
    float beat = beatPulse(uBeatPhase, 4.0);
    vec3 col = cosPalette(acc * 0.05 + t * 0.05 + beat * 0.1,
                          vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.3, 0.2, 0.6));
    col *= 0.15 + beat * 0.85;
    fragColor = vec4(finalize(col, uv), 1.0);
}
