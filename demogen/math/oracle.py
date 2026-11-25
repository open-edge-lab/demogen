"""Oracolo matematico: verifica i math_requests dell'LLM e genera GLSL verificato.

Flusso: parse_safe (whitelist) → verify_claim (subprocess isolato) →
codegen_glsl. Solo le richieste **accepted** producono codice GLSL che entra
nel payload; le rejected tornano all'LLM con la motivazione (fixer loop).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..spec.models import MathRequest
from .codegen import codegen_glsl
from .safe_parse import UnsafeExpressionError, parse_safe, used_names
from .verify import VerifyResult, verify_claim

VERIFIABLE_KINDS = {"sdf", "lipschitz", "periodic_path", "easing", "identity", "other"}


@dataclass
class MathRequestResult:
    id: str
    status: str  # accepted | rejected
    reason: str = ""
    verify: VerifyResult | None = None
    glsl: str = ""


@dataclass
class MathOracleResult:
    results: list[MathRequestResult] = field(default_factory=list)
    math_glsl: str = ""  # concatenazione delle funzioni accepted

    @property
    def accepted(self) -> list[MathRequestResult]:
        return [r for r in self.results if r.status == "accepted"]

    @property
    def rejected(self) -> list[MathRequestResult]:
        return [r for r in self.results if r.status == "rejected"]


def run_math_oracle(requests: list[MathRequest], seed: int = 42) -> MathOracleResult:
    """Verifica una lista di MathRequest e ritorna il risultato aggregato."""
    out = MathOracleResult()
    for req in requests:
        res = MathRequestResult(id=req.id, status="rejected")
        try:
            if req.kind not in VERIFIABLE_KINDS:
                res.reason = (f"kind {req.kind!r} non verificabile; usa "
                              "sdf|lipschitz|periodic_path|easing|identity")
            elif not req.expr.strip():
                res.reason = "expr mancante"
            else:
                parse_safe(req.expr)  # solleva UnsafeExpressionError se malevola
                params = sorted(used_names(req.expr))
                # t è il tempo; gli altri parametri devono essere dichiarati negli inputs
                extra = [p for p in params if p != "t" and p not in req.inputs]
                if extra:
                    res.reason = f"variabili non dichiarate in inputs: {extra}"
                else:
                    v = verify_claim(req, seed=seed)
                    res.verify = v
                    if v.ok:
                        res.status = "accepted"
                        res.glsl = codegen_glsl(req.id, req.expr, params)
                        res.reason = v.detail
                    else:
                        res.reason = f"claim falso: {v.detail}"
        except UnsafeExpressionError as exc:
            res.reason = f"espressione non sicura: {exc}"
        except Exception as exc:  # noqa: BLE001 - l'oracolo non deve mai crashare la pipeline
            res.reason = f"errore interno: {type(exc).__name__}: {exc}"
        out.results.append(res)
    out.math_glsl = "\n".join(r.glsl for r in out.results if r.status == "accepted")
    return out
