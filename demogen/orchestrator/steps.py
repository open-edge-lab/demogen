"""Step della pipeline S0–S9 (audio S8 è Fase 2, saltato qui)."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..browser.harness import Harness
from ..browser.perf_lane import perf_lane
from ..critic.flash import analyze_flash
from ..critic.gates import run_gates
from ..critic.metrics_perf import perf_profile
from ..critic.metrics_video import video_metrics
from ..critic.sheets import burst_strip, contact_sheet, diff_heatmap
from ..glsl.treeshake import load_library, treeshake
from ..llm.envelope import parse_envelope
from ..llm.structured import chat_structured
from ..project.store import slugify
from ..spec.models import DemoSpec, SceneBrief, ShaderSubmission
from . import prompts as P
from .selection import select_best

LIB = load_library(Path(__file__).resolve().parents[1] / "glsl" / "lib")


def common_for(spec: DemoSpec, scene_srcs: dict[str, str], style_src: str) -> str:
    """common = libreria tree-shaked (topologica) + style."""
    entry = "\n".join(scene_srcs.values()) + "\n" + style_src
    return treeshake(entry, LIB) + "\n" + style_src


def mono_payload(spec: DemoSpec, scene_id: str, src: str, common: str, bpm: float) -> dict:
    slot = next(s for s in spec.timeline.scenes if s.id == scene_id)
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
        "scenes": {scene_id: src},
        "render": {"profile": spec.profile, "overrides": {scene_id: spec.profile}},
        "text": spec.text,
        "post": {},
        "quality": {"min_scale": 0.5, "target_fps": 60},
    }


# ---------------------------------------------------------------- S0 brief
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
    # coerenze: durata = timeline, max 120 s
    total = sum(s.bars for s in spec.timeline.scenes)
    spec.duration_s = total * spec.timeline.beats_per_bar * 60 / spec.timeline.bpm
    spec.duration_s = min(spec.duration_s, 120.0)
    ctx.project.write("spec.json", spec.model_dump_json(indent=1))
    return spec


# ---------------------------------------------------------------- S1 style
def s1_style(ctx, spec: DemoSpec) -> str:
    resp = ctx.client("orchestrator").chat(
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
    style_src = env.glsl_blocks[0] if env.glsl_blocks else ""
    if not style_src:
        raise ValueError(f"S1: nessuno blocco glsl nella risposta: {resp.content[:300]}")
    ctx.project.write("style.glsl", style_src)
    ctx.project.write("post.json", json.dumps(post))
    return style_src


# ---------------------------------------------------------------- S2 draft
async def s2_draft(ctx, spec: DemoSpec, style_src: str) -> dict[str, str]:
    """Bozza di tutte le scene in parallelo (asyncio, llm_concurrency)."""

    async def one(scene: SceneBrief) -> tuple[str, str, dict]:
        tmpl = "orchestrator_scene_retro.md.j2" if (
            scene.profile or spec.profile
        ) == "retro" else "orchestrator_scene_modern.md.j2"
        prof = ctx.cfg.realtime.profiles.get("retro" if (scene.profile or spec.profile) == "retro" else "modern")
        user = P.render(
            tmpl,
            spec=spec,
            scene=scene,
            profile=scene.profile or spec.profile,
            res=prof["res"] if prof else [1920, 1080],
            budget_p95=prof["p95"] if prof else 6.0,
            budget_mean=prof["mean"] if prof else 4.0,
        )
        msgs = [
            {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
            {"role": "user", "content": user},
        ]
        resp = await ctx.client("orchestrator").achat(msgs, step=f"draft:{scene.id}")
        env = parse_envelope(resp.content)
        meta = ShaderSubmission.model_validate(env.json())
        src = env.glsl_blocks[0]
        # Fase 6: oracolo matematico sui math_requests (verifica in subprocess isolato)
        math_glsl = ""
        if meta.math_requests:
            math_glsl = run_oracle_for(ctx, scene.id, 1, meta.math_requests)
        return scene.id, src, meta.model_dump(), math_glsl

    sem = asyncio.Semaphore(ctx.cfg.budget.llm_concurrency)

    async def bounded(scene: SceneBrief):
        async with sem:
            return await one(scene)

    results = await asyncio.gather(*(bounded(s) for s in spec.scenes))
    srcs: dict[str, str] = {}
    for scene_id, src, meta, _math_glsl in results:
        srcs[scene_id] = src
        ctx.project.write(f"scenes/{scene_id}/v1.glsl", src)
        ctx.project.write(f"scenes/{scene_id}/v1.meta.json", json.dumps(meta, indent=1))
    return srcs


def run_oracle_for(ctx, scene_id: str, version: int, requests) -> str:
    """Fase 6: verifica i math_requests con l'oracolo e salva v{version}.math.{json,glsl}.

    Ritorna il GLSL delle richieste accepted (vuoto se nessuna)."""
    from ..math import run_math_oracle

    oracle = run_math_oracle(requests)
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


def with_math(ctx, scene_id: str, version: int, src: str) -> str:
    """Concatena il math.glsl oracolo (v{version}, fallback v1) davanti allo shader."""
    for v in (version, 1):
        p = ctx.project.path / "scenes" / scene_id / f"v{v}.math.glsl"
        if p.exists():
            return p.read_text(encoding="utf-8") + "\n" + src
    return src


# ---------------------------------------------------------------- S4 compile + fixer
def s4_compile(ctx, harness: Harness, spec: DemoSpec, scene_id: str, src: str,
               common: str, version: int) -> tuple[bool, str, list[str]]:
    """Compila la scena nell'harness; se fallisce, loop col fixer (max_fix_attempts)."""
    bpm = spec.timeline.bpm
    cur = src
    errors: list[str] = []
    for attempt in range(ctx.cfg.budget.max_fix_attempts + 1):
        payload = mono_payload(spec, scene_id, with_math(ctx, scene_id, version, cur), common, bpm)
        res = harness.load(payload)
        if res["ok"]:
            ctx.project.write(f"scenes/{scene_id}/v{version}.glsl", cur)
            return True, cur, []
        errors = res["errors"]
        if attempt >= ctx.cfg.budget.max_fix_attempts:
            break
        fix_user = P.render("fixer.md.j2", src=cur, errors="\n".join(errors)[:4000])
        resp = ctx.client("fixer").chat(
            [
                {"role": "system", "content": P.system_prompt(bpm)},
                {"role": "user", "content": fix_user},
            ],
            step=f"fixer:{scene_id}",
        )
        env = parse_envelope(resp.content)
        if not env.glsl_blocks:
            break
        cur = env.glsl_blocks[0]
    ctx.project.write(f"scenes/{scene_id}/v{version}.glsl", cur)
    ctx.project.write(
        f"scenes/{scene_id}/v{version}.compile_errors.json", json.dumps(errors, indent=1)
    )
    return False, cur, errors


