"""Lock globale per le misure di prestazioni: una sola misura GPU alla volta."""

from __future__ import annotations

import threading
from contextlib import contextmanager

PERF_LOCK = threading.Lock()


@contextmanager
def perf_lane():
    """Serializza le misure perf (più carichi GPU contemporanei falsano i tempi)."""
    with PERF_LOCK:
        yield
