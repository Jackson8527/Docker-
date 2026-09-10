"""Tests for the registry-mirror fallback in POST /api/images/pull.

Docker Hub is unreachable on some networks, which used to make every pull
fail outright. The endpoint now retries Hub references through mirrors and
re-tags the result under the canonical name.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.routers.images import (
    _canonical,
    _hub_path,
    _is_docker_hub_ref,
    _is_registry_unreachable,
)

c = TestClient(app)

UNREACHABLE = (
    'failed to resolve reference "docker.io/library/mysql:latest": '
    "dial tcp 66.220.149.32:443: connectex: A connection attempt failed"
)


class _FakeImage:
    def __init__(self, client, ref):
        self._client = client
        self._ref = ref

    def tag(self, repository, tag=None):
        self._client.tags.append(f"{repository}:{tag}")


class _FakeImages:
    def __init__(self, fail_on=None):
        # fail_on maps a repository name to the error message it raises.
        self.fail_on = fail_on or {}
        self.pull_calls = []
        self.removed = []
        self.tags = []

    def pull(self, repository, tag=None):
        self.pull_calls.append(f"{repository}:{tag}")
        if repository in self.fail_on:
            raise RuntimeError(self.fail_on[repository])
        return _FakeImage(self, f"{repository}:{tag}")

    def get(self, ref):
        return _FakeImage(self, ref)

    def remove(self, ref, force=False):
        self.removed.append(ref)


class _FakeClient:
    def __init__(self, images):
        self.images = images


def _install(monkeypatch, images, mirrors=("mirror.example.com",)):
    import app.routers.images as images_mod

    monkeypatch.setattr(images_mod, "get_docker_client", lambda: _FakeClient(images))
    monkeypatch.setattr(images_mod, "get_settings", lambda: {"image_mirrors": list(mirrors)})
    return images


# ------------------------------------------------------------ pure helpers --


def test_is_docker_hub_ref():
    assert _is_docker_hub_ref("mysql")
    assert _is_docker_hub_ref("library/mysql")
    assert _is_docker_hub_ref("user/app")
    assert _is_docker_hub_ref("docker.io/library/mysql")
    # A first segment with a dot or colon is a registry host.
    assert not _is_docker_hub_ref("ghcr.io/foo/bar")
    assert not _is_docker_hub_ref("localhost:5000/foo")
    assert not _is_docker_hub_ref("quay.io/foo")


def test_hub_path_and_canonical():
    assert _hub_path("mysql") == "library/mysql"
    assert _hub_path("user/app") == "user/app"
    assert _hub_path("docker.io/mysql") == "library/mysql"

    # Official images should end up as the bare name users expect.
    assert _canonical("mysql") == "mysql"
    assert _canonical("library/mysql") == "mysql"
    assert _canonical("docker.io/library/mysql") == "mysql"
    assert _canonical("user/app") == "user/app"


def test_is_registry_unreachable():
    assert _is_registry_unreachable(UNREACHABLE)
    assert _is_registry_unreachable("dial tcp: i/o timeout")
    # A genuinely missing image must NOT be treated as a network problem.
    assert not _is_registry_unreachable("404 Client Error: pull access denied")
    assert not _is_registry_unreachable("manifest unknown")
    assert not _is_registry_unreachable("")


# ------------------------------------------------------------------ pull --


def test_pull_direct_success_does_not_touch_mirrors(monkeypatch):
    images = _install(monkeypatch, _FakeImages())

    r = c.post("/api/images/pull", json={"name": "mysql", "tag": "latest"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "direct"
    assert body["image"] == "mysql:latest"
    assert images.pull_calls == ["mysql:latest"], "mirror should not be used"


def test_pull_falls_back_to_mirror_and_retags(monkeypatch):
    images = _install(monkeypatch, _FakeImages(fail_on={"mysql": UNREACHABLE}))

    r = c.post("/api/images/pull", json={"name": "mysql", "tag": "latest"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "mirror.example.com"
    assert body["image"] == "mysql:latest", "must be usable under the canonical name"

    assert images.pull_calls == [
        "mysql:latest",
        "mirror.example.com/library/mysql:latest",
    ]
    # Re-tagged so `docker run mysql` works...
    assert "mysql:latest" in images.tags
    # ...and the mirror-specific tag was cleaned up.
    assert "mirror.example.com/library/mysql:latest" in images.removed


def test_pull_tries_every_mirror_in_order(monkeypatch):
    images = _install(
        monkeypatch,
        _FakeImages(
            fail_on={"mysql": UNREACHABLE, "bad.example.com/library/mysql": "i/o timeout"}
        ),
        mirrors=("bad.example.com", "good.example.com"),
    )

    r = c.post("/api/images/pull", json={"name": "mysql"})
    assert r.status_code == 200
    assert r.json()["source"] == "good.example.com"
    assert images.pull_calls == [
        "mysql:latest",
        "bad.example.com/library/mysql:latest",
        "good.example.com/library/mysql:latest",
    ]


def test_pull_missing_image_is_not_retried_on_mirrors(monkeypatch):
    """Only network failures should trigger the mirror path."""
    images = _install(
        monkeypatch,
        _FakeImages(fail_on={"nosuchimage": "404 Client Error: pull access denied"}),
    )

    r = c.post("/api/images/pull", json={"name": "nosuchimage"})
    assert r.status_code == 500
    assert images.pull_calls == ["nosuchimage:latest"], "must not hit a mirror"


def test_pull_unreachable_non_hub_registry_reports_clearly(monkeypatch):
    images = _install(monkeypatch, _FakeImages(fail_on={"ghcr.io/foo/bar": UNREACHABLE}))

    r = c.post("/api/images/pull", json={"name": "ghcr.io/foo/bar"})
    assert r.status_code == 502
    assert "镜像源" in r.json()["detail"]
    assert images.pull_calls == ["ghcr.io/foo/bar:latest"], "no mirror for non-Hub refs"


def test_pull_all_mirrors_failing_reports_every_attempt(monkeypatch):
    _install(
        monkeypatch,
        _FakeImages(
            fail_on={
                "mysql": UNREACHABLE,
                "a.example.com/library/mysql": "dial tcp: i/o timeout",
                "b.example.com/library/mysql": "connection refused",
            }
        ),
        mirrors=("a.example.com", "b.example.com"),
    )

    r = c.post("/api/images/pull", json={"name": "mysql"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "a.example.com" in detail and "b.example.com" in detail
    assert "IMAGE_MIRRORS" in detail


def test_pull_rejects_empty_name(monkeypatch):
    _install(monkeypatch, _FakeImages())
    r = c.post("/api/images/pull", json={"name": "   "})
    assert r.status_code == 400
