"""Cross-site request guards.

The panel has no login and is meant to be bound to 127.0.0.1 - but that does
NOT make it safe against a malicious web page. Any site the user visits can make
the browser send requests *from* 127.0.0.1: a cross-site form/fetch for HTTP,
and a raw WebSocket handshake for ``/ws/*`` (the same-origin policy does not
cover WebSockets at all). The request really does originate from the user's own
machine, so a localhost bind cannot tell it apart from the real UI.

What *can* tell them apart is the ``Origin`` header. Browsers attach it to
exactly the requests that matter here - every WebSocket handshake, and
cross-site unsafe methods - and a page on ``evil.example`` cannot forge it.

Policy
------
* No ``Origin`` header -> allow. Non-browser clients (curl, verification
  scripts, the test client) do not send one, and they are not the threat being
  guarded against.
* ``Origin`` host is localhost / 127.0.0.1 / [::1] -> allow (the panel's own
  UI, whichever port the browser used to reach it). ``0.0.0.0`` is deliberately
  NOT in that set: spec.md requires the panel to be reachable only on
  ``127.0.0.1:8088`` and forbids exposing the backend on 0.0.0.0, and
  deploy/docker-compose.yml only `expose`s the backend, so a browser can never
  legitimately be at ``http://0.0.0.0:8088``.
* ``Origin`` host equals the request's ``Host`` -> allow (same-origin; covers an
  operator who deliberately exposes the panel under another hostname).
* Anything else -> reject.
"""

from urllib.parse import urlsplit

LOCAL_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def host_of(value: str | None) -> str | None:
    """Extract the host part of either an Origin URL or a bare Host header."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if "://" in value:
        try:
            return (urlsplit(value).hostname or "").lower() or None
        except ValueError:
            return None
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1].lower() if end != -1 else value.lower()
    return (value.rsplit(":", 1)[0] if ":" in value else value).lower()


def is_same_site(origin: str | None, host: str | None) -> bool:
    """True when a browser-originated request may proceed (see module docstring)."""
    origin_host = host_of(origin)
    if origin_host is None:
        return True
    if origin_host in LOCAL_ORIGIN_HOSTS:
        return True
    request_host = host_of(host)
    return request_host is not None and origin_host == request_host
