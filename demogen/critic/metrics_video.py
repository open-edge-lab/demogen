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


def flicker_score(bursts: list[list[np.ndarray]]) -> tuple[float, float]:
    """Oscillazione temporale su frame REALMENTE consecutivi (burst a fps di preview).

    Per pixel e per tripletta di frame consecutivi: se le due differenze hanno segno
    opposto (su-giù o giù-su a frame rate) conta min(|d1|, |d2|), altrimenti 0. Il moto
    regolare (differenze concordi) dà ~0; aliasing temporale, rumore instabile o strobo
    a frame rate danno valori alti. Ritorna (score massimo sui burst, diff media tra
    frame consecutivi), entrambi in unità di luma [0,1].
    """
    scores, diffs = [], []
    for burst in bursts:
        if len(burst) < 3:
            continue
        L = np.stack([_luma(f) for f in burst])  # (T,H,W)
        d = np.diff(L, axis=0)
        diffs.append(float(np.abs(d).mean()))
        d1, d2 = d[:-1], d[1:]
        osc = np.where(d1 * d2 < 0, np.minimum(np.abs(d1), np.abs(d2)), 0.0)
        scores.append(float(osc.mean()))
    return (max(scores) if scores else 0.0), (float(np.mean(diffs)) if diffs else 0.0)


def video_metrics(
    frames: list[np.ndarray],
    float_stats: list[dict] | None = None,
    loop: bool = False,
    bursts: list[list[np.ndarray]] | None = None,
    seam: tuple[np.ndarray, np.ndarray] | None = None,
) -> dict:
    """Metriche §12.1: NaN/Inf (da float), nero/bianco, luma, entropia, colorfulness,
    temporali e loop_seam.

    - `bursts`: frame consecutivi a fps di preview → flicker_score (i keyframe sono
      troppo distanti nel tempo per dire qualcosa sul flicker);
    - `seam`: (frame a t=dur−1/fps, frame a t=0) → loop_seam, la diff alla cucitura del
      loop, e loop_seam_ratio, la stessa diviso la diff tipica tra frame consecutivi.
    """
    if not frames:
        raise ValueError("no frames")
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

    # diff tra keyframe (lontani nel tempo): misura di "quanto cambia" la scena, non di flicker
    diffs = np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2)) if stack.shape[0] > 1 else np.array([0.0])

    flicker = consecutive_diff = None
    if bursts:
        flicker, consecutive_diff = flicker_score(bursts)

    loop_seam = loop_seam_ratio = None
    if loop and seam is not None:
        loop_seam = float(np.abs(_luma(seam[0]) - _luma(seam[1])).mean())
        if consecutive_diff:
            loop_seam_ratio = loop_seam / max(consecutive_diff, 1e-6)

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
        "consecutive_diff_mean": consecutive_diff,
        "flicker_score": flicker,
        "loop_seam": loop_seam,
        "loop_seam_ratio": loop_seam_ratio,
    }
