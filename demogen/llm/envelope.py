"""Envelope delle risposte LLM [D8]: un blocco ```json (metadati) + N blocchi
```glsl (codice). Il GLSL viaggia fuori dal JSON per evitare errori di escaping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

ANY_BLOCK = re.compile(r"```(\w*)\s*(.*?)```", re.DOTALL)


class EnvelopeError(ValueError):
    """Envelope malformato: blocco json/glsl mancante o JSON non valido."""


@dataclass
class Envelope:
    json_text: str | None
    glsl_blocks: list[str] = field(default_factory=list)
    other_blocks: dict[str, list[str]] = field(default_factory=dict)
    raw: str = ""

    def json(self) -> dict:
        if self.json_text is None:
            raise EnvelopeError("Nessun blocco ```json nella risposta")
        try:
            data = json.loads(self.json_text)
        except json.JSONDecodeError as e:
            raise EnvelopeError(f"blocco ```json non valido: {e}") from e
        if not isinstance(data, dict):
            raise EnvelopeError("il blocco ```json deve essere un oggetto")
        return data

    def glsl(self, i: int = 0) -> str:
        """i-esimo blocco ```glsl; ripiega su un blocco senza linguaggio che contiene mainImage."""
        if i < len(self.glsl_blocks):
            return self.glsl_blocks[i]
        if i == 0:
            for lang in ("glsl", "c", "cpp", "hlsl", "text"):
                for body in self.other_blocks.get(lang, []):
                    if "mainImage" in body:
                        return body
        raise EnvelopeError(f"Nessun blocco ```glsl #{i} nella risposta")


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
