"""Gate di perf relativo: il costo di una scena in multipli della scena di riferimento.

I ms assoluti dipendono dal renderer (SwiftShader è decine di volte più lento di una GPU) e
dalla macchina; il rapporto con una scena nota, misurata nello stesso browser e alla stessa
risoluzione, molto meno. Misure del 2026-11-26 (riferimento = 1×):

    scena                          SwiftShader 480×270   Intel UHD 620 1920×1080
    esempi tunnel / ifs / penguin       0,7–1,0×              0,5–0,9×
    esempio terrain                       16×                    14×
    run reale "nuvole volumetriche"     27–29×                 21–24×

Così il gate funziona anche nel run di default su SwiftShader, dove i ms erano solo
informativi e scene da 2 fps passavano senza che nessuno chiedesse di alleggerirle.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from ..browser.perf_lane import perf_lane
from ..glsl.treeshake import treeshake

REFERENCE_SRC = Path(__file__).with_name("reference_scene.glsl")
REF_TIMES = (1.0, 3.0, 5.0, 7.0)


def reference_payload(lib: dict) -> dict:
    """Payload mono-scena (8 s, profilo modern) della scena di riferimento."""
    src = REFERENCE_SRC.read_text(encoding="utf-8")
    return {
        "format": "demogen/1",
        "meta": {"title": "perf reference", "duration_s": 8.0, "loop": False, "bpm": 120, "beats_per_bar": 4},
        "timeline": {"bpm": 120, "beats_per_bar": 4, "scenes": [
            {"id": "ref", "start_bar": 0, "bars": 4, "transition_in": "cut", "transition_bars": 0}]},
        "common": treeshake(src, lib),
        "scenes": {"ref": src},
        "render": {"profile": "modern"},
        "post": {},
        "quality": {"min_scale": 0.25, "target_fps": 60},
    }


def measure_reference(harness, width: int, height: int, lib: dict, repeats: int = 3) -> float:
    """ms della scena di riferimento (mediana sui tempi) in questo browser a width×height.

    Sostituisce il payload caricato nell'harness: chiamarla quando la scena non serve più."""
    res = harness.load(reference_payload(lib))
    if not res["ok"]:
        raise RuntimeError("the reference scene does not compile: " + "\n".join(res["errors"])[:500])
    with perf_lane():
        prof = harness.profile(list(REF_TIMES), width, height, repeats=repeats)
    return float(statistics.median(float(v) for v in prof["samples"].values()))


def add_ratios(perf: dict, ref_ms: float | None) -> dict:
    """Aggiunge a `perf` il costo del riferimento e i rapporti p95/mean (per gate, report e pannello).

    Il riferimento è misurato lordo (con il costo fisso della misura): il rapporto è lordo su lordo,
    quindi ai ms della scena, già netti, si riaggiunge `fixed_ms` (soglie tarate così)."""
    if ref_ms and ref_ms > 0:
        fixed = float(perf.get("fixed_ms") or 0.0)
        perf["ref_ms"] = round(ref_ms, 3)
        perf["ref_ratio_p95"] = round((float(perf.get("p95_ms") or 0.0) + fixed) / ref_ms, 2)
        perf["ref_ratio_mean"] = round((float(perf.get("mean_ms") or 0.0) + fixed) / ref_ms, 2)
    return perf


BASELINE_SRC = "void mainImage(out vec4 c, in vec2 p) { c = vec4(0.0, 0.0, 0.0, 1.0); }\n"
BASELINE_TIMES = (0.5, 1.0, 1.5, 2.0)


def baseline_payload(payload: dict) -> dict:
    """Una scena che non fa niente con la stessa resa del payload (profilo, risoluzione interna
    retro): misura il costo fisso di un fotogramma. Senza bloom, che è un costo vero della demo."""
    render = {k: v for k, v in (payload.get("render") or {"profile": "modern"}).items() if k != "overrides"}
    return {
        "format": "demogen/1",
        "meta": {"title": "perf baseline", "duration_s": 4.0, "loop": False, "bpm": 120, "beats_per_bar": 4},
        "timeline": {"bpm": 120, "beats_per_bar": 4, "scenes": [
            {"id": "base", "start_bar": 0, "bars": 2, "transition_in": "cut", "transition_bars": 0}]},
        "common": "",
        "scenes": {"base": BASELINE_SRC},
        "render": render,
        "post": {},
        "quality": payload.get("quality", {"min_scale": 0.25, "target_fps": 60}),
    }


def measure_baseline(harness, width: int, height: int, payload: dict, repeats: int = 5) -> float:
    """ms della scena vuota (mediana) in questo browser a width×height, con la resa di `payload`.

    Sostituisce il payload caricato nell'harness: chiamarla quando la scena non serve più."""
    res = harness.load(baseline_payload(payload))
    if not res["ok"]:
        raise RuntimeError("the baseline scene does not compile: " + "\n".join(res["errors"])[:500])
    with perf_lane():
        prof = harness.profile(list(BASELINE_TIMES), width, height, repeats=repeats)
    return float(statistics.median(float(v) for v in prof["samples"].values()))
