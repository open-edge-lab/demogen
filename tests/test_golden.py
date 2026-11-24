"""Golden test: la demo M1 (examples/timeline.json) renderizzata via harness su
SwiftShader deve dare frame coerenti con i golden salvati (tolleranza media < 3/255).
La prima run genera i golden in tests/fixtures/golden/.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image", reason="serve Pillow")

from demogen.browser.harness import Harness  # noqa: E402
from demogen.bundle.build import build_payload  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples" / "timeline.json"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
TIMES = [2.0, 20.0, 40.0, 60.0]
SIZE = (320, 180)


@pytest.mark.skipif(not (ROOT / "player" / "dist" / "demogen-harness.js").exists(),
                    reason="build del player mancante (npm run build)")
def test_demo_m1_golden_swiftshader() -> None:
    try:
        payload = build_payload(json.loads(SPEC.read_text(encoding="utf-8")), SPEC.parent)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"build payload fallito: {e}")
    try:
        with Harness(gpu="swiftshader") as h:
            res = h.load(payload)
            assert res["ok"], "\n".join(res["errors"])[:3000]
            pngs = h.capture(TIMES, *SIZE)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"browser Playwright non disponibile: {e}")

    GOLDEN.mkdir(parents=True, exist_ok=True)
    for t, png in zip(TIMES, pngs):
        golden_path = GOLDEN / f"m1_t{t}.png"
        if not golden_path.exists():
            golden_path.write_bytes(png)
            continue
        a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=float)
        b = np.asarray(Image.open(golden_path).convert("RGB"), dtype=float)
        diff = float(np.abs(a - b).mean())
        assert diff < 3.0, f"t={t}: diff media {diff:.2f} > 3.0"
        assert b.max() > 10  # non nero
