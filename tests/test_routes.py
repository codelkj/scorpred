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
    def test_nba_prediction_without_session_redirects(self, client):
        rv = client.get("/nba/prediction")
        assert rv.status_code in (302, 303)

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
             patch("nba_live_client.get_team_recent_form", side_effect=[[home_game, away_game], [away_game, home_game]]), \
             patch("nba_live_client.get_team_injuries", side_effect=[[], []]), \
             patch("nba_live_client.get_team_season_stats", side_effect=[stats_a, stats_b]), \
             patch("nba_live_client.get_standings", return_value={"west": [{"team": {"name": "Lakers"}, "rank": 3}], "east": [{"team": {"name": "Celtics"}, "rank": 1}]}), \
             patch("scorpred_engine.scorpred_predict", return_value=_mock_nba_scorpred()), \
             patch("model_tracker.save_prediction") as mock_save:
            rv = client.get("/nba/prediction")

        assert rv.status_code == 200
        assert b"Match Winner Prediction" in rv.data
        assert b"Lakers Win" in rv.data
        assert b"Scorpred Engine Score" in rv.data
        assert b"Team Snapshot" in rv.data
        assert mock_save.call_count == 1
        assert mock_save.call_args.kwargs["game_date"] == "2026-04-21T19:30:00Z"


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
        assert "/matchup" in rv.headers.get("Location", "")

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
