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
import re
from utils.parsing import normalize_date

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


def _load_predictions() -> list[dict]:
    """Load all tracked predictions."""
    _ensure_tracking_file()
    try:
        with open(_TRACKING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        predictions = data.get("predictions", []) if isinstance(data, dict) else []
        changed = False
        for pred in predictions:
            if pred.get("status") == "completed":
                changed = _apply_grading(pred) or changed
        if changed:
            with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
                json.dump({"predictions": predictions}, f, indent=2)
        return predictions
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


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _canonical_outcome(value: Any, team_a: str, team_b: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""

    draw_aliases = {
        "draw",
        "d",
        "x",
        "tie",
        "tied",
        "stalemate",
        "home/away draw",
    }
    if text in draw_aliases:
        return "draw"

    if text in {"a", "home", "home win", "homewin", "1", "team a", "teama"}:
        return "A"
    if text in {"b", "away", "away win", "awaywin", "2", "team b", "teamb"}:
        return "B"

    norm_a = _normalize_text(team_a)
    norm_b = _normalize_text(team_b)
    if norm_a and (text == norm_a or f"{norm_a} win" in text):
        return "A"
    if norm_b and (text == norm_b or f"{norm_b} win" in text):
        return "B"

    return ""


def _canonical_total_pick(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    if text in {"over", "o", "ov", "over 2.5", "over 220.5"}:
        return "Over"
    if text in {"under", "u", "un", "under 2.5", "under 220.5"}:
        return "Under"
    return ""


def _actual_result_from_score(final_score: dict | None) -> str:
    if not isinstance(final_score, dict):
        return ""
    a_score = final_score.get("a")
    b_score = final_score.get("b")
    if a_score is None or b_score is None:
        return ""
    try:
        a_val = int(a_score)
        b_val = int(b_score)
    except (TypeError, ValueError):
        return ""
    if a_val > b_val:
        return "A"
    if b_val > a_val:
        return "B"
    return "draw"


def _totals_line_for_sport(sport: str) -> float:
    return 220.5 if sport == "nba" else 2.5


def _apply_grading(pred: dict[str, Any]) -> bool:
    """Recompute winner/totals/overall grading for one prediction record."""
    changed = False
    sport = str(pred.get("sport") or "").lower()
    team_a = str(pred.get("team_a") or "")
    team_b = str(pred.get("team_b") or "")
    final_score = pred.get("final_score") if isinstance(pred.get("final_score"), dict) else None

    predicted_outcome = _canonical_outcome(pred.get("predicted_winner"), team_a, team_b)
    actual_outcome = _canonical_outcome(pred.get("actual_result"), team_a, team_b)
    if not actual_outcome:
        actual_outcome = _actual_result_from_score(final_score)

    winner_hit: bool | None
    if predicted_outcome and actual_outcome:
        winner_hit = predicted_outcome == actual_outcome
    else:
        winner_hit = None

    total_scored: int | None = None
    if final_score:
        a_score = final_score.get("a")
        b_score = final_score.get("b")
        if isinstance(a_score, (int, float)) and isinstance(b_score, (int, float)):
            total_scored = int(a_score) + int(b_score)

    ou_line = _totals_line_for_sport(sport)
    actual_total_side = ""
    if total_scored is not None:
        if total_scored > ou_line:
            actual_total_side = "Over"
        elif total_scored < ou_line:
            actual_total_side = "Under"
        else:
            actual_total_side = "Push"

    predicted_total_side = _canonical_total_pick(
        pred.get("predicted_total_pick")
        or pred.get("predicted_ou")
        or pred.get("ou_pick")
    )

    totals_hit: bool | None
    if predicted_total_side and actual_total_side in {"Over", "Under"}:
        totals_hit = predicted_total_side == actual_total_side
    else:
        totals_hit = None

    if winner_hit is True:
        if totals_hit is False:
            overall_result = "Partial"
        else:
            overall_result = "Win"
    elif winner_hit is False:
        if totals_hit is True:
            overall_result = "Partial"
        else:
            overall_result = "Loss"
    else:
        overall_result = "Pending"

    winner_display = "Winner Pick: Pending"
    if winner_hit is True:
        winner_display = "Winner Pick: Hit"
    elif winner_hit is False:
        winner_display = "Winner Pick: Miss"

    totals_display = "Totals Pick: Not tracked"
    if predicted_total_side:
        if actual_total_side == "Push":
            totals_display = f"Totals Pick ({predicted_total_side} {ou_line}): Push"
        elif totals_hit is True:
            totals_display = f"Totals Pick ({predicted_total_side} {ou_line}): Hit"
        elif totals_hit is False:
            totals_display = f"Totals Pick ({predicted_total_side} {ou_line}): Miss"
        else:
            totals_display = "Totals Pick: Pending"

    if final_score and isinstance(final_score, dict):
        final_score_display = f"{final_score.get('a', 0)}-{final_score.get('b', 0)}"
    else:
        final_score_display = "Unknown"

    if actual_outcome == "A":
        actual_winner = team_a or "Unknown"
    elif actual_outcome == "B":
        actual_winner = team_b or "Unknown"
    elif actual_outcome == "draw":
        actual_winner = "Draw"
    else:
        actual_winner = "Unknown"

    updates: dict[str, Any] = {
        "predicted_winner_normalized": predicted_outcome,
        "actual_result_normalized": actual_outcome,
        "winner_hit": winner_hit,
        "is_correct": winner_hit,
        "winner_display": winner_display,
        "actual_winner": actual_winner,
        "total_scored": total_scored,
        "total_label": f"Total {'Points' if sport == 'nba' else 'Goals'}: {total_scored}" if total_scored is not None else "",
        "ou_line": ou_line,
        "ou_result": actual_total_side,
        "totals_hit": totals_hit,
        "ou_hit": totals_hit,
        "ou_display": totals_display,
        "final_score_display": final_score_display,
        "game_win": bool(winner_hit) if winner_hit is not None else False,
        "overall_game_result": overall_result,
    }

    for key, value in updates.items():
        if pred.get(key) != value:
            pred[key] = value
            changed = True

    return changed


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
    
    game_date_normalized = normalize_date(game_date)
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
            pred["status"] = "completed"
            pred["final_score"] = final_score
            _apply_grading(pred)
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
        _apply_grading(pred)
    
    return completed
