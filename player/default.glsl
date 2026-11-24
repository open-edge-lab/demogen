// Shader di default dello spike: plasma coseno (contratto mainImage).
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime;
    vec2 p = uv * 3.0;
    float v = sin(p.x + t)
            + sin(p.y + t * 1.3)
            + sin((p.x + p.y) * 0.7 + t * 0.6)
            + sin(length(p) * 2.0 - t);
    vec3 col = 0.5 + 0.5 * cos(t + v * 0.5 + vec3(0.0, 0.33, 0.67));
    fragColor = vec4(col, 1.0);
}
