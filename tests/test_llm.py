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


def test_structured_json_con_fence_accettato_al_livello_json_object(tmp_path: Path) -> None:
    text = (FIXTURES / "envelope_valid.txt").read_text(encoding="utf-8")
    # json_object che risponde con un envelope (```json ... ``` + glsl): il parsing tollerante lo accetta
    with FakeOpenAI([(200, chat_response(text))] * 6) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        caps = Capabilities(vision=False, json_schema=False, source="test")
        out = chat_structured(c, [{"role": "user", "content": "scena"}], SceneMeta, caps=caps)
        assert out.scene_id == "s1"
        assert len(fake.requests) == 1
        assert fake.requests[0]["response_format"] == {"type": "json_object"}


def test_structured_4xx_passa_al_livello_successivo(tmp_path: Path) -> None:
    bad = {"error": {"message": "response_format json_schema not supported", "type": "invalid_request_error"}}
    with FakeOpenAI([(400, bad), (400, bad), (200, chat_response('{"scene_id": "s3"}'))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        caps = Capabilities(vision=False, json_schema=True, source="test")
        out = chat_structured(c, [{"role": "user", "content": "x"}], SceneMeta, caps=caps)
        assert out.scene_id == "s3"
        kinds = [r.get("response_format", {}).get("type") for r in fake.requests]
        assert kinds == ["json_schema", "json_object", None]  # un tentativo per livello, poi envelope


def test_structured_401_non_viene_mascherato(tmp_path: Path) -> None:
    from openai import AuthenticationError

    err = {"error": {"message": "bad key", "type": "auth"}}
    with FakeOpenAI([(401, err)] * 3) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=0)
        caps = Capabilities(vision=False, json_schema=True, source="test")
        with pytest.raises(AuthenticationError):
            chat_structured(c, [{"role": "user", "content": "x"}], SceneMeta, caps=caps)
        assert len(fake.requests) == 1


def test_strict_schema_compatibile() -> None:
    from demogen.critic.models import CriticReport
    from demogen.llm.structured import strict_schema
    from demogen.spec.models import DemoSpec

    s = strict_schema(DemoSpec)
    assert s is not None
    assert "title" in s["properties"]  # il campo `title` non va confuso con la chiave di metadati

    def objects(node):
        if isinstance(node, dict):
            if "properties" in node:
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    for obj in objects(s):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert "default" not in json.dumps(s)
    # dict libero (scores) non esprimibile in strict
    assert strict_schema(CriticReport) is None


def test_loads_tolerant() -> None:
    from demogen.llm.structured import loads_tolerant

    assert loads_tolerant('{"a": 1}') == {"a": 1}
    assert loads_tolerant('ecco:\n```json\n{"a": 2}\n```\nfine') == {"a": 2}
    assert loads_tolerant('prefisso {"a": 3} suffisso') == {"a": 3}
    with pytest.raises(ValueError):
        loads_tolerant("niente json qui")


def _fast_time(monkeypatch) -> None:
    """Backoff istantaneo SOLO nel modulo client (non nel server finto)."""
    import time as _time
    import types

    import demogen.llm.client as cl

    monkeypatch.setattr(
        cl, "time", types.SimpleNamespace(monotonic=_time.monotonic, sleep=lambda s: None)
    )
    monkeypatch.setattr(cl, "_backoff", lambda attempt: 0.0)


def test_achat_choices_none_viene_ritentato(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    # alcuni provider rispondono 200 con un errore nel body e senza choices
    with FakeOpenAI([(200, {"error": {"message": "upstream"}}), (200, chat_response("ok"))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=2)
        _fast_time(monkeypatch)
        r = asyncio.run(c.achat([{"role": "user", "content": "hi"}], step="t"))
        assert r.content == "ok" and r.finish_reason == "stop"
        assert len(fake.requests) == 2


def test_achat_non_blocca_l_event_loop(tmp_path: Path, monkeypatch) -> None:
    """Il backoff di achat è asyncio.sleep: un'altra coroutine avanza durante l'attesa."""
    import asyncio
    import time as _time

    import demogen.llm.client as cl

    monkeypatch.setattr(cl, "_backoff", lambda attempt: 0.5)
    err = {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    with FakeOpenAI([(429, err), (200, chat_response("ok"))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, max_retries=1)
        end: dict[str, float] = {}

        async def call():
            r = await c.achat([{"role": "user", "content": "hi"}], step="t")
            end["achat"] = _time.monotonic()
            return r

        async def ticker() -> None:
            for _ in range(5):
                await asyncio.sleep(0.03)
            end["ticker"] = _time.monotonic()

        async def main():
            return await asyncio.gather(call(), ticker())

        r, _ = asyncio.run(main())
        assert r.content == "ok"
        # con time.sleep il ticker resterebbe fermo per tutto il backoff e finirebbe dopo achat
        assert end["ticker"] < end["achat"]


def test_finish_reason_length_solleva_dopo_log_e_addebito(tmp_path: Path) -> None:
    from demogen.llm.client import LLMTruncated

    resp = chat_response("troncat")
    resp["choices"][0]["finish_reason"] = "length"
    with FakeOpenAI([(200, resp)]) as fake:
        cfg = make_config(fake.url)
        budget = Budget(100, 60, cfg.pricing)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=budget, max_retries=0)
        with pytest.raises(LLMTruncated) as ei:
            c.chat([{"role": "user", "content": "hi"}], step="t")
        assert ei.value.response.content == "troncat"
        assert budget.spent_usd > 0
        assert len(list(tmp_path.glob("*.json"))) == 1


def test_costo_con_id_del_modello_configurato(tmp_path: Path) -> None:
    # il server risponde con un id diverso (alias/versione): il prezzo è quello del modello configurato
    with FakeOpenAI([(200, chat_response("x", model="vendor/fake-1-2026-01"))]) as fake:
        cfg = make_config(fake.url)
        budget = Budget(100, 60, cfg.pricing)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path, budget=budget)
        r = c.chat([{"role": "user", "content": "hi"}], step="t")
        assert r.cost_usd == pytest.approx(10 / 1e6 * 1.0 + 20 / 1e6 * 2.0)
        assert budget.spent_usd == pytest.approx(r.cost_usd)


def test_log_non_sovrascritti_al_resume(tmp_path: Path) -> None:
    (tmp_path / "0007_orchestrator_vecchio.json").write_text("{}", encoding="utf-8")
    with FakeOpenAI([(200, chat_response("a")), (200, chat_response("b"))]) as fake:
        cfg = make_config(fake.url)
        c = LLMClient(cfg, "orchestrator", log_dir=tmp_path)
        c.chat([{"role": "user", "content": "hi"}], step="t")
        c2 = LLMClient(cfg, "orchestrator", log_dir=tmp_path)  # un altro client sulla stessa cartella
        c2.chat([{"role": "user", "content": "hi"}], step="t")
    names = sorted(p.name for p in tmp_path.glob("*.json"))
    assert names == ["0007_orchestrator_vecchio.json", "0008_orchestrator_t.json", "0009_orchestrator_t.json"]


def test_budget_riparte_dalla_spesa_salvata() -> None:
    cfg = Config(providers={}, roles={}, budget={"max_total_cost_usd": 1.0})
    b = Budget.from_config(cfg, spent_usd=0.75)
    assert b.spent_usd == 0.75
    b.add("m", 0, 0, 0.3)
    with pytest.raises(BudgetExceeded):
        b.check()


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
                "supported_parameters": ["response_format", "structured_outputs", "temperature"],
            },
            {
                # solo json_object: niente schema strict
                "id": "org/fake-2",
                "input_modalities": ["text"],
                "supported_parameters": ["response_format", "temperature"],
            },
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
            # campo per campo: vision imposta true in config, json_schema resta auto → rilevato
            cfg2 = cfg.model_copy(update={"roles": {
                "critic": RoleConfig(provider="or", model="org/fake-2", vision=True),
                "orch": RoleConfig(provider="or", model="org/fake-1", json_schema=False),
            }})
            c_mixed = detect_capabilities(cfg2, "critic")
            assert c_mixed.vision is True and c_mixed.json_schema is False  # solo response_format
            c_mixed2 = detect_capabilities(cfg2, "orch")
            assert c_mixed2.vision is True and c_mixed2.json_schema is False  # false esplicito vince
        finally:
            del os.environ["K"]


def test_capabilities_catalogo_irraggiungibile_default_prudente(tmp_path: Path) -> None:
    cfg = Config(
        providers={"or": ProviderConfig(type="openrouter", base_url="http://127.0.0.1:9/v1", api_key="sk-x123456789")},
        roles={"critic": RoleConfig(provider="or", model="m")},
        cache_dir=str(tmp_path / "cache"),
    )
    caps = detect_capabilities(cfg, "critic")
    assert caps.vision is False and caps.json_schema is False
    assert caps.source.startswith("default-prudente")


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
