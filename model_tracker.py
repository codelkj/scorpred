"""
model_tracker.py — Lightweight prediction tracking and performance metrics.

Stores predictions in JSON format for easy inspection and analysis.
Provides functions to save, update, and summarize model performance.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
import uuid

_TRACKING_FILE = os.path.join(os.path.dirname(__file__), "cache", "prediction_tracking.json")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_tracking_file() -> None:
    """Create tracking file if it doesn't exist."""
    if os.path.exists(_TRACKING_FILE):
        # Migrate existing predictions to add status field
        _migrate_predictions()
        return
    folder = os.path.dirname(_TRACKING_FILE)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump({"predictions": []}, f, indent=2)


def _migrate_predictions() -> None:
    """Migrate existing predictions to add status field if missing."""
    try:
        with open(_TRACKING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        predictions = data.get("predictions", [])
        migrated = False
        
        for pred in predictions:
            if "status" not in pred:
                # Set status based on whether result is known
                if pred.get("is_correct") is not None:
                    pred["status"] = "completed"
                else:
                    pred["status"] = "pending"
                migrated = True
        
        if migrated:
            with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
                json.dump({"predictions": predictions}, f, indent=2)
    except Exception:
        pass  # Silent fail if migration fails


def _normalize_date(date_str: str | None) -> str | None:
    """Return YYYY-MM-DD for any date-like string, or None if missing."""
    if not date_str:
        return None
    try:
        return str(date_str)[:10]
    except Exception:
        return None


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


def _get_game_key(sport: str, date: str, team_a: str, team_b: str) -> str:
    """Generate a unique key for a game to prevent duplicates."""
    # Normalize teams by sorting alphabetically
    teams = sorted([team_a.lower().strip(), team_b.lower().strip()])
    return f"{sport.lower()}|{date}|{teams[0]}|{teams[1]}"


def save_prediction(
    sport: str,
    team_a: str,
    team_b: str,
    predicted_winner: str,  # "A" | "B" | "draw"
    win_probs: dict[str, float],  # {"a": x, "b": y, "draw": z}
    confidence: str,  # "High" | "Medium" | "Low"
    game_date: str | None = None,
    team_a_id: str | int | None = None,
    team_b_id: str | int | None = None,
    league_id: int | None = None,
    season: int | None = None,
) -> str:
    """
    Save a new prediction to the tracking file.
    
    Returns the prediction ID for later updates.
    Checks for duplicates based on sport, date, and teams.
    If a duplicate exists, returns the existing ID without saving.
    If no concrete game date is available, the prediction is not tracked.
    """
    predictions = _load_predictions()
    
    game_date_normalized = _normalize_date(game_date)
    if not game_date_normalized:
        return ""
    game_key = _get_game_key(sport, game_date_normalized, team_a, team_b)
    
    # Check for existing prediction with same game key
    for existing in predictions:
        existing_key = _get_game_key(
            existing.get("sport", ""),
            existing.get("date", ""),
            existing.get("team_a", ""),
            existing.get("team_b", "")
        )
        if existing_key == game_key:
            # Duplicate found, return existing ID without saving new one
            return existing.get("id", "")
    
    pred_id = str(uuid.uuid4())[:8]
    now = _utc_now().isoformat().replace("+00:00", "Z")
    
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
        "status": "pending",
        "actual_result": None,
        "is_correct": None,
        "created_at": now,
        "updated_at": now,
    }
    if team_a_id is not None:
        prediction["team_a_id"] = str(team_a_id)
    if team_b_id is not None:
        prediction["team_b_id"] = str(team_b_id)
    if league_id is not None:
        prediction["league_id"] = int(league_id)
    if season is not None:
        prediction["season"] = int(season)
    
    predictions.append(prediction)
    _save_predictions(predictions)
    
    return pred_id


def clean_duplicate_predictions() -> int:
    """
    Remove duplicate predictions, keeping the most recent one for each game.
    
    Returns the number of duplicates removed.
    """
    predictions = _load_predictions()
    seen_keys = {}
    to_keep = []
    removed = 0
    
    # Sort by updated_at descending to keep the latest
    predictions.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    
    for pred in predictions:
        game_key = _get_game_key(
            pred.get("sport", ""),
            pred.get("date", ""),
            pred.get("team_a", ""),
            pred.get("team_b", "")
        )
        if game_key not in seen_keys:
            seen_keys[game_key] = True
            to_keep.append(pred)
        else:
            removed += 1
    
    if removed > 0:
        _save_predictions(to_keep)
    
    return removed


