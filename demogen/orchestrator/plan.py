"""Il piano della demo (spec.json scritto da S0) letto e cambiato PRIMA che si disegni.

Con `generate --review-plan` la pipeline si ferma dopo S0 (`state["paused"] = "plan"`): l'utente
legge il piano (`demogen plan <progetto>`), lo cambia a mano (`--scene s1 --description ...`) o
con una nota all'LLM (`--note ...`, una chiamata), poi `demogen resume` riprende da S1 con il
piano cambiato. Il piano è modificabile solo finché lo style (S1) non è stato fatto: dopo,
style e scene ne dipendono e si cambia una scena con `revise`.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from ..project.store import Project
from ..spec.models import DemoSpec
from .steps import PipelineError

PAUSE_PLAN = "plan"
SCENE_FIELDS = ("title", "description", "motion")
_WIDTH = 100


class PlanError(PipelineError):
    """Piano mancante, scena inesistente o piano già in uso (messaggio per l'utente, in inglese)."""


def load_plan(project: Project) -> DemoSpec:
    if not project.exists("spec.json"):
        raise PlanError(f"{project.path} has no plan yet (spec.json): it is written by the first step of generate")
    return DemoSpec.model_validate_json(project.read("spec.json"))


def plan_editable(state: dict) -> bool:
    """Il piano si cambia solo prima dello style: S1 e le scene sono disegnati a partire da lui."""
    return "S1" not in (state.get("done") or [])


def require_editable(project: Project) -> dict:
    state = project.load_state()
    if not plan_editable(state):
        raise PlanError(
            "the plan is already in use: style and scenes are drawn from it. Change a scene with "
            f"`demogen revise {project.path} --scene <id> --note \"...\"`"
        )
    return state


def edit_scene(spec: DemoSpec, scene_id: str, **fields: str | None) -> DemoSpec:
    """Cambia titolo, descrizione o movimento di una scena; gli altri campi restano come sono."""
    unknown = set(fields) - set(SCENE_FIELDS)
    if unknown:
        raise PlanError(f"cannot change {sorted(unknown)}: only {', '.join(SCENE_FIELDS)}")
    changes = {k: v.strip() for k, v in fields.items() if v is not None}
    if not changes:
        raise PlanError("nothing to change: give a new " + ", ".join(SCENE_FIELDS))
    if any(not v for v in changes.values()):
        raise PlanError("a scene field cannot be empty")
    scene = next((s for s in spec.scenes if s.id == scene_id), None)
    if scene is None:
        raise PlanError(f"scene {scene_id!r} does not exist (scenes: {', '.join(s.id for s in spec.scenes)})")
    for k, v in changes.items():
        setattr(scene, k, v)
    return DemoSpec.model_validate(spec.model_dump())


def edit_plan(project: Project, scene_id: str, **fields: str | None) -> DemoSpec:
    """Modifica a mano (nessuna chiamata LLM) di una scena del piano, salvata in spec.json."""
    require_editable(project)
    spec = edit_scene(load_plan(project), scene_id, **fields)
    save_plan(project, spec)
    return spec


def save_plan(project: Project, spec: DemoSpec) -> None:
    project.write("spec.json", spec.model_dump_json(indent=1))


def is_paused_for_plan(project_dir: Path) -> bool:
    try:
        state = json.loads((Path(project_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(state, dict) and state.get("paused") == PAUSE_PLAN


# ---------------------------------------------------------------- testo per l'utente
def _fmt(x: float) -> str:
    return f"{x:.1f}" if abs(x - round(x)) > 1e-9 else f"{x:.0f}"


def _wrap(label: str, text: str) -> list[str]:
    head = f"      {label}: "
    return textwrap.wrap(text, _WIDTH, initial_indent=head, subsequent_indent=" " * len(head)) or [head.rstrip()]


def format_plan(spec: DemoSpec) -> str:
    """Il piano in chiaro: demo, poi le scene in ordine di timeline con tempi in secondi e battute."""
    tl = spec.timeline
    bar_s = tl.beats_per_bar * 60 / tl.bpm
    loop = "yes" if spec.loop else "no"
    lines = [
        f'PLAN  "{spec.title}"',
        f"  {_fmt(spec.duration_s)} s · {_fmt(tl.bpm)} BPM · style {spec.profile} · loop {loop} · "
        f"{len(spec.scenes)} scene{'s' if len(spec.scenes) != 1 else ''}",
    ]
    if spec.art_direction:
        lines += textwrap.wrap(spec.art_direction, _WIDTH, initial_indent="  art direction: ",
                               subsequent_indent=" " * 17)
    if spec.palette_hint:
        # virgole: l'LLM scrive anche voci con il nome ("cream #f2e8c9"), con gli spazi si confondono
        lines += textwrap.wrap(", ".join(spec.palette_hint), _WIDTH, initial_indent="  palette: ",
                               subsequent_indent=" " * 11)
    if spec.text:
        lines.append(f'  text: "{spec.text}"')
    if spec.avoid:
        lines += textwrap.wrap(", ".join(spec.avoid), _WIDTH, initial_indent="  avoid: ", subsequent_indent=" " * 9)
    briefs = {s.id: s for s in spec.scenes}
    lines.append("")
    for slot in sorted(tl.scenes, key=lambda s: s.start_bar):
        sc = briefs.get(slot.id)
        if sc is None:
            continue
        start, end = slot.start_bar * bar_s, (slot.start_bar + slot.bars) * bar_s
        trans = slot.transition_in if slot.transition_in == "cut" else \
            f"{slot.transition_in} {slot.transition_bars:g} bar{'s' if slot.transition_bars != 1 else ''}"
        lines.append(f"  {sc.id:<4} {sc.title}")
        lines.append(f"      {start:.1f}–{end:.1f} s  (bars {slot.start_bar:g}–{slot.start_bar + slot.bars:g}, "
                     f"in: {trans})")
        lines += _wrap("what you see", sc.description)
        lines += _wrap("motion", sc.motion)
        if sc.camera:
            lines += _wrap("camera", sc.camera)
        if sc.techniques:
            lines += _wrap("techniques", ", ".join(sc.techniques))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def next_steps(project_dir: Path, editable: bool) -> str:
    p = str(project_dir)
    if not editable:
        return (f"the drawing has started from this plan: change a scene with\n"
                f"  demogen revise {p} --scene <id> --note \"...\"")
    return "\n".join([
        "the plan can still change (nothing has been drawn yet):",
        f"  demogen plan {p} --scene <id> --description \"...\"   (also --title, --motion: no LLM call)",
        f"  demogen plan {p} --note \"...\"                      (the LLM rewrites the plan: one call)",
        f"continue with: demogen resume {p}",
    ])
