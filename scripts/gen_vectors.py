"""Genera shared/vectors/timeline_cases.json con la semantica Python di référence.

Il test vitest (player/test/timeline.test.ts) rilegge gli stessi casi e verifica
che il TypeScript produca gli stessi valori: parità tra i due mondi.
"""

from __future__ import annotations

import json
from pathlib import Path

from demogen.spec.timeline import state_at

OUT = Path(__file__).resolve().parents[1] / "shared" / "vectors" / "timeline_cases.json"

TIMELINES = [
    {
        "bpm": 128.0,
        "beats_per_bar": 4,
        "scenes": [
            {"id": "s1", "start_bar": 0, "bars": 8, "transition_in": "cut", "transition_bars": 0},
            {"id": "s2", "start_bar": 8, "bars": 8,
             "transition_in": "crossfade", "transition_bars": 1},
            {"id": "s3", "start_bar": 16, "bars": 8,
             "transition_in": "flash", "transition_bars": 2},
        ],
    },
    {
        "bpm": 90.0,
        "beats_per_bar": 4,
        "scenes": [
            {"id": "a", "start_bar": 0, "bars": 4, "transition_in": "cut", "transition_bars": 0},
            {"id": "b", "start_bar": 4, "bars": 4,
             "transition_in": "fade_black", "transition_bars": 1},
        ],
    },
]


def main() -> None:
    out = []
    for tl in TIMELINES:
        last = tl["scenes"][-1]
        duration = (last["start_bar"] + last["bars"]) * tl["beats_per_bar"] * 60 / tl["bpm"]
        ts = [round(duration * f, 4) for f in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)]
        # aggiungi tempi precisi dentro le finestre di transizione
        for s in tl["scenes"][1:]:
            if s["transition_bars"] > 0:
                t0bar = s["start_bar"] - s["transition_bars"]
                for frac in (0.0, 0.5, 0.999):
                    bar = t0bar + frac * s["transition_bars"]
                    ts.append(bar * tl["beats_per_bar"] * 60 / tl["bpm"])
        cases = [{"t": t, "expect": state_at(tl, t)} for t in sorted(set(ts))]
        out.append({"timeline": tl, "cases": cases})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"scritti {sum(len(o['cases']) for o in out)} casi in {OUT}")


if __name__ == "__main__":
    main()
