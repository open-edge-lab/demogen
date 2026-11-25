"""Fogli visivi per il critico LLM: contact sheet, burst strip, heatmap, grafico perf."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _label(img: Image.Image, text: str) -> Image.Image:
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 18], fill=(0, 0, 0))
    d.text((4, 4), text, fill=(255, 255, 0))
    return img


def contact_sheet(
    frames: list[Image.Image], times: list[float], out_path: Path, cols: int = 4
) -> Path:
    """Griglia keyframe con timestamp sovrimpresso."""
    rows = (len(frames) + cols - 1) // cols
    tw, th = frames[0].width, frames[0].height
    sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), (10, 10, 10))
    for i, (f, t) in enumerate(zip(frames, times)):
        f2 = _label(f.convert("RGB").copy(), f"t={t:.2f}s bar={t:.1f}")
        sheet.paste(f2, ((i % cols) * tw, (i // cols) * (th + 18)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def burst_strip(frames: list[Image.Image], out_path: Path, label: str = "burst") -> Path:
    """Riga di frame consecutivi per giudicare il moto."""
    tw, th = frames[0].width, frames[0].height
    strip = Image.new("RGB", (len(frames) * tw, th + 18), (10, 10, 10))
    for i, f in enumerate(frames):
        strip.paste(_label(f.convert("RGB").copy(), f"{label} #{i}"), (i * tw, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out_path)
    return out_path


def burst_sheet(bursts: list[list[Image.Image]], out_path: Path) -> Path:
    """Più raffiche di frame consecutivi, una riga per raffica (moto e flicker a frame rate)."""
    tw, th = bursts[0][0].width, bursts[0][0].height
    cols = max(len(b) for b in bursts)
    sheet = Image.new("RGB", (cols * tw, len(bursts) * (th + 18)), (10, 10, 10))
    for r, burst in enumerate(bursts):
        for i, f in enumerate(burst):
            sheet.paste(_label(f.convert("RGB").copy(), f"raffica {r} #{i}"), (i * tw, r * (th + 18)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def diff_heatmap(frames: list[np.ndarray], out_path: Path) -> Path:
    """|frame[i+1]-frame[i]| come heatmap per frame (flicker/aliasing temporale)."""
    n = len(frames) - 1
    if n < 1:
        raise ValueError("servono almeno 2 frame")
    h, w = frames[0].shape[:2]
    strip = Image.new("RGB", (n * w, h + 18), (0, 0, 0))
    d = ImageDraw.Draw(strip)
    d.rectangle([0, 0, n * w, 18], fill=(0, 0, 0))
    d.text((4, 4), "|diff| frame consecutivi (heatmap)", fill=(255, 255, 0))
    for i in range(n):
        diff = np.abs(frames[i + 1].astype(float) - frames[i].astype(float)).mean(axis=2)
        diff = np.clip(diff * 4, 0, 255).astype(np.uint8)  # amplifica ×4
        img = Image.fromarray(diff, mode="L").convert("RGB")
        strip.paste(img, (i * w, 18))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out_path)
    return out_path


def perf_chart(samples: dict[float, float], budget_ms: float, out_path: Path,
               title: str = "ms/frame") -> Path:
    """Grafico ms per tempo con linea di budget."""
    w, h = 640, 240
    img = Image.new("RGB", (w, h), (12, 12, 12))
    d = ImageDraw.Draw(img)
    ts = sorted(samples)
    if not ts:
        raise ValueError("no samples")
    ms = [samples[t] for t in ts]
    ymax = max(max(ms) * 1.2, budget_ms * 1.5, 1.0)
    tmin, tmax = ts[0], ts[-1]

    def xy(t: float, v: float) -> tuple[float, float]:
        x = 40 + (t - tmin) / max(tmax - tmin, 1e-9) * (w - 60)
        y = h - 30 - (v / ymax) * (h - 50)
        return x, y

    # linea budget
    yb = h - 30 - (budget_ms / ymax) * (h - 50)
    d.line([(40, yb), (w - 20, yb)], fill=(255, 80, 80), width=1)
    d.text((w - 90, yb - 12), f"budget {budget_ms:.1f}ms", fill=(255, 80, 80))
    pts = [xy(t, v) for t, v in zip(ts, ms)]
    d.line(pts, fill=(80, 200, 255), width=2)
    for (t, v), (x, y) in zip(zip(ts, ms), pts):
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(80, 200, 255))
    d.text((40, 6), f"{title}  (p95={np.percentile(ms,95):.2f} ms, mean={np.mean(ms):.2f} ms)",
           fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
