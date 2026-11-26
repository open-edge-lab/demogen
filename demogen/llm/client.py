"""Client LLM unificato (SDK openai, base_url arbitrario).

- retry con backoff esponenziale + jitter su 429/5xx/timeout/connessioni (max N)
- log di ogni chiamata in JSON con rédaction di chiavi/Authorization
- usage e costo (campo extra di OpenRouter se presente, altrimenti tabella prezzi)
- versione async (achat) per le chiamate parallele delle scene
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

from .. import progress
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
    finish_reason: str | None = None


class LLMBadResponse(Exception):
    """Risposta 200 senza `choices` (alcuni provider restituiscono un errore nel body): ritentabile."""


class LLMTruncated(Exception):
    """finish_reason == "length": la risposta è stata troncata (già pagata e loggata)."""

    def __init__(self, response: LLMResponse) -> None:
        super().__init__(
            f"response truncated (finish_reason=length, {response.usage.get('completion_tokens', '?')} tokens)"
        )
        self.response = response


MAX_TOKENS_CAP = 65536


def grown_max_tokens(client, max_tokens: int | None) -> int:
    """Il doppio dei token della chiamata (tetto MAX_TOKENS_CAP): i modelli con reasoning
    possono consumare quasi tutto il budget nel ragionamento e troncare la risposta."""
    base = max_tokens or getattr(getattr(client, "role_cfg", None), "max_tokens", 4096)
    return min(MAX_TOKENS_CAP, int(base) * 2)


def chat_with_room(client, messages: list[dict], *, step: str = "", **kw) -> LLMResponse:
    """chat(); se la risposta è troncata (finish_reason=length) riprova UNA volta col doppio dei token."""
    try:
        return client.chat(messages, step=step, **kw)
    except LLMTruncated:
        kw["max_tokens"] = grown_max_tokens(client, kw.get("max_tokens"))
        return client.chat(messages, step=step + ":retry", **kw)


async def achat_with_room(client, messages: list[dict], *, step: str = "", **kw) -> LLMResponse:
    """Come chat_with_room, async."""
    try:
        return await client.achat(messages, step=step, **kw)
    except LLMTruncated:
        kw["max_tokens"] = grown_max_tokens(client, kw.get("max_tokens"))
        return await client.achat(messages, step=step + ":retry", **kw)


def _backoff(attempt: int) -> float:
    """Attesa prima del retry `attempt`: esponenziale (max 30 s) con jitter."""
    return min(2**attempt, 30) * (0.5 + random.random())


_LOG_NAME = re.compile(r"^(\d{4,})_")


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
        if not key and prov.type == "openrouter":
            raise ValueError(
                f"Role '{role}': missing API key for provider '{self.role_cfg.provider}' "
                "(set providers.<name>.api_key in demogen.yaml or the environment variable named by api_key_env)"
            )
        self.api_key = key or "EMPTY"  # openai_compatible locali accettano una chiave fittizia
        self.model = self.role_cfg.model
        self.max_retries = max_retries
        self.budget = budget
        self.log_dir = Path(log_dir) if log_dir else Path(config.log_dir)
        # riparte dal massimo esistente: al resume i log precedenti non vengono sovrascritti
        self._counter = self._max_log_index()
        http_kwargs = dict(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers=dict(prov.headers),
            timeout=self.role_cfg.timeout_s,
            max_retries=0,  # il retry lo gestiamo noi (backoff + jitter + log)
        )
        self._client = OpenAI(**http_kwargs)
        self._aclient = AsyncOpenAI(**http_kwargs)

    def _max_log_index(self) -> int:
        if not self.log_dir.is_dir():
            return 0
        idx = [int(m.group(1)) for p in self.log_dir.glob("*.json") if (m := _LOG_NAME.match(p.name))]
        return max(idx, default=0)

    def _next_log(self, step: str) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_step = re.sub(r"[^\w.-]", "_", step)[:40]
        # più client (ruoli) condividono la cartella: mai sovrascrivere un log esistente
        self._counter = max(self._counter, self._max_log_index())
        while True:
            self._counter += 1
            path = self.log_dir / f"{self._counter:04d}_{self.role}_{safe_step}.json"
            if not path.exists():
                return path

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
        if not getattr(resp, "choices", None):
            raise LLMBadResponse(f"response without choices:{redact(str(resp))[:300]}")
        choice = resp.choices[0]
        content = (choice.message.content if choice.message is not None else None) or ""
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
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def _finalize(self, r: LLMResponse, kw: dict, step: str) -> LLMResponse:
        """Addebita, logga e SOLO DOPO controlla budget/troncamento (la risposta è già pagata)."""
        if self.budget is not None:
            # prezzo per l'id CONFIGURATO: resp.model può essere un alias/versione del provider
            r.cost_usd = self.budget.add(
                self.model,
                r.usage.get("prompt_tokens", 0) or 0,
                r.usage.get("completion_tokens", 0) or 0,
                r.cost_usd,
            )
        raw_req = {"kwargs": {k: v for k, v in kw.items() if k != "messages"}}
        self._log(
            self._next_log(step),
            {
                "role": self.role,
                "model": r.model,
                "request": redact(json.dumps(raw_req, default=str)),
                "messages": _redact_messages(kw["messages"]),
                "response": redact(r.content),
                "finish_reason": r.finish_reason,
                "usage": r.usage,
                "cost_usd": r.cost_usd,
                "latency_s": round(r.latency_s, 3),
            },
        )
        if self.budget is not None:
            self.budget.check()
        if r.finish_reason == "length":
            raise LLMTruncated(r)
        return r

    def _finalize_reported(self, r: LLMResponse, kw: dict, step: str, call: dict) -> LLMResponse:
        """_finalize + dati della chiamata per l'evento `llm.end` (anche se la risposta è troncata)."""
        try:
            return self._finalize(r, kw, step)
        finally:
            call.update(
                cost=r.cost_usd,
                prompt_tokens=r.usage.get("prompt_tokens", 0) or 0,
                completion_tokens=r.usage.get("completion_tokens", 0) or 0,
                latency=r.latency_s,
            )

    def _precheck(self, kw: dict) -> None:
        if self.budget is None:
            return
        reason = self.budget.blocking_cap(self.model, kw["max_tokens"])
        if reason is not None:
            raise BudgetExceeded(f"budget: {reason}")

    @staticmethod
    def _retryable(e: Exception) -> bool:
        if isinstance(e, (APITimeoutError, APIConnectionError, LLMBadResponse)):
            return True
        if isinstance(e, APIStatusError):
            # 4xx non recuperabili (400, 401, 404...), tranne il rate limit
            return e.status_code is None or e.status_code >= 500 or e.status_code == 429
        return False

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
        with progress.llm_call(self.role, self.model, step) as call:
            for attempt in range(self.max_retries + 1):
                self._precheck(kw)
                t0 = time.monotonic()
                try:
                    resp = self._client.chat.completions.create(**kw)
                    r = self._extract(resp, time.monotonic() - t0)
                except Exception as e:  # noqa: BLE001 - classificato da _retryable
                    if not self._retryable(e):
                        raise
                    last_err = e
                else:
                    return self._finalize_reported(r, kw, step, call)
                if attempt < self.max_retries:
                    time.sleep(_backoff(attempt))
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
        with progress.llm_call(self.role, self.model, step) as call:
            for attempt in range(self.max_retries + 1):
                self._precheck(kw)
                t0 = time.monotonic()
                try:
                    resp = await self._aclient.chat.completions.create(**kw)
                    r = self._extract(resp, time.monotonic() - t0)
                except Exception as e:  # noqa: BLE001 - classificato da _retryable
                    if not self._retryable(e):
                        raise
                    last_err = e
                else:
                    return self._finalize_reported(r, kw, step, call)
                if attempt < self.max_retries:
                    await asyncio.sleep(_backoff(attempt))  # mai time.sleep: bloccherebbe le altre scene
            assert last_err is not None
            raise last_err
