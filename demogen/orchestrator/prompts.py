"""Render dei template Jinja2 dei prompt + riferimento API della libreria (cache)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..glsl.docs import generate_api_reference

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
LIB_DIR = Path(__file__).resolve().parents[1] / "glsl" / "lib"

_ENV = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(name: str, **kw) -> str:
    return _ENV.get_template(name).render(**kw)


@lru_cache(maxsize=1)
def api_ref() -> str:
    return generate_api_reference(LIB_DIR)


def system_prompt(bpm: float) -> str:
    return render("system_contract.md.j2", bpm=bpm, api_ref=api_ref(), scene_id="-")
