"""Fixture condivise.

Regola: solo l'AVVIO del browser può trasformarsi in skip (e mai in CI, dove diventa
un fallimento). Gli assert dei test stanno sempre fuori da qualsiasi try/except.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_JS = ROOT / "player" / "dist" / "demogen-harness.js"


def in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def skip_or_fail(reason: str) -> NoReturn:
    """Skip in locale; in CI (CI=true) un browser mancante è un errore, non uno skip."""
    if in_ci():
        pytest.fail(f"[CI] {reason}", pytrace=False)
    pytest.skip(reason)


def require_browser() -> None:
    """Verifica che build del player e Chromium siano disponibili (skip/fail altrimenti)."""
    if not HARNESS_JS.exists():
        skip_or_fail("build del player mancante (npm run build)")
    try:
        from demogen.browser.harness import Harness

        with Harness(gpu="swiftshader"):
            pass
    except Exception as e:  # noqa: BLE001 - solo l'avvio del browser
        skip_or_fail(f"browser Playwright non disponibile: {e}")


@pytest.fixture
def harness() -> Iterator[object]:
    """Harness SwiftShader avviato e chiuso per test; skip/fail SOLO sull'avvio."""
    if not HARNESS_JS.exists():
        skip_or_fail("build del player mancante (npm run build)")
    from demogen.browser.harness import Harness

    h = Harness(gpu="swiftshader")
    try:
        h.__enter__()
    except Exception as e:  # noqa: BLE001 - solo l'avvio del browser
        skip_or_fail(f"browser Playwright non disponibile: {e}")
    try:
        yield h
    finally:
        h.__exit__(None, None, None)
