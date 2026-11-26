"""Menu interattivo di demogen (`demogen menu`, avviato da scripts/run.mts): tutta l'app in un posto solo.

Stesso stile del pannello dal vivo della generazione (palette neon, riquadri rich). Ogni azione
gira come sottoprocesso della CLI nello stesso terminale: una generazione mostra il suo pannello,
Ctrl+C riporta al menu. Testi visibili in inglese; commenti in italiano.

Senza menu: `demogen menu --action <nome> [--yes]` esegue una voce con i valori di default
(le conferme — spesa, chiusura processi, apertura del browser — valgono sì solo con --yes).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .dashboard import CYAN, DIM, GREEN, MAGENTA, PINK, PURPLE, RED, SOFT, YELLOW, neon_text

REPO = Path(__file__).resolve().parents[1]
console = Console(highlight=False)

HW_STYLE = {"GPU": (MAGENTA, "[GPU] "), "CPU": (GREEN, "[CPU] "), "CPU+": (YELLOW, "[CPU+]")}
HW_LEGEND = (
    ("GPU", "realtime in the browser: needs a GPU, stutters on CPU only"),
    ("CPU", "CPU is enough: same speed with or without a GPU"),
    ("CPU+", "works on CPU only (SwiftShader, the default); a GPU makes the checks faster"),
)


# ---------------------------------------------------------------- input
class Ui:
    """Domande all'utente; senza menu (`--action`) restituisce i default, le conferme valgono --yes."""

    def __init__(self, interactive: bool = True, yes: bool = False) -> None:
        self.interactive = interactive
        self.yes = yes

    def ask(self, label: str, default: str = "") -> str:
        if not self.interactive:
            return default
        v = Prompt.ask(f"  [bold {PINK}]»[/] [{SOFT}]{label}[/]", default=default or None, show_default=bool(default),
                       console=console)
        return (v or "").strip()

    def confirm(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return self.yes
        return Confirm.ask(f"  [bold {PINK}]»[/] [{SOFT}]{question}[/]", default=default, console=console)

    def choice(self, label: str, options: list[str], default: str) -> str:
        while True:
            v = self.ask(f"{label} ({' / '.join(options)})", default)
            if v in options:
                return v
            if v.isdigit() and 1 <= int(v) <= len(options):
                return options[int(v) - 1]
            pref = [o for o in options if v and o.startswith(v)]
            if len(pref) == 1:
                return pref[0]
            if not self.interactive:
                raise ValueError(f"invalid value for {label!r}: {v}")
            note(f"choose one of: {', '.join(options)}", YELLOW)

    def number(self, label: str, default: float, lo: float, hi: float) -> float:
        while True:
            v = self.ask(f"{label} ({lo:g}-{hi:g})", f"{default:g}").replace(",", ".")
            try:
                x = float(v)
                if lo <= x <= hi:
                    return x
            except ValueError:
                pass
            if not self.interactive:
                raise ValueError(f"invalid value for {label!r}: {v}")
            note(f"a number between {lo:g} and {hi:g}", YELLOW)

    def pick(self, title: str, items: list, label: Callable[[object], str], allow_path: bool = False):
        """Elenco numerato: numero (o percorso, se ammesso); vuoto = annulla."""
        if not items:
            return None
        t = Table.grid(padding=(0, 2))
        for i, it in enumerate(items, 1):
            t.add_row(Text(f"{i:>3}", style=f"bold {CYAN}"), Text(label(it), style=SOFT))
        console.print(Text("  " + title, style=f"bold {SOFT}"))
        console.print(t)
        if not self.interactive:
            return items[0]
        while True:
            v = self.ask("choice (empty = cancel)", "")
            if not v:
                return None
            if v.isdigit() and 1 <= int(v) <= len(items):
                return items[int(v) - 1]
            if allow_path and Path(v).exists():
                return str(Path(v).resolve())
            note("invalid choice", YELLOW)


def note(text: str, color: str = DIM) -> None:
    console.print(Text("  " + text, style=color))


def title(text: str) -> None:
    console.print()
    console.print(Rule(Text(f" {text} ", style=f"bold {CYAN}"), style=PURPLE, align="left", characters="━"))


# ---------------------------------------------------------------- esecuzione
def spawn(cmd: list[str]) -> int | None:
    """Esegue `cmd` nello stesso terminale; None se interrotto con Ctrl+C.

    Ctrl+C arriva anche al figlio: gli si lascia il tempo di chiudersi da solo (salvare lo stato,
    chiudere il browser) invece di ucciderlo dopo 0,25 s come farebbe subprocess.run."""
    # senza buffer: con l'output del menu rediretto (log, CI) il figlio scriverebbe tutto solo alla fine
    proc = subprocess.Popen(cmd, cwd=REPO, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=20)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.kill()
            proc.wait()
        note("interrupted", YELLOW)
        return None


def run_cli(args: list[str]) -> bool:
    """`demogen <args>` nello stesso terminale (il pannello della generazione resta interattivo)."""
    shown = " ".join(a if re.fullmatch(r"[\w./\\:=-]+", a) else f'"{a}"' for a in args)
    note(f"> demogen {shown}")
    code = spawn([sys.executable, "-m", "demogen.cli", *args])
    if code is None:
        return False
    if code != 0:
        console.print(Text(f"  the command stopped with an error (exit code {code}): the reason is above", style=RED))
    return code == 0


def run_tool(cmd: list[str], label: str) -> bool:
    exe = shutil.which(cmd[0])
    if exe is None:
        console.print(Text(f"  {cmd[0]} not found: {label}", style=RED))
        return False
    note("> " + " ".join(cmd))
    code = spawn([exe, *cmd[1:]])
    if code is None:
        return False
    if code != 0:
        console.print(Text(f"  stopped with exit code {code}", style=RED))
    return code == 0


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - apertura locale voluta
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def player_built() -> bool:
    return (REPO / "player" / "dist" / "demogen-player.min.js").exists()


# ---------------------------------------------------------------- stato della macchina
_GPU: str | None = None


def gpu_names() -> str:
    """Schede video reali (Windows); '' = nessuna rilevata. Calcolato una volta sola."""
    global _GPU
    if _GPU is not None:
        return _GPU
    names: list[str] = []
    if sys.platform == "win32":
        try:
            query = "(Get-CimInstance Win32_VideoController).Name"
            out = subprocess.run(["powershell", "-NoProfile", "-Command", query],
                                 capture_output=True, text=True, timeout=20).stdout
            names = [ln.strip() for ln in out.splitlines() if ln.strip()
                     and not re.search(r"Basic Display|Basic Render|Remote|Virtual|Hyper-V|Mirror|Parsec", ln)]
        except (OSError, subprocess.SubprocessError):
            names = []
    _GPU = " + ".join(names)
    return _GPU


def config_status() -> tuple[object | None, str]:
    """(config, errore): la chiave non viene mai mostrata."""
    path = REPO / "demogen.yaml"
    if not path.exists():
        return None, "demogen.yaml missing"
    try:
        from .config import load_config

        return load_config(path, interactive=False), ""
    except Exception as e:  # noqa: BLE001
        return None, f"demogen.yaml not readable: {str(e)[:120]}"


def llm_models(cfg) -> str:
    from .config import resolve_role

    out = []
    for r in ("orchestrator", "critic", "fixer", "composer"):
        if r in cfg.roles:
            try:
                out.append(f"{r} {resolve_role(cfg, r).model}")
            except Exception:  # noqa: BLE001
                out.append(f"{r} ?")
    return " · ".join(out)


def demogen_processes() -> list[dict]:
    """Processi di demogen: browser di Playwright, python del venv (trampolino e interprete vero,
    che ha il venv nella riga di comando), node di vitest/esbuild del repo, più i loro figli.
    Mai il menu stesso né i processi che l'hanno avviato."""
    import psutil

    venv = str((REPO / ".venv").resolve()).lower()
    repo = str(REPO).lower()
    me = {os.getpid()} | {p.pid for p in psutil.Process().parents()}
    procs: dict[int, dict] = {}
    children: dict[int, list[dict]] = defaultdict(list)
    for p in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time", "memory_info"]):
        i = p.info
        procs[i["pid"]] = i
        children[i["ppid"]].append(i)
    found: dict[int, str] = {}
    for pid, i in procs.items():
        if pid in me:
            continue
        exe = (i.get("exe") or "").lower()
        cmd = " ".join(i.get("cmdline") or []).lower()
        name = (i.get("name") or "").lower()
        if "ms-playwright" in f"{exe} {cmd}" and "mcp-chrome" not in cmd:
            found[pid] = "Playwright browser"
        elif exe.startswith(venv) or venv in cmd:
            found[pid] = "demogen python"
        elif name.startswith("node") and repo in cmd and ("vitest" in cmd or "esbuild" in cmd):
            found[pid] = "node (player)"
    queue = list(found)
    while queue:
        pid = queue.pop()
        for c in children.get(pid, []):
            cp = c["pid"]
            if cp in found or cp in me or (c.get("name") or "").lower() == "conhost.exe":
                continue
            if (c.get("create_time") or 0) < (procs[pid].get("create_time") or 0):  # PID riusato
                continue
            found[cp] = found[pid]
            queue.append(cp)
    out = []
    for pid in sorted(found):
        i = procs[pid]
        mem = i.get("memory_info")
        out.append({"pid": pid, "kind": found[pid], "name": i.get("name") or "?",
                    "mb": int(mem.rss / 2**20) if mem else 0, "cmd": " ".join(i.get("cmdline") or [])[:90]})
    return out


# ---------------------------------------------------------------- disegno
def header() -> Panel:
    cfg, err = config_status()
    status = Text()
    status.append("venv ok", style=GREEN)
    status.append("  ·  ", style=DIM)
    built = player_built()
    status.append("player ok" if built else f"player not built (entry {key_of('setup')})",
                  style=GREEN if built else RED)
    status.append("  ·  ", style=DIM)
    lines: list = [Text.assemble(("NEURAL DEMO FORGE", f"bold {SOFT}"), ("  //  ", DIM),
                                 ("◢ CONTROL DECK ◣", f"bold {MAGENTA}"),
                                 ("   " + datetime.now().strftime("%H:%M"), CYAN))]
    if cfg is None:
        status.append(f"{err} (entry {key_of('config')})", style=RED)
        lines.append(status)
    else:
        from .cli import budget_summary

        s = budget_summary(cfg)
        c = s["caps"]
        status.append(f"today {s['today']:.3f}" + (f"/{c['daily']:g}" if c["daily"] else ""), style=SOFT)
        status.append(f"  month {s['month']:.3f}" + (f"/{c['monthly']:g}" if c["monthly"] else "") + " USD",
                      style=SOFT)
        status.append(f"  ·  cap {c['run']:g} USD/run", style=SOFT)
        lines.append(status)
        lines.append(Text.assemble(("LLM  ", f"bold {PINK}"), (llm_models(cfg) or "-", SOFT)))
    gpu = gpu_names()
    lines.append(Text.assemble(("GPU  ", f"bold {PINK}"),
                               (gpu or "none detected: [GPU] entries will stutter", SOFT if gpu else YELLOW)))
    procs = len(demogen_processes())
    if procs:
        lines.append(Text(f"{procs} demogen processes still running (entry {key_of('ps')} shows them, "
                          f"{key_of('kill')} closes them)", style=YELLOW))
    return Panel(Group(*lines), box=box.HEAVY, border_style=PURPLE, padding=(0, 1),
                 title=Text(" ▞▚ ", style=f"bold {PINK}") + neon_text("D E M O G E N", 0.0)
                 + Text(" ▚▞ ", style=f"bold {CYAN}"), title_align="left")


def menu_body(entries: list[Entry]) -> Group:
    rows: list = []
    section = ""
    t: Table | None = None
    for e in entries:
        if e.section != section:
            section = e.section
            if t is not None:
                rows.append(t)
            rows.append(Rule(Text(f" {section} ", style=f"bold {CYAN}"), style=DIM, align="left", characters="─"))
            t = Table.grid(padding=(0, 2))
        color, tag = HW_STYLE[e.hw]
        t.add_row(Text(f"{e.key:>3}", style=f"bold {CYAN}"), Text(tag, style=f"bold {color}"),
                  Text(e.label, style=SOFT))
    if t is not None:
        rows.append(t)
    legend = Table.grid(padding=(0, 1))
    for hw, desc in HW_LEGEND:
        color, tag = HW_STYLE[hw]
        legend.add_row(Text(tag, style=f"bold {color}"), Text(desc, style=DIM))
    rows += [Rule(style=DIM, characters="─"), legend, Text("    0  quit", style=f"bold {CYAN}")]
    return Group(*rows)


# ---------------------------------------------------------------- progetti ed esempi
def project_label(d: Path) -> str:
    import json

    label = d.name
    try:
        spec = d / "spec.json"
        if spec.exists():
            label += "  ·  " + str(json.loads(spec.read_text(encoding="utf-8")).get("title", ""))
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        status = "complete" if "S9" in (st.get("done") or []) else "incomplete"
        if st.get("stopped"):
            status = "stopped (" + str(st["stopped"])[:40] + ")"
        if st.get("paused") == "plan":
            status = "plan ready for review"
        label += f"  [{status}"
        if st.get("budget_spent_usd"):
            label += f", {float(st['budget_spent_usd']):.3f} USD"
        label += "]"
    except Exception:  # noqa: BLE001
        pass
    return label


def select_project(ui: Ui) -> Path | None:
    base = REPO / "projects"
    dirs = sorted((d for d in base.iterdir() if (d / "state.json").exists()), key=lambda d: d.stat().st_mtime,
                  reverse=True) if base.exists() else []
    if not dirs:
        note("no projects in projects/ (they are created by Generate)")
        p = ui.ask("path of a project (empty = cancel)", "")
        return Path(p) if p and (Path(p) / "state.json").exists() else None
    p = ui.pick("Project (number, or the path of another folder):", dirs, lambda d: project_label(Path(d)),
                allow_path=True)
    if p is None:
        return None
    p = Path(p)
    if not (p / "state.json").exists():
        note(f"{p} is not a demogen project (no state.json)", YELLOW)
        return None
    return p


def examples(shaders: bool = False) -> list[Path]:
    ex = REPO / "examples"
    items = sorted(ex.rglob("*timeline*.json"), key=lambda f: (f.name != "timeline.json", str(f)))
    if shaders:
        items += [f for f in sorted((ex / "shaders").glob("*.glsl")) if "mainImage" in f.read_text(encoding="utf-8")]
    return items


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def newest(dirpath: Path, pattern: str, dirs: bool = False) -> Path | None:
    if not dirpath.exists():
        return None
    items = [p for p in dirpath.glob(pattern) if p.is_dir() == dirs]
    return max(items, key=lambda p: p.stat().st_mtime) if items else None


def open_project_demo(ui: Ui, project: Path) -> None:
    html = newest(project / "out", "*.html")
    if html is None:
        note(f"no demo in {project / 'out'} (did the run reach the bundle step?)", YELLOW)
        return
    console.print(Text(f"  demo: {html}", style=GREEN))
    if ui.confirm("Open it in the browser? (click to start; space = pause, S = stop, L = loop, M = mute)", True):
        open_path(html)


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > 30:  # al massimo 30 caratteri, tagliando su un trattino e non a metà parola
        cut = s[:31]
        s = cut[:-1] if cut.endswith("-") else (cut.rsplit("-", 1)[0] if "-" in cut else s[:30])
    return s.strip("-") or "demo"


def render_check(ui: Ui) -> str:
    note("checks renderer: swiftshader = CPU only (default, works anywhere: scene cost is measured against the")
    note("reference scene); hardware = GPU, faster, adds absolute ms budgets (strict on integrated GPUs)")
    return ui.choice("checks renderer", ["swiftshader", "hardware"], "swiftshader")


# ---------------------------------------------------------------- azioni
def do_generate(ui: Ui, fake: bool = False) -> bool:
    cfg = None
    if fake:
        title("Generate a fake demo (--fake: no API calls, real checks in the browser)")
        d_prompt, d_dur, d_bpm = "neon plasma pulsing on the kick", 8.0, 120.0
    else:
        title("Generate a demo with the LLM")
        cfg, err = config_status()
        if cfg is None:
            note(f"{err}: create it with LLM config", RED)
            return False
        from .cli import budget_summary

        s = budget_summary(cfg)
        note(f"models: {llm_models(cfg)}")
        note(f"spent today {s['today']:.3f} USD, this month {s['month']:.3f} USD; caps: "
             + ", ".join(f"{k} {'none' if v is None else v}" for k, v in s["caps"].items()))
        d_prompt, d_dur, d_bpm = "", 30.0, 128.0
    prompt = ui.ask("prompt (empty = cancel)", d_prompt).replace('"', "'")
    if not prompt:
        note("cancelled")
        return False
    dur = ui.number("duration in seconds", d_dur, 4, 120)
    note("BPM = beats per minute, the tempo of the music: kicks, flashes, pulses and scene cuts follow it")
    note("(90 slow, 120-128 house/techno, 170+ drum'n'bass)")
    bpm = ui.number("BPM", d_bpm, 60, 200)
    note("style: modern = full resolution; retro = 320x180 pixels with a 16-color palette. It applies to every scene")
    prof = ui.choice("style", ["modern", "retro"], "modern")
    note("loop: auto = loops forever if the prompt asks for it (\"seamless loop\"), otherwise plays once")
    loop = ui.choice("loop at the end", ["auto", "yes", "no"], "auto")
    gpu = render_check(ui)
    note("music: the composer LLM writes the soundtrack on the demo BPM (one more call); it is listened to")
    note("automatically: hits on the beat, loudness, no distortion")
    with_music = ui.choice("music", ["yes", "no"], "yes")
    music_prompt = ""
    if with_music == "yes":
        music_prompt = ui.ask("music prompt: genre, instruments, mood (empty = from the demo prompt)", "")
        music_prompt = music_prompt.replace('"', "'")
    note("plan review: stop after the plan (scenes, timing, palette: one cheap call) to read it and change it")
    note("before the drawing starts; most of the cost comes later, while the scenes are drawn and judged")
    review = ui.choice("review the plan first", ["yes", "no"], "no" if fake else "yes")
    proj = ui.ask("project folder", f"projects/{datetime.now():%Y%m%d-%H%M%S}_{slug(prompt)}")
    args = ["generate", prompt, "--duration", f"{dur:g}", "--bpm", f"{bpm:g}", "--profile", prof, "--gpu", gpu,
            "--project", proj]
    if loop != "auto":
        args.append("--loop" if loop == "yes" else "--no-loop")
    if with_music == "no":
        args.append("--no-music")
    elif music_prompt:
        args += ["--music", music_prompt]
    if review == "yes":
        args.append("--review-plan")
    cap: float | None = None
    if fake:
        args.append("--fake")
    else:
        cap = ui.number("spending cap for this run (USD)", float(cfg.budget.max_total_cost_usd), 0.01, 1000)
        args += ["--max-cost", f"{cap:g}"]
        if not ui.confirm(f"Start? LLM calls are paid (cap {cap:g} USD)", True):
            note("cancelled")
            return False
    ok = run_cli(args)
    path = REPO / proj if not Path(proj).is_absolute() else Path(proj)
    if ok and paused_for_plan(path):
        return review_plan(ui, path, fake=fake, gpu=gpu, cap=cap, show=False)  # generate l'ha appena stampato
    if ok:
        open_project_demo(ui, path)
    return ok


def paused_for_plan(project: Path) -> bool:
    from .orchestrator.plan import is_paused_for_plan

    return is_paused_for_plan(project)


def plan_scenes(project: Path) -> list[dict]:
    import json

    try:
        return list(json.loads((project / "spec.json").read_text(encoding="utf-8")).get("scenes") or [])
    except (OSError, ValueError, AttributeError):
        return []


def review_plan(ui: Ui, project: Path, fake: bool, gpu: str, cap: float | None = None, show: bool = True) -> bool:
    """Il piano scritto, poi: continua (resume), cambia una scena a mano, nota all'LLM, o fermati qui.

    Il piano si stampa una volta sola: all'inizio (se `generate` non l'ha appena stampato, `show=False`)
    e poi dal comando che lo cambia, che mostra già il piano aggiornato."""
    plan = ["plan", str(project), "--no-hints"]  # i comandi successivi li offre il menu
    llm = ["--fake"] if fake else []
    cost = ["--max-cost", f"{cap:g}"] if cap is not None else []
    title("The plan: read it, change it, then the drawing starts")
    if show and not run_cli(plan):
        return False
    while True:
        note("continue = draw it as it is; edit = rewrite a scene yourself (no LLM call);")
        note("note = tell the LLM what to change in the plan (one call); stop = keep the plan, resume it later")
        action = ui.choice("plan", ["continue", "edit", "note", "stop"], "continue")
        if action == "continue":
            ok = run_cli(["resume", str(project), "--gpu", gpu, *llm, *cost])
            if ok:
                open_project_demo(ui, project)
            return ok
        if action == "stop":
            note(f"the plan is saved: continue later with Resume (or demogen resume {rel(project)})", GREEN)
            return True
        if action == "edit":
            scenes = plan_scenes(project)
            if not scenes:
                note("the plan has no scenes", YELLOW)
                continue
            ids = [str(s.get("id")) for s in scenes]
            sid = ui.choice("scene", ids, ids[0])
            field = ui.choice("what to change", ["description", "motion", "title"], "description")
            cur = str(next(s for s in scenes if str(s.get("id")) == sid).get(field) or "")
            # niente testo attuale come default: è appena stampato nel piano, e Rich lo ripeterebbe intero
            value = ui.ask(f"new {field} of {sid} (empty = keep the current one)", "").replace('"', "'")
            if value and value != cur:
                run_cli([*plan, "--scene", sid, f"--{field}", value])
        else:
            text = ui.ask("what should change? (e.g. the cat is black, add a scene where it sleeps; "
                          "empty = cancel)", "").replace('"', "'")
            if text:
                run_cli([*plan, "--note", text, *llm, *cost])


def do_resume(ui: Ui) -> bool:
    title("Resume a project: redo only the missing steps, without repeating calls already made")
    p = select_project(ui)
    if p is None:
        return False
    llm = ui.choice("LLM", ["real", "fake"], "real")
    gpu = render_check(ui)
    if paused_for_plan(p):
        note("this project stopped after the plan, waiting for your review")
        return review_plan(ui, p, fake=llm == "fake", gpu=gpu)
    args = ["resume", str(p), "--gpu", gpu] + (["--fake"] if llm == "fake" else [])
    ok = run_cli(args)
    if ok:
        open_project_demo(ui, p)
    return ok


def do_revise(ui: Ui) -> bool:
    import json

    title("Revise a scene: a new version guided by your note")
    p = select_project(ui)
    if p is None:
        return False
    sdir = p / "scenes"
    scenes = sorted(d.name for d in sdir.iterdir() if d.is_dir()) if sdir.exists() else []
    if not scenes:
        note("the project has no scenes yet", YELLOW)
        return False
    for s in scenes:
        b = sdir / s / "best.json"
        info = "no version chosen yet"
        if b.exists():
            data = json.loads(b.read_text(encoding="utf-8"))
            info = f"best {data.get('version')}, score {data.get('score')}"
        note(f"{s}: {info}", SOFT)
    scene = ui.choice("scene", scenes, scenes[0])
    note_text = ui.ask("note (e.g. less fog, more contrast on the kick; empty = cancel)", "").replace('"', "'")
    if not note_text:
        note("cancelled")
        return False
    llm = ui.choice("LLM", ["real", "fake"], "real")
    args = ["revise", str(p), "--scene", scene, "--note", note_text, "--gpu", render_check(ui)]
    ok = run_cli(args + (["--fake"] if llm == "fake" else []))
    if ok:
        open_project_demo(ui, p)
    return ok


def do_music(ui: Ui) -> bool:
    import json

    title("Music: (re)compose a project's soundtrack from a prompt, then rebuild the demo")
    p = select_project(ui)
    if p is None:
        return False
    best = p / "audio" / "best.json"
    cur = (json.loads(best.read_text(encoding="utf-8")) or {}).get("version") if best.exists() else None
    note(f"current music: {cur} (the new one will be another version)" if cur else "the project has no music yet")
    note("describe what you want to hear: genre, instruments, mood, energy")
    note("(e.g. slow synthwave with arpeggios and pads, acid techno with a straight kick, cheerful chiptune)")
    mp = ui.ask("music prompt (empty = from the demo prompt)", "").replace('"', "'")
    llm = ui.choice("LLM", ["real", "fake"], "real")
    args = ["music", str(p)] + (["--prompt", mp] if mp else []) + (["--fake"] if llm == "fake" else [])
    ok = run_cli(args)
    if ok:
        open_project_demo(ui, p)
    return ok


def do_report(ui: Ui) -> bool:
    title("Project report")
    p = select_project(ui)
    if p is None:
        return False
    from .project.report import build_report

    console.print(Panel(Markdown(build_report(p)), border_style=PURPLE, box=box.ROUNDED))
    return True


def do_plan(ui: Ui) -> bool:
    title("Plan: read a project's plan (scenes, timing, palette) and change it before the drawing starts")
    p = select_project(ui)
    if p is None:
        return False
    if not paused_for_plan(p):
        return run_cli(["plan", str(p)])
    llm = ui.choice("LLM for notes and drawing", ["real", "fake"], "real")
    return review_plan(ui, p, fake=llm == "fake", gpu=render_check(ui))


def do_preview(ui: Ui) -> bool:
    from .orchestrator.plan import PlanError
    from .orchestrator.preview import describe, scene_versions

    title("Preview a scene of a project in the browser (also while it is being generated)")
    p = select_project(ui)
    if p is None:
        return False
    try:
        table = scene_versions(p)
    except PlanError as e:
        note(str(e), YELLOW)
        return False
    for sv in table:
        note(describe(sv), SOFT)
    ready = [sv for sv in table if sv.versions]
    if not ready:
        note("no scene has a shader yet: the drafts arrive after the plan and the style", YELLOW)
        return False
    sid = ui.choice("scene", [sv.id for sv in ready], ready[0].id)
    sv = next(x for x in ready if x.id == sid)
    ver = ui.choice("version", [f"v{v}" for v in sv.versions], f"v{sv.default}")
    sheet = p / "scenes" / sid / f"{ver}.probe" / "contact.png"
    if sheet.exists():
        note(f"16 frames of {sid} {ver} (the ones the critic saw): {rel(sheet)}")
        if ui.confirm("Open the frame sheet too?", False):
            open_path(sheet)
    note("auto = GPU if available; hardware = force the GPU; swiftshader = CPU only (stutters)")
    gpu = ui.choice("renderer", ["auto", "hardware", "swiftshader"], "auto")
    note("a browser window opens: close it to come back to the menu")
    return run_cli(["play", str(p), "--scene", sid, "--version", ver[1:], "--gpu", gpu])


def do_open(ui: Ui) -> bool:
    title("Open a project's demo")
    p = select_project(ui)
    if p is None:
        return False
    open_project_demo(ui, p)
    return True


def do_play_main(ui: Ui) -> bool:
    title("Main demo in realtime (examples/timeline.json)")
    note("a browser window opens: close it to come back to the menu")
    return run_cli(["play", "examples/timeline.json", "--gpu", "auto"])


CATS_PAGE = REPO / "examples" / "web" / "whisker-hunt.html"


def do_cats(ui: Ui) -> bool:
    title("Cat demo: whisker hunt (examples/web/whisker-hunt.html)")
    note("pixel-art cats: wake up, a big cat idle, a hunt for a moth (crouch, tail wag, pounce, look up), fade out")
    note("a standalone page: player and demo are inside the HTML, it opens in the browser even from file://")
    if not CATS_PAGE.exists():
        note(f"{rel(CATS_PAGE)} missing: rebuild it with the bundle entry on examples/whisker_hunt.timeline.json",
             YELLOW)
        return False
    open_path(CATS_PAGE)
    return True


def do_play(ui: Ui) -> bool:
    title("Play an example in realtime")
    f = ui.pick("Example:", examples(shaders=True), lambda x: rel(Path(x)))
    if f is None:
        return False
    note("auto = GPU if available; hardware = force the GPU; swiftshader = CPU only (stutters, for comparison)")
    gpu = ui.choice("renderer", ["auto", "hardware", "swiftshader"], "auto")
    note("a browser window opens: close it to come back to the menu")
    return run_cli(["play", rel(Path(f)), "--gpu", gpu])


def do_inspect(ui: Ui) -> bool:
    title("Inspect: metrics, checks (flash, perf, NaN...) and sheets in out/")
    f = ui.pick("Example:", examples(shaders=True), lambda x: rel(Path(x)))
    if f is None:
        return False
    note("swiftshader = CPU only (full metrics and checks); hardware = GPU (faster, real ms)")
    gpu = ui.choice("renderer", ["swiftshader", "hardware"], "swiftshader")
    ok = run_cli(["inspect", rel(Path(f)), "--gpu", gpu, "--out", "out"])
    d = newest(REPO / "out", "inspect_*", dirs=True)
    if ok and d is not None and ui.confirm(f"Open {rel(d)}?", True):
        open_path(d)
    return ok


def do_bundle(ui: Ui) -> bool:
    title("Bundle an example: .demo + standalone .html in out/")
    f = ui.pick("Example:", examples(), lambda x: rel(Path(x)))
    if f is None:
        return False
    ok = run_cli(["bundle", rel(Path(f)), "--out", "out"])
    h = newest(REPO / "out", "*.html")
    if ok and h is not None and ui.confirm(f"Open {rel(h)}?", True):
        open_path(h)
    return ok


def do_web(ui: Ui) -> bool:
    title("Web examples of the player (examples/web, they also work from file://)")
    if not player_built():
        note("the player is not built (player/dist missing)", YELLOW)
        if not ui.confirm("Build it now (npm run build)?", True):
            return False
        if not run_tool(["npm", "run", "build"], "install Node.js"):
            return False
    pages = sorted((REPO / "examples" / "web").glob("*.html"))
    f = ui.pick("Page:", pages, lambda x: Path(x).name)
    if f is None:
        return False
    open_path(Path(f))
    return True


def do_setup(ui: Ui) -> bool:
    title("Setup: Chromium for the checks, player dependencies and build")
    note("the Python environment (uv sync) is set up by the launcher before the menu: `npm run menu -- --setup`")
    ok = run_cli_python(["-m", "playwright", "install", "chromium"])
    ok = ok and run_tool(["npm", "install"], "install Node.js (https://nodejs.org)")
    ok = ok and run_tool(["npm", "run", "build"], "install Node.js")
    if ok:
        console.print(Text("  setup completed", style=GREEN))
    return ok


def run_cli_python(args: list[str]) -> bool:
    note("> python " + " ".join(args))
    return spawn([sys.executable, *args]) == 0


def do_doctor(ui: Ui) -> bool:
    title("Doctor: environment and GPU/CPU renderer")
    return run_cli(["doctor"])


def do_config(ui: Ui) -> bool:
    title("LLM configuration")
    path = REPO / "demogen.yaml"
    cfg, err = config_status()
    note(f"demogen.yaml present, models: {llm_models(cfg)} (it is in .gitignore)" if cfg else err,
         SOFT if cfg else YELLOW)
    what = ui.choice("what to do", ["create", "edit", "check"], "check" if cfg else "create")
    if what == "create":
        return run_cli(["init"])
    if what == "edit":
        if not path.exists() and not run_cli(["init"]):
            return False
        note("key in providers.openrouter.api_key, models in roles, caps in budget (or use Spending caps)")
        editor = os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "nano")
        subprocess.Popen([editor, str(path)])
        return True
    note("one minimal call per role (text, vision, json): costs a few cents")
    if not ui.confirm("Go?", True):
        return False
    return run_cli(["models", "check"])


