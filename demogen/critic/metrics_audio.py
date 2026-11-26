"""Metrica audio (Fase 2): spettrogramma con griglia di battute, onset detection
(spectral flux) e allineamento onset vs griglia beat (errore in ms)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def spectral_flux_onsets(x: np.ndarray, sr: int, hop: int = 256, nfft: int = 1024) -> list[float]:
    """Onset (secondi) via spectral flux positiva con soglia adattiva."""
    return onsets_with_strength(x, sr, hop, nfft)[0]


def onsets_with_strength(
    x: np.ndarray, sr: int, hop: int = 256, nfft: int = 1024
) -> tuple[list[float], list[float]]:
    """Onset (secondi) via spectral flux positiva e forza = salto di RMS (50 ms dopo − 50 ms prima).

    Il flux misura "quanto è nuovo" lo spettro (un hi-hat debole ma a banda larga ha flux
    alto); la forza percepita di un colpo è la sua energia, quindi si usa l'RMS. Si misura il
    SALTO di energia e non l'energia: con un basso sostenuto a 55–80 Hz la finestra di 23 ms
    vede l'ampiezza oscillare e produce onset spuri fuori dal beat; misurati come energia
    assoluta risultavano "forti" (il basso è forte), come salto sono ~0."""
    if len(x) < nfft:
        return [], []
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
        return [], []
    thr = flux.mean() + 1.5 * flux.std()
    onsets: list[float] = []
    peaks: list[float] = []
    for i in range(1, n_frames - 1):
        if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            t = (i * hop + nfft // 2) / sr  # centro della finestra: allinea l'onset all'inizio dell'evento
            if not onsets or t - onsets[-1] > 0.08:  # refractory 80 ms
                onsets.append(t)
                peaks.append(float(flux[i]))
            elif flux[i] > peaks[-1]:  # dentro il refractory tieni il picco più forte
                onsets[-1], peaks[-1] = t, float(flux[i])
    win = max(1, int(0.05 * sr))

    def rms(a: int, b: int) -> float:
        seg = x[max(0, a):max(0, b)]
        return float(np.sqrt(np.mean(seg**2))) if len(seg) else 0.0

    strengths = []
    for t in onsets:
        a = int(t * sr) - win // 4
        strengths.append(max(0.0, rms(a, a + win) - rms(a - win, a)))
    return onsets, strengths


def beat_grid(duration_s: float, bpm: float) -> np.ndarray:
    beat_dur = 60.0 / bpm
    return np.arange(0.0, duration_s, beat_dur)


STRONG_FRAC = 0.5  # colpi "forti": flux >= 50% del colpo più forte
SUBDIV = 4  # griglia ritmica: sedicesimi del beat (beatDur/4)


def onset_beat_error(onsets: list[float], bpm: float, strengths: list[float] | None = None,
                     subdiv: int = SUBDIV) -> dict:
    """Errore medio |onset - punto più vicino della griglia ritmica| in ms, SOLO sui colpi forti.

    La griglia è a sedicesimi (beatDur/subdiv): una musica a tempo mette i colpi su beat,
    ottavi o sedicesimi. Contro i soli beat un arpeggio in ottavi senza cassa (run reale:
    chiptune a 128 BPM) dava 107 ms di errore pur essendo a tempo entro 2 ms. Una musica
    slegata dal BPM resta riconoscibile: colpi a caso darebbero in media beatDur/(4·subdiv)
    (~29 ms a 128 BPM), contro ~1,5 ms di una a tempo. Hi-hat e code deboli sono esclusi
    (solo i colpi forti)."""
    if not onsets:
        return {"n_onsets": 0, "n_strong": 0, "mean_abs_err_ms": None, "max_abs_err_ms": None}
    strong = list(onsets)
    if strengths:
        top = max(strengths)
        strong = [o for o, s in zip(onsets, strengths) if s >= STRONG_FRAC * top]
    grid = beat_grid(max(strong) + 1.0, bpm * max(1, subdiv))
    errs = [float(np.min(np.abs(grid - o))) * 1000.0 for o in strong]
    return {
        "n_onsets": len(onsets),
        "n_strong": len(strong),
        "mean_abs_err_ms": float(np.mean(errs)),
        "max_abs_err_ms": float(np.max(errs)),
    }


def to_mono(x: np.ndarray, channels: int = 1) -> np.ndarray:
    """Interleaved [L,R,L,R,...] → mono (L+R)/2; 1 canale invariato."""
    x = np.asarray(x, dtype=np.float64)
    if channels <= 1:
        return x
    n = len(x) // channels * channels
    return x[:n].reshape(-1, channels).mean(axis=1)


def audio_metrics(x: np.ndarray, sr: int, bpm: float, channels: int = 1) -> dict:
    mono = to_mono(x, channels)
    rms = float(np.sqrt(np.mean(mono**2))) if len(mono) else 0.0
    xs = np.asarray(x, dtype=np.float64)
    peak = float(np.abs(xs).max()) if len(xs) else 0.0  # il clip si misura per canale, non sul mix
    onsets, strengths = onsets_with_strength(mono, sr)
    return {
        "sr": sr,
        "duration_s": float(len(mono) / sr),
        "rms": rms,
        "peak": peak,
        "clipped": bool(peak >= 0.999),
        "onsets_s": onsets,
        "onset_vs_beat": onset_beat_error(onsets, bpm, strengths),
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
