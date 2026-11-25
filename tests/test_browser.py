"""Sessione browser: rete bloccata, pulizia sugli errori di avvio, player e link shader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from demogen.browser import session as sess_mod
from demogen.browser.session import BrowserSession, is_local_url
from tests.conftest import require_browser, skip_or_fail

ROOT = Path(__file__).resolve().parents[1]


def test_skip_or_fail_in_ci_fallisce(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception):
        skip_or_fail("browser mancante")
    monkeypatch.setenv("CI", "")
    with pytest.raises(pytest.skip.Exception):
        skip_or_fail("browser mancante")


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("http://127.0.0.1:5000/", True),
        ("http://127.0.0.1:5000/harness.html?x=1", True),
        ("http://127.0.0.1:5000", True),
        ("http://127.0.0.1:50001/x", False),  # stesso prefisso, porta diversa
        ("http://127.0.0.1:5000@evil.example/x", False),  # userinfo
        ("https://127.0.0.1:5000/x", False),
        ("http://localhost:5000/x", False),
        ("http://evil.example/x", False),
        ("data:text/plain,ciao", False),
        ("http://127.0.0.1:99999999/x", False),  # porta non valida
    ],
)
def test_is_local_url(url: str, ok: bool) -> None:
    assert is_local_url(url, 5000) is ok


class _Boom(RuntimeError):
    pass


def test_enter_fallito_chiude_playwright_e_server(monkeypatch) -> None:
    """Se launch() fallisce, __enter__ deve fermare playwright e il server prima di rilanciare."""
    stopped = {"pw": False, "server": False}

    class FakeChromium:
        def launch(self, **kw):
            raise _Boom("launch fallito")

    class FakePW:
        chromium = FakeChromium()

        def stop(self) -> None:
            stopped["pw"] = True

    class FakeStarter:
        def start(self):
            return FakePW()

    class FakeServer:
        def shutdown(self) -> None:
            stopped["server"] = True

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(sess_mod, "sync_playwright", lambda: FakeStarter())
    monkeypatch.setattr(sess_mod, "start_local_server", lambda d: (FakeServer(), 5000))
    s = BrowserSession(gpu="swiftshader")
    with pytest.raises(_Boom):
        s.__enter__()
    assert stopped == {"pw": True, "server": True}
    assert s._playwright is None and s._server is None


@pytest.mark.xfail(strict=True, reason="review #23 (batch F): index.html non espone window.__demogen")
def test_play_index_html_si_apre_senza_timeout() -> None:
    require_browser()
    from demogen.cli import _payload_from_file, open_player

    payload = _payload_from_file(ROOT / "examples" / "timeline.json", 120.0)
    with BrowserSession(gpu="swiftshader", headless=True, timeout_ms=20_000) as s:
        info = open_player(s, payload)
    assert info["webgl2"]
    assert not (ROOT / "player" / ".tmp-demo.json").exists()


@pytest.mark.xfail(strict=True, reason="review #21 (batch F): LINK_STATUS non controllato")
def test_link_fallito_riportato_ok_false(harness) -> None:
    # compila (vUv dichiarato in input) ma il link fallisce: il vertex shader non lo produce
    src = "in vec2 vUv;\nvoid mainImage(out vec4 c, in vec2 p){ c = vec4(vUv, 0.0, 1.0); }\n"
    res = harness.load_fragment(src)
    assert res["ok"] is False
    assert any("link" in e.lower() for e in res["errors"]), json.dumps(res["errors"])[:500]
