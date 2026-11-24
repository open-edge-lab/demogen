"""Minify base del GLSL: toglie commenti e spazi, accorcia i letterali float.

Non rinomina gli identificatori (minify aggressivo = Fase 7 con tool esterno).
Preserva le righe che iniziano con # (direttive preprocessor).
"""

from __future__ import annotations

import re

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_WS = re.compile(r"[ \t]+")
_AROUND_OP = re.compile(r"\s*([+\-*/%<>=!&|^~,;(){}\[\]])\s*")
_FLOAT_INT = re.compile(r"\b(\d+)\.0+\b")
_FLOAT_LEAD = re.compile(r"\b0\.(\d+)")
_FLOAT_TRAIL = re.compile(r"\.(\d+)")


def minify(src: str) -> str:
    src = _BLOCK_COMMENT.sub(" ", src)
    src = _LINE_COMMENT.sub("", src)
    out_lines: list[str] = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out_lines.append(stripped)  # direktive: una per riga, non toccarle
            continue
        line = _WS.sub(" ", line)
        line = _AROUND_OP.sub(r"\1", line)
        line = _FLOAT_INT.sub(r"\1.", line)
        line = _FLOAT_LEAD.sub(r".\1", line)
        line = line.strip()
        if line:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"
