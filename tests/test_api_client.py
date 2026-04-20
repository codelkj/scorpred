"""Tests for API client suppression and rate-limit recovery behavior."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.trust_env = False
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def _reset_api_client_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api_client, "API_KEY", "test-key")
    monkeypatch.setattr(api_client, "CACHE_DIR", tmp_path)
    api_client._memory_cache.clear()
    api_client._FORBIDDEN_ENDPOINTS.clear()
    api_client._RATE_LIMITED_ENDPOINTS.clear()


def test_api_get_skips_rate_limited_endpoint_during_cooldown(tmp_path, monkeypatch):
    _reset_api_client_state(tmp_path, monkeypatch)

    class _NoNetworkSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            raise AssertionError("network call should be suppressed during cooldown")

    api_client._RATE_LIMITED_ENDPOINTS["injuries"] = time.time() + 60
    monkeypatch.setattr(api_client.requests, "Session", lambda: _NoNetworkSession())

    result = api_client.api_get("injuries", {"team": 10, "league": 39, "season": 2026})

    assert result["status"] == "fail"
    assert result["rate_limited"] is True


def test_api_get_sets_endpoint_cooldown_after_429(tmp_path, monkeypatch):
    _reset_api_client_state(tmp_path, monkeypatch)
    session = _FakeSession(_FakeResponse(429))
    monkeypatch.setattr(api_client.requests, "Session", lambda: session)

    before = time.time()
    result = api_client.api_get("injuries", {"team": 10, "league": 39, "season": 2026})

    assert result["status"] == "fail"
    assert result["rate_limited"] is True
    assert session.calls == 1
    assert api_client._RATE_LIMITED_ENDPOINTS["injuries"] >= before
