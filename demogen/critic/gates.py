"""Gate tecnici numerici PRIMA del critico LLM (D10, piano §12.5)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .models import Issue


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
    if vm.get("flicker_peaks", 0) > 0:
        add("minor", f"{vm['flicker_peaks']} picchi temporali (z>4): possibile flicker",
            "riduci aliasing temporale (aa.glsl) o sorgenti di rumore instabili")

    # --- perf ---
    perf = metrics.get("perf")
    if perf:
        prof = perf.get("profile", "modern")
        budget = rt.profiles.get(prof, rt.profiles["modern"])
        p95 = perf.get("p95_ms", 0.0)
        mean = perf.get("mean_ms", 0.0)
        if p95 > budget["p95"]:
            hot = ", ".join(f"t={h['t']}s ({h['ms']:.1f}ms)" for h in perf.get("hotspots", [])[:3])
            add("blocker", f"perf p95 {p95:.2f} ms > budget {budget['p95']} ms [{prof}]",
                f"hotspot: {hot}. Riduci MAX_STEPS (qSteps), ottave fbm, "
                "soft shadow/AO sopra soglia uQuality, bounding volume",
                at=perf.get("hotspots", [{}])[0].get("t") if perf.get("hotspots") else None)
        if mean > budget["mean"]:
            add("major", f"carico medio {mean:.2f} ms > budget {budget['mean']} ms [{prof}] "
                f"(GPU load stimato {perf.get('gpu_load_est', 0):.0%})",
                "riduci il costo per-pixel: meno passi, meno ottave, bloom off a bassa qualità")
        floor = perf.get("floor_p95_ms")
        if floor is not None and floor > rt.floor_ratio * budget["p95"]:
            add("major", f"pavimento p95 {floor:.2f} ms > floor_ratio×budget: la qualità adattiva non ha margine",
                "la scena è troppo pesante anche a qualità minima: semplifica la geometria")

    # --- flash ---
    flash = metrics.get("flash")
    if flash and not flash.get("passed", True):
        if flash.get("red_flash_events", 0) > 0:
            add("blocker", f"{flash['red_flash_events']} flash rossi saturi",
                "niente transizioni verso rosso saturo; usa crossfade o beatFlash con uFlashLimit")
        add("blocker", f"flash: {flash.get('max_flashes_per_s', 0):.1f}/s > {safety.flash_max_per_s}/s "
            f"finestre {flash.get('windows', [])[:3]}",
            "riduci strobo/flash a tutto schermo; usa beatFlash (rispetta uFlashLimit)")

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
    sizes = metrics.get("sizes")
    if sizes:
        gz = sizes.get("payload_gzip_bytes", 0)
        if gz > cfg.bundle.max_payload_gz_kb * 1024:
            add("major", f"payload {gz} B gzip > {cfg.bundle.max_payload_gz_kb} KB",
                "minify aggressivo, treeshake più stretto, meno scene")

    order = {"blocker": 0, "major": 1, "minor": 2}
    issues.sort(key=lambda i: order[i.severity])
    return issues
