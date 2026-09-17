"""Safety guards shared by software-only rehearsal scripts."""

from __future__ import annotations

from urllib.parse import urlsplit

LOCAL_REHEARSAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_allowed_loopback_server_url(value: str) -> bool:
    """Return whether *value* is an HTTP URL to an exact loopback host.

    Rehearsals send credential-bearing requests, so this guard intentionally
    rejects user-info, query/fragment, and path-bearing URLs as well as
    lookalike hostnames. Production ServerClient URLs are not constrained by
    this test-only policy.
    """

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False

    return (
        parsed.scheme.lower() == "http"
        and hostname is not None
        and hostname.lower() in LOCAL_REHEARSAL_HOSTS
        and (port is None or 0 <= port <= 65535)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
    )
