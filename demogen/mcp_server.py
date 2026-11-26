"""Server MCP: demogen come motore puro (Fase 9).

Un agente esterno (Claude Code, Claude Desktop, un altro client MCP) scrive shader, style e timeline
come file e usa questi strumenti per compilarli, vederli e misurarli. demogen non chiama nessun LLM:
niente chiavi, niente spesa; restano le stesse misure e gli stessi gate della pipeline.

Avvio (trasporto stdio): `uv run demogen mcp [--root CARTELLA] [--gpu hardware|swiftshader]`.

- I percorsi degli strumenti sono relativi a `--root` (la cartella del progetto dell'agente) e non ne
  possono uscire; gli esempi di demogen (`examples/`) si leggono sempre.
- I risultati (fotogrammi, rapporti, bundle) vanno in `<root>/out/mcp/`.
- Il browser dell'harness (Playwright sincrono) vive su un thread suo, aperto alla prima richiesta e
  riusato: avviarlo costa un paio di secondi, una richiesta successiva no.
"""

from __future__ import annotations

import io
import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage
from PIL import ImageDraw

from .bundle.build import build_payload, build_payload_from_sources, write_bundle
from .engine import CompileFailed, default_config, inspect_payload, owning_timeline, payload_from_file
from .glsl.docs import generate_api_reference
from .glsl.treeshake import load_library, treeshake

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
LIB_DIR = Path(__file__).resolve().parent / "glsl" / "lib"
DEFAULT_STYLE = EXAMPLES / "common.glsl"
SRC_STYLE, SRC_SCENE = 1, 2  # come la pipeline: `#line 1 N` attribuisce gli errori al file giusto
_ERR_LINE = re.compile(r"ERROR:\s*(\d+):(\d+):\s*(.*)")
_SRC_MARK = re.compile(r"--- (?:sorgente|source) ---")
MAX_ERRORS = 30

T = TypeVar("T")


# ---------------------------------------------------------------------------------------- browser
class Renderer:
    """L'harness su un thread dedicato: Playwright sincrono va usato sempre dallo stesso thread, mentre
    l'SDK MCP esegue gli strumenti sincroni su thread di un pool."""

    def __init__(self, gpu: str = "hardware") -> None:
        self.gpu = gpu
        self.renderer = ""
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demogen-harness")
        self._h = None
        self._lock = threading.Lock()

    def run(self, fn: Callable[[Any], T]) -> T:
        with self._lock:
            return self._pool.submit(self._call, fn).result()

    def _call(self, fn: Callable[[Any], T]) -> T:
        if self._h is None:
            self._open()
        try:
            return fn(self._h)
        except Exception:
            # browser chiuso o caduto: alla prossima richiesta se ne apre un altro
            if self._h is not None and self._h.page.is_closed():
                self._close()
            raise

    def _open(self) -> None:
        from .browser.harness import Harness

        modes = [self.gpu] + (["swiftshader"] if self.gpu == "hardware" else [])
        last: Exception | None = None
        for mode in modes:
            h = Harness(gpu=mode, headless=True, channel="chromium" if mode == "hardware" else None)  # type: ignore[arg-type]
            try:
                h.__enter__()
            except Exception as e:  # noqa: BLE001 - GPU non disponibile: si prova la CPU
                last = e
                continue
            self._h = h
            self.renderer = str(h.info().get("renderer", ""))
            return
        raise ToolError(f"cannot start the browser harness: {last}")

    def _close(self) -> None:
        if self._h is not None:
            try:
                self._h.__exit__(None, None, None)
            finally:
                self._h = None

    def close(self) -> None:
        try:
            self._pool.submit(self._close).result(timeout=30)
        finally:
            self._pool.shutdown(wait=False)


