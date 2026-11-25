"""Budget LLM: costo (da usage o tabella prezzi) e wall-time, con stop anticipato."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    max_total_cost_usd: float
    max_wall_minutes: float
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)
    spent_usd: float = 0.0
    started: float = field(default_factory=time.monotonic)

    @classmethod
    def from_config(cls, cfg, spent_usd: float = 0.0) -> Budget:
        """`spent_usd`: spesa già fatta (da state.json) — al resume il budget non riparte da zero."""
        b = cfg.budget
        return cls(
            max_total_cost_usd=b.max_total_cost_usd,
            max_wall_minutes=b.max_wall_minutes,
            pricing=cfg.pricing,
            spent_usd=float(spent_usd or 0.0),
        )

    def price(self, model: str) -> dict[str, float]:
        return self.pricing.get(model, {"prompt_per_mtok": 0.0, "completion_per_mtok": 0.0})

    def estimate_cost_usd(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        p = self.price(model)
        return prompt_tokens / 1e6 * p["prompt_per_mtok"] + completion_tokens / 1e6 * p[
            "completion_per_mtok"
        ]

    def max_cost_of(self, model: str, max_tokens: int, prompt_tokens_est: int = 4000) -> float:
        """Stima del costo massimo di una chiamata (per il gate prima di farla)."""
        return self.estimate_cost_usd(model, prompt_tokens_est, max_tokens)

    def can_afford(self, model: str, max_tokens: int) -> bool:
        return self.spent_usd + self.max_cost_of(model, max_tokens) <= self.max_total_cost_usd

    def add(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None,
    ) -> float:
        cost = cost_usd if cost_usd is not None else self.estimate_cost_usd(
            model, prompt_tokens, completion_tokens
        )
        self.spent_usd += cost
        return cost

    def check(self) -> None:
        if self.spent_usd > self.max_total_cost_usd:
            raise BudgetExceeded(
                f"Budget costo superato: {self.spent_usd:.4f} > {self.max_total_cost_usd} USD"
            )
        elapsed_min = (time.monotonic() - self.started) / 60
        if elapsed_min > self.max_wall_minutes:
            raise BudgetExceeded(
                f"Budget tempo superato: {elapsed_min:.1f} > {self.max_wall_minutes} min"
            )
