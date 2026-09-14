"""Behaviour coverage for endpoints that previously had no unit tests.

The Phase 4.6 review found 14 endpoints with zero tests, including three
main-line capabilities (F6 commit, F7 streaming export, F10 copy-out). The
volume-create contract test at the top is a regression lock for the Critical
the review found: `name: str = Body(...)` without embed=True expects a bare JSON
string, so every create from the UI failed with 422 string_type.

Every docker-py double in here follows docker-py 7.2.0's real shape: attribute
names and method signatures are copied from `.venv/Lib/site-packages/docker`.
A double that takes `(*args, **kwargs)` cannot notice a call site drifting from
the real API, and one that invents attributes (`Container.name == "/web"`)
cannot notice the router reading the wrong field.
"""
import json
import socket

import docker
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

c = TestClient(app)


def _client(**attrs):
    """A fake DockerClient exposing just the sub-clients a test needs."""
    return type("_Client", (), attrs)()


# --------------------------------------------------------------------------- #
# Contracts the UI depends on
# --------------------------------------------------------------------------- #


def test_volume_create_accepts_object_body(monkeypatch):
    import app.routers.volumes as volumes_mod

    seen = {}

    class _Volumes:
        def create(self, name):
            seen["name"] = name
            return object()

    monkeypatch.setattr(volumes_mod, "get_docker_client", lambda: _client(volumes=_Volumes()))

    r = c.post("/api/volumes", json={"name": "app-data"})

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert seen == {"name": "app-data"}


def test_network_create_accepts_object_body(monkeypatch):
    import app.routers.networks as networks_mod

    seen = {}

    class _Networks:
        def create(self, name, driver=None):
            seen.update(name=name, driver=driver)
            return object()

    monkeypatch.setattr(networks_mod, "get_docker_client", lambda: _client(networks=_Networks()))

    r = c.post("/api/networks", json={"name": "web", "driver": "bridge"})

    assert r.status_code == 200, r.text
    assert seen == {"name": "web", "driver": "bridge"}


# --------------------------------------------------------------------------- #
# Container actions (F1)
# --------------------------------------------------------------------------- #


def test_pause_and_unpause_call_docker(monkeypatch):
    import app.routers.containers as containers_mod

    class _Cont:
        def __init__(self):
            self.calls = []

        def pause(self):
            self.calls.append("pause")

        def unpause(self):
            self.calls.append("unpause")

    cont = _Cont()

    class _Containers:
        def get(self, cid):
            assert cid == "web"
            return cont

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    assert c.post("/api/containers/web/pause").json() == {"ok": True}
    assert c.post("/api/containers/web/unpause").json() == {"ok": True}
    assert cont.calls == ["pause", "unpause"]


# --------------------------------------------------------------------------- #
# F6 - commit a container into an image
# --------------------------------------------------------------------------- #


def _commit_client(commit):
    class _Cont:
        def __init__(self):
            self.kwargs = None

        def commit(self, **kwargs):
            self.kwargs = kwargs
            return commit()

    cont = _Cont()

    class _Containers:
        def get(self, cid):
            return cont

    return cont, _client(containers=_Containers())


def test_commit_creates_image_with_repo_and_tag(monkeypatch):
    import app.routers.containers as containers_mod

    class _Img:
        id = "sha256:deadbeef"

    cont, client = _commit_client(lambda: _Img())
    monkeypatch.setattr(containers_mod, "get_docker_client", lambda: client)

    r = c.post("/api/containers/web/commit", json={"repo": "myimg", "tag": "v1"})

    assert r.status_code == 200, r.text
    assert r.json() == {"image_id": "sha256:deadbeef"}
    assert cont.kwargs == {"repository": "myimg", "tag": "v1"}


def test_commit_failure_is_reported_with_a_readable_reason(monkeypatch):
    import app.routers.containers as containers_mod

    def boom():
        raise Exception("no space left on device")

    _, client = _commit_client(boom)
    monkeypatch.setattr(containers_mod, "get_docker_client", lambda: client)

    r = c.post("/api/containers/web/commit", json={"repo": "myimg", "tag": "v1"})

    assert r.status_code == 500
    assert "no space left" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# F7 - streaming image export
