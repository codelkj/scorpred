"""
Live NBA data client built around ESPN's public JSON endpoints.

This module keeps the existing standings/team-stats helpers from nba_client,
but replaces mock scoreboards, schedules, rosters, and injuries with live data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import nba_client as legacy
from runtime_paths import cache_dir

logger = logging.getLogger(__name__)

NBA_SEASON = getattr(legacy, "NBA_SEASON", datetime.now().year)
NBA_ESPN_BASE_URL = os.getenv(
    "NBA_ESPN_BASE_URL",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba",
).rstrip("/")
EXTERNAL_API_TIMEOUT_SECONDS = float(os.getenv("EXTERNAL_API_TIMEOUT_SECONDS", "20"))
EXTERNAL_API_RETRY_ATTEMPTS = max(1, int(os.getenv("EXTERNAL_API_RETRY_ATTEMPTS", "3")))
EXTERNAL_API_RETRY_BACKOFF_SECONDS = float(os.getenv("EXTERNAL_API_RETRY_BACKOFF_SECONDS", "1.2"))
PAGE_RENDER_TIMEOUT_SECONDS = float(os.getenv("EXTERNAL_API_PAGE_TIMEOUT_SECONDS", "3"))
PAGE_RENDER_RETRY_ATTEMPTS = max(1, int(os.getenv("EXTERNAL_API_PAGE_RETRY_ATTEMPTS", "1")))
PAGE_RENDER_RETRY_BACKOFF_SECONDS = float(os.getenv("EXTERNAL_API_PAGE_RETRY_BACKOFF_SECONDS", "0.0"))

NBA_CACHE_DIR = cache_dir("nba_public")
NBA_LIVE_TTL_SECONDS = 60
NBA_SCHEDULE_TTL_SECONDS = 60 * 60
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

# Process-level caches reduce disk I/O and repeated schedule normalization work
# when users navigate between NBA pages in the same running app instance.
_MEM_CACHE: dict[str, tuple[float, Any]] = {}
_SCHEDULE_MEM: dict[str, tuple[float, list[dict[str, Any]]]] = {}

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
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age.total_seconds() < ttl_seconds


def _load_cache(path: Path) -> Any:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def _save_cache(path: Path, payload: Any) -> None:
    NBA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file)


def _request_settings(request_profile: str = "default") -> tuple[float, int, float]:
    if request_profile == "page":
        return (
            PAGE_RENDER_TIMEOUT_SECONDS,
            PAGE_RENDER_RETRY_ATTEMPTS,
            PAGE_RENDER_RETRY_BACKOFF_SECONDS,
        )
    return (
        EXTERNAL_API_TIMEOUT_SECONDS,
        EXTERNAL_API_RETRY_ATTEMPTS,
        EXTERNAL_API_RETRY_BACKOFF_SECONDS,
    )


def _espn_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
    ttl_seconds: int = NBA_SCHEDULE_TTL_SECONDS,
    request_profile: str = "default",
) -> Any:
    params = params or {}
    now_ts = time.time()
    mem_key = f"espn:{endpoint}:{tuple(sorted(params.items()))}"
    cached = _MEM_CACHE.get(mem_key)
    if cached and cached[0] > now_ts:
        return cached[1]

    path = _cache_path(f"espn:{endpoint}", params)

    if _cache_valid(path, ttl_seconds):
<<<<<<< HEAD
        logger.debug("ESPN cache HIT  %s", endpoint)
        return _load_cache(path)
=======
        payload = _load_cache(path)
        _MEM_CACHE[mem_key] = (now_ts + ttl_seconds, payload)
        return payload
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561

    logger.debug("ESPN cache MISS %s", endpoint)
    url = f"{NBA_ESPN_BASE_URL}/{endpoint.lstrip('/')}"
<<<<<<< HEAD
    timeout_seconds, retry_attempts, retry_backoff_seconds = _request_settings(request_profile)
    last_exc: Exception | None = None
    for attempt in range(retry_attempts):
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=timeout_seconds,
                )

            if response.status_code in RETRY_STATUS_CODES and attempt < retry_attempts - 1:
                time.sleep(retry_backoff_seconds * (2 ** attempt))
                continue

            response.raise_for_status()
            payload = response.json()
            _save_cache(path, payload)
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < retry_attempts - 1:
                time.sleep(retry_backoff_seconds * (2 ** attempt))
                continue

    if path.exists():
        logger.warning("ESPN STALE fallback for %s", endpoint)
        return _load_cache(path)
    raise RuntimeError(f"NBA ESPN request failed for {endpoint}") from last_exc
=======
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
    _MEM_CACHE[mem_key] = (now_ts + ttl_seconds, payload)
    return payload
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561


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
    try:
        stats = legacy.get_team_season_stats(team_id, season)
        if stats:
            return stats
    except Exception:
        pass

    games = _latest_completed_team_games(team_id, season=season, enrich_scores=True)
    return _derive_team_stats_from_games(team_id, games)


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


def get_scoreboard_games(target_date: datetime | None = None, request_profile: str = "default") -> list[dict]:
    target_date = target_date or datetime.now()
    payload = _espn_get(
        "scoreboard",
        params={"dates": _ymd(target_date)},
        ttl_seconds=NBA_LIVE_TTL_SECONDS,
        request_profile=request_profile,
    )
    games = []
    for event in payload.get("events") or []:
        if normalized := _normalize_event(event):
            games.append(normalized)
    games.sort(key=lambda game: game["date"]["start"])
    return games


def get_today_games(request_profile: str = "default") -> list[dict]:
    return get_scoreboard_games(request_profile=request_profile)


def get_upcoming_games(next_n: int = 12, days_ahead: int = 5, request_profile: str = "default") -> list[dict]:
    now = datetime.now()
    dates = [now + timedelta(days=d) for d in range(days_ahead + 1)]

    # Fetch all dates in parallel instead of sequentially
    from concurrent.futures import ThreadPoolExecutor, as_completed
    day_results: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(len(dates), 6)) as pool:
        futs = {pool.submit(get_scoreboard_games, d, request_profile): i for i, d in enumerate(dates)}
        for fut in as_completed(futs):
            try:
                day_results[futs[fut]] = fut.result()
            except Exception:
                day_results[futs[fut]] = []

    seen: set[str] = set()
    upcoming: list[dict] = []
    for i in range(len(dates)):
        for game in day_results.get(i, []):
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


def get_event_snapshot(event_id: str, date_hint: str | None = None, request_profile: str = "default") -> dict | None:
    event_id = str(event_id)
    for candidate in _candidate_dates_from_hint(date_hint):
        for game in get_scoreboard_games(candidate, request_profile=request_profile):
            if game["id"] == event_id:
                return game
    return None


def get_game_summary(event_id: str, request_profile: str = "default") -> dict:
    return _espn_get(
        "summary",
        params={"event": str(event_id)},
        ttl_seconds=NBA_LIVE_TTL_SECONDS,
        request_profile=request_profile,
    )


<<<<<<< HEAD
def _team_schedule(team_id: str, season: int | None = None, request_profile: str = "default") -> list[dict]:
=======
def _team_schedule(team_id: str, season: int | None = None) -> list[dict]:
    season_key = "none" if season is None else str(season)
    mem_key = f"team_schedule:{team_id}:{season_key}"
    now_ts = time.time()
    mem_cached = _SCHEDULE_MEM.get(mem_key)
    if mem_cached and mem_cached[0] > now_ts:
        return mem_cached[1]

>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561
    params: dict = {}
    if season is not None:
        params["season"] = season
    payload = _espn_get(
        f"teams/{team_id}/schedule",
        params=params if params else None,
        ttl_seconds=NBA_SCHEDULE_TTL_SECONDS,
        request_profile=request_profile,
    )
    events = []
    for event in payload.get("events") or []:
        if normalized := _normalize_event(event):
            events.append(normalized)
    _SCHEDULE_MEM[mem_key] = (now_ts + NBA_SCHEDULE_TTL_SECONDS, events)
    return events


<<<<<<< HEAD
def _completed_team_games_for_season(team_id: str, season: int, request_profile: str = "default") -> list[dict]:
    finished = [game for game in _team_schedule(team_id, season=season, request_profile=request_profile) if game["status"]["state"] == "post"]
=======
def get_team_recent_form(team_id, season: int = NBA_SEASON, n: int = 10) -> list[dict]:
    team_id = str(team_id)
    finished = [
        game
        for game in _team_schedule(team_id, season=season)
        if game["status"]["state"] == "post"
    ]
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561
    finished.sort(key=lambda game: game["date"]["start"], reverse=True)
    return finished


def _extract_summary_scores(summary: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    competitions = ((summary.get("header") or {}).get("competitions") or [])
    if not competitions:
        return None
    competitors = competitions[0].get("competitors") or []
    home = next((entry for entry in competitors if entry.get("homeAway") == "home"), None)
    away = next((entry for entry in competitors if entry.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    return {
        "scores": {
            "home": {
                "points": _as_int(home.get("score")),
                "linescore": [line.get("displayValue") or str(line.get("value")) for line in (home.get("linescores") or [])],
            },
            "visitors": {
                "points": _as_int(away.get("score")),
                "linescore": [line.get("displayValue") or str(line.get("value")) for line in (away.get("linescores") or [])],
            },
        },
        "records": {
            "home": home.get("record") or [],
            "visitors": away.get("record") or [],
        },
        "event_id": str(event_id),
    }


def _enrich_game_scores(game: dict[str, Any], request_profile: str = "default") -> dict[str, Any]:
    if game["scores"]["home"].get("points") is not None and game["scores"]["visitors"].get("points") is not None:
        return game

    event_id = str(game.get("id") or "")
    if not event_id:
        return game

    try:
        summary = get_game_summary(event_id, request_profile=request_profile)
    except Exception:
        return game

    enriched = _extract_summary_scores(summary, event_id)
    if not enriched:
        return game

    game["scores"] = enriched["scores"]
    game["records"] = enriched["records"]
    return game


def _latest_completed_team_games(
    team_id: str,
    season: int = NBA_SEASON,
    lookback_seasons: int = 0,
    enrich_scores: bool = False,
    request_profile: str = "default",
) -> list[dict]:
    team_id = str(team_id)
    for candidate_season in range(season, season - lookback_seasons - 1, -1):
        try:
            games = _completed_team_games_for_season(team_id, candidate_season, request_profile=request_profile)
        except TypeError:
            games = _completed_team_games_for_season(team_id, candidate_season)
        if games:
            if enrich_scores:
                return [_enrich_game_scores(dict(game), request_profile=request_profile) for game in games]
            return games
    return []


def _season_from_game_date(game: dict[str, Any]) -> int | None:
    date_text = ((game.get("date") or {}).get("start") or "")[:10]
    if not date_text:
        return None
    try:
        dt = datetime.fromisoformat(date_text)
    except ValueError:
        return None
    # NBA regular season spans two years; treat Jul-Dec as season year and Jan-Jun as previous season year.
    return dt.year if dt.month >= 7 else dt.year - 1


def get_team_recent_form_context(team_id, season: int = NBA_SEASON, n: int = 10, historical_lookback: int = 2, request_profile: str = "default") -> dict[str, Any]:
    """Return current-season recent form plus optional clearly-separated historical context."""
    team_id = str(team_id)
    current = _latest_completed_team_games(
        team_id,
        season=season,
        lookback_seasons=0,
        enrich_scores=True,
        request_profile=request_profile,
    )[:n]
    historical: list[dict[str, Any]] = []
    historical_season: int | None = None

    if not current:
        for candidate in range(season - 1, season - historical_lookback - 1, -1):
            try:
                rows = _completed_team_games_for_season(team_id, candidate, request_profile=request_profile)
            except TypeError:
                rows = _completed_team_games_for_season(team_id, candidate)
            if rows:
                historical = [_enrich_game_scores(dict(game), request_profile=request_profile) for game in rows[:n]]
                historical_season = candidate
                break

    return {
        "current_games": current,
        "historical_games": historical,
        "current_season": season,
        "historical_season": historical_season,
        "current_complete": len(current) >= min(5, n),
        "using_historical_context": bool(historical),
    }


def _points_for_team(game: dict[str, Any], team_id: str) -> tuple[int | None, int | None, bool | None]:
    team_id = str(team_id)
    home = game["teams"]["home"]
    away = game["teams"]["visitors"]
    home_points = _as_int(game["scores"]["home"].get("points"))
    away_points = _as_int(game["scores"]["visitors"].get("points"))

    if str(home.get("id") or "") == team_id:
        return home_points, away_points, True
    if str(away.get("id") or "") == team_id:
        return away_points, home_points, False
    return None, None, None


def _record_string(wins: int, losses: int) -> str:
    return f"{wins}-{losses}"


def _parse_record_value(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    if "-" not in text:
        return 0, 0
    left, right = text.split("-", 1)
    return _as_int(left) or 0, _as_int(right) or 0


def _team_record_map(game: dict[str, Any], team_id: str) -> dict[str, str]:
    team_id = str(team_id)
    side = "home" if str(game["teams"]["home"].get("id") or "") == team_id else "visitors"
    entries = game.get("records", {}).get(side) or []
    records: dict[str, str] = {}
    for entry in entries:
        record_type = str(entry.get("type") or "").strip().lower()
        summary = entry.get("summary") or entry.get("displayValue") or ""
        if record_type:
            records[record_type] = summary
    return records


def _derive_team_stats_from_games(team_id: str, games: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not games:
        return None

    team_id = str(team_id)
    totals = {
        "wins": 0,
        "losses": 0,
        "points_for": 0,
        "points_against": 0,
        "home_w": 0,
        "home_l": 0,
        "away_w": 0,
        "away_l": 0,
    }
    recent_results: list[str] = []
    scored_games = 0

    for game in games:
        our_points, their_points, is_home = _points_for_team(game, team_id)
        if our_points is None or their_points is None or is_home is None:
            continue

        scored_games += 1
        won = our_points > their_points
        recent_results.append("W" if won else "L")
        totals["wins" if won else "losses"] += 1
        totals["points_for"] += our_points
        totals["points_against"] += their_points
        if is_home:
            totals["home_w" if won else "home_l"] += 1
        else:
            totals["away_w" if won else "away_l"] += 1

    latest_records = _team_record_map(games[0], team_id)
    total_record = latest_records.get("total", "")
    home_record = latest_records.get("home", "")
    away_record = latest_records.get("road", latest_records.get("away", ""))
    record_wins, record_losses = _parse_record_value(total_record)

    total_games = totals["wins"] + totals["losses"]
    if record_wins or record_losses:
        totals["wins"] = record_wins
        totals["losses"] = record_losses
        total_games = record_wins + record_losses
    if total_games == 0:
        return None

    last10_results = recent_results[:10]
    last10_wins = sum(1 for result in last10_results if result == "W")
    last10_losses = len(last10_results) - last10_wins

    streak_value = ""
    if recent_results:
        streak_result = recent_results[0]
        streak_count = 0
        for result in recent_results:
            if result != streak_result:
                break
            streak_count += 1
        streak_value = f"{streak_result}{streak_count}"

    return {
        "games": total_games,
        "wins": totals["wins"],
        "losses": totals["losses"],
        "win_pct": round(totals["wins"] / total_games, 3),
        "ppg": round(totals["points_for"] / max(scored_games, 1), 1),
        "opp_ppg": round(totals["points_against"] / max(scored_games, 1), 1),
        "net_rtg": round((totals["points_for"] - totals["points_against"]) / max(scored_games, 1), 1),
        "home_record": home_record or _record_string(totals["home_w"], totals["home_l"]),
        "away_record": away_record or _record_string(totals["away_w"], totals["away_l"]),
        "home_w": totals["home_w"],
        "home_l": totals["home_l"],
        "away_w": totals["away_w"],
        "away_l": totals["away_l"],
        "last10": _record_string(last10_wins, last10_losses),
        "last10_w": last10_wins,
        "last10_l": last10_losses,
        "streak": streak_value,
    }


def get_team_recent_form(team_id, season: int = NBA_SEASON, n: int = 10, request_profile: str = "default") -> list[dict]:
    team_id = str(team_id)
    context = get_team_recent_form_context(team_id, season=season, n=n, historical_lookback=0, request_profile=request_profile)
    return context.get("current_games") or []


def get_h2h(team_a_id, team_b_id, season: int = NBA_SEASON, request_profile: str = "default") -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    team_a_id = str(team_a_id)
    team_b_id = str(team_b_id)
    seen_ids: set[str] = set()
    games: list[dict] = []
    target_set = {team_a_id, team_b_id}

    def _scan_season(yr: int) -> list[dict]:
        found: list[dict] = []
        try:
            for game in _team_schedule(team_a_id, season=yr, request_profile=request_profile):
                if game["status"]["state"] != "post":
                    continue
                home_id = game["teams"]["home"]["id"]
                away_id = game["teams"]["visitors"]["id"]
                if {home_id, away_id} != target_set:
                    continue
                found.append(game)
        except Exception:
            pass
        return found

    # Fetch 5 seasons in parallel
    seasons = list(range(season - 4, season + 1))
    with ThreadPoolExecutor(max_workers=len(seasons)) as pool:
        season_results = list(pool.map(_scan_season, seasons))

    for season_games in season_results:
        for game in season_games:
            gid = game["id"]
            if gid not in seen_ids:
                seen_ids.add(gid)
                games.append(_enrich_game_scores(dict(game), request_profile=request_profile))

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


def get_team_roster(team_id, season: int = NBA_SEASON, request_profile: str = "default") -> list[dict]:
    payload = _espn_get(
        f"teams/{team_id}/roster",
        ttl_seconds=NBA_SCHEDULE_TTL_SECONDS,
        request_profile=request_profile,
    )
    roster = [_normalize_roster_player(player) for player in (payload.get("athletes") or [])]
    roster.sort(key=lambda player: (player["lastname"], player["firstname"]))
    return roster


def get_injuries_from_roster(roster: list[dict]) -> list[dict]:
    injuries = []
    for player in roster:
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


def get_team_injuries(team_id, season: int = NBA_SEASON, request_profile: str = "default") -> list[dict]:
    roster = get_team_roster(team_id, season=season, request_profile=request_profile)
    return get_injuries_from_roster(roster)


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
