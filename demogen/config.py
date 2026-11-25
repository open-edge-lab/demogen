"""Configurazione demogen: YAML + env, validazione pydantic v2.

Chiavi API: `api_key` direttamente nel file (solo la config locale `demogen.yaml`,
gitignored) oppure `api_key_env` (nome di variabile d'ambiente). Il template
committabile e' `demogen/demo.yaml` (unica copia): se `demogen.yaml` manca,
all'avvio viene creata da quel template chiedendo la chiave (vedi `ensure_config`),
oppure con `demogen init`.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("demogen.yaml")
ENV_CONFIG = "DEMOGEN_CONFIG"
DEMO_TEMPLATE = Path(__file__).resolve().parent / "demo.yaml"
# .gitignore esclude i file con questo nome: solo loro possono contenere api_key in chiaro
IGNORED_CONFIG_NAME = DEFAULT_CONFIG_PATH.name

_PLACEHOLDER = re.compile(r"^\s*(<.*>)?\s*$")  # "", spazi, "<INSERISCI-...>"


class ProviderConfig(BaseModel):
    type: Literal["openai_compatible", "openrouter"]
    base_url: str | None = None
    api_key_env: str | None = None
    # chiave diretta: usarla solo in demogen.yaml (gitignored). SecretStr: mai in repr/traceback/log
    api_key: SecretStr | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("api_key", mode="before")
    @classmethod
    def _placeholder_is_none(cls, v: object) -> object:
        """Placeholder del template o stringa vuota = chiave assente (si ricade su api_key_env)."""
        if isinstance(v, str) and _PLACEHOLDER.match(v):
            return None
        return v


class RoleConfig(BaseModel):
    provider: str | None = None  # required dopo resolve_role (puo' venire da inherit)
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    vision: bool | Literal["auto"] = "auto"
    json_schema: bool | Literal["auto"] = "auto"
    timeout_s: float = 600.0
    extra_body: dict = Field(default_factory=dict)
    inherit: str | None = None  # eredita i campi mancanti da un altro ruolo


class BudgetConfig(BaseModel):
    max_iterations_per_scene: int = 4
    max_fix_attempts: int = 3
    max_total_cost_usd: float = 5.0
    max_wall_minutes: float = 60.0
    llm_concurrency: int = 4


class RealtimeConfig(BaseModel):
    target_fps: int = 60
    floor_ratio: float = 0.4  # p95 a qualità minima ≤ floor_ratio × budget p95
    max_compile_ms_scene: float = 400.0
    max_compile_ms_total: float = 1500.0
    max_first_frame_ms: float = 1500.0
    profile_step_s: float = 0.25
    # budget ms per profilo: {p95, mean, resolution}
    profiles: dict[str, dict] = Field(
        default_factory=lambda: {
            "modern": {"p95": 6.0, "mean": 4.0, "res": [1920, 1080]},
            "retro": {"p95": 1.0, "mean": 0.5, "res": [320, 180]},
        }
    )


class AudioConfig(BaseModel):
    prebuffer_s: float = 8.0
    max_render_ms_prebuffer: float = 4000.0
    max_onset_err_ms: float = 5.0  # onset vs griglia beat (dominio dei dati)


class SafetyConfig(BaseModel):
    flash_max_per_s: int = 3
    red_flash: bool = True
    # campionamento del flash: >= 30 fps su tutta la durata (8 fps andava in aliasing con strobo a 8 Hz)
    flash_fps: int = 30
    # area WCAG: 25% di un campo visivo di 10° ≈ 341×256 px su 1024×768 ≈ 2.8% dello schermo
    flash_area_frac: float = 0.028
    flash_grid: int = 16  # griglia g×g di celle (16 → 256 celle, ~0.4% dello schermo ciascuna)


class BundleLimits(BaseModel):
    max_payload_gz_kb: int = 48
    max_payload_bytes: int = 1024 * 1024
    max_scene_bytes: int = 256 * 1024


class PreviewConfig(BaseModel):
    width: int = 480
    height: int = 270
    keyframes: int = 16
    bursts: int = 3
    burst_len: int = 6
    fps: int = 60


class Config(BaseModel):
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    realtime: RealtimeConfig = Field(default_factory=RealtimeConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    bundle: BundleLimits = Field(default_factory=BundleLimits)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
    log_dir: str = ".demogen_logs/llm_calls"
    cache_dir: str = ".demogen_cache"

    @model_validator(mode="after")
    def _roles_resolvable(self) -> Config:
        """Ogni ruolo deve risolversi (inherit senza cicli) in provider esistente + model."""
        for name in self.roles:
            r = resolve_role(self, name)
            if r.provider not in self.providers:
                raise ValueError(f"Ruolo '{name}': provider '{r.provider}' non definito in providers")
        return self


def is_git_ignored_name(path: Path) -> bool:
    """True se il nome del file e' quello escluso da .gitignore (unico posto sicuro per api_key)."""
    return Path(path).name == IGNORED_CONFIG_NAME