# ---------------------------------------------------------------- S5 probe
def s5_probe(ctx, harness: Harness, spec: DemoSpec, scene_id: str, src: str,
             common: str, version: int) -> dict:
    """Cattura keyframe + stats + perf + flash per la scena; gate; salva vN.probe/."""
    import gzip

    bpm = spec.timeline.bpm
    slot = next(s for s in spec.timeline.scenes if s.id == scene_id)
    dur = slot.bars * spec.timeline.beats_per_bar * 60 / bpm
    payload = mono_payload(spec, scene_id, with_math(ctx, scene_id, version, src), common, bpm)
    pdir = ctx.project.path / "scenes" / scene_id / f"v{version}.probe"
    pdir.mkdir(parents=True, exist_ok=True)

    pw, ph = ctx.cfg.preview.width, ctx.cfg.preview.height
    times = [round(dur * (i + 0.5) / ctx.cfg.preview.keyframes, 3)
             for i in range(ctx.cfg.preview.keyframes)]
    pngs = harness.capture(times, pw, ph)
    stats = harness.scene_stats(times, pw, ph)
    with perf_lane():
        prof = harness.profile(times[:6], pw, ph, repeats=3)
    cells = harness.cell_sequence(0.0, min(dur, 6.0), 8, 128, 72)

    for i, p in enumerate(pngs):
        (pdir / f"key_{i:02d}_t{times[i]}s.png").write_bytes(p)

    frames = [np.asarray(Image.open(io.BytesIO(p)).convert("RGB")) for p in pngs]
    vm = video_metrics(frames, stats, loop=spec.loop)
    info = harness.info()
    pf = perf_profile(
        {float(k): v for k, v in prof["samples"].items()},
        scene_id=scene_id,
        profile=spec.profile,
        resolution=(pw, ph),
        method=str(prof["method"]),
        gpu=str(info["renderer"]),
        target_fps=ctx.cfg.realtime.target_fps,
    )
    fl = analyze_flash(cells, fps=8, flash_max_per_s=ctx.cfg.safety.flash_max_per_s,
                       red_flash=ctx.cfg.safety.red_flash)
    raw = json.dumps(payload).encode()
    metrics = {
        "video": vm,
        "perf": pf.model_dump(),
        "flash": fl.model_dump(),
        "sizes": {"payload_gzip_bytes": len(gzip.compress(raw, 9))},
        "gpu": info["renderer"],
    }
    issues = run_gates(metrics, ctx.cfg)
    (pdir / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    (pdir / "issues.json").write_text(
        json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8"
    )
    imgs = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    contact_sheet(imgs, times, pdir / "contact.png")
    burst_strip(imgs[:6], pdir / "burst.png")
    diff_heatmap(frames, pdir / "diff.png")
    # issues anche a livello di versione (per selection)
    ctx.project.write(
        f"scenes/{scene_id}/v{version}.issues.json",
        json.dumps([i.model_dump() for i in issues], indent=1),
    )
    return metrics


# ---------------------------------------------------------------- S6 critique
def s6_critique(ctx, spec: DemoSpec, scene: SceneBrief, version: int) -> dict:
    from ..critic.critic import critique

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
        from ..critic.models import CriticReport

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
        )
    ctx.project.write(
        f"scenes/{scene.id}/v{version}.critique.json", report.model_dump_json(indent=1)
    )
    return report.model_dump()


