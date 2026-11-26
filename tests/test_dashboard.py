"""Bus degli eventi di avanzamento e pannello dal vivo (senza browser)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from demogen import progress
from demogen.dashboard import Dashboard


def _console(width: int = 100) -> Console:
    return Console(file=io.StringIO(), width=width, force_terminal=True, color_system="truecolor", record=True)


def test_emit_senza_iscritti_e_listener_che_solleva() -> None:
    progress.emit("step", step="S0", state="run")  # nessun iscritto: non succede nulla
    seen: list = []

    def broken(ev, d):
        raise RuntimeError("UI rotta")

    off_broken = progress.subscribe(broken)
    off_seen = progress.subscribe(lambda ev, d: seen.append((ev, d)))
    try:
        progress.emit("step", step="S0", state="run")  # il listener rotto non ferma gli altri
    finally:
        off_broken()
        off_seen()
    progress.emit("step", step="S1", state="run")  # disiscritto
    assert seen == [("step", {"step": "S0", "state": "run"})]


def test_llm_call_riporta_esito_e_dati() -> None:
    seen: list = []
    off = progress.subscribe(lambda ev, d: seen.append((ev, d)))
    try:
        with progress.llm_call("critic", "m", "critique") as call:
            call.update(cost=0.01, prompt_tokens=10)
        with pytest.raises(ValueError), progress.llm_call("fixer", "m", "fixer:s1"):
            raise ValueError("x")
    finally:
        off()
    ends = [d for ev, d in seen if ev == "llm.end"]
    assert ends[0]["ok"] is True and ends[0]["cost"] == 0.01
    assert ends[1]["ok"] is False and ends[1]["error"] == "ValueError"
    assert seen[0][1]["id"] != seen[2][1]["id"]


def test_client_reale_emette_inizio_e_fine(tmp_path) -> None:
    from demogen.llm.client import LLMClient
    from tests.fake_openai import FakeOpenAI, chat_response
    from tests.test_llm import make_config

    seen: list = []
    off = progress.subscribe(lambda ev, d: seen.append((ev, d)))
    try:
        with FakeOpenAI([(200, chat_response("ok"))]) as fake:
            c = LLMClient(make_config(fake.url), "orchestrator", log_dir=tmp_path, max_retries=0)
            c.chat([{"role": "user", "content": "hi"}], step="style")
    finally:
        off()
    kinds = [ev for ev, _ in seen]
    assert kinds[0] == "llm.start" and kinds[-1] == "llm.end"
    end = seen[-1][1]
    assert end["ok"] and end["step"] == "style" and end["completion_tokens"] > 0


def _run_events(emit) -> None:
    emit("pipeline.start", project="p/demo", prompt="neon", gpu="swiftshader", fake=False, cap=1.0,
         spent=0.0, max_iter=3, models={"orchestrator": "z-ai/glm-5.3"})
    emit("step", step="S0", state="run", detail="brief")
    emit("step", step="S0", state="done")
    emit("spec", title="Neon", duration=16, bpm=120, profile="modern",
         scenes=[{"id": "s1", "title": "Gate"}, {"id": "s2", "title": "Plasma"}])
    emit("step", step="S1", state="done")
    emit("step", step="S2", state="done")
    emit("step", step="SC", state="run", detail="scene")


def test_pannello_completo_dal_vivo() -> None:
    con = _console()
    with Dashboard("generate", console=con, refresh_per_second=30) as d:
        _run_events(progress.emit)
        progress.emit("llm.start", id=1, role="critic", model="mistralai/mistral-large-4-0", step="critique")
        progress.emit("scene", scene="s1", phase="probe", version=1, detail="flash a 30 fps")
        progress.emit("scene.result", scene="s1", version=1, verdict="revise", score=4.7, best="v1",
                      blockers=["flash: 5/s > 3/s"])
        progress.emit("budget", spent=0.186, cap=1.0)
        middle = d.overall()
        con.print(d.render())  # fotogramma intermedio
        progress.emit("llm.end", id=1, role="critic", model="m", step="critique", ok=True, cost=0.004)
        for s in ("s1", "s2"):
            progress.emit("scene.done", scene=s, best="v2", score=8.1)
        progress.emit("step", step="SC", state="done")
        progress.emit("step", step="S9", state="done")
    text = con.export_text()
    assert 0.2 < middle < 1.0 and d.overall() == 1.0
    for s in ("S4-7 SCENE", "Gate", "probing", "flash: 5/s", "mistral-large-4-0", "0.186", "COMPLETED", "8.10"):
        assert s in text, s
    progress.emit("step", step="S0", state="run")  # disiscritto all'uscita
    assert d.steps["S0"] == "done"


@pytest.mark.parametrize(("exc", "outcome", "label"), [
    (RuntimeError("boom"), "error", "ERROR"),
    (KeyboardInterrupt(), "interrupted", "INTERRUPTED"),
])
def test_pannello_in_caso_di_errore(exc: BaseException, outcome: str, label: str) -> None:
    con = _console()
    with pytest.raises(type(exc)), Dashboard("resume", console=con) as d:
        _run_events(progress.emit)
        raise exc
    assert d.outcome == outcome
    assert label in con.export_text()


def test_stop_per_budget() -> None:
    con = _console()
    with Dashboard(console=con) as d:
        _run_events(progress.emit)
        progress.emit("stop", reason="budget: 1.02 > 1.0 USD")
    assert d.outcome == "budget" and "BUDGET STOP" in con.export_text()


def test_pausa_dopo_il_piano() -> None:
    con = _console(140)
    with Dashboard("generate", console=con) as d:
        progress.emit("pipeline.start", project="p/demo", prompt="cat", gpu="swiftshader", fake=True)
        progress.emit("step", step="S0", state="done")
        progress.emit("pause", reason="plan", project="p/demo")
    out = con.export_text()
    assert d.outcome == "paused" and "PLAN READY" in out
    assert "demogen plan p/demo" in d.last and "demogen resume p/demo" in d.last
    assert "COMPLETED" not in out


def test_avanzamento_della_scena_non_torna_indietro() -> None:
    d = Dashboard(console=_console())
    _run_events(lambda ev, **kw: d.on_event(ev, kw))
    fracs = []
    for phase in ("compile", "probe", "critic", "revise", "compile", "probe", "critic", "revise", "probe"):
        d.on_event("scene", {"scene": "s1", "phase": phase, "version": 1})
        fracs.append(d.scenes["s1"].frac)
    assert fracs == sorted(fracs) and fracs[-1] < 1.0
    d.on_event("scene.done", {"scene": "s1", "best": "v3", "score": 8.0})
    assert d.scenes["s1"].frac == 1.0 and d.scenes["s1"].version == 3


@pytest.mark.parametrize("width", [60, 80, 140])
def test_rendering_a_varie_larghezze(width: int) -> None:
    con = _console(width)
    d = Dashboard(console=con)
    _run_events(lambda ev, **kw: d.on_event(ev, kw))
    d.on_event("llm.start", {"id": 9, "role": "orchestrator", "model": "z-ai/glm-5.3", "step": "revise:s1"})
    con.print(d.render())
    lines = con.export_text().splitlines()
    assert lines and max(len(line) for line in lines) <= width


OPENROUTER_402 = {"error": {
    "message": "This request requires more credits, or fewer max_tokens. You requested up to 16000 tokens, "
               "but can only afford 2756.",
    "code": 402,
    "metadata": {"provider_name": "Z.AI", "raw": "insufficient balance"},
}}


def _status_error(status: int, body):
    import httpx
    from openai import APIStatusError

    resp = httpx.Response(status, request=httpx.Request("POST", "https://x/v1/chat/completions"))
    return APIStatusError(f"Error code: {status} - {body}", response=resp, body=body)


def test_messaggio_del_provider_estratto_e_spiegato() -> None:
    import httpx
    from openai import APIConnectionError

    from demogen.llm.errors import describe_llm_error

    info = describe_llm_error(_status_error(402, OPENROUTER_402))
    assert info is not None and "insufficient credit" in info.title and "(402)" in info.title
    # il testo vero del provider, non il dict Python di str(e)
    assert info.detail.startswith("This request requires more credits") and "can only afford 2756" in info.detail
    assert "Z.AI" in info.detail and "insufficient balance" in info.detail
    assert "max_tokens" in info.hint
    assert "api_key" in describe_llm_error(_status_error(401, {"error": {"message": "No auth"}})).hint
    assert "roles.<role>.model" in describe_llm_error(_status_error(404, None)).hint
    assert "provider-side" in describe_llm_error(_status_error(503, {"error": {"message": "overloaded"}})).title
    conn = APIConnectionError(request=httpx.Request("POST", "https://x"))
    assert "connect" in describe_llm_error(conn).title
    assert describe_llm_error(ValueError("altro")) is None


def test_errore_del_provider_chiaro_nella_cli_e_nel_pannello(capsys) -> None:
    import typer

    from demogen import cli

    events: list = []
    off = progress.subscribe(lambda ev, d: events.append((ev, d)))

    def run():
        with progress.llm_call("critic", "mistralai/mistral-large-4-0", "critique"):
            raise _status_error(402, OPENROUTER_402)

    try:
        with pytest.raises(typer.Exit) as ei:
            cli._guard(run, Path("projects/x"))
    finally:
        off()
    assert ei.value.exit_code == 1
    err = capsys.readouterr().err
    assert "ERROR: insufficient credit" in err
    assert "call:       critic · mistralai/mistral-large-4-0 · step critique" in err
    assert "message:    This request requires more credits" in err
    assert "what to do:" in err and "demogen resume" in err and "projects" in err
    end = [d for ev, d in events if ev == "llm.end"][0]
    assert end["ok"] is False and end["status"] == 402 and "requires more credits" in end["detail"]

    con = _console()
    d = Dashboard(console=con)
    _run_events(lambda ev, **kw: d.on_event(ev, kw))
    for ev, data in events:
        d.on_event(ev, data)
    d.__exit__(typer.Exit, typer.Exit(1), None)
    con.print(d.render())
    text = con.export_text()
    for s in ("ERROR", "insufficient credit", "requires more credits", "what to do", "critic"):
        assert s in text, s


def test_errore_non_del_provider_resta_un_errore_normale() -> None:
    from demogen import cli

    def boom():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        cli._guard(boom)


def test_cli_senza_terminale_usa_il_log_semplice(monkeypatch) -> None:
    from demogen import cli

    called = []
    monkeypatch.setattr(cli, "_guard", lambda fn, project=None: called.append("plain") or fn())
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert cli._execute(lambda: 42, "generate", plain=False) == 42
    assert called == ["plain"]


def test_nessun_ridisegno_se_non_cambia_nulla(monkeypatch) -> None:
    """Anti-sfarfallio: il pannello si ridisegna solo quando cambia qualcosa di visibile."""
    import time

    con = _console()
    with Dashboard("generate", console=con, refresh_per_second=20) as d:
        assert d._live.auto_refresh is False  # niente ridisegno a tempo di rich
        draws = []
        real = d._live.refresh
        monkeypatch.setattr(d._live, "refresh", lambda: (draws.append(time.monotonic()), real())[1])
        time.sleep(0.6)  # fermo: solo l'orologio (al secondo) può cambiare
        idle = len(draws)
        progress.emit("step", step="S0", state="done")
        time.sleep(0.3)
        after_event = len(draws)
    assert idle <= 2, idle  # a 20 fps sarebbero stati ~12 ridisegni
    assert after_event > idle  # un evento ridisegna subito (al tick successivo)


def test_la_firma_cambia_con_lo_stato_visibile() -> None:
    d = Dashboard(console=_console())
    d._t0 = __import__("time").monotonic()
    a = d._signature()
    assert d._signature() == a
    d.on_event("step", {"step": "S1", "state": "done"})
    assert d._signature() != a
