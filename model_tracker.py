"""
model_tracker.py — Lightweight prediction tracking and performance metrics.

Stores predictions in JSON format for easy inspection and analysis.
Provides functions to save, update, and summarize model performance.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
import uuid
import re
from runtime_paths import prediction_tracking_path
from utils.parsing import normalize_date

logger = logging.getLogger(__name__)

_TRACKING_FILE = str(prediction_tracking_path())


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
        logger.warning("Prediction migration failed", exc_info=True)


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
    except Exception:
        logger.error("Failed to save predictions to %s", _TRACKING_FILE, exc_info=True)


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

    if text in {"avoid", "skip", "pass", "no bet", "nobet"}:
        return "avoid"

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
    model_probability: float | None = None,   # model's top class probability (0-1)
    implied_probability: float | None = None,  # market implied probability (reserved)
    form_a_length: int | None = None,          # home team's form list length (for recency_bias detection)
    elo_diff: float | None = None,             # home_elo - away_elo (for popular_team_overrating)
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
    if model_probability is not None:
        prediction["model_probability"] = round(float(model_probability), 6)
    prediction["implied_probability"] = implied_probability  # None by default (reserved for odds)
    if form_a_length is not None:
        prediction["form_a_length"] = int(form_a_length)
    if elo_diff is not None:
        prediction["elo_diff"] = round(float(elo_diff), 2)

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


def get_summary_metrics(exclude_seeded: bool = True) -> dict[str, Any]:
    """
    Compute summary metrics across tracked winner predictions.

    Completed predictions are graded from the persisted winner outcome stored in
    `is_correct`, which is the source of truth for dashboard accuracy.

    Args:
        exclude_seeded: When True (default), exclude predictions with is_seeded=True.

    Returns:
        {
            "total_predictions": int,
            "finalized_predictions": int,
            "wins": int,
            "losses": int,
            "overall_accuracy": float,  # 0-100%
            "by_confidence": {...},
            "by_sport": {...},
            "calibration": {...},
            "seeded_count": int,         # number of seeded predictions excluded
            "recent_predictions": list   # Last 10
        }
    """
    all_predictions = _load_predictions()
    seeded_count = sum(1 for p in all_predictions if p.get("is_seeded"))
    predictions = [p for p in all_predictions if not (exclude_seeded and p.get("is_seeded"))]
    
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
    
    # Calibration: per confidence tier, compare avg model_probability vs actual hit rate
    calibration: dict[str, dict[str, Any]] = {}
    for conf_level in ("High", "Medium", "Low"):
        tier_preds = [p for p in finalized if p.get("confidence") == conf_level]
        if not tier_preds:
            continue
        probs = [float(p["model_probability"]) for p in tier_preds if p.get("model_probability") is not None]
        tier_wins = sum(1 for p in tier_preds if is_game_win(p))
        actual_hr  = round(tier_wins / len(tier_preds), 4)
        avg_model  = round(sum(probs) / len(probs), 4) if probs else None
        gap = round(actual_hr - avg_model, 4) if avg_model is not None else None
        if gap is not None:
            if gap < -0.05:
                label = "Overconfident"
            elif gap > 0.05:
                label = "Underconfident"
            else:
                label = "Well-calibrated"
        else:
            label = "No probability data"
        calibration[conf_level] = {
            "avg_model_probability": avg_model,
            "actual_hit_rate":       actual_hr,
            "calibration_gap":       gap,
            "label":                 label,
            "count":                 len(tier_preds),
        }

    return {
        "total_predictions": len(predictions),
        "finalized_predictions": len(finalized),
        "wins": wins,
        "losses": losses,
        "overall_accuracy": round(overall_accuracy, 1),
        "by_confidence": by_confidence,
        "by_sport": by_sport,
        "calibration": calibration,
        "seeded_count": seeded_count,
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


def _prediction_timestamp(pred: dict[str, Any]) -> datetime:
    """Best-effort timestamp parser for stable chronological ordering."""
    for key in ("updated_at", "created_at", "game_date", "date"):
        raw = str(pred.get(key) or "").strip()
        if not raw:
            continue
        try:
            if raw.endswith("Z"):
                raw = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(raw)
        except Exception:
            continue
    return datetime(1970, 1, 1, tzinfo=UTC)


def _is_win(pred: dict[str, Any]) -> bool:
    value = pred.get("is_correct")
    if value is not None:
        return bool(value)
    return bool(pred.get("winner_hit"))


def _predicted_outcome(pred: dict[str, Any]) -> str:
    outcome = _canonical_outcome(
        pred.get("predicted_winner_normalized") or pred.get("predicted_winner"),
        pred.get("team_a") or "",
        pred.get("team_b") or "",
    )
    if outcome:
        return outcome
    return ""


def _confidence_percent(pred: dict[str, Any]) -> float:
    probs = [pred.get("prob_a"), pred.get("prob_b"), pred.get("prob_draw")]
    numeric_probs = []
    for value in probs:
        if isinstance(value, (int, float)):
            numeric_probs.append(float(value))
    if numeric_probs:
        top_prob = max(numeric_probs)
        if top_prob <= 1.0:
            top_prob *= 100.0
        return max(0.0, min(100.0, round(top_prob, 1)))

    tier = str(pred.get("confidence") or "").lower()
    mapped = {"high": 85.0, "medium": 70.0, "low": 55.0}
    return mapped.get(tier, 50.0)


def _confidence_bucket(conf_pct: float) -> str:
    if conf_pct >= 80.0:
        return "80-100"
    if conf_pct >= 60.0:
        return "60-80"
    if conf_pct >= 40.0:
        return "40-60"
    return "<40"


def _finalized_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = [
        pred for pred in predictions
        if pred.get("status") == "completed" and pred.get("is_correct") is not None
    ]
    finalized.sort(key=_prediction_timestamp)
    return finalized


def _build_rolling_accuracy_series(finalized: list[dict[str, Any]], rolling_window: int) -> list[dict[str, Any]]:
    window_size = max(1, int(rolling_window))
    rolling_points: list[dict[str, Any]] = []
    recent_binary: list[int] = []

    for idx, pred in enumerate(finalized, start=1):
        is_win = _is_win(pred)
        recent_binary.append(1 if is_win else 0)
        window = recent_binary[max(0, len(recent_binary) - window_size) :]
        rolling_acc = round((sum(window) / len(window)) * 100.0, 1) if window else 0.0

        label = pred.get("date") or pred.get("game_date") or pred.get("updated_at") or ""
        rolling_points.append(
            {
                "match_index": idx,
                "label": str(label)[:10] if label else f"#{idx}",
                "rolling_accuracy": rolling_acc,
                "is_win": is_win,
            }
        )

    return rolling_points


def _build_daily_rolling_accuracy_series(finalized: list[dict[str, Any]], rolling_window: int) -> list[dict[str, Any]]:
    window_size = max(1, int(rolling_window))
    daily_buckets: dict[str, dict[str, int]] = {}
    for pred in finalized:
        day = normalize_date(pred.get("date") or pred.get("game_date")) or "unknown"
        bucket = daily_buckets.setdefault(day, {"wins": 0, "count": 0})
        bucket["count"] += 1
        bucket["wins"] += 1 if _is_win(pred) else 0

    daily_points: list[dict[str, Any]] = []
    rolling_daily: list[float] = []
    for idx, day in enumerate(sorted(daily_buckets.keys()), start=1):
        bucket = daily_buckets[day]
        day_acc = round((bucket["wins"] / bucket["count"]) * 100.0, 1) if bucket["count"] else 0.0
        rolling_daily.append(day_acc)
        day_window = rolling_daily[max(0, len(rolling_daily) - window_size) :]
        daily_points.append(
            {
                "day_index": idx,
                "label": day,
                "daily_accuracy": day_acc,
                "rolling_accuracy": round(sum(day_window) / len(day_window), 1) if day_window else 0.0,
                "matches": bucket["count"],
            }
        )

    return daily_points


def _build_cumulative_performance_series(finalized: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cumulative_points: list[dict[str, Any]] = []
    cumulative_value = 0

    for idx, pred in enumerate(finalized, start=1):
        is_win = _is_win(pred)
        outcome = _predicted_outcome(pred)
        delta = 0 if outcome == "avoid" else (1 if is_win else -1)
        cumulative_value += delta

        label = pred.get("date") or pred.get("game_date") or pred.get("updated_at") or ""
        cumulative_points.append(
            {
                "match_index": idx,
                "label": str(label)[:10] if label else f"#{idx}",
                "cumulative_points": cumulative_value,
                "delta": delta,
            }
        )

    return cumulative_points


def _build_confidence_bucket_stats(finalized: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calibration_counts = {
        "80-100": {"count": 0, "wins": 0},
        "60-80": {"count": 0, "wins": 0},
        "40-60": {"count": 0, "wins": 0},
        "<40": {"count": 0, "wins": 0},
    }
    for pred in finalized:
        conf_pct = _confidence_percent(pred)
        bucket_key = _confidence_bucket(conf_pct)
        calibration_counts[bucket_key]["count"] += 1
        calibration_counts[bucket_key]["wins"] += 1 if _is_win(pred) else 0

    confidence_calibration = []
    for bucket_key in ("80-100", "60-80", "40-60", "<40"):
        bucket = calibration_counts[bucket_key]
        hit_rate = round((bucket["wins"] / bucket["count"]) * 100.0, 1) if bucket["count"] else 0.0
        confidence_calibration.append(
            {
                "bucket": bucket_key,
                "sample_size": bucket["count"],
                "avg_confidence": {
                    "80-100": 90.0,
                    "60-80": 70.0,
                    "40-60": 50.0,
                    "<40": 30.0,
                }[bucket_key],
                "actual_hit_rate": hit_rate,
            }
        )

    return confidence_calibration


def _build_outcome_breakdown(finalized: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcome_breakdown = []
    for key, label in (("A", "Home"), ("B", "Away"), ("draw", "Draw")):
        subset = [pred for pred in finalized if _predicted_outcome(pred) == key]
        wins = sum(1 for pred in subset if _is_win(pred))
        count = len(subset)
        outcome_breakdown.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "wins": wins,
                "losses": count - wins,
                "accuracy": round((wins / count) * 100.0, 1) if count else None,
            }
        )
    return outcome_breakdown


def _build_recent_form(finalized: list[dict[str, Any]]) -> dict[str, dict[str, int | float | None]]:
    recent_10 = finalized[-10:]
    recent_20 = finalized[-20:]
    return {
        "last_10": {
            "count": len(recent_10),
            "accuracy": round((sum(1 for pred in recent_10 if _is_win(pred)) / len(recent_10)) * 100.0, 1)
            if recent_10 else None,
        },
        "last_20": {
            "count": len(recent_20),
            "accuracy": round((sum(1 for pred in recent_20 if _is_win(pred)) / len(recent_20)) * 100.0, 1)
            if recent_20 else None,
        },
    }


def _recommendation_label(pred: dict[str, Any]) -> str:
    existing = str(pred.get("play_type") or pred.get("recommendation") or "").strip()
    if existing:
        return existing

    outcome = _predicted_outcome(pred)
    if outcome == "A":
        return f"{pred.get('team_a') or 'Team A'} ML"
    if outcome == "B":
        return f"{pred.get('team_b') or 'Team B'} ML"
    if outcome == "draw":
        return "Draw"
    if outcome == "avoid":
        return "Avoid"
    return "--"


def _build_failure_rows(finalized: list[dict[str, Any]], failure_limit: int) -> list[dict[str, Any]]:
    failures = [pred for pred in finalized if not _is_win(pred)]
    failures.sort(key=_prediction_timestamp, reverse=True)
    failure_rows = []
    for pred in failures[: max(1, failure_limit)]:
        failure_rows.append(
            {
                "date": normalize_date(pred.get("date") or pred.get("game_date")) or (str(pred.get("updated_at") or "")[:10]),
                "sport": str(pred.get("sport") or "").upper(),
                "matchup": f"{pred.get('team_a', 'Team A')} vs {pred.get('team_b', 'Team B')}",
                "predicted_outcome": pred.get("predicted_winner") or _predicted_outcome(pred) or "--",
                "actual_result": pred.get("actual_winner") or pred.get("actual_result") or pred.get("actual_result_normalized") or "--",
                "confidence": pred.get("confidence") or "Low",
                "confidence_pct": _confidence_percent(pred),
                "recommendation": _recommendation_label(pred),
                "notes": pred.get("reasoning") or pred.get("winner_display") or "",
            }
        )
    return failure_rows


def _build_pass_rows(finalized: list[dict[str, Any]], pass_limit: int) -> list[dict[str, Any]]:
    passes = [pred for pred in finalized if _is_win(pred)]
    passes.sort(key=_prediction_timestamp, reverse=True)
    pass_rows = []
    for pred in passes[: max(1, pass_limit)]:
        pass_rows.append(
            {
                "date": normalize_date(pred.get("date") or pred.get("game_date")) or (str(pred.get("updated_at") or "")[:10]),
                "sport": str(pred.get("sport") or "").upper(),
                "matchup": f"{pred.get('team_a', 'Team A')} vs {pred.get('team_b', 'Team B')}",
                "predicted_outcome": pred.get("predicted_winner") or _predicted_outcome(pred) or "--",
                "actual_result": pred.get("actual_winner") or pred.get("actual_result") or pred.get("actual_result_normalized") or "--",
                "confidence": pred.get("confidence") or "Low",
                "confidence_pct": _confidence_percent(pred),
                "recommendation": _recommendation_label(pred),
                "notes": pred.get("reasoning") or pred.get("winner_display") or "",
            }
        )
    return pass_rows


def _build_strategy_comparison(
    metrics: dict[str, Any],
    finalized: list[dict[str, Any]],
    all_predictions: list[dict[str, Any]],
    strategy_reference: dict[str, Any],
) -> list[dict[str, Any]]:
    tracker_accuracy = metrics.get("overall_accuracy")
    edge_filtered_subset = [
        pred for pred in finalized
        if _predicted_outcome(pred) != "avoid" and _confidence_percent(pred) >= 60.0
    ]
    edge_filtered_accuracy = (
        round((sum(1 for pred in edge_filtered_subset if _is_win(pred)) / len(edge_filtered_subset)) * 100.0, 1)
        if edge_filtered_subset else None
    )
    avoid_aware_score = (
        round(
            ((sum(1 for pred in all_predictions if _predicted_outcome(pred) == "avoid") + metrics.get("wins", 0))
             / max(1, len(all_predictions))) * 100.0,
            1,
        )
        if all_predictions else None
    )

    ml_accuracy = strategy_reference.get("ml_accuracy")
    combined_accuracy = strategy_reference.get("combined_accuracy")

    return [
        {"strategy": "Rule-Based", "accuracy": tracker_accuracy, "sample_size": metrics.get("finalized_predictions", 0), "source": "live"},
        {"strategy": "ML (Stacking)", "accuracy": ml_accuracy, "sample_size": strategy_reference.get("evaluation_matches"), "source": "offline"},
        {"strategy": "Combined Signal", "accuracy": combined_accuracy, "sample_size": strategy_reference.get("evaluation_matches"), "source": "offline"},
        {"strategy": "Edge-Filtered", "accuracy": edge_filtered_accuracy, "sample_size": len(edge_filtered_subset), "source": "live"},
        {"strategy": "Avoid-Aware", "accuracy": avoid_aware_score, "sample_size": len(all_predictions), "source": "live"},
    ]


def get_evaluation_dashboard(
    rolling_window: int = 10,
    failure_limit: int = 12,
    pass_limit: int = 12,
    strategy_reference: dict[str, Any] | None = None,
    exclude_seeded: bool = True,
) -> dict[str, Any]:
    """Build a full evaluation payload for the model performance dashboard."""
    raw_predictions = _load_predictions()
    seeded_count = sum(1 for p in raw_predictions if p.get("is_seeded"))
    all_predictions = [p for p in raw_predictions if not (exclude_seeded and p.get("is_seeded"))]
    metrics = get_summary_metrics(exclude_seeded=exclude_seeded)
    finalized = _finalized_predictions(all_predictions)

    avoids_skipped = sum(1 for pred in all_predictions if _predicted_outcome(pred) == "avoid")

    rolling_points = _build_rolling_accuracy_series(finalized, rolling_window)
    daily_points = _build_daily_rolling_accuracy_series(finalized, rolling_window)
    cumulative_points = _build_cumulative_performance_series(finalized)
    confidence_calibration = _build_confidence_bucket_stats(finalized)
    outcome_breakdown = _build_outcome_breakdown(finalized)
    recent_form = _build_recent_form(finalized)
    failure_rows = _build_failure_rows(finalized, failure_limit)
    pass_rows = _build_pass_rows(finalized, pass_limit)

    strategy_reference = strategy_reference or {}
    strategy_comparison = _build_strategy_comparison(
        metrics,
        finalized,
        all_predictions,
        strategy_reference,
    )
    tracker_accuracy = metrics.get("overall_accuracy")

    valid_strategies = [item for item in strategy_comparison if isinstance(item.get("accuracy"), (int, float))]
    best_strategy = max(valid_strategies, key=lambda item: item.get("accuracy", -1))["strategy"] if valid_strategies else "Awaiting sample"

    roi_fields = ["profit", "roi", "points_won"]
    roi_values = [
        float(pred.get(field))
        for pred in finalized
        for field in roi_fields
        if isinstance(pred.get(field), (int, float))
    ]
    cumulative_value = cumulative_points[-1]["cumulative_points"] if cumulative_points else 0
    roi_or_points = round(sum(roi_values), 2) if roi_values else cumulative_value

    kpis = {
        "overall_accuracy": tracker_accuracy,
        "rolling_win_rate": rolling_points[-1]["rolling_accuracy"] if rolling_points else None,
        "total_tracked_predictions": metrics.get("total_predictions", 0),
        "finalized_predictions": metrics.get("finalized_predictions", 0),
        "avoids_skipped": avoids_skipped,
        "current_best_strategy": best_strategy,
        "roi_or_points": roi_or_points,
    }

    by_confidence_tier = []
    for tier in ("High", "Medium", "Low"):
        row = (metrics.get("by_confidence") or {}).get(tier)
        if row:
            by_confidence_tier.append(
                {
                    "tier": tier,
                    "accuracy": row.get("accuracy"),
                    "count": row.get("count", 0),
                    "wins": row.get("wins", 0),
                    "losses": row.get("losses", 0),
                }
            )

    by_sport = []
    for sport_key in ("soccer", "nba"):
        row = (metrics.get("by_sport") or {}).get(sport_key)
        if row:
            by_sport.append(
                {
                    "sport": sport_key,
                    "accuracy": row.get("accuracy"),
                    "count": row.get("count", 0),
                    "wins": row.get("wins", 0),
                    "losses": row.get("losses", 0),
                }
            )

    return {
        "kpis": kpis,
        "rolling_window": max(1, int(rolling_window)),
        "series": {
            "rolling_by_match": rolling_points,
            "rolling_by_day": daily_points,
            "cumulative_points": cumulative_points,
        },
        "confidence_calibration": confidence_calibration,
        "strategy_comparison": strategy_comparison,
        "breakdowns": {
            "by_sport": by_sport,
            "by_confidence_tier": by_confidence_tier,
            "by_predicted_outcome": outcome_breakdown,
            "recent_form": recent_form,
        },
        "failure_rows": failure_rows,
        "pass_rows": pass_rows,
        "seeded_count": seeded_count,
        "exclude_seeded": exclude_seeded,
    }
