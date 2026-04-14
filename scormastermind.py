"""Unified prediction orchestration for soccer and NBA routes.

ScorMastermind blends:
- Rule-based engine output (scorpred_engine)
- Optional ML signal (report-driven or provided model output)
- Lightweight heuristics (form + context)

Primary API:
    predict_match(context) -> dict
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import scorpred_engine as se

_ML_REPORT_PATH = Path("cache/ml/model_comparison.json")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "High"
    if confidence >= 0.5:
        return "Medium"
    return "Low"


def _is_weak_data_quality(data_quality: str) -> bool:
    return str(data_quality or "").strip().lower() in {"limited", "weak", "poor"}


def _load_ml_report() -> dict[str, Any] | None:
    if not _ML_REPORT_PATH.exists():
        return None
    try:
        return json.loads(_ML_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _results_to_points(rows: list[dict], sport: str) -> float:
    if not rows:
        return 0.5
    pts = 0.0
    for row in rows[:5]:
        result = str(row.get("result", "")).upper()
        if result == "W":
            pts += 1.0
        elif result == "D" and sport == "soccer":
            pts += 0.45
    return pts / max(1.0, min(5.0, float(len(rows[:5]))))


def _heuristic_signal(context: dict[str, Any]) -> dict[str, Any]:
    sport = str(context.get("sport") or "soccer").lower()
    form_a = context.get("form_a") or []
    form_b = context.get("form_b") or []
    team_a_is_home = bool(context.get("team_a_is_home", True))

    form_a_pts = _results_to_points(form_a, sport)
    form_b_pts = _results_to_points(form_b, sport)
    form_delta = form_a_pts - form_b_pts

    home_adv = 0.06 if team_a_is_home else -0.06
    prob_a = _clamp(0.5 + form_delta * 0.22 + home_adv, 0.05, 0.95)
    return {
        "available": True,
        "prob_a": prob_a,
        "form_delta": round(form_delta, 3),
        "home_advantage": home_adv,
    }


def _ml_signal(context: dict[str, Any]) -> dict[str, Any]:
    ml_outputs = context.get("ml_outputs") or {}
    report = context.get("ml_report") or _load_ml_report() or {}

    for key in ("prob_a", "home_win_prob", "winner_prob"):
        if key in ml_outputs:
            prob = _clamp(_safe_float(ml_outputs.get(key), 0.5), 0.01, 0.99)
            return {
                "available": True,
                "prob_a": prob,
                "source": "provided_ml_output",
                "top_features": ml_outputs.get("top_features") or [],
            }

    ranking = report.get("ranking") or []
    best = ranking[0] if ranking else {}
    top_features = best.get("top_features") or []
    if not top_features:
        return {
            "available": False,
            "prob_a": 0.5,
            "source": "missing_ml_data",
            "top_features": [],
        }

    form_a = context.get("form_a") or []
    form_b = context.get("form_b") or []
    sport = str(context.get("sport") or "soccer").lower()

    form_delta = _results_to_points(form_a, sport) - _results_to_points(form_b, sport)
    feature_weight = min(1.0, sum(_safe_float(item.get("importance", item.get("weight", 0.0))) for item in top_features[:3]))
    prob = _clamp(0.5 + form_delta * 0.2 * max(0.3, feature_weight), 0.05, 0.95)

    return {
        "available": True,
        "prob_a": prob,
        "source": "model_comparison_report",
        "top_features": top_features[:5],
    }


def _build_rule_prediction(context: dict[str, Any]) -> dict[str, Any]:
    return se.scorpred_predict(
        form_a=context.get("form_a") or [],
        form_b=context.get("form_b") or [],
        h2h_form_a=context.get("h2h_form_a") or [],
        h2h_form_b=context.get("h2h_form_b") or [],
        injuries_a=context.get("injuries_a") or [],
        injuries_b=context.get("injuries_b") or [],
        team_a_is_home=bool(context.get("team_a_is_home", True)),
        team_a_name=context.get("team_a_name") or "Team A",
        team_b_name=context.get("team_b_name") or "Team B",
        sport=str(context.get("sport") or "soccer"),
        opp_strengths=context.get("opp_strengths") or {},
    )


def _ui_prediction(
    context: dict[str, Any],
    rule_prediction: dict[str, Any],
    prob_a: float,
    prob_b: float,
    prob_draw: float,
    confidence_float: float,
) -> dict[str, Any]:
    sport = str(context.get("sport") or "soccer").lower()
    team_a_name = context.get("team_a_name") or "Team A"
    team_b_name = context.get("team_b_name") or "Team B"
    confidence_label = _confidence_label(confidence_float)

    ui = dict(rule_prediction or {})

    if sport == "soccer":
        win_probs = {
            "a": round(prob_a * 100.0, 1),
            "draw": round(prob_draw * 100.0, 1),
            "b": round(prob_b * 100.0, 1),
        }
    else:
        win_probs = {
            "a": round(prob_a * 100.0, 1),
            "b": round(prob_b * 100.0, 1),
        }

    ui["win_probabilities"] = win_probs
    ui["prob_a"] = win_probs.get("a", 0.0)
    ui["prob_b"] = win_probs.get("b", 0.0)
    ui["prob_draw"] = win_probs.get("draw", 0.0)
    ui["home_pct"] = win_probs.get("a", 0.0)
    ui["away_pct"] = win_probs.get("b", 0.0)
    ui["draw_pct"] = win_probs.get("draw", 0.0)
    ui["confidence"] = confidence_label

    if sport == "soccer" and win_probs.get("draw", 0.0) >= max(win_probs.get("a", 0.0), win_probs.get("b", 0.0)):
        winner_text = "Draw"
        winner_team = "draw"
    elif win_probs.get("a", 0.0) >= win_probs.get("b", 0.0):
        winner_text = f"{team_a_name} Win"
        winner_team = "A"
    else:
        winner_text = f"{team_b_name} Win"
        winner_team = "B"

    ui["winner_label"] = winner_text
    ui["best_pick"] = {
        "prediction": winner_text,
        "team": winner_team,
        "confidence": confidence_label,
        "reasoning": f"ScorMastermind blended ML, rule model, and heuristic context for this edge.",
    }
    return ui


def predict_match(context: dict[str, Any]) -> dict[str, Any]:
    """Return a unified prediction for soccer or NBA.

    Required context keys (flexible):
    - form_a, form_b, h2h_form_a, h2h_form_b
    - injuries_a, injuries_b
    - team_a_name, team_b_name
    - sport, team_a_is_home
    Optional:
    - ml_outputs, ml_report, team_stats, rule_prediction
    """
    sport = str(context.get("sport") or "soccer").lower()
    team_a_name = context.get("team_a_name") or "Team A"
    team_b_name = context.get("team_b_name") or "Team B"

    rule_prediction = context.get("rule_prediction") or _build_rule_prediction(context)
    rule_probs = rule_prediction.get("win_probabilities") or {}

    rule_prob_a_total = _clamp(_safe_float(rule_probs.get("a"), 50.0) / 100.0, 0.01, 0.99)
    rule_prob_b_total = _clamp(_safe_float(rule_probs.get("b"), 50.0) / 100.0, 0.01, 0.99)
    rule_prob_draw = _clamp(_safe_float(rule_probs.get("draw"), 0.0) / 100.0, 0.0, 0.6) if sport == "soccer" else 0.0

    ml = _ml_signal(context)
    heur = _heuristic_signal(context)

    if sport == "soccer":
        non_draw_total = max(0.01, rule_prob_a_total + rule_prob_b_total)
        rule_prob_a = _clamp(rule_prob_a_total / non_draw_total, 0.01, 0.99)
    else:
        rule_prob_a = rule_prob_a_total

    if ml.get("available"):
        combined_prob_a = _clamp(rule_prob_a * 0.65 + _safe_float(ml.get("prob_a"), 0.5) * 0.25 + _safe_float(heur.get("prob_a"), 0.5) * 0.10, 0.01, 0.99)
    else:
        combined_prob_a = _clamp(rule_prob_a * 0.88 + _safe_float(heur.get("prob_a"), 0.5) * 0.12, 0.01, 0.99)

    if sport == "soccer":
        prob_draw = rule_prob_draw
        prob_a = _clamp(combined_prob_a * (1.0 - prob_draw), 0.01, 0.98)
        prob_b = _clamp((1.0 - combined_prob_a) * (1.0 - prob_draw), 0.01, 0.98)
        norm = prob_a + prob_b + prob_draw
        prob_a, prob_b, prob_draw = prob_a / norm, prob_b / norm, prob_draw / norm
    else:
        prob_draw = 0.0
        prob_a = combined_prob_a
        prob_b = 1.0 - combined_prob_a

    has_forms = bool(context.get("form_a") and context.get("form_b"))
    stats = context.get("team_stats") or {}
    has_stats = bool((stats.get("a") or stats.get("team_a")) and (stats.get("b") or stats.get("team_b")))

    confidence = 0.45 + abs(prob_a - prob_b) * 0.75
    if not ml.get("available"):
        confidence -= 0.08
    if not has_forms:
        confidence -= 0.12
    if not has_stats:
        confidence -= 0.12
    confidence = _clamp(confidence, 0.05, 0.95)

    if sport == "soccer" and prob_draw >= max(prob_a, prob_b):
        winner = "Draw"
        winner_prob = prob_draw
    elif prob_a >= prob_b:
        winner = f"{team_a_name} Win"
        winner_prob = prob_a
    else:
        winner = f"{team_b_name} Win"
        winner_prob = prob_b

    explanation = {
        "ml_signal": {
            "available": bool(ml.get("available")),
            "source": ml.get("source", "missing_ml_data"),
            "prob_a": round(_safe_float(ml.get("prob_a"), 0.5), 4),
        },
        "rule_signal": {
            "winner": (rule_prediction.get("best_pick") or {}).get("prediction", ""),
            "probabilities": rule_probs,
            "confidence": (rule_prediction.get("best_pick") or {}).get("confidence", ""),
        },
        "top_features": ml.get("top_features") or [],
    }

    ui_prediction = _ui_prediction(
        context,
        rule_prediction,
        prob_a=prob_a,
        prob_b=prob_b,
        prob_draw=prob_draw,
        confidence_float=confidence,
    )

    outcomes: list[dict[str, Any]] = [
        {"team": "A", "prediction": f"{team_a_name} Win", "prob": prob_a},
        {"team": "B", "prediction": f"{team_b_name} Win", "prob": prob_b},
    ]
    if sport == "soccer":
        outcomes.append({"team": "draw", "prediction": "Draw", "prob": prob_draw})
    outcomes.sort(key=lambda item: _safe_float(item.get("prob"), 0.0), reverse=True)

    top_outcome = outcomes[0]
    second_outcome = outcomes[1] if len(outcomes) > 1 else outcomes[0]
    top_prob_pct = _safe_float(top_outcome.get("prob"), 0.0) * 100.0
    top_two_gap_pct = (_safe_float(top_outcome.get("prob"), 0.0) - _safe_float(second_outcome.get("prob"), 0.0)) * 100.0

    data_quality = str(rule_prediction.get("data_quality") or "Moderate")
    weak_data_quality = _is_weak_data_quality(data_quality)

    ml_prob_a = _safe_float(ml.get("prob_a"), 0.5)
    ml_side = "A" if ml_prob_a >= 0.58 else "B" if ml_prob_a <= 0.42 else ""
    rule_side = "A" if rule_prob_a >= 0.58 else "B" if rule_prob_a <= 0.42 else ""
    strong_signal_disagreement = bool(ml.get("available")) and bool(ml_side) and bool(rule_side) and ml_side != rule_side and abs(ml_prob_a - rule_prob_a) >= 0.20

    avoid_reasons: list[str] = []
    if top_prob_pct < 70.0:
        avoid_reasons.append("No strong edge found")
    if top_two_gap_pct < 4.0:
        avoid_reasons.append("Outcome probabilities are too close")
    if weak_data_quality:
        avoid_reasons.append("High uncertainty matchup")
    if strong_signal_disagreement:
        avoid_reasons.append("ML and rule signals disagree strongly")

    avoid_triggered = bool(avoid_reasons)
    top_lean = {
        "team": top_outcome.get("team"),
        "prediction": top_outcome.get("prediction"),
        "probability": round(top_prob_pct, 1),
        "display": f"Top lean: {top_outcome.get('prediction')} ({top_prob_pct:.1f}%)",
    }

    best_pick = ui_prediction.get("best_pick") or {}
    if avoid_triggered:
        reason = avoid_reasons[0]
        best_pick["prediction"] = "Avoid"
        best_pick["team"] = "avoid"
        best_pick["tracking_team"] = top_outcome.get("team")
        best_pick["confidence"] = "Low"
        best_pick["reasoning"] = reason
        ui_prediction["confidence"] = "Low"
        ui_prediction["recommended_play"] = "Avoid"
        ui_prediction["avoid_reasons"] = avoid_reasons
        ui_prediction["top_lean"] = top_lean
        ui_prediction["risk_label"] = "Elevated"
    else:
        best_pick["tracking_team"] = best_pick.get("team") or top_outcome.get("team")
        ui_prediction["recommended_play"] = best_pick.get("prediction") or top_outcome.get("prediction")
        ui_prediction["avoid_reasons"] = []
        ui_prediction["top_lean"] = top_lean

    ui_prediction["best_pick"] = best_pick

    return {
        "winner": winner,
        "probability": round(winner_prob, 4),
        "confidence": round(confidence, 4),
        "explanation": explanation,
        "ui_prediction": ui_prediction,
        "rule_prediction": rule_prediction,
    }
