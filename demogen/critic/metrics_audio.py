"""Metrica audio (Fase 2): spettrogramma con griglia di battute, onset detection
(spectral flux) e allineamento onset vs griglia beat (errore in ms)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def spectral_flux_onsets(x: np.ndarray, sr: int, hop: int = 256, nfft: int = 1024) -> list[float]:
    """Onset (secondi) via spectral flux positiva con soglia adattiva."""
    if len(x) < nfft:
        return []
    win = np.hanning(nfft)
    n_frames = 1 + (len(x) - nfft) // hop
    flux = np.zeros(n_frames)
    prev = None
    for i in range(n_frames):
        seg = x[i * hop : i * hop + nfft] * win
        mag = np.abs(np.fft.rfft(seg))
        if prev is not None:
            flux[i] = float(np.sum(np.maximum(mag - prev, 0.0)))
        prev = mag
    if flux.max() <= 0:
        return []
    thr = flux.mean() + 1.5 * flux.std()
    onsets: list[float] = []
    for i in range(1, n_frames - 1):
        if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            if not onsets or (i * hop / sr) - onsets[-1] > 0.08:  # refractory 80 ms
                # centro della finestra: allinea l'onset al vero inizio dell'evento
                onsets.append((i * hop + nfft // 2) / sr)
    return onsets


def beat_grid(duration_s: float, bpm: float) -> np.ndarray:
    beat_dur = 60.0 / bpm
    return np.arange(0.0, duration_s, beat_dur)


def onset_beat_error(onsets: list[float], bpm: float) -> dict:
    """Errore medio |onset - beat più vicino| in ms (kick allineato al beat)."""
    if not onsets:
        return {"n_onsets": 0, "mean_abs_err_ms": None, "max_abs_err_ms": None}
    grid = beat_grid(max(onsets) + 1.0, bpm)
    errs = [float(np.min(np.abs(grid - o))) * 1000.0 for o in onsets]
    return {
        "n_onsets": len(onsets),
        "mean_abs_err_ms": float(np.mean(errs)),
        "max_abs_err_ms": float(np.max(errs)),
    }


def audio_metrics(x: np.ndarray, sr: int, bpm: float, channels: int = 1) -> dict:
    x = np.asarray(x, dtype=np.float64)
    mono = x[0::channels] if channels > 1 else x
    rms = float(np.sqrt(np.mean(mono**2))) if len(mono) else 0.0
    peak = float(np.abs(mono).max()) if len(mono) else 0.0
    onsets = spectral_flux_onsets(mono, sr)
    return {
        "sr": sr,
        "duration_s": float(len(mono) / sr),
        "rms": rms,
        "peak": peak,
        "clipped": bool(peak >= 0.999),
        "onsets_s": onsets,
        "onset_vs_beat": onset_beat_error(onsets, bpm),
    }


def spectrogram_png(
    x: np.ndarray, sr: int, bpm: float, out_path: Path, width: int = 160, height: int = 64
) -> None:
    """Spettrogramma log in PNG con griglia verticale dei beat (PIL, no rete)."""
    from PIL import Image, ImageDraw

    mono = np.asarray(x, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    nfft, hop = 1024, 512
    if len(mono) < nfft:
        mono = np.pad(mono, (0, nfft - len(mono)))
    n_frames = 1 + (len(mono) - nfft) // hop
    win = np.hanning(nfft)
    spec = np.zeros((nfft // 2, n_frames))
    for i in range(n_frames):
        spec[:, i] = np.abs(np.fft.rfft(mono[i * hop : i * hop + nfft] * win))[: nfft // 2]
    log = np.log1p(spec)
    log = (log - log.min()) / max(log.max() - log.min(), 1e-9)
    img = Image.fromarray((log[::-1] * 255).astype(np.uint8)).resize((width, height))
    img = img.convert("RGB")
    dr = ImageDraw.Draw(img)
    beat_dur = 60.0 / bpm
    dur = len(mono) / sr
    for b in np.arange(0.0, dur, beat_dur):
        px = int(b / dur * width)
        dr.line([(px, 0), (px, height)], fill=(255, 80, 80), width=1)
    img.save(out_path)
