"""Tetti di consumo LLM: per run, giornaliero, mensile, numero di chiamate; registro della spesa; `demogen budget`."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from demogen.cli import app, budget_summary
from demogen.config import Config, ProviderConfig, RoleConfig, load_config, set_budget_values
from demogen.llm.budget import Budget, BudgetExceeded, ledger_path, read_ledger, spend_totals
from demogen.llm.client import LLMClient
from tests.fake_openai import FakeOpenAI, chat_response


def _cfg(url: str = "http://127.0.0.1:1", **budget) -> Config:
    return Config(
        providers={"test": ProviderConfig(type="openai_compatible", base_url=url)},
        roles={"orchestrator": RoleConfig(provider="test", model="fake-1")},
        pricing={"fake-1": {"prompt_per_mtok": 1.0, "completion_per_mtok": 2.0}},
        budget=budget,
    )


def _ledger() -> Path:
    return Path(os.environ["DEMOGEN_SPEND_LEDGER"])  # isolato per test da conftest


def _write_rows(rows: list[dict]) -> None:
    _ledger().parent.mkdir(parents=True, exist_ok=True)
    _ledger().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_totali_di_oggi_e_del_mese() -> None:
    now = datetime(2026, 11, 26, 15, 0)
    rows = [
        {"ts": "2026-11-26T09:00:00", "cost": 0.5},
        {"ts": "2026-11-26T14:59:00", "cost": 0.25},
        {"ts": "2026-11-02T10:00:00", "cost": 1.0},
        {"ts": "2026-10-31T23:59:00", "cost": 9.0},  # mese scorso
    ]
    day, month = spend_totals(rows, now)
    assert day == pytest.approx(0.75)
    assert month == pytest.approx(1.75)


def test_registro_con_righe_rotte_non_blocca() -> None:
    _ledger().parent.mkdir(parents=True, exist_ok=True)
    _ledger().write_text('{"ts": "2026-11-26T09:00:00", "cost": 0.5}\nnon json\n{"cost": "x"}\n[1]\n',
                         encoding="utf-8")
    assert read_ledger(_ledger()) == [{"ts": "2026-11-26T09:00:00", "cost": 0.5}]
    assert read_ledger(None) == []


def test_ogni_chiamata_pagata_finisce_nel_registro() -> None:
    b = Budget.from_config(_cfg(), project="p1")
    b.add("fake-1", 0, 0, 0.01)
    b.add("fake-1", 0, 0, 0.02)
    rows = read_ledger(ledger_path(_cfg()))
    assert [(r["project"], r["model"], r["cost"]) for r in rows] == [("p1", "fake-1", 0.01), ("p1", "fake-1", 0.02)]
    assert b.calls == 2 and b.day_spent == pytest.approx(0.03)


def test_tetto_giornaliero_conta_anche_le_altre_generazioni() -> None:
    today = datetime.now().isoformat(timespec="seconds")
    _write_rows([{"ts": today, "project": "altro", "model": "m", "cost": 0.97}])
    b = Budget.from_config(_cfg(max_daily_cost_usd=1.0, max_total_cost_usd=5.0))
    assert b.day_spent == pytest.approx(0.97) and b.spent_usd == 0  # il run non ha ancora speso nulla
    reason = b.blocking_cap("fake-1", 16000)  # fino a ~0.036 USD: 0.97 + 0.036 > 1.0
    assert reason is not None and reason.startswith("daily cap")
    # un tetto giornaliero più alto lascia passare la stessa chiamata
    assert Budget.from_config(_cfg(max_daily_cost_usd=2.0)).blocking_cap("fake-1", 16000) is None


def test_tetto_mensile() -> None:
    month_day = datetime.now().strftime("%Y-%m") + "-01T08:00:00"
    _write_rows([{"ts": month_day, "cost": 19.99}])
    b = Budget.from_config(_cfg(max_monthly_cost_usd=20.0))
    assert b.blocking_cap("fake-1", 16000).startswith("monthly cap")
    b2 = Budget.from_config(_cfg(max_monthly_cost_usd=20.0))
    b2.add("fake-1", 0, 0, 0.02)
    with pytest.raises(BudgetExceeded, match="monthly spending cap exceeded"):
        b2.check()


def test_tetto_sul_numero_di_chiamate() -> None:
    b = Budget.from_config(_cfg(max_calls_per_run=2))
    for _ in range(2):
        assert b.blocking_cap("fake-1", 10) is None
        b.add("fake-1", 0, 0, 0.0)
    b.check()  # 2 chiamate su 2: ancora valido
    assert b.blocking_cap("fake-1", 10).startswith("call cap: 2 of 2")


def test_senza_tetti_extra_nessun_blocco() -> None:
    b = Budget.from_config(_cfg())
    assert b.max_daily_cost_usd is None and b.max_monthly_cost_usd is None and b.max_calls is None
    assert b.blocking_cap("fake-1", 1000) is None


def test_il_client_blocca_prima_della_chiamata_con_il_motivo(tmp_path: Path) -> None:
    today = datetime.now().isoformat(timespec="seconds")
    _write_rows([{"ts": today, "cost": 3.0}])
    with FakeOpenAI([(200, chat_response("ok", cost=0.001))]) as fake:
        cfg = _cfg(fake.url, max_daily_cost_usd=3.0)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=Budget.from_config(cfg), max_retries=0)
        with pytest.raises(BudgetExceeded, match="budget: daily cap"):
            c.chat([{"role": "user", "content": "hi"}], step="t")
        assert len(fake.requests) == 0  # nessuna chiamata reale


def test_il_client_registra_la_spesa_reale(tmp_path: Path) -> None:
    with FakeOpenAI([(200, chat_response("ok", cost=0.004))]) as fake:
        cfg = _cfg(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=Budget.from_config(cfg, project="demo-x"),
                      max_retries=0)
        c.chat([{"role": "user", "content": "hi"}], step="t")
    rows = read_ledger(_ledger())
    assert len(rows) == 1 and rows[0]["project"] == "demo-x" and rows[0]["cost"] == pytest.approx(0.004)


YAML = """\
providers:
  openrouter:
    type: openai_compatible
    base_url: https://openrouter.ai/api/v1
    api_key: "sk-or-v1-NONVERA"   # resta com'è
