"""Step della pipeline S0–S9 (audio S8 è Fase 2, saltato qui).

Regole di coerenza (review #15-#20):
- ciò che si compila in S4/S5 è ciò che S9 spedisce: stesso math per versione
  (`math_for`), common ricalcolato dalla sorgente corrente, profilo per scena;
- ogni step riusa il suo artefatto su disco se esiste (resume senza nuove chiamate LLM);
- le sorgenti compilate portano direttive `#line` per pezzo, così gli errori del
  compilatore si rimappano sulle righe della scena (sorgente 2) o dello style (sorgente 1).
"""

from __future__ import annotations

import asyncio
import io
import json
import math as _math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import ValidationError

from ..browser.harness import Harness
from ..browser.perf_lane import perf_lane
from ..critic.flash import analyze_flash
from ..critic.gates import is_software_renderer, run_gates
from ..critic.metrics_perf import perf_profile
from ..critic.metrics_video import video_metrics
from ..critic.sheets import burst_sheet, contact_sheet, diff_heatmap
from ..glsl.treeshake import load_library, treeshake
from ..llm.budget import BudgetExceeded
from ..llm.client import LLMTruncated, achat_with_room, chat_with_room
from ..llm.envelope import EnvelopeError, parse_envelope
from ..llm.structured import chat_structured
from ..project.store import slugify
from ..spec.models import DemoSpec, SceneBrief, ShaderSubmission
from . import prompts as P
from .selection import list_versions, load_issues, next_version, select_best

LIB = load_library(Path(__file__).resolve().parents[1] / "glsl" / "lib")

MAX_DURATION_S = 120.0
# numeri di sorgente nelle direttive #line: gli errori ANGLE escono come "ERROR: <src>:<riga>: ..."
SRC_STYLE = 1
SRC_SCENE = 2
MAX_FIXER_ERRORS = 30

_ERR_LINE = re.compile(r"ERROR:\s*(\d+):(\d+):\s*(.*)")


class PipelineError(RuntimeError):
    """Errore della pipeline con messaggio per l'utente (exit code != 0)."""


# ---------------------------------------------------------------- sorgenti
def scene_profile(spec: DemoSpec, scene_id: str) -> str:
    sc = next((s for s in spec.scenes if s.id == scene_id), None)
    return (sc.profile if sc and sc.profile else None) or spec.profile


def style_src(ctx) -> str:
    """Lo style corrente da disco (il fixer può correggerlo durante S4)."""
    return ctx.project.read("style.glsl") if ctx.project.exists("style.glsl") else ""


def math_for(ctx, scene_id: str, version: int) -> str:
    """GLSL dell'oracolo valido per `version`: unione delle funzioni accepted di v1..version.

    Una revisione eredita le funzioni verificate delle versioni precedenti (il suo codice
    le usa ancora); un id ridefinito in una versione successiva sostituisce il precedente.
    Usata da S4, S5 e S9: quello che si compila è quello che si spedisce.
    """
    sdir = ctx.project.path / "scenes" / scene_id
    funcs: dict[str, str] = {}
    for k in range(1, version + 1):
        mj = sdir / f"v{k}.math.json"
        if mj.exists():
            data = json.loads(mj.read_text(encoding="utf-8"))
            for r in data.get("results", []):
                if r.get("status") == "accepted" and r.get("glsl"):
                    funcs[r["id"]] = r["glsl"]
        elif (sdir / f"v{k}.math.glsl").exists():  # progetti vecchi senza math.json
            funcs[f"__v{k}"] = (sdir / f"v{k}.math.glsl").read_text(encoding="utf-8")
    return "\n".join(funcs.values())


def compile_sources(ctx, scene_id: str, version: int, src: str, style: str) -> tuple[str, str]:
    """(common, scena) da compilare per una scena, con #line per la rimappatura degli errori."""
    math = math_for(ctx, scene_id, version)
    common = treeshake(math + "\n" + src + "\n" + style, LIB) + f"\n#line 1 {SRC_STYLE}\n" + style
    scene = (math + "\n" if math else "") + f"#line 1 {SRC_SCENE}\n" + src
    return common, scene


