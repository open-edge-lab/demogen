// Penguin walk — pinguino pixel-art che cammina goffo da sinistra a destra,
// si ferma, salta gridando "HI!", poi torna indietro. Loop di 16 s (8 bar @ 120 BPM).
// Palette pastello, no flash, no flicker (gate epilettico verde).

float sdEllipse2(vec2 p, vec2 r) {
    return length(p / r) - 1.0;
}

float sdRoundBox2(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Pinguino in spazio locale (origine ai piedi). Ritorna vec4(colore, maschera).
vec4 penguin(vec2 q, float dir, float walkPhase, float jump) {
    q.x *= dir;                                   // specchia per camminare a sinistra
    q.y += jump;                                  // salto
    float moving = step(0.001, abs(dir));
    float rot = sin(walkPhase * 3.14159) * 0.13 * moving;   // waddle goffo
    float c = cos(rot), s = sin(rot);
    q = vec2(c * q.x + s * q.y, -s * q.x + c * q.y);
    q.y -= abs(cos(walkPhase * 3.14159)) * 2.0 * moving;    // bob

    vec3 ink = vec3(0.055, 0.078, 0.125);         // nero-blu
    vec3 col = vec3(0.0);
    float mask = 0.0;

    // zampe arancioni, sollevate alternativamente
    float liftR = max(0.0, sin(walkPhase * 3.14159)) * 3.0 * moving;
    float liftL = max(0.0, sin(walkPhase * 3.14159 + 3.14159)) * 3.0 * moving;
    float feet = min(sdRoundBox2(q - vec2(4.0, 2.0 + liftR), vec2(4.5, 2.2), 1.5),
                     sdRoundBox2(q - vec2(-4.0, 2.0 + liftL), vec2(4.5, 2.2), 1.5));
    float m = aaStep(0.0, -feet * 1.5);
    col = mix(col, vec3(1.0, 0.839, 0.647), m); mask = max(mask, m);

    // ali: oscillano camminando, alzate durante il salto
    float wing = mix(sin(walkPhase * 3.14159) * 0.30 * moving, 0.9, step(0.001, jump));
    float ca = cos(wing), sa = sin(wing);
    vec2 pr = vec2(ca * (q.x - 10.5) + sa * (q.y - 17.0), -sa * (q.x - 10.5) + ca * (q.y - 17.0));
    vec2 pl = vec2(ca * (q.x + 10.5) - sa * (q.y - 17.0), sa * (q.x + 10.5) + ca * (q.y - 17.0));
    float wings = min(sdEllipse2(pr, vec2(3.0, 8.5)), sdEllipse2(pl, vec2(3.0, 8.5)));
    m = aaStep(0.0, -wings * 1.5);
    col = mix(col, ink, m); mask = max(mask, m);

    // corpo + testa
    float body = sdEllipse2(q - vec2(0.0, 15.0), vec2(10.5, 13.5));
    float head = length(q - vec2(0.0, 30.5)) - 8.5;
    float bt = smin(body, head, 3.0);
    m = aaStep(0.0, -bt * 1.5);
    col = mix(col, ink, m); mask = max(mask, m);

    // pancia bianca
    float belly = sdEllipse2(q - vec2(0.0, 14.5), vec2(6.8, 9.5));
    m = aaStep(0.0, -belly * 1.5) * mask;
    col = mix(col, vec3(0.96, 0.98, 1.0), m);

    // occhi bianchi + pupille
    float eyes = min(length(q - vec2(3.2, 31.5)) - 1.9, length(q - vec2(-3.2, 31.5)) - 1.9);
    m = aaStep(0.0, -eyes * 1.5) * mask;
    col = mix(col, vec3(1.0), m);
    float pup = min(length(q - vec2(3.2, 32.1)) - 0.85, length(q - vec2(-3.2, 32.1)) - 0.85);
    m = aaStep(0.0, -pup * 1.5) * mask;
    col = mix(col, vec3(0.05, 0.08, 0.12), m);

    // becco a rombo arancione
    vec2 bp = vec2(abs(q.x), q.y - 28.0);
    float beak = sdRoundBox2(bp, vec2(3.2, 1.8), 0.8);
    m = aaStep(0.0, -beak * 1.5) * mask;
    col = mix(col, vec3(1.0, 0.839, 0.647), m);

    return vec4(col, mask);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord;
    float W = res.x, H = res.y;
    float groundY = 34.0;

    // ---- timeline loop 16 s: 0-40% ida, 40-55% "fa qualcosa", 55-100% ritorno
    float period = 16.0;
    float p = loopT(iTime, period); // già normalizzato in [0,1)
    float x, dir, jump = 0.0, hi = 0.0;
    if (p < 0.40) {
        float k = smoothstep(0.0, 1.0, p / 0.40);
        x = mix(-30.0, W * 0.72, k);
        dir = 1.0;
    } else if (p < 0.55) {
        x = W * 0.72;
        dir = 0.0;
        float jp = (p - 0.40) / 0.15;                       // 3 salti
        jump = sin(fract(jp * 3.0) * 3.14159) * 14.0;        // parabola di ogni salto
        hi = smoothstep(0.05, 0.2, jp) * (1.0 - smoothstep(0.85, 1.0, jp));
    } else {
        float k = smoothstep(0.0, 1.0, (p - 0.55) / 0.45);
        x = mix(W * 0.72, -30.0, k);
        dir = -1.0;
    }
    float walkPhase = max(x + 30.0, 0.0) * 0.12; // passi proporzionati allo spostamento

    // ---- sfondo pastello: cielo, sole, nuvole, neve
    vec3 col = mix(vec3(0.635, 0.824, 1.0), vec3(0.878, 0.984, 0.988), clamp(px.y / H, 0.0, 1.0));
    float sun = length(px - vec2(W - 52.0, H - 42.0)) - 13.0;
    col = mix(col, vec3(0.992, 1.0, 0.714), aaStep(0.0, -sun * 1.5));
    col += vec3(0.992, 1.0, 0.714) * 0.10 * aaStep(6.0, -sun * 1.5); // alone morbido
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float cx = mod(iTime * (2.0 + fi) + fi * 130.0, W + 90.0) - 45.0;
        float cy = H - 34.0 - fi * 22.0;
        float cl = sdEllipse2(px - vec2(cx, cy), vec2(16.0, 6.0));
        cl = min(cl, sdEllipse2(px - vec2(cx + 12.0, cy - 4.0), vec2(10.0, 5.0)));
        col = mix(col, vec3(1.0), aaStep(0.0, -cl * 1.5) * 0.9);
    }
    float ground = aaStep(0.0, -(groundY - px.y) * 1.5);
    col = mix(col, vec3(0.93, 0.96, 0.99), ground); // neve

    // ---- pinguino + ombra
    vec2 pos = vec2(x, groundY);
    float shScale = 1.0 - clamp(jump / 16.0, 0.0, 1.0) * 0.5;
    float sh = sdEllipse2(vec2(px.x - pos.x, px.y - (groundY + 2.0)), vec2(12.0, 3.0) * vec2(shScale, 1.0));
    col = mix(col, vec3(0.55, 0.65, 0.75), aaStep(0.0, -sh * 1.5) * 0.30 * ground);
    vec4 pg = penguin(px - pos, dir, walkPhase, jump);
    col = mix(col, pg.rgb, pg.a);

    // "HI!" sopra la testa durante i salti
    float hiMask = drawText(px, pos + vec2(-9.0, 46.0 + jump), 1.0);
    col = mix(col, vec3(0.239, 0.353, 0.502), hiMask * hi);

    // scroller in basso, lento e morbido
    float speed = 24.0;
    float textW = float(uTextLen) * 8.0;
    float x0 = W + 8.0 - mod(iTime * speed, textW + W + 16.0);
    float cov = drawText(px, vec2(x0, 8.0), 1.0);
    col = mix(col, vec3(0.239, 0.353, 0.502), cov * 0.85);

    fragColor = vec4(finalize(col, px / res), 1.0);
}
