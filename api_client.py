"""
api_client.py — API-Football wrapper with 24-hour JSON caching.
All calls go through api_get(); cached responses are served instantly.
"""

import os
import json
import hashlib
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path("cache")
CACHE_HOURS = 24
API_BASE_URL = os.getenv("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io").rstrip("/")
API_MODE = os.getenv("API_FOOTBALL_MODE", "apisports").strip().lower()
RAPIDAPI_HOST = os.getenv("API_FOOTBALL_RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
API_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
PLACEHOLDER_API_KEYS = {"", "your_api_key_here"}


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_path(endpoint: str, params: dict) -> Path:
    raw = endpoint + str(sorted((params or {}).items()))
    key = hashlib.md5(raw.encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(hours=CACHE_HOURS)


def _request_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}

    if API_MODE == "rapidapi":
        headers["x-rapidapi-host"] = RAPIDAPI_HOST
        headers["x-rapidapi-key"] = API_KEY
    else:
        headers["x-apisports-key"] = API_KEY

    return headers


# ── Core request ───────────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict = None) -> dict:
    """Make a GET request to API-Football, returning cached data when fresh."""
    params = params or {}
    path = _cache_path(endpoint, params)

    if _cache_valid(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    if API_KEY.lower() in PLACEHOLDER_API_KEYS:
        raise RuntimeError("Set API_FOOTBALL_KEY in .env to a real API-Football key.")

    headers = _request_headers()
    url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("errors"):
        raise RuntimeError(f"API-Football error for {endpoint}: {data['errors']}")

    CACHE_DIR.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return data


# ── Domain helpers ─────────────────────────────────────────────────────────────

def get_teams(league: int = 39, season: int = 2024) -> list:
    return api_get("teams", {"league": league, "season": season}).get("response", [])


def get_h2h(id_a: int, id_b: int, last: int = 10) -> list:
    return api_get(
        "fixtures/headtohead", {"h2h": f"{id_a}-{id_b}", "last": last}
    ).get("response", [])


def get_fixture_stats(fixture_id: int) -> list:
    return api_get("fixtures/statistics", {"fixture": fixture_id}).get("response", [])


def get_fixture_events(fixture_id: int) -> list:
    return api_get("fixtures/events", {"fixture": fixture_id}).get("response", [])


def get_squad(team_id: int) -> list:
    data = api_get("players/squads", {"team": team_id}).get("response", [])
    return data[0].get("players", []) if data else []


def get_player_stats(player_id: int, season: int = 2024) -> list:
    return api_get("players", {"id": player_id, "season": season}).get("response", [])


def get_injuries(team_id: int, league: int = 39, season: int = 2024) -> list:
    return api_get(
        "injuries", {"league": league, "season": season, "team": team_id}
    ).get("response", [])


def get_team_fixtures(team_id: int, league: int = 39, season: int = 2024, last: int = 10) -> list:
    return api_get(
        "fixtures", {"team": team_id, "league": league, "season": season, "last": last}
    ).get("response", [])


def get_standings(league: int = 39, season: int = 2024) -> list:
    return api_get("standings", {"league": league, "season": season}).get("response", [])


def get_upcoming_fixtures(league: int = 39, season: int = 2024, next_n: int = 20) -> list:
    return api_get("fixtures", {"league": league, "season": season, "next": next_n}).get("response", [])


# ── Enrichment helpers ─────────────────────────────────────────────────────────

def enrich_fixture(fixture: dict) -> dict:
    """Add events and stats to a fixture dict (cached individually)."""
    fid = fixture["fixture"]["id"]
    return {
        **fixture,
        "events": get_fixture_events(fid),
        "stats": get_fixture_stats(fid),
    }


def parse_stat(stats: list, team_id: int, stat_type: str):
    """Pull a single stat value for a team from fixture stats response."""
    for team_stats in stats:
        if team_stats["team"]["id"] == team_id:
            for s in team_stats["statistics"]:
                if s["type"] == stat_type:
                    return s["value"]
    return None
