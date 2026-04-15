"""
Unit tests for prediction tracking and result reconciliation.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import model_tracker as mt
import result_updater as ru


@pytest.fixture
def tracking_file(tmp_path, monkeypatch):
    path = tmp_path / "prediction_tracking.json"
    monkeypatch.setattr(mt, "_TRACKING_FILE", str(path))
    return path


def _load_predictions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("predictions", [])


def _set_prediction_fields(path: Path, pred_id: str, fields: dict) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    predictions = payload.get("predictions", [])
    for pred in predictions:
        if pred.get("id") == pred_id:
            pred.update(fields)
            break
    path.write_text(json.dumps({"predictions": predictions}, indent=2), encoding="utf-8")


def test_save_prediction_stores_explicit_game_date(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Manchester United",
        team_b="Liverpool",
        predicted_winner="A",
        win_probs={"a": 54.2, "draw": 24.1, "b": 21.7},
        confidence="High",
        game_date="2026-04-15T19:30:00Z",
        team_a_id=33,
        team_b_id=40,
        league_id=39,
        season=2025,
    )

    assert pred_id
    predictions = _load_predictions(tracking_file)
    assert len(predictions) == 1
    assert predictions[0]["game_date"] == "2026-04-15"
    assert predictions[0]["date"] == "2026-04-15"
    assert predictions[0]["team_a_id"] == "33"
    assert predictions[0]["team_b_id"] == "40"
    assert predictions[0]["league_id"] == 39
    assert predictions[0]["season"] == 2025


def test_update_pending_predictions_uses_stored_game_date(tracking_file, monkeypatch):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Manchester United",
        team_b="Liverpool",
        predicted_winner="A",
        win_probs={"a": 60.0, "draw": 22.0, "b": 18.0},
        confidence="High",
        game_date="2026-04-20",
        team_a_id=33,
        team_b_id=40,
        league_id=39,
        season=2025,
    )
    assert pred_id

    calls = {}

    def fake_fetch(team_a, team_b, date_str, league_id=39, season=2025, team_a_id=None, team_b_id=None):
        calls["team_a"] = team_a
        calls["team_b"] = team_b
        calls["date_str"] = date_str
        calls["league_id"] = league_id
        calls["season"] = season
        calls["team_a_id"] = team_a_id
        calls["team_b_id"] = team_b_id
        return {
            "found": True,
            "winner": "A",
            "score": {"a": 2, "b": 1},
            "status": "FT",
            "teams": {"a": team_a, "b": team_b},
        }

    monkeypatch.setattr(ru, "fetch_soccer_result", fake_fetch)

    stats = ru.update_pending_predictions()

    assert stats["checked"] == 1
    assert stats["found"] == 1
    assert stats["updated"] == 1
    assert calls["date_str"] == "2026-04-20"
    assert calls["league_id"] == 39
    assert calls["season"] == 2025
    assert calls["team_a_id"] == "33"
    assert calls["team_b_id"] == "40"

    completed = mt.get_completed_predictions()
    assert len(completed) == 1
    assert completed[0]["actual_result"] == "A"
    assert completed[0]["winner_hit"] is True
    assert completed[0]["final_score_display"] == "2-1"


def test_get_summary_metrics_grades_completed_predictions_from_persisted_results(tracking_file):
    correct_id = mt.save_prediction(
        sport="soccer",
        team_a="Arsenal",
        team_b="Chelsea",
        predicted_winner="A",
        win_probs={"a": 55.0, "draw": 23.0, "b": 22.0},
        confidence="High",
        game_date="2026-04-18",
    )
    wrong_id = mt.save_prediction(
        sport="nba",
        team_a="Lakers",
        team_b="Celtics",
        predicted_winner="B",
        win_probs={"a": 48.0, "b": 52.0},
        confidence="Low",
        game_date="2026-04-19",
    )

    mt.update_prediction_result(correct_id, "A", {"a": 2, "b": 1})
    mt.update_prediction_result(wrong_id, "A", {"a": 112, "b": 107})

    metrics = mt.get_summary_metrics()

    assert metrics["finalized_predictions"] == 2
    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["overall_accuracy"] == 50.0
    assert metrics["by_confidence"]["High"]["wins"] == 1
    assert metrics["by_confidence"]["Low"]["losses"] == 1
    assert metrics["by_sport"]["soccer"]["accuracy"] == 100.0
    assert metrics["by_sport"]["nba"]["accuracy"] == 0.0


def test_draw_prediction_hits_when_final_score_is_draw(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="Draw",
        win_probs={"a": 31.5, "draw": 35.0, "b": 33.5},
        confidence="Low",
        game_date="2026-04-22",
    )

    assert mt.update_prediction_result(pred_id, "draw", {"a": 1, "b": 1})
    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is True
    assert completed[0]["winner_display"] == "Winner Pick: Hit"


def test_team_name_prediction_misses_when_actual_is_draw(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="Chelsea",
        win_probs={"a": 45.0, "draw": 30.0, "b": 25.0},
        confidence="Medium",
        game_date="2026-04-23",
    )

    assert mt.update_prediction_result(pred_id, "draw", {"a": 1, "b": 1})
    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is False


def test_home_win_prediction_misses_when_away_team_wins(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="Home Win",
        win_probs={"a": 52.0, "draw": 24.0, "b": 24.0},
        confidence="Medium",
        game_date="2026-04-24",
    )

    assert mt.update_prediction_result(pred_id, "B", {"a": 0, "b": 2})
    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is False


def test_totals_hit_but_winner_miss_is_split_correctly(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="B",
        win_probs={"a": 52.0, "draw": 23.0, "b": 25.0},
        confidence="Medium",
        game_date="2026-04-25",
    )
    _set_prediction_fields(tracking_file, pred_id, {"predicted_total_pick": "Over"})

    assert mt.update_prediction_result(pred_id, "A", {"a": 2, "b": 1})
    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is False
    assert completed[0]["totals_hit"] is True
    assert completed[0]["overall_game_result"] == "Partial"


def test_winner_hit_but_totals_miss_is_split_correctly(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="A",
        win_probs={"a": 52.0, "draw": 23.0, "b": 25.0},
        confidence="Medium",
        game_date="2026-04-26",
    )
    _set_prediction_fields(tracking_file, pred_id, {"predicted_total_pick": "Over"})

    assert mt.update_prediction_result(pred_id, "A", {"a": 1, "b": 0})
    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is True
    assert completed[0]["totals_hit"] is False
    assert completed[0]["overall_game_result"] == "Partial"


def test_completed_card_labels_use_corrected_grading_fields(tracking_file):
    pred_id = mt.save_prediction(
        sport="soccer",
        team_a="Chelsea",
        team_b="Manchester United",
        predicted_winner="A",
        win_probs={"a": 52.0, "draw": 23.0, "b": 25.0},
        confidence="Medium",
        game_date="2026-04-27",
    )
    _set_prediction_fields(tracking_file, pred_id, {"predicted_total_pick": "Under"})

    assert mt.update_prediction_result(pred_id, "A", {"a": 2, "b": 0})
    completed = mt.get_completed_predictions()
    assert completed[0]["final_score_display"] == "2-0"
    assert completed[0]["winner_display"] == "Winner Pick: Hit"
    assert "Totals Pick (Under 2.5): Hit" == completed[0]["ou_display"]
    assert completed[0]["overall_game_result"] == "Win"


def test_stale_completed_record_is_recomputed_on_load(tracking_file):
    stale = {
        "predictions": [
            {
                "id": "stale001",
                "sport": "soccer",
                "date": "2026-04-28",
                "game_date": "2026-04-28",
                "team_a": "Chelsea",
                "team_b": "Manchester United",
                "predicted_winner": "Chelsea",
                "prob_a": 51.0,
                "prob_b": 25.0,
                "prob_draw": 24.0,
                "confidence": "Medium",
                "status": "completed",
                "actual_result": "draw",
                "is_correct": True,
                "final_score": {"a": 1, "b": 1},
                "created_at": "2026-04-28T12:00:00Z",
                "updated_at": "2026-04-28T12:00:00Z",
            }
        ]
    }
    tracking_file.write_text(json.dumps(stale, indent=2), encoding="utf-8")

    completed = mt.get_completed_predictions()
    assert completed[0]["winner_hit"] is False
    assert completed[0]["is_correct"] is False

    reloaded = _load_predictions(tracking_file)
    assert reloaded[0]["is_correct"] is False


def test_evaluation_dashboard_builds_series_breakdowns_and_failures(tracking_file):
    # High-confidence home win (correct)
    pred_a = mt.save_prediction(
        sport="soccer",
        team_a="Arsenal",
        team_b="Chelsea",
        predicted_winner="A",
        win_probs={"a": 0.84, "draw": 0.08, "b": 0.08},
        confidence="High",
        game_date="2026-04-01",
    )
    mt.update_prediction_result(pred_a, "A", {"a": 2, "b": 1})

    # Medium-confidence away win (incorrect)
    pred_b = mt.save_prediction(
        sport="soccer",
        team_a="Liverpool",
        team_b="Everton",
        predicted_winner="B",
        win_probs={"a": 0.25, "draw": 0.20, "b": 0.55},
        confidence="Medium",
        game_date="2026-04-02",
    )
    mt.update_prediction_result(pred_b, "A", {"a": 3, "b": 1})

    # Draw call (correct)
    pred_c = mt.save_prediction(
        sport="soccer",
        team_a="Tottenham",
        team_b="West Ham",
        predicted_winner="draw",
        win_probs={"a": 0.31, "draw": 0.42, "b": 0.27},
        confidence="Low",
        game_date="2026-04-03",
    )
    mt.update_prediction_result(pred_c, "draw", {"a": 1, "b": 1})

    # Pending avoid should count toward avoids_skipped but not finalized series
    avoid_id = mt.save_prediction(
        sport="soccer",
        team_a="Leeds",
        team_b="Brighton",
        predicted_winner="avoid",
        win_probs={"a": 0.34, "draw": 0.33, "b": 0.33},
        confidence="Low",
        game_date="2026-04-04",
    )
    assert avoid_id

    evaluation = mt.get_evaluation_dashboard(
        rolling_window=2,
        strategy_reference={"ml_accuracy": 58.0, "combined_accuracy": 62.5, "evaluation_matches": 120},
    )

    assert evaluation["kpis"]["finalized_predictions"] == 3
    assert evaluation["kpis"]["total_tracked_predictions"] == 4
    assert evaluation["kpis"]["avoids_skipped"] == 1
    assert evaluation["kpis"]["rolling_win_rate"] == 50.0

    rolling_match = evaluation["series"]["rolling_by_match"]
    cumulative = evaluation["series"]["cumulative_points"]
    rolling_day = evaluation["series"]["rolling_by_day"]
    assert len(rolling_match) == 3
    assert len(cumulative) == 3
    assert len(rolling_day) == 3
    assert cumulative[-1]["cumulative_points"] == 1

    calibration = {row["bucket"]: row for row in evaluation["confidence_calibration"]}
    assert calibration["80-100"]["sample_size"] == 1
    assert calibration["60-80"]["sample_size"] == 1
    assert calibration["40-60"]["sample_size"] == 1
    assert calibration["<40"]["sample_size"] == 0

    breakdown = {row["key"]: row for row in evaluation["breakdowns"]["by_predicted_outcome"]}
    assert breakdown["A"]["count"] == 1
    assert breakdown["B"]["count"] == 1
    assert breakdown["draw"]["count"] == 1
    assert breakdown["A"]["accuracy"] == 100.0
    assert breakdown["B"]["accuracy"] == 0.0

    strategies = {row["strategy"]: row for row in evaluation["strategy_comparison"]}
    assert strategies["ML"]["accuracy"] == 58.0
    assert strategies["Combined"]["accuracy"] == 62.5
    assert strategies["Rule-Based"]["sample_size"] == 3

    failures = evaluation["failure_rows"]
    assert failures
    assert failures[0]["matchup"] == "Liverpool vs Everton"
    assert failures[0]["recommendation"] == "Everton ML"
