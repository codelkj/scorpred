"""
result_updater.py — Automatic game result fetcher and prediction updater.

Fetches completed game results from API and updates pending predictions
in the tracking file to mark them correct or incorrect.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import api_client as ac
import nba_live_client as nc
import model_tracker as mt


def _normalize_team_name(name: str) -> str:
    """Normalize team name for matching: lowercase, remove special chars."""
    if not name:
        return ""
    text = name.lower().strip()
    # Remove common abbreviations and special characters
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\b(fc|cf|sc|afc|club|united|city)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _teams_match(team_a: str, team_b: str) -> bool:
    """Check if two team names match after normalization."""
    norm_a = _normalize_team_name(team_a)
    norm_b = _normalize_team_name(team_b)
    
    if not norm_a or not norm_b:
        return False
    
    # Exact match
    if norm_a == norm_b:
        return True
    
    # Partial match (one contains the other)
    if norm_a in norm_b or norm_b in norm_a:
        return True
    
    return False


def _parse_date(date_str: str) -> str:
    """Extract YYYY-MM-DD from various date formats."""
    if not date_str:
        return ""
    try:
        return str(date_str)[:10]
    except Exception:
        return ""


def fetch_soccer_result(
    team_a: str,
    team_b: str,
    date_str: str,
    league_id: int = 39,
    season: int = 2025,
) -> dict[str, Any] | None:
    """
    Fetch the actual result of a soccer match.
    
    Args:
        team_a: Team A name (from prediction)
        team_b: Team B name (from prediction)
        date_str: Date in YYYY-MM-DD format
        league_id: competition ID for the tracked prediction
        season: season year
    
    Returns:
        {
            "status": "FT|AET|PEN|...",
            "score": {"a": int, "b": int},
            "winner": "A|B|D",
            "teams": {"a": str, "b": str},
            "found": True
        }
        or None if not found
    """
    target_date = _parse_date(date_str)
    fixtures = []

    # Attempt 1: ESPN league scoreboard (returns all events including completed)
    try:
        slug_map = getattr(ac, "ESPN_SLUG_BY_LEAGUE", {})
        espn_slug = slug_map.get(league_id, "eng.1")
        fixtures = ac.get_espn_fixtures(espn_slug, next_n=50)
    except Exception:
        fixtures = []

    # Attempt 2: API-Football recent fixtures for the league
    if not fixtures:
        try:
            fixtures = ac.get_fixtures_by_league(league_id, season, last=20)
        except Exception:
            fixtures = []
    
    # Attempt 3: Try yesterday's fixtures in case some finished late
    if not fixtures:
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            fixtures = ac.get_fixtures_by_date(yesterday, league_id, season)
        except Exception:
            pass
    
    for fixture in fixtures:
        try:
            fixture_date = _parse_date((fixture.get("fixture") or {}).get("date", ""))
            if fixture_date != target_date:
                continue
            
            # Check if game is finished
            status = ((fixture.get("fixture") or {}).get("status") or {}).get("short", "")
            if status not in ("FT", "AET", "PEN"):
                continue
            
            # Get team names and scores
            h_name = (fixture.get("teams") or {}).get("home", {}).get("name", "")
            a_name = (fixture.get("teams") or {}).get("away", {}).get("name", "")
            h_goals = fixture.get("goals", {}).get("home")
            a_goals = fixture.get("goals", {}).get("away")
            
            # Check if teams match (try both orderings)
            if (_teams_match(team_a, h_name) and _teams_match(team_b, a_name)):
                # team_a is home
                if h_goals is None or a_goals is None:
                    continue
                
                if h_goals > a_goals:
                    winner = "A"
                elif a_goals > h_goals:
                    winner = "B"
                else:
                    winner = "draw"
                
                return {
                    "status": status,
                    "score": {"a": h_goals, "b": a_goals},
                    "winner": winner,
                    "teams": {"a": h_name, "b": a_name},
                    "found": True,
                }
            
            elif (_teams_match(team_a, a_name) and _teams_match(team_b, h_name)):
                # team_a is away
                if h_goals is None or a_goals is None:
                    continue
                
                if a_goals > h_goals:
                    winner = "A"
                elif h_goals > a_goals:
                    winner = "B"
                else:
                    winner = "draw"
                
                return {
                    "status": status,
                    "score": {"a": a_goals, "b": h_goals},
                    "winner": winner,
                    "teams": {"a": a_name, "b": h_name},
                    "found": True,
                }
        except Exception:
            continue
    
    return None


def fetch_nba_result(
    team_a: str,
    team_b: str,
    date_str: str,
) -> dict[str, Any] | None:
    """
    Fetch the actual result of an NBA game.
    
    Args:
        team_a: Team A name (from prediction)
        team_b: Team B name (from prediction)
        date_str: Date in YYYY-MM-DD format
    
    Returns:
        {
            "status": "Final",
            "score": {"a": int, "b": int},
            "winner": "A|B",
            "teams": {"a": str, "b": str},
            "found": True
        }
        or None if not found
    """
    target_date = _parse_date(date_str)
    
    all_games: list[dict] = []
    seen_ids: set[str] = set()

    candidate_days: list[datetime] = []
    try:
        if target_date:
            candidate_days.append(datetime.fromisoformat(target_date))
    except Exception:
        pass
    now = datetime.now()
    candidate_days.extend([now - timedelta(days=1), now, now + timedelta(days=1)])

    for day in candidate_days:
        try:
            for game in nc.get_scoreboard_games(day):
                game_id = str(game.get("id") or "")
                if game_id and game_id in seen_ids:
                    continue
                seen_ids.add(game_id)
                all_games.append(game)
        except Exception:
            continue
    
    for game in all_games:
        try:
            game_date = _parse_date((game.get("date") or {}).get("start", ""))
            if game_date != target_date:
                continue
            
            # Check if game is finished
            status_info = game.get("status") or {}
            status = str(status_info.get("long") or status_info.get("short") or "").upper()
            state = str(status_info.get("state") or "").lower()
            if state != "post" and "FINAL" not in status:
                continue
            
            # Get team names
            teams = game.get("teams") or {}
            home_team = teams.get("home") or {}
            away_team = teams.get("visitors") or {}
            home_name = home_team.get("name") or home_team.get("nickname", "")
            away_name = away_team.get("name") or away_team.get("nickname", "")
            
            scores = game.get("scores") or {}
            home_score = int((scores.get("home") or {}).get("points") or 0)
            away_score = int((scores.get("visitors") or {}).get("points") or 0)
            
            # Check if teams match (try both orderings)
            if (_teams_match(team_a, home_name) and _teams_match(team_b, away_name)):
                # team_a is home
                if home_score > away_score:
                    winner = "A"
                else:
                    winner = "B"
                
                return {
                    "status": status,
                    "score": {"a": home_score, "b": away_score},
                    "winner": winner,
                    "teams": {"a": home_name, "b": away_name},
                    "found": True,
                }
            
            elif (_teams_match(team_a, away_name) and _teams_match(team_b, home_name)):
                # team_a is away
                if away_score > home_score:
                    winner = "A"
                else:
                    winner = "B"
                
                return {
                    "status": status,
                    "score": {"a": away_score, "b": home_score},
                    "winner": winner,
                    "teams": {"a": away_name, "b": home_name},
                    "found": True,
                }
        except Exception:
            continue
    
    return None


def update_pending_predictions() -> dict[str, Any]:
    """
    Go through all pending predictions and try to fetch their actual results.
    
    Returns:
        {
            "checked": int,  # How many pending predictions were checked
            "found": int,    # How many actual results were found
            "updated": int,  # How many predictions were updated
            "failed": int,   # How many API calls failed
            "errors": [str], # Error messages
        }
    """
    predictions = mt._load_predictions()
    
    if not predictions:
        return {
            "checked": 0,
            "found": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }
    
    # Filter to pending predictions only (status != completed)
    pending = [p for p in predictions if p.get("status") != "completed"]
    
    stats = {
        "checked": len(pending),
        "found": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
    }
    
    for pred in pending:
        sport = pred.get("sport", "").lower()
        team_a = pred.get("team_a", "")
        team_b = pred.get("team_b", "")
        date_str = pred.get("game_date") or pred.get("date", "")
        pred_id = pred.get("id", "")
        
        result = None
        
        try:
            if sport == "soccer":
                result = fetch_soccer_result(
                    team_a,
                    team_b,
                    date_str,
                    league_id=int(pred.get("league_id") or 39),
                )
            elif sport == "nba":
                result = fetch_nba_result(team_a, team_b, date_str)
            else:
                stats["errors"].append(f"Unknown sport: {sport}")
                continue
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"{pred_id} ({team_a} vs {team_b}): {str(e)[:60]}")
            continue
        
        if result and result.get("found"):
            stats["found"] += 1
            actual_winner = result.get("winner", "")
            final_score = result.get("score", None)
            
            # Update the prediction with result and final score
            if mt.update_prediction_result(pred_id, actual_winner, final_score):
                stats["updated"] += 1
        else:
            # Log why the result wasn't found
            stats["errors"].append(f"{pred_id} ({team_a} vs {team_b} on {date_str}): No result found - game may not be finished yet")
    
    return stats


def get_update_summary() -> dict[str, Any]:
    """
    Get summary of pending vs. completed predictions.
    
    Returns:
        {
            "pending": int,
            "completed": int,
            "total": int,
            "completion_rate": float,  # percent
        }
    """
    predictions = mt._load_predictions()
    
    total = len(predictions)
    completed = sum(1 for p in predictions if p.get("status") == "completed")
    pending = total - completed
    
    completion_rate = (completed / total * 100) if total > 0 else 0
    
    return {
        "pending": pending,
        "completed": completed,
        "total": total,
        "completion_rate": round(completion_rate, 1),
    }
