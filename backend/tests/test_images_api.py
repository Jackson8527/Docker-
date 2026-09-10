from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_images_returns_list(monkeypatch):
    import app.routers.images as images_mod

    class _Img:
        id = "sha256:abc"
        short_id = "abc"
        tags = ["nginx:latest"]

    class _Images:
        def list(self, **k):
            return [_Img()]

    class _Client:
        images = _Images()

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _Client())

    r = c.get("/api/images")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["tags"] == ["nginx:latest"]