def do_budget(ui: Ui) -> bool:
    title("Spending caps: LLM spending and limits")
    cfg, err = config_status()
    if cfg is None:
        note(f"{err}: create it with LLM config", RED)
        return False
    from .cli import budget_summary
    from .config import set_budget_values

    def show() -> dict:
        s = budget_summary(config_status()[0])
        c = s["caps"]
        t = Table(box=box.SIMPLE_HEAVY, border_style=PURPLE, header_style=f"bold {CYAN}")
        t.add_column("cap")
        t.add_column("limit", justify="right")
        t.add_column("spent", justify="right")
        fmt = lambda v, u=" USD": "no cap" if v is None else f"{v:g}{u}"  # noqa: E731
        t.add_row("per run", fmt(c["run"]), "")
        t.add_row("per day (all runs)", fmt(c["daily"]), f"{s['today']:.4f} USD")
        t.add_row("per month (all runs)", fmt(c["monthly"]), f"{s['month']:.4f} USD")
        t.add_row("LLM calls per run", fmt(c["calls"], ""), "")
        t.add_row("minutes per run", fmt(c["minutes"], ""), "")
        console.print(t)
        if s["projects"]:
            p = Table(box=box.SIMPLE, header_style=f"bold {CYAN}", title="this month by project", title_style=DIM)
            p.add_column("project")
            p.add_column("USD", justify="right")
            for name, usd in list(s["projects"].items())[:8]:
                p.add_row(name, f"{usd:.4f}")
            console.print(p)
        note("the spending log starts with the first call made after spending caps were added")
        return c

    caps = show()
    if not ui.interactive or not ui.confirm("Change the caps?", False):
        return True
    note("Enter keeps the current value; 0 = no cap (daily, monthly, calls)")
    changes: dict[str, object] = {}
    for key, cfg_key, label, lo in (("run", "max_total_cost_usd", "per run (USD)", 0.01),
                                    ("daily", "max_daily_cost_usd", "per day (USD)", 0.0),
                                    ("monthly", "max_monthly_cost_usd", "per month (USD)", 0.0),
                                    ("calls", "max_calls_per_run", "LLM calls per run", 0.0),
                                    ("minutes", "max_wall_minutes", "minutes per run", 1.0)):
        cur = caps[key]
        v = ui.number(label, float(cur or 0), lo, 100000)
        if v != float(cur or 0):
            if key == "calls":
                changes[cfg_key] = int(v) if v > 0 else None
            elif key in ("daily", "monthly"):
                changes[cfg_key] = v if v > 0 else None
            else:
                changes[cfg_key] = v
    if changes:
        set_budget_values(REPO / "demogen.yaml", changes)
        console.print(Text("  saved in demogen.yaml", style=GREEN))
        show()
    return True


