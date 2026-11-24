// s1 — tunnel al neon che respira col beat (raymarching, profilo modern).
float map(vec3 p) {
    vec2 q = p.xz;
    float r = length(q);
    float d = r - 2.5;
    d += 0.25 * sin(p.y * 4.0 + iTime * 2.0) * sin(atan(q.y, q.x) * 6.0 + iTime);
    return d * 0.7;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    vec3 ro = vec3(0.0, 0.0, -iTime * 4.0);
    mat3 basis = lookAt(ro, ro + vec3(0.0, 0.0, 1.0), 0.0);
    vec3 rd = rayDir(uv, ro, basis, 1.2);
    float d = raymarch(ro, rd, 30.0, 96, 0.7);
    vec3 col = vec3(0.0);
    if (d > 0.0) {
        vec3 p = ro + rd * d;
        vec3 n = calcNormal(p);
        float sh = softShadow(p + n * 0.02, normalize(vec3(0.5, 0.8, 0.3)), 5.0, 8.0);
        float beat = beatPulse(uBeatPhase, 6.0);
        vec3 base = cosPalette(p.y * 0.1 + uBar * 0.05, vec3(0.5), vec3(0.5), vec3(1.0),
                               vec3(0.0, 0.33, 0.67));
        col = base * (0.3 + 0.7 * sh) * (0.6 + 0.6 * beat);
        col += vec3(0.2, 0.9, 1.0) * beat * 0.3 * sh;
        float fog = 1.0 - exp(-d * 0.08);
        col = mix(col, vec3(0.02, 0.0, 0.05), fog);
    }
    fragColor = vec4(finalize(col, uv), 1.0);
}
