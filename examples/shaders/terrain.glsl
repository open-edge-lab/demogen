// s3 — terreno fbm con nebbia e camera che avanza, profilo modern.
float map(vec3 p) {
    return p.y - fbm(p.xz * 0.35 + vec2(0.0, iTime * 0.15)) * 2.0 - 0.5;
}

// Raymarch del campo d'altezza. map() non è 1-Lipschitz (pendenze fino a ~1.8): con il raymarch
// della libreria a passo 0.9 il raggio saltava sotto la superficie e il "colpo" restava dentro la
// roccia, dove AO e ombra valgono 0 (macchie nere a strisce). Qui il passo è con segno, quindi sotto
// la superficie si torna indietro; finiti i passi sotto maxDist il raggio è radente al suolo e conta
// come colpito.
float marchTerrain(vec3 ro, vec3 rd, float maxDist, int maxSteps) {
    float t = 0.0;
    int n = qSteps(maxSteps);
    for (int i = 0; i < 256; i++) {
        if (i >= n) break;
        float d = map(ro + rd * t);
        if (abs(d) < 0.001 * max(1.0, t)) return t;
        t += d * 0.5;
        if (t > maxDist) return -1.0;
    }
    return t;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    vec3 ro = vec3(0.0, 2.5, -iTime * 2.0);
    mat3 basis = lookAt(ro, ro + vec3(0.0, -0.15, 1.0), 0.0);
    vec3 rd = rayDir(uv, ro, basis, 1.1);
    float d = marchTerrain(ro, rd, 60.0, 128);
    vec3 col = vec3(0.02, 0.03, 0.08);
    if (d > 0.0) {
        vec3 p = ro + rd * d;
        vec3 n = calcNormal(p);
        float ao = calcAO(p, n);
        float sh = softShadow(p + n * 0.05, normalize(vec3(0.4, 0.9, 0.2)), 20.0, 6.0);
        float h = clamp(fbm(p.xz * 0.35 + vec2(0.0, iTime * 0.15)) * 0.5 + 0.5, 0.0, 1.0);
        vec3 base = cosPalette(h + uBeatPhase * 0.1, vec3(0.5), vec3(0.5), vec3(1.0),
                               vec3(0.0, 0.1, 0.2));
        col = base * (0.25 + 0.75 * sh) * ao;
        float fog = 1.0 - exp(-d * 0.03);
        col = mix(col, vec3(0.02, 0.03, 0.08), fog);
    }
    fragColor = vec4(finalize(col, uv), 1.0);
}
