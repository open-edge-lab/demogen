// quality.glsl — helper che scalano il costo con uQuality (0..1, 1 = piena).

/// @fn qSteps
/// numero di passi di un ciclo: maxSteps a uQuality=1, metà a uQuality=0.
int qSteps(int maxSteps) {
    return int(float(maxSteps) * mix(0.5, 1.0, uQuality) + 0.5);
}

/// @fn qOctaves
/// numero di ottave di noise: maxOct a uQuality=1, metà a uQuality=0.
int qOctaves(int maxOct) {
    return int(float(maxOct) * mix(0.5, 1.0, uQuality) + 0.5);
}

/// @fn qEnable
/// true solo se uQuality >= soglia (feature costose spente a bassa qualità).
bool qEnable(float threshold) {
    return uQuality >= threshold;
}
