"""
tests/test_routes.py — Flask route tests for ScorPred.

Run with:
    pytest tests/test_routes.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as flask_app_module


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app_module.app.config["TESTING"] = True
    flask_app_module.app.config["SECRET_KEY"] = "test-secret"
    flask_app_module.app.config["WTF_CSRF_ENABLED"] = False
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


class TestTodayPredictionsRoute:
    def test_today_predictions_handles_missing_score_gap(self, client):
        payload = [
            {
                "fixture": {
                    "date": "2026-04-12T15:00:00+00:00",
                },
                "teams": {
                    "home": {"name": "Alpha", "logo": ""},
                    "away": {"name": "Beta", "logo": ""},
                },
                "league": {"name": "Premier League"},
                "prediction": {
                    "best_pick": {
                        "prediction": "Alpha",
                        "confidence": "High",
                        "reasoning": "Recent form edge",
                    },
                    "win_probabilities": {"a": 61.0, "draw": 22.0, "b": 17.0},
                },
            }
        ]

        with patch("app._load_upcoming_fixtures", return_value=(payload, None, "configured", "")):
            rv = client.get("/today-soccer-predictions")

        assert rv.status_code == 200
        assert b"Upcoming Soccer Predictions" in rv.data


# ── Select / team selection ───────────────────────────────────────────────────

class TestSelectRoute:
    def test_select_redirects_to_matchup(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": "40"})
        assert rv.status_code in (302, 303)
        assert "/matchup" in rv.headers.get("Location", "")

    def test_select_same_team_redirects_home(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": "33"})
        assert rv.status_code in (302, 303)
        assert rv.headers.get("Location", "").endswith("/")

    def test_select_missing_team_redirects_home(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": ""})
        assert rv.status_code in (302, 303)

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

    def test_matchup_handles_upstream_failures(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("api_client.get_h2h", side_effect=Exception("h2h down")), \
             patch("api_client.get_team_fixtures", side_effect=Exception("fixtures down")), \
             patch("api_client.get_injuries", side_effect=Exception("injuries down")), \
             patch("api_client.get_standings", side_effect=Exception("standings down")):
            rv = client.get("/matchup")
        assert rv.status_code == 200


# ── Prediction page ───────────────────────────────────────────────────────────

class TestPredictionRoute:
    def test_prediction_without_session_redirects(self, client):
        rv = client.get("/prediction")
        assert rv.status_code in (302, 303)

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

    def test_prediction_handles_upstream_failures(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("api_client.get_h2h", side_effect=Exception("h2h down")), \
             patch("api_client.get_team_fixtures", side_effect=Exception("fixtures down")), \
             patch("api_client.get_injuries", side_effect=Exception("injuries down")), \
             patch("api_client.get_standings", side_effect=Exception("standings down")):
            rv = client.get("/prediction")
        assert rv.status_code == 200


# ── Players page ──────────────────────────────────────────────────────────────

class TestPlayersRoute:
    def test_players_without_session_redirects(self, client):
        rv = client.get("/players")
        assert rv.status_code in (302, 303)

    def test_players_uses_squad_fallback_and_renders(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        squad = [
            {"id": 1, "name": "Player A", "position": "Goalkeeper", "photo": "", "number": 1},
            {"id": 2, "name": "Player B", "position": "Forward", "photo": "", "number": 9},
        ]
        with patch("app.ac.get_squad", return_value=squad), \
             patch("app.ac.get_injuries", return_value=[]):
            rv = client.get("/players")
        assert rv.status_code == 200
        assert b"Full Squads" in rv.data

    def test_players_handles_squad_fetch_failure(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("app.ac.get_squad", side_effect=Exception("squad down")):
            rv = client.get("/players")
        assert rv.status_code == 200


class TestPropsRoute:
    def test_props_without_session_redirects(self, client):
        rv = client.get("/props")
        assert rv.status_code in (302, 303)

    def test_props_with_session_renders(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("app.ac.get_squad", return_value=[]):
            rv = client.get("/props")
        assert rv.status_code == 200

    def test_props_handles_squad_fetch_failure(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        with patch("app.ac.get_squad", side_effect=Exception("squad down")):
            rv = client.get("/props")
        assert rv.status_code == 200


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

    def test_football_squad_api_invalid_team_id(self, client):
        rv = client.get("/api/football/squad?team_id=abc")
        assert rv.status_code == 400

    def test_player_stats_api_missing_id(self, client):
        rv = client.get("/api/player-stats")
        assert rv.status_code == 400

    def test_player_stats_api_invalid_player_id(self, client):
        rv = client.get("/api/player-stats?player_id=abc")
        assert rv.status_code == 400

    def test_props_generate_missing_params(self, client):
        rv = client.post("/props/generate", data={})
        assert rv.status_code == 400

    def test_props_generate_invalid_numeric_payload_returns_400(self, client):
        rv = client.post(
            "/props/generate",
            json={"player_id": "abc", "player_team_id": "x", "opponent_id": "y"},
        )
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


class TestUpdateResultsRoute:
    def test_update_results_post_with_null_accuracy_renders(self, client):
        summary = {"pending": 1, "completed": 0, "total": 1, "completion_rate": 0.0}
        update_stats = {"checked": 1, "found": 0, "updated": 0, "failed": 0, "errors": []}
        metrics = {
            "total_predictions": 1,
            "finalized_predictions": 0,
            "wins": 0,
            "losses": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "recent_predictions": [],
        }

        with patch("result_updater.get_update_summary", return_value=summary), \
             patch("result_updater.update_pending_predictions", return_value=update_stats), \
             patch("model_tracker.get_summary_metrics", return_value=metrics):
            rv = client.post("/update-prediction-results")

        assert rv.status_code == 200
        assert b"Overall Accuracy" in rv.data


class TestConnectedFlows:
    def test_soccer_connected_flow(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()), \
             patch("api_client.get_upcoming_fixtures", return_value=[_mock_fixture()]), \
             patch("api_client.get_h2h", return_value=[_mock_fixture()]), \
             patch("api_client.get_team_fixtures", return_value=[_mock_fixture()]), \
             patch("api_client.get_injuries", return_value=[]), \
             patch("api_client.get_standings", return_value=[]), \
             patch("app.ac.get_squad", return_value=[]):
            assert client.get("/").status_code == 200
            assert client.get("/soccer").status_code == 200

            select_resp = client.post("/select", data={"team_a": "33", "team_b": "40"})
            assert select_resp.status_code in (302, 303)
            assert "/matchup" in select_resp.headers.get("Location", "")

            assert client.get("/matchup").status_code == 200
            assert client.get("/prediction").status_code == 200
            assert client.get("/players").status_code == 200
            assert client.get("/props").status_code == 200

    def test_model_performance_to_update_results_flow(self, client):
        with patch("result_updater.get_update_summary", return_value={"pending": 1, "completed": 0, "total": 1, "completion_rate": 0.0}), \
             patch("model_tracker.get_summary_metrics", return_value={"total_predictions": 1, "finalized_predictions": 0, "wins": 0, "losses": 0, "overall_accuracy": None, "by_confidence": {}, "by_sport": {}, "recent_predictions": []}):
            assert client.get("/model-performance").status_code == 200
            assert client.get("/update-prediction-results").status_code == 200


class TestNbaFailureHandling:
    def test_nba_index_handles_fetch_failures(self, client):
        with patch("nba_live_client.get_teams", side_effect=Exception("teams down")), \
             patch("nba_live_client.get_today_games", side_effect=Exception("games down")), \
             patch("nba_live_client.get_upcoming_games", side_effect=Exception("upcoming down")), \
             patch("nba_live_client.get_standings", return_value={"conference": []}):
            rv = client.get("/nba/")
        assert rv.status_code == 200

    def test_worldcup_same_team_shows_error(self, client):
        with patch("app.ac.get_espn_fixtures", return_value=[], create=True):
            rv = client.post("/worldcup", data={"team_a": "Brazil", "team_b": "Brazil"})
        assert rv.status_code == 200
        assert b"different" in rv.data.lower() or b"error" in rv.data.lower()
