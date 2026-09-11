"""A standalone HTTP surface over a `MockRegistry`.

The API serves these endpoints through FastAPI, because n8n calls back into the same process
that opened the run. Everywhere *else* that runs a workflow needs the same thing and has no
FastAPI app to hang it on - the CLI in CI, and the integration tests.

The registry and the server must share one object. A separately running API would hold a
different registry, so every mocked response would 404 and every injected failure would
silently fail to fire, leaving a run that looks measured and is not.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from workflow_core.execution.mocks import MockRegistry

__all__ = ["serve_mocks"]


@contextmanager
def serve_mocks(registry: MockRegistry | None = None) -> Iterator[tuple[MockRegistry, str]]:
    """Serve ``registry`` for the duration of the block.

    Yields the registry and the base URL to hand the emitter. Binds to port 0 so a developer's
    own API on 8000 is never mistaken for this one, and on the loopback interface because
    nothing outside this machine has any business reaching a test's mocks.
    """
    registry = registry or MockRegistry()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(registry))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield registry, f"http://127.0.0.1:{server.server_address[1]}/mock"
    finally:
        server.shutdown()
        server.server_close()


def _handler_for(registry: MockRegistry) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            parts = [p for p in self.path.split("?")[0].strip("/").split("/") if p]
            if len(parts) < 3 or parts[0] != "mock":
                return self._send(404, {"error": "not a mock endpoint"})

            run_token, node_id = parts[1], parts[2]
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length).decode() if length else ""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw

            response = registry.respond(
                run_token, node_id, {"method": self.command, "query": {}, "body": body}
            )
            if response is None:
                # The run is closed or never existed. Answering anyway would let a leaked
                # workflow keep producing plausible results after its run finished.
                return self._send(404, {"error": f"no open test run {run_token!r}"})

            if response.delay_seconds:
                # Genuinely wait: a timeout injection only exercises timeout handling if the
                # caller actually has to wait for it.
                threading.Event().wait(response.delay_seconds)

            if response.raw_text is not None:
                return self._send_raw(response.status_code, response.raw_text.encode())
            return self._send(response.status_code, response.body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        def _send(self, status: int, body: object) -> None:
            self._send_raw(status, json.dumps(body).encode())

        def _send_raw(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            # Two calls to the same node must stay distinguishable; that is how retries are
            # counted, and a cache between n8n and here would collapse them.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            """Silent: one line per mocked call would drown a fuzz campaign's output."""

    return Handler
