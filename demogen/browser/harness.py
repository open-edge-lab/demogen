"""API Python di alto livello verso window.__demogen (harness nel browser)."""

from __future__ import annotations

import base64
from typing import Any

from .session import BrowserSession, GPUMode

_LOAD_FRAGMENT_JS = """
(src) => {
  const header = '#version 300 es\\nprecision highp float;\\n'
    + 'uniform vec3 iResolution;\\nuniform float iTime;\\n'
    + 'void mainImage(out vec4 c, in vec2 p);\\nout vec4 o;\\n'
    + 'void main(){ mainImage(o, gl_FragCoord.xy); }\\n';
  const payload = {
    format: 'demogen/1',
    meta: { title: 'v', duration_s: 1, loop: false, bpm: 120, beats_per_bar: 4 },
    timeline: { bpm: 120, beats_per_bar: 4, scenes: [
      { id: 's1', start_bar: 0, bars: 1, transition_in: 'cut', transition_bars: 0 }] },
    common: '', scenes: { s1: src }, render: { profile: 'modern' },
  };
  return window.__demogen.load(payload);
}
"""


class Harness:
    """Pilota harness.html in Chromium: load/capture/profile/lumaSequence/info."""

    def __init__(
        self, gpu: GPUMode = "swiftshader", headless: bool = True, channel: str | None = None
    ) -> None:
        self.sess = BrowserSession(gpu=gpu, headless=headless, channel=channel)

    def __enter__(self) -> Harness:
        self.sess.__enter__()
        self.sess.goto("harness.html")
        assert self.sess.page is not None
        self.sess.page.wait_for_function("window.__demogen !== undefined", timeout=15000)
        return self

    def __exit__(self, *exc: object) -> None:
        self.sess.__exit__(*exc)

    @property
    def page(self):
        assert self.sess.page is not None
        return self.sess.page

    def info(self) -> dict[str, Any]:
        return self.page.evaluate("() => window.__demogen.info()")

    def load(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.page.evaluate("(p) => window.__demogen.load(p)", payload)

    def load_fragment(self, frag_src: str) -> dict[str, Any]:
        """Compila un singolo fragment (header+main+src) — per il validator."""
        return self.page.evaluate(_LOAD_FRAGMENT_JS, frag_src)

    def capture(self, times: list[float], width: int, height: int) -> list[bytes]:
        """PNG (bytes) per ogni tempo."""
        urls = self.page.evaluate(
            "(o) => window.__demogen.capture(o)",
            {"times": times, "width": width, "height": height},
        )
        return [base64.b64decode(u.split(",", 1)[1]) for u in urls]

    def profile(
        self, times: list[float], width: int, height: int, repeats: int = 3
    ) -> dict[str, Any]:
        return self.page.evaluate(
            "(o) => window.__demogen.profile(o)",
            {"times": times, "width": width, "height": height, "repeats": repeats},
        )

    def cell_sequence(
        self, t0: float, t1: float, fps: int, width: int, height: int
    ) -> list[list[list[float]]]:
        """Per ogni frame: 64 celle (8x8) × [r,g,b] medi — per l'analisi flash."""
        return self.page.evaluate(
            "(o) => window.__demogen.cellSequence(o)",
            {"t0": t0, "t1": t1, "fps": fps, "width": width, "height": height},
        )

    def scene_stats(
        self, times: list[float], width: int, height: int
    ) -> list[dict]:
        """Statistiche float (NaN/Inf/luma) per tempo, su FBO RGBA32F."""
        return self.page.evaluate(
            "(o) => window.__demogen.stats(o)",
            {"times": times, "width": width, "height": height},
        )
