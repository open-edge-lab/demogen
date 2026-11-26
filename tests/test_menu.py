"""Menu interattivo (`demogen menu`, avviato da scripts/run.mts): voci, azioni dirette, argomenti, lanciatore."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from demogen import menu
from demogen.config import Config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def quiet(monkeypatch):
    """Console in memoria e nessuna rilevazione GPU (PowerShell) o processo reale."""
    con = Console(record=True, width=100, force_terminal=False)
    monkeypatch.setattr(menu, "console", con)
    monkeypatch.setattr(menu, "_GPU", "Test GPU")
    return con


@pytest.fixture
def calls(monkeypatch):
    """Registra le chiamate alla CLI al posto di eseguirle."""
    seen: list[list[str]] = []

    def fake_run(args: list[str]) -> bool:
        seen.append(list(args))
        return True

    monkeypatch.setattr(menu, "run_cli", fake_run)
    monkeypatch.setattr(menu, "open_project_demo", lambda ui, p: None)
    return seen


def test_voci_numerate_in_ordine_e_nomi_unici() -> None:
    keys = [e.key for e in menu.ENTRIES]
    assert keys == [str(i) for i in range(1, len(menu.ENTRIES) + 1)]
    names = [e.name for e in menu.ENTRIES]
    assert len(set(names)) == len(names)
    assert all(e.hw in menu.HW_STYLE for e in menu.ENTRIES)
    assert {"generate", "fake", "resume", "revise", "music", "budget", "config", "kill", "ps", "cats",
            "plan", "preview"} <= set(names)
    assert menu.find_entry("cats").section == "EXAMPLES"
    assert menu.find_entry("plan").section == menu.find_entry("preview").section == "MAIN"


def test_la_demo_dei_gatti_si_apre_dal_menu(quiet, monkeypatch) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(menu, "open_path", opened.append)
    assert menu.run_entry(menu.find_entry("cats"), menu.Ui(interactive=False)) is True
    assert opened == [REPO / "examples" / "web" / "whisker-hunt.html"] and opened[0].exists()


def test_ogni_esempio_del_menu_compila(harness) -> None:
    # run reale: dal menu (play/inspect) gli shader del gatto e del pinguino, avviati da soli, non
    # compilavano: prendevano solo il common.glsl generico invece di common e testo della loro timeline
    from demogen.cli import _payload_from_file

    items = menu.examples(shaders=True)
    assert REPO / "examples" / "whisker_hunt.timeline.json" in items
    for f in items:
        res = harness.load(_payload_from_file(f, 120.0))
        assert res["ok"], f"{f.name}: " + "\n".join(res["errors"])[:800]


def test_find_entry_per_numero_e_per_nome() -> None:
    assert menu.find_entry("1").name == "generate"
    assert menu.find_entry(" Music ").name == "music"
    assert menu.find_entry("99") is None and menu.find_entry("") is None


def test_azione_list_e_azione_sconosciuta(quiet) -> None:
    assert menu.main("list") == 0
    out = quiet.export_text()
    assert "generate" in out and "[CPU+]" in out and "[GPU]" in out
    assert menu.main("nope") == 2
    assert "unknown action: nope" in quiet.export_text()


def test_ui_non_interattiva_usa_i_default_e_conferma_solo_con_yes() -> None:
    ui = menu.Ui(interactive=False, yes=False)
    assert ui.ask("x", "def") == "def"
    assert ui.confirm("go?", True) is False
    assert menu.Ui(interactive=False, yes=True).confirm("go?", False) is True
    assert ui.choice("style", ["modern", "retro"], "retro") == "retro"
    assert ui.number("bpm", 128, 60, 200) == 128
    with pytest.raises(ValueError):
        ui.choice("style", ["modern", "retro"], "nope")
    with pytest.raises(ValueError):
        ui.number("bpm", 500, 60, 200)


def test_scelte_per_numero_e_per_prefisso(monkeypatch) -> None:
    answers = iter(["2", "ret", "3"])
    ui = menu.Ui()
    monkeypatch.setattr(ui, "ask", lambda label, default="": next(answers))
    assert ui.choice("style", ["modern", "retro"], "modern") == "retro"
    assert ui.choice("style", ["modern", "retro"], "modern") == "retro"
    assert ui.pick("Example:", ["a", "b", "c"], str) == "c"


def test_genera_finta_passa_gli_argomenti_alla_cli(quiet, calls) -> None:
    assert menu.do_generate(menu.Ui(interactive=False), fake=True)
    (args,) = calls
    assert args[:12] == ["generate", "neon plasma pulsing on the kick", "--duration", "8", "--bpm", "120",
                         "--profile", "modern", "--gpu", "swiftshader", "--project", args[11]]
    assert args[11].startswith("projects/") and args[11].endswith("_neon-plasma-pulsing-on-the")
    assert args[-1] == "--fake" and "--max-cost" not in args
    assert "--music" not in args and "--no-music" not in args  # musica sì, prompt vuoto = dal prompt della demo


def test_genera_con_musica_e_tetto_di_spesa(quiet, calls, monkeypatch) -> None:
    cfg = Config.model_validate({"providers": {}, "roles": {}, "budget": {"max_total_cost_usd": 0.8}})
    monkeypatch.setattr(menu, "config_status", lambda: (cfg, ""))
    answers = {"prompt (empty = cancel)": 'a "cat" sprite', "music prompt": "chiptune"}

    ui = menu.Ui(interactive=False, yes=True)
    monkeypatch.setattr(ui, "ask", lambda label, default="": next(
        (v for k, v in answers.items() if label.startswith(k)), default))
    assert menu.do_generate(ui)
    (args,) = calls
    assert args[1] == "a 'cat' sprite"  # le virgolette doppie romperebbero la riga di comando su Windows
    assert args[args.index("--music") + 1] == "chiptune"
    assert args[args.index("--max-cost") + 1] == "0.8"
    assert args[args.index("--bpm") + 1] == "128" and "--fake" not in args


def test_genera_reale_senza_conferma_non_spende(quiet, calls, monkeypatch) -> None:
    cfg = Config.model_validate({"providers": {}, "roles": {}})
    monkeypatch.setattr(menu, "config_status", lambda: (cfg, ""))
    ui = menu.Ui(interactive=False, yes=False)
    monkeypatch.setattr(ui, "ask", lambda label, default="": "x" if label.startswith("prompt") else default)
    assert menu.do_generate(ui) is False
    assert calls == []


def test_genera_reale_senza_config(quiet, calls, monkeypatch) -> None:
    monkeypatch.setattr(menu, "config_status", lambda: (None, "demogen.yaml missing"))
    assert menu.do_generate(menu.Ui(interactive=False, yes=True)) is False
    assert calls == [] and "demogen.yaml missing" in quiet.export_text()


def test_musica_di_un_progetto(quiet, calls, monkeypatch, tmp_path: Path) -> None:
    proj = tmp_path / "p"
    (proj / "audio").mkdir(parents=True)
    (proj / "state.json").write_text("{}", encoding="utf-8")
    (proj / "audio" / "best.json").write_text('{"version": "v2"}', encoding="utf-8")
    monkeypatch.setattr(menu, "select_project", lambda ui: proj)
    ui = menu.Ui(interactive=False)
    monkeypatch.setattr(ui, "ask", lambda label, default="": "acid techno" if label.startswith("music") else default)
    assert menu.do_music(ui)
    assert calls == [["music", str(proj), "--prompt", "acid techno"]]
    assert "current music: v2" in quiet.export_text()


def _scripted(ui: menu.Ui, monkeypatch, answers: dict[str, list[str]]) -> None:
    """Risposte in ordine per etichetta (prefisso); le altre domande prendono il default."""

    def ask(label: str, default: str = "") -> str:
        for k, vals in answers.items():
            if label.startswith(k) and vals:
                return vals.pop(0)
        return default

    monkeypatch.setattr(ui, "ask", ask)


def test_genera_reale_con_revisione_del_piano(quiet, calls, monkeypatch) -> None:
    cfg = Config.model_validate({"providers": {}, "roles": {}, "budget": {"max_total_cost_usd": 0.5}})
    monkeypatch.setattr(menu, "config_status", lambda: (cfg, ""))
    monkeypatch.setattr(menu, "paused_for_plan", lambda p: True)
    ui = menu.Ui(interactive=False, yes=True)
    _scripted(ui, monkeypatch, {"prompt": ["a cat hunting"]})
    assert menu.do_generate(ui)
    # generate stampa già il piano (niente seconda stampa); di default poi si continua
    gen, resume = calls
    assert "--review-plan" in gen and gen[gen.index("--max-cost") + 1] == "0.5"
    proj = gen[gen.index("--project") + 1]
    assert resume == ["resume", str(menu.REPO / proj), "--gpu", "swiftshader", "--max-cost", "0.5"]
    out = quiet.export_text()
    assert "plan review: stop after the plan" in out and "most of the cost comes later" in out


def test_revisione_del_piano_modifica_e_nota(quiet, calls, monkeypatch, tmp_path: Path) -> None:
    from tests.test_plan_review import _spec

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "spec.json").write_text(_spec().model_dump_json(), encoding="utf-8")
    ui = menu.Ui(interactive=False)
    _scripted(ui, monkeypatch, {"plan (": ["edit", "edit", "note", "stop"], "scene (": ["s2", "s1"],
                                "what to change": ["title", "motion"], "new title of s2": ['a "big" cat'],
                                "new motion of s1": [""], "what should change?": ["black cat"]})
    assert menu.review_plan(ui, proj, fake=True, gpu="swiftshader") is True
    plan = ["plan", str(proj), "--no-hints"]
    assert calls == [  # il piano si stampa una volta: all'inizio, poi dai comandi che lo cambiano
        plan,
        [*plan, "--scene", "s2", "--title", "a 'big' cat"],
        # motion vuota: niente da cambiare, nessuna chiamata
        [*plan, "--note", "black cat", "--fake"],
    ]
    assert "continue later with Resume" in quiet.export_text()


def test_un_progetto_fermo_al_piano(quiet, calls, monkeypatch, tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "state.json").write_text(json.dumps({"done": ["S0"], "paused": "plan"}), encoding="utf-8")
    assert "plan ready for review" in menu.project_label(proj)
    monkeypatch.setattr(menu, "select_project", lambda ui: proj)
    assert menu.do_resume(menu.Ui(interactive=False))  # il resume passa dalla revisione del piano
    assert calls == [["plan", str(proj), "--no-hints"], ["resume", str(proj), "--gpu", "swiftshader"]]


def test_anteprima_di_una_scena_dal_menu(quiet, calls, monkeypatch, tmp_path: Path) -> None:
    from tests.test_plan_review import _drawn_project

    proj = _drawn_project(tmp_path)
    monkeypatch.setattr(menu, "select_project", lambda ui: proj)
    assert menu.run_entry(menu.find_entry("preview"), menu.Ui(interactive=False))
    assert calls == [["play", str(proj), "--scene", "s1", "--version", "1", "--gpu", "auto"]]
    out = quiet.export_text()
    assert "s1  Plasma: v1, v2 (best v1)" in out and "s2  Plasma variant: no shader yet" in out


def test_lo_slug_del_progetto() -> None:
    assert menu.slug("8-bit Pixel Art Cat: sprite in side view!") == "8-bit-pixel-art-cat-sprite-in"
    assert menu.slug("città già") == "citta-gia"
    assert menu.slug("???") == "demo"
    assert menu.slug("a" * 40) == "a" * 30
    assert menu.slug("neon plasma pulsing on the beat") == "neon-plasma-pulsing-on-the"  # 31 caratteri


def test_header_e_menu_si_disegnano(quiet, monkeypatch) -> None:
    monkeypatch.setattr(menu, "demogen_processes", lambda: [])
    quiet.print(menu.header())
    quiet.print(menu.menu_body(menu.ENTRIES))
    out = quiet.export_text()
    assert "D E M O G E N" in out and "CONTROL DECK" in out and "GPU  Test GPU" in out
    for section in ("MAIN", "EXAMPLES", "SETUP & TESTS", "PROCESSES"):
        assert section in out
    assert "0  quit" in out


def test_menu_interattivo_esce_con_zero(quiet, monkeypatch) -> None:
    monkeypatch.setattr(menu, "demogen_processes", lambda: [])
    answers = iter(["zzz", "0"])  # una scelta non valida ridisegna il menu, poi si esce
    monkeypatch.setattr(menu.Prompt, "ask", lambda *a, **k: next(answers))
    assert menu.main() == 0
    assert "bye" in quiet.export_text()


def test_i_processi_non_includono_il_menu_stesso() -> None:
    pids = {p["pid"] for p in menu.demogen_processes()}
    assert os.getpid() not in pids


def test_tabella_processi_con_console_stretta(quiet) -> None:
    menu.console = Console(record=True, width=80, force_terminal=False)
    menu.process_table([{"pid": 18580, "kind": "Playwright browser", "name": "chrome-headless-shell.exe",
                         "mb": 97, "cmd": "C:/a/very/long/command/line " * 6}])
    out = menu.console.export_text()
    assert "18580" in out and "97" in out and "PID" in out and "MB" in out


def test_spawn_restituisce_il_codice_di_uscita() -> None:
    assert menu.spawn([sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert menu.spawn([sys.executable, "-c", "pass"]) == 0


# ---------------------------------------------------------------- lanciatore Node + TypeScript (scripts/run.mts)
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node.js non installato")
LAUNCHER = REPO / "scripts" / "run.mts"


def _launch(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run([NODE, str(LAUNCHER), *args], capture_output=True, text=True, encoding="utf-8",
                          cwd=REPO, timeout=timeout)


def test_niente_piu_powershell_e_lanciatori_presenti() -> None:
    assert not (REPO / "run.ps1").exists()
    cmd = (REPO / "run.cmd").read_bytes()
    assert b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b"")  # i .cmd vogliono CRLF
    assert b"scripts\\run.mts" in cmd
    assert b"scripts/run.mts" in (REPO / "run.sh").read_bytes()
    pkg = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    assert pkg["scripts"]["menu"] == "node scripts/run.mts"


@needs_node
def test_lanciatore_avvia_il_menu() -> None:
    res = _launch("--action", "list")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "generate" in res.stdout and "kill" in res.stdout


@needs_node
def test_lanciatore_errori_e_aiuto() -> None:
    res = _launch("--action", "nope")
    assert res.returncode == 2 and "unknown action: nope" in res.stdout + res.stderr
    res = _launch("--bogus")
    assert res.returncode == 2 and "unknown option: --bogus" in res.stderr
    res = _launch("--help")
    assert res.returncode == 0 and "npm run menu -- --action" in res.stdout


@needs_node
def test_lanciatore_accetta_anche_le_opzioni_di_run_ps1() -> None:
    code = ("import { parseArgs, menuArgs } from './scripts/run.mts';"
            "const a = parseArgs(['-Action', 'kill', '-Yes', '-Setup']);"
            "const b = parseArgs(['--action=list']);"
            "console.log(JSON.stringify([a, menuArgs(a), b]));")
    res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True,
                         encoding="utf-8", cwd=REPO, timeout=60)
    assert res.returncode == 0, res.stderr
    a, args, b = json.loads(res.stdout.strip().splitlines()[-1])
    assert a == {"action": "kill", "yes": True, "setup": True, "help": False}
    assert args == ["run", "--quiet", "demogen", "menu", "--action", "kill", "--yes"]
    assert b["action"] == "list"


@pytest.mark.skipif(not (REPO / "node_modules" / ".bin").exists(), reason="npm install non eseguito")
def test_lanciatore_typecheck() -> None:
    tsc = REPO / "node_modules" / ".bin" / ("tsc.cmd" if sys.platform == "win32" else "tsc")
    res = subprocess.run([str(tsc), "-p", str(REPO / "scripts" / "tsconfig.json")], capture_output=True, text=True,
                         cwd=REPO, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
