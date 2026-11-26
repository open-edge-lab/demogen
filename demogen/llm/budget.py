"""Budget LLM: costo (da usage o tabella prezzi), tetti di consumo e wall-time, con stop anticipato.

Tetti (tutti configurabili in `budget:` di demogen.yaml, o con `demogen budget`):
- per run: `max_total_cost_usd` (spesa del progetto, ripresa da state.json al resume);
- per giorno e per mese: `max_daily_cost_usd`, `max_monthly_cost_usd`, su TUTTE le generazioni,
  sommando il registro locale `<cache_dir>/spend.jsonl` (una riga per chiamata pagata);
- `max_calls_per_run`: numero massimo di chiamate LLM in un run;
- `max_wall_minutes`: durata massima del run.

Prima di ogni chiamata `can_afford` stima il costo massimo (prompt stimato + max_tokens) e la
blocca se sforerebbe un tetto; dopo, `check` ferma il run se un tetto è stato superato. Più
processi in parallelo condividono il registro ma vedono la spesa degli altri solo all'avvio.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import progress


class BudgetExceeded(Exception):
    pass


def ledger_path(cfg) -> Path:
    """Registro della spesa: `<cache_dir>/spend.jsonl`, o DEMOGEN_SPEND_LEDGER (i test lo isolano)."""
    env = os.environ.get("DEMOGEN_SPEND_LEDGER")
    return Path(env) if env else Path(cfg.cache_dir) / "spend.jsonl"


def read_ledger(path: Path | None) -> list[dict]:
    """Righe del registro della spesa (quelle rotte si saltano: il registro non deve mai bloccare)."""
    if path is None or not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("cost"), (int, float)):
            out.append(row)
    return out


def spend_totals(rows: list[dict], now: datetime | None = None) -> tuple[float, float]:
    """(spesa di oggi, spesa del mese) in ora locale."""
    now = now or datetime.now()
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    d = sum(float(r["cost"]) for r in rows if str(r.get("ts", "")).startswith(day))
    m = sum(float(r["cost"]) for r in rows if str(r.get("ts", "")).startswith(month))
    return d, m


@dataclass
class Budget:
    max_total_cost_usd: float
    max_wall_minutes: float
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)
    spent_usd: float = 0.0
    started: float = field(default_factory=time.monotonic)
    max_daily_cost_usd: float | None = None
    max_monthly_cost_usd: float | None = None
    max_calls: int | None = None
    calls: int = 0
    ledger: Path | None = None  # None: nessun registro (test, models check senza cache)
    project: str = ""
    day_spent: float = 0.0  # spesa di oggi e del mese all'avvio + quella di questo processo
    month_spent: float = 0.0

    @classmethod
    def from_config(cls, cfg, spent_usd: float = 0.0, project: str = "") -> Budget:
        """`spent_usd`: spesa già fatta dal progetto (state.json): al resume il tetto per run non riparte da zero."""
        b = cfg.budget
        ledger = ledger_path(cfg)
        day, month = spend_totals(read_ledger(ledger))
        return cls(
            max_total_cost_usd=b.max_total_cost_usd,
            max_wall_minutes=b.max_wall_minutes,
            pricing=cfg.pricing,
            spent_usd=float(spent_usd or 0.0),
            max_daily_cost_usd=b.max_daily_cost_usd,
            max_monthly_cost_usd=b.max_monthly_cost_usd,
            max_calls=b.max_calls_per_run,
            ledger=ledger,
            project=project,
            day_spent=day,
            month_spent=month,
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

    def _caps(self) -> list[tuple[str, float, float | None]]:
        """(nome, speso, tetto) per ogni tetto in USD."""
        return [
            ("per-run", self.spent_usd, self.max_total_cost_usd),
            ("daily", self.day_spent, self.max_daily_cost_usd),
            ("monthly", self.month_spent, self.max_monthly_cost_usd),
        ]

    def blocking_cap(self, model: str, max_tokens: int) -> str | None:
        """Il tetto che una chiamata a `model` con `max_tokens` potrebbe sforare (None: si può fare)."""
        est = self.max_cost_of(model, max_tokens)
        for name, spent, cap in self._caps():
            if cap is not None and spent + est > cap:
                return (f"{name} cap: a call to {model} could cost up to {est:.4f} USD, "
                        f"{spent:.4f} of {cap:g} USD already spent")
        if self.max_calls is not None and self.calls >= self.max_calls:
            return f"call cap: {self.calls} of {self.max_calls} LLM calls already made in this run"
        return None

    def can_afford(self, model: str, max_tokens: int) -> bool:
        return self.blocking_cap(model, max_tokens) is None

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
        self.day_spent += cost
        self.month_spent += cost
        self.calls += 1
        self._log(model, cost)
        progress.emit("budget", spent=self.spent_usd, cap=self.max_total_cost_usd,
                      day=self.day_spent, day_cap=self.max_daily_cost_usd,
                      month=self.month_spent, month_cap=self.max_monthly_cost_usd)
        return cost

    def _log(self, model: str, cost: float) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            row = {"ts": datetime.now().isoformat(timespec="seconds"), "project": self.project,
                   "model": model, "cost": round(float(cost), 8)}
            with self.ledger.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass  # il registro è di servizio: non deve mai fermare la generazione

    def check(self) -> None:
        for name, spent, cap in self._caps():
            if cap is not None and spent > cap:
                raise BudgetExceeded(f"{name} spending cap exceeded: {spent:.4f} > {cap:g} USD")
        if self.max_calls is not None and self.calls > self.max_calls:
            raise BudgetExceeded(f"call cap exceeded: {self.calls} > {self.max_calls} LLM calls")
        elapsed_min = (time.monotonic() - self.started) / 60
        if elapsed_min > self.max_wall_minutes:
            raise BudgetExceeded(f"time cap exceeded: {elapsed_min:.1f} > {self.max_wall_minutes} min")
