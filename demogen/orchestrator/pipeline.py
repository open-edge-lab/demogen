"""Macchina a stati della pipeline S0–S9 con state.json e resume idempotente.

state.json:
- `request`: prompt e flag della CLI (salvati PRIMA di S0: il resume funziona anche se S0 fallisce);
- `done`: step globali completati (S0, S1, S2, S9);
- `scenes`: {id: {"done": bool}} per il loop S4–S7 di ogni scena;
- `budget_spent_usd`: spesa LLM, aggiornata a ogni salvataggio;
- `stopped`: motivo di uno stop anticipato (es. budget esaurito).
"""

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
from ..llm.budget import Budget, BudgetExceeded
from ..llm.capabilities import Capabilities, detect_capabilities
from ..llm.client import LLMClient
from ..project.report import build_report
from ..project.store import Project
from ..spec.models import DemoSpec
from . import steps
from .selection import has_blocker, list_versions, load_issues, select_best
from .steps import PipelineError

ClientFactory = Callable[..., object]


def default_factory(cfg: Config, role: str, **kw) -> LLMClient:
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
        state = self.project.load_state()
        self.budget = Budget.from_config(cfg, spent_usd=state.get("budget_spent_usd", 0.0))

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

    def _save(self, state: dict) -> None:
        state["budget_spent_usd"] = round(self.budget.spent_usd, 6)
        self.project.save_state(state)

    def _harness(self) -> Harness:
        channel = "chromium" if self.gpu == "hardware" else None
        return Harness(gpu=self.gpu, headless=True, channel=channel)  # type: ignore[arg-type]

    # ------------------------------------------------------------ run
    def run(self, prompt: str, duration_s: float = 30, bpm: float = 128.0,
            profile: str = "modern", loop: bool = False) -> DemoSpec:
        state = self.project.load_state()
        state.setdefault("done", [])
        state.setdefault("scenes", {})
        # la richiesta originale vince al resume (la CLI di resume la rilegge da qui)
        state.setdefault("request", {"prompt": prompt, "duration_s": duration_s, "bpm": bpm,
                                     "profile": profile, "loop": loop})
        self._save(state)
        req = state["request"]
        try:
            return self._run_steps(state, req)
        except BudgetExceeded as e:
            return self._stop_for_budget(state, e)

    def resume(self) -> DemoSpec:
        """Riprende dal punto salvato in state.json senza rifare il lavoro (e le chiamate) già fatto."""
        state = self.project.load_state()
        req = state.get("request")
        if req is None:
            if not self.project.exists("spec.json"):
                raise PipelineError("resume: state.json senza `request` e nessuno spec.json")
            spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
            req = {"prompt": spec.prompt, "duration_s": spec.duration_s, "bpm": spec.timeline.bpm,
                   "profile": spec.profile, "loop": spec.loop}
        return self.run(**req)

    def _run_steps(self, state: dict, req: dict) -> DemoSpec:
        done = set(state["done"])

        def mark(step: str) -> None:
            done.add(step)
            state["done"] = sorted(done)
            self._save(state)

        if "S0" in done and self.project.exists("spec.json"):
            spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        else:
            spec = steps.s0_brief(self, req["prompt"], req["duration_s"], req["bpm"],
                                  req["profile"], req["loop"])
            mark("S0")

        if "S1" not in done or not self.project.exists("style.glsl"):
            steps.s1_style(self, spec)
            mark("S1")

        if "S2" not in done:
            asyncio.run(steps.s2_draft(self, spec, steps.style_src(self)))
            mark("S2")

        # S4–S7 per scena (harness riutilizzato); ogni scena completata è marcata a sé
        pending = [s for s in spec.scenes if not state["scenes"].get(s.id, {}).get("done")]
        if pending:
            with self._harness() as h:
                for scene in pending:
                    self._scene_loop(h, spec, scene)
                    state["scenes"][scene.id] = {"done": True}
                    self._save(state)

        if "S9" not in done:
            self._bundle_and_probe(spec, state)
            mark("S9")
        return spec

    # ------------------------------------------------------------ scene loop
    def _scene_loop(self, harness: Harness, spec: DemoSpec, scene) -> None:
        sdir = self.project.path / "scenes" / scene.id
        src = self.project.read(f"scenes/{scene.id}/v1.glsl")
        ok, cur, errors = steps.s4_compile(self, harness, spec, scene.id, src, 1)
        if not ok:
            raise PipelineError(
                f"S4: scena {scene.id} non compila dopo i tentativi del fixer:\n"
                + "\n".join(str(e).split("--- sorgente ---", 1)[0] for e in errors)[:2000]
            )
        version = 1
        consumed: set[int] = set()  # revisioni già riusate in questo run (replay del resume)
        max_iter = self.cfg.budget.max_iterations_per_scene
        for it in range(max_iter):
            steps.s5_probe(self, harness, spec, scene.id, cur, version)
            issues = [i.model_dump() for i in load_issues(sdir, version)]
            crit = steps.s6_critique(self, spec, scene, version)
            best = select_best(sdir)
            blocked = has_blocker(load_issues(sdir, version))
            print(f"[{scene.id}] v{version} score={best['score']} verdict={crit['verdict']}"
                  + (" (blocker: non accettabile)" if blocked else ""))
            # "accept" vale solo senza blocker dei gate
            if (crit["verdict"] == "accept" and not blocked) or it >= max_iter - 1:
                break
            version, cur = steps.s7_revise(self, harness, spec, scene, version, cur, crit,
                                           issues, consumed=consumed)
        select_best(sdir)

    # ------------------------------------------------------------ S9
    def _bundle_and_probe(self, spec: DemoSpec, state: dict) -> dict:
        post = json.loads(self.project.read("post.json")) if self.project.exists("post.json") else {}
        res = steps.s9_bundle(self, spec, post)
        try:
            self._probe_whole_demo(res["payload"], spec)
        finally:
            self._save(state)
            self.project.write("report.md", build_report(self.project.path))
        print(f"[S9] bundle: {res['sizes']['paths']}  report: {self.project.path}/report.md")
        return res

    def _stop_for_budget(self, state: dict, err: BudgetExceeded) -> DemoSpec:
        """Budget esaurito: se ogni scena ha una versione compilata, bundle con le best attuali."""
        state["stopped"] = f"budget: {err}"
        self._save(state)
        print(f"[budget] stop anticipato: {err}")
        if not self.project.exists("spec.json"):
            raise PipelineError(f"budget esaurito prima dello spec: {err}") from err
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        missing = [s.id for s in spec.scenes if not self._has_compiled_version(s.id)]
        if missing or not self.project.exists("style.glsl"):
            raise PipelineError(f"budget esaurito prima di avere tutte le scene ({missing}): {err}") from err
        self._bundle_and_probe(spec, state)
        state["done"] = sorted(set(state["done"]) | {"S9"})
        self._save(state)
        return spec

    def _has_compiled_version(self, scene_id: str) -> bool:
        sdir = self.project.path / "scenes" / scene_id
        return any(not (sdir / f"v{v}.compile_errors.json").exists() and (sdir / f"v{v}.glsl").stat().st_size
                   for v in list_versions(sdir))

    # ------------------------------------------------------------ probe demo intera
    def _probe_whole_demo(self, payload: dict, spec: DemoSpec) -> None:
        """Probe del bundle spedito: compila, metriche, flash su TUTTA la demo (transizioni incluse).

        Con blocker solleva PipelineError (S9 non viene marcato fatto)."""
        import gzip

        from ..critic.metrics_perf import perf_profile

        with self._harness() as h:
            res = h.load(payload)
            if not res["ok"]:
                raise PipelineError("S9: il bundle non compila:\n" + "\n".join(res["errors"])[:2000])
            info = h.info()
            dur = payload["meta"]["duration_s"]
            times = [round(dur * (i + 0.5) / 8, 3) for i in range(8)]
            pngs = h.capture(times, 320, 180)
            stats = h.scene_stats(times, 320, 180)
            prof = h.profile(times, 320, 180, repeats=2)
            fl = steps.probe_flash(self, h, dur)
        frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
        vm = video_metrics(frames, stats, loop=spec.loop)
        pf = perf_profile(
            {float(k): v for k, v in prof["samples"].items()},
            profile=spec.profile,
            resolution=(320, 180), method=str(prof["method"]),
            gpu=str(info["renderer"]), target_fps=self.cfg.realtime.target_fps,
        )
        raw = json.dumps(payload).encode()
        metrics = {
            "video": vm,
            "perf": pf.model_dump(),
            "flash": fl.model_dump(),
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
        if blockers:
            raise PipelineError("S9: la demo intera ha blocker:\n" + "\n".join(f"- {b.description}" for b in blockers))

    # ------------------------------------------------------------ revise mirato
    def run_revise(self, scene_id: str, note: str) -> None:
        """Revisione mirata di una scena con nota testuale, poi nuovo bundle."""
        state = self.project.load_state()
        state.setdefault("done", [])
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        scene = next((s for s in spec.scenes if s.id == scene_id), None)
        if scene is None:
            raise PipelineError(f"revise: scena {scene_id!r} inesistente ({[s.id for s in spec.scenes]})")
        sdir = self.project.path / "scenes" / scene_id
        best = select_best(sdir)
        version = int(best["version"][1:])
        src = self.project.read(f"scenes/{scene_id}/v{version}.glsl")
        try:
            with self._harness() as h:
                issues = [{"severity": "major", "source": "user", "description": note, "suggested_fix": ""}]
                crit = {"scores": {}, "issues": issues, "verdict": "revise", "summary": note}
                new_version, new_src = steps.s7_revise(self, h, spec, scene, version, src, crit, issues,
                                                       reuse=False)
                if new_version != version:
                    steps.s5_probe(self, h, spec, scene_id, new_src, new_version)
                    steps.s6_critique(self, spec, scene, new_version)
                select_best(sdir)
        finally:
            self._save(state)
        res = self._bundle_and_probe(spec, state)
        print(f"[revise] scena {scene_id} → {res['name']}; report aggiornato")
