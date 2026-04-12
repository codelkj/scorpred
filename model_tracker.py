"""
model_tracker.py — Lightweight prediction tracking and performance metrics.

Stores predictions in JSON format for easy inspection and analysis.
Provides functions to save, update, and summarize model performance.
"""

from __future__ import annotations

import json
import os
import re
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

            if "prediction_market" not in pred:
                pred["prediction_market"] = "winner"
                migrated = True

            if "fixture_id" not in pred:
                pred["fixture_id"] = None
                migrated = True

            original_pick = pred.get("predicted_winner")
            normalized_pick = _winner_choice_code(
                original_pick,
                pred.get("team_a", ""),
                pred.get("team_b", ""),
            )
            if normalized_pick and pred.get("predicted_winner") != normalized_pick:
                pred["predicted_winner"] = normalized_pick
                migrated = True

            display_pick = _prediction_label_from_value(
                pred.get("predicted_pick_label") or original_pick,
                pred.get("team_a", ""),
                pred.get("team_b", ""),
            )
            if pred.get("predicted_pick_label") != display_pick:
                pred["predicted_pick_label"] = display_pick
                migrated = True

            actual_result = pred.get("actual_result")
            normalized_actual = _winner_choice_code(
                actual_result,
                pred.get("team_a", ""),
                pred.get("team_b", ""),
            )
            if actual_result and normalized_actual and actual_result != normalized_actual:
                pred["actual_result"] = normalized_actual
                migrated = True

            if pred.get("status") == "completed" or pred.get("actual_result"):
                outcome = _compute_prediction_outcome(pred)
                if pred.get("is_correct") != outcome["winner_hit"]:
                    pred["is_correct"] = outcome["winner_hit"]
                    migrated = True
                if pred.get("actual_winner") != outcome["actual_winner"]:
                    pred["actual_winner"] = outcome["actual_winner"]
                    migrated = True
                if pred.get("winner_result") != outcome["winner_result"]:
                    pred["winner_result"] = outcome["winner_result"]
                    migrated = True
                if pred.get("totals_result") != outcome["totals_result"]:
                    pred["totals_result"] = outcome["totals_result"]
                    migrated = True
                if pred.get("overall_result") != outcome["overall_result"]:
                    pred["overall_result"] = outcome["overall_result"]
                    migrated = True
        
        if migrated:
            with open(_TRACKING_FILE, "w", encoding="utf-8") as f:
                json.dump({"predictions": predictions}, f, indent=2)
    except Exception:
        pass  # Silent fail if migration fails


def _normalize_date(date_str: str | None) -> str:
    """Return YYYY-MM-DD for any date-like string, or today if missing."""
    if not date_str:
        return _utc_now().strftime("%Y-%m-%d")
    try:
        return str(date_str)[:10]
    except Exception:
        return _utc_now().strftime("%Y-%m-%d")


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


def _get_game_key(
    sport: str,
    date: str,
    team_a: str,
    team_b: str,
    league_id: int | None = None,
) -> str:
    """Generate a unique key for a game to prevent duplicates.

    Strict dedupe requires sport, date, home_team, and away_team to match exactly.
    """
    parts = [sport.lower().strip()]
    if sport.lower().strip() == "soccer" and league_id is not None:
        parts.append(str(league_id))
    parts.extend([str(date)[:10], team_a.lower().strip(), team_b.lower().strip()])
    return "|".join(parts)


