"""Layout della cartella progetto e state.json (resume idempotente)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

# nomi di dispositivo riservati su Windows (anche con estensione: con.html apre la console)
_WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


def slugify(text: str, max_len: int = 40) -> str:
    """Slug sicuro come nome file: solo [a-z0-9-], mai vuoto, mai un nome riservato di Windows."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    s = s[:max_len].strip("-") or "demo"
    if s in _WIN_RESERVED:
        s = f"demo-{s}"
    return s


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

    def resolve(self, rel: str) -> Path:
        """Path dentro il progetto; ValueError se `rel` esce dalla root (`..`, assoluto)."""
        root = self.path.resolve()
        p = (root / rel).resolve()
        if not p.is_relative_to(root):
            raise ValueError(f"path fuori dal progetto: {rel!r}")
        return p

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    def write(self, rel: str, content: str | bytes) -> Path:
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return p

    def read(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    def read_json(self, rel: str):
        return json.loads(self.read(rel))
