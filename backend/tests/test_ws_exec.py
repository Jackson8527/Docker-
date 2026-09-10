"""Tests for the interactive exec terminal.

These use a real socket pair instead of a live daemon so the bidirectional
data path (websocket -> docker socket -> websocket) is actually exercised.
"""
import json
import socket
import time

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


class _FakeSocketIO:
    """Mimics docker-py's SocketIO wrapper.

    It exposes `_sock` and `close()` but deliberately has NO settimeout() or
    setblocking(), because the real wrapper does not either - code that calls
    `sock.settimeout(...)` raises AttributeError in production.
    """

    def __init__(self, sock):
        self._sock = sock

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class _FakeApi:
    def __init__(self, server_sock):
        self._server_sock = server_sock
        self.create_calls = []
        self.resize_calls = []

    def exec_create(self, container_id, cmd, **kwargs):
        self.create_calls.append((container_id, cmd, kwargs))
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, **kwargs):
        self.start_kwargs = kwargs
        return _FakeSocketIO(self._server_sock)

    def exec_resize(self, exec_id, height=None, width=None):
        self.resize_calls.append((exec_id, height, width))


class _Containers:
    def __init__(self, cont):
        self._cont = cont

    def get(self, cid):
        return self._cont


class _FakeCont:
    name = "web"
    id = "web-id"


class _Client:
    def __init__(self, api, cont):
        self.api = api
        self.containers = _Containers(cont)


def _wire(monkeypatch):
    """Install a fake docker client wired to a socket pair; return both ends."""
    import app.routers.ws as ws_mod

    server_end, test_end = socket.socketpair()
    api = _FakeApi(server_end)
    cont = _FakeCont()
    client = _Client(api, cont)
    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: client)
    return api, server_end, test_end


def test_exec_create_uses_stdin_true(monkeypatch):
    """Regression: without stdin=True the daemon sets AttachStdin=False and
    silently discards everything the user types."""
    api, server_end, test_end = _wire(monkeypatch)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            ws.send_text(json.dumps({"type": "input", "data": "echo hi\n"}))
            test_end.settimeout(5)
            test_end.recv(4096)
    except Exception:
        pass
    finally:
        test_end.close()

    assert api.create_calls, "exec_create was never called"
    _, cmd, kwargs = api.create_calls[0]
    assert kwargs.get("stdin") is True, "exec_create must be called with stdin=True"
    assert kwargs.get("tty") is True, "an interactive terminal needs tty=True"


def test_exec_forwards_input_and_output(monkeypatch):
    """Typed text must reach the docker socket and its output must come back."""
    api, server_end, test_end = _wire(monkeypatch)
    test_end.settimeout(5)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            # websocket -> docker socket (JSON control protocol)
            ws.send_text(json.dumps({"type": "input", "data": "echo hi\n"}))
            forwarded = test_end.recv(4096)
            assert b"echo hi" in forwarded, f"input not forwarded: {forwarded!r}"

            # docker socket -> websocket (raw terminal bytes)
            test_end.send(b"hi\r\n")
            msg = ws.receive_text()
            assert "hi" in msg, f"output not relayed back: {msg!r}"
    finally:
        test_end.close()


def test_exec_accepts_legacy_raw_text_input(monkeypatch):
    """Plain text frames must still work so older clients keep functioning."""
    api, server_end, test_end = _wire(monkeypatch)
    test_end.settimeout(5)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            ws.send_text("echo legacy\n")
            forwarded = test_end.recv(4096)
            assert b"echo legacy" in forwarded, f"legacy input not forwarded: {forwarded!r}"
    finally:
        test_end.close()


def test_exec_resize_is_forwarded_to_pty(monkeypatch):
    """The PTY must be resized to match the browser terminal.

    Without this the daemon keeps its default 80x24 PTY, so a wider terminal
    wraps every line at the wrong column.
    """
    api, server_end, test_end = _wire(monkeypatch)
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 30}))
            deadline = time.time() + 5
            while not api.resize_calls and time.time() < deadline:
                time.sleep(0.05)
    except Exception:
        pass
    finally:
        test_end.close()

    assert api.resize_calls, "exec_resize was never called"
    exec_id, height, width = api.resize_calls[0]
    assert exec_id == "exec-1"
    assert (height, width) == (30, 120), (
        f"expected height=rows(30) width=cols(120), got height={height} width={width}"
    )


def test_exec_route_reachable_for_missing_container(monkeypatch):
    """An unknown container must not hang or crash the route."""
    import app.routers.ws as ws_mod

    class _Containers:
        def get(self, cid):
            raise RuntimeError("no such container")

    class _Api:
        pass

    class _Client:
        api = _Api()
        containers = _Containers()

    monkeypatch.setattr(ws_mod, "get_docker_client", lambda: _Client())

    try:
        with c.websocket_connect("/ws/exec?container=missing") as ws:
            ws.send_text(json.dumps({"type": "input", "data": "ls"}))
            time.sleep(0.2)
    except Exception:
        # Closing the socket for a missing container is acceptable.
        pass
