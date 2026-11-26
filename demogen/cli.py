from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import typer

from . import __version__
from .browser.session import PLAYER_DIR, BrowserSession
from .engine import owning_timeline, payload_from_file

# console con code page legacy (cp1252 con output in pipe): un carattere non codificabile (→, ▸, ♪)
# deve diventare '?' invece di far cadere il comando con UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (getattr(_stream, "encoding", "") or "").lower() not in ("utf-8", "utf8"):
        try:
            _stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass

app = typer.Typer(
    help="demogen — offline generator of realtime demoscene demos (dual-mode WebGL2 engine, GPU/CPU)",
    pretty_exceptions_show_locals=False,  # i locals possono contenere la config (api_key)
)
models_app = typer.Typer(help="Query the configured models")
app.add_typer(models_app, name="models")

MAX_COST_HELP = "Spending cap for this run in USD (overrides budget.max_total_cost_usd)"


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
    """Check the environment: tools, Playwright browser, WebGL2 renderer on GPU and CPU."""
    print(f"demogen {__version__} — doctor")
    print(f"python:           {sys.version.split()[0]}")
    print(f"node:             {_run(['node', '--version']) or 'MISSING'}")
    print(f"npm:              {_run(['npm', '--version']) or 'MISSING'}")
    glslang = _run(["glslangValidator", "--version"]) or "mancante (serve dalla Fase 1)"
    print(f"glslangValidator: {glslang}")
    print(f"ffmpeg:           {_run(['ffmpeg', '-version']) or 'missing (optional)'}")

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
            print(f"  max_texture={info['maxTextureSize']}  key extensions: {interesting}")
        except Exception as e:  # noqa: BLE001
            print(f"\n[{mode}] ERROR: {e}")


# il motore senza CLI (anche per il server MCP); i nomi con _ restano per chi li importa (test)
_owning_timeline = owning_timeline
_payload_from_file = payload_from_file


def open_player(sess: BrowserSession, payload: dict) -> dict:
    """Apre player/index.html sul payload e attende che il player sia pronto (info renderer)."""
    tmp = PLAYER_DIR / ".tmp-demo.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    try:
        sess.goto("index.html?demo=.tmp-demo.json")
        return sess.harness_info()
    finally:
        tmp.unlink(missing_ok=True)


@app.command()
def play(
    file: Path = typer.Argument(
        ..., exists=True, readable=True,
        help=".glsl (single scene), timeline.json (demo) or a project folder (with --scene)"
    ),
    gpu: str = typer.Option("auto", help="auto | hardware | swiftshader"),
    headless: bool = typer.Option(False, help="Start the browser headless"),
    bpm: float = typer.Option(120.0, help="BPM for a single shader"),
    scene: str = typer.Option("", help="With a project folder: the scene to preview (s1, s2, ...), "
                                       "also while the project is being generated"),
    version: int = typer.Option(0, help="With --scene: the version to show (default: the best so far, "
                                        "else the latest)"),
) -> None:
    """Realtime rendering in a browser window (local server on 127.0.0.1)."""
    if file.is_dir():
        from .orchestrator.preview import scene_preview_payload

        payload, shown = _guard(lambda: scene_preview_payload(file, scene, version or None))
        print(f"preview: scene {scene} v{shown} of {file} (in a loop, with the project's style and post)")
    else:
        payload = _payload_from_file(file, bpm)
    with BrowserSession(gpu=gpu, headless=headless) as sess:  # type: ignore[arg-type]
        info = open_player(sess, payload)
        print(f"renderer: {info['renderer']}  (gpu={gpu}, headless={headless})")
        print("Realtime rendering running — close the browser window to stop.")
        sess.page.wait_for_event("close", timeout=0)


