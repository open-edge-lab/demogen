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


CELLS = 256  # griglia 16×16 dell'harness
FPS = CFG.safety.flash_fps  # campionamento di produzione


def _seq(lum_at, seconds: float = 2.0, n_flashing: int = CELLS, rgb=(1.0, 1.0, 1.0), bg: float = 0.05):
    """Sequenza di celle lineari: le prime n_flashing seguono lum_at(t), le altre restano a bg."""
    seq = []
    for i in range(int(seconds * FPS)):
        v = float(lum_at(i / FPS))
        frame = [[v * rgb[0], v * rgb[1], v * rgb[2]] for _ in range(n_flashing)]
        frame += [[bg, bg, bg] for _ in range(CELLS - n_flashing)]
        seq.append(frame)
    return seq


def _square(hz: float):
    return lambda t: 1.0 if int(t * hz * 2) % 2 == 0 else 0.0


def test_gate_flash_strobo_10hz_blocker() -> None:
    rep = analyze_flash(_seq(_square(10.0)), fps=FPS, flash_max_per_s=3)
    assert not rep.passed
    assert rep.max_flashes_per_s > 3
    issues = run_gates({"flash": rep.model_dump()}, CFG)
    assert any(i.severity == "blocker" and "flash" in i.description for i in issues)


def test_flash_strobo_8hz_campionato_in_produzione_bloccato() -> None:
    # a 8 fps (vecchio campionamento) uno strobo a 8 Hz andava in aliasing e risultava 0 flash
    rep = analyze_flash(_seq(_square(8.0)), fps=FPS)
    assert not rep.passed
    assert rep.max_flashes_per_s >= 7


def test_flash_area_parziale_5pct_bloccato_2pct_passa() -> None:
    rep = analyze_flash(_seq(_square(8.0), n_flashing=13), fps=FPS)  # 13/256 ≈ 5% > 2.8%
    assert not rep.passed
    rep2 = analyze_flash(_seq(_square(8.0), n_flashing=5), fps=FPS)  # 5/256 ≈ 2% < 2.8%
    assert rep2.passed


def test_flash_sul_beat_2hz_passa() -> None:
    # beatFlash a 120 bpm: un lampo (su e giù) per beat = 2 flash/s ≤ 3 → conforme
    rep = analyze_flash(_seq(lambda t: 0.05 + 0.9 * np.exp(-8.0 * ((t * 2.0) % 1.0)), seconds=3.0), fps=FPS)
    assert rep.passed, rep
    assert 1.5 <= rep.max_flashes_per_s <= 3


def test_flash_onda_che_attraversa_lo_schermo_passa() -> None:
    # banda luminosa che scorre su tutte le celle 2 volte al secondo: ogni cella lampeggia 2 volte/s
    seq = []
    for i in range(int(3.0 * FPS)):
        pos = ((i / FPS) * 2.0 % 1.0) * CELLS
        seq.append([[v, v, v] for v in (0.9 if abs(j - pos) < 20 else 0.05 for j in range(CELLS))])
    assert analyze_flash(seq, fps=FPS).passed


def test_flash_strobo_mescolato_a_texture_mobile_bloccato() -> None:
    rng = np.random.default_rng(1)
    strobe = _square(8.0)
    seq = []
    for i in range(int(2.0 * FPS)):
        t = i / FPS
        v = strobe(t)
        frame = [[v, v, v] for _ in range(13)]  # 5% dello schermo a 8 Hz
        frame += [[x, x, x] for x in (0.3 + 0.2 * np.sin(t * 3 + rng.random() * 0.1 + j) for j in range(CELLS - 13))]
        seq.append(frame)
    assert not analyze_flash(seq, fps=FPS).passed


def test_flash_lento_passa() -> None:
    rep = analyze_flash(_seq(lambda t: 0.4 + 0.35 * np.sin(2 * np.pi * t)), fps=FPS)  # 1 Hz morbido
    assert rep.passed


def test_flash_chiaro_sopra_soglia_scura_passa() -> None:
    # alternanza rapida ma tra 0.85 e 1.0: lo stato più scuro non è < 0.8 → nessun flash
    rep = analyze_flash(_seq(lambda t: 0.85 if int(t * 20) % 2 else 1.0), fps=FPS)
    assert rep.passed


def test_flash_rosso_contato_a_coppie() -> None:
    red = (1.0, 0.0, 0.0)
    fast = analyze_flash(_seq(_square(10.0), rgb=red), fps=FPS, red_flash=True)
    assert fast.max_red_flashes_per_s > 3 and fast.red_flash_events > 0
    assert not fast.passed
    issues = run_gates({"flash": fast.model_dump()}, CFG)
    assert any(i.severity == "blocker" and "rossi" in i.description for i in issues)
    # una sola transizione verso il rosso (o un rosso a 1 Hz) non è più un blocker
    slow = analyze_flash(_seq(_square(1.0), rgb=red), fps=FPS, red_flash=True)
    assert slow.passed


def test_gate_perf_scalato_alla_risoluzione_del_budget() -> None:
    # 1.0 ms misurato a 480×270 → ~16 ms a 1080p (16× pixel): oltre il budget di 6 ms
    perf = {"profile": "modern", "p95_ms": 1.0, "mean_ms": 0.5, "resolution": (480, 270),
            "gpu": "ANGLE (NVIDIA GeForce)", "hotspots": []}
    issues = run_gates({"perf": perf}, CFG)
    blk = [i for i in issues if i.severity == "blocker"]
    assert blk and "stimato" in blk[0].description
    # alla risoluzione del budget nessuna scala
    perf_full = {**perf, "resolution": (1920, 1080)}
    assert not any(i.severity == "blocker" for i in run_gates({"perf": perf_full}, CFG))
    # retro: risoluzione interna fissa, niente scala
    retro = {**perf, "profile": "retro", "p95_ms": 0.8, "mean_ms": 0.3}
    assert not any(i.severity == "blocker" for i in run_gates({"perf": retro}, CFG))


def test_gate_perf_su_swiftshader_solo_informativo() -> None:
    perf = {"profile": "modern", "p95_ms": 40.0, "mean_ms": 30.0, "resolution": (1920, 1080),
            "gpu": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))", "hotspots": []}
    issues = run_gates({"perf": perf}, CFG)
    assert issues and all(i.severity == "info" for i in issues)
    assert "software" in issues[0].description


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