def warn_if_not_ignored(path: Path) -> None:
    if is_git_ignored_name(path):
        print(f"Scritto {path} — e' in .gitignore, non verra' mai committata.")
    else:
        print(
            f"Scritto {path}. ATTENZIONE: solo i file '{IGNORED_CONFIG_NAME}' sono in .gitignore; "
            f"se metti la chiave in `api_key` qui, non committare {path.name} (oppure usa api_key_env)."
        )


def ensure_config(path: Path, *, interactive: bool | None = None, template: Path | None = None) -> Path:
    """Se `path` manca, prova a crearla dal template demo chiedendo la chiave.

    In modalita' non interattiva (niente TTY) solleva FileNotFoundError con le
    istruzioni. Ritorna il path esistente o appena creato.
    """
    path = Path(path)
    if path.exists():
        return path
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    demo = Path(template) if template is not None else DEMO_TEMPLATE
    if not interactive or not demo.exists():
        raise FileNotFoundError(
            f"Config non trovata: {path}. Creala con `demogen init` (template {DEMO_TEMPLATE.name}), "
            "poi inserisci la chiave OpenRouter in `api_key` (o usa `api_key_env`)."
        )
    print(f"Config non trovata: {path}")
    ans = input(f"Creo {path.name} dal template {demo.name}? [S/n] ").strip().lower()
    if ans in ("n", "no"):
        raise FileNotFoundError(f"Config non trovata: {path} (creazione annullata)")
    text = demo.read_text(encoding="utf-8")
    key = getpass.getpass("Chiave API OpenRouter (invio = lascia il placeholder): ").strip()
    if key:
        # json.dumps = scalare YAML double-quoted con escape di " e \ (YAML e' superset di JSON)
        text, n = re.subn(r"(?m)^(\s*api_key:).*$", lambda m: f"{m.group(1)} {json.dumps(key)}", text, count=1)
        if n == 0:
            print("Il template non ha una riga `api_key:`: inseriscila a mano sotto providers.openrouter.")
    path.write_text(text, encoding="utf-8")
    warn_if_not_ignored(path)
    print("Configura i modelli in roles/*/model, poi: demogen models check")
    return path


def load_config(path: Path | str | None = None, *, interactive: bool | None = None) -> Config:
    """Carica la config da path, oppure $DEMOGEN_CONFIG, oppure ./demogen.yaml.

    Se il file manca e la sessione e' interattiva, lo crea dal template
    chiedendo la chiave OpenRouter (vedi ensure_config).
    """
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG_PATH
    path = ensure_config(Path(path), interactive=interactive)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config.model_validate(data)


def resolve_role(cfg: Config, role: str, _chain: tuple[str, ...] = ()) -> RoleConfig:
    """Risolve `inherit`: i campi impostati esplicitamente nel ruolo vincono su quelli ereditati.

    I default pydantic del figlio NON sovrascrivono i valori del padre (model_dump exclude_unset).
    """
    if role in _chain:
        raise ValueError(f"inherit ciclico tra ruoli: {' -> '.join((*_chain, role))}")
    if role not in cfg.roles:
        where = f" (inherit da '{_chain[-1]}')" if _chain else ""
        raise ValueError(f"Ruolo '{role}' non configurato{where}")
    r = cfg.roles[role]
    if r.inherit is not None:
        base = resolve_role(cfg, r.inherit, (*_chain, role))
        explicit = r.model_dump(exclude_unset=True, exclude={"inherit"})
        r = RoleConfig.model_validate({**base.model_dump(exclude={"inherit"}), **explicit})
    if not r.provider or not r.model:
        raise ValueError(f"Ruolo '{role}': provider/model mancanti (anche dopo inherit)")
    return r
