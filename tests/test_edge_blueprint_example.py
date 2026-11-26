"""Esempio "edge blueprint" (examples/edge_blueprint.timeline.json): sfondo delle sezioni di un sito,
la griglia di puntini da disegno tecnico che respira.

Sta dietro a testo, card e moduli per tutta la pagina: deve restare scuro e discreto (fondo del sito,
mai sotto la soglia 0.02 del gate "nero"), avere i puntini, respirare (due istanti non sono uguali) e
girare in loop senza scatti. Le misure sono in px CSS di uno schermo alto 900.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.bundle.build import build_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
W, H = 720, 450


def _luma(png: bytes) -> np.ndarray:
    rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64) / 255
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def test_sfondo_discreto_disegnato_e_loop_senza_giunture(harness) -> None:
    spec = json.loads((EXAMPLES / "edge_blueprint.timeline.json").read_text(encoding="utf-8"))
    payload = build_payload(spec, EXAMPLES, do_minify=True)
    assert payload["meta"]["loop"] is True and payload["quality"]["target_fps"] == 30
    period = payload["meta"]["duration_s"]
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:1500]

    times = [0.0, 12.0, 30.0, 47.0, round(period - 1 / 60, 4)]
    frames = [_luma(png) for png in harness.capture(times, W, H)]
    for t, lum in zip(times, frames, strict=True):
        assert lum.min() >= 0.02, f"t={t}: pixels below the black gate threshold (luma {lum.min():.4f})"
        assert lum.mean() < 0.045, f"t={t}: too bright for a background behind text ({lum.mean():.3f})"
        drawn = float((lum > 0.06).mean())  # puntini e crocini sopra il fondo
        assert 0.002 < drawn < 0.08, f"t={t}: dots cover {drawn:.4f} (no dots or too busy)"

    breath = float(np.abs(frames[0] - frames[1]).max())
    assert breath > 0.02, f"the dots do not breathe: max change between t=0 and t=12 is {breath:.4f}"
    seam = float(np.abs(frames[0] - frames[-1]).mean())
    assert seam < 0.005, f"loop seam: first and last frame differ by {seam:.4f} on average"
