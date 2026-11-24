// domain.glsl — deformazioni del dominio 3D/2D.

/// @fn rep
/// ripetizione limitata di p in celle di size (per asse con mask>0).
vec3 rep(vec3 p, vec3 size) {
    return p - size * floor(p / size + 0.5);
}

/// @fn mirror
/// specchio sull'origine: |p| per asse.
vec3 mirror(vec3 p) { return abs(p); }

/// @fn polar
/// ripetizione polare 2D: n settori angolari.
vec2 polar(vec2 p, float n) {
    float a = atan(p.y, p.x);
    float r = length(p);
    a = mod(a + 3.14159265, 6.28318530 / n) - 3.14159265 / n;
    return vec2(cos(a), sin(a)) * r;
}

/// @fn twist
/// twist attorno a Y. NON 1-Lipschitz: scala lo step del raymarch di conseguenza.
vec3 twist(vec3 p, float k) {
    float c = cos(k * p.y);
    float s = sin(k * p.y);
    mat2 m = mat2(c, -s, s, c);
    return vec3(m * p.xz, p.y);
}
