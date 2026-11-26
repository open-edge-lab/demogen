from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from .serve import start_local_server

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER_DIR = REPO_ROOT / "player"

GPUMode = Literal["auto", "hardware", "swiftshader"]

# SwiftShader = rendering CPU dentro Chromium (fallback quando la GPU non c'è).
SWIFTSHADER_FLAGS = [
    "--use-gl=angle",
    "--use-angle=swiftshader-webgl",
    "--enable-unsafe-swiftshader",
]
# GPU reale: default di Chromium (ANGLE sceglie il backend nativo:
# Metal su macOS, D3D su Windows, Vulkan su Linux). Non forzare --use-gl=angle:
# in headless senza backend valido il contesto WebGL2 non si crea.
HARDWARE_FLAGS: list[str] = []


def is_local_url(url: str, port: int) -> bool:
    """True solo per http://127.0.0.1:<port>/… (niente userinfo, porta esatta).

    Un semplice startswith(base_url) farebbe passare :50001 con base :5000, o
    http://127.0.0.1:5000@evil.example/.
    """
    try:
        u = urlsplit(url)
        return (
            u.scheme == "http"
            and u.hostname == "127.0.0.1"
            and u.port == port
            and u.username is None
            and u.password is None
        )
    except ValueError:
        return False


def is_console_noise(text: str) -> bool:
    """Avvisi di prestazione del driver GL di Chromium ("GPU stall due to ReadPixels"): li provoca la
    cattura dei frame dell'harness, sono attesi e riempivano il log di ogni generazione."""
    return "GL Driver Message" in text and "Performance" in text


def _print_console(msg) -> None:
    if not is_console_noise(msg.text):
        print(f"[console:{msg.type}] {msg.text}")


class BrowserSession:
    """Sessione Playwright: server locale su 127.0.0.1, rete esterna bloccata via page.route."""

    def __init__(
        self,
        gpu: GPUMode = "auto",
        headless: bool = True,
        channel: str | None = None,
        timeout_ms: float = 30_000,
    ) -> None:
        self.gpu = gpu
        self.headless = headless
        self.timeout_ms = timeout_ms
        # channel="chromium" fuerza il full Chromium (anche in headless) invece della
        # headless shell: solo così in headless si può usare la GPU reale.
        self.channel = channel
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._server = None
        self.base_url = ""

    def __enter__(self) -> BrowserSession:
        try:
            self._start()
        except BaseException:
            # __exit__ non viene chiamato se __enter__ solleva: chiudi qui ciò che è partito
            self.__exit__(None, None, None)
            raise
        return self

    def _start(self) -> None:
        flags = SWIFTSHADER_FLAGS if self.gpu == "swiftshader" else HARDWARE_FLAGS
        self._server, port = start_local_server(PLAYER_DIR)
        self.base_url = f"http://127.0.0.1:{port}"
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless, args=flags, channel=self.channel
        )
        self.page = self.browser.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.set_default_navigation_timeout(self.timeout_ms)
        self.page.on("console", _print_console)
        self.page.on("pageerror", lambda err: print(f"[pageerror] {err}"))

        def _block_external(route, request) -> None:
            if is_local_url(request.url, port):
                route.continue_()
            else:
                route.abort()

        self.page.route("**/*", _block_external)

    def __exit__(self, *exc: object) -> None:
        # ogni risorsa chiusa a sé: un errore su una non deve lasciare aperte le altre
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001
                pass
            self.browser = None
            self.page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    def goto(self, path: str) -> None:
        assert self.page is not None
        self.page.goto(f"{self.base_url}/{path}")

    def harness_info(self) -> dict:
        """Attende window.__demogen e ne legge info() (renderer, estensioni, limiti)."""
        assert self.page is not None
        self.page.wait_for_function(
            "window.__demogen !== undefined || window.__demogen_error !== undefined",
            timeout=15000,
        )
        err = self.page.evaluate("window.__demogen_error || null")
        if err:
            raise RuntimeError(f"harness error: {err}")
        return self.page.evaluate("window.__demogen.info()")
