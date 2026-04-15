"""
tests/test_routes.py — Flask route tests for ScorPred.

Run with:
    pytest tests/test_routes.py -v
"""

import json
import logging
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as flask_app_module
import security


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app_module.app.config["TESTING"] = True
    flask_app_module.app.config["SECRET_KEY"] = "test-secret"
    flask_app_module.app.config["WTF_CSRF_ENABLED"] = False
    security.reset_chat_rate_limits()
    with flask_app_module.app.test_client() as c:
        yield c


@pytest.fixture
def secure_client():
    flask_app_module.app.config["TESTING"] = True
    flask_app_module.app.config["SECRET_KEY"] = "test-secret"
    flask_app_module.app.config["WTF_CSRF_ENABLED"] = True
    flask_app_module.app.config["CHAT_RATE_LIMIT_COUNT"] = 2
    flask_app_module.app.config["CHAT_RATE_LIMIT_WINDOW_SECONDS"] = 60
    security.reset_chat_rate_limits()
    with flask_app_module.app.test_client() as c:
        yield c


def _mock_teams():
    return [
        {"team": {"id": 33, "name": "Manchester United", "logo": "https://example.com/manu.png"}},
        {"team": {"id": 40, "name": "Liverpool", "logo": "https://example.com/lfc.png"}},
    ]


def _mock_fixture():
    return {
        "fixture": {"id": 1, "date": "2025-04-10T15:00:00+00:00"},
        "teams": {
            "home": {"id": 33, "name": "Manchester United", "logo": ""},
            "away": {"id": 40, "name": "Liverpool", "logo": ""},
        },
        "goals": {"home": 2, "away": 1},
        "league": {"name": "Premier League", "id": 39},
    }


def _mock_nba_game(
    home_id: str = "1610612747",
    away_id: str = "1610612738",
    home_name: str = "Los Angeles Lakers",
    away_name: str = "Boston Celtics",
    home_nickname: str = "Lakers",
    away_nickname: str = "Celtics",
    home_pts: int = 112,
    away_pts: int = 107,
    date: str = "2026-04-21",
) -> dict:
    return {
        "id": f"{home_id}-{away_id}-{date}",
        "short_name": f"{away_nickname} @ {home_nickname}",
        "date": {"start": f"{date}T19:30:00Z"},
        "status": {
            "long": "Final",
            "short": "Final",
            "detail": "Final",
            "state": "post",
        },
        "venue": {"name": "Test Arena"},
        "teams": {
            "home": {
                "id": str(home_id),
                "name": home_name,
                "nickname": home_nickname,
                "city": home_name.replace(f" {home_nickname}", ""),
                "logo": "https://example.com/lakers.png",
            },
            "visitors": {
                "id": str(away_id),
                "name": away_name,
                "nickname": away_nickname,
                "city": away_name.replace(f" {away_nickname}", ""),
                "logo": "https://example.com/celtics.png",
            },
        },
        "scores": {
            "home": {"points": home_pts, "linescore": [28, 26, 29, 29]},
            "visitors": {"points": away_pts, "linescore": [25, 27, 26, 29]},
        },
        "leaders": {"home": [], "visitors": []},
        "records": {"home": [], "visitors": []},
        "broadcasts": [],
        "geo_broadcasts": [],
        "odds": {},
        "attendance": 19000,
        "summary_link": "",
        "is_live": False,
        "is_pre": False,
        "is_post": True,
    }


def _mock_nba_teams() -> list[dict]:
    return [
        {
            "id": "1610612747",
            "name": "Los Angeles Lakers",
            "nickname": "Lakers",
            "city": "Los Angeles",
            "logo": "https://example.com/lakers.png",
        },
        {
            "id": "1610612738",
            "name": "Boston Celtics",
            "nickname": "Celtics",
            "city": "Boston",
            "logo": "https://example.com/celtics.png",
        },
    ]


def _mock_nba_variant_teams() -> list[dict]:
    return [
        {"id": "200", "name": "Hornets", "nickname": "Hornets", "city": "Charlotte", "abbrev": "CHA", "logo": "https://example.com/hornets.png"},
        {"id": "201", "name": "Heat", "nickname": "Heat", "city": "Miami", "abbrev": "MIA", "logo": "https://example.com/heat.png"},
        {"id": "202", "name": "Clippers", "nickname": "Clippers", "city": "Los Angeles", "abbrev": "LAC", "logo": "https://example.com/clippers.png"},
        {"id": "203", "name": "Warriors", "nickname": "Warriors", "city": "Golden State", "abbrev": "GSW", "logo": "https://example.com/warriors.png"},
        {"id": "204", "name": "Knicks", "nickname": "Knicks", "city": "New York", "abbrev": "NYK", "logo": "https://example.com/knicks.png"},
        {"id": "205", "name": "Lakers", "nickname": "Lakers", "city": "Los Angeles", "abbrev": "LAL", "logo": "https://example.com/lakers.png"},
    ]


