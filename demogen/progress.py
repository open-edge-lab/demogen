"""Eventi di avanzamento della pipeline (pubblica / iscriviti).

Chi lavora (pipeline, step, client LLM, budget) chiama `emit()`; chi mostra (il pannello
della CLI, `demogen.dashboard`) si iscrive con `subscribe()`. Senza iscritti `emit()` non
fa nulla, quindi test e uso come libreria non cambiano. Un listener che solleva non
interrompe mai la pipeline.

Eventi (nome → campi principali):
- `pipeline.start`  project, prompt, gpu, fake, cap, spent, max_iter, models
- `step`            step (S0 S1 S2 SC S9), state (run done skip), detail
- `spec`            title, duration, bpm, profile, scenes [{id, title}]
- `scene`           scene, phase (draft math drafted compile fix probe critic revise), version, detail
- `scene.result`    scene, version, score, verdict, blockers
- `scene.done`      scene, best, score
- `math`            scene, version, accepted, rejected
- `llm.start`       id, role, model, step
- `llm.end`         id, role, model, step, ok, error, cost, prompt_tokens, completion_tokens, latency
- `budget`          spent, cap
- `stop`            reason (stop anticipato, es. budget)
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

Listener = Callable[[str, dict[str, Any]], None]

_listeners: list[Listener] = []
_lock = threading.Lock()
_call_ids = itertools.count(1)


def subscribe(fn: Listener) -> Callable[[], None]:
    """Iscrive `fn(evento, dati)`; ritorna la funzione che la disiscrive."""
    with _lock:
        _listeners.append(fn)

    def unsubscribe() -> None:
        with _lock:
            if fn in _listeners:
                _listeners.remove(fn)

    return unsubscribe


def emit(event: str, **data: Any) -> None:
    with _lock:
        targets = list(_listeners)
    for fn in targets:
        try:
            fn(event, data)
        except Exception:  # noqa: BLE001 - la UI non deve mai fermare la pipeline
            pass


@contextmanager
def llm_call(role: str, model: str, step: str) -> Iterator[dict[str, Any]]:
    """Avvolge una chiamata LLM: `llm.start` subito, `llm.end` alla fine con esito e i dati
    che il chiamante mette nel dict ceduto (costo, token, latenza)."""
    info = {"id": next(_call_ids), "role": role, "model": model, "step": step}
    emit("llm.start", **info)
    out: dict[str, Any] = {}
    try:
        yield out
    except BaseException as e:
        if getattr(e, "demogen_call", None) is None:  # la chiamata più interna che è fallita
            try:
                e.demogen_call = dict(info)  # type: ignore[attr-defined]
            except AttributeError:
                pass
        from .llm.errors import provider_message  # import tardivo: llm.client importa questo modulo

        emit("llm.end", **info, **out, ok=False, error=type(e).__name__,
             status=getattr(e, "status_code", None), detail=provider_message(e)[:300])
        raise
    emit("llm.end", **info, **out, ok=True)
