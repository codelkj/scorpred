"""Flask application for the ScorPred football and NBA predictor."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import api_client as ac
import model_tracker as mt
import predictor as pred
import props_engine as pe
import result_updater as ru
import scorpred_engine as se
from league_config import (
    CURRENT_SEASON,
    DEFAULT_LEAGUE_ID,
    LEAGUE_BY_ID,
    SUPPORTED_LEAGUES,
    SUPPORTED_LEAGUE_IDS,
)
from nba_routes import nba_bp

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None

try:
    import nba_live_client as nc
except Exception:  # pragma: no cover
    nc = None

try:
    import nba_predictor as np_nba
except Exception:  # pragma: no cover
    np_nba = None

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "scorpred-dev-secret")

# Initialize app config with tracking state
app.config["TRACKING_LAST_BOOTSTRAP"] = None

# ── Blueprints ─────────────────────────────────────────────────────────────────
app.register_blueprint(nba_bp)

LEAGUE = DEFAULT_LEAGUE_ID
SEASON = CURRENT_SEASON

_EMPTY_METRICS = {
    "finalized_predictions": 0,
    "overall_accuracy": None,
    "by_confidence": {},
    "by_sport": {},
    "recent_predictions": [],
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _refresh_requested() -> bool:
    return str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}


def _set_data_refresh() -> bool:
    refresh = _refresh_requested()
    try:
        ac.set_force_refresh(refresh)
    except Exception:
        pass
    return refresh


@app.after_request
def _reset_force_refresh(response):
    try:
        ac.set_force_refresh(False)
    except Exception:
        pass
    return response


def _football_data_source() -> str:
    return "API-Football via RapidAPI" if getattr(ac, "RAPIDAPI_OK", False) else "ESPN public football fallback"


def _page_context(data_source: str | None = None, **kwargs) -> dict:
    context = {
        "data_source": data_source or _football_data_source(),
        "last_updated": _now_stamp(),
    }
    context.update(kwargs)
    return context


def _clean_injuries(items: list[dict]) -> list[dict]:
    cleaned = []
    for item in items or []:
        if item.get("placeholder"):
            continue
        player = item.get("player") or {}
        if player.get("name") == "No injuries reported":
            continue
        cleaned.append(item)
    return cleaned


def _display_injuries(items: list[dict]) -> list[dict]:
    return _clean_injuries(items)


def _build_opp_strengths(standings: list) -> dict:
    try:
        return se.build_opp_strengths_from_standings(standings)
    except Exception:
        return {}


def _normalise_probs(win_prob: dict) -> dict:
    keys = ("a", "draw", "b")
    values = [max(0.0, float(win_prob.get(key, 0.0))) for key in keys]
    if not any(values):
        return {"a": 33.4, "draw": 33.3, "b": 33.3}

    total = sum(values) or 1.0
    rounded = [round((value * 100.0) / total, 1) for value in values]
    largest_idx = max(range(len(rounded)), key=lambda idx: rounded[idx])
    rounded[largest_idx] = round(rounded[largest_idx] + (100.0 - sum(rounded)), 1)
    return {key: rounded[idx] for idx, key in enumerate(keys)}


def _football_supported_leagues() -> list[dict]:
    leagues = []
    for key, league_id in getattr(ac, "LEAGUES", {}).items():
        config = LEAGUE_BY_ID.get(league_id, {})
        leagues.append(
            {
                "key": key,
                "id": league_id,
                "name": config.get("name", key.replace("_", " ").title()),
                "country": config.get("country", ""),
                "flag": config.get("flag", ""),
                "difficulty": config.get("difficulty", 1.0),
                "type": config.get("type", "competition"),
            }
        )
    return leagues


def _critical_error(message: str, status_code: int = 503):
    return render_template("error.html", **_page_context(msg=message)), status_code


def _normalize_team_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    ignored = {"fc", "cf", "sc", "afc", "club"}
    tokens = [token for token in text.split() if token not in ignored]
    return " ".join(tokens)


def _tracking_window_dates() -> tuple[set[str], list[str]]:
    today = date.today()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    required = {yesterday, today.strftime("%Y-%m-%d")}
    return required, [yesterday, today.strftime("%Y-%m-%d"), tomorrow]


def _tracking_is_complete() -> bool:
    required_dates, _ = _tracking_window_dates()
    predictions = mt._load_predictions()
    seen_dates = {p.get("date", "") for p in predictions if p.get("sport", "").lower() in {"soccer", "nba"}}
    return required_dates.issubset(seen_dates)


def _bootstrap_model_tracking() -> dict[str, int]:
    required_dates, tracking_dates = _tracking_window_dates()
    inserted = 0
    updated = 0
    predictions_generated = 0
    soccer_fetched = 0
    nba_fetched = 0

    existing_keys = {
        mt._get_game_key(
            p.get("sport", ""),
            p.get("date", ""),
            p.get("team_a", ""),
            p.get("team_b", ""),
        )
        for p in mt._load_predictions()
    }

    def _soccer_fixture_key(fixture: dict) -> str:
        fixture_date = str((fixture.get("fixture") or {}).get("date") or "")[:10]
        home = (fixture.get("teams") or {}).get("home", {}).get("name", "")
        away = (fixture.get("teams") or {}).get("away", {}).get("name", "")
        return f"{fixture_date}|{home}|{away}"

    fixtures_seen: set[str] = set()
    soccer_fixtures: list[dict] = []
    for league_id in SUPPORTED_LEAGUE_IDS:
        try:
            upcoming = ac.get_upcoming_fixtures(league_id, SEASON, next_n=40)
        except Exception:
            upcoming = []

        for fixture in upcoming:
            fixture_date = str((fixture.get("fixture") or {}).get("date") or "")[:10]
            if fixture_date not in tracking_dates:
                continue
            key = _soccer_fixture_key(fixture)
            if key in fixtures_seen:
                continue
            fixtures_seen.add(key)
            soccer_fixtures.append(fixture)

        slug = getattr(ac, "ESPN_SLUG_BY_LEAGUE", {}).get(league_id)
        if not slug:
            continue

        try:
            espn_fixtures = ac.get_espn_fixtures(slug, next_n=40)
        except Exception:
            espn_fixtures = []

        for fixture in espn_fixtures:
            fixture_date = str((fixture.get("fixture") or {}).get("date") or "")[:10]
            if fixture_date not in tracking_dates:
                continue
            key = _soccer_fixture_key(fixture)
            if key in fixtures_seen:
                continue
            fixtures_seen.add(key)
            soccer_fixtures.append(fixture)

    soccer_fetched = len(soccer_fixtures)

    standings_cache: dict[int, list[dict]] = {}
    for fixture in soccer_fixtures:
        fixture_date = str((fixture.get("fixture") or {}).get("date") or "")[:10]
        home = (fixture.get("teams") or {}).get("home", {})
        away = (fixture.get("teams") or {}).get("away", {})
        home_id = home.get("id")
        away_id = away.get("id")
        home_name = home.get("name", "Home")
        away_name = away.get("name", "Away")

        league_id = (fixture.get("league") or {}).get("id") or LEAGUE
        if league_id not in standings_cache:
            try:
                standings_cache[league_id] = ac.get_standings(league_id, SEASON)
            except Exception:
                standings_cache[league_id] = []

        opp_strengths = _build_opp_strengths(standings_cache.get(league_id, []))

        try:
            h2h_raw = ac.get_h2h(home_id, away_id, last=10) if home_id and away_id else []
        except Exception:
            h2h_raw = []
        try:
            fixtures_home = ac.get_team_fixtures(home_id, league_id, SEASON, last=10) if home_id else []
        except Exception:
            fixtures_home = []
        try:
            fixtures_away = ac.get_team_fixtures(away_id, league_id, SEASON, last=10) if away_id else []
        except Exception:
            fixtures_away = []
        try:
            injuries_home = _clean_injuries(ac.get_injuries(league_id, SEASON, home_id)) if home_id else []
        except Exception:
            injuries_home = []
        try:
            injuries_away = _clean_injuries(ac.get_injuries(league_id, SEASON, away_id)) if away_id else []
        except Exception:
            injuries_away = []

        form_home = pred.extract_form(
            pred.filter_recent_completed_fixtures(fixtures_home, current_season=SEASON),
            home_id,
        )[:5]
        form_away = pred.extract_form(
            pred.filter_recent_completed_fixtures(fixtures_away, current_season=SEASON),
            away_id,
        )[:5]
        h2h_form_home = pred.extract_form(
            pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5),
            home_id,
        )[:5]
        h2h_form_away = pred.extract_form(
            pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5),
            away_id,
        )[:5]

        try:
            prediction = se.scorpred_predict(
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
        except Exception:
            continue

        best_pick = prediction.get("best_pick", {})
        pred_winner = best_pick.get("prediction", "")
        probs = prediction.get("win_probabilities", {})
        conf = best_pick.get("confidence", "Low")
        game_key = mt._get_game_key("soccer", fixture_date, home_name, away_name)
        existing = game_key in existing_keys

        try:
            mt.save_prediction(
                sport="soccer",
                team_a=home_name,
                team_b=away_name,
                predicted_winner=pred_winner,
                win_probs=probs,
                confidence=conf,
                game_date=fixture_date,
            )
            predictions_generated += 1
            if existing:
                updated += 1
            else:
                inserted += 1
                existing_keys.add(game_key)
        except Exception:
            continue

    # Track NBA games
    nba_games: list[dict] = []

    if nc is not None and np_nba is not None:
        try:
            nba_games.extend(nc.get_scoreboard_games(date.today()))
        except Exception:
            pass
        try:
            nba_games.extend(nc.get_scoreboard_games(date.today() - timedelta(days=1)))
        except Exception:
            pass
        try:
            nba_games.extend(nc.get_upcoming_games(next_n=40, days_ahead=1))
        except Exception:
            pass

        game_ids: set[str] = set()
        unique_nba_games: list[dict] = []
        for game in nba_games:
            game_id = str(game.get("id", ""))
            if not game_id or game_id in game_ids:
                continue
            game_ids.add(game_id)
            unique_nba_games.append(game)

        nba_fetched = len(unique_nba_games)

        nba_standings = {}
        try:
            raw_standings = nc.get_standings()
            flat: list = []
            if isinstance(raw_standings, dict):
                for group in raw_standings.values():
                    if isinstance(group, list):
                        flat.extend(group)
            else:
                flat = list(raw_standings or [])

            ranked = []
            for i, entry in enumerate(flat):
                if not isinstance(entry, dict):
                    continue
                team_info = entry.get("team") or entry
                name = team_info.get("name") or team_info.get("nickname", "")
                rank = entry.get("rank") or entry.get("conference", {}).get("rank") or (i + 1)
                if name:
                    ranked.append({"team": {"name": name}, "rank": rank})

            nba_standings = se.build_opp_strengths_from_standings(ranked)
        except Exception:
            nba_standings = {}

        for game in unique_nba_games:
            teams_block = game.get("teams") or {}
            home_team = teams_block.get("home") or {}
            away_team = teams_block.get("visitors") or {}

            home_name = home_team.get("name") or home_team.get("nickname", "Home")
            away_name = away_team.get("name") or away_team.get("nickname", "Away")
            fixture_date = str((game.get("date") or {}).get("start") or "")[:10]

            try:
                h2h_raw = []
                form_home_raw = []
                form_away_raw = []
                injuries_home = []
                injuries_away = []

                try:
                    h2h_raw = nc.get_h2h(str(home_team.get("id", "")), str(away_team.get("id", "")))
                except Exception:
                    pass
                try:
                    form_home_raw = nc.get_team_recent_form(str(home_team.get("id", "")))
                except Exception:
                    pass
                try:
                    form_away_raw = nc.get_team_recent_form(str(away_team.get("id", "")))
                except Exception:
                    pass
                try:
                    injuries_home = nc.get_team_injuries(str(home_team.get("id", "")))
                except Exception:
                    pass
                try:
                    injuries_away = nc.get_team_injuries(str(away_team.get("id", "")))
                except Exception:
                    pass

                prediction = se.scorpred_predict(
                    form_a=np_nba.extract_recent_form(form_home_raw, str(home_team.get("id", "")), n=5),
                    form_b=np_nba.extract_recent_form(form_away_raw, str(away_team.get("id", "")), n=5),
                    h2h_form_a=np_nba.extract_recent_form(h2h_raw, str(home_team.get("id", "")), n=5),
                    h2h_form_b=np_nba.extract_recent_form(h2h_raw, str(away_team.get("id", "")), n=5),
                    injuries_a=injuries_home,
                    injuries_b=injuries_away,
                    team_a_is_home=True,
                    team_a_name=home_name,
                    team_b_name=away_name,
                    sport="nba",
                    opp_strengths=nba_standings,
                )
            except Exception:
                continue

            best_pick = prediction.get("best_pick", {})
            pred_winner = best_pick.get("prediction", "")
            probs = prediction.get("win_probabilities", {})
            conf = best_pick.get("confidence", "Low")
            game_key = mt._get_game_key("nba", fixture_date, home_name, away_name)
            existing = game_key in existing_keys

            try:
                mt.save_prediction(
                    sport="nba",
                    team_a=home_name,
                    team_b=away_name,
                    predicted_winner=pred_winner,
                    win_probs=probs,
                    confidence=conf,
                    game_date=fixture_date,
                )
                predictions_generated += 1
                if existing:
                    updated += 1
                else:
                    inserted += 1
                    existing_keys.add(game_key)
            except Exception:
                continue
    else:
        app.logger.warning("NBA tracking skipped because nba_live_client or nba_predictor is unavailable.")
        nba_fetched = 0

    result_stats = ru.update_pending_predictions()
    completed_updated = result_stats.get("updated", 0)
    app.logger.debug(
        "model_tracking: soccer_fetched=%d nba_fetched=%d predictions_generated=%d inserted=%d updated=%d results_updated=%d",
        soccer_fetched,
        nba_fetched,
        predictions_generated,
        inserted,
        updated,
        completed_updated,
    )

    return {
        "soccer_fetched": soccer_fetched,
        "nba_fetched": nba_fetched,
        "predictions_generated": predictions_generated,
        "inserted": inserted,
        "updated": updated,
        "results_updated": completed_updated,
    }


def _ensure_model_tracking():
    if not _tracking_is_complete():
        app.logger.info("Model performance tracking bootstrap triggered.")
        _bootstrap_model_tracking()


@app.before_request
def _bootstrap_tracking_daily():
    if request.endpoint in {None, "static"}:
        return
    today_str = date.today().strftime("%Y-%m-%d")
    if app.config.get("TRACKING_LAST_BOOTSTRAP") == today_str:
        return
    try:
        _ensure_model_tracking()
    except Exception as exc:
        app.logger.debug("Daily tracking check failed: %s", exc, exc_info=True)
    app.config["TRACKING_LAST_BOOTSTRAP"] = today_str


def _resolve_provider_team_by_name(name: str, teams: list[dict]) -> dict | None:
    target = _normalize_team_name(name)
    if not target:
        return None

    provider_teams = [(entry.get("team") or entry) for entry in teams]
    provider_teams = [team for team in provider_teams if team.get("id")]

    for team in provider_teams:
        if _normalize_team_name(team.get("name")) == target:
            return team

    for team in provider_teams:
        candidate = _normalize_team_name(team.get("name"))
        if candidate and (target in candidate or candidate in target):
            return team

    target_tokens = set(target.split())
    best_team = None
    best_score = 0
    for team in provider_teams:
        candidate_tokens = set(_normalize_team_name(team.get("name")).split())
        score = len(target_tokens & candidate_tokens)
        if score > best_score:
            best_score = score
            best_team = team

    return best_team if best_score else None


def _fixture_context_from_form() -> dict | None:
    fixture_id = request.form.get("fixture_id", "").strip()
    fixture_date = request.form.get("fixture_date", "").strip()
    if not fixture_id and not fixture_date:
        return None
    return {
        "id": fixture_id,
        "date": fixture_date,
        "league_name": request.form.get("league_name", "").strip(),
        "round": request.form.get("round", "").strip(),
        "venue_name": request.form.get("venue_name", "").strip(),
        "data_source": request.form.get("data_source", "configured").strip().lower() or "configured",
        "home_name": request.form.get("team_a_name", "").strip(),
        "home_logo": request.form.get("team_a_logo", "").strip(),
        "away_name": request.form.get("team_b_name", "").strip(),
        "away_logo": request.form.get("team_b_logo", "").strip(),
    }


def _selected_fixture() -> dict:
    return session.get("selected_fixture", {})


def _load_upcoming_fixtures(next_n: int = 20):
    load_error = None
    fixtures_with_pred = []
    data_source = _football_data_source()

    try:
        upcoming = ac.get_upcoming_fixtures(LEAGUE, SEASON, next_n=next_n)
    except Exception as exc:
        upcoming = []
        load_error = str(exc)
        app.logger.error("Upcoming fixtures fetch failed: %s", exc)

    try:
        standings_list = ac.get_standings(LEAGUE, SEASON)
    except Exception as exc:
        standings_list = []
        app.logger.warning("Standings unavailable for quick predictions: %s", exc)

    for fixture in upcoming:
        try:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            home_name = fixture["teams"]["home"]["name"]
            away_name = fixture["teams"]["away"]["name"]

            h2h_raw = []
            fixtures_home = []
            fixtures_away = []
            injuries_home = []
            injuries_away = []

            try:
                h2h_raw = ac.get_h2h(home_id, away_id, last=10)
            except Exception:
                app.logger.debug("Upcoming fixture h2h missing for %s vs %s", home_name, away_name)
            try:
                fixtures_home = ac.get_team_fixtures(home_id, LEAGUE, SEASON, last=10)
            except Exception:
                app.logger.debug("Upcoming fixture home team form missing for %s", home_name)
            try:
                fixtures_away = ac.get_team_fixtures(away_id, LEAGUE, SEASON, last=10)
            except Exception:
                app.logger.debug("Upcoming fixture away team form missing for %s", away_name)
            try:
                injuries_home = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, home_id))
            except Exception:
                app.logger.debug("Upcoming fixture home injuries missing for %s", home_name)
            try:
                injuries_away = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, away_id))
            except Exception:
                app.logger.debug("Upcoming fixture away injuries missing for %s", away_name)

            h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)
            fixtures_home = pred.filter_recent_completed_fixtures(fixtures_home, current_season=SEASON)
            fixtures_away = pred.filter_recent_completed_fixtures(fixtures_away, current_season=SEASON)

            form_home = pred.extract_form(fixtures_home, home_id)[:5]
            form_away = pred.extract_form(fixtures_away, away_id)[:5]
            h2h_form_home = pred.extract_form(h2h_raw, home_id)[:5]
            h2h_form_away = pred.extract_form(h2h_raw, away_id)[:5]

            prediction = se.scorpred_predict(
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
                opp_strengths=_build_opp_strengths(standings_list),
            )
        except Exception as exc:
            app.logger.warning(
                "Upcoming fixture prediction failed for %s vs %s: %s",
                fixture.get("fixture", {}).get("id"),
                exc,
            )
            prediction = se.scorpred_predict(
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

    return fixtures_with_pred, load_error, data_source, ""


def _require_teams():
    if "team_a_id" not in session:
        return None, None
    return (
        {"id": session["team_a_id"], "name": session["team_a_name"], "logo": session["team_a_logo"]},
        {"id": session["team_b_id"], "name": session["team_b_name"], "logo": session["team_b_logo"]},
    )


def _store_selected_teams(team_a: dict, team_b: dict, fixture_context: dict | None = None) -> None:
    session["team_a_id"] = int(team_a["id"])
    session["team_a_name"] = team_a.get("name", "")
    session["team_a_logo"] = team_a.get("logo", "")
    session["team_b_id"] = int(team_b["id"])
    session["team_b_name"] = team_b.get("name", "")
    session["team_b_logo"] = team_b.get("logo", "")

    if fixture_context:
        fixture_context["home_name"] = fixture_context["home_name"] or team_a.get("name", "")
        fixture_context["home_logo"] = fixture_context["home_logo"] or team_a.get("logo", "")
        fixture_context["away_name"] = fixture_context["away_name"] or team_b.get("name", "")
        fixture_context["away_logo"] = fixture_context["away_logo"] or team_b.get("logo", "")
        session["selected_fixture"] = fixture_context
    else:
        session.pop("selected_fixture", None)


def _team_form_payload(team_id: int) -> dict:
    fixtures = ac.get_team_fixtures(team_id, LEAGUE, SEASON, last=20)
    fixtures = pred.filter_recent_completed_fixtures(fixtures, current_season=SEASON)
    form = pred.extract_form(fixtures, team_id)[:5]
    return {"form_string": "".join(item.get("result", "") for item in form), "rows": form}


def _fallback_chat_reply(message: str) -> str:
    lower = (message or "").strip().lower()
    team_a, team_b = _require_teams()
    matchup = f"{team_a['name']} vs {team_b['name']}" if team_a and team_b else "your selected matchup"

    if "props" in lower:
        return f"Use the Props page to generate player lines for {matchup}. Pick a player, choose markets, and the app will build a bet slip from live stats."
    if "prediction" in lower or "winner" in lower:
        return f"The Prediction page uses the Scorpred Engine — a weighted model combining form, H2H, injuries, venue advantage, and opponent strength — to predict {matchup}."
    if "player" in lower:
        return "The Player page compares squad members side by side and can generate prop ideas from their season profile and opponent context."
    if "nba" in lower:
        return "The NBA section has its own home, matchup, player, prediction, and standings views under /nba."
    return "Ask about matchup analysis, player props, prediction logic, injuries, or where to find a specific football or NBA view."


def _chat_reply(message: str, history: list[dict] | None = None) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or anthropic is None:
        return _fallback_chat_reply(message)

    system_prompt = (
        "You are the ScorPred assistant — a helpful AI built into a football and NBA prediction app. "
        "You help users navigate the app, understand predictions, interpret stats, and find features. "
        "Key pages: Home (team selection + upcoming fixtures), Matchup (H2H, form, injuries), "
        "Players (squad comparison, prop ideas), Prediction (Poisson model, win probability), "
        "Props (player bet lines with 6-layer stat model), Fixtures (upcoming schedule), "
        "NBA (full NBA section at /nba with standings, matchup, players, predictions), "
        "World Cup (/worldcup). "
        "Be concise (2-3 sentences max), accurate, and friendly. "
        "Do not make up odds or guarantees. If unsure, say so."
    )

    messages = []
    for entry in (history or [])[-8:]:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=300,
            system=system_prompt,
            messages=messages,
        )
        text_blocks = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", "") == "text"
        ]
        reply = " ".join(text_blocks).strip()
        return reply or _fallback_chat_reply(message)
    except Exception as exc:
        app.logger.warning("Claude chat API error: %s", exc)
        return _fallback_chat_reply(message)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("home.html", **_page_context())


@app.route("/soccer", methods=["GET"])
def soccer():
    _set_data_refresh()
    load_error = None
    teams = []
    upcoming_fixtures = []
    fixtures_error = None
    fixtures_source = _football_data_source()

    try:
        teams = ac.get_teams(LEAGUE, SEASON)
    except Exception as exc:
        load_error = str(exc)
        app.logger.error("Failed to fetch teams: %s", exc)

    try:
        upcoming_fixtures, fixtures_error, fixtures_source, _ = _load_upcoming_fixtures(next_n=8)
    except Exception as exc:
        fixtures_error = str(exc)
        app.logger.error("Failed to fetch upcoming fixtures: %s", exc)

    return render_template(
        "soccer.html",
        **_page_context(
            data_source=fixtures_source,
            teams=teams or [],
            load_error=load_error,
            upcoming_fixtures=upcoming_fixtures or [],
            fixtures_error=fixtures_error,
            fixtures_source=fixtures_source,
            selected_fixture=_selected_fixture(),
        ),
    )


@app.route("/fixtures", methods=["GET"])
def fixtures():
    """Legacy fixtures page route (kept for backwards compatibility)."""
    _set_data_refresh()
    selected_slug = (request.args.get("espn_slug") or "").strip()
    fixtures_data: list[dict] = []
    load_error = None
    data_source = _football_data_source()

    if selected_slug:
        try:
            fixtures_data = ac.get_espn_fixtures(selected_slug, next_n=20)
            data_source = "espn"
        except Exception as exc:
            load_error = str(exc)
            app.logger.error("Failed to fetch ESPN fixtures (%s): %s", selected_slug, exc)
            fixtures_data = []
    else:
        fixtures_data, load_error, data_source, _ = _load_upcoming_fixtures(next_n=20)

    return render_template(
        "fixtures.html",
        **_page_context(
            fixtures=fixtures_data or [],
            load_error=load_error,
            data_source=data_source,
            espn_slug=selected_slug,
        ),
    )


@app.route("/select", methods=["GET", "POST"])
@app.route("/select-game", methods=["GET", "POST"])
@app.route("/matchup", methods=["POST"])
def select_game():
    _set_data_refresh()
    a_id_raw = (request.form.get("team_a") or request.args.get("team_a") or "").strip()
    b_id_raw = (request.form.get("team_b") or request.args.get("team_b") or "").strip()
    fixture_context = _fixture_context_from_form()
    source = (fixture_context or {}).get("data_source", "configured")

    if not a_id_raw or not b_id_raw or a_id_raw == b_id_raw:
        return redirect(url_for("index"))

    try:
        teams = ac.get_teams(LEAGUE, SEASON)
    except Exception as exc:
        app.logger.error("Failed to fetch provider teams during selection: %s", exc)
        teams = []

    if not teams:
        return _critical_error("Team data is unavailable, so the matchup could not be prepared.")

    team_map = {
        str((entry.get("team") or entry).get("id")): (entry.get("team") or entry)
        for entry in teams
        if (entry.get("team") or entry).get("id")
    }
    team_a = team_map.get(a_id_raw)
    team_b = team_map.get(b_id_raw)

    if (not team_a or not team_b) and source == "espn" and teams:
        team_a = _resolve_provider_team_by_name(request.form.get("team_a_name", ""), teams)
        team_b = _resolve_provider_team_by_name(request.form.get("team_b_name", ""), teams)

    if not team_a or not team_b:
        return render_template(
            "error.html",
            msg=(
                "This fixture could not be matched to the configured football data "
                "provider, so the full analysis could not be loaded."
            ),
            **_page_context(),
        )

    _store_selected_teams(team_a, team_b, fixture_context)
    return redirect(url_for("matchup"))


@app.route("/matchup", methods=["GET"])
def matchup():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    id_a, id_b = team_a["id"], team_b["id"]
    selected_fixture = _selected_fixture()

    h2h_raw = []
    fixtures_a = []
    fixtures_b = []
    injuries_a_raw = []
    injuries_b_raw = []

    try:
        h2h_raw = ac.get_h2h(id_a, id_b, last=20)
    except Exception as exc:
        app.logger.error("H2H fetch error: %s", exc)

    try:
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Team A fixtures fetch error: %s", exc)

    try:
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Team B fixtures fetch error: %s", exc)

    h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)
    fixtures_a = pred.filter_recent_completed_fixtures(fixtures_a, current_season=SEASON)
    fixtures_b = pred.filter_recent_completed_fixtures(fixtures_b, current_season=SEASON)

    try:
        injuries_a_raw = ac.get_injuries(LEAGUE, SEASON, id_a)
    except Exception as exc:
        app.logger.error("Team A injuries fetch error: %s", exc)

    try:
        injuries_b_raw = ac.get_injuries(LEAGUE, SEASON, id_b)
    except Exception as exc:
        app.logger.error("Team B injuries fetch error: %s", exc)

    h2h_enriched = []
    for fixture in h2h_raw[:5]:
        try:
            h2h_enriched.append(ac.enrich_fixture(fixture))
        except Exception:
            h2h_enriched.append({**fixture, "events": [], "stats": []})

    form_a = pred.extract_form(fixtures_a, id_a)[:5]
    form_b = pred.extract_form(fixtures_b, id_b)[:5]
    split_a = pred.home_away_split(form_a)
    split_b = pred.home_away_split(form_b)
    h2h_rec = pred.h2h_record(h2h_raw, id_a, id_b)
    injuries_a = _display_injuries(injuries_a_raw)
    injuries_b = _display_injuries(injuries_b_raw)

    def _avg(rows: list[dict], key: str) -> float:
        return round(sum(float(row.get(key, 0) or 0) for row in rows) / len(rows), 2) if rows else 0.0

    stats_compare = [
        {"label": "Goals scored", "a": _avg(form_a, "goals_for"), "b": _avg(form_b, "goals_for")},
        {"label": "Goals conceded", "a": _avg(form_a, "goals_against"), "b": _avg(form_b, "goals_against")},
        {"label": "Shots", "a": _avg(form_a, "shots"), "b": _avg(form_b, "shots")},
        {"label": "Shots on target", "a": _avg(form_a, "shots_on_target"), "b": _avg(form_b, "shots_on_target")},
        {"label": "Possession", "a": _avg(form_a, "possession"), "b": _avg(form_b, "possession")},
        {"label": "Corners", "a": _avg(form_a, "corners"), "b": _avg(form_b, "corners")},
    ]

    standings = []
    try:
        standings = ac.get_standings(LEAGUE, SEASON)
    except Exception:
        standings = []

    opp_strengths = _build_opp_strengths(standings)

    prediction = se.scorpred_predict(
        form_a=form_a,
        form_b=form_b,
        h2h_form_a=pred.extract_form(h2h_raw, id_a)[:5],
        h2h_form_b=pred.extract_form(h2h_raw, id_b)[:5],
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        team_a_is_home=True,
        team_a_name=team_a["name"],
        team_b_name=team_b["name"],
        sport="soccer",
        opp_strengths=opp_strengths,
    )

    return render_template(
        "matchup.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            h2h=h2h_enriched,
            form_a=form_a,
            form_b=form_b,
            split_a=split_a,
            split_b=split_b,
            h2h_rec=h2h_rec,
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            stats_compare=stats_compare,
            prediction=prediction,
            scorpred=prediction,
        ),
    )


@app.route("/prediction", methods=["GET"])
def prediction():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    id_a, id_b = team_a["id"], team_b["id"]

    try:
        fixtures_a = pred.filter_recent_completed_fixtures(
            ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20),
            current_season=SEASON,
        )
    except Exception:
        fixtures_a = []

    try:
        fixtures_b = pred.filter_recent_completed_fixtures(
            ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20),
            current_season=SEASON,
        )
    except Exception:
        fixtures_b = []

    try:
        h2h_raw = pred.filter_recent_completed_fixtures(
            ac.get_h2h(id_a, id_b, last=20),
            current_season=SEASON,
            seasons_back=5,
        )
    except Exception:
        h2h_raw = []

    try:
        injuries_a = _display_injuries(ac.get_injuries(LEAGUE, SEASON, id_a))
    except Exception:
        injuries_a = []

    try:
        injuries_b = _display_injuries(ac.get_injuries(LEAGUE, SEASON, id_b))
    except Exception:
        injuries_b = []

    try:
        standings = ac.get_standings(LEAGUE, SEASON)
    except Exception:
        standings = []

    result = se.scorpred_predict(
        form_a=pred.extract_form(fixtures_a, id_a)[:5],
        form_b=pred.extract_form(fixtures_b, id_b)[:5],
        h2h_form_a=pred.extract_form(h2h_raw, id_a)[:5],
        h2h_form_b=pred.extract_form(h2h_raw, id_b)[:5],
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        team_a_is_home=True,
        team_a_name=team_a["name"],
        team_b_name=team_b["name"],
        sport="soccer",
        opp_strengths=_build_opp_strengths(standings),
    )

    return render_template(
        "prediction.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            prediction=result,
            scorpred=result,
            selected_fixture=_selected_fixture(),
        ),
    )


@app.route("/players", methods=["GET"])
def players():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    squad_a = []
    squad_b = []

    try:
        squad_a = ac.get_players(team_a["id"], SEASON)
    except Exception as exc:
        app.logger.warning("Players fetch failed for %s: %s", team_a["name"], exc)

    try:
        squad_b = ac.get_players(team_b["id"], SEASON)
    except Exception as exc:
        app.logger.warning("Players fetch failed for %s: %s", team_b["name"], exc)

    return render_template(
        "player.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            squad_a=squad_a or [],
            squad_b=squad_b or [],
            selected_fixture=_selected_fixture(),
        ),
    )


@app.route("/props", methods=["GET"])
def props():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    squad_a = []
    squad_b = []
    players = []

    try:
        squad_a = ac.get_players(team_a["id"], SEASON)
    except Exception as exc:
        app.logger.warning("Props squad fetch failed for %s: %s", team_a["name"], exc)

    try:
        squad_b = ac.get_players(team_b["id"], SEASON)
    except Exception as exc:
        app.logger.warning("Props squad fetch failed for %s: %s", team_b["name"], exc)

    for team_side, squad, opponent in (
        ("home", squad_a, team_b),
        ("away", squad_b, team_a),
    ):
        for item in squad or []:
            player = item.get("player") or item
            if not isinstance(player, dict):
                continue
            pid = player.get("id")
            if not pid:
                continue
            players.append(
                {
                    "id": pid,
                    "name": player.get("name", "Unknown Player"),
                    "firstname": player.get("firstname", ""),
                    "lastname": player.get("lastname", ""),
                    "age": player.get("age"),
                    "photo": player.get("photo", ""),
                    "position": (
                        (item.get("statistics") or [{}])[0].get("games", {}).get("position", "")
                        if isinstance(item, dict)
                        else ""
                    ),
                    "team_id": team_a["id"] if team_side == "home" else team_b["id"],
                    "team_name": team_a["name"] if team_side == "home" else team_b["name"],
                    "opponent_id": opponent["id"],
                    "opponent_name": opponent["name"],
                    "is_home": team_side == "home",
                }
            )

    players = sorted(players, key=lambda p: p["name"])
    markets = [
        {"key": "goals", "label": "Goals"},
        {"key": "assists", "label": "Assists"},
        {"key": "shots", "label": "Shots"},
        {"key": "shots_on_target", "label": "Shots on Target"},
        {"key": "key_passes", "label": "Key Passes"},
        {"key": "minutes", "label": "Minutes"},
    ]

    return render_template(
        "props.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            players=players,
            markets=markets,
            selected_fixture=_selected_fixture(),
            supported_leagues=_football_supported_leagues(),
            current_season=SEASON,
            current_league=LEAGUE,
        ),
    )


# ── Props Bet Builder ─────────────────────────────────────────────────────────

@app.route("/props/generate", methods=["GET", "POST"])
def props_generate():
    _set_data_refresh()
    payload = request.get_json(silent=True) or request.values

    player_id = int(payload.get("player_id", 0) or 0)
    player_name = payload.get("player_name", "Unknown Player")
    player_team_id = int(payload.get("player_team_id", 0) or 0)
    opponent_id = int(payload.get("opponent_id", 0) or 0)
    opponent_name = payload.get("opponent_name", "Opponent")
    is_home_str = str(payload.get("is_home", "true")).lower()
    markets_str = str(payload.get("markets", "goals,assists,shots_on_target,key_passes"))
    season = int(payload.get("season", SEASON) or SEASON)
    league = int(payload.get("league", LEAGUE) or LEAGUE)
    player_position = payload.get("player_position", "")
    include_all_comps = str(payload.get("include_all_comps", "false")).lower() in ("true", "1", "yes", "on")
    league_ids_raw = str(payload.get("league_ids", ""))
    league_ids = [int(value) for value in league_ids_raw.split(",") if value.strip().isdigit()]

    if not player_id or not player_team_id or not opponent_id:
        return jsonify({"error": "Required: player_id, player_team_id, opponent_id"}), 400

    is_home = is_home_str not in ("false", "0", "no")
    markets = [m.strip() for m in markets_str.split(",") if m.strip()]

    try:
        result = pe.generate_props(
            sport="soccer",
            player_id=player_id,
            player_name=player_name,
            player_team_id=player_team_id,
            opponent_team_id=opponent_id,
            opponent_name=opponent_name,
            is_home=is_home,
            markets=markets,
            player_position=player_position,
            season=season,
            league=league,
            include_all_comps=include_all_comps,
            league_ids=league_ids or None,
        )
        result["data_source"] = _football_data_source()
        result["last_updated"] = _now_stamp()
        return jsonify(result)
    except Exception as exc:
        app.logger.error("Props generation failed: %s", exc)
        return jsonify(
            {
                "error": str(exc),
                "data_source": _football_data_source(),
                "last_updated": _now_stamp(),
            }
        ), 500


@app.route("/chat", methods=["POST"])
def chat():
    message = (request.get_json(silent=True) or request.form or {}).get("message", "")
    message = str(message).strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    history = session.get("chat_history", [])[-8:]
    reply = _chat_reply(message, history=history)
    history.extend(
        [
            {"role": "user", "content": message, "timestamp": _now_stamp()},
            {"role": "assistant", "content": reply, "timestamp": _now_stamp()},
        ]
    )
    session["chat_history"] = history[-10:]
    return jsonify({"reply": reply, "history": session["chat_history"], "last_updated": _now_stamp()})


@app.route("/chat/clear", methods=["POST"])
def chat_clear():
    session.pop("chat_history", None)
    return jsonify({"status": "cleared", "last_updated": _now_stamp()})


@app.route("/api/football/leagues", methods=["GET"])
def api_football_leagues():
    return jsonify({"leagues": _football_supported_leagues(), "season": SEASON})


@app.route("/api/football/teams", methods=["GET"])
def api_football_teams():
    league_id = int(request.args.get("league", LEAGUE) or LEAGUE)
    try:
        teams = ac.get_teams(league_id, SEASON)
    except Exception as exc:
        app.logger.error("api_football_teams failed: %s", exc)
        return jsonify({"error": "Unable to load teams", "league": league_id, "season": SEASON}), 503
    return jsonify({"teams": teams or [], "league": league_id, "season": SEASON})


@app.route("/api/football/squad", methods=["GET"])
def api_football_squad():
    team_id = int(request.args.get("team_id", 0) or 0)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    try:
        squad = ac.get_squad(team_id)
    except Exception as exc:
        app.logger.error("api_football_squad failed for team_id=%s: %s", team_id, exc)
        return jsonify({"error": "Unable to load squad", "team_id": team_id}), 503
    return jsonify({"team_id": team_id, "squad": squad or []})


@app.route("/api/player-stats", methods=["GET"])
def api_player_stats():
    player_id = int(request.args.get("player_id", 0) or 0)
    if not player_id:
        return jsonify({"error": "player_id is required"}), 400
    season = int(request.args.get("season", SEASON) or SEASON)
    league = int(request.args.get("league", LEAGUE) or LEAGUE)
    try:
        stats = ac.get_player_stats(player_id, season=season, league=league)
    except Exception as exc:
        app.logger.error(
            "api_player_stats failed for player_id=%s season=%s league=%s: %s",
            player_id,
            season,
            league,
            exc,
        )
        return jsonify({"error": "Unable to load player stats", "player_id": player_id}), 503
    return jsonify({"player_id": player_id, "stats": stats or []})


@app.route("/today-soccer-predictions", methods=["GET"])
def today_soccer_predictions():
    """Show soccer predictions for today's fixtures or next available fixtures."""
    _set_data_refresh()
    load_error = None
    data_source = _football_data_source()
    fixtures_with_pred, load_error, data_source, _ = _load_upcoming_fixtures(next_n=20)

    # Sort by confidence
    def _confidence_rank(item):
        pred = item.get("prediction", {})
        best_pick = pred.get("best_pick", {})
        conf = best_pick.get("confidence", "Low")
        conf_map = {"High": 0, "Medium": 1, "Low": 2}
        prob_gap = abs(
            pred.get("win_probabilities", {}).get("a", 0.5)
            - pred.get("win_probabilities", {}).get("b", 0.5)
        )
        return (conf_map.get(conf, 3), -prob_gap)

    fixtures_with_pred.sort(key=_confidence_rank)

    # Prepare predictions for template
    predictions = []
    for fixture in fixtures_with_pred:
        try:
            teams_block = fixture.get("teams", {})
            home_team = teams_block.get("home", {})
            away_team = teams_block.get("away", {})
            fixture_block = fixture.get("fixture", {})
            league_block = fixture.get("league", {})
            prediction = fixture.get("prediction", {})
            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})

            predictions.append({
                "fixture": fixture,
                "home_team": home_team,
                "away_team": away_team,
                "league": league_block,
                "predicted_winner": best_pick.get("prediction", "—"),
                "confidence": best_pick.get("confidence", "Low"),
                "prob_home": probs.get("a", 50),
                "prob_draw": probs.get("draw", 0),
                "prob_away": probs.get("b", 50),
                "reasoning": best_pick.get("reasoning", ""),
            })
        except Exception as e:
            app.logger.warning("Error preparing fixture prediction: %s", e)
            continue

    return render_template(
        "today_predictions.html",
        **_page_context(
            predictions=predictions,
            total_fixtures=len(fixtures_with_pred),
            total_predictions=len(predictions),
            load_error=load_error,
            data_source=data_source,
        ),
    )


