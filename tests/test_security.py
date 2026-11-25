"""Batch C: iniezione HTML nel bundle, path confinati, runner dell'oracolo isolato, clamp dei claim."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from demogen.bundle.build import build_payload_from_sources, write_bundle
from demogen.math.safe_parse import eval_points
from demogen.math.verify import verify_claim
from demogen.project.store import Project, slugify
from demogen.spec.models import MathRequest, SceneBrief, SceneSlot

EVIL = "</script><script>window.__pwned=1</script><!--"
SCENE = "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }\n"


def _payload(title: str, text: str | None) -> dict:
    spec = {
        "name": title,
        "bpm": 120,
        "beats_per_bar": 4,
        "text": text,
        "scenes": [{"id": "s1", "start_bar": 0, "bars": 1, "transition_in": "cut", "transition_bars": 0}],
    }
    return build_payload_from_sources(spec, {"s1": SCENE}, do_minify=False)


def test_bundle_html_non_iniettabile(tmp_path: Path) -> None:
    payload = _payload(f"titolo {EVIL}", EVIL)
    sizes = write_bundle(payload, tmp_path / "out", "demo")
    html = Path(sizes["paths"]["html"]).read_text(encoding="utf-8")
    # 3 script legittimi: player, payload, bootstrap. Nessuno in più dal payload.
    assert html.count("<script") == 3
    assert html.lower().count("</script") == 3
    assert "<!--" not in html
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    assert m and "<" not in m.group(1)
    # il payload incorporato resta JSON valido e identico
    blob = html.split("const PAYLOAD=", 1)[1].split(";</script>", 1)[0]
    assert json.loads(blob) == payload


def test_bundle_nome_file_confinato(tmp_path: Path) -> None:
    payload = _payload("x", None)
    out = tmp_path / "out"
    sizes = write_bundle(payload, out, "../../evil:ads")
    for p in sizes["paths"].values():
        assert Path(p).resolve().parent == out.resolve()
        assert ":" not in Path(p).name


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Plasma Tunnel!", "plasma-tunnel"),
        ("../x:ads", "x-ads"),
        ("CON", "demo-con"),
        ("nul", "demo-nul"),
        ("com1", "demo-com1"),
        ("", "demo"),
        ("///", "demo"),
    ],
)
def test_slugify(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_project_path_confinato(tmp_path: Path) -> None:
    proj = Project(tmp_path / "p")
    proj.write("scenes/s1/v1.glsl", "x")
    assert proj.exists("scenes/s1/v1.glsl")
    assert proj.read("scenes/s1/v1.glsl") == "x"
    for bad in ("../fuori.txt", "scenes/../../fuori.txt", str(tmp_path / "abs.txt")):
        with pytest.raises(ValueError):
            proj.write(bad, "x")
        with pytest.raises(ValueError):
            proj.read(bad)
    assert not (tmp_path / "fuori.txt").exists()


@pytest.mark.parametrize("bad", ["../x", "a/b", "s 1", "", "x" * 33, "c:ads"])
def test_id_scena_validato(bad: str) -> None:
    with pytest.raises(ValidationError):
        SceneSlot(id=bad, start_bar=0, bars=1)
    with pytest.raises(ValidationError):
        SceneBrief(id=bad, title="t", description="d", motion="m")


def test_runner_oracolo_isolato_da_cwd(tmp_path: Path, monkeypatch) -> None:
    """Un json.py nella cartella corrente non deve essere importato dal runner (-I)."""
    (tmp_path / "json.py").write_text("raise SystemExit('json.py planted importato')\n", encoding="utf-8")
    (tmp_path / "math.py").write_text("raise SystemExit('math.py planted importato')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert eval_points("x + 1", [{"x": 1.0}, {"x": 2.0}]) == [2.0, 3.0]


def _req(kind: str, expr: str, claim: dict, inputs: dict | None = None) -> MathRequest:
    return MathRequest(id="t", kind=kind, description="test", expr=expr, claim=claim,
                       inputs=inputs or {"x": "float", "y": "float"})


def test_claim_samples_enormi_clampati_senza_oom() -> None:
    t0 = time.monotonic()
    r = verify_claim(_req("identity", "x - x", {"domain": [[-1, 1], [-1, 1]], "samples": 1e8}))
    assert r.ok
    assert r.n_samples <= 4096
    assert time.monotonic() - t0 < 30


@pytest.mark.parametrize(
    "claim",
    [
        {"tol": math.inf},
        {"tol": float("nan")},
        {"tol": -1.0},
        {"tol_grad": math.inf},
        {"domain": [[0, math.inf]]},
        {"domain": [[1, 0]]},
        {"domain": [[0, 1]] * 5},
        {"domain": [[0, 1e9]]},
        {"domain": "boom"},
        {"samples": "molti"},
    ],
)
def test_claim_parametri_non_validi_rifiutati(claim: dict) -> None:
    with pytest.raises(ValueError):
        verify_claim(_req("identity", "x - x", claim))


def test_claim_tol_largo_clampato() -> None:
    # tol=1e9 farebbe passare qualsiasi identità: viene ridotto a 1e-2
    r = verify_claim(_req("identity", "x", {"domain": [[-1, 1], [-1, 1]], "tol": 1e9, "samples": 16}))
    assert not r.ok


def test_lipschitz_bound_infinito_rifiutato() -> None:
    with pytest.raises(ValueError):
        verify_claim(_req("lipschitz", "sin(x)", {"bound": math.inf, "domain": [[-3, 3]]}))
