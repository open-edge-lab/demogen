// Scena di riferimento per il gate di perf relativo (critic/perf_ref.py).
// Rappresenta una scena "tipica" che gira fluida: raymarching a 96 passi, normali,
// soft shadow, nebbia (come il tunnel degli esempi). Il costo di una scena generata
// si misura in multipli di questa, sullo stesso renderer e alla stessa risoluzione:
// così il confronto vale anche su SwiftShader, dove i ms assoluti non dicono nulla.
// NON modificarla senza ritarare realtime.max_ref_ratio_* (i rapporti cambierebbero).
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
        vec3 base = cosPalette(p.y * 0.1, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.0, 0.33, 0.67));
        col = base * (0.3 + 0.7 * sh);
        col = mix(col, vec3(0.02, 0.0, 0.05), 1.0 - exp(-d * 0.08));
    }
    fragColor = vec4(pow(clamp(col, 0.0, 1.0), vec3(0.4545)), 1.0);
}