# --------------------------------------------------------------------------- #


def test_image_save_streams_and_keeps_the_name(monkeypatch):
    """The exported tarball must retain repository:tag (docker-py named=True)."""
    import app.routers.images as images_mod

    seen = {}

    class _Img:
        def save(self, named=False):
            seen["named"] = named
            return iter([b"TAR", b"BYTES"])

    class _Images:
        def get(self, iid):
            return _Img()

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _client(images=_Images()))

    r = c.get("/api/images/sha256:abc/save")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-tar"
    assert r.content == b"TARBYTES"
    assert seen["named"] is True, "named=False drops repository:tag from the archive"


def test_image_save_reports_failure(monkeypatch):
    import app.routers.images as images_mod

    class _Images:
        def get(self, iid):
            raise Exception("no such image")

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _client(images=_Images()))

    r = c.get("/api/images/nope/save")

    assert r.status_code == 500
    assert "no such image" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# F10 - copy a file out of a container
# --------------------------------------------------------------------------- #


def _copy_out_client(get_archive):
    class _Cont:
        def get_archive(self, path):
            return get_archive(path)

    class _Containers:
        def get(self, cid):
            return _Cont()

    return _client(containers=_Containers())


def test_copy_out_streams_the_archive(monkeypatch):
    import app.routers.files as files_mod

    def get_archive(path):
        assert path == "/etc/hosts"
        return iter([b"tar-bytes"]), {"name": "hosts"}

    monkeypatch.setattr(files_mod, "get_docker_client", lambda: _copy_out_client(get_archive))

    r = c.get("/api/containers/web/copy", params={"path": "/etc/hosts"})

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-tar"
    assert r.content == b"tar-bytes"


def test_copy_out_reports_failure(monkeypatch):
    import app.routers.files as files_mod

    def get_archive(path):
        raise Exception("path not found")

    monkeypatch.setattr(files_mod, "get_docker_client", lambda: _copy_out_client(get_archive))

    r = c.get("/api/containers/web/copy", params={"path": "/nope"})

    assert r.status_code == 500
    assert "path not found" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# F9 - exec terminal must say why it cannot open
# --------------------------------------------------------------------------- #


def test_ws_exec_reports_missing_container(monkeypatch):
    """A zero-frame close is indistinguishable from "the shell just exited"."""
    import app.routers.ws as ws_mod

    class _Containers:
        def get(self, cid):
            raise docker.errors.NotFound(f"no such container: {cid}")

    monkeypatch.setattr(
        ws_mod,
        "get_docker_client",
        lambda: _client(api=object(), containers=_Containers()),
    )

    with c.websocket_connect("/ws/exec?container=bogus") as ws:
        msg = ws.receive_json()

    assert "no such container" in msg["error"]
    # Discriminator, so a container's own JSON log line is never mistaken for a
    # protocol frame (L-06).
    assert msg.get("dockermgr") == "error"


def _exec_client_raising(monkeypatch, exc):
    import app.routers.ws as ws_mod

    class _Containers:
        def get(self, cid):
            raise exc

    monkeypatch.setattr(
        ws_mod,
        "get_docker_client",
        lambda: _client(api=object(), containers=_Containers()),
    )


def _docker_api_error(status, reason, explanation, url="http://127.0.0.1:2375/containers/x"):
    """docker-py's APIError renders status/url/reason straight off the response."""
    response = type("_Resp", (), {"status_code": status, "reason": reason, "url": url})()
    return docker.errors.APIError("daemon refused", response=response, explanation=explanation)


