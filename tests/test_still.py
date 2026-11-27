"""Immagini fisse (demogen/still.py + player/src/still.ts): tile, orientamento, supersampling."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from demogen.engine import payload_from_file
from demogen.still import render_still, validate_still_args

# bordi netti senza AA (diagonali) + gradiente: R cresce verso destra, G verso l'alto
SHADER = """
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float d = step(0.5, fract(uv.x * 7.0 + uv.y * 3.0));
    fragColor = vec4(uv.x, uv.y, d, 1.0);
}
"""
W, H, T = 96, 64, 1.0


@pytest.fixture
def payload(tmp_path) -> dict:
    # due livelli sotto tmp_path: payload_from_file cerca common.glsl anche nella cartella sopra lo
    # shader, e nella base temporanea di pytest altri test ne lasciano uno
    src = tmp_path / "still" / "src" / "edges.glsl"
    src.parent.mkdir(parents=True)
    src.write_text(SHADER, encoding="utf-8")
    return payload_from_file(src)


def test_spp1_tiled_matches_realtime_frame(harness, payload) -> None:
    """Un campione al centro del pixel, a tile non divisibili, è il frame realtime della stessa dimensione."""
    res = render_still(harness, payload, t=T, width=W, height=H, spp=1, tile=40)
    assert len(res.tiles) == 6  # 3×2 tile, gli ultimi parziali
    frame = np.asarray(Image.open(io.BytesIO(harness.capture([T], W, H)[0])).convert("RGB"), dtype=int)
    assert np.abs(res.image.astype(int) - frame).max() <= 1
    # orientamento: verde (uv.y) in alto, rosso (uv.x) a destra
    assert res.image[0, :, 1].mean() > res.image[-1, :, 1].mean() + 100
    assert res.image[:, -1, 0].mean() > res.image[:, 0, 0].mean() + 100


def test_tile_size_does_not_change_the_image(harness, payload) -> None:
    small = render_still(harness, payload, t=T, width=W, height=H, spp=8, tile=40)
    whole = render_still(harness, payload, t=T, width=W, height=H, spp=8, tile=128)
    assert len(whole.tiles) == 1
    assert np.abs(small.image.astype(int) - whole.image.astype(int)).max() <= 1


def test_supersampling_smooths_hard_edges(harness, payload) -> None:
    one = render_still(harness, payload, t=T, width=W, height=H, spp=1, tile=128).image[..., 2].astype(int)
    many = render_still(harness, payload, t=T, width=W, height=H, spp=16, tile=128).image[..., 2].astype(int)
    mid = lambda b: int(((b > 8) & (b < 247)).sum())  # noqa: E731
    assert mid(one) == 0  # senza AA ogni pixel è 0 o 255
    assert mid(many) > 50  # i pixel di bordo diventano coperture intermedie
    assert abs(one.mean() - many.mean()) < 6  # stessa copertura media


def test_retro_scene_is_refused(harness, payload) -> None:
    retro = {**payload, "render": {"profile": "retro"}}
    with pytest.raises(Exception, match="retro"):
        render_still(harness, retro, t=T, width=W, height=H, spp=1, tile=128)


@pytest.mark.parametrize("args", [
    (0, 64, 1, 128, 1.0),
    (40000, 64, 1, 128, 1.0),
    (20000, 20000, 1, 128, 1.0),
    (64, 64, 0, 128, 1.0),
    (64, 64, 1, 8, 1.0),
    (64, 64, 1, 128, 5.0),
])
def test_invalid_arguments(args) -> None:
    with pytest.raises(ValueError):
        validate_still_args(*args)


def test_bloom_glows_and_scales_with_resolution() -> None:
    """Il bloom dello still: alone attorno alle zone chiare, raggio proporzionale all'altezza."""
    from demogen.still import apply_bloom

    def spread(h: int) -> float:
        img = np.zeros((h, h * 16 // 9, 3), dtype=np.uint8)
        c = h // 2
        img[c - h // 20:c + h // 20, c - h // 20:c + h // 20] = 255  # quadrato bianco al centro
        out = apply_bloom(img, threshold=0.8, intensity=0.5)
        row = out[c, :, 1].astype(int)
        lit = np.nonzero(row > 4)[0]
        return (lit.max() - lit.min()) / h  # larghezza illuminata relativa all'altezza

    s1, s2 = spread(540), spread(1080)
    assert s1 > 0.1 + 0.01  # più largo del solo quadrato (0.1 dell'altezza): alone di ~0.009 per lato
    assert abs(s2 - s1) < 0.01  # stesso alone relativo a risoluzione doppia
    dark = np.full((90, 160, 3), 100, dtype=np.uint8)
    assert np.array_equal(apply_bloom(dark, 0.8, 0.5), dark)  # sotto soglia non cambia niente


def test_still_gates_on_the_final_image(harness, tmp_path) -> None:
    black = tmp_path / "gates" / "src" / "black.glsl"
    black.parent.mkdir(parents=True)
    black.write_text("void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n"
                     "    fragColor = vec4(0.0, 0.0, 0.0, 1.0);\n}\n", encoding="utf-8")
    res = render_still(harness, payload_from_file(black), t=T, width=W, height=H, spp=1, tile=128)
    assert res.blockers == 1 and "black" in res.issues[0].description
    assert res.summary()["issues"][0]["severity"] == "blocker"
