"""Verifica numerica dei claim matematici (Fase 6).

Ogni claim è un'espressione safe (vedi safe_parse) valutata su punti random
deterministici in un subprocess isolato; il check statistico avviene qui.
Tipi soportati: sdf, lipschitz, periodic_path, easing, identity/other.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..spec.models import MathRequest
from .safe_parse import eval_points, used_names


@dataclass
class VerifyResult:
    ok: bool
    kind: str
    detail: str = ""
    max_err: float | None = None
    n_samples: int = 0
    samples: list[float] = field(default_factory=list)  # primi valori di f (debug)


def _rand_points(domain: list[list[float]], n: int, seed: int) -> list[dict[str, float]]:
    rng = random.Random(seed)
    (x0, x1), (y0, y1) = domain[0], domain[1] if len(domain) > 1 else domain[0]
    pts = []
    for _ in range(n):
        p = {"x": rng.uniform(x0, x1)}
        if len(domain) > 1:
            p["y"] = rng.uniform(y0, y1)
        pts.append(p)
    return pts


def _grad(f: dict[tuple, float], base: dict[str, float], h: float = 1e-4) -> tuple[float, float]:
    def at(dx: float, dy: float) -> float:
        return f.get((base["x"] + dx, base.get("y", 0.0) + dy), math.nan)
    gx = (at(h, 0.0) - at(-h, 0.0)) / (2 * h)
    gy = (at(0.0, h) - at(0.0, -h)) / (2 * h)
    return gx, gy


MIN_SAMPLES, MAX_SAMPLES = 8, 4096
MAX_TOL, MAX_TOL_GRAD = 1e-2, 0.1
MAX_ABS_DOMAIN = 1e4


def _finite(claim: dict, key: str, default: float | None = None) -> float:
    """Float finito da `claim[key]` (ValueError se assente senza default, non numerico o inf/nan)."""
    if key not in claim:
        if default is None:
            raise ValueError(f"claim senza '{key}'")
        return default
    v = claim[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"claim '{key}' non numerico: {v!r}")
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"claim '{key}' non finito: {v}")
    return v


def _claim_params(claim: dict) -> tuple[list[list[float]], float, float, int]:
    """Valida e limita i parametri decisi dall'LLM PRIMA di costruire qualsiasi punto.

    - samples clampato a [8, 4096] (1e8 manderebbe in OOM il processo padre);
    - tol in (0, 1e-2] e tol_grad in (0, 0.1]: una tolleranza enorme farebbe passare qualsiasi claim;
    - domain: 1..3 coppie finite [lo, hi] con lo < hi e |v| <= 1e4.
    """
    if not isinstance(claim, dict):
        raise ValueError("claim non è un oggetto")
    domain = claim.get("domain", [[-2.0, 2.0], [-2.0, 2.0]])
    if not isinstance(domain, list) or not 1 <= len(domain) <= 3:
        raise ValueError(f"domain deve avere 1..3 intervalli: {domain!r}")
    dom: list[list[float]] = []
    for iv in domain:
        if not isinstance(iv, (list, tuple)) or len(iv) != 2:
            raise ValueError(f"intervallo non valido: {iv!r}")
        lo, hi = (_finite({"v": x}, "v") for x in iv)
        if not lo < hi or max(abs(lo), abs(hi)) > MAX_ABS_DOMAIN:
            raise ValueError(f"intervallo non valido: [{lo}, {hi}]")
        dom.append([lo, hi])
    tol = _finite(claim, "tol", 1e-3)
    tol_grad = _finite(claim, "tol_grad", 5e-2)
    if tol <= 0 or tol_grad <= 0:
        raise ValueError("tol e tol_grad devono essere > 0")
    n = int(_finite(claim, "samples", 64))
    return dom, min(tol, MAX_TOL), min(tol_grad, MAX_TOL_GRAD), max(MIN_SAMPLES, min(n, MAX_SAMPLES))


def verify_claim(req: MathRequest, seed: int = 42) -> VerifyResult:
    """Verifica un MathRequest. Ritorna VerifyResult con ok/detail/max_err.

    ValueError se i parametri del claim non sono validi (l'oracolo lo registra come rifiuto).
    """
    expr = req.expr
    claim = req.claim
    names = used_names(expr)
    domain, tol, tol_grad, n = _claim_params(claim)

    if "t" in names:
        # dominio temporale 1D: domain = [[t0, t1]]
        t0, t1 = domain[0]
        base_pts = [{"t": random.Random(seed + i).uniform(t0, t1)} for i in range(n)]
    else:
        base_pts = _rand_points(domain, n, seed)

    kind = req.kind

    if kind == "sdf":
        # claim: f è una SDF esatta -> |grad f| = 1 vicino alla superficie e
        # (se inside_negative) esiste regione con f < 0 e regione con f > 0.
        inside_neg = bool(claim.get("inside_negative", True))
        evals: list[dict[str, float]] = []
        keys: list[tuple] = []
        h = 1e-4
        for p in base_pts:
            for dx, dy in ((0, 0), (h, 0), (-h, 0), (0, h), (0, -h)):
                q = dict(p)
                if "x" in q:
                    q["x"] += dx
                if "y" in q:
                    q["y"] = q.get("y", 0.0) + dy
                evals.append(q)
                keys.append((q.get("x", 0.0), q.get("y", 0.0)))
        vals = eval_points(expr, evals)
        fmap = dict(zip(keys, vals))
        errs: list[float] = []
        for p in base_pts:
            f0 = fmap.get((p.get("x", 0.0), p.get("y", 0.0)))
            if f0 is None or abs(f0) > 0.5:
                continue  # gradiente relevante solo vicino alla superficie
            gx, gy = _grad(fmap, p)
            errs.append(abs(math.hypot(gx, gy) - 1.0))
        fvals = [v for v in vals if v is not None]
        has_neg = any(v < 0 for v in fvals)
        has_pos = any(v > 0 for v in fvals)
        max_err = max(errs) if errs else None
        ok_sign = (not inside_neg) or (has_neg and has_pos)
        ok_grad = max_err is not None and max_err <= tol_grad
        return VerifyResult(
            ok=ok_sign and ok_grad,
            kind=kind,
            detail=f"|grad|-1 max={max_err}, segno ok={ok_sign} (neg={has_neg}, pos={has_pos})",
            max_err=max_err,
            n_samples=len(fvals),
            samples=fvals[:8],
        )

    if kind == "lipschitz":
        bound = _finite(claim, "bound")
        pts = base_pts * 2  # doppie per formare coppie
        vals = eval_points(expr, pts)
        pairs = list(zip(pts[::2], vals[::2], pts[1::2], vals[1::2]))
        max_ratio = 0.0
        for a, fa, b, fb in pairs:
            if fa is None or fb is None:
                continue
            dist = math.dist([a.get("x", a.get("t", 0.0)), a.get("y", 0.0)],
                             [b.get("x", b.get("t", 0.0)), b.get("y", 0.0)])
            if dist < 1e-9:
                continue
            max_ratio = max(max_ratio, abs(fa - fb) / dist)
        ok = max_ratio <= bound + tol
        return VerifyResult(
            ok=ok, kind=kind,
            detail=f"max |df|/dist={max_ratio:.4f} vs bound={bound}",
            max_err=max_ratio, n_samples=len(pairs),
        )

    if kind == "periodic_path":
        period = _finite(claim, "period")
        t0, t1 = domain[0]
        pts = [{"t": random.Random(seed + i).uniform(t0, t1)} for i in range(n)]
        shifted = [{"t": p["t"] + period} for p in pts]
        v1 = eval_points(expr, pts)
        v2 = eval_points(expr, shifted)
        errs = [abs(a - b) for a, b in zip(v1, v2) if a is not None and b is not None]
        max_err = max(errs) if errs else None
        return VerifyResult(
            ok=max_err is not None and max_err <= tol, kind=kind,
            detail=f"max |f(t+T)-f(t)|={max_err} (T={period}, tol={tol})",
            max_err=max_err, n_samples=len(errs), samples=v1[:8],
        )

    if kind == "easing":
        lo, hi = domain[0]
        v0 = eval_points(expr, [{"t": lo}])[0]
        v1 = eval_points(expr, [{"t": hi}])[0]
        ts = [{"t": lo + (hi - lo) * i / 32} for i in range(33)]
        vs = eval_points(expr, ts)
        monotonic = all(
            b >= a - tol for a, b in zip(vs, vs[1:]) if a is not None and b is not None
        )
        ok = (v0 is not None and v1 is not None and abs(v0) <= tol and abs(v1 - 1.0) <= tol
              and monotonic)
        return VerifyResult(
            ok=ok, kind=kind,
            detail=f"f({lo})={v0}, f({hi})={v1}, monotona={monotonic}",
            max_err=max(abs(v0 or 0), abs((v1 or 0) - 1.0)), n_samples=len(vs), samples=vs[:8],
        )

    # identity / other: |f| <= tol ovunque nel dominio
    vals = eval_points(expr, base_pts)
    good = [v for v in vals if v is not None]
    max_err = max((abs(v) for v in good), default=None)
    return VerifyResult(
        ok=max_err is not None and max_err <= tol, kind=kind or "identity",
        detail=f"max |f|={max_err} (tol={tol})",
        max_err=max_err, n_samples=len(good), samples=good[:8],
    )
