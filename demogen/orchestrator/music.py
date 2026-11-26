"""Colonna sonora (passo SM): il compositore LLM scrive la musica, poi la si "ascolta" con i numeri.

La musica è uno shader GLSL `void mainAudio(out vec4 o, in float t)` che il player calcola sulla GPU
a blocchi (Fase 2). Qui:
- prompt al ruolo `composer` dal prompt della demo, dal prompt musicale dell'utente (facoltativo),
  dall'`audio_brief` dello spec e dalle sezioni della timeline;
- ascolto nell'harness: compila, calcola i campioni (≤ 30 s), misura volume, picco, colpi rispetto
  al beat, battute mute, velocità di calcolo;
- con problemi bloccanti (non compila, NaN, muta, troppo pesante) revisione, fino a
  `budget.max_iterations_per_scene` versioni.

File in `audio/`: vN.glsl, vN.meta.json, vN.metrics.json, vN.issues.json, vN.spectrogram.png e
best.json (`{"version": "vN"}`, oppure `null` se nessuna versione è utilizzabile: la demo esce muta
con un avviso nel report, invece di fallire).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

from .. import progress
from ..critic.gates import run_gates
from ..critic.metrics_audio import audio_metrics, spectrogram_png, to_mono
from ..critic.models import Issue
from ..glsl.treeshake import treeshake
from ..llm.client import LLMTruncated, chat_with_room
from ..llm.envelope import EnvelopeError, parse_envelope
from ..spec.models import DemoSpec
from . import prompts as P
from .selection import list_versions, next_version
from .steps import LIB, error_log

SRC_MUSIC = 3  # numero di sorgente (#line) del codice del compositore: errori con le sue righe
AUDIO_BLOCK_SAMPLES = 16384
ANALYSIS_MAX_S = 30.0
SILENT_SCENE = "void mainImage(out vec4 c, in vec2 p) { c = vec4(0.0, 0.0, 0.0, 1.0); }\n"
CHIP_LIB = Path(__file__).resolve().parents[1] / "glsl" / "lib" / "audio" / "chip.glsl"
_ERR = re.compile(r"ERROR:\s*(\d+):(\d+):\s*(.*)")
_FN = re.compile(r"/// @fn (\w+)\n((?:///[^\n]*\n)*)(\w+\s+\w+\s*\([^)]*\))")


def audio_dir(ctx) -> Path:
    return ctx.project.path / "audio"


# ---------------------------------------------------------------- prompt
def library_reference() -> str:
    """Le funzioni della libreria audio con la loro documentazione (dai commenti `/// @fn`)."""
    out = []
    for m in _FN.finditer(CHIP_LIB.read_text(encoding="utf-8")):
        doc = " ".join(line.lstrip("/").strip() for line in m.group(2).splitlines())
        out.append(f"- `{m.group(3).strip()}`: {doc}")
    out.append("- `float hash11(float p)`: deterministic hash in [0,1); per-sample noise: "
               "`hash11(floor(t * iSampleRate))`")
    return "\n".join(out)


def sections(spec: DemoSpec) -> list[dict]:
    """Le sezioni della timeline (una per scena) con battute, secondi e carattere della scena."""
    bpb, bpm = spec.timeline.beats_per_bar, spec.timeline.bpm
    bar_s = 60.0 * bpb / bpm
    briefs = {s.id: s for s in spec.scenes}
    out = []
    for slot in spec.timeline.scenes:
        b = briefs.get(slot.id)
        out.append({
            "id": slot.id,
            "start_bar": slot.start_bar,
            "end_bar": slot.start_bar + slot.bars,
            "t0": round(slot.start_bar * bar_s, 2),
            "t1": round((slot.start_bar + slot.bars) * bar_s, 2),
            "title": b.title if b else "",
            "mood": (b.description if b else "")[:200],
            "motion": (b.motion if b else "")[:160],
            "transition": slot.transition_in,
        })
    return out


def _common_vars(ctx, spec: DemoSpec, music_prompt: str) -> dict:
    return {
        "spec": spec,
        "music_prompt": music_prompt.strip(),
        "sections": sections(spec),
        "library": library_reference(),
        "max_onset_ms": ctx.cfg.audio.max_onset_err_ms,
        "min_realtime": ctx.cfg.audio.min_realtime_factor,
    }


def _system() -> dict:
    return {"role": "system", "content": (
        "You are a demoscene musician. You write music as GLSL ES 3.00 audio shaders that a realtime "
        "player evaluates for every audio sample on the GPU. You answer ONLY with the requested envelope: "
        "one ```json block and one ```glsl block.")}


def _composer(ctx):
    """Ruolo `composer` (in demo.yaml eredita dall'orchestrator); se la config non lo ha, orchestrator."""
    if getattr(ctx, "fake", False) or "composer" in ctx.cfg.roles:
        return ctx.client("composer")
    return ctx.client("orchestrator")


def _ask(ctx, user: str, step: str) -> str:
    try:
        return chat_with_room(_composer(ctx), [_system(), {"role": "user", "content": user}], step=step).content
    except LLMTruncated as e:  # troncata anche col doppio dei token: la revisione lo saprà
        return e.response.content


# ---------------------------------------------------------------- ascolto
def music_payload(spec: DemoSpec, src: str) -> dict:
    """Payload per ascoltare la musica: una scena nera lunga quanto la demo, più l'audio.

    `#line 1 3` fa riportare gli errori di compilazione con le righe del codice del compositore."""
    bpb, bpm = spec.timeline.beats_per_bar, spec.timeline.bpm
    bars = max(s.start_bar + s.bars for s in spec.timeline.scenes)
    return {
        "format": "demogen/1",
        "meta": {"title": f"{spec.title}:music", "duration_s": bars * bpb * 60.0 / bpm, "loop": spec.loop,
                 "bpm": bpm, "beats_per_bar": bpb},
        "timeline": {"bpm": bpm, "beats_per_bar": bpb, "scenes": [
            {"id": "m", "start_bar": 0, "bars": bars, "transition_in": "cut", "transition_bars": 0}]},
        "common": "",
        "scenes": {"m": SILENT_SCENE},
        "render": {"profile": "modern"},
        "post": {},
        "quality": {"min_scale": 0.25, "target_fps": 60},
        "audio": treeshake(src, LIB) + f"\n#line 1 {SRC_MUSIC}\n" + src,
    }


def compile_errors(errors: list[str]) -> list[str]:
    """Errori del codice del compositore come `line N: messaggio` (le righe sono le sue)."""
    out = []
    for e in errors:
        for line in error_log(e).splitlines():
            m = _ERR.search(line)
            if m and int(m.group(1)) == SRC_MUSIC:
                out.append(f"line {m.group(2)}: {m.group(3).strip()}")
    if not out:
        out = [error_log(e).strip()[:600] for e in errors]
    return out[:30]


def analyze_audio(harness, duration_s: float, bpm: float, beats_per_bar: int) -> tuple[dict, np.ndarray, int]:
    """Calcola i primi ≤ 30 s dell'audio del payload caricato e ne misura volume, picco, colpi
    rispetto al beat, battute mute, NaN e velocità di calcolo. → (metriche, stereo (N,2), sr)."""
    dur = max(1.0, min(duration_s, ANALYSIS_MAX_S))
    blocks = math.ceil(dur * 44100 / AUDIO_BLOCK_SAMPLES) + 1
    x, sr, ms = harness.render_audio_array(0.0, blocks)
    rendered_s = len(x) / 2 / sr
    x = x[: int(dur * sr) * 2]
    finite = np.isfinite(x)
    nan_ratio = float(1.0 - finite.mean()) if len(x) else 0.0
    xs = np.where(finite, x, 0.0).astype(np.float64)
    m = audio_metrics(xs, sr, bpm, channels=2)
    m["onsets_s"] = m["onsets_s"][:64]  # il file resta piccolo
    mono = to_mono(xs, 2)
    bar_n = max(1, int(60.0 * beats_per_bar / bpm * sr))
    bars = [mono[i:i + bar_n] for i in range(0, len(mono) - bar_n + 1, bar_n)] or [mono]
    silent = sum(1 for b in bars if float(np.sqrt(np.mean(b ** 2))) < 0.005)
    m.update(
        nan_ratio=nan_ratio,
        render_ms=round(ms, 2),
        realtime_factor=round(rendered_s / (ms / 1000.0), 1) if ms > 0 else None,
        analyzed_s=round(dur, 2),
        silent_bar_ratio=round(silent / len(bars), 3),
    )
    return m, xs[: len(xs) // 2 * 2].reshape(-1, 2), sr


def music_gates(m: dict, cfg) -> list[Issue]:
    """Bloccanti: NaN, muta, troppo pesante. Avvisi: clip, colpi fuori dal beat, troppe battute mute."""
    issues: list[Issue] = []

    def add(sev: str, desc: str, fix: str) -> None:
        issues.append(Issue(severity=sev, description=desc, suggested_fix=fix))  # type: ignore[arg-type]

    if m.get("nan_ratio", 0.0) > 0:
        add("blocker", f"NaN/Inf in the audio ({m['nan_ratio']:.4f} of the samples)",
            "no division by ~0, no pow with a negative base, no log of values <= 0")
    if m.get("rms", 0.0) < cfg.audio.min_rms:
        add("blocker", f"music silent or nearly silent (rms {m.get('rms', 0.0):.4f}, minimum {cfg.audio.min_rms})",
            "the signal must reach o.x and o.y; check envelopes and timing (t is in seconds from the start)")
    elif m.get("silent_bar_ratio", 0.0) > 0.5:
        add("major", f"more than half of the bars are silent ({m['silent_bar_ratio']:.0%})",
            "fill the sections: at least a continuous bass or pad between one hit and the next")
    rf = m.get("realtime_factor")
    if rf is not None and rf < cfg.audio.min_realtime_factor:
        add("blocker", f"too heavy to compute: {rf:.1f}x realtime "
            f"(minimum {cfg.audio.min_realtime_factor:g}x)",
            "fewer voices and operations per sample, no long loops: this code runs ~44100 times per second")
    return issues + run_gates({"audio": m}, cfg)  # clip e colpi sul beat (major)


def listen(ctx, harness, spec: DemoSpec, src: str) -> tuple[dict, list[Issue], np.ndarray | None, int]:
    res = harness.load(music_payload(spec, src))
    if not res["ok"]:
        errs = compile_errors(res["errors"])
        issue = Issue(severity="blocker", description="the music does not compile: " + "; ".join(errs[:6]),
                      suggested_fix="fix the errors listed (line numbers refer to your code)")
        return {"compiled": False, "errors": errs}, [issue], None, 0
    m, stereo, sr = analyze_audio(harness, spec.duration_s, spec.timeline.bpm, spec.timeline.beats_per_bar)
    m["compiled"] = True
    return m, music_gates(m, ctx.cfg), stereo, sr


# ---------------------------------------------------------------- ciclo
def _issue_lines(issues: list) -> str:
    out = []
    for i in issues:
        d = i.model_dump() if hasattr(i, "model_dump") else i
        out.append(f"[{d['severity']}] {d['description']} -> {d.get('suggested_fix', '')}")
    return "\n".join(out) or "-"


def select_music(adir: Path) -> str | None:
    """La versione più recente senza problemi bloccanti (None: nessuna utilizzabile)."""
    for v in sorted(list_versions(adir), reverse=True):
        p = adir / f"v{v}.issues.json"
        if p.exists() and not any(i.get("severity") == "blocker" for i in json.loads(p.read_text(encoding="utf-8"))):
            return f"v{v}"
    return None


def best_music_src(ctx) -> str:
    p = audio_dir(ctx) / "best.json"
    if not p.exists():
        return ""
    ver = (json.loads(p.read_text(encoding="utf-8")) or {}).get("version")
    src_path = audio_dir(ctx) / f"{ver}.glsl"
    return src_path.read_text(encoding="utf-8") if ver and src_path.exists() else ""


def run_music(ctx, harness, spec: DemoSpec, music_prompt: str = "") -> str | None:
    """Compone, ascolta e (se serve) rivede la musica. Ritorna la versione scelta o None."""
    adir = audio_dir(ctx)
    adir.mkdir(parents=True, exist_ok=True)
    common = _common_vars(ctx, spec, music_prompt)
    src: str | None = None
    issues: list = []
    metrics: dict = {}
    parent: int | None = None
    for _ in range(ctx.cfg.budget.max_iterations_per_scene):
        version = next_version(adir)
        if src is None:
            progress.emit("music", phase="compose", version=version,
                          detail=("from your prompt: " + music_prompt[:60]) if music_prompt else "from the demo prompt")
            content = _ask(ctx, P.render("composer_music.md.j2", **common), "music")
        else:
            detail = f"v{parent} → v{version}" if parent else f"v{version}: new take (the last answer had no code)"
            progress.emit("music", phase="revise", version=version, detail=detail)
            user = P.render("composer_revise.md.j2", **common, current_src=src, issues_text=_issue_lines(issues),
                            metrics_text=_metrics_text(metrics))
            content = _ask(ctx, user, "music_revise")
        meta: dict = {"parent": parent, "prompt": music_prompt}
        try:
            env = parse_envelope(content)
            new_src = env.glsl()
            try:  # le note sono facoltative: un JSON rotto non butta via il codice
                meta |= (env.json() or {}) if env.json_text else {}
            except ValueError:
                pass
        except EnvelopeError as e:
            issues = [Issue(severity="blocker", description=f"response without a valid ```glsl block: {e}",
                            suggested_fix="answer with one ```json block and one ```glsl block")]
            (adir / f"v{version}.glsl").write_text("", encoding="utf-8")
            (adir / f"v{version}.issues.json").write_text(json.dumps([i.model_dump() for i in issues], indent=1),
                                                          encoding="utf-8")
            src = src or ""  # la revisione riparte dall'ultimo codice vero (o da zero), con l'errore come nota
            continue  # parent resta l'ultima versione con codice: quella vuota non è un genitore
        (adir / f"v{version}.glsl").write_text(new_src, encoding="utf-8")
        (adir / f"v{version}.meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
        progress.emit("music", phase="listen", version=version,
                      detail="compile, render the samples, rhythm and loudness")
        metrics, issues, stereo, sr = listen(ctx, harness, spec, new_src)
        (adir / f"v{version}.metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
        (adir / f"v{version}.issues.json").write_text(json.dumps([i.model_dump() for i in issues], indent=1),
                                                      encoding="utf-8")
        if stereo is not None:
            spectrogram_png(stereo, sr, spec.timeline.bpm, adir / f"v{version}.spectrogram.png")
        blockers = [i.description for i in issues if i.severity == "blocker"]
        progress.emit("music.result", version=version, ok=not blockers,
                      issues=blockers + [i.description for i in issues if i.severity == "major"],
                      rms=metrics.get("rms"), realtime=metrics.get("realtime_factor"))
        for b in blockers:
            print(f"[music] v{version}: {b}")
        if not blockers:
            break
        src, parent = new_src, version
    best = select_music(adir)
    (adir / "best.json").write_text(json.dumps({"version": best}), encoding="utf-8")
    if best is None:
        print("[music] no usable version: the demo will be silent (details in audio/vN.issues.json)")
    progress.emit("music.done", best=best)
    return best


def _metrics_text(m: dict) -> str:
    if not m:
        return "-"
    if not m.get("compiled", True):
        return "did not compile"
    obe = m.get("onset_vs_beat") or {}
    return (f"rms {m.get('rms', 0):.3f}, peak {m.get('peak', 0):.3f}, silent bars {m.get('silent_bar_ratio', 0):.0%}, "
            f"hits on beat: mean error {obe.get('mean_abs_err_ms')} ms over {obe.get('n_strong')} strong onsets, "
            f"render speed {m.get('realtime_factor')}x realtime")