# ---------------------------------------------------------------- S7 revise
def s7_revise(ctx, harness: Harness, spec: DemoSpec, scene: SceneBrief, style_src: str,
              common: str, version: int, src: str, critique: dict, issues: list) -> tuple[int, str]:
    """Una iterazione di revisione: nuova versione → torna a S4 (chiamato dal caller)."""
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
        history_text="-",
    )
    msgs = [
        {"role": "system", "content": P.system_prompt(spec.timeline.bpm)},
        {"role": "user", "content": user},
    ]
    resp = ctx.client("orchestrator").chat(msgs, step=f"revise:{scene.id}")
    env = parse_envelope(resp.content)
    new_src = env.glsl_blocks[0]
    new_version = version + 1
    ctx.project.write(f"scenes/{scene.id}/v{new_version}.glsl", new_src)
    try:  # Fase 6: il revise può emettere nuovi math_requests
        new_meta = ShaderSubmission.model_validate(env.json())
        if new_meta.math_requests:
            run_oracle_for(ctx, scene.id, new_version, new_meta.math_requests)
    except Exception as exc:  # noqa: BLE001 - il meta è opzionale
        print(f"[math] revise {scene.id}: nessun math_request ({exc})")
    ok, fixed, errors = s4_compile(ctx, harness, spec, scene.id, new_src, common, new_version)
    if not ok:
        return version, src  # tieni la vecchia se la nuova non compila
    return new_version, fixed


# ---------------------------------------------------------------- S9 bundle
def s9_bundle(ctx, spec: DemoSpec, style_src: str, post: dict) -> dict:
    from ..bundle.build import build_payload_from_sources, write_bundle

    best_srcs: dict[str, str] = {}
    math_srcs: dict[str, str] = {}
    for scene in spec.scenes:
        best = select_best(ctx.project.path / "scenes" / scene.id)
        v = best["version"]
        best_srcs[scene.id] = ctx.project.read(f"scenes/{scene.id}/{v}.glsl")
        math_path = ctx.project.path / "scenes" / scene.id / f"{v}.math.glsl"
        if math_path.exists():
            math_srcs[scene.id] = math_path.read_text(encoding="utf-8")

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
        "scenes": [
            {
                "id": s.id,
                "start_bar": slot.start_bar,
                "bars": slot.bars,
                "transition_in": slot.transition_in,
                "transition_bars": slot.transition_bars,
            }
            for s, slot in zip(spec.scenes, spec.timeline.scenes)
        ],
    }
    payload = build_payload_from_sources(
        spec_dict, best_srcs, style_src, do_minify=True, math_srcs=math_srcs
    )
    name = slugify(spec.title)  # il titolo viene dall'LLM: mai usarlo crudo come nome file
    sizes = write_bundle(payload, ctx.project.path / "out", name)
    return {"payload": payload, "sizes": sizes, "name": name}
