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
        try:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            prediction = pred.quick_predict_from_standings(home_id, away_id, standings_list)
        except Exception:
            prediction = pred.quick_predict_from_standings(0, 0, [])
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
    fixtures = ac.get_team_fixtures(team_id, LEAGUE, SEASON, last=5)
    form = pred.extract_form(fixtures, team_id)[:5]
    return {"form_string": "".join(item.get("result", "") for item in form), "rows": form}


def _fallback_chat_reply(message: str) -> str:
    lower = (message or "").strip().lower()
    team_a, team_b = _require_teams()
    matchup = f"{team_a['name']} vs {team_b['name']}" if team_a and team_b else "your selected matchup"

    if "props" in lower:
        return f"Use the Props page to generate player lines for {matchup}. Pick a player, choose markets, and the app will build a bet slip from live stats."
    if "prediction" in lower or "winner" in lower:
        return f"The Prediction page combines recent form, head-to-head data, injuries, and a Poisson model for {matchup}."
    if "player" in lower:
        return "The Player page compares squad members side by side and can generate prop ideas from their season profile and opponent context."
    if "nba" in lower:
        return "The NBA section has its own home, matchup, player, prediction, and standings views under /nba."
    return "Ask about matchup analysis, player props, prediction logic, injuries, or where to find a specific football or NBA view."


def _chat_reply(message: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or anthropic is None:
        return _fallback_chat_reply(message)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=180,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are the ScorPred assistant. Answer briefly, accurately, and focus on football and NBA app usage. "
                        f"User question: {message}"
                    ),
                }
            ],
        )
        text_blocks = [block.text for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"]
        reply = " ".join(text_blocks).strip()
        return reply or _fallback_chat_reply(message)
    except Exception:
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


@app.route("/select", methods=["POST"])
@app.route("/matchup", methods=["POST"])
def select():
    _set_data_refresh()
    a_id_raw = request.form.get("team_a", "").strip()
    b_id_raw = request.form.get("team_b", "").strip()
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
        h2h_raw = ac.get_h2h(id_a, id_b, last=10)
    except Exception as exc:
        app.logger.error("H2H fetch error: %s", exc)

    try:
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=10)
    except Exception as exc:
        app.logger.error("Team A fixtures fetch error: %s", exc)

    try:
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=10)
    except Exception as exc:
        app.logger.error("Team B fixtures fetch error: %s", exc)

    try:
        injuries_a_raw = ac.get_injuries(LEAGUE, SEASON, id_a)
    except Exception as exc:
        app.logger.error("Team A injuries fetch error: %s", exc)

    try:
        injuries_b_raw = ac.get_injuries(LEAGUE, SEASON, id_b)
    except Exception as exc:
        app.logger.error("Team B injuries fetch error: %s", exc)

    if not h2h_raw and not fixtures_a and not fixtures_b:
        return _critical_error("Matchup data is unavailable right now. Please try refreshing in a moment.")

    h2h_enriched = []
    for f in h2h_raw[:5]:
        try:
            h2h_enriched.append(ac.enrich_fixture(f))
        except Exception:
            h2h_enriched.append({**f, "events": [], "stats": []})

    form_a = pred.extract_form(fixtures_a, id_a)[:5]
    form_b = pred.extract_form(fixtures_b, id_b)[:5]
    split_a = pred.home_away_split(pred.extract_form(fixtures_a, id_a))
    split_b = pred.home_away_split(pred.extract_form(fixtures_b, id_b))
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
        ),
    )


@app.route("/player")
def player():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))
    selected_fixture = _selected_fixture()

    squad_a = []
    squad_b = []
    try:
        squad_a = ac.get_squad(team_a["id"], SEASON)
    except Exception as exc:
        app.logger.error("Player squad A fetch error: %s", exc)

    try:
        squad_b = ac.get_squad(team_b["id"], SEASON)
    except Exception as exc:
        app.logger.error("Player squad B fetch error: %s", exc)

    if not squad_a and not squad_b:
        return _critical_error("Player squad data is unavailable right now.")

    return render_template(
        "player.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            squad_a=squad_a,
            squad_b=squad_b,
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
        h2h = ac.get_h2h(id_a, id_b, last=10)
    except Exception as exc:
        app.logger.error("Prediction H2H fetch error: %s", exc)

    try:
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=10)
    except Exception as exc:
        app.logger.error("Prediction team A fixtures fetch error: %s", exc)

    try:
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=10)
    except Exception as exc:
        app.logger.error("Prediction team B fixtures fetch error: %s", exc)

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
        return _critical_error("Prediction data is unavailable right now. Please refresh and try again.")

    result = pred.predict(
        id_a, id_b, h2h, fixtures_a, fixtures_b,
        injuries_a, injuries_b, squad_a, squad_b
    )
    result["win_prob"] = _normalise_probs(result.get("win_prob", {}))

    return render_template(
        "prediction.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_fixture=selected_fixture,
            result=result,
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
    reply = _chat_reply(message)
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
    return render_template("error.html", **_page_context(msg=str(e))), 500


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    use_reloader = os.getenv("FLASK_USE_RELOADER", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, use_reloader=use_reloader, port=port)
