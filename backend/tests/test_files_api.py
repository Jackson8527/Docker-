import io

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_copy_route_requires_valid_container(monkeypatch):
    # Server should return a Docker error (non-2xx) for missing container,
    # proving the route exists and is reachable.
    import app.routers.files as files_mod

    class _Missing:
        def put_archive(self, *a, **k):
            raise Exception("no such container")

    class _Containers:
        def get(self, cid):
            return _Missing()

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(files_mod, "get_docker_client", lambda: _Client())
    monkeypatch.setattr(files_mod, "get_tmp_dir",
                        lambda: files_mod.Path("."))

    r = c.post(
        "/api/containers/missing/copy",
        data={"dest": "/tmp"},
        files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert r.status_code == 500