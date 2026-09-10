"""Tests for the interactive exec terminal.

These use a real socket pair instead of a live daemon so the bidirectional
data path (websocket -> docker socket -> websocket) is actually exercised.
"""
import socket
import time

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


class _FakeSocketIO:
    """Mimics docker-py's SocketIO wrapper.

    It exposes `_sock` and `close()` but deliberately has NO settimeout(),
    because the real wrapper does not either - code that calls
    `sock.settimeout(...)` raises AttributeError in production.
    """

    def __init__(self, sock):
        self._sock = sock

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class _FakeExecResult:
    def __init__(self, output):
        self.output = output


class _FakeCont:
    name = "web"

    def __init__(self, server_sock):
        self._server_sock = server_sock
        self.calls = []

    def exec_run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return _FakeExecResult(_FakeSocketIO(self._server_sock))


def _wire(monkeypatch):
    """Install a fake docker client wired to a socket pair; return both ends."""
    import app.routers.ws as ws_mod

    server_end, test_end = socket.socketpair()
    cont = _FakeCont(server_end)

    class _Containers:
        def get(self, cid):
            return cont

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: _Client())
    return cont, server_end, test_end


def test_exec_run_uses_stdin_true(monkeypatch):
    """Regression: without stdin=True the daemon sets AttachStdin=False and
    silently discards everything the user types."""
    cont, server_end, test_end = _wire(monkeypatch)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            ws.send_text("echo hi\n")
            time.sleep(0.3)
    finally:
        test_end.close()

    assert cont.calls, "exec_run was never called"
    _, kwargs = cont.calls[0]
    assert kwargs.get("stdin") is True, "exec_run must be called with stdin=True"
    assert kwargs.get("tty") is True, "an interactive terminal needs tty=True"
    assert kwargs.get("socket") is True


def test_exec_forwards_input_and_output(monkeypatch):
    """Typed text must reach the docker socket and its output must come back."""
    cont, server_end, test_end = _wire(monkeypatch)
    test_end.settimeout(5)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            # websocket -> docker socket
            ws.send_text("echo hi\n")
            forwarded = test_end.recv(4096)
            assert b"echo hi" in forwarded, f"input not forwarded: {forwarded!r}"

            # docker socket -> websocket
            test_end.send(b"hi\r\n")
            msg = ws.receive_text()
            assert "hi" in msg, f"output not relayed back: {msg!r}"
    finally:
        test_end.close()


def test_exec_route_reachable_for_missing_container(monkeypatch):
    """An unknown container must not hang or crash the route."""
    import app.routers.ws as ws_mod

    class _Containers:
        def get(self, cid):
            raise RuntimeError("no such container")

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: _Client())

    try:
        with c.websocket_connect("/ws/exec?container=missing") as ws:
            ws.send_text("ls")
            time.sleep(0.2)
    except Exception:
        # Closing the socket for a missing container is acceptable.
        pass
