"""Selezione della versione migliore per scena + anti-regressione (piano §10)."""

from __future__ import annotations

import json
from pathlib import Path

from ..critic.models import CriticReport, Issue

WEIGHTS = {
    "brief": 1.0,
    "composition": 1.2,
    "color": 1.0,
    "motion": 1.2,
    "technical": 1.5,
    "originality": 1.0,
}


def score_version(critique: CriticReport | None, issues: list[Issue]) -> float:
    """Media pesata dei punteggi del critico, penalità per gate falliti."""
    if critique is None or not critique.scores:
        base = 5.0
    else:
        num = sum(WEIGHTS.get(k, 1.0) * v for k, v in critique.scores.items())
        den = sum(WEIGHTS.get(k, 1.0) for k in critique.scores)
        base = num / den if den else 5.0
    blockers = sum(1 for i in issues if i.severity == "blocker")
    majors = sum(1 for i in issues if i.severity == "major")
    return base - 3.0 * blockers - 1.0 * majors


def select_best(scene_dir: Path) -> dict:
    """Sceglie la vN con score più alto; anti-regressione: se l'ultima è peggio
    di > 1 punto rispetto alla best, tieni la best."""
    versions = sorted(scene_dir.glob("v*.critique.json"))
    best: dict | None = None
    for c in versions:
        v = c.stem.split(".")[0]
        critique = CriticReport.model_validate(json.loads(c.read_text(encoding="utf-8")))
        issues_path = scene_dir / f"{v}.issues.json"
        issues = []
        if issues_path.exists():
            issues = [Issue.model_validate(i) for i in json.loads(issues_path.read_text())]
        score = score_version(critique, issues)
        if best is None or score > best["score"] + 1.0 or (
            score > best["score"] - 1.0 and v > best["version"]
        ):
            if best is None or score >= best["score"] - 1.0:
                best = {"version": v, "score": round(score, 3)}
    if best is None:
        # nessuna critica: prendi l'ultima versione
        srcs = sorted(scene_dir.glob("v*.glsl"))
        best = {"version": srcs[-1].stem if srcs else "v1", "score": 0.0}
    (scene_dir / "best.json").write_text(json.dumps(best), encoding="utf-8")
    return best
