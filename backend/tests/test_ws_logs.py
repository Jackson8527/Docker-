import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


class _Stream:
    """A finished log stream: yields the given lines, then stops."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass


class _LongLivedStream:
    """Models `logs(follow=True)` on a *busy* container.

    It produces `lines` at a fixed pace and then - exactly like a real
    follow-stream on a container that has gone quiet - keeps the connection
    open and blocks instead of ending. `produced` is set once every line has
    been handed over, which lets a test observe the coalescing that happens
    *while the stream is still running*.
    """

    def __init__(self, lines, delay=0.003):
        self._lines = list(lines)
        self._i = 0
        self._delay = delay
        self._released = threading.Event()
        self.produced = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        if self._i < len(self._lines):
            line = self._lines[self._i]
            self._i += 1
            time.sleep(self._delay)
            if self._i == len(self._lines):
                self.produced.set()
            return line
        # Production is over but the stream does NOT end: block until the
        # server closes it, which is what a real follow-stream does.
        self.produced.set()
        self._released.wait(timeout=30)
        raise StopIteration

    def close(self):
        self._released.set()


def _patch(monkeypatch, cont_factory):
    import app.routers.ws as ws_mod

    calls = {"list_all": []}

    class _Containers:
        def list(self, all=False):
            calls["list_all"].append(all)
            return cont_factory(all)

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: _Client())
    return calls


def test_ws_logs_reports_missing_container(monkeypatch):
    """No matching container => an explicit error frame, not a silent close.

    The assertion deliberately sits OUTSIDE any try/except: the previous version
    wrapped it in `try: ... except Exception: pass`, and since a failing assert
    raises AssertionError (an Exception) the case passed no matter what.
    """
    _patch(monkeypatch, lambda all: [])

    with c.websocket_connect("/ws/logs?filter=&stream=stdout") as ws:
        ws.send_text("ping")
        msg = ws.receive_json()

    assert msg.get("error") == "no container"
    # The discriminator is what keeps a container that prints a single-line
    # JSON log like {"error": "..."} from being mistaken for a protocol frame.
    assert msg.get("dockermgr") == "error", (
        "failure frames must carry the dockermgr discriminator (L-06)"
    )


def test_ws_logs_streams_a_stopped_container(monkeypatch):
    """A stopped container is still a valid target: its logs are the whole point."""
    captured = {}

    class _Cont:
        name = "old-web"

        def logs(self, **kwargs):
            captured.update(kwargs)
            return _Stream([b"last gasp\n"])

    calls = _patch(monkeypatch, lambda all: [] if not all else [_Cont()])

    with c.websocket_connect("/ws/logs?filter=old") as ws:
        assert ws.receive_text() == "last gasp"

    assert calls["list_all"] == [False, True], "running containers must be preferred"
    assert captured["follow"] is True


def test_ws_logs_joins_lines_with_newlines(monkeypatch):
    """One frame carries many `\\n`-joined lines (the frame format contract).

    NOTE: this case does NOT prove that batching happens - the mock stream ends
    immediately, so the closing flush alone would satisfy it. The coalescing
    itself is locked by `test_ws_logs_batches_a_long_lived_stream` below.
    """
    class _Cont:
        name = "chatty"

        def logs(self, **kwargs):
            return _Stream([b"l1\n", b"l2\n", b"l3\n"])

    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=chatty") as ws:
        frame = ws.receive_text()

    assert frame.split("\n") == ["l1", "l2", "l3"]


def test_ws_logs_batches_a_long_lived_stream(monkeypatch):
    """A busy container must be coalesced per flush interval, with no tail lost.

    Spec §6 asks for throttling, which is implemented by a timer thread that
    periodically flushes a buffer filled by the blocking reader thread. That
    mechanism used to have no regression test at all: with a short mock stream
    the closing flush satisfies every assertion, so deleting the whole timer
    thread changed nothing (`600 lines -> 1 frame`, tests still green).

    So this case uses a stream that keeps producing (600 lines, ~3 ms apart =
    ~1.8 s) and then stays open. While it is STILL open we require:
      * frames actually arrived during the run  -> deleting the timer thread
        yields 0 frames and fails here;
      * every line arrived, tail included       -> the timer's periodic flush
        must deliver the last partial batch without waiting for the stream end;
      * frames << lines                         -> without coalescing (one frame
        per line) this fails as well.
    """
    LINES = 600
    payload = [f"line-{i:03d}\n".encode() for i in range(LINES)]
    stream = _LongLivedStream(payload, delay=0.003)

    class _Cont:
        name = "chatty"

        def logs(self, **kwargs):
            return stream

    _patch(monkeypatch, lambda all: [_Cont()])

    frames: list[str] = []
    errors: list[BaseException] = []

    with c.websocket_connect("/ws/logs?filter=chatty") as ws:
        def collect():
            try:
                while True:
                    frames.append(ws.receive_text())
            except BaseException as e:  # connection closed by the server
                errors.append(e)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()

        try:
            # Wait until the mock has handed over all 600 lines; from here on
            # the only thing that can move data to the client is the timer.
            assert stream.produced.wait(timeout=30), "mock stream produced nothing"

            def received_lines() -> list[str]:
                return [ln for f in list(frames) for ln in f.split("\n") if ln]

            # Give the flush interval room to deliver the final partial batch,
            # even though the stream itself never ends.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(received_lines()) < LINES:
                time.sleep(0.05)

            lines_now = received_lines()
            frames_now = len(frames)
            # Printed so a healthy run documents the coalescing it observed
            # (run pytest with -s); it is also what a failure must explain.
            print(
                f"\n  batching: {len(lines_now)} lines delivered in {frames_now} "
                f"frames while the stream was still open"
            )
            assert frames_now > 0, (
                "no frame arrived while the stream was still producing: the "
                "periodic flush (timer thread) is gone, so everything now waits "
                "for the stream to end"
            )
            assert len(lines_now) == LINES, (
                f"only {len(lines_now)}/{LINES} lines arrived while the stream "
                "was still open - the tail of an idle container is being lost"
            )
            assert lines_now[0] == "line-000" and lines_now[-1] == f"line-{LINES - 1:03d}"
            assert frames_now * 3 < LINES, (
                f"{frames_now} frames for {LINES} lines: lines are no longer "
                "coalesced (one frame per line is the pre-throttle behaviour)"
            )
        finally:
            # Closing the socket unblocks the reader and ends the session, so
            # the test cannot leave a thread waiting for 30 s.
            stream.close()

    # The reader ends as soon as the session (and with it the stream) closes.
    reader.join(timeout=10)
    assert not reader.is_alive(), "the websocket session did not shut down"


def test_ws_logs_reports_a_stream_that_cannot_be_opened(monkeypatch):
    """A failed stream setup is reported, not closed silently.

    `cont.logs()` can fail on its own (the daemon hiccups, the container is
    removed between the name lookup and the request). That used to fall through
    to the generic handler and close the socket with zero frames, which from the
    browser is indistinguishable from "the container logged nothing". Opening
    the stream now happens on the producer thread, so the async side is the only
    one that can send - and it does: error frame first, close second.

    Note this is the one case where the producer must NOT set `stop`: doing so
    would let the receive loop leave before it got to send the frame.
    """
    class _Cont:
        name = "grumpy"

        def logs(self, **kwargs):
            raise RuntimeError("daemon said no")

    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=grumpy") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error", (
        "a stream that cannot be opened must still carry the error discriminator"
    )
    assert isinstance(msg.get("error"), str) and msg["error"], (
        "the error frame must carry a non-empty string"
    )
    assert "daemon said no" in msg["error"], (
        f"the daemon's own words must reach the user, got {msg['error']!r}"
    )


@pytest.mark.parametrize("lines", [40, 43])
def test_ws_logs_drops_the_oldest_lines_when_the_buffer_is_full(monkeypatch, lines):
    """Overflow keeps the NEWEST lines and says how many were dropped.

    This is the RD3-12 case: the comment claimed a bounded "drop-oldest" buffer
    while the code did `pending.clear()` - throwing the newest lines away along
    with the old ones, i.e. exactly the output a client that fell behind wants.
    The rule is now really drop-oldest, and this case pins the observable
    semantics: which lines survive, which are gone, and that the loss is
    announced instead of silent.

    Both an exact multiple of the limit (40) and a non-multiple (43) are pinned.
    The multiple is the pathological case that makes the old code lose *every*
    line; the non-multiple shows the subtler - and more common - half of the
    same defect, where the old code happened to keep a few of the OLDEST lines
    while still discarding the newest.
    """
    import app.routers.ws as ws_mod

    LIMIT = 5
    LINES = lines
    monkeypatch.setattr(ws_mod, "LOG_MAX_PENDING_LINES", LIMIT)
    # One flush only - the closing one. A periodic flush in the middle would
    # drain the buffer and the overflow would never happen.
    monkeypatch.setattr(ws_mod, "LOG_FLUSH_INTERVAL", 60.0)

    payload = [f"line-{i:02d}\n".encode() for i in range(LINES)]

    class _Cont:
        name = "flood"

        def logs(self, **kwargs):
            return _Stream(payload)

    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=flood") as ws:
        frame = ws.receive_text()

    got = frame.split("\n")
    print(f"\n  overflow with limit={LIMIT}, {LINES} lines: {got!r}")

    # The notice is its own line - `"\n".join` never glues it to a log line.
    assert got[0] == f"... {LINES - LIMIT} lines dropped (client too slow) ...", (
        f"the drop notice must be a line of its own, got {frame!r}"
    )
    # Drop-OLDEST: the newest LIMIT lines survive, in order...
    assert got[1:] == [f"line-{i:02d}" for i in range(LINES - LIMIT, LINES)], (
        f"the buffer must keep the newest {LIMIT} lines, got {got[1:]!r}"
    )
    # ...and the oldest ones are the ones that went missing.
    assert not any(line in frame for line in ("line-00", "line-01", "line-34"))


def test_ws_logs_keeps_the_empty_lines_the_container_actually_logged(monkeypatch):
    """An empty line in the frame means the container logged an empty line.

    RD3-12: the drop-notice comment used to promise a frame free of empty
    lines. `"\\n".join` cannot promise that - an empty log line is preserved
    verbatim, and deliberately so: filtering it out would hide real output.
    What the notice does guarantee is only that it is never glued onto a
    neighbouring line and carries no newline of its own. This case pins both
    halves of that honest claim.
    """
    class _Cont:
        name = "blank"

        def logs(self, **kwargs):
            return _Stream([b"a\n", b"\n", b"c\n"])

    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=blank") as ws:
        frame = ws.receive_text()

    assert frame == "a\n\nc", (
        f"the container's own empty line must survive verbatim, got {frame!r}"
    )


def _record_threads(monkeypatch):
    """Capture every thread `/ws/logs` starts, so leaks are observable.

    `threading.enumerate()` would be global (and noisy: other tests' threads,
    the TestClient portal); recording the factory keeps the assertion scoped to
    the two threads this endpoint owns.
    """
    import app.routers.ws as ws_mod

    created: list[threading.Thread] = []
    real_thread = threading.Thread

    class _Recording:
        Event = threading.Event
        Lock = threading.Lock

        @staticmethod
        def Thread(target=None, daemon=None, **kwargs):
            thread = real_thread(target=target, daemon=daemon, **kwargs)
            created.append(thread)
            return thread

    monkeypatch.setattr(ws_mod, "threading", _Recording)
    return created


def _wait_dead(threads, timeout=10.0) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(t.is_alive() for t in threads):
        time.sleep(0.05)
    return [t.name for t in threads if t.is_alive()]


class _GatedStream:
    """A stream whose *opening* is held until the test releases it."""

    def __init__(self):
        self.closed = threading.Event()
        self._released = threading.Event()
        self._first = True

    def __iter__(self):
        return self

    def __next__(self):
        if self._first:
            self._first = False
            return b"late\n"
        self._released.wait(timeout=5)
        raise StopIteration

    def close(self):
        self.closed.set()
        self._released.set()


def test_ws_logs_stops_its_threads_when_the_client_disconnects(monkeypatch):
    """A disconnected client must not leave a reader parked on the socket.

    The follow-stream of an idle container never ends by itself, so teardown has
    to close it to unblock the producer. Miss that and every closed browser tab
    leaves a thread blocked in `next()` for the lifetime of the process.
    """
    created = _record_threads(monkeypatch)
    stream = _LongLivedStream([b"one\n"], delay=0.001)
    closed = {"n": 0}

    class _Cont:
        name = "idle"

        def logs(self, **kwargs):
            return stream

    real_close = stream.close

    def _counting_close():
        closed["n"] += 1
        real_close()

    monkeypatch.setattr(stream, "close", _counting_close)
    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=idle") as ws:
        assert ws.receive_text() == "one"

    assert created, "no producer/timer thread was ever started"
    alive = _wait_dead(created)
    assert not alive, f"threads still alive after the client left: {alive}"
    assert closed["n"] >= 1, "the log stream was never closed on disconnect"


def test_ws_logs_closes_the_stream_if_the_client_leaves_during_setup(monkeypatch):
    """The client can vanish while the daemon is still answering `logs()`.

    Setup now happens on the producer thread, so the handler's `finally` can run
    while `log_stream` is still None - it has nothing of its own to close. The
    producer therefore has to notice `stop` by itself once the stream finally
    arrives. Without that check the stream is never closed: the docker-side
    stream and its socket leak for the life of the process.
    """
    created = _record_threads(monkeypatch)
    gate = threading.Event()
    stream = _GatedStream()

    class _Cont:
        name = "slow"

        def logs(self, **kwargs):
            # Still answering while the client comes and goes.
            gate.wait(timeout=10)
            return stream

    _patch(monkeypatch, lambda all: [_Cont()])

    with c.websocket_connect("/ws/logs?filter=slow") as ws:
        ws.send_text("hello")  # accepted, then dropped: we leave immediately

    # Well past LOG_POLL_INTERVAL: the handler has given up and returned by now,
    # so `log_stream` was still None when its `finally` ran.
    time.sleep(1.0)
    gate.set()

    alive = _wait_dead(created)
    assert not alive, f"threads still alive after the client left: {alive}"
    assert stream.closed.is_set(), (
        "the stream opened after the client had already gone and was never "
        "closed: the producer must check `stop` before it starts reading"
    )


def test_ws_logs_delivers_the_tail_even_if_the_flush_timer_never_runs(monkeypatch):
    """The final flush must not depend on the timer thread being alive.

    Teardown joins the timer thread before the last flush. If that join is not
    guarded, a timer thread that was never started (or already gone) makes the
    join raise - and the tail of the log is lost on the way out. The reader
    thread must still run, so only the flusher is replaced.
    """
    import app.routers.ws as ws_mod

    class _DeadTimer:
        def start(self):
            pass

        def is_alive(self):
            return False

        def join(self, timeout=None):
            raise AssertionError("must not join a thread that was never started")

    class _Threading:
        Event = threading.Event
        Lock = threading.Lock

        @staticmethod
        def Thread(target=None, daemon=None, **kwargs):
            if getattr(target, "__name__", "") == "flusher":
                return _DeadTimer()
            return threading.Thread(target=target, daemon=daemon, **kwargs)

    monkeypatch.setattr(ws_mod, "threading", _Threading)

    class _Cont:
        name = "quiet"

        def logs(self, **kwargs):
            return _Stream([b"one\n", b"two\n", b"three\n"])

    _patch(monkeypatch, lambda all: [_Cont()])

    frames: list[str] = []
    with c.websocket_connect("/ws/logs?filter=quiet") as ws:
        def collect():
            try:
                while True:
                    frames.append(ws.receive_text())
            except BaseException:  # the server closed the socket: expected
                pass

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        # Bounded wait, so a missing frame fails the case instead of blocking
        # the whole run on a receive that will never return.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not frames:
            time.sleep(0.05)

    assert frames, (
        "the tail must still be flushed when the timer thread is not running"
    )
    assert frames[0].split("\n") == ["one", "two", "three"]
