from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from . import __version__
from .browser.session import PLAYER_DIR, BrowserSession

app = typer.Typer(
    help="demogen — generatore offline di demo realtime (motore WebGL2 dual-mode GPU/CPU)"
)


def _run(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])  # su Windows risolve npm.cmd, node.exe, ecc.
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=30)
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else "ok"
    except (OSError, subprocess.TimeoutExpired):
        return None


@app.command()
def doctor() -> None:
    """Verifica ambiente: tool, browser Playwright, renderer WebGL2 in GPU e CPU."""
    print(f"demogen {__version__} — doctor")
    print(f"python:           {sys.version.split()[0]}")
    print(f"node:             {_run(['node', '--version']) or 'MANCANTE'}")
    print(f"npm:              {_run(['npm', '--version']) or 'MANCANTE'}")
    glslang = _run(["glslangValidator", "--version"]) or "mancante (serve dalla Fase 1)"
    print(f"glslangValidator: {glslang}")
    print(f"ffmpeg:           {_run(['ffmpeg', '-version']) or 'mancante (opzionale)'}")

    for mode in ("hardware", "swiftshader"):
        channel = "chromium" if mode == "hardware" else None
        try:
            with BrowserSession(gpu=mode, headless=True, channel=channel) as sess:  # type: ignore[arg-type]
                sess.goto("harness.html")
                info = sess.harness_info()
            interesting = [
                e
                for e in info["extensions"]
                if e
                in (
                    "EXT_color_buffer_float",
                    "KHR_parallel_shader_compile",
                    "EXT_disjoint_timer_query_webgl2",
                    "WEBGL_debug_renderer_info",
                )
            ]
            print(f"\n[{mode}] renderer = {info['renderer']}")
            print(f"  webgl2={info['webgl2']}  vendor={info['vendor']}")
            print(f"  max_texture={info['maxTextureSize']}  estensioni chiave: {interesting}")
        except Exception as e:  # noqa: BLE001
            print(f"\n[{mode}] ERRORE: {e}")


def _payload_from_file(path: Path, bpm: float) -> dict:
    """Da .glsl (scena singola) o timeline.json (demo) → payload .demo."""
    from .bundle.build import build_payload
    from .glsl.treeshake import load_library, treeshake

    if path.suffix == ".json":
        return build_payload(json.loads(path.read_text(encoding="utf-8")), path.parent)
    # shader singolo: common = libreria tree-shaked, 1 scena, 16 bar
    src = path.read_text(encoding="utf-8")
    lib = load_library(Path(__file__).resolve().parent / "glsl" / "lib")
    common = treeshake(src, lib)
    return {
        "format": "demogen/1",
        "meta": {
            "title": path.stem,
            "duration_s": 32.0,
            "loop": True,
            "bpm": bpm,
            "beats_per_bar": 4,
        },
        "timeline": {
            "bpm": bpm,
            "beats_per_bar": 4,
            "scenes": [
                {
                    "id": "s1", "start_bar": 0, "bars": 16,
                    "transition_in": "cut", "transition_bars": 0,
                }
            ],
        },
        "common": common,
        "scenes": {"s1": src},
        "render": {"profile": "modern"},
        "quality": {"target_fps": 60, "min_scale": 0.5},
    }


@app.command()
def play(
    file: Path = typer.Argument(
        ..., exists=True, readable=True, help=".glsl (scena singola) o timeline.json (demo)"
    ),
    gpu: str = typer.Option("auto", help="auto | hardware | swiftshader"),
    headless: bool = typer.Option(False, help="Avvia il browser in headless"),
    bpm: float = typer.Option(120.0, help="BPM per uno shader singolo"),
) -> None:
    """Rendering realtime in una finestra del browser (server locale 127.0.0.1)."""
    payload = _payload_from_file(file, bpm)
    tmp = PLAYER_DIR / ".tmp-demo.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    with BrowserSession(gpu=gpu, headless=headless) as sess:  # type: ignore[arg-type]
        sess.goto("index.html?demo=.tmp-demo.json")
        info = sess.harness_info()
        print(f"renderer: {info['renderer']}  (gpu={gpu}, headless={headless})")
        print("Rendering realtime in corso — chiudi la finestra del browser per terminare.")
        sess.page.wait_for_event("close", timeout=0)


@app.command()
def bundle(
    spec: Path = typer.Argument(..., exists=True, readable=True, help="timeline.json della demo"),
    name: str = typer.Option("", help="Nome output (default: dal campo name della spec)"),
    out: Path = typer.Option(Path("out"), help="Cartella di output"),
    no_minify: bool = typer.Option(False, help="Disattiva il minify"),
) -> None:
    """Costruisce out/<name>.demo e out/<name>.html (standalone, funziona offline)."""
    from .bundle.build import build_payload, write_bundle

    spec_dict = json.loads(spec.read_text(encoding="utf-8"))
    payload = build_payload(spec_dict, spec.parent, do_minify=not no_minify)
    name = name or spec_dict.get("name", "demo")
    sizes = write_bundle(payload, out, name)
    print(f"demo: {sizes['paths']['demo']}  ({sizes['demo']['raw']} B, "
          f"gzip {sizes['demo']['gzip']} B)")
    print(f"html: {sizes['paths']['html']}  ({sizes['html']['raw']} B)")
    print(f"player core gzip: {sizes['player_core_gz']} B (budget 12288 B)")


@app.command()
def probe(
    file: Path = typer.Argument(..., exists=True, readable=True, help="timeline.json o .demo"),
    gpu: str = typer.Option("swiftshader", help="hardware | swiftshader"),
    frames: int = typer.Option(8, help="Numero di frame catturati"),
    width: int = typer.Option(640),
    height: int = typer.Option(360),
    out: Path = typer.Option(Path("out"), help="Cartella per i PNG"),
) -> None:
    """Carica la demo nell'harness, cattura frame + profilo ms e salva PNG in out/."""
    from .browser.harness import Harness
    from .browser.perf_lane import perf_lane

    if file.suffix == ".demo":
        payload = json.loads(file.read_text(encoding="utf-8"))
    else:
        payload = _payload_from_file(file, 120.0)
    duration = payload["meta"]["duration_s"]
    times = [round(duration * (i + 0.5) / frames, 3) for i in range(frames)]
    channel = "chromium" if gpu == "hardware" else None
    with Harness(gpu=gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
        res = h.load(payload)
        if not res["ok"]:
            print("ERRORI di compilazione:")
            for e in res["errors"]:
                print(e[:2000])
            raise typer.Exit(1)
        print(f"load ok (compile {res['compile_ms']:.1f} ms)  renderer={h.info()['renderer']}")
        pngs = h.capture(times, width, height)
        out.mkdir(parents=True, exist_ok=True)
        for i, png in enumerate(pngs):
            (out / f"probe_{file.stem}_{gpu}_f{i:02d}_t{times[i]}s.png").write_bytes(png)
        with perf_lane():
            prof = h.profile(times, width, height, repeats=3)
        print(f"profilo ({prof['method']}) a {width}x{height}:")
        for t, ms in prof["samples"].items():
            print(f"  t={t}s  {ms:.3f} ms")
        print(f"PNG salvati in {out}/")


if __name__ == "__main__":
    app()
