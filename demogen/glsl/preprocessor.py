"""Preprocessor GLSL minimale: #include (include-once, path confinati), mappa righe.

Risoluzione di `#include "x.glsl"`: prima rispetto alla cartella del file che include,
poi rispetto a `base_dir`, poi alla libreria (demogen/glsl/lib). Il path deve essere
relativo e restare dentro `base_dir` o la libreria: niente path assoluti né `..` che
escono. Ogni file viene incluso una sola volta (include-once); un ciclo è un errore
con la catena completa.

La mappa righe permette di rimappare gli errori del compilatore sulle righe dei
sorgenti originali (file, riga).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

LIB_DIR = Path(__file__).resolve().parent / "lib"

_INCLUDE_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]\s*$')


@dataclass
class SourceMap:
    """Mappa riga del sorgente assemblato → (file, riga originale)."""

    entries: list[tuple[str, int]] = field(default_factory=list)

    def original_line(self, assembled_line: int) -> tuple[str, int]:
        if 0 < assembled_line <= len(self.entries):
            return self.entries[assembled_line - 1]
        return ("<unknown>", assembled_line)


def _resolve_include(rel: str, including_dir: Path | None, roots: list[Path], where: str) -> Path:
    if PurePosixPath(rel).is_absolute() or Path(rel).is_absolute() or re.match(r"^[A-Za-z]:", rel):
        raise ValueError(f"#include with an absolute path is not allowed: {rel!r} ({where})")
    candidates = ([including_dir] if including_dir else []) + roots
    for base in candidates:
        inc = (base / rel).resolve()
        if not any(inc.is_relative_to(r) for r in roots):
            raise ValueError(f"#include outside the allowed folders: {rel!r} ({where})")
        if inc.exists():
            return inc
    raise FileNotFoundError(f"#include not found: {rel} ({where})")


def preprocess(src: str, base_dir: Path | None = None, max_depth: int = 8) -> tuple[str, SourceMap]:
    """Espande gli #include ricorsivamente. Ritorna (sorgente, mappa_righe)."""
    roots = list(dict.fromkeys(p.resolve() for p in (base_dir or LIB_DIR, LIB_DIR)))
    smap = SourceMap()
    out_lines: list[str] = []
    included: set[Path] = set()

    def expand(text: str, fname: str, here: Path | None, stack: list[str]) -> None:
        if len(stack) > max_depth:
            raise ValueError(f"#include nested too deeply (>{max_depth}): {' -> '.join(stack)}")
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _INCLUDE_RE.match(line)
            if not m:
                out_lines.append(line)
                smap.entries.append((fname, lineno))
                continue
            inc = _resolve_include(m.group(1), here, roots, f"{fname}:{lineno}")
            key = str(inc)
            if key in stack:
                raise ValueError(f"cyclic #include: {' -> '.join([*stack, key])}")
            if inc in included:
                continue  # include-once
            included.add(inc)
            expand(inc.read_text(encoding="utf-8"), key, inc.parent, [*stack, key])

    expand(src, "<input>", None, ["<input>"])
    return "\n".join(out_lines) + "\n", smap
