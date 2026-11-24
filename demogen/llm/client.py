"""Client LLM unificato (SDK openai, base_url arbitrario).

- retry con backoff esponenziale + jitter su 429/5xx/timeout/connessioni (max N)
- log di ogni chiamata in JSON con rédaction di chiavi/Authorization
- usage e costo (campo extra di OpenRouter se presente, altrimenti tabella prezzi)
- versione async (achat) per le chiamate parallele delle scene
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

from ..config import Config, resolve_role
from .budget import Budget, BudgetExceeded
from .providers import api_key_for, base_url_for

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|api[_-]?key['\"]?\s*[:=]\s*['\"]?[^\s,'\"]+)",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    return SECRET_RE.sub("***", text)


def _redact_messages(messages: list[dict]) -> list[dict]:
    """Sostituisce le immagini inline con un riferimento (niente base64 nei log)."""
    out = []
    for m in messages:
        m2 = dict(m)
        content = m2.get("content")
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    url = str(p.get("image_url", {}).get("url", ""))
                    ref = f"[data:image, {len(url)} chars]"
                    parts.append({"type": "image_url", "image_url": ref})
                else:
                    parts.append(p)
            m2["content"] = parts
        out.append(m2)
    return out


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, Any]
    cost_usd: float | None
    latency_s: float
    raw: dict[str, Any]


class LLMClient:
    def __init__(
        self,
        config: Config,
        role: str,
        *,
        log_dir: Path | str | None = None,
        max_retries: int = 4,
        budget: Budget | None = None,
    ) -> None:
        self.role = role
        self.role_cfg = resolve_role(config, role)
        prov = config.providers[self.role_cfg.provider]
        self.base_url = base_url_for(prov)
        key = api_key_for(prov)
        self.api_key = key or "EMPTY"
        self.model = self.role_cfg.model
        self.max_retries = max_retries
        self.budget = budget
        self.log_dir = Path(log_dir) if log_dir else Path(config.log_dir)
        self._counter = 0
        http_kwargs = dict(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers=dict(prov.headers),
            timeout=self.role_cfg.timeout_s,
            max_retries=0,  # il retry lo gestiamo noi (backoff + jitter + log)
        )
        self._client = OpenAI(**http_kwargs)
        self._aclient = AsyncOpenAI(**http_kwargs)

    def _next_log(self, step: str) -> Path:
        self._counter += 1
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_step = re.sub(r"[^\w.-]", "_", step)[:40]
        return self.log_dir / f"{self._counter:04d}_{self.role}_{safe_step}.json"

    def _log(self, path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )

    def _kwargs(
        self,
        messages: list[dict],
        max_tokens: int | None,
        temperature: float | None,
        response_format: dict | None,
        extra_body: dict | None,
    ) -> dict:
        kw: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.role_cfg.max_tokens,
            "temperature": (
                temperature if temperature is not None else self.role_cfg.temperature
            ),
        }
        if response_format is not None:
            kw["response_format"] = response_format
        eb = {**self.role_cfg.extra_body, **(extra_body or {})}
        if eb:
            kw["extra_body"] = eb
        return kw

    def _extract(self, resp, latency_s: float) -> LLMResponse:
        content = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage is not None else {}
        cost: float | None = None
        if resp.usage is not None:
            extra = getattr(resp.usage, "model_extra", None) or {}
            for k in ("cost", "total_cost", "cost_usd"):
                if k in extra:
                    cost = float(extra[k])
                    break
        return LLMResponse(
            content=content,
            model=resp.model or self.model,
            usage=usage,
            cost_usd=cost,
            latency_s=latency_s,
            raw=resp.model_dump(),
        )

    def _finalize(self, r: LLMResponse, kw: dict, step: str, raw_req: dict) -> LLMResponse:
        if self.budget is not None:
            r.cost_usd = self.budget.add(
                r.model,
                r.usage.get("prompt_tokens", 0),
                r.usage.get("completion_tokens", 0),
                r.cost_usd,
            )
            self.budget.check()
        self._log(
            self._next_log(step),
            {
                "role": self.role,
                "model": r.model,
                "request": redact(json.dumps(raw_req, default=str)),
                "messages": _redact_messages(kw["messages"]),
                "response": redact(r.content),
                "usage": r.usage,
                "cost_usd": r.cost_usd,
                "latency_s": round(r.latency_s, 3),
            },
        )
        return r

    def chat(
        self,
        messages: list[dict],
        *,
        step: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
        extra_body: dict | None = None,
    ) -> LLMResponse:
        kw = self._kwargs(messages, max_tokens, temperature, response_format, extra_body)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.budget is not None and not self.budget.can_afford(self.model, kw["max_tokens"]):
                raise BudgetExceeded(
                    f"budget: una chiamata a {self.model} costerebbe più del residuo "
                    f"({self.budget.spent_usd:.4f}/{self.budget.max_total_cost_usd} USD)"
                )
            t0 = time.monotonic()
            try:
                resp = self._client.chat.completions.create(**kw)
                r = self._extract(resp, time.monotonic() - t0)
                raw_req = {"kwargs": {k: v for k, v in kw.items() if k != "messages"}}
                return self._finalize(r, kw, step, raw_req)
            except (APITimeoutError, APIConnectionError) as e:
                last_err = e
            except APIStatusError as e:
                if e.status_code is not None and e.status_code < 500 and e.status_code != 429:
                    raise  # 4xx non recuperabili (es. 401, 400)
                last_err = e
            if attempt < self.max_retries:
                time.sleep(min(2**attempt, 30) * (0.5 + random.random()))
        assert last_err is not None
        raise last_err

    async def achat(
        self,
        messages: list[dict],
        *,
        step: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
        extra_body: dict | None = None,
    ) -> LLMResponse:
        kw = self._kwargs(messages, max_tokens, temperature, response_format, extra_body)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.budget is not None and not self.budget.can_afford(self.model, kw["max_tokens"]):
                raise BudgetExceeded("budget superato prima della chiamata")
            t0 = time.monotonic()
            try:
                resp = await self._aclient.chat.completions.create(**kw)
                r = self._extract(resp, time.monotonic() - t0)
                return self._finalize(r, kw, step, {})
            except (APITimeoutError, APIConnectionError) as e:
                last_err = e
            except APIStatusError as e:
                if e.status_code is not None and e.status_code < 500 and e.status_code != 429:
                    raise
                last_err = e
            if attempt < self.max_retries:
                time.sleep(min(2**attempt, 30) * (0.5 + random.random()))
        assert last_err is not None
        raise last_err
