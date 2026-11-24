from __future__ import annotations

from pathlib import Path
from typing import Literal

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


class BrowserSession:
    """Sessione Playwright: server locale su 127.0.0.1, rete esterna bloccata via page.route."""

    def __init__(
        self, gpu: GPUMode = "auto", headless: bool = True, channel: str | None = None
    ) -> None:
        self.gpu = gpu
        self.headless = headless
        # channel="chromium" fuerza il full Chromium (anche in headless) invece della
        # headless shell: solo così in headless si può usare la GPU reale.
        self.channel = channel
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._server = None
        self.base_url = ""

    def __enter__(self) -> BrowserSession:
        flags = SWIFTSHADER_FLAGS if self.gpu == "swiftshader" else HARDWARE_FLAGS
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless, args=flags, channel=self.channel
        )
        self.page = self.browser.new_page()
        self.page.on(
            "console", lambda msg: print(f"[console:{msg.type}] {msg.text}")
        )
        self.page.on("pageerror", lambda err: print(f"[pageerror] {err}"))
        self._server, port = start_local_server(PLAYER_DIR)
        self.base_url = f"http://127.0.0.1:{port}"

        def _block_external(route, request) -> None:
            if request.url.startswith(self.base_url):
                route.continue_()
            else:
                route.abort()

        self.page.route("**/*", _block_external)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.browser is not None:
            self.browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        if self._server is not None:
            self._server.shutdown()

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