@app.command()
def bundle(
    spec: Path = typer.Argument(..., exists=True, readable=True, help="timeline.json of the demo"),
    name: str = typer.Option("", help="Output name (default: the name field of the spec)"),
    out: Path = typer.Option(Path("out"), help="Output folder"),
    no_minify: bool = typer.Option(False, help="Disable minification"),
) -> None:
    """Build out/<name>.demo and out/<name>.html (standalone, works offline)."""
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
    file: Path = typer.Argument(..., exists=True, readable=True, help="timeline.json or .demo"),
    gpu: str = typer.Option("swiftshader", help="hardware | swiftshader"),
    frames: int = typer.Option(8, help="Number of captured frames"),
    width: int = typer.Option(640),
    height: int = typer.Option(360),
    out: Path = typer.Option(Path("out"), help="Folder for the PNGs"),
) -> None:
    """Load the demo in the harness, capture frames + ms profile and save PNGs in out/."""
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
            print("Compile errors:")
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
        print(f"profile ({prof['method']}) at {width}x{height}:")
        for t, ms in prof["samples"].items():
            print(f"  t={t}s  {ms:.3f} ms")
        print(f"PNGs saved in {out}/")


@app.command()
def init(
    out: Path = typer.Option(Path("demogen.yaml"), help="Local config to create (gitignored)"),
) -> None:
    """Create demogen.yaml from the package template (demogen/demo.yaml); demogen.yaml is gitignored."""
    from .config import DEMO_TEMPLATE, warn_if_not_ignored

    if out.exists():
        print(f"{out} already exists — not overwritten.")
        raise typer.Exit(0)
    shutil.copy(DEMO_TEMPLATE, out)
    warn_if_not_ignored(out)
    print("Next steps: put the OpenRouter key in providers.openrouter.api_key,")
    print("set the models in roles/*/model. Then: demogen models check")