@app.route("/top-picks-today", methods=["GET"])
def top_picks_today():
    """Show high-confidence picks from today's soccer and NBA predictions."""
    _set_data_refresh()
    
    # Load soccer fixtures
    soccer_predictions, _, _, _ = _load_upcoming_fixtures(next_n=20)
    soccer_picks = []
    for fixture in soccer_predictions:
        try:
            teams_block = fixture.get("teams", {})
            home_team = teams_block.get("home", {})
            away_team = teams_block.get("away", {})
            prediction = fixture.get("prediction", {})
            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})
            
            if best_pick.get("confidence") == "High":
                soccer_picks.append({
                    "fixture": fixture,
                    "home_team": home_team,
                    "away_team": away_team,
                    "predicted_winner": best_pick.get("prediction", "—"),
                    "confidence": "High",
                    "prob_home": probs.get("a", 50),
                    "prob_draw": probs.get("draw", 0),
                    "prob_away": probs.get("b", 50),
                    "pick_type": "match_winner" if best_pick.get("prediction") != "Draw" else "draw",
                    "reasoning": best_pick.get("reasoning", ""),
                })
        except Exception as e:
            app.logger.debug("Error preparing soccer top pick: %s", e)
            continue
    
    # Load NBA predictions from tracker
    nba_picks = []
    try:
        recent = mt.get_recent_predictions(limit=50)
        from datetime import date, timedelta
        today_str = date.today().strftime("%Y-%m-%d")
        nba_records = [
            p for p in recent
            if p.get("sport") == "nba"
            and p.get("date", "") == today_str
            and p.get("is_correct") is None
        ]
        for record in nba_records[:10]:
            if record.get("best_pick", {}).get("confidence") == "High":
                nba_picks.append(record)
    except Exception as e:
        app.logger.debug("Error loading NBA picks: %s", e)
    
    return render_template(
        "top_picks_today.html",
        **_page_context(
            soccer_picks=soccer_picks[:10],
            nba_picks=nba_picks[:10],
        ),
    )


