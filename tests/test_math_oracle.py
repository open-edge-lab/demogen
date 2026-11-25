"""Fase 6 — oracolo matematico: safe_parse, verify, codegen, oracle E2E."""

from __future__ import annotations

import pytest

from demogen.math import (
    UnsafeExpressionError,
    codegen_glsl,
    parse_safe,
    run_math_oracle,
    verify_claim,
)
from demogen.spec.models import MathRequest

# ---------------------------------------------------------------- safe_parse

@pytest.mark.parametrize("expr", [
    "sin(x) + cos(y) * 2.0",
    "len2(x, y) - 1.0",
    "pow(x, 2.0) + pow(y, 2.0)",
    "clamp(x, 0.0, 1.0) * t",
    "mix(0.0, 1.0, t) - pi / 2.0",
    "-x + +y",
])
def test_parse_safe_accetta_valide(expr: str) -> None:
    parse_safe(expr)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo pwned')",
    "().__class__.__bases__",
    "lambda: 1",
    "x[0]",
    "x.y",
    "open('/etc/passwd')",
    "f'{x}'",
    "x if y else z",
    "[x for x in range(3)]",
    "eval('1+1')",
    "x; import os",
    "",
])
def test_parse_safe_rifiuta_malevoli(expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        parse_safe(expr)


def test_eval_points_subprocess_isolato() -> None:
    from demogen.math.safe_parse import eval_points
    vals = eval_points("x * 2.0 + 1.0", [{"x": 1.0}, {"x": 2.0}])
    assert vals == [3.0, 5.0]
    # dominio: sqrt di negativo -> None, non crash
    vals = eval_points("sqrt(x)", [{"x": -1.0}, {"x": 4.0}])
    assert vals[0] is None and vals[1] == 2.0


# ---------------------------------------------------------------- verify

def req(kind: str, expr: str, claim: dict, inputs: dict | None = None) -> MathRequest:
    return MathRequest(
        id="t", kind=kind, description="test", expr=expr, claim=claim,
        inputs=inputs or {"x": "float", "y": "float", "t": "float"},
    )


def test_verify_sdf_cerchio_esatto_accettato() -> None:
    # SDF del cerchio: |grad| = 1 e segno corretto (negativo dentro)
    r = verify_claim(req("sdf", "len2(x, y) - 1.0", {"domain": [[-2, 2], [-2, 2]], "samples": 48}))
    assert r.ok, r.detail


def test_verify_sdf_errore_segno_rifiutato() -> None:
    # len2(x,y) è sempre >= 0: niente regione negativa -> non è una SDF con dentro negativo
    r = verify_claim(req("sdf", "len2(x, y)", {"domain": [[-2, 2], [-2, 2]], "samples": 48}))
    assert not r.ok


@pytest.mark.xfail(strict=True, reason="review #32 (batch G): verify lega solo x,y,t; SDF 3D non verificabili")
def test_verify_sdf_toro_3d_accettato() -> None:
    # toro 3D (raggio maggiore 2, minore 0.5): SDF esatta, |grad| = 1
    expr = "len2(len2(x, y) - 2.0, z) - 0.5"
    r = verify_claim(req("sdf", expr, {"domain": [[-3, 3], [-3, 3], [-1, 1]], "samples": 48},
                         inputs={"x": "float", "y": "float", "z": "float"}))
    assert r.ok, r.detail


def test_verify_lipschitz_seno_accetta_bound_1_rifiuta_05() -> None:
    claim = {"bound": 1.0, "domain": [[-3.14, 3.14]], "samples": 40, "tol": 1e-3}
    r = verify_claim(req("lipschitz", "sin(x)", claim, inputs={"x": "float"}))
    assert r.ok, r.detail
    claim2 = {**claim, "bound": 0.5}
    r2 = verify_claim(req("lipschitz", "sin(x)", claim2, inputs={"x": "float"}))
    assert not r2.ok


def test_verify_periodic_path_accetta_T_giusto_rifiuta_sbagliato() -> None:
    claim = {"period": 16.0, "domain": [[0.0, 16.0]], "tol": 1e-6, "samples": 32}
    expr = "sin(tau * t / 16.0)"
    r = verify_claim(req("periodic_path", expr, claim, inputs={"t": "float"}))
    assert r.ok, r.detail
    r2 = verify_claim(req("periodic_path", expr, {**claim, "period": 8.0}, inputs={"t": "float"}))
    assert not r2.ok


def test_verify_easing_accetta_e_rifiuta() -> None:
    claim = {"domain": [[0.0, 1.0]], "tol": 1e-9}
    r = verify_claim(req("easing", "t * t * (3.0 - 2.0 * t)", claim, inputs={"t": "float"}))
    assert r.ok, r.detail
    r2 = verify_claim(req("easing", "t", {**claim, "tol": 1e-9}, inputs={"t": "float"}))
    assert r2.ok  # identidad también è easing valida (f(0)=0, f(1)=1, monotona)
    r3 = verify_claim(req("easing", "t * 2.0", claim, inputs={"t": "float"}))
    assert not r3.ok  # f(1) = 2 != 1


def test_verify_identity_accetta_rifiuta() -> None:
    claim = {"domain": [[-2, 2], [-2, 2]], "tol": 1e-9, "samples": 32}
    r = verify_claim(req("identity", "pow(sin(x), 2.0) + pow(cos(x), 2.0) - 1.0", claim))
    assert r.ok, r.detail
    r2 = verify_claim(req("identity", "sin(x)", claim))
    assert not r2.ok


# ---------------------------------------------------------------- codegen

def test_codegen_glsl() -> None:
    glsl = codegen_glsl("mySdf", "len2(x, y) - r", ["r", "x", "y"])
    assert "float mySdf(float r, float x, float y)" in glsl
    assert "length(vec2(x, y))" in glsl
    assert "pow(" in codegen_glsl("p", "pow(x, 2.0)", ["x"])
    assert "mod(" in codegen_glsl("m", "mod(x, 2.0)", ["x"])
    assert "3.14" in codegen_glsl("c", "pi", [])


def test_codegen_rifiuta_param_mancanti() -> None:
    with pytest.raises(ValueError):
        codegen_glsl("f", "x + y", ["x"])  # y non tra i params


# ---------------------------------------------------------------- oracle E2E

def test_oracle_accetta_veri_rifiuta_falsi_e_malevoli() -> None:
    requests = [
        MathRequest(id="sdf_cerchio", kind="sdf", description="cerchio r=1",
                    expr="len2(x, y) - 1.0", claim={"domain": [[-2, 2], [-2, 2]], "samples": 48},
                    inputs={"x": "float", "y": "float"}),
        MathRequest(id="sdf_falso", kind="sdf", description="segno sbagliato",
                    expr="len2(x, y)", claim={"domain": [[-2, 2], [-2, 2]], "samples": 48},
                    inputs={"x": "float", "y": "float"}),
        MathRequest(id="periodo", kind="periodic_path", description="loop 16s",
                    expr="sin(tau * t / 16.0)", claim={"period": 16.0, "domain": [[0, 16]], "samples": 24},
                    inputs={"t": "float"}),
        MathRequest(id="malevolo", kind="identity", description="tentativo",
                    expr="__import__('os')", claim={}, inputs={}),
        MathRequest(id="kind_ignoto", kind="fourier", description="non verificabile",
                    expr="sin(t)", claim={}, inputs={"t": "float"}),
    ]
    res = run_math_oracle(requests)
    by_id = {r.id: r for r in res.results}
    assert by_id["sdf_cerchio"].status == "accepted"
    assert by_id["periodo"].status == "accepted"
    assert by_id["sdf_falso"].status == "rejected"
    assert "falso" in by_id["sdf_falso"].reason or "segno" in by_id["sdf_falso"].reason
    assert by_id["malevolo"].status == "rejected"
    assert "non sicura" in by_id["malevolo"].reason
    assert by_id["kind_ignoto"].status == "rejected"
    assert "sdf_cerchio" in res.math_glsl and "periodo" in res.math_glsl
    assert "sdf_falso" not in res.math_glsl and "malevolo" not in res.math_glsl
