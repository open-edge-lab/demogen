"""Minify base del GLSL: toglie commenti e spazi, accorcia i letterali float.

Non rinomina gli identificatori (minify aggressivo = Fase 7 con tool esterno).
Preserva le righe che iniziano con # (direttive preprocessor).
"""

from __future__ import annotations

import re

# commenti in UN solo passaggio: vince quello che inizia prima, quindi `// TODO /*`
# non apre un blocco che si mangerebbe il codice fino al `*/` successivo
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_WS = re.compile(r"[ \t]+")
_AROUND_OP = re.compile(r"\s*([+\-*/%<>=!&|^~,;(){}\[\]?:])\s*")
# `b - -c`, `e + +f`, `h - --i`: fra due segni uguali lo spazio serve (b--c è un decremento)
_SAME_SIGN = re.compile(r"([+-])\s+(?=\1)")
_KEEP = "\x00"
_FLOAT_TRAIL = re.compile(r"\b(\d+\.\d*?[1-9])0+\b")  # 1.50 → 1.5
_FLOAT_INT = re.compile(r"\b(\d+)\.0+\b")  # 1.0 → 1.
_FLOAT_LEAD = re.compile(r"\b0\.(\d+)")  # 0.5 → .5


def _drop_comment(m: re.Match[str]) -> str:
    text = m.group(0)
    if text.startswith("//"):
        return ""
    # un blocco su più righe lascia le sue righe: le direttive # restano a inizio riga
    return "\n" * text.count("\n") or " "


def minify(src: str) -> str:
    src = _COMMENTS.sub(_drop_comment, src)
    out_lines: list[str] = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out_lines.append(stripped)  # direttive: una per riga, non toccarle
            continue
        line = _WS.sub(" ", line)
        line = _SAME_SIGN.sub(lambda m: m.group(1) + _KEEP, line)
        line = _AROUND_OP.sub(r"\1", line)
        line = line.replace(_KEEP, " ")
        line = _FLOAT_TRAIL.sub(r"\1", line)
        line = _FLOAT_INT.sub(r"\1.", line)
        line = _FLOAT_LEAD.sub(r".\1", line)
        line = line.strip()
        if line:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"
