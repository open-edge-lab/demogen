"""Correzioni emerse dalla generazione reale del gatto 8-bit (5 s, 4 scene):
scena capovolta, scene incoerenti tra loro, critico senza palette, richieste dell'oracolo
rifiutate per l'annotazione del tipo, numeri non formattati nel report."""

from __future__ import annotations

import json
from pathlib import Path

from demogen.llm.fake import _fake_spec
from demogen.math.oracle import run_math_oracle
from demogen.orchestrator import prompts as P
from demogen.orchestrator.steps import style_api
from demogen.project.report import build_report
from demogen.spec.models import DemoSpec, MathRequest


def _spec() -> DemoSpec:
    d = _fake_spec("gatto 8-bit che salta", 8.0, 128.0, "modern")
    d["palette_hint"] = ["#2b2b2b", "#f3e9d2", "#f4a6b6", "#000000"]
    return DemoSpec.model_validate(d)


def test_il_contratto_spiega_che_y_va_verso_l_alto() -> None:
    text = P.system_prompt(128.0)
    assert "BOTTOM-left pixel and y grows UPWARD" in text
    assert "row = H - 1 - y" in text


def test_il_brief_permette_una_sola_scena_per_una_sequenza_continua() -> None:
    text = P.render("orchestrator_brief.md.j2", prompt="p", duration_s=5, bpm=128, profile="modern",
                    loop=True, schema_name="DemoSpec")
    assert "1..6 scenes" in text and "2..6 scenes" not in text
    assert "is ONE scene" in text and "described identically" in text


def test_la_scena_vede_palette_altre_scene_e_funzioni_dello_style() -> None:
    spec = _spec()
    scene = spec.scenes[0]
    for tmpl in ("orchestrator_scene_modern.md.j2", "orchestrator_scene_retro.md.j2"):
        text = P.render(tmpl, spec=spec, scene=scene, profile="modern", res=[1920, 1080], budget_p95=6.0,
                        budget_mean=4.0, max_ref_ratio=4.0, style_api="- `vec4 drawCat(vec2 p, float pose)`: x")
        assert "Palette: #2b2b2b, #f3e9d2, #f4a6b6, #000000" in text
        assert "do not redefine them; pass every argument exactly as its comment documents it" in text
        assert "\n- `vec4 drawCat(vec2 p, float pose)`: x" in text
        others = [s for s in spec.scenes if s.id != scene.id]
        if others:
            assert "Other scenes of the demo" in text
            assert all(f'- {s.id} "{s.title}"' in text for s in others)
            assert f'- {scene.id} "{scene.title}"' not in text


def test_scena_unica_senza_sezione_altre_scene() -> None:
    spec = _spec()
    one = spec.model_copy(update={"scenes": spec.scenes[:1]})
    text = P.render("orchestrator_scene_modern.md.j2", spec=one, scene=one.scenes[0], profile="modern",
                    res=[1920, 1080], budget_p95=6.0, budget_mean=4.0, max_ref_ratio=4.0, style_api="")
    assert "Other scenes" not in text and "Shared functions" not in text


def test_style_api_elenca_le_funzioni_condivise() -> None:
    style = """
// palette
const vec3 CREAM = vec3(0.95, 0.91, 0.82);

vec4 drawCat(vec2 p, float pose) {   // sprite del gatto
    return vec4(CREAM, 1.0);
}
/* float vecchia(float x) { return x; } */
float groundY(  float h ) { return h * 0.1; }
vec3 finalize(vec3 col, vec2 uv) { return toSRGB(col); }
"""
    assert style_api(style) == "- `vec4 drawCat(vec2 p, float pose)`: sprite del gatto\n- `float groundY(float h)`"
    assert style_api("") == ""


def test_style_api_porta_alla_scena_il_significato_dei_parametri() -> None:
    # run reale: la scena non vedeva il commento e passava (crouch, coda, blink, wiggle) dove lo style
    # voleva (crouch, salto, gambe, blink): niente coda, niente blink, gambe ferme
    style = """
// ---------------------------------------------------------------------------
// drawCat - the ONE chunky side-view pixel cat.
//   p : pixel coords, origin on the ground, +y = up.
//   A : (crouch 0..1, hop px, legSwing -1..1, blink 0/1)
// ---------------------------------------------------------------------------
vec4 drawCat(vec2 p,
             vec4 A) {
    return vec4(0.0);
}

/* blocco
   su piu righe */
// distanza punto-segmento
float segD(vec2 p, vec2 a, vec2 b) { return 0.0; }
"""
    api = style_api(style)
    assert api.splitlines() == [
        "- `vec4 drawCat(vec2 p, vec4 A)`: drawCat - the ONE chunky side-view pixel cat. p : pixel coords, "
        "origin on the ground, +y = up. A : (crouch 0..1, hop px, legSwing -1..1, blink 0/1)",
        "- `float segD(vec2 p, vec2 a, vec2 b)`: distanza punto-segmento",
    ]
    long_doc = "// " + "x" * 2000 + "\nfloat f(float a) { return a; }"
    assert len(style_api(long_doc)) < 700 and style_api(long_doc).endswith("...")


