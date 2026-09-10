"""Tests for creating a container from an image (POST /api/containers).

Covers both the free-text parsers and the endpoint's error handling.
"""
import pytest
from fastapi.testclient import TestClient
from docker.errors import ImageNotFound

from app.main import app
from app.services.run_spec import (
    build_run_kwargs,
    parse_env,
    parse_ports,
    parse_restart_policy,
    parse_volumes,
)

c = TestClient(app)


# ------------------------------------------------------------- port parser --


def test_parse_ports_forms():
    assert parse_ports("8080:80") == {"80/tcp": 8080}
    assert parse_ports("127.0.0.1:8080:80") == {"80/tcp": ("127.0.0.1", 8080)}
    # Host port omitted: publish on a random one.
    assert parse_ports("80") == {"80/tcp": None}
    assert parse_ports("53:53/udp") == {"53/udp": 53}


def test_parse_ports_separators():
    assert parse_ports("8080:80, 443:443") == {"80/tcp": 8080, "443/tcp": 443}
    assert parse_ports("\n8080:80\n\n443:443\n") == {"80/tcp": 8080, "443/tcp": 443}
    assert parse_ports("") == {}
    assert parse_ports(None) == {}


@pytest.mark.parametrize(
    "bad",
    [
        "abc:80",          # non-numeric
        "8080:99999",      # out of range
        "0:80",            # out of range
        "8080:80/xyz",     # unknown protocol
        "8080:80/tcp/udp", # malformed
        "1:2:3:4",         # too many segments
    ],
)
def test_parse_ports_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_ports(bad)


# -------------------------------------------------------------- env parser --


def test_parse_env():
    assert parse_env("A=1\nB=hello world") == ["A=1", "B=hello world"]
    assert parse_env("A=") == ["A="]
    # A value may contain '=' and commas.
    assert parse_env("URL=a=b,c") == ["URL=a=b,c"]


@pytest.mark.parametrize("bad", ["NOEQUALS", "1BAD=1", "=value", "A-B=1"])
def test_parse_env_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_env(bad)


# ---------------------------------------------------------- volume parser --


def test_parse_volumes():
    assert parse_volumes("/data:/var/lib/data") == {
        "/data": {"bind": "/var/lib/data", "mode": "rw"}
    }
    assert parse_volumes("/data:/var/lib/data:ro") == {
        "/data": {"bind": "/var/lib/data", "mode": "ro"}
    }
    # A named volume on the host side.
    assert parse_volumes("app-data:/var/lib/data") == {
        "app-data": {"bind": "/var/lib/data", "mode": "rw"}
    }


def test_parse_volumes_keeps_windows_drive_letter():
    """'D:\\data:/data' must not be split on the drive-letter colon."""
    assert parse_volumes(r"D:\data:/data") == {
        r"D:\data": {"bind": "/data", "mode": "rw"}
    }


@pytest.mark.parametrize("bad", ["/data", "/data:relative/path", ":/data", "/data:"])
def test_parse_volumes_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_volumes(bad)


# -------------------------------------------------------- restart policies --


def test_parse_restart_policy():
    assert parse_restart_policy("always") == {"Name": "always"}
    assert parse_restart_policy("unless-stopped") == {"Name": "unless-stopped"}
    assert parse_restart_policy("") is None
    assert parse_restart_policy(None) is None
    with pytest.raises(ValueError):
        parse_restart_policy("sometimes")


# ------------------------------------------------------------- kwargs glue --


def test_build_run_kwargs_minimal():
    assert build_run_kwargs(image="mysql") == {"image": "mysql"}


def test_build_run_kwargs_omits_blank_optionals():
    kwargs = build_run_kwargs(
        image="alpine", name="   ", ports="", env="\n\n", volumes=None, command="  "
    )
    assert kwargs == {"image": "alpine"}


