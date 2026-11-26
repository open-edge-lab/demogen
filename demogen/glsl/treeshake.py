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
# definizione di funzione: [qualificatore] tipo nome(params) {  — non una chiamata né un prototipo
FN_DEF = re.compile(
    r"^\s*((?:(?:highp|mediump|lowp|precise)\s+)?[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*\([^;{)]*\))\s*\{",
    re.MULTILINE,
)
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def defined_signatures(src: str) -> dict[str, str]:
    """{nome: firma} delle funzioni DEFINITE (con corpo) in un sorgente GLSL, commenti esclusi."""
    return {name: " ".join(sig.split()) for sig, name in FN_DEF.findall(_COMMENTS.sub(" ", src))}


def defined_functions(src: str) -> set[str]:
    return set(defined_signatures(src))


def load_library(lib_dir: Path) -> dict[str, str]:
    """Ritorna {nome_funzione: blocco_sorgente (doc + definizione + corpo)}."""
    funcs: dict[str, str] = {}
    where: dict[str, Path] = {}
    for path in sorted(lib_dir.rglob("*.glsl")):
        text = path.read_text(encoding="utf-8")
        markers = list(FN_MARKER.finditer(text))
        for i, m in enumerate(markers):
            name = m.group(1)
            if name in funcs:  # una seconda definizione sovrascriverebbe la prima in silenzio
                raise ValueError(f"@fn {name} duplicated in the library: {where[name].name} and {path.name}")
            start = m.start()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            funcs[name] = text[start:end].strip() + "\n"
            where[name] = path
    return funcs


def _called_names(body: str, known: set[str]) -> set[str]:
    return {n for n in known if re.search(rf"\b{re.escape(n)}\s*\(", body)}


def treeshake(entry_src: str, lib_funcs: dict[str, str]) -> str:
    """Ritorna il sottoinsieme della libreria raggiungibile dagli entry point.

    entry_src: sorgente della scena + style (contiene mainImage e le chiamate).
    Le funzioni sono emesse in ordine topologico (dipendenze prima dell'uso),
    perché GLSL ES 3.00 richiede la dichiarazione prima della chiamata.
    Le funzioni che l'entry definisce già NON vengono importate dalla libreria
    (sarebbe una ridefinizione: errore di compilazione); se una funzione di libreria
    inclusa le chiama, si emette il prototipo con la firma dell'entry, perché il
    common precede la scena.
    """
    own = defined_signatures(entry_src)
    known = set(lib_funcs) - set(own)
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
    body = "\n".join(lib_funcs[n] for n in ordered)
    protos = [f"{own[n]};" for n in sorted(own) if n in lib_funcs and _called_names(body, {n})]
    return ("\n".join(protos) + "\n" if protos else "") + body


def shared_common_conflicts(scenes: dict[str, str], style: str, lib_funcs: dict[str, str]) -> list[str]:
    """Conflitti del common CONDIVISO tra scene: una scena ridefinisce una funzione di
    libreria che un'altra scena (o la libreria che usa) chiama senza definirla."""
    defs = {k: defined_functions(src) for k, src in scenes.items()}
    out: list[str] = []
    for k, src in scenes.items():
        others = set().union(*(d for j, d in defs.items() if j != k)) & set(lib_funcs)
        others -= defs[k]
        if not others:
            continue
        closure = treeshake(src + "\n" + style, lib_funcs)
        needed = _called_names(src + "\n" + closure, others)
        for name in sorted(needed):
            owners = sorted(j for j, d in defs.items() if name in d)
            out.append(f"scene {k} uses the library function {name}(), but {', '.join(owners)} redefines it "
                       "and the common code is shared: rename the scene's function")
    return out
