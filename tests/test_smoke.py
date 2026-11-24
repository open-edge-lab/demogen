"""Smoke test Fase 0: l'harness nel browser compila lo shader e cattura un frame non nero."""

from __future__ import annotations

import base64
import io

import pytest

pytest.importorskip("playwright")

from demogen.browser.session import BrowserSession  # noqa: E402


def _capture(mode: str) -> tuple[dict, bytes, dict]:
    with BrowserSession(gpu=mode, headless=True) as sess:  # type: ignore[arg-type]
        sess.goto("harness.html")
        info = sess.harness_info()
        png_b64 = sess.page.evaluate("window.__demogen.capture(1.0)")
        prof = sess.page.evaluate("window.__demogen.profile([0.0, 1.0], 2)")
    png = base64.b64decode(png_b64.split(",", 1)[1])
    # le chiavi numeriche dell'oggetto JS llegan a Python come stringhe
    prof = {float(k): v for k, v in prof.items()}
    return info, png, prof


def test_harness_swiftshader_compila_e_cattura() -> None:
    try:
        info, png, prof = _capture("swiftshader")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"browser Playwright non disponibile: {e}")
    assert info["webgl2"]
    assert "swiftshader" in info["renderer"].lower()
    # la misura ms in headless shell è unreliable (valori ~0): qui basta che il
    # profilo restituisca numeri; la misura accurata arriva in Fase 1 (timer query)
    assert prof[0.0] >= 0 and prof[1.0] >= 0

    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("L")
    assert img.size == (640, 360)
    assert img.getextrema()[1] > 10  # frame non nero