def mono_payload(spec: DemoSpec, scene_id: str, scene_src: str, common: str) -> dict:
    bpm = spec.timeline.bpm
    slot = next(s for s in spec.timeline.scenes if s.id == scene_id)
    profile = scene_profile(spec, scene_id)
    return {
        "format": "demogen/1",
        "meta": {
            "title": f"{spec.title}:{scene_id}",
            "duration_s": slot.bars * spec.timeline.beats_per_bar * 60 / bpm,
            "loop": spec.loop,
            "bpm": bpm,
            "beats_per_bar": spec.timeline.beats_per_bar,
        },
        "timeline": {
            "bpm": bpm,
            "beats_per_bar": spec.timeline.beats_per_bar,
            "scenes": [
                {
                    "id": scene_id,
                    "start_bar": 0,
                    "bars": slot.bars,
                    "transition_in": "cut",
                    "transition_bars": 0,
                }
            ],
        },
        "common": common,
        "scenes": {scene_id: scene_src},
        "render": {"profile": profile, "overrides": {scene_id: profile}},
        "text": spec.text,
        "post": {},
        "quality": {"min_scale": 0.5, "target_fps": 60},
    }


@dataclass
class CompileErrors:
    scene: list[str] = field(default_factory=list)  # "riga N: messaggio" (righe della scena)
    style: list[str] = field(default_factory=list)  # righe di style.glsl
    other: list[str] = field(default_factory=list)  # header/lib/math/link

    def for_fixer(self, which: str) -> str:
        errs = getattr(self, which) or self.other
        return "\n".join(errs[:MAX_FIXER_ERRORS]) or "-"


def parse_compile_errors(errors: list[str]) -> CompileErrors:
    """Smista gli errori ANGLE per sorgente (#line) e toglie il sorgente completo dal messaggio."""
    out = CompileErrors()
    for e in errors:
        log = str(e).split("--- sorgente ---", 1)[0]
        matched = False
        for line in log.splitlines():
            m = _ERR_LINE.search(line)
            if not m:
                continue
            matched = True
            src_no, ln, msg = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            item = f"riga {ln}: {msg}"
            if src_no == SRC_SCENE:
                out.scene.append(item)
            elif src_no == SRC_STYLE:
                out.style.append(item)
            else:
                out.other.append(f"(header/libreria/math) {item}")
        if not matched:
            out.other.append(log.strip()[:1000])
    return out


# ---------------------------------------------------------------- S0 brief
def timeline_duration(spec: DemoSpec) -> float:
    tl = spec.timeline
    end = max((s.start_bar + s.bars for s in tl.scenes), default=0.0)
    return end * tl.beats_per_bar * 60 / tl.bpm


def truncate_timeline(spec: DemoSpec, max_s: float = MAX_DURATION_S) -> None:
    """Tronca la timeline a `max_s` (via gli slot oltre il limite, l'ultimo accorciato)."""
    tl = spec.timeline
    max_bars = _math.floor(max_s * tl.bpm / 60 / tl.beats_per_bar)
    if timeline_duration(spec) <= max_s:
        return
    kept = []
    for slot in tl.scenes:
        if slot.start_bar >= max_bars:
            continue
        slot.bars = min(slot.bars, max_bars - slot.start_bar)
        slot.transition_bars = min(slot.transition_bars, slot.bars)
        kept.append(slot)
    if not kept:
        raise PipelineError(f"S0: timeline vuota dopo il troncamento a {max_s} s")
    tl.scenes = kept
    ids = {s.id for s in kept}
    spec.scenes = [s for s in spec.scenes if s.id in ids]


def apply_request(spec: DemoSpec, prompt: str, bpm: float, profile: str, loop: bool) -> DemoSpec:
    """I flag della CLI sono autoritativi: vincono sulle scelte dell'LLM."""
    if profile not in ("modern", "retro"):
        raise PipelineError(f"profilo non valido: {profile!r} (modern | retro)")
    spec.prompt = prompt
    spec.timeline.bpm = float(bpm)
    spec.profile = profile  # type: ignore[assignment]
    spec.loop = bool(loop)
    truncate_timeline(spec)
    spec.duration_s = timeline_duration(spec)
    return DemoSpec.model_validate(spec.model_dump())  # rivalida (slot/scene coerenti)


