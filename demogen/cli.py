from __future__ import annotations

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


@app.command()
def spike() -> None:
    """Spike del motore: cattura un frame e misura ms/frame in modalità GPU e CPU (PNG in out/)."""
    from .browser.spike import run_spike

    run_spike(Path("out"))


@app.command()
def play(
    shader: Path = typer.Argument(..., exists=True, readable=True, help="File .glsl con mainImage"),
    gpu: str = typer.Option("auto", help="auto | hardware | swiftshader"),
    headless: bool = typer.Option(False, help="Avvia il browser in headless"),
) -> None:
    """Rendering realtime dello shader in una finestra del browser (server locale 127.0.0.1)."""
    tmp = PLAYER_DIR / ".spike-shader.glsl"
    tmp.write_text(shader.read_text(encoding="utf-8"), encoding="utf-8")
    with BrowserSession(gpu=gpu, headless=headless) as sess:  # type: ignore[arg-type]
        sess.goto("index.html?shader=.spike-shader.glsl")
        info = sess.harness_info()
        print(f"renderer: {info['renderer']}  (gpu={gpu}, headless={headless})")
        print("Rendering realtime in corso — chiudi la finestra del browser per terminare.")
        sess.page.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    app()
