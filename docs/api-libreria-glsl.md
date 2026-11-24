# Libreria GLSL demogen (GLSL ES 3.00)

## `aa.glsl`

### `aaStep`

smoothstep filtrato: bordo morbido di un pixel.

```glsl
float aaStep(float edge, float x) {
```

### `aaSmoothstep`

smoothstep con bordi filtrati.

```glsl
float aaSmoothstep(float e0, float e1, float x) {
```

## `camera.glsl`

### `lookAt`

matrice 3x3 con base ortonormale: z = direzione forward.

```glsl
mat3 lookAt(vec3 eye, vec3 target, float roll) {
```

### `rayDir`

raggio dalla camera: uv in [-1,1] (aspect-corretti), fov in radianti.
uJitter è 0 in realtime (solo export offline).

```glsl
vec3 rayDir(vec2 uv, vec3 ro, mat3 basis, float fov) {
```

## `domain.glsl`

### `rep`

ripetizione limitata di p in celle di size (per asse con mask>0).

```glsl
vec3 rep(vec3 p, vec3 size) {
```

### `mirror`

specchio sull'origine: |p| per asse.

```glsl
vec3 mirror(vec3 p) { return abs(p); }
```

### `polar`

ripetizione polare 2D: n settori angolari.

```glsl
vec2 polar(vec2 p, float n) {
```

### `twist`

twist attorno a Y. NON 1-Lipschitz: scala lo step del raymarch di conseguenza.

```glsl
vec3 twist(vec3 p, float k) {
```

## `easing.glsl`

### `easeOutCubic`

```glsl
float easeOutCubic(float x) {
```

### `beatPulse`

impulso sul beat: 1 all'inizio del beat, decade esponenzialmente.
phase = uBeatPhase, k = decadimento.

```glsl
float beatPulse(float phase, float k) {
```

### `beatFlash`

flash sul beat che rispetta uFlashLimit (fotosensibilità):
ampiezza scalata da uFlashLimit, mai a tutto schermo.

```glsl
float beatFlash(float phase, float k) {
```

## `hash.glsl`

### `hash11`

hash 1→1 in [0,1) da un float (via bit pattern).

```glsl
float hash11(float p) {
```

### `hash21`

hash 2D→1 in [0,1).

```glsl
float hash21(vec2 p) {
```

### `hash31`

hash 3D→1 in [0,1).

```glsl
float hash31(vec3 p) {
```

## `noise.glsl`

### `vnoise`

value noise 2D in [-1,1].

```glsl
float vnoise(vec2 p) {
```

### `gnoise`

gradient noise 2D in [-1,1].

```glsl
float gnoise(vec2 p) {
```

### `fbm`

fractal Brownian motion 2D in [-1,1]; ottave scalate da uQuality (qOctaves).

```glsl
float fbm(vec2 p) {
```

### `ridged`

ridged multifractal 2D in [0,1]-ish.

```glsl
float ridged(vec2 p) {
```

## `palette.glsl`

### `cosPalette`

palette coseno: t in [0,1] → colore.

```glsl
vec3 cosPalette(float t, vec3 a, vec3 b, vec3 c, vec3 d) {
```

## `post.glsl`

### `aces`

tonemap approssimazione ACES (Narkowicz).

```glsl
vec3 aces(vec3 x) {
```

### `toSRGB`

lineare → sRGB.

```glsl
vec3 toSRGB(vec3 c) {
```

### `vignette`

```glsl
vec3 vignette(vec3 c, vec2 uv, float strength) {
```

### `grain`

grana deterministica da iTime (no texture).

```glsl
vec3 grain(vec3 c, vec2 fragCoord, float amount) {
```

## `quality.glsl`

### `qSteps`

numero di passi di un ciclo: maxSteps a uQuality=1, metà a uQuality=0.

```glsl
int qSteps(int maxSteps) {
```

### `qOctaves`

numero di ottave di noise: maxOct a uQuality=1, metà a uQuality=0.

```glsl
int qOctaves(int maxOct) {
```

### `qEnable`

true solo se uQuality >= soglia (feature costose spente a bassa qualità).

```glsl
bool qEnable(float threshold) {
```

## `raymarch.glsl`

### `raymarch`

