// whisker hunt, scena 2 "idle": il gattone di "Whisker Idle", ora intero nell'inquadratura.
// Nell'originale le celle erano di 8 pixel con i piedi a y = 112: testa e orecchie (19 celle in
// tutto) uscivano dal bordo alto. Qui celle di 7 pixel e piedi sul pavimento in basso (133 px di
// gatto, 19 px di margine). Colori, sfondo e animazione restano quelli originali; blink e guizzo
// dell'orecchio cadono dentro la scena (nell'originale erano oltre la sua fine) e l'ultimo
// fotogramma è la posa da cui parte la caccia.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord.xy;

    // orologio dello sprite: tutto a scatti a 12 fps, mai sotto il pixel
    int ft = int(floor(uSceneTime * 12.0)); // 0..22
    bool blink = ft >= 8 && ft <= 9;
    bool twitch = ft >= 14 && ft <= 17;
    // coda: seno quantizzato, un giro nella scena (parte e finisce a 0, come la caccia)
    int tail = int(round(2.0 * sin(float(ft) * 6.2831853 / 22.5)));

    ivec2 g = ivec2(floor((px - vec2(160.0, BC_FLOOR)) / BC_CELL));
    int flags = (twitch ? BC_EAR : 0) | (blink ? BC_BLINK : 0);
    int id = bigCatId(g, 0, tail, 0, ivec2(0), 0, flags);

    vec3 col = bigCatColor(id, bigCatBackground(px, res));
    fragColor = vec4(finalize(col, px / res), 1.0);
}