def do_tests(ui: Ui) -> bool:
    title("Python tests: ruff + pytest (the full suite with the browser takes a few minutes)")
    k = ui.ask("pytest -k filter (empty = all)", "")
    if not run_cli_python(["-m", "ruff", "check", "."]):
        return False
    return run_cli_python(["-m", "pytest", "-q"] + (["-k", k] if k else []))


def do_player_tests(ui: Ui) -> bool:
    title("Player tests: typecheck (player and launcher) + vitest + build")
    return (run_tool(["npm", "run", "typecheck", "--workspace", "player"], "install Node.js")
            and run_tool(["npm", "run", "typecheck:scripts"], "install Node.js")
            and run_tool(["npm", "test", "--workspace", "player"], "install Node.js")
            and run_tool(["npm", "run", "build"], "install Node.js"))


def do_calibrate(ui: Ui) -> bool:
    title("Calibrate: ms per frame of the example shaders at 1920x1080 on the GPU")
    if not gpu_names():
        note("no GPU detected: this measure makes no sense on CPU only", YELLOW)
        return False
    ok = run_cli(["calibrate", "--gpu", "hardware", "--out", "out"])
    f = REPO / "out" / "calibrate.json"
    if ok and f.exists():
        console.print(f.read_text(encoding="utf-8"))
    return ok


