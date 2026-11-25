"""Selezione della versione migliore per scena + anti-regressione (piano §10)."""

from __future__ import annotations

import json
import re
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
REGRESSION_MARGIN = 1.0  # una versione nuova vince solo se non perde più di 1 punto dal massimo

_VER = re.compile(r"^v(\d+)\.glsl$")  # v12.glsl sì; v1.math.glsl no


def list_versions(scene_dir: Path) -> list[int]:
    """Versioni shader esistenti (vN.glsl, esclusi *.math.glsl), in ordine numerico."""
    if not scene_dir.is_dir():
        return []
    return sorted(int(m.group(1)) for p in scene_dir.iterdir() if (m := _VER.match(p.name)))


def next_version(scene_dir: Path) -> int:
    """Numero della prossima versione: massimo esistente + 1 (mai sovrascrivere)."""
    return max(list_versions(scene_dir), default=0) + 1


def load_issues(scene_dir: Path, version: int) -> list[Issue]:
    p = scene_dir / f"v{version}.issues.json"
    if not p.exists():
        return []
    return [Issue.model_validate(i) for i in json.loads(p.read_text(encoding="utf-8"))]


def has_blocker(issues: list[Issue]) -> bool:
    return any(i.severity == "blocker" for i in issues)


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
    """Sceglie la versione da spedire tra quelle criticate, in ordine numerico.

    - le versioni con blocker sono escluse (salvo che lo siano tutte);
    - anti-regressione: una versione più recente sostituisce la best solo se il suo
      score è >= (massimo visto finora - REGRESSION_MARGIN), così una catena di piccoli
      peggioramenti non deriva verso il basso.
    """
    scored: list[tuple[int, float, bool]] = []
    for v in list_versions(scene_dir):
        c = scene_dir / f"v{v}.critique.json"
        if not c.exists():
            continue
        critique = CriticReport.model_validate(json.loads(c.read_text(encoding="utf-8")))
        issues = load_issues(scene_dir, v)
        scored.append((v, score_version(critique, issues), has_blocker(issues)))

    candidates = [s for s in scored if not s[2]] or scored
    best: dict | None = None
    max_score = float("-inf")
    for v, score, _blk in candidates:
        if best is None or score >= max_score - REGRESSION_MARGIN:
            best = {"version": f"v{v}", "score": round(score, 3)}
        max_score = max(max_score, score)
    if best is None:
        # nessuna critica: prendi l'ultima versione che compila
        vs = [v for v in list_versions(scene_dir) if not (scene_dir / f"v{v}.compile_errors.json").exists()]
        best = {"version": f"v{vs[-1]}" if vs else "v1", "score": 0.0}
    (scene_dir / "best.json").write_text(json.dumps(best), encoding="utf-8")
    return best
