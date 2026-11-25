"""report.md finale del progetto (piano §16)."""

from __future__ import annotations

import json
from pathlib import Path


def build_report(project_path: Path) -> str:
    p = Path(project_path)
    state = json.loads((p / "state.json").read_text(encoding="utf-8")) if (p / "state.json").exists() else {}
    lines = ["# demogen — report", ""]
    spec_path = p / "spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        lines += [
            f"## Demo: {spec.get('title', '?')}",
            "",
            f"- prompt: {spec.get('prompt', '')}",
            f"- durata: {spec.get('duration_s')} s, bpm {spec['timeline']['bpm']}, "
            f"profilo {spec.get('profile')}, loop={spec.get('loop')}",
            f"- scene: {len(spec.get('scenes', []))}",
            "",
        ]
    lines.append("## Scene e versioni")
    lines.append("")
    scenes_dir = p / "scenes"
    if scenes_dir.exists():
        for scene_dir in sorted(scenes_dir.iterdir()):
            best_path = scene_dir / "best.json"
            if best_path.exists():
                best = json.loads(best_path.read_text(encoding="utf-8"))
                lines.append(f"- `{scene_dir.name}`: best={best.get('version')} score={best.get('score')}")
            crits = sorted(scene_dir.glob("v*.critique.json"))
            for c in crits:
                data = json.loads(c.read_text(encoding="utf-8"))
                lines.append(
                    f"  - {c.name}: verdict={data.get('verdict')} scores={data.get('scores')}"
                )
    lines.append("")
    metrics_path = p / "out" / "metrics.json"
    if metrics_path.exists():
        m = json.loads(metrics_path.read_text(encoding="utf-8"))
        lines += [
            "## Metriche e gate (demo intera)",
            "",
            f"- gpu: {m.get('gpu', '?')}",
        ]
        perf = m.get("perf", {})
        if perf:
            lines.append(
                f"- perf: p95={perf.get('p95_ms'):.2f} ms mean={perf.get('mean_ms'):.2f} ms "
                f"load={perf.get('gpu_load_est', 0):.0%} ({perf.get('method')})"
            )
        fl = m.get("flash", {})
        if fl:
            lines.append(f"- flash: passed={fl.get('passed')} max/s={fl.get('max_flashes_per_s')}")
        vm = m.get("video", {})
        if vm:
            lines.append(
                f"- video: luma={vm.get('luma_mean'):.3f} black={vm.get('black_ratio'):.3f} "
                f"nan={vm.get('nan_ratio')}"
            )
        lines.append("")
    issues_path = p / "out" / "issues.json"
    if issues_path.exists():
        issues = json.loads(issues_path.read_text(encoding="utf-8"))
        lines += [f"## Gate: {len(issues)} issue", ""]
        for i in issues:
            lines.append(f"- [{i['severity']}] {i['description']}")
        lines.append("")
    budget = state.get("budget_spent_usd")
    if budget is not None:
        lines += ["## Costo", "", f"- LLM: {budget:.4f} USD", ""]
    out_dir = p / "out"
    if out_dir.exists():
        lines += ["## Artefatti", ""]
        for f in sorted(out_dir.iterdir()):
            lines.append(f"- `out/{f.name}` ({f.stat().st_size} B)")
        lines.append("")
    return "\n".join(lines)
