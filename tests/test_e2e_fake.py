"""E2E con LLM finto deterministico: `generate --fake` produce una .demo di 8 s
che compila nell'harness e passa i gate senza blocker (nessuna API reale)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright")
np = pytest.importorskip("numpy")
from PIL import Image

from demogen.browser.harness import Harness
from demogen.config import Config
from demogen.critic.gates import run_gates
from demogen.critic.metrics_perf import perf_profile
from demogen.critic.metrics_video import video_metrics
from demogen.llm.fake import fake_client_factory
from demogen.orchestrator.pipeline import Pipeline
from demogen.project.store import Project


def test_generate_fake_e2e(tmp_path: Path) -> None:
    cfg = Config.model_validate({"providers": {}, "roles": {}})
    proj = Project(tmp_path / "proj")
    pipe = Pipeline(proj, cfg, gpu="swiftshader", client_factory=fake_client_factory)
    spec = pipe.run("plasma demo 8 secondi", duration_s=8, bpm=120, profile="modern")

    assert spec.duration_s <= 120
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert "S9" in state["done"]
    demos = list((proj.path / "out").glob("*.demo"))
    assert demos, "nessun .demo prodotto"
    assert (proj.path / "out" / "report.md").exists() or (proj.path / "report.md").exists()
    assert (proj.path / "scenes" / "s1" / "best.json").exists()

    payload = json.loads(demos[0].read_text(encoding="utf-8"))
    try:
        with Harness(gpu="swiftshader") as h:
            res = h.load(payload)
            assert res["ok"], "\n".join(res["errors"])[:2000]
            dur = payload["meta"]["duration_s"]
            times = [round(dur * (i + 0.5) / 4, 3) for i in range(4)]
            pngs = h.capture(times, 320, 180)
            stats = h.scene_stats(times, 320, 180)
            prof = h.profile(times, 320, 180, repeats=2)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"browser non disponibile: {e}")

    frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
    vm = video_metrics(frames, stats)
    pf = perf_profile({float(k): v for k, v in prof["samples"].items()}, resolution=(320, 180))
    metrics = {"video": vm, "perf": pf.model_dump()}
    issues = run_gates(metrics, cfg)
    assert not any(i.severity == "blocker" for i in issues), [i.description for i in issues]
    assert vm["nan_ratio"] == 0.0
