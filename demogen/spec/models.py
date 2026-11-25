"""Modelli pydantic completi (piano v2 §9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RenderProfile = Literal["modern", "retro"]
PerfTier = Literal["light", "medium", "heavy"]
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


class SceneBrief(BaseModel):
    id: str
    title: str
    description: str  # cosa si vede
    motion: str  # come si muove, legame col beat
    techniques: list[str] = Field(default_factory=list)
    camera: str = ""
    profile: RenderProfile | None = None  # override del profilo della demo
    perf_tier: PerfTier = "medium"


class DemoSpec(BaseModel):
    title: str
    prompt: str
    duration_s: float
    loop: bool = False
    profile: RenderProfile = "modern"
    timeline: Timeline
    scenes: list[SceneBrief]
    art_direction: str = ""
    palette_hint: list[str] = Field(default_factory=list)
    audio_brief: str = ""
    text: str | None = None  # scroller retro, max 256 caratteri ASCII
    avoid: list[str] = Field(default_factory=list)


class MathRequest(BaseModel):
    id: str
    kind: Literal[
        "sdf", "lipschitz", "intersection", "periodic_path", "easing",
        "parametric_curve", "attractor_params", "fourier", "identity", "other",
    ]
    description: str
    inputs: dict[str, str] = Field(default_factory=dict)
    output_signature: str = ""
    # Fase 6 (oracolo): espressione python-safe verificabile + parametri del claim
    expr: str = ""
    claim: dict = Field(default_factory=dict)


class ShaderSubmission(BaseModel):
    """Metadati dell'envelope; il GLSL viaggia a parte nei blocchi ```glsl."""

    scene_id: str
    notes: str = ""
    math_requests: list[MathRequest] = Field(default_factory=list)
    perf_tier: PerfTier = "medium"
    quality_knobs: list[str] = Field(default_factory=list)


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
    audio: str = ""  # Fase 2: sorgente GLSL con mainAudio(out vec4, in float t)