@models_app.command("check")
def models_check(
    config: Path | None = typer.Option(None, help="Config path (default: ./demogen.yaml)"),
    role: str | None = typer.Option(None, help="Test a single role"),
) -> None:
    """For each role: a minimal text call (+ image if vision, + schema if json_schema)."""
    import base64
    import io

    from .config import load_config
    from .llm.budget import Budget
    from .llm.capabilities import detect_capabilities
    from .llm.client import LLMClient

    cfg = load_config(config)
    budget = Budget.from_config(cfg)
    roles = [role] if role else list(cfg.roles)
    header = (
        f"{'role':<14} {'model':<28} {'text':<6} {'vision':<7} "
        f"{'json':<6} {'latency':<8} {'cost USD'}"
    )
    print(header)
    for r in roles:
        try:
            client = LLMClient(cfg, r, max_retries=1, budget=budget)
        except ValueError as e:
            print(f"{r:<14} {'-':<28} CONFIG ERROR: {e}")
            continue
        caps = detect_capabilities(cfg, r, cache_dir=Path(cfg.cache_dir))
        errors: list[tuple[str, BaseException]] = []
        # 1) testo
        try:
            resp = client.chat(
                [{"role": "user", "content": "Reply exactly: OK"}], step="models-check"
            )
            ok_text = "OK" in resp.content
            lat = f"{resp.latency_s:.2f}s"
            cost = f"{resp.cost_usd:.6f}" if resp.cost_usd is not None else "-"
        except Exception as e:  # noqa: BLE001
            print(f"{r:<14} {client.model:<28} ERROR")
            print(_llm_error_text(e, indent="    "))
            continue
        # 2) vision: immagine 64x64 rossa
        ok_vision = "-"
        if caps.vision:
            from PIL import Image

            img = Image.new("RGB", (64, 64), (255, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            try:
                vresp = client.chat(
                    [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "What color is it? Reply JSON {\"color\": \"...\"}.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    step="models-check-vision",
                )
                low = vresp.content.lower()
                ok_vision = "ok" if ("ross" in low or "red" in low) else f"? ({low[:30]!r})"
            except Exception as e:  # noqa: BLE001
                ok_vision = "ERROR"
                errors.append(("vision", e))
        # 3) json_schema
        ok_json = "-"
        if caps.json_schema:
            try:
                client.chat(
                    [{"role": "user", "content": "Return JSON {\"ok\": true}"}],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "Ping",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    step="models-check-json",
                )
                ok_json = "ok"
            except Exception as e:  # noqa: BLE001
                ok_json = "ERROR"
                errors.append(("json_schema", e))
        row = (
            f"{r:<14} {client.model:<28} {'ok' if ok_text else 'NO':<6} "
            f"{ok_vision:<7} {ok_json:<6} {lat:<8} {cost}"
        )
        print(row)
        for what, e in errors:
            print(f"    [{what}]")
            print(_llm_error_text(e, indent="    "))


def _llm_error_text(e: BaseException, indent: str = "") -> str:
    """Errore del provider spiegato (titolo, messaggio vero, cosa fare); gli altri come testo."""
    from .llm.errors import describe_llm_error

    info = describe_llm_error(e)
    text = info.text() if info is not None else f"ERROR: {type(e).__name__}: {e}"
    return "\n".join(indent + line for line in text.splitlines())


def _try_config() -> object | None:
    """Config se esiste, altrimenti None (inspect/gates funzionano con i default)."""
    from .config import load_config

    try:
        return load_config(None, interactive=False)
    except FileNotFoundError:
        return None


@app.command()
def inspect(
    file: Path = typer.Argument(..., exists=True, readable=True, help=".glsl | timeline.json | .demo"),
    gpu: str = typer.Option("swiftshader", help="hardware | swiftshader"),
    frames: int = typer.Option(16, help="Number of captured keyframes"),
    width: int = typer.Option(480),
    height: int = typer.Option(270),
    out: Path = typer.Option(Path("out"), help="Report folder"),
) -> None:
    """Load the demo in the harness, compute metrics + gates, save sheets and the report in out/."""
    from .browser.harness import Harness
    from .engine import CompileFailed, default_config, inspect_payload

    payload = payload_from_file(file, 120.0)
    channel = "chromium" if gpu == "hardware" else None
    with Harness(gpu=gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
        try:
            rep = inspect_payload(h, payload, width=width, height=height, frames=frames, cfg=default_config(),
                                  report_dir=out / f"inspect_{file.stem}")
        except CompileFailed as e:
            print("Compile errors:")
            for err in e.errors:
                print(err[:2000])
            raise typer.Exit(1) from None

    vm, pf, fl = rep.metrics["video"], rep.metrics["perf"], rep.metrics["flash"]
    print(f"inspect {file.name}  gpu={rep.renderer}")
    print(f"  video: luma_mean={vm['luma_mean']:.3f} black={vm['black_ratio']:.3f} "
          f"nan={vm['nan_ratio']:.4f} flicker={vm['flicker_score']:.4f}")
    print(f"  perf:  p95={pf['p95_ms']:.2f} ms  mean={pf['mean_ms']:.2f} ms  "
          f"load={pf['gpu_load_est']:.0%}  ({pf['method']}, fixed cost {pf['fixed_ms']:.2f} ms subtracted)")
    print(f"  flash: passed={fl['passed']} max/s={fl['max_flashes_per_s']:.1f} red={fl['red_flash_events']}")
    if "audio" in rep.metrics:
        am = rep.metrics["audio"]
        obe = am["onset_vs_beat"]
        print(f"  audio: rms={am['rms']:.3f} peak={am['peak']:.3f} "
              f"onsets={obe['n_onsets']} err_vs_beat mean="
              f"{obe['mean_abs_err_ms'] if obe['mean_abs_err_ms'] is not None else float('nan'):.2f} ms")
    print(f"  gate:  {len(rep.issues)} issue ({rep.blockers} blocker, {rep.majors} major)")
    for i in rep.issues:
        print(f"    [{i.severity}] {i.description}")
    print(f"  report: {rep.report_dir}/ ({', '.join(rep.files)})")


@app.command()
def calibrate(
    gpu: str = typer.Option("hardware", help="hardware | swiftshader"),
    width: int = typer.Option(1920),
    height: int = typer.Option(1080),
    out: Path = typer.Option(Path("out"), help="Where to save calibrate.json"),
) -> None:
    """Measure the example shaders at the reference resolution and save out/calibrate.json."""
    import json as _json

    from .browser.harness import Harness
    from .browser.perf_lane import perf_lane

    shaders = sorted((Path(__file__).resolve().parents[1] / "examples" / "shaders").glob("*.glsl"))
    channel = "chromium" if gpu == "hardware" else None
    results: dict = {"gpu_mode": gpu, "resolution": [width, height], "shaders": {}}
    for sh in shaders:
        payload = _payload_from_file(sh, 120.0)
        with Harness(gpu=gpu, headless=True, channel=channel) as h:  # type: ignore[arg-type]
            res = h.load(payload)
            if not res["ok"]:
                results["shaders"][sh.stem] = {"ok": False, "errors": res["errors"]}
                continue
            info = h.info()
            with perf_lane():
                prof = h.profile([1.0, 2.0, 3.0], width, height, repeats=5)
            results["shaders"][sh.stem] = {
                "ok": True,
                "renderer": info["renderer"],
                "method": prof["method"],
                "samples": prof["samples"],
            }
            print(f"{sh.stem:<18} renderer={info['renderer'][:40]}  samples={prof['samples']}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "calibrate.json").write_text(_json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {out}/calibrate.json")


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Text prompt of the demo"),
    duration: float = typer.Option(30.0, help="Duration in seconds"),
    bpm: float = typer.Option(128.0),
    profile: str = typer.Option("modern", help="modern | retro: the style of every scene (the LLM cannot change it)"),
    loop: bool | None = typer.Option(None, "--loop/--no-loop",
                                     help="Loop forever at the end (default: as the prompt asks)"),
    project: Path | None = typer.Option(None, help="Project folder (default: projects/<date>_<slug>)"),
    fake: bool = typer.Option(False, help="Deterministic fake LLM (smoke test, no real API)"),
    gpu: str = typer.Option("swiftshader", help="hardware | swiftshader"),
    plain: bool = typer.Option(False, "--plain", help="Plain text log, no live panel"),
    max_cost: float | None = typer.Option(None, "--max-cost", help=MAX_COST_HELP),
    music: str = typer.Option("", "--music", help="Prompt for the music (genre, instruments, mood); "
                              "empty = from the demo prompt"),
    no_music: bool = typer.Option(False, "--no-music", help="Demo without a soundtrack"),
    review_plan: bool = typer.Option(False, "--review-plan",
                                     help="Stop after the plan (scenes, timing, palette: one LLM call) to read and "
                                          "change it with `demogen plan`, then continue with `demogen resume`"),
) -> None:
    """Full pipeline: prompt -> spec -> style -> shaders and music -> compile -> probe -> critique -> bundle."""
    from .orchestrator.plan import format_plan, is_paused_for_plan, next_steps
    from .project.store import Project, new_project_dir

    proj = Project(project or new_project_dir(prompt))
    pipe = _pipeline(proj, gpu, fake, max_cost)
    spec = _execute(lambda: pipe.run(prompt, duration_s=duration, bpm=bpm, profile=profile, loop=loop,
                                     audio=not no_music, music=music, pause_after_plan=review_plan),
                    "generate", plain, proj.path)
    if is_paused_for_plan(proj.path):
        print(format_plan(spec))
        print(next_steps(proj.path, editable=True))
        return
    print(f"project: {proj.path}")
    print(f"spec: {spec.title} — {len(spec.scenes)} scenes, {spec.duration_s:.1f}s, bpm {spec.timeline.bpm}")
    print(f"report: {proj.path / 'report.md'}")


def _pipeline(proj, gpu: str, fake: bool, max_cost: float | None = None):
    from .config import Config, load_config
    from .llm.fake import fake_client_factory
    from .orchestrator.pipeline import Pipeline

    if fake:
        return Pipeline(proj, Config.model_validate({"providers": {}, "roles": {}}), gpu=gpu,
                        client_factory=fake_client_factory)
    cfg = load_config(None)
    if max_cost is not None:
        if max_cost <= 0:
            raise typer.BadParameter("--max-cost must be > 0")
        cfg.budget.max_total_cost_usd = max_cost
    return Pipeline(proj, cfg, gpu=gpu)


def _guard(fn, project: Path | None = None):
    """Errori attesi della pipeline e del provider LLM → messaggio chiaro ed exit code 1, niente
    traceback. Lo stato è già salvato: `demogen resume` riparte senza rifare le chiamate fatte."""
    from . import progress
    from .llm.errors import describe_llm_error
    from .orchestrator.steps import PipelineError

    then = (f"continue with `demogen resume {project}` (menu: Resume): calls already made are not repeated"
            if project is not None else "")
    try:
        return fn()
    except PipelineError as e:
        progress.emit("error", title="the pipeline stopped", detail=str(e)[:600], hint="", where="")
        print(f"ERROR: {e}", file=sys.stderr)
        raise typer.Exit(1) from e
    except Exception as e:
        info = describe_llm_error(e)
        if info is None:
            raise  # non è un errore del provider: traceback normale
        progress.emit("error", title=info.title, detail=info.detail, hint=info.hint, where=info.where)
        print(info.text(then), file=sys.stderr)
        raise typer.Exit(1) from e


def _execute(fn, mode: str, plain: bool, project: Path | None = None):
    """Esegue la pipeline: in un terminale con il pannello dal vivo, altrimenti (output rediretto,
    --plain o DEMOGEN_PLAIN=1) con il solo log testuale."""
    import os

    if plain or os.environ.get("DEMOGEN_PLAIN") or not sys.stdout.isatty():
        return _guard(fn, project)
    from .dashboard import Dashboard

    with Dashboard(mode):
        return _guard(fn, project)


@app.command()
def resume(
    project: Path = typer.Argument(..., exists=True, help="Project folder"),
    gpu: str = typer.Option("swiftshader"),
    fake: bool = typer.Option(False, help="Deterministic fake LLM (smoke test, no real API)"),
    plain: bool = typer.Option(False, "--plain", help="Plain text log, no live panel"),
    max_cost: float | None = typer.Option(None, "--max-cost", help=MAX_COST_HELP),
) -> None:
    """Resume a project from state.json without redoing completed steps (or LLM calls)."""
    from .project.store import Project

    pipe = _pipeline(Project(project), gpu, fake, max_cost)
    _execute(pipe.resume, "resume", plain, project)


@app.command()
def plan(
    project: Path = typer.Argument(..., exists=True, file_okay=False, help="Project folder"),
    scene: str = typer.Option("", help="Scene to change (s1, s2, ...)"),
    title: str | None = typer.Option(None, help="New title of --scene"),
    description: str | None = typer.Option(None, help="New description of --scene: what you see"),
    motion: str | None = typer.Option(None, help="New motion of --scene: how it moves, how it follows the beat"),
    note: str = typer.Option("", help="A change to the whole plan, applied by the LLM (one call)"),
    fake: bool = typer.Option(False, help="Deterministic fake LLM for --note (smoke test, no real API)"),
    max_cost: float | None = typer.Option(None, "--max-cost", help=MAX_COST_HELP),
    hints: bool = typer.Option(True, "--hints/--no-hints", hidden=True,
                               help="Print the next commands (the menu offers its own choices)"),
) -> None:
    """Show a project's plan (scenes, timing, palette) and change it before the drawing starts."""
    from .orchestrator.plan import edit_plan, format_plan, load_plan, next_steps, plan_editable
    from .project.store import Project

    proj = Project(project)
    fields = {"title": title, "description": description, "motion": motion}
    edits = {k: v for k, v in fields.items() if v is not None}
    if note and (scene or edits):
        raise typer.BadParameter("use either --note (the LLM rewrites the plan) or --scene with "
                                 "--title/--description/--motion (you change it), not both")
    if edits and not scene:
        raise typer.BadParameter("--title, --description and --motion need --scene")
    if scene and not edits:
        raise typer.BadParameter("--scene needs what to change: --title, --description or --motion")
    if note:
        pipe = _pipeline(proj, "swiftshader", fake, max_cost)
        print("the LLM is rewriting the plan with your note...")
        spec = _guard(lambda: pipe.replan(note))
        print("plan updated\n")
    elif scene:
        spec = _guard(lambda: edit_plan(proj, scene, **edits))
        print(f"plan updated: {', '.join(edits)} of {scene}\n")
    else:
        spec = _guard(lambda: load_plan(proj))
    print(format_plan(spec))
    if hints:
        print(next_steps(proj.path, plan_editable(proj.load_state())))


@app.command()
def revise(
    project: Path = typer.Argument(..., exists=True),
    scene: str = typer.Option(..., help="scene id (s1, s2, ...)"),
    note: str = typer.Option(..., help="Revision note (e.g. 'less fog, more contrast on the kick')"),
    gpu: str = typer.Option("swiftshader"),
    fake: bool = typer.Option(False, help="Deterministic fake LLM (smoke test, no real API)"),
    plain: bool = typer.Option(False, "--plain", help="Plain text log, no live panel"),
    max_cost: float | None = typer.Option(None, "--max-cost", help=MAX_COST_HELP),
) -> None:
    """Targeted revision of a scene from a text note (new version max+1), then a new bundle."""
    from .project.store import Project

    pipe = _pipeline(Project(project), gpu, fake, max_cost)
    _execute(lambda: pipe.run_revise(scene, note), "revise", plain, project)


@app.command()
def music(
    project: Path = typer.Argument(..., exists=True, help="Project folder"),
    prompt: str = typer.Option("", "--prompt", help="What you want to hear (genre, instruments, mood); "
                               "empty = from the demo prompt"),
    gpu: str = typer.Option("swiftshader"),
    fake: bool = typer.Option(False, help="Deterministic fake LLM (smoke test, no real API)"),
    plain: bool = typer.Option(False, "--plain", help="Plain text log, no live panel"),
    max_cost: float | None = typer.Option(None, "--max-cost", help=MAX_COST_HELP),
) -> None:
    """(Re)compose the soundtrack of a project from a prompt, listen to it and rebuild the bundle."""
    from .project.store import Project

    pipe = _pipeline(Project(project), gpu, fake, max_cost)
    if _execute(lambda: pipe.run_music(prompt), "musica", plain, project):
        out = sorted((Path(project) / "out").glob("*.html"))
        print(f"music ready in the bundle: {out[-1] if out else Path(project) / 'out'}")


def budget_summary(cfg) -> dict:
    """Tetti di consumo LLM e spesa (oggi, mese, per progetto nel mese) dal registro locale."""
    from datetime import datetime

    from .llm.budget import ledger_path, read_ledger, spend_totals

    rows = read_ledger(ledger_path(cfg))
    today, month = spend_totals(rows)
    ym = datetime.now().strftime("%Y-%m")
    per_project: dict[str, float] = {}
    for r in rows:
        if str(r.get("ts", "")).startswith(ym):
            key = str(r.get("project") or "-")
            per_project[key] = per_project.get(key, 0.0) + float(r["cost"])
    b = cfg.budget
    return {
        "caps": {"run": b.max_total_cost_usd, "daily": b.max_daily_cost_usd, "monthly": b.max_monthly_cost_usd,
                 "calls": b.max_calls_per_run, "minutes": b.max_wall_minutes},
        "today": round(today, 6),
        "month": round(month, 6),
        "projects": dict(sorted(per_project.items(), key=lambda kv: -kv[1])),
    }


@app.command()
def budget(
    run: float | None = typer.Option(None, "--run", help="Cap per run in USD"),
    daily: float | None = typer.Option(None, "--daily", help="Daily cap in USD across all runs (0 = no cap)"),
    monthly: float | None = typer.Option(None, "--monthly", help="Monthly cap in USD across all runs (0 = no cap)"),
    calls: int | None = typer.Option(None, "--calls", help="Max LLM calls per run (0 = no cap)"),
    minutes: float | None = typer.Option(None, "--minutes", help="Max minutes per run"),
    config: Path = typer.Option(Path("demogen.yaml"), help="Config file"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Show LLM spending (today, this month, per project) and the spending caps; set caps with the options."""
    import json as _json

    from .config import set_budget_values

    if not config.exists():
        print(f"ERROR: {config} not found: create it with `demogen init`", file=sys.stderr)
        raise typer.Exit(1)
    changes: dict[str, object] = {}
    if run is not None:
        if run <= 0:
            raise typer.BadParameter("--run must be > 0")
        changes["max_total_cost_usd"] = float(run)
    for key, val in (("max_daily_cost_usd", daily), ("max_monthly_cost_usd", monthly)):
        if val is not None:
            if val < 0:
                raise typer.BadParameter("caps must be >= 0 (0 = no cap)")
            changes[key] = float(val) if val > 0 else None
    if calls is not None:
        changes["max_calls_per_run"] = int(calls) if calls > 0 else None
    if minutes is not None:
        if minutes <= 0:
            raise typer.BadParameter("--minutes must be > 0")
        changes["max_wall_minutes"] = float(minutes)
    if changes:
        try:
            set_budget_values(config, changes)
        except Exception as e:  # noqa: BLE001 - il file resta com'era
            print(f"ERROR: could not update {config}: {e}", file=sys.stderr)
            raise typer.Exit(1) from e
    from .config import load_config

    s = budget_summary(load_config(config, interactive=False))
    if as_json:
        print(_json.dumps(s))
        return
    if changes:
        print(f"updated {config}: " + ", ".join(f"{k}={'none' if v is None else v}" for k, v in changes.items()))

    def cap(v, unit=" USD") -> str:
        return "no cap" if v is None else f"{v:g}{unit}"

    c = s["caps"]
    print("LLM spending caps")
    print(f"  per run      {cap(c['run'])}")
    print(f"  per day      {cap(c['daily']):<14}  spent today       {s['today']:.4f} USD")
    print(f"  per month    {cap(c['monthly']):<14}  spent this month  {s['month']:.4f} USD")
    print(f"  calls/run    {cap(c['calls'], '')}")
    print(f"  minutes/run  {cap(c['minutes'], '')}")
    if s["projects"]:
        print("This month by project:")
        for name, usd in list(s["projects"].items())[:10]:
            print(f"  {name:<44} {usd:.4f} USD")
    print("(the spending log starts with the first call made after this feature was added)")


@app.command()
def report(project: Path = typer.Argument(..., exists=True)) -> None:
    """Print the report.md of the project."""
    from .project.report import build_report

    print(build_report(project))


@app.command()
def mcp(
    root: Path = typer.Option(Path("."), help="Workspace root: tool paths are relative to it and cannot leave it"),
    gpu: str = typer.Option("hardware", help="hardware (falls back to swiftshader) | swiftshader"),
    out: Path | None = typer.Option(None, help="Output folder (default: <root>/out/mcp)"),
) -> None:
    """MCP server on stdio: an external agent writes shaders, style and timeline; demogen compiles,
    renders, measures (gates) and bundles them. No LLM on the demogen side."""
    from .mcp_server import run_stdio

    if gpu not in ("hardware", "swiftshader"):
        raise typer.BadParameter("--gpu must be hardware or swiftshader")
    run_stdio(root, gpu, out)


@app.command()
def menu(
    action: str = typer.Option("", "--action", help="Run one menu entry by name or number, no menu ('list' = all)"),
    yes: bool = typer.Option(False, "--yes", help="With --action: answer yes to confirmations"),
) -> None:
    """Interactive control deck: the whole app in one menu (`npm run menu` or run.cmd starts it)."""
    from .menu import main as menu_main

    raise typer.Exit(menu_main(action, yes))


if __name__ == "__main__":
    app()
