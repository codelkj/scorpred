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