def process_table(items: list[dict]) -> None:
    if not items:
        console.print(Text("  no demogen processes running", style=GREEN))
        return
    t = Table(box=box.SIMPLE_HEAVY, header_style=f"bold {CYAN}", border_style=PURPLE)
    # con una cella no_wrap più larga della console rich porta a zero le colonne corte (PID, MB):
    # il comando ha una larghezza massima pari a quel che resta
    t.add_column("PID", justify="right", no_wrap=True)
    t.add_column("kind", no_wrap=True)
    t.add_column("name", no_wrap=True, overflow="ellipsis", max_width=16)
    t.add_column("MB", justify="right", no_wrap=True)
    t.add_column("command", no_wrap=True, overflow="ellipsis", max_width=max(12, console.width - 68))
    for p in items:
        t.add_row(str(p["pid"]), p["kind"], p["name"], str(p["mb"]), p["cmd"])
    console.print(t)
    note(f"{len(items)} processes, {sum(p['mb'] for p in items)} MB in total", SOFT)


def do_ps(ui: Ui) -> bool:
    title("Running demogen processes")
    process_table(demogen_processes())
    return True


def do_kill(ui: Ui) -> bool:
    import psutil

    title("Close demogen processes")
    note("Playwright browsers, venv python (CLI, tests, oracle), vitest/esbuild node and their children;")
    note("this menu, your Chrome and other programs are never touched")
    items = demogen_processes()
    process_table(items)
    if not items or not ui.confirm(f"Close these {len(items)} processes?", False):
        return not items
    for p in items:
        try:
            psutil.Process(p["pid"]).kill()
        except psutil.Error:
            pass  # già terminato insieme al padre
    time.sleep(0.8)
    left = demogen_processes()
    if left:
        note(f"still running: {len(left)}", YELLOW)
        process_table(left)
        return False
    console.print(Text(f"  closed {len(items)} processes", style=GREEN))
    return True


