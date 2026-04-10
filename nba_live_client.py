"""
Live NBA data client built around ESPN's public JSON endpoints.

This module keeps the existing standings/team-stats helpers from nba_client,
but replaces mock scoreboards, schedules, rosters, and injuries with live data.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import nba_client as legacy


NBA_SEASON = getattr(legacy, "NBA_SEASON", datetime.now().year)
NBA_ESPN_BASE_URL = os.getenv(
    "NBA_ESPN_BASE_URL",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba",
).rstrip("/")

NBA_CACHE_DIR = Path("cache/nba_public")
NBA_LIVE_TTL_SECONDS = 60
NBA_SCHEDULE_TTL_SECONDS = 60 * 60

ROUTE_FEATURES: dict[str, list[str]] = {
    "index": ["teams", "scoreboard"],
    "matchup": ["team_stats", "h2h", "form", "injuries"],
    "player": ["roster", "player_stats"],
    "prediction": ["team_stats", "h2h", "form", "injuries"],
    "standings": ["standings"],
}


def _cache_path(endpoint: str, params: dict[str, Any] | None = None) -> Path:
    raw = f"{endpoint}:{sorted((params or {}).items())}"
    key = hashlib.md5(raw.encode("utf-8")).hexdigest()
    NBA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return NBA_CACHE_DIR / f"{key}.json"


def _cache_valid(path: Path, ttl_seconds: int) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age.total_seconds() < ttl_seconds


def _load_cache(path: Path) -> Any:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def _save_cache(path: Path, payload: Any) -> None:
    NBA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file)


def _espn_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
    ttl_seconds: int = NBA_SCHEDULE_TTL_SECONDS,
) -> Any:
    params = params or {}
    path = _cache_path(f"espn:{endpoint}", params)

    if _cache_valid(path, ttl_seconds):
        return _load_cache(path)

    url = f"{NBA_ESPN_BASE_URL}/{endpoint.lstrip('/')}"
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=20,
        )
    response.raise_for_status()
    payload = response.json()
    _save_cache(path, payload)
    return payload


def _feature_catalog() -> dict[str, dict[str, str]]:
    return {
        "teams": {
            "state": "live",
            "title": "Live team directory",
            "detail": "Team identities come from the current provider-backed NBA team directory.",
        },
        "standings": {
            "state": "live",
            "title": "Live standings",
            "detail": "Standings and team-level season stats are live from the configured standings feed.",
        },
        "team_stats": {
            "state": "live",
            "title": "Live team stats",
            "detail": "Season records, PPG, opponent PPG, and net rating are live.",
        },
        "scoreboard": {
            "state": "live",
            "title": "Live scoreboard",
            "detail": "Upcoming, scheduled, and in-progress NBA games are pulled from ESPN's public scoreboard feed.",
        },
        "h2h": {
            "state": "live",
            "title": "Live matchup history",
            "detail": "Head-to-head history is built from real completed games on the public team schedule feed.",
        },
        "form": {
            "state": "live",
            "title": "Live recent form",
            "detail": "Recent form is built from real completed games on each team's public schedule feed.",
        },
        "injuries": {
            "state": "live",
            "title": "Live injuries",
            "detail": "Injury statuses come from the public team roster feed for the selected teams.",
        },
        "roster": {
            "state": "live",
            "title": "Live rosters",
            "detail": "Rosters come from ESPN's public team roster endpoint.",
        },
        "player_stats": {
            "state": "fallback",
            "title": "Roster-first player view",
            "detail": "The app now shows live rosters and featured leaders for the selected game, but full player game-log props are still limited by public endpoint coverage.",
        },
    }


def get_route_support(route_name: str) -> dict[str, dict[str, str]]:
    catalog = _feature_catalog()
    return {
        key: catalog[key]
        for key in ROUTE_FEATURES.get(route_name, [])
        if key in catalog
    }


def get_teams() -> list[dict]:
    return legacy.get_teams()


def get_standings(season: int = NBA_SEASON) -> dict:
    return legacy.get_standings(season)


def get_team_season_stats(team_id, season: int = NBA_SEASON):
    return legacy.get_team_season_stats(team_id, season)


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _team_from_competitor(competitor: dict[str, Any]) -> dict[str, Any]:
    team = competitor.get("team") or {}
    return {
        "id": str(team.get("id") or competitor.get("id") or ""),
        "name": team.get("displayName") or team.get("name") or "Team",
        "nickname": team.get("shortDisplayName") or team.get("name") or "Team",
        "city": team.get("location", ""),
        "abbrev": team.get("abbreviation", ""),
        "logo": team.get("logo")
        or ((team.get("logos") or [{}])[0].get("href"))
        or "",
    }


def _event_state(status: dict[str, Any]) -> str:
    return ((status or {}).get("type") or {}).get("state", "")


def _event_status(status: dict[str, Any]) -> dict[str, Any]:
    type_info = (status or {}).get("type") or {}
    return {
        "long": type_info.get("description") or status.get("type") or "Scheduled",
        "short": type_info.get("shortDetail") or status.get("displayClock") or "",
        "state": type_info.get("state", ""),
        "detail": type_info.get("detail") or type_info.get("shortDetail") or "",
    }


def _normalize_competition(event: dict[str, Any], competition: dict[str, Any]) -> dict[str, Any] | None:
    competitors = competition.get("competitors") or []
    home = next((entry for entry in competitors if entry.get("homeAway") == "home"), None)
    away = next((entry for entry in competitors if entry.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status = competition.get("status") or event.get("status") or {}
    broadcasts = competition.get("broadcasts") or event.get("broadcasts") or []
    geo_broadcasts = competition.get("geoBroadcasts") or event.get("geoBroadcasts") or []
    venue = competition.get("venue") or {}

    return {
        "id": str(event.get("id") or competition.get("id") or ""),
        "short_name": event.get("shortName", ""),
        "date": {"start": event.get("date") or competition.get("date") or ""},
        "status": _event_status(status),
        "venue": {"name": venue.get("fullName", "")},
        "teams": {
            "home": _team_from_competitor(home),
            "visitors": _team_from_competitor(away),
        },
        "scores": {
            "home": {
                "points": _as_int(home.get("score")),
                "linescore": [
                    line.get("displayValue") or str(line.get("value"))
                    for line in (home.get("linescores") or [])
                ],
            },
            "visitors": {
                "points": _as_int(away.get("score")),
                "linescore": [
                    line.get("displayValue") or str(line.get("value"))
                    for line in (away.get("linescores") or [])
                ],
            },
        },
        "leaders": {
            "home": home.get("leaders") or [],
            "visitors": away.get("leaders") or [],
        },
        "records": {
            "home": home.get("record") or [],
            "visitors": away.get("record") or [],
        },
        "broadcasts": broadcasts,
        "geo_broadcasts": geo_broadcasts,
        "odds": (competition.get("odds") or [{}])[0],
        "attendance": competition.get("attendance"),
        "summary_link": next(
            (link.get("href") for link in (event.get("links") or []) if "summary" in (link.get("rel") or [])),
            "",
        ),
        "is_live": _event_state(status) == "in",
        "is_pre": _event_state(status) == "pre",
        "is_post": _event_state(status) == "post",
    }


def _normalize_event(event: dict[str, Any]) -> dict[str, Any] | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    return _normalize_competition(event, competitions[0])


def _ymd(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def get_scoreboard_games(target_date: datetime | None = None) -> list[dict]:
    target_date = target_date or datetime.now()
    payload = _espn_get(
        "scoreboard",
        params={"dates": _ymd(target_date)},
        ttl_seconds=NBA_LIVE_TTL_SECONDS,
    )
    games = []
    for event in payload.get("events") or []:
        if normalized := _normalize_event(event):
            games.append(normalized)
    games.sort(key=lambda game: game["date"]["start"])
    return games


def get_today_games() -> list[dict]:
    return get_scoreboard_games()


def get_upcoming_games(next_n: int = 12, days_ahead: int = 5) -> list[dict]:
    now = datetime.now()
    seen: set[str] = set()
    upcoming: list[dict] = []

    for day_offset in range(days_ahead + 1):
        for game in get_scoreboard_games(now + timedelta(days=day_offset)):
            if game["id"] in seen:
                continue
            if game.get("status", {}).get("state") not in {"pre", "in"}:
                continue
            seen.add(game["id"])
            upcoming.append(game)
            if len(upcoming) >= next_n:
                return upcoming

    return upcoming


def _candidate_dates_from_hint(date_hint: str | None) -> list[datetime]:
    candidates = []
    if date_hint:
        text = str(date_hint).replace("Z", "+00:00")
        try:
            base = datetime.fromisoformat(text)
        except ValueError:
            try:
                base = datetime.fromisoformat(str(date_hint)[:10])
            except ValueError:
                base = None
        if base is not None:
            candidates.extend([base - timedelta(days=1), base, base + timedelta(days=1)])

    today = datetime.now()
    candidates.extend([today - timedelta(days=1), today, today + timedelta(days=1)])
    unique: list[datetime] = []
    seen_dates: set[str] = set()
    for candidate in candidates:
        key = candidate.strftime("%Y-%m-%d")
        if key not in seen_dates:
            seen_dates.add(key)
            unique.append(candidate)
    return unique


def get_event_snapshot(event_id: str, date_hint: str | None = None) -> dict | None:
    event_id = str(event_id)
    for candidate in _candidate_dates_from_hint(date_hint):
        for game in get_scoreboard_games(candidate):
            if game["id"] == event_id:
                return game
    return None


def get_game_summary(event_id: str) -> dict:
    return _espn_get(
        "summary",
        params={"event": str(event_id)},
        ttl_seconds=NBA_LIVE_TTL_SECONDS,
    )


def _team_schedule(team_id: str, season: int | None = None) -> list[dict]:
    params: dict = {}
    if season is not None:
        params["season"] = season
    payload = _espn_get(
        f"teams/{team_id}/schedule",
        params=params if params else None,
        ttl_seconds=NBA_SCHEDULE_TTL_SECONDS,
    )
    events = []
    for event in payload.get("events") or []:
        if normalized := _normalize_event(event):
            events.append(normalized)
    return events


def get_team_recent_form(team_id, season: int = NBA_SEASON, n: int = 10) -> list[dict]:
    team_id = str(team_id)
    finished = [game for game in _team_schedule(team_id) if game["status"]["state"] == "post"]
    finished.sort(key=lambda game: game["date"]["start"], reverse=True)
    return finished[:n]


def get_h2h(team_a_id, team_b_id, season: int = NBA_SEASON) -> list[dict]:
    team_a_id = str(team_a_id)
    team_b_id = str(team_b_id)
    seen_ids: set[str] = set()
    games: list[dict] = []
    # Fetch the last 5 seasons so H2H is not limited to current season only
    for yr in range(season - 4, season + 1):
        try:
            for game in _team_schedule(team_a_id, season=yr):
                if game["status"]["state"] != "post":
                    continue
                home_id = game["teams"]["home"]["id"]
                away_id = game["teams"]["visitors"]["id"]
                if {home_id, away_id} != {team_a_id, team_b_id}:
                    continue
                gid = game["id"]
                if gid not in seen_ids:
                    seen_ids.add(gid)
                    games.append(game)
        except Exception:
            continue
    games.sort(key=lambda game: game["date"]["start"], reverse=True)
    return games[:10]


def _normalize_roster_player(player: dict[str, Any]) -> dict[str, Any]:
    injuries = player.get("injuries") or []
    position = player.get("position") or {}
    status = player.get("status") or {}
    return {
        "id": str(player.get("id") or ""),
        "firstname": player.get("firstName", ""),
        "lastname": player.get("lastName", ""),
        "displayName": player.get("displayName") or player.get("fullName") or "",
        "photo": (player.get("headshot") or {}).get("href", ""),
        "jersey": player.get("jersey", ""),
        "age": player.get("age"),
        "position": position.get("displayName") or position.get("name") or "",
        "leagues": {
            "standard": {
                "pos": position.get("abbreviation", ""),
                "active": status.get("type") == "active" or status.get("name") == "Active",
            }
        },
        "injuries": injuries,
        "status": status.get("name", ""),
        "_raw": player,
    }


def get_team_roster(team_id, season: int = NBA_SEASON) -> list[dict]:
    payload = _espn_get(
        f"teams/{team_id}/roster",
        ttl_seconds=NBA_SCHEDULE_TTL_SECONDS,
    )
    roster = [_normalize_roster_player(player) for player in (payload.get("athletes") or [])]
    roster.sort(key=lambda player: (player["lastname"], player["firstname"]))
    return roster


def get_team_injuries(team_id) -> list[dict]:
    injuries = []
    for player in get_team_roster(team_id):
        for injury in player.get("injuries") or []:
            injuries.append(
                {
                    "player": {
                        "id": player["id"],
                        "firstname": player["firstname"],
                        "lastname": player["lastname"],
                        "pos": player["leagues"]["standard"]["pos"],
                    },
                    "status": injury.get("status", player.get("status", "")),
                    "description": injury.get("detail") or injury.get("type") or injury.get("status") or "",
                    "date": injury.get("date", ""),
                }
            )
    return injuries


def get_injuries() -> list:
    return []


def get_game_stats(game_id) -> list:
    summary = get_game_summary(str(game_id))
    return (summary.get("boxscore") or {}).get("teams", [])


def _extract_featured_leaders(side: list[dict]) -> list[dict]:
    featured = []
    for leader in side:
        athlete = ((leader.get("leaders") or [{}])[0] or {}).get("athlete") or {}
        if not athlete:
            continue
        featured.append(
            {
                "metric": leader.get("displayName") or leader.get("name") or "",
                "abbreviation": leader.get("abbreviation") or "",
                "value": (leader.get("leaders") or [{}])[0].get("displayValue", ""),
                "name": athlete.get("displayName") or athlete.get("fullName") or "",
                "headshot": athlete.get("headshot", ""),
                "position": (athlete.get("position") or {}).get("abbreviation", ""),
                "team_id": str((athlete.get("team") or {}).get("id") or ""),
            }
        )
    return featured


def get_featured_players_for_event(event_id: str, date_hint: str | None = None) -> dict[str, list[dict]]:
    snapshot = get_event_snapshot(event_id, date_hint=date_hint)
    if not snapshot:
        return {"home": [], "visitors": []}
    return {
        "home": _extract_featured_leaders(snapshot.get("leaders", {}).get("home", [])),
        "visitors": _extract_featured_leaders(snapshot.get("leaders", {}).get("visitors", [])),
    }


def get_player_season_averages(player_id, season: int = NBA_SEASON):
    return None


def get_player_last_n_games(player_id, season: int = NBA_SEASON, n: int = 5) -> list:
    return []


def get_player_vs_team(player_id, team_id, player_team_id, seasons=None) -> dict:
    return {"games": 0, "records": [], "averages": None, "limited_sample": True}


def get_player_stats(player_id, season: int = NBA_SEASON) -> list:
    return []


def get_player_game_log(player_id, season: int = NBA_SEASON, n: int = 10) -> list:
    return []


def compute_last5_averages_from_records(records: list) -> dict | None:
    return None


def format_game_stat_line(stat_record: dict) -> dict:
    return stat_record
