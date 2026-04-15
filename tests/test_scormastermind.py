"""Regression tests for ScorMastermind recommendation behavior."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import scormastermind as sm


def _context_with_rule_probs(a: float, draw: float, b: float, data_quality: str = "Strong") -> dict:
    return {
        "sport": "soccer",
        "team_a_name": "Chelsea",
        "team_b_name": "Manchester United",
        "team_a_is_home": True,
        "form_a": [{"result": "W"}] * 5,
        "form_b": [{"result": "W"}] * 5,
        "team_stats": {
            "a": {"ok": True},
            "b": {"ok": True},
        },
        "rule_prediction": {
            "win_probabilities": {"a": a, "draw": draw, "b": b},
            "data_quality": data_quality,
            "best_pick": {
                "prediction": "Chelsea Win",
                "team": "A",
                "confidence": "High",
                "reasoning": "Rule model edge.",
            },
        },
        "ml_outputs": {"prob_a": 0.50},
    }


def test_avoid_triggered_when_probabilities_are_too_close():
    context = _context_with_rule_probs(31.5, 35.0, 33.5, data_quality="Strong")

    result = sm.predict_match(context)
    ui = result["ui_prediction"]

    assert ui["recommended_play"] == "Avoid"
    assert ui["best_pick"]["prediction"] == "Avoid"
    assert ui["best_pick"]["confidence"] == "Low"
    assert ui["top_lean"]["prediction"] == "Draw"
    assert ui["top_lean"]["probability"] == 35.0
    assert "No strong edge found" in ui["avoid_reasons"]


def test_strong_matchup_keeps_real_pick():
    context = _context_with_rule_probs(78.0, 10.0, 12.0, data_quality="Strong")
    context["ml_outputs"] = {"prob_a": 0.92}

    result = sm.predict_match(context)
    ui = result["ui_prediction"]

    assert ui["recommended_play"] != "Avoid"
    assert ui["best_pick"]["prediction"] == "Chelsea Win"
    assert ui["best_pick"]["tracking_team"] == "A"
    assert ui["win_probabilities"]["a"] >= 70.0


def test_supported_side_edge_beats_default_draw():
    context = _context_with_rule_probs(38.0, 34.0, 28.0, data_quality="Strong")
    context["form_a"] = [{"result": "W"}] * 4 + [{"result": "D"}]
    context["form_b"] = [{"result": "L"}] * 3 + [{"result": "D"}] * 2
    context["ml_outputs"] = {
        "prob_a": 0.61,
        "prob_draw": 0.16,
        "prob_b": 0.23,
    }

    result = sm.predict_match(context)
    ui = result["ui_prediction"]

    assert ui["best_pick"]["prediction"] == "Chelsea Win"
    assert ui["best_pick"]["team"] == "A"
    assert ui["recommended_play"] != "Avoid"
    assert ui["win_probabilities"]["a"] > ui["win_probabilities"]["draw"]
