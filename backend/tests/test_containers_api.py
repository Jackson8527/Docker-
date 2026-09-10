from fastapi.testclient import TestClient

from app.main import app
from app.routers.containers import _format_ports

c = TestClient(app)


class _Img:
    """Mirrors docker-py: image.tags is a LIST."""
    tags = ["nginx:latest"]


class _Cont:
    """Mirrors docker-py Container shape.

    Deliberately has NO `.state` attribute, `.image.tags` is a list, and
    `.ports` is a dict keyed by container port - that is how the real
    docker-py object behaves. A mock that invents `.state` or a list-shaped
    `.ports` hides real integration bugs.
    """
    id = "abc123"
    name = "web"
    image = _Img()
    status = "running"
    ports = {
        "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
        "443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}],
        "9000/tcp": None,
    }
    attrs = {
        "Created": "2026-01-01T00:00:00Z",
        "State": {"Status": "running", "StartedAt": "2026-01-01T00:00:01Z"},
        "Name": "/web",
    }


def _client(monkeypatch, cont=None):
    import app.routers.containers as containers_mod

    class _Containers:
        def list(self, **k):
            return [cont or _Cont()]

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(containers_mod, "get_docker_client", lambda: _Client())


def test_containers_list_returns_list(monkeypatch):
    _client(monkeypatch)

    r = c.get("/api/containers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "web"
    assert data[0]["state"] == "running"
    assert data[0]["image"] == "nginx:latest"


class _DanglingCont:
    """A container whose image has been deleted.

    docker-py resolves `.image` through an API call that raises ImageNotFound
    in this case, which used to turn the entire listing into a 500.
    """

    id = "dangling1"
    name = "orphan"
    status = "exited"
    ports = {}
    attrs = {
        "Created": "2026-01-01T00:00:00Z",
        "State": {"Status": "exited"},
        "Image": "sha256:ca1f4099dc47ab14112ba323e663638a3be2efa7dcca39f7aeda7e3e1784dc7e",
        "Config": {"Image": "removed-app:latest"},
    }

    @property
    def image(self):
        raise RuntimeError("404 Client Error: No such image")


def test_containers_list_survives_dangling_image_reference(monkeypatch):
    """One container pointing at a deleted image must not break the page."""
    _client(monkeypatch, cont=_DanglingCont())

    r = c.get("/api/containers")
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert row["name"] == "orphan"
    # Falls back to the name recorded at creation time.
    assert row["image"] == "removed-app:latest"


def test_containers_list_falls_back_to_image_id(monkeypatch):
    """With no Config.Image either, show a short image id rather than failing."""

    class _NoConfigImage(_DanglingCont):
        attrs = {
            "Created": "2026-01-01T00:00:00Z",
            "State": {"Status": "exited"},
            "Image": "sha256:ca1f4099dc47ab14112ba323e663638a3be2efa7dcca39f7aeda7e3e1784dc7e",
        }

    _client(monkeypatch, cont=_NoConfigImage())

    r = c.get("/api/containers")
    assert r.status_code == 200, r.text
    assert r.json()[0]["image"] == "ca1f4099dc47"


def test_format_ports_is_human_readable():
    """The UI shows this string directly, so it must not be a dict repr."""
    assert _format_ports({"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}) == "8080->80/tcp"
    assert (
        _format_ports({"443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]})
        == "127.0.0.1:8443->443/tcp"
    )
    # A port with no host binding is exposed but not published.
    assert _format_ports({"9000/tcp": None}) == "9000/tcp"
    assert _format_ports({}) == ""
    assert _format_ports(None) == ""


def test_format_ports_collapses_ipv4_ipv6_duplicates():
    """A published port comes back bound to both 0.0.0.0 and ::.

    Both render identically, which used to show up as '56371->80/tcp,
    56371->80/tcp' in the UI.
    """
    ports = {
        "80/tcp": [
            {"HostIp": "0.0.0.0", "HostPort": "56371"},
            {"HostIp": "::", "HostPort": "56371"},
        ]
    }
    assert _format_ports(ports) == "56371->80/tcp"


def test_format_ports_keeps_distinct_bindings():
    """Two genuinely different host bindings must both survive."""
    ports = {
        "80/tcp": [
            {"HostIp": "127.0.0.1", "HostPort": "8080"},
            {"HostIp": "192.168.1.5", "HostPort": "8080"},
        ]
    }
    assert _format_ports(ports) == "127.0.0.1:8080->80/tcp, 192.168.1.5:8080->80/tcp"


def test_containers_ports_field_is_formatted(monkeypatch):
    _client(monkeypatch)

    data = c.get("/api/containers").json()
    ports = data[0]["ports"]
    assert "8080->80/tcp" in ports, f"ports not formatted: {ports!r}"
    assert "9000/tcp" in ports
    assert "{" not in ports, "raw dict repr leaked into the UI"
