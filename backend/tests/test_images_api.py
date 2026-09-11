from fastapi.testclient import TestClient

from app.main import app
from app.routers.images import _repo_digest

c = TestClient(app)


class _Img:
    """Mirrors docker-py: .attrs carries RepoDigests, tags is a list."""

    id = "sha256:abc123def456"
    short_id = "sha256:abc123def456"
    tags = ["nginx:latest"]

    def __init__(self, repo_digests=None):
        self.attrs = {"RepoDigests": repo_digests or []}


class _Images:
    def __init__(self, imgs):
        self._imgs = imgs

    def list(self, **k):
        return self._imgs


def _install(monkeypatch, imgs):
    import app.routers.images as images_mod

    class _Client:
        images = _Images(imgs)

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _Client())


def test_images_returns_list(monkeypatch):
    _install(monkeypatch, [_Img()])

    r = c.get("/api/images")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["tags"] == ["nginx:latest"]


def test_repo_digest_is_not_the_image_id():
    """The Digest column used to be an exact copy of the ID column."""
    img = _Img(["nginx@sha256:" + "f" * 64])
    assert _repo_digest(img) == "sha256:" + "f" * 64
    assert _repo_digest(img) != img.short_id


def test_repo_digest_empty_for_locally_built_images():
    assert _repo_digest(_Img()) == ""


def test_repo_digest_survives_a_missing_attrs_attribute():
    class _Bare:
        pass

    assert _repo_digest(_Bare()) == ""


def test_images_expose_distinct_id_and_digest(monkeypatch):
    _install(monkeypatch, [_Img(["mysql@sha256:" + "a" * 64])])

    row = c.get("/api/images").json()[0]
    # The UI shows short_id and the manifest digest as separate columns.
    assert row["short_id"] == "abc123def456"
    assert row["digest"] == "sha256:" + "a" * 64
    assert row["short_id"] not in row["digest"]
