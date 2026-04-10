"""
league_config.py -- BallDontLie-supported football competitions for ScorPred.

Only competitions with BallDontLie football coverage are exposed in the props
experience. Difficulty weights are used during cross-competition aggregation:
  < 1.00 = tougher competition
  > 1.00 = softer competition
  1.00   = baseline domestic league
"""

from __future__ import annotations

CURRENT_SEASON: int = 2024
DEFAULT_LEAGUE_KEY = "premier_league"

# key -> {id, name, country, flag, difficulty, type, bdl_slug, bdl_version}
SUPPORTED_LEAGUES: dict[str, dict] = {
    "premier_league": {
        "id": 39,
        "name": "Premier League",
        "country": "England",
        "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "difficulty": 1.00,
        "type": "league",
        "bdl_slug": "epl",
        "bdl_version": "v2",
    },
    "la_liga": {
        "id": 140,
        "name": "La Liga",
        "country": "Spain",
        "flag": "🇪🇸",
        "difficulty": 1.00,
        "type": "league",
        "bdl_slug": "laliga",
        "bdl_version": "v1",
    },
    "serie_a": {
        "id": 135,
        "name": "Serie A",
        "country": "Italy",
        "flag": "🇮🇹",
        "difficulty": 1.00,
        "type": "league",
        "bdl_slug": "seriea",
        "bdl_version": "v1",
    },
    "bundesliga": {
        "id": 78,
        "name": "Bundesliga",
        "country": "Germany",
        "flag": "🇩🇪",
        "difficulty": 1.00,
        "type": "league",
        "bdl_slug": "bundesliga",
        "bdl_version": "v1",
    },
    "ligue_1": {
        "id": 61,
        "name": "Ligue 1",
        "country": "France",
        "flag": "🇫🇷",
        "difficulty": 1.00,
        "type": "league",
        "bdl_slug": "ligue1",
        "bdl_version": "v1",
    },
    "champions_league": {
        "id": 2,
        "name": "Champions League",
        "country": "Europe",
        "flag": "⭐",
        "difficulty": 0.85,
        "type": "european",
        "bdl_slug": "ucl",
        "bdl_version": "v1",
    },
}

# Convenience: id → config
LEAGUE_FLAGS: dict[str, str] = {
    "premier_league": "🏴",
    "la_liga": "🇪🇸",
    "serie_a": "🇮🇹",
    "bundesliga": "🇩🇪",
    "ligue_1": "🇫🇷",
    "champions_league": "⭐",
}

for _league_key, _flag in LEAGUE_FLAGS.items():
    if _league_key in SUPPORTED_LEAGUES:
        SUPPORTED_LEAGUES[_league_key]["flag"] = _flag

LEAGUE_BY_ID: dict[int, dict] = {cfg["id"]: cfg for cfg in SUPPORTED_LEAGUES.values()}
LEAGUE_KEY_BY_ID: dict[int, str] = {
    cfg["id"]: key for key, cfg in SUPPORTED_LEAGUES.items()
}
DEFAULT_LEAGUE_ID: int = SUPPORTED_LEAGUES[DEFAULT_LEAGUE_KEY]["id"]
SUPPORTED_LEAGUE_IDS: list[int] = [cfg["id"] for cfg in SUPPORTED_LEAGUES.values()]

# Convenience: difficulty by league id
COMP_DIFFICULTY: dict[int, float] = {cfg["id"]: cfg["difficulty"] for cfg in SUPPORTED_LEAGUES.values()}

# Domestic leagues grouped by country (for cross-comp filtering)
DOMESTIC_LEAGUE_IDS: set[int] = {
    cfg["id"] for cfg in SUPPORTED_LEAGUES.values() if cfg["type"] == "league"
}
EUROPEAN_COMP_IDS: set[int] = {
    cfg["id"] for cfg in SUPPORTED_LEAGUES.values() if cfg["type"] == "european"
}
CUP_IDS: set[int] = set()


def get_difficulty(league_id: int) -> float:
    """Return the competition difficulty weight for a league id (default 1.0)."""
    return COMP_DIFFICULTY.get(league_id, 1.00)


def get_league_info(league_id: int) -> dict | None:
    """Return the league config dict for a given id, or None if not found."""
    return LEAGUE_BY_ID.get(league_id)


def get_league_key(league_id: int) -> str | None:
    """Return the internal league key for a given competition id."""
    return LEAGUE_KEY_BY_ID.get(league_id)


def all_leagues() -> list[dict]:
    """Return all supported competitions in UI order."""
    return list(SUPPORTED_LEAGUES.values())


def leagues_for_country(country: str) -> list[dict]:
    """Return all leagues/cups for a given country name."""
    return [cfg for cfg in SUPPORTED_LEAGUES.values() if cfg["country"] == country]
