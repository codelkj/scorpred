"""Tests for the football-data.org provider adapter."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import football_data_client as fdc


# ── Fixtures (sample payloads) ───────────────────────────────────────────────

_SCHEDULED_MATCH = {
    "id": 500001,
    "utcDate": "2026-05-03T14:00:00Z",
    "status": "SCHEDULED",
    "matchday": 36,
    "competition": {"id": 2021, "name": "Premier League", "code": "PL"},
    "season": {"id": 1564, "startDate": "2025-08-01", "endDate": "2026-05-31"},
    "homeTeam": {"id": 61, "name": "Chelsea FC", "shortName": "Chelsea", "crest": "https://crests.football-data.org/61.png"},
    "awayTeam": {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "crest": "https://crests.football-data.org/57.png"},
    "score": {
        "winner": None,
        "duration": "REGULAR",
        "fullTime": {"home": None, "away": None},
        "halfTime": {"home": None, "away": None},
    },
}

_FINISHED_MATCH = {
    "id": 400001,
    "utcDate": "2026-04-20T16:00:00Z",
    "status": "FINISHED",
    "matchday": 34,
    "competition": {"id": 2021, "name": "Premier League", "code": "PL"},
    "season": {"id": 1564, "startDate": "2025-08-01", "endDate": "2026-05-31"},
    "homeTeam": {"id": 65, "name": "Manchester City", "shortName": "Man City", "crest": "https://crests.football-data.org/65.png"},
    "awayTeam": {"id": 64, "name": "Liverpool FC", "shortName": "Liverpool", "crest": "https://crests.football-data.org/64.png"},
    "score": {
        "winner": "HOME_TEAM",
        "duration": "REGULAR",
        "fullTime": {"home": 2, "away": 1},
        "halfTime": {"home": 1, "away": 0},
    },
}

_POSTPONED_MATCH = {
    "id": 300001,
    "utcDate": "2026-04-15T19:45:00Z",
    "status": "POSTPONED",
    "matchday": 33,
    "competition": {"id": 2001, "name": "UEFA Champions League", "code": "CL"},
    "season": {"id": 1600, "startDate": "2025-07-01", "endDate": "2026-06-01"},
    "homeTeam": {"id": 86, "name": "Real Madrid CF", "shortName": "Real Madrid", "crest": ""},
    "awayTeam": {"id": 524, "name": "FC Barcelona", "shortName": "Barcelona", "crest": ""},
    "score": {
        "winner": None,
        "fullTime": {"home": None, "away": None},
    },
}


# ── Header tests ─────────────────────────────────────────────────────────────

def test_fdo_get_uses_x_auth_token_header(monkeypatch):
    """football-data.org requests must use X-Auth-Token, never RapidAPI headers."""
    captured_headers = {}

    class _FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"matches": []}

    class _FakeRequests:
        def get(self, url, *, headers, params, timeout, **_):
            captured_headers.update(headers)
            return _FakeResponse()

    monkeypatch.setattr(fdc, "FDO_KEY", "test-token-xyz")
    fdc._cache.clear()

    # Directly test headers by patching the requests import inside the module
    import unittest.mock as mock
    with mock.patch("requests.get") as mock_get:
        mock_get.return_value = _FakeResponse()
        monkeypatch.setattr(fdc, "FDO_KEY", "secret-token")
        fdc._cache.clear()
        fdc.fdo_get("competitions/PL/matches", {})
        assert mock_get.called
        call_kwargs = mock_get.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert "X-Auth-Token" in sent_headers
        assert sent_headers["X-Auth-Token"] == "secret-token"
        assert "X-RapidAPI-Key" not in sent_headers
        assert "x-apisports-key" not in sent_headers


# ── Normalize — scheduled match ───────────────────────────────────────────────

def test_normalize_scheduled_match_canonical_fields():
    """Scheduled match normalizes to canonical ScorPred shape."""
    result = fdc.normalize_match(_SCHEDULED_MATCH, league_id=39)

    # Top-level canonical fields
    assert result["match_id"] == "500001"
    assert result["home_team"]["name"] == "Chelsea FC"
    assert result["away_team"]["name"] == "Arsenal FC"
    assert result["kickoff"] == "2026-05-03T14:00:00Z"
    assert result["status"] == "scheduled"
    assert result["score"] == {"home": None, "away": None}
    assert result["winner"] is None
    assert result["competition"]["code"] == "PL"
    assert result["source"] == "football-data.org"


def test_normalize_scheduled_match_v3_compat():
    """Scheduled match must include v3-compatible fields for match_brain."""
    result = fdc.normalize_match(_SCHEDULED_MATCH, league_id=39)

    # v3 fixture block
    assert result["fixture"]["id"] == 500001
    assert result["fixture"]["status"]["short"] == "NS"
    assert result["fixture"]["date"] == "2026-05-03T14:00:00Z"

    # teams block
    assert result["teams"]["home"]["name"] == "Chelsea FC"
    assert result["teams"]["away"]["name"] == "Arsenal FC"

    # league block
    assert result["league"]["id"] == 39
    assert result["league"]["name"] == "Premier League"
    assert result["league"]["season"] == 2025
    assert "36" in result["league"]["round"]

    # goals block
    assert result["goals"] == {"home": None, "away": None}


def test_normalize_scheduled_match_marks_limited_data():
    """Scheduled match must mark prediction data as limited — no faked values."""
    result = fdc.normalize_match(_SCHEDULED_MATCH, league_id=39)
    pred = result["prediction"]

    assert pred["win_probabilities"] == {"a": None, "draw": None, "b": None}
    assert pred["confidence_pct"] is None
    assert pred["odds"] == {}
    dc = pred["data_completeness"]
    assert dc["tier"] == "limited"
    assert dc["prediction_source"] == "fixture/results only"
    assert "injuries" in dc["unavailable"]
    assert "odds" in dc["unavailable"]
    assert "win_probabilities" in dc["unavailable"]


# ── Normalize — completed match ───────────────────────────────────────────────

def test_normalize_completed_match_result():
    """Finished match must have status=completed and correct score/winner."""
    result = fdc.normalize_match(_FINISHED_MATCH, league_id=39)

    assert result["status"] == "completed"
    assert result["fixture"]["status"]["short"] == "FT"
    assert result["score"] == {"home": 2, "away": 1}
    assert result["winner"] == "home"
    assert result["goals"] == {"home": 2, "away": 1}


def test_normalize_completed_match_team_names():
    result = fdc.normalize_match(_FINISHED_MATCH, league_id=39)
    assert result["home_team"]["name"] == "Manchester City"
    assert result["away_team"]["name"] == "Liverpool FC"
    assert result["home_team"]["logo"] == "https://crests.football-data.org/65.png"


# ── Normalize — unavailable match ─────────────────────────────────────────────

def test_normalize_postponed_match_status():
    """POSTPONED/SUSPENDED/CANCELLED → status=unavailable."""
    result = fdc.normalize_match(_POSTPONED_MATCH, league_id=2)
    assert result["status"] == "unavailable"
    assert result["fixture"]["status"]["short"] == "PST"


def test_normalize_cancelled_status():
    match = {**_SCHEDULED_MATCH, "status": "CANCELLED", "id": 999}
    result = fdc.normalize_match(match, league_id=39)
    assert result["status"] == "unavailable"
    assert result["fixture"]["status"]["short"] == "CANC"


def test_normalize_suspended_status():
    match = {**_SCHEDULED_MATCH, "status": "SUSPENDED", "id": 998}
    result = fdc.normalize_match(match, league_id=39)
    assert result["status"] == "unavailable"
    assert result["fixture"]["status"]["short"] == "SUSP"


# ── Normalize — live match ─────────────────────────────────────────────────────

def test_normalize_in_play_status():
    match = {**_SCHEDULED_MATCH, "status": "IN_PLAY", "id": 997}
    result = fdc.normalize_match(match, league_id=39)
    assert result["status"] == "live"
    assert result["fixture"]["status"]["short"] == "1H"


def test_normalize_paused_status():
    match = {**_SCHEDULED_MATCH, "status": "PAUSED", "id": 996}
    result = fdc.normalize_match(match, league_id=39)
    assert result["status"] == "live"
    assert result["fixture"]["status"]["short"] == "HT"


# ── MatchBrain compatibility ──────────────────────────────────────────────────

def test_normalized_fixture_has_required_match_brain_fields():
    """match_brain.canonical_from_fixture reads specific keys — ensure they're present."""
    result = fdc.normalize_match(_SCHEDULED_MATCH, league_id=39)

    # canonical_from_fixture reads fixture.get("teams")
    assert "teams" in result
    assert "home" in result["teams"]
    assert "away" in result["teams"]
    assert result["teams"]["home"].get("name")

    # canonical_from_fixture reads (fixture.get("fixture") or {}).get("id")
    assert result["fixture"]["id"] == 500001

    # canonical_from_fixture reads fixture.get("prediction") → data_completeness
    assert "prediction" in result
    assert "data_completeness" in result["prediction"]


