"""
odds_fetcher.py — Fetch live odds from The Odds API and compute edge vs model.

Usage:
    from odds_fetcher import fetch_match_odds, compute_edge

The Odds API docs: https://the-odds-api.com/liveapi/guides/v4/
Requires environment variable: ODDS_API_KEY
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
_CACHE_TTL = 600  # 10 minutes
_CACHE_DIR = Path(os.environ.get("SCORPRED_DATA_ROOT", "")) / "cache" / "odds" if os.environ.get("SCORPRED_DATA_ROOT") else Path("cache") / "odds"

# Sport keys used by The Odds API
_SPORT_KEY_MAP = {
    "soccer": "soccer_epl",      # English Premier League
    "nba": "basketball_nba",
}


def _cache_path(cache_key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in cache_key)
    return _CACHE_DIR / f"{safe}.json"


def _load_cached(cache_key: str) -> dict | None:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("_cached_at", 0) < _CACHE_TTL:
            return data.get("payload")
    except Exception:
        pass
    return None


def _save_cached(cache_key: str, payload: Any) -> None:
    try:
        _cache_path(cache_key).write_text(
            json.dumps({"_cached_at": time.time(), "payload": payload})
        )
    except Exception:
        pass


def fetch_match_odds(
    sport: str,
    team_a: str,
    team_b: str,
    *,
    markets: str = "h2h",
    regions: str = "uk,eu,us",
) -> dict[str, Any]:
    """Fetch best available odds for a specific match from The Odds API.

    Returns:
        {
            "available": bool,
            "home_odds": float | None,    # decimal odds for team_a (home)
            "away_odds": float | None,    # decimal odds for team_b (away)
            "draw_odds": float | None,    # decimal odds for draw (soccer only)
            "bookmaker": str | None,      # bookmaker name with the best line
            "source": "live" | "cache" | "unavailable",
        }
    """
    if not _ODDS_API_KEY:
        return _unavailable("No ODDS_API_KEY set")

    sport_key = _SPORT_KEY_MAP.get(sport.lower())
    if not sport_key:
        return _unavailable(f"Unsupported sport: {sport}")

    cache_key = f"{sport_key}_{team_a}_{team_b}"
    cached = _load_cached(cache_key)
    if cached is not None:
        cached["source"] = "cache"
        return cached

    try:
        url = f"{_ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "apiKey": _ODDS_API_KEY,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        resp = requests.get(url, params=params, timeout=6)
        resp.raise_for_status()
        games = resp.json()
    except Exception as exc:
        logger.warning("odds_fetcher: API call failed — %s", exc)
        return _unavailable(str(exc))

    result = _find_match(games, team_a, team_b)
    _save_cached(cache_key, result)
    result["source"] = "live"
    return result


def _find_match(games: list[dict], team_a: str, team_b: str) -> dict[str, Any]:
    """Scan API response for the matching game and extract best odds."""
    a_norm = _norm(team_a)
    b_norm = _norm(team_b)

    for game in games:
        home = _norm(game.get("home_team", ""))
        away = _norm(game.get("away_team", ""))
        if not (_teams_match(a_norm, home) and _teams_match(b_norm, away)):
            continue

        # Collect h2h outcomes across bookmakers and pick best (highest) odds
        best: dict[str, float] = {}
        best_book: dict[str, str] = {}

        for bm in game.get("bookmakers", []):
            bm_name = bm.get("title", "")
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = _norm(outcome.get("name", ""))
                    price = float(outcome.get("price", 0) or 0)
                    if price <= 1.0:
                        continue
                    if name == home and price > best.get("home", 0):
                        best["home"] = price
                        best_book["home"] = bm_name
                    elif name == away and price > best.get("away", 0):
                        best["away"] = price
                        best_book["away"] = bm_name
                    elif "draw" in name and price > best.get("draw", 0):
                        best["draw"] = price
                        best_book["draw"] = bm_name

        if best:
            return {
                "available": True,
                "home_odds": best.get("home"),
                "away_odds": best.get("away"),
                "draw_odds": best.get("draw"),
                "bookmaker": best_book.get("home") or best_book.get("away"),
            }

    return _unavailable("Match not found in current odds feed")


def compute_edge(
    model_prob: float,
    market_odds: float | None,
) -> dict[str, Any]:
    """Compute expected value edge.

    Args:
        model_prob: Model's probability for the outcome (0.0–1.0 or 0–100).
        market_odds: Best available decimal odds from bookmaker.

    Returns:
        {
            "edge_pct": float,        # positive = positive EV
            "ev_per_unit": float,     # expected profit per 1-unit stake
            "implied_prob": float,    # market's implied probability
            "has_edge": bool,
            "label": str,             # "Value Bet" | "Fair" | "Avoid"
        }
    """
    if market_odds is None or market_odds <= 1.0:
        return {"edge_pct": None, "ev_per_unit": None, "implied_prob": None, "has_edge": False, "label": "No odds"}

    # Normalise model_prob to 0-1 range
    if model_prob > 1.0:
        model_prob = model_prob / 100.0
    model_prob = max(0.0, min(1.0, model_prob))

    implied_prob = 1.0 / market_odds
    edge_pct = round((model_prob - implied_prob) * 100, 1)
    ev_per_unit = round(model_prob * (market_odds - 1) - (1 - model_prob), 3)

    if edge_pct >= 3.0:
        label = "Value Bet"
        has_edge = True
    elif edge_pct >= -2.0:
        label = "Fair"
        has_edge = False
    else:
        label = "Avoid"
        has_edge = False

    return {
        "edge_pct": edge_pct,
        "ev_per_unit": ev_per_unit,
        "implied_prob": round(implied_prob * 100, 1),
        "has_edge": has_edge,
        "label": label,
    }


def _unavailable(reason: str = "") -> dict[str, Any]:
    return {
        "available": False,
        "home_odds": None,
        "away_odds": None,
        "draw_odds": None,
        "bookmaker": None,
        "source": "unavailable",
        "reason": reason,
    }


def _norm(s: str) -> str:
    return s.lower().strip()


def _teams_match(query: str, candidate: str) -> bool:
    """Fuzzy team name matching — handles 'Man City' vs 'Manchester City'."""
    if not query or not candidate:
        return False
    if query == candidate:
        return True
    # Substring match (one direction is enough for common abbreviations)
    q_words = set(query.split())
    c_words = set(candidate.split())
    overlap = q_words & c_words
    return len(overlap) >= max(1, len(q_words) - 1)
