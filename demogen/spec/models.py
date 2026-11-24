"""Modelli pydantic minimi (Fase 1): timeline e payload .demo."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RenderProfile = Literal["modern", "retro"]
Transition = Literal["cut", "crossfade", "flash", "fade_black"]


class SceneSlot(BaseModel):
    id: str
    start_bar: float
    bars: float
    transition_in: Transition = "cut"
    transition_bars: float = 0.0


class Timeline(BaseModel):
    bpm: float = Field(gt=0)
    beats_per_bar: int = 4
    scenes: list[SceneSlot]


class DemoMeta(BaseModel):
    title: str
    duration_s: float
    loop: bool = False
    bpm: float
    beats_per_bar: int = 4


class RenderSpec(BaseModel):
    profile: RenderProfile = "modern"
    overrides: dict[str, RenderProfile] = Field(default_factory=dict)
    retro: dict = Field(
        default_factory=lambda: {"internal_resolution": [320, 180], "upscale": "nearest"}
    )


class DemoPayloadSpec(BaseModel):
    """Schema del file .demo (validazione completa lato Python)."""

    format: Literal["demogen/1"] = "demogen/1"
    meta: DemoMeta
    timeline: Timeline
    common: str = ""
    scenes: dict[str, str]
    render: RenderSpec = Field(default_factory=RenderSpec)
    text: str | None = None
    post: dict = Field(default_factory=dict)
    quality: dict = Field(default_factory=lambda: {"min_scale": 0.5, "target_fps": 60})
