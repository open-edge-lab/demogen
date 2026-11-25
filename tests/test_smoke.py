"""Smoke test: l'harness nel browser carica un payload, compila e cattura un frame non nero."""

from __future__ import annotations

import io

PAYLOAD = {
    "format": "demogen/1",
    "meta": {"title": "smoke", "duration_s": 4, "loop": True, "bpm": 120, "beats_per_bar": 4},
    "timeline": {
        "bpm": 120,
        "beats_per_bar": 4,
        "scenes": [
            {"id": "s1", "start_bar": 0, "bars": 4, "transition_in": "cut", "transition_bars": 0}
        ],
    },
    "common": "",
    "scenes": {
        "s1": (
            "void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n"
            "    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;\n"
            "    vec3 col = 0.5 + 0.5 * cos(iTime + uv.xyx + vec3(0.0, 0.33, 0.67));\n"
            "    fragColor = vec4(col, 1.0);\n"
            "}\n"
        )
    },
    "render": {"profile": "modern"},
    "quality": {"target_fps": 60, "min_scale": 0.5},
}


def test_harness_swiftshader_load_capture_profile(harness) -> None:
    res = harness.load(PAYLOAD)
    assert res["ok"], res["errors"]
    info = harness.info()
    assert info["webgl2"]
    assert "swiftshader" in info["renderer"].lower()
    pngs = harness.capture([1.0], 320, 180)
    prof = harness.profile([0.0, 1.0], 320, 180, repeats=2)

    from PIL import Image

    img = Image.open(io.BytesIO(pngs[0])).convert("L")
    assert img.size == (320, 180)
    assert img.getextrema()[1] > 10  # frame non nero
    assert {float(k) for k in prof["samples"]} == {0.0, 1.0}
    assert all(v >= 0 for v in prof["samples"].values())
