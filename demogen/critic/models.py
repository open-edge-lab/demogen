"""Modelli del critico e dei gate (piano v2 §9, §12)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Issue(BaseModel):
    # info: misura riportata ma non vincolante (es. perf su renderer software)
    severity: Literal["blocker", "major", "minor", "info"]
    source: Literal["gate", "critic", "user"] = "gate"
    at_s: float | None = None
    description: str
    suggested_fix: str = ""


class CriticReport(BaseModel):
    scores: dict[str, int] = Field(default_factory=dict)  # 1..10
    issues: list[Issue] = Field(default_factory=list)
    verdict: Literal["accept", "revise"] = "revise"
    summary: str = ""


class PerfProfile(BaseModel):
    scene_id: str = "demo"
    profile: str = "modern"
    resolution: tuple[int, int] = (0, 0)
    method: str = "fence"
    gpu: str = ""
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    floor_p95_ms: float | None = None
    gpu_load_est: float = 0.0  # mean_ms / (1000 / target_fps)
    hotspots: list[dict] = Field(default_factory=list)  # [{t, ms}]


class FlashReport(BaseModel):
    max_flashes_per_s: float = 0.0
    max_red_flashes_per_s: float = 0.0
    red_flash_events: int = 0  # flash rossi totali (coppie di transizioni)
    windows: list[tuple[float, float]] = Field(default_factory=list)
    area_cells: int = 0  # celle minime che devono transitare insieme (area WCAG)
    passed: bool = True
