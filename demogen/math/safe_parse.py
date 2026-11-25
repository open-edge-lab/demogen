"""Parse ed esecuzione sicure di espressioni matematiche (whitelist AST).

Le espressioni arrivano dall'LLM (math_requests): mai `eval` diretto sul
processo principale. `parse_safe` accetta solo un sottoinsieme puro e
`eval_points` esegue i punti in un **subprocess** con limiti di risorse
(RLIMIT_AS ~ watchdog RSS su macOS, RLIMIT_CPU, timeout) così un input
malevolo o un loop infinito non blocca l'orchestratore.

Sottoinsieme ammesso:
- costanti numeriche, nomi whitelist (variabili + `pi`, `e`, `tau`)
- operatori + - * / % ** (unari + -)
- chiamate a funzioni whitelist (math + vettoriali 2D/3D, vedi FUNCTIONS)
- niente attributi, subscript, lambda, comprehension, if-exp, stringhe
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys

# nome python-safe -> nome GLSL (il codegen usa questa tabella)
FUNCTIONS: dict[str, str] = {
    "sin": "sin", "cos": "cos", "tan": "tan",
    "asin": "asin", "acos": "acos",
    "atan": "atan", "atan2": "atan2",
    "exp": "exp", "log": "log", "log2": "log2",
    "sqrt": "sqrt", "abs": "abs", "sign": "sign",
    "floor": "floor", "ceil": "ceil", "fract": "fract",
    "mod": "mod", "pow": "pow",
    "min": "min", "max": "max", "clamp": "clamp",
    "mix": "mix", "step": "step", "smoothstep": "smoothstep",
    "len2": "length(vec2", "len3": "length(vec3",
    "dot2": "dot(vec2", "dot3": "dot(vec3",
    "dist2": "distance(vec2", "dist3": "distance(vec3",
    "norm2": "normalize(vec2", "norm3": "normalize(vec3",
}

CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub,
)


class UnsafeExpressionError(ValueError):
    """Espressione fuori dalla whitelist (o malformata)."""


def parse_safe(expr: str) -> ast.Expression:
    """Valida l'espressione contro la whitelist AST e la ritorna."""
    if not isinstance(expr, str) or not expr.strip():
        raise UnsafeExpressionError("empty expression")
    if len(expr) > 2000:
        raise UnsafeExpressionError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"syntax error: {exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpressionError(f"node non ammesso: {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise UnsafeExpressionError("solo costanti numeriche")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise UnsafeExpressionError("nomi dunder vietati")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise UnsafeExpressionError(f"chiamata non in whitelist: {ast.dump(node.func)}")
            if node.keywords:
                raise UnsafeExpressionError("no keyword arguments")
    return tree


def used_names(expr: str) -> set[str]:
    """Variabili usate dall'espressione (escluse costanti e funzioni)."""
    tree = parse_safe(expr)
    return {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in CONSTANTS and node.id not in FUNCTIONS
    }


_RUNNER = r"""
import ast, json, math, sys

# watchdog risorse: su POSIX/macOS RLIMIT_AS copre il controllo RSS; su Windows
# (no modulo resource) ci pensa il timeout del padre.
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
except ImportError:
    pass

F = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "atan2": math.atan2,
    "exp": math.exp, "log": math.log, "log2": math.log2,
    "sqrt": math.sqrt, "abs": abs, "sign": lambda v: float((v > 0) - (v < 0)),
    "floor": math.floor, "ceil": math.ceil, "fract": lambda v: v - math.floor(v),
    "mod": math.fmod, "pow": math.pow,
    "min": min, "max": max,
    "clamp": lambda v, a, b: min(max(v, a), b),
    "mix": lambda a, b, t: a + (b - a) * t,
    "step": lambda e, v: 0.0 if v < e else 1.0,
    "smoothstep": lambda a, b, v: (0.0 if v <= a else 1.0 if v >= b else
        (lambda t: t * t * (3.0 - 2.0 * t))((v - a) / (b - a))),
    "len2": math.hypot,
    "len3": lambda x, y, z: math.sqrt(x * x + y * y + z * z),
    "dot2": lambda ax, ay, bx, by: ax * bx + ay * by,
    "dot3": lambda ax, ay, az, bx, by, bz: ax * bx + ay * by + az * bz,
    "dist2": lambda ax, ay, bx, by: math.hypot(ax - bx, ay - by),
    "dist3": lambda ax, ay, az, bx, by, bz: math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2),
}
C = {"pi": math.pi, "e": math.e, "tau": math.tau}

def evaluate(code, names, env):
    g = {"__builtins__": {}}
    for n in names:
        if n in C:
            g[n] = C[n]
        elif n in F:
            fn = F[n]
            g[n] = (lambda f: lambda *a: float(f(*[float(x) for x in a])))(fn)
        elif n in env:
            g[n] = float(env[n])
        else:
            raise ValueError(f"nome non ammesso: {n}")
    return float(eval(code, g, {}))  # noqa: S307 - AST validata dalla whitelist

data = json.load(sys.stdin)
tree = ast.parse(data["expr"], mode="eval")
code = compile(tree, "<safe>", "eval")
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
out = []
for env in data["envs"]:
    try:
        out.append({"ok": True, "value": evaluate(code, names, env)})
    except Exception as exc:  # il subprocess isola qualsiasi errore di dominio
        out.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
print(json.dumps(out))
"""


def eval_points(expr: str, points: list[dict[str, float]], timeout_s: float = 10.0) -> list[float | None]:
    """Valuta `expr` su punti {variabile: valore} in un subprocess isolato.

    Ritorna float (None dove l'eval di dominio è fallita, es. sqrt di negativo).
    """
    parse_safe(expr)
    envs = [{k: float(v) for k, v in p.items()} for p in points]
    # -I (isolated): niente cwd/script dir in sys.path, niente PYTHON* env, niente site utente:
    # un json.py/math.py lasciato nella cartella corrente non viene importato. -c: nessun file temp.
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _RUNNER],
        input=json.dumps({"expr": expr, "envs": envs}),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise UnsafeExpressionError(f"subprocess fallita: {proc.stderr.strip()[:300]}")
    results = json.loads(proc.stdout.strip().splitlines()[-1])
    return [r["value"] if r["ok"] else None for r in results]