@app.route("/model-performance")
def model_performance():
    try:
        sport_filter = request.args.get("sport", "").lower()
        metrics = mt.get_summary_metrics()
        completed_predictions = mt.get_completed_predictions()
        pending_predictions = mt.get_pending_predictions()

        if sport_filter in ["soccer", "nba"]:
            completed_predictions = [
                p for p in completed_predictions if p.get("sport", "").lower() == sport_filter
            ]

        metrics.setdefault("finalized_predictions", 0)
        metrics.setdefault("by_confidence", {})
        metrics.setdefault("by_sport", {})
        metrics.setdefault("recent_predictions", [])
    except Exception as exc:
        app.logger.error("model_performance: get_summary_metrics failed — %s", exc, exc_info=True)
        metrics = dict(_EMPTY_METRICS)
        completed_predictions = []
        pending_predictions = []

    return render_template(
        "model_performance.html",
        **_page_context(
            metrics=metrics,
            completed_predictions=completed_predictions,
            pending_predictions=pending_predictions,
            sport_filter=sport_filter,
        ),
    )


@app.route("/update-prediction-results", methods=["GET", "POST"])
def update_prediction_results():
    summary = ru.get_update_summary()
    update_stats = None

    if request.method == "POST":
        update_stats = ru.update_pending_predictions()
        metrics = mt.get_summary_metrics()
    else:
        metrics = mt.get_summary_metrics()

    return render_template(
        "update_results.html",
        **_page_context(
            summary=summary,
            update_stats=update_stats,
            metrics=metrics,
        ),
    )


