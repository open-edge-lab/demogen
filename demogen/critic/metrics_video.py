"""Metriche video da frame (numpy HxWx3 uint8) e statistiche float dell'harness."""

from __future__ import annotations

import numpy as np


def _luma(img: np.ndarray) -> np.ndarray:
    """Luma Rec.709 in [0,1] da un frame uint8 RGB."""
    f = img.astype(np.float64) / 255.0
    return 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]


def colorfulness(img: np.ndarray) -> float:
    """Metrica di Hasler–Süsstrunk."""
    f = img.astype(np.float64) / 255.0
    rg = f[..., 0] - f[..., 1]
    yb = 0.5 * (f[..., 0] + f[..., 1]) - f[..., 2]
    std_rg, std_yb = float(rg.std()), float(yb.std())
    mean_rg, mean_yb = float(rg.mean()), float(yb.mean())
    return float(np.sqrt(std_rg**2 + std_yb**2) + 0.3 * np.sqrt(mean_rg**2 + mean_yb**2))


def histogram_entropy(luma: np.ndarray, bins: int = 256) -> float:
    hist, _ = np.histogram(luma, bins=bins, range=(0.0, 1.0))
    p = hist / max(1, hist.sum())
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def video_metrics(
    frames: list[np.ndarray],
    float_stats: list[dict] | None = None,
    loop: bool = False,
) -> dict:
    """Metriche §12.1: NaN/Inf (da float), nero/bianco, luma, entropia, colorfulness,
    temporali (diff tra frame consecutivi, picchi z>4), loop_seam."""
    if not frames:
        raise ValueError("nessun frame")
    stack = np.stack([_luma(f) for f in frames])  # (N,H,W) in [0,1]
    luma_mean = float(stack.mean())
    luma_std = float(stack.std())
    black_ratio = float((stack < 0.02).mean())
    white_ratio = float((stack > 0.98).mean())
    ent = float(np.mean([histogram_entropy(stack[i]) for i in range(stack.shape[0])]))
    col = float(np.mean([colorfulness(f) for f in frames]))

    nan_ratio = inf_ratio = 0.0
    if float_stats:
        nan_ratio = float(np.mean([s.get("nan_ratio", 0.0) for s in float_stats]))
        inf_ratio = float(np.mean([s.get("inf_ratio", 0.0) for s in float_stats]))

    diffs = np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2)) if stack.shape[0] > 1 else np.array([0.0])
    z = (diffs - diffs.mean()) / (diffs.std() + 1e-12)
    flicker_peaks = int((z > 4).sum())

    loop_seam = None
    if loop and stack.shape[0] > 1:
        loop_seam = float(np.abs(stack[0] - stack[-1]).mean())

    return {
        "frames": int(stack.shape[0]),
        "nan_ratio": nan_ratio,
        "inf_ratio": inf_ratio,
        "black_ratio": black_ratio,
        "white_ratio": white_ratio,
        "luma_mean": luma_mean,
        "luma_std": luma_std,
        "histogram_entropy": ent,
        "colorfulness": col,
        "temporal_diff_mean": float(diffs.mean()),
        "flicker_peaks": flicker_peaks,
        "loop_seam": loop_seam,
    }