def update_prediction_result(pred_id: str, actual_result: str, final_score: dict | None = None) -> bool:
    """
    Update a prediction with the actual game result and final score.
    
    Args:
        pred_id: The prediction ID returned from save_prediction()
        actual_result: "A" | "B" | "draw"
        final_score: Optional dict with {"a": int, "b": int} for the final score
    
    Returns True if updated, False if prediction not found.
    """
    predictions = _load_predictions()
    
    for pred in predictions:
        if pred.get("id") == pred_id:
            pred["actual_result"] = actual_result
            pred["is_correct"] = (pred.get("predicted_winner") == actual_result)
            pred["status"] = "completed"
            pred["final_score"] = final_score
            pred["updated_at"] = _utc_now().isoformat().replace("+00:00", "Z")
            _save_predictions(predictions)
            return True
    
    return False


def get_summary_metrics() -> dict[str, Any]:
    """
    Compute summary metrics across tracked winner predictions.

    Completed predictions are graded from the persisted winner outcome stored in
    `is_correct`, which is the source of truth for dashboard accuracy.
    
    Returns:
        {
            "total_predictions": int,
            "finalized_predictions": int,
            "wins": int,
            "losses": int,
            "overall_accuracy": float,  # 0-100%
            "by_confidence": {
                "High": {"accuracy": float, "count": int, "wins": int, "losses": int},
                "Medium": {"accuracy": float, "count": int, "wins": int, "losses": int},
                "Low": {"accuracy": float, "count": int, "wins": int, "losses": int},
            },
            "by_sport": {
                "soccer": {"accuracy": float, "count": int, "wins": int, "losses": int},
                "nba": {"accuracy": float, "count": int, "wins": int, "losses": int},
            },
            "recent_predictions": list  # Last 10
        }
    """
    predictions = _load_predictions()
    
    if not predictions:
        return {
            "total_predictions": 0,
            "finalized_predictions": 0,
            "wins": 0,
            "losses": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "recent_predictions": [],
        }

    # Filter to only finalized predictions with an actual graded outcome.
    finalized = [
        p for p in predictions
        if p.get("status") == "completed" and p.get("is_correct") is not None
    ]

    if not finalized:
        return {
            "total_predictions": len(predictions),
            "finalized_predictions": 0,
            "wins": 0,
            "losses": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "recent_predictions": sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:10],
        }
    
    def is_game_win(pred: dict[str, Any]) -> bool:
        if pred.get("is_correct") is not None:
            return bool(pred.get("is_correct"))
        if pred.get("winner_hit") is not None:
            return bool(pred.get("winner_hit"))
        if pred.get("game_win") is not None:
            return bool(pred.get("game_win"))
        return False
    
    wins = sum(1 for p in finalized if is_game_win(p))
    losses = len(finalized) - wins
    overall_accuracy = (wins / len(finalized)) * 100 if finalized else 0
    
    # By confidence level
    by_confidence = {}
    for conf_level in ("High", "Medium", "Low"):
        conf_preds = [p for p in finalized if p.get("confidence") == conf_level]
        if conf_preds:
            conf_wins = sum(1 for p in conf_preds if is_game_win(p))
            conf_losses = len(conf_preds) - conf_wins
            by_confidence[conf_level] = {
                "accuracy": round((conf_wins / len(conf_preds)) * 100, 1) if conf_preds else 0,
                "count": len(conf_preds),
                "wins": conf_wins,
                "losses": conf_losses,
            }
    
    # By sport
    by_sport = {}
    for sport in ("soccer", "nba"):
        sport_preds = [p for p in finalized if p.get("sport") == sport]
        if sport_preds:
            sport_wins = sum(1 for p in sport_preds if is_game_win(p))
            sport_losses = len(sport_preds) - sport_wins
            by_sport[sport] = {
                "accuracy": round((sport_wins / len(sport_preds)) * 100, 1) if sport_preds else 0,
                "count": len(sport_preds),
                "wins": sport_wins,
                "losses": sport_losses,
            }
    
    return {
        "total_predictions": len(predictions),
        "finalized_predictions": len(finalized),
        "wins": wins,
        "losses": losses,
        "overall_accuracy": round(overall_accuracy, 1),
        "by_confidence": by_confidence,
        "by_sport": by_sport,
        "recent_predictions": sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:10],
    }


