"""Verifica numerica dei claim matematici (Fase 6).

Ogni claim è un'espressione safe (vedi safe_parse) valutata su punti random
deterministici in un subprocess isolato; il check statistico avviene qui.
Tipi supportati: sdf, lipschitz, periodic_path, easing, identity/other.

Regole comuni:
- si legano TUTTE le variabili della richiesta (ordine di `inputs`, più quelle usate
  e non dichiarate): domain[i] è l'intervallo della i-esima, l'ultimo si ripete;
- un claim è accettato solo se almeno max(8, 90%) dei punti si valutano (un claim
  "vero" su zero punti non dice nulla).
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


MIN_SAMPLES, MAX_SAMPLES = 8, 4096
MAX_TOL, MAX_TOL_GRAD = 1e-2, 0.1
MAX_ABS_DOMAIN = 1e4
MAX_INTERVALS = 4  # x, y, z, t
MIN_VALID_FRAC = 0.9
H = 1e-4  # passo delle differenze finite


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
    - domain: 1..4 coppie finite [lo, hi] con lo < hi e |v| <= 1e4.
    """
    if not isinstance(claim, dict):
        raise ValueError("claim non è un oggetto")
    domain = claim.get("domain", [[-2.0, 2.0], [-2.0, 2.0]])
    if not isinstance(domain, list) or not 1 <= len(domain) <= MAX_INTERVALS:
        raise ValueError(f"domain deve avere 1..{MAX_INTERVALS} intervalli: {domain!r}")
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


def variables(req: MathRequest, names: set[str]) -> list[str]:
    """Variabili da legare: ordine di `inputs`, poi quelle usate e non dichiarate (es. t)."""
    out = list(req.inputs)
    out += [n for n in sorted(names) if n not in out]
    return out


def _need(n: int) -> int:
    return max(MIN_SAMPLES, math.ceil(MIN_VALID_FRAC * n)) if n >= MIN_SAMPLES else n


def _too_few(kind: str, valid: int, n: int) -> VerifyResult:
    return VerifyResult(ok=False, kind=kind, n_samples=valid,
                        detail=f"solo {valid}/{n} punti valutati (servono >= {_need(n)})")


def verify_claim(req: MathRequest, seed: int = 42) -> VerifyResult:
    """Verifica un MathRequest. Ritorna VerifyResult con ok/detail/max_err.

    ValueError se i parametri del claim non sono validi (l'oracolo lo registra come rifiuto).
    """
    expr = req.expr
    claim = req.claim
    names = used_names(expr)
    domain, tol, tol_grad, n = _claim_params(claim)
    vars_ = variables(req, names)
    dom = {v: domain[min(i, len(domain) - 1)] for i, v in enumerate(vars_)}
    rng = random.Random(seed)

    def rand_point() -> dict[str, float]:
        return {v: rng.uniform(*dom[v]) for v in vars_}

    kind = req.kind

    if kind == "sdf":
        return _verify_sdf(expr, claim, names, vars_, dom, n, tol_grad, rand_point)

    if kind == "lipschitz":
        bound = _finite(claim, "bound")
        lv = [v for v in vars_ if v in names]
        span = sum(dom[v][1] - dom[v][0] for v in lv) / max(1, len(lv))
        delta = 1e-3 * span
        base = [rand_point() for _ in range(n)]
        pairs = []
        for p in base:  # coppia VICINA: p e p + δ·u, u unitario casuale (pendenza locale)
            u = [rng.gauss(0.0, 1.0) for _ in lv] or [0.0]
            norm = math.sqrt(sum(c * c for c in u)) or 1.0
            q = dict(p)
            for v, c in zip(lv, u):
                q[v] = p[v] + delta * c / norm
            pairs.append(q)
        vals = eval_points(expr, base + pairs)
        fa, fb = vals[:n], vals[n:]
        ratios = []
        for p, q, a, b in zip(base, pairs, fa, fb):
            if a is None or b is None:
                continue
            dist = math.sqrt(sum((q[v] - p[v]) ** 2 for v in lv))
            ratios.append(abs(a - b) / dist if dist > 0 else 0.0)
        if len(ratios) < _need(n):
            return _too_few(kind, len(ratios), n)
        max_ratio = max(ratios)
        return VerifyResult(
            ok=max_ratio <= bound + tol, kind=kind,
            detail=f"max |df|/dist={max_ratio:.4f} vs bound={bound} su {len(ratios)} coppie vicine",
            max_err=max_ratio, n_samples=len(ratios),
        )

    if kind == "periodic_path":
        period = _finite(claim, "period")
        if "t" not in vars_:
            return VerifyResult(ok=False, kind=kind, detail="periodic_path senza variabile t")
        pts = [rand_point() for _ in range(n)]
        shifted = [p | {"t": p["t"] + period} for p in pts]
        vals = eval_points(expr, pts + shifted)
        v1, v2 = vals[:n], vals[n:]
        errs = [abs(a - b) for a, b in zip(v1, v2) if a is not None and b is not None]
        if len(errs) < _need(n):
            return _too_few(kind, len(errs), n)
        max_err = max(errs)
        return VerifyResult(
            ok=max_err <= tol, kind=kind,
            detail=f"max |f(t+T)-f(t)|={max_err} (T={period}, tol={tol})",
            max_err=max_err, n_samples=len(errs), samples=[v for v in v1 if v is not None][:8],
        )

    if kind == "easing":
        tvar = "t" if "t" in vars_ else vars_[0]
        lo, hi = dom[tvar]
        mid = {v: (dom[v][0] + dom[v][1]) / 2 for v in vars_ if v != tvar}
        ts = [mid | {tvar: lo + (hi - lo) * i / 32} for i in range(33)]
        vs = eval_points(expr, ts)
        v0, v1 = vs[0], vs[-1]
        good = [v for v in vs if v is not None]
        if len(good) < _need(len(vs)) or v0 is None or v1 is None:
            return _too_few(kind, len(good), len(vs))
        monotonic = all(b >= a - tol for a, b in zip(vs, vs[1:]) if a is not None and b is not None)
        ok = abs(v0) <= tol and abs(v1 - 1.0) <= tol and monotonic
        return VerifyResult(
            ok=ok, kind=kind,
            detail=f"f({lo})={v0}, f({hi})={v1}, monotona={monotonic}",
            max_err=max(abs(v0), abs(v1 - 1.0)), n_samples=len(good), samples=good[:8],
        )

    # identity / other: |f| <= tol ovunque nel dominio
    vals = eval_points(expr, [rand_point() for _ in range(n)])
    good = [v for v in vals if v is not None]
    if len(good) < _need(n):
        return _too_few(kind or "identity", len(good), n)
    max_err = max(abs(v) for v in good)
    return VerifyResult(
        ok=max_err <= tol, kind=kind or "identity",
        detail=f"max |f|={max_err} (tol={tol})",
        max_err=max_err, n_samples=len(good), samples=good[:8],
    )


