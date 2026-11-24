"""Server finto OpenAI-compatible per i test (in-process, 127.0.0.1)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def chat_response(content: str, model: str = "fake-1", prompt_tokens: int = 10,
                  completion_tokens: int = 20, cost: float | None = None) -> dict:
    usage: dict = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "model": model,
        "usage": usage,
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/v1/models"):
            self._send(200, self.server.fake.models_payload or {"data": []})  # type: ignore[attr-defined]
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        self.server.fake.requests.append(body)  # type: ignore[attr-defined]
        if self.path.startswith("/v1/chat/completions"):
            queue = self.server.fake.responses  # type: ignore[attr-defined]
            if queue:
                item = queue.pop(0)
                status, payload = item[0], item[1]
                delay = item[2] if len(item) > 2 else 0.0
                if delay:
                    time.sleep(delay)
                if isinstance(payload, dict) and "choices" not in payload:
                    payload = chat_response(**payload) if "content" in payload else payload
                self._send(status, payload)
            else:
                self._send(200, chat_response("OK"))
        else:
            self._send(404, {"error": "not found"})


class FakeOpenAI:
    def __init__(self, responses: list | None = None, models_payload: dict | None = None):
        self.responses = list(responses or [])
        self.requests: list[dict] = []
        self.models_payload = models_payload or {"data": []}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.fake = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self) -> FakeOpenAI:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