def test_colori_retro_in_spazio_display() -> None:
    # run reale: drawCat restituiva colori lineari (srgb2lin) in una scena retro, retroFinalize li
    # quantizzava sulla voce sbagliata della palette: corpo nero invece di grigio, petto rosa invece di crema
    contract = P.system_prompt(128.0)
    assert "never convert them to linear" in contract
    spec = _spec()
    retro = P.render("orchestrator_scene_retro.md.j2", spec=spec, scene=spec.scenes[0], profile="retro",
                     res=[320, 180], budget_p95=1.0, budget_mean=0.5, max_ref_ratio=4.0, style_api="")
    assert "fragColor = vec4(finalize(col, uv), 1.0);" in retro and "do not call retroFinalize" in retro
    scenes = [spec.scenes[0].model_copy(update={"profile": "retro"}), *spec.scenes[1:]]
    style = P.render("orchestrator_style.md.j2", title=spec.title, art_direction=spec.art_direction,
                     palette_hint="-", profile="modern", bpm=128, scenes=scenes)
    assert f'- {scenes[0].id} "{scenes[0].title}" (retro profile):' in style
    assert all(f'- {s.id} "{s.title}" (modern profile):' in style for s in scenes[1:])
    assert "never `srgb2lin`/`pow(c, 2.2)`" in style
    assert "documents each parameter" in style and "the scenes see only the signature and that comment" in style


def test_lo_style_riceve_le_scene_per_condividere_il_soggetto() -> None:
    spec = _spec()
    text = P.render("orchestrator_style.md.j2", title=spec.title, art_direction=spec.art_direction,
                    palette_hint="-", profile="modern", bpm=128, scenes=spec.scenes)
    assert all(f'- {s.id} "{s.title}"' in text for s in spec.scenes)
    assert "define ONE function here that draws it" in text


def test_il_critico_controlla_orientamento_e_palette() -> None:
    spec = _spec()
    text = P.render("critic_scene.md.j2", scene=spec.scenes[0], art_direction="pixel art, side view",
                    palette_hint="#2b2b2b, #f3e9d2", metrics_json="{}")
    assert "Demo art direction: pixel art, side view" in text and "Palette hint: #2b2b2b, #f3e9d2" in text
    assert "nothing upside down" in text and "an upside-down subject or a different palette is a major issue" in text


def test_oracolo_accetta_il_tipo_annotato_come_lo_scrivono_i_modelli() -> None:
    # run reale: {"x": "float in [0,1]"} rifiutato con "inputs must be float"
    req = MathRequest(id="ease_out", kind="easing", description="", expr="1.0 - (1.0 - x) ** 2",
                      inputs={"x": "float in [0,1]"}, claim={"domain": [[0, 1]]})
    r = run_math_oracle([req])
    assert [x.status for x in r.results] == ["accepted"], r.results
    bad = MathRequest(id="v", kind="identity", description="", expr="x - x", inputs={"x": "vec2"},
                      claim={"domain": [[0, 1]]})
    assert run_math_oracle([bad]).results[0].reason.startswith("inputs must be float")


def test_report_con_numeri_formattati(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    spec = _spec().model_dump()
    spec["duration_s"] = 5.0000625
    (proj / "audio").mkdir(parents=True)
    (proj / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (proj / "state.json").write_text(json.dumps({"done": ["S9"], "budget_spent_usd": 0.3391}), encoding="utf-8")
    (proj / "audio" / "best.json").write_text('{"version": "v1"}', encoding="utf-8")
    (proj / "audio" / "v1.metrics.json").write_text(json.dumps(
        {"rms": 0.065, "peak": 0.483, "realtime_factor": 55.5123,
         "onset_vs_beat": {"mean_abs_err_ms": 1.80070088641515}}), encoding="utf-8")
    text = build_report(proj)
    assert "- duration: 5 s, bpm 128," in text
    assert "mean error 1.8 ms" in text and "render speed 56x realtime" in text


def test_loop_senza_flag_lo_decide_il_prompt() -> None:
    from demogen.orchestrator import steps

    spec = _spec()
    spec.loop = True  # l'LLM ha letto "seamless loop" nel prompt
    assert steps.apply_request(spec.model_copy(deep=True), "p", 128.0, "modern", None).loop is True
    assert steps.apply_request(spec.model_copy(deep=True), "p", 128.0, "modern", False).loop is False
    spec.loop = False
    assert steps.apply_request(spec.model_copy(deep=True), "p", 128.0, "modern", True).loop is True


def test_brief_con_loop_libero_o_imposto() -> None:
    free = P.render("orchestrator_brief.md.j2", prompt="p", duration_s=5, bpm=128, profile="modern",
                    loop=None, schema_name="DemoSpec")
    assert "loop: your choice" in free and "loop=None" not in free
    forced = P.render("orchestrator_brief.md.j2", prompt="p", duration_s=5, bpm=128, profile="modern",
                      loop=False, schema_name="DemoSpec")
    assert "loop=False" in forced and "loop: your choice" not in forced


def test_menu_passa_loop_solo_se_scelto(monkeypatch) -> None:
    from demogen import menu

    seen: list[list[str]] = []
    monkeypatch.setattr(menu, "run_cli", lambda args: seen.append(args) or True)
    monkeypatch.setattr(menu, "open_project_demo", lambda ui, p: None)
    monkeypatch.setattr(menu, "_GPU", "x")
    for choice, flag in (("auto", None), ("yes", "--loop"), ("no", "--no-loop")):
        ui = menu.Ui(interactive=False)
        monkeypatch.setattr(ui, "ask", lambda label, default="", c=choice: c if label.startswith("loop") else default)
        assert menu.do_generate(ui, fake=True)
        args = seen.pop()
        assert ("--loop" in args, "--no-loop" in args) == (flag == "--loop", flag == "--no-loop")