def _normalized_text(value: str | None) -> str:
    """Return a lowercase, alphanumeric-only token stream for fuzzy comparisons."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _winner_choice_code(value: str | None, team_a: str = "", team_b: str = "") -> str:
    """Normalize raw winner labels into canonical tracking codes A/B/draw."""
    text = _normalized_text(value)
    if not text:
        return ""

    if text in {"a", "team a", "home", "home win"}:
        return "A"
    if text in {"b", "team b", "away", "away win"}:
        return "B"
    if text in {"draw", "tie", "x"} or "draw" in text or "tie" in text:
        return "draw"

    team_a_norm = _normalized_text(team_a)
    team_b_norm = _normalized_text(team_b)
    if team_a_norm and (text == team_a_norm or text == f"{team_a_norm} win" or text.startswith(f"{team_a_norm} ")):
        return "A"
    if team_b_norm and (text == team_b_norm or text == f"{team_b_norm} win" or text.startswith(f"{team_b_norm} ")):
        return "B"
    return ""


def _prediction_label_from_value(value: str | None, team_a: str = "", team_b: str = "") -> str:
    """Convert a raw stored pick into a clean human-readable winner label."""
    choice = _winner_choice_code(value, team_a, team_b)
    if choice == "A":
        return team_a or "Team A"
    if choice == "B":
        return team_b or "Team B"
    if choice == "draw":
        return "Draw"

    text = str(value or "").strip()
    if text.lower().endswith(" win"):
        text = text[:-4].strip()
    return text or "Unknown"


def _compute_prediction_outcome(prediction: dict) -> dict:
    """Compute winner/totals display values for a completed prediction.

    ScorPred currently stores winner picks only (A/B/draw). Totals are informative
    and should not change whether the prediction is graded correct.
    """
    sport = (prediction.get("sport") or "").lower()
    final_score = prediction.get("final_score") or {}
    actual_result = _winner_choice_code(
        prediction.get("actual_result"),
        prediction.get("team_a", ""),
        prediction.get("team_b", ""),
    )
    predicted_winner = _winner_choice_code(
        prediction.get("predicted_winner"),
        prediction.get("team_a", ""),
        prediction.get("team_b", ""),
    )

    winner_hit = bool(actual_result and predicted_winner and actual_result == predicted_winner)
    actual_winner = prediction.get("actual_winner") or "Unknown"
    if actual_result == "A":
        actual_winner = prediction.get("team_a", "Unknown")
    elif actual_result == "B":
        actual_winner = prediction.get("team_b", "Unknown")
    elif actual_result == "draw":
        actual_winner = "Draw"

    total_line = 2.5 if sport == "soccer" else 220.5
    totals_hit = True
    totals_result = None
    ou_display = None
    total_scored = None

    if isinstance(final_score, dict) and "a" in final_score and "b" in final_score:
        total_scored = final_score.get("a", 0) + final_score.get("b", 0)
        totals_hit = total_scored > total_line
        totals_result = "Over" if totals_hit else "Under"
        ou_display = f"U/O {total_line}: {'Hit' if totals_hit else 'Miss'}"

    game_win = winner_hit
    overall_result = "Win" if game_win else "Loss"
    winner_result = "Hit" if winner_hit else "Miss"

    return {
        "winner_hit": winner_hit,
        "actual_winner": actual_winner,
        "winner_result": winner_result,
        "totals_result": totals_result,
        "totals_hit": totals_hit,
        "ou_display": ou_display,
        "game_win": game_win,
        "overall_result": overall_result,
        "total_scored": total_scored,
    }


def _display_predicted_winner(prediction: dict) -> str:
    """Return a human-readable predicted winner label for a stored prediction."""
    if prediction.get("predicted_pick_label"):
        return str(prediction.get("predicted_pick_label") or "Unknown")
    return _prediction_label_from_value(
        prediction.get("predicted_winner"),
        prediction.get("team_a", ""),
        prediction.get("team_b", ""),
    )


def _enhance_prediction_record(prediction: dict) -> dict:
    """Return a copy of a prediction with derived display fields."""
    pred = dict(prediction or {})
    sport = str(pred.get("sport") or "").lower()
    final_score = pred.get("final_score", {})

    pred["prediction_market"] = str(pred.get("prediction_market") or "winner").lower()
    pred["predicted_winner_display"] = _display_predicted_winner(pred)
    pred["predicted_winner_code"] = _winner_choice_code(
        pred.get("predicted_winner"),
        pred.get("team_a", ""),
        pred.get("team_b", ""),
    )

    if isinstance(final_score, dict) and "a" in final_score and "b" in final_score:
        total_value = final_score.get("a", 0) + final_score.get("b", 0)
        pred["total_scored"] = total_value
        pred["total_label"] = (
            f"Total Goals: {total_value}" if sport == "soccer" else f"Total Points: {total_value}"
        )
        pred["final_score_display"] = f"{final_score.get('a', 0)}-{final_score.get('b', 0)}"
    else:
        pred["final_score_display"] = "Unknown"

    outcome = _compute_prediction_outcome(pred)
    pred["actual_winner"] = outcome["actual_winner"]
    pred["winner_hit"] = outcome["winner_hit"]
    pred["winner_display"] = f"Winner Pick: {'Hit' if outcome['winner_hit'] else 'Miss'}"
    pred["ou_result"] = outcome["totals_result"]
    pred["ou_hit"] = outcome["totals_hit"]
    pred["ou_display"] = outcome["ou_display"]
    pred["game_win"] = outcome["game_win"]
    pred["overall_game_result"] = outcome["overall_result"]

    return pred


def save_prediction(
    sport: str,
    team_a: str,
    team_b: str,
    predicted_winner: str,  # "A" | "B" | "draw"
    win_probs: dict[str, float],  # {"a": x, "b": y, "draw": z}
    confidence: str,  # "High" | "Medium" | "Low"
    game_date: str | None = None,
    league_id: int | None = None,
    league_name: str | None = None,
    prediction_notes: str | None = None,
    model_factors: dict[str, Any] | None = None,
    fixture_id: str | int | None = None,
    prediction_market: str = "winner",
) -> str:
    """
    Save or update a prediction in the tracking file.
    
    Returns the prediction ID for later updates.
    If a matching game already exists, update the existing record instead of creating a duplicate.
    """
    predictions = _load_predictions()
    normalized_pick = _winner_choice_code(predicted_winner, team_a, team_b) or str(predicted_winner or "").strip()
    predicted_pick_label = _prediction_label_from_value(predicted_winner, team_a, team_b)
    normalized_market = str(prediction_market or "winner").strip().lower() or "winner"
    fixture_id_value = str(fixture_id).strip() if fixture_id is not None and str(fixture_id).strip() else None
    
    game_date_normalized = _normalize_date(game_date)
    game_key = _get_game_key(sport, game_date_normalized, team_a, team_b, league_id)
    
    # Check for existing prediction with same game key
    for existing in predictions:
        existing_key = _get_game_key(
            existing.get("sport", ""),
            existing.get("date", ""),
            existing.get("team_a", ""),
            existing.get("team_b", ""),
            existing.get("league_id"),
        )
        if existing_key == game_key:
            if existing.get("status") != "completed":
                existing["predicted_winner"] = normalized_pick
                existing["predicted_pick_label"] = predicted_pick_label
                existing["prob_a"] = round(win_probs.get("a", 0), 1)
                existing["prob_b"] = round(win_probs.get("b", 0), 1)
                existing["prob_draw"] = round(win_probs.get("draw", 0), 1)
                existing["confidence"] = confidence
                existing["prediction_market"] = normalized_market
                existing["status"] = "pending"
                existing["actual_result"] = None
                existing["is_correct"] = None
                existing["final_score"] = None
                existing["actual_winner"] = None
                existing["winner_result"] = None
                existing["totals_result"] = None
                existing["overall_result"] = None
                existing["league_id"] = league_id
                existing["league_name"] = league_name
                existing["fixture_id"] = fixture_id_value
                existing["prediction_notes"] = prediction_notes
                existing["model_factors"] = model_factors if isinstance(model_factors, dict) else {}
                existing["updated_at"] = _utc_now().isoformat().replace("+00:00", "Z")
                _save_predictions(predictions)
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
        "predicted_winner": normalized_pick,
        "predicted_pick_label": predicted_pick_label,
        "prob_a": round(win_probs.get("a", 0), 1),
        "prob_b": round(win_probs.get("b", 0), 1),
        "prob_draw": round(win_probs.get("draw", 0), 1),
        "confidence": confidence,
        "prediction_market": normalized_market,
        "league_id": league_id,
        "league_name": league_name,
        "fixture_id": fixture_id_value,
        "prediction_notes": prediction_notes,
        "model_factors": model_factors if isinstance(model_factors, dict) else {},
        "status": "pending",
        "actual_result": None,
        "is_correct": None,
        "final_score": None,
        "actual_winner": None,
        "winner_result": None,
        "totals_result": None,
        "overall_result": None,
        "created_at": now,
        "updated_at": now,
    }
    
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
            pred.get("team_b", ""),
            pred.get("league_id"),
        )
        if game_key not in seen_keys:
            seen_keys[game_key] = True
            to_keep.append(pred)
        else:
            removed += 1
    
    if removed > 0:
        _save_predictions(to_keep)
    
    return removed


def update_prediction_result(
    pred_id: str,
    actual_result: str,
    final_score: dict | None = None,
    fixture_id: str | int | None = None,
) -> bool:
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
            pred["actual_result"] = _winner_choice_code(
                actual_result,
                pred.get("team_a", ""),
                pred.get("team_b", ""),
            ) or str(actual_result or "")
            pred["status"] = "completed"
            pred["final_score"] = final_score
            if fixture_id is not None and str(fixture_id).strip():
                pred["fixture_id"] = str(fixture_id).strip()
            outcome = _compute_prediction_outcome(pred)
            pred["is_correct"] = outcome["winner_hit"]
            pred["actual_winner"] = outcome["actual_winner"]
            pred["winner_result"] = outcome["winner_result"]
            pred["totals_result"] = outcome["totals_result"]
            pred["overall_result"] = outcome["overall_result"]
            pred["updated_at"] = _utc_now().isoformat().replace("+00:00", "Z")
            _save_predictions(predictions)
            return True
    
    return False


def get_summary_metrics() -> dict[str, Any]:
    """
    Compute summary metrics across all predictions.

    Accuracy is based on winner-pick correctness for completed games.
    
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
            "by_league": {
                "Premier League": {"accuracy": float, "count": int, "wins": int, "losses": int},
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
            "by_league": {},
            "recent_predictions": [],
        }

    # Filter to only finalized predictions (status = completed)
    finalized = [p for p in predictions if p.get("status") == "completed"]

    if not finalized:
        return {
            "total_predictions": len(predictions),
            "finalized_predictions": 0,
            "wins": 0,
            "losses": 0,
            "overall_accuracy": None,
            "by_confidence": {},
            "by_sport": {},
            "by_league": {},
            "recent_predictions": sorted(predictions, key=lambda p: p.get("created_at", ""), reverse=True)[:10],
        }
    
    # Calculate game-level wins/losses from winner correctness.
    def is_game_win(pred):
        outcome = _compute_prediction_outcome(pred)
        return outcome["winner_hit"]
    
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

    by_league = {}
    soccer_preds = [p for p in finalized if p.get("sport") == "soccer"]
    league_names = sorted({(p.get("league_name") or "Unspecified League") for p in soccer_preds})
    for league_name in league_names:
        league_preds = [p for p in soccer_preds if (p.get("league_name") or "Unspecified League") == league_name]
        if not league_preds:
            continue
        league_wins = sum(1 for p in league_preds if is_game_win(p))
        league_losses = len(league_preds) - league_wins
        by_league[league_name] = {
            "accuracy": round((league_wins / len(league_preds)) * 100, 1) if league_preds else 0,
            "count": len(league_preds),
            "wins": league_wins,
            "losses": league_losses,
        }
    
    return {
        "total_predictions": len(predictions),
        "finalized_predictions": len(finalized),
        "wins": wins,
        "losses": losses,
        "overall_accuracy": round(overall_accuracy, 1),
        "by_confidence": by_confidence,
        "by_sport": by_sport,
        "by_league": by_league,
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
    
    return [_enhance_prediction_record(pred) for pred in completed]


def get_prediction_by_id(pred_id: str) -> dict | None:
    """Fetch a prediction by its stable tracking ID with derived display fields."""
    lookup = str(pred_id or "").strip()
    if not lookup:
        return None

    for pred in _load_predictions():
        if str(pred.get("id") or "") == lookup:
            return _enhance_prediction_record(pred)
    return None
