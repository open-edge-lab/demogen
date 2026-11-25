"""Output strutturato a livelli (§8.4):

1. response_format json_schema (strict se lo schema è compatibile, se il modello lo supporta)
2. response_format json_object
3. envelope: blocco ```json estratto dal testo libero

Validazione pydantic + loop di riparazione (max 2) che rimanda l'errore. Un 4xx su un
livello (il provider non supporta quel response_format) fa passare al livello successivo.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, TypeVar

from openai import APIStatusError
from pydantic import BaseModel

from .capabilities import Capabilities
from .client import LLMClient, LLMTruncated
from .envelope import parse_envelope

T = TypeVar("T", bound=BaseModel)

# status che indicano "questo response_format non è supportato qui" → livello successivo
_LEVEL_UNSUPPORTED = {400, 404, 422}
_FENCE = re.compile(r"```[\w-]*\s*(.*?)```", re.DOTALL)


def strict_schema(model: type[BaseModel]) -> dict | None:
    """JSON schema compatibile con lo strict mode di OpenAI, oppure None se impossibile.

    Strict richiede: su ogni oggetto `additionalProperties: false` e TUTTE le properties in
    `required`; niente `default`. Un dict libero (additionalProperties con schema, es.
    `CriticReport.scores`) non è esprimibile → None (il chiamante usa strict=False).
    """
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> bool:
        """Visita SOLO le posizioni che contengono sotto-schemi (mai le mappe di nomi)."""
        if not isinstance(node, dict):
            return True
        node.pop("default", None)
        node.pop("title", None)
        ok = True
        if node.get("type") == "object" or "properties" in node:
            ap = node.get("additionalProperties")
            if isinstance(ap, dict) or ap is True:
                return False  # dict libero: non esprimibile in strict
            props = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props)
            ok = all(walk(s) for s in props.values())
        for key in ("$defs", "definitions"):
            ok = ok and all(walk(s) for s in node.get(key, {}).values())
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            ok = ok and all(walk(s) for s in node.get(key, []))
        if isinstance(node.get("items"), dict):
            ok = ok and walk(node["items"])
        return ok

    return schema if walk(schema) else None


def _schema_rf(schema: type[BaseModel]) -> dict:
    strict = strict_schema(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": strict is not None,
            "schema": strict if strict is not None else schema.model_json_schema(),
        },
    }


def loads_tolerant(text: str) -> Any:
    """JSON da una risposta LLM: puro, oppure nel primo fence ``` , oppure tra la prima `{` e l'ultima `}`."""
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(s)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        return json.loads(s[i : j + 1])
    raise ValueError("nessun oggetto JSON nella risposta")


def chat_structured(
    client: LLMClient,
    messages: list[dict],
    schema: type[T],
    *,
    step: str = "",
    caps: Capabilities | None = None,
    max_repairs: int = 2,
) -> T:
    """Chiama il modello e valida con pydantic; ripara fino a max_repairs volte per livello."""
    use_schema = caps.json_schema if caps else False
    levels: list[dict | None] = [_schema_rf(schema)] if use_schema else []
    levels += [{"type": "json_object"}, None]
    last_err: Exception | None = None
    for level in levels:
        msgs = list(messages)
        for repair in range(max_repairs + 1):
            try:
                resp = client.chat(msgs, step=step, response_format=level)
                text = resp.content
            except LLMTruncated as e:
                text = e.response.content
                last_err = e
                err_msg = "la risposta è stata troncata: restituisci un output più compatto"
            except APIStatusError as e:
                if level is not None and e.status_code in _LEVEL_UNSUPPORTED:
                    last_err = e
                    break  # questo response_format non è supportato: livello successivo
                raise
            else:
                try:
                    data = loads_tolerant(text) if level is not None else _envelope_json(text)
                    return schema.model_validate(data)
                except Exception as e:  # noqa: BLE001 - errore di parsing/validazione → riparazione
                    last_err = e
                    err_msg = f"il tuo output non valida lo schema {schema.__name__}: {e}"
            if repair < max_repairs:
                msgs = msgs + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"{err_msg}. Restituisci SOLO l'output valido, senza commenti."},
                ]
    raise ValueError(
        f"Output non valido secondo {schema.__name__} dopo tutti i livelli e {max_repairs} "
        f"riparazioni. Ultimo errore: {last_err}"
    )


def _envelope_json(text: str) -> Any:
    env = parse_envelope(text)
    if env.json_text is not None:
        return env.json()
    return loads_tolerant(text)
