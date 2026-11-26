"""report.md finale del progetto (piano §16)."""

from __future__ import annotations

import json
from pathlib import Path


def _music_section(p: Path, state: dict) -> list[str]:
    """Colonna sonora: prompt, versione scelta, note del compositore, misure dell'ascolto."""
    adir = p / "audio"
    req = state.get("request") or {}
    if not adir.exists():
        return ["## Music", "", "- no soundtrack" + ("" if req.get("audio") else " (not requested)"), ""]
    best = (json.loads((adir / "best.json").read_text(encoding="utf-8")) or {}).get("version") \
        if (adir / "best.json").exists() else None
    lines = ["## Music", ""]
    if req.get("music"):
        lines.append(f"- music prompt: {req['music']}")
    if not best:
        lines += ["- no usable version: the demo is silent", ""]
        return lines
    meta_p, met_p = adir / f"{best}.meta.json", adir / f"{best}.metrics.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    m = json.loads(met_p.read_text(encoding="utf-8")) if met_p.exists() else {}
    obe = m.get("onset_vs_beat") or {}
    lines.append(f"- version: {best}" + (f" — {meta['notes']}" if meta.get("notes") else ""))
    if m:
        err, rt = obe.get("mean_abs_err_ms"), m.get("realtime_factor")
        lines.append(
            f"- listening: rms={m.get('rms', 0):.3f} peak={m.get('peak', 0):.3f}, "
            f"hits vs the rhythm grid: mean error {'-' if err is None else f'{err:.1f}'} ms, "
            f"render speed {'-' if rt is None else f'{rt:.0f}'}x realtime"
        )
    lines.append("")
    return lines


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
            f"- duration: {round(float(spec.get('duration_s') or 0), 2):g} s, bpm {spec['timeline']['bpm']:g}, "
            f"profile {spec.get('profile')}, loop={spec.get('loop')}",
            f"- scenes: {len(spec.get('scenes', []))}",
            "",
        ]
    lines.append("## Scenes and versions")
    lines.append("")
    scenes_dir = p / "scenes"
    if scenes_dir.exists():
        for scene_dir in sorted(scenes_dir.iterdir()):
            best_path = scene_dir / "best.json"
            if best_path.exists():
                best = json.loads(best_path.read_text(encoding="utf-8"))
                lines.append(f"- `{scene_dir.name}`: best={best.get('version')} score={best.get('score')}")
            crits = sorted(scene_dir.glob("v*.critique.json"), key=lambda c: int(c.name[1:].split(".")[0]))
            for c in crits:
                data = json.loads(c.read_text(encoding="utf-8"))
                lines.append(
                    f"  - {c.name}: verdict={data.get('verdict')} scores={data.get('scores')}"
                )
    lines.append("")
    lines += _music_section(p, state)
    metrics_path = p / "out" / "metrics.json"
    if metrics_path.exists():
        m = json.loads(metrics_path.read_text(encoding="utf-8"))
        lines += [
            "## Metrics and gates (whole demo)",
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
        lines += [f"## Gates: {len(issues)} issues", ""]
        for i in issues:
            lines.append(f"- [{i['severity']}] {i['description']}")
        lines.append("")
    budget = state.get("budget_spent_usd")
    if budget is not None:
        lines += ["## Cost", "", f"- LLM: {budget:.4f} USD", ""]
    if state.get("stopped"):
        lines += ["## Early stop", "", f"- {state['stopped']}", ""]
    out_dir = p / "out"
    if out_dir.exists():
        lines += ["## Artifacts", ""]
        for f in sorted(out_dir.iterdir()):
            lines.append(f"- `out/{f.name}` ({f.stat().st_size} B)")
        lines.append("")
    return "\n".join(lines)
