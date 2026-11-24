"""Output strutturato a livelli (§8.4):

1. response_format json_schema strict (se il modello lo soporta)
2. response_format json_object
3. envelope: blocco ```json estratto dal testo libero

Validazione pydantic + loop di riparazione (max 2) che rimanda l'errore.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel

from .capabilities import Capabilities
from .client import LLMClient
from .envelope import parse_envelope

T = TypeVar("T", bound=BaseModel)


def _schema_rf(schema: type[BaseModel], strict: bool) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": strict,
            "schema": schema.model_json_schema(),
        },
    }


def chat_structured(
    client: LLMClient,
    messages: list[dict],
    schema: type[T],
    *,
    step: str = "",
    caps: Capabilities | None = None,
    max_repairs: int = 2,
) -> T:
    """Chiama il modello e valida con pydantic; ripara fino a max_repairs volte."""
    # livelli: 1) json_schema strict, 2) json_object, 3) envelope dal testo libero
    use_schema = caps.json_schema if caps else False
    levels: list[dict | None] = ([_schema_rf(schema, strict=True)] if use_schema else [])
    levels += [{"type": "json_object"}, None]
    last_err: Exception | None = None
    for level in levels:
        msgs = list(messages)
        for repair in range(max_repairs + 1):
            resp = client.chat(msgs, step=step, response_format=level)
            text = resp.content
            try:
                data = json.loads(text) if level is not None else parse_envelope(text).json()
                return schema.model_validate(data)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if repair < max_repairs:
                    msgs = msgs + [
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                f"Il tuo output non valida lo schema {schema.__name__}: {e}. "
                                "Restituisci SOLO l'output valido, senza commenti."
                            ),
                        },
                    ]
    raise ValueError(
        f"Output non valido secondo {schema.__name__} dopo tutti i livelli e {max_repairs} "
        f"riparazioni. Ultimo errore: {last_err}"
    )
