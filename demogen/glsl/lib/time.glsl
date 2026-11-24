// time.glsl — avvolgimento del tempo per evitare perdita di precisione fp32
// su durate lunghe: porta t dentro [0, period) prima di usarlo in funzioni
// periodiche ad alta frequenza.

/// @fn wrapTime
/// t modulo period (precisione fp32 preservata).
float wrapTime(float t, float period) {
    return t - period * floor(t / period);
}

/// @fn loopT
/// t in [0,1) dentro un loop di periodo T secondi.
float loopT(float t, float period) {
    return wrapTime(t, period) / period;
}
