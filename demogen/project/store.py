"""Layout della cartella progetto e state.json (resume idempotente)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "demo"


def new_project_dir(prompt: str, root: Path = Path("projects")) -> Path:
    name = f"{date.today().isoformat()}_{slugify(prompt)}"
    path = root / name
    n = 1
    while path.exists():
        n += 1
        path = root / f"{name}-{n}"
    return path


class Project:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        for sub in ("scenes", "llm_calls", "out"):
            (self.path / sub).mkdir(parents=True, exist_ok=True)

    @property
    def state_path(self) -> Path:
        return self.path / "state.json"

    def load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"done": [], "step": "S0"}

    def save_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")

    def write(self, rel: str, content: str | bytes) -> Path:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return p

    def read(self, rel: str) -> str:
        return (self.path / rel).read_text(encoding="utf-8")

    def read_json(self, rel: str):
        return json.loads(self.read(rel))
