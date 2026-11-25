"""Oracolo matematico (Fase 6): parse sicuro di espressioni, verifica numerica
dei claim, generazione di GLSL ES 3.00 verificato."""

from .codegen import codegen_glsl
from .oracle import MathOracleResult, MathRequestResult, run_math_oracle
from .safe_parse import UnsafeExpressionError, parse_safe
from .verify import VerifyResult, verify_claim

__all__ = [
    "MathOracleResult",
    "MathRequestResult",
    "run_math_oracle",
    "UnsafeExpressionError",
    "parse_safe",
    "VerifyResult",
    "verify_claim",
    "codegen_glsl",
]
