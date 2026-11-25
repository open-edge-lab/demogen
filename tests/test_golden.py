"""Golden test: la demo M1 (examples/timeline.json) renderizzata via harness su
SwiftShader deve dare frame coerenti con i golden salvati (tolleranza media < 3/255).

Un golden mancante è un fallimento. Per (ri)generarli: DEMOGEN_UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from demogen.bundle.build import build_payload

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples" / "timeline.json"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
TIMES = [2.0, 20.0, 40.0, 60.0]
SIZE = (320, 180)
UPDATE = os.environ.get("DEMOGEN_UPDATE_GOLDEN") == "1"


def test_demo_m1_golden_swiftshader(harness) -> None:
    payload = build_payload(json.loads(SPEC.read_text(encoding="utf-8")), SPEC.parent)
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:3000]
    pngs = harness.capture(TIMES, *SIZE)

    if UPDATE:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for t, png in zip(TIMES, pngs):
            (GOLDEN / f"m1_t{t}.png").write_bytes(png)
        return

    for t, png in zip(TIMES, pngs):
        golden_path = GOLDEN / f"m1_t{t}.png"
        if not golden_path.exists():
            pytest.fail(f"golden mancante: {golden_path} (DEMOGEN_UPDATE_GOLDEN=1 per rigenerare)")
        a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=float)
        b = np.asarray(Image.open(golden_path).convert("RGB"), dtype=float)
        assert a.max() > 10, f"t={t}: frame nero"
        diff = float(np.abs(a - b).mean())
        assert diff < 3.0, f"t={t}: diff media {diff:.2f} > 3.0"