class _FakeSocketIO:
    """Mimics docker-py's SocketIO wrapper.

    It exposes `_sock` and `close()` and deliberately has NO settimeout() /
    setblocking(), because the real wrapper has none either - a router that
    calls them on the wrapper instead of the raw socket raises AttributeError in
    production while a friendlier double stays green.
    """

    def __init__(self, sock):
        self._sock = sock

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class _ExecApi:
    """docker-py 7.2.0's ExecApiMixin, with recording instead of HTTP.

    The parameter lists are copied from `.venv/Lib/site-packages/docker/api/
    exec_api.py`:

        exec_create(self, container, cmd, stdout=True, stderr=True, stdin=False,
                    tty=False, privileged=False, user='', environment=None,
                    workdir=None, detach_keys=None)
        exec_start(self, exec_id, detach=False, tty=False, stream=False,
                   socket=False, demux=False)

    Being *exact* is the whole point (RD3-11). The previous double was
    `exec_create(self, *args, **kwargs)`: it accepted every keyword, so a call
    site that grew a typo (`stdin_=True`) or a keyword docker-py never had would
    be recorded happily and the suite would stay green while the real daemon
    call raised TypeError. Note also that docker-py's first parameter really is
    named `container` - `utils.check_resource('container')` looks it up by name,
    so a keyword call must use exactly that spelling.
    """

    def __init__(self, create_error=None, start_error=None, socket_io=None):
        self.calls = []
        self.create_error = create_error
        self.start_error = start_error
        self.socket_io = socket_io
        self.resize_calls = []

    def exec_create(self, container, cmd, stdout=True, stderr=True, stdin=False,
                    tty=False, privileged=False, user="", environment=None,
                    workdir=None, detach_keys=None):
        self.calls.append(("exec_create", {
            "container": container, "cmd": cmd, "stdout": stdout,
            "stderr": stderr, "stdin": stdin, "tty": tty,
            "privileged": privileged, "user": user, "environment": environment,
            "workdir": workdir, "detach_keys": detach_keys,
        }))
        if self.create_error is not None:
            raise self.create_error
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, detach=False, tty=False, stream=False,
                   socket=False, demux=False):
        self.calls.append(("exec_start", {
            "exec_id": exec_id, "detach": detach, "tty": tty, "stream": stream,
            "socket": socket, "demux": demux,
        }))
        if self.start_error is not None:
            raise self.start_error
        return self.socket_io

    def exec_resize(self, exec_id, height=None, width=None):
        self.resize_calls.append((exec_id, height, width))


def test_ws_exec_reports_a_daemon_failure_instead_of_closing_silently(monkeypatch):
    """A non-404 docker failure must come with a readable reason too.

    Widening the handler to `except Exception` used to keep every test green:
    the error classification had no test at all, so a container that merely
    wasn't running produced a zero-frame close ("已断开", no reason).
    """
    _exec_client_raising(
        monkeypatch,
        _docker_api_error(409, "Conflict", "Container stopped-one is not running"),
    )

    with c.websocket_connect("/ws/exec?container=stopped-one") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error"
    assert "守护进程错误" in msg["error"], msg
    assert "not running" in msg["error"], msg


def test_ws_exec_treats_a_404_api_error_as_missing(monkeypatch):
    """docker-py raises plain APIError with status 404 in some paths."""
    _exec_client_raising(
        monkeypatch, _docker_api_error(404, "Not Found", "No such container: gone")
    )

    with c.websocket_connect("/ws/exec?container=gone") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error"
    assert "no such container: gone" in msg["error"], msg


def test_ws_exec_reports_an_unreachable_daemon(monkeypatch):
    """A daemon that cannot be talked to at all is still not a silent close."""
    _exec_client_raising(
        monkeypatch, docker.errors.DockerException("Error while fetching server API version")
    )

    with c.websocket_connect("/ws/exec?container=web") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error"
    assert "无法连接 docker 守护进程" in msg["error"], msg


