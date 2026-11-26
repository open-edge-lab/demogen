"""Gate dimensione: player core ≤ 12 KB min+gzip (CI)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[1] / "player" / "dist" / "demogen-player.min.js"
BUDGET = 12 * 1024


@pytest.mark.skipif(not DIST.exists(), reason="dist missing: run npm run build first")
def test_player_core_gzip_budget() -> None:
    gz = len(gzip.compress(DIST.read_bytes(), 9))
    assert gz <= BUDGET, f"player core {gz} B gzip > budget {BUDGET} B"
