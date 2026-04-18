"""Flask application for the ScorPred football and NBA predictor."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):
        return False
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, g
from werkzeug.middleware.proxy_fix import ProxyFix

import api_client as ac
import predictor as pred
import props_engine as pe
import scorpred_engine as se
import scormastermind as sm
import model_tracker as mt
import user_auth
import odds_fetcher
import result_updater as ru
from runtime_paths import ensure_runtime_dirs
from security import check_chat_rate_limit, configure_security, sanitize_error
from services import analysis_assistant as assistant_services

try:
    import nba_live_client as nc
    import nba_predictor as np_nba
except ImportError:  # pragma: no cover
    nc = None  # type: ignore[assignment]
    np_nba = None  # type: ignore[assignment]
from services import evidence as evidence_services
from services import strategy_lab as strategy_lab_services
from services import tracking_bootstrap as bootstrap_services
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
ensure_runtime_dirs()


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
configure_security(app, os.getenv("SECRET_KEY", "").strip())

# ── Blueprints ─────────────────────────────────────────────────────────────────
app.register_blueprint(nba_bp)
app.register_blueprint(user_auth.user_auth_bp)
@app.before_request
def inject_user():
    g.current_user = user_auth.current_user()

@app.context_processor
def inject_auth_context():
    return {
        "current_user": user_auth.current_user(),
        "is_guest": user_auth.current_user() is None,
    }

LEAGUE = DEFAULT_LEAGUE_ID
SEASON = CURRENT_SEASON


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_stamp() -> str:
    return assistant_services.now_stamp()


def _refresh_requested() -> bool:
    return bootstrap_services.refresh_requested(request.args)


def _set_data_refresh() -> bool:
    return bootstrap_services.set_data_refresh(ac, request.args)


@app.after_request
def _reset_force_refresh(response):
    return bootstrap_services.reset_force_refresh(ac, response)


def _football_data_source() -> str:
    return assistant_services.football_data_source(ac)


def _page_context(data_source: str | None = None, **kwargs) -> dict:
    return assistant_services.page_context(ac, data_source=data_source, **kwargs)


def _selection_error_redirect(endpoint: str, message: str):
    return redirect(url_for(endpoint, selection_error=message))


def _clean_injuries(items: list[dict]) -> list[dict]:
    return evidence_services.clean_injuries(items)


def _display_injuries(items: list[dict]) -> list[dict]:
    return evidence_services.display_injuries(items)


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
    return bootstrap_services.football_supported_leagues(ac, LEAGUE_BY_ID)


def _critical_error(message: str, status_code: int = 503):
    return render_template("error.html", **_page_context(msg=message)), status_code


def _resolve_provider_team_by_name(name: str, teams: list[dict]) -> dict | None:
    return bootstrap_services.resolve_provider_team_by_name(name, teams)


def _fixture_context_from_form() -> dict | None:
    return bootstrap_services.fixture_context_from_form(request.form)


def _selected_fixture() -> dict:
    return bootstrap_services.selected_fixture(session)


def _load_upcoming_fixtures(next_n: int = 20, max_deep_predictions: int = 6):
    return evidence_services.load_upcoming_fixtures(
        ac,
        pred,
        se,
        league=LEAGUE,
        season=SEASON,
        logger=app.logger,
        football_data_source=_football_data_source,
        next_n=next_n,
        max_deep_predictions=max_deep_predictions,
    )


def _require_teams():
    return bootstrap_services.require_teams(session)


def _store_selected_teams(team_a: dict, team_b: dict, fixture_context: dict | None = None) -> None:
    bootstrap_services.store_selected_teams(session, team_a, team_b, fixture_context)


def _team_form_payload(team_id: int) -> dict:
    return evidence_services.team_form_payload(
        ac,
        pred,
        team_id=team_id,
        league=LEAGUE,
        season=SEASON,
    )


def _run_parallel(tasks: dict[str, tuple[Callable[[], Any], Any, str]]) -> dict[str, Any]:
    """Run independent I/O tasks concurrently and return key->result with safe fallbacks."""
    if not tasks:
        return {}

    max_workers = min(8, len(tasks))
    results: dict[str, Any] = {key: default for key, (_, default, _) in tasks.items()}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(func): (key, default, error_label)
            for key, (func, default, error_label) in tasks.items()
        }
        for future, (key, default, error_label) in futures.items():
            try:
                results[key] = future.result()
            except Exception as exc:
                results[key] = default
                if error_label:
                    app.logger.error("%s: %s", error_label, exc)

    return results


def _fallback_chat_reply(message: str) -> str:
    team_a, team_b = _require_teams()
    return assistant_services.fallback_chat_reply(message, team_a=team_a, team_b=team_b)


def _chat_reply(message: str, history: list[dict] | None = None) -> str:
    team_a, team_b = _require_teams()
    return assistant_services.chat_reply(
        message,
        history=history,
        anthropic_module=anthropic,
        api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        team_a=team_a,
        team_b=team_b,
        logger=app.logger,
    )


def _prediction_top_probability(pred: dict[str, Any]) -> float:
    return max(
        float(pred.get("prob_a", 0.0) or 0.0),
        float(pred.get("prob_b", 0.0) or 0.0),
        float(pred.get("prob_draw", 0.0) or 0.0),
    )


def _home_play_type(pred: dict[str, Any]) -> str:
    predicted_winner = str(pred.get("predicted_winner") or "").lower()
    if predicted_winner == "avoid":
        return "AVOID"

    confidence = str(pred.get("confidence") or "")
    top_prob = _prediction_top_probability(pred)
    if confidence == "High" and top_prob >= 60.0:
        return "BET"
    return "LEAN"


def _home_recommendation(pred: dict[str, Any]) -> str:
    predicted_winner = str(pred.get("predicted_winner") or "")
    team_a = pred.get("team_a") or "Team A"
    team_b = pred.get("team_b") or "Team B"

    if predicted_winner == "A":
        return f"{team_a} ML"
    if predicted_winner == "B":
        return f"{team_b} ML"
    if str(predicted_winner).lower() == "draw":
        return "Draw"
    return "No clear edge"


def _best_strategy_label(metrics: dict[str, Any]) -> str:
    candidates: list[tuple[float, int, str]] = []
    for key, row in (metrics.get("by_confidence") or {}).items():
        accuracy = row.get("accuracy")
        count = int(row.get("count") or 0)
        if accuracy is not None and count >= 3:
            candidates.append((float(accuracy), count, f"{key} Confidence"))

    for key, row in (metrics.get("by_sport") or {}).items():
        accuracy = row.get("accuracy")
        count = int(row.get("count") or 0)
        if accuracy is not None and count >= 3:
            label = "Soccer" if key == "soccer" else "NBA" if key == "nba" else str(key).title()
            candidates.append((float(accuracy), count, f"{label} Segment"))

    if not candidates:
        return "Awaiting sample"
    best = max(candidates, key=lambda item: (item[0], item[1]))
    return f"{best[2]} ({best[0]:.1f}%)"


def _build_home_dashboard_context() -> dict[str, Any]:
    metrics = mt.get_summary_metrics()
    pending = mt.get_pending_predictions(limit=40)
    completed = mt.get_completed_predictions(limit=8)

    conf_rank = {"High": 3, "Medium": 2, "Low": 1}
    candidates = [
        pred for pred in pending
        if str(pred.get("predicted_winner") or "").lower() != "avoid"
        and str(pred.get("confidence") or "") in {"High", "Medium"}
        and _prediction_top_probability(pred) >= 52.0
    ]

    candidates.sort(
        key=lambda pred: (
            conf_rank.get(str(pred.get("confidence") or ""), 0),
            _prediction_top_probability(pred),
            str(pred.get("created_at") or ""),
        ),
        reverse=True,
    )

    top_picks = []
    for pred in candidates[:5]:
        confidence = str(pred.get("confidence") or "Low")
        top_prob = _prediction_top_probability(pred)
        top_picks.append(
            {
                "matchup": f"{pred.get('team_a', 'Team A')} vs {pred.get('team_b', 'Team B')}",
                "play_type": _home_play_type(pred),
                "recommendation": _home_recommendation(pred),
                "confidence": confidence,
                "confidence_display": f"{top_prob:.1f}% · {confidence}",
                "sport": str(pred.get("sport") or "").upper(),
                "game_date": pred.get("game_date") or pred.get("date"),
            }
        )

    performance_preview = [
        (pred.get("overall_game_result") or ("Win" if pred.get("winner_hit") else "Loss"))
        for pred in completed[:6]
    ]

    return {
        "system_snapshot": {
            "overall_accuracy": (
                f"{metrics.get('overall_accuracy'):.1f}%"
                if metrics.get("overall_accuracy") is not None
                else "Awaiting sample"
            ),
            "tracked_predictions": int(metrics.get("total_predictions") or 0),
            "best_strategy": _best_strategy_label(metrics),
        },
        "top_picks": top_picks,
        "performance_preview": performance_preview,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    home_context = _build_home_dashboard_context()
    return render_template("home.html", **_page_context(**home_context))


@app.route("/soccer", methods=["GET"])
def soccer():
    _set_data_refresh()
    load_error = None
    teams = []
    upcoming_fixtures = []
    fixtures_error = None
    fixtures_source = _football_data_source()

    results = _run_parallel(
        {
            "teams": (
                lambda: ac.get_teams(LEAGUE, SEASON),
                [],
                "Failed to fetch teams",
            ),
            "upcoming": (
                lambda: _load_upcoming_fixtures(next_n=8, max_deep_predictions=4),
                ([], None, fixtures_source, None),
                "Failed to fetch upcoming fixtures",
            ),
        }
    )

    teams = results.get("teams") or []
    upcoming_bundle = results.get("upcoming") or ([], None, fixtures_source, None)
    upcoming_fixtures, fixtures_error, fixtures_source, _ = upcoming_bundle

    if not teams:
        load_error = "Teams are unavailable right now."

    return render_template(
        "soccer.html",
        **_page_context(
            data_source=fixtures_source,
            teams=teams or [],
            load_error=load_error,
            upcoming_fixtures=upcoming_fixtures or [],
            fixtures_error=fixtures_error,
            fixtures_source=fixtures_source,
            selection_notice=(request.args.get("selection_error") or "").strip() or None,
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
        return _selection_error_redirect("soccer", "The selected soccer fixture could not be prepared for Match Analysis.")

    try:
        teams = ac.get_teams(LEAGUE, SEASON)
    except Exception as exc:
        app.logger.error("Failed to fetch provider teams during selection: %s", exc)
        return _selection_error_redirect("soccer", "The selected soccer fixture could not be loaded because team data is unavailable.")

    if not teams:
        return _selection_error_redirect("soccer", "The selected soccer fixture could not be loaded because team data is unavailable.")

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
        return _selection_error_redirect(
            "soccer",
            "The selected soccer fixture could not be matched to the current provider, so Match Analysis was not loaded.",
        )

    _store_selected_teams(team_a, team_b, fixture_context)
    return redirect(url_for("prediction"))


@app.route("/matchup", methods=["GET"])
def matchup():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return _selection_error_redirect("soccer", "Match Analysis could not be opened because no soccer fixture is selected.")
    selected_fixture = _selected_fixture()

    id_a, id_b = team_a["id"], team_b["id"]
    results = _run_parallel(
        {
            "h2h_raw": (
                lambda: ac.get_h2h(id_a, id_b, last=20),
                [],
                "H2H fetch error",
            ),
            "fixtures_a": (
                lambda: ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20),
                [],
                "Team A fixtures fetch error",
            ),
            "fixtures_b": (
                lambda: ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20),
                [],
                "Team B fixtures fetch error",
            ),
            "injuries_a_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_a),
                [],
                "Team A injuries fetch error",
            ),
            "injuries_b_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_b),
                [],
                "Team B injuries fetch error",
            ),
            "standings_for_opp": (
                lambda: ac.get_standings(LEAGUE, SEASON),
                [],
                "Standings fetch error",
            ),
            "squad_a": (
                lambda: ac.get_squad(id_a, SEASON),
                [],
                "Matchup squad A fetch error",
            ),
            "squad_b": (
                lambda: ac.get_squad(id_b, SEASON),
                [],
                "Matchup squad B fetch error",
            ),
        }
    )

    h2h_raw = results.get("h2h_raw") or []
    fixtures_a = results.get("fixtures_a") or []
    fixtures_b = results.get("fixtures_b") or []
    injuries_a_raw = results.get("injuries_a_raw") or []
    injuries_b_raw = results.get("injuries_b_raw") or []
    standings_for_opp = results.get("standings_for_opp") or []
    squad_a = results.get("squad_a") or []
    squad_b = results.get("squad_b") or []

    h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)
    fixtures_a = pred.filter_recent_completed_fixtures(fixtures_a, current_season=SEASON)
    fixtures_b = pred.filter_recent_completed_fixtures(fixtures_b, current_season=SEASON)

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
    opp_strengths = _build_opp_strengths(standings_for_opp)

    # ── Fetch live odds (graceful no-op when ODDS_API_KEY is unset) ──────────
    odds_result = odds_fetcher.fetch_match_odds("soccer", team_a["name"], team_b["name"])
    odds_ctx: dict[str, Any] | None = None
    if odds_result.get("available"):
        odds_ctx = {
            "home": odds_result.get("home_odds"),
            "draw": odds_result.get("draw_odds"),
            "away": odds_result.get("away_odds"),
        }

    mastermind = sm.predict_match(
        {
            "sport": "soccer",
            "team_a_name": team_a["name"],
            "team_b_name": team_b["name"],
            "team_a_is_home": True,
            "form_a": form_a,
            "form_b": form_b,
            "h2h_form_a": h2h_form_a,
            "h2h_form_b": h2h_form_b,
            "injuries_a": injuries_a_raw,
            "injuries_b": injuries_b_raw,
            "opp_strengths": opp_strengths,
            "team_stats": {
                "a": split_a,
                "b": split_b,
            },
            **(({"odds": odds_ctx}) if odds_ctx else {}),
        }
    )
    scorpred = mastermind.get("ui_prediction") or {}

    # ── Compute odds edge for template display ─────────────────────────────────
    edge_data: dict[str, Any] = {}
    if odds_result.get("available"):
        probs = scorpred.get("win_probabilities") or {}
        best_pick_team = (scorpred.get("best_pick") or {}).get("team", "A")
        if best_pick_team in (team_a["name"], "A"):
            model_prob = float(probs.get("a", 0) or 0) / 100.0
            market_odds = odds_result.get("home_odds")
        elif best_pick_team in (team_b["name"], "B"):
            model_prob = float(probs.get("b", 0) or 0) / 100.0
            market_odds = odds_result.get("away_odds")
        else:
            model_prob = float(probs.get("draw", 0) or 0) / 100.0
            market_odds = odds_result.get("draw_odds")
        edge_data = odds_fetcher.compute_edge(model_prob, market_odds)

    # ── Key threats (danger men) ────────────────────────────────────────────────
    threats_a = _build_key_threats(squad_a, injuries_a_raw, fixtures_a, id_a)
    threats_b = _build_key_threats(squad_b, injuries_b_raw, fixtures_b, id_b)

    # Save prediction to tracker
    try:
        best_pick = scorpred.get("best_pick", {})
        mt.save_prediction(
            sport="soccer",
            team_a=team_a["name"],
            team_b=team_b["name"],
            predicted_winner=best_pick.get("tracking_team") or best_pick.get("team", ""),
            win_probs=scorpred.get("win_probabilities", {}),
            confidence=best_pick.get("confidence", "Low"),
            game_date=(selected_fixture or {}).get("date") or None,
            team_a_id=team_a["id"],
            team_b_id=team_b["id"],
            league_id=LEAGUE,
            season=SEASON,
            model_probability=mastermind.get("model_probability"),
            form_a_length=len(form_a),
        )
    except Exception:
        app.logger.warning("Prediction tracking failed (matchup)", exc_info=True)

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
            edge_data=edge_data,
        ),
    )


def _build_key_threats(squad: list, injuries: list, fixtures: list, team_id: int) -> list[dict]:
    return evidence_services.build_key_threats(
        squad,
        injuries,
        fixtures,
        team_id,
        predictor=pred,
        current_season=SEASON,
    )


def _build_soccer_total_pick(fixture: dict[str, Any], opp_strengths: dict[str, Any]) -> dict[str, Any] | None:
    try:
        home_id = fixture["teams"]["home"]["id"]
        away_id = fixture["teams"]["away"]["id"]
        home_name = fixture["teams"]["home"]["name"]
        away_name = fixture["teams"]["away"]["name"]

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

        if expected_total > 2.5:
            pick = "Over 2.5 Goals"
            over_probability = min(95, 50 + (expected_total - 2.5) * 20)
        else:
            pick = "Under 2.5 Goals"
            over_probability = max(5, 50 - (2.5 - expected_total) * 20)

        if abs(expected_total - 2.5) >= 1.0:
            confidence = "High"
        elif abs(expected_total - 2.5) >= 0.5:
            confidence = "Medium"
        else:
            confidence = "Low"

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

        if confidence != "High" and over_probability <= 60:
            return None

        return {
            "fixture": fixture,
            "home_team": fixture["teams"]["home"],
            "away_team": fixture["teams"]["away"],
            "pick": pick,
            "probability": round(over_probability),
            "confidence": confidence,
            "note": note,
            "expected_total": round(expected_total, 1),
        }
    except Exception as exc:
        app.logger.warning("Totals prediction failed for soccer fixture %s: %s", fixture.get("fixture", {}).get("id"), exc)
        return None


def _build_nba_winner_pick(
    game: dict[str, Any],
    team_map: dict[str, dict[str, Any]],
    nba_opp_strengths: dict[str, Any],
    nc: Any,
    np_nba: Any,
) -> dict[str, Any] | None:
    try:
        if not isinstance(game, dict):
            return None

        teams_block = game.get("teams") or {}
        home_raw = teams_block.get("home") or {}
        away_raw = teams_block.get("visitors") or {}

        home_id = str(home_raw.get("id") or "")
        away_id = str(away_raw.get("id") or "")

        if not home_id or not away_id:
            return None

        home_team = team_map.get(home_id) or home_raw
        away_team = team_map.get(away_id) or away_raw

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

        if confidence != "High" and prob_home <= 60 and prob_away <= 60:
            return None

        predicted_winner = best_pick.get("prediction", "—")
        winner_team = (
            home_team.get("name")
            if predicted_winner == "Home"
            else away_team.get("name") if predicted_winner == "Away" else "—"
        )

        return {
            "game": game,
            "home_team": home_team,
            "away_team": away_team,
            "predicted_winner": winner_team,
            "win_probability": prob_home if predicted_winner == "Home" else prob_away,
            "confidence": confidence,
            "reasoning": best_pick.get("reasoning", ""),
        }
    except Exception as exc:
        app.logger.warning("Prediction failed for NBA game %s: %s", game.get("id"), exc)
        return None


@app.route("/player")
def player():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))
    selected_fixture = _selected_fixture()
    id_a, id_b = team_a["id"], team_b["id"]

    results = _run_parallel(
        {
            "squad_a": (
                lambda: ac.get_squad(id_a, SEASON),
                [],
                "Player squad A fetch error",
            ),
            "squad_b": (
                lambda: ac.get_squad(id_b, SEASON),
                [],
                "Player squad B fetch error",
            ),
            "injuries_a_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_a),
                [],
                "Player injuries A fetch error",
            ),
            "injuries_b_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_b),
                [],
                "Player injuries B fetch error",
            ),
            "fixtures_a": (
                lambda: ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20),
                [],
                "Player fixtures A fetch error",
            ),
            "fixtures_b": (
                lambda: ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20),
                [],
                "Player fixtures B fetch error",
            ),
        }
    )

    squad_a = results.get("squad_a") or []
    squad_b = results.get("squad_b") or []
    injuries_a_raw = results.get("injuries_a_raw") or []
    injuries_b_raw = results.get("injuries_b_raw") or []
    fixtures_a = results.get("fixtures_a") or []
    fixtures_b = results.get("fixtures_b") or []

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
        return jsonify({"error": sanitize_error(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 500


@app.route("/prediction")
def prediction():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    if not team_a:
        return _selection_error_redirect("soccer", "Match Analysis could not be opened because no soccer fixture is selected.")
    selected_fixture = _selected_fixture()

    id_a, id_b = team_a["id"], team_b["id"]
    results = _run_parallel(
        {
            "h2h": (
                lambda: ac.get_h2h(id_a, id_b, last=20),
                [],
                "Prediction H2H fetch error",
            ),
            "fixtures_a": (
                lambda: ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=20),
                [],
                "Prediction team A fixtures fetch error",
            ),
            "fixtures_b": (
                lambda: ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=20),
                [],
                "Prediction team B fixtures fetch error",
            ),
            "injuries_a_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_a),
                [],
                "Prediction team A injuries fetch error",
            ),
            "injuries_b_raw": (
                lambda: ac.get_injuries(LEAGUE, SEASON, id_b),
                [],
                "Prediction team B injuries fetch error",
            ),
            "standings_for_opp": (
                lambda: ac.get_standings(LEAGUE, SEASON),
                [],
                "Prediction standings fetch error",
            ),
        }
    )

    h2h = results.get("h2h") or []
    fixtures_a = results.get("fixtures_a") or []
    fixtures_b = results.get("fixtures_b") or []
    injuries_a = _clean_injuries(results.get("injuries_a_raw") or [])
    injuries_b = _clean_injuries(results.get("injuries_b_raw") or [])
    standings_for_opp = results.get("standings_for_opp") or []

    h2h = pred.filter_recent_completed_fixtures(h2h, current_season=SEASON)
    fixtures_a = pred.filter_recent_completed_fixtures(fixtures_a, current_season=SEASON)
    fixtures_b = pred.filter_recent_completed_fixtures(fixtures_b, current_season=SEASON)

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
    opp_strengths = _build_opp_strengths(standings_for_opp)

    # Optional decimal odds for edge calculation — all three required or ignored
    _odds: dict[str, float] | None = None
    try:
        _ho = (request.args.get("home_odds") or "").strip()
        _do = (request.args.get("draw_odds") or "").strip()
        _ao = (request.args.get("away_odds") or "").strip()
        if _ho and _do and _ao:
            _odds = {"home": float(_ho), "draw": float(_do), "away": float(_ao)}
    except (TypeError, ValueError):
        _odds = None

    # Single unified prediction from ScorMastermind
    mastermind = sm.predict_match(
        {
            "sport": "soccer",
            "team_a_name": team_a["name"],
            "team_b_name": team_b["name"],
            "team_a_is_home": True,
            "form_a": form_a,
            "form_b": form_b,
            "h2h_form_a": h2h_form_a,
            "h2h_form_b": h2h_form_b,
            "injuries_a": injuries_a,
            "injuries_b": injuries_b,
            "opp_strengths": opp_strengths,
            "team_stats": {
                "a": {"form": form_a},
                "b": {"form": form_b},
            },
            "odds": _odds,
        }
    )
    prediction = mastermind.get("ui_prediction") or {}

    # Track this prediction
    try:
        best_pick = prediction.get("best_pick", {})
        pred_winner = best_pick.get("tracking_team") or best_pick.get("team", "")
        probs = prediction.get("win_probabilities", {})
        conf = best_pick.get("confidence", "Medium")
        
        mt.save_prediction(
            sport="soccer",
            team_a=team_a["name"],
            team_b=team_b["name"],
            predicted_winner=pred_winner,
            win_probs=probs,
            confidence=conf,
            game_date=(selected_fixture or {}).get("date") or None,
            team_a_id=team_a["id"],
            team_b_id=team_b["id"],
            league_id=LEAGUE,
            season=SEASON,
            model_probability=mastermind.get("model_probability"),
        )
    except Exception:
        app.logger.warning("Prediction tracking failed (prediction)", exc_info=True)

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
    fixtures_with_pred, load_error, data_source, espn_slug = _load_upcoming_fixtures(next_n=20, max_deep_predictions=6)

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
    fixtures_with_pred = []

    now_utc = datetime.now(timezone.utc)
    app.logger.info(
        "today_soccer_predictions: UTC=%s, league=%s",
        now_utc.strftime("%Y-%m-%d %H:%M"),
        LEAGUE,
    )

    try:
        fixtures_with_pred, load_error, _, _ = _load_upcoming_fixtures(next_n=20, max_deep_predictions=6)
        app.logger.info(
            "today_soccer_predictions: fixture payload size=%d",
            len(fixtures_with_pred),
        )
        for fx in fixtures_with_pred:
            fx_id = (fx.get("fixture") or {}).get("id", "?")
            fx_date = (fx.get("fixture") or {}).get("date", "unknown")
            fx_status = (fx.get("fixture") or {}).get("status", {}).get("short", "?")
            home = (fx.get("teams") or {}).get("home", {})
            away = (fx.get("teams") or {}).get("away", {})
            app.logger.debug(
                "FIXTURE: id=%s %s vs %s on %s [%s]",
                fx_id, home.get("name", "?"), away.get("name", "?"), fx_date, fx_status
            )
            pred = fx.get("prediction") or {}
            form_a = pred.get("form_a", []) if isinstance(pred, dict) else []
            form_b = pred.get("form_b", []) if isinstance(pred, dict) else []
            app.logger.debug(
                "  Home team ID=%s, Away team ID=%s, form_a_len=%d, form_b_len=%d",
                home.get("id", "?"), away.get("id", "?"), len(form_a), len(form_b)
            )
            if not form_a or not form_b:
                app.logger.warning(
                    "  MISSING FORM: fixture_id=%s home_id=%s away_id=%s (form_a_len=%d, form_b_len=%d)",
                    fx_id, home.get("id", "?"), away.get("id", "?"), len(form_a), len(form_b)
                )
    except Exception as exc:
        app.logger.error("Upcoming fixtures fetch failed: %s", exc, exc_info=True)
        load_error = sanitize_error(exc)

    # Build response payload from shared fixture predictions
    predictions_for_fixtures = []
    for row in fixtures_with_pred or []:
        try:
            fixture = row or {}
            prediction = fixture.get("prediction") or {}
            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})

            # Diagnostics for fallback/limited data
            form_a = prediction.get("form_a", []) if isinstance(prediction, dict) else []
            form_b = prediction.get("form_b", []) if isinstance(prediction, dict) else []
            fallback_reason = None
            data_quality = prediction.get("data_quality", "Limited")
            has_data = data_quality != "Limited"

            # Guard against neutral-fallback predictions that slipped through
            # quality checks (e.g. stale cache served empty form data).
            score_gap = prediction.get("score_gap", 0)
            if has_data and score_gap == 0:
                pa, pd, pb = probs.get("a", 0), probs.get("draw", 0), probs.get("b", 0)
                if abs(pa - 37.0) < 0.5 and abs(pd - 26.0) < 0.5 and abs(pb - 37.0) < 0.5:
                    has_data = False
                    fallback_reason = "Neutral fallback probabilities detected"

            # If form is missing, set fallback reason
            if not form_a or not form_b:
                has_data = False
                fallback_reason = "Missing recent form data"

            # Add to predictions list with fixture info
            predictions_for_fixtures.append({
                "fixture": fixture,
                "home_team": fixture["teams"]["home"],
                "away_team": fixture["teams"]["away"],
                "prediction": prediction,
                "predicted_winner": best_pick.get("prediction", "—") if has_data else "—",
                "confidence": best_pick.get("confidence", "Low") if has_data else "Low",
                "prob_home": probs.get("a", 33.3),
                "prob_draw": probs.get("draw", 33.4),
                "prob_away": probs.get("b", 33.3),
                "reasoning": best_pick.get("reasoning", "") if has_data else fallback_reason or "",
                "score_gap": prediction.get("score_gap", 0),
                "data_quality": data_quality,
                "has_data": has_data,
                "form_a_len": len(form_a),
                "form_b_len": len(form_b),
                "fallback_reason": fallback_reason,
            })
        except Exception as exc:
            app.logger.warning("Prediction for fixture %s failed: %s", (row or {}).get("fixture", {}).get("id"), exc)
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
            total_fixtures=len(fixtures_with_pred),
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
    """Display model evaluation dashboard with trends, calibration, and strategy analytics."""
    sport_filter = request.args.get('sport', '').lower()
    rolling_window = request.args.get('window', default=10, type=int) or 10
    exclude_seeded = request.args.get('include_seeded', '0') != '1'
    try:
        metrics = mt.get_summary_metrics(exclude_seeded=exclude_seeded)
        completed_predictions = mt.get_completed_predictions()
        pending_predictions = mt.get_pending_predictions()

        strategy_context = strategy_lab_services.build_strategy_lab_context()
        performance_comparison = strategy_context.get("performance_comparison") or {}
        ml_comparison = strategy_context.get("ml_comparison") or {}
        evaluation = mt.get_evaluation_dashboard(
            rolling_window=max(1, min(rolling_window, 50)),
            strategy_reference=performance_comparison,
            exclude_seeded=exclude_seeded,
        )
        
        # Filter completed predictions by sport if specified
        if sport_filter in ['soccer', 'nba']:
            completed_predictions = [p for p in completed_predictions if p.get('sport', '').lower() == sport_filter]
            evaluation["failure_rows"] = [
                row for row in evaluation.get("failure_rows", [])
                if row.get("sport", "").lower() == sport_filter
            ]
            evaluation["pass_rows"] = [
                row for row in evaluation.get("pass_rows", [])
                if row.get("sport", "").lower() == sport_filter
            ]
        
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
        evaluation = {
            "kpis": {
                "overall_accuracy": None,
                "rolling_win_rate": None,
                "total_tracked_predictions": 0,
                "finalized_predictions": 0,
                "avoids_skipped": 0,
                "current_best_strategy": "Awaiting sample",
                "roi_or_points": 0,
            },
            "rolling_window": rolling_window,
            "series": {
                "rolling_by_match": [],
                "rolling_by_day": [],
                "cumulative_points": [],
            },
            "confidence_calibration": [],
            "strategy_comparison": [],
            "breakdowns": {
                "by_sport": [],
                "by_confidence_tier": [],
                "by_predicted_outcome": [],
                "recent_form": {"last_10": {"count": 0, "accuracy": None}, "last_20": {"count": 0, "accuracy": None}},
            },
            "failure_rows": [],
            "pass_rows": [],
        }
        performance_comparison = {}
        ml_comparison = {}

    return render_template(
        "model_performance.html",
        **_page_context(
            metrics=metrics,
            completed_predictions=completed_predictions,
            pending_predictions=pending_predictions,
            sport_filter=sport_filter,
            evaluation=evaluation,
            performance_comparison=performance_comparison,
            ml_comparison=ml_comparison,
            walk_forward=strategy_lab_services.walk_forward_summary(),
        ),
    )


@app.route("/pass-analysis")
def pass_analysis():
    """Display recent successful picks to complement failure analysis."""
    sport_filter = request.args.get("sport", "").lower()
    rolling_window = request.args.get("window", default=10, type=int) or 10
    try:
        evaluation = mt.get_evaluation_dashboard(
            rolling_window=max(1, min(rolling_window, 50)),
        )
        pass_rows = evaluation.get("pass_rows", [])
        if sport_filter in ["soccer", "nba"]:
            pass_rows = [
                row for row in pass_rows
                if row.get("sport", "").lower() == sport_filter
            ]
    except Exception as exc:
        app.logger.error("pass_analysis: failed to build pass rows - %s", exc, exc_info=True)
        evaluation = {"kpis": {}, "rolling_window": rolling_window}
        pass_rows = []

    return render_template(
        "pass_analysis.html",
        **_page_context(
            evaluation=evaluation,
            pass_rows=pass_rows,
            sport_filter=sport_filter,
        ),
    )


@app.route("/strategy-lab")
def strategy_lab():
    """Display product-facing strategy and ML comparison context."""
    exclude_seeded = request.args.get('include_seeded', '0') != '1'
    try:
        context = strategy_lab_services.build_strategy_lab_context()
    except Exception as exc:
        app.logger.error("strategy_lab: failed to build context - %s", exc, exc_info=True)
        context = strategy_lab_services.empty_strategy_lab_context()

    # Add calibration data from tracker
    try:
        _metrics = mt.get_summary_metrics(exclude_seeded=exclude_seeded)
        context["calibration"] = _metrics.get("calibration") or {}
        context["seeded_count"] = _metrics.get("seeded_count", 0) if exclude_seeded else 0
        context["real_prediction_count"] = _metrics.get("total_predictions", 0)
        context["exclude_seeded"] = exclude_seeded
    except Exception:
        context.setdefault("calibration", {})
        context.setdefault("seeded_count", 0)
        context.setdefault("real_prediction_count", 0)
        context.setdefault("exclude_seeded", exclude_seeded)

    return render_template(
        "strategy_lab.html",
        **_page_context(**context),
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
        return jsonify({"error": sanitize_error(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 500


@app.route("/chat", methods=["POST"])
def chat():
    retry_after = check_chat_rate_limit(
        limit=int(app.config.get("CHAT_RATE_LIMIT_COUNT", 8)),
        window_seconds=int(app.config.get("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60)),
    )
    if retry_after:
        return jsonify(
            {
                "error": "Chat rate limit exceeded. Please wait before sending another message.",
                "retry_after": retry_after,
            }
        ), 429

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
        with ThreadPoolExecutor(max_workers=min(8, len(upcoming_fixtures or [])) or 1) as executor:
            futures = [
                executor.submit(_build_soccer_total_pick, fixture, opp_strengths)
                for fixture in (upcoming_fixtures or [])
            ]
            for future in futures:
                result = future.result()
                if result:
                    soccer_totals.append(result)

    except Exception as exc:
        app.logger.error("Failed to process soccer totals: %s", exc)

    # ── NBA Winners ────────────────────────────────────────────────────────
    
    nba_winners = []
    try:
        if nc is None or np_nba is None:
            raise ImportError("NBA client not available")

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
        
        with ThreadPoolExecutor(max_workers=min(8, len(today_games or [])) or 1) as executor:
            futures = [
                executor.submit(_build_nba_winner_pick, game, team_map, nba_opp_strengths, nc, np_nba)
                for game in (today_games or [])
            ]
            for future in futures:
                result = future.result()
                if result:
                    nba_winners.append(result)
                
    except Exception as exc:
        app.logger.error("Failed to fetch NBA data: %s", exc)
        if not load_error:
            load_error = sanitize_error(exc)
    
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
        teams = ac.get_teams(league_id, season)
    except Exception as exc:
        return jsonify({"teams": [], "league": LEAGUE_BY_ID.get(league_id, {}), "error": sanitize_error(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200

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
        return jsonify({"error": sanitize_error(exc), "form_string": "", "rows": [], "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200


@app.route("/api/football/squad")
def football_squad_api():
    _set_data_refresh()
    team_id = request.args.get("team_id", type=int)
    league_id = request.args.get("league", default=LEAGUE, type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    try:
        squad = ac.get_squad(team_id, SEASON)
    except Exception as exc:
        return jsonify({"players": [], "league_id": league_id, "error": sanitize_error(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200

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
        return jsonify({"competitions": [], "league_ids": [], "error": sanitize_error(exc), "data_source": _football_data_source(), "last_updated": _now_stamp()}), 200
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
            "error": sanitize_error(exc),
            "data_source": _football_data_source(),
            "last_updated": _now_stamp(),
        }), 200


@app.route("/props")
def props_page():
    _set_data_refresh()
    team_a, team_b = _require_teams()
    squad_a = []
    squad_b = []
    tasks: dict[str, tuple[Callable[[], Any], Any, str]] = {}
    if team_a:
        tasks["squad_a"] = (
            lambda: ac.get_squad(team_a["id"], SEASON),
            [],
            "Props page squad A fetch error",
        )
    if team_b:
        tasks["squad_b"] = (
            lambda: ac.get_squad(team_b["id"], SEASON),
            [],
            "Props page squad B fetch error",
        )
    results = _run_parallel(tasks)
    squad_a = results.get("squad_a") or []
    squad_b = results.get("squad_b") or []

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
            app.logger.error(
                "Port %s is already in use. Stop the running process or set PORT to a different value.",
                port,
            )
        else:
            raise
