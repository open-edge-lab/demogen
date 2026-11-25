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
import re
import subprocess
import sys
import threading
import time

# nome python-safe -> nome GLSL (il codegen usa questa tabella; GLSL ha atan(y, x), non atan2)
FUNCTIONS: dict[str, str] = {
    "sin": "sin", "cos": "cos", "tan": "tan",
    "asin": "asin", "acos": "acos",
    "atan": "atan", "atan2": "atan",
    "exp": "exp", "log": "log", "log2": "log2",
    "sqrt": "sqrt", "abs": "abs", "sign": "sign",
    "floor": "floor", "ceil": "ceil", "fract": "fract",
    "mod": "mod", "pow": "pow",
    "min": "min", "max": "max", "clamp": "clamp",
    "mix": "mix", "step": "step", "smoothstep": "smoothstep",
    "len2": "length", "len3": "length",
    "dot2": "dot", "dot3": "dot",
    "dist2": "distance", "dist3": "distance",
}

# numero di argomenti: Python accetterebbe min(a,b,c) o hypot(x,y,z), GLSL no
ARITY: dict[str, int] = {
    "sin": 1, "cos": 1, "tan": 1, "asin": 1, "acos": 1, "atan": 1, "atan2": 2,
    "exp": 1, "log": 1, "log2": 1, "sqrt": 1, "abs": 1, "sign": 1,
    "floor": 1, "ceil": 1, "fract": 1, "mod": 2, "pow": 2,
    "min": 2, "max": 2, "clamp": 3, "mix": 3, "step": 2, "smoothstep": 3,
    "len2": 2, "len3": 3, "dot2": 4, "dot3": 6, "dist2": 4, "dist3": 6,
}

CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

# nomi che non possono essere variabili né id di funzione nel GLSL generato
GLSL_RESERVED = frozenset("""
attribute const uniform varying layout centroid flat smooth break continue do for while switch case
default if else in out inout float int void bool true false invariant discard return mat2 mat3 mat4
mat2x2 mat2x3 mat2x4 mat3x2 mat3x3 mat3x4 mat4x2 mat4x3 mat4x4 vec2 vec3 vec4 ivec2 ivec3 ivec4 bvec2
bvec3 bvec4 uint uvec2 uvec3 uvec4 lowp mediump highp precision sampler2D sampler3D samplerCube
sampler2DShadow struct precise asm class union enum typedef template this goto inline noinline
volatile public static extern external interface long short double half fixed unsigned input
output sizeof cast namespace using main radians degrees sin cos tan asin acos atan pow exp log exp2
log2 sqrt inversesqrt abs sign floor ceil fract mod min max clamp mix step smoothstep length distance
dot cross normalize reflect refract texture round trunc isnan isinf
""".split())


def check_identifier(name: str, what: str = "nome") -> None:
    """Un identificatore che finisce nel GLSL: valido, non riservato, niente gl_ né __."""
    if not re.fullmatch(r"[A-Za-z_]\w*", name or ""):
        raise UnsafeExpressionError(f"{what} non valido: {name!r}")
    if name in GLSL_RESERVED or name.startswith("gl_") or "__" in name:
        raise UnsafeExpressionError(f"{what} riservato in GLSL: {name!r}")

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
    call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpressionError(f"node non ammesso: {type(node).__name__}")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise UnsafeExpressionError("solo costanti numeriche")
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise UnsafeExpressionError("nomi dunder vietati")
            if node.id in FUNCTIONS:
                if id(node) not in call_funcs:  # `sin + 1`: una funzione usata come valore
                    raise UnsafeExpressionError(f"funzione {node.id} usata senza chiamarla")
            elif node.id not in CONSTANTS:
                check_identifier(node.id, "variabile")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            # x**2..4 diventa moltiplicazione (stessa semantica ovunque); altrimenti pow(),
            # che in GLSL è indefinito con base negativa (il runner lo rispecchia)
            r = node.right
            if not (isinstance(r, ast.Constant) and not isinstance(r.value, bool)
                    and isinstance(r.value, (int, float)) and float(r.value) in (2.0, 3.0, 4.0)):
                raise UnsafeExpressionError("** solo con esponente costante 2, 3 o 4: usa pow(x, y)")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise UnsafeExpressionError(f"chiamata non in whitelist: {ast.dump(node.func)}")
            if node.keywords:
                raise UnsafeExpressionError("no keyword arguments")
            want = ARITY[node.func.id]
            if len(node.args) != want:
                raise UnsafeExpressionError(
                    f"{node.func.id} vuole {want} argomenti, ne ha {len(node.args)}"
                )
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

