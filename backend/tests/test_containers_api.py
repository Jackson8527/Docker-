from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_containers_list_returns_list(monkeypatch):
    import app.routers.containers as containers_mod

    class _Img:
        tags = "nginx:latest"

    class _Cont:
        id = "abc123"
        name = "web"
        image = _Img()
        state = "running"
        status = "Up 2 hours"
        ports = [{"PrivatePort": 80, "PublicPort": 8080}]
        attrs = {"Created": "2026-01-01T00:00:00Z"}

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