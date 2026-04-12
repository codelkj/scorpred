"""
tests/test_routes.py — Flask route tests for ScorPred.

Run with:
    pytest tests/test_routes.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

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
        assert "/soccer?league=" in rv.headers.get("Location", "")

    def test_select_stores_league_context(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()):
            rv = client.post("/select", data={"team_a": "33", "team_b": "40", "league_id": "140"})
        assert rv.status_code in (302, 303)
        with client.session_transaction() as sess:
            assert sess.get("football_league_id") == 140

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

    def test_football_team_form_api(self, client):
        with patch("app._team_form_payload", return_value={"form_string": "WWDLW", "rows": []}):
            rv = client.get("/api/football/team-form?team_id=33&league=140")
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data["form_string"] == "WWDLW"
        assert data["league"] == 140


class TestLeagueSelectionFlow:
    def test_soccer_respects_league_query_for_team_loading(self, client):
        with patch("api_client.get_teams", return_value=_mock_teams()) as get_teams_mock, \
             patch("app._load_upcoming_fixtures", return_value=([], None, "configured", "")):
            rv = client.get("/soccer?league=140")
        assert rv.status_code == 200
        get_teams_mock.assert_called_once_with(140, flask_app_module.SEASON)

    def test_league_change_clears_existing_selected_matchup(self, client):
        with client.session_transaction() as sess:
            sess["football_league_id"] = 39
            sess["team_a_id"] = 33
            sess["team_b_id"] = 40

        with patch("api_client.get_teams", return_value=_mock_teams()), \
             patch("app._load_upcoming_fixtures", return_value=([], None, "configured", "")):
            rv = client.get("/soccer?league=140")

        assert rv.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("football_league_id") == 140
            assert "team_a_id" not in sess
            assert "team_b_id" not in sess


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

    def test_props_page_renders_soccer_mode_with_team_context(self, client):
        with client.session_transaction() as sess:
            sess["team_a_id"] = 33
            sess["team_a_name"] = "Manchester United"
            sess["team_a_logo"] = ""
            sess["team_b_id"] = 40
            sess["team_b_name"] = "Liverpool"
            sess["team_b_logo"] = ""

        squad = [
            {
                "player": {"id": 1, "name": "Player One", "pos": "FW"},
                "leagues": {"standard": {"pos": "FW"}},
            }
        ]
        with patch("app.ac.get_squad", return_value=squad):
            rv = client.get("/props")
        assert rv.status_code == 200
        assert b"Football" in rv.data
        assert b"Player One" in rv.data


class TestTopPicksRoute:
    def test_top_picks_uses_soccer_and_nba_payload_shapes(self, client):
        today_str = date.today().strftime("%Y-%m-%d")
        soccer_fixtures = [
            {
                "teams": {
                    "home": {"id": 1, "name": "Alpha"},
                    "away": {"id": 2, "name": "Beta"},
                },
                "prediction": {
                    "best_pick": {
                        "prediction": "Alpha",
                        "confidence": "High",
                        "reasoning": "Strong form edge",
                    },
                    "win_probabilities": {"a": 64.0, "b": 21.0, "draw": 15.0},
                },
            }
        ]
        nba_recent = [
            {
                "sport": "nba",
                "date": today_str,
                "is_correct": None,
                "team_a": "Celtics",
                "team_b": "Heat",
                "predicted_winner": "A",
                "confidence": "High",
                "prob_a": 61.0,
                "prob_b": 39.0,
                "prob_draw": 0.0,
            }
        ]

        with patch("app._load_upcoming_fixtures", return_value=(soccer_fixtures, None, "configured", "")), \
             patch("app.mt.get_recent_predictions", return_value=nba_recent):
            rv = client.get("/top-picks-today")

        assert rv.status_code == 200
        assert b"Alpha" in rv.data
        assert b"Celtics" in rv.data


class TestNbaFailureHandling:
    def test_nba_index_handles_fetch_failures(self, client):
        with patch("nba_live_client.get_teams", side_effect=Exception("teams down")), \
             patch("nba_live_client.get_today_games", side_effect=Exception("games down")), \
             patch("nba_live_client.get_upcoming_games", side_effect=Exception("upcoming down")), \
             patch("nba_live_client.get_standings", return_value={"conference": []}):
            rv = client.get("/nba/")
        assert rv.status_code == 200

    def test_nba_index_shows_predicted_winner_for_upcoming_game(self, client):
        teams = [
            {"id": "1", "name": "Boston Celtics", "nickname": "Celtics", "city": "Boston", "logo": ""},
            {"id": "2", "name": "Orlando Magic", "nickname": "Magic", "city": "Orlando", "logo": ""},
        ]
        game = {
            "id": "evt-1",
            "date": {"start": "2026-04-12T22:00:00Z"},
            "status": {"long": "Scheduled", "short": "Scheduled", "state": "pre"},
            "venue": {"name": "TD Garden"},
            "teams": {
                "home": {"id": "1", "name": "Boston Celtics", "nickname": "Celtics", "logo": ""},
                "visitors": {"id": "2", "name": "Orlando Magic", "nickname": "Magic", "logo": ""},
            },
            "scores": {"home": {"points": 0}, "visitors": {"points": 0}},
        }

        with patch("nba_routes.nc.get_teams", return_value=teams), \
             patch("nba_routes.nc.get_today_games", return_value=[]), \
             patch("nba_routes.nc.get_upcoming_games", return_value=[game]), \
             patch("nba_routes.nc.get_h2h", return_value=[]), \
             patch("nba_routes.nc.get_team_recent_form", return_value=[]), \
             patch("nba_routes.nc.get_team_injuries", return_value=[]), \
             patch("nba_routes.nc.get_standings", return_value={"east": [], "west": []}), \
             patch("nba_routes.se.scorpred_predict", return_value={
                 "best_pick": {"prediction": "Celtics", "confidence": "High"},
                 "win_probabilities": {"a": 62.3, "b": 37.7},
             }):
            rv = client.get("/nba/")

        assert rv.status_code == 200
        assert b"Predicted winner: Celtics" in rv.data
        assert b"Game tied" not in rv.data

    def test_worldcup_same_team_shows_error(self, client):
        with patch("app.ac.get_espn_fixtures", return_value=[], create=True):
            rv = client.post("/worldcup", data={"team_a": "Brazil", "team_b": "Brazil"})
        assert rv.status_code == 200
        assert b"different" in rv.data.lower() or b"error" in rv.data.lower()
