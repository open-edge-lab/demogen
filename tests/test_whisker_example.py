"""Esempio "whisker hunt" (examples/whisker_hunt.timeline.json): il gattone resta nell'inquadratura.

Nella demo generata da cui viene ("Whisker Idle") il gattone aveva celle di 8 pixel con i piedi a
y = 112 e testa e orecchie uscivano dal bordo alto; nella caccia salta, quindi il controllo copre
tutte le pose di idle e caccia.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.bundle.build import build_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_il_gattone_non_esce_dall_inquadratura(harness) -> None:
    spec = json.loads((EXAMPLES / "whisker_hunt.timeline.json").read_text(encoding="utf-8"))
    res = harness.load(build_payload(spec, EXAMPLES, do_minify=True))
    assert res["ok"], "\n".join(res["errors"])[:1500]
    times = [round(1.9 + 0.1 * i, 2) for i in range(56)]  # idle e caccia: 1,875..7,5 s
    for t, png in zip(times, harness.capture(times, 320, 180), strict=True):
        rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float32) / 255
        top = rgb[:10].mean(axis=-1)  # le 10 righe più in alto: solo sfondo verde acqua
        assert top.min() > 0.1, f"t={t}: contorno del gatto nel bordo alto (luma {top.min():.3f})"
