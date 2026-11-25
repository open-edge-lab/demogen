"""Modelli pydantic completi (piano v2 §9)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

RenderProfile = Literal["modern", "retro"]
PerfTier = Literal["light", "medium", "heavy"]
Transition = Literal["cut", "crossfade", "flash", "fade_black"]

# gli id delle scene diventano path (scenes/<id>/...): niente separatori, `..` o `:`
SCENE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
SceneId = Annotated[str, Field(pattern=SCENE_ID_PATTERN)]
MAX_TEXT_BYTES = 256  # uText[64] × 4 byte: il player legge byte UTF-8, non caratteri


def _check_text(v: str | None) -> str | None:
    if v is not None and len(v.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"text: massimo {MAX_TEXT_BYTES} byte UTF-8 (ne ha {len(v.encode('utf-8'))})")
    return v


class SceneSlot(BaseModel):
    id: SceneId
    start_bar: float
    bars: float
    transition_in: Transition = "cut"
    transition_bars: float = 0.0


class Timeline(BaseModel):
    bpm: float = Field(gt=0)
    beats_per_bar: int = 4
    scenes: list[SceneSlot]


class SceneBrief(BaseModel):
    id: SceneId
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

    @field_validator("text")
    @classmethod
    def _text_bytes(cls, v: str | None) -> str | None:
        return _check_text(v)

    @model_validator(mode="after")
    def _check_slots(self) -> DemoSpec:
        """Scene e slot di timeline si abbinano per id: stessi id, unici, durate sensate.

        L'errore torna all'LLM nel repair loop di chat_structured."""
        slot_ids = [s.id for s in self.timeline.scenes]
        scene_ids = [s.id for s in self.scenes]
        if not slot_ids:
            raise ValueError("timeline.scenes vuota")
        if len(set(slot_ids)) != len(slot_ids) or len(set(scene_ids)) != len(scene_ids):
            raise ValueError(f"id di scena duplicati: timeline={slot_ids} scenes={scene_ids}")
        if set(slot_ids) != set(scene_ids):
            raise ValueError(
                f"timeline.scenes e scenes devono avere gli stessi id: {sorted(slot_ids)} vs {sorted(scene_ids)}"
            )
        for s in self.timeline.scenes:
            if s.bars <= 0 or s.start_bar < 0:
                raise ValueError(f"slot {s.id}: bars deve essere > 0 e start_bar >= 0")
            if not 0 <= s.transition_bars <= s.bars:
                raise ValueError(f"slot {s.id}: transition_bars deve stare in [0, bars]")
        return self


class MathRequest(BaseModel):
    id: str
    kind: Literal[
        "sdf", "lipschitz", "intersection", "periodic_path", "easing",
        "parametric_curve", "attractor_params", "fourier", "identity", "other",
    ]
    # facoltativa: l'esempio del prompt non la mette e i modelli la omettono spesso
    # (nel run live 3 draft su 4 venivano rifiutati solo per questo)
    description: str = ""
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

    @field_validator("text")
    @classmethod
    def _text_bytes(cls, v: str | None) -> str | None:
        return _check_text(v)
