"""
football_data_client.py — Adapter for football-data.org API v4.

Normalises football-data.org responses to the api-sports.io v3 shape so the
rest of the app (match_brain, evidence, standings, etc.) needs zero changes.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

_logger = logging.getLogger(__name__)

FDO_API_KEY  = os.getenv("FOOTBALL_DATA_ORG_KEY", "").strip()
FDO_BASE_URL = "https://api.football-data.org/v4"

# Our app uses api-sports.io league IDs internally; FDO uses competition codes.
# Mapping: app league_id → FDO competition code
_LEAGUE_TO_FDO_CODE: dict[int, str] = {
    39:  "PL",   # Premier League
    140: "PD",   # La Liga
    135: "SA",   # Serie A
    78:  "BL1",  # Bundesliga
    61:  "FL1",  # Ligue 1
    2:   "CL",   # Champions League
}

# Reverse: FDO competition numeric id → app league_id
_FDO_ID_TO_LEAGUE: dict[int, int] = {
    2021: 39,
    2014: 140,
    2019: 135,
    2002: 78,
    2015: 61,
    2001: 2,
}

# FDO match status → api-sports.io v3 short status
_STATUS_MAP: dict[str, str] = {
    "SCHEDULED": "NS",
    "TIMED":     "NS",
    "IN_PLAY":   "1H",
    "PAUSED":    "HT",
    "FINISHED":  "FT",
    "SUSPENDED": "SUSP",
    "POSTPONED": "PST",
    "CANCELLED": "CANC",
    "AWARDED":   "AWD",
}

_STATUS_LONG: dict[str, str] = {
    "NS":   "Not Started",
    "1H":   "First Half",
    "HT":   "Halftime",
    "FT":   "Match Finished",
    "SUSP": "Suspended",
    "PST":  "Postponed",
    "CANC": "Cancelled",
    "AWD":  "Awarded",
}

# Simple in-process cache: key → (data, expires_at)
_cache: dict[str, tuple[Any, float]] = {}


def _fdo_get(path: str, params: dict | None = None, cache_ttl_seconds: int = 300) -> dict:
    """HTTP GET against football-data.org v4 API with in-process caching."""
    if not FDO_API_KEY:
        return {}

    cache_key = f"fdo:{path}:{sorted((params or {}).items())}"
    cached = _cache.get(cache_key)
    if cached and time.monotonic() < cached[1]:
        return cached[0]

    try:
        import requests as _req
        url = f"{FDO_BASE_URL}/{path.lstrip('/')}"
        resp = _req.get(
            url,
            headers={"X-Auth-Token": FDO_API_KEY},
            params=params or {},
            timeout=10,
        )
        if resp.status_code == 429:
            _logger.warning("football-data.org rate limit hit")
            return {}
        if resp.status_code == 403:
            _logger.error("football-data.org 403 — check API key or plan permissions")
            return {}
        resp.raise_for_status()
        data = resp.json()
        _cache[cache_key] = (data, time.monotonic() + cache_ttl_seconds)
        return data
    except Exception as exc:
        _logger.warning("football-data.org request failed for %s: %s", path, exc)
        return {}


def _normalize_fdo_match(match: dict, league_id: int) -> dict:
    """Convert a football-data.org match object to api-sports.io v3 fixture shape."""
    if not isinstance(match, dict):
        return {}

    fdo_status = match.get("status", "SCHEDULED")
    status_short = _STATUS_MAP.get(fdo_status, "NS")
    status_long  = _STATUS_LONG.get(status_short, fdo_status)

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    comp = match.get("competition") or {}

    # FDO competition id → our app league_id (cross-check)
    fdo_comp_id = comp.get("id")
    resolved_league_id = _FDO_ID_TO_LEAGUE.get(fdo_comp_id, league_id)

    matchday = match.get("matchday")
    season_obj = match.get("season") or {}
    season_year = None
    if season_obj.get("startDate"):
        try:
            season_year = int(str(season_obj["startDate"])[:4])
        except (ValueError, TypeError):
            pass

    round_str = f"Regular Season - {matchday}" if matchday else ""

    return {
        "fixture": {
            "id": match.get("id", 0),
            "date": match.get("utcDate", ""),
            "status": {"short": status_short, "long": status_long},
            "venue": {"name": "", "city": ""},
        },
        "teams": {
            "home": {
                "id": home.get("id", 0),
                "name": home.get("name") or home.get("shortName") or "Home",
                "logo": home.get("crest") or "",
            },
            "away": {
                "id": away.get("id", 0),
                "name": away.get("name") or away.get("shortName") or "Away",
                "logo": away.get("crest") or "",
            },
        },
        "league": {
            "id": resolved_league_id,
            "name": comp.get("name") or "",
            "season": season_year,
            "round": round_str,
        },
        "goals": {
            "home": full_time.get("home"),
            "away": full_time.get("away"),
        },
        "score": {
            "fulltime": {"home": full_time.get("home"), "away": full_time.get("away")},
        },
        "prediction": {},
        "source": "football-data.org",
    }


def get_upcoming_fixtures_fdo(league_id: int, next_n: int = 20) -> list[dict]:
    """Fetch upcoming SCHEDULED matches for a league from football-data.org."""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        _logger.debug("No FDO code mapping for league_id=%s", league_id)
        return []

    now = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    data = _fdo_get(
        f"competitions/{code}/matches",
        {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to},
        cache_ttl_seconds=300,
    )
    matches = data.get("matches") or []
    fixtures = [_normalize_fdo_match(m, league_id) for m in matches if isinstance(m, dict)]
    fixtures.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""))
    return fixtures[:next_n]


def get_standings_fdo(league_id: int) -> list[dict]:
    """Fetch league standings from football-data.org, normalised to v3 shape."""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        return []

    data = _fdo_get(f"competitions/{code}/standings", cache_ttl_seconds=3600)
    standing_groups = data.get("standings") or []

    # Find the TOTAL type table (overall standings, not home/away split)
    table: list[dict] = []
    for group in standing_groups:
        if group.get("type") == "TOTAL":
            table = group.get("table") or []
            break
    if not table and standing_groups:
        table = (standing_groups[0].get("table") or [])

    rows = []
    for entry in table:
        team = entry.get("team") or {}
        rows.append({
            "rank": entry.get("position"),
            "team": {
                "id": team.get("id", 0),
                "name": team.get("name") or team.get("shortName") or "",
                "logo": team.get("crest") or "",
            },
            "points": entry.get("points"),
            "goalsDiff": entry.get("goalDifference"),
            "form": entry.get("form") or "",
            "all": {
                "played": entry.get("playedGames"),
                "win":    entry.get("won"),
                "draw":   entry.get("draw"),
                "lose":   entry.get("lost"),
                "goals":  {
                    "for":     entry.get("goalsFor"),
                    "against": entry.get("goalsAgainst"),
                },
            },
            "home": {"played": 0, "win": 0, "draw": 0, "lose": 0, "goals": {"for": 0, "against": 0}},
            "away": {"played": 0, "win": 0, "draw": 0, "lose": 0, "goals": {"for": 0, "against": 0}},
        })
    return rows


def get_teams_fdo(league_id: int) -> list[dict]:
    """Fetch teams for a competition from football-data.org, normalised to v3 shape."""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        return []

    data = _fdo_get(f"competitions/{code}/teams", cache_ttl_seconds=86400)
    raw_teams = data.get("teams") or []
    result = []
    for team in raw_teams:
        if not isinstance(team, dict):
            continue
        result.append({
            "team": {
                "id": team.get("id", 0),
                "name": team.get("name") or team.get("shortName") or "",
                "logo": team.get("crest") or "",
                "country": team.get("area", {}).get("name") or "",
            },
            "venue": {"name": team.get("venue") or ""},
        })
    return result


def is_available() -> bool:
    """Return True when a football-data.org key is configured."""
    return bool(FDO_API_KEY)
