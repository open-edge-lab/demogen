// raymarch.glsl — marcia SDF. L'utente definisce `float map(vec3 p)`;
// la libreria chiama map() (GLSL ES 3.00 non ha function pointer).

/// @fn raymarch
/// Marchia da ro lungo rd fino a map() < eps o maxDist. Ritorna t, o -1 se nulla.
/// stepScale = 1.0 per SDF esatte; < 1 per deformazioni non-Lipschitz (twist).
/// Il numero di passi scala con uQuality (qSteps).
float raymarch(vec3 ro, vec3 rd, float maxDist, int maxSteps, float stepScale) {
    float t = 0.0;
    int n = qSteps(maxSteps);
    for (int i = 0; i < 256; i++) {
        if (i >= n) break;
        vec3 p = ro + rd * t;
        float d = map(p) * stepScale;
        if (d < 0.001 * max(1.0, t)) return t;
        t += d;
        if (t > maxDist) break;
    }
    return -1.0;
}

/// @fn calcNormal
/// normale via tecnica del tetraedro (4 sample di map()).
vec3 calcNormal(vec3 p) {
    const vec2 e = vec2(0.001, -0.001);
    return normalize(
        e.xyy * map(p + e.xyy) +
        e.yyx * map(p + e.yyx) +
        e.yxy * map(p + e.yxy) +
        e.xxx * map(p + e.xxx)
    );
}

/// @fn softShadow
/// soft shadow: ritorna 0..1 (1 = luce piena). passi scalati con uQuality.
float softShadow(vec3 ro, vec3 rd, float maxDist, float k) {
    float res = 1.0;
    float t = 0.01;
    int n = qSteps(32);
    for (int i = 0; i < 64; i++) {
        if (i >= n) break;
        float h = map(ro + rd * t);
        if (h < 0.001) return 0.0;
        res = min(res, k * h / t);
        t += clamp(h, 0.01, 0.5);
        if (t > maxDist) break;
    }
    return clamp(res, 0.0, 1.0);
}

/// @fn calcAO
/// AO approssimato (5 sample). passi scalati con uQuality.
float calcAO(vec3 p, vec3 n) {
    float occ = 0.0;
    float sca = 1.0;
    int steps = qSteps(5);
    for (int i = 0; i < 8; i++) {
        if (i >= steps) break;
        float h = 0.01 + 0.12 * float(i) / 4.0; // raggio max ~0.13 (con 0.12*i arrivava a 0.49)
        occ += (h - map(p + n * h)) * sca;
        sca *= 0.95;
    }
    return clamp(1.0 - 3.0 * occ, 0.0, 1.0);
}
