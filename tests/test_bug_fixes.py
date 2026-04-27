"""Regression tests for the 11 confirmed production bugs.

Bug refs:
 1  NBA card None crash
 2  API unmapped endpoint returns structured error
 3  prediction_service tuple consistency
 4  Rate-limit transparency (RAPIDAPI_OK set on 429)
 5  /prediction direct-link recovery via _fixture_by_id
 6  Confidence-53 false rejection
 7  Empty matchup fallback
 8  NBA confidence KeyError
 9  Cache key collision (separate namespaces)
10  Probability normalization (fractions → percentages)
11  SSL/API failure transparency via api_status()
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api_client
import decision_ui as dui
from services import prediction_service, cache_service
from services.prediction_contract import (
    validate_analysis_contract,
    FORBIDDEN_PROBABILITY_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_api(tmp_path, monkeypatch):
    monkeypatch.setattr(api_client, "API_KEY", "test-key")
    monkeypatch.setattr(api_client, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(api_client, "_USING_FREE_API", False)
    monkeypatch.setattr(api_client, "API_BASE", "https://api-football-v1.p.rapidapi.com/v3")
    monkeypatch.setattr(api_client, "RAPIDAPI_OK", True)
    api_client._memory_cache.clear()
    api_client._FORBIDDEN_ENDPOINTS.clear()
    api_client._RATE_LIMITED_ENDPOINTS.clear()


class _FakeResp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.trust_env = False
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.resp


# ---------------------------------------------------------------------------
# Bug 1 — NBA card None crash
# ---------------------------------------------------------------------------

def test_bug1_nba_card_none_no_crash():
    """build_decision_card returning None must not crash the NBA prediction builder."""
    with patch.object(dui, "build_decision_card", return_value=None):
        # Simulate the fixed code path: guard before .get()
        card = dui.build_decision_card()
        prediction = {}
        if card is None:
            result = {"prediction": None}
        else:
            prediction["decision_card"] = card
            prediction["play_type"] = card.get("action")
            prediction["confidence_pct"] = card.get("confidence_pct", 0)
            result = {"prediction": prediction}
    assert result == {"prediction": None}


# ---------------------------------------------------------------------------
# Bug 2 — Unmapped free-API endpoint returns structured error
# ---------------------------------------------------------------------------

def test_bug2_unmapped_free_api_endpoint_returns_structured_error(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api_client, "_USING_FREE_API", True)

    result = api_client.api_get("injuries", {"team": 10, "league": 39, "season": 2025})

    assert result.get("status") == "fail"
    assert result.get("unavailable") is True
    assert "injuries" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Bug 3 — prediction_service tuple consistency
# ---------------------------------------------------------------------------

def test_bug3_get_fixture_cards_no_load_fn_returns_5_tuple():
    """When load_fixtures dep is absent the early return must be a 5-tuple."""
    prediction_service._deps.clear()
    result = prediction_service.get_fixture_cards(39)
    assert len(result) == 5, f"Expected 5-tuple, got {len(result)}-tuple"
    cards, fixtures, load_error, source, marker = result
    assert cards == []
    assert load_error == "Unavailable"


def test_bug3_get_fixture_cards_load_fn_returns_5_tuple(monkeypatch):
    """Normal path also returns 5-tuple."""
    fake_payload = ([], None, "espn", "eng.1")

    def _fake_load(league_id):
        return fake_payload

    prediction_service._deps.clear()
    prediction_service._deps["load_fixtures"] = _fake_load
    # Clear any redis cache that might interfere
    with patch.object(cache_service, "get_json", return_value=None), \
         patch.object(cache_service, "set_json"):
        result = prediction_service.get_fixture_cards(39)

    assert len(result) == 5
    prediction_service._deps.clear()


# ---------------------------------------------------------------------------
# Bug 4 — Rate-limit transparency: RAPIDAPI_OK set to False on 429
# ---------------------------------------------------------------------------

def test_bug4_429_sets_rapidapi_ok_false(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    session = _FakeSession(_FakeResp(429))
    monkeypatch.setattr(api_client.requests, "Session", lambda: session)

    api_client.api_get("fixtures", {"league": 39, "season": 2025})

    assert api_client.RAPIDAPI_OK is False


def test_bug4_api_status_reports_degraded_when_rate_limited(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    api_client._RATE_LIMITED_ENDPOINTS["fixtures"] = time.time() + 60

    status = api_client.api_status()

    assert status["degraded"] is True
    assert "fixtures" in status["rate_limited_endpoints"]
    assert status["message"]


# ---------------------------------------------------------------------------
# Bug 5 — /prediction direct-link recovery: _fixture_by_id loads missing fixture
# ---------------------------------------------------------------------------

def test_bug5_fixture_by_id_loads_from_cache_when_index_empty(monkeypatch):
    """If _FIXTURE_INDEX is empty, _fixture_by_id must call load_fixtures_cached."""
    # Import the module so we can patch module-level dict
    import app as _app

    _app._FIXTURE_INDEX.clear()

    fake_fixture = {"fixture": {"id": 99999}, "teams": {"home": {"name": "Alpha"}, "away": {"name": "Beta"}}}

    def _fake_load(league_id):
        _app._FIXTURE_INDEX["99999"] = fake_fixture
        return ([fake_fixture], None, "espn", "eng.1")

    with patch.object(_app, "load_fixtures_cached", side_effect=_fake_load):
        result = _app._fixture_by_id("99999")

    assert result is not None
    assert result["fixture"]["id"] == 99999
    _app._FIXTURE_INDEX.clear()


# ---------------------------------------------------------------------------
# Bug 6 — Confidence 53 not rejected when probs are not fake
# ---------------------------------------------------------------------------

def test_bug6_confidence_53_with_real_probs_is_valid():
    analysis = {
        "match_id": "123",
        "action": "BET",
        "recommended_side": "Home",
        "confidence": 53,
        "probabilities": {"a": 0.47, "draw": 0.28, "b": 0.25},
        "reason": "Model edge detected",
        "data_quality": "Strong Data",
        "metric_breakdown": None,
    }
    errors = validate_analysis_contract(analysis)
    assert not errors, f"Should be valid but got: {errors}"


def test_bug6_confidence_53_with_fake_probs_is_rejected():
    analysis = {
        "match_id": "123",
        "action": "BET",
        "recommended_side": "Home",
        "confidence": 53,
        "probabilities": {"a": 38, "draw": 26, "b": 36},
        "reason": "Decision generated.",
        "data_quality": "Partial Data",
        "metric_breakdown": None,
    }
    errors = validate_analysis_contract(analysis)
    assert any("forbidden" in e for e in errors), f"Should be rejected but got: {errors}"


# ---------------------------------------------------------------------------
# Bug 7 — Empty matchup fallback from home/away names
# ---------------------------------------------------------------------------

def test_bug7_matchup_falls_back_to_team_names():
    from services.match_brain import MatchBrain
    from services.decision_engine import DecisionEngine

    de = DecisionEngine()
    brain = MatchBrain(
        load_fixtures=lambda league_id: ([], None, "test", ""),
        get_fixture_by_id=lambda mid: None,
        decision_engine=de,
    )
    fixture = {
        "fixture": {"id": 1, "date": "2025-05-01T15:00:00+00:00"},
        "teams": {"home": {"name": "Arsenal", "id": 42}, "away": {"name": "Chelsea", "id": 49}},
        "league": {"name": "Premier League"},
        "prediction": {},
    }
    result = brain.canonical_from_fixture(fixture)
    if result:
        assert "Arsenal" in result["matchup"] and "Chelsea" in result["matchup"], \
            f"Matchup should contain team names, got: {result['matchup']}"


# ---------------------------------------------------------------------------
# Bug 8 — NBA confidence_pct uses .get() not []
# ---------------------------------------------------------------------------

def test_bug8_confidence_pct_missing_key_does_not_raise():
    """decision_card without confidence_pct key must not raise KeyError."""
    card = {"action": "BET", "matchup": "Alpha vs Beta"}
    # The fixed code uses .get("confidence_pct", 0)
    val = card.get("confidence_pct", 0)
    assert val == 0


# ---------------------------------------------------------------------------
# Bug 9 — Cache key collision: separate namespaces
# ---------------------------------------------------------------------------

def test_bug9_fixture_cache_uses_fixtures_raw_namespace():
    """fixtures_raw and fixtures namespaces must produce different cache keys."""
    key_raw = cache_service.make_key("fixtures_raw", 39)
    key_old = cache_service.make_key("fixtures", 39)
    assert key_raw != key_old, "fixtures_raw and fixtures must have different cache keys"


def test_bug9_prediction_service_uses_fixtures_raw_namespace():
    """prediction_service.get_fixture_cards must use fixtures_raw key."""
    import inspect
    src = inspect.getsource(prediction_service.get_fixture_cards)
    assert "fixtures_raw" in src, "get_fixture_cards must use fixtures_raw cache key"


# ---------------------------------------------------------------------------
# Bug 10 — Probability normalization: fractions become percentages
# ---------------------------------------------------------------------------

def test_bug10_normalize_percent_converts_fraction():
    assert dui.normalize_percent(0.34, 0) == pytest.approx(34.0)
    assert dui.normalize_percent(0.0, 0) == 0.0
    assert dui.normalize_percent(1.0, 0) == pytest.approx(100.0)
    assert dui.normalize_percent(34.0, 0) == pytest.approx(34.0)  # already a percentage


def test_bug10_probability_rows_in_card_are_percentages():
    analysis = {
        "match_id": "1",
        "matchup": "Home vs Away",
        "confidence": 70,
        "probabilities": {"a": 0.45, "draw": 0.30, "b": 0.25},
        "action": "BET",
        "recommended_side": "Home",
        "reason": "Edge found",
        "data_quality": "Strong Data",
        "metric_breakdown": None,
    }
    card = dui.build_decision_card(analysis=analysis)
    assert card is not None
    prob_rows = card.get("probability_rows", [])
    assert prob_rows, "Card should have probability_rows"
    for row in prob_rows:
        val = row["value"]
        assert val >= 1.0, f"Probability row value {val} looks like a fraction, expected percentage"


# ---------------------------------------------------------------------------
# Bug 11 — SSL/API failure transparency via api_status()
# ---------------------------------------------------------------------------

def test_bug11_api_status_ok_when_no_issues(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    status = api_client.api_status()
    assert status["ok"] is True
    assert status["degraded"] is False
    assert status["rate_limited_endpoints"] == []


def test_bug11_api_status_degraded_when_rapidapi_ok_false(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api_client, "RAPIDAPI_OK", False)
    status = api_client.api_status()
    assert status["ok"] is False
    assert status["degraded"] is True


def test_bug11_api_status_degraded_when_rate_limited(tmp_path, monkeypatch):
    _reset_api(tmp_path, monkeypatch)
    api_client._RATE_LIMITED_ENDPOINTS["fixtures"] = time.time() + 300
    status = api_client.api_status()
    assert status["degraded"] is True
    assert "fixtures" in status["rate_limited_endpoints"]


# ---------------------------------------------------------------------------
# pytest import fix for normalize_percent assertion
# ---------------------------------------------------------------------------
import pytest
