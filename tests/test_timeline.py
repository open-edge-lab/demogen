"""Parità Python ↔ vettori condivisi (il lato TS è testato da vitest)."""

from __future__ import annotations

import json
from pathlib import Path

from demogen.spec.timeline import state_at

VECTORS = Path(__file__).resolve().parents[1] / "shared" / "vectors" / "timeline_cases.json"


def test_vettori_aggiornati_e_coerenti() -> None:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert data, "vettori vuoti: esegui scripts/gen_vectors.py"
    for entry in data:
        tl = entry["timeline"]
        for case in entry["cases"]:
            got = state_at(tl, case["t"])
            for k, v in case["expect"].items():
                if isinstance(v, float):
                    assert abs(got[k] - v) < 1e-9, (case["t"], k, got[k], v)
                else:
                    assert got[k] == v, (case["t"], k, got[k], v)


def test_transizione_crossfade() -> None:
    tl = {
        "bpm": 120.0,
        "beats_per_bar": 4,
        "scenes": [
            {"id": "s1", "start_bar": 0, "bars": 4, "transition_in": "cut", "transition_bars": 0},
            {"id": "s2", "start_bar": 4, "bars": 4,
             "transition_in": "crossfade", "transition_bars": 1},
        ],
    }
    # a metà transizione (bar = 3.5 → t = 3.5*4*0.5 = 7s) alpha = 0.5
    st = state_at(tl, 7.0)
    assert st["transition"] == "crossfade"
    assert st["prevSceneId"] == "s1"
    assert st["nextSceneId"] == "s2"
    assert abs(st["alpha"] - 0.5) < 1e-9
    # fuori dalla finestra: cut
    st2 = state_at(tl, 5.0)
    assert st2["transition"] == "cut"
    assert st2["sceneId"] == "s1"
