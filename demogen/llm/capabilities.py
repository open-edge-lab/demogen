"""Rilevamento capacità dei modelli (vision / json_schema).

- openrouter: interroga GET /api/v1/models e legge il record del modello;
  cache su disco per 24 h. [VERIFICARE] i nomi esatti dei campi: euristica
  robusta su input_modalities / supported_parameters.
- openai_compatible generico: non rilevabile in modo affidabile → default
  prudente (vision false, json_schema false) a meno che il ruolo non imponga true.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import Config, resolve_role
from .providers import api_key_for, base_url_for

CACHE_TTL_S = 24 * 3600
CACHE_VERSION = 2  # v2: json_schema = structured_outputs (v1 usava response_format)


@dataclass
class Capabilities:
    vision: bool
    json_schema: bool
    source: str  # "openrouter" | "config" | "default-prudente" | "cache"


def _cache_path(cache_dir: Path, base_url: str, model: str) -> Path:
    h = hashlib.sha1(f"{base_url}|{model}".encode()).hexdigest()[:16]
    return cache_dir / f"models_{h}.json"


def _from_openrouter_catalog(cfg: Config, role: str) -> Capabilities | None:
    r = resolve_role(cfg, role)
    prov = cfg.providers[r.provider]
    if prov.type != "openrouter":
        return None
    base = base_url_for(prov)
    key = api_key_for(prov)
    headers = dict(prov.headers)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(timeout=30) as http:
        resp = http.get(f"{base}/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    for m in data.get("data", []):
        if m.get("id") == r.model or m.get("id", "").endswith("/" + r.model):
            modalities = m.get("input_modalities") or m.get("supported_input_modalities") or []
            arch = m.get("architecture") or {}
            modalities = list(modalities) + list(arch.get("input_modalities") or [])
            params = [str(p).lower() for p in (m.get("supported_parameters") or [])]
            vision = "image" in [str(x).lower() for x in modalities]
            # "response_format" = solo json_object; lo schema strict è "structured_outputs"
            json_schema = "structured_outputs" in params
            return Capabilities(vision=vision, json_schema=json_schema, source="openrouter")
    return Capabilities(
        vision=False, json_schema=False, source="openrouter (modello non in catalogo)"
    )


def detect_capabilities(cfg: Config, role: str, cache_dir: Path | None = None) -> Capabilities:
    """Risolve ogni campo `auto` → bool (i bool espliciti della config vincono, campo per campo).

    Il rilevamento (cache 24 h → catalogo OpenRouter → default prudente) si fa solo se
    almeno un campo è `auto`.
    """
    r = resolve_role(cfg, role)
    if isinstance(r.vision, bool) and isinstance(r.json_schema, bool):
        return Capabilities(vision=r.vision, json_schema=r.json_schema, source="config")
    det = _detect_auto(cfg, role, cache_dir)
    return Capabilities(
        vision=r.vision if isinstance(r.vision, bool) else det.vision,
        json_schema=r.json_schema if isinstance(r.json_schema, bool) else det.json_schema,
        source=det.source if not isinstance(r.vision, bool) and not isinstance(r.json_schema, bool)
        else f"config+{det.source}",
    )


def _detect_auto(cfg: Config, role: str, cache_dir: Path | None) -> Capabilities:
    r = resolve_role(cfg, role)
    cache_dir = cache_dir or Path(cfg.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    prov = cfg.providers[r.provider]
    cpath = _cache_path(cache_dir, base_url_for(prov), r.model)
    if cpath.exists():
        cached = json.loads(cpath.read_text(encoding="utf-8"))
        if cached.get("v") == CACHE_VERSION and time.time() - cached.get("ts", 0) < CACHE_TTL_S:
            caps = cached["caps"]
            return Capabilities(
                vision=caps["vision"], json_schema=caps["json_schema"], source="cache"
            )
    try:
        caps = _from_openrouter_catalog(cfg, role)
    except (httpx.HTTPError, ValueError) as e:
        # catalogo irraggiungibile o malformato: default prudente, NON in cache (si riprova)
        return Capabilities(vision=False, json_schema=False, source=f"default-prudente ({type(e).__name__})")
    if caps is None:
        # openai_compatible generico: default prudente
        caps = Capabilities(vision=False, json_schema=False, source="default-prudente")
    cpath.write_text(json.dumps({"v": CACHE_VERSION, "ts": time.time(), "caps": caps.__dict__}), encoding="utf-8")
    return caps
