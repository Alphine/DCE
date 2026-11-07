"""DCE_TRUSTED_PROXIES: client IP resolution and its effect on the login rate limit (docs/api.md section 9)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.clientip import resolve_client_ip
from app.config import Settings, parse_trusted_proxies
from tests.conftest import PASSWORD, Env

TRUSTED = parse_trusted_proxies("10.0.0.1, 192.168.0.0/16")


# --- Unit tests for the resolver --------------------------------------------------------------------------------

def test_empty_list_ignores_forwarded_for() -> None:
    assert resolve_client_ip("203.0.113.9", "198.51.100.7", ()) == "203.0.113.9"


def test_untrusted_peer_spoofing_forwarded_for_is_ignored() -> None:
    assert resolve_client_ip("203.0.113.9", "198.51.100.7", TRUSTED) == "203.0.113.9"


def test_trusted_peer_uses_rightmost_untrusted_entry() -> None:
    xff = "198.51.100.7, 203.0.113.50, 10.0.0.1"
    assert resolve_client_ip("10.0.0.1", xff, TRUSTED) == "203.0.113.50"


def test_trusted_cidr_hops_are_skipped() -> None:
    xff = "198.51.100.7, 192.168.5.4"
    assert resolve_client_ip("10.0.0.1", xff, TRUSTED) == "198.51.100.7"


def test_all_entries_trusted_returns_leftmost() -> None:
    assert resolve_client_ip("10.0.0.1", "192.168.1.1, 10.0.0.1", TRUSTED) == "192.168.1.1"


def test_malformed_rightmost_entry_falls_back_to_peer() -> None:
    assert resolve_client_ip("10.0.0.1", "198.51.100.7, not-an-ip", TRUSTED) == "10.0.0.1"


def test_missing_forwarded_for_uses_peer() -> None:
    assert resolve_client_ip("10.0.0.1", None, TRUSTED) == "10.0.0.1"
    assert resolve_client_ip("10.0.0.1", " , ", TRUSTED) == "10.0.0.1"


def test_missing_peer_is_unknown() -> None:
    assert resolve_client_ip(None, None, TRUSTED) == "unknown"


def test_ipv6_trusted_range() -> None:
    trusted = parse_trusted_proxies("2001:db8::/32")
    assert resolve_client_ip("2001:db8::5", "198.51.100.7", trusted) == "198.51.100.7"


def test_malformed_setting_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, trusted_proxies="10.0.0.1, not-a-network")


def test_default_setting_is_empty() -> None:
    assert Settings(_env_file=None, trusted_proxies="").trusted_proxy_networks == ()


# --- Integration: the login limiter keys on the resolved address ----------------------------------------------

@contextmanager
def _peer(env: Env, peer: str) -> Iterator[TestClient]:
    """One client per peer address. The lifespan runs once per client, so the limiter state is kept for the test."""
    with TestClient(env.app, base_url="http://testserver", client=(peer, 40000)) as client:
        yield client


def _login(client: TestClient, forwarded_for: str | None, password: str = "wrong-password-1") -> int:
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    response = client.post("/api/auth/login", json={"username": "admin", "password": password}, headers=headers)
    return response.status_code


def test_spoofed_forwarded_for_from_untrusted_peer_does_not_bypass_limit(
        make_env: Callable[..., Env]) -> None:
    env = make_env(trusted_proxies="10.0.0.1")
    with _peer(env, "203.0.113.9") as client:
        codes = [_login(client, f"198.51.100.{i}") for i in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429  # every attempt counted against the real peer, whatever XFF claimed


def test_trusted_peer_with_forwarded_for_limits_the_client_ip(make_env: Callable[..., Env]) -> None:
    env = make_env(trusted_proxies="10.0.0.1")
    with _peer(env, "10.0.0.1") as client:
        assert [_login(client, "198.51.100.7") for _ in range(10)] == [401] * 10
        assert _login(client, "198.51.100.7") == 429
        # A different client behind the same trusted proxy has its own budget.
        assert _login(client, "198.51.100.8") == 401


def test_empty_trusted_list_ignores_forwarded_for_in_login(make_env: Callable[..., Env]) -> None:
    env = make_env()  # DCE_TRUSTED_PROXIES defaults to empty
    with _peer(env, "10.0.0.1") as client:
        codes = [_login(client, f"198.51.100.{i}") for i in range(11)]
    assert codes[10] == 429


def test_trusted_peer_correct_password_still_logs_in(make_env: Callable[..., Env]) -> None:
    env = make_env(trusted_proxies="10.0.0.1")
    with _peer(env, "10.0.0.1") as client:
        assert _login(client, "198.51.100.7", password=PASSWORD) == 200
