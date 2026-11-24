// camera.glsl — camera orbit e raggio da fragCoord.

/// @fn lookAt
/// matrice 3x3 con base ortonormale: z = direzione forward.
mat3 lookAt(vec3 eye, vec3 target, float roll) {
    vec3 z = normalize(target - eye);
    vec3 x = normalize(cross(vec3(0.0, 1.0, 0.0), z));
    vec3 y = cross(z, x);
    if (length(x) < 0.001) x = vec3(1.0, 0.0, 0.0);
    float cr = cos(roll), sr = sin(roll);
    vec3 xr = x * cr + y * sr;
    vec3 yr = y * cr - x * sr;
    return mat3(xr, yr, z);
}

/// @fn rayDir
/// raggio dalla camera: uv in [-1,1] (aspect-corretti), fov in radianti.
/// uJitter è 0 in realtime (solo export offline).
vec3 rayDir(vec2 uv, vec3 ro, mat3 basis, float fov) {
    vec3 rd = normalize(basis * vec3(uv, 1.0 / tan(fov * 0.5)));
    return rd;
}
