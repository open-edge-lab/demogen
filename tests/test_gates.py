"""Test sintetici dei gate (piano §12.5): esito atteso senza browser."""

from __future__ import annotations

import numpy as np

from demogen.config import Config
from demogen.critic.flash import analyze_flash
from demogen.critic.gates import run_gates
from demogen.critic.metrics_video import video_metrics

CFG = Config.model_validate({"providers": {}, "roles": {}})


def _frame(v: int, color=(0, 0, 0)) -> np.ndarray:
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = color
    img[:] = img[0, 0] * 0 + v if color == (0, 0, 0) else color
    return img


def test_gate_nero_major() -> None:
    frames = [np.zeros((16, 16, 3), dtype=np.uint8) for _ in range(4)]
    m = video_metrics(frames)
    issues = run_gates({"video": m}, CFG)
    assert any(i.severity == "major" and "nero" in i.description for i in issues)


def test_gate_nan_blocker() -> None:
    m = video_metrics([np.full((8, 8, 3), 128, dtype=np.uint8)],
                      float_stats=[{"nan_ratio": 0.5, "inf_ratio": 0.0}])
    issues = run_gates({"video": m}, CFG)
    assert any(i.severity == "blocker" and "NaN" in i.description for i in issues)


def test_gate_perf_p95_blocker_e_mean_major() -> None:
    # p95 oltre budget → blocker con hotspot; mean oltre budget → major (consumo)
    perf = {"profile": "modern", "p95_ms": 9.0, "mean_ms": 5.0,
            "gpu_load_est": 5.0 / 16.7, "hotspots": [{"t": 3.0, "ms": 12.0}]}
    issues = run_gates({"perf": perf}, CFG)
    assert any(i.severity == "blocker" and "p95" in i.description for i in issues)
    assert any(i.severity == "major" and "carico medio" in i.description for i in issues)
    # p95 nel budget ma mean alto → solo major (consumo), niente blocker perf
    perf2 = {"profile": "modern", "p95_ms": 5.0, "mean_ms": 4.5, "gpu_load_est": 0.27, "hotspots": []}
    issues2 = run_gates({"perf": perf2}, CFG)
    assert not any(i.severity == "blocker" and "p95" in i.description for i in issues2)
    assert any(i.severity == "major" and "carico medio" in i.description for i in issues2)


def test_gate_flash_strobo_10hz_blocker() -> None:
    # 10 Hz alternato bianco/nero su tutte le celle → ~10 flash/s > 3
    fps = 30
    seq = []
    for i in range(fps * 2):
        v = 255 if i % 2 == 0 else 0
        seq.append([[float(v), float(v), float(v)] for _ in range(64)])
    rep = analyze_flash(seq, fps=fps, flash_max_per_s=3)
    assert not rep.passed
    assert rep.max_flashes_per_s > 3
    issues = run_gates({"flash": rep.model_dump()}, CFG)
    assert any(i.severity == "blocker" and "flash" in i.description for i in issues)


def test_flash_lento_passa() -> None:
    fps = 30
    seq = []
    for i in range(fps * 2):
        v = int(127 + 100 * np.sin(2 * np.pi * i / fps))  # 1 Hz morbido
        seq.append([[float(v), float(v), float(v)] for _ in range(64)])
    rep = analyze_flash(seq, fps=fps)
    assert rep.passed


def test_flash_rosso_blocker() -> None:
    fps = 30
    seq = []
    for i in range(fps):
        if i % 2 == 0:
            seq.append([[0.0, 0.0, 0.0] for _ in range(64)])
        else:
            seq.append([[255.0, 0.0, 0.0] for _ in range(64)])  # rosso saturo
    rep = analyze_flash(seq, fps=fps, red_flash=True)
    assert rep.red_flash_events > 0
    assert not rep.passed


def test_gate_payload_fuori_limite() -> None:
    issues = run_gates({"sizes": {"payload_gzip_bytes": 100 * 1024}}, CFG)
    assert any(i.severity == "major" and "payload" in i.description for i in issues)


def test_gate_compilazione_lenta() -> None:
    issues = run_gates({"startup": {"compile_total_ms": 5000.0}}, CFG)
    assert any(i.severity == "major" and "compilazione" in i.description for i in issues)


def test_video_metrics_loop_seam() -> None:
    a = np.full((8, 8, 3), 200, dtype=np.uint8)
    b = np.zeros((8, 8, 3), dtype=np.uint8)
    m = video_metrics([a, b], loop=True)
    assert m["loop_seam"] is not None and m["loop_seam"] > 0.5
    m2 = video_metrics([a, b], loop=False)
    assert m2["loop_seam"] is None