def test_unsupported_prediction_fields_do_not_crash_normalization():
    """Missing prediction-specific data must not raise exceptions."""
    minimal = {
        "id": 123456,
        "utcDate": "2026-06-01T15:00:00Z",
        "status": "SCHEDULED",
        "homeTeam": {"id": 1, "name": "Team A"},
        "awayTeam": {"id": 2, "name": "Team B"},
        "competition": {"id": 2021, "name": "Premier League", "code": "PL"},
        # deliberately omit: score, season, matchday, odds, etc.
    }
    result = fdc.normalize_match(minimal, league_id=39)
    assert result["match_id"] == "123456"
    assert result["home_team"]["name"] == "Team A"
    assert result["prediction"]["win_probabilities"] == {"a": None, "draw": None, "b": None}
    assert result["prediction"]["odds"] == {}


def test_normalize_empty_dict_returns_empty():
    result = fdc.normalize_match({}, league_id=39)
    assert result == {}


# ── League mapping ────────────────────────────────────────────────────────────

def test_league_to_fdo_code_covers_supported_leagues():
    """All app-supported league IDs must have a FDO competition code."""
    for league_id in [39, 140, 135, 78, 61, 2]:
        assert league_id in fdc._LEAGUE_TO_FDO_CODE, f"league_id {league_id} missing from FDO mapping"


