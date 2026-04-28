"""
football_data_client.py — football-data.org API v4 adapter for ScorPred.

Normalises responses to the ScorPred canonical fixture shape so match_brain,
evidence, and decision pipelines need zero changes.

Configuration
─────────────
  API_FOOTBALL_PROVIDER=football_data   activate this provider
  FOOTBALL_DATA_KEY=<token>             X-Auth-Token (required)
  FOOTBALL_DATA_BASE_URL=...            default: https://api.football-data.org/v4

Data available via free plan
─────────────────────────────
  ✅ Fixtures / match schedule & results
  ✅ Standings
  ✅ Team rosters
  ✅ Head-to-head results
  ✅ Competition metadata

Data NOT available (marked limited in fixture)
──────────────────────────────────────────────
  ✗  Win-probability predictions
  ✗  Injury lists
  ✗  Bookmaker odds
  ✗  xG / advanced player metrics
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

_logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
FDO_PROVIDER_NAME = "football_data"

# Active when API_FOOTBALL_PROVIDER=football_data OR FOOTBALL_DATA_KEY set.
# FOOTBALL_DATA_ORG_KEY accepted as legacy alias.
FDO_KEY = (
    os.getenv("FOOTBALL_DATA_KEY", "")
    or os.getenv("FOOTBALL_DATA_ORG_KEY", "")
    or os.getenv("FOOTBALL_DATA_ORG_KEY", "")
).strip()
FDO_BASE_URL = os.getenv(
    "FOOTBALL_DATA_BASE_URL",
    os.getenv("FOOTBALL_DATA_ORG_BASE_URL", "https://api.football-data.org/v4"),
).rstrip("/")

_PROVIDER_ENV = os.getenv("API_FOOTBALL_PROVIDER", "").strip().lower()
_ACTIVE = _PROVIDER_ENV == "football_data" or bool(FDO_KEY)

# ── All competitions available on the free plan ─────────────────────────────
AVAILABLE_COMPETITIONS: dict[str, str] = {
    "WC":  "FIFA World Cup",
    "CL":  "UEFA Champions League",
    "BL1": "Bundesliga",
    "DED": "Eredivisie",
    "BSA": "Campeonato Brasileiro Série A",
    "PD":  "Primera Division",
    "FL1": "Ligue 1",
    "ELC": "Championship",
    "PPL": "Primeira Liga",
    "EC":  "European Championship",
    "SA":  "Serie A",
    "PL":  "Premier League",
}

# App league IDs (api-sports.io convention) → FDO competition codes
_LEAGUE_TO_FDO_CODE: dict[int, str] = {
    39:  "PL",    # Premier League
    140: "PD",    # La Liga
    135: "SA",    # Serie A
    78:  "BL1",   # Bundesliga
    61:  "FL1",   # Ligue 1
    2:   "CL",    # Champions League
}

# FDO numeric competition id → app league ID
_FDO_COMP_ID_TO_LEAGUE: dict[int, int] = {
    2021: 39,
    2014: 140,
    2019: 135,
    2002: 78,
    2015: 61,
    2001: 2,
}

# ── Status mapping ───────────────────────────────────────────────────────────
# ScorPred canonical status (used in top-level fixture.status)
_FDO_TO_CANONICAL_STATUS: dict[str, str] = {
    "SCHEDULED":  "scheduled",
    "TIMED":      "scheduled",
    "IN_PLAY":    "live",
    "PAUSED":     "live",
    "FINISHED":   "completed",
    "POSTPONED":  "unavailable",
    "SUSPENDED":  "unavailable",
    "CANCELLED":  "unavailable",
    "AWARDED":    "completed",
}

# v3-compatible short codes (used inside fixture.fixture.status for match_brain)
_FDO_TO_V3_SHORT: dict[str, str] = {
    "SCHEDULED":  "NS",
    "TIMED":      "NS",
    "IN_PLAY":    "1H",
    "PAUSED":     "HT",
    "FINISHED":   "FT",
    "POSTPONED":  "PST",
    "SUSPENDED":  "SUSP",
    "CANCELLED":  "CANC",
    "AWARDED":    "FT",
}

_V3_SHORT_TO_LONG: dict[str, str] = {
    "NS":   "Not Started",
    "1H":   "First Half",
    "HT":   "Halftime",
    "FT":   "Match Finished",
    "PST":  "Postponed",
    "SUSP": "Suspended",
    "CANC": "Cancelled",
    "AWD":  "Awarded",
}

# ── Provider health tracking ─────────────────────────────────────────────────
_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "last_success": None,
    "last_error": None,
    "error_count": 0,
    "rate_limited": False,
    "rate_limit_reset": None,
}

# Simple in-process response cache: key → (data, expires_monotonic)
_cache: dict[str, tuple[Any, float]] = {}


def _record_success() -> None:
    with _stats_lock:
        _stats["last_success"] = datetime.now(timezone.utc).isoformat()
        _stats["rate_limited"] = False


def _record_error(msg: str, rate_limited: bool = False) -> None:
    with _stats_lock:
        _stats["last_error"] = msg
        _stats["error_count"] += 1
        if rate_limited:
            _stats["rate_limited"] = True
            _stats["rate_limit_reset"] = (
                datetime.now(timezone.utc) + timedelta(minutes=1)
            ).isoformat()


# ── HTTP client ──────────────────────────────────────────────────────────────

def fdo_get(path: str, params: dict | None = None, cache_ttl: int = 300) -> dict:
    """
    GET /v4/<path> from football-data.org.

    Returns the parsed JSON dict (empty dict on error).
    Cache key includes path + sorted params.
    """
    if not FDO_KEY:
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
            headers={
                "X-Auth-Token": FDO_KEY,
                "Accept": "application/json",
            },
            params=params or {},
            timeout=10,
        )

        if resp.status_code == 429:
            _record_error("rate limited (HTTP 429)", rate_limited=True)
            _logger.warning("football-data.org: rate limit hit on %s", path)
            return {}

        if resp.status_code == 403:
            msg = f"403 on {path} — check key/plan permissions"
            _record_error(msg)
            _logger.error("football-data.org: %s", msg)
            return {}

        if resp.status_code == 404:
            _logger.debug("football-data.org: 404 for %s", path)
            return {}

        resp.raise_for_status()
        data = resp.json()
        _cache[cache_key] = (data, time.monotonic() + cache_ttl)
        _record_success()
        return data

    except Exception as exc:
        _record_error(str(exc))
        _logger.warning("football-data.org request failed [%s]: %s", path, exc)
        return {}


# ── Normalization ─────────────────────────────────────────────────────────────

def _team_block(raw: dict) -> dict:
    return {
        "id":   raw.get("id", 0),
        "name": raw.get("name") or raw.get("shortName") or "",
        "logo": raw.get("crest") or "",
    }


def normalize_match(match: dict, league_id: int | None = None) -> dict:
    """
    Convert a football-data.org match object to the ScorPred canonical fixture shape.

    The returned dict is compatible with both:
    • match_brain.canonical_from_fixture() — reads fixture.fixture.id, fixture.teams.*, etc.
    • The ScorPred canonical top-level fields — match_id, home_team, status, etc.
    """
    if not isinstance(match, dict) or not match.get("id"):
        return {}

    fdo_status = match.get("status", "SCHEDULED")
    canonical_status = _FDO_TO_CANONICAL_STATUS.get(fdo_status, "scheduled")
    v3_short = _FDO_TO_V3_SHORT.get(fdo_status, "NS")
    v3_long  = _V3_SHORT_TO_LONG.get(v3_short, fdo_status)

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_block = _team_block(home)
    away_block = _team_block(away)

    score_obj  = match.get("score") or {}
    full_time  = score_obj.get("fullTime") or {}
    goals_home = full_time.get("home")
    goals_away = full_time.get("away")

    winner_raw = score_obj.get("winner")  # "HOME_TEAM" | "AWAY_TEAM" | "DRAW" | None
    winner_map = {"HOME_TEAM": "home", "AWAY_TEAM": "away", "DRAW": "draw"}
    winner = winner_map.get(winner_raw) if winner_raw else None

    comp = match.get("competition") or {}
    fdo_comp_id = comp.get("id")
    resolved_league_id = _FDO_COMP_ID_TO_LEAGUE.get(fdo_comp_id, league_id or 0)
    comp_code = comp.get("code") or ""

    season_obj  = match.get("season") or {}
    season_year: int | None = None
    if season_obj.get("startDate"):
        try:
            season_year = int(str(season_obj["startDate"])[:4])
        except (ValueError, TypeError):
            pass

    matchday = match.get("matchday")
    round_str = f"Regular Season - {matchday}" if matchday else ""

    match_id = match.get("id", 0)
    kickoff  = match.get("utcDate", "")

    return {
        # ── ScorPred canonical top-level fields ──────────────────────────────
        "match_id":   str(match_id),
        "home_team":  home_block,
        "away_team":  away_block,
        "kickoff":    kickoff,
        "status":     canonical_status,
        "score":      {"home": goals_home, "away": goals_away},
        "winner":     winner,
        "competition": {
            "id":   resolved_league_id,
            "name": comp.get("name") or "",
            "code": comp_code,
        },
        "source": "football-data.org",

        # ── v3-compatible fields for match_brain / evidence pipeline ─────────
        "fixture": {
            "id":     match_id,
            "date":   kickoff,
            "status": {"short": v3_short, "long": v3_long},
            "venue":  {"name": "", "city": ""},
        },
        "teams": {
            "home": home_block,
            "away": away_block,
        },
        "league": {
            "id":     resolved_league_id,
            "name":   comp.get("name") or "",
            "season": season_year,
            "round":  round_str,
        },
        "goals": {
            "home": goals_home,
            "away": goals_away,
        },

        # ── Prediction block: marks limited data so match_brain degrades ─────
        "prediction": {
            "win_probabilities": {"a": None, "draw": None, "b": None},
            "best_pick":         {},
            "confidence_pct":    None,
            "odds":              {},
            "data_completeness": {
                "tier":             "limited",
                "prediction_source": "fixture/results only",
                "available":        ["teams", "kickoff", "status", "score", "competition", "standings"],
                "unavailable":      ["injuries", "odds", "win_probabilities", "advanced_metrics"],
            },
        },
    }


# ── Public endpoint helpers ──────────────────────────────────────────────────

def get_upcoming_fixtures(league_id: int, next_n: int = 20) -> list[dict]:
    """Fetch upcoming SCHEDULED matches for a league. Endpoint: /competitions/{code}/matches"""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        _logger.debug("fdo: no competition code for league_id=%s", league_id)
        return []

    now       = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    data = fdo_get(
        f"competitions/{code}/matches",
        {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to},
        cache_ttl=300,
    )
    matches  = data.get("matches") or []
    fixtures = [normalize_match(m, league_id) for m in matches if isinstance(m, dict)]
    fixtures.sort(key=lambda f: str(f.get("kickoff") or ""))
    return fixtures[:next_n]


def get_match(match_id: int | str) -> dict:
    """Fetch a single match. Endpoint: /matches/{id}"""
    data = fdo_get(f"matches/{match_id}", cache_ttl=120)
    match = data.get("match") or data  # FDO wraps in {"match": {...}} for single-match endpoint
    return normalize_match(match) if isinstance(match, dict) and match.get("id") else {}


def get_head2head(match_id: int | str, limit: int = 10) -> list[dict]:
    """Fetch head-to-head history for a fixture. Endpoint: /matches/{id}/head2head"""
    data = fdo_get(f"matches/{match_id}/head2head", {"limit": limit}, cache_ttl=3600)
    matches = data.get("matches") or []
    return [normalize_match(m) for m in matches if isinstance(m, dict)]


def get_team_matches(team_id: int, limit: int = 10, status: str = "FINISHED") -> list[dict]:
    """Fetch recent matches for a team. Endpoint: /teams/{id}/matches"""
    data = fdo_get(f"teams/{team_id}/matches", {"status": status, "limit": limit}, cache_ttl=1800)
    matches = data.get("matches") or []
    return [normalize_match(m) for m in matches if isinstance(m, dict)]


def get_standings(league_id: int) -> list[dict]:
    """Fetch standings. Endpoint: /competitions/{code}/standings"""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        return []

    data = fdo_get(f"competitions/{code}/standings", cache_ttl=3600)
    groups = data.get("standings") or []

    table: list[dict] = []
    for group in groups:
        if group.get("type") == "TOTAL":
            table = group.get("table") or []
            break
    if not table and groups:
        table = groups[0].get("table") or []

    rows = []
    for entry in table:
        team = entry.get("team") or {}
        rows.append({
            "rank": entry.get("position"),
            "team": {
                "id":   team.get("id", 0),
                "name": team.get("name") or team.get("shortName") or "",
                "logo": team.get("crest") or "",
            },
            "points":    entry.get("points"),
            "goalsDiff": entry.get("goalDifference"),
            "form":      entry.get("form") or "",
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


def get_teams(league_id: int) -> list[dict]:
    """Fetch teams for a competition. Endpoint: /competitions/{code}/teams"""
    code = _LEAGUE_TO_FDO_CODE.get(league_id)
    if not code:
        return []

    data = fdo_get(f"competitions/{code}/teams", cache_ttl=86400)
    raw_teams = data.get("teams") or []
    result = []
    for team in raw_teams:
        if not isinstance(team, dict):
            continue
        result.append({
            "team": {
                "id":      team.get("id", 0),
                "name":    team.get("name") or team.get("shortName") or "",
                "logo":    team.get("crest") or "",
                "country": (team.get("area") or {}).get("name") or "",
            },
            "venue": {"name": team.get("venue") or ""},
        })
    return result


# ── Provider metadata ────────────────────────────────────────────────────────

def is_available() -> bool:
    """True when a football-data.org key is configured and provider is active."""
    return _ACTIVE and bool(FDO_KEY)


def get_provider_info() -> dict:
    """Return provider metadata for the /health endpoint."""
    with _stats_lock:
        stats = dict(_stats)
    return {
        "provider":               FDO_PROVIDER_NAME,
        "base_url":               FDO_BASE_URL,
        "available_competitions": sorted(AVAILABLE_COMPETITIONS.keys()),
        "supported_league_ids":   sorted(_LEAGUE_TO_FDO_CODE.keys()),
        "last_success":           stats["last_success"],
        "last_error":             stats["last_error"],
        "error_count":            stats["error_count"],
        "rate_limited":           stats["rate_limited"],
        "rate_limit_reset":       stats["rate_limit_reset"],
    }