@app.route("/worldcup", methods=["GET", "POST"])
def worldcup():
    _set_data_refresh()
    teams = sorted(pred.WC_TEAMS.keys())
    result = None
    team_a = request.form.get("team_a", "")
    team_b = request.form.get("team_b", "")
    wc_error = None

    wc_fixtures = []
    for slug in ("FIFA.WC.2026", "FIFA.WC", "FIFA.WWQ.CONMEBOL"):
        try:
            wc_fixtures = ac.get_espn_fixtures(slug, next_n=16)
            if wc_fixtures:
                break
        except Exception:
            continue

    if request.method == "POST" and team_a and team_b:
        if team_a == team_b:
            wc_error = "Please select two different teams."
        else:
            result = pred.wc_predict(team_a, team_b)
            if result is None:
                wc_error = "Unknown team name — pick from the list."

    return render_template(
        "worldcup.html",
        **_page_context(
            teams=teams,
            team_a=team_a,
            team_b=team_b,
            result=result or {},
            wc_error=wc_error,
            wc_fixtures=wc_fixtures,
        ),
    )


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "app": "ScorPred",
            "data_source": _football_data_source(),
            "timestamp": _now_stamp(),
        }
    )


if __name__ == "__main__":
    debug = str(os.getenv("FLASK_DEBUG", "0")).strip().lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("PORT", "5001"))
    app.run(debug=debug, port=port)
