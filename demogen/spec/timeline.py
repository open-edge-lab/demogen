"""Semantica della timeline — DEVE restare identica a player/src/timeline.ts.

La parità è verificata dai vettori condivisi in shared/vectors/timeline_cases.json:
scripts/gen_vectors.py li genera con questa implementazione e il test vitest
li rilegge lato TypeScript. Le chiavi del dizionario sono le stesse del TS
(camelCase) per evitare mappature.
"""

from __future__ import annotations

from typing import Any, TypedDict


class SceneSlotDict(TypedDict):
    id: str
    start_bar: float
    bars: float
    transition_in: str
    transition_bars: float


class TimelineDict(TypedDict):
    bpm: float
    beats_per_bar: int
    scenes: list[SceneSlotDict]


class TimelineState(TypedDict):
    sceneId: str
    prevSceneId: str | None
    nextSceneId: str | None
    transition: str
    alpha: float
    beat: float
    bar: float
    sceneTime: float
    sceneProgress: float
    durationS: float


def state_at(tl: TimelineDict | Any, t: float) -> TimelineState:
    bpm = tl["bpm"] if isinstance(tl, dict) else tl.bpm
    bpb = tl["beats_per_bar"] if isinstance(tl, dict) else tl.beats_per_bar
    scenes_raw = tl["scenes"] if isinstance(tl, dict) else tl.scenes
    scenes: list[SceneSlotDict] = [
        s if isinstance(s, dict) else s.model_dump() for s in scenes_raw
    ]
    sec_per_beat = 60.0 / bpm
    beat = t / sec_per_beat
    bar = beat / bpb
    last = scenes[-1]
    duration_s = (last["start_bar"] + last["bars"]) * bpb * sec_per_beat

    idx = 0
    for i, s in enumerate(scenes):
        if bar >= s["start_bar"]:
            idx = i
    cur = scenes[idx]

    transition = "cut"
    alpha = 1.0
    prev_scene_id: str | None = None
    next_scene_id: str | None = None
    if idx + 1 < len(scenes):
        nxt = scenes[idx + 1]
        t0 = nxt["start_bar"] - nxt["transition_bars"]
        in_window = t0 <= bar < nxt["start_bar"]
        if nxt["transition_in"] != "cut" and nxt["transition_bars"] > 0 and in_window:
            transition = nxt["transition_in"]
            alpha = (bar - t0) / nxt["transition_bars"]
            prev_scene_id = cur["id"]
            next_scene_id = nxt["id"]

    scene_start_s = cur["start_bar"] * bpb * sec_per_beat
    scene_dur_s = cur["bars"] * bpb * sec_per_beat
    return {
        "sceneId": cur["id"],
        "prevSceneId": prev_scene_id,
        "nextSceneId": next_scene_id,
        "transition": transition,
        "alpha": min(1.0, max(0.0, alpha)),
        "beat": beat,
        "bar": bar,
        "sceneTime": t - scene_start_s,
        "sceneProgress": (
            min(1.0, max(0.0, (t - scene_start_s) / scene_dur_s)) if scene_dur_s > 0 else 0.0
        ),
        "durationS": duration_s,
    }
