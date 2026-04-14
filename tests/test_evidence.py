"""Tests for fixture evidence loading cache behavior."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import evidence


class _DummyApi:
    FORCE_REFRESH = False

    def __init__(self):
        self.calls = {
            "get_upcoming_fixtures": 0,
            "get_standings": 0,
            "get_h2h": 0,
            "get_team_fixtures": 0,
            "get_injuries": 0,
        }

    def get_upcoming_fixtures(self, league, season, next_n=20):
        self.calls["get_upcoming_fixtures"] += 1
        return [
            {
                "fixture": {"id": 1, "date": "2026-04-15T19:00:00+00:00", "status": {"short": "NS"}, "venue": {"name": "A"}},
                "teams": {
                    "home": {"id": 10, "name": "Team A", "logo": ""},
                    "away": {"id": 20, "name": "Team B", "logo": ""},
                },
                "league": {"name": "Premier League", "round": "Round 1"},
            }
        ]

    def get_standings(self, league, season):
        self.calls["get_standings"] += 1
        return []

    def get_h2h(self, home_id, away_id, last=10):
        self.calls["get_h2h"] += 1
        return []

    def get_team_fixtures(self, team_id, league, season, last=10):
        self.calls["get_team_fixtures"] += 1
        return []

    def get_injuries(self, league, season, team_id):
        self.calls["get_injuries"] += 1
        return []


class _DummyPredictor:
    @staticmethod
    def filter_recent_completed_fixtures(rows, current_season=None, seasons_back=None):
        return rows or []

    @staticmethod
    def extract_form(rows, team_id):
        return []


class _DummyEngine:
    @staticmethod
    def build_opp_strengths_from_standings(rows):
        return {}

    @staticmethod
    def scorpred_predict(**kwargs):
        return {
            "confidence": "Low",
            "best_pick": {"prediction": "Draw", "team": "draw", "confidence": "Low", "reasoning": "test"},
            "win_probabilities": {"a": 33.3, "draw": 33.4, "b": 33.3},
            "home_pct": 33.3,
            "draw_pct": 33.4,
            "away_pct": 33.3,
        }


class _DummyLogger:
    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


def test_load_upcoming_fixtures_uses_short_ttl_cache(monkeypatch):
    evidence._UPCOMING_FIXTURE_CACHE.clear()

    api = _DummyApi()
    predictor = _DummyPredictor()
    engine = _DummyEngine()
    logger = _DummyLogger()

    first = evidence.load_upcoming_fixtures(
        api,
        predictor,
        engine,
        league=39,
        season=2026,
        logger=logger,
        football_data_source=lambda: "espn",
        next_n=6,
    )
    second = evidence.load_upcoming_fixtures(
        api,
        predictor,
        engine,
        league=39,
        season=2026,
        logger=logger,
        football_data_source=lambda: "espn",
        next_n=6,
    )

    assert first[0] and second[0]
    assert api.calls["get_upcoming_fixtures"] == 1
    assert api.calls["get_h2h"] == 1
    assert api.calls["get_team_fixtures"] == 2
    assert api.calls["get_injuries"] == 2


def test_load_upcoming_fixtures_bypasses_cache_on_force_refresh():
    evidence._UPCOMING_FIXTURE_CACHE.clear()

    api = _DummyApi()
    predictor = _DummyPredictor()
    engine = _DummyEngine()
    logger = _DummyLogger()

    evidence.load_upcoming_fixtures(
        api,
        predictor,
        engine,
        league=39,
        season=2026,
        logger=logger,
        football_data_source=lambda: "espn",
        next_n=6,
    )

    api.FORCE_REFRESH = True
    evidence.load_upcoming_fixtures(
        api,
        predictor,
        engine,
        league=39,
        season=2026,
        logger=logger,
        football_data_source=lambda: "espn",
        next_n=6,
    )

    assert api.calls["get_upcoming_fixtures"] == 2
