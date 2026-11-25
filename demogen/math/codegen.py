"""Codegen: da AST safe (whitelist) a GLSL ES 3.00 normalizzato.

Traduce solo nodi whitelist; le funzioni vettoriali 2D/3D diventano
costruttori vec2/vec3. Il risultato è deterministico e non contiene mai
codice arbitrario (niente stringhe, attributi, subscript).
"""

from __future__ import annotations

import ast

from .safe_parse import CONSTANTS, FUNCTIONS, parse_safe, used_names

_BINOP = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "mod", ast.Pow: None,
}

# funzioni vettoriali: nome -> (funzione GLSL, numero componenti del vec)
_VEC_FUNCS = {
    "len2": ("length", 2), "len3": ("length", 3),
    "dot2": ("dot", 2), "dot3": ("dot", 3),
    "dist2": ("distance", 2), "dist3": ("distance", 3),
    "norm2": ("normalize", 2), "norm3": ("normalize", 3),
}


def _fmt_num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v)}.0"
    return repr(v)


def _gen(node: ast.AST) -> str:
    if isinstance(node, ast.Expression):
        return _gen(node.body)
    if isinstance(node, ast.Constant):
        return _fmt_num(float(node.value))
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return _fmt_num(CONSTANTS[node.id])
        return node.id
    if isinstance(node, ast.UnaryOp):
        op = "-" if isinstance(node.op, ast.USub) else "+"
        return f"({op}{_gen(node.operand)})"
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            return f"pow({_gen(node.left)}, {_gen(node.right)})"
        op = _BINOP[type(node.op)]
        return f"({_gen(node.left)} {op} {_gen(node.right)})"
    if isinstance(node, ast.Call):
        fname = node.func.id  # type: ignore[attr-defined]
        args = ", ".join(_gen(a) for a in node.args)
        if fname in _VEC_FUNCS:  # len2/dot2/... -> length(vec2(a, b)) ecc.
            glsl_fn, nargs = _VEC_FUNCS[fname]
            return f"{glsl_fn}(vec{nargs}({args}))"
        return f"{FUNCTIONS[fname]}({args})"
    raise ValueError(f"nodo non gestito: {type(node).__name__}")


def codegen_glsl(req_id: str, expr: str, params: list[str]) -> str:
    """Genera la funzione GLSL ES 3.00 per un'espressione verificata.

    `params` sono i nomi delle variabili usate (oltre a costanti/funzioni),
    tipicamente un sottoinsieme di x, y, z, t. La firma è
    `float <req_id>(float p0, float p1, ...)`.
    """
    tree = parse_safe(expr)
    names = sorted(used_names(expr))
    unknown = [n for n in names if n not in params]
    if unknown:
        raise ValueError(f"parametri mancanti: {unknown}")
    sig = ", ".join(f"float {p}" for p in params)
    body = _gen(tree)
    return f"// oracolo matematico verificato: {req_id}\nfloat {req_id}({sig}) {{\n    return {body};\n}}\n"
