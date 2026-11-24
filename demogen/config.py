"""Configurazione demogen: YAML + env, validazione pydantic v2.

Le chiavi API arrivano SOLO da variabili d'ambiente (api_key_env), mai dal file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("demogen.yaml")
ENV_CONFIG = "DEMOGEN_CONFIG"


class ProviderConfig(BaseModel):
    type: Literal["openai_compatible", "openrouter"]
    base_url: str | None = None
    api_key_env: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class RoleConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    vision: bool | Literal["auto"] = "auto"
    json_schema: bool | Literal["auto"] = "auto"
    timeout_s: float = 600.0
    extra_body: dict = Field(default_factory=dict)
    inherit: str | None = None  # eredita i campi mancanti da un altro ruolo


class BudgetConfig(BaseModel):
    max_iterations_per_scene: int = 4
    max_fix_attempts: int = 3
    max_total_cost_usd: float = 5.0
    max_wall_minutes: float = 60.0
    llm_concurrency: int = 4


class Config(BaseModel):
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    log_dir: str = ".demogen_logs/llm_calls"
    cache_dir: str = ".demogen_cache"


def load_config(path: Path | str | None = None) -> Config:
    """Carica la config da path, oppure $DEMOGEN_CONFIG, oppure ./demogen.yaml."""
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config non trovata: {path}. Crea demogen.yaml (vedi `demogen init`)"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config.model_validate(data)


def resolve_role(cfg: Config, role: str) -> RoleConfig:
    """Risolve `inherit`: i campi espliciti del ruolo vincono su quelli ereditati."""
    r = cfg.roles[role]
    if r.inherit is None:
        return r
    base = resolve_role(cfg, r.inherit)
    merged = base.model_dump()
    merged.update({k: v for k, v in r.model_dump().items() if k != "inherit" and v is not None})
    # i default pydantic vanno ритontati solo se non espliciti: ricreo con i campi GREzzi
    raw = r.model_dump(exclude={"inherit"})
    for k, v in raw.items():
        if k in ("vision", "json_schema") and v == "auto":
            continue
        merged[k] = v
    merged["provider"] = r.provider
    merged["model"] = r.model
    return RoleConfig.model_validate(merged)
