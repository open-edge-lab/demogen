"""Macchina a stati della pipeline S0–S9 con state.json e resume idempotente."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..browser.harness import Harness
from ..config import Config
from ..critic.gates import run_gates
from ..critic.metrics_video import video_metrics
from ..llm.budget import Budget
from ..llm.capabilities import Capabilities, detect_capabilities
from ..llm.client import LLMClient
from ..project.report import build_report
from ..project.store import Project
from ..spec.models import DemoSpec
from . import steps
from .selection import select_best

ClientFactory = Callable[..., object]


def default_factory(cfg: Config, role: str, **kw) -> LLMClient:
    kw.pop("budget", None)
    return LLMClient(cfg, role, **kw)


class Pipeline:
    def __init__(
        self,
        project: Project,
        cfg: Config,
        *,
        gpu: str = "swiftshader",
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.project = project
        self.cfg = cfg
        self.gpu = gpu
        self.fake = client_factory is not None
        self.client_factory = client_factory or default_factory
        self._clients: dict[str, object] = {}
        self.budget = Budget.from_config(cfg)

    def client(self, role: str):
        if role not in self._clients:
            self._clients[role] = self.client_factory(
                self.cfg, role, log_dir=self.project.path / "llm_calls", budget=self.budget
            )
        return self._clients[role]

    def caps(self, role: str) -> Capabilities:
        if self.fake:
            return Capabilities(vision=False, json_schema=False, source="fake")
        return detect_capabilities(self.cfg, role, cache_dir=Path(self.cfg.cache_dir))

    # ------------------------------------------------------------ run
    def run(self, prompt: str, duration_s: float = 30, bpm: float = 128.0,
            profile: str = "modern", loop: bool = False) -> DemoSpec:
        state = self.project.load_state()
        done = set(state.get("done", []))

        if "S0" not in done:
            spec = steps.s0_brief(self, prompt, duration_s, bpm, profile, loop)
            done.add("S0")
            state["done"] = sorted(done)
            self.project.save_state(state)
        else:
            spec = DemoSpec.model_validate_json(self.project.read("spec.json"))

        style_src = self.project.read("style.glsl") if (self.project.path / "style.glsl").exists() else None
        if "S1" not in done or style_src is None:
            style_src = steps.s1_style(self, spec)
            done.add("S1")
            state["done"] = sorted(done)
            self.project.save_state(state)

        if "S2" not in done:
            srcs = asyncio.run(steps.s2_draft(self, spec, style_src))
            done.add("S2")
            state["done"] = sorted(done)
            self.project.save_state(state)
        else:
            srcs = {
                s.id: self.project.read(f"scenes/{s.id}/v1.glsl") for s in spec.scenes
            }

        # S4–S7 per scena (con harness riutilizzato)
        channel = "chromium" if self.gpu == "hardware" else None
        with Harness(gpu=self.gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
            for scene in spec.scenes:
                self._scene_loop(h, spec, scene, srcs[scene.id], style_src, done, state)

        # S9 bundle + probe demo intera + report
        if "S9" not in done:
            post = {}
            pj = self.project.path / "post.json"
            if pj.exists():
                post = json.loads(pj.read_text(encoding="utf-8"))
            res = steps.s9_bundle(self, spec, style_src, post)
            self._probe_whole_demo(res["payload"], spec)
            report = build_report(self.project.path)
            self.project.write("report.md", report)
            done.add("S9")
            state["done"] = sorted(done)
            state["budget_spent_usd"] = self.budget.spent_usd
            self.project.save_state(state)
            print(f"[S9] bundle: {res['sizes']['paths']}  report: {self.project.path}/report.md")
        return spec

    # ------------------------------------------------------------ scene loop
    def _scene_loop(self, harness: Harness, spec: DemoSpec, scene, src: str,
                    style_src: str, done: set, state: dict) -> None:
        common = steps.common_for(spec, {s.id: src for s in spec.scenes if s.id == scene.id} |
                                  {s.id: self.project.read(f"scenes/{s.id}/v1.glsl")
                                   for s in spec.scenes if s.id != scene.id and
                                   (self.project.path / f"scenes/{s.id}/v1.glsl").exists()},
                                  style_src)
        ok, cur, errors = steps.s4_compile(self, harness, spec, scene.id, src, common, 1)
        if not ok:
            raise RuntimeError(
                f"S4: scena {scene.id} non compila dopo i tentativi del fixer:\n"
                + "\n".join(errors)[:2000]
            )
        version, cur = 1, cur
        max_iter = self.cfg.budget.max_iterations_per_scene
        for it in range(max_iter):
            steps.s5_probe(self, harness, spec, scene.id, cur, common, version)
            issues = json.loads(self.project.read(f"scenes/{scene.id}/v{version}.issues.json"))
            crit = steps.s6_critique(self, spec, scene, version)
            best = select_best(self.project.path / "scenes" / scene.id)
            print(f"[{scene.id}] v{version} score={best['score']} verdict={crit['verdict']}")
            if crit["verdict"] == "accept" or it >= max_iter - 1:
                break
            version, cur = steps.s7_revise(self, harness, spec, scene, style_src, common,
                                           version, cur, crit, issues)
        select_best(self.project.path / "scenes" / scene.id)
        done.update({"S4", "S5", "S6", "S7"})
        state["done"] = sorted(done)
        self.project.save_state(state)

    # ------------------------------------------------------------ probe demo intera
    def _probe_whole_demo(self, payload: dict, spec: DemoSpec) -> None:
        import gzip

        channel = "chromium" if self.gpu == "hardware" else None
        with Harness(gpu=self.gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
            res = h.load(payload)
            if not res["ok"]:
                raise RuntimeError("S9: il bundle non compila:\n" + "\n".join(res["errors"])[:2000])
            info = h.info()
            dur = payload["meta"]["duration_s"]
            times = [round(dur * (i + 0.5) / 8, 3) for i in range(8)]
            pngs = h.capture(times, 320, 180)
            stats = h.scene_stats(times, 320, 180)
            prof = h.profile(times, 320, 180, repeats=2)
        frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
        vm = video_metrics(frames, stats, loop=spec.loop)
        from ..critic.metrics_perf import perf_profile

        pf = perf_profile(
            {float(k): v for k, v in prof["samples"].items()},
            resolution=(320, 180), method=str(prof["method"]),
            gpu=str(info["renderer"]), target_fps=self.cfg.realtime.target_fps,
        )
        raw = json.dumps(payload).encode()
        metrics = {
            "video": vm,
            "perf": pf.model_dump(),
            "startup": {"compile_total_ms": res["compile_ms"]},
            "sizes": {"payload_gzip_bytes": len(gzip.compress(raw, 9))},
            "gpu": info["renderer"],
        }
        issues = run_gates(metrics, self.cfg)
        out = self.project.path / "out"
        (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
        (out / "issues.json").write_text(
            json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8"
        )
        blockers = [i for i in issues if i.severity == "blocker"]
        print(f"[S9] probe demo intera: {len(issues)} issue ({len(blockers)} blocker)")

    # ------------------------------------------------------------ revise mirato
    def run_revise(self, scene_id: str, note: str) -> None:
        """Revisione mirata di una scena con nota testuale (max iterazioni da config)."""
        self.project.load_state()
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        style_src = self.project.read("style.glsl")
        scene = next(s for s in spec.scenes if s.id == scene_id)
        best = select_best(self.project.path / "scenes" / scene_id)
        version = int(best["version"][1:])
        src = self.project.read(f"scenes/{scene_id}/{best['version']}.glsl")
        channel = "chromium" if self.gpu == "hardware" else None
        with Harness(gpu=self.gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
            common = steps.common_for(spec, {s.id: self.project.read(f"scenes/{s.id}/v1.glsl")
                                              for s in spec.scenes}, style_src)
            issues = [{"severity": "major", "source": "user", "description": note, "suggested_fix": ""}]
            crit = {"scores": {}, "issues": issues, "verdict": "revise", "summary": note}
            new_version, new_src = steps.s7_revise(self, h, spec, scene, style_src, common,
                                                   version, src, crit, issues)
            if new_version != version:
                steps.s5_probe(self, h, spec, scene_id, new_src, common, new_version)
                steps.s6_critique(self, spec, scene, new_version)
            select_best(self.project.path / "scenes" / scene_id)
        post = json.loads(self.project.read("post.json")) if (self.project.path / "post.json").exists() else {}
        res = steps.s9_bundle(self, spec, style_src, post)
        self._probe_whole_demo(res["payload"], spec)
        self.project.write("report.md", build_report(self.project.path))
        print(f"[revise] scena {scene_id} → {res['name']}; report aggiornato")