def test_ws_exec_reports_a_container_that_cannot_be_executed(monkeypatch):
    """The common real-world failure happens at exec_create, not at get().

    `containers.get()` happily returns a stopped container; the daemon then
    answers exec_create with 409 Conflict. That path used to hit the generic
    handler and close with zero frames, which is exactly the "已断开 with no
    reason" the users reported.
    """
    import app.routers.ws as ws_mod

    class _Cont:
        id = "abc123"

    class _Containers:
        def get(self, cid):
            return _Cont()

    api = _ExecApi(create_error=_docker_api_error(
        409, "Conflict", "Container abc123 is not running",
        url="http://127.0.0.1:2375/exec",
    ))

    monkeypatch.setattr(
        ws_mod,
        "get_docker_client",
        lambda: _client(api=api, containers=_Containers()),
    )

    with c.websocket_connect("/ws/exec?container=stopped-one") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error"
    # APIError is a subclass of DockerException, so the generic branch would
    # also produce a frame - with the wrong explanation. Require the specific
    # classification, not just "some reason arrived".
    assert "守护进程错误" in msg["error"], msg
    assert "无法连接" not in msg["error"], msg
    assert "not running" in msg["error"], msg
    # The failure came from docker-py's exec_create, called the way docker-py
    # expects to be called - otherwise the mock would be testing itself.
    assert [name for name, _ in api.calls] == ["exec_create"], api.calls


def test_ws_exec_calls_docker_py_with_the_arguments_it_really_takes(monkeypatch):
    """Shape check against docker-py 7.2.0, run over a real socket pair.

    The double carries the real parameter list, so a drifted call site raises
    TypeError while binding and this test goes red - with `(*args, **kwargs)` it
    stayed green (mutation proof in the RD3 report). Two arguments are
    load-bearing for behaviour, not just shape:

    * `exec_create(..., stdin=True)` - without it the daemon answers with
      AttachStdin=False and silently discards every keystroke;
    * `exec_start(..., socket=True)` - without it docker-py returns an iterator
      of frames instead of the raw socket the PTY reader needs.
    """
    import app.routers.ws as ws_mod

    server_end, test_end = socket.socketpair()
    api = _ExecApi(socket_io=_FakeSocketIO(server_end))

    class _Cont:
        id = "abc123"

    class _Containers:
        def get(self, cid):
            return _Cont()

    monkeypatch.setattr(
        ws_mod,
        "get_docker_client",
        lambda: _client(api=api, containers=_Containers()),
    )
    try:
        with c.websocket_connect("/ws/exec?container=web") as ws:
            ws.send_text(json.dumps({"type": "input", "data": "echo hi\n"}))
            test_end.settimeout(5)
            test_end.recv(4096)
    except Exception:
        pass  # the assertions below are the point, not the live traffic
    finally:
        test_end.close()

    assert [name for name, _ in api.calls] == ["exec_create", "exec_start"], api.calls
    create = api.calls[0][1]
    assert create["container"] == "abc123"
    assert create["cmd"] == ["/bin/sh"], "the PTY must run the shell, not argv[0]"
    assert create["stdin"] is True, "without stdin=True the daemon discards input"
    assert create["tty"] is True, "an interactive terminal needs tty=True"
    assert create["stdout"] is True
    assert create["stderr"] is True
    assert api.calls[1][1] == {
        "exec_id": "exec-1", "detach": False, "tty": True, "stream": False,
        "socket": True, "demux": False,
    }, api.calls[1][1]


def test_ws_exec_still_reports_when_the_error_message_cannot_be_rendered(monkeypatch):
    """The failure frame must never depend on `str(exception)` succeeding.

    docker-py's APIError.__str__ dereferences `response.url`; if that blows up
    while we build the message and we let it escape, the socket closes with zero
    frames again - the silent close this endpoint exists to prevent.
    """
    class _UnprintableError(docker.errors.APIError):
        def __str__(self):
            raise RuntimeError("no string form for this error")

    _exec_client_raising(monkeypatch, _UnprintableError("boom"))

    with c.websocket_connect("/ws/exec?container=web") as ws:
        msg = ws.receive_json()

    assert msg.get("dockermgr") == "error"
    assert "_UnprintableError" in msg["error"], msg


# --------------------------------------------------------------------------- #
# Cross-site guard on state-changing endpoints
# --------------------------------------------------------------------------- #


