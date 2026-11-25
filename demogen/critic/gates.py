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
    return k, f" (stimato ×{k:.1f} da {res[0]}×{res[1]} a {bres[0]}×{bres[1]})"


def run_gates(metrics: dict[str, Any], cfg: Config | None = None) -> list[Issue]:
    """Valuta le metriche contro le soglie e ritorna le issue (ordinate per gravità)."""
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
        add("blocker", f"NaN/Inf nel {nan_inf:.4f} dei pixel (pre-quantizzazione)",
            "semplifica lo shader: niente divisioni per ~0, clamp dei log, normalize safe")
    if vm.get("black_ratio", 0.0) >= 0.9:
        add("major", f"frame quasi nero (black_ratio={vm['black_ratio']:.2f})",
            "controlla condizioni di luce/raymarch: niente hit → colore di sfondo")
    fs = vm.get("flicker_score")
    if fs is not None and fs > cfg.preview.flicker_max:
        add("minor", f"flicker temporale: oscillazione {fs:.3f} > {cfg.preview.flicker_max} "
            "tra frame consecutivi",
            "riduci aliasing temporale (aa.glsl), rumore che cambia a ogni frame, dettagli sub-pixel")
    lsr = vm.get("loop_seam_ratio")
    if lsr is not None and lsr > cfg.preview.loop_seam_max_ratio:
        add("minor", f"cucitura del loop visibile: salto {lsr:.1f}× la diff tipica tra frame",
            "rendi la scena periodica sulla durata (tempo modulo durata, easing che torna allo stato iniziale)")

    # --- perf ---
    perf = metrics.get("perf")
    if perf:
        prof = perf.get("profile", "modern")
        budget = rt.profiles.get(prof, rt.profiles["modern"])
        k, est = perf_scale(perf, budget)
        # su renderer software (SwiftShader) i ms non dicono nulla della GPU: solo informativi (piano §M0)
        sw = is_software_renderer(perf.get("gpu") or metrics.get("gpu"))
        sev_hi, sev_mid = ("info", "info") if sw else ("blocker", "major")
        note = " [renderer software: solo informativo]" if sw else ""
        p95 = perf.get("p95_ms", 0.0) * k
        mean = perf.get("mean_ms", 0.0) * k
        if p95 > budget["p95"]:
            hot = ", ".join(f"t={h['t']}s ({h['ms']:.1f}ms)" for h in perf.get("hotspots", [])[:3])
            add(sev_hi, f"perf p95 {p95:.2f} ms > budget {budget['p95']} ms [{prof}]{est}{note}",
                f"hotspot: {hot}. Riduci MAX_STEPS (qSteps), ottave fbm, "
                "soft shadow/AO sopra soglia uQuality, bounding volume",
                at=perf.get("hotspots", [{}])[0].get("t") if perf.get("hotspots") else None)
        if mean > budget["mean"]:
            add(sev_mid, f"carico medio {mean:.2f} ms > budget {budget['mean']} ms [{prof}]{est}{note} "
                f"(GPU load stimato {perf.get('gpu_load_est', 0) * k:.0%})",
                "riduci il costo per-pixel: meno passi, meno ottave, bloom off a bassa qualità")
        floor = perf.get("floor_p95_ms")
        if floor is not None and floor * k > rt.floor_ratio * budget["p95"]:
            add(sev_mid, f"pavimento p95 {floor * k:.2f} ms > floor_ratio×budget{est}{note}: "
                "la qualità adattiva non ha margine",
                "la scena è troppo pesante anche a qualità minima: semplifica la geometria")

    # --- flash ---
    flash = metrics.get("flash")
    if flash and not flash.get("passed", True):
        lim = safety.flash_max_per_s
        wins = flash.get("windows", [])[:3]
        at = wins[0][0] if wins else None
        if flash.get("max_red_flashes_per_s", 0) > lim:
            add("blocker", f"flash rossi saturi: {flash['max_red_flashes_per_s']:.0f}/s > {lim}/s finestre {wins}",
                "niente alternanze rapide verso rosso saturo; usa crossfade o beatFlash con uFlashLimit", at=at)
        if flash.get("max_flashes_per_s", 0) > lim:
            add("blocker", f"flash: {flash['max_flashes_per_s']:.0f}/s > {lim}/s (WCAG 2.3.1) finestre {wins}",
                "riduci strobo/flash su aree ampie; usa beatFlash (rispetta uFlashLimit)", at=at)

    # --- avvio ---
    startup = metrics.get("startup")
    if startup:
        if startup.get("compile_total_ms", 0) > rt.max_compile_ms_total:
            add("major", f"compilazione totale {startup['compile_total_ms']:.0f} ms > {rt.max_compile_ms_total:.0f} ms",
                "cicli con limiti costanti piccoli, niente unrolling pesante (ANGLE→D3D lento)")
        if startup.get("first_frame_ms", 0) > rt.max_first_frame_ms:
            add("major", f"primo frame {startup['first_frame_ms']:.0f} ms > {rt.max_first_frame_ms:.0f} ms",
                "compilazione parallela, prebuffer audio breve")

    # --- dimensione ---
    # --- audio (Fase 2): onset allineati alla griglia beat ---
    am = metrics.get("audio")
    if am:
        if am.get("clipped"):
            add("major", "audio in clip (peak >= 0.999)", "abbassa i guadagni o usa soft clip (tanh)")
        obe = am.get("onset_vs_beat") or {}
        mean_err = obe.get("mean_abs_err_ms")
        if mean_err is not None and mean_err > cfg.audio.max_onset_err_ms:
            add("major", f"onset audio non allineati al beat: errore medio {mean_err:.1f} ms "
                f"(> {cfg.audio.max_onset_err_ms} ms)", "ancorare kick/snare a floor(t/beatDur), non a iTime libero")

    sizes = metrics.get("sizes")
    if sizes:
        gz = sizes.get("payload_gzip_bytes", 0)
        if gz > cfg.bundle.max_payload_gz_kb * 1024:
            add("major", f"payload {gz} B gzip > {cfg.bundle.max_payload_gz_kb} KB",
                "minify aggressivo, treeshake più stretto, meno scene")

    order = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
    issues.sort(key=lambda i: order[i.severity])
    return issues
