"""Il motore senza CLI: payload da file e ispezione completa (metriche, gate, fogli).

Usato da `demogen play/probe/inspect` e dal server MCP (`demogen/mcp_server.py`): le stesse
misure e gli stessi gate, che a chiederli sia una persona dal terminale o un agente esterno.
"""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .bundle.build import build_payload
from .glsl.treeshake import load_library, treeshake

LIB_DIR = Path(__file__).resolve().parent / "glsl" / "lib"


class CompileFailed(RuntimeError):
    """Il payload non compila nel player: `errors` sono i log del compilatore."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("compile errors")
        self.errors = errors


def owning_timeline(path: Path) -> tuple[Path, dict, dict] | None:
    """Timeline vicina (cartella dello shader o quella sopra, più un livello di sottocartelle) che usa
    questo shader come scena: (file, spec, scena). Ricerca limitata, niente rglob su cartelle grandi."""
    target = path.resolve()
    for d in dict.fromkeys((path.parent, path.parent.parent)):
        for tl in sorted([*d.glob("*timeline*.json"), *d.glob("*/*timeline*.json")]):
            try:
                spec = json.loads(tl.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for scene in spec.get("scenes", []) if isinstance(spec, dict) else []:
                src = scene.get("src") if isinstance(scene, dict) else None
                if isinstance(src, str) and (tl.parent / src).resolve() == target:
                    return tl, spec, scene
    return None


def payload_from_file(path: Path, bpm: float = 120.0) -> dict:
    """Da .glsl (scena singola), timeline.json (demo) o .demo (payload già pronto) → payload .demo."""
    if path.suffix == ".demo":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".json":
        return build_payload(json.loads(path.read_text(encoding="utf-8")), path.parent)
    # shader di una timeline (esempi): la sua scena da sola, in loop, con common, testo, stile e BPM
    # della timeline (con il solo common.glsl generico gli shader del gatto e del pinguino non
    # compilavano: funzioni dello style mancanti, uniform del testo non dichiarati)
    owner = owning_timeline(path)
    if owner is not None:
        tl, spec, scene = owner
        one = {**scene, "start_bar": 0, "transition_in": "cut", "transition_bars": 0}
        return build_payload({**spec, "loop": True, "scenes": [one]}, tl.parent)
    # shader singolo: common = libreria tree-shaked + style (common.glsl vicino, se c'è)
    src = path.read_text(encoding="utf-8")
    style = ""
    for cand in (path.parent / "common.glsl", path.parent.parent / "common.glsl"):
        if cand.exists():
            style = cand.read_text(encoding="utf-8")
            break
    common = treeshake(src + "\n" + style, load_library(LIB_DIR)) + ("\n" + style if style else "")
    return {
        "format": "demogen/1",
        "meta": {"title": path.stem, "duration_s": 32.0, "loop": True, "bpm": bpm, "beats_per_bar": 4},
        "timeline": {
            "bpm": bpm,
            "beats_per_bar": 4,
            "scenes": [{"id": "s1", "start_bar": 0, "bars": 16, "transition_in": "cut", "transition_bars": 0}],
        },
        "common": common,
        "scenes": {"s1": src},
        "render": {"profile": "modern"},
        "quality": {"target_fps": 60, "min_scale": 0.25},
    }


def default_config():
    """La config di demogen.yaml se c'è, altrimenti i default (inspect e gate non servono chiavi)."""
    from .config import Config, load_config

    try:
        return load_config(None, interactive=False)
    except FileNotFoundError:
        return Config.model_validate({"providers": {}, "roles": {}})


@dataclass
class InspectReport:
    metrics: dict[str, Any]
    issues: list  # list[critic.models.Issue]
    renderer: str
    times: list[float]
    report_dir: Path
    files: list[str] = field(default_factory=list)  # nomi dei file scritti in report_dir

    @property
    def blockers(self) -> int:
        return sum(1 for i in self.issues if i.severity == "blocker")

    @property
    def majors(self) -> int:
        return sum(1 for i in self.issues if i.severity == "major")


