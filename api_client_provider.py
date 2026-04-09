"""
Provider-aware football data client with 24-hour JSON caching.

The rest of the app expects API-Football-style shapes, so SportMonks
responses are normalized into that structure here.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path("cache")
CACHE_HOURS = 24

PROVIDER = os.getenv("FOOTBALL_DATA_PROVIDER", "sportmonks").strip().lower()

API_FOOTBALL_BASE_URL = os.getenv(
    "API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"
).rstrip("/")
API_FOOTBALL_MODE = os.getenv("API_FOOTBALL_MODE", "apisports").strip().lower()
API_FOOTBALL_RAPIDAPI_HOST = os.getenv(
    "API_FOOTBALL_RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com"
)
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()

SPORTMONKS_BASE_URL = os.getenv(
    "SPORTMONKS_BASE_URL", "https://api.sportmonks.com/v3/football"
).rstrip("/")
SPORTMONKS_API_TOKEN = os.getenv("SPORTMONKS_API_TOKEN", "").strip()
SPORTMONKS_SEASON_ID = os.getenv("SPORTMONKS_SEASON_ID", "").strip()

API_FOOTBALL_PLACEHOLDERS = {"", "your_api_key_here"}
SPORTMONKS_TOKEN_PLACEHOLDERS = {
    "",
    "your_sportmonks_token_here",
    "your_api_token_here",
}
SPORTMONKS_SEASON_PLACEHOLDERS = {"", "your_season_id_here"}

SPORTMONKS_FIXTURE_STAT_MAP = {
    "shotsontarget": "Shots on Goal",
    "shotontarget": "Shots on Goal",
    "shotstotal": "Total Shots",
    "totalshots": "Total Shots",
    "corners": "Corner Kicks",
    "yellowcards": "Yellow Cards",
    "yellowcard": "Yellow Cards",
    "redcards": "Red Cards",
    "redcard": "Red Cards",
    "ballpossession": "Ball Possession",
    "possession": "Ball Possession",
}

SPORTMONKS_EVENT_MAP = {
    "goal": ("Goal", "Goal"),
    "owngoal": ("Goal", "Own Goal"),
    "yellowcard": ("Card", "Yellow Card"),
    "redcard": ("Card", "Red Card"),
    "yellowredcard": ("Card", "Red Card"),
}


def _cache_path(endpoint: str, params: dict[str, Any]) -> Path:
    raw = f"{PROVIDER}:{endpoint}:{sorted((params or {}).items())}"
    key = hashlib.md5(raw.encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(hours=CACHE_HOURS)


def _request_json(
    *,
    base_url: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    params = params or {}
    path = _cache_path(endpoint, params)

    if _cache_valid(path):
        with open(path, encoding="utf-8") as file:
            return json.load(file)

    url = f"{base_url}/{endpoint.lstrip('/')}"
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(url, headers=headers or {}, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    CACHE_DIR.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file)

    return data


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _normalize_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _api_football_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}

    if API_FOOTBALL_MODE == "rapidapi":
        headers["x-rapidapi-host"] = API_FOOTBALL_RAPIDAPI_HOST
        headers["x-rapidapi-key"] = API_FOOTBALL_KEY
    else:
        headers["x-apisports-key"] = API_FOOTBALL_KEY

    return headers


def _api_football_request(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if API_FOOTBALL_KEY.lower() in API_FOOTBALL_PLACEHOLDERS:
        raise RuntimeError("Set API_FOOTBALL_KEY in .env to a real API-Football key.")

    data = _request_json(
        base_url=API_FOOTBALL_BASE_URL,
        endpoint=endpoint,
        params=params,
        headers=_api_football_headers(),
    )

    if data.get("errors"):
        raise RuntimeError(f"API-Football error for {endpoint}: {data['errors']}")

    return data


def _sportmonks_headers() -> dict[str, str]:
    return {"Accept": "application/json", "Authorization": SPORTMONKS_API_TOKEN}


def _sportmonks_request(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if SPORTMONKS_API_TOKEN.lower() in SPORTMONKS_TOKEN_PLACEHOLDERS:
        raise RuntimeError(
            "Set SPORTMONKS_API_TOKEN in .env to a real SportMonks API token."
        )

    data = _request_json(
        base_url=SPORTMONKS_BASE_URL,
        endpoint=endpoint,
        params=params,
        headers=_sportmonks_headers(),
    )

    if isinstance(data, dict):
        if data.get("errors"):
            raise RuntimeError(f"SportMonks error for {endpoint}: {data['errors']}")
        if data.get("error"):
            raise RuntimeError(f"SportMonks error for {endpoint}: {data['error']}")
        if data.get("message") and "data" not in data:
            raise RuntimeError(f"SportMonks error for {endpoint}: {data['message']}")

    return data


def _sportmonks_season_id() -> int:
    if SPORTMONKS_SEASON_ID.lower() in SPORTMONKS_SEASON_PLACEHOLDERS:
        raise RuntimeError(
            "Set SPORTMONKS_SEASON_ID in .env to the SportMonks season ID you want to use."
        )
    try:
        return int(SPORTMONKS_SEASON_ID)
    except ValueError as exc:
        raise RuntimeError("SPORTMONKS_SEASON_ID must be a number.") from exc


def _sportmonks_includes(*values: str) -> str:
    return ";".join(value for value in values if value)


def _sportmonks_data(response: dict[str, Any]) -> Any:
    return response.get("data", [])


def _sportmonks_season_record() -> dict[str, Any]:
    response = _sportmonks_request(f"seasons/{_sportmonks_season_id()}")
    data = _sportmonks_data(response)
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _sportmonks_season_dates() -> tuple[str, str]:
    season = _sportmonks_season_record()
    start = str(season.get("starting_at") or "")[:10]
    end = str(season.get("ending_at") or "")[:10]
    if not start or not end:
        raise RuntimeError(
            "SportMonks season data is missing starting_at or ending_at for SPORTMONKS_SEASON_ID."
        )
    return start, end


def _simplify_position(name: str | None) -> str:
    text = str(name or "").lower()
    if any(token in text for token in ("goal", "keeper")):
        return "Goalkeeper"
    if any(token in text for token in ("def", "back")):
        return "Defender"
    if any(token in text for token in ("mid", "wing")):
        return "Midfielder"
    if any(token in text for token in ("forward", "striker", "att")):
        return "Attacker"
    return str(name or "")


def _participant_from_scores(scores: list[dict], location: str) -> dict[str, Any]:
    for score in scores:
        score_info = score.get("score") or {}
        if score_info.get("participant") == location and score.get("participant"):
            return score["participant"]
    return {}


def _participant_location(participant: dict[str, Any], scores: list[dict]) -> str | None:
    for key in ("meta", "pivot", "metadata"):
        meta = participant.get(key) or {}
        location = meta.get("location")
        if location in {"home", "away"}:
            return location

    location = participant.get("location")
    if location in {"home", "away"}:
        return location

    participant_id = participant.get("id")
    for score in scores:
        score_info = score.get("score") or {}
        if score.get("participant_id") == participant_id and score_info.get("participant") in {
            "home",
            "away",
        }:
            return score_info["participant"]

    return None


def _fixture_home_away(raw_fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    scores = _as_list(raw_fixture.get("scores"))
    participants = _as_list(raw_fixture.get("participants"))

    home: dict[str, Any] = {}
    away: dict[str, Any] = {}

    for participant in participants:
        location = _participant_location(participant, scores)
        if location == "home":
            home = participant
        elif location == "away":
            away = participant

    if not home:
        home = _participant_from_scores(scores, "home")
    if not away:
        away = _participant_from_scores(scores, "away")

    return home, away


def _current_score_map(scores: list[dict]) -> tuple[int | None, int | None]:
    home_goals = None
    away_goals = None

    for score in scores:
        if score.get("description") != "CURRENT":
            continue
        score_info = score.get("score") or {}
        location = score_info.get("participant")
        goals = score_info.get("goals")
        if location == "home":
            home_goals = goals
        elif location == "away":
            away_goals = goals

    return home_goals, away_goals


def _normalize_sportmonks_events(raw_fixture: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for event in _as_list(raw_fixture.get("events")):
        type_info = event.get("type") or {}
        event_key = _normalize_key(
            _first_non_empty(
                type_info.get("developer_name"),
                type_info.get("code"),
                type_info.get("name"),
            )
        )

        mapped = SPORTMONKS_EVENT_MAP.get(event_key)
        if not mapped:
            continue

        event_type, detail = mapped
        minute = event.get("minute")

        normalized.append(
            {
                "type": event_type,
                "detail": detail,
                "player": {
                    "name": _first_non_empty(
                        event.get("player_name"),
                        (event.get("player") or {}).get("name"),
                        "Unknown",
                    )
                },
                "team": {
                    "id": _first_non_empty(
                        event.get("participant_id"),
                        (event.get("participant") or {}).get("id"),
                    )
                },
                "time": {"elapsed": minute if minute is not None else 0},
            }
        )

    normalized.sort(
        key=lambda item: (
            item["time"]["elapsed"],
            0 if item["type"] == "Goal" else 1,
        )
    )
    return normalized


def _extract_stat_value(stat: dict[str, Any]) -> Any:
    data = stat.get("data")
    if not isinstance(data, dict):
        return data

    for key in ("value", "total", "goals", "won", "successful", "success"):
        if data.get(key) is not None:
            return data[key]

    for value in data.values():
        if value is not None:
            return value

    return None


def _normalize_sportmonks_stats(raw_fixture: dict[str, Any]) -> list[dict[str, Any]]:
    home_team, away_team = _fixture_home_away(raw_fixture)
    grouped: dict[int, dict[str, Any]] = {}

    for stat in _as_list(raw_fixture.get("statistics")):
        type_info = stat.get("type") or {}
        stat_key = _normalize_key(
            _first_non_empty(
                type_info.get("developer_name"),
                type_info.get("code"),
                type_info.get("name"),
            )
        )
        stat_name = SPORTMONKS_FIXTURE_STAT_MAP.get(stat_key)
        if not stat_name:
            continue

        participant_id = stat.get("participant_id")
        if participant_id is None:
            continue

        value = _extract_stat_value(stat)
        if value is None:
            continue

        if stat_name == "Ball Possession":
            text = str(value)
            value = text if "%" in text else f"{text}%"

        grouped.setdefault(participant_id, {})[stat_name] = value

    def team_stats(team: dict[str, Any]) -> dict[str, Any]:
        team_id = team.get("id")
        return {
            "team": {"id": team_id},
            "statistics": [
                {"type": name, "value": value}
                for name, value in grouped.get(team_id, {}).items()
            ],
        }

    return [team_stats(home_team), team_stats(away_team)]


def _normalize_sportmonks_fixture(raw_fixture: dict[str, Any]) -> dict[str, Any]:
    home_team, away_team = _fixture_home_away(raw_fixture)
    scores = _as_list(raw_fixture.get("scores"))
    home_goals, away_goals = _current_score_map(scores)

    return {
        "fixture": {
            "id": raw_fixture.get("id"),
            "date": raw_fixture.get("starting_at"),
        },
        "league": {
            "name": _first_non_empty((raw_fixture.get("league") or {}).get("name"), "League")
        },
        "teams": {
            "home": {
                "id": home_team.get("id"),
                "name": home_team.get("name"),
                "logo": home_team.get("image_path", ""),
            },
            "away": {
                "id": away_team.get("id"),
                "name": away_team.get("name"),
                "logo": away_team.get("image_path", ""),
            },
        },
        "goals": {"home": home_goals, "away": away_goals},
        "events": _normalize_sportmonks_events(raw_fixture),
        "stats": _normalize_sportmonks_stats(raw_fixture),
    }


def _sort_fixtures_desc(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        fixtures,
        key=lambda fixture: str((fixture.get("fixture") or {}).get("date") or ""),
        reverse=True,
    )


def _api_football_recent_fixtures(fixtures: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return _sort_fixtures_desc(fixtures)[:limit]


def _sportmonks_fixture_details(fixture_id: int) -> dict[str, Any]:
    response = _sportmonks_request(
        f"fixtures/{fixture_id}",
        {
            "include": _sportmonks_includes(
                "league",
                "participants",
                "scores.participant",
                "events.type",
                "statistics.type",
            )
        },
    )
    data = _sportmonks_data(response)
    if isinstance(data, list):
        raw_fixture = data[0] if data else {}
    else:
        raw_fixture = data or {}
    return _normalize_sportmonks_fixture(raw_fixture)


def _sportmonks_fixture_list(raw_fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _sort_fixtures_desc(
        [_normalize_sportmonks_fixture(fixture) for fixture in raw_fixtures]
    )


def _sportmonks_detail_value(
    details: list[dict[str, Any]],
    aliases: tuple[str, ...],
    preferred_keys: tuple[str, ...],
    default: Any = 0,
) -> Any:
    for detail in details:
        type_info = detail.get("type") or {}
        detail_key = _normalize_key(
            _first_non_empty(
                type_info.get("developer_name"),
                type_info.get("code"),
                type_info.get("name"),
            )
        )
        if not detail_key:
            continue
        if not any(alias == detail_key or alias in detail_key for alias in aliases):
            continue

        value = detail.get("value")
        if not isinstance(value, dict):
            return value if value is not None else default

        for key in preferred_keys:
            if value.get(key) is not None:
                return value[key]

        for candidate in value.values():
            if candidate is not None:
                return candidate

    return default


def _normalize_sportmonks_player_stats(raw_player: dict[str, Any]) -> list[dict[str, Any]]:
    season_id = _sportmonks_season_id()
    statistics = _as_list(raw_player.get("statistics"))

    season_stat = next(
        (item for item in statistics if item.get("season_id") == season_id),
        statistics[0] if statistics else {},
    )
    details = _as_list(season_stat.get("details"))

    position_name = _simplify_position(
        _first_non_empty(
            (raw_player.get("detailedPosition") or {}).get("name"),
            (raw_player.get("position") or {}).get("name"),
        )
    )

    return [
        {
            "player": {
                "id": raw_player.get("id"),
                "name": _first_non_empty(raw_player.get("display_name"), raw_player.get("name")),
                "photo": raw_player.get("image_path", ""),
            },
            "statistics": [
                {
                    "games": {
                        "position": position_name,
                        "rating": str(
                            _sportmonks_detail_value(
                                details,
                                ("rating",),
                                ("average", "rating", "total", "value"),
                                "0",
                            )
                        ),
                        "minutes": _sportmonks_detail_value(
                            details,
                            ("minutesplayed", "minutes"),
                            ("total", "minutes", "value"),
                            0,
                        ),
                        "appearences": _sportmonks_detail_value(
                            details,
                            ("appearances", "appearence", "appearences", "gamesplayed"),
                            ("total", "value"),
                            0,
                        ),
                    },
                    "goals": {
                        "total": _sportmonks_detail_value(
                            details,
                            ("goals", "goal"),
                            ("total", "goals", "value"),
                            0,
                        ),
                        "assists": _sportmonks_detail_value(
                            details,
                            ("assists", "assist", "goalassists", "goalassist"),
                            ("total", "assists", "value"),
                            0,
                        ),
                    },
                    "shots": {
                        "on": _sportmonks_detail_value(
                            details,
                            ("shotsontarget", "shotontarget"),
                            ("total", "on", "value"),
                            0,
                        )
                    },
                    "passes": {
                        "key": _sportmonks_detail_value(
                            details,
                            ("keypasses", "keypass"),
                            ("total", "value"),
                            0,
                        )
                    },
                    "dribbles": {
                        "success": _sportmonks_detail_value(
                            details,
                            ("successfuldribbles", "dribblessuccess", "dribblescompleted"),
                            ("total", "successful", "success", "value"),
                            0,
                        )
                    },
                    "duels": {
                        "won": _sportmonks_detail_value(
                            details,
                            ("duelswon", "duelwon"),
                            ("won", "total", "value"),
                            0,
                        )
                    },
                }
            ],
        }
    ]


def _normalize_sportmonks_squad(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    squad: list[dict[str, Any]] = []

    for entry in entries:
        player = entry.get("player") or {}
        position_name = _first_non_empty(
            (entry.get("detailedPosition") or {}).get("name"),
            (entry.get("position") or {}).get("name"),
            (player.get("detailedPosition") or {}).get("name"),
            (player.get("position") or {}).get("name"),
        )
        squad.append(
            {
                "id": _first_non_empty(player.get("id"), entry.get("player_id")),
                "name": _first_non_empty(player.get("display_name"), player.get("name")),
                "photo": player.get("image_path", ""),
                "position": _simplify_position(position_name),
            }
        )

    return squad


def _normalize_sportmonks_injuries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    injuries: list[dict[str, Any]] = []

    for entry in entries:
        player = entry.get("player") or {}
        position_name = _first_non_empty(
            (player.get("detailedPosition") or {}).get("name"),
            (player.get("position") or {}).get("name"),
        )
        reason = _first_non_empty(
            (entry.get("sideline") or {}).get("name"),
            (entry.get("sideline") or {}).get("description"),
            (entry.get("type") or {}).get("name"),
            entry.get("category"),
            "Unavailable",
        )

        injuries.append(
            {
                "player": {
                    "id": _first_non_empty(player.get("id"), entry.get("player_id")),
                    "name": _first_non_empty(player.get("display_name"), player.get("name")),
                    "position": _simplify_position(position_name),
                    "reason": reason,
                }
            }
        )

    return injuries


def get_teams(league: int = 39, season: int = 2024) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(f"teams/seasons/{_sportmonks_season_id()}")
        teams = _as_list(_sportmonks_data(response))
        return [
            {
                "team": {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "logo": team.get("image_path", ""),
                }
            }
            for team in teams
        ]

    return _api_football_request("teams", {"league": league, "season": season}).get(
        "response", []
    )


def get_h2h(id_a: int, id_b: int, last: int = 10) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(
            f"fixtures/head-to-head/{id_a}/{id_b}",
            {
                "include": _sportmonks_includes("league", "participants", "scores.participant"),
                "per_page": max(last, 10),
            },
        )
        fixtures = _sportmonks_fixture_list(_as_list(_sportmonks_data(response)))
        return fixtures[:last]

    response = _api_football_request("fixtures/headtohead", {"h2h": f"{id_a}-{id_b}"}).get(
        "response", []
    )
    return _api_football_recent_fixtures(response, last)


def get_fixture_stats(fixture_id: int) -> list:
    if PROVIDER == "sportmonks":
        return _sportmonks_fixture_details(fixture_id).get("stats", [])

    return _api_football_request("fixtures/statistics", {"fixture": fixture_id}).get(
        "response", []
    )


def get_fixture_events(fixture_id: int) -> list:
    if PROVIDER == "sportmonks":
        return _sportmonks_fixture_details(fixture_id).get("events", [])

    return _api_football_request("fixtures/events", {"fixture": fixture_id}).get(
        "response", []
    )


def get_squad(team_id: int) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(
            f"squads/seasons/{_sportmonks_season_id()}/teams/{team_id}",
            {"include": _sportmonks_includes("player", "position", "detailedPosition")},
        )
        return _normalize_sportmonks_squad(_as_list(_sportmonks_data(response)))

    data = _api_football_request("players/squads", {"team": team_id}).get("response", [])
    return data[0].get("players", []) if data else []


def get_player_stats(player_id: int, season: int = 2024) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(
            f"players/{player_id}",
            {
                "include": _sportmonks_includes(
                    "position",
                    "detailedPosition",
                    "statistics.details.type",
                ),
                "filters": f"playerStatisticSeasons:{_sportmonks_season_id()}",
            },
        )
        data = _sportmonks_data(response)
        if isinstance(data, list):
            raw_player = data[0] if data else {}
        else:
            raw_player = data or {}
        return _normalize_sportmonks_player_stats(raw_player) if raw_player else []

    return _api_football_request("players", {"id": player_id, "season": season}).get(
        "response", []
    )


def get_injuries(team_id: int, league: int = 39, season: int = 2024) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(
            f"teams/{team_id}",
            {
                "include": _sportmonks_includes(
                    "sidelined.player.position",
                    "sidelined.player.detailedPosition",
                    "sidelined.type",
                    "sidelined.sideline",
                )
            },
        )
        data = _sportmonks_data(response)
        if isinstance(data, list):
            raw_team = data[0] if data else {}
        else:
            raw_team = data or {}
        return _normalize_sportmonks_injuries(_as_list(raw_team.get("sidelined")))

    return _api_football_request(
        "injuries", {"league": league, "season": season, "team": team_id}
    ).get("response", [])


def get_team_fixtures(team_id: int, league: int = 39, season: int = 2024, last: int = 10) -> list:
    if PROVIDER == "sportmonks":
        start_date, end_date = _sportmonks_season_dates()
        response = _sportmonks_request(
            f"fixtures/between/{start_date}/{end_date}/{team_id}",
            {
                "include": _sportmonks_includes("league", "participants", "scores.participant"),
                "per_page": 100,
            },
        )
        season_id = _sportmonks_season_id()
        raw_fixtures = [
            fixture
            for fixture in _as_list(_sportmonks_data(response))
            if fixture.get("season_id") == season_id
        ]
        return _sportmonks_fixture_list(raw_fixtures)[:last]

    response = _api_football_request(
        "fixtures", {"team": team_id, "league": league, "season": season}
    ).get("response", [])
    return _api_football_recent_fixtures(response, last)


def get_standings(league: int = 39, season: int = 2024) -> list:
    if PROVIDER == "sportmonks":
        response = _sportmonks_request(
            f"standings/seasons/{_sportmonks_season_id()}",
            {"include": "participant"},
        )
        return _as_list(_sportmonks_data(response))

    return _api_football_request("standings", {"league": league, "season": season}).get(
        "response", []
    )


def get_upcoming_fixtures(league: int = 39, season: int = 2024, next_n: int = 20) -> list:
    if PROVIDER == "sportmonks":
        today = datetime.now().strftime("%Y-%m-%d")
        _, end_date = _sportmonks_season_dates()
        response = _sportmonks_request(
            f"fixtures/between/{today}/{end_date}",
            {
                "include": _sportmonks_includes("league", "participants", "scores.participant"),
                "per_page": next_n * 2,
            },
        )
        season_id = _sportmonks_season_id()
        raw_fixtures = [
            f
            for f in _as_list(_sportmonks_data(response))
            if f.get("season_id") == season_id
        ]
        normalized = [_normalize_sportmonks_fixture(f) for f in raw_fixtures]
        normalized.sort(key=lambda f: str((f.get("fixture") or {}).get("date") or ""))
        return normalized[:next_n]

    return _api_football_request(
        "fixtures", {"league": league, "season": season, "next": next_n}
    ).get("response", [])


def enrich_fixture(fixture: dict) -> dict:
    fixture_id = fixture["fixture"]["id"]
    if PROVIDER == "sportmonks":
        return _sportmonks_fixture_details(fixture_id)

    return {
        **fixture,
        "events": get_fixture_events(fixture_id),
        "stats": get_fixture_stats(fixture_id),
    }


def parse_stat(stats: list, team_id: int, stat_type: str):
    for team_stats in stats:
        if team_stats["team"]["id"] == team_id:
            for stat in team_stats["statistics"]:
                if stat["type"] == stat_type:
                    return stat["value"]
    return None


# ── ESPN free public API (no key required) ─────────────────────────────────────

ESPN_SOCCER_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Map API-Football league IDs → ESPN league slugs
ESPN_LEAGUE_SLUGS: dict[int, str] = {
    39:  "eng.1",   # Premier League
    140: "esp.1",   # La Liga
    78:  "ger.1",   # Bundesliga
    135: "ita.1",   # Serie A
    61:  "fra.1",   # Ligue 1
    2:   "UEFA.CL", # Champions League
    3:   "UEFA.EL", # Europa League
}


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_espn_event(event: dict) -> dict | None:
    competitions = _as_list(event.get("competitions"))
    if not competitions:
        return None
    comp = competitions[0]
    competitors = _as_list(comp.get("competitors"))

    home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home_c or not away_c:
        return None

    ht = home_c.get("team") or {}
    at = away_c.get("team") or {}
    status_state = ((comp.get("status") or {}).get("type") or {}).get("state", "pre")
    is_pre = status_state == "pre"

    venue = comp.get("venue") or {}
    season = event.get("season") or {}
    week = event.get("week") or {}

    return {
        "fixture": {
            "id": str(event.get("id", "")),
            "date": event.get("date", ""),
            "venue": {"name": venue.get("fullName", "")},
        },
        "league": {
            "name": season.get("displayName", "League"),
            "round": f"Gameweek {week['number']}" if week.get("number") else "",
        },
        "teams": {
            "home": {
                "id": _safe_int(ht.get("id")) or 0,
                "name": ht.get("displayName", "Home"),
                "logo": ht.get("logo", ""),
            },
            "away": {
                "id": _safe_int(at.get("id")) or 0,
                "name": at.get("displayName", "Away"),
                "logo": at.get("logo", ""),
            },
        },
        "goals": {
            "home": None if is_pre else _safe_int(home_c.get("score")),
            "away": None if is_pre else _safe_int(away_c.get("score")),
        },
        "_source": "espn",
    }


def get_espn_fixtures(league_slug: str = "eng.1", next_n: int = 20) -> list:
    """
    Fetch upcoming fixtures from ESPN's free public API — no API key needed.
    Tries up to 6 consecutive weeks ahead and caches each fetch separately.
    """
    from datetime import timezone

    all_events: list[dict] = []
    seen_ids: set[str] = set()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    for week in range(6):
        if len(all_events) >= next_n:
            break
        target = (now + timedelta(weeks=week)).strftime("%Y%m%d")
        cache_key = f"espn:{league_slug}:{target}"
        cache_p = Path("cache") / f"{hashlib.md5(cache_key.encode()).hexdigest()}.json"

        if cache_p.exists() and _cache_valid(cache_p):
            try:
                raw: list[dict] = json.loads(cache_p.read_text(encoding="utf-8"))
            except Exception:
                raw = []
        else:
            try:
                url = f"{ESPN_SOCCER_BASE}/{league_slug}/scoreboard"
                with requests.Session() as sess:
                    sess.trust_env = False
                    resp = sess.get(
                        url,
                        params={"dates": target},
                        timeout=15,
                        headers={"Accept": "application/json"},
                    )
                resp.raise_for_status()
                raw = [
                    norm
                    for e in resp.json().get("events", [])
                    if (norm := _normalize_espn_event(e)) is not None
                ]
                Path("cache").mkdir(exist_ok=True)
                cache_p.write_text(json.dumps(raw), encoding="utf-8")
            except Exception:
                raw = []

        for event in raw:
            eid = event["fixture"]["id"]
            if eid not in seen_ids and event["fixture"]["date"][:10] >= today_str:
                seen_ids.add(eid)
                all_events.append(event)

    all_events.sort(key=lambda e: e["fixture"]["date"])
    return all_events[:next_n]
