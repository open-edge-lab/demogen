"""Esempio "whisker hunt" (examples/whisker_hunt.timeline.json): gatto e falena restano nell'inquadratura.

Nella caccia il gatto arancione salta ad arco e la falena vola via verso l'alto: il controllo copre
tutti i fotogrammi di idle e caccia e vuole solo sfondo nelle righe più in alto.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.bundle.build import build_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_gatto_e_falena_restano_nell_inquadratura(harness) -> None:
    spec = json.loads((EXAMPLES / "whisker_hunt.timeline.json").read_text(encoding="utf-8"))
    res = harness.load(build_payload(spec, EXAMPLES, do_minify=True))
    assert res["ok"], "\n".join(res["errors"])[:1500]
    times = [round(1.9 + 0.1 * i, 2) for i in range(56)]  # idle e caccia: 1,875..7,5 s
    for t, png in zip(times, harness.capture(times, 320, 180), strict=True):
        rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float32) / 255
        top = rgb[:10].mean(axis=-1)  # le 10 righe più in alto: solo sfondo verde acqua
        assert top.min() > 0.1, f"t={t}: gatto o falena nel bordo alto (luma {top.min():.3f})"