def _exploding_volumes(monkeypatch):
    import app.routers.volumes as volumes_mod

    class _Volumes:
        def create(self, name):
            raise AssertionError("docker must not be reached for a rejected request")

    monkeypatch.setattr(volumes_mod, "get_docker_client", lambda: _client(volumes=_Volumes()))


def test_cross_site_write_is_rejected(monkeypatch):
    """A foreign page must not be able to drive the Docker socket."""
    _exploding_volumes(monkeypatch)

    r = c.post("/api/volumes", json={"name": "x"}, headers={"origin": "http://evil.example"})

    assert r.status_code == 403
    assert "cross-site" in r.json()["detail"]


def test_local_origin_write_is_allowed(monkeypatch):
    import app.routers.volumes as volumes_mod

    class _Volumes:
        def create(self, name):
            return object()

    monkeypatch.setattr(volumes_mod, "get_docker_client", lambda: _client(volumes=_Volumes()))

    r = c.post(
        "/api/volumes", json={"name": "x"}, headers={"origin": "http://127.0.0.1:8088"}
    )

    assert r.status_code == 200, r.text


def test_reads_are_deliberately_not_guarded(monkeypatch):
    """GET has no side effects, so it stays callable from anywhere."""
    r = c.get("/api/health", headers={"origin": "http://evil.example"})

    assert r.status_code == 200


def test_ws_handshake_from_a_foreign_page_is_rejected(monkeypatch):
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(
            "/ws/logs?filter=x", headers={"origin": "http://evil.example"}
        ):
            pass


# --------------------------------------------------------------------------- #
# Remaining endpoints: list flags, container detail/lifecycle/delete,
# network + volume + image delete, pull mirrors (C-15 leftovers)
# --------------------------------------------------------------------------- #


def test_containers_list_passes_the_all_flag(monkeypatch):
    """`?all=true` must reach the daemon: stopped containers are only visible then."""
    import app.routers.containers as containers_mod

    seen = []

    class _Containers:
        def list(self, all=False):
            seen.append(all)
            return []

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    assert c.get("/api/containers").status_code == 200
    assert c.get("/api/containers", params={"all": "true"}).status_code == 200
    assert seen == [False, True], "the all query parameter is not being forwarded"


