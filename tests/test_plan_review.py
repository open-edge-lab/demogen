"""Revisione del piano prima di disegnare (`generate --review-plan`, `demogen plan`) e anteprima di una
scena di un progetto (`demogen play <progetto> --scene s1`), anche a generazione in corso."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from demogen.cli import app
from demogen.config import Config
from demogen.llm.fake import FAKE_SCENE, FAKE_STYLE, FakeLLM, _fake_spec
from demogen.orchestrator import plan as P
from demogen.orchestrator.pipeline import Pipeline
from demogen.orchestrator.preview import scene_preview_payload, scene_versions
from demogen.project.store import Project
from demogen.spec.models import DemoSpec
from tests.conftest import require_browser

EASE = "float ease_smooth(float x) { return x * x * (3.0 - 2.0 * x); }"


def _recording_factory(log: list[tuple[str, list[dict]]]):
    """FakeLLM che registra step e messaggi di ogni chiamata."""

    def factory(config=None, role: str = "orchestrator", **kw):
        c = FakeLLM(config, role, **kw)
        orig = c.chat

        def chat(messages, *, step: str = "", **k):
            log.append((step, messages))
            return orig(messages, step=step, **k)

        c.chat = chat  # achat passa da self.chat
        return c

    return factory


def _pipe(proj: Project, log: list) -> Pipeline:
    cfg = Config.model_validate({"providers": {}, "roles": {}})
    return Pipeline(proj, cfg, gpu="swiftshader", client_factory=_recording_factory(log))


def _paused_project(tmp_path: Path, profile: str = "modern") -> tuple[Project, list]:
    log: list = []
    proj = Project(tmp_path / "p")
    _pipe(proj, log).run("gatto 8-bit che caccia", duration_s=8, bpm=120, profile=profile, audio=False,
                         pause_after_plan=True)
    return proj, log


def _spec() -> DemoSpec:
    return DemoSpec.model_validate(_fake_spec("plasma", 8.0, 120.0, "modern"))


# ---------------------------------------------------------------- testo del piano
def test_il_piano_si_legge_con_tempi_e_scene_in_ordine() -> None:
    spec = _spec()
    spec.text = "HELLO"
    text = P.format_plan(spec)
    assert text.startswith('PLAN  "Fake Demo"')
    assert "8 s · 120 BPM · style modern · loop no · 2 scenes" in text
    assert "palette: #ff00ff, #00ffff" in text and 'text: "HELLO"' in text
    # run reale: voci con il nome del colore, unite da spazi sembravano assegnare il nome al colore prima
    spec.palette_hint = ["#0e3a3a", "cream #f2e8c9"]
    assert "palette: #0e3a3a, cream #f2e8c9" in P.format_plan(spec)
    assert "s1   Plasma\n      0.0–4.0 s  (bars 0–2, in: cut)" in text
    assert "s2   Plasma variant\n      4.0–8.0 s  (bars 2–4, in: crossfade 1 bar)" in text
    assert "      what you see: colorful plasma pulsing on the beat" in text
    assert text.index("s1   Plasma") < text.index("s2   Plasma variant")
    assert max(len(line) for line in text.splitlines()) <= 100


def test_modifica_di_una_scena_e_campi_non_validi() -> None:
    spec = P.edit_scene(_spec(), "s2", description=" a black cat sleeping ", title=None)
    assert spec.scenes[1].description == "a black cat sleeping" and spec.scenes[1].title == "Plasma variant"
    with pytest.raises(P.PlanError, match="does not exist"):
        P.edit_scene(_spec(), "s9", title="x")
    with pytest.raises(P.PlanError, match="nothing to change"):
        P.edit_scene(_spec(), "s1")
    with pytest.raises(P.PlanError, match="cannot be empty"):
        P.edit_scene(_spec(), "s1", title="  ")
    with pytest.raises(P.PlanError, match="only title"):
        P.edit_scene(_spec(), "s1", palette="#000")


# ---------------------------------------------------------------- pausa e nota
def test_generate_si_ferma_dopo_il_piano(tmp_path: Path) -> None:
    proj, log = _paused_project(tmp_path)
    assert [step for step, _ in log] == ["brief"]  # una sola chiamata: niente style né scene
    state = proj.load_state()
    assert state["paused"] == "plan" and state["done"] == ["S0"]
    assert proj.exists("spec.json") and not proj.exists("style.glsl")
    assert not list((proj.path / "scenes").rglob("*.glsl"))
    assert P.is_paused_for_plan(proj.path) and "pause_after_plan" not in state["request"]


def test_la_nota_riscrive_il_piano_con_i_flag_dell_utente(tmp_path: Path) -> None:
    proj, log = _paused_project(tmp_path, profile="retro")
    spec = _pipe(proj, log).replan("the cat is black")
    assert spec.scenes[0].description.endswith("(the cat is black)")
    assert spec.profile == "retro" and all(s.profile is None for s in spec.scenes)
    step, msgs = log[-1]
    assert step == "brief:replan"
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert "Change requested by the user: the cat is black" in msgs[-1]["content"]
    assert json.loads(msgs[2]["content"])["scenes"][0]["id"] == "s1"  # il piano precedente
    assert P.load_plan(proj).scenes[0].description.endswith("(the cat is black)")
    assert proj.load_state()["paused"] == "plan"


def test_il_piano_non_si_cambia_dopo_lo_style(tmp_path: Path) -> None:
    proj, log = _paused_project(tmp_path)
    state = proj.load_state()
    state["done"] = ["S0", "S1"]
    proj.save_state(state)
    with pytest.raises(P.PlanError, match="already in use"):
        P.edit_plan(proj, "s1", title="x")
    with pytest.raises(P.PlanError, match="already in use"):
        _pipe(proj, log).replan("x")
    assert [step for step, _ in log] == ["brief"]  # nessuna chiamata spesa


def test_resume_disegna_il_piano_cambiato(tmp_path: Path) -> None:
    require_browser()
    proj, log = _paused_project(tmp_path)
    P.edit_plan(proj, "s1", description="a black cat crouching in the grass")
    spec = _pipe(proj, log).resume()
    state = proj.load_state()
    assert "paused" not in state and "S9" in state["done"]
    assert spec.scenes[0].description == "a black cat crouching in the grass"
    steps = [step for step, _ in log]
    assert steps.count("brief") == 1  # il piano non è stato riscritto
    draft = next(msgs for step, msgs in log if step == "draft:s1")
    style = next(msgs for step, msgs in log if step == "style")
    assert "a black cat crouching in the grass" in draft[-1]["content"]
    assert "a black cat crouching in the grass" in style[-1]["content"]
    assert list((proj.path / "out").glob("*.html"))


# ---------------------------------------------------------------- CLI
def test_cli_generate_review_plan_e_comando_plan(tmp_path: Path) -> None:
    p = tmp_path / "p"
    run = CliRunner().invoke
    res = run(app, ["generate", "plasma", "--duration", "8", "--bpm", "120", "--fake", "--no-music",
                    "--review-plan", "--plain", "--project", str(p)])
    assert res.exit_code == 0, res.output
    assert 'PLAN  "Fake Demo"' in res.output and f"continue with: demogen resume {p}" in res.output
    assert not (p / "style.glsl").exists()

    res = run(app, ["plan", str(p), "--scene", "s2", "--title", "Sleeping cat"])
    assert res.exit_code == 0, res.output
    assert "plan updated: title of s2" in res.output and "s2   Sleeping cat" in res.output
    res = run(app, ["plan", str(p), "--no-hints"])  # dal menu: i comandi successivi li offre il menu
    assert res.exit_code == 0 and 'PLAN  "Fake Demo"' in res.output and "demogen resume" not in res.output

    res = run(app, ["plan", str(p), "--note", "more contrast", "--fake"])
    assert res.exit_code == 0, res.output
    assert "(more contrast)" in res.output

    assert run(app, ["plan", str(p), "--title", "x"]).exit_code != 0  # manca --scene
    assert run(app, ["plan", str(p), "--scene", "s1"]).exit_code != 0  # niente da cambiare
    assert run(app, ["plan", str(p), "--scene", "s1", "--title", "x", "--note", "y"]).exit_code != 0
    res = run(app, ["plan", str(p), "--scene", "s7", "--title", "x"])
    assert res.exit_code == 1 and "does not exist" in res.output

    state = json.loads((p / "state.json").read_text(encoding="utf-8"))
    state["done"] = ["S0", "S1"]
    (p / "state.json").write_text(json.dumps(state), encoding="utf-8")
    res = run(app, ["plan", str(p)])
    assert res.exit_code == 0 and "the drawing has started" in res.output
    res = run(app, ["plan", str(p), "--scene", "s1", "--title", "x"])
    assert res.exit_code == 1 and "already in use" in res.output


# ---------------------------------------------------------------- anteprima
def _drawn_project(tmp_path: Path) -> Path:
    """Progetto a metà: s1 con due versioni (best v1), s2 ancora senza shader."""
    root = tmp_path / "drawn"
    proj = Project(root)
    proj.write("spec.json", _spec().model_dump_json())
    proj.save_state({"done": ["S0", "S1", "S2"], "scenes": {}})
    proj.write("style.glsl", FAKE_STYLE)
    proj.write("post.json", json.dumps({"bloom": {"threshold": 0.8, "intensity": 0.4}}))
    proj.write("scenes/s1/v1.glsl", FAKE_SCENE)
    proj.write("scenes/s1/v1.math.json", json.dumps({"results": [
        {"id": "ease_smooth", "status": "accepted", "glsl": EASE}]}))
    proj.write("scenes/s1/v2.glsl", FAKE_SCENE.replace("6.0", "3.0"))
    proj.write("scenes/s1/best.json", json.dumps({"version": "v1", "score": 8.0}))
    return root


def test_anteprima_di_una_scena_del_progetto(tmp_path: Path) -> None:
    root = _drawn_project(tmp_path)
    before = sorted(str(f) for f in root.rglob("*"))
    table = {sv.id: sv for sv in scene_versions(root)}
    assert (table["s1"].versions, table["s1"].best, table["s1"].default) == ([1, 2], 1, 1)
    assert table["s2"].versions == [] and table["s2"].default is None

    payload, v = scene_preview_payload(root, "s1")
    assert v == 1 and payload["meta"]["loop"] is True and payload["meta"]["title"] == "Fake Demo: s1 v1"
    assert "vec3 finalize(" in payload["common"] and EASE in payload["scenes"]["s1"]  # style e oracolo
    assert payload["post"] == {"bloom": {"threshold": 0.8, "intensity": 0.4}}
    payload2, v2 = scene_preview_payload(root, "s1", 2)
    assert v2 == 2 and "beatPulse(uBeatPhase, 3.0)" in payload2["scenes"]["s1"]

    with pytest.raises(P.PlanError, match="no shader yet"):
        scene_preview_payload(root, "s2")
    with pytest.raises(P.PlanError, match="has no v5"):
        scene_preview_payload(root, "s1", 5)
    with pytest.raises(P.PlanError, match="choose a scene with --scene"):
        scene_preview_payload(root, "")
    assert sorted(str(f) for f in root.rglob("*")) == before  # l'anteprima non scrive nel progetto


def test_anteprima_compila_nel_browser(harness, tmp_path: Path) -> None:
    payload, _ = scene_preview_payload(_drawn_project(tmp_path), "s1")
    res = harness.load(payload)
    assert res["ok"], "\n".join(res["errors"])[:800]


def test_play_di_un_progetto_senza_scena_elenca_le_scene(tmp_path: Path) -> None:
    res = CliRunner().invoke(app, ["play", str(_drawn_project(tmp_path)), "--headless"])
    assert res.exit_code == 1
    assert "choose a scene with --scene" in res.output
    assert "s1  Plasma: v1, v2 (best v1)" in res.output and "s2  Plasma variant: no shader yet" in res.output
