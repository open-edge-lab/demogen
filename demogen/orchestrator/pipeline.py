"""Macchina a stati della pipeline S0–S9 con state.json e resume idempotente.

state.json:
- `request`: prompt e flag della CLI (salvati PRIMA di S0: il resume funziona anche se S0 fallisce);
- `done`: step globali completati (S0, S1, S2, S9);
- `scenes`: {id: {"done": bool}} per il loop S4–S7 di ogni scena;
- `budget_spent_usd`: spesa LLM, aggiornata a ogni salvataggio;
- `stopped`: motivo di uno stop anticipato (es. budget esaurito);
- `paused`: "plan" se la run si è fermata dopo S0 per la revisione del piano (`generate --review-plan`).
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .. import progress
from ..browser.harness import Harness
from ..config import Config, resolve_role
from ..critic.gates import run_gates
from ..critic.metrics_video import video_metrics
from ..critic.models import Issue
from ..critic.perf_ref import add_ratios
from ..llm.budget import Budget, BudgetExceeded
from ..llm.capabilities import Capabilities, detect_capabilities
from ..llm.client import LLMClient
from ..project.report import build_report
from ..project.store import Project
from ..spec.models import DemoSpec
from . import music, steps
from .plan import PAUSE_PLAN, load_plan, require_editable
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
        self.ref_cache: dict[tuple, float | None] = {}  # ms della scena di riferimento per renderer/risoluzione
        state = self.project.load_state()
        self.budget = Budget.from_config(cfg, spent_usd=state.get("budget_spent_usd", 0.0),
                                         project=self.project.path.name)

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

    # ------------------------------------------------------------ eventi di avanzamento
    def _models(self) -> dict[str, str]:
        if self.fake:
            return {"llm": "fake"}
        out: dict[str, str] = {}
        for role in ("orchestrator", "critic", "fixer"):
            try:
                out[role] = resolve_role(self.cfg, role).model
            except Exception:  # noqa: BLE001 - solo informativo
                continue
        return out

    def _announce(self, prompt: str) -> None:
        progress.emit(
            "pipeline.start", project=str(self.project.path), prompt=prompt, gpu=self.gpu, fake=self.fake,
            cap=self.budget.max_total_cost_usd, spent=self.budget.spent_usd,
            max_iter=self.cfg.budget.max_iterations_per_scene, models=self._models(),
            max_ref=self.cfg.realtime.max_ref_ratio_p95,
        )

    def _announce_spec(self, spec: DemoSpec, done_scenes: set[str]) -> None:
        progress.emit(
            "spec", title=spec.title, duration=spec.duration_s, bpm=spec.timeline.bpm, profile=spec.profile,
            scenes=[{"id": s.id, "title": s.title} for s in spec.scenes],
        )
        for s in spec.scenes:
            if s.id in done_scenes:
                self._emit_scene_done(s.id)
            elif self.project.exists(f"scenes/{s.id}/v1.glsl"):
                progress.emit("scene", scene=s.id, phase="drafted", version=1)

    def _emit_scene_done(self, scene_id: str, best: dict | None = None) -> None:
        if best is None:
            p = self.project.path / "scenes" / scene_id / "best.json"
            try:
                best = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except ValueError:
                best = {}
        progress.emit("scene.done", scene=scene_id, best=best.get("version"), score=best.get("score"))

    # ------------------------------------------------------------ run
    def run(self, prompt: str, duration_s: float = 30, bpm: float = 128.0,
            profile: str = "modern", loop: bool | None = None, audio: bool = True, music: str = "",
            pause_after_plan: bool = False) -> DemoSpec:
        """`audio`: genera anche la colonna sonora (passo SM); `music`: prompt musicale facoltativo.
        `pause_after_plan`: si ferma dopo S0 (`state["paused"] = "plan"`) perché l'utente legga e
        cambi il piano (`demogen plan`); `resume` riprende da S1. Non è salvato nella richiesta:
        il resume non si ferma di nuovo."""
        state = self.project.load_state()
        state.setdefault("done", [])
        state.setdefault("scenes", {})
        # la richiesta originale vince al resume (la CLI di resume la rilegge da qui); i progetti creati
        # prima della musica non hanno "audio": per loro vale False (nessuna chiamata a sorpresa)
        state.setdefault("request", {"prompt": prompt, "duration_s": duration_s, "bpm": bpm,
                                     "profile": profile, "loop": loop, "audio": audio, "music": music})
        self._save(state)
        req = state["request"]
        self._announce(req["prompt"])
        try:
            return self._run_steps(state, req, pause_after_plan)
        except BudgetExceeded as e:
            return self._stop_for_budget(state, e)
        except BaseException:
            # qualsiasi errore: la spesa già addebitata va salvata, o il resume la sottostimerebbe
            self._save(state)
            raise

    def resume(self) -> DemoSpec:
        """Riprende dal punto salvato in state.json senza rifare il lavoro (e le chiamate) già fatto."""
        state = self.project.load_state()
        req = state.get("request")
        if req is None:
            if not self.project.exists("spec.json"):
                raise PipelineError("resume: state.json has no `request` and there is no spec.json")
            spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
            req = {"prompt": spec.prompt, "duration_s": spec.duration_s, "bpm": spec.timeline.bpm,
                   "profile": spec.profile, "loop": spec.loop, "audio": False}
        return self.run(**req)

    def _run_steps(self, state: dict, req: dict, pause_after_plan: bool = False) -> DemoSpec:
        done = set(state["done"])

        def mark(step: str) -> None:
            done.add(step)
            state["done"] = sorted(done)
            self._save(state)
            progress.emit("step", step=step, state="done")

        def start(step: str, detail: str) -> None:
            progress.emit("step", step=step, state="run", detail=detail)

        if "S0" in done and self.project.exists("spec.json"):
            spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
            progress.emit("step", step="S0", state="skip")
        else:
            start("S0", "brief: the LLM writes the demo spec (scenes, timeline, palette)")
            spec = steps.s0_brief(self, req["prompt"], req["duration_s"], req["bpm"],
                                  req["profile"], req["loop"])
            mark("S0")
        self._announce_spec(spec, {k for k, v in state["scenes"].items() if v.get("done")})

        if pause_after_plan and "S1" not in done:
            state["paused"] = PAUSE_PLAN
            self._save(state)
            progress.emit("pause", reason=PAUSE_PLAN, project=str(self.project.path))
            return spec
        if state.pop("paused", None) is not None:
            self._save(state)

        if "S1" not in done or not self.project.exists("style.glsl"):
            start("S1", "global style: shared functions, palette and post-processing")
            steps.s1_style(self, spec)
            mark("S1")
        else:
            progress.emit("step", step="S1", state="skip")

        if "S2" not in done:
            start("S2", "shader drafts: one per scene, in parallel")
            asyncio.run(steps.s2_draft(self, spec, steps.style_src(self)))
            mark("S2")
        else:
            progress.emit("step", step="S2", state="skip")

        # SM musica e S4–S7 per scena con lo stesso browser; ogni scena completata è marcata a sé
        want_music = bool(req.get("audio")) and "SM" not in done
        pending = [s for s in spec.scenes if not state["scenes"].get(s.id, {}).get("done")]
        if want_music or pending:
            with self._harness() as h:
                if want_music:
                    start("SM", "soundtrack: the composer writes the music, then it is listened to "
                                "(rhythm, loudness, cost)")
                    music.run_music(self, h, spec, str(req.get("music") or ""))
                    mark("SM")
                if pending:
                    start("SC", "for each scene: compile, browser probe, visual critique, revision")
                    for scene in pending:
                        self._scene_loop(h, spec, scene)
                        state["scenes"][scene.id] = {"done": True}
                        self._save(state)
                    progress.emit("step", step="SC", state="done")
        if not want_music:
            progress.emit("step", step="SM", state="skip")
        if not pending:
            progress.emit("step", step="SC", state="skip")

        if "S9" not in done:
            start("S9", "bundle: minified payload, .demo and .html")
            self._bundle_and_probe(spec, state)
            mark("S9")
        else:
            progress.emit("step", step="S9", state="skip")
        return spec

    # ------------------------------------------------------------ scene loop
    def _scene_loop(self, harness: Harness, spec: DemoSpec, scene) -> None:
        sdir = self.project.path / "scenes" / scene.id
        src = self.project.read(f"scenes/{scene.id}/v1.glsl")
        ok, cur, errors = steps.s4_compile(self, harness, spec, scene.id, src, 1)
        if not ok:
            raise PipelineError(
                f"S4: scene {scene.id} does not compile after the fixer attempts:\n"
                + "\n".join(steps.error_log(e) for e in errors)[:2000]
            )
        version = 1
        consumed: set[int] = set()  # revisioni già riusate in questo run (replay del resume)
        max_iter = self.cfg.budget.max_iterations_per_scene
        for it in range(max_iter):
            probe = steps.s5_probe(self, harness, spec, scene.id, cur, version)
            issues = [i.model_dump() for i in load_issues(sdir, version)]
            crit = steps.s6_critique(self, spec, scene, version)
            best = select_best(sdir)
            v_issues = load_issues(sdir, version)
            blocked = has_blocker(v_issues)
            progress.emit(
                "scene.result", scene=scene.id, version=version, verdict=crit["verdict"],
                score=best["score"], best=best["version"],
                blockers=[i.description for i in v_issues if i.severity == "blocker"],
                cost=probe.get("perf", {}).get("ref_ratio_p95"),
            )
            print(f"[{scene.id}] v{version} score={best['score']} verdict={crit['verdict']}"
                  + (" (blocker: not acceptable)" if blocked else ""))
            # "accept" vale solo senza blocker dei gate
            if (crit["verdict"] == "accept" and not blocked) or it >= max_iter - 1:
                break
            new_version, cur = steps.s7_revise(self, harness, spec, scene, version, cur, crit,
                                               issues, consumed=consumed)
            if new_version == version:  # la revisione non compila: si riparte dalla stessa versione
                print(f"[{scene.id}] the revision of v{version} does not compile even after the fixer: "
                      f"keeping v{version} and asking again with the compile errors")
            version = new_version
        self._emit_scene_done(scene.id, select_best(sdir))

    # ------------------------------------------------------------ S9
    def _bundle_and_probe(self, spec: DemoSpec, state: dict) -> dict:
        post = json.loads(self.project.read("post.json")) if self.project.exists("post.json") else {}
        res = steps.s9_bundle(self, spec, post)
        progress.emit("step", step="S9", state="run",
                      detail="whole-demo probe: compile, frames, flash at 30 fps across the transitions")
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
        print(f"[budget] early stop: {err}")
        progress.emit("stop", reason=f"budget: {err}")
        if not self.project.exists("spec.json"):
            raise PipelineError(f"budget exhausted before the spec: {err}") from err
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        missing = [s.id for s in spec.scenes if not self._has_compiled_version(s.id)]
        if missing or not self.project.exists("style.glsl"):
            raise PipelineError(f"budget exhausted before every scene was ready ({missing}): {err}") from err
        progress.emit("step", step="S9", state="run", detail="bundle with the best versions available")
        self._bundle_and_probe(spec, state)
        state["done"] = sorted(set(state["done"]) | {"S9"})
        self._save(state)
        progress.emit("step", step="S9", state="done")
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
                raise PipelineError("S9: the bundle does not compile:\n" + "\n".join(res["errors"])[:2000])
            info = h.info()
            dur = payload["meta"]["duration_s"]
            times = [round(dur * (i + 0.5) / 8, 3) for i in range(8)]
            pngs = h.capture(times, 320, 180)
            stats = h.scene_stats(times, 320, 180)
            prof = h.profile(times, 320, 180, repeats=2)
            fl = steps.probe_flash(self, h, dur)
            bursts = steps.capture_bursts(self, h, dur)
            seam = steps.capture_seam(self, h, dur) if spec.loop else None
            audio_m = None
            if payload.get("audio"):  # la musica spedita, nel bundle vero (minificato)
                audio_m, _, _ = music.analyze_audio(h, dur, spec.timeline.bpm, spec.timeline.beats_per_bar)
            # per ultimi: scena vuota e riferimento cambiano il payload nell'harness
            fixed = steps.baseline_ms(h, (320, 180), payload)
            ref = steps.reference_ms(self, h, (320, 180), str(info["renderer"]))
        frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
        vm = video_metrics(frames, stats, loop=spec.loop, bursts=steps._np_bursts(bursts), seam=seam)
        pf = perf_profile(
            {float(k): v for k, v in prof["samples"].items()},
            profile=spec.profile,
            resolution=(320, 180), method=str(prof["method"]),
            gpu=str(info["renderer"]), target_fps=self.cfg.realtime.target_fps,
            fixed_ms=fixed,
        )
        raw = json.dumps(payload).encode()
        metrics = {
            "video": vm,
            "perf": add_ratios(pf.model_dump(), ref),
            "flash": fl.model_dump(),
            "startup": {"compile_total_ms": res["compile_ms"]},
            "sizes": {"payload_gzip_bytes": len(gzip.compress(raw, 9))},
            "gpu": info["renderer"],
        }
        if audio_m is not None:
            metrics["audio"] = audio_m
        # la perf eccessiva qui è un avviso: le scene sono già state spinte ad alleggerirsi in S5–S7
        issues = (run_gates(metrics, self.cfg, perf_blocking=False) + self._unresolved_scene_blockers(spec)
                  + self._music_warning(bool(payload.get("audio"))))
        out = self.project.path / "out"
        (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
        (out / "issues.json").write_text(
            json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8"
        )
        blockers = [i for i in issues if i.severity == "blocker"]
        print(f"[S9] whole-demo probe: {len(issues)} issues ({len(blockers)} blockers)")
        if blockers:
            raise PipelineError("S9: the whole demo has blockers:\n"
                                + "\n".join(f"- {b.description}" for b in blockers))

    def _music_warning(self, has_audio: bool) -> list[Issue]:
        """Musica richiesta ma nessuna versione utilizzabile: la demo esce muta, con un avviso."""
        req = self.project.load_state().get("request") or {}
        if has_audio or not req.get("audio"):
            return []
        msg = "music requested but no usable version: the demo is silent (see audio/vN.issues.json)"
        print(f"[S9] WARNING {msg}")
        return [Issue(severity="major", source="gate", description=msg,
                      suggested_fix='demogen music <project> --prompt "..." to compose it again')]

    def _unresolved_scene_blockers(self, spec: DemoSpec) -> list[Issue]:
        """Scene consegnate con la versione migliore che ha ancora blocker (es. tutte le versioni
        nere o troppo pesanti): avviso nel report invece di un fallimento silenzioso."""
        out: list[Issue] = []
        for s in spec.scenes:
            sdir = self.project.path / "scenes" / s.id
            p = sdir / "best.json"
            if not p.exists():
                continue
            ver = json.loads(p.read_text(encoding="utf-8")).get("version", "")
            if not str(ver)[1:].isdigit():
                continue
            blk = [i.description for i in load_issues(sdir, int(str(ver)[1:])) if i.severity == "blocker"]
            if blk:
                msg = f"scene {s.id} delivered with {ver}, which still has blockers: {blk[0]}"
                print(f"[S9] WARNING {msg}")
                out.append(Issue(severity="major", source="gate", description=msg,
                                 suggested_fix=f"demogen revise <project> --scene {s.id} --note \"...\""))
        return out

    # ------------------------------------------------------------ musica di un progetto esistente
    def run_music(self, music_prompt: str = "") -> bool:
        """(Ri)compone la colonna sonora (nuova versione in audio/) e, se la demo è completa, rifà il
        bundle con la musica. Ritorna True se il bundle è stato rifatto."""
        if not self.project.exists("spec.json"):
            raise PipelineError("music: the project has no spec yet (run generate or resume first)")
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        state = self.project.load_state()
        state.setdefault("done", [])
        state.setdefault("scenes", {})
        req = state.setdefault("request", {"prompt": spec.prompt, "duration_s": spec.duration_s,
                                           "bpm": spec.timeline.bpm, "profile": spec.profile, "loop": spec.loop})
        req["audio"], req["music"] = True, music_prompt
        self._save(state)
        self._announce(spec.prompt)
        done_scenes = {k for k, v in state["scenes"].items() if v.get("done")}
        self._announce_spec(spec, done_scenes)
        for step in ("S0", "S1", "S2"):
            progress.emit("step", step=step, state="skip" if step in state["done"] else "pending")
        progress.emit("step", step="SM", state="run", detail="soundtrack: composition and listening")
        try:
            with self._harness() as h:
                music.run_music(self, h, spec, music_prompt)
            state["done"] = sorted(set(state["done"]) | {"SM"})
        finally:
            self._save(state)
        progress.emit("step", step="SM", state="done")
        complete = all(s.id in done_scenes for s in spec.scenes) and self.project.exists("style.glsl")
        if not complete:
            progress.emit("step", step="SC", state="pending")
            print("[music] ready: finish the demo with `demogen resume <project>` to get the bundle")
            return False
        progress.emit("step", step="SC", state="skip")
        progress.emit("step", step="S9", state="run", detail="bundle with the new music")
        self._bundle_and_probe(spec, state)
        state["done"] = sorted(set(state["done"]) | {"S9"})
        self._save(state)
        progress.emit("step", step="S9", state="done")
        return True

    # ------------------------------------------------------------ piano cambiato con una nota
    def replan(self, note: str) -> DemoSpec:
        """L'LLM riscrive il piano (S0) con la nota dell'utente: una chiamata, prima dello style."""
        note = note.strip()
        if not note:
            raise PipelineError("replan: the note is empty")
        state = require_editable(self.project)
        spec = load_plan(self.project)
        req = state.get("request") or {"prompt": spec.prompt, "duration_s": spec.duration_s,
                                       "bpm": spec.timeline.bpm, "profile": spec.profile, "loop": spec.loop}
        try:
            return steps.s0_replan(self, spec, note, req)
        except BudgetExceeded as e:
            raise PipelineError(f"the plan was not changed: {e}") from e
        finally:
            self._save(state)  # la spesa della chiamata, anche se è fallita

    # ------------------------------------------------------------ revise mirato
    def run_revise(self, scene_id: str, note: str) -> None:
        """Revisione mirata di una scena con nota testuale, poi nuovo bundle."""
        state = self.project.load_state()
        state.setdefault("done", [])
        spec = DemoSpec.model_validate_json(self.project.read("spec.json"))
        scene = next((s for s in spec.scenes if s.id == scene_id), None)
        if scene is None:
            raise PipelineError(f"revise: scene {scene_id!r} does not exist ({[s.id for s in spec.scenes]})")
        sdir = self.project.path / "scenes" / scene_id
        best = select_best(sdir)
        version = int(best["version"][1:])
        src = self.project.read(f"scenes/{scene_id}/v{version}.glsl")
        self._announce(spec.prompt)
        self._announce_spec(spec, {s.id for s in spec.scenes if s.id != scene_id})
        for step in ("S0", "S1", "S2"):
            progress.emit("step", step=step, state="skip")
        progress.emit("step", step="SC", state="run", detail=f"revising {scene_id}: {note}")
        try:
            with self._harness() as h:
                issues = [{"severity": "major", "source": "user", "description": note, "suggested_fix": ""}]
                crit = {"scores": {}, "issues": issues, "verdict": "revise", "summary": note}
                new_version, new_src = steps.s7_revise(self, h, spec, scene, version, src, crit, issues,
                                                       reuse=False)
                if new_version != version:
                    steps.s5_probe(self, h, spec, scene_id, new_src, new_version)
                    steps.s6_critique(self, spec, scene, new_version)
                self._emit_scene_done(scene_id, select_best(sdir))
        finally:
            self._save(state)
        progress.emit("step", step="SC", state="done")
        progress.emit("step", step="S9", state="run", detail="bundle: minified payload, .demo and .html")
        res = self._bundle_and_probe(spec, state)
        progress.emit("step", step="S9", state="done")
        print(f"[revise] scene {scene_id} → {res['name']}; report updated")