Marchia da ro lungo rd fino a map() < eps o maxDist. Ritorna t, o -1 se nulla.
stepScale = 1.0 per SDF esatte; < 1 per deformazioni non-Lipschitz (twist).
Il numero di passi scala con uQuality (qSteps).

```glsl
float raymarch(vec3 ro, vec3 rd, float maxDist, int maxSteps, float stepScale) {
```

### `calcNormal`

normale via tecnica del tetraedro (4 sample di map()).

```glsl
vec3 calcNormal(vec3 p) {
```

### `softShadow`

soft shadow: ritorna 0..1 (1 = luce piena). passi scalati con uQuality.

```glsl
float softShadow(vec3 ro, vec3 rd, float maxDist, float k) {
```

### `calcAO`

AO approssimato (5 sample). passi scalati con uQuality.

```glsl
float calcAO(vec3 p, vec3 n) {
```

## `retro\effects.glsl`

### `plasma2`

plasma 2D classico in [-1,1].

```glsl
float plasma2(vec2 uv, float t) {
```

### `starfield`

starfield 2D: hash della cella → posizione e luminosità della stella.

```glsl
vec3 starfield(vec2 uv, float t, float speed) {
```

### `copperBar`

barra rame/raster verticale che oscilla col beat.

```glsl
float copperBar(vec2 uv, float phase, float k) {
```

## `retro\font.glsl`

### `fontGlyph`

ritorna i 64 bit del glifo 8x8: riga 0 = byte alto di .x, bit 7 = colonna 0.

```glsl
uvec2 fontGlyph(int code) {
```

### `textChar`

carattere i-esimo del testo da uText (ASCII, 0 se oltre uTextLen).

```glsl
int textChar(int i) {
```

### `drawText`

copertura 0..1 del testo (da uText) disegnato in coordinate pixel:
origin = angolo alto-sx del primo glifo, scale = dimensione glifo (8*scale px).
Ritorna 1 dove il testo copre il pixel.

```glsl
float drawText(vec2 fragPx, vec2 origin, float scale) {
```

## `retro\palette.glsl`

### `bayer4`

matrice Bayer 4x4 in [0,1) dalla posizione pixel.

```glsl
float bayer4(vec2 px) {
```

### `retroQuantize`

colore più vicino nella palette (distanza RGB) + dithering Bayer 4x4.

```glsl
vec3 retroQuantize(vec3 col, const vec3 pal[16], int n, vec2 px) {
```

### `retroFinalize`

output finale per scena retro: quantizza col nella palette data e applica
vignetta leggera. Chiamare alla fine di mainImage in profilo retro.

```glsl
vec3 retroFinalize(vec3 col, vec2 uv, vec2 fragCoord, const vec3 pal[16], int n) {
```

## `retro\pixel.glsl`

### `pixUV`

uv normalizzato [0,1] allineato ai pixel della risoluzione interna.

```glsl
vec2 pixUV(vec2 fragCoord, vec2 res) {
```

### `scanline`

scanline CRT leggero: 1 sulle righe pari (usa solo se non in modalità eco).

```glsl
float scanline(vec2 fragCoord, float strength) {
```

## `sdf.glsl`

### `sdSphere`

```glsl
float sdSphere(vec3 p, float r) { return length(p) - r; }
```

### `sdBox`

```glsl
float sdBox(vec3 p, vec3 b) {
```

### `sdRoundBox`

```glsl
float sdRoundBox(vec3 p, vec3 b, float r) { return sdBox(p, b - r) - r; }
```

### `sdTorus`

```glsl
float sdTorus(vec3 p, vec2 t) {
```

### `sdCapsule`

```glsl
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
```

### `sdPlane`

```glsl
float sdPlane(vec3 p, vec3 n, float d) { return dot(p, n) + d; }
```

### `smin`

smooth min polinomiale (k = raggio di blend).

```glsl
float smin(float a, float b, float k) {
```

### `smax`

```glsl
float smax(float a, float b, float k) { return -smin(-a, -b, k); }
```

## `time.glsl`

### `wrapTime`

t modulo period (precisione fp32 preservata).

```glsl
float wrapTime(float t, float period) {
```

### `loopT`

t in [0,1) dentro un loop di periodo T secondi.

```glsl
float loopT(float t, float period) {
```
