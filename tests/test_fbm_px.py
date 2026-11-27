"""fbmPx (noise.glsl): le ottave arrivano fino al pixel, quindi a risoluzione più alta c'è più dettaglio.

La pendenza media misurata in unità di p è una proprietà della funzione: per fbm (ottave fisse) non
cambia con la risoluzione, per fbmPx cresce perché a ogni raddoppio della risoluzione entra un'ottava.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from demogen.engine import payload_from_file

SHADER = """
float NOISE_AT(vec2 p, float px) { return NOISE_CALL; }

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    const float S = 4.0;
    float px = S / iResolution.y;                  // unità di p per pixel
    vec2 p = fragCoord / iResolution.y * S;
    // passo fisso e più corto di ogni onda: la derivata è la stessa a ogni risoluzione (con mezzo pixel
    // a 160x90 il passo filtrava le ottave alte)
    vec2 e = vec2(0.0005, 0.0);
    float slope = abs(NOISE_AT(p + e, px) - NOISE_AT(p - e, px)) / (2.0 * e.x);   // pendenza in unità di p
    fragColor = vec4(vec3(clamp(slope / 8.0, 0.0, 1.0)), 1.0);
}
"""
CALLS = {"fbm": "fbm(p)", "fbmPx": "fbmPx(p, px)"}


def _mean_slope(harness, tmp_path, noise: str, w: int, h: int) -> float:
    # due livelli sotto tmp_path: lontano dai common.glsl che altri test lasciano nella base temporanea
    src = tmp_path / noise / "src" / "slope.glsl"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(SHADER.replace("NOISE_CALL", CALLS[noise]), encoding="utf-8")
    res = harness.load(payload_from_file(src))
    assert res["ok"], "\n".join(res["errors"])[:1500]
    png = harness.capture([1.0], w, h)[0]
    return float(np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=float).mean())


def test_detail_grows_with_resolution_only_for_fbm_px(harness, tmp_path) -> None:
    # 8× la risoluzione: tre ottave in più per fbmPx (le pendenze di ottave indipendenti si sommano in
    # quadratura: rapporto atteso ~√(6.3/3.3) ≈ 1.4), nessuna per fbm
    fixed = _mean_slope(harness, tmp_path, "fbm", 1280, 720) / _mean_slope(harness, tmp_path, "fbm", 160, 90)
    px = _mean_slope(harness, tmp_path, "fbmPx", 1280, 720) / _mean_slope(harness, tmp_path, "fbmPx", 160, 90)
    print(f"slope ratio 1280/160: fbm {fixed:.3f}, fbmPx {px:.3f}")
    assert 0.95 < fixed < 1.05, f"fbm: same function at any resolution, slope ratio {fixed:.2f}"
    assert px > 1.25, f"fbmPx: three more octaves at 8x the resolution, slope ratio only {px:.2f}"