def test_container_detail_maps_docker_py_shape(monkeypatch):
    """GET /{cid} must map attrs['State'] and the ports dict, not invent fields.

    The container is shaped exactly like docker-py 7.2.0 hands it over:
    `Container.name` is a property returning `attrs["Name"].lstrip("/")`, so it
    has NO leading slash, while `attrs["Name"]` always has one. The response
    must be built from the property - `attrs["Name"]` would leak "/web" to the
    UI (RD3-11: the double used to set `name = "/web"`, a shape docker-py never
    produces, which hid exactly that mistake).
    """
    import app.routers.containers as containers_mod

    seen = {}

    class _Img:
        tags = ["nginx:latest"]

    class _Cont:
        id = "abc123"
        name = "web"  # docker-py: attrs["Name"].lstrip("/")
        image = _Img()
        status = "running"
        ports = {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
        attrs = {
            "Name": "/web",  # the raw inspect value, slash included
            "Created": "2026-01-01T00:00:00Z",
            "State": {"Status": "running"},
        }

    class _Containers:
        def get(self, cid):
            seen["cid"] = cid
            return _Cont()

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    r = c.get("/api/containers/web")

    assert r.status_code == 200, r.text
    assert seen == {"cid": "web"}
    body = r.json()
    assert body["name"] == "web", (
        "name must come from Container.name; reading attrs['Name'] verbatim "
        "would return '/web'"
    )
    assert body["state"] == "running"
    assert body["image"] == "nginx:latest"
    assert body["ports"] == "8080->80/tcp"


@pytest.mark.parametrize("raw_name, expected", [("/web", "web"), (None, "")])
def test_container_detail_accepts_a_name_that_is_not_pre_stripped(
    monkeypatch, raw_name, expected
):
    """`_info`'s `(cont.name or "").lstrip("/")` guards the unprepped value.

    For a real docker-py 7.2.0 Container this is belt-and-braces: its `name`
    property already strips. It stops being redundant for anything whose `.name`
    hands back the raw attrs value - another docker-py version, a duck-typed
    object, a double - which is the case this test pins. The `or ""` half is
    real too: docker-py's property has no `else` branch, so a container whose
    attrs carry no `Name` returns None, and `ContainerInfo.name` is a plain str.
    """
    import app.routers.containers as containers_mod

    class _Cont:
        id = "abc123"
        image = None
        status = "running"
        ports = {}
        attrs = {"Created": "", "State": {"Status": "running"}}

    _Cont.name = raw_name

    class _Containers:
        def get(self, cid):
            return _Cont()

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    body = c.get("/api/containers/web").json()

    assert body["name"] == expected, body


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_container_lifecycle_actions_reach_docker(monkeypatch, action):
    import app.routers.containers as containers_mod

    calls = []

    class _Cont:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def restart(self):
            calls.append("restart")

    class _Containers:
        def get(self, cid):
            calls.append(("get", cid))
            return _Cont()

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    r = c.post(f"/api/containers/web/{action}")

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert calls == [("get", "web"), action]


def test_container_delete_passes_force(monkeypatch):
    """?force=true must be forwarded; it is what makes a running container go."""
    import app.routers.containers as containers_mod

    seen = {}

    class _Cont:
        def remove(self, force=False):
            seen["force"] = force

    class _Containers:
        def get(self, cid):
            seen["cid"] = cid
            return _Cont()

    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _client(containers=_Containers())
    )

    r = c.delete("/api/containers/web", params={"force": "true"})

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert seen == {"cid": "web", "force": True}

    # Default must stay non-forced (removing a running container without force
    # is supposed to fail loudly, not to kill it).
    assert c.delete("/api/containers/web").status_code == 200
    assert seen["force"] is False


def test_network_delete_removes_the_network(monkeypatch):
    import app.routers.networks as networks_mod

    calls = []

    class _Net:
        def remove(self):
            calls.append("remove")

    class _Networks:
        def get(self, nid):
            calls.append(("get", nid))
            return _Net()

    monkeypatch.setattr(
        networks_mod, "get_docker_client", lambda: _client(networks=_Networks())
    )

    r = c.delete("/api/networks/net1")

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert calls == [("get", "net1"), "remove"]


def test_volume_delete_removes_the_volume(monkeypatch):
    import app.routers.volumes as volumes_mod

    calls = []

    class _Vol:
        def remove(self):
            calls.append("remove")

    class _Volumes:
        def get(self, vid):
            calls.append(("get", vid))
            return _Vol()

    monkeypatch.setattr(
        volumes_mod, "get_docker_client", lambda: _client(volumes=_Volumes())
    )

    r = c.delete("/api/volumes/app-data")

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert calls == [("get", "app-data"), "remove"]


def test_image_delete_passes_force(monkeypatch):
    import app.routers.images as images_mod

    seen = {}

    class _Images:
        def remove(self, iid, force=False):
            seen.update(iid=iid, force=force)

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _client(images=_Images()))

    r = c.delete("/api/images/sha256:abc", params={"force": "true"})

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert seen == {"iid": "sha256:abc", "force": True}

    c.delete("/api/images/sha256:abc")
    assert seen["force"] is False


def test_pull_mirrors_reports_the_configured_list(monkeypatch):
    """The UI explains which mirrors a failing pull will try, so it must be readable."""
    import app.routers.images as images_mod

    monkeypatch.setattr(
        images_mod, "get_settings", lambda: {"image_mirrors": ["m1.example.com", "m2.example.com"]}
    )

    r = c.get("/api/images/pull/mirrors")

    assert r.status_code == 200, r.text
    assert r.json() == {"mirrors": ["m1.example.com", "m2.example.com"]}
