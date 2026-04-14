"""Season-consistency tests for NBA live client form helpers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import nba_live_client as nc


def _game(game_id: str, date_start: str) -> dict:
    return {
        "id": game_id,
        "date": {"start": date_start},
        "status": {"state": "post"},
        "teams": {
            "home": {"id": "1", "name": "Team A", "nickname": "A", "logo": ""},
            "visitors": {"id": "2", "name": "Team B", "nickname": "B", "logo": ""},
        },
        "scores": {
            "home": {"points": 110, "linescore": [25, 28, 29, 28]},
            "visitors": {"points": 101, "linescore": [22, 24, 26, 29]},
        },
        "records": {"home": [], "visitors": []},
    }


def test_get_team_recent_form_prefers_current_season_only(monkeypatch):
    def fake_completed(team_id: str, season: int):
        if season == 2026:
            return [_game("cur-1", "2026-04-01T19:00:00Z")]
        return [_game("old-1", "2025-03-01T19:00:00Z")]

    monkeypatch.setattr(nc, "_completed_team_games_for_season", fake_completed)

    rows = nc.get_team_recent_form("1", season=2026, n=5)

    assert len(rows) == 1
    assert rows[0]["id"] == "cur-1"


def test_recent_form_context_exposes_historical_when_current_missing(monkeypatch):
    def fake_completed(team_id: str, season: int):
        if season == 2026:
            return []
        if season == 2025:
            return [_game("old-1", "2025-03-01T19:00:00Z")]
        return []

    monkeypatch.setattr(nc, "_completed_team_games_for_season", fake_completed)

    context = nc.get_team_recent_form_context("1", season=2026, n=5, historical_lookback=2)

    assert context["current_games"] == []
    assert len(context["historical_games"]) == 1
    assert context["historical_season"] == 2025
    assert context["using_historical_context"] is True
