"""Esempio "edge horizon" (examples/edge_horizon.timeline.json): sfondo per la hero di un sito.

Uno sfondo deve lasciare leggibile il testo che ci sta sopra e girare in loop senza scatti: il cielo
resta al colore del sito (mai sotto la soglia 0.02 del gate "nero": #020617 ha luma 0.025, una
vignetta o un tone mapping lo farebbero scendere), la fascia del titolo resta scura, il pianeta in
basso c'è e l'ultimo fotogramma del loop combacia con il primo.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.bundle.build import build_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
W, H = 640, 360


def _luma(png: bytes) -> np.ndarray:
    rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64) / 255
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def test_sfondo_leggibile_e_loop_senza_giunture(harness) -> None:
    spec = json.loads((EXAMPLES / "edge_horizon.timeline.json").read_text(encoding="utf-8"))
    payload = build_payload(spec, EXAMPLES, do_minify=True)
    assert payload["meta"]["loop"] is True
    period = payload["meta"]["duration_s"]
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:1500]

    times = [0.0, 20.0, 45.0, 70.0, 100.0, round(period - 1 / 60, 4)]
    frames = [_luma(png) for png in harness.capture(times, W, H)]
    for t, lum in zip(times, frames, strict=True):
        assert lum.min() >= 0.02, f"t={t}: pixels below the black gate threshold (luma {lum.min():.4f})"
        title = lum[int(0.35 * H):int(0.55 * H), int(0.3 * W):int(0.7 * W)]
        assert title.mean() < 0.06, f"t={t}: title band too bright for text on top (luma {title.mean():.3f})"
        top, bottom = lum[: H // 4].mean(), lum[-H // 6:].mean()
        assert bottom > top + 0.1, f"t={t}: no planet at the bottom (top {top:.3f}, bottom {bottom:.3f})"

    seam = float(np.abs(frames[0] - frames[-1]).mean())
    assert seam < 0.01, f"loop seam: first and last frame differ by {seam:.4f} on average"