def _gl_pow(a, b):
    # GLSL: pow(x, y) con x < 0 è indefinito (NaN sulle GPU): il claim non deve contarci
    if a < 0 or (a == 0 and b <= 0):
        raise ValueError("pow con base negativa (indefinito in GLSL)")
    return math.pow(a, b)


def _gl_smoothstep(e0, e1, v):
    # formula GLSL (vale anche con e0 > e1); e0 == e1 è indefinito
    t = min(max((v - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


F = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "atan2": math.atan2,
    "exp": math.exp, "log": math.log, "log2": math.log2,
    "sqrt": math.sqrt, "abs": abs, "sign": lambda v: float((v > 0) - (v < 0)),
    "floor": math.floor, "ceil": math.ceil, "fract": lambda v: v - math.floor(v),
    "mod": lambda a, b: a - b * math.floor(a / b),  # GLSL mod è "floored", non fmod
    "pow": _gl_pow,
    "min": min, "max": max,
    "clamp": lambda v, a, b: min(max(v, a), b),
    "mix": lambda a, b, t: a + (b - a) * t,
    "step": lambda e, v: 0.0 if v < e else 1.0,
    "smoothstep": _gl_smoothstep,
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


DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_RSS_MB = 512


class SandboxKilled(UnsafeExpressionError):
    """Il watchdog ha ucciso il subprocess (memoria o tempo)."""


def run_isolated(code: str, stdin_text: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_rss_mb: float = DEFAULT_MAX_RSS_MB) -> tuple[int, str, str]:
    """Esegue `code` in `python -I -c` con watchdog psutil su RSS (processo + figli) e tempo.

    -I (isolated): niente cwd/script dir in sys.path, niente PYTHON* env, niente site utente:
    un json.py/math.py lasciato nella cartella corrente non viene importato. Il watchdog vale
    su tutti gli OS (su Windows non esiste RLIMIT_AS). Ritorna (returncode, stdout, stderr);
    SandboxKilled se il processo supera i limiti.
    """
    import psutil

    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    killed: dict[str, str] = {}
    limit = int(max_rss_mb * 1024 * 1024)

    def watch() -> None:
        try:
            ps = psutil.Process(proc.pid)
            while proc.poll() is None:
                rss = ps.memory_info().rss + sum(c.memory_info().rss for c in ps.children(recursive=True))
                if rss > limit:
                    killed["reason"] = f"memoria: RSS {rss >> 20} MB > {max_rss_mb:.0f} MB"
                    proc.kill()
                    return
                time.sleep(0.05)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        killed.setdefault("reason", f"timeout: oltre {timeout_s:.1f} s")
        proc.kill()
        out, err = proc.communicate()
    watcher.join(timeout=1.0)
    if "reason" in killed:
        raise SandboxKilled(f"watchdog: {killed['reason']}")
    return proc.returncode, out, err


def eval_points(expr: str, points: list[dict[str, float]], timeout_s: float = DEFAULT_TIMEOUT_S,
                max_rss_mb: float = DEFAULT_MAX_RSS_MB) -> list[float | None]:
    """Valuta `expr` su punti {variabile: valore} in un subprocess isolato con watchdog.

    Ritorna float (None dove l'eval di dominio è fallita, es. sqrt di negativo).
    """
    parse_safe(expr)
    envs = [{k: float(v) for k, v in p.items()} for p in points]
    code, out, err = run_isolated(_RUNNER, json.dumps({"expr": expr, "envs": envs}), timeout_s, max_rss_mb)
    if code != 0:
        raise UnsafeExpressionError(f"subprocess fallita: {err.strip()[:300]}")
    results = json.loads(out.strip().splitlines()[-1])
    return [r["value"] if r["ok"] else None for r in results]
