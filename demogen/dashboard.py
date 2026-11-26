"""Pannello dal vivo di generate / resume / revise: estetica neon, dati veri.

Si iscrive agli eventi di `demogen.progress` (la pipeline non sa che esiste) e li disegna
con rich.Live: i passi S0–S9 con la barra di avanzamento, ogni scena con fase, versione e
voto, le chiamate LLM in corso col tempo che scorre, i crediti spesi sul tetto.
Le print() della pipeline finiscono sopra il pannello, così a fine corsa resta anche il log.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import progress

PINK = "#ff2a6d"
MAGENTA = "#f72585"
PURPLE = "#b14aed"
CYAN = "#05d9e8"
GREEN = "#39ff14"
YELLOW = "#ffe600"
RED = "#ff3355"
DIM = "#5a6a8c"
SOFT = "#c9d4f2"
DONE_BEFORE = "#2f9e6e"  # passo già fatto in un run precedente (resume)

_RAMP = ["#ff2a6d", "#f72585", "#d13ed1", "#b14aed", "#7b5cff", "#3d7bff", "#05d9e8", "#00f5d4"]
NEON = _RAMP + _RAMP[-2:0:-1]  # andata e ritorno: nessuno stacco mentre il gradiente scorre
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
EIGHTHS = "▏▎▍▌▋▊▉"

STEPS = (("S0", "BRIEF"), ("S1", "STYLE"), ("S2", "SHADER"), ("SM", "MUSIC"), ("SC", "SCENE"), ("S9", "BUNDLE"))
STEP_WEIGHT = {"S0": 0.05, "S1": 0.05, "S2": 0.15, "SM": 0.07, "SC": 0.58, "S9": 0.10}
MUSIC_ID = "♪"  # la colonna sonora è una riga della tabella, dopo le scene
MUSIC_FRAC = {"compose": 0.15, "listen": 0.5, "revise": 0.7}
# avanzamento di una scena per fase; le revisioni aggiungono poco alla volta (monotono)
PHASE_FRAC = {"compile": 0.10, "fix": 0.15, "probe": 0.30, "critic": 0.55, "revise": 0.75}
ACTIVE_PHASES = {"draft", "math", "compile", "fix", "probe", "critic", "revise", "compose", "listen"}
PHASE_LABEL = {
    "queued": "queued",
    "draft": "drafting the shader",
    "math": "math oracle",
    "drafted": "draft ready, queued",
    "compile": "compiling",
    "fix": "fixer",
    "probe": "probing",
    "critic": "visual critique",
    "revise": "revising",
    "compose": "composing",
    "listen": "listening",
    "done": "done",
}
OUTCOME = {
    None: ("", MAGENTA),
    "ok": ("COMPLETED", GREEN),
    "error": ("ERROR", RED),
    "interrupted": ("INTERRUPTED", YELLOW),
    "budget": ("BUDGET STOP", YELLOW),
}


@dataclass
class SceneView:
    id: str
    title: str = ""
    phase: str = "queued"
    detail: str = ""
    version: int | None = None
    revisions: int = 0
    frac: float = 0.0
    score: float | None = None
    verdict: str = ""
    blockers: list[str] = field(default_factory=list)
    math: tuple[int, int] | None = None
    cost: float | None = None  # p95 in multipli della scena di riferimento

    @property
    def done(self) -> bool:
        return self.phase == "done"


# ---------------------------------------------------------------- pezzi grafici

def _clock(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _mmss(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _short_model(model: str) -> str:
    return str(model).rsplit("/", 1)[-1]


def _tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def neon_text(s: str, shift: float, style: str = "bold") -> Text:
    t = Text()
    for i, ch in enumerate(s):
        t.append(ch, style=f"{style} {NEON[int(i * 0.6 + shift) % len(NEON)]}")
    return t


def neon_bar(frac: float, width: int, shift: float) -> Text:
    """Barra a gradiente che scorre, con 1/8 di blocco di risoluzione."""
    frac = min(1.0, max(0.0, frac))
    cells = frac * width
    full = int(cells)
    t = Text()
    for i in range(full):
        t.append("█", style=NEON[int(i * 0.5 + shift) % len(NEON)])
    used = full
    rem = int((cells - full) * 8)
    if full < width and rem > 0:
        t.append(EIGHTHS[rem - 1], style=NEON[int(full * 0.5 + shift) % len(NEON)])
        used += 1
    t.append("░" * (width - used), style=DIM)
    return t


def seg_bar(frac: float, n: int, color: str) -> Text:
    k = max(0, min(n, round(frac * n)))
    return Text("▰" * k, style=color) + Text("▱" * (n - k), style=DIM)


def _line(*parts: Text) -> Text:
    t = Text(no_wrap=True, overflow="ellipsis")
    for p in parts:
        t.append_text(p)
    return t


# ---------------------------------------------------------------- pannello

class Dashboard:
    """`with Dashboard("generate"): pipeline.run(...)` — si iscrive agli eventi e disegna."""

    def __init__(self, mode: str = "generate", *, console: Console | None = None,
                 refresh_per_second: float = 2.0) -> None:
        self.mode = mode
        self.console = console or Console()
        self.refresh_per_second = refresh_per_second
        self._lock = threading.RLock()
        self._t0 = time.monotonic()
        self._end: float | None = None
        self.prompt = ""
        self.project = ""
        self.gpu = ""
        self.fake = False
        self.models: dict[str, str] = {}
        self.spec: dict[str, Any] | None = None
        self.steps = {k: "pending" for k, _ in STEPS}
        self.step_detail = ""
        self.scenes: dict[str, SceneView] = {}
        self.active: dict[int, dict[str, Any]] = {}
        self.finished: deque[dict[str, Any]] = deque(maxlen=3)
        self.calls = 0
        self.tok_in = 0
        self.tok_out = 0
        self.spent = 0.0
        self.cap: float | None = None
        self.max_ref = 4.0
        self.stopped = ""
        self.error: dict[str, Any] | None = None  # errore che ha fermato la pipeline (provider, pipeline)
        self.last = "powering up…"
        self.outcome: str | None = None
        self._live: Live | None = None
        self._unsub = None
        self._ticking = threading.Event()
        self._ticker: threading.Thread | None = None

    # ------------------------------------------------------------ ciclo di vita
    def __enter__(self) -> Dashboard:
        self._t0 = time.monotonic()
        self._unsub = progress.subscribe(self.on_event)
        # niente auto-refresh: ridisegnare ~25 righe 8 volte al secondo sfarfallava nelle console
        # Windows. Il ticker ridisegna al massimo refresh_per_second volte, e solo se qualcosa è cambiato.
        self._live = Live(
            get_renderable=self.render, console=self.console, auto_refresh=False,
            redirect_stdout=True, redirect_stderr=True, transient=False,
        )
        self._live.start(refresh=True)
        self._ticking.set()
        self._ticker = threading.Thread(target=self._tick, name="demogen-dashboard", daemon=True)
        self._ticker.start()
        return self

    def _tick(self) -> None:
        last = None
        period = 1.0 / max(0.5, self.refresh_per_second)
        while self._ticking.is_set():
            time.sleep(period)
            sig = self._signature()
            if sig != last and self._ticking.is_set() and self._live is not None:
                last = sig
                try:
                    self._live.refresh()
                except Exception:  # noqa: BLE001 - il pannello non deve mai fermare la pipeline
                    pass

    def _signature(self) -> tuple:
        """Tutto ciò che si vede: se non cambia, non si ridisegna."""
        with self._lock:
            now = time.monotonic()
            busy = self.outcome is None and ("run" in self.steps.values() or bool(self.active))
            return (
                self.outcome, self.last, tuple(self.steps.items()), self.step_detail,
                tuple((s.id, s.phase, s.detail, s.version, round(s.frac, 2), s.score, s.verdict,
                       len(s.blockers), s.cost, s.math) for s in self.scenes.values()),
                tuple(sorted(self.active)), len(self.finished), self.calls, round(self.spent, 4),
                self.error is not None, int((self._end or now) - self._t0),  # orologi al secondo
                int(now * self.refresh_per_second) if busy else 0,  # spinner
            )

    def __exit__(self, exc_type, exc, tb) -> bool:
        with self._lock:
            self._end = time.monotonic()
            self.outcome = self._outcome(exc_type, exc)
            if self.outcome == "ok":
                self.last = "demo ready ▸ " + str(Path(self.project) / "out") if self.project else "done"
            elif self.outcome == "budget":
                self.last = f"spending cap reached: bundled the best versions so far ▸ {self.stopped}"
            elif self.outcome == "interrupted":
                self.last = "interrupted ▸ continue from here with: demogen resume <project>"
            elif self.error:
                self.last = f"ERROR ▸ {self.error.get('title')}  (then: demogen resume <project>)"
            else:
                self.last = f"error during: {self.last}  (details above; then demogen resume)"
        self._ticking.clear()
        if self._ticker is not None:
            self._ticker.join(timeout=2.0)
        try:
            if self._live is not None:
                self._live.refresh()
                self._live.stop()
        finally:
            if self._unsub is not None:
                self._unsub()
        return False

    def _outcome(self, exc_type, exc) -> str:
        if exc_type is None or getattr(exc, "exit_code", 1) == 0:
            return "budget" if self.stopped else "ok"
        if issubclass(exc_type, KeyboardInterrupt):
            return "interrupted"
        return "error"

    # ------------------------------------------------------------ eventi
    def on_event(self, event: str, data: dict[str, Any]) -> None:
        handler = getattr(self, "_on_" + event.replace(".", "_"), None)
        if handler is not None:
            with self._lock:
                handler(data)

    def _scene(self, scene_id: str) -> SceneView:
        return self.scenes.setdefault(scene_id, SceneView(scene_id))

    def _on_pipeline_start(self, d: dict[str, Any]) -> None:
        self.prompt = str(d.get("prompt") or "")
        self.project = str(d.get("project") or "")
        self.gpu = str(d.get("gpu") or "")
        self.fake = bool(d.get("fake"))
        self.models = dict(d.get("models") or {})
        self.cap = d.get("cap")
        self.spent = float(d.get("spent") or 0.0)
        self.max_ref = float(d.get("max_ref") or self.max_ref)
        self.last = "uplink established"

    def _on_step(self, d: dict[str, Any]) -> None:
        step, state = d.get("step"), d.get("state")
        if step not in self.steps:
            return
        self.steps[step] = state
        label = ("S4-7" if step == "SC" else step) + " " + dict(STEPS)[step]
        if state == "run":
            self.step_detail = str(d.get("detail") or "")
            self.last = f"{label} ▸ {self.step_detail}"
        elif state == "done":
            self.last = f"{label} completed"

    def _on_spec(self, d: dict[str, Any]) -> None:
        self.spec = d
        for s in d.get("scenes") or []:
            self._scene(s["id"]).title = str(s.get("title") or "")
        self.last = f"spec received ▸ {d.get('title')} · {len(self.scenes)} scenes"

    def _on_scene(self, d: dict[str, Any]) -> None:
        sv = self._scene(d["scene"])
        phase = str(d.get("phase") or "")
        if phase == "revise":
            sv.revisions += 1
        sv.phase = phase
        sv.detail = str(d.get("detail") or "")
        if d.get("version"):
            sv.version = int(d["version"])
        if phase in PHASE_FRAC:
            bonus = 0.2 * (1 - 0.5 ** sv.revisions)
            sv.frac = max(sv.frac, min(0.95, PHASE_FRAC[phase] + bonus))
        self.last = f"{sv.id} ▸ {PHASE_LABEL.get(phase, phase)}" + (f": {sv.detail}" if sv.detail else "")

    def _music(self) -> SceneView:
        sv = self._scene(MUSIC_ID)
        sv.title = "soundtrack"
        return sv

    def _on_music(self, d: dict[str, Any]) -> None:
        sv = self._music()
        phase = str(d.get("phase") or "")
        if phase == "revise":
            sv.revisions += 1
        sv.phase, sv.detail = phase, str(d.get("detail") or "")
        if d.get("version"):
            sv.version = int(d["version"])
        if phase in MUSIC_FRAC:
            sv.frac = max(sv.frac, min(0.95, MUSIC_FRAC[phase] + 0.1 * sv.revisions))
        self.last = f"music ▸ {PHASE_LABEL.get(phase, phase)}" + (f": {sv.detail}" if sv.detail else "")

    def _on_music_result(self, d: dict[str, Any]) -> None:
        sv = self._music()
        problems = [str(i) for i in d.get("issues") or []]
        sv.blockers = problems if not d.get("ok") else []
        sv.verdict = "ok" if d.get("ok") else "retake"
        msg = f"music v{d.get('version')} ▸ " + ("listened: ok" if d.get("ok") else "needs another take")
        if problems:
            msg += f" · {problems[0]}"
        self.last = msg

    def _on_music_done(self, d: dict[str, Any]) -> None:
        sv = self._music()
        sv.phase, sv.frac, sv.detail = "done", 1.0, ""
        best = str(d.get("best") or "")
        if best[1:].isdigit():
            sv.version, sv.verdict, sv.blockers = int(best[1:]), "ok", []
            self.last = f"music ready ▸ {best}"
        else:
            sv.verdict = "silent demo"
            self.last = "music: no usable version, the demo will be silent"

    def _on_scene_result(self, d: dict[str, Any]) -> None:
        sv = self._scene(d["scene"])
        sv.score = d.get("score")
        sv.verdict = str(d.get("verdict") or "")
        sv.blockers = [str(b) for b in d.get("blockers") or []]
        if d.get("cost") is not None:
            sv.cost = float(d["cost"])
        msg = f"{sv.id} v{d.get('version')} ▸ critique: {sv.verdict}, best score {sv.score}"
        if sv.blockers:
            msg += f" · BLOCKER: {sv.blockers[0]}"
        self.last = msg

    def _on_scene_done(self, d: dict[str, Any]) -> None:
        sv = self._scene(d["scene"])
        sv.phase, sv.frac, sv.detail = "done", 1.0, ""
        best = str(d.get("best") or "")
        if best[1:].isdigit():
            sv.version = int(best[1:])
        if d.get("score") is not None:
            sv.score = d["score"]
        self.last = f"{sv.id} done ▸ best {best or '?'}, score {sv.score}"

    def _on_math(self, d: dict[str, Any]) -> None:
        sv = self._scene(d["scene"])
        sv.math = (int(d.get("accepted") or 0), int(d.get("rejected") or 0))
        self.last = f"{sv.id} ▸ math oracle: {sv.math[0]} accepted, {sv.math[1]} rejected"

    def _on_llm_start(self, d: dict[str, Any]) -> None:
        self.active[d["id"]] = {**d, "t": time.monotonic()}
        self.last = f"uplink ▸ {d.get('role')} · {_short_model(d.get('model', ''))} · {d.get('step')}"

    def _on_llm_end(self, d: dict[str, Any]) -> None:
        call = self.active.pop(d["id"], None) or {}
        self.calls += 1
        self.tok_in += int(d.get("prompt_tokens") or 0)
        self.tok_out += int(d.get("completion_tokens") or 0)
        self.finished.appendleft({**d, "dt": time.monotonic() - call.get("t", time.monotonic())})
        if not d.get("ok"):
            code = f"{d['status']} " if d.get("status") else ""
            self.last = (f"uplink ✗ {d.get('role')} · {d.get('step')}: {code}"
                         f"{d.get('detail') or d.get('error')}")

    def _on_budget(self, d: dict[str, Any]) -> None:
        self.spent = float(d.get("spent") or 0.0)
        if d.get("cap") is not None:
            self.cap = d["cap"]

    def _on_error(self, d: dict[str, Any]) -> None:
        self.error = dict(d)
        self.last = f"ERROR ▸ {d.get('title')}"

    def _on_stop(self, d: dict[str, Any]) -> None:
        self.stopped = str(d.get("reason") or "")
        self.last = f"early stop ▸ {self.stopped}"

    # ------------------------------------------------------------ avanzamento
    def overall(self) -> float:
        if self.outcome == "ok":
            return 1.0
        scenes = [s for s in self.scenes.values() if s.id != MUSIC_ID]
        n = len(scenes)
        total = 0.0
        for step, w in STEP_WEIGHT.items():
            st = self.steps[step]
            if st in ("done", "skip"):
                f = 1.0
            elif st != "run":
                f = 0.0
            elif step == "S2" and n:
                f = sum(s.phase == "drafted" for s in scenes) / n
            elif step == "SC" and n:
                f = sum(s.frac for s in scenes) / n
            elif step == "SM" and MUSIC_ID in self.scenes:
                f = self.scenes[MUSIC_ID].frac
            else:
                f = 0.4
            total += w * f
        return min(total, 0.99)

    # ------------------------------------------------------------ disegno
    def render(self) -> RenderableType:
        with self._lock:
            now = time.monotonic()
            shift = 0.0  # gradiente fermo: colori che cambiano a ogni fotogramma = sfarfallio
            body = Group(
                self._header(now),
                self._rule("PIPELINE"),
                self._pipeline(now, shift),
                self._rule("SCENES"),
                self._scene_table(now),
                self._rule("LLM UPLINK  ·  CREDITS"),
                self._bottom(now),
                *self._error_box(),
            )
            color = OUTCOME[self.outcome][1] if self.outcome else PURPLE
            width = max(20, self.console.width - 8)
            subtitle = Text("» " + self.last, style=f"bold {color if self.outcome else CYAN}")
            subtitle.truncate(width, overflow="ellipsis")
            return Panel(
                body, box=box.HEAVY, border_style=color, padding=(0, 1),
                title=self._title(now, shift), title_align="left",
                subtitle=subtitle, subtitle_align="left",
            )

    def _title(self, now: float, shift: float) -> Text:
        word = "D E M O G E N"
        return Text(" ▞▚ ", style=f"bold {PINK}") + neon_text(word, shift) + Text(" ▚▞ ", style=f"bold {CYAN}")

    def _rule(self, title: str) -> Rule:
        return Rule(Text(f" {title} ", style=f"bold {CYAN}"), style=DIM, align="left", characters="─")

    def _kv(self, key: str, value: Text) -> Text:
        return _line(Text(f"{key:<7}", style=f"bold {PINK}"), Text("▸ ", style=DIM), value)

    def _header(self, now: float) -> RenderableType:
        tag, color = OUTCOME[self.outcome]
        tag = tag or self.mode.upper()
        top = Table.grid(expand=True)
        top.add_column()
        top.add_column(justify="right")
        top.add_row(
            _line(Text("NEURAL DEMO FORGE", style=f"bold {SOFT}"), Text("  //  ", style=DIM),
                  Text(f"◢ {tag} ◣", style=f"bold {color}")),
            Text("T+", style=DIM) + Text(_clock((self._end or now) - self._t0), style=f"bold {CYAN}"),
        )
        lines: list[RenderableType] = [top, self._kv("PROMPT", Text(self.prompt or "—", style=SOFT))]
        if self.spec:
            s = self.spec
            n = len([x for x in self.scenes if x != MUSIC_ID])
            lines.append(self._kv("SPEC", Text(
                f"{s.get('title')} · {n} scenes · {float(s.get('duration') or 0):.0f} s · "
                f"{float(s.get('bpm') or 0):g} bpm · {s.get('profile')}", style=SOFT)))
        else:
            lines.append(self._kv("SPEC", Text("incoming from the LLM…", style=DIM)))
        models = " · ".join(_short_model(m) for m in dict.fromkeys(self.models.values())) or "—"
        lines.append(_line(
            Text(f"{'NODE':<7}", style=f"bold {PINK}"), Text("▸ ", style=DIM),
            Text(Path(self.project).name if self.project else "—", style=SOFT),
            Text("   GPU ", style=f"bold {PINK}"), Text(self.gpu or "—", style=SOFT),
            Text("   LLM ", style=f"bold {PINK}"), Text(models, style=SOFT),
        ))
        return Group(*lines)

    def _pipeline(self, now: float, shift: float) -> RenderableType:
        chips = Text(no_wrap=True, overflow="ellipsis")
        for i, (step, name) in enumerate(STEPS):
            st = self.steps[step]
            label = ("S4-7" if step == "SC" else step) + " " + name
            if i:
                chips.append(" ━ ", style=DIM)
            if st == "done":
                chips.append("■ " + label, style=f"bold {GREEN}")
            elif st == "skip":
                chips.append("■ " + label, style=DONE_BEFORE)
            elif st == "run":
                if self.outcome is None:
                    spin = SPIN[int(now * self.refresh_per_second) % len(SPIN)]
                    chips.append(spin + " " + label, style=f"bold {MAGENTA}")
                else:
                    chips.append("◆ " + label, style=f"bold {OUTCOME[self.outcome][1]}")
            else:
                chips.append("□ " + label, style=DIM)
        frac = self.overall()
        width = max(10, min(60, self.console.width - 16))
        bar = Text("  ") + neon_bar(frac, width, shift) + Text(f" {frac * 100:3.0f}%", style=f"bold {SOFT}")
        detail = {
            None: self.step_detail,
            "ok": "all steps completed",
            "budget": "stopped by the spending cap",
            "interrupted": "stopped from the keyboard",
            "error": "stopped by an error",
        }[self.outcome]
        return Group(Text("  ") + chips, bar, Text("  " + detail, style=DIM, no_wrap=True, overflow="ellipsis"))

    def _scene_table(self, now: float) -> RenderableType:
        if not self.scenes:
            msg = "waiting for the spec: the LLM is writing the scenes…" if self.outcome is None else "no scenes"
            return Text("  " + msg, style=DIM)
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column(no_wrap=True)  # id
        t.add_column(no_wrap=True, max_width=22, overflow="ellipsis")  # titolo
        t.add_column(no_wrap=True)  # segmenti
        t.add_column(no_wrap=True, justify="right")  # versione
        t.add_column(no_wrap=True, justify="right")  # costo relativo
        t.add_column(no_wrap=True, ratio=1, overflow="ellipsis")  # fase
        t.add_column(no_wrap=True, justify="right")  # voto
        t.add_column(no_wrap=True, max_width=36, overflow="ellipsis")  # verdetto / blocker
        for sv in self.scenes.values():
            t.add_row(
                Text(" " + sv.id, style=f"bold {CYAN}"),
                Text(sv.title, style=SOFT),
                seg_bar(sv.frac, 6, GREEN if sv.done else MAGENTA),
                Text(f"v{sv.version}" if sv.version else "", style=PURPLE),
                self._cost_cell(sv.cost),
                self._phase_cell(sv, now),
                self._score_cell(sv.score),
                self._verdict_cell(sv),
            )
        return t

    def _phase_cell(self, sv: SceneView, now: float) -> Text:
        if sv.done:
            t = Text("✓ done", style=f"bold {GREEN}")
        elif sv.phase in ACTIVE_PHASES and self.outcome is None:
            t = Text(SPIN[int(now * self.refresh_per_second + len(sv.id)) % len(SPIN)] + " ", style=f"bold {MAGENTA}")
            t.append(PHASE_LABEL[sv.phase], style=f"bold {SOFT}")
            if sv.detail:
                t.append(": " + sv.detail, style=DIM)
        elif sv.phase in ACTIVE_PHASES:
            t = Text("◆ " + PHASE_LABEL[sv.phase], style=OUTCOME[self.outcome][1])
        else:
            t = Text("◌ " + PHASE_LABEL.get(sv.phase, sv.phase), style=DIM)
        if sv.math:
            t.append(f"  ∑{sv.math[0]}✓{sv.math[1]}✗", style=PURPLE)
        return t

    def _cost_cell(self, cost: float | None) -> Text:
        """Costo in multipli della scena di riferimento: rosso oltre il limite del gate."""
        if cost is None:
            return Text("")
        col = RED if cost > self.max_ref else YELLOW if cost > 0.6 * self.max_ref else GREEN
        return Text(f"{cost:.1f}×", style=f"bold {col}")

    @staticmethod
    def _score_cell(score: float | None) -> Text:
        if score is None:
            return Text("")
        s = float(score)
        return Text(f"{s:.2f}", style=f"bold {GREEN if s >= 7.5 else YELLOW if s >= 6 else PINK}")

    @staticmethod
    def _verdict_cell(sv: SceneView) -> Text:
        if sv.verdict == "silent demo":
            return Text("⚠ no usable version: silent demo", style=f"bold {RED}")
        if sv.blockers and not sv.done:
            return Text("⚠ " + sv.blockers[0], style=f"bold {RED}")
        if sv.verdict:
            return Text(sv.verdict, style=GREEN if sv.verdict == "accept" else YELLOW)
        return Text("")

    def _error_box(self) -> list[RenderableType]:
        """Riquadro rosso con l'errore che ha fermato la pipeline: titolo, chiamata, messaggio, cosa fare."""
        if not self.error:
            return []
        rows: list[RenderableType] = [
            Rule(Text(" ERROR ", style=f"bold {RED}"), style=RED, align="left", characters="━"),
            Text("✗ " + str(self.error.get("title") or ""), style=f"bold {RED}"),
        ]
        for key, label in (("where", "call"), ("detail", "message"), ("hint", "what to do")):
            val = str(self.error.get(key) or "")
            if val:
                rows.append(Text(f"{label:<10}", style=f"bold {PINK}") + Text(val, style=SOFT))
        return rows

    def _bottom(self, now: float) -> RenderableType:
        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(ratio=3)
        grid.add_column(ratio=2)
        grid.add_row(self._uplink(now), self._credits())
        return grid

    def _uplink(self, now: float) -> RenderableType:
        lines: list[Text] = []
        active = sorted(self.active.values(), key=lambda c: c["t"])
        for c in active[:3]:
            lines.append(_line(
                Text(SPIN[int(now * self.refresh_per_second + c["id"]) % len(SPIN)] + " ", style=f"bold {MAGENTA}"),
                Text(f"{c.get('role', ''):<12} ", style=f"bold {SOFT}"),
                Text(f"{_short_model(c.get('model', '')):<17} ", style=PURPLE),
                Text(f"{c.get('step', ''):<13} ", style=CYAN),
                Text(_mmss(now - c["t"]), style=f"bold {YELLOW}"),
            ))
        if len(active) > 3:
            lines.append(Text(f"  … {len(active) - 3} more in flight", style=DIM))
        if not active:
            lines.append(Text("◌ channel idle" if self.outcome is None else "◌ channel closed", style=DIM))
        for c in list(self.finished)[: max(0, 3 - len(lines))]:
            ok = bool(c.get("ok"))
            cost = c.get("cost")
            lines.append(_line(
                Text("✓ " if ok else "✗ " + (f"{c['status']} " if c.get("status") else ""),
                     style=GREEN if ok else f"bold {RED}"),
                Text(f"{c.get('role', ''):<12} ", style=DIM),
                Text(f"{_short_model(c.get('model', '')):<17} ", style=DIM),
                Text(f"{c.get('step', ''):<13} ", style=DIM),
                Text(f"{c['dt']:.1f}s", style=DIM),
                Text(f"  ${cost:.4f}" if cost else "", style=DIM),
            ))
        while len(lines) < 3:  # altezza fissa: il pannello non salta
            lines.append(Text(""))
        return Group(*lines)

    def _credits(self) -> RenderableType:
        lines: list[Text] = []
        if self.fake:
            lines.append(_line(Text("fake LLM", style=f"bold {PURPLE}"), Text(" · no spending", style=DIM)))
        else:
            cap = float(self.cap or 0.0)
            frac = self.spent / cap if cap > 0 else 0.0
            col = GREEN if frac < 0.6 else YELLOW if frac < 0.85 else RED
            w = 14 if self.console.width >= 100 else 6
            k = max(0, min(w, round(frac * w)))
            lines.append(_line(
                Text("█" * k, style=col), Text("░" * (w - k), style=DIM),
                Text(f" {self.spent:.3f}", style=f"bold {col}"), Text(f" / {cap:.2f} USD", style=DIM),
            ))
        lines.append(_line(
            Text(f"calls {self.calls}", style=SOFT), Text(" · ", style=DIM),
            Text(f"token {_tokens(self.tok_in)} ▸ {_tokens(self.tok_out)}", style=SOFT),
        ))
        lines.append(Text("⚠ " + self.stopped, style=YELLOW, no_wrap=True, overflow="ellipsis")
                     if self.stopped else Text(""))
        return Group(*lines)
