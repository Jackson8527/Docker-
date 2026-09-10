"""Regression test for the /ws/logs event-loop freeze.

The original implementation iterated docker-py's blocking
`logs(follow=True)` generator directly inside the async handler. On an idle
container `next()` blocks on the docker socket indefinitely, which froze
uvicorn's event loop and made the WHOLE API unresponsive (every request
returned nginx 499 because nothing was ever answered).

A mocked in-memory generator cannot reproduce that, so this test runs a real
uvicorn server and checks that the API still answers while a log stream sits
open and idle.
"""
import asyncio
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

from app.main import app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _IdleLogStream:
    """Models `logs(follow=True)` on an idle container.

    Yields one line, then blocks waiting for output that never comes - the
    exact condition that used to freeze the event loop.
    """

    def __init__(self):
        self._released = threading.Event()
        self._first = True

    def __iter__(self):
        return self

    def __next__(self):
        if self._first:
            self._first = False
            return b"container started\n"
        self._released.wait(timeout=30)
        raise StopIteration

    def close(self):
        self._released.set()


class _Cont:
    name = "web"

    def __init__(self):
        self._stream = _IdleLogStream()

    def logs(self, **kwargs):
        return self._stream


class _Containers:
    def __init__(self, cont):
        self._cont = cont

    def list(self):
        return [self._cont]


class _Client:
    def __init__(self, cont):
        self.containers = _Containers(cont)


@pytest.fixture
def live_server(monkeypatch):
    """A real uvicorn server, so event-loop blocking is actually observable."""
    import app.routers.ws as ws_mod

    cont = _Cont()
    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: _Client(cont))

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("uvicorn did not start in time")

    yield port

    server.should_exit = True
    thread.join(timeout=10)


def test_ws_logs_does_not_freeze_the_api(live_server):
    port = live_server
    received = []
    errors = []

    async def consume():
        import websockets
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws/logs?filter=web"
            ) as ws:
                received.append(await asyncio.wait_for(ws.recv(), timeout=15))
                # Hold the connection open while the stream is idle.
                await asyncio.sleep(6)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    worker = threading.Thread(target=lambda: asyncio.run(consume()), daemon=True)
    worker.start()

    # Wait until the first line arrived, meaning the reader is now blocked idle.
    deadline = time.time() + 15
    while not received and time.time() < deadline:
        time.sleep(0.1)
    assert received, f"no log line received over websocket; errors={errors}"
    assert "container started" in received[0]

    # The API must stay responsive while the log stream is open and idle.
    start = time.time()
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/health", timeout=10
    ) as resp:
        body = resp.read()
    elapsed = time.time() - start

    assert resp.status == 200
    assert b"ok" in body
    assert elapsed < 3, (
        f"API was blocked for {elapsed:.1f}s while /ws/logs sat idle - "
        "the blocking docker log generator is running on the event loop again"
    )
