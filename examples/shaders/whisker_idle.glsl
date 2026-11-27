// whisker hunt, scena 2 "idle": il gatto arancione (quello della dissolvenza, stessa misura) seduto a
// destra, dove comincia la caccia: sbatte gli occhi, muove la coda e un orecchio; nella seconda metà
// entra da sinistra la falena e lui si gira a guardarla. L'ultimo fotogramma è il primo della caccia,
// così il taglio non salta. Gatto, falena e sfondo sono in whisker_common.glsl; tutto a scatti a 12 fps.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord.xy;
    int ft = int(floor(uSceneTime * 12.0)); // 0..22: 1 battuta a 128 BPM = 1,875 s

    int flags = 0;
    if (ft == 8 || ft == 9) flags |= OC_BLINK;
    if (ft == 14 || ft == 15) flags |= OC_EAR;
    // coda: sale fino a 2 celle e torna giù, partendo e finendo a 1 come la caccia
    int tb = 1 + int(round(2.0 * (0.5 - 0.5 * cos(float(ft) * 6.2831853 / 22.5))));
    ivec2 look = ft >= 19 ? ivec2(-1, 0) : ivec2(0); // si gira verso la falena
    int idx = orangeCatPixel(px, vec2(240.0, WH_FLOOR), 0, tb, 0, look, flags);

    // falena: entra da sinistra e arriva dove la trova la caccia, (152, 50)
    if (ft >= 12) {
        vec2 moth = vec2(152.0 - 16.0 * float(22 - ft), 50.0 + floor(5.0 * sin(float(ft - 22) * 0.55)));
        if (mothAt(px, moth, ft % 2 == 0)) idx = 2;
    }

    fragColor = vec4(whiskerFinalize(floorBackground(px, res), idx, fragCoord, res), 1.0);
}
