"""Test livello LLM con server OpenAI-compatible finto (nessuna chiamata reale)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from demogen.cli import app
from demogen.config import Config, ProviderConfig, RoleConfig
from demogen.llm.budget import Budget, BudgetExceeded
from demogen.llm.capabilities import Capabilities, detect_capabilities
from demogen.llm.client import LLMClient, redact
from demogen.llm.envelope import parse_envelope
from demogen.llm.structured import chat_structured
from tests.fake_openai import FakeOpenAI, chat_response

FIXTURES = Path(__file__).parent / "fixtures" / "llm"


class SceneMeta(BaseModel):
    scene_id: str
    notes: str = ""
    perf_tier: str = "medium"


def make_config(url: str, **role_kw) -> Config:
    return Config(
        providers={"test": ProviderConfig(type="openai_compatible", base_url=url)},
        roles={"orchestrator": RoleConfig(provider="test", model="fake-1", **role_kw)},
        pricing={"fake-1": {"prompt_per_mtok": 1.0, "completion_per_mtok": 2.0}},
    )


def test_chat_ok_usage_costo(tmp_path: Path) -> None:
    with FakeOpenAI([(200, chat_response("ciao", cost=0.001))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=1)
        r = c.chat([{"role": "user", "content": "hi"}], step="t")
        assert r.content == "ciao"
        assert r.usage["prompt_tokens"] == 10
        assert r.cost_usd == pytest.approx(0.001)  # costo da usage (OpenRouter-style)
        # log salvato e redatto
        logs = list(tmp_path.glob("*.json"))
        assert len(logs) == 1


def test_costo_da_pricing_se_manca_in_usage(tmp_path: Path) -> None:
    with FakeOpenAI([(200, chat_response("x"))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=Budget(100, 60, cfg.pricing))
        r = c.chat([{"role": "user", "content": "hi"}], step="t")
        # 10 prompt * 1.0/1e6 + 20 completion * 2.0/1e6
        assert r.cost_usd == pytest.approx(10 / 1e6 * 1.0 + 20 / 1e6 * 2.0)


def test_envelope_parse_da_fixture() -> None:
    text = (FIXTURES / "envelope_valid.txt").read_text(encoding="utf-8")
    env = parse_envelope(text)
    meta = SceneMeta.model_validate(env.json())
    assert meta.scene_id == "s1" and meta.perf_tier == "medium"
    assert len(env.glsl_blocks) == 1
    assert "mainImage" in env.glsl_blocks[0]


def test_structured_json_schema_e_riparazione(tmp_path: Path) -> None:
    with FakeOpenAI(
        [
            (200, chat_response('{"scene_id": "s1", "perf_tier": "medium"}')),  # valido
        ]
    ) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        caps = Capabilities(vision=False, json_schema=True, source="test")
        out = chat_structured(
            c, [{"role": "user", "content": "dammi i metadati"}], SceneMeta, caps=caps
        )
        assert out.scene_id == "s1"
        # la richiesta aveva response_format json_schema
        assert fake.requests[0]["response_format"]["type"] == "json_schema"

    # riparazione: prima output malformato, poi valido
    with FakeOpenAI(
        [
            (200, chat_response("{non è json")),
            (200, chat_response('{"scene_id": "s2"}')),
        ]
    ) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        out = chat_structured(c, [{"role": "user", "content": "x"}], SceneMeta, max_repairs=2)
        assert out.scene_id == "s2"
        assert len(fake.requests) == 2


def test_structured_envelope_fallback(tmp_path: Path) -> None:
    text = (FIXTURES / "envelope_valid.txt").read_text(encoding="utf-8")
    # tante risposte uguali: i livelli json_object falliscono, il livello envelope va
    with FakeOpenAI([(200, chat_response(text))] * 6) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        caps = Capabilities(vision=False, json_schema=False, source="test")
        out = chat_structured(c, [{"role": "user", "content": "scena"}], SceneMeta, caps=caps)
        assert out.scene_id == "s1"
        # l'ultimo livello (envelope) non manda response_format
        assert "response_format" not in fake.requests[-1]


def _fast_time(monkeypatch) -> None:
    """Backoff istantaneo SOLO nel modulo client (non nel server finto)."""
    import time as _time
    import types

    import demogen.llm.client as cl

    monkeypatch.setattr(
        cl, "time", types.SimpleNamespace(monotonic=_time.monotonic, sleep=lambda s: None)
    )


def test_retry_su_429(tmp_path: Path, monkeypatch) -> None:
    err = {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    with FakeOpenAI([(429, err), (429, err), (200, chat_response("ok"))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=3)
        _fast_time(monkeypatch)
        r = c.chat([{"role": "user", "content": "hi"}], step="t")
        assert r.content == "ok"
        assert len(fake.requests) == 3


def test_timeout_dopo_retry(tmp_path: Path, monkeypatch) -> None:
    from openai import APITimeoutError

    slow = (200, chat_response("lento"), 2.0)
    with FakeOpenAI([slow, slow]) as fake:
        cfg = make_config(fake.url, timeout_s=0.2)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=1)
        _fast_time(monkeypatch)
        with pytest.raises(APITimeoutError):
            c.chat([{"role": "user", "content": "hi"}], step="t")
        assert len(fake.requests) == 2  # 1 + 1 retry


def test_budget_blocca_prima_della_chiamata(tmp_path: Path) -> None:
    with FakeOpenAI() as fake:
        cfg = make_config(fake.url)
        budget = Budget(max_total_cost_usd=0.0001, max_wall_minutes=60, pricing=cfg.pricing)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=budget, max_retries=0)
        with pytest.raises(BudgetExceeded):
            c.chat([{"role": "user", "content": "hi"}], step="t")
        assert len(fake.requests) == 0  # nessuna chiamata reale


def test_capabilities_openrouter_con_cache(tmp_path: Path) -> None:
    models = {
        "data": [
            {
                "id": "org/fake-1",
                "input_modalities": ["text", "image"],
                "supported_parameters": ["response_format", "temperature"],
            }
        ]
    }
    with FakeOpenAI(models_payload=models) as fake:
        cfg = Config(
            providers={
                "or": ProviderConfig(type="openrouter", base_url=fake.url, api_key_env="K")
            },
            roles={"critic": RoleConfig(provider="or", model="org/fake-1")},
            cache_dir=str(tmp_path / "cache"),
        )
        os.environ["K"] = "sk-testsecret"
        try:
            caps = detect_capabilities(cfg, "critic")
            assert caps.vision is True and caps.json_schema is True
            caps2 = detect_capabilities(cfg, "critic")  # seconda: usa la cache
            assert caps2.source == "cache"
        finally:
            del os.environ["K"]


def test_redact() -> None:
    assert "sk-1234567890abcdef" not in redact("chiave sk-1234567890abcdef qui")
    assert "***" in redact("Authorization: Bearer abc.def.ghi")
    assert redact("testo normale") == "testo normale"


def test_init_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "demogen.yaml"
    res = runner.invoke(app, ["init", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert out.exists()
    assert "providers:" in out.read_text(encoding="utf-8")


def test_init_cli_avvisa_se_il_path_non_e_ignorato(tmp_path: Path) -> None:
    res = CliRunner().invoke(app, ["init", "--out", str(tmp_path / "altro.yaml")])
    assert res.exit_code == 0, res.output
    assert "ATTENZIONE" in res.output


def test_client_openrouter_senza_chiave_errore_esplicito() -> None:
    cfg = Config(
        providers={"or": ProviderConfig(type="openrouter", api_key="<INSERISCI-OPENROUTER-API-KEY>")},
        roles={"critic": RoleConfig(provider="or", model="m")},
    )
    with pytest.raises(ValueError, match="chiave API mancante"):
        LLMClient(cfg, "critic")


def test_models_check_ruolo_senza_chiave_non_blocca_gli_altri(tmp_path: Path) -> None:
    with FakeOpenAI([(200, chat_response("OK"))]) as fake:
        cfg_path = tmp_path / "demogen.yaml"
        cfg_path.write_text(
            json.dumps(
                {
                    "providers": {
                        "or": {"type": "openrouter", "api_key_env": "DEMOGEN_TEST_NO_SUCH_KEY"},
                        "test": {"type": "openai_compatible", "base_url": fake.url},
                    },
                    "roles": {
                        "critic": {"provider": "or", "model": "m"},
                        "orchestrator": {
                            "provider": "test", "model": "fake-1", "vision": False, "json_schema": False,
                        },
                    },
                    "log_dir": str(tmp_path / "logs"),
                    "cache_dir": str(tmp_path / "cache"),
                }
            )
        )
        res = CliRunner().invoke(app, ["models", "check", "--config", str(cfg_path)])
        assert res.exit_code == 0, res.output
        assert "chiave API mancante" in res.output
        assert "orchestrator" in res.output and "ok" in res.output


def test_models_check_cli_con_fake(tmp_path: Path) -> None:
    with FakeOpenAI([(200, chat_response("OK"))]) as fake:
        cfg_path = tmp_path / "demogen.yaml"
        cfg_path.write_text(
            json.dumps(
                {
                    "providers": {
                        "test": {"type": "openai_compatible", "base_url": fake.url}
                    },
                    "roles": {
                        "orchestrator": {
                            "provider": "test",
                            "model": "fake-1",
                            "vision": False,
                            "json_schema": False,
                        }
                    },
                    "log_dir": str(tmp_path / "logs"),
                    "cache_dir": str(tmp_path / "cache"),
                }
            )
        )
        runner = CliRunner()
        res = runner.invoke(app, ["models", "check", "--config", str(cfg_path)])
        assert res.exit_code == 0, res.output
        assert "orchestrator" in res.output and "ok" in res.output
