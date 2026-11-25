"""Oracolo matematico: verifica i math_requests dell'LLM e genera GLSL verificato.

Flusso: parse_safe (whitelist) → verify_claim (subprocess isolato) →
codegen_glsl. Solo le richieste **accepted** producono codice GLSL che entra
nel payload; le rejected tornano all'LLM con la motivazione (fixer loop).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..spec.models import MathRequest
from .codegen import codegen_glsl
from .safe_parse import UnsafeExpressionError, check_identifier, parse_safe, used_names
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


def run_math_oracle(requests: list[MathRequest], seed: int = 42,
                    reserved_names: set[str] | frozenset[str] = frozenset()) -> MathOracleResult:
    """Verifica una lista di MathRequest e ritorna il risultato aggregato.

    `reserved_names`: nomi già usati nel GLSL (funzioni della libreria): un id uguale
    produrrebbe una ridefinizione, quindi viene rifiutato."""
    out = MathOracleResult()
    seen_ids: set[str] = set()
    for req in requests:
        res = MathRequestResult(id=req.id, status="rejected")
        try:
            check_identifier(req.id, "id")  # l'id diventa il nome della funzione GLSL
            bad_types = {k: t for k, t in req.inputs.items() if t not in ("float", "f")}
            if req.id in seen_ids:
                res.reason = f"id duplicato: {req.id!r}"
            elif req.id in reserved_names:
                res.reason = f"id {req.id!r} coincide con una funzione della libreria: scegli un altro nome"
            elif bad_types:
                res.reason = f"gli inputs devono essere float: {bad_types}"
            elif req.kind not in VERIFIABLE_KINDS:
                res.reason = (f"kind {req.kind!r} non verificabile; usa "
                              "sdf|lipschitz|periodic_path|easing|identity")
            elif not req.expr.strip():
                res.reason = "expr mancante"
            else:
                parse_safe(req.expr)  # solleva UnsafeExpressionError se malevola
                used = used_names(req.expr)
                # t è il tempo; gli altri parametri devono essere dichiarati negli inputs
                extra = sorted(p for p in used if p != "t" and p not in req.inputs)
                if extra:
                    res.reason = f"variabili non dichiarate in inputs: {extra}"
                else:
                    v = verify_claim(req, seed=seed)
                    res.verify = v
                    if v.ok:
                        res.status = "accepted"
                        # firma nell'ordine di `inputs` (come la chiamerà lo shader), poi t se usato
                        params = list(req.inputs) + (["t"] if "t" in used and "t" not in req.inputs else [])
                        res.glsl = codegen_glsl(req.id, req.expr, params)
                        res.reason = v.detail
                    else:
                        res.reason = f"claim falso: {v.detail}"
            seen_ids.add(req.id)
        except UnsafeExpressionError as exc:
            res.reason = f"espressione non sicura: {exc}"
        except Exception as exc:  # noqa: BLE001 - l'oracolo non deve mai crashare la pipeline
            res.reason = f"errore interno: {type(exc).__name__}: {exc}"
        out.results.append(res)
    out.math_glsl = "\n".join(r.glsl for r in out.results if r.status == "accepted")
    return out
