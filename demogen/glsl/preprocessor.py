"""Preprocessor GLSL minimale: #include, #define, mappa righe.

L expansión de los include se hace rispetto a `lib/` (demogen/glsl/lib).
La mappa righe permite di rimappare gli errori del compilatore sulle righe
dei sorgenti originali (file, riga).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent / "lib"

_INCLUDE_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]\s*$')


@dataclass
class SourceMap:
    """Mappa riga del sorgente assemblato → (file, riga originale)."""

    entries: list[tuple[str, int]] = field(default_factory=list)

    def original_line(self, assembled_line: int) -> tuple[str, int]:
        if 0 < assembled_line <= len(self.entries):
            return self.entries[assembled_line - 1]
        return ("<sconosciuto>", assembled_line)


def preprocess(src: str, base_dir: Path | None = None, max_depth: int = 8) -> tuple[str, SourceMap]:
    """Espande gli #include ricorsivamente. Ritorna (sorgente, mappa_righe)."""
    base = base_dir or LIB_DIR
    smap = SourceMap()
    out_lines: list[str] = []

    def expand(text: str, fname: str, depth: int) -> None:
        if depth > max_depth:
            raise ValueError(f"#include troppo annidati (>{max_depth}) da {fname}")
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _INCLUDE_RE.match(line)
            if m:
                inc = (base / m.group(1)).resolve()
                if not inc.exists():
                    raise FileNotFoundError(
                        f"#include non trovato: {m.group(1)} (da {fname}:{lineno})"
                    )
                expand(inc.read_text(encoding="utf-8"), str(inc), depth + 1)
            else:
                out_lines.append(line)
                smap.entries.append((fname, lineno))

    expand(src, "<input>", 0)
    return "\n".join(out_lines) + "\n", smap
