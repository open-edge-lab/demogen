"""Esempio "penguin walk" (examples/penguin.timeline.json): da fermo il pinguino resta un pinguino.

Nella sosta in cui salta e grida "HI!" (dir = 0) penguin() faceva q.x *= dir: con x azzerata il
profilo al centro del pinguino si allargava a tutto lo schermo in strisce orizzontali che saltavano
con lui (gate flash: 9 flash/s fra 6 e 9 s). Il controllo guarda la parte di cielo a sinistra del
pinguino durante la sosta e il gate flash sulla finestra dei salti.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.bundle.build import build_payload
from demogen.critic.flash import analyze_flash

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_da_fermo_resta_un_pinguino_e_i_salti_non_lampeggiano(harness) -> None:
    spec = json.loads((EXAMPLES / "penguin.timeline.json").read_text(encoding="utf-8"))
    res = harness.load(build_payload(spec, EXAMPLES, do_minify=True))
    assert res["ok"], "\n".join(res["errors"])[:1500]

    times = [6.6, 7.0, 7.5, 8.0, 8.5]  # la sosta va da 6,4 a 8,8 s, il pinguino è a x = 0,72 W
    for t, png in zip(times, harness.capture(times, 320, 180), strict=True):
        rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64) / 255
        luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
        left = luma[:150, :120]  # cielo e neve a sinistra del pinguino, sopra lo scroller
        assert left.min() > 0.3, f"t={t}: penguin ink across the screen (min luma {left.min():.3f})"

    cells = harness.cell_sequence(6.0, 9.0, 30, 128, 72, grid=16)
    report = analyze_flash(cells, fps=30)
    assert report.passed, f"flash: {report.max_flashes_per_s}/s in the jumps"
