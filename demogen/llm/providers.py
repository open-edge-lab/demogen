"""Preset provider: openai_compatible (base_url arbitrario) e openrouter."""

from __future__ import annotations

import os

from ..config import ProviderConfig

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def base_url_for(p: ProviderConfig) -> str:
    if p.type == "openrouter":
        return p.base_url or OPENROUTER_BASE_URL
    if not p.base_url:
        raise ValueError("provider openai_compatible richiede base_url")
    return p.base_url.rstrip("/")


def api_key_for(p: ProviderConfig, env: dict | None = None) -> str | None:
    """Chiave API solo da env (mai da file di config)."""
    env = os.environ if env is None else env
    if p.api_key_env:
        return env.get(p.api_key_env)
    return None
