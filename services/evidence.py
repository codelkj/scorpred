"""Evidence-building helpers for soccer matchup and prediction routes."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any


_UPCOMING_FIXTURE_CACHE_TTL_SECONDS = 600
_UPCOMING_FIXTURE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def clean_injuries(items: list[dict]) -> list[dict]:
    cleaned = []
    for item in items or []:
        if item.get("placeholder"):
            continue
        player = item.get("player") or {}
        if player.get("name") == "No injuries reported":
            continue
        cleaned.append(item)
    return cleaned


def display_injuries(items: list[dict]) -> list[dict]:
    return clean_injuries(items)


def build_opp_strengths(engine, standings: list) -> dict:
    try:
        return engine.build_opp_strengths_from_standings(standings)
    except Exception:
        return {}


def load_upcoming_fixtures(
    api_client,
    predictor,
    engine,
    *,
    league: int,
    season: int,
    logger,
    football_data_source,
    next_n: int = 20,
    max_deep_predictions: int = 6,
):
    force_refresh = bool(getattr(api_client, "FORCE_REFRESH", False))
    deep_limit = max(0, int(max_deep_predictions))
    cache_key = (league, season, int(next_n), deep_limit, football_data_source())
    now = datetime.now(UTC)

    if not force_refresh:
        cached = _UPCOMING_FIXTURE_CACHE.get(cache_key)
        if cached and isinstance(cached.get("expires_at"), datetime) and cached["expires_at"] > now:
            return deepcopy(cached["value"])

    load_error = None
    fixtures_with_pred = []
    data_source = football_data_source()

    try:
        upcoming = api_client.get_upcoming_fixtures(league, season, next_n=next_n)
    except Exception as exc:
        upcoming = []
        load_error = str(exc)
        logger.error("Upcoming fixtures fetch failed: %s", exc)

    standings_list = []
    if deep_limit > 0:
        try:
            standings_list = api_client.get_standings(league, season)
        except Exception as exc:
            standings_list = []
            logger.warning("Standings unavailable for quick predictions: %s", exc)

    opp_strengths = build_opp_strengths(engine, standings_list)

    # Avoid duplicate team API calls in the same page load.
    team_fixtures_cache: dict[int, list] = {}
    injuries_cache: dict[int, list] = {}
    h2h_cache: dict[tuple[int, int], list] = {}

    def _cached_team_fixtures(team_id: int) -> list:
        if team_id in team_fixtures_cache:
            return team_fixtures_cache[team_id]
        rows = api_client.get_team_fixtures(team_id, league, season, last=10)
        team_fixtures_cache[team_id] = rows
        return rows

    def _cached_injuries(team_id: int) -> list:
        if team_id in injuries_cache:
            return injuries_cache[team_id]
        rows = clean_injuries(api_client.get_injuries(league, season, team_id))
        injuries_cache[team_id] = rows
        return rows

    def _cached_h2h(home_id: int, away_id: int) -> list:
        key = tuple(sorted((int(home_id), int(away_id))))
        if key in h2h_cache:
            return h2h_cache[key]
        rows = api_client.get_h2h(home_id, away_id, last=10)
        h2h_cache[key] = rows
        return rows

    for idx, fixture in enumerate(upcoming):
        prediction = None
        try:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            home_name = fixture["teams"]["home"]["name"]
            away_name = fixture["teams"]["away"]["name"]

            if idx >= deep_limit:
                prediction = engine.scorpred_predict(
                    form_a=[],
                    form_b=[],
                    h2h_form_a=[],
                    h2h_form_b=[],
                    injuries_a=[],
                    injuries_b=[],
                    team_a_is_home=True,
                    team_a_name=home_name,
                    team_b_name=away_name,
                    sport="soccer",
                    opp_strengths=opp_strengths,
                )
                fixtures_with_pred.append({**fixture, "prediction": prediction})
                continue

            h2h_raw = []
            fixtures_home = []
            fixtures_away = []
            injuries_home = []
            injuries_away = []

            try:
                h2h_raw = _cached_h2h(home_id, away_id)
            except Exception:
                logger.debug("Upcoming fixture h2h missing for %s vs %s", home_name, away_name)
            try:
                fixtures_home = _cached_team_fixtures(home_id)
            except Exception:
                logger.debug("Upcoming fixture home team form missing for %s", home_name)
            try:
                fixtures_away = _cached_team_fixtures(away_id)
            except Exception:
                logger.debug("Upcoming fixture away team form missing for %s", away_name)
            try:
                injuries_home = _cached_injuries(home_id)
            except Exception:
                logger.debug("Upcoming fixture home injuries missing for %s", home_name)
            try:
                injuries_away = _cached_injuries(away_id)
            except Exception:
                logger.debug("Upcoming fixture away injuries missing for %s", away_name)

            h2h_raw = predictor.filter_recent_completed_fixtures(
                h2h_raw,
                current_season=season,
                seasons_back=5,
            )
            fixtures_home = predictor.filter_recent_completed_fixtures(
                fixtures_home,
                current_season=season,
            )
            fixtures_away = predictor.filter_recent_completed_fixtures(
                fixtures_away,
                current_season=season,
            )

            form_home = predictor.extract_form(fixtures_home, home_id)[:5]
            form_away = predictor.extract_form(fixtures_away, away_id)[:5]
            h2h_form_home = predictor.extract_form(h2h_raw, home_id)[:5]
            h2h_form_away = predictor.extract_form(h2h_raw, away_id)[:5]

            prediction = engine.scorpred_predict(
                form_a=form_home,
                form_b=form_away,
                h2h_form_a=h2h_form_home,
                h2h_form_b=h2h_form_away,
                injuries_a=injuries_home,
                injuries_b=injuries_away,
                team_a_is_home=True,
                team_a_name=home_name,
                team_b_name=away_name,
                sport="soccer",
                opp_strengths=opp_strengths,
            )
        except Exception as exc:
            logger.warning(
                "Upcoming fixture prediction failed for %s vs %s: %s",
                fixture.get("fixture", {}).get("id"),
                exc,
            )
            prediction = engine.scorpred_predict(
                form_a=[],
                form_b=[],
                h2h_form_a=[],
                h2h_form_b=[],
                injuries_a=[],
                injuries_b=[],
                team_a_is_home=True,
                team_a_name=fixture.get("teams", {}).get("home", {}).get("name", "Home"),
                team_b_name=fixture.get("teams", {}).get("away", {}).get("name", "Away"),
                sport="soccer",
                opp_strengths={},
            )
        fixtures_with_pred.append({**fixture, "prediction": prediction})

    result = (fixtures_with_pred, load_error, data_source, "")
    _UPCOMING_FIXTURE_CACHE[cache_key] = {
        "expires_at": now + timedelta(seconds=_UPCOMING_FIXTURE_CACHE_TTL_SECONDS),
        "value": deepcopy(result),
    }
    return result


def build_key_threats(
    squad: list,
    injuries: list,
    fixtures: list,
    team_id: int,
    *,
    predictor,
    current_season: int,
) -> list[dict]:
    injured_ids = {
        (inj.get("player") or {}).get("id")
        for inj in injuries
        if (inj.get("player") or {}).get("id")
    }
    fixtures = predictor.filter_recent_completed_fixtures(fixtures, current_season=current_season)
    form = predictor.extract_form(fixtures, team_id)
    avg_gf = predictor.avg_goals(form, scored=True) if form else 1.2
    team_lambda = max(0.3, avg_gf)

    position_order = {"Attacker": 0, "Midfielder": 1, "Defender": 2, "Goalkeeper": 3}
    threat_labels = {
        "Attacker": "Goal Threat",
        "Midfielder": "Creative Threat",
        "Defender": "Set Piece Threat",
        "Goalkeeper": "Shot Stopper",
    }
    contribution_map = {
        "Attacker": "goals / shots on target",
        "Midfielder": "key passes / assists",
        "Defender": "aerial duels / clearances",
        "Goalkeeper": "saves / clean sheet",
    }

    candidates = []
    for player_entry in squad:
        player_obj = player_entry.get("player") or player_entry
        player_id = player_obj.get("id")
        if not player_id:
            continue
        position = player_obj.get("position") or player_entry.get("position") or "Unknown"
        is_injured = player_id in injured_ids
        pos_rank = position_order.get(position, 4)

        pos_boost = 1.4 if position == "Attacker" else 1.1 if position == "Midfielder" else 0.7
        health_penalty = 0.5 if is_injured else 1.0
        score = pos_boost * health_penalty * team_lambda

        candidates.append(
            {
                "id": player_id,
                "name": player_obj.get("name") or "",
                "photo": player_obj.get("photo", ""),
                "position": position,
                "pos_rank": pos_rank,
                "threat_label": threat_labels.get(position, "Key Player"),
                "contribution": contribution_map.get(position, "match impact"),
                "injured": is_injured,
                "score": score,
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["pos_rank"]))
    return candidates[:5]


def team_form_payload(
    api_client,
    predictor,
    *,
    team_id: int,
    league: int,
    season: int,
) -> dict:
    fixtures = api_client.get_team_fixtures(team_id, league, season, last=20)
    fixtures = predictor.filter_recent_completed_fixtures(fixtures, current_season=season)
    form = predictor.extract_form(fixtures, team_id)[:5]
    return {
        "form_string": "".join(item.get("result", "") for item in form),
        "rows": form,
    }
