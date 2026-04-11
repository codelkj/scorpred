"""Flask application for the ScorPred football and NBA predictor."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import api_client as ac
import api_client as football_api
import predictor as pred
import props_engine as pe
import scorpred_engine as se
import model_tracker as mt
import result_updater as ru
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

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "scorpred-dev-secret")

# ── Blueprints ─────────────────────────────────────────────────────────────────
app.register_blueprint(nba_bp)

LEAGUE = DEFAULT_LEAGUE_ID
SEASON = CURRENT_SEASON


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
    """Delegate to scorpred_engine — builds normalised_name → strength (0-10)."""
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
        prediction = None
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
            app.logger.warning("Upcoming fixture prediction failed for %s vs %s: %s", fixture.get("fixture", {}).get("id"), exc)
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
    """Return (team_a, team_b) session dicts, or None if not set."""
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

    # Build messages list from history + current message
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
        text_blocks = [block.text for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"]
        reply = " ".join(text_blocks).strip()
        return reply or _fallback_chat_reply(message)
    except Exception as exc:
        app.logger.warning("Claude chat API error: %s", exc)
        return _fallback_chat_reply(message)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
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
        "index.html",
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
    selected_fixture = _selected_fixture()

    id_a, id_b = team_a["id"], team_b["id"]
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

    if not h2h_raw and not fixtures_a and not fixtures_b:
        app.logger.warning("Matchup has no historical source data; using fallback neutral values for %s vs %s", team_a["name"], team_b["name"])

    h2h_enriched = []
    for f in h2h_raw[:5]:
        try:
            h2h_enriched.append(ac.enrich_fixture(f))
        except Exception:
            h2h_enriched.append({**f, "events": [], "stats": []})

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
        {"label": "Goals scored", "a": _avg(form_a, "gf"), "b": _avg(form_b, "gf")},
        {"label": "Goals conceded", "a": _avg(form_a, "ga"), "b": _avg(form_b, "ga")},
        {"label": "Wins in last 5", "a": sum(1 for row in form_a if row.get("result") == "W"), "b": sum(1 for row in form_b if row.get("result") == "W")},
        {"label": "Clean sheets", "a": sum(1 for row in form_a if row.get("cs")), "b": sum(1 for row in form_b if row.get("cs"))},
    ]

    # ── Scorpred Engine ────────────────────────────────────────────────────────
    # H2H form from each team's perspective for the Scorpred model
    h2h_form_a = pred.extract_form(h2h_raw, id_a)[:10]
    h2h_form_b = pred.extract_form(h2h_raw, id_b)[:10]

    # Standings → opponent strength lookup for quality-of-schedule adjustment
    standings_for_opp = []
    try:
        standings_for_opp = ac.get_standings(LEAGUE, SEASON)
    except Exception:
        pass
    opp_strengths = _build_opp_strengths(standings_for_opp)

    scorpred = se.scorpred_predict(
        form_a=form_a,
        form_b=form_b,
        h2h_form_a=h2h_form_a,
        h2h_form_b=h2h_form_b,
        injuries_a=injuries_a_raw,
        injuries_b=injuries_b_raw,
        team_a_is_home=True,
        team_a_name=team_a["name"],
        team_b_name=team_b["name"],
        sport="soccer",
        opp_strengths=opp_strengths,
    )

    # ── Key threats (danger men) ────────────────────────────────────────────────
    squad_a, squad_b = [], []
    try:
        squad_a = ac.get_squad(id_a, SEASON)
    except Exception:
        pass
    try:
        squad_b = ac.get_squad(id_b, SEASON)
    except Exception:
        pass
    threats_a = _build_key_threats(squad_a, injuries_a_raw, fixtures_a, id_a)
    threats_b = _build_key_threats(squad_b, injuries_b_raw, fixtures_b, id_b)

    # Save prediction to tracker
    try:
        best_pick = scorpred.get("best_pick", {})
        mt.save_prediction(
            sport="soccer",
            team_a=team_a["name"],
            team_b=team_b["name"],
            predicted_winner=best_pick.get("team", ""),
            win_probs=scorpred.get("win_probabilities", {}),
            confidence=best_pick.get("confidence", "Low"),
        )
    except Exception:
        pass

    return render_template(
        "matchup.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            h2h=h2h_enriched,
            h2h_rec=h2h_rec,
            form_a=form_a,
            form_b=form_b,
            split_a=split_a,
            split_b=split_b,
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            stats_compare=stats_compare,
            scorpred=scorpred,
            threats_a=threats_a,
            threats_b=threats_b,
        ),
    )


def _build_key_threats(squad: list, injuries: list, fixtures: list, team_id: int) -> list[dict]:
    """Return up to 5 key threat players ranked by position + form."""
    injured_ids = {
        (inj.get("player") or {}).get("id")
        for inj in injuries
        if (inj.get("player") or {}).get("id")
    }
    fixtures = pred.filter_recent_completed_fixtures(fixtures, current_season=SEASON)
    form = pred.extract_form(fixtures, team_id)
    avg_gf = pred.avg_goals(form, scored=True) if form else 1.2
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
    for p in squad:
        player_obj = p.get("player") or p
        pid = player_obj.get("id")
        if not pid:
            continue
        position = player_obj.get("position") or p.get("position") or "Unknown"
        is_injured = pid in injured_ids
        pos_rank = position_order.get(position, 4)

        # Score: attackers first, healthy players first, position boost
        pos_boost = 1.4 if position == "Attacker" else 1.1 if position == "Midfielder" else 0.7
        health_penalty = 0.5 if is_injured else 1.0
        score = pos_boost * health_penalty * team_lambda

        candidates.append({
            "id": pid,
            "name": player_obj.get("name") or "",
            "photo": player_obj.get("photo", ""),
            "position": position,
            "pos_rank": pos_rank,
            "threat_label": threat_labels.get(position, "Key Player"),
            "contribution": contribution_map.get(position, "match impact"),
            "injured": is_injured,
            "score": score,
        })

    candidates.sort(key=lambda x: (-x["score"], x["pos_rank"]))
    return candidates[:5]


@app.route("/player")
def player():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))
    selected_fixture = _selected_fixture()
    id_a, id_b = team_a["id"], team_b["id"]

    squad_a, squad_b = [], []
    injuries_a_raw, injuries_b_raw = [], []
    fixtures_a, fixtures_b = [], []

    try:
        squad_a = ac.get_squad(id_a, SEASON)
    except Exception as exc:
        app.logger.error("Player squad A fetch error: %s", exc)
    try:
        squad_b = ac.get_squad(id_b, SEASON)
    except Exception as exc:
        app.logger.error("Player squad B fetch error: %s", exc)
    try:
        injuries_a_raw = ac.get_injuries(LEAGUE, SEASON, id_a)
    except Exception as exc:
        app.logger.error("Player injuries A fetch error: %s", exc)
    try:
        injuries_b_raw = ac.get_injuries(LEAGUE, SEASON, id_b)
    except Exception as exc:
        app.logger.error("Player injuries B fetch error: %s", exc)
    try:
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Player fixtures A fetch error: %s", exc)
    try:
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Player fixtures B fetch error: %s", exc)

    fixtures_a = pred.filter_recent_completed_fixtures(fixtures_a, current_season=SEASON)
    fixtures_b = pred.filter_recent_completed_fixtures(fixtures_b, current_season=SEASON)

    if not squad_a and not squad_b:
        return _critical_error("Player squad data is unavailable right now.")

    threats_a = _build_key_threats(squad_a, injuries_a_raw, fixtures_a, id_a)
    threats_b = _build_key_threats(squad_b, injuries_b_raw, fixtures_b, id_b)

    # Group full squads by position for the roster section
    def _group_by_position(squad):
        groups = {"Goalkeeper": [], "Defender": [], "Midfielder": [], "Attacker": []}
        for p in squad:
            player_obj = p.get("player") or p
            pos = player_obj.get("position") or p.get("position") or "Unknown"
            if pos in groups:
                groups[pos].append(player_obj)
            else:
                groups.setdefault("Unknown", []).append(player_obj)
        return groups

    return render_template(
        "player.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            threats_a=threats_a,
            threats_b=threats_b,
            squad_a=_group_by_position(squad_a),
            squad_b=_group_by_position(squad_b),
            injuries_a=_display_injuries(injuries_a_raw),
            injuries_b=_display_injuries(injuries_b_raw),
        ),
    )


@app.route("/player/analyze", methods=["POST"])
def player_analyze():
    _set_data_refresh()
    payload = request.get_json(silent=True) or request.form
    player_id = int(payload.get("player_id", 0) or 0)
    team_id = int(payload.get("team_id", 0) or 0)
    opponent_team_id = int(payload.get("opponent_team_id", 0) or 0)
    league_id = int(payload.get("league", LEAGUE) or LEAGUE)
    season = int(payload.get("season", SEASON) or SEASON)

    if not player_id:
        return jsonify({"error": "player_id is required"}), 400

    try:
        stats = ac.get_player_stats(player_id, league_id, season) or []
    except Exception as exc:
        app.logger.error("Player analysis stats fetch error: %s", exc)
        stats = []

    try:
        vs_team = ac.get_player_vs_team(player_id, team_id, opponent_team_id, seasons=[season, season - 1, season - 2]) if team_id and opponent_team_id else []
    except Exception as exc:
        app.logger.error("Player analysis vs-team fetch error: %s", exc)
        vs_team = []

    return jsonify(
        {
            "stats": stats,
            "vs_team": vs_team,
            "h2h_sample_warning": len(vs_team) < 3,
            "data_source": _football_data_source(),
            "last_updated": _now_stamp(),
        }
    )


@app.route("/api/player-stats")
def player_stats_api():
    _set_data_refresh()
    pid = request.args.get("id", type=int)
    league_id = request.args.get("league", default=LEAGUE, type=int)
    season = request.args.get("season", default=SEASON, type=int)
    if not pid:
        return jsonify({"error": "missing id"}), 400
    try:
        data = ac.get_player_stats(pid, league_id, season) or []
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 500


@app.route("/prediction")
def prediction():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))
    selected_fixture = _selected_fixture()

    id_a, id_b = team_a["id"], team_b["id"]
    h2h = []
    fixtures_a = []
    fixtures_b = []
    injuries_a = []
    injuries_b = []
    squad_a = []
    squad_b = []

    try:
        h2h = ac.get_h2h(id_a, id_b, last=20)
    except Exception as exc:
        app.logger.error("Prediction H2H fetch error: %s", exc)

    try:
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Prediction team A fixtures fetch error: %s", exc)

    try:
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20)
    except Exception as exc:
        app.logger.error("Prediction team B fixtures fetch error: %s", exc)

    h2h = pred.filter_recent_completed_fixtures(h2h, current_season=SEASON)
    fixtures_a = pred.filter_recent_completed_fixtures(fixtures_a, current_season=SEASON)
    fixtures_b = pred.filter_recent_completed_fixtures(fixtures_b, current_season=SEASON)

    try:
        injuries_a = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, id_a))
    except Exception as exc:
        app.logger.error("Prediction team A injuries fetch error: %s", exc)

    try:
        injuries_b = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, id_b))
    except Exception as exc:
        app.logger.error("Prediction team B injuries fetch error: %s", exc)

    try:
        squad_a = ac.get_squad(id_a)
    except Exception as exc:
        app.logger.error("Prediction squad A fetch error: %s", exc)

    try:
        squad_b = ac.get_squad(id_b)
    except Exception as exc:
        app.logger.error("Prediction squad B fetch error: %s", exc)

    if not fixtures_a and not fixtures_b and not h2h:
        app.logger.warning(
            "No historical data for %s vs %s — Scorpred will use neutral fallbacks",
            team_a["name"], team_b["name"],
        )

    # ── Unified Scorpred Engine Model (ONLY prediction source) ──────────────────
    # Extract form data from fixtures
    form_a = pred.extract_form(fixtures_a, id_a)[:5]
    form_b = pred.extract_form(fixtures_b, id_b)[:5]
    
    # H2H form from each team's perspective
    h2h_form_a = pred.extract_form(h2h, id_a)[:5]
    h2h_form_b = pred.extract_form(h2h, id_b)[:5]

    # Standings → opponent strength lookup for quality-of-schedule adjustment
    standings_for_opp = []
    try:
        standings_for_opp = ac.get_standings(LEAGUE, SEASON)
    except Exception:
        pass
    opp_strengths = _build_opp_strengths(standings_for_opp)

    # Single unified prediction from Scorpred Engine
    prediction = se.scorpred_predict(
        form_a=form_a,
        form_b=form_b,
        h2h_form_a=h2h_form_a,
        h2h_form_b=h2h_form_b,
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        team_a_is_home=True,
        team_a_name=team_a["name"],
        team_b_name=team_b["name"],
        sport="soccer",
        opp_strengths=opp_strengths,
    )

    # Track this prediction
    try:
        best_pick = prediction.get("best_pick", {})
        pred_winner = best_pick.get("team", "")
        probs = prediction.get("win_probabilities", {})
        conf = best_pick.get("confidence", "Medium")
        
        mt.save_prediction(
            sport="soccer",
            team_a=team_a["name"],
            team_b=team_b["name"],
            predicted_winner=pred_winner,
            win_probs=probs,
            confidence=conf,
        )
    except Exception:
        pass  # Silent fail if tracking fails

    return render_template(
        "prediction.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            prediction=prediction,
            scorpred=prediction,   # template uses 'scorpred' — same Scorpred object
        ),
    )


@app.route("/fixtures")
def fixtures():
    _set_data_refresh()
    fixtures_with_pred, load_error, data_source, espn_slug = _load_upcoming_fixtures(next_n=20)

    return render_template(
        "fixtures.html",
        **_page_context(
            data_source=data_source,
            fixtures=fixtures_with_pred,
            load_error=load_error,
            espn_slug=espn_slug,
        ),
    )


@app.route("/today-soccer-predictions")
def today_soccer_predictions():
    """
    Show upcoming soccer predictions (next ~36 h window, never strictly today-only).
    """
    _set_data_refresh()
    load_error = None
    upcoming_fixtures = []
    standings_list = []

    now_utc = datetime.utcnow()
    app.logger.info(
        "today_soccer_predictions: UTC=%s, league=%s",
        now_utc.strftime("%Y-%m-%d %H:%M"),
        LEAGUE,
    )

    try:
        upcoming_fixtures = ac.get_upcoming_fixtures(LEAGUE, SEASON, next_n=20)
        app.logger.info(
            "today_soccer_predictions: get_upcoming_fixtures returned %d fixtures",
            len(upcoming_fixtures),
        )
        for fx in upcoming_fixtures[:3]:  # log first few for debug
            fx_date = (fx.get("fixture") or {}).get("date", "unknown")
            fx_status = (fx.get("fixture") or {}).get("status", {}).get("short", "?")
            app.logger.debug(
                "today_soccer_predictions: fixture %s vs %s on %s [%s]",
                (fx.get("teams") or {}).get("home", {}).get("name", "?"),
                (fx.get("teams") or {}).get("away", {}).get("name", "?"),
                fx_date,
                fx_status,
            )
    except Exception as exc:
        app.logger.error("Upcoming fixtures fetch failed: %s", exc, exc_info=True)
        load_error = str(exc)
    
    try:
        standings_list = ac.get_standings(LEAGUE, SEASON)
    except Exception:
        standings_list = []
    
    # Build predictions for each fixture
    predictions_for_fixtures = []
    opp_strengths = _build_opp_strengths(standings_list)
    
    for fixture in upcoming_fixtures or []:
        try:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            home_name = fixture["teams"]["home"]["name"]
            away_name = fixture["teams"]["away"]["name"]
            
            # Fetch form, H2H, and injuries for prediction
            h2h_raw = []
            fixtures_home = []
            fixtures_away = []
            injuries_home = []
            injuries_away = []
            
            try:
                h2h_raw = ac.get_h2h(home_id, away_id, last=10)
            except Exception:
                pass
            
            try:
                fixtures_home = ac.get_team_fixtures(home_id, LEAGUE, SEASON, last=10)
            except Exception:
                pass
            
            try:
                fixtures_away = ac.get_team_fixtures(away_id, LEAGUE, SEASON, last=10)
            except Exception:
                pass
            
            try:
                injuries_home = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, home_id))
            except Exception:
                pass
            
            try:
                injuries_away = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, away_id))
            except Exception:
                pass
            
            # Filter to completed matches
            h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)
            fixtures_home = pred.filter_recent_completed_fixtures(fixtures_home, current_season=SEASON)
            fixtures_away = pred.filter_recent_completed_fixtures(fixtures_away, current_season=SEASON)
            
            # Extract form
            form_home = pred.extract_form(fixtures_home, home_id)[:5]
            form_away = pred.extract_form(fixtures_away, away_id)[:5]
            h2h_form_home = pred.extract_form(h2h_raw, home_id)[:5]
            h2h_form_away = pred.extract_form(h2h_raw, away_id)[:5]
            
            # Run Scorpred prediction
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
            
            # Extract key info for display
            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})
            
            # Add to predictions list with fixture info
            predictions_for_fixtures.append({
                "fixture": fixture,
                "home_team": fixture["teams"]["home"],
                "away_team": fixture["teams"]["away"],
                "prediction": prediction,
                "predicted_winner": best_pick.get("prediction", "—"),
                "confidence": best_pick.get("confidence", "Low"),
                "prob_home": probs.get("a", 33.3),
                "prob_draw": probs.get("draw", 33.4),
                "prob_away": probs.get("b", 33.3),
                "reasoning": best_pick.get("reasoning", ""),
                "score_gap": prediction.get("score_gap", 0),
            })
        except Exception as exc:
            app.logger.warning("Prediction for fixture %s failed: %s", fixture.get("fixture", {}).get("id"), exc)
            continue
    
    # Sort by confidence (High first) and score gap (larger gaps = more confident)
    conf_order = {"High": 0, "Medium": 1, "Low": 2}
    predictions_for_fixtures.sort(
        key=lambda x: (
            conf_order.get(x["confidence"], 3),
            -x["score_gap"],
        )
    )
    
    # ── Yesterday section: completed predictions from tracker ─────────────────
    from datetime import date, timedelta
    yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        recent = mt.get_recent_predictions(limit=50)
        yesterday_results = [
            p for p in recent
            if p.get("sport") == "soccer"
            and p.get("date", "") in (yesterday_str, today_str)
            and p.get("is_correct") is not None
        ]
    except Exception:
        yesterday_results = []

    return render_template(
        "today_predictions.html",
        **_page_context(
            sport="soccer",
            predictions=predictions_for_fixtures,
            total_fixtures=len(upcoming_fixtures),
            total_predictions=len(predictions_for_fixtures),
            load_error=load_error,
            yesterday_results=yesterday_results,
        ),
    )


_EMPTY_METRICS = {
    "total_predictions": 0,
    "finalized_predictions": 0,
    "overall_accuracy": None,
    "by_confidence": {},
    "by_sport": {},
    "recent_predictions": [],
}


@app.route("/model-performance")
def model_performance():
    """Display model accuracy metrics and recent predictions."""
    try:
        sport_filter = request.args.get('sport', '').lower()
        metrics = mt.get_summary_metrics()
        completed_predictions = mt.get_completed_predictions()
        pending_predictions = mt.get_pending_predictions()
        
        # Filter completed predictions by sport if specified
        if sport_filter in ['soccer', 'nba']:
            completed_predictions = [p for p in completed_predictions if p.get('sport', '').lower() == sport_filter]
        
        # Guarantee every key the template expects is present
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
    """
    Trigger automatic update of pending predictions with game results.
    
    GET: Shows a form with info about pending predictions
    POST: Runs the updater and shows the results
    """
    summary = ru.get_update_summary()
    update_stats = None
    
    if request.method == "POST":
        # Run the updater
        update_stats = ru.update_pending_predictions()
        # Recalculate metrics after update
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

    # Fetch upcoming WC fixtures from ESPN (best-effort)
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
            sport             = "soccer",
            player_id         = player_id,
            player_name       = player_name,
            player_team_id    = player_team_id,
            opponent_team_id  = opponent_id,
            opponent_name     = opponent_name,
            is_home           = is_home,
            markets           = markets,
            player_position   = player_position,
            season            = season,
            league            = league,
            include_all_comps = include_all_comps,
            league_ids        = league_ids or None,
        )
        result["data_source"] = _football_data_source()
        result["last_updated"] = _now_stamp()
        return jsonify(result)
    except Exception as exc:
        app.logger.error("Props generation failed: %s", exc)
        return jsonify({"error": str(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 500


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


@app.route("/top-picks-today")
def top_picks_today():
    """
    Show the strongest model-backed picks across soccer and NBA for today.
    Only displays high-confidence recommendations.
    """
    _set_data_refresh()
    load_error = None
    
    # ── Soccer Totals ───────────────────────────────────────────────────
    soccer_totals = []
    try:
        upcoming_fixtures = ac.get_upcoming_fixtures(LEAGUE, SEASON, next_n=20)
        standings_list = ac.get_standings(LEAGUE, SEASON)
        opp_strengths = _build_opp_strengths(standings_list)
        for fixture in upcoming_fixtures or []:
            try:
                home_id = fixture["teams"]["home"]["id"]
                away_id = fixture["teams"]["away"]["id"]
                home_name = fixture["teams"]["home"]["name"]
                away_name = fixture["teams"]["away"]["name"]
                
                # Fetch data (same as above)
                h2h_raw = ac.get_h2h(home_id, away_id, last=10)
                fixtures_home = ac.get_team_fixtures(home_id, LEAGUE, SEASON, last=10)
                fixtures_away = ac.get_team_fixtures(away_id, LEAGUE, SEASON, last=10)
                injuries_home = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, home_id))
                injuries_away = _clean_injuries(ac.get_injuries(LEAGUE, SEASON, away_id))
                
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
                    opp_strengths=opp_strengths,
                )
                
                best_pick = prediction.get("best_pick", {})
                confidence = best_pick.get("confidence", "Low")
                team_a_score = prediction.get("team_a_score", 0)
                team_b_score = prediction.get("team_b_score", 0)
                expected_total = team_a_score + team_b_score

                # Determine Over/Under pick based on expected total goals
                if expected_total > 2.5:
                    pick = "Over 2.5 Goals"
                    # Probability based on how much over 2.5
                    over_probability = min(95, 50 + (expected_total - 2.5) * 20)
                else:
                    pick = "Under 2.5 Goals"
                    # Probability based on how much under 2.5
                    over_probability = max(5, 50 - (2.5 - expected_total) * 20)

                # Adjust confidence based on prediction strength
                if abs(expected_total - 2.5) >= 1.0:
                    confidence = "High"
                elif abs(expected_total - 2.5) >= 0.5:
                    confidence = "Medium"
                else:
                    confidence = "Low"

                # Generate specific matchup-based note
                home_avg_goals = sum([1 if result in ['W', 'D'] else 0 for result in form_home]) / len(form_home) if form_home else 0
                away_avg_goals = sum([1 if result in ['W', 'D'] else 0 for result in form_away]) / len(form_away) if form_away else 0

                if expected_total > 3.5:
                    if team_a_score > team_b_score:
                        note = f"{home_name}'s strong home form and {away_name}'s defensive struggles suggest a high-scoring game."
                    else:
                        note = f"Both teams' recent attacking displays and {away_name}'s away goal concessions point to over 2.5 goals."
                elif expected_total > 3.0:
                    note = f"{home_name}'s scoring trend and {away_name}'s recent matches indicate this could go over 2.5."
                elif expected_total < 2.0:
                    note = f"{home_name} and {away_name} have combined for low-scoring games in recent fixtures."
                elif expected_total < 2.5:
                    if team_a_score < team_b_score:
                        note = f"{away_name}'s defensive solidity and {home_name}'s scoring drought suggest under 2.5 goals."
                    else:
                        note = f"Recent form shows {home_name} and {away_name} involved in low-scoring encounters."
                else:
                    if abs(team_a_score - team_b_score) < 0.3:
                        note = f"Balanced matchup between {home_name} and {away_name} with moderate goal expectations."
                    else:
                        note = f"{home_name if team_a_score > team_b_score else away_name}'s edge and recent trends make this total competitive."

                # Filter for strong picks: High confidence OR >60% probability
                if confidence == "High" or over_probability > 60:
                    soccer_totals.append({
                        "fixture": fixture,
                        "home_team": fixture["teams"]["home"],
                        "away_team": fixture["teams"]["away"],
                        "pick": pick,
                        "probability": round(over_probability),
                        "confidence": confidence,
                        "note": note,
                        "expected_total": round(expected_total, 1),
                    })

            except Exception as exc:
                app.logger.warning("Totals prediction failed for soccer fixture %s: %s", fixture.get("fixture", {}).get("id"), exc)
                continue

    except Exception as exc:
        app.logger.error("Failed to process soccer totals: %s", exc)

    # ── NBA Winners ────────────────────────────────────────────────────────
    
    # ── NBA Winners ────────────────────────────────────────────────────────
    nba_winners = []
    try:
        import nba_live_client as nc
        import nba_predictor as np_nba
        
        today_games = nc.get_today_games()
        if not today_games:
            today_games = nc.get_upcoming_games(next_n=12, days_ahead=2)
        
        team_map = {str(t["id"]): t for t in nc.get_teams()}
        
        # Build opponent strengths
        nba_opp_strengths = {}
        try:
            nba_standings = nc.get_standings()
            flat_standings = []
            if isinstance(nba_standings, dict):
                for conf_teams in nba_standings.values():
                    if isinstance(conf_teams, list):
                        flat_standings.extend(conf_teams)
            
            ranked = []
            for i, entry in enumerate(flat_standings):
                if isinstance(entry, dict):
                    team_info = entry.get("team") or entry
                    name = team_info.get("name") or team_info.get("nickname", "")
                    rank = entry.get("rank") or entry.get("conference", {}).get("rank") or (i + 1)
                    if name:
                        ranked.append({"team": {"name": name}, "rank": rank})
            
            nba_opp_strengths = se.build_opp_strengths_from_standings(ranked)
        except Exception:
            pass
        
        for game in today_games or []:
            try:
                if not isinstance(game, dict):
                    continue
                teams_block = game.get("teams") or {}
                home_raw = teams_block.get("home") or {}
                away_raw = teams_block.get("visitors") or {}
                
                home_id = str(home_raw.get("id") or "")
                away_id = str(away_raw.get("id") or "")
                
                if not home_id or not away_id:
                    continue
                
                home_team = team_map.get(home_id) or home_raw
                away_team = team_map.get(away_id) or away_raw
                
                # Fetch data
                h2h_raw = nc.get_h2h(home_id, away_id)
                form_home_raw = nc.get_team_recent_form(home_id)
                form_home = np_nba.extract_recent_form(form_home_raw, home_id, n=5)
                form_away_raw = nc.get_team_recent_form(away_id)
                form_away = np_nba.extract_recent_form(form_away_raw, away_id, n=5)
                injuries_home = nc.get_team_injuries(home_id)
                injuries_away = nc.get_team_injuries(away_id)
                
                h2h_form_home = np_nba.extract_recent_form(h2h_raw, home_id, n=5) if h2h_raw else []
                h2h_form_away = np_nba.extract_recent_form(h2h_raw, away_id, n=5) if h2h_raw else []
                
                prediction = se.scorpred_predict(
                    form_a=form_home,
                    form_b=form_away,
                    h2h_form_a=h2h_form_home,
                    h2h_form_b=h2h_form_away,
                    injuries_a=injuries_home,
                    injuries_b=injuries_away,
                    team_a_is_home=True,
                    team_a_name=home_team.get("nickname") or home_team.get("name") or "Home",
                    team_b_name=away_team.get("nickname") or away_team.get("name") or "Away",
                    sport="nba",
                    opp_strengths=nba_opp_strengths,
                )
                
                best_pick = prediction.get("best_pick", {})
                probs = prediction.get("win_probabilities", {})
                confidence = best_pick.get("confidence", "Low")
                prob_home = probs.get("a", 50)
                prob_away = probs.get("b", 50)
                
                # Filter for strong picks: High confidence OR >60% probability
                if confidence == "High" or prob_home > 60 or prob_away > 60:
                    predicted_winner = best_pick.get("prediction", "—")
                    winner_team = home_team.get("name") if predicted_winner == "Home" else away_team.get("name") if predicted_winner == "Away" else "—"
                    
                    nba_winners.append({
                        "game": game,
                        "home_team": home_team,
                        "away_team": away_team,
                        "predicted_winner": winner_team,
                        "win_probability": prob_home if predicted_winner == "Home" else prob_away,
                        "confidence": confidence,
                        "reasoning": best_pick.get("reasoning", ""),
                    })
                    
            except Exception as exc:
                app.logger.warning("Prediction failed for NBA game %s: %s", game.get("id"), exc)
                continue
                
    except Exception as exc:
        app.logger.error("Failed to fetch NBA data: %s", exc)
        if not load_error:
            load_error = str(exc)
    
    # Sort each section by confidence then probability
    conf_order = {"High": 0, "Medium": 1, "Low": 2}
    
    soccer_totals.sort(key=lambda x: (conf_order.get(x["confidence"], 3), -x["probability"]))
    nba_winners.sort(key=lambda x: (conf_order.get(x["confidence"], 3), -x["win_probability"]))
    
    return render_template(
        "top_picks_today.html",
        **_page_context(
            soccer_totals=soccer_totals,
            nba_winners=nba_winners,
            load_error=load_error,
        ),
    )


@app.route("/api/football/leagues")
def football_leagues_api():
    return jsonify(
        {
            "leagues": _football_supported_leagues(),
            "default_league_id": LEAGUE,
            "season": SEASON,
            "data_source": _football_data_source(),
            "last_updated": _now_stamp(),
        }
    )


@app.route("/api/football/teams")
def football_teams_api():
    _set_data_refresh()
    league_id = request.args.get("league", default=LEAGUE, type=int)
    season = request.args.get("season", default=SEASON, type=int)
    try:
        teams = football_api.get_teams(league_id, season)
    except Exception as exc:
        return jsonify({"teams": [], "league": LEAGUE_BY_ID.get(league_id, {}), "error": str(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200

    payload = []
    for entry in teams:
        team = entry.get("team") or entry or {}
        venue = entry.get("venue") or {}
        if not team.get("id"):
            continue
        payload.append({
            "id": team.get("id"),
            "name": team.get("name"),
            "logo": team.get("logo", ""),
            "country": team.get("country", ""),
            "league_id": league_id,
            "venue_name": venue.get("name", ""),
        })
    payload.sort(key=lambda item: item["name"])
    return jsonify({"teams": payload, "league": LEAGUE_BY_ID.get(league_id, {}), "data_source": _football_data_source(), "last_updated": _now_stamp()})


@app.route("/api/football/team-form")
def football_team_form_api():
    _set_data_refresh()
    team_id = request.args.get("team_id", type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    try:
        payload = _team_form_payload(team_id)
        payload["data_source"] = _football_data_source()
        payload["last_updated"] = _now_stamp()
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"error": str(exc), "form_string": "", "rows": [], "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200


@app.route("/api/football/squad")
def football_squad_api():
    _set_data_refresh()
    team_id = request.args.get("team_id", type=int)
    league_id = request.args.get("league", default=LEAGUE, type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    try:
        squad = football_api.get_squad(team_id, SEASON)
    except Exception as exc:
        return jsonify({"players": [], "league_id": league_id, "error": str(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200

    payload = []
    for entry in squad:
        player = entry.get("player") or entry
        position = (
            player.get("pos")
            or entry.get("position")
            or entry.get("pos")
            or ""
        )
        position_group = ac.normalize_position_group(position)
        payload.append({
            "id": player.get("id"),
            "name": player.get("name") or player.get("firstname") or "",
            "firstname": player.get("firstname", ""),
            "lastname": player.get("lastname", ""),
            "photo": player.get("photo", ""),
            "number": player.get("number"),
            "position": position,
            "position_group": position_group,
            "default_markets": ac.POSITION_DEFAULT_MARKETS.get(
                position_group,
                ac.POSITION_DEFAULT_MARKETS.get("", []),
            ),
        })
    payload = [p for p in payload if p.get("id")]
    payload.sort(key=lambda item: item["name"])
    return jsonify({"players": payload, "league_id": league_id, "data_source": _football_data_source(), "last_updated": _now_stamp()})


@app.route("/api/football/relevant-competitions")
def football_relevant_competitions_api():
    _set_data_refresh()
    player_id = request.args.get("player_id", type=int)
    team_id = request.args.get("team_id", type=int)
    primary_league = request.args.get("league", default=LEAGUE, type=int)
    season = request.args.get("season", default=SEASON, type=int)
    if not player_id or not team_id:
        return jsonify({"error": "player_id and team_id are required"}), 400

    try:
        league_ids = ac.relevant_competitions_for_player(
            player_id,
            team_id,
            primary_league,
            season,
        )
    except Exception as exc:
        return jsonify({"competitions": [], "league_ids": [], "error": str(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200
    competitions = []
    for league_id in league_ids:
        info = LEAGUE_BY_ID.get(league_id, {})
        competitions.append({
            "id": league_id,
            "name": info.get("name", f"League {league_id}"),
            "flag": info.get("flag", ""),
            "difficulty": info.get("difficulty", 1.0),
        })
    return jsonify({"competitions": competitions, "league_ids": league_ids, "data_source": _football_data_source(), "last_updated": _now_stamp()})


@app.route("/api/football/prefetch-competition")
def football_prefetch_competition_api():
    _set_data_refresh()
    player_id = request.args.get("player_id", type=int)
    team_id = request.args.get("team_id", type=int)
    league_id = request.args.get("league_id", type=int)
    season = request.args.get("season", default=SEASON, type=int)
    if not player_id or not team_id or not league_id:
        return jsonify({"error": "player_id, team_id, and league_id are required"}), 400

    try:
        payload = ac.prefetch_competition(player_id, team_id, league_id, season)
        payload["data_source"] = _football_data_source()
        payload["last_updated"] = _now_stamp()
        return jsonify(payload)
    except Exception as exc:
        return jsonify({
            "league_id": league_id,
            "league_name": (LEAGUE_BY_ID.get(league_id) or {}).get("name", f"League {league_id}"),
            "error": str(exc),
            "data_source": _football_data_source(),
            "last_updated": _now_stamp(),
        }), 200


@app.route("/props")
def props_page():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    squad_a = []
    squad_b = []
    if team_a:
        try:
            squad_a = ac.get_squad(team_a["id"], SEASON)
        except Exception as exc:
            app.logger.error("Props page squad A fetch error: %s", exc)
    if team_b:
        try:
            squad_b = ac.get_squad(team_b["id"], SEASON)
        except Exception as exc:
            app.logger.error("Props page squad B fetch error: %s", exc)

    return render_template(
        "props.html",
        **_page_context(
            team_a=team_a or {},
            team_b=team_b or {},
            squad_a=squad_a,
            squad_b=squad_b,
            sport="soccer",
            supported_leagues=_football_supported_leagues(),
            default_league_id=LEAGUE,
            football_markets=ac.get_market_catalog(),
            football_position_default_markets=ac.POSITION_DEFAULT_MARKETS,
            football_supported_league_ids=SUPPORTED_LEAGUE_IDS,
            current_season=SEASON,
            football_mock_mode=False,
            selected_fixture=_selected_fixture(),
        ),
    )


# ── Error page ────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", **_page_context(msg="Page not found.")), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error("Internal server error: %s", e)
    return render_template("error.html", **_page_context(msg="An internal error occurred. Please try again.")), 500


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    use_reloader = os.getenv("FLASK_USE_RELOADER", "0").strip().lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("PORT", "5000"))
    try:
        app.run(debug=debug, use_reloader=use_reloader, port=port)
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print(f"\n  Port {port} is already in use.")
            print(f"  Stop the other process first, or set a different port:")
            print(f"  PORT=5001 python app.py\n")
        else:
            raise