roles:
  orchestrator: {provider: openrouter, model: org/m}

budget:
  max_iterations_per_scene: 4
  max_total_cost_usd: 5.0       # per run
  max_daily_cost_usd: null      # giornaliero
  max_wall_minutes: 60

audio:
  min_rms: 0.01
"""


def test_set_budget_values_cambia_solo_le_righe_del_budget(tmp_path: Path) -> None:
    p = tmp_path / "demogen.yaml"
    p.write_text(YAML, encoding="utf-8")
    set_budget_values(p, {"max_total_cost_usd": 2.5, "max_daily_cost_usd": 4.0, "max_calls_per_run": 60})
    text = p.read_text(encoding="utf-8")
    assert '  max_total_cost_usd: 2.5       # per run' in text
    assert '  max_daily_cost_usd: 4      # giornaliero' in text
    assert '  max_calls_per_run: 60' in text
    assert 'api_key: "sk-or-v1-NONVERA"   # resta com\'è' in text
    # la chiave mancante va dentro il blocco budget, non in fondo al file
    assert text.index("max_calls_per_run") < text.index("audio:")
    cfg = load_config(p, interactive=False)
    assert cfg.budget.max_total_cost_usd == 2.5 and cfg.budget.max_daily_cost_usd == 4.0
    assert cfg.budget.max_calls_per_run == 60 and cfg.audio.min_rms == 0.01
    set_budget_values(p, {"max_daily_cost_usd": None})
    assert load_config(p, interactive=False).budget.max_daily_cost_usd is None


def test_set_budget_values_valore_non_valido_lascia_il_file_com_era(tmp_path: Path) -> None:
    p = tmp_path / "demogen.yaml"
    p.write_text(YAML, encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - qualsiasi errore di validazione
        set_budget_values(p, {"max_calls_per_run": "tante"})
    assert p.read_text(encoding="utf-8") == YAML


def test_set_budget_values_senza_blocco_budget(tmp_path: Path) -> None:
    p = tmp_path / "demogen.yaml"
    p.write_text(YAML.split("budget:")[0], encoding="utf-8")
    set_budget_values(p, {"max_monthly_cost_usd": 30.0})
    assert load_config(p, interactive=False).budget.max_monthly_cost_usd == 30.0


def test_cli_budget_imposta_e_mostra(tmp_path: Path) -> None:
    p = tmp_path / "demogen.yaml"
    p.write_text(YAML, encoding="utf-8")
    today = datetime.now().isoformat(timespec="seconds")
    _write_rows([{"ts": today, "project": "a", "cost": 0.2}, {"ts": today, "project": "b", "cost": 0.05}])
    res = CliRunner().invoke(app, ["budget", "--config", str(p), "--daily", "3", "--monthly", "0", "--calls", "40",
                                   "--json"])
    assert res.exit_code == 0, res.output
    s = json.loads(res.output.strip().splitlines()[-1])
    assert s["caps"] == {"run": 5.0, "daily": 3.0, "monthly": None, "calls": 40, "minutes": 60.0}
    assert s["today"] == pytest.approx(0.25) and list(s["projects"]) == ["a", "b"]
    res = CliRunner().invoke(app, ["budget", "--config", str(p)])
    assert res.exit_code == 0 and "per day      3 USD" in res.output and "spent today       0.2500 USD" in res.output


def test_cli_budget_rifiuta_valori_negativi_e_config_mancante(tmp_path: Path) -> None:
    p = tmp_path / "demogen.yaml"
    p.write_text(YAML, encoding="utf-8")
    assert CliRunner().invoke(app, ["budget", "--config", str(p), "--daily", "-1"]).exit_code != 0
    assert CliRunner().invoke(app, ["budget", "--config", str(p), "--run", "0"]).exit_code != 0
    assert p.read_text(encoding="utf-8") == YAML
    res = CliRunner().invoke(app, ["budget", "--config", str(tmp_path / "manca.yaml")])
    assert res.exit_code == 1 and "demogen init" in res.output


def test_budget_summary_per_progetto_ordinato_per_spesa() -> None:
    month = datetime.now().strftime("%Y-%m")
    _write_rows([{"ts": f"{month}-01T10:00:00", "project": "x", "cost": 0.1},
                 {"ts": f"{month}-02T10:00:00", "project": "y", "cost": 0.3},
                 {"ts": f"{month}-03T10:00:00", "project": "x", "cost": 0.05}])
    s = budget_summary(_cfg())
    assert list(s["projects"].items()) == [("y", pytest.approx(0.3)), ("x", pytest.approx(0.15))]


def test_max_cost_della_cli_sovrascrive_il_tetto_per_run(tmp_path: Path, monkeypatch) -> None:
    from demogen import cli
    from demogen.project.store import Project

    p = tmp_path / "demogen.yaml"
    p.write_text(YAML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    pipe = cli._pipeline(Project(tmp_path / "proj"), "swiftshader", False, max_cost=0.4)
    assert pipe.budget.max_total_cost_usd == 0.4
    import typer

    with pytest.raises(typer.BadParameter):
        cli._pipeline(Project(tmp_path / "proj2"), "swiftshader", False, max_cost=0)
