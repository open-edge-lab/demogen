"""Esempio "dead channel" (examples/dead_channel.timeline.json): un monoscopio anni '80 su un tubo CRT
che viene bucato da un'intrusione hacker, il segnale dirottato e il ritorno, in loop.

Deve: compilare; mostrare il monoscopio con le barre colore all'inizio; chiudere il loop senza giunta
(l'ultimo fotogramma è il primo, orologio compreso); e restare dentro il limite WCAG dei flash proprio
nelle scene dei disturbi, dove i glitch sono stati dosati apposta.
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
W, H = 480, 270


def _rgb(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64)


def test_monoscopio_loop_e_flash(harness) -> None:
    spec = json.loads((EXAMPLES / "dead_channel.timeline.json").read_text(encoding="utf-8"))
    payload = build_payload(spec, EXAMPLES, do_minify=True)
    assert payload["meta"]["loop"] is True and len(payload["timeline"]["scenes"]) == 4
    duration = payload["meta"]["duration_s"]
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:1500]

    first, card, last = (_rgb(p) for p in harness.capture([0.0, 2.0, round(duration - 1 / 60, 4)], W, H))
    # barra gialla del monoscopio (seconda delle otto, a metà della fascia delle barre)
    r, g, b = card[84, 169]
    assert r > 150 and g > 150 and b < 90, f"yellow bar expected, got {(r, g, b)}"
    # loop: l'ultimo istante del ritorno è il primo fotogramma (stesso orologio, nessun disturbo)
    assert np.abs(first - last).mean() < 2.0, "visible seam at the loop point"

    # flash WCAG sulle scene dei disturbi (intrusione e dirottamento), come il gate: 30 fps, griglia 16
    s2 = payload["timeline"]["scenes"][1]
    t0 = s2["start_bar"] * 4 * 60 / payload["meta"]["bpm"]
    cells = harness.cell_sequence(t0, t0 + 24.0, 30, 128, 72, grid=16)
    report = analyze_flash(cells, fps=30)
    assert report.passed and report.max_flashes_per_s <= 2, report
