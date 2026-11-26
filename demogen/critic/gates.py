"""Gate tecnici numerici PRIMA del critico LLM (D10, piano §12.5)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .models import Issue

_SOFTWARE_MARKERS = ("swiftshader", "llvmpipe", "softpipe", "software")


def is_software_renderer(name: str | None) -> bool:
    """Come isSoftwareRenderer in player/src/gl.ts: rendering su CPU (ms non confrontabili coi budget GPU)."""
    n = (name or "").lower()
    return any(m in n for m in _SOFTWARE_MARKERS)


def perf_scale(perf: dict, budget: dict) -> tuple[float, str]:
    """Fattore per riportare i ms misurati alla risoluzione del budget (rapporto di pixel).

    Il profilo retro renderizza sempre alla risoluzione interna fissa: niente scala."""
    res, bres = perf.get("resolution"), budget.get("res")
    if perf.get("profile") == "retro" or not res or not bres:
        return 1.0, ""
    px, bpx = res[0] * res[1], bres[0] * bres[1]
    if px <= 0 or abs(bpx / px - 1.0) < 0.01:
        return 1.0, ""
    k = bpx / px
    return k, f" (estimated ×{k:.1f} from {res[0]}×{res[1]} to {bres[0]}×{bres[1]})"


HEAVY_FIX = (
    "make it lighter: no volumes ray-marched inside the main loop (volumetric clouds/fog), "
    "no fbm at every step, MAX_STEPS <= 96 with qSteps, fbm <= 4 octaves with qOctaves, "
    "bounding volumes, 2D layers or analytic fog instead of volumes"
)


def run_gates(metrics: dict[str, Any], cfg: Config | None = None, *, perf_blocking: bool = True) -> list[Issue]:
    """Valuta le metriche contro le soglie e ritorna le issue (ordinate per gravità).

    `perf_blocking=False` (probe della demo intera in S9): la perf eccessiva resta un avviso
    "major", così la demo viene consegnata comunque; le scene sono già state spinte ad
    alleggerirsi nel loop S5–S7."""
    cfg = cfg or Config.model_validate({"providers": {}, "roles": {}})
    rt = cfg.realtime
    safety = cfg.safety
    issues: list[Issue] = []

    def add(sev: str, desc: str, fix: str = "", at: float | None = None) -> None:
        issues.append(Issue(severity=sev, description=desc, suggested_fix=fix, at_s=at))  # type: ignore[arg-type]

    # --- qualità immagine (metrics["video"]) ---
    vm = metrics.get("video", metrics)
    nan_inf = vm.get("nan_ratio", 0.0) + vm.get("inf_ratio", 0.0)
    if nan_inf > 0:
        add("blocker", f"NaN/Inf in {nan_inf:.4f} of the pixels (pre-quantization)",
            "simplify the shader: no divisions by ~0, clamp log arguments, safe normalize")
    black = vm.get("black_ratio", 0.0)
    black_fix = ("mainImage must assign the final color to fragColor (e.g. fragColor = vec4(col, 1.0)); "
                 "check lighting/raymarch: no hit → background color, not black")
    if black >= 0.98:  # tutta nera: è rotta, non è una scelta artistica
        add("blocker", f"scene is entirely black (black_ratio={black:.2f})", black_fix)
    elif black >= 0.9:
        add("major", f"frame almost black (black_ratio={black:.2f})", black_fix)
    fs = vm.get("flicker_score")
    if fs is not None and fs > cfg.preview.flicker_max:
        add("minor", f"temporal flicker: oscillation {fs:.3f} > {cfg.preview.flicker_max} "
            "between consecutive frames",
            "reduce temporal aliasing (aa.glsl), noise that changes every frame, sub-pixel detail")
    lsr = vm.get("loop_seam_ratio")
    if lsr is not None and lsr > cfg.preview.loop_seam_max_ratio:
        add("minor", f"visible loop seam: jump of {lsr:.1f}× the typical frame-to-frame diff",
            "make the scene periodic over its duration (time modulo duration, easing back to the initial state)")

    # --- perf ---
    perf = metrics.get("perf")
    if perf:
        prof = perf.get("profile", "modern")
        budget = rt.profiles.get(prof, rt.profiles["modern"])
        k, est = perf_scale(perf, budget)
        # su renderer software (SwiftShader) i ms non dicono nulla della GPU: solo informativi (piano §M0)
        sw = is_software_renderer(perf.get("gpu") or metrics.get("gpu"))
        sev_hi, sev_mid = ("info", "info") if sw else ("blocker", "major")
        note = " [software renderer: informational only]" if sw else ""
        p95 = perf.get("p95_ms", 0.0) * k
        mean = perf.get("mean_ms", 0.0) * k
        if p95 > budget["p95"]:
            hot = ", ".join(f"t={h['t']}s ({h['ms']:.1f}ms)" for h in perf.get("hotspots", [])[:3])
            add(sev_hi, f"perf p95 {p95:.2f} ms > budget {budget['p95']} ms [{prof}]{est}{note}",
                f"hotspots: {hot}. Reduce MAX_STEPS (qSteps) and fbm octaves, "
                "enable soft shadows/AO only above a uQuality threshold, use bounding volumes",
                at=perf.get("hotspots", [{}])[0].get("t") if perf.get("hotspots") else None)
        if mean > budget["mean"]:
            add(sev_mid, f"average load {mean:.2f} ms > budget {budget['mean']} ms [{prof}]{est}{note} "
                f"(estimated GPU load {perf.get('gpu_load_est', 0) * k:.0%})",
                "reduce the per-pixel cost: fewer steps, fewer octaves, bloom off at low quality")
        floor = perf.get("floor_p95_ms")
        if floor is not None and floor * k > rt.floor_ratio * budget["p95"]:
            add(sev_mid, f"p95 floor {floor * k:.2f} ms > floor_ratio×budget{est}{note}: "
                "adaptive quality has no headroom",
                "the scene is too heavy even at minimum quality: simplify the geometry")
        # costo relativo alla scena di riferimento: vale su qualunque renderer, anche SwiftShader
        r95, rmean, ref = perf.get("ref_ratio_p95"), perf.get("ref_ratio_mean"), perf.get("ref_ms")
        res = perf.get("resolution") or ["?", "?"]
        where = f"{perf.get('p95_ms', 0.0):.0f} ms vs {ref or 0:.0f} ms at {res[0]}×{res[1]}"
        tail = "" if perf_blocking else " (demo delivered anyway: lighten the scenes with revise)"
        if r95 is not None and r95 > rt.max_ref_ratio_p95:
            add("blocker" if perf_blocking else "major",
                f"too heavy: p95 {r95:.1f}× the reference scene (max {rt.max_ref_ratio_p95:g}×; "
                f"{where}){tail}", HEAVY_FIX)
        elif rmean is not None and rmean > rt.max_ref_ratio_mean:
            add("major", f"heavy: on average {rmean:.1f}× the reference scene "
                f"(max {rt.max_ref_ratio_mean:g}×){tail}", HEAVY_FIX)

    # --- flash ---
    flash = metrics.get("flash")
    if flash and not flash.get("passed", True):
        lim = safety.flash_max_per_s
        wins = flash.get("windows", [])[:3]
        at = wins[0][0] if wins else None
        if flash.get("max_red_flashes_per_s", 0) > lim:
            add("blocker", f"saturated red flashes: {flash['max_red_flashes_per_s']:.0f}/s > {lim}/s windows {wins}",
                "no rapid alternation towards saturated red; use crossfade or beatFlash with uFlashLimit", at=at)
        if flash.get("max_flashes_per_s", 0) > lim:
            add("blocker", f"flash: {flash['max_flashes_per_s']:.0f}/s > {lim}/s (WCAG 2.3.1) windows {wins}",
                "reduce strobe/flashes over large areas; use beatFlash (respects uFlashLimit)", at=at)

    # --- avvio ---
    startup = metrics.get("startup")
    if startup:
        if startup.get("compile_total_ms", 0) > rt.max_compile_ms_total:
            add("major", f"total compile time {startup['compile_total_ms']:.0f} ms > {rt.max_compile_ms_total:.0f} ms",
                "loops with small constant bounds, no heavy unrolling (ANGLE→D3D is slow)")
        if startup.get("first_frame_ms", 0) > rt.max_first_frame_ms:
            add("major", f"first frame {startup['first_frame_ms']:.0f} ms > {rt.max_first_frame_ms:.0f} ms",
                "parallel compilation, short audio prebuffer")

    # --- dimensione ---
    # --- audio (Fase 2): onset allineati alla griglia beat ---
    am = metrics.get("audio")
    if am:
        if am.get("clipped"):
            add("major", "audio clipping (peak >= 0.999)", "lower the gains or use soft clipping (tanh)")
        obe = am.get("onset_vs_beat") or {}
        mean_err = obe.get("mean_abs_err_ms")
        if mean_err is not None and mean_err > cfg.audio.max_onset_err_ms:
            add("major", f"audio hits off the rhythm grid (beats, 8ths, 16ths of the BPM): mean error "
                f"{mean_err:.1f} ms (> {cfg.audio.max_onset_err_ms} ms)",
                "start every hit at a multiple of beatDur/4 computed from t (floor(t/beatDur)), "
                "not from free-running time or another tempo")

    sizes = metrics.get("sizes")
    if sizes:
        gz = sizes.get("payload_gzip_bytes", 0)
        if gz > cfg.bundle.max_payload_gz_kb * 1024:
            add("major", f"payload {gz} B gzip > {cfg.bundle.max_payload_gz_kb} KB",
                "aggressive minify, tighter treeshake, fewer scenes")

    order = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
    issues.sort(key=lambda i: order[i.severity])
    return issues