@dataclass
class Entry:
    name: str
    hw: str
    section: str
    label: str
    run: Callable[[Ui], bool]
    key: str = ""


ENTRIES: list[Entry] = [
    Entry("generate", "CPU+", "MAIN", "Generate a demo with the LLM (OpenRouter, paid)", lambda ui: do_generate(ui)),
    Entry("fake", "CPU+", "MAIN", "Generate a fake demo (--fake, no API)", lambda ui: do_generate(ui, fake=True)),
    Entry("resume", "CPU+", "MAIN", "Resume an interrupted project", do_resume),
    Entry("plan", "CPU", "MAIN", "Plan: read a project's plan, change it before the drawing starts", do_plan),
    Entry("revise", "CPU+", "MAIN", "Revise a scene with a note", do_revise),
    Entry("music", "CPU+", "MAIN", "Music: (re)compose a project's soundtrack from a prompt", do_music),
    Entry("report", "CPU", "MAIN", "Show a project's report", do_report),
    Entry("open", "GPU", "MAIN", "Open a project's demo in the browser", do_open),
    Entry("preview", "GPU", "MAIN", "Preview a scene of a project, also during a generation", do_preview),
    Entry("m1", "GPU", "EXAMPLES", "Main demo in realtime (examples/timeline.json)", do_play_main),
    Entry("cats", "GPU", "EXAMPLES", "Cat demo: whisker hunt, in the browser", do_cats),
    Entry("play", "GPU", "EXAMPLES", "Play an example (timeline or shader)", do_play),
    Entry("inspect", "CPU+", "EXAMPLES", "Inspect an example: metrics, checks and sheets in out/", do_inspect),
    Entry("bundle", "CPU", "EXAMPLES", "Bundle an example (.demo + .html in out/)", do_bundle),
    Entry("web", "GPU", "EXAMPLES", "Web examples of the player (examples/web)", do_web),
    Entry("setup", "CPU", "SETUP & TESTS", "Setup (Chromium, npm install, player build)", do_setup),
    Entry("doctor", "CPU", "SETUP & TESTS", "Doctor: environment and GPU/CPU renderer", do_doctor),
    Entry("config", "CPU", "SETUP & TESTS", "LLM config: create or edit demogen.yaml, check the models", do_config),
    Entry("budget", "CPU", "SETUP & TESTS", "Spending caps: LLM spending today/this month, set the caps", do_budget),
    Entry("test", "CPU", "SETUP & TESTS", "Python tests (ruff + pytest)", do_tests),
    Entry("test-player", "CPU", "SETUP & TESTS", "Player tests (typecheck + vitest + build)", do_player_tests),
    Entry("calibrate", "GPU", "SETUP & TESTS", "Calibrate: ms of the example shaders on the GPU", do_calibrate),
    Entry("ps", "CPU", "PROCESSES", "Show the demogen processes still running", do_ps),
    Entry("kill", "CPU", "PROCESSES", "Close the demogen processes (browser, python, node)", do_kill),
]
for _i, _e in enumerate(ENTRIES, 1):
    _e.key = str(_i)


