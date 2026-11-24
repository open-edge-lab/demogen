// sdf.glsl — primitive SDF 3D (Lipschitz ≈ 1) e operatori booleani.
// Convenzioni: `/// @fn`, niente stato globale. Le SDF esatte permettono
// raymarch con stepScale = 1.0.

/// @fn sdSphere
float sdSphere(vec3 p, float r) { return length(p) - r; }

/// @fn sdBox
float sdBox(vec3 p, vec3 b) {
    vec3 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}

/// @fn sdRoundBox
float sdRoundBox(vec3 p, vec3 b, float r) { return sdBox(p, b - r) - r; }

/// @fn sdTorus
float sdTorus(vec3 p, vec2 t) {
    vec2 q = vec2(length(p.xz) - t.x, p.y);
    return length(q) - t.y;
}

/// @fn sdCapsule
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
    vec3 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}

/// @fn sdPlane
float sdPlane(vec3 p, vec3 n, float d) { return dot(p, n) + d; }

/// @fn smin
/// smooth min polinomiale (k = raggio di blend).
float smin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return mix(b, a, h) - k * h * (1.0 - h);
}

/// @fn smax
float smax(float a, float b, float k) { return -smin(-a, -b, k); }
