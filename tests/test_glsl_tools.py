"""Unit test: preprocessor, treeshake, minify, docs."""

from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(("src", "must", "must_not"), [
    ("float a = b - -c;", "b- -c", "b--c"),
    ("float a = e + +f;", "e+ +f", "e++f"),
    ("float a = h - --i;", "h- --i", "h---i"),
    ("float a = x * -y;", "x*-y", None),
    ("float a = 1.50 + 0.250;", "1.5+.25", "1.50"),
])
def test_minify_operatori_e_float(src: str, must: str, must_not: str | None) -> None:
    out = minify(src)
    assert must in out, out
    if must_not:
        assert must_not not in out


def test_minify_commenti_nell_ordine_giusto() -> None:
    # `// TODO /*` NON apre un blocco: prima il blocco veniva tolto per primo e si mangiava b e c
    src = "float a = 1.0; // TODO /* \nfloat b = 2.0;\nfloat c = 3.0; /* x */\n#define K 1\n"
    out = minify(src)
    assert "b=2." in out and "c=3." in out and "#define K 1" in out
    # un blocco su più righe non incolla una direttive alla riga precedente
    out2 = minify("float a = 1.0; /* uno\ndue */\n#define Q 2\nfloat q = 1.0;\n")
    assert "\n#define Q 2\n" in "\n" + out2


def test_treeshake_non_ridefinisce_le_funzioni_della_scena() -> None:
    lib = load_library(LIB)
    # la scena definisce hash21 e usa vnoise (che chiama hash21): niente copia della libreria,
    # ma il prototipo con la firma della scena, perché il common precede la scena
    entry = ("float hash21(vec2 p) { return fract(p.x * 0.1); }\n"
             "void mainImage(out vec4 c, in vec2 p){ c = vec4(vnoise(p)); }")
    out = treeshake(entry, lib)
    assert "float vnoise" in out
    assert "/// @fn hash21" not in out
    assert out.splitlines()[0] == "float hash21(vec2 p);"


def test_load_library_rifiuta_fn_duplicate(tmp_path: Path) -> None:
    (tmp_path / "a.glsl").write_text("/// @fn f\nfloat f(float x){ return x; }\n", encoding="utf-8")
    (tmp_path / "b.glsl").write_text("/// @fn f\nfloat f(float x){ return 2.0*x; }\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        load_library(tmp_path)


def test_conflitto_del_common_condiviso() -> None:
    from demogen.glsl.treeshake import shared_common_conflicts

    lib = load_library(LIB)
    scenes = {
        "s1": "float hash21(vec2 p) { return 0.5; }\nvoid mainImage(out vec4 c, in vec2 p){ c = vec4(hash21(p)); }",
        "s2": "void mainImage(out vec4 c, in vec2 p){ c = vec4(vnoise(p)); }",  # vnoise → hash21 di libreria
    }
    msgs = shared_common_conflicts(scenes, "", lib)
    assert msgs and "s2" in msgs[0] and "hash21" in msgs[0]
    assert shared_common_conflicts({"s2": scenes["s2"]}, "", lib) == []


def test_preprocess_include_once_cicli_e_path_confinati(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.glsl").write_text('#include "sub/b.glsl"\nfloat a(){ return 1.0; }\n', encoding="utf-8")
    # b include c relativo alla PROPRIA cartella
    (tmp_path / "sub" / "b.glsl").write_text('#include "c.glsl"\nfloat b(){ return 2.0; }\n', encoding="utf-8")
    (tmp_path / "sub" / "c.glsl").write_text("float c(){ return 3.0; }\n", encoding="utf-8")
    out, _ = preprocess('#include "a.glsl"\n#include "sub/c.glsl"\n', base_dir=tmp_path)
    assert out.count("float c()") == 1  # include-once
    assert "float a()" in out and "float b()" in out
    # ciclo con la catena completa
    (tmp_path / "x.glsl").write_text('#include "y.glsl"\n', encoding="utf-8")
    (tmp_path / "y.glsl").write_text('#include "x.glsl"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="cyclic.*x.glsl.*y.glsl.*x.glsl"):
        preprocess('#include "x.glsl"\n', base_dir=tmp_path)
    # path fuori dalle cartelle ammesse o assoluti
    (tmp_path.parent / "segreto.glsl").write_text("float s(){ return 0.0; }\n", encoding="utf-8")
    for bad in ('#include "../segreto.glsl"\n', f'#include "{(tmp_path / "a.glsl").as_posix()}"\n'):
        with pytest.raises(ValueError):
            preprocess(bad, base_dir=tmp_path)


def test_esempi_minificati_compilano(harness) -> None:
    import json

    from demogen.bundle.build import build_payload

    examples = Path(__file__).resolve().parents[1] / "examples"
    for spec in ("timeline.json", "audio_chip.timeline.json", "penguin.timeline.json", "whisker_hunt.timeline.json",
                 "edge_horizon.timeline.json"):
        payload = build_payload(json.loads((examples / spec).read_text(encoding="utf-8")), examples, do_minify=True)
        res = harness.load(payload)
        assert res["ok"], f"{spec}: " + "\n".join(res["errors"])[:1500]


def test_gnoise_continuo_agli_interi_e_hash_sotto_1(harness) -> None:
    import io

    from PIL import Image

    lib = load_library(LIB)
    scene = (
        "void mainImage(out vec4 c, in vec2 p){\n"
        "  float y = p.y * 0.173;\n"
        "  float d = 0.0;\n"
        "  for (int k = -3; k <= 3; k++) {\n"
        "    float x = float(k);\n"
        "    d = max(d, abs(gnoise(vec2(x - 1e-3, y)) - gnoise(vec2(x + 1e-3, y))));\n"
        "  }\n"
        "  float h = max(hash11(p.x * 7.77), hash21(p * 1.3));\n"
        "  c = vec4(d * 50.0, step(1.0, h), 0.0, 1.0);\n"
        "}\n"
    )
    payload = {
        "format": "demogen/1",
        "meta": {"title": "n", "duration_s": 1, "loop": False, "bpm": 120, "beats_per_bar": 4},
        "timeline": {"bpm": 120, "beats_per_bar": 4, "scenes": [
            {"id": "s1", "start_bar": 0, "bars": 1, "transition_in": "cut", "transition_bars": 0}]},
        "common": treeshake(scene, lib), "scenes": {"s1": scene}, "render": {"profile": "modern"},
    }
    res = harness.load(payload)
    assert res["ok"], res["errors"]
    import numpy as np

    img = np.asarray(Image.open(io.BytesIO(harness.capture([0.0], 128, 128)[0])).convert("RGB"))
    r_max, g_max = int(img[..., 0].max()), int(img[..., 1].max())
    assert r_max < 100, f"gnoise discontinuo agli interi (salto ×50 = {r_max}/255)"
    assert g_max == 0, "hash ha restituito 1.0"


def test_docs_api_reference() -> None:
    md = generate_api_reference(LIB)
    assert "hash11" in md and "raymarch" in md and "retroFinalize" in md
    assert "@fn" not in md.split("###")[1]  # i marker non restano nei titoli