def key_of(name: str) -> str:
    """Numero della voce `name` nel menu (i numeri seguono l'ordine delle voci)."""
    e = find_entry(name)
    return e.key if e else "?"


def find_entry(choice: str) -> Entry | None:
    c = choice.strip().lower()
    return next((e for e in ENTRIES if c in (e.key, e.name)), None)


def run_entry(e: Entry, ui: Ui) -> bool:
    if e.hw == "GPU" and not gpu_names():
        note("no GPU detected: realtime rendering will stutter (SwiftShader on CPU)", YELLOW)
    try:
        return bool(e.run(ui))
    except KeyboardInterrupt:
        note("interrupted", YELLOW)
        return False
    except Exception as ex:  # noqa: BLE001 - il menu non deve chiudersi per un errore di una voce
        console.print(Text(f"  error: {ex}", style=RED))
        return False


def main(action: str = "", yes: bool = False) -> int:
    os.chdir(REPO)
    if action:
        if action in ("list", "?"):
            for e in ENTRIES:
                console.print(Text.assemble((f"{e.key:>3}  ", CYAN), (HW_STYLE[e.hw][1] + " ", HW_STYLE[e.hw][0]),
                                            (f"{e.name:<12} ", f"bold {SOFT}"), (e.label, SOFT)))
            return 0
        e = find_entry(action)
        if e is None:
            console.print(Text(f"unknown action: {action} (list: demogen menu --action list)", style=RED))
            return 2
        return 0 if run_entry(e, Ui(interactive=False, yes=yes)) else 1
    ui = Ui()
    while True:
        console.clear()
        console.print(header())
        console.print(Panel(menu_body(ENTRIES), box=box.HEAVY, border_style=PURPLE, padding=(0, 1)))
        try:
            choice = Prompt.ask(f"  [bold {PINK}]»[/] [bold {SOFT}]select[/]", console=console, default="",
                                show_default=False)
        except (KeyboardInterrupt, EOFError):
            break
        if choice.strip().lower() in ("0", "q", "quit", "exit"):
            break
        e = find_entry(choice)
        if e is None:
            continue
        run_entry(e, ui)
        try:
            Prompt.ask(f"\n  [{DIM}]Enter to go back to the menu[/]", console=console, default="", show_default=False)
        except (KeyboardInterrupt, EOFError):
            break
    console.print(Text("  bye", style=DIM))
    return 0
