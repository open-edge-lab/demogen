from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D102
        pass


def start_local_server(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    """Server HTTP locale su 127.0.0.1 (porta casuale) che serve `directory`."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]
