"""
tests/test_predictor.py — Unit tests for predictor.py

Run with:
    pytest tests/test_predictor.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from league_config import CURRENT_SEASON

import predictor as pred


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fixture(home_id: int, away_id: int, home_goals: int, away_goals: int,
                  date: str | None = None,
                  season: str | int | None = None,
                  status_short: str = "FT") -> dict:
    if date is None:
        date = f"{CURRENT_SEASON}-01-15T15:00:00+00:00"
    league = {"id": 39, "name": "Premier League"}
    if season is not None:
        league["season"] = season
    return {
        "fixture": {"id": 1, "date": date, "status": {"short": status_short}},
        "teams": {
            "home": {"id": home_id, "name": f"Team{home_id}", "logo": ""},
            "away": {"id": away_id, "name": f"Team{away_id}", "logo": ""},
        },
        "goals": {"home": home_goals, "away": away_goals},
        "league": league,
    }


# ── extract_form ──────────────────────────────────────────────────────────────

class TestExtractForm:
    def test_win_result(self):
        fixture = _make_fixture(1, 2, 3, 1)
        form = pred.extract_form([fixture], team_id=1)
        assert form[0]["result"] == "W"
        assert form[0]["gf"] == 3
        assert form[0]["ga"] == 1
        assert form[0]["home"] is True

    def test_loss_result_as_away(self):
        fixture = _make_fixture(1, 2, 3, 1)
        form = pred.extract_form([fixture], team_id=2)
        assert form[0]["result"] == "L"
        assert form[0]["gf"] == 1
        assert form[0]["ga"] == 3
        assert form[0]["home"] is False

    def test_draw_result(self):
        fixture = _make_fixture(1, 2, 2, 2)
        form = pred.extract_form([fixture], team_id=1)
        assert form[0]["result"] == "D"

    def test_skips_fixture_with_null_goals(self):
        fixture = _make_fixture(1, 2, None, None)
        fixture["goals"] = {"home": None, "away": None}
        form = pred.extract_form([fixture], team_id=1)
        assert form == []

    def test_clean_sheet_flag(self):
        fixture = _make_fixture(1, 2, 2, 0)
        form = pred.extract_form([fixture], team_id=1)
        assert form[0]["cs"] is True

    def test_no_clean_sheet_flag(self):
        fixture = _make_fixture(1, 2, 2, 1)
        form = pred.extract_form([fixture], team_id=1)
        assert form[0]["cs"] is False

    def test_empty_fixture_list(self):
        assert pred.extract_form([], team_id=1) == []

    def test_date_truncated_to_10_chars(self):
        fixture = _make_fixture(1, 2, 1, 0, date=f"{CURRENT_SEASON}-03-20T19:00:00+00:00")
        form = pred.extract_form([fixture], team_id=1)
        assert form[0]["date"] == f"{CURRENT_SEASON}-03-20"

    def test_filters_to_recent_completed_matches(self):
        old_fixture = _make_fixture(1, 2, 2, 1, date="2022-12-10T15:00:00+00:00")
        recent_fixture = _make_fixture(1, 2, 1, 0, date="2024-05-10T15:00:00+00:00")
        pending_fixture = _make_fixture(1, 2, None, None, date="2024-05-20T15:00:00+00:00")
        form = pred.extract_form([old_fixture, pending_fixture, recent_fixture], team_id=1)
        assert len(form) == 1
        assert form[0]["date"] == "2024-05-10"

    def test_extract_form_sorts_newest_first(self):
        older = _make_fixture(1, 2, 1, 0, date="2024-04-01T15:00:00+00:00")
        newer = _make_fixture(1, 2, 2, 1, date="2024-05-01T15:00:00+00:00")
        form = pred.extract_form([older, newer], team_id=1)
        assert form[0]["date"] == "2024-05-01"
        assert form[1]["date"] == "2024-04-01"

    def test_previous_season_fixture_is_included(self):
        prev_season = _make_fixture(
            1, 2, 1, 0,
            date="2024-05-10T15:00:00+00:00",
            season="2023/2024",
            status_short="FT",
        )
        form = pred.filter_recent_completed_fixtures([prev_season], current_season=CURRENT_SEASON)
        assert len(form) == 1

    def test_live_match_is_excluded_even_with_goals(self):
        live_fixture = _make_fixture(
            1, 2, 2, 1,
            date="2024-04-10T15:00:00+00:00",
            season="2023/2024",
            status_short="1H",
        )
        filtered = pred.filter_recent_completed_fixtures([live_fixture], current_season=CURRENT_SEASON)
        assert filtered == []

    def test_split_year_season_metadata_parses_start_year(self):
        split_year_fixture = _make_fixture(
            1, 2, 2, 0,
            date="2024-05-10T15:00:00+00:00",
            season="2023/2024",
            status_short="FT",
        )
        filtered = pred.filter_recent_completed_fixtures([split_year_fixture], current_season=CURRENT_SEASON)
        assert len(filtered) == 1
        assert filtered[0]["league"]["season"] == "2023/2024"

    def test_date_fallback_uses_real_season_boundaries(self):
        date_fallback_fixture = _make_fixture(
            1, 2, 1, 0,
            date="2024-05-10T15:00:00+00:00",
            season=None,
            status_short="FT",
        )
        filtered = pred.filter_recent_completed_fixtures([date_fallback_fixture], current_season=CURRENT_SEASON)
        assert len(filtered) == 1


# ── form_pts ──────────────────────────────────────────────────────────────────

class TestFormPts:
    def test_all_wins(self):
        form = [{"result": "W"}, {"result": "W"}, {"result": "W"}]
        assert pred.form_pts(form) == 1.0

    def test_all_losses(self):
        form = [{"result": "L"}, {"result": "L"}]
        assert pred.form_pts(form) == 0.0

    def test_all_draws(self):
        form = [{"result": "D"}, {"result": "D"}]
        assert round(pred.form_pts(form), 4) == round(1 / 3, 4)

    def test_empty_form_returns_neutral(self):
        assert pred.form_pts([]) == 0.5

    def test_mixed_form(self):
        form = [{"result": "W"}, {"result": "D"}, {"result": "L"}]
        # (3 + 1 + 0) / (3*3) = 4/9
        assert round(pred.form_pts(form), 4) == round(4 / 9, 4)


# ── avg_goals ─────────────────────────────────────────────────────────────────

class TestAvgGoals:
    def test_scored_average(self):
        form = [{"gf": 2, "ga": 0}, {"gf": 3, "ga": 1}]
        assert pred.avg_goals(form, scored=True) == 2.5

    def test_conceded_average(self):
        form = [{"gf": 2, "ga": 0}, {"gf": 3, "ga": 1}]
        assert pred.avg_goals(form, scored=False) == 0.5

    def test_empty_form_returns_default(self):
        assert pred.avg_goals([], scored=True) == 1.2


# ── home_away_split ───────────────────────────────────────────────────────────

class TestHomeAwaySplit:
    def test_split_counts(self):
        form = [
            {"result": "W", "gf": 2, "ga": 0, "home": True},
            {"result": "L", "gf": 0, "ga": 2, "home": True},
            {"result": "W", "gf": 1, "ga": 0, "home": False},
        ]
        split = pred.home_away_split(form)
        assert split["home"]["p"] == 2
        assert split["away"]["p"] == 1
        assert split["home"]["w"] == 1
        assert split["home"]["l"] == 1

    def test_empty_form_returns_zeros(self):
        split = pred.home_away_split([])
        assert split["home"]["p"] == 0
        assert split["away"]["p"] == 0


# ── h2h_record ────────────────────────────────────────────────────────────────

class TestH2hRecord:
    def test_basic_record(self):
        fixtures = [
            _make_fixture(1, 2, 2, 0),  # team 1 wins
            _make_fixture(1, 2, 1, 1),  # draw
            _make_fixture(2, 1, 3, 0),  # team 2 wins (home), so team 1 loses
        ]
        rec = pred.h2h_record(fixtures, id_a=1, id_b=2)
        assert rec["a_wins"] == 1
        assert rec["draws"] == 1
        assert rec["b_wins"] == 1
        assert rec["total"] == 3

    def test_h2h_record_filters_old_matches(self):
        fixtures = [
            _make_fixture(1, 2, 2, 0, date="2022-12-10T15:00:00+00:00"),
            _make_fixture(1, 2, 1, 1, date="2024-05-10T15:00:00+00:00"),
        ]
        rec = pred.h2h_record(fixtures, id_a=1, id_b=2)
        assert rec["total"] == 1
        assert rec["a_wins"] == 0
        assert rec["draws"] == 1

    def test_empty_h2h(self):
        rec = pred.h2h_record([], id_a=1, id_b=2)
        assert rec["total"] == 1  # avoids division by zero
        assert rec["a_wins"] == 0

    def test_percentages_sum_to_1(self):
        fixtures = [
            _make_fixture(1, 2, 2, 1),
            _make_fixture(1, 2, 0, 1),
        ]
        rec = pred.h2h_record(fixtures, id_a=1, id_b=2)
        total_pct = rec["a_pct"] + rec["d_pct"] + rec["b_pct"]
        assert round(total_pct, 5) == 1.0


# ── _normalise_probs (via app helper) ─────────────────────────────────────────

class TestNormaliseProbs:
    """Test the probability normalisation helper in app.py."""

    def setup_method(self):
        import app as flask_app
        self._normalise = flask_app._normalise_probs

    def test_sums_to_100(self):
        result = self._normalise({"a": 50.0, "draw": 25.0, "b": 25.0})
        assert round(result["a"] + result["draw"] + result["b"], 1) == 100.0

    def test_all_zeros_returns_equal_split(self):
        result = self._normalise({"a": 0, "draw": 0, "b": 0})
        assert result == {"a": 33.4, "draw": 33.3, "b": 33.3}

    def test_negative_values_clamped_to_zero(self):
        result = self._normalise({"a": -10, "draw": 50, "b": 50})
        assert result["a"] == 0.0
        assert round(result["draw"] + result["b"], 1) == 100.0

    def test_preserves_relative_proportions(self):
        result = self._normalise({"a": 60.0, "draw": 20.0, "b": 20.0})
        assert result["a"] > result["draw"]
        assert result["a"] > result["b"]


# ── quick_predict_from_standings ──────────────────────────────────────────────

class TestQuickPredictFromStandings:
    def _make_standing(self, team_id: int, points: int, played: int = 20,
                       gf: int = 30, ga: int = 20, form: str = "WWDLW") -> dict:
        return {
            "team": {"id": team_id, "name": f"Team{team_id}"},
            "points": points,
            "form": form,
            "all": {
                "played": played,
                "goals": {"for": gf, "against": ga},
            },
        }

    def test_returns_dict_with_keys(self):
        standings = [
            self._make_standing(1, 60, gf=50, ga=20),
            self._make_standing(2, 40, gf=30, ga=30),
        ]
        result = pred.quick_predict_from_standings(1, 2, standings)
        assert isinstance(result, dict)
        assert "home_pct" in result
        assert "away_pct" in result
        assert "draw_pct" in result

    def test_empty_standings_returns_dict(self):
        result = pred.quick_predict_from_standings(1, 2, [])
        assert isinstance(result, dict)
