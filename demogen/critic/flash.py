"""Analisi fotosensibilità (WCAG 2.3.1) da sequenza di celle RGB dell'harness.

Input: cell_seq = lista di frame; ogni frame = 64 celle (8x8) × [r,g,b] in [0,255].
Un flash = coppia di variazioni opposte di luminanza relativa >= 0.1 in cui lo
stato più scuro < 0.8, su celle che coprono >= 25% dello schermo (16/64).
Gate: più di `flash_max_per_s` flash in una finestra di 1 s → fail; flash rossi
saturi (R/(R+G+B) >= 0.8) contati allo stesso modo.
"""

from __future__ import annotations

import numpy as np

from .models import FlashReport

CELLS = 64
MIN_CELLS = 16  # 25% di 64


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def analyze_flash(
    cell_seq: list[list[list[float]]],
    fps: float,
    flash_max_per_s: int = 3,
    red_flash: bool = True,
) -> FlashReport:
    if len(cell_seq) < 2:
        return FlashReport(passed=True)
    frames = np.array(cell_seq, dtype=np.float64)  # (N, 64, 3)
    lin = _srgb_to_linear(frames)
    luma = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]  # (N,64)

    n = len(frames)
    flash_events: list[float] = []  # tempo (s) di ogni flash
    red_events: list[float] = []
    for i in range(n - 1):
        dl = luma[i + 1] - luma[i]  # (64,)
        # celle con variazione significativa in una direzione
        up = (dl >= 0.1) & (luma[i] < 0.8)
        down = (dl <= -0.1) & (luma[i + 1] < 0.8)
        is_flash = (up.sum() >= MIN_CELLS) or (down.sum() >= MIN_CELLS)
        if is_flash:
            flash_events.append((i + 1) / fps)
        if red_flash:
            r = lin[i + 1, :, 0]
            g = lin[i + 1, :, 1]
            b = lin[i + 1, :, 2]
            tot = r + g + b + 1e-9
            red_mask = (r / tot >= 0.8) & (dl >= 0.1)
            if red_mask.sum() >= MIN_CELLS:
                red_events.append((i + 1) / fps)

    # finestre di 1 s: max flash per secondo
    max_per_s = 0.0
    windows: list[tuple[float, float]] = []
    if flash_events:
        ev = np.array(flash_events)
        for t0 in np.arange(0, ev.max() + 1.0, 1.0):
            count = float(((ev >= t0) & (ev < t0 + 1.0)).sum())
            if count > max_per_s:
                max_per_s = count
            if count > flash_max_per_s:
                windows.append((float(t0), float(t0 + 1.0)))
    passed = max_per_s <= flash_max_per_s and len(red_events) == 0
    return FlashReport(
        max_flashes_per_s=max_per_s,
        red_flash_events=len(red_events),
        windows=windows,
        passed=passed,
    )
