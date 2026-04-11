"""
model_tracker.py — Lightweight prediction tracking and performance metrics.

Stores predictions in JSON format for easy inspection and analysis.
Provides functions to save, update, and summarize model performance.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
import uuid

_TRACKING_FILE = os.path.join(os.path.dirname(__file__), "cache", "prediction_tracking.json")


def _ensure_tracking_file() -> None:
    """Create tracking file if it doesn't exist."""
    if os.path.exists(_TRACKING_FILE):
        return
    folder = os.path.dirname(_TRACKING_FILE)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump({"predictions": []}, f, indent=2)


def _normalize_date(date_str: str | None) -> str:
    """Return YYYY-MM-DD for any date-like string, or today if missing."""
    if not date_str:
        return datetime.utcnow().strftime("%Y-%m-%d")
    try:
        return str(date_str)[:10]
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def _load_predictions() -> list[dict]:
    """Load all tracked predictions."""
    _ensure_tracking_file()
    try:
        with open(_TRACKING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("predictions", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_predictions(predictions: list[dict]) -> None:
    """Save predictions to file."""
    try:
        _ensure_tracking_file()
        with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
            json.dump({"predictions": predictions}, f, indent=2)
    except Exception as e:
        pass  # Silent fail if file can't be written


def save_prediction(
    sport: str,
    team_a: str,
    team_b: str,
    predicted_winner: str,  # "A" | "B" | "draw"
    win_probs: dict[str, float],  # {"a": x, "b": y, "draw": z}
    confidence: str,  # "High" | "Medium" | "Low"
    game_date: str | None = None,
) -> str:
    """
    Save a new prediction to the tracking file.
    
    Returns the prediction ID for later updates.
    """
    predictions = _load_predictions()
    
    pred_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat() + "Z"
    game_date_normalized = _normalize_date(game_date)
    
    prediction = {
        "id": pred_id,
        "sport": sport,
        "date": game_date_normalized,
        "game_date": game_date_normalized,
        "team_a": team_a,
        "team_b": team_b,
        "predicted_winner": predicted_winner,
        "prob_a": round(win_probs.get("a", 0), 1),
        "prob_b": round(win_probs.get("b", 0), 1),
        "prob_draw": round(win_probs.get("draw", 0), 1),
        "confidence": confidence,
        "actual_result": None,
        "is_correct": None,
        "created_at": now,
        "updated_at": now,
    }
    
    predictions.append(prediction)
    _save_predictions(predictions)
    
    return pred_id


def update_prediction_result(pred_id: str, actual_result: str) -> bool:
    """
    Update a prediction with the actual game result.
    
    Args:
        pred_id: The prediction ID returned from save_prediction()
        actual_result: "A" | "B" | "draw"
    
    Returns True if updated, False if prediction not found.
    """
    predictions = _load_predictions()
    
    for pred in predictions:
        if pred.get("id") == pred_id:
            pred["actual_result"] = actual_result
            pred["is_correct"] = (pred.get("predicted_winner") == actual_result)
            pred["updated_at"] = datetime.utcnow().isoformat() + "Z"
            _save_predictions(predictions)
            return True
    
    return False


def get_summary_metrics() -> dict[str, Any]:
    """
    Compute summary metrics across all predictions.
    
    Returns:
        {
            "total_predictions": int,
            "overall_accuracy": float,  # 0-100%
            "by_confidence": {
                "High": {"accuracy": float, "count": int},
                "Medium": {"accuracy": float, "count": int},
                "Low": {"accuracy": float, "count": int},
            },
            "by_sport": {
                "soccer": {"accuracy": float, "count": int},
                "nba": {"accuracy": float, "count": int},
            },
            "recent_predictions": list  # Last 10
        }
    """
    predictions = _load_predictions()
    
    if not predictions:
        return {
            "total_predictions": 0,
            "finalized_predictions": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "recent_predictions": [],
        }

    # Filter to only finalized predictions
    finalized = [p for p in predictions if p.get("is_correct") is not None]

    if not finalized:
        return {
            "total_predictions": len(predictions),
            "finalized_predictions": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "recent_predictions": sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:10],
        }
    
    # Overall accuracy
    correct_count = sum(1 for p in finalized if p.get("is_correct"))
    overall_accuracy = (correct_count / len(finalized)) * 100 if finalized else 0
    
    # By confidence level
    by_confidence = {}
    for conf_level in ("High", "Medium", "Low"):
        conf_preds = [p for p in finalized if p.get("confidence") == conf_level]
        if conf_preds:
            conf_correct = sum(1 for p in conf_preds if p.get("is_correct"))
            by_confidence[conf_level] = {
                "accuracy": round((conf_correct / len(conf_preds)) * 100, 1),
                "count": len(conf_preds),
            }
    
    # By sport
    by_sport = {}
    for sport in ("soccer", "nba"):
        sport_preds = [p for p in finalized if p.get("sport") == sport]
        if sport_preds:
            sport_correct = sum(1 for p in sport_preds if p.get("is_correct"))
            by_sport[sport] = {
                "accuracy": round((sport_correct / len(sport_preds)) * 100, 1),
                "count": len(sport_preds),
            }
    
    return {
        "total_predictions": len(predictions),
        "finalized_predictions": len(finalized),
        "overall_accuracy": round(overall_accuracy, 1),
        "by_confidence": by_confidence,
        "by_sport": by_sport,
        "recent_predictions": sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:10],
    }


def get_recent_predictions(limit: int = 20) -> list[dict]:
    """Get the most recent predictions (finalized or not)."""
    predictions = _load_predictions()
    return sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:limit]
