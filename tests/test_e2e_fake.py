"""E2E con LLM finto deterministico: `generate --fake` produce una .demo di 8 s
che compila nell'harness e passa i gate senza blocker (nessuna API reale)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from rich.console import Console

from demogen import progress
from demogen.browser.harness import Harness
from demogen.config import Config
from demogen.critic.gates import run_gates
from demogen.critic.metrics_perf import perf_profile
from demogen.critic.metrics_video import video_metrics
from demogen.dashboard import Dashboard
from demogen.llm.fake import FAKE_SCENE, FAKE_STYLE, _fake_spec, fake_client_factory
from demogen.orchestrator.pipeline import Pipeline
from demogen.project.store import Project
from demogen.spec.models import DemoSpec
from tests.conftest import require_browser


def test_generate_fake_e2e(tmp_path: Path) -> None:
    # la pipeline apre il browser da sé: il pre-check è l'unico punto che può diventare skip
    require_browser()
    cfg = Config.model_validate({"providers": {}, "roles": {}})
    proj = Project(tmp_path / "proj")
    pipe = Pipeline(proj, cfg, gpu="swiftshader", client_factory=fake_client_factory)
    events: list[tuple[str, dict]] = []
    unsubscribe = progress.subscribe(lambda ev, d: events.append((ev, d)))
    try:
        spec = pipe.run("plasma demo 8 secondi", duration_s=8, bpm=120, profile="modern")
    finally:
        unsubscribe()

    _check_progress_events(events, [s.id for s in spec.scenes])
    assert spec.duration_s <= 120
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert "S9" in state["done"] and "SM" in state["done"]
    demos = list((proj.path / "out").glob("*.demo"))
    assert demos, "no .demo produced"
    assert (proj.path / "out" / "report.md").exists() or (proj.path / "report.md").exists()
    assert (proj.path / "scenes" / "s1" / "best.json").exists()
    assert _audio_best(proj) == "v1"

    payload = json.loads(demos[0].read_text(encoding="utf-8"))
    assert payload.get("audio") and "mainAudio" in payload["audio"]  # la colonna sonora è nel bundle
    with Harness(gpu="swiftshader") as h:
        res = h.load(payload)
        assert res["ok"], "\n".join(res["errors"])[:2000]
        dur = payload["meta"]["duration_s"]
        times = [round(dur * (i + 0.5) / 4, 3) for i in range(4)]
        pngs = h.capture(times, 320, 180)
        stats = h.scene_stats(times, 320, 180)
        prof = h.profile(times, 320, 180, repeats=2)
        gpu = str(h.info()["renderer"])

    frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
    vm = video_metrics(frames, stats)
    pf = perf_profile({float(k): v for k, v in prof["samples"].items()}, resolution=(320, 180), gpu=gpu)
    metrics = {"video": vm, "perf": pf.model_dump()}
    issues = run_gates(metrics, cfg)
    assert not any(i.severity == "blocker" for i in issues), [i.description for i in issues]
    assert vm["nan_ratio"] == 0.0

    # musica ricomposta su un progetto finito: nuova versione in audio/, bundle e report rifatti
    demo_mtime = demos[0].stat().st_mtime_ns
    assert pipe.run_music("acid techno") is True
    assert _audio_best(proj) == "v2"
    assert (proj.path / "audio" / "v2.glsl").exists()
    meta = json.loads((proj.path / "audio" / "v2.meta.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == "acid techno"
    assert demos[0].stat().st_mtime_ns > demo_mtime
    payload = json.loads(demos[0].read_text(encoding="utf-8"))
    assert payload.get("audio") and "mainAudio" in payload["audio"]
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert state["request"]["audio"] is True and state["request"]["music"] == "acid techno"
    report = (proj.path / "report.md").read_text(encoding="utf-8")
    assert "## Music" in report and "- music prompt: acid techno" in report
    assert "- version: v2" in report and "- listening: rms=" in report


def _audio_best(proj: Project) -> str | None:
    return json.loads((proj.path / "audio" / "best.json").read_text(encoding="utf-8"))["version"]


def test_resume_progetto_senza_audio_nella_richiesta_non_compone(tmp_path: Path) -> None:
    # progetto creato prima della musica: la richiesta in state.json non ha "audio"; tutto il resto è
    # già fatto, quindi il resume non apre il browser e non chiama nessun LLM
    proj = Project(tmp_path / "old")
    spec = DemoSpec.model_validate(_fake_spec("old demo", 8.0, 120.0, "modern"))
    proj.write("spec.json", spec.model_dump_json(indent=1))
    proj.write("style.glsl", FAKE_STYLE)
    for s in spec.scenes:
        proj.write(f"scenes/{s.id}/v1.glsl", FAKE_SCENE)
        proj.write(f"scenes/{s.id}/best.json", json.dumps({"version": "v1", "score": 7.0}))
    request = {"prompt": "old demo", "duration_s": 8.0, "bpm": 120.0, "profile": "modern", "loop": False}
    proj.save_state({"request": request, "done": ["S0", "S1", "S2", "S9"],
                     "scenes": {s.id: {"done": True} for s in spec.scenes}})

    roles: list[str] = []

    def factory(config=None, role: str = "orchestrator", **kw):
        roles.append(role)
        return fake_client_factory(config, role, **kw)

    cfg = Config.model_validate({"providers": {}, "roles": {}})
    events: list[tuple[str, dict]] = []
    unsubscribe = progress.subscribe(lambda ev, d: events.append((ev, d)))
    try:
        Pipeline(proj, cfg, client_factory=factory).resume()
    finally:
        unsubscribe()
    assert roles == []
    assert not (proj.path / "audio").exists()
    assert not any(ev.startswith("music") for ev, _ in events)
    steps = {d["step"]: d["state"] for ev, d in events if ev == "step"}
    assert steps["SM"] == "skip" and steps["SC"] == "skip" and steps["S9"] == "skip"
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert "SM" not in state["done"] and "audio" not in state["request"]


def _check_progress_events(events: list[tuple[str, dict]], scene_ids: list[str]) -> None:
    """Gli eventi della pipeline vera bastano al pannello per arrivare al 100%."""
    done_steps = {d["step"] for ev, d in events if ev == "step" and d["state"] == "done"}
    assert done_steps == {"S0", "S1", "S2", "SM", "SC", "S9"}
    assert {d.get("best") for ev, d in events if ev == "music.done"} == {"v1"}
    assert [d["scenes"] for ev, d in events if ev == "spec"][0] and events[0][0] == "pipeline.start"
    assert {d["scene"] for ev, d in events if ev == "scene.done"} == set(scene_ids)
    phases = [d["phase"] for ev, d in events if ev == "scene" and d["scene"] == scene_ids[0]]
    for p in ("draft", "drafted", "compile", "probe", "critic"):
        assert p in phases, phases
    starts = {d["id"] for ev, d in events if ev == "llm.start"}
    assert starts and starts == {d["id"] for ev, d in events if ev == "llm.end"}

    console = Console(file=io.StringIO(), width=100, force_terminal=True, record=True)
    dash = Dashboard("generate", console=console)
    for ev, d in events:
        dash.on_event(ev, d)
    dash.__exit__(None, None, None)
    console.print(dash.render())
    assert dash.overall() == 1.0
    assert "COMPLETED" in console.export_text()
