"""Spike M0: un frame e ms/frame fuori da rAF in modalità GPU e CPU (SwiftShader).

Usa l'API corrente dell'harness: load(payload) → capture/profile a dimensione esplicita.
"""

from __future__ import annotations

from pathlib import Path

from .harness import Harness

_SPIKE_SCENE = (
    "void mainImage(out vec4 fragColor, in vec2 fragCoord) {\n"
    "    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;\n"
    "    vec3 col = 0.5 + 0.5 * cos(iTime + uv.xyx + vec3(0.0, 2.0, 4.0));\n"
    "    fragColor = vec4(col, 1.0);\n"
    "}\n"
)

SPIKE_PAYLOAD = {
    "format": "demogen/1",
    "meta": {"title": "spike", "duration_s": 4, "loop": True, "bpm": 120, "beats_per_bar": 4},
    "timeline": {"bpm": 120, "beats_per_bar": 4, "scenes": [
        {"id": "s1", "start_bar": 0, "bars": 2, "transition_in": "cut", "transition_bars": 0}]},
    "common": "",
    "scenes": {"s1": _SPIKE_SCENE},
    "render": {"profile": "modern"},
}


def _run_mode(mode: str, out_dir: Path) -> dict:
    # hardware → full Chromium (channel="chromium") per avere la GPU reale anche in headless
    channel = "chromium" if mode == "hardware" else None
    with Harness(gpu=mode, headless=True, channel=channel) as h:  # type: ignore[arg-type]
        res = h.load(SPIKE_PAYLOAD)
        if not res["ok"]:
            raise RuntimeError("spike: lo shader non compila:\n" + "\n".join(res["errors"]))
        info = h.info()
        png = h.capture([1.0], 640, 360)[0]
        prof = h.profile([0.0, 0.5, 1.0, 2.0], 640, 360, repeats=3)
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = out_dir / f"spike_{mode}.png"
    rel.write_bytes(png)
    return {"mode": mode, "info": info, "profile": prof, "png": str(rel)}


def run_spike(out_dir: Path | None = None) -> list[dict]:
    """Cattura un frame e misura ms/frame fuori da rAF in modalità GPU e CPU."""
    out_dir = out_dir or Path("out")
    results = []
    for mode in ("hardware", "swiftshader"):
        try:
            results.append(_run_mode(mode, out_dir))
        except Exception as e:  # noqa: BLE001 - la GPU reale può mancare (CI, VM)
            print(f"[{mode}] non disponibile: {e}")
    for r in results:
        info = r["info"]
        ms = {t: round(v, 3) for t, v in r["profile"]["samples"].items()}
        print(f"[{r['mode']}] renderer={info['renderer']!r} webgl2={info['webgl2']} ({r['profile']['method']})")
        print(f"  ms/frame (mediana): {ms}  ->  {r['png']}")
    return results


def main() -> None:
    run_spike(Path("out"))


if __name__ == "__main__":
    main()