def get_recent_predictions(limit: int = 20) -> list[dict]:
    """Get the most recent predictions (finalized or not)."""
    predictions = _load_predictions()
    return sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:limit]


def get_pending_predictions(limit: int = 20) -> list[dict]:
    """Get the most recent pending predictions."""
    predictions = _load_predictions()
    pending = [p for p in predictions if p.get("status") != "completed"]
    return sorted(pending, key=lambda p: p.get("created_at", ""), reverse=True)[:limit]


def get_completed_predictions(limit: int = 50) -> list[dict]:
    """
    Get completed predictions with detailed result information.
    
    Returns predictions with status="completed" including:
    - Final score
    - Total scored (goals/points)
    - Over/Under result
    - Winner pick result
    """
    predictions = _load_predictions()
    completed = [p for p in predictions if p.get("status") == "completed"]
    
    # Sort by most recent first
    completed = sorted(completed, key=lambda p: p.get("updated_at", ""), reverse=True)[:limit]
    
    # Enhance with calculated fields
    for pred in completed:
        sport = pred.get("sport", "").lower()
        final_score = pred.get("final_score", {})
        
        # Calculate total scored
        if final_score and isinstance(final_score, dict):
            if sport == "soccer":
                total_goals = final_score.get("a", 0) + final_score.get("b", 0)
                pred["total_scored"] = total_goals
                pred["total_label"] = f"Total Goals: {total_goals}"
                
                # Determine O/U result (using 2.5 as default line)
                ou_line = 2.5
                if total_goals > ou_line:
                    pred["ou_result"] = "Over"
                    pred["ou_hit"] = True
                else:
                    pred["ou_result"] = "Under" 
                    pred["ou_hit"] = False
                pred["ou_display"] = f"U/O {ou_line}: {'Hit' if pred['ou_hit'] else 'Miss'}"
                
            elif sport == "nba":
                total_points = final_score.get("a", 0) + final_score.get("b", 0)
                pred["total_scored"] = total_points
                pred["total_label"] = f"Total Points: {total_points}"
                
                # For NBA, use a dynamic line based on typical NBA totals
                # This is a simple approximation - in reality you'd want historical data
                ou_line = 220.5  # Default NBA total line
                if total_points > ou_line:
                    pred["ou_result"] = "Over"
                    pred["ou_hit"] = True
                else:
                    pred["ou_result"] = "Under"
                    pred["ou_hit"] = False
                pred["ou_display"] = f"U/O {ou_line}: {'Hit' if pred['ou_hit'] else 'Miss'}"
        
        # Format final score display
        if final_score and isinstance(final_score, dict):
            pred["final_score_display"] = f"{final_score.get('a', 0)}-{final_score.get('b', 0)}"
        else:
            pred["final_score_display"] = "Unknown"
        
        # Determine actual winner
        actual_result = pred.get("actual_result", "")
        if actual_result == "A":
            pred["actual_winner"] = pred.get("team_a", "Unknown")
        elif actual_result == "B":
            pred["actual_winner"] = pred.get("team_b", "Unknown")
        elif actual_result == "draw":
            pred["actual_winner"] = "Draw"
        else:
            pred["actual_winner"] = "Unknown"
        
        # Winner pick result
        pred["winner_hit"] = pred.get("is_correct", False)
        pred["winner_display"] = f"Winner Pick: {'Hit' if pred['winner_hit'] else 'Miss'}"
        
        # The tracked prediction is the winner pick. Totals are shown as context,
        # but dashboard grading should follow the actual persisted winner result.
        pred["game_win"] = pred["winner_hit"]
        pred["overall_game_result"] = "Win" if pred["game_win"] else "Loss"
    
    return completed
