from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


class _Img:
    """Mirrors docker-py: image.tags is a LIST."""
    tags = ["nginx:latest"]


class _Cont:
    """Mirrors docker-py Container shape.

    Deliberately has NO `.state` attribute and `.image.tags` is a list,
    because that is how the real docker-py object behaves. A mock that
    invents `.state` would hide the real integration bug.
    """
    id = "abc123"
    name = "web"
    image = _Img()
    status = "running"
    ports = [{"PrivatePort": 80, "PublicPort": 8080}]
    attrs = {
        "Created": "2026-01-01T00:00:00Z",
        "State": {"Status": "running", "StartedAt": "2026-01-01T00:00:01Z"},
        "Name": "/web",
    }


def test_containers_list_returns_list(monkeypatch):
    import app.routers.containers as containers_mod

    class _Containers:
        def list(self, **k):
            return [_Cont()]

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(containers_mod, "get_docker_client", lambda: _Client())

    r = c.get("/api/containers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "web"
    assert data[0]["state"] == "running"
    assert data[0]["image"] == "nginx:latest"