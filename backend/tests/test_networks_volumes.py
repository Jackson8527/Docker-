from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_networks_list(monkeypatch):
    import app.routers.networks as networks_mod

    class _N:
        id = "net1"
        name = "bridge"
        attrs = {"Driver": "bridge", "Scope": "local"}

    class _Networks:
        def list(self, **k):
            return [_N()]

    class _Client:
        networks = _Networks()

    monkeypatch.setattr(networks_mod, "get_docker_client", lambda: _Client())

    r = c.get("/api/networks")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "bridge"


def test_volumes_list(monkeypatch):
    import app.routers.volumes as volumes_mod

    class _V:
        name = "mydata"
        attrs = {"Driver": "local", "Mountpoint": "/var/lib/docker/volumes/mydata/_data"}

    class _Volumes:
        def list(self, **k):
            return [_V()]

    class _Client:
        volumes = _Volumes()

    monkeypatch.setattr(volumes_mod, "get_docker_client", lambda: _Client())

    r = c.get("/api/volumes")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "mydata"