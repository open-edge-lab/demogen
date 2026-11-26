"""Test config YAML: api_key nel file (demogen.yaml, gitignored), bootstrap dal template, inherit dei ruoli."""

from __future__ import annotations

import builtins
import getpass
from pathlib import Path

import pytest

from demogen.config import (
    DEMO_TEMPLATE,
    Config,
    ProviderConfig,
    RoleConfig,
    ensure_config,
    load_config,
    resolve_role,
)
from demogen.llm.providers import api_key_for


def _demo_text() -> str:
    return DEMO_TEMPLATE.read_text(encoding="utf-8")


def _interactive(monkeypatch: pytest.MonkeyPatch, answer: str = "s", key: str = "") -> None:
    monkeypatch.setattr(builtins, "input", lambda _prompt: answer)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: key)


# ------------------------------------------------------------------ api_key


def test_api_key_file_wins_over_env() -> None:
    p = ProviderConfig(type="openrouter", api_key="sk-from-file", api_key_env="K")
    assert api_key_for(p, env={"K": "sk-from-env"}) == "sk-from-file"


def test_api_key_env_fallback() -> None:
    p = ProviderConfig(type="openrouter", api_key_env="K")
    assert api_key_for(p, env={"K": "sk-from-env"}) == "sk-from-env"
    assert api_key_for(p, env={}) is None


@pytest.mark.parametrize("placeholder", ["<INSERISCI-OPENROUTER-API-KEY>", "", "   "])
def test_placeholder_api_key_cade_su_env(placeholder: str) -> None:
    p = ProviderConfig(type="openrouter", api_key=placeholder, api_key_env="K")
    assert api_key_for(p, env={"K": "sk-from-env"}) == "sk-from-env"


def test_api_key_non_compare_nel_repr() -> None:
    """Typer/rich stampano i locals nei traceback: la chiave non deve comparire nel repr."""
    cfg = Config(
        providers={"or": ProviderConfig(type="openrouter", api_key="sk-or-v1-segretissima")},
        roles={"orchestrator": RoleConfig(provider="or", model="m")},
    )
    assert "segretissima" not in repr(cfg)
    assert "segretissima" not in str(cfg.model_dump())


def test_typer_non_mostra_locals_nei_traceback() -> None:
    from demogen.cli import app

    assert app.pretty_exceptions_show_locals is False


def test_load_config_reads_api_key_from_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "demogen.yaml"
    cfg_path.write_text(
        _demo_text().replace('api_key: "<INSERISCI-OPENROUTER-API-KEY>"', 'api_key: "sk-test-123"'),
        encoding="utf-8",
    )
    cfg = load_config(cfg_path, interactive=False)
    assert api_key_for(cfg.providers["openrouter"], env={}) == "sk-test-123"


# ------------------------------------------------------------------ inherit


def _cfg(roles: dict) -> Config:
    return Config.model_validate(
        {"providers": {"p": {"type": "openai_compatible", "base_url": "http://x"}}, "roles": roles}
    )


def test_inherit_eredita_campi_e_override_espliciti() -> None:
    cfg = _cfg(
        {
            "base": {"provider": "p", "model": "m1", "temperature": 0.2, "max_tokens": 16000, "vision": True},
            "child": {"inherit": "base", "temperature": 0.9},
        }
    )
    r = resolve_role(cfg, "child")
    assert (r.provider, r.model) == ("p", "m1")
    assert r.temperature == 0.9  # esplicito vince
    assert r.max_tokens == 16000  # ereditato, NON il default 4096
    assert r.vision is True  # ereditato, NON il default "auto"


def test_inherit_ciclico_errore() -> None:
    with pytest.raises(ValueError, match="cyclic"):
        _cfg({"a": {"inherit": "b"}, "b": {"inherit": "a"}})


def test_ruolo_senza_provider_rifiutato_al_load() -> None:
    with pytest.raises(ValueError, match="provider"):
        _cfg({"orchestrator": {"model": "m"}})


def test_ruolo_con_provider_inesistente_rifiutato_al_load() -> None:
    with pytest.raises(ValueError, match="nope"):
        _cfg({"orchestrator": {"provider": "nope", "model": "m"}})


def test_template_demo_risolve_tutti_i_ruoli(tmp_path: Path) -> None:
    cfg_path = tmp_path / "demogen.yaml"
    cfg_path.write_text(_demo_text(), encoding="utf-8")
    cfg = load_config(cfg_path, interactive=False)
    for role in cfg.roles:
        r = resolve_role(cfg, role)
        assert r.provider in cfg.providers
    comp, orch = resolve_role(cfg, "composer"), resolve_role(cfg, "orchestrator")
    assert (comp.model, comp.max_tokens, comp.timeout_s) == (orch.model, orch.max_tokens, orch.timeout_s)


# ------------------------------------------------------------------ ensure_config


def test_ensure_config_non_interactive_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="demogen init"):
        ensure_config(tmp_path / "demogen.yaml", interactive=False)
    assert not (tmp_path / "demogen.yaml").exists()


def test_ensure_config_interactive_creates_from_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interactive(monkeypatch, key="sk-live-999")
    out = ensure_config(tmp_path / "demogen.yaml", interactive=True)
    text = out.read_text(encoding="utf-8")
    assert "<INSERISCI-OPENROUTER-API-KEY>" not in text
    cfg = load_config(out, interactive=False)
    assert api_key_for(cfg.providers["openrouter"], env={}) == "sk-live-999"


def test_ensure_config_chiave_con_caratteri_speciali_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = 'sk-a"b\\c#d'
    _interactive(monkeypatch, key=key)
    out = ensure_config(tmp_path / "demogen.yaml", interactive=True)
    cfg = load_config(out, interactive=False)
    assert api_key_for(cfg.providers["openrouter"], env={}) == key


def test_ensure_config_template_senza_api_key_non_scrive_la_chiave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    tpl = tmp_path / "tpl.yaml"
    tpl.write_text(_demo_text().replace('api_key: "<INSERISCI-OPENROUTER-API-KEY>"', ""), encoding="utf-8")
    _interactive(monkeypatch, key="sk-mai-nei-commenti")
    out = ensure_config(tmp_path / "demogen.yaml", interactive=True, template=tpl)
    assert "sk-mai-nei-commenti" not in out.read_text(encoding="utf-8")
    assert "api_key" in capsys.readouterr().out  # avvisa di inserirla a mano


def test_ensure_config_avvisa_se_il_path_non_e_ignorato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _interactive(monkeypatch, key="sk-x")
    ensure_config(tmp_path / "mia-config.yaml", interactive=True)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "will never be committed" not in out


def test_ensure_config_declined_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _interactive(monkeypatch, answer="n")
    with pytest.raises(FileNotFoundError, match="cancelled"):
        ensure_config(tmp_path / "demogen.yaml", interactive=True)
    assert not (tmp_path / "demogen.yaml").exists()


def test_demo_template_is_committable_safe() -> None:
    """Il template demo non deve contenere chiavi reali."""
    text = _demo_text()
    assert "<INSERISCI-OPENROUTER-API-KEY>" in text
    assert "sk-" not in text
