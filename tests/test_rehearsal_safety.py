from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

rehearsal_safety = importlib.import_module("rehearsal_safety")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://localhost:8080",
        "http://127.0.0.1",
        "http://127.0.0.1:8080",
        "http://[::1]",
        "http://[::1]:8080",
    ],
)
def test_loopback_rehearsal_urls_are_allowed(url: str) -> None:
    assert rehearsal_safety.is_allowed_loopback_server_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.example.com",
        "http://localhost@evil.example",
        "http://127.0.0.1.evil.example",
        "https://localhost",
        "http://example.com",
        "http://",
        "not a URL",
        "http://localhost:invalid",
        "http://user:password@localhost",
        "http://localhost?redirect=example.com",
    ],
)
def test_non_loopback_rehearsal_urls_are_rejected(url: str) -> None:
    assert not rehearsal_safety.is_allowed_loopback_server_url(url)


def test_invalid_rehearsal_url_is_rejected_before_http_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_mock = importlib.import_module("full_mock_e2e")
    client_creations: list[object] = []

    def unexpected_client_creation(*args: object, **kwargs: object) -> object:
        client_creations.append((args, kwargs))
        raise AssertionError("credential-bearing rehearsal client was created")

    monkeypatch.setenv("POPPY_E2E_SERVER_URL", "http://localhost@evil.example:8080")
    monkeypatch.setenv("POPPY_E2E_AGENT_TOKEN", "test-token-never-sent")
    monkeypatch.setattr(full_mock, "E2EHttpClient", unexpected_client_creation)

    with pytest.raises(full_mock.FullMockE2EError):
        full_mock.E2EConfig.from_environment()

    assert client_creations == []