# ---------------------------------------------------------------------------------------- input
class Workspace:
    """Percorsi degli strumenti: relativi a `root` e confinati lì (più gli esempi di demogen)."""

    def __init__(self, root: Path, out: Path | None = None) -> None:
        self.root = root.resolve()
        self.out = (out or self.root / "out" / "mcp").resolve()

    def allowed(self, p: Path) -> bool:
        p = p.resolve()
        return p.is_relative_to(self.root) or p.is_relative_to(EXAMPLES.resolve())

    def resolve(self, path: str) -> Path:
        p = Path(path)
        p = (p if p.is_absolute() else self.root / p).resolve()
        if not self.allowed(p):
            raise ToolError(f"{path}: outside the workspace root {self.root} (and demogen's examples/)")
        if not p.is_file():
            raise ToolError(f"{path}: file not found (resolved to {p})")
        return p

    def check_timeline(self, tl: Path) -> dict:
        """La timeline e i file a cui rimanda (scene, style, audio) devono stare negli stessi confini:
        un `src` come "../../segreto" farebbe leggere un file qualunque, che tornerebbe all'agente
        negli errori di compilazione. Ritorna lo spec."""
        if not self.allowed(tl):
            raise ToolError(f"{tl}: timeline outside the workspace root {self.root}")
        try:
            spec = json.loads(tl.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ToolError(f"{self.rel(tl)}: {e}") from None
        if not isinstance(spec, dict):
            raise ToolError(f"{self.rel(tl)}: the timeline is not a JSON object")
        refs = [s.get("src") if isinstance(s, dict) else None for s in spec.get("scenes", [])]
        refs += [spec.get("common"), spec.get("audio")]
        for ref in refs:
            if ref is None:
                continue
            if not isinstance(ref, str) or not self.allowed(tl.parent / ref):
                raise ToolError(f"{self.rel(tl)}: {ref!r} is outside the workspace root {self.root}")
        return spec

    def nearby_style(self, shader: Path) -> Path:
        """Style di uno shader senza timeline: common.glsl vicino (dentro i confini) o quello degli esempi."""
        for cand in (shader.parent / "common.glsl", shader.parent.parent / "common.glsl"):
            if cand.exists() and self.allowed(cand):
                return cand
        return DEFAULT_STYLE

    def payload(self, p: Path) -> dict:
        """Payload di un file già confinato, controllando anche i file a cui rimanda."""
        if p.suffix == ".demo":  # sorgenti già dentro il payload: nessun file da leggere
            return payload_from_file(p)
        if p.suffix == ".json":
            spec = self.check_timeline(p)
            return build_payload(spec, p.parent)
        owner = owning_timeline(p)
        if owner is not None:
            self.check_timeline(owner[0])
            return payload_from_file(p)
        style = self.nearby_style(p)
        return inline_payload(p.read_text(encoding="utf-8"), style.read_text(encoding="utf-8"), seconds=32.0)

    def out_dir(self, *parts: str) -> Path:
        d = self.out.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(p)


def inline_payload(shader: str, style: str = "", *, bpm: float = 120.0, seconds: float = 8.0,
                   profile: str = "modern", text: str | None = None) -> dict:
    """Payload mono-scena da sorgenti in memoria, con `#line` per gli errori (scena 2, style 1)."""
    if profile not in ("modern", "retro"):
        raise ToolError(f"profile must be modern or retro, not {profile!r}")
    if style.strip() == "":
        style = DEFAULT_STYLE.read_text(encoding="utf-8")
    bars = max(seconds, 0.5) * bpm / 60.0 / 4.0
    render: dict[str, Any] = {"profile": profile}
    if profile == "retro":
        render["retro"] = {"internal_resolution": [320, 180], "upscale": "nearest"}
    lib = load_library(LIB_DIR)
    common = treeshake(shader + "\n" + style, lib) + f"\n#line 1 {SRC_STYLE}\n" + style
    return {
        "format": "demogen/1",
        "meta": {"title": "inline", "duration_s": bars * 4 * 60.0 / bpm, "loop": False, "bpm": bpm,
                 "beats_per_bar": 4},
        "timeline": {"bpm": bpm, "beats_per_bar": 4, "scenes": [
            {"id": "s1", "start_bar": 0, "bars": bars, "transition_in": "cut", "transition_bars": 0}]},
        "common": common,
        "scenes": {"s1": f"#line 1 {SRC_SCENE}\n" + shader},
        "render": render,
        "text": text,
        "post": {},
        "quality": {"target_fps": 60, "min_scale": 0.25},
    }


def parse_errors(errors: list[str], scene_file: str, style_file: str) -> list[str]:
    """Log del compilatore → "file:riga: messaggio" (sorgente completo accodato tolto)."""
    out: list[str] = []
    for e in errors:
        log = _SRC_MARK.split(str(e), 1)[0]
        matched = False
        for line in log.splitlines():
            m = _ERR_LINE.search(line)
            if not m:
                continue
            matched = True
            src_no, ln, msg = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            where = {SRC_SCENE: scene_file, SRC_STYLE: style_file}.get(src_no, "(header/library)")
            out.append(f"{where}:{ln}: {msg}")
        if not matched:
            out.append(log.strip()[:1000])
    return out[:MAX_ERRORS]


def scene_sources(tl_path: Path, ws: Workspace) -> tuple[dict, list[tuple[str, Path]], Path | None]:
    """(spec, [(id scena, file)], file dello style) di una timeline, con i riferimenti già confinati."""
    spec = ws.check_timeline(tl_path)
    scenes = [(str(s["id"]), (tl_path.parent / s["src"]).resolve()) for s in spec.get("scenes", [])]
    style = (tl_path.parent / spec["common"]).resolve() if spec.get("common") else None
    return spec, scenes, style


def debug_payloads(path: Path, ws: Workspace) -> list[tuple[str, str, dict]]:
    """Per `validate`: un payload per scena, non minificato e con `#line`, così ogni errore punta a
    file e riga veri. Ritorna [(file scena, file style, payload)]."""
    from .glsl.preprocessor import preprocess

    if path.suffix == ".glsl":
        owner = owning_timeline(path)
        if owner is None:  # shader sciolto: style common.glsl vicino (nei confini) o quello degli esempi
            style_path = ws.nearby_style(path)
            payload = inline_payload(path.read_text(encoding="utf-8"), style_path.read_text(encoding="utf-8"))
            return [(ws.rel(path), ws.rel(style_path), payload)]
        tl_path = owner[0]
        only: str | None = str(owner[2]["id"])
    else:
        tl_path, only = path, None
    spec, scenes, style_path = scene_sources(tl_path, ws)
    style = preprocess(style_path.read_text(encoding="utf-8"), base_dir=tl_path.parent)[0] if style_path else ""
    out = []
    lib = load_library(LIB_DIR)
    for sid, src_path in scenes:
        if only is not None and sid != only:
            continue
        src = src_path.read_text(encoding="utf-8")
        common = treeshake(src + "\n" + style, lib) + f"\n#line 1 {SRC_STYLE}\n" + style
        one = {**next(s for s in spec["scenes"] if str(s["id"]) == sid),
               "start_bar": 0, "transition_in": "cut", "transition_bars": 0}
        payload = build_payload_from_sources({**spec, "scenes": [one]}, {sid: f"#line 1 {SRC_SCENE}\n" + src},
                                             "", do_minify=False)
        payload["common"] = common
        out.append((ws.rel(src_path), ws.rel(style_path) if style_path else "(none)", payload))
    return out


# ---------------------------------------------------------------------------------------- immagini
def preview_image(img: PILImage.Image, max_width: int = 1280) -> Image:
    """Immagine per l'agente: JPEG e al più `max_width` px (un foglio PNG di 16 fotogrammi pesava 2 MB);
    i PNG a piena risoluzione restano su disco."""
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return Image(data=buf.getvalue(), format="jpeg")


def frame_sheet(pngs: list[bytes], times: list[float], cols: int = 2) -> PILImage.Image:
    """Fotogrammi in griglia con il tempo sopra ciascuno (una sola immagine da mandare all'agente)."""
    frames = [PILImage.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    cols = max(1, min(cols, len(frames)))
    rows = (len(frames) + cols - 1) // cols
    w, h = frames[0].size
    sheet = PILImage.new("RGB", (cols * w, rows * (h + 16)), (12, 12, 12))
    d = ImageDraw.Draw(sheet)
    for i, (f, t) in enumerate(zip(frames, times, strict=True)):
        x, y = (i % cols) * w, (i // cols) * (h + 16)
        d.text((x + 4, y + 2), f"t={t:g}s", fill=(255, 230, 120))
        sheet.paste(f, (x, y + 16))
    return sheet


# ---------------------------------------------------------------------------------------- guida
GUIDE = """# demogen engine — guide for an external agent

demogen is a realtime WebGL2 demo engine. You write the shaders, the style and the timeline as files;
the tools of this server compile them, render frames, measure them against the same gates the built-in
pipeline uses, and bundle the result. No LLM runs on the demogen side.

## Workflow
1. `guide` (this text) and `glsl_library` (functions you can call without defining them).
2. Write the files (paths relative to the workspace root): a timeline JSON, a style GLSL (`common`), one
   GLSL file per scene. Start from an example: {examples}.
3. `validate` until it compiles (errors come back as `file:line: message`).
4. `render` to look at frames, `inspect` for the gates (NaN, black, flicker, loop seam, flashes, perf).
5. `verify_math` for formulas whose correctness matters (exact SDF, Lipschitz bound, period, easing).
6. `bundle` → `.demo` payload + standalone `.html`.

## Files
- Timeline JSON: `{{"name", "bpm", "beats_per_bar": 4, "loop": bool, "common": "style.glsl",
  "text": "scroller text (retro, <= 256 bytes)", "render": {{"profile": "modern" | "retro",
  "retro": {{"internal_resolution": [320, 180], "upscale": "nearest"}}, "overrides": {{"<scene id>": "retro"}}}},
  "post": {{"bloom": {{"threshold": 0.8, "intensity": 0.5}}}}, "quality": {{"target_fps": 60, "min_scale": 0.5}},
  "scenes": [{{"id": "s1", "src": "shaders/s1.glsl", "start_bar": 0, "bars": 8,
  "transition_in": "cut" | "crossfade" | "flash" | "fade_black", "transition_bars": 0}}]}}`.
  Duration = (last start_bar + bars) * beats_per_bar * 60 / bpm.
- Style (`common`): shared by all scenes. It must define `vec3 finalize(vec3 col, vec2 uv)` (tone map /
  gamma for modern; `retroFinalize(col, uv, gl_FragCoord.xy, PALETTE, PALETTE_N)` for retro) and
  `const vec3 PALETTE[16]` + `const int PALETTE_N`. See `examples/common.glsl`.
- Scene file: helper functions + `void mainImage(out vec4 fragColor, in vec2 fragCoord)` ending with
  `fragColor = vec4(finalize(col, uv), 1.0);`. Library functions are added automatically when you call
  them (no `#include`); do not redefine a library function. Raymarching scenes define `float map(vec3 p)`.

{contract}
## Gates (what `inspect` checks)
- blocker: NaN/Inf pixels; black frames (luma < 0.02 on >= 98% of pixels; >= 90% is major); flashes
  over {flash} per second on 2.8% of the screen or red flashes (WCAG 2.3.1); perf over budget on a real GPU.
- minor: flicker between consecutive frames > 0.02; loop seam (looping demos) > 4x the typical frame change.
- perf budget (real GPU): modern p95 {modern_p95} ms at 1920x1080, retro p95 {retro_p95} ms at 320x180;
  the fixed cost of a measurement (an empty scene) is subtracted first. On SwiftShader (CPU) perf is
  informational only.
"""


def render_guide() -> str:
    from .orchestrator.prompts import render as render_prompt

    contract = render_prompt("system_contract.md.j2", bpm="<bpm of the timeline>", api_ref="", scene_id="-")
    start = contract.index("## Provided uniforms / defines")
    end = contract.index("## Library API reference")
    cfg = default_config()
    examples = ", ".join(f"`examples/{p.name}`" for p in sorted(EXAMPLES.glob("*timeline*.json")))
    return GUIDE.format(
        examples=examples,
        contract=contract[start:end].strip() + "\n",
        flash=cfg.safety.flash_max_per_s,
        modern_p95=cfg.realtime.profiles["modern"]["p95"],
        retro_p95=cfg.realtime.profiles["retro"]["p95"],
    )


def library_reference(query: str = "") -> str:
    """Riferimento API della libreria, intero o solo le voci che contengono `query`."""
    md = generate_api_reference(LIB_DIR)
    if not query.strip():
        return md
    q = query.lower()
    parts = re.split(r"(?m)^(?=### )", md)
    hits = [p.strip() for p in parts[1:] if q in p.lower()]
    return "\n\n".join(hits) if hits else f"No library function matches {query!r}."


# ---------------------------------------------------------------------------------------- server
def build_server(root: Path, gpu: str = "hardware", out: Path | None = None) -> tuple[MCPServer, Renderer]:
    """Il server MCP con i suoi strumenti; il Renderer va chiuso alla fine (`renderer.close()`)."""
    ws = Workspace(root, out)
    renderer = Renderer(gpu)
    server = MCPServer(
        name="demogen",
        title="demogen engine",
        instructions=(
            "demogen is a realtime WebGL2 demo engine. Call `guide` first: you write shaders, style and "
            "timeline as files, these tools compile, render, measure (gates) and bundle them. Paths are "
            f"relative to {ws.root}; outputs go to {ws.rel(ws.out)}."
        ),
    )

    def source_payload(path: str, shader: str, style: str, seconds: float, profile: str) -> tuple[dict, str]:
        """(payload, nome) da un file del progetto o da uno shader in linea."""
        if path and shader:
            raise ToolError("pass either `path` or `shader`, not both")
        if path:
            p = ws.resolve(path)
            try:
                return ws.payload(p), p.stem.replace(".timeline", "")
            except (ValueError, KeyError, OSError) as e:
                raise ToolError(f"{path}: {e}") from None
        if shader:
            return inline_payload(shader, style, seconds=seconds, profile=profile), "inline"
        raise ToolError("pass `path` (a .glsl, timeline .json or .demo file) or `shader` (GLSL source)")

    def compile_or_raise(h, payload: dict, scene_file: str, style_file: str) -> dict:
        res = h.load(payload)
        if not res["ok"]:
            raise ToolError("does not compile (`validate` gives file:line errors):\n"
                            + "\n".join(parse_errors(res["errors"], scene_file, style_file)))
        return res

    @server.tool()
    def guide() -> str:
        """How to write a demo for this engine: workflow, files (timeline, style, scenes), the GLSL
        contract (uniforms, hard rules) and the gates `inspect` applies. Read it before writing code."""
        return render_guide()

    @server.tool()
    def glsl_library(query: str = "") -> str:
        """Reference of the GLSL library (noise, sdf, raymarch, palette, post, retro font/effects...).
        These functions are added automatically when a scene calls them. `query` filters by name or
        description (e.g. "noise", "sdBox", "retro")."""
        return library_reference(query)

    @server.tool()
    def validate(path: str = "", shader: str = "", style: str = "", profile: str = "modern") -> dict:
        """Compile in the real player (WebGL2 in Chromium) and report errors as `file:line: message`.

        `path`: a timeline .json (every scene is checked, then the minified bundle), a scene .glsl
        (with its timeline's style if a timeline nearby uses it) or a .demo payload. Or pass `shader`
        (scene source) with an optional `style` (default: examples/common.glsl) and `profile`."""
        if path and shader:
            raise ToolError("pass either `path` or `shader`, not both")
        if shader:
            jobs = [("(shader)", "(style)" if style.strip() else "examples/common.glsl",
                     inline_payload(shader, style, profile=profile))]
            full = None
        else:
            p = ws.resolve(path) if path else None
            if p is None:
                raise ToolError("pass `path` or `shader`")
            try:
                jobs = debug_payloads(p, ws) if p.suffix in (".json", ".glsl") else []
                full = ws.payload(p) if p.suffix in (".json", ".demo") else None
            except (ValueError, KeyError, OSError) as e:
                return {"ok": False, "errors": [f"{path}: {e}"]}

        def work(h) -> dict:
            errors: list[str] = []
            compile_ms = 0.0
            for scene_file, style_file, payload in jobs:
                res = h.load(payload)
                compile_ms += float(res.get("compile_ms") or 0.0)
                if not res["ok"]:
                    errors += parse_errors(res["errors"], scene_file, style_file)
            if full is not None and not errors:  # il bundle vero: minificato, tutte le scene insieme
                res = h.load(full)
                compile_ms = float(res.get("compile_ms") or 0.0)
                if not res["ok"]:
                    errors += parse_errors(res["errors"], "(bundle)", "(bundle)")
            return {"ok": not errors, "errors": errors[:MAX_ERRORS], "compile_ms": round(compile_ms, 1),
                    "renderer": renderer.renderer}

        return renderer.run(work)

    @server.tool(structured_output=False)
    def render(path: str = "", shader: str = "", style: str = "", times: list[float] | None = None,
               width: int = 640, height: int = 360, profile: str = "modern", seconds: float = 8.0) -> list:
        """Render frames and return them as one image (a grid with the time over each frame); the PNGs
        are also saved under out/mcp/render_<name>/.

        `times` in seconds (default: 4 evenly spaced over the duration, at most 12). Source as in
        `validate`; with `shader`, `seconds` is the length of the loop."""
        payload, name = source_payload(path, shader, style, seconds, profile)
        width, height = max(16, min(width, 1920)), max(16, min(height, 1080))
        duration = float(payload["meta"]["duration_s"])
        ts = [float(t) for t in (times or [duration * (i + 0.5) / 4 for i in range(4)])][:12]
        ts = [round(min(max(t, 0.0), duration), 3) for t in ts]

        def work(h) -> list[bytes]:
            compile_or_raise(h, payload, path or "(shader)", "(style)")
            return h.capture(ts, width, height)

        pngs = renderer.run(work)
        d = ws.out_dir(f"render_{name}")
        for t, png in zip(ts, pngs, strict=True):
            (d / f"t{t:g}s.png").write_bytes(png)
        cols = 1 if len(pngs) == 1 else (2 if width >= height else 4)
        summary = f"{len(pngs)} frames at {width}x{height}, duration {duration:g} s; saved in {ws.rel(d)}/"
        return [summary, preview_image(frame_sheet(pngs, ts, cols))]

    @server.tool(structured_output=False)
    def inspect(path: str = "", shader: str = "", style: str = "", profile: str = "modern",
                seconds: float = 8.0, frames: int = 16, width: int = 480, height: int = 270) -> list:
        """Measure the demo and apply the gates: NaN/Inf, black frames, flicker, loop seam, WCAG flashes
        (whole duration at 30 fps), perf (net of the fixed cost of a measurement; absolute budgets only
        on a real GPU), payload size. Returns a summary with the issues and the contact sheet; the full
        report (burst, diff, perf charts, metrics.json, issues.json) is saved under out/mcp/inspect_<name>/."""
        payload, name = source_payload(path, shader, style, seconds, profile)
        frames = max(4, min(frames, 32))
        rdir = ws.out / f"inspect_{name}"

        def work(h):
            try:
                return inspect_payload(h, payload, width=width, height=height, frames=frames, report_dir=rdir)
            except CompileFailed as e:
                raise ToolError("does not compile:\n" + "\n".join(parse_errors(e.errors, path or "(shader)",
                                                                                "(style)"))) from None

        rep = renderer.run(work)
        vm, pf, fl = rep.metrics["video"], rep.metrics["perf"], rep.metrics["flash"]
        summary = {
            "renderer": rep.renderer,
            "blockers": rep.blockers,
            "majors": rep.majors,
            "issues": [{"severity": i.severity, "at_s": i.at_s, "description": i.description,
                        "fix": i.suggested_fix} for i in rep.issues],
            "video": {k: round(float(vm[k]), 4) for k in ("luma_mean", "black_ratio", "nan_ratio", "flicker_score")
                      if k in vm},
            "perf": {"p95_ms": round(pf["p95_ms"], 3), "mean_ms": round(pf["mean_ms"], 3),
                     "fixed_ms_subtracted": round(pf["fixed_ms"], 3),
                     "at": "x".join(str(v) for v in pf["resolution"]), "method": pf["method"]},
            "flash": {"passed": fl["passed"], "max_per_s": fl["max_flashes_per_s"]},
            "payload_gzip_bytes": rep.metrics["sizes"]["payload_gzip_bytes"],
            "report": f"{ws.rel(rep.report_dir)}/ ({', '.join(rep.files)})",
        }
        contact = PILImage.open(rep.report_dir / "contact.png").convert("RGB")
        return [json.dumps(summary, indent=1), preview_image(contact)]

    @server.tool()
    def verify_math(requests: list[dict]) -> dict:
        """Verify formulas numerically (sandboxed subprocess) and get GLSL for the accepted ones.

        Each request: `{"id": "sdf_ring", "kind": "sdf" | "lipschitz" | "periodic_path" | "easing" |
        "identity", "inputs": {"x": "float", "y": "float"}, "expr": "<python-safe expression>",
        "claim": {"domain": [[lo, hi], ...] (one per input), ...}}`. Claims: sdf (|grad| = 1, negative
        inside, positive on the border; give "inside": [x, y] for thin shapes), lipschitz ("bound"),
        periodic_path ("period"), easing (f(lo)=0, f(hi)=1, monotonic), identity (expr == 0).
        `expr` functions: sin cos tan asin acos atan exp log log2 sqrt abs sign floor ceil fract,
        atan2 mod pow min max step, clamp mix smoothstep, len2 len3 dot2 dist2 dot3 dist3; ** only with
        exponent 2, 3 or 4; constants pi e tau. Accepted results carry a GLSL function named `id`:
        paste it into your scene file."""
        from pydantic import ValidationError

        from .math.oracle import run_math_oracle
        from .spec.models import MathRequest

        try:
            reqs = [MathRequest.model_validate(r) for r in requests]
        except ValidationError as e:
            raise ToolError(f"invalid request: {e}") from None
        res = run_math_oracle(reqs, reserved_names=frozenset(load_library(LIB_DIR)))
        return {"results": [{"id": r.id, "status": r.status, "reason": r.reason, "glsl": r.glsl} for r in res.results]}

    @server.tool()
    def bundle(path: str, name: str = "", minify: bool = True) -> dict:
        """Build the demo from a timeline .json: a `.demo` payload (for `<demogen-player src=...>` or
        the Player API) and a standalone `.html` that opens offline, under out/mcp/bundle/."""
        p = ws.resolve(path)
        if p.suffix != ".json":
            raise ToolError("bundle takes a timeline .json")
        try:
            spec = ws.check_timeline(p)
            payload = build_payload(spec, p.parent, do_minify=minify)
        except (ValueError, KeyError, OSError) as e:
            raise ToolError(f"{path}: {e}") from None

        def work(h) -> dict:
            return compile_or_raise(h, payload, "(bundle)", "(bundle)")

        res = renderer.run(work)
        sizes = write_bundle(payload, ws.out_dir("bundle"), name or spec.get("name", p.stem))
        return {"demo": ws.rel(Path(sizes["paths"]["demo"])), "html": ws.rel(Path(sizes["paths"]["html"])),
                "demo_bytes": sizes["demo"]["raw"], "demo_gzip_bytes": sizes["demo"]["gzip"],
                "duration_s": payload["meta"]["duration_s"],
                "compile_ms": round(float(res.get("compile_ms") or 0.0), 1)}

    return server, renderer


def run_stdio(root: Path, gpu: str = "hardware", out: Path | None = None) -> None:
    server, renderer = build_server(root, gpu, out)
    try:
        server.run("stdio")
    finally:
        renderer.close()
