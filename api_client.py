"""
api_client.py — API-Football (RapidAPI) wrapper with JSON caching.

Provider: api-football-v1.p.rapidapi.com
Cache:    cache/football/  (1-hour TTL by default)
Retry:    HTTP 429 → wait 12 s → retry once
On error: returns empty list or empty dict — never raises to caller
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from utils.parsing import safe_float as _sf, safe_int

from league_config import (
    COMP_DIFFICULTY,
    CURRENT_SEASON,
    DEFAULT_LEAGUE_ID,
    LEAGUE_BY_ID,
    SUPPORTED_LEAGUE_IDS,
    _current_football_season,
)

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

API_KEY  = os.getenv("API_FOOTBALL_KEY", "").strip()
API_HOST = os.getenv("API_FOOTBALL_HOST", "api-football-v1.p.rapidapi.com").strip()
API_BASE = os.getenv("API_FOOTBALL_BASE_URL", "https://api-football-v1.p.rapidapi.com/v3").rstrip("/")

CACHE_DIR          = Path("cache/football")
CACHE_HOURS        = 1          # default 1-hour TTL
PROPS_CACHE_DIR    = Path("cache/props")
PLAYER_LOG_TTL_H   = 1
FORCE_REFRESH      = False
RAPIDAPI_OK        = True

ESPN_SLUG_BY_LEAGUE: dict[int, str] = {
    39: "eng.1",
    140: "esp.1",
    135: "ita.1",
    78: "ger.1",
    61: "fra.1",
    2: "uefa.champions",
    3: "uefa.europa",
    848: "uefa.europa.conf",
    45: "eng.fa",
    143: "esp.copa_del_rey",
    137: "ita.coppa_italia",
    81: "ger.dfb_pokal",
    66: "fra.coupe_de_france",
}

LEAGUES: dict[str, int] = {
    "premier_league": 39,
    "la_liga": 140,
    "serie_a": 135,
    "bundesliga": 78,
    "ligue_1": 61,
    "champions_league": 2,
    "europa_league": 3,
    "conference_league": 848,
    "fa_cup": 45,
    "copa_del_rey": 143,
    "coppa_italia": 137,
    "dfb_pokal": 81,
    "coupe_de_france": 66,
}

API_TEAM_ID_ALIASES: dict[int, int] = {
    33: 360,   # Manchester United
    50: 382,   # Manchester City
    66: 362,   # Aston Villa
}

API_PLAYER_ID_ALIASES: dict[int, dict[str, Any]] = {
    276: {"espn_id": 124091, "team_id": 360, "league_id": 39, "name": "Bruno Fernandes"},
}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_V2_BASE = "https://site.api.espn.com/apis/v2/sports/soccer"
ESPN_WEB_BASE = "https://site.web.api.espn.com/apis/common/v3/sports/soccer"

# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_path(endpoint: str, params: dict) -> Path:
    raw = endpoint + str(sorted((params or {}).items()))
    key = hashlib.md5(raw.encode()).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cache_valid(path: Path, hours: int = CACHE_HOURS) -> bool:
    if not path.exists():
        return False
    age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return age < timedelta(hours=hours)


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ── Core HTTP ──────────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "X-RapidAPI-Key":  API_KEY,
        "X-RapidAPI-Host": API_HOST,
        "Accept":          "application/json",
    }


def api_get(
    endpoint: str,
    params: dict | None = None,
    *,
    cache_hours: int = CACHE_HOURS,
    force_refresh: bool = False,
) -> dict:
    """
    GET request to API-Football with caching and 429-retry.
    Raises on non-recoverable HTTP errors; caller wraps in try/except.
    """
    global RAPIDAPI_OK

    params = params or {}
    path   = _cache_path(endpoint, params)
    force_refresh = force_refresh or FORCE_REFRESH

    if not force_refresh and _cache_valid(path, cache_hours):
        return _load(path)

    if not API_KEY:
        raise RuntimeError("API_FOOTBALL_KEY not set in .env")

    if not RAPIDAPI_OK:
        raise RuntimeError("API-Football RapidAPI access is unavailable for this key.")

    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    for attempt in range(2):
        try:
            with requests.Session() as sess:
                sess.trust_env = False
                resp = sess.get(url, headers=_headers(), params=params, timeout=20)
            if resp.status_code == 429 and attempt == 0:
                time.sleep(12)
                continue
            if resp.status_code == 403:
                RAPIDAPI_OK = False
                raise RuntimeError(resp.text[:200] or "API-Football returned 403.")
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                errs = data["errors"]
                if isinstance(errs, dict) and errs:
                    raise RuntimeError(f"API-Football error {endpoint}: {errs}")
            _save(path, data)
            return data
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429 and attempt == 0:
                time.sleep(12)
                continue
            raise
    raise RuntimeError(f"API-Football request failed for {endpoint}")


# -- Runtime controls --------------------------------------------------------

def set_force_refresh(enabled: bool) -> None:
    global FORCE_REFRESH
    FORCE_REFRESH = bool(enabled)


def clear_cache() -> None:
    if CACHE_DIR.exists():
        for path in CACHE_DIR.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass


# -- ESPN fallback helpers ---------------------------------------------------

def _current_espn_season() -> int:
    now = datetime.now(UTC)
    return now.year - 1 if now.month < 7 else now.year


def _requested_or_current_season(_season: int) -> int:
    return _current_espn_season()


def _espn_slug(league_id: int) -> str:
    return ESPN_SLUG_BY_LEAGUE.get(league_id, ESPN_SLUG_BY_LEAGUE[DEFAULT_LEAGUE_ID])


def _espn_cache_key(prefix: str, parts: tuple[Any, ...]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw = prefix + ":" + "|".join(str(part) for part in parts)
    return CACHE_DIR / f"{hashlib.md5(raw.encode('utf-8')).hexdigest()}.json"


def _espn_get_json(url: str, cache_key: str, ttl_hours: float = 1.0) -> dict:
    path = _espn_cache_key("espn", (cache_key,))
    if not FORCE_REFRESH and _cache_valid(path, ttl_hours):
        return _load(path)

    with requests.Session() as session:
        session.trust_env = False
        response = session.get(url, timeout=20, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    _save(path, payload)
    return payload


def _espn_league_teams(league_id: int) -> list[dict]:
    slug = _espn_slug(league_id)
    payload = _espn_get_json(
        f"{ESPN_BASE}/{slug}/teams",
        f"teams:{league_id}:{slug}:{_requested_or_current_season(CURRENT_SEASON)}",
        ttl_hours=6,
    )
    sports = payload.get("sports") or []
    leagues = (sports[0].get("leagues") or []) if sports else []
    return (leagues[0].get("teams") or []) if leagues else []


def _espn_team_lookup(league_id: int) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for entry in _espn_league_teams(league_id):
        team = entry.get("team") or {}
        if team.get("id"):
            lookup[str(team["id"])] = team
    return lookup


def _resolve_team_id(team_id: int, league_id: int = DEFAULT_LEAGUE_ID) -> int:
    raw_id = _si(team_id)
    if not raw_id:
        return raw_id
    if raw_id in API_TEAM_ID_ALIASES:
        return API_TEAM_ID_ALIASES[raw_id]
    lookup = _espn_team_lookup(league_id)
    if str(raw_id) in lookup:
        return raw_id
    return raw_id


def _normalize_position(pos: str) -> str:
    pos = (pos or "").strip().lower()
    if pos.startswith("g"):
        return "Goalkeeper"
    if pos.startswith("d"):
        return "Defender"
    if pos.startswith("m"):
        return "Midfielder"
    if pos.startswith("f"):
        return "Attacker"
    return pos.title() if pos else ""


def _parse_record(summary: str) -> tuple[int, int, int]:
    if not summary:
        return 0, 0, 0
    parts = [part for part in summary.split("-") if part.strip()]
    if len(parts) != 3:
        return 0, 0, 0
    return _si(parts[0]), _si(parts[1]), _si(parts[2])


def _espn_stat_map(stats: list[dict]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for stat in stats or []:
        key = stat.get("name") or stat.get("abbreviation") or stat.get("label")
        if key:
            data[str(key)] = stat.get("value", stat.get("displayValue"))
    return data


def _team_logo(team: dict) -> str:
    logos = team.get("logos") or []
    if logos:
        return logos[0].get("href", "")
    return team.get("logo", "")


def _espn_score(score_val) -> int | None:
    """Extract integer score from an ESPN score field.

    ESPN returns scores in two shapes depending on the endpoint:
      - Simple scalar: "2" or 2
      - Rich object:   {"value": 2.0, "displayValue": "2", "$ref": "..."}
    """
    if score_val is None:
        return None
    if isinstance(score_val, dict):
        val = score_val.get("value") if score_val.get("value") is not None else score_val.get("displayValue")
        if val is None:
            return None
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None
    try:
        return int(float(score_val))
    except (TypeError, ValueError):
        return None


def _espn_fixture_status(state: str) -> dict[str, str]:
    state = (state or "").lower()
    if state == "post":
        return {"short": "FT", "long": "Finished"}
    if state == "in":
        return {"short": "LIVE", "long": "In Progress"}
    return {"short": "NS", "long": "Scheduled"}


def _normalize_espn_fixture(event: dict, league_id: int) -> dict | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None

    competition = competitions[0]
    competitors = competition.get("competitors") or []
    home = next((entry for entry in competitors if entry.get("homeAway") == "home"), None)
    away = next((entry for entry in competitors if entry.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    status_type = ((competition.get("status") or {}).get("type") or {})
    status = _espn_fixture_status(status_type.get("state"))
    venue = competition.get("venue") or event.get("venue") or {}

    return {
        "fixture": {
            "id": _si(event.get("id")),
            "date": event.get("date", ""),
            "season": _requested_or_current_season(CURRENT_SEASON),
            "status": status,
            "venue": {"name": venue.get("fullName", "")},
        },
        "league": {
            "id": league_id,
            "name": ((event.get("season") or {}).get("displayName")) or _league_name(league_id),
            "round": (((event.get("week") or {}).get("number")) and f"Round {(event.get('week') or {}).get('number')}") or "",
        },
        "teams": {
            "home": {
                "id": _si(home_team.get("id")),
                "name": home_team.get("displayName") or home_team.get("name") or "Home",
                "logo": home_team.get("logo") or _team_logo(home_team),
            },
            "away": {
                "id": _si(away_team.get("id")),
                "name": away_team.get("displayName") or away_team.get("name") or "Away",
                "logo": away_team.get("logo") or _team_logo(away_team),
            },
        },
        "goals": {
            "home": _espn_score(home.get("score")),
            "away": _espn_score(away.get("score")),
        },
        "score": {"halftime": {"home": None, "away": None}},
        "events": [],
        "stats": [],
        "source": "espn",
    }


def _espn_schedule(team_id: int, league_id: int, season: int = CURRENT_SEASON) -> list[dict]:
    slug = _espn_slug(league_id)
    resolved_team_id = _resolve_team_id(team_id, league_id)
    payload = _espn_get_json(
        f"{ESPN_BASE}/{slug}/teams/{resolved_team_id}/schedule?season={season}",
        f"schedule:{league_id}:{resolved_team_id}:{season}",
        ttl_hours=1,
    )
    events = payload.get("events") or []
    fixtures = []
    for event in events:
        normalized = _normalize_espn_fixture(event, league_id)
        if normalized:
            fixtures.append(normalized)
    return fixtures


def _espn_roster(team_id: int, league_id: int) -> list[dict]:
    slug = _espn_slug(league_id)
    resolved_team_id = _resolve_team_id(team_id, league_id)
    payload = _espn_get_json(
        f"{ESPN_BASE}/{slug}/teams/{resolved_team_id}/roster",
        f"roster:{league_id}:{resolved_team_id}:{_requested_or_current_season(CURRENT_SEASON)}",
        ttl_hours=6,
    )
    return payload.get("athletes") or []


def _extract_roster_stat(athlete: dict, stat_name: str, default: float = 0.0) -> float:
    categories = ((((athlete.get("statistics") or {}).get("splits") or {}).get("categories")) or [])
    for category in categories:
        for stat in category.get("stats") or []:
            if stat.get("name") == stat_name:
                return _sf(stat.get("value"), default)
    return default


def _player_overview(player_id: int, league_id: int = DEFAULT_LEAGUE_ID) -> dict:
    preferred = _espn_slug(league_id)
    for slug in [preferred, *[value for value in ESPN_SLUG_BY_LEAGUE.values() if value != preferred]]:
        try:
            payload = _espn_get_json(
                f"{ESPN_WEB_BASE}/{slug}/athletes/{player_id}/overview",
                f"athlete:{player_id}:{slug}",
                ttl_hours=6,
            )
        except Exception:
            continue
        if payload.get("statistics"):
            return payload
    return {}


def _resolve_player_id(player_id: int) -> tuple[int, int | None]:
    alias = API_PLAYER_ID_ALIASES.get(_si(player_id))
    if alias:
        return _si(alias.get("espn_id")), _si(alias.get("team_id"), None)
    return _si(player_id), None


def _normalize_espn_squad_player(athlete: dict) -> dict:
    position = athlete.get("position") or {}
    photo = (athlete.get("headshot") or {}).get("href", "")
    player_id = _si(athlete.get("id"))
    name = athlete.get("displayName") or athlete.get("fullName") or ""
    normalized = {
        "id": player_id,
        "name": name,
        "firstname": athlete.get("firstName", ""),
        "lastname": athlete.get("lastName", ""),
        "photo": photo,
        "position": _normalize_position(position.get("abbreviation") or position.get("displayName") or ""),
        "number": athlete.get("jersey"),
        "player": {
            "id": player_id,
            "name": name,
            "photo": photo,
            "number": athlete.get("jersey"),
            "pos": position.get("abbreviation", ""),
        },
    }
    return normalized


def _overview_split(payload: dict, league_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    stats_root = payload.get("statistics") or {}
    names = stats_root.get("names") or []
    splits = stats_root.get("splits") or []
    wanted_slug = _espn_slug(league_id)
    split = next((entry for entry in splits if entry.get("leagueSlug") == wanted_slug), None)
    if split is None and splits:
        split = splits[0]
    if split is None:
        return {}, {}
    values = {name: split["stats"][idx] for idx, name in enumerate(names) if idx < len(split.get("stats") or [])}
    return values, split


def _normalize_espn_player_response(player_id: int, league_id: int) -> list[dict]:
    resolved_player_id, hinted_team_id = _resolve_player_id(player_id)
    payload = _player_overview(resolved_player_id, league_id)
    athlete = payload.get("athlete") or {}
    values, split = _overview_split(payload, league_id)
    team_id = _si(split.get("teamId"), hinted_team_id)
    team_name = split.get("displayName", "").replace(f"{_requested_or_current_season(CURRENT_SEASON)+1} ", "")
    player_name = athlete.get("displayName") or athlete.get("fullName") or API_PLAYER_ID_ALIASES.get(player_id, {}).get("name", "")

    response = {
        "player": {
            "id": resolved_player_id,
            "name": player_name,
            "photo": (athlete.get("headshot") or {}).get("href", ""),
        },
        "statistics": [{
            "team": {"id": team_id, "name": team_name},
            "league": {"id": league_id, "name": _league_name(league_id)},
            "games": {
                "position": _normalize_position(((athlete.get("position") or {}).get("abbreviation")) or ((athlete.get("position") or {}).get("displayName")) or ""),
                "rating": "0",
                "minutes": 0,
                "appearences": _sf(values.get("starts", 0)) or _sf(values.get("appearances", 0)),
            },
            "goals": {
                "total": _sf(values.get("totalGoals", 0)),
                "assists": _sf(values.get("goalAssists", 0)),
            },
            "shots": {
                "total": _sf(values.get("totalShots", 0)),
                "on": _sf(values.get("shotsOnTarget", 0)),
            },
            "passes": {"key": 0, "total": 0},
            "dribbles": {"success": 0},
            "duels": {"won": 0},
            "cards": {
                "yellow": _sf(values.get("yellowCards", 0)),
                "red": _sf(values.get("redCards", 0)),
            },
            "tackles": {"total": 0, "interceptions": 0, "blocks": 0},
        }],
    }
    return [response] if player_name else []


def _espn_top_players(league_id: int, stat_name: str) -> list[dict]:
    leaders: list[dict] = []
    for entry in get_teams(league_id, CURRENT_SEASON):
        team = entry.get("team") or {}
        team_id = _si(team.get("id"))
        if not team_id:
            continue
        for athlete in _espn_roster(team_id, league_id):
            value = _extract_roster_stat(athlete, stat_name, 0.0)
            if value <= 0:
                continue
            player = _normalize_espn_squad_player(athlete)
            leaders.append({
                "player": {
                    "id": player["id"],
                    "name": player["name"],
                    "photo": player["photo"],
                },
                "statistics": [{
                    "team": {"id": team_id, "name": team.get("name", "")},
                    "league": {"id": league_id, "name": _league_name(league_id)},
                    "goals": {
                        "total": _extract_roster_stat(athlete, "totalGoals", 0.0),
                        "assists": _extract_roster_stat(athlete, "goalAssists", 0.0),
                    },
                    "games": {"appearences": _extract_roster_stat(athlete, "appearances", 0.0)},
                }],
                "_sort": value,
            })
    leaders.sort(key=lambda item: item.get("_sort", 0), reverse=True)
    for item in leaders:
        item.pop("_sort", None)
    return leaders[:20]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _si(v, d: int | None = 0) -> int | None:
    return safe_int(v, d)


def _league_name(league_id: int) -> str:
    return (LEAGUE_BY_ID.get(league_id) or {}).get("name", f"League {league_id}")


def _fixture_finished(f: dict) -> bool:
    status = (f.get("fixture") or {}).get("status") or {}
    short  = str(status.get("short") or "")
    return short in {"FT", "AET", "PEN"}


def _fixture_id(f: dict) -> int | None:
    v = (f.get("fixture") or {}).get("id")
    return _si(v) or None


def _fixture_date(f: dict) -> str:
    return str((f.get("fixture") or {}).get("date") or "")[:10]


def _opponent(fixture: dict, team_id: int) -> dict:
    teams = fixture.get("teams") or {}
    home  = teams.get("home") or {}
    away  = teams.get("away") or {}
    return away if str(home.get("id")) == str(team_id) else home


def _player_stats_entry(fp_data: list, player_id: int) -> dict | None:
    for team_entry in fp_data:
        for pe in team_entry.get("players") or []:
            p = pe.get("player") or {}
            if str(p.get("id")) == str(player_id):
                sl = pe.get("statistics") or [{}]
                return sl[0] if sl else {}
    return None


def _stat(stats: dict, section: str, key: str) -> float | None:
    raw = (stats.get(section) or {}).get(key)
    return _sf(raw) if raw is not None else None


# ── Domain methods ─────────────────────────────────────────────────────────────

def get_teams(league_id: int = DEFAULT_LEAGUE_ID, season: int = CURRENT_SEASON) -> list:
    try:
        data = api_get("teams", {"league": league_id, "season": season}, cache_hours=24)
        if data.get("response"):
            return data.get("response", [])
    except Exception:
        pass

    teams = []
    for entry in _espn_league_teams(league_id):
        team = entry.get("team") or {}
        teams.append({
            "team": {
                "id": _si(team.get("id")),
                "name": team.get("displayName") or team.get("name") or "",
                "logo": _team_logo(team),
                "country": (LEAGUE_BY_ID.get(league_id) or {}).get("country", ""),
            },
            "venue": {
                "name": (((team.get("venue") or {}).get("fullName")) if isinstance(team.get("venue"), dict) else "") or "",
            },
        })
    return teams


def get_h2h(id_a: int, id_b: int, last: int = 10) -> list:
    try:
        data = api_get("fixtures/headtohead", {"h2h": f"{id_a}-{id_b}"}, cache_hours=6)
        resp = data.get("response", [])
        if resp:
            resp.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""), reverse=True)
            return resp[:last]
    except Exception:
        pass

    team_a_id = _resolve_team_id(id_a)
    team_b_id = _resolve_team_id(id_b)
    fixtures = []
    for league_id in [DEFAULT_LEAGUE_ID, *SUPPORTED_LEAGUE_IDS]:
        try:
            for season_year in (CURRENT_SEASON, CURRENT_SEASON - 1):
                for fixture in _espn_schedule(team_a_id, league_id, season_year):
                    teams = fixture.get("teams") or {}
                    home_id = _si((teams.get("home") or {}).get("id"))
                    away_id = _si((teams.get("away") or {}).get("id"))
                    if {home_id, away_id} == {team_a_id, team_b_id} and _fixture_finished(fixture):
                        fixtures.append(fixture)
        except Exception:
            continue
        if fixtures:
            break
    fixtures.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""), reverse=True)
    return fixtures[:last]


def get_fixture_stats(fixture_id: int) -> list:
    try:
        data = api_get("fixtures/statistics", {"fixture": fixture_id}, cache_hours=24)
        if data.get("response"):
            return data.get("response", [])
    except Exception:
        pass
    return []


def get_fixture_events(fixture_id: int) -> list:
    try:
        data = api_get("fixtures/events", {"fixture": fixture_id}, cache_hours=24)
        if data.get("response"):
            return data.get("response", [])
    except Exception:
        pass
    return []


def get_fixture_player_stats(
    fixture_id: int,
    player_id: int | None = None,
    *,
    team_id: int | None = None,
) -> list | dict | None:
    params: dict = {"fixture": fixture_id}
    if team_id is not None:
        params["team"] = team_id
    try:
        resp = api_get("fixtures/players", params, cache_hours=24).get("response", [])
    except Exception:
        return [] if player_id is None else None
    if player_id is None:
        return resp
    return _player_stats_entry(resp, player_id)


def get_squad(team_id: int, season: int = CURRENT_SEASON) -> list:
    try:
        data = api_get("players/squads", {"team": team_id}, cache_hours=6).get("response", [])
        if data:
            return data[0].get("players", [])
    except Exception:
        pass
    league_id = DEFAULT_LEAGUE_ID
    for possible_league in [DEFAULT_LEAGUE_ID, *SUPPORTED_LEAGUE_IDS]:
        try:
            roster = [_normalize_espn_squad_player(player) for player in _espn_roster(team_id, possible_league)]
            if roster:
                return roster
        except Exception:
            continue
    return []


def get_player_stats(
    player_id: int,
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
) -> list:
    """Season aggregate stats for a player in a specific league."""
    try:
        resp = api_get(
            "players",
            {"id": player_id, "season": season, "league": league_id},
            cache_hours=6,
        ).get("response", [])
        filtered = []
        for item in resp:
            stats = [
                s for s in (item.get("statistics") or [])
                if (s.get("league") or {}).get("id") == league_id
            ]
            if stats:
                clone = deepcopy(item)
                clone["statistics"] = stats
                filtered.append(clone)
        if filtered:
            return filtered
    except Exception:
        pass
    return _normalize_espn_player_response(player_id, league_id)


def get_injuries(
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
    team_id: int | None = None,
) -> list:
    if team_id is None and league_id not in SUPPORTED_LEAGUE_IDS and season in SUPPORTED_LEAGUE_IDS:
        team_id, league_id, season = league_id, season, _current_football_season()
    try:
        params = {"league": league_id, "season": season}
        if team_id is not None:
            params["team"] = team_id
        data = api_get("injuries", params, cache_hours=4)
        if data.get("response"):
            return data.get("response", [])
    except Exception:
        pass

    teams = [team_id] if team_id else [entry.get("team", {}).get("id") for entry in get_teams(league_id, season)]
    injuries: list[dict] = []
    for raw_team_id in teams:
        if not raw_team_id:
            continue
        for athlete in _espn_roster(_si(raw_team_id), league_id):
            for injury in athlete.get("injuries") or []:
                injuries.append({
                    "player": {
                        "id": _si(athlete.get("id")),
                        "name": athlete.get("displayName") or athlete.get("fullName") or "",
                        "position": _normalize_position(((athlete.get("position") or {}).get("abbreviation")) or ((athlete.get("position") or {}).get("displayName")) or ""),
                        "reason": injury.get("detail") or injury.get("type") or injury.get("status") or "Unavailable",
                    }
                })
    if injuries:
        return injuries
    if team_id is not None:
        return [{
            "placeholder": True,
            "player": {
                "id": 0,
                "name": "No injuries reported",
                "position": "",
                "reason": "Fully fit squad",
            },
        }]
    return []


def get_team_fixtures(
    team_id: int,
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
    last: int = 10,
) -> list:
    def _unique_fixtures(fixtures: list[dict]) -> list[dict]:
        seen = {}
        for fixture in fixtures:
            fixture_id = _fixture_id(fixture)
            if fixture_id:
                seen[fixture_id] = fixture
            else:
                home_id = (fixture.get("teams") or {}).get("home", {}).get("id") or ""
                away_id = (fixture.get("teams") or {}).get("away", {}).get("id") or ""
                key = f"{(fixture.get('fixture') or {}).get('date') or ''}:{home_id}:{away_id}"
                seen.setdefault(key, fixture)
        return list(seen.values())

    fixtures = []
    try:
        for season_year in (season, season - 1):
            season_fixtures = api_get(
                "fixtures",
                {"team": team_id, "league": league_id, "season": season_year},
                cache_hours=2,
            ).get("response", [])
            if season_fixtures:
                fixtures.extend(season_fixtures)
        if fixtures:
            fixtures = _unique_fixtures(fixtures)
            fixtures = [f for f in fixtures if _fixture_finished(f)]
            fixtures.sort(
                key=lambda f: str((f.get("fixture") or {}).get("date") or ""),
                reverse=True,
            )
            return fixtures[:last]
    except Exception:
        pass

    fixtures = []
    for season_year in (season, season - 1):
        try:
            fixtures.extend(
                [fixture for fixture in _espn_schedule(team_id, league_id, season_year) if _fixture_finished(fixture)]
            )
        except Exception:
            continue
    fixtures = _unique_fixtures(fixtures)
    fixtures.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""), reverse=True)
    return fixtures[:last]


def get_standings(
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
) -> list:
    try:
        response = api_get("standings", {"league": league_id, "season": season}, cache_hours=4).get("response", [])
        if response:
            return (((response[0] or {}).get("league") or {}).get("standings") or [[]])[0]
    except Exception:
        pass

    try:
        payload = _espn_get_json(
            f"{ESPN_V2_BASE}/{_espn_slug(league_id)}/standings",
            f"standings:{league_id}:{_requested_or_current_season(season)}",
            ttl_hours=6,
        )
        entries = (((payload.get("children") or [{}])[0].get("standings") or {}).get("entries") or [])
    except Exception:
        return []

    rows = []
    for entry in entries:
        team = entry.get("team") or {}
        stats = _espn_stat_map(entry.get("stats") or [])
        wins, draws, losses = _parse_record(str(stats.get("overall", "")))
        played = _si(stats.get("gamesPlayed"))
        goals_for = _si(stats.get("pointsFor"))
        goals_against = _si(stats.get("pointsAgainst"))
        rows.append({
            "rank": _si(stats.get("rank")),
            "team": {
                "id": _si(team.get("id")),
                "name": team.get("displayName") or team.get("name") or "",
                "logo": _team_logo(team),
            },
            "points": _si(stats.get("points")),
            "goalsDiff": _si(stats.get("pointDifferential")),
            "form": "",
            "all": {
                "played": played,
                "win": wins,
                "draw": draws,
                "lose": losses,
                "goals": {"for": goals_for, "against": goals_against},
            },
            "home": {"played": 0, "win": 0, "draw": 0, "lose": 0, "goals": {"for": 0, "against": 0}},
            "away": {"played": 0, "win": 0, "draw": 0, "lose": 0, "goals": {"for": 0, "against": 0}},
        })
    return rows


def get_upcoming_fixtures(
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
    next_n: int = 20,
) -> list:
    try:
        response = api_get(
            "fixtures",
            {"league": league_id, "season": season, "next": next_n},
            cache_hours=2,
        ).get("response", [])
        if response:
            return response
    except Exception:
        pass

    # ESPN fallback: scan ahead across the next few weeks (UTC) because many
    # leagues have multi-day gaps between matchdays. A short 2-3 day window can
    # look empty even when valid upcoming fixtures exist.
    slug = _espn_slug(league_id)
    now_utc = datetime.now(UTC)
    all_fixtures: list = []
    seen_ids: set[str] = set()
    max_days_ahead = max(7, min(28, next_n * 2))

    _FINISHED = {"FT", "AET", "PEN", "SUSP", "ABD", "WO"}
    _LIVE     = {"LIVE", "1H", "2H", "HT", "ET", "BT", "P", "INT"}

    for day_offset in range(max_days_ahead + 1):
        target = now_utc + timedelta(days=day_offset)
        date_str = target.strftime("%Y%m%d")
        try:
            payload = _espn_get_json(
                f"{ESPN_BASE}/{slug}/scoreboard?dates={date_str}",
                f"scoreboard:{league_id}:{date_str}",
                ttl_hours=0.5,
            )
        except Exception:
            continue

        for event in payload.get("events") or []:
            fixture = _normalize_espn_fixture(event, league_id)
            if not fixture:
                continue
            fid = str((fixture.get("fixture") or {}).get("id") or "")
            if fid and fid in seen_ids:
                continue
            if fid:
                seen_ids.add(fid)
            status_short = (fixture.get("fixture") or {}).get("status", {}).get("short", "NS")
            # Keep not-started and any unknown status; skip finished and live
            if status_short not in _FINISHED and status_short not in _LIVE:
                all_fixtures.append(fixture)

        if len(all_fixtures) >= next_n:
            break

    all_fixtures.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""))
    return all_fixtures[:next_n]


def get_espn_fixtures(espn_slug: str, next_n: int = 20) -> list:
    """Fetch upcoming fixtures from ESPN for a given sport slug (e.g. 'FIFA.WC.2026').

    Used by the World Cup page and other non-league ESPN endpoints that are not
    covered by the standard API-Football provider.

    Args:
        espn_slug: ESPN competition slug string.
        next_n: Maximum number of upcoming fixtures to return.

    Returns:
        List of normalised fixture dicts (same shape as get_upcoming_fixtures).
    """
    # ESPN base for soccer scoreboard uses league slug in path
    soccer_base = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    url = f"{soccer_base}/{espn_slug}/scoreboard"
    cache_key = f"espn_slug:{espn_slug}:{datetime.now(UTC).strftime('%Y-%m-%d')}"
    try:
        payload = _espn_get_json(url, cache_key, ttl_hours=0.5)
    except Exception:
        return []

    # Use league_id=0 as a sentinel — _normalize_espn_fixture will still work for
    # the teams/goals/fixture fields we need.
    fixtures = []
    for event in payload.get("events") or []:
        fixture = _normalize_espn_fixture(event, 0)
        if not fixture:
            continue
        fixtures.append(fixture)

    fixtures.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""))
    return fixtures[:next_n]


def get_top_scorers(league_id: int = DEFAULT_LEAGUE_ID, season: int = CURRENT_SEASON) -> list:
    try:
        response = api_get(
            "players/topscorers",
            {"league": league_id, "season": season},
            cache_hours=6,
        ).get("response", [])
        if response:
            return response
    except Exception:
        pass
    return _espn_top_players(league_id, "totalGoals")


def get_top_assisters(league_id: int = DEFAULT_LEAGUE_ID, season: int = CURRENT_SEASON) -> list:
    try:
        response = api_get(
            "players/topassists",
            {"league": league_id, "season": season},
            cache_hours=6,
        ).get("response", [])
        if response:
            return response
    except Exception:
        pass
    return _espn_top_players(league_id, "goalAssists")


def enrich_fixture(fixture: dict) -> dict:
    fid = fixture["fixture"]["id"]
    return {
        **fixture,
        "events": get_fixture_events(fid),
        "stats":  get_fixture_stats(fid),
    }


def get_fixture_players(fixture_id: int) -> list:
    result = get_fixture_player_stats(fixture_id)
    return result if isinstance(result, list) else []


def get_fixture_prediction(fixture_id: int) -> list:
    try:
        response = api_get("predictions", {"fixture": fixture_id}, cache_hours=6).get("response", [])
        if response:
            return response
    except Exception:
        pass
    return []


def get_live_fixtures(league_id: int | None = None) -> list:
    results = []
    league_ids = [league_id] if league_id else [DEFAULT_LEAGUE_ID]
    for lid in league_ids:
        try:
            payload = _espn_get_json(
                f"{ESPN_BASE}/{_espn_slug(lid)}/scoreboard",
                f"live:{lid}:{datetime.now(UTC).strftime('%Y-%m-%d-%H')}",
                ttl_hours=0.016,
            )
        except Exception:
            continue
        for event in payload.get("events") or []:
            fixture = _normalize_espn_fixture(event, lid)
            if fixture and ((fixture.get("fixture") or {}).get("status") or {}).get("short") == "LIVE":
                results.append(fixture)
    return results


def get_today_fixtures(league_id: int | None = None) -> list:
    results = []
    league_ids = [league_id] if league_id else [DEFAULT_LEAGUE_ID]
    for lid in league_ids:
        try:
            payload = _espn_get_json(
                f"{ESPN_BASE}/{_espn_slug(lid)}/scoreboard",
                f"today:{lid}:{datetime.now(UTC).strftime('%Y-%m-%d')}",
                ttl_hours=1,
            )
        except Exception:
            continue
        for event in payload.get("events") or []:
            fixture = _normalize_espn_fixture(event, lid)
            if fixture:
                results.append(fixture)
    results.sort(key=lambda item: str((item.get("fixture") or {}).get("date") or ""))
    return results


def parse_stat(stats: list, team_id: int, stat_type: str):
    for team_stats in stats:
        if team_stats["team"]["id"] == team_id:
            for s in team_stats["statistics"]:
                if s["type"] == stat_type:
                    return s["value"]
    return None


# ── Player game log (props engine feed) ────────────────────────────────────────

def _build_game_row(
    fixture: dict,
    fp_data: list,
    player_id: int,
    team_id: int,
    league_id: int,
) -> dict | None:
    stats = _player_stats_entry(fp_data, player_id)
    if not stats:
        return None
    opp    = _opponent(fixture, team_id)
    goals  = _stat(stats, "goals", "total") or 0.0
    assists = _stat(stats, "goals", "assists") or 0.0
    return {
        "fixture_id":       _fixture_id(fixture),
        "date":             _fixture_date(fixture),
        "league_id":        league_id,
        "league_name":      _league_name(league_id),
        "difficulty":       COMP_DIFFICULTY.get(league_id, 1.00),
        "home_id":          ((fixture.get("teams") or {}).get("home") or {}).get("id"),
        "away_id":          ((fixture.get("teams") or {}).get("away") or {}).get("id"),
        "home_name":        ((fixture.get("teams") or {}).get("home") or {}).get("name"),
        "away_name":        ((fixture.get("teams") or {}).get("away") or {}).get("name"),
        "opponent_id":      opp.get("id"),
        "opponent":         opp.get("name"),
        "goals":            goals,
        "assists":          assists,
        "goal_or_assist":   goals + assists,
        "shots":            _stat(stats, "shots", "total"),
        "shots_on_target":  _stat(stats, "shots", "on"),
        "key_passes":       _stat(stats, "passes", "key"),
        "chances_created":  _stat(stats, "passes", "key"),
        "dribbles":         _stat(stats, "dribbles", "success"),
        "dribbles_completed": _stat(stats, "dribbles", "success"),
        "passes_completed": _stat(stats, "passes", "total"),
        "tackles":          _stat(stats, "tackles", "total"),
        "interceptions":    _stat(stats, "tackles", "interceptions"),
        "clearances":       _stat(stats, "tackles", "blocks"),
        "aerial_duels_won": _stat(stats, "duels", "won"),
        "yellow_card":      _stat(stats, "cards", "yellow"),
        "yellow_cards":     _stat(stats, "cards", "yellow"),
        "minutes":          _stat(stats, "games", "minutes"),
        "minutes_played":   _stat(stats, "games", "minutes"),
        "rating":           _stat(stats, "games", "rating"),
        "touches_opp_box":  None,   # not in standard endpoint
        "xg":               _stat(stats, "expected", "goals"),
        "xa":               _stat(stats, "expected", "assists"),
    }


def get_player_game_log(
    player_id: int,
    team_id: int,
    league_id: int,
    season: int = CURRENT_SEASON,
) -> list:
    """
    Per-game stat rows for a player in a single competition.
    Results cached in cache/props/player_{id}_league_{league_id}_season_{season}.json
    """
    PROPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROPS_CACHE_DIR / f"player_{player_id}_league_{league_id}_season_{season}.json"
    if _cache_valid(path, PLAYER_LOG_TTL_H):
        return _load(path)

    try:
        fixtures = api_get(
            "fixtures",
            {"team": team_id, "league": league_id, "season": season, "status": "FT"},
            cache_hours=2,
        ).get("response", [])
    except Exception:
        fixtures = []

    if not fixtures:
        _save(path, [])
        return []

    rows: list[dict] = []
    for fixture in sorted(
        fixtures,
        key=lambda f: str((f.get("fixture") or {}).get("date") or ""),
        reverse=True,
    ):
        fid = _fixture_id(fixture)
        if not fid:
            continue
        fp = get_fixture_player_stats(fid, team_id=team_id)
        if not isinstance(fp, list):
            continue
        row = _build_game_row(fixture, fp, player_id, team_id, league_id)
        if row:
            rows.append(row)

    _save(path, rows)
    return rows


def get_player_vs_team(
    player_id: int,
    team_id: int,
    opponent_team_id: int,
    league_ids: list[int] | None = None,
    season: int = CURRENT_SEASON,
) -> dict:
    """Historical records of player_id vs opponent across leagues and past seasons."""
    league_ids = league_ids or list(SUPPORTED_LEAGUE_IDS)
    seasons    = [season - i for i in range(4)]
    games: list[dict] = []

    for season in seasons:
        for lid in league_ids:
            try:
                fixtures = api_get(
                    "fixtures",
                    {"team": team_id, "league": lid, "season": season, "status": "FT"},
                    cache_hours=6,
                ).get("response", [])
            except Exception:
                continue
            for fixture in fixtures:
                if str(_opponent(fixture, team_id).get("id")) != str(opponent_team_id):
                    continue
                fid = _fixture_id(fixture)
                if not fid:
                    continue
                fp = get_fixture_player_stats(fid, team_id=team_id)
                if not isinstance(fp, list):
                    continue
                row = _build_game_row(fixture, fp, player_id, team_id, lid)
                if row:
                    row["season"] = season
                    games.append(row)
    if not games:
        return {
            "games_played": 0,
            "goals": 0.0,
            "assists": 0.0,
            "shots": 0.0,
            "shots_on_target": 0.0,
            "key_passes": 0.0,
            "dribbles": 0.0,
            "avg_rating": 0.0,
            "games": [],
        }

    def _sum(metric: str) -> float:
        return round(sum(_sf(g.get(metric)) for g in games), 2)

    avg_rating = (
        round(sum(_sf(g.get("rating")) for g in games) / len(games), 2)
        if games else 0.0
    )
    return {
        "games_played":    len(games),
        "goals":           _sum("goals"),
        "assists":         _sum("assists"),
        "shots":           _sum("shots"),
        "shots_on_target": _sum("shots_on_target"),
        "key_passes":      _sum("key_passes"),
        "dribbles":        _sum("dribbles"),
        "avg_rating":      avg_rating,
        "games":           sorted(games, key=lambda g: g["date"], reverse=True),
    }


def get_player_season_stats_all_comps(
    player_id: int,
    team_id: int,
    season: int = CURRENT_SEASON,
) -> list:
    """Season stats for a player across all supported competitions."""
    try:
        resp = api_get("players", {"id": player_id, "season": season}, cache_hours=6).get("response", [])
        if not resp:
            raise RuntimeError("No API-Football data")
    except Exception:
        overview = _player_overview(_resolve_player_id(player_id)[0], DEFAULT_LEAGUE_ID)
        stats_root = overview.get("statistics") or {}
        names = stats_root.get("names") or []
        splits = stats_root.get("splits") or []
        breakdown = []
        for split in splits:
            league_slug = split.get("leagueSlug", "")
            league_id_match = next((lid for lid, slug in ESPN_SLUG_BY_LEAGUE.items() if slug == league_slug), None)
            if league_id_match not in SUPPORTED_LEAGUE_IDS:
                continue
            values = {name: split["stats"][idx] for idx, name in enumerate(names) if idx < len(split.get("stats") or [])}
            goals = _sf(values.get("totalGoals", 0))
            assists = _sf(values.get("goalAssists", 0))
            shots = _sf(values.get("totalShots", 0))
            appearances = _sf(values.get("starts", 0))
            breakdown.append({
                "player_id": _resolve_player_id(player_id)[0],
                "player_name": (overview.get("athlete") or {}).get("displayName", ""),
                "team_id": _si(split.get("teamId")),
                "team_name": split.get("displayName", ""),
                "league_id": league_id_match,
                "league_name": _league_name(league_id_match),
                "difficulty": COMP_DIFFICULTY.get(league_id_match, 1.0),
                "appearances": appearances,
                "minutes": 0.0,
                "goals": goals,
                "assists": assists,
                "shots": shots,
                "key_passes": 0.0,
                "goal_or_assist": goals + assists,
                "goals_per_90": goals,
                "assists_per_90": assists,
                "shots_per_90": shots,
                "kp_per_90": 0.0,
                "raw": split,
            })
        breakdown.sort(key=lambda item: item["league_name"])
        return breakdown

    breakdown: list[dict] = []
    for item in resp:
        player = item.get("player") or {}
        for stat in item.get("statistics") or []:
            league  = stat.get("league") or {}
            team    = stat.get("team")   or {}
            lid     = league.get("id")
            if lid not in SUPPORTED_LEAGUE_IDS:
                continue
            if team_id and str(team.get("id")) != str(team_id):
                continue
            games       = stat.get("games") or {}
            minutes     = _sf(games.get("minutes"))
            appearances = _sf(games.get("appearences") or games.get("appearances"))
            goals       = _sf((stat.get("goals")  or {}).get("total"))
            assists     = _sf((stat.get("goals")  or {}).get("assists"))
            shots       = _sf((stat.get("shots")  or {}).get("total"))
            key_passes  = _sf((stat.get("passes") or {}).get("key"))
            breakdown.append({
                "player_id":       player.get("id"),
                "player_name":     player.get("name"),
                "team_id":         team.get("id"),
                "team_name":       team.get("name"),
                "league_id":       lid,
                "league_name":     _league_name(lid),
                "difficulty":      COMP_DIFFICULTY.get(lid, 1.00),
                "appearances":     appearances,
                "minutes":         minutes,
                "goals":           goals,
                "assists":         assists,
                "shots":           shots,
                "key_passes":      key_passes,
                "goal_or_assist":  goals + assists,
                "goals_per_90":    round(goals   / minutes * 90, 3) if minutes > 0 else 0.0,
                "assists_per_90":  round(assists / minutes * 90, 3) if minutes > 0 else 0.0,
                "shots_per_90":    round(shots   / minutes * 90, 3) if minutes > 0 else 0.0,
                "kp_per_90":       round(key_passes / minutes * 90, 3) if minutes > 0 else 0.0,
                "raw": stat,
            })
    breakdown.sort(key=lambda x: x["league_name"])
    return breakdown


def get_opponent_defensive_stats(
    team_id: int,
    league_id: int = DEFAULT_LEAGUE_ID,
    season: int = CURRENT_SEASON,
) -> dict:
    """Opponent defensive profile from team statistics endpoint."""
    empty = {
        "league_id": league_id, "league_name": _league_name(league_id),
        "games": 0, "goals_conceded_pg": 0.0,
        "shots_conceded_pg": 0.0, "clean_sheets": 0, "cards_given_pg": 0.0,
    }
    try:
        resp = api_get(
            "teams/statistics",
            {"team": team_id, "league": league_id, "season": season},
            cache_hours=6,
        ).get("response", {})
        if not resp:
            raise RuntimeError("No API-Football team stats")
    except Exception:
        fixtures = get_team_fixtures(team_id, league_id, season, last=30)
        conceded = []
        for fixture in fixtures:
            teams = fixture.get("teams") or {}
            goals = fixture.get("goals") or {}
            home_id = _si((teams.get("home") or {}).get("id"))
            away_id = _si((teams.get("away") or {}).get("id"))
            home_goals = goals.get("home")
            away_goals = goals.get("away")
            if home_id == _resolve_team_id(team_id, league_id) and away_goals is not None:
                conceded.append(_si(away_goals))
            elif away_id == _resolve_team_id(team_id, league_id) and home_goals is not None:
                conceded.append(_si(home_goals))
        if not conceded:
            return empty
        clean_sheets = sum(1 for value in conceded if value == 0)
        return {
            "league_id": league_id,
            "league_name": _league_name(league_id),
            "games": len(conceded),
            "goals_conceded_pg": round(sum(conceded) / len(conceded), 2),
            "shots_conceded_pg": 0.0,
            "clean_sheets": clean_sheets,
            "cards_given_pg": 0.0,
        }

    ga_avg      = _sf(((resp.get("goals") or {}).get("against") or {}).get("average", {}).get("total"))
    clean       = _si((resp.get("clean_sheet") or {}).get("total"))
    played      = _si(((resp.get("fixtures") or {}).get("played") or {}).get("total"))
    return {
        "league_id":        league_id,
        "league_name":      _league_name(league_id),
        "games":            played,
        "goals_conceded_pg": round(ga_avg, 2),
        "shots_conceded_pg": 0.0,
        "clean_sheets":     clean,
        "cards_given_pg":   0.0,
    }


# ── Position / market helpers used by app.py ──────────────────────────────────

POSITION_DEFAULT_MARKETS: dict[str, list[str]] = {
    "Attacker":   ["goals", "shots", "shots_on_target", "assists", "goal_or_assist", "key_passes", "dribbles"],
    "Midfielder": ["key_passes", "passes_completed", "assists", "goal_or_assist", "dribbles", "tackles", "interceptions"],
    "Defender":   ["tackles", "interceptions", "clearances", "aerial_duels_won", "passes_completed"],
    "Goalkeeper": ["minutes", "yellow_cards"],
    "":           ["goals", "assists", "shots_on_target", "key_passes"],
}

_POS_MAP: dict[str, str] = {
    "g": "Goalkeeper", "gk": "Goalkeeper", "goalkeeper": "Goalkeeper",
    "d": "Defender",   "cb": "Defender",   "lb": "Defender", "rb": "Defender",
    "defender": "Defender", "back": "Defender",
    "m": "Midfielder", "cm": "Midfielder", "dm": "Midfielder", "am": "Midfielder",
    "midfielder": "Midfielder", "mid": "Midfielder", "wing": "Midfielder",
    "f": "Attacker",   "fw": "Attacker",   "st": "Attacker", "cf": "Attacker",
    "lw": "Attacker",  "rw": "Attacker",
    "attacker": "Attacker", "forward": "Attacker", "striker": "Attacker",
}


def normalize_position_group(pos: str) -> str:
    key = (pos or "").strip().lower()
    return _POS_MAP.get(key, _POS_MAP.get(key[:2], ""))


def get_market_catalog() -> list[dict]:
    """Return all supported football prop markets for the UI."""
    from props_engine import SOCCER_MARKETS
    return [
        {
            "key":      k,
            "label":    v[0],
            "abbr":     v[1],
            "per_90":   v[2],
            "category": (
                "attacking"  if k in {"goals","assists","goal_or_assist","shots_total","shots_on_target","dribbles","touches_opp_box","anytime_goalscorer"} else
                "chance"     if k in {"key_passes","chances_created","xG","xA"} else
                "midfield"   if k in {"passes_completed"} else
                "defensive"  if k in {"tackles","interceptions","clearances","aerial_duels_won"} else
                "universal"
            ),
        }
        for k, v in SOCCER_MARKETS.items()
    ]


def relevant_competitions_for_player(
    player_id: int,
    team_id: int,
    primary_league: int,
    season: int = CURRENT_SEASON,
) -> list[int]:
    """
    Return competition IDs where this player has season data, plus the primary league.
    """
    comps = get_player_season_stats_all_comps(player_id, team_id, season)
    ids = [primary_league]
    for entry in comps:
        lid = entry.get("league_id")
        if lid and lid not in ids:
            ids.append(lid)
    return ids


def prefetch_competition(
    player_id: int,
    team_id: int,
    league_id: int,
    season: int = CURRENT_SEASON,
) -> dict:
    """
    Pre-warm the player game-log cache for one competition.
    Returns a summary dict with game count.
    """
    rows = get_player_game_log(player_id, team_id, league_id, season)
    return {
        "league_id":   league_id,
        "league_name": _league_name(league_id),
        "games_found": len(rows),
        "status":      "ok",
    }
