"""Codegen: da AST safe (whitelist) a GLSL ES 3.00 normalizzato.

Traduce solo nodi whitelist; le funzioni vettoriali 2D/3D diventano costruttori
vec2/vec3 (per dot/distance: due vettori con metà degli argomenti ciascuno). Il
risultato è deterministico e non contiene mai codice arbitrario (niente stringhe,
attributi, subscript). La semantica coincide con quella del runner di verifica:
`%` → mod() floored, `**` con esponente 2..4 → moltiplicazioni, atan2 → atan(y, x).
"""

from __future__ import annotations

import ast

from .safe_parse import CONSTANTS, FUNCTIONS, check_identifier, parse_safe, used_names

_BINOP = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}

# funzioni vettoriali: nome -> (funzione GLSL, componenti, numero di vettori)
_VEC_FUNCS = {
    "len2": ("length", 2, 1), "len3": ("length", 3, 1),
    "dot2": ("dot", 2, 2), "dot3": ("dot", 3, 2),
    "dist2": ("distance", 2, 2), "dist3": ("distance", 3, 2),
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
        left, right = _gen(node.left), _gen(node.right)
        if isinstance(node.op, ast.Pow):
            n = int(float(node.right.value))  # type: ignore[attr-defined]  # 2..4, garantito da parse_safe
            return "(" + " * ".join([f"({left})"] * n) + ")"
        if isinstance(node.op, ast.Mod):
            return f"mod({left}, {right})"
        return f"({left} {_BINOP[type(node.op)]} {right})"
    if isinstance(node, ast.Call):
        fname = node.func.id  # type: ignore[attr-defined]
        args = [_gen(a) for a in node.args]
        if fname in _VEC_FUNCS:  # len2(x,y) → length(vec2(x, y)); dot2(a,b,c,d) → dot(vec2(a,b), vec2(c,d))
            glsl_fn, n, k = _VEC_FUNCS[fname]
            vecs = [f"vec{n}({', '.join(args[i * n:(i + 1) * n])})" for i in range(k)]
            return f"{glsl_fn}({', '.join(vecs)})"
        return f"{FUNCTIONS[fname]}({', '.join(args)})"
    raise ValueError(f"nodo non gestito: {type(node).__name__}")


def codegen_glsl(req_id: str, expr: str, params: list[str]) -> str:
    """Genera la funzione GLSL ES 3.00 per un'espressione verificata.

    `params` è la firma, NELL'ORDINE in cui il chiamante la userà (l'ordine di
    `inputs` della richiesta); deve contenere tutte le variabili usate. La firma è
    `float <req_id>(float p0, float p1, ...)`.
    """
    check_identifier(req_id, "id della funzione")
    for p in params:
        check_identifier(p, "parametro")
    tree = parse_safe(expr)
    unknown = sorted(n for n in used_names(expr) if n not in params)
    if unknown:
        raise ValueError(f"parametri mancanti: {unknown}")
    sig = ", ".join(f"float {p}" for p in params)
    body = _gen(tree)
    return f"// oracolo matematico verificato: {req_id}\nfloat {req_id}({sig}) {{\n    return {body};\n}}\n"