def _verify_sdf(expr, claim, names, vars_, dom, n, tol_grad, rand_point) -> VerifyResult:
    """SDF esatta: |∇f| = 1 vicino alla superficie, f < 0 dentro e f > 0 sul bordo del dominio.

    Il bordo del dominio (anello/guscio esterno) deve stare FUORI dalla forma: una SDF
    invertita (1 − |p|) ha entrambi i segni ma è negativa fuori, quindi viene rifiutata.
    Con `inside` (coordinate spaziali, nell'ordine) si verifica anche f(inside) < 0.
    """
    kind = "sdf"
    spatial = [v for v in vars_ if v != "t" and v in names]
    if not spatial:
        return VerifyResult(ok=False, kind=kind, detail="sdf senza variabili spaziali usate")
    inside_neg = bool(claim.get("inside_negative", True))
    base = [rand_point() for _ in range(n)]
    evals: list[dict[str, float]] = []
    for p in base:
        evals.append(p)
        for v in spatial:
            evals.append(p | {v: p[v] + H})
            evals.append(p | {v: p[v] - H})
    # guscio esterno: punti sulle facce del box dei domini spaziali
    ring = []
    n_ring = max(MIN_SAMPLES, n // 2)
    for i in range(n_ring):
        q = rand_point()
        v = spatial[i % len(spatial)]
        q[v] = dom[v][i // len(spatial) % 2]
        ring.append(q)
    inside = claim.get("inside")
    inside_pt = None
    if inside is not None:
        if not isinstance(inside, list) or len(inside) != len(spatial):
            raise ValueError(f"inside deve avere {len(spatial)} coordinate ({spatial})")
        inside_pt = rand_point() | {v: float(c) for v, c in zip(spatial, inside)}
    vals = eval_points(expr, evals + ring + ([inside_pt] if inside_pt else []))
    stride = 1 + 2 * len(spatial)
    errs: list[float] = []
    f0s: list[float] = []
    for i in range(n):
        chunk = vals[i * stride:(i + 1) * stride]
        if any(v is None for v in chunk):
            continue
        f0 = chunk[0]
        f0s.append(f0)
        if abs(f0) > 0.5:
            continue  # gradiente rilevante solo vicino alla superficie
        g2 = sum(((chunk[1 + 2 * k] - chunk[2 + 2 * k]) / (2 * H)) ** 2 for k in range(len(spatial)))
        errs.append(abs(math.sqrt(g2) - 1.0))
    if len(f0s) < _need(n):
        return _too_few(kind, len(f0s), n)
    ring_vals = vals[n * stride:n * stride + n_ring]
    ring_ok = all(v is not None and v > 0 for v in ring_vals)
    inside_ok = True
    if inside_pt is not None:
        fi = vals[-1]
        inside_ok = fi is not None and fi < 0
    # forme sottili (anelli, tubi): i campioni casuali possono non cadere mai dentro;
    # un punto `inside` con f < 0 basta a provare che la regione negativa esiste
    has_neg = any(v < 0 for v in f0s) or (inside_pt is not None and inside_ok)
    max_err = max(errs) if errs else None
    ok_sign = (not inside_neg) or (has_neg and ring_ok and inside_ok)
    ok_grad = max_err is not None and max_err <= tol_grad
    return VerifyResult(
        ok=ok_sign and ok_grad,
        kind=kind,
        detail=(f"|grad|-1 max={max_err} su {len(errs)} punti vicino alla superficie ({', '.join(spatial)}), "
                f"segno ok={ok_sign} (dentro<0: {has_neg}, bordo>0: {ring_ok}, inside: {inside_ok})"
                + ("" if has_neg or inside_pt is not None else
                   " — nessun campione dentro la forma: per forme sottili indica `inside` nel claim")),
        max_err=max_err,
        n_samples=len(f0s),
        samples=f0s[:8],
    )
