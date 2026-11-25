// hash.glsl — hash interi deterministici (niente fract(sin(...))).
// Nota: le costanti sono < 2^31 perché ANGLE/SwiftShader fallisce sugli hex > 2^31-1.
// Convenzioni: ogni funzione è preceduta da `/// @fn <nome>` (docs.py + treeshake.py).

/// @fn hash11
/// hash 1→1 in [0,1) da un float (via bit pattern).
float hash11(float p) {
    uint x = floatBitsToUint(p);
    x = ((x >> 16u) ^ x) * 2146503469u;
    x = ((x >> 16u) ^ x) * 2146503469u;
    x = (x >> 16u) ^ x;
    return float(x >> 8u) * (1.0 / 16777216.0); // 24 bit: float esatto, sempre < 1.0
}

/// @fn hash21
/// hash 2D→1 in [0,1).
float hash21(vec2 p) {
    uint h = floatBitsToUint(p.x) * 2146503469u ^ floatBitsToUint(p.y) * 1804288421u;
    h = ((h >> 16u) ^ h) * 1103515245u;
    h = (h >> 15u) ^ h;
    return float(h >> 8u) * (1.0 / 16777216.0); // 24 bit: float esatto, sempre < 1.0
}

/// @fn hash31
/// hash 3D→1 in [0,1).
float hash31(vec3 p) {
    uint h = floatBitsToUint(p.x) * 2146503469u
           ^ floatBitsToUint(p.y) * 1804288421u
           ^ floatBitsToUint(p.z) * 1103515245u;
    h = ((h >> 16u) ^ h) * 2146503469u;
    h = (h >> 13u) ^ h;
    return float(h >> 8u) * (1.0 / 16777216.0); // 24 bit: float esatto, sempre < 1.0
}
