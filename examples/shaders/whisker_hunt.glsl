// whisker hunt, scena 3 "caccia": il gatto arancione (quello della dissolvenza, stessa misura) vede la
// falena, si acquatta scodinzolando e dimenando il sedere, salta a sinistra ad arco, atterra, si rimette
// composto e guarda in alto la falena che vola via. Comincia dall'ultimo fotogramma di "idle" e finisce
// seduto a x = 160 nella posa con cui comincia la dissolvenza, così né il taglio né la dissolvenza
// incrociata saltano. Gatto, falena e sfondo sono in whisker_common.glsl; tutto a scatti a 12 fps.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 px = fragCoord.xy;
    int f = int(floor(uSceneTime * 12.0)); // 0..44: 2 battute a 128 BPM = 3,75 s

    // posa del fotogramma
    int k = 0;
    int tb = 1;
    int hip = 0;
    int flags = 0;
    ivec2 look = ivec2(-1, 0); // la falena è a sinistra
    float ox = 240.0;
    float oy = WH_FLOOR;
    const int WAG[4] = int[4](0, 2, 3, 1); // scodinzolo: base della coda a ogni fotogramma
    if (f < 6) {                 // seduto: guarda la falena, l'orecchio scatta
        if (f >= 3) flags |= OC_EAR;
    } else if (f < 8) {          // si abbassa
        k = 1;
    } else if (f < 24) {         // a terra: scodinzola, poi dimena il sedere prima del balzo
        k = 2;
        tb = WAG[f % 4];
        if (f >= 16) hip = ((f / 2) % 2 == 0) ? -1 : 1;
    } else if (f < 30) {         // balzo a sinistra ad arco, zampe sospese
        float s = float(f - 23) / 7.0;
        k = 2;
        tb = 3;
        flags |= OC_AIR;
        ox = floor(mix(240.0, 160.0, s));
        oy = WH_FLOOR + floor(24.0 * sin(3.14159265 * s));
    } else if (f < 32) {         // atterra acquattato dove c'era la falena
        k = 2;
        ox = 160.0;
        tb = 0;
        look = ivec2(-1, 1);
    } else if (f < 34) {         // si rialza
        k = 1;
        ox = 160.0;
        look = ivec2(-1, 1);
    } else if (f < 41) {         // composto: segue con gli occhi la falena che vola via
        ox = 160.0;
        look = ivec2(-1, 1);
        tb = 1 + int(round(sin(float(f - 34) * 0.9)));
    } else {                     // la posa con cui comincia la dissolvenza
        ox = 160.0;
        look = ivec2(0);
    }
    int idx = orangeCatPixel(px, vec2(ox, oy), k, tb, hip, look, flags);

    // falena: svolazza bassa davanti al gatto; appena lui salta scappa in alto a sinistra e resta a
    // svolazzare in alto mentre lui la guarda
    float mf = float(f);
    vec2 moth = vec2(152.0 + floor(4.0 * sin(mf * 0.9)), 50.0 + floor(5.0 * sin(mf * 0.55)));
    if (f >= 26) {
        float a = float(min(f, 31) - 25);
        float b = float(max(f - 31, 0));
        moth += vec2(-8.0 * a - 1.0 * b, 9.0 * a + 4.0 * b);
    }
    if (mothAt(px, moth, f % 2 == 0)) idx = 2;

    fragColor = vec4(whiskerFinalize(floorBackground(px, res), idx, fragCoord, res), 1.0);
}