def test_build_run_kwargs_full():
    kwargs = build_run_kwargs(
        image="mysql",
        name="db",
        ports="3306:3306",
        env="MYSQL_ROOT_PASSWORD=secret",
        volumes="/data/mysql:/var/lib/mysql",
        command="--default-authentication-plugin=mysql_native_password",
        restart_policy="unless-stopped",
    )
    assert kwargs["image"] == "mysql"
    assert kwargs["name"] == "db"
    assert kwargs["ports"] == {"3306/tcp": 3306}
    assert kwargs["environment"] == ["MYSQL_ROOT_PASSWORD=secret"]
    assert kwargs["volumes"] == {
        "/data/mysql": {"bind": "/var/lib/mysql", "mode": "rw"}
    }
    assert kwargs["command"].startswith("--default")
    assert kwargs["restart_policy"] == {"Name": "unless-stopped"}


def test_build_run_kwargs_rejects_empty_image():
    with pytest.raises(ValueError):
        build_run_kwargs(image="   ")


# ---------------------------------------------------------------- endpoint --


class _FakeCont:
    id = "new123"
    name = "db"
    image = None
    status = "running"
    ports = {"3306/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3306"}]}
    attrs = {"Created": "2026-01-01T00:00:00Z", "State": {"Status": "running"}}

    def reload(self):
        pass


class _FakeContainers:
    def __init__(self):
        self.run_calls = []
        self.create_calls = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)
        return _FakeCont()

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeCont()


class _FakeImages:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def get(self, ref):
        if ref in self.missing:
            raise ImageNotFound(ref)
        return object()


class _FakeClient:
    def __init__(self, containers, images):
        self.containers = containers
        self.images = images


def _install(monkeypatch, missing=()):
    import app.routers.containers as containers_mod

    conts = _FakeContainers()
    imgs = _FakeImages(missing)
    monkeypatch.setattr(
        containers_mod, "get_docker_client", lambda: _FakeClient(conts, imgs)
    )
    return conts


def test_create_container_starts_it_by_default(monkeypatch):
    conts = _install(monkeypatch)

    r = c.post(
        "/api/containers",
        json={"image": "mysql:latest", "name": "db", "ports": "3306:3306"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "db"
    assert body["state"] == "running"

    assert len(conts.run_calls) == 1, "auto_start should call containers.run"
    assert conts.create_calls == []
    kwargs = conts.run_calls[0]
    assert kwargs["image"] == "mysql:latest"
    assert kwargs["name"] == "db"
    assert kwargs["ports"] == {"3306/tcp": 3306}
    assert kwargs["detach"] is True


def test_create_container_can_skip_start(monkeypatch):
    conts = _install(monkeypatch)

    r = c.post("/api/containers", json={"image": "alpine", "auto_start": False})
    assert r.status_code == 200, r.text
    assert conts.run_calls == [], "auto_start=False must not start the container"
    assert len(conts.create_calls) == 1
    assert conts.create_calls[0]["detach"] is True


def test_create_container_missing_image_is_404(monkeypatch):
    _install(monkeypatch, missing=("nosuch:latest",))

    r = c.post("/api/containers", json={"image": "nosuch:latest"})
    assert r.status_code == 404
    assert "不存在" in r.json()["detail"]


def test_create_container_bad_ports_is_400(monkeypatch):
    conts = _install(monkeypatch)

    r = c.post("/api/containers", json={"image": "alpine", "ports": "not-a-port"})
    assert r.status_code == 400
    assert "端口" in r.json()["detail"]
    assert conts.run_calls == [], "invalid input must not reach the daemon"


def test_create_container_reports_port_conflict(monkeypatch):
    conts = _install(monkeypatch)

    def boom(**kwargs):
        raise RuntimeError(
            "500 Server Error: port is already allocated"
        )

    conts.run = boom

    r = c.post("/api/containers", json={"image": "alpine", "ports": "80:80"})
    assert r.status_code == 409
    assert "占用" in r.json()["detail"]


def test_create_container_reports_duplicate_name(monkeypatch):
    conts = _install(monkeypatch)

    def boom(**kwargs):
        raise RuntimeError(
            '409 Client Error: Conflict ("Conflict. The container name "/db" '
            'is already in use by container abc")'
        )

    conts.run = boom

    r = c.post("/api/containers", json={"image": "alpine", "name": "db"})
    assert r.status_code == 409
    assert "容器名" in r.json()["detail"]