def test_fdo_comp_id_resolves_to_app_league_id():
    """FDO competition numeric IDs must resolve back to app league IDs."""
    assert fdc._FDO_COMP_ID_TO_LEAGUE[2021] == 39   # PL
    assert fdc._FDO_COMP_ID_TO_LEAGUE[2001] == 2    # CL
    assert fdc._FDO_COMP_ID_TO_LEAGUE[2002] == 78   # BL1


def test_available_competitions_includes_spec_codes():
    """All competition codes from the spec must be present."""
    required = {"PL", "CL", "BL1", "DED", "BSA", "PD", "FL1", "ELC", "PPL", "SA"}
    assert required.issubset(fdc.AVAILABLE_COMPETITIONS.keys())


# ── Provider info ─────────────────────────────────────────────────────────────

def test_provider_info_structure():
    info = fdc.get_provider_info()
    assert info["provider"] == "football_data"
    assert info["base_url"] == fdc.FDO_BASE_URL
    assert isinstance(info["available_competitions"], list)
    assert isinstance(info["error_count"], int)
    assert "last_success" in info
    assert "rate_limited" in info


def test_is_available_requires_key(monkeypatch):
    monkeypatch.setattr(fdc, "FDO_KEY", "")
    monkeypatch.setattr(fdc, "_ACTIVE", True)
    assert fdc.is_available() is False


def test_is_available_with_key(monkeypatch):
    monkeypatch.setattr(fdc, "FDO_KEY", "some-key")
    monkeypatch.setattr(fdc, "_ACTIVE", True)
    assert fdc.is_available() is True
