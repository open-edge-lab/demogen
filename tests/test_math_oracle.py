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
    r = verify_claim(req("identity", "sin(x)**2 + cos(x)**2 - 1.0", claim))
    assert r.ok, r.detail
    r2 = verify_claim(req("identity", "sin(x)", claim))
    assert not r2.ok
    # pow con base negativa è indefinito in GLSL: il claim su sin(x) < 0 non può passare
    r3 = verify_claim(req("identity", "pow(sin(x), 2.0) + pow(cos(x), 2.0) - 1.0", claim))
    assert not r3.ok and "punti valutati" in r3.detail


# ---------------------------------------------------------------- batch G: verifica più severa

def test_verify_sdf_invertita_rifiutata() -> None:
    # 1 - |p| ha entrambi i segni e |grad| = 1, ma è negativa FUORI: non è una SDF con dentro negativo
    r = verify_claim(req("sdf", "1.0 - len2(x, y)", {"domain": [[-2, 2], [-2, 2]], "samples": 48},
                         inputs={"x": "float", "y": "float"}))
    assert not r.ok and "bordo>0: False" in r.detail


def test_verify_sdf_punto_inside() -> None:
    claim = {"domain": [[-2, 2], [-2, 2]], "samples": 48, "inside": [0.0, 0.0]}
    assert verify_claim(req("sdf", "len2(x, y) - 1.0", claim, inputs={"x": "float", "y": "float"})).ok
    claim["inside"] = [1.5, 0.0]  # fuori dal cerchio: il claim sul punto interno è falso
    assert not verify_claim(req("sdf", "len2(x, y) - 1.0", claim, inputs={"x": "float", "y": "float"})).ok


def test_verify_lipschitz_senza_punti_valutati_rifiutato() -> None:
    # sqrt di un argomento sempre negativo: nessun punto si valuta (prima: max_ratio=0 → accettato)
    r = verify_claim(req("lipschitz", "sqrt(-1.0 - x * x)", {"bound": 1.0, "domain": [[-1, 1]]},
                         inputs={"x": "float"}))
    assert not r.ok and "punti valutati" in r.detail


def test_verify_lipschitz_coppie_vicine() -> None:
    # sin(10x) ha costante 10: con coppie lontane e casuali la pendenza veniva sottostimata
    claim = {"bound": 9.0, "domain": [[-3, 3]], "samples": 64}
    assert not verify_claim(req("lipschitz", "sin(10.0 * x)", claim, inputs={"x": "float"})).ok
    assert verify_claim(req("lipschitz", "sin(10.0 * x)", {**claim, "bound": 10.0},
                            inputs={"x": "float"})).ok


def test_verify_un_solo_punto_valido_rifiutato() -> None:
    # valida solo per x >= 1.99: quasi tutti i punti falliscono → rifiuto
    r = verify_claim(req("identity", "sqrt(x - 1.99) * 0.0", {"domain": [[-2, 2]], "samples": 32},
                         inputs={"x": "float"}))
    assert not r.ok


