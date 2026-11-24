"""Unit test: preprocessor, treeshake, minify, docs."""

from __future__ import annotations

from pathlib import Path

from demogen.glsl.docs import generate_api_reference
from demogen.glsl.minify import minify
from demogen.glsl.preprocessor import preprocess
from demogen.glsl.treeshake import load_library, treeshake

LIB = Path(__file__).resolve().parents[1] / "demogen" / "glsl" / "lib"


def test_preprocess_include_e_mappa_righe() -> None:
    src = '#include "hash.glsl"\nvoid mainImage(out vec4 c, in vec2 p){ c = vec4(hash11(1.0)); }\n'
    out, smap = preprocess(src)
    assert "float hash11" in out
    # la riga di mainImage nell'assemblato rimappa al file <input>
    line_main = next(i + 1 for i, ln in enumerate(out.splitlines()) if "mainImage" in ln)
    fname, lineno = smap.original_line(line_main)
    assert fname == "<input>" and lineno == 2


def test_treeshake_include_solo_raggiungibili() -> None:
    lib = load_library(LIB)
    assert "hash11" in lib and "raymarch" in lib
    entry = "void mainImage(out vec4 c, in vec2 p){ c = vec4(hash11(p.x)); }"
    out = treeshake(entry, lib)
    assert "hash11" in out
    assert "raymarch" not in out  # non chiamata
    # fbm chiama qOctaves e vnoise → transitivi inclusi
    entry2 = "void mainImage(out vec4 c, in vec2 p){ c = vec4(fbm(p)); }"
    out2 = treeshake(entry2, lib)
    assert "fbm" in out2 and "vnoise" in out2 and "qOctaves" in out2
    assert "hash21" in out2  # vnoise usa hash21
    assert "hash11" not in out2  # non raggiungibile da fbm


def test_minify() -> None:
    src = """// commento
float x = 1.0 + 0.5;  /* blocco */
#define A 1
"""
    out = minify(src)
    assert "#define A 1" in out
    assert "1." in out and "1.0" not in out
    assert ".5" in out and "0.5" not in out
    assert "//" not in out


def test_docs_api_reference() -> None:
    md = generate_api_reference(LIB)
    assert "hash11" in md and "raymarch" in md and "retroFinalize" in md
    assert "@fn" not in md.split("###")[1]  # i marker non restano nei titoli
