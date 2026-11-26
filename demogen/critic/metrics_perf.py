"""Metriche di prestazioni da profili dell'harness (ms per tempo)."""

from __future__ import annotations

import numpy as np

from .models import PerfProfile


def perf_profile(
    samples: dict[float, float],
    *,
    scene_id: str = "demo",
    profile: str = "modern",
    resolution: tuple[int, int] = (0, 0),
    method: str = "fence",
    gpu: str = "",
    target_fps: int = 60,
    floor_samples: dict[float, float] | None = None,
    fixed_ms: float = 0.0,
) -> PerfProfile:
    """`fixed_ms`: costo fisso della misura (scena vuota, perf_ref.measure_baseline), tolto da ogni
    campione: scalato alla risoluzione del budget (×16 da 480×270, ×36 da 320×180) bocciava anche una
    scena vuota sulle GPU dove il giro di sincronizzazione costa qualche ms."""
    fixed_ms = max(float(fixed_ms), 0.0)
    ts = np.array(sorted(samples.keys()), dtype=float)
    ms = np.maximum(np.array([samples[float(t)] for t in ts], dtype=float) - fixed_ms, 0.0)
    hotspots = [
        {"t": float(t), "ms": float(m)}
        for t, m in sorted(zip(ts, ms), key=lambda x: -x[1])[:5]
    ]
    floor_p95 = None
    if floor_samples:
        floor_p95 = max(float(np.percentile(list(floor_samples.values()), 95)) - fixed_ms, 0.0)
    return PerfProfile(
        scene_id=scene_id,
        profile=profile,
        resolution=resolution,
        method=method,
        gpu=gpu,
        p50_ms=float(np.percentile(ms, 50)),
        p95_ms=float(np.percentile(ms, 95)),
        max_ms=float(ms.max()),
        mean_ms=float(ms.mean()),
        floor_p95_ms=floor_p95,
        fixed_ms=fixed_ms,
        gpu_load_est=float(ms.mean() / (1000.0 / target_fps)),
        hotspots=hotspots,
    )
