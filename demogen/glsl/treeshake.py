"""Tree-shaking della libreria GLSL.

Convenzione della libreria (§7 del piano): ogni funzione è preceduta dal
marker `/// @fn <nome>`. Il grafo delle chiamate si ricava cercando gli
identificatori delle funzioni definite dentro i corpi. Entry point: gli
identificatori usati nello shader di scena (mainImage + altro) e in style.
"""

from __future__ import annotations

import re
from pathlib import Path

FN_MARKER = re.compile(r"^///\s*@fn\s+(\w+)\s*$", re.MULTILINE)
FN_DEF = re.compile(r"^[\w\[\]<>,\s\*]+?\b(\w+)\s*\(", re.MULTILINE)


def load_library(lib_dir: Path) -> dict[str, str]:
    """Ritorna {nome_funzione: blocco_sorgente (doc + definizione + corpo)}."""
    funcs: dict[str, str] = {}
    for path in sorted(lib_dir.rglob("*.glsl")):
        text = path.read_text(encoding="utf-8")
        markers = list(FN_MARKER.finditer(text))
        for i, m in enumerate(markers):
            name = m.group(1)
            start = m.start()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            funcs[name] = text[start:end].strip() + "\n"
    return funcs


def _called_names(body: str, known: set[str]) -> set[str]:
    return {n for n in known if re.search(rf"\b{re.escape(n)}\s*\(", body)}


def treeshake(entry_src: str, lib_funcs: dict[str, str]) -> str:
    """Ritorna il sottoinsieme della libreria raggiungibile dagli entry point.

    entry_src: sorgente della scena + style (contiene mainImage e le chiamate).
    Le funzioni sono emesse in ordine topologico (dipendenze prima dell'uso),
    perché GLSL ES 3.00 richiede la dichiarazione prima della chiamata.
    """
    known = set(lib_funcs)
    # entry points: funzioni della libreria chiamate direttamente dall'entry
    used = _called_names(entry_src, known)
    queue = list(used)
    seen = set(used)
    while queue:
        name = queue.pop()
        for dep in _called_names(lib_funcs.get(name, ""), known):
            if dep not in seen:
                seen.add(dep)
                queue.append(dep)
    # topological sort: una funzione viene dopo tutte le sue dipendenze
    # (escludendo il self-loop: la definizione contiene "nome(")
    deps = {n: (_called_names(lib_funcs[n], known) & seen) - {n} for n in seen}
    ordered: list[str] = []
    placed: set[str] = set()
    pending = set(seen)
    while pending:
        progressed = False
        for n in sorted(pending):
            if deps[n] <= placed:
                ordered.append(n)
                placed.add(n)
                pending.discard(n)
                progressed = True
        if not progressed:  # ciclo: appendi in ordine alfabetico per non bloccare
            ordered.extend(sorted(pending))
            break
    return "\n".join(lib_funcs[n] for n in ordered)
