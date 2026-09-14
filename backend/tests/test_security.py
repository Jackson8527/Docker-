"""Unit tests for the cross-site guard.

The panel has no login and is reachable from any web page the user visits, so
this guard is what keeps a foreign page from driving the Docker socket.
"""
import pytest

from app.services.security import host_of, is_same_site


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("localhost", "localhost"),
        ("localhost:8088", "localhost"),
        ("127.0.0.1:8088", "127.0.0.1"),
        ("[::1]:8088", "[::1]"),
        ("http://127.0.0.1:8088", "127.0.0.1"),
        ("https://localhost", "localhost"),
        ("http://[::1]:8088", "::1"),
        ("http://evil.example", "evil.example"),
        ("evil.example", "evil.example"),
    ],
)
def test_host_of(value, expected):
    assert host_of(value) == expected


def test_missing_origin_is_allowed():
    """curl / scripts / the test client send no Origin and are not the threat."""
    assert is_same_site(None, "127.0.0.1:8088") is True


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:8088", "http://127.0.0.1:8088", "http://[::1]:8088"],
)
def test_local_origins_are_allowed(origin):
    assert is_same_site(origin, "127.0.0.1:8088") is True


def test_same_origin_host_is_allowed():
    """An operator exposing the panel under another name still works."""
    assert is_same_site("http://panel.lan:8088", "panel.lan:8088") is True


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "https://evil.example:8088",
        "http://127.0.0.1.evil.example",  # prefix lookalike must not pass
        "null",                            # sandboxed iframe / file:// pages
        "not a url",
    ],
)
def test_foreign_origins_are_rejected(origin):
    assert is_same_site(origin, "127.0.0.1:8088") is False


def test_zero_zero_zero_zero_is_not_a_local_origin():
    """0.0.0.0 is not a place a browser can legitimately be, so it is not local.

    spec.md requires the panel to be bound/reachable only on 127.0.0.1:8088 and
    forbids exposing the backend on 0.0.0.0; deploy/docker-compose.yml only
    `expose`s the backend. Keeping 0.0.0.0 in the localhost allowlist meant
    treating a deployment shape that must not exist as a trusted source.
    """
    assert is_same_site("http://0.0.0.0:8088", "127.0.0.1:8088") is False


def test_same_host_origin_still_covers_a_deliberate_zero_zero_zero_zero_bind():
    """If someone really serves the panel on 0.0.0.0, the same-origin branch
    (Origin host == Host) still lets their own UI through - just not as a
    'local' origin."""
    assert is_same_site("http://0.0.0.0:8088", "0.0.0.0:8088") is True
