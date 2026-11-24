"""Envelope delle risposte LLM [D8]: un blocco ```json (metadati) + N blocchi
```glsl (codice). Il GLSL viaggia fuori dal JSON per evitare errori di escaping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.DOTALL)
GLSL_BLOCK = re.compile(r"```glsl\s*(.*?)```", re.DOTALL)
ANY_BLOCK = re.compile(r"```(\w*)\s*(.*?)```", re.DOTALL)


@dataclass
class Envelope:
    json_text: str | None
    glsl_blocks: list[str] = field(default_factory=list)
    other_blocks: dict[str, list[str]] = field(default_factory=dict)
    raw: str = ""

    def json(self) -> dict:
        if self.json_text is None:
            raise ValueError("Nessun blocco ```json nella risposta")
        return json.loads(self.json_text)


def parse_envelope(text: str) -> Envelope:
    """Estrae il primo blocco json e tutti i blocchi glsl (ordine preservato)."""
    blocks = list(ANY_BLOCK.finditer(text))
    json_text: str | None = None
    glsl: list[str] = []
    other: dict[str, list[str]] = {}
    for m in blocks:
        lang, body = m.group(1).lower(), m.group(2).strip("\n")
        if lang == "json" and json_text is None:
            json_text = body
        elif lang == "glsl":
            glsl.append(body)
        else:
            other.setdefault(lang or "text", []).append(body)
    return Envelope(json_text=json_text, glsl_blocks=glsl, other_blocks=other, raw=text)
