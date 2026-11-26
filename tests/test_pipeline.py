"""Batch D: correttezza della pipeline (versioni, math per versione, errori rimappati,
flag di S0, draft isolati, resume senza nuove chiamate LLM, revise max+1)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from demogen.config import Config
from demogen.llm.fake import FakeLLM, FakeResponse, _fake_spec
from demogen.orchestrator import steps
from demogen.orchestrator.pipeline import Pipeline
from demogen.orchestrator.selection import list_versions, next_version, select_best
from demogen.project.store import Project
from demogen.spec.models import DemoSpec
from tests.conftest import require_browser

CFG = Config.model_validate({"providers": {}, "roles": {}})


def _crit(sdir: Path, v: int, score: int, blocker: bool = False) -> None:
    (sdir / f"v{v}.glsl").write_text("x", encoding="utf-8")
    scores = {k: score for k in ("brief", "composition", "color", "motion", "technical", "originality")}
    (sdir / f"v{v}.critique.json").write_text(json.dumps({"scores": scores, "verdict": "revise"}), encoding="utf-8")
    issues = [{"severity": "blocker", "description": "flash"}] if blocker else []
    (sdir / f"v{v}.issues.json").write_text(json.dumps(issues), encoding="utf-8")


# ---------------------------------------------------------------- versioni
def test_versioni_ordine_numerico_e_math_escluso(tmp_path: Path) -> None:
    for name in ("v1.glsl", "v2.glsl", "v10.glsl", "v1.math.glsl", "v2.meta.json"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert list_versions(tmp_path) == [1, 2, 10]
    assert next_version(tmp_path) == 11


def test_select_best_v10_dopo_v9(tmp_path: Path) -> None:
    for v in range(1, 11):
        _crit(tmp_path, v, 7)
    (tmp_path / "v1.math.glsl").write_text("float f(float x){return x;}", encoding="utf-8")
    assert select_best(tmp_path)["version"] == "v10"


def test_select_best_anti_regressione_sul_massimo(tmp_path: Path) -> None:
    # 8 → 7.5 → 6.5 → 5.5 (media brief/color): ogni passo perde ≤ 1 dal precedente, la deriva non passa
    for v, (a, b) in ((1, (8, 8)), (2, (7, 8)), (3, (6, 7)), (4, (5, 6))):
        _crit(tmp_path, v, 0)
        crit = {"scores": {"brief": a, "color": b}, "verdict": "revise"}
        (tmp_path / f"v{v}.critique.json").write_text(json.dumps(crit), encoding="utf-8")
    assert select_best(tmp_path)["version"] == "v2"


def test_select_best_esclude_i_blocker(tmp_path: Path) -> None:
    _crit(tmp_path, 1, 5)
    _crit(tmp_path, 2, 9, blocker=True)
    assert select_best(tmp_path)["version"] == "v1"
    # se tutte hanno blocker, si sceglie comunque la migliore
    _crit(tmp_path, 1, 5, blocker=True)
    assert select_best(tmp_path)["version"] == "v2"


# ---------------------------------------------------------------- math per versione
class _Ctx:
    def __init__(self, path: Path) -> None:
        self.project = Project(path)
        self.cfg = CFG


def _math_json(ctx: _Ctx, v: int, funcs: dict[str, str]) -> None:
    res = [{"id": k, "status": "accepted", "glsl": g} for k, g in funcs.items()]
    ctx.project.write(f"scenes/s1/v{v}.math.json", json.dumps({"results": res}))


def test_math_for_eredita_e_sovrascrive(tmp_path: Path) -> None:
    ctx = _Ctx(tmp_path)
    _math_json(ctx, 1, {"ease": "float ease(float t){return t;}", "sdf": "float sdf(float x){return x;}"})
    _math_json(ctx, 3, {"ease": "float ease(float t){return t*t;}"})
    assert "return t;" in steps.math_for(ctx, "s1", 2)  # v2 senza math eredita da v1
    m3 = steps.math_for(ctx, "s1", 3)
    assert "return t*t;" in m3 and "return t;}" not in m3 and "float sdf" in m3
    assert steps.math_for(ctx, "s2", 1) == ""


def test_compile_sources_con_line_directives(tmp_path: Path) -> None:
    ctx = _Ctx(tmp_path)
    common, scene = steps.compile_sources(ctx, "s1", 1, "void mainImage(out vec4 c, in vec2 p){}", "// style")
    assert f"#line 1 {steps.SRC_STYLE}\n// style" in common
    assert scene.startswith(f"#line 1 {steps.SRC_SCENE}\n")


def test_parse_compile_errors_smista_per_sorgente() -> None:
    errs = ["Error: Errore compilazione shader:\nERROR: 1:2: 'y' : undeclared identifier\n"
            "ERROR: 2:3: 'zzz' : undeclared identifier\nERROR: 0:40: 'q' : boh\n--- sorgente ---\nfloat x;"]
    ce = steps.parse_compile_errors(errs)
    assert ce.scene == ["line 3: 'zzz' : undeclared identifier"]
    assert ce.style == ["line 2: 'y' : undeclared identifier"]
    assert ce.other and "float x" not in " ".join(ce.other)
    # stesso risultato col marcatore inglese del player
    ce_en = steps.parse_compile_errors([errs[0].replace("--- sorgente ---", "--- source ---")])
    assert ce_en == ce


def test_errori_di_compilazione_rimappati_su_scena_e_style(harness, tmp_path: Path) -> None:
    ctx = _Ctx(tmp_path)
    spec = _spec()
    style = "vec3 finalize(vec3 c, vec2 uv) { return c; }\nfloat styleBad(float x) { return yy; }\n"
    src = "void mainImage(out vec4 c, in vec2 p) {\n  float a = 1.0;\n  c = vec4(zzz);\n}\n"
    common, scene = steps.compile_sources(ctx, "s1", 1, src, style)
    res = harness.load(steps.mono_payload(spec, "s1", scene, common))
    assert not res["ok"]
    ce = steps.parse_compile_errors(res["errors"])
    assert any(e.startswith("line 3:") and "zzz" in e for e in ce.scene), ce
    assert any(e.startswith("line 2:") and "yy" in e for e in ce.style), ce


def test_output_lint_fragcolor_mai_assegnato() -> None:
    # run reale (liminal-gate s3): `finalize(col, uv);` senza assegnare fragColor → scena nera
    src = "// fragColor nel commento non conta\nvec3 f(){return vec3(1.);}\n" \
          "void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n  vec3 col = f();\n  finalize(col, uv);\n}\n"
    msg = steps.output_lint(src)
    assert msg is not None and msg.startswith(f"ERROR: {steps.SRC_SCENE}:3:") and "fragColor" in msg
    ce = steps.parse_compile_errors([msg])
    assert ce.scene and "never assigns" in ce.scene[0]  # arriva al fixer come errore della scena
    for ok in ("void mainImage(out vec4 c, in vec2 p) { c = vec4(1.0); }",
               "void mainImage(out vec4 c, in vec2 p) { c.rgb = vec3(1.0); c.a = 1.0; }",
               "void mainImage(out vec4 c, in vec2 p) { shade(c, p); }",  # out passato a una funzione
               "float notMain(float x) { return x; }"):
        assert steps.output_lint(ok) is None, ok


def test_s4_scena_senza_fragcolor_va_al_fixer(harness, tmp_path: Path) -> None:
    from demogen.llm.fake import FAKE_STYLE, fake_client_factory

    pipe = Pipeline(Project(tmp_path / "p"), CFG, client_factory=fake_client_factory)
    pipe.project.write("style.glsl", FAKE_STYLE)
    # la scena del fixer finto usa una funzione che nel run vero arriva dall'oracolo
    _math_json(pipe, 1, {"ease_smooth": "float ease_smooth(float t) { return t * t * (3.0 - 2.0 * t); }"})
    src = ("void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n"
           "  vec3 col = vec3(0.5);\n  finalize(col, vec2(0.0));\n}\n")
    ok, fixed, errors = steps.s4_compile(pipe, harness, _spec(), "s1", src, 1)
    assert ok and not errors
    assert fixed != src and steps.output_lint(fixed) is None
    assert pipe.client("fixer").calls == ["fixer:s1"]


def test_costo_nel_prompt_di_revisione(tmp_path: Path) -> None:
    ctx = _Ctx(tmp_path)
    assert "not measured" in steps.cost_text(ctx, "s1", 1)
    for v, ratio in ((1, 3.45), (2, 8.8)):
        ctx.project.write(f"scenes/s1/v{v}.probe/metrics.json", json.dumps({"perf": {"ref_ratio_p95": ratio}}))
    within, over = steps.cost_text(ctx, "s1", 1), steps.cost_text(ctx, "s1", 2)
    assert "3.5x" in within and "do not exceed" in within
    assert "8.8x" in over and "OVER" in over
    user = steps.P.render("orchestrator_revise.md.j2", scene_id="s1", version=2, current_src="", critique_json="{}",
                          issues_text="-", history_text="-", math_rejections="-", cost_text=over)
    assert "8.8x the reference scene, OVER" in user


def test_scena_di_riferimento_misurabile(harness) -> None:
    from demogen.critic.perf_ref import add_ratios, measure_reference

    ref = measure_reference(harness, 160, 90, steps.LIB)
    assert ref > 0
    perf = add_ratios({"p95_ms": ref * 6, "mean_ms": ref * 2}, ref)
    assert perf["ref_ratio_p95"] == pytest.approx(6.0) and perf["ref_ratio_mean"] == pytest.approx(2.0)


# ---------------------------------------------------------------- S0 e spec
def _spec(**over) -> DemoSpec:
    d = _fake_spec("p", 8.0, 120.0, "modern")
    d.update(over)
    return DemoSpec.model_validate(d)


def test_s0_applica_i_flag_della_cli() -> None:
    spec = steps.apply_request(_spec(), "il mio prompt", 100.0, "retro", True)
    assert spec.prompt == "il mio prompt"
    assert spec.timeline.bpm == 100.0 and spec.profile == "retro" and spec.loop is True
    assert spec.duration_s == pytest.approx(steps.timeline_duration(spec))


def test_s0_tronca_la_timeline_a_120s() -> None:
    d = _fake_spec("p", 8.0, 120.0, "modern")
    d["timeline"]["scenes"] = [
        {"id": "s1", "start_bar": 0, "bars": 50, "transition_in": "cut", "transition_bars": 0},
        {"id": "s2", "start_bar": 50, "bars": 50, "transition_in": "crossfade", "transition_bars": 1},
    ]  # 100 bar a 120 bpm = 200 s
    spec = steps.apply_request(DemoSpec.model_validate(d), "p", 120.0, "modern", False)
    assert spec.duration_s <= 120.0
    assert steps.timeline_duration(spec) == pytest.approx(spec.duration_s)
    assert {s.id for s in spec.scenes} == {s.id for s in spec.timeline.scenes}


def test_demospec_slot_e_scene_coerenti() -> None:
    d = _fake_spec("p", 8.0, 120.0, "modern")
    d["timeline"]["scenes"][1]["id"] = "s9"
    with pytest.raises(ValidationError, match="same ids"):
        DemoSpec.model_validate(d)
    d = _fake_spec("p", 8.0, 120.0, "modern")
    d["timeline"]["scenes"][0]["bars"] = 0
    with pytest.raises(ValidationError):
        DemoSpec.model_validate(d)


# ---------------------------------------------------------------- S2 isolato per scena
class _ScriptedLLM(FakeLLM):
    """FakeLLM con risposte forzate per step (lista consumata in ordine) e registro chiamate."""

    log: list[str] = []
    script: dict[str, list[str]] = {}

    def _respond(self, step: str, prompt_hint: str = "") -> FakeResponse:
        _ScriptedLLM.log.append(step)
        queue = _ScriptedLLM.script.get(step)
        if queue:
            item = queue.pop(0)
            if item == "RAISE":
                raise RuntimeError(f"crash simulato in {step}")
            return FakeResponse(content=item)
        return super()._respond(step, prompt_hint)


def _scripted_factory(config=None, role: str = "orchestrator", **kw):
    return _ScriptedLLM(config, role, **kw)


@pytest.fixture
def scripted():
    _ScriptedLLM.log = []
    _ScriptedLLM.script = {}
    yield _ScriptedLLM
    _ScriptedLLM.script = {}


def test_s2_envelope_malformato_ritentato_e_isolato(tmp_path: Path, scripted) -> None:
    pipe = Pipeline(Project(tmp_path / "p"), CFG, client_factory=_scripted_factory)
    spec = _spec()
    scripted.script = {"draft:s2": ["nessun blocco qui"]}  # primo tentativo malformato, poi ok
    srcs = asyncio.run(steps.s2_draft(pipe, spec, ""))
    assert set(srcs) == {"s1", "s2"}
    assert scripted.log.count("draft:s2") == 2 and scripted.log.count("draft:s1") == 1

    # s2 sempre malformato: errore chiaro, s1 resta su disco e al giro dopo non viene rifatta
    pipe2 = Pipeline(Project(tmp_path / "q"), CFG, client_factory=_scripted_factory)
    scripted.log = []
    scripted.script = {"draft:s2": ["boh", "ancora boh"]}
    with pytest.raises(steps.PipelineError, match="s2"):
        asyncio.run(steps.s2_draft(pipe2, spec, ""))
    assert pipe2.project.exists("scenes/s1/v1.glsl")
    assert not pipe2.project.exists("scenes/s2/v1.glsl")
    scripted.log = []
    asyncio.run(steps.s2_draft(pipe2, spec, ""))
    assert scripted.log == ["draft:s2"]


class _PayingLLM(_ScriptedLLM):
    """Come _ScriptedLLM ma addebita 0.25 USD al budget della pipeline a ogni risposta."""

    def __init__(self, config=None, role: str = "orchestrator", **kw) -> None:
        super().__init__(config, role, **kw)
        self.budget = kw.get("budget")

    def _respond(self, step: str, prompt_hint: str = "") -> FakeResponse:
        if self.budget is not None:
            self.budget.add("m", 0, 0, 0.25)
        return super()._respond(step, prompt_hint)


def test_spesa_salvata_anche_se_la_pipeline_fallisce(tmp_path: Path, scripted) -> None:
    scripted.script = {"style": ["RAISE"]}
    proj = Project(tmp_path / "p")
    pipe = Pipeline(proj, CFG, client_factory=lambda c=None, r="orchestrator", **kw: _PayingLLM(c, r, **kw))
    with pytest.raises(RuntimeError, match="crash simulato"):
        pipe.run("x", duration_s=8, bpm=120)
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    # brief + style (pagato prima del crash): prima si salvava solo la spesa di S0
    assert state["budget_spent_usd"] == pytest.approx(0.5)
    assert Pipeline(proj, CFG, client_factory=_scripted_factory).budget.spent_usd == pytest.approx(0.5)


# ---------------------------------------------------------------- resume e revise (browser)
def test_resume_senza_nuove_chiamate_e_revise_max_piu_uno(tmp_path: Path, scripted) -> None:
    require_browser()
    proj = Project(tmp_path / "proj")
    # 1) crash simulato alla critica della scena 2
    scripted.script = {"critique:s2": ["RAISE"]}
    with pytest.raises(RuntimeError, match="crash simulato"):
        Pipeline(proj, CFG, client_factory=_scripted_factory).run("plasma 8s", duration_s=8, bpm=120)
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert state["request"]["prompt"] == "plasma 8s"
    assert state["scenes"].get("s1", {}).get("done") is True
    assert not state["scenes"].get("s2", {}).get("done")
    first_run = list(scripted.log)
    assert "critique:s1" in first_run

    # 2) resume: niente brief/style/draft né lavoro della scena 1
    scripted.log = []
    Pipeline(proj, CFG, client_factory=_scripted_factory).resume()
    assert scripted.log == ["critique:s2"], scripted.log
    state = json.loads((proj.path / "state.json").read_text(encoding="utf-8"))
    assert "S9" in state["done"] and "budget_spent_usd" in state

    # 3) secondo resume a progetto completo: zero chiamate
    scripted.log = []
    Pipeline(proj, CFG, client_factory=_scripted_factory).resume()
    assert scripted.log == []

    # 4) revise: nuova versione = massimo + 1, nessuna sovrascrittura
    sdir = proj.path / "scenes" / "s1"
    before = list_versions(sdir)
    Pipeline(proj, CFG, client_factory=_scripted_factory).run_revise("s1", "più contrasto")
    after = list_versions(sdir)
    assert after == before + [before[-1] + 1]
    meta = json.loads((sdir / f"v{after[-1]}.meta.json").read_text(encoding="utf-8"))
    assert meta["parent"] in before
