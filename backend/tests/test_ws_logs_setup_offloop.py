"""Regression test for the RD3-02 freeze: opening the log stream must not run
on the event loop.

`test_ws_logs_blocking.py` covers the *iteration* half of `/ws/logs`: a stream
that sits idle after the first line never blocks the loop, because `next()`
runs on the producer thread. It does not cover the half that was still broken.

`cont.logs(follow=True, stream=True)` is not a lazy generator. docker-py sends
the HTTP request (and, inside `_check_is_tty`, a synchronous inspect) on the
*calling* thread before it returns anything to iterate. Called from the async
handler, one slow daemon answer froze every other request and websocket for its
whole duration. The reviewer measured `/api/health` at 1525 ms worst case with
`logs()` forged to take 1.5 s (healthy baseline: 1-34 ms).

A mocked in-memory generator cannot show that, so this test drives a real
uvicorn server and measures `/api/health` while the mock `logs()` is
deliberately parked.

Methodology
-----------
* The mock sets `entered` *immediately before* it blocks, so the health request
  is guaranteed to be issued inside the blocking window - the measurement is
  never accidentally taken before the freeze starts.
* Two orders of magnitude separate the outcomes: with the setup on the loop the
  answer cannot come back before the park ends (~1.5 s), with the setup on a
  worker thread it comes back in single-digit milliseconds. The threshold sits
  an order of magnitude below the failing measurement and an order of magnitude
  above a healthy one, so this cannot pass or fail by luck.
* A warm-up request is issued before the websocket connects, so a cold server's
  first-request cost is not mistaken for a freeze.
"""
import asyncio
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

from app.main import app

BLOCK_SECONDS = 1.5
# 3x below the blocking window (so the broken version cannot sneak under it) and
# ~10x above a healthy answer (so a loaded CI machine cannot push it over).
MAX_LATENCY = 0.5


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _IdleLogStream:
    """A follow-stream after its first line: stays open and blocks."""

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
    """A container whose `logs()` takes BLOCK_SECONDS to even return."""

    name = "web"

    def __init__(self):
        self.entered = threading.Event()
        self.logs_calls = 0

    def logs(self, **kwargs):
        # This is the whole point of the mock: docker-py does its HTTP work
        # *here*, on whichever thread calls it, before handing back a generator.
        self.logs_calls += 1
        self.entered.set()
        time.sleep(BLOCK_SECONDS)
        return _IdleLogStream()


class _Containers:
    def __init__(self, cont):
        self._cont = cont

    def list(self, all=False):
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

    yield port, cont

    server.should_exit = True
    thread.join(timeout=10)


def _health(port: int) -> tuple[float, int, bytes]:
    # `time.perf_counter`, not `time.monotonic`: on Windows the latter is backed
    # by GetTickCount64, whose tick is 15.625 ms. A healthy answer is well under
    # one tick, so `monotonic` would report it as a flat 0 ms and hide the very
    # number this test exists to show. perf_counter uses QueryPerformanceCounter
    # (100 ns) and resolves it.
    start = time.perf_counter()
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/health", timeout=10
    ) as resp:
        body = resp.read()
    return time.perf_counter() - start, resp.status, body


def test_ws_logs_stream_setup_does_not_block_the_event_loop(live_server):
    port, cont = live_server

    # Warm-up: the first HTTP request on a fresh server pays import/socket costs
    # that have nothing to do with the freeze under test.
    _, warm_status, warm_body = _health(port)
    assert warm_status == 200 and b"ok" in warm_body

    received: list[str] = []
    errors: list[str] = []

    async def consume():
        import websockets

        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws/logs?filter=web"
            ) as ws:
                received.append(await asyncio.wait_for(ws.recv(), timeout=20))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    worker = threading.Thread(target=lambda: asyncio.run(consume()), daemon=True)
    worker.start()

    # Park the daemon stand-in inside logs(), then measure. Waiting on `entered`
    # is what makes the measurement meaningful: the request below is issued
    # while logs() is provably still running.
    assert cont.entered.wait(timeout=15), "the websocket never reached cont.logs()"
    assert cont.logs_calls == 1, (
        f"cont.logs() was called {cont.logs_calls} times, expected exactly one"
    )

    elapsed, status, body = _health(port)
    print(
        f"\n  /api/health while logs() was parked: {elapsed * 1000:.2f} ms "
        f"(blocking window {BLOCK_SECONDS * 1000:.0f} ms, "
        f"budget {MAX_LATENCY * 1000:.0f} ms)"
    )

    assert status == 200
    assert b"ok" in body
    assert elapsed < MAX_LATENCY, (
        f"/api/health took {elapsed:.2f}s while cont.logs() was parked for "
        f"{BLOCK_SECONDS}s: opening the log stream is running on the event loop "
        "again (RD3-02) - one slow daemon answer freezes the whole API"
    )

    worker.join(timeout=20)
    assert received, f"no log line ever arrived over the websocket; errors={errors}"
    assert "container started" in received[0]
