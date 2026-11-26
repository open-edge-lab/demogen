"""Anteprima di una scena di un progetto nel browser (`demogen play <progetto> --scene s1`).

Funziona anche a generazione in corso: legge soltanto (spec.json, style.glsl, post.json, vN.glsl,
le funzioni dell'oracolo) e non scrive nulla nel progetto, quindi non disturba la pipeline.
La scena è compilata come in S4/S5 (stesso common, stesse funzioni dell'oracolo) e con il
post-processing del progetto, cioè come apparirà nella demo, in loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from ..project.store import Project
from . import steps
from .plan import PlanError, load_plan
from .selection import list_versions


@dataclass
class SceneVersions:
    id: str
    title: str
    versions: list[int]  # versioni con uno shader su disco, in ordine numerico
    best: int | None  # quella scelta finora (best.json), se c'è
    default: int | None  # quella mostrata senza --version: la best, altrimenti l'ultima che compila


def _best(sdir: Path, versions: list[int]) -> int | None:
    try:
        v = json.loads((sdir / "best.json").read_text(encoding="utf-8")).get("version", "")
        n = int(str(v).lstrip("v"))
    except (OSError, ValueError, AttributeError):
        return None
    return n if n in versions else None


def scene_versions(project_dir: Path) -> list[SceneVersions]:
    """Le scene del piano, in ordine di timeline, con le versioni disegnate finora."""
    proj = Project(project_dir)
    spec = load_plan(proj)
    order = {s.id: i for i, s in enumerate(sorted(spec.timeline.scenes, key=lambda s: s.start_bar))}
    out = []
    for sc in sorted(spec.scenes, key=lambda s: order.get(s.id, len(order))):
        sdir = proj.path / "scenes" / sc.id
        vs = list_versions(sdir) if sdir.is_dir() else []
        best = _best(sdir, vs)
        compiled = [v for v in vs if not (sdir / f"v{v}.compile_errors.json").exists()]
        default = best or (compiled[-1] if compiled else (vs[-1] if vs else None))
        out.append(SceneVersions(sc.id, sc.title, vs, best, default))
    return out


def describe(sv: SceneVersions) -> str:
    if not sv.versions:
        return f"{sv.id}  {sv.title}: no shader yet"
    vs = ", ".join(f"v{v}" for v in sv.versions)
    return f"{sv.id}  {sv.title}: {vs}" + (f" (best v{sv.best})" if sv.best else "")


def scene_preview_payload(project_dir: Path, scene_id: str, version: int | None = None) -> tuple[dict, int]:
    """(payload .demo con la sola scena in loop, versione mostrata)."""
    proj = Project(project_dir)
    spec = load_plan(proj)
    table = {sv.id: sv for sv in scene_versions(project_dir)}
    if not scene_id:
        raise PlanError("choose a scene with --scene:\n  " + "\n  ".join(describe(sv) for sv in table.values()))
    sv = table.get(scene_id)
    if sv is None:
        raise PlanError(f"scene {scene_id!r} does not exist (scenes: {', '.join(table)})")
    if not sv.versions:
        raise PlanError(f"scene {scene_id} has no shader yet: the drafts are written after the plan and the "
                        "style (step S2)")
    v = version or sv.default
    if v not in sv.versions:
        raise PlanError(f"scene {scene_id} has no v{v} (versions: {', '.join(f'v{x}' for x in sv.versions)})")
    src = proj.read(f"scenes/{scene_id}/v{v}.glsl")
    style = proj.read("style.glsl") if proj.exists("style.glsl") else ""
    common, scene = steps.compile_sources(SimpleNamespace(project=proj), scene_id, v, src, style)
    payload = steps.mono_payload(spec, scene_id, scene, common)
    payload["meta"]["loop"] = True  # l'anteprima gira finché la finestra resta aperta
    payload["meta"]["title"] = f"{spec.title}: {scene_id} v{v}"
    if proj.exists("post.json"):
        payload["post"] = json.loads(proj.read("post.json"))
    return payload, v
