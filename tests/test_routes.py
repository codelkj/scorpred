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
