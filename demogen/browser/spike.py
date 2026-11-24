from __future__ import annotations

import base64
from pathlib import Path

from .session import BrowserSession


def _run_mode(mode: str, out_dir: Path) -> dict:
    # hardware → full Chromium (channel="chromium") per avere la GPU reale anche in headless
    channel = "chromium" if mode == "hardware" else None
    with BrowserSession(gpu=mode, headless=True, channel=channel) as sess:  # type: ignore[arg-type]
        sess.goto("harness.html")
        info = sess.harness_info()
        png_b64 = sess.page.evaluate("window.__demogen.capture(1.0)")
        prof = sess.page.evaluate("window.__demogen.profile([0.0, 0.5, 1.0, 2.0], 3)")
        png = base64.b64decode(png_b64.split(",", 1)[1])
        out_dir.mkdir(parents=True, exist_ok=True)
        rel = out_dir / f"spike_{mode}.png"
        rel.write_bytes(png)
        return {"mode": mode, "info": info, "profile": prof, "png": str(rel)}


def run_spike(out_dir: Path | None = None) -> list[dict]:
    """Cattura un frame e misura ms/frame fuori da rAF in modalità GPU e CPU."""
    out_dir = out_dir or Path("out")
    results = [_run_mode("hardware", out_dir), _run_mode("swiftshader", out_dir)]
    for r in results:
        info = r["info"]
        ms = {t: round(v, 3) for t, v in r["profile"].items()}
        print(f"[{r['mode']}] renderer={info['renderer']!r} webgl2={info['webgl2']}")
        print(f"  ms/frame (mediana): {ms}  ->  {r['png']}")
    return results


def main() -> None:
    run_spike(Path("out"))


if __name__ == "__main__":
    main()