def _mock_nba_scorpred():
    return {
        "team_a_score": 6.8,
        "team_b_score": 5.4,
        "score_gap": 1.4,
        "win_probabilities": {"a": 62.0, "b": 38.0},
        "components_a": {
            "form": 6.7,
            "offense": 6.4,
            "defense": 6.1,
            "h2h": 5.8,
            "home_away": 6.5,
            "opp_strength": 5.7,
            "squad": 8.6,
            "match_context": 5.0,
        },
        "components_b": {
            "form": 5.4,
            "offense": 5.8,
            "defense": 5.6,
            "h2h": 5.1,
            "home_away": 4.7,
            "opp_strength": 6.0,
            "squad": 8.2,
            "match_context": 4.8,
        },
        "best_pick": {
            "prediction": "Lakers Win",
            "team": "A",
            "confidence": "High",
            "reasoning": "Stronger recent form and the home-court edge tilt the matchup.",
        },
        "key_edges": [
            {"team": "A", "team_name": "Lakers", "category": "Form", "margin": 1.3},
            {"team": "A", "team_name": "Lakers", "category": "Venue", "margin": 1.8},
        ],
        "matchup_reading": "Lakers hold the clearest overall edge thanks to better recent form and the venue boost.",
        "optional_picks": [
            {"market": "Total Points O/U 220", "lean": "Over", "reasoning": "Avg combined scoring: 224.4 pts/game"},
        ],
    }


def _mock_strategy_metrics() -> dict:
    return {
        "total_predictions": 28,
        "finalized_predictions": 20,
        "wins": 11,
        "losses": 9,
        "overall_accuracy": 55.0,
        "by_confidence": {
            "High": {"accuracy": 62.5, "count": 8, "wins": 5, "losses": 3},
            "Medium": {"accuracy": 50.0, "count": 8, "wins": 4, "losses": 4},
            "Low": {"accuracy": 50.0, "count": 4, "wins": 2, "losses": 2},
        },
        "by_sport": {
            "soccer": {"accuracy": 58.3, "count": 12, "wins": 7, "losses": 5},
            "nba": {"accuracy": 50.0, "count": 8, "wins": 4, "losses": 4},
        },
        "recent_predictions": [],
    }


def _mock_completed_prediction(
    team_a: str = "Arsenal",
    team_b: str = "Chelsea",
    overall_result: str = "Win",
    winner_hit: bool = True,
) -> dict:
    return {
        "team_a": team_a,
        "team_b": team_b,
        "date": "2026-04-10",
        "final_score_display": "2-1",
        "overall_game_result": overall_result,
        "winner_hit": winner_hit,
    }


# ── Home page ─────────────────────────────────────────────────────────────────

class TestIndexRoute:
    def test_index_returns_200(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()), \
             patch("api_client.get_upcoming_fixtures", return_value=[]), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/")
        assert rv.status_code == 200

    def test_index_contains_brand(self, client):
        with patch("api_client.get_teams", return_value=[]), \
             patch("api_client.get_upcoming_fixtures", return_value=[]), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/")
        assert b"ScorPred" in rv.data

    def test_index_handles_api_failure_gracefully(self, client):
        with patch("api_client.get_teams", side_effect=Exception("API down")), \
             patch("api_client.get_upcoming_fixtures", side_effect=Exception("API down")), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/")
        # Should not crash — should return 200 with partial content
        assert rv.status_code == 200


# ── Fixtures page ─────────────────────────────────────────────────────────────

class TestFixturesRoute:
    def test_fixtures_returns_200(self, client):
        with patch("api_client.get_upcoming_fixtures", return_value=[_mock_fixture()]), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/fixtures")
        assert rv.status_code == 200

    def test_fixtures_empty_list_still_200(self, client):
        with patch("api_client.get_upcoming_fixtures", return_value=[]), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/fixtures")
        assert rv.status_code == 200

    def test_fixtures_analysis_form_includes_csrf_token(self, client):
        with patch("api_client.get_upcoming_fixtures", return_value=[_mock_fixture()]), \
             patch("api_client.get_standings", return_value=[]):
            rv = client.get("/fixtures")
        assert rv.status_code == 200
        assert b'name="csrf_token"' in rv.data


# ── Select / team selection ───────────────────────────────────────────────────