def s0_brief(ctx, prompt: str, duration_s: float, bpm: float, profile: str, loop: bool) -> DemoSpec:
    caps = ctx.caps("orchestrator")
    user = P.render(
        "orchestrator_brief.md.j2",
        prompt=prompt,
        duration_s=duration_s,
        bpm=bpm,
        profile=profile,
        loop=loop,
        schema_name="DemoSpec",
    )
    msgs = [
        {"role": "system", "content": P.system_prompt(bpm)},
        {"role": "user", "content": user},
    ]
    spec = chat_structured(ctx.client("orchestrator"), msgs, DemoSpec, step="brief", caps=caps)
    spec = apply_request(spec, prompt, bpm, profile, loop)
    ctx.project.write("spec.json", spec.model_dump_json(indent=1))
    return spec


# ---------------------------------------------------------------- S1 style
def s1_style(ctx, spec: DemoSpec) -> str:
    resp = chat_with_room(
        ctx.client("orchestrator"),
        [
            {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
            {
                "role": "user",
                "content": P.render(
                    "orchestrator_style.md.j2",
                    title=spec.title,
                    art_direction=spec.art_direction,
                    palette_hint=", ".join(spec.palette_hint) or "-",
                    profile=spec.profile,
                    bpm=spec.timeline.bpm,
                ),
            },
        ],
        step="style",
    )
    env = parse_envelope(resp.content)
    post = env.json() if env.json_text else {}
    try:
        style = env.glsl()
    except EnvelopeError as e:
        raise PipelineError(f"S1: nessun blocco glsl nella risposta: {resp.content[:300]}") from e
    ctx.project.write("post.json", json.dumps(post))
    ctx.project.write("style.glsl", style)
    return style


# ---------------------------------------------------------------- S2 draft
def _scene_prompt(ctx, spec: DemoSpec, scene: SceneBrief) -> list[dict]:
    profile = scene.profile or spec.profile
    tmpl = "orchestrator_scene_retro.md.j2" if profile == "retro" else "orchestrator_scene_modern.md.j2"
    prof = ctx.cfg.realtime.profiles.get(profile)
    user = P.render(
        tmpl,
        spec=spec,
        scene=scene,
        profile=profile,
        res=prof["res"] if prof else [1920, 1080],
        budget_p95=prof["p95"] if prof else 6.0,
        budget_mean=prof["mean"] if prof else 4.0,
    )
    return [
        {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
        {"role": "user", "content": user},
    ]


def _bad_envelope_feedback(content: str, err: Exception) -> list[dict]:
    return [
        {"role": "assistant", "content": content},
        {
            "role": "user",
            "content": f"La risposta non è un envelope valido ({err}). Rispondi con un blocco ```json "
            "(metadati ShaderSubmission) e un blocco ```glsl con il corpo completo di mainImage.",
        },
    ]


async def s2_draft(ctx, spec: DemoSpec, style: str) -> dict[str, str]:
    """Bozza delle scene in parallelo (asyncio, llm_concurrency).

    Ogni scena è isolata: un envelope malformato viene ritentato una volta con l'errore,
    e i draft già arrivati restano su disco (v1.glsl è scritto per ultimo, dopo meta e
    math, ed è il marcatore di "scena fatta" per il resume).
    """

    async def one(scene: SceneBrief) -> None:
        msgs = _scene_prompt(ctx, spec, scene)
        last_err: Exception | None = None
        for _attempt in range(2):
            content = ""
            try:
                resp = await achat_with_room(ctx.client("orchestrator"), msgs, step=f"draft:{scene.id}")
                content = resp.content
                env = parse_envelope(content)
                meta = ShaderSubmission.model_validate(env.json())
                src = env.glsl()
                break
            except LLMTruncated as e:  # troncata anche col doppio dei token
                last_err, content = e, e.response.content
            except (EnvelopeError, ValidationError) as e:
                last_err = e
            msgs = msgs + _bad_envelope_feedback(content, last_err)
        else:
            raise PipelineError(f"S2: draft della scena {scene.id} non valido dopo 2 tentativi: {last_err}")
        ctx.project.write(f"scenes/{scene.id}/v1.meta.json", json.dumps(meta.model_dump(), indent=1))
        if meta.math_requests:
            # verifica in subprocess: fuori dall'event loop, le altre scene continuano
            await asyncio.to_thread(run_oracle_for, ctx, scene.id, 1, meta.math_requests)
        ctx.project.write(f"scenes/{scene.id}/v1.glsl", src)

    todo = [s for s in spec.scenes if not ctx.project.exists(f"scenes/{s.id}/v1.glsl")]
    sem = asyncio.Semaphore(ctx.cfg.budget.llm_concurrency)

    async def bounded(scene: SceneBrief):
        async with sem:
            return await one(scene)

    results = await asyncio.gather(*(bounded(s) for s in todo), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    for e in errors:
        if isinstance(e, BudgetExceeded):
            raise e
    if errors:
        raise PipelineError("S2: " + "; ".join(str(e) for e in errors))
    return {s.id: ctx.project.read(f"scenes/{s.id}/v1.glsl") for s in spec.scenes}


def run_oracle_for(ctx, scene_id: str, version: int, requests) -> str:
    """Fase 6: verifica i math_requests con l'oracolo e salva v{version}.math.{json,glsl}.

    Ritorna il GLSL delle richieste accepted (vuoto se nessuna)."""
    from ..math import run_math_oracle

    oracle = run_math_oracle(requests, reserved_names=frozenset(LIB))
    ctx.project.write(
        f"scenes/{scene_id}/v{version}.math.json",
        json.dumps(
            {"results": [r.__dict__ | {"verify": r.verify.__dict__ if r.verify else None}
                         for r in oracle.results]},
            indent=1, default=str,
        ),
    )
    if oracle.math_glsl:
        ctx.project.write(f"scenes/{scene_id}/v{version}.math.glsl", oracle.math_glsl)
    for r in oracle.rejected:
        print(f"[math] {scene_id}/{r.id} rifiutato: {r.reason}")
    return oracle.math_glsl


# ---------------------------------------------------------------- S4 compile + fixer
def _run_fixer(ctx, spec: DemoSpec, scene_id: str, target: str, src: str, errors: str) -> str | None:
    fix_user = P.render("fixer.md.j2", src=src, errors=errors, target=target)
    resp = chat_with_room(
        ctx.client("fixer"),
        [
            {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
            {"role": "user", "content": fix_user},
        ],
        step=f"fixer:{scene_id}" + (":style" if target == "style" else ""),
    )
    try:
        return parse_envelope(resp.content).glsl()
    except EnvelopeError:
        return None


def s4_compile(ctx, harness: Harness, spec: DemoSpec, scene_id: str, src: str,
               version: int) -> tuple[bool, str, list[str]]:
    """Compila la scena nell'harness; se fallisce, loop col fixer (max_fix_attempts).

    Gli errori arrivano al fixer con le righe della scena (o dello style, che il fixer
    può correggere: la versione precedente resta in style.prev.glsl).
    """
    cur = src
    errors: list[str] = []
    for attempt in range(ctx.cfg.budget.max_fix_attempts + 1):
        style = style_src(ctx)
        common, scene = compile_sources(ctx, scene_id, version, cur, style)
        res = harness.load(mono_payload(spec, scene_id, scene, common))
        if res["ok"]:
            ctx.project.write(f"scenes/{scene_id}/v{version}.glsl", cur)
            ctx.project.resolve(f"scenes/{scene_id}/v{version}.compile_errors.json").unlink(missing_ok=True)
            return True, cur, []
        errors = res["errors"]
        if attempt >= ctx.cfg.budget.max_fix_attempts:
            break
        ce = parse_compile_errors(errors)
        if ce.style and not ce.scene:
            fixed = _run_fixer(ctx, spec, scene_id, "style", style, ce.for_fixer("style"))
            if not fixed:
                break
            ctx.project.write("style.prev.glsl", style)
            ctx.project.write("style.glsl", fixed)
        else:
            fixed = _run_fixer(ctx, spec, scene_id, "scene", cur, ce.for_fixer("scene"))
            if not fixed:
                break
            cur = fixed
    ctx.project.write(f"scenes/{scene_id}/v{version}.glsl", cur)
    ctx.project.write(
        f"scenes/{scene_id}/v{version}.compile_errors.json",
        json.dumps([str(e).split("--- sorgente ---", 1)[0] for e in errors], indent=1),
    )
    return False, cur, errors


# ---------------------------------------------------------------- S5 probe
def probe_flash(ctx, harness: Harness, dur: float):
    """Analisi flash WCAG sull'intera durata (scena in S5, demo intera con le transizioni in S9)."""
    sf = ctx.cfg.safety
    cells = harness.cell_sequence(0.0, dur, sf.flash_fps, 128, 72, grid=sf.flash_grid)
    return analyze_flash(cells, fps=sf.flash_fps, flash_max_per_s=sf.flash_max_per_s,
                         red_flash=sf.red_flash, area_frac=sf.flash_area_frac)


def probe_perf(ctx, harness: Harness, times: list[float], profile: str, renderer: str):
    """Profilo perf + pavimento (qualità minima).

    Su GPU hardware si misura alla risoluzione del budget del profilo (i ms a 480×270
    non dicono nulla del 1080p); su renderer software (SwiftShader) alla risoluzione di
    preview: il gate li tratta comunque come informativi."""
    if is_software_renderer(renderer):
        rw, rh = ctx.cfg.preview.width, ctx.cfg.preview.height
    else:
        budget = ctx.cfg.realtime.profiles.get(profile, ctx.cfg.realtime.profiles["modern"])
        rw, rh = budget.get("res", [ctx.cfg.preview.width, ctx.cfg.preview.height])
    with perf_lane():
        prof = harness.profile(times, rw, rh, repeats=3)
        floor = harness.profile(times, rw, rh, repeats=2, floor=True)
    return prof, floor, (rw, rh)


def capture_bursts(ctx, harness: Harness, dur: float) -> list[list[bytes]]:
    """`preview.bursts` raffiche di `preview.burst_len` frame CONSECUTIVI a `preview.fps`."""
    pv = ctx.cfg.preview
    out = []
    span = (pv.burst_len - 1) / pv.fps
    for b in range(pv.bursts):
        t0 = max(0.0, min(dur - span, dur * (b + 0.5) / pv.bursts - span / 2))
        out.append(harness.capture([round(t0 + k / pv.fps, 5) for k in range(pv.burst_len)],
                                   pv.width, pv.height))
    return out


def capture_seam(ctx, harness: Harness, dur: float) -> tuple[np.ndarray, np.ndarray]:
    """Frame a cavallo della cucitura del loop: t = dur − 1/fps e t = 0."""
    pv = ctx.cfg.preview
    a, b = harness.capture([max(0.0, dur - 1.0 / pv.fps), 0.0], pv.width, pv.height)
    return _np_frame(a), _np_frame(b)


def _np_frame(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def _np_bursts(bursts: list[list[bytes]]) -> list[list[np.ndarray]]:
    return [[_np_frame(p) for p in burst] for burst in bursts]


def write_burst_sheets(bursts: list[list[bytes]], out_dir: Path) -> None:
    """burst.png (raffiche di frame consecutivi, una riga per raffica) e diff.png (prima raffica)."""
    rows = [[Image.open(io.BytesIO(p)).convert("RGB") for p in burst] for burst in bursts if burst]
    if not rows:
        return
    burst_sheet(rows, out_dir / "burst.png")
    if len(rows[0]) > 1:
        diff_heatmap([np.asarray(im) for im in rows[0]], out_dir / "diff.png")


def s5_probe(ctx, harness: Harness, spec: DemoSpec, scene_id: str, src: str, version: int) -> dict:
    """Cattura keyframe + stats + perf + flash per la scena; gate; salva vN.probe/.

    Riusa il probe su disco se esiste già (resume)."""
    import gzip

    pdir = ctx.project.path / "scenes" / scene_id / f"v{version}.probe"
    issues_rel = f"scenes/{scene_id}/v{version}.issues.json"
    if (pdir / "metrics.json").exists() and ctx.project.exists(issues_rel):
        return json.loads((pdir / "metrics.json").read_text(encoding="utf-8"))

    bpm = spec.timeline.bpm
    slot = next(s for s in spec.timeline.scenes if s.id == scene_id)
    dur = slot.bars * spec.timeline.beats_per_bar * 60 / bpm
    common, scene = compile_sources(ctx, scene_id, version, src, style_src(ctx))
    payload = mono_payload(spec, scene_id, scene, common)
    res = harness.load(payload)
    if not res["ok"]:
        raise PipelineError(f"S5: la scena {scene_id} v{version} non compila più:\n"
                            + "\n".join(res["errors"])[:2000])
    pdir.mkdir(parents=True, exist_ok=True)

    pw, ph = ctx.cfg.preview.width, ctx.cfg.preview.height
    times = [round(dur * (i + 0.5) / ctx.cfg.preview.keyframes, 3)
             for i in range(ctx.cfg.preview.keyframes)]
    pngs = harness.capture(times, pw, ph)
    stats = harness.scene_stats(times, pw, ph)
    info = harness.info()
    prof_name = scene_profile(spec, scene_id)
    prof, floor, (rw, rh) = probe_perf(ctx, harness, times[:6], prof_name, str(info["renderer"]))
    fl = probe_flash(ctx, harness, dur)
    bursts = capture_bursts(ctx, harness, dur)
    seam = capture_seam(ctx, harness, dur) if spec.loop and len(spec.timeline.scenes) == 1 else None

    for i, p in enumerate(pngs):
        (pdir / f"key_{i:02d}_t{times[i]}s.png").write_bytes(p)

    frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
    vm = video_metrics(frames, stats, loop=spec.loop, bursts=_np_bursts(bursts), seam=seam)
    pf = perf_profile(
        {float(k): v for k, v in prof["samples"].items()},
        scene_id=scene_id,
        profile=prof_name,
        resolution=(rw, rh),
        method=str(prof["method"]),
        gpu=str(info["renderer"]),
        target_fps=ctx.cfg.realtime.target_fps,
        floor_samples={float(k): v for k, v in floor["samples"].items()},
    )
    raw = json.dumps(payload).encode()
    metrics = {
        "video": vm,
        "perf": pf.model_dump(),
        "flash": fl.model_dump(),
        "sizes": {"payload_gzip_bytes": len(gzip.compress(raw, 9))},
        "gpu": info["renderer"],
    }
    issues = run_gates(metrics, ctx.cfg)
    (pdir / "issues.json").write_text(
        json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8"
    )
    imgs = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    contact_sheet(imgs, times, pdir / "contact.png")
    write_burst_sheets(bursts, pdir)
    # issues anche a livello di versione (per selection); metrics.json per ultimo = probe completo
    ctx.project.write(issues_rel, json.dumps([i.model_dump() for i in issues], indent=1))
    (pdir / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    return metrics


# ---------------------------------------------------------------- S6 critique
def s6_critique(ctx, spec: DemoSpec, scene: SceneBrief, version: int) -> dict:
    from ..critic.critic import critique
    from ..critic.models import CriticReport

    crit_rel = f"scenes/{scene.id}/v{version}.critique.json"
    if ctx.project.exists(crit_rel):  # resume: niente nuova chiamata
        return CriticReport.model_validate_json(ctx.project.read(crit_rel)).model_dump()

    pdir = ctx.project.path / "scenes" / scene.id / f"v{version}.probe"
    metrics = json.loads((pdir / "metrics.json").read_text(encoding="utf-8"))
    images = [pdir / "contact.png", pdir / "burst.png", pdir / "diff.png"]
    images = [p for p in images if p.exists()]
    user = P.render(
        "critic_scene.md.j2",
        scene=scene,
        metrics_json=json.dumps(metrics, default=str)[:4000],
    )
    if ctx.fake:
        # senza API reali: il fake risponde direttamente il CriticReport JSON
        resp = ctx.client("critic").chat(
            [{"role": "user", "content": user + "\n" + json.dumps(metrics, default=str)}],
            step=f"critique:{scene.id}",
        )
        report = CriticReport.model_validate_json(resp.content)
    else:
        report = critique(
            ctx.cfg,
            "critic",
            prompt=user,
            images=images,
            metrics_json=json.dumps(metrics, default=str),
            log_dir=ctx.project.path / "llm_calls",
            client=ctx.client("critic"),
            budget=ctx.budget,
        )
    ctx.project.write(crit_rel, report.model_dump_json(indent=1))
    return report.model_dump()


# ---------------------------------------------------------------- S7 revise
def history_text(ctx, scene_id: str) -> str:
    """Storia delle versioni per il prompt di revisione (verdetti, score, compilazioni fallite)."""
    sdir = ctx.project.path / "scenes" / scene_id
    lines = []
    for v in list_versions(sdir):
        ce = sdir / f"v{v}.compile_errors.json"
        if ce.exists():
            errs = json.loads(ce.read_text(encoding="utf-8"))
            first = parse_compile_errors(errs)
            msg = "; ".join((first.scene or first.style or first.other)[:3]) or "errore di compilazione"
            lines.append(f"- v{v}: NON COMPILAVA ({msg[:300]}) — non ripetere lo stesso errore")
            continue
        cp = sdir / f"v{v}.critique.json"
        if cp.exists():
            c = json.loads(cp.read_text(encoding="utf-8"))
            blk = sum(1 for i in load_issues(sdir, v) if i.severity == "blocker")
            lines.append(f"- v{v}: verdict={c.get('verdict')} scores={c.get('scores')} blocker={blk}")
    return "\n".join(lines) or "-"


def math_rejections(ctx, scene_id: str, version: int) -> str:
    """Richieste dell'oracolo rifiutate per la versione (con il motivo), da rimandare all'LLM."""
    p = ctx.project.path / "scenes" / scene_id / f"v{version}.math.json"
    if not p.exists():
        return "-"
    rej = [r for r in json.loads(p.read_text(encoding="utf-8")).get("results", []) if r.get("status") != "accepted"]
    return "\n".join(f"- {r.get('id')}: {str(r.get('reason', ''))[:300]}" for r in rej) or "-"


def _version_parent(sdir: Path, v: int) -> int | None:
    mp = sdir / f"v{v}.meta.json"
    if not mp.exists():
        return None
    return json.loads(mp.read_text(encoding="utf-8")).get("parent")


def s7_revise(ctx, harness: Harness, spec: DemoSpec, scene: SceneBrief, version: int, src: str,
              critique: dict, issues: list, *, consumed: set[int] | None = None,
              reuse: bool = True) -> tuple[int, str]:
    """Una iterazione di revisione → nuova versione (numero = massimo esistente + 1).

    Con `reuse`, se una revisione di `version` esiste già su disco (resume) e non è
    ancora stata consumata in questo run, la si riusa senza chiamare l'LLM.
    Ritorna la versione corrente: la nuova se compila, altrimenti quella di partenza.
    """
    sdir = ctx.project.path / "scenes" / scene.id
    consumed = consumed if consumed is not None else set()
    if reuse:
        children = [v for v in list_versions(sdir)
                    if v not in consumed and _version_parent(sdir, v) == version]
        if children:
            v = min(children)
            consumed.add(v)
            if (sdir / f"v{v}.compile_errors.json").exists():
                return version, src
            prev_src = ctx.project.read(f"scenes/{scene.id}/v{v}.glsl")
            ok, fixed, _ = s4_compile(ctx, harness, spec, scene.id, prev_src, v)
            return (v, fixed) if ok else (version, src)

    issues_text = "\n".join(
        f"[{i['severity']}] {i['description']} -> {i.get('suggested_fix', '')}" for i in issues
    ) or "-"
    user = P.render(
        "orchestrator_revise.md.j2",
        scene_id=scene.id,
        version=version,
        current_src=src,
        critique_json=json.dumps(critique, default=str)[:2000],
        issues_text=issues_text,
        history_text=history_text(ctx, scene.id),
        math_rejections=math_rejections(ctx, scene.id, version),
    )
    msgs = [
        {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
        {"role": "user", "content": user},
    ]
    resp = chat_with_room(ctx.client("orchestrator"), msgs, step=f"revise:{scene.id}")
    env = parse_envelope(resp.content)
    new_version = next_version(sdir)
    consumed.add(new_version)
    meta: dict = {"parent": version}
    try:
        new_src = env.glsl()
    except EnvelopeError as e:
        # registra il tentativo fallito: la storia lo mostra alla prossima iterazione
        ctx.project.write(f"scenes/{scene.id}/v{new_version}.meta.json", json.dumps(meta, indent=1))
        ctx.project.write(f"scenes/{scene.id}/v{new_version}.glsl", "")
        ctx.project.write(f"scenes/{scene.id}/v{new_version}.compile_errors.json",
                          json.dumps([f"envelope non valido: {e}"]))
        return version, src
    try:  # Fase 6: il revise può emettere nuovi math_requests
        new_meta = ShaderSubmission.model_validate(env.json())
        meta |= new_meta.model_dump()
        if new_meta.math_requests:
            run_oracle_for(ctx, scene.id, new_version, new_meta.math_requests)
    except (EnvelopeError, ValidationError) as exc:  # il meta è opzionale
        print(f"[math] revise {scene.id}: nessun math_request ({exc})")
    meta["parent"] = version
    ctx.project.write(f"scenes/{scene.id}/v{new_version}.meta.json", json.dumps(meta, indent=1))
    ok, fixed, _errors = s4_compile(ctx, harness, spec, scene.id, new_src, new_version)
    if not ok:
        return version, src  # tieni la vecchia se la nuova non compila
    return new_version, fixed


# ---------------------------------------------------------------- S9 bundle
def s9_bundle(ctx, spec: DemoSpec, post: dict) -> dict:
    from ..bundle.build import build_payload_from_sources, write_bundle

    best_srcs: dict[str, str] = {}
    math_srcs: dict[str, str] = {}
    for scene in spec.scenes:
        best = select_best(ctx.project.path / "scenes" / scene.id)
        v = int(best["version"][1:])
        best_srcs[scene.id] = ctx.project.read(f"scenes/{scene.id}/v{v}.glsl")
        m = math_for(ctx, scene.id, v)
        if m:
            math_srcs[scene.id] = m

    slots = {s.id: s for s in spec.timeline.scenes}
    spec_dict = {
        "name": spec.title,  # titolo leggibile (meta.title, escaped nell'HTML)
        "bpm": spec.timeline.bpm,
        "beats_per_bar": spec.timeline.beats_per_bar,
        "loop": spec.loop,
        "text": spec.text,
        "render": {
            "profile": spec.profile,
            "overrides": {s.id: s.profile for s in spec.scenes if s.profile},
        },
        "post": post,
        "quality": {"min_scale": 0.5, "target_fps": ctx.cfg.realtime.target_fps},
        "scenes": [  # in ordine di timeline, abbinati per id (non per posizione)
            {
                "id": slot.id,
                "start_bar": slot.start_bar,
                "bars": slot.bars,
                "transition_in": slot.transition_in,
                "transition_bars": slot.transition_bars,
            }
            for slot in slots.values()
        ],
    }
    try:
        payload = build_payload_from_sources(
            spec_dict, best_srcs, style_src(ctx), do_minify=True, math_srcs=math_srcs
        )
    except ValueError as e:
        raise PipelineError(f"S9: {e}") from e
    name = slugify(spec.title)  # il titolo viene dall'LLM: mai usarlo crudo come nome file
    sizes = write_bundle(payload, ctx.project.path / "out", name)
    return {"payload": payload, "sizes": sizes, "name": name}
