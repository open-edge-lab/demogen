"""Analisi fotosensibilità (WCAG 2.3.1, "three flashes or below threshold").

Input: `cell_seq` = lista di frame campionati a `fps`; ogni frame = N celle (griglia g×g)
× [R, G, B] **lineari** in [0, 1] (l'harness linearizza ogni pixel PRIMA della media).

Definizioni (WCAG 2.x) e come sono applicate:
- transizione generale: variazione di luminanza relativa >= 0.1 in cui lo stato più
  scuro è < 0.8. Per cella si estraggono gli estremi con isteresi 0.1 (zigzag): ogni
  coppia di estremi consecutivi è una transizione, anche se distribuita su più frame;
- flash = coppia di transizioni opposte (su-giù o giù-su) della stessa area: per cella,
  le transizioni alternano, quindi i flash sono le coppie consecutive;
- area: WCAG conta i flash di un'area >= 25% di un campo visivo di 10° (≈ 341×256 px su
  1024×768, cioè ~2.8% dello schermo, `area_frac`). Si fallisce se, in una qualsiasi
  finestra di 1 s, almeno K = ceil(area_frac × celle) celle lampeggiano più di
  `flash_max_per_s` volte. Approssimazione conservativa: le K celle possono essere
  non contigue. Il valore riportato è il ritmo sostenuto dall'area di K celle più
  "lampeggiante" (il K-esimo conteggio per cella nella finestra peggiore);
- flash rosso: stessa logica sul segnale max(0, (R−G−B)·320) con soglia 20, valida se
  lo stato più rosso è saturo (R/(R+G+B) >= 0.8).

Un'onda di luce che attraversa lo schermo fa lampeggiare ogni cella poche volte al
secondo (passa); uno strobo o la statica TV fanno lampeggiare molte celle molte volte
(fallisce), anche se mescolati a una texture in movimento.
"""

from __future__ import annotations

import math

import numpy as np

from .models import FlashReport

LUMA_THR = 0.1
DARK_MAX = 0.8
RED_THR = 20.0
RED_SAT = 0.8


def _zigzag(x: np.ndarray, thr: float) -> list[tuple[int, float]]:
    """Estremi alternati con isteresi `thr` (pivot consecutivi differiscono di >= thr).

    L'estremo è il PRIMO frame che raggiunge il massimo/minimo (la transizione finisce lì)."""
    n = len(x)
    if n < 2:
        return []
    pivots: list[tuple[int, float]] = []
    trend = 0
    hi = lo = cur = 0
    for i in range(1, n):
        v = x[i]
        if trend == 0:
            if v > x[hi]:
                hi = i
            if v < x[lo]:
                lo = i
            if x[hi] - x[lo] >= thr:
                if hi > lo:
                    pivots, trend, cur = [(lo, float(x[lo]))], 1, hi
                else:
                    pivots, trend, cur = [(hi, float(x[hi]))], -1, lo
        elif trend == 1:
            if v > x[cur]:
                cur = i
            elif x[cur] - v >= thr:
                pivots.append((cur, float(x[cur])))
                trend, cur = -1, i
        else:
            if v < x[cur]:
                cur = i
            elif v - x[cur] >= thr:
                pivots.append((cur, float(x[cur])))
                trend, cur = 1, i
    if trend != 0 and abs(x[cur] - pivots[-1][1]) >= thr:
        pivots.append((cur, float(x[cur])))
    return pivots


def _cell_flashes(signal: np.ndarray, thr: float, valid) -> np.ndarray:
    """(N, C) bool: True al frame in cui una cella completa un flash (2ª transizione di una coppia).

    `valid(j, ia, va, ib, vb)` filtra le transizioni (es. stato scuro < 0.8). Una
    transizione non valida interrompe la coppia in corso."""
    n, c = signal.shape
    out = np.zeros((n, c), dtype=bool)
    for j in range(c):
        piv = _zigzag(signal[:, j], thr)
        pending = False  # c'è una prima transizione valida in attesa della sua opposta
        for (ia, va), (ib, vb) in zip(piv, piv[1:]):
            if not valid(j, ia, va, ib, vb):
                pending = False
                continue
            if pending:
                out[ib, j] = True
                pending = False
            else:
                pending = True
    return out


def _area_rate(flashes: np.ndarray, fps: float, k: int) -> np.ndarray:
    """Per ogni frame i: il K-esimo conteggio di flash per cella nella finestra (t_i − 1 s, t_i]."""
    n, c = flashes.shape
    w = max(1, int(round(fps)))
    cs = np.cumsum(flashes, axis=0, dtype=np.int32)
    prev = np.zeros_like(cs)
    prev[w:] = cs[:-w]
    counts = cs - prev  # (N, C)
    k = min(k, c)
    return -np.partition(-counts, k - 1, axis=1)[:, k - 1]


def analyze_flash(
    cell_seq: list[list[list[float]]],
    fps: float,
    flash_max_per_s: int = 3,
    red_flash: bool = True,
    area_frac: float = 0.028,
) -> FlashReport:
    if len(cell_seq) < 2:
        return FlashReport(passed=True)
    rgb = np.clip(np.asarray(cell_seq, dtype=np.float64), 0.0, 1.0)  # (N, C, 3) lineari
    n_cells = rgb.shape[1]
    k = max(1, math.ceil(area_frac * n_cells))
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]

    gen = _cell_flashes(luma, LUMA_THR, lambda j, ia, va, ib, vb: min(va, vb) < DARK_MAX)
    rate = _area_rate(gen, fps, k)

    red_rate = np.zeros_like(rate)
    red_total = 0
    if red_flash:
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        red = np.maximum(0.0, (r - g - b) * 320.0)
        sat = r / (r + g + b + 1e-9) >= RED_SAT

        def red_valid(j: int, ia: int, va: float, ib: int, vb: float) -> bool:
            return bool(sat[ia if va >= vb else ib, j])

        red_fl = _cell_flashes(red, RED_THR, red_valid)
        red_rate = _area_rate(red_fl, fps, k)
        red_total = int(red_fl.any(axis=1).sum())

    max_per_s = float(rate.max(initial=0))
    max_red = float(red_rate.max(initial=0))
    passed = max_per_s <= flash_max_per_s and max_red <= flash_max_per_s
    windows: list[tuple[float, float]] = []
    if not passed:
        bad = np.flatnonzero((rate > flash_max_per_s) | (red_rate > flash_max_per_s))
        last = -1e9
        for i in bad:  # una finestra per secondo, non una per frame
            t1 = (i + 1) / fps
            if t1 - last >= 1.0:
                windows.append((round(max(0.0, t1 - 1.0), 3), round(t1, 3)))
                last = t1
            if len(windows) >= 8:
                break
    return FlashReport(
        max_flashes_per_s=max_per_s,
        max_red_flashes_per_s=max_red,
        red_flash_events=red_total,
        windows=windows,
        area_cells=k,
        passed=passed,
    )