class TestSelectRoute:
    def test_select_redirects_to_prediction(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": "40"})
        assert rv.status_code in (302, 303)
        assert "/prediction" in rv.headers.get("Location", "")

    def test_select_fixture_stores_selected_context(self, client):
        fixture_payload = {
            "team_a": "33",
            "team_b": "40",
            "team_a_name": "Manchester United",
            "team_a_logo": "https://example.com/manu.png",
            "team_b_name": "Liverpool",
            "team_b_logo": "https://example.com/lfc.png",
            "fixture_id": "9001",
            "fixture_date": "2026-04-21T19:45:00+00:00",
            "league_name": "Premier League",
            "round": "Matchday 33",
            "venue_name": "Old Trafford",
            "data_source": "configured",
        }

        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data=fixture_payload)

        assert rv.status_code in (302, 303)
        assert "/prediction" in rv.headers.get("Location", "")
        with client.session_transaction() as sess:
            assert sess["team_a_id"] == 33
            assert sess["team_b_id"] == 40
            assert sess["selected_fixture"]["id"] == "9001"
            assert sess["selected_fixture"]["venue_name"] == "Old Trafford"

    def test_select_same_team_redirects_to_soccer_with_notice(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": "33"})
        assert rv.status_code in (302, 303)
        assert "/soccer?selection_error=" in rv.headers.get("Location", "")

    def test_select_missing_team_redirects_to_soccer_with_notice(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": ""})
        assert rv.status_code in (302, 303)
        assert "/soccer?selection_error=" in rv.headers.get("Location", "")

    def test_select_no_teams_available_returns_error(self, client):
        with patch("api_client.get_teams", return_value=[]):
            rv = client.post("/select", data={"team_a": "33", "team_b": "40"})
        # Should return an error page (503) when no team data
        assert rv.status_code in (302, 503)


# ── Matchup page ──────────────────────────────────────────────────────────────

class TestMatchupRoute:
    def test_matchup_without_session_redirects(self, client):
        rv = client.get("/matchup")
        assert rv.status_code in (302, 303)

    def test_matchup_with_session_returns_200(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("api_client.get_h2h", return_value=[_mock_fixture()]), \
             patch("api_client.get_team_fixtures", return_value=[_mock_fixture()]), \
             patch("api_client.get_injuries", return_value=[]), \
             patch("api_client.enrich_fixture", return_value={**_mock_fixture(), "events": [], "stats": []}):
            rv = client.get("/matchup")
        assert rv.status_code == 200


# ── Prediction page ───────────────────────────────────────────────────────────

class TestPredictionRoute:
    def test_prediction_without_session_redirects_to_soccer(self, client):
        rv = client.get("/prediction")
        assert rv.status_code in (302, 303)
        assert "/soccer?selection_error=" in rv.headers.get("Location", "")

    def test_prediction_with_session_returns_200(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        fixtures = [_mock_fixture()]
        with patch("api_client.get_h2h", return_value=fixtures), \
             patch("api_client.get_team_fixtures", return_value=fixtures), \
             patch("api_client.get_injuries", return_value=[]), \
             patch("api_client.get_squad", return_value=[]):
            rv = client.get("/prediction")
        assert rv.status_code == 200

    def test_prediction_tracks_selected_fixture_date(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""
            sess["selected_fixture"] = {
                "date": "2026-04-21T19:45:00+00:00",
                "data_source": "configured",
            }

        fixtures = [_mock_fixture()]
        with patch("api_client.get_h2h", return_value=fixtures), \
             patch("api_client.get_team_fixtures", return_value=fixtures), \
             patch("api_client.get_injuries", return_value=[]), \
             patch("api_client.get_squad", return_value=[]), \
             patch("model_tracker.save_prediction") as mock_save:
            rv = client.get("/prediction")

        assert rv.status_code == 200
        assert mock_save.call_count == 1
        assert mock_save.call_args.kwargs["game_date"] == "2026-04-21T19:45:00+00:00"


class TestNbaPredictionRoute:
    def test_nba_prediction_without_session_redirects_to_nba_index(self, client):
        rv = client.get("/nba/prediction")
        assert rv.status_code in (302, 303)
        assert "/nba/?selection_error=" in rv.headers.get("Location", "")

    def test_nba_select_game_redirects_to_prediction_and_stores_context(self, client):
        live_game = _mock_nba_game(date="2026-04-21")
        home = live_game["teams"]["home"]
        away = live_game["teams"]["visitors"]

        with patch("nba_live_client.get_teams", return_value=_mock_nba_teams()):
            rv = client.post(
                "/nba/select-game",
                data={
                    "team_a": home["id"],
                    "team_b": away["id"],
                    "team_a_name": home["name"],
                    "team_a_logo": home["logo"],
                    "team_b_name": away["name"],
                    "team_b_logo": away["logo"],
                    "event_id": live_game["id"],
                    "event_date": live_game["date"]["start"],
                    "event_status": live_game["status"]["long"],
                    "venue_name": live_game["venue"]["name"],
                    "short_name": live_game["short_name"],
                },
            )

        assert rv.status_code in (302, 303)
        assert "/nba/prediction" in rv.headers.get("Location", "")
        with client.session_transaction() as sess:
            assert sess["nba_team_a_id"] == home["id"]
            assert sess["nba_team_b_id"] == away["id"]
            assert sess["nba_selected_game"]["event_id"] == live_game["id"]
            assert sess["nba_selected_game"]["venue_name"] == "Test Arena"

    def test_nba_select_game_missing_context_redirects_with_notice(self, client):
        with patch("nba_live_client.get_teams", return_value=_mock_nba_teams()):
            rv = client.post("/nba/select-game", data={"team_a": "1610612747", "team_b": ""})

        assert rv.status_code in (302, 303)
        assert "/nba/?selection_error=" in rv.headers.get("Location", "")

    def test_nba_select_game_uses_payload_fallback_when_team_directory_is_empty(self, client):
        with patch("nba_live_client.get_teams", return_value=[]):
            rv = client.post(
                "/nba/select-game",
                data={
                    "team_a": "30",
                    "team_b": "14",
                    "team_a_name": "Charlotte Hornets",
                    "team_a_logo": "https://example.com/hornets.png",
                    "team_b_name": "Miami Heat",
                    "team_b_logo": "https://example.com/heat.png",
                    "event_id": "401866755",
                    "event_date": "2026-04-14T23:30:00Z",
                    "event_status": "Scheduled",
                    "venue_name": "Spectrum Center",
                    "short_name": "MIA @ CHA",
                },
            )

        assert rv.status_code in (302, 303)
        assert "/nba/prediction" in rv.headers.get("Location", "")
        with client.session_transaction() as sess:
            assert sess["nba_team_a_id"] == "30"
            assert sess["nba_team_a_name"] == "Charlotte Hornets"
            assert sess["nba_team_a_nickname"] == "Hornets"
            assert sess["nba_team_a_city"] == "Charlotte"
            assert sess["nba_team_b_id"] == "14"
            assert sess["nba_team_b_name"] == "Miami Heat"
            assert sess["nba_team_b_nickname"] == "Heat"
            assert sess["nba_team_b_city"] == "Miami"
            assert sess["nba_selected_game"]["event_id"] == "401866755"

    @pytest.mark.parametrize(
        ("home_name", "away_name", "expected_home", "expected_away"),
        [
            ("Charlotte Hornets", "Miami Heat", "Hornets", "Heat"),
            ("LA Clippers", "Golden State Warriors", "Clippers", "Warriors"),
            ("New York Knicks", "Los Angeles Lakers", "Knicks", "Lakers"),
        ],
    )
    def test_nba_select_game_matches_canonical_names_when_ids_do_not_align(
        self,
        client,
        home_name,
        away_name,
        expected_home,
        expected_away,
    ):
        with patch("nba_live_client.get_teams", return_value=_mock_nba_variant_teams()):
            rv = client.post(
                "/nba/select-game",
                data={
                    "team_a": "espn-home-id",
                    "team_b": "espn-away-id",
                    "team_a_name": home_name,
                    "team_b_name": away_name,
                    "event_id": "401866755",
                    "event_date": "2026-04-14T23:30:00Z",
                    "event_status": "Scheduled",
                    "venue_name": "Test Arena",
                    "short_name": "TEST @ TEST",
                },
            )

        assert rv.status_code in (302, 303)
        assert "/nba/prediction" in rv.headers.get("Location", "")
        with client.session_transaction() as sess:
            assert sess["nba_team_a_name"] == expected_home
            assert sess["nba_team_b_name"] == expected_away
            assert sess["nba_selected_game"]["event_id"] == "401866755"

    def test_nba_select_game_logs_exact_mismatch_details(self, client, caplog):
        caplog.set_level(logging.INFO)

        with patch("nba_live_client.get_teams", return_value=_mock_nba_variant_teams()):
            rv = client.post(
                "/nba/select-game",
                data={
                    "team_a": "espn-home-id",
                    "team_b": "espn-away-id",
                    "team_a_name": "Seattle Supersonics",
                    "team_b_name": "Miami Heat",
                    "event_id": "401866756",
                },
            )

        assert rv.status_code in (302, 303)
        assert "/nba/?selection_error=" in rv.headers.get("Location", "")
        assert "selected_home='Seattle Supersonics'" in caplog.text
        assert "selected_away='Miami Heat'" in caplog.text
        assert "normalized_selected={'home': 'seattle supersonics', 'away': 'heat'}" in caplog.text
        assert "available_team_names=['Hornets', 'Heat', 'Clippers', 'Warriors', 'Knicks', 'Lakers']" in caplog.text
        assert "failure_reason=home=no canonical match for seattle supersonics; away=matched by canonical name heat" in caplog.text

    def test_nba_prediction_renders_current_payload(self, client):
        with client.session_transaction() as sess:
            sess["nba_team_a_id"] = "1610612747"
            sess["nba_team_a_name"] = "Los Angeles Lakers"
            sess["nba_team_a_logo"] = "https://example.com/lakers.png"
            sess["nba_team_a_nickname"] = "Lakers"
            sess["nba_team_a_city"] = "Los Angeles"
            sess["nba_team_b_id"] = "1610612738"
            sess["nba_team_b_name"] = "Boston Celtics"
            sess["nba_team_b_logo"] = "https://example.com/celtics.png"
            sess["nba_team_b_nickname"] = "Celtics"
            sess["nba_team_b_city"] = "Boston"
            sess["nba_selected_game"] = {
                "event_id": "401000001",
                "date": "2026-04-21T19:30:00Z",
                "status": "Scheduled",
                "venue_name": "Test Arena",
                "short_name": "Celtics @ Lakers",
            }

        home_game = _mock_nba_game()
        away_game = _mock_nba_game(
            home_id="1610612738",
            away_id="1610612747",
            home_name="Boston Celtics",
            away_name="Los Angeles Lakers",
            home_nickname="Celtics",
            away_nickname="Lakers",
            home_pts=107,
            away_pts=112,
            date="2026-04-18",
        )
        stats_a = {
            "wins": 50,
            "losses": 28,
            "ppg": 118.4,
            "opp_ppg": 112.1,
            "net_rtg": 6.3,
            "home_record": "29-10",
            "away_record": "21-18",
            "last10": "7-3",
            "streak": "W3",
        }
        stats_b = {
            "wins": 54,
            "losses": 24,
            "ppg": 117.2,
            "opp_ppg": 109.8,
            "net_rtg": 7.4,
            "home_record": "31-8",
            "away_record": "23-16",
            "last10": "6-4",
            "streak": "L1",
        }

        with patch("nba_live_client.get_event_snapshot", return_value=home_game), \
             patch("nba_live_client.get_h2h", return_value=[home_game, away_game]), \
             patch("nba_live_client.get_team_recent_form_context", side_effect=[
                 {"current_games": [home_game, away_game], "historical_games": [], "using_historical_context": False},
                 {"current_games": [away_game, home_game], "historical_games": [], "using_historical_context": False},
             ]), \
             patch("nba_live_client.get_team_injuries", side_effect=[[], []]), \
             patch("nba_live_client.get_team_season_stats", side_effect=[stats_a, stats_b]), \
             patch("nba_live_client.get_standings", return_value={"west": [{"team": {"name": "Lakers"}, "rank": 3}], "east": [{"team": {"name": "Celtics"}, "rank": 1}]}), \
             patch("scormastermind.predict_match", return_value={"ui_prediction": _mock_nba_scorpred()}), \
             patch("model_tracker.save_prediction") as mock_save:
            rv = client.get("/nba/prediction")

        assert rv.status_code == 200
        assert b"Match Winner Prediction" in rv.data
        assert b"Lakers Win" in rv.data
        assert b"Scorpred Engine Score" in rv.data
        assert b"Team Snapshot" in rv.data
        assert mock_save.call_count == 1
        assert mock_save.call_args.kwargs["game_date"] == "2026-04-21T19:30:00Z"

    def test_nba_index_never_renders_no_confidence_phrase(self, client):
        game = _mock_nba_game(date="2026-04-21")

        with patch("nba_live_client.get_teams", return_value=_mock_nba_teams()), \
             patch("nba_live_client.get_today_games", return_value=[]), \
             patch("nba_live_client.get_upcoming_games", return_value=[game]), \
             patch("nba_live_client.get_h2h", return_value=[]), \
             patch("nba_live_client.get_team_recent_form_context", return_value={"current_games": [], "using_historical_context": False}), \
             patch("nba_live_client.get_team_injuries", return_value=[]), \
             patch("nba_live_client.get_standings", return_value={}), \
             patch("scorpred_engine.scorpred_predict", return_value={
                 "best_pick": {"prediction": "Lakers Win", "team": "A"},
                 "win_probabilities": {"a": 51.0, "b": 49.0},
                 "prob_home": 51.0,
                 "prob_away": 49.0,
             }):
            rv = client.get("/nba/")

        assert rv.status_code == 200
        assert b"No confidence" not in rv.data
        assert b"Limited Data" in rv.data

    def test_nba_prediction_shows_limited_data_notice_when_current_season_is_sparse(self, client):
        with client.session_transaction() as sess:
            sess["nba_team_a_id"] = "1610612747"
            sess["nba_team_a_name"] = "Los Angeles Lakers"
            sess["nba_team_a_logo"] = "https://example.com/lakers.png"
            sess["nba_team_a_nickname"] = "Lakers"
            sess["nba_team_a_city"] = "Los Angeles"
            sess["nba_team_b_id"] = "1610612738"
            sess["nba_team_b_name"] = "Boston Celtics"
            sess["nba_team_b_logo"] = "https://example.com/celtics.png"
            sess["nba_team_b_nickname"] = "Celtics"
            sess["nba_team_b_city"] = "Boston"
            sess["nba_selected_game"] = {
                "event_id": "401000001",
                "date": "2026-04-21T19:30:00Z",
                "status": "Scheduled",
                "venue_name": "Test Arena",
                "short_name": "Celtics @ Lakers",
            }

        home_game = _mock_nba_game()

        with patch("nba_live_client.get_event_snapshot", return_value=home_game), \
             patch("nba_live_client.get_h2h", return_value=[]), \
             patch("nba_live_client.get_team_recent_form_context", side_effect=[
                 {"current_games": [], "historical_games": [home_game], "using_historical_context": True},
                 {"current_games": [], "historical_games": [home_game], "using_historical_context": True},
             ]), \
             patch("nba_live_client.get_team_injuries", side_effect=[[], []]), \
             patch("nba_live_client.get_team_season_stats", side_effect=[None, None]), \
             patch("nba_live_client.get_standings", return_value={}), \
             patch("scormastermind.predict_match", return_value={
                 "ui_prediction": {
                     "best_pick": {"prediction": "Lakers Win", "team": "A", "confidence": "Low", "reasoning": "Edge is thin."},
                     "win_probabilities": {"a": 51.0, "b": 49.0},
                     "score_gap": 0.4,
                     "components_a": {"form": 5, "offense": 5, "defense": 5, "h2h": 5, "home_away": 5, "opp_strength": 5, "squad": 5, "match_context": 5},
                     "components_b": {"form": 5, "offense": 5, "defense": 5, "h2h": 5, "home_away": 5, "opp_strength": 5, "squad": 5, "match_context": 5},
                     "team_a_score": 5.2,
                     "team_b_score": 5.0,
                     "key_edges": [],
                 }
             }), \
             patch("model_tracker.save_prediction"):
            rv = client.get("/nba/prediction")

        assert rv.status_code == 200
        assert b"Current-season data is limited for this matchup" in rv.data
        assert b"Historical context is shown where current-season coverage is incomplete" in rv.data


class TestStrategyLabRoute:
    def test_strategy_lab_renders_saved_ml_comparison(self, client, tmp_path, monkeypatch):
        report_path = tmp_path / "model_comparison.json"
        report_path.write_text(
            json.dumps(
                {
                    "best_model": "random_forest",
                    "generated_at": "2026-04-13T10:00:00Z",
                    "models": {
                        "logistic_regression": {
                            "accuracy": 0.482,
                            "top_features": [{"feature": "home_form_last_5"}],
                        },
                        "random_forest": {
                            "accuracy": 0.501,
                            "top_features": [
                                {"feature": "home_form_last_5"},
                                {"feature": "away_goals_conceded_last_5"},
                                {"feature": "strength_gap"},
                                {"feature": "league_draw_rate"},
                                {"feature": "recent_goal_trend"},
                            ],
                        },
                    },
                    "workflow": {
                        "train_size": 2800,
                        "test_size": 943,
                        "train_start": "2021-08-01",
                        "train_end": "2025-03-15",
                        "test_start": "2025-03-16",
                        "test_end": "2026-03-30",
                        "feature_keys": [
                            "home_form_last_5",
                            "away_goals_conceded_last_5",
                            "strength_gap",
                            "league_draw_rate",
                            "recent_goal_trend",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(flask_app_module.strategy_lab_services.mt, "get_summary_metrics", lambda: _mock_strategy_metrics())
        monkeypatch.setattr(
            flask_app_module.strategy_lab_services.mt,
            "get_completed_predictions",
            lambda limit=6: [_mock_completed_prediction()] * limit,
        )
        monkeypatch.setattr(flask_app_module.strategy_lab_services.mlp, "DEFAULT_REPORT_PATH", report_path)

        rv = client.get("/strategy-lab")

        assert rv.status_code == 200
        assert b"ML Model Comparison" in rv.data
        assert b"Best ML Model" in rv.data
        assert b"Baseline Logistic Regression" in rv.data
        assert b"Random Forest" in rv.data


class TestModelPerformanceRoute:
    def test_model_performance_renders_evaluation_sections(self, client, monkeypatch):
        monkeypatch.setattr(flask_app_module.mt, "get_summary_metrics", lambda: _mock_strategy_metrics())
        monkeypatch.setattr(flask_app_module.mt, "get_completed_predictions", lambda limit=50: [_mock_completed_prediction()] * min(limit, 3))
        monkeypatch.setattr(flask_app_module.mt, "get_pending_predictions", lambda limit=20: [])
        monkeypatch.setattr(
            flask_app_module.mt,
            "get_evaluation_dashboard",
            lambda rolling_window=10, strategy_reference=None: {
                "kpis": {
                    "overall_accuracy": 55.0,
                    "rolling_win_rate": 60.0,
                    "total_tracked_predictions": 28,
                    "finalized_predictions": 20,
                    "avoids_skipped": 2,
                    "current_best_strategy": "Combined",
                    "roi_or_points": 9,
                },
                "rolling_window": rolling_window,
                "series": {
                    "rolling_by_match": [{"label": "2026-04-01", "rolling_accuracy": 50.0}],
                    "rolling_by_day": [{"label": "2026-04-01", "rolling_accuracy": 50.0, "matches": 1}],
                    "cumulative_points": [{"label": "2026-04-01", "cumulative_points": 1, "delta": 1}],
                },
                "confidence_calibration": [{"bucket": "80-100", "sample_size": 1, "avg_confidence": 90.0, "actual_hit_rate": 100.0}],
                "strategy_comparison": [{"strategy": "Rule-Based", "accuracy": 55.0, "sample_size": 20}],
                "breakdowns": {
                    "by_sport": [{"sport": "soccer", "accuracy": 58.3, "count": 12, "wins": 7, "losses": 5}],
                    "by_confidence_tier": [{"tier": "High", "accuracy": 62.5, "count": 8, "wins": 5, "losses": 3}],
                    "by_predicted_outcome": [{"key": "A", "label": "Home", "count": 10, "wins": 6, "losses": 4, "accuracy": 60.0}],
                    "recent_form": {
                        "last_10": {"count": 10, "accuracy": 60.0},
                        "last_20": {"count": 20, "accuracy": 55.0},
                    },
                },
                "failure_rows": [
                    {
                        "date": "2026-04-02",
                        "sport": "SOCCER",
                        "matchup": "Liverpool vs Everton",
                        "predicted_outcome": "B",
                        "actual_result": "Liverpool",
                        "confidence": "Medium",
                        "confidence_pct": 61.0,
                        "recommendation": "Everton ML",
                        "notes": "Winner Pick: Miss",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            flask_app_module.strategy_lab_services,
            "build_strategy_lab_context",
            lambda: {
                "performance_comparison": {
                    "rule_accuracy": 55.0,
                    "ml_accuracy": 57.0,
                    "combined_accuracy": 59.0,
                    "evaluation_matches": 120,
                },
                "ml_comparison": {
                    "best_model_label": "Random Forest",
                    "baseline_logistic_accuracy": 52.0,
                    "random_forest_accuracy": 57.0,
                },
            },
        )

        rv = client.get("/model-performance")

        assert rv.status_code == 200
        assert b"Model Evaluation Dashboard" in rv.data
        assert b"Win Rate Over Time" in rv.data
        assert b"Confidence Calibration" in rv.data
        assert b"Strategy Comparison" in rv.data
        assert b"Failure Analysis" in rv.data

    def test_strategy_lab_renders_clean_fallback_without_report(self, client, tmp_path, monkeypatch):
        missing_path = tmp_path / "missing_model_comparison.json"
        missing_dataset = tmp_path / "missing_historical_matches.csv"

        monkeypatch.setattr(flask_app_module.strategy_lab_services.mt, "get_summary_metrics", lambda: _mock_strategy_metrics())
        monkeypatch.setattr(
            flask_app_module.strategy_lab_services.mt,
            "get_completed_predictions",
            lambda limit=6: [_mock_completed_prediction(winner_hit=False, overall_result="Loss")] * limit,
        )
        monkeypatch.setattr(flask_app_module.strategy_lab_services.mlp, "DEFAULT_REPORT_PATH", missing_path)
        monkeypatch.setattr(flask_app_module.strategy_lab_services, "_DEFAULT_DATASET", missing_dataset)

        rv = client.get("/strategy-lab")

        assert rv.status_code == 200
        assert b"ML comparison is not available yet" in rv.data
        assert b"Generating ML insights..." in rv.data
        assert str(missing_path).encode("utf-8") in rv.data

    def test_strategy_lab_auto_generates_ml_report_from_dataset(self, client, tmp_path, monkeypatch):
        report_path = tmp_path / "model_comparison.json"
        dataset_path = tmp_path / "historical_matches.csv"
        dataset_path.write_text(
            "\n".join(
                [
                    "date,home_team,away_team,form,goals_scored,goals_conceded,goal_diff,result",
                    "2024-01-01,Arsenal,Chelsea,7.2,2,1,1,HomeWin",
                    "2024-01-02,Liverpool,Everton,6.9,1,1,0,Draw",
                    "2024-01-03,Newcastle,Tottenham,4.8,0,2,-2,AwayWin",
                    "2024-01-04,West Ham,Brighton,5.4,2,1,1,HomeWin",
                    "2024-01-05,Fulham,Brentford,4.9,1,1,0,Draw",
                    "2024-01-06,Leicester,Wolves,6.1,3,2,1,HomeWin",
                    "2024-01-07,Crystal Palace,Aston Villa,3.7,0,1,-1,AwayWin",
                    "2024-01-08,Southampton,Leeds,5.0,2,2,0,Draw",
                    "2024-01-09,Manchester United,Bournemouth,7.5,3,0,3,HomeWin",
                    "2024-01-10,Nottingham Forest,Manchester City,3.2,0,2,-2,AwayWin",
                    "2024-01-11,Arsenal,Everton,7.4,2,0,2,HomeWin",
                    "2024-01-12,Chelsea,Liverpool,5.8,1,2,-1,AwayWin",
                ]
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(flask_app_module.strategy_lab_services.mt, "get_summary_metrics", lambda: _mock_strategy_metrics())
        monkeypatch.setattr(
            flask_app_module.strategy_lab_services.mt,
            "get_completed_predictions",
            lambda limit=6: [_mock_completed_prediction()] * limit,
        )
        monkeypatch.setattr(flask_app_module.strategy_lab_services.mlp, "DEFAULT_REPORT_PATH", report_path)
        monkeypatch.setattr(flask_app_module.strategy_lab_services, "_DEFAULT_DATASET", dataset_path)

        rv = client.get("/strategy-lab")

        assert rv.status_code == 200
        assert report_path.exists()
        assert b"Best ML Model" in rv.data
        assert b"Baseline Logistic Regression" in rv.data
        assert b"Random Forest" in rv.data


# ── Chat API ──────────────────────────────────────────────────────────────────

class TestChatRoute:
    def test_chat_returns_reply(self, client):
        rv = client.post("/chat", data={"message": "How do predictions work?"})
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "reply" in data
        assert len(data["reply"]) > 0

    def test_chat_empty_message_returns_400(self, client):
        rv = client.post("/chat", data={"message": ""})
        assert rv.status_code == 400

    def test_chat_clear_clears_history(self, client):
        # First send a message
        client.post("/chat", data={"message": "Hello"})
        # Then clear
        rv = client.post("/chat/clear")
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data.get("status") == "cleared"

    def test_chat_with_anthropic_key_calls_api(self, client):
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "The prediction uses a Poisson model."
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic", return_value=mock_client), \
             patch.object(flask_app_module, "anthropic", __import__("anthropic")):
            rv = client.post("/chat", data={"message": "Explain predictions"})

        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "reply" in data


# ── API endpoints ─────────────────────────────────────────────────────────────

class TestSecurityHardening:
    def test_select_rejects_missing_csrf_token(self, secure_client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = secure_client.post("/select", data={"team_a": "33", "team_b": "40"})

        assert rv.status_code == 400
        assert b"csrf" in rv.data.lower()

    def test_select_accepts_valid_csrf_token(self, secure_client):
        with secure_client.session_transaction() as sess:
            sess[security.CSRF_SESSION_KEY] = "known-token"

        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = secure_client.post(
                "/select",
                data={"team_a": "33", "team_b": "40", "csrf_token": "known-token"},
            )

        assert rv.status_code in (302, 303)
        assert "/prediction" in rv.headers.get("Location", "")

    def test_chat_rate_limit_returns_429(self, secure_client):
        with secure_client.session_transaction() as sess:
            sess[security.CSRF_SESSION_KEY] = "chat-token"

        with patch.object(flask_app_module, "_chat_reply", return_value="Stub reply"):
            rv1 = secure_client.post("/chat", data={"message": "One", "csrf_token": "chat-token"})
            rv2 = secure_client.post("/chat", data={"message": "Two", "csrf_token": "chat-token"})
            rv3 = secure_client.post("/chat", data={"message": "Three", "csrf_token": "chat-token"})

        assert rv1.status_code == 200
        assert rv2.status_code == 200
        assert rv3.status_code == 429
        data = json.loads(rv3.data)
        assert "retry_after" in data
        assert "rate limit" in data["error"].lower()


class TestAPIRoutes:
    def test_football_leagues_api(self, client):
        rv = client.get("/api/football/leagues")
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "leagues" in data
        assert "season" in data

    def test_football_teams_api(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.get("/api/football/teams?league=39")
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "teams" in data

    def test_football_squad_api_missing_team_id(self, client):
        rv = client.get("/api/football/squad")
        assert rv.status_code == 400

    def test_player_stats_api_missing_id(self, client):
        rv = client.get("/api/player-stats")
        assert rv.status_code == 400

    def test_props_generate_missing_params(self, client):
        rv = client.post("/props/generate", data={})
        assert rv.status_code == 400


# ── Error pages ───────────────────────────────────────────────────────────────

class TestErrorPages:
    def test_404_returns_error_page(self, client):
        rv = client.get("/this-page-does-not-exist")
        assert rv.status_code == 404
        assert b"not found" in rv.data.lower() or b"error" in rv.data.lower()


# ── World Cup page ────────────────────────────────────────────────────────────

class TestWorldCupRoute:
    def test_worldcup_get_returns_200(self, client):
        with patch("app.ac.get_espn_fixtures", return_value=[], create=True):
            rv = client.get("/worldcup")
        assert rv.status_code == 200

    def test_worldcup_post_with_valid_teams(self, client):
        with patch("app.ac.get_espn_fixtures", return_value=[], create=True):
            rv = client.post("/worldcup", data={"team_a": "Brazil", "team_b": "Argentina"})
        assert rv.status_code == 200

    def test_worldcup_same_team_shows_error(self, client):
        with patch("app.ac.get_espn_fixtures", return_value=[], create=True):
            rv = client.post("/worldcup", data={"team_a": "Brazil", "team_b": "Brazil"})
        assert rv.status_code == 200
        assert b"different" in rv.data.lower() or b"error" in rv.data.lower()