@pytest.mark.parametrize("expr", [
    "min(x, y, t)",  # arità sbagliata (Python la accetterebbe)
    "len2(x)",
    "len2(x, y, 0.0)",
    "log(x, 2.0)",
    "sin + 1.0",  # funzione usata come valore
    "out + 1.0",  # nome riservato GLSL
    "gl_FragCoord + 1.0",
    "a__b + 1.0",
    "x ** 0.5",  # ** solo con esponente 2..4
    "x ** y",
    "True + x",
])
def test_parse_safe_rifiuta_arita_e_nomi(expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        parse_safe(expr)


def test_semantica_python_come_glsl() -> None:
    from demogen.math.safe_parse import eval_points

    # mod floored come GLSL (fmod darebbe -1.5)
    assert eval_points("mod(x, 2.0)", [{"x": -1.5}]) == [pytest.approx(0.5)]
    # smoothstep con estremi invertiti: formula GLSL (prima: 0 per ogni v <= a)
    assert eval_points("smoothstep(1.0, 0.0, x)", [{"x": 0.25}]) == [pytest.approx(1 - 0.15625)]
    # pow con base negativa: indefinito in GLSL → None
    assert eval_points("pow(x, 2.0)", [{"x": -2.0}]) == [None]
    assert eval_points("x ** 2", [{"x": -2.0}]) == [4.0]
    assert eval_points("atan2(y, x)", [{"x": -1.0, "y": 0.0}]) == [pytest.approx(3.14159265)]


def test_codegen_costrutti_glsl_validi() -> None:
    g = codegen_glsl("f", "x % 2.0 + atan2(y, x) + dot2(x, y, 1.0, 2.0) + x ** 3", ["x", "y"])
    assert "mod(x, 2.0)" in g and " mod " not in g
    assert "atan(y, x)" in g and "atan2" not in g
    assert "dot(vec2(x, y), vec2(1.0, 2.0))" in g
    assert "((x) * (x) * (x))" in g and "pow" not in g
    assert "distance(vec3(x, y, 0.0), vec3(1.0, 2.0, 3.0))" in codegen_glsl(
        "d", "dist3(x, y, 0.0, 1.0, 2.0, 3.0)", ["x", "y"])


def test_oracle_firma_nell_ordine_di_inputs() -> None:
    r = run_math_oracle([MathRequest(id="sdfp", kind="sdf", description="", expr="len2(x, y) - 1.0",
                                     inputs={"y": "float", "x": "float"},
                                     claim={"domain": [[-2, 2], [-2, 2]], "samples": 32})])
    assert r.results[0].status == "accepted", r.results[0].reason
    assert "float sdfp(float y, float x)" in r.math_glsl  # non alfabetico


@pytest.mark.parametrize(("rid", "why"), [
    ("1abc", "non valido"), ("main", "riservato"), ("gl_x", "riservato"), ("a b", "non valido"),
])
def test_oracle_id_validato(rid: str, why: str) -> None:
    r = run_math_oracle([MathRequest(id=rid, kind="identity", description="", expr="x - x",
                                     inputs={"x": "float"}, claim={"domain": [[0, 1]]})])
    assert r.results[0].status == "rejected" and why in r.results[0].reason
    assert r.math_glsl == ""


def test_oracle_id_duplicato_o_della_libreria() -> None:
    mk = lambda i: MathRequest(id=i, kind="identity", description="", expr="x - x",  # noqa: E731
                               inputs={"x": "float"}, claim={"domain": [[0, 1]]})
    r = run_math_oracle([mk("zero"), mk("zero"), mk("hash11")], reserved_names={"hash11"})
    st = [(x.status, x.reason) for x in r.results]
    assert st[0][0] == "accepted"
    assert st[1][0] == "rejected" and "duplicato" in st[1][1]
    assert st[2][0] == "rejected" and "libreria" in st[2][1]


# ---------------------------------------------------------------- watchdog psutil

def test_watchdog_uccide_per_memoria() -> None:
    from demogen.math.safe_parse import SandboxKilled, run_isolated

    code = "a = []\nwhile True:\n    a.append(bytearray(20_000_000))\n"
    with pytest.raises(SandboxKilled, match="memoria"):
        run_isolated(code, "", timeout_s=30.0, max_rss_mb=200)


def test_watchdog_uccide_per_tempo() -> None:
    import time

    from demogen.math.safe_parse import SandboxKilled, run_isolated

    t0 = time.monotonic()
    with pytest.raises(SandboxKilled, match="timeout"):
        run_isolated("while True:\n    pass\n", "", timeout_s=1.0)
    assert time.monotonic() - t0 < 6.0


def test_codegen_compila_nel_browser(harness) -> None:
    """Ogni costrutto emesso dal codegen compila davvero in GLSL ES 3.00 (ANGLE)."""
    exprs = {
        "c_mod": "x % 2.0 + mod(y, 3.0)",
        "c_atan": "atan(x) + atan2(y, x)",
        "c_vec": "dot2(x, y, 1.0, 2.0) + dist3(x, y, 0.0, 1.0, 2.0, 3.0) + len3(x, y, 1.0) + len2(x, y)",
        "c_minmax": "min(x, y) + max(x, y) + clamp(x, 0.0, 1.0) + mix(x, y, 0.5)",
        "c_step": "smoothstep(0.0, 1.0, x) + step(0.5, y)",
        "c_pow": "pow(abs(x) + 1.0, 2.5) + x ** 2 + y ** 3 + x ** 4",
        "c_misc": "abs(x) + floor(y) + fract(x) + exp(-x * x) + log(x * x + 1.0) + sqrt(y * y + 1.0)"
                  " + sign(x) + ceil(y) + sin(x) * cos(y) + tan(0.1) + log2(2.0) - pi + tau * e",
    }
    funcs = "\n".join(codegen_glsl(k, v, ["x", "y"]) for k, v in exprs.items())
    calls = " + ".join(f"{k}(p.x, p.y)" for k in exprs)
    src = funcs + f"void mainImage(out vec4 c, in vec2 p){{ c = vec4(vec3({calls}) * 0.0 + 0.5, 1.0); }}\n"
    res = harness.load_fragment(src)
    assert res["ok"], "\n".join(res["errors"])[:2000]


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
