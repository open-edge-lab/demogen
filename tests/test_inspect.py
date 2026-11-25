"""E2E di `demogen inspect` sulla demo M1 in SwiftShader (skip se manca il browser)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from demogen.cli import _payload_from_file  # noqa: E402
from demogen.config import Config  # noqa: E402
from demogen.critic.flash import analyze_flash  # noqa: E402
from demogen.critic.gates import run_gates  # noqa: E402
from demogen.critic.metrics_perf import perf_profile  # noqa: E402
from demogen.critic.metrics_video import video_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CFG = Config.model_validate({"providers": {}, "roles": {}})


def test_inspect_demo_m1_swiftshader(harness) -> None:
    payload = _payload_from_file(ROOT / "examples" / "timeline.json", 120.0)
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:2000]
    duration = payload["meta"]["duration_s"]
    times = [round(duration * (i + 0.5) / 4, 3) for i in range(4)]
    pngs = harness.capture(times, 320, 180)
    stats = harness.scene_stats(times, 320, 180)
    prof = harness.profile(times, 320, 180, repeats=2)
    cells = harness.cell_sequence(0.0, 2.0, 10, 160, 90)

    frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
    vm = video_metrics(frames, stats)
    assert vm["nan_ratio"] == 0.0  # la demo M1 non deve avere NaN
    assert vm["black_ratio"] < 0.9
    pf = perf_profile({float(k): v for k, v in prof["samples"].items()}, resolution=(320, 180),
                      gpu=str(harness.info()["renderer"]))
    fl = analyze_flash(cells, fps=10)
    metrics = {"video": vm, "perf": pf.model_dump(), "flash": fl.model_dump()}
    issues = run_gates(metrics, CFG)
    assert isinstance(issues, list)
    # la demo M1 hand-written non deve avere blocker
    assert not any(i.severity == "blocker" for i in issues), [
        i.description for i in issues
    ]
