"""Fase 2 — audio: render GPU a blocchi, continuità tra chunk, FFT del chip synth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright")
np = pytest.importorskip("numpy")

from demogen.browser.harness import Harness
from demogen.bundle.build import build_payload

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

SIN_AUDIO = """
void mainAudio(out vec4 o, in float t) {
    float s = sin(6.2831 * 440.0 * t);
    o = vec4(s, s, 0.0, 1.0);
}
"""


def _payload_with_audio(audio_src: str) -> dict:
    spec = json.loads((EXAMPLES / "audio_chip.timeline.json").read_text(encoding="utf-8"))
    spec["audio"] = None
    payload = build_payload(spec, EXAMPLES, do_minify=False)
    payload["audio"] = audio_src
    return payload


def _chip_payload() -> dict:
    spec = json.loads((EXAMPLES / "audio_chip.timeline.json").read_text(encoding="utf-8"))
    return build_payload(spec, EXAMPLES, do_minify=False)


def test_audio_compila_e_renderizza_continuita_chunk() -> None:
    """Sinusoide 440 Hz renderizzata su 3 blocchi GPU consecutivi: nessuna
    discontinuità ai confini dei chunk (niente click/gap)."""
    with Harness(gpu="swiftshader", headless=True) as h:
        res = h.load(_payload_with_audio(SIN_AUDIO))
        assert res["ok"], res["errors"]
        blocks = h.render_audio(0.0, 3)
        assert len(blocks) == 3
        x = np.concatenate([np.asarray(b, dtype=np.float64)[0::2] for b in blocks])
        assert len(x) == 3 * 16384
        # continuità: la sinusoide non può saltare più di max diff atteso ai confini
        diffs = np.abs(np.diff(x))
        # campionamento 44100 (o sampleRate del context): max diff teorico ~ 2*pi*440/sr
        assert diffs.max() < 0.2, f"discontinuità: max diff {diffs.max():.3f}"
        # frequenza dominante 440 Hz via FFT
        spec = np.abs(np.fft.rfft(x[:16384] * np.hanning(16384)))
        freqs = np.fft.rfftfreq(16384, 1 / 44100)
        peak = freqs[int(np.argmax(spec))]
        assert abs(peak - 440.0) < 5.0, f"picco a {peak:.1f} Hz invece di 440"


def test_chip_synth_fft_kick_hat() -> None:
    """Il chip demo (kick/hat/snare/bass) renderizzato su GPU ha: energia dominante
    del kick sotto i 200 Hz e hat con energia sopra i 5 kHz."""
    with Harness(gpu="swiftshader", headless=True) as h:
        res = h.load(_chip_payload())
        assert res["ok"], res["errors"]
        blocks = h.render_audio(0.0, 8)  # ~3 s a 44.1 kHz
        x = np.concatenate([np.asarray(b, dtype=np.float64)[0::2] for b in blocks])
        assert np.isfinite(x).all()
        assert np.abs(x).max() > 0.05, "audio muto"
        # FFT sul primo beat (0.5 s a 120 bpm): il kick domina sotto i 200 Hz
        n = 22050
        spec = np.abs(np.fft.rfft(x[:n] * np.hanning(n)))
        freqs = np.fft.rfftfreq(n, 1 / 44100)
        low = spec[freqs < 200]
        high = spec[freqs > 5000]
        assert low.max() > high.max() * 0.5, "kick non dominante in basso"
        assert high.max() > spec.max() * 0.005, "hat (alte frequenze) assente"
        # RMS non nulla e no clip
        rms = float(np.sqrt(np.mean(x**2)))
        assert 0.01 < rms < 1.0
        assert np.abs(x).max() <= 1.0


def test_bundle_audio_chip_include_audio() -> None:
    payload = _chip_payload()
    assert "audio" in payload and "mainAudio" in payload["audio"]
    assert "chipKick" in payload["common"] or "chipKick" in payload["audio"]


def test_metrics_audio_onset_vs_beat() -> None:
    """Burst a ogni beat (120 bpm -> 0.5 s): onset allineati, errore ~0 ms."""
    from demogen.critic.metrics_audio import audio_metrics

    sr = 44100
    bpm = 120.0
    dur = 4.0
    t = np.arange(int(sr * dur)) / sr
    x = np.zeros_like(t)
    for k in range(int(dur * bpm / 60)):
        i0 = int(k * 60.0 / bpm * sr)
        x[i0 : i0 + 400] += np.hanning(400) * 0.9  # burst di 400 sample sul beat
    m = audio_metrics(x, sr, bpm)
    assert m["onset_vs_beat"]["n_onsets"] >= 6
    assert m["onset_vs_beat"]["mean_abs_err_ms"] < 5.0
    assert not m["clipped"]
