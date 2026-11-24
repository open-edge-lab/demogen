"""Genera il riferimento API della libreria dai doc-comment `///` → markdown.

Iniettato nei prompt LLM (Fase 5) come plastica stabile cacheable.
"""

from __future__ import annotations

import re
from pathlib import Path

MARKER = re.compile(r"^///\s*@fn\s+(\w+)\s*$", re.MULTILINE)


def generate_api_reference(lib_dir: Path, out_path: Path | None = None) -> str:
    lines = ["# Libreria GLSL demogen (GLSL ES 3.00)", ""]
    for path in sorted(lib_dir.rglob("*.glsl")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(lib_dir)
        markers = list(MARKER.finditer(text))
        if not markers:
            continue
        lines.append(f"## `{rel}`")
        lines.append("")
        for i, m in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            block = text[m.start() : end].strip().splitlines()
            doc = [ln[3:].strip() for ln in block if ln.startswith("///") and "@fn" not in ln]
            # firma: prima riga non-doc dopo il marker
            sig = next((ln for ln in block if ln and not ln.startswith("///")), "")
            lines.append(f"### `{m.group(1)}`")
            lines.append("")
            if doc:
                lines.extend(doc)
                lines.append("")
            lines.append("```glsl")
            lines.append(sig)
            lines.append("```")
            lines.append("")
    md = "\n".join(lines)
    if out_path is not None:
        out_path.write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    lib = Path(__file__).resolve().parent / "lib"
    out = Path(__file__).resolve().parents[2] / "docs" / "api-libreria-glsl.md"
    print(generate_api_reference(lib, out)[:200])
    print(f"... → {out}")
