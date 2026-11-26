"""Errori del provider LLM in chiaro: cosa è successo, il messaggio del provider, quale chiamata, cosa fare.

Usato dalla CLI (niente traceback), dal pannello dal vivo e da `models check`. OpenRouter mette
il testo utile in `body["error"]["message"]` e l'errore del provider a monte in
`metadata.raw`: `str(e)` invece restituisce un dict Python poco leggibile.
"""

from __future__ import annotations

from dataclasses import dataclass

_TITLES = {
    400: "request rejected by the LLM provider",
    401: "invalid LLM provider key",
    402: "insufficient credit on the LLM provider key",
    403: "the key is not allowed to use this model",
    404: "model not found by the provider",
    408: "the provider timed out",
    413: "request too large for the model",
    429: "too many requests: provider rate limit",
}
_HINTS = {
    400: "often a parameter the model does not support: try `demogen models check` (menu: LLM config)",
    401: "check providers.<name>.api_key in demogen.yaml (or the environment variable named in api_key_env)",
    402: ("top up the credit or raise the key limit (OpenRouter: Settings > Keys); or lower "
          "roles.<role>.max_tokens in demogen.yaml"),
    403: "check the key permissions and roles.<role>.model in demogen.yaml",
    404: "check roles.<role>.model in demogen.yaml: it must be the exact model id on the provider",
    408: "retry; if it keeps happening raise roles.<role>.timeout_s",
    413: "the prompt is too long for this model: pick one with a larger context",
    429: "wait a few minutes or lower budget.llm_concurrency in demogen.yaml",
}


@dataclass
class LLMErrorInfo:
    title: str
    detail: str = ""
    hint: str = ""
    where: str = ""

    def text(self, then: str = "") -> str:
        lines = [f"ERROR: {self.title}"]
        if self.where:
            lines.append(f"  call:       {self.where}")
        if self.detail:
            lines.append(f"  message:    {self.detail}")
        if self.hint:
            lines.append(f"  what to do: {self.hint}")
        if then:
            lines.append(f"  then:       {then}")
        return "\n".join(lines)


def provider_message(e: BaseException) -> str:
    """Il testo dell'errore come lo scrive il provider (OpenRouter: error.message + metadata.raw)."""
    body = getattr(e, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(err, dict) and err.get("message"):
        msg = str(err["message"]).strip()
        meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
        raw, prov = meta.get("raw"), meta.get("provider_name")
        if raw:
            msg += f" [{'provider ' + str(prov) + ': ' if prov else ''}{str(raw).strip()[:300]}]"
        return msg
    return str(getattr(e, "message", "") or e).strip()


def call_of(e: BaseException) -> str:
    """Quale chiamata è fallita (ruolo · modello · passo), se registrata da progress.llm_call."""
    c = getattr(e, "demogen_call", None)
    if not isinstance(c, dict):
        return ""
    return f"{c.get('role')} · {c.get('model')} · step {c.get('step') or '-'}"


def describe_llm_error(e: BaseException) -> LLMErrorInfo | None:
    """None se non è un errore del provider LLM (allora resta un errore normale)."""
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    from .client import LLMBadResponse, LLMTruncated

    where = call_of(e)
    if isinstance(e, APIStatusError):
        s = e.status_code
        if s in _TITLES:
            title = f"{_TITLES[s]} ({s})"
        elif s is not None and s >= 500:
            title = f"LLM provider-side error ({s})"
        else:
            title = f"the LLM provider answered with error {s}"
        hint = _HINTS.get(s, "retry later; if it persists, try another model in demogen.yaml"
                          if s is not None and s >= 500 else "")
        return LLMErrorInfo(title, provider_message(e), hint, where)
    if isinstance(e, APITimeoutError):  # prima di APIConnectionError: ne è una sottoclasse
        return LLMErrorInfo("the LLM provider did not answer in time (timeout, even after retries)",
                            provider_message(e), "check the connection or raise roles.<role>.timeout_s", where)
    if isinstance(e, APIConnectionError):
        return LLMErrorInfo("could not connect to the LLM provider (even after retries)", provider_message(e),
                            "check the internet connection and providers.<name>.base_url", where)
    if isinstance(e, LLMBadResponse):
        return LLMErrorInfo("invalid answer from the LLM provider", str(e)[:300], "retry; if it persists, change model",
                            where)
    if isinstance(e, LLMTruncated):
        return LLMErrorInfo("answer truncated even with twice the tokens", str(e)[:300],
                            "raise roles.<role>.max_tokens or lower extra_body.reasoning.effort in demogen.yaml",
                            where)
    return None
