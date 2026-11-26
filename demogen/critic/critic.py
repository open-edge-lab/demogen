"""Chiamata al ruolo LLM critic (vision) — il materiale (sheets + metriche) è
prodotto da sheets.py/metrics; qui solo l'invocazione (usata dalla Fase 5)."""

from __future__ import annotations

import base64
from pathlib import Path

from ..config import Config
from ..llm.budget import Budget
from ..llm.capabilities import detect_capabilities
from ..llm.client import LLMClient
from ..llm.structured import chat_structured
from .models import CriticReport


def _img_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def critique(
    cfg: Config,
    role: str,
    *,
    prompt: str,
    images: list[Path],
    metrics_json: str,
    log_dir: Path | None = None,
    client: LLMClient | None = None,
    budget: Budget | None = None,
) -> CriticReport:
    """Invia prompt + fogli + metriche al critic e parsea il CriticReport."""
    if client is None:
        client = LLMClient(cfg, role, log_dir=log_dir, budget=budget)
    caps = detect_capabilities(cfg, role)
    if not caps.vision:
        raise RuntimeError(f"role {role} has no vision: a degraded metrics-only critique is not available here")
    content: list[dict] = [{"type": "text", "text": prompt + "\n\nMetrics (JSON):\n" + metrics_json}]
    for p in images:
        content.append(_img_part(p))
    messages = [{"role": "user", "content": content}]
    return chat_structured(client, messages, CriticReport, step="critique", caps=caps)