def _np(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def inspect_payload(h, payload: dict, *, width: int = 480, height: int = 270, frames: int = 16,
                    cfg=None, report_dir: Path) -> InspectReport:
    """Carica il payload nell'harness `h`, misura (fotogrammi, NaN, perf al netto del costo fisso,
    flash WCAG su tutta la durata a 30 fps, raffiche, giunta del loop, audio), applica i gate e scrive
    il rapporto in `report_dir` (contact/burst/diff/perf.png, metrics.json, issues.json).

    La perf su una GPU vera si misura alla risoluzione del budget del profilo (come la pipeline): a
    480×270 il costo netto di una scena leggera è rumore di misura, e scalato ×16 diventava un blocker.
    Su SwiftShader (solo informativa) e per il retro (risoluzione interna fissa) a width×height.

    Alla fine nell'harness resta la scena vuota della misura del costo fisso."""
    from .browser.perf_lane import perf_lane
    from .critic.flash import analyze_flash
    from .critic.gates import is_software_renderer, run_gates
    from .critic.metrics_perf import perf_profile
    from .critic.metrics_video import video_metrics
    from .critic.perf_ref import measure_baseline
    from .critic.sheets import burst_sheet, contact_sheet, diff_heatmap, perf_chart

    cfg = cfg if cfg is not None else default_config()
    res = h.load(payload)
    if not res["ok"]:
        raise CompileFailed(list(res["errors"]))
    info = h.info()
    duration = float(payload["meta"]["duration_s"])
    times = [round(duration * (i + 0.5) / frames, 3) for i in range(frames)]
    pngs = h.capture(times, width, height)
    stats = h.scene_stats(times, width, height)
    prof_name = str(payload.get("render", {}).get("profile", "modern"))
    pw, ph = width, height
    if prof_name != "retro" and not is_software_renderer(str(info["renderer"])):
        budget = cfg.realtime.profiles.get(prof_name, cfg.realtime.profiles["modern"])
        pw, ph = (int(v) for v in budget.get("res", [width, height]))
    with perf_lane():
        # 5 ripetizioni (mediana): con 3 un picco isolato del giro di misura decideva il p95
        prof = h.profile(times[:8], pw, ph, repeats=5)
    sf = cfg.safety
    # flash WCAG su TUTTA la durata a >= 30 fps (a 10 fps uno strobo veloce andava in aliasing)
    cells = h.cell_sequence(0.0, duration, sf.flash_fps, 128, 72, grid=sf.flash_grid)
    pv = cfg.preview
    span = (pv.burst_len - 1) / pv.fps
    bursts_png = [
        h.capture([round(max(0.0, min(duration - span, duration * (b + 0.5) / pv.bursts - span / 2))
                         + k / pv.fps, 5) for k in range(pv.burst_len)], width, height)
        for b in range(pv.bursts)
    ]
    loop = bool(payload["meta"].get("loop"))
    seam_png = h.capture([max(0.0, duration - 1.0 / pv.fps), 0.0], width, height) if loop else None

    audio_m = audio_x = None
    if payload.get("audio"):
        from .critic.metrics_audio import audio_metrics

        sr = 44100
        blocks = int(np.ceil(duration * sr / 16384)) + 1
        raw = h.render_audio(0.0, blocks)
        audio_x = np.concatenate([np.asarray(b, dtype=np.float64) for b in raw])
        audio_m = audio_metrics(audio_x, sr, float(payload["meta"]["bpm"]), channels=2)

    # per ultimo: la scena vuota sostituisce il payload nell'harness
    fixed_ms = measure_baseline(h, pw, ph, payload)

    vm = video_metrics([_np(p) for p in pngs], stats, loop=loop, bursts=[[_np(p) for p in b] for b in bursts_png],
                       seam=(_np(seam_png[0]), _np(seam_png[1])) if seam_png else None)
    pf = perf_profile(
        {float(k): v for k, v in prof["samples"].items()},
        profile=prof_name,
        resolution=(pw, ph),
        method=str(prof["method"]),
        gpu=str(info["renderer"]),
        target_fps=cfg.realtime.target_fps,
        fixed_ms=fixed_ms,
    )
    fl = analyze_flash(cells, fps=sf.flash_fps, flash_max_per_s=sf.flash_max_per_s,
                       red_flash=sf.red_flash, area_frac=sf.flash_area_frac)
    raw_demo = json.dumps(payload).encode()
    metrics: dict[str, Any] = {
        "video": vm,
        "perf": pf.model_dump(),
        "flash": fl.model_dump(),
        "startup": {"compile_total_ms": res["compile_ms"]},
        "sizes": {"payload_raw_bytes": len(raw_demo), "payload_gzip_bytes": len(gzip.compress(raw_demo, 9))},
        "gpu": info["renderer"],
    }
    if audio_m is not None:
        metrics["audio"] = audio_m
    issues = run_gates(metrics, cfg)

    report_dir.mkdir(parents=True, exist_ok=True)
    files = ["contact.png", "burst.png", "diff.png", "perf.png", "metrics.json", "issues.json"]
    contact_sheet([Image.open(io.BytesIO(p)).convert("RGB") for p in pngs], times, report_dir / "contact.png")
    rows = [[Image.open(io.BytesIO(p)).convert("RGB") for p in b] for b in bursts_png]
    burst_sheet(rows, report_dir / "burst.png")
    diff_heatmap([np.asarray(im) for im in rows[0]], report_dir / "diff.png")
    perf_chart({float(k): max(v - fixed_ms, 0.0) for k, v in prof["samples"].items()},
               cfg.realtime.profiles["modern"]["p95"], report_dir / "perf.png")
    if audio_m is not None and audio_x is not None:
        from .critic.metrics_audio import spectrogram_png

        # audio_x è stereo interleaved: (N, 2) → spectrogram_png fa la media dei canali
        stereo = audio_x[: len(audio_x) // 2 * 2].reshape(-1, 2)
        spectrogram_png(stereo, 44100, float(payload["meta"]["bpm"]), report_dir / "spectrogram.png")
        files.append("spectrogram.png")
    (report_dir / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    (report_dir / "issues.json").write_text(json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8")
    return InspectReport(metrics=metrics, issues=issues, renderer=str(info["renderer"]), times=times,
                         report_dir=report_dir, files=files)
