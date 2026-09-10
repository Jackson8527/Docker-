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


def test_containers_ports_field_is_formatted(monkeypatch):
    _client(monkeypatch)

    data = c.get("/api/containers").json()
    ports = data[0]["ports"]
    assert "8080->80/tcp" in ports, f"ports not formatted: {ports!r}"
    assert "9000/tcp" in ports
    assert "{" not in ports, "raw dict repr leaked into the UI"
