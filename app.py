"""Flask application for the ScorPred football and NBA predictor."""

from __future__ import annotations

import os

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
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
from db_models import db

try:
    import nba_live_client as nc
    import nba_predictor as np_nba
except ImportError:  # pragma: no cover
    nc = None  # type: ignore[assignment]
    np_nba = None  # type: ignore[assignment]
from services import evidence as evidence_services
from services import strategy_lab as strategy_lab_services
from services.strategy_lab import _EMPTY_METRICS
from services import tracking_bootstrap as bootstrap_services
from services.tracking_bootstrap import fixture_context_from_form
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
except ImportError:  # pragma: no cover
    anthropic = None

load_dotenv()
ensure_runtime_dirs()

import logging as _logging
_logger = _logging.getLogger(__name__)

# ── Production startup guard ───────────────────────────────────────────────────
_secret_key = os.environ.get("SECRET_KEY", "").strip()
_is_production = bool(os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production")
if _is_production and not _secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if not _secret_key:
    _logger.warning("SECRET_KEY not set — using an insecure default. Set SECRET_KEY for production.")
    _secret_key = "dev-insecure-key-change-me"

# --- Persistent session config ---
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
configure_security(app, _secret_key)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///scorpred.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
db.init_app(app)
# --- Persistent session config ---
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# ── Blueprints ──────────────────────────────────────────────────────────────────
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


@app.errorhandler(Exception)
def handle_unhandled_exception(exc):
    _logger.error("Unhandled exception in route %s: %s", request.path, exc, exc_info=True)
    return render_template(
        "error.html",
        message="Something went wrong. Please try again or go back to the home page.",
    ), 500


@app.errorhandler(404)
def handle_404(exc):
    return render_template("error.html", message="Page not found."), 404


LEAGUE = DEFAULT_LEAGUE_ID
SEASON = CURRENT_SEASON
LEAGUE_SESSION_KEY = "selected_league_id"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_stamp() -> str:
    return assistant_services.now_stamp()


 # --- Restored missing backend helpers for prediction/result display ---
def _fixture_context_from_form():
    """
    Wrapper for fixture_context_from_form using Flask's request.form or request.args.
    """
    from flask import request
    # Prefer form data, fallback to args
    form_data = request.form if request.method == "POST" else request.args
    return fixture_context_from_form(form_data)
def _summarize_form_compare(form_compare: dict, actual_winner: str | None = None) -> str | None:
    """
    Summarize recent form comparison for both teams, optionally referencing the actual winner.
    """
    if not form_compare or not isinstance(form_compare, dict):
        return None
    segments = []
    for team, stats in (form_compare or {}).items():
        if not stats:
            continue
        wins = stats.get("wins")
        losses = stats.get("losses")
        avg_for = stats.get("avg_goals_for") or stats.get("avg_points_for")
        avg_against = stats.get("avg_goals_against") or stats.get("avg_points_against")
        seg = f"{team}: {wins}W-{losses}L"
        if avg_for is not None and avg_against is not None:
            seg += f" ({avg_for} for, {avg_against} against)"
        segments.append(seg)
    if not segments:
        return None
    joined = "; ".join(segments)
    if actual_winner and actual_winner != "Unknown":
        return f"Recent form: {joined}. {actual_winner} had the edge in recent results." if actual_winner in form_compare else f"Recent form: {joined}."
    return f"Recent form: {joined}."


def _reality_sentence(record: dict) -> str:
    """
    Generate a short sentence summarizing the actual result for a prediction record.
    """
    actual_winner = record.get("actual_winner") or "Unknown"
    final_score = record.get("final_score_display") or "Unknown"
    total_scored = record.get("total_scored")
    if total_scored is not None:
        unit = "goal" if str(record.get("sport") or "").lower() == "soccer" else "point"
        label = unit if total_scored == 1 else f"{unit}s"
        return f"{actual_winner}, {final_score}, {total_scored} {label}"
    return f"{actual_winner}, {final_score}"


def _prediction_sentence(record: dict) -> str:
    """
    Generate a short sentence summarizing the model's prediction for a record.
    """
    pick = _prediction_pick_display(record)
    prob = _predicted_outcome_probability(record)
    prob_text = _format_percent_value(prob)
    if pick and prob_text:
        return f"Model pick: {pick} ({prob_text})"
    if pick:
        return f"Model pick: {pick}"
    return "Model pick unavailable"


def _filter_useful_injury_context(injuries: dict) -> dict:
    """
    Filter injury context to only include teams with at least one notable injury.
    """
    if not injuries or not isinstance(injuries, dict):
        return {}
    return {team: row for team, row in injuries.items() if row and (row.get("count", 0) > 0 or row.get("notable"))}


def _extract_totals_leg(prediction: dict) -> dict | None:
    """
    Extract the totals leg (pick/line/market) from a prediction dict.
    """
    if not prediction or not isinstance(prediction, dict):
        return None
    # Try direct keys first
    pick = prediction.get("totals_pick")
    line = prediction.get("totals_line")
    market = prediction.get("totals_market")
    # If not present, try nested or legacy keys
    if not pick and "optional_picks" in prediction:
        for opt in prediction["optional_picks"]:
            m = str(opt.get("market") or "").lower()
            if "over/under" in m or "o/u" in m:
                pick = opt.get("lean") or opt.get("pick")
                try:
                    line = float(opt.get("line") or opt.get("value") or 0)
                except Exception:
                    line = None
                market = opt.get("market")
                break
    result = {}
    if pick:
        result["pick"] = pick
    if line is not None:
        result["line"] = line
    if market:
        result["market"] = market
    return result if result else None


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
    if isinstance(items, dict) and items.get("status") == "fail" and items.get("restricted"):
        return None  # Signal restricted
    return evidence_services.clean_injuries(items)



def _display_injuries(items: list[dict]) -> list[dict]:
    if isinstance(items, dict) and items.get("status") == "fail" and items.get("restricted"):
        return None
    return evidence_services.display_injuries(items)


def _fetch_team_squad(team_id: int, season: int = SEASON, league_id: int | None = None) -> list[dict]:
    selected_league_id = _coerce_league_id(league_id if league_id is not None else _active_league_id())
    cache_key = f"squad:{team_id}:{season}:{selected_league_id}"
    if not hasattr(g, "_api_squad_cache"):
        g._api_squad_cache = {}
    if cache_key in g._api_squad_cache:
        return g._api_squad_cache[cache_key]
    getter = getattr(ac, "get_players", None)
    if callable(getter):
        try:
            data = getter(team_id, season, selected_league_id)
        except TypeError:
            data = getter(team_id, season)
        if data:
            g._api_squad_cache[cache_key] = data
            return data
    data = ac.get_squad(team_id, season, selected_league_id)
    g._api_squad_cache[cache_key] = data
    return data


def _group_squad_by_position(squad: list[dict]) -> dict[str, list[dict]]:
    grouped = {"Goalkeeper": [], "Defender": [], "Midfielder": [], "Attacker": []}
    for raw in squad or []:
        player = raw.get("player") if isinstance(raw, dict) and isinstance(raw.get("player"), dict) else raw
        if not isinstance(player, dict):
            continue
        position = str(player.get("position") or raw.get("position") or "Attacker").strip().title()
        if position not in grouped:
            if position in {"Forward", "Striker", "Winger"}:
                position = "Attacker"
            elif position in {"Centre-Back", "Center Back", "Fullback", "Wing Back"}:
                position = "Defender"
            elif position in {"Keeper", "Goalie"}:
                position = "Goalkeeper"
            else:
                position = "Midfielder"
        grouped[position].append(
            {
                "id": player.get("id"),
                "name": player.get("name", ""),
                "photo": player.get("photo", ""),
                "number": player.get("number"),
                "position": position,
            }
        )
    return grouped


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
    return bootstrap_services.football_supported_leagues(ac, LEAGUE_BY_ID)


def _critical_error(message: str, status_code: int = 503):
    return render_template("error.html", **_page_context(msg=message)), status_code


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_prediction_date(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Unknown"
    include_time = "T" in raw or (len(raw) > 10 and ":" in raw)
    for candidate in (raw, raw.replace("Z", "+00:00"), f"{raw[:10]}T00:00:00"):
        try:
            fmt = "%b %d, %Y %H:%M UTC" if include_time else "%b %d, %Y"
            return datetime.fromisoformat(candidate).strftime(fmt)
        except ValueError:
            continue
    return raw[:10]


def _normalize_team_name(name: str) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _natural_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _predicted_outcome_probability(record: dict) -> float | None:
    predicted_code = str(record.get("predicted_winner") or "").lower()
    mapping = {"a": "prob_a", "b": "prob_b", "draw": "prob_draw"}
    key = mapping.get(predicted_code)
    if not key:
        return None
    raw = record.get(key)
    return _safe_float(raw) if raw is not None else None


def _team_names_match(left: str, right: str) -> bool:
    a = _normalize_team_name(left)
    b = _normalize_team_name(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _fixture_finished(fixture: dict) -> bool:
    status = ((fixture.get("fixture") or {}).get("status") or {}).get("short", "")
    return str(status).upper() in {"FT", "AET", "PEN"}


def _parse_stat_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _format_stat_number(value: float | None, *, percent: bool = False) -> str:
    if value is None:
        return "N/A"
    if percent:
        return f"{round(value, 1)}%"
    if float(value).is_integer():
        return str(int(value))
    return str(round(value, 2))


def _prediction_pick_display(record: dict) -> str:
    if record.get("predicted_winner_display"):
        return str(record.get("predicted_winner_display") or "Unknown")
    if record.get("predicted_pick_label"):
        return str(record.get("predicted_pick_label") or "Unknown")
    winner_code = str(record.get("predicted_winner", "")).strip().lower()

    if winner_code == "a":
        return record.get("team_a", "Team A")
    if winner_code == "b":
        return record.get("team_b", "Team B")
    if winner_code == "draw":
        final_score = record.get("final_score_display") or "Unknown"
        return f"Match drawn {final_score}" if final_score != "Unknown" else "Match drawn"

    # Fallback to actual winner if available
    actual_winner = record.get("actual_winner")
    final_score = record.get("final_score_display") or "Unknown"
    if actual_winner:
        return f"{actual_winner} won {final_score}" if final_score != "Unknown" else actual_winner
    return "Unknown"


def _prepare_model_component_sections(record: dict) -> list[dict]:
    factors = record.get("model_factors") if isinstance(record.get("model_factors"), dict) else {}
    sections: list[dict] = []

    for team_key, title in (("team_a", record.get("team_a") or "Team A"), ("team_b", record.get("team_b") or "Team B")):
        team_factors = factors.get(team_key)
        if not isinstance(team_factors, dict):
            continue
        rows = [
            {"label": key.replace("_", " ").title(), "value": round(value, 2) if isinstance(value, float) else value}
            for key, value in team_factors.items()
        ]
        if rows:
            sections.append({"title": f"{title} model components", "rows": rows})

    general_rows = [
        {"label": key.replace("_", " ").title(), "value": round(value, 2) if isinstance(value, float) else value}
        for key, value in factors.items()
        if not isinstance(value, dict)
    ]
    if general_rows:
        sections.insert(0, {"title": "Model factors", "rows": general_rows})
    return sections


def _actual_outcome_probability(record: dict) -> float | None:
    actual_code = str(record.get("actual_result") or "").lower()
    mapping = {"a": "prob_a", "b": "prob_b", "draw": "prob_draw"}
    key = mapping.get(actual_code)
    if not key:
        return None
    raw = record.get(key)
    return _safe_float(raw) if raw is not None else None


def _format_percent_value(value: float | None) -> str | None:
    if value is None:
        return None
    rounded = round(value, 1)
    return f"{int(rounded)}%" if float(rounded).is_integer() else f"{rounded}%"


def _outcome_range_label(actual_prob: float | None) -> str | None:
    if actual_prob is None:
        return None
    if actual_prob <= 25:
        return "Major upset"
    if actual_prob <= 40:
        return "Notable upset"
    return "Expected range"


def _score_margin_from_display(final_score_display: str | None) -> int | None:
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", str(final_score_display or ""))
    if not m:
        return None
    return abs(int(m.group(1)) - int(m.group(2)))


def _summarize_injury_context(injuries: dict[str, dict]) -> str | None:
    if not injuries:
        return None

    segments = []
    for team_name, row in injuries.items():
        count = _safe_int((row or {}).get("count"))
        notable = [str(name).strip() for name in (row or {}).get("notable") or [] if str(name).strip()]
        if count <= 0 and not notable:
            continue
        if notable:
            notable_names = _natural_join(notable[:2])
            if count > len(notable):
                segments.append(f"{team_name} had {count} listed absences, including {notable_names}")
            else:
                segments.append(f"{team_name} were missing {notable_names}")
        else:
            segments.append(f"{team_name} had {count} listed absences")

    if not segments:
        return None
    return f"Injury context: {'; '.join(segments)}."


def _build_evidence_summary(
    record: dict,
    evidence_layer: str,
    *,
    form_compare: dict[str, dict] | None = None,
    injuries: dict[str, dict] | None = None,
    extra_points: list[str] | None = None,
) -> tuple[list[dict], list[str], str]:
    sport = str(record.get("sport") or "").lower()
    predicted_pick = _prediction_pick_display(record)
    predicted_prob = _predicted_outcome_probability(record)
    actual_prob = _actual_outcome_probability(record)
    upset_label = _outcome_range_label(actual_prob)
    actual_winner = record.get("actual_winner") or "Unknown"
    final_score = record.get("final_score_display") or "Unknown"
    winner_hit = record.get("winner_hit")
    winner_leg = "Hit" if winner_hit is True else "Miss" if winner_hit is False else "Pending"
    totals_pick = record.get("totals_pick_display")
    totals_hit = record.get("ou_hit")
    totals_leg = "Hit" if totals_hit is True else "Miss" if totals_hit is False else "Pending"
    total_scored = record.get("total_scored")
    actual_total_side = record.get("actual_total_side")
    confidence = record.get("confidence") or "Unknown"
    score_margin = _score_margin_from_display(final_score)
    is_soccer = sport == "soccer"
    measure_label = "goal" if is_soccer else "point"
    total_label = measure_label if total_scored == 1 else f"{measure_label}s"

    layer_labels = {
        "stats": "Full match stats",
        "events": "Match events",
        "summary": "Evidence summary",
    }
    summary_rows = [
        {"label": "Evidence Layer", "value": layer_labels.get(evidence_layer, "Evidence summary")},
        {"label": "Final Score", "value": final_score},
        {"label": "Actual Winner", "value": actual_winner},
    ]

    winner_value = f"{winner_leg} · {predicted_pick}"
    predicted_prob_text = _format_percent_value(predicted_prob)
    if predicted_prob_text:
        winner_value += f" · Model {predicted_prob_text}"
    summary_rows.append({"label": "Winner Leg", "value": winner_value})

    if totals_pick:
        totals_value = f"{totals_leg} · {totals_pick}"
        if total_scored is not None:
            totals_value += f" · {total_scored} {total_label}"
            if actual_total_side:
                totals_value += f" · {actual_total_side}"
        summary_rows.append({"label": "Totals Leg", "value": totals_value})

    if upset_label:
        outcome_value = upset_label
        actual_prob_text = _format_percent_value(actual_prob)
        if actual_prob_text:
            outcome_value += f" · {actual_winner} closed at {actual_prob_text}"
        summary_rows.append({"label": "Outcome Context", "value": outcome_value})

    summary_rows.append({"label": "Confidence", "value": confidence})

    summary_points = [point for point in (extra_points or []) if point]

    if winner_hit is True:
        if predicted_prob_text:
            summary_points.append(
                f"The winner leg aligned with the pre-match expectation: {predicted_pick} carried {predicted_prob_text} and got the result."
            )
        else:
            summary_points.append(f"The winner leg aligned with the pre-match expectation: {predicted_pick} got the result.")
    elif winner_hit is False:
        narrow_margin = (is_soccer and score_margin is not None and score_margin <= 1) or (
            not is_soccer and score_margin is not None and score_margin <= 6
        )
        if actual_prob is not None and actual_prob <= 25:
            summary_points.append(
                f"The winner leg missed on a genuine upset: {actual_winner} was only {_format_percent_value(actual_prob)} in the pre-match model."
            )
        elif narrow_margin and score_margin is not None:
            summary_points.append(
                f"The winner leg was a narrow miss: the model backed {predicted_pick}, but the game turned on a {score_margin}-{measure_label} margin."
            )
        else:
            summary_points.append(
                f"The winner leg missed: the model backed {predicted_pick}, but {actual_winner} ended up taking the result."
            )

    if totals_pick and total_scored is not None:
        totals_line = record.get("totals_line")
        try:
            totals_line = float(totals_line) if totals_line is not None else None
        except (TypeError, ValueError):
            totals_line = None

        if totals_hit is True:
            summary_points.append(
                f"The totals leg aligned with expectation: {totals_pick} matched a {total_scored}-{measure_label} game."
            )
        elif totals_hit is False:
            if totals_line is not None and abs(float(total_scored) - totals_line) <= 0.5:
                summary_points.append(
                    f"The totals leg was a narrow miss: {totals_pick} was one score away from landing."
                )
            else:
                summary_points.append(
                    f"The totals leg missed decisively: {totals_pick} did not match the {actual_total_side or 'final'} finish."
                )

    form_sentence = _summarize_form_compare(form_compare or {}, actual_winner=actual_winner)
    if form_sentence:
        summary_points.append(form_sentence)

    injury_sentence = _summarize_injury_context(injuries or {})
    if injury_sentence:
        summary_points.append(injury_sentence)

    if not summary_points:
        summary_points.append(f"Final result recorded at {final_score} with {confidence} model confidence.")

    summary_points = summary_points[:4]
    return summary_rows, summary_points, " ".join(summary_points)


def _build_soccer_key_events(raw_events: list[dict]) -> list[dict]:
    events = []
    seen = set()
    for event in raw_events[:60]:
        event_type = str(event.get("type") or "").strip()
        detail = str(event.get("detail") or event.get("comments") or "").strip()
        detail_lower = detail.lower()

        if event_type == "Goal":
            if "own goal" in detail_lower:
                display_type = "Own Goal"
            elif "penalty" in detail_lower:
                display_type = "Penalty Goal"
            else:
                display_type = "Goal"
        elif event_type == "Card":
            if "red" not in detail_lower:
                continue
            display_type = "Red Card"
        elif event_type == "Var":
            display_type = "VAR"
        else:
            continue

        elapsed = ((event.get("time") or {}).get("elapsed"))
        extra = ((event.get("time") or {}).get("extra"))
        if elapsed is None:
            elapsed_display = ""
        elif extra not in (None, "", 0):
            elapsed_display = f"{elapsed}+{extra}'"
        else:
            elapsed_display = f"{elapsed}'"

        player_name = ((event.get("player") or {}).get("name") or "")
        team_name = ((event.get("team") or {}).get("name") or "")
        dedupe_key = (elapsed_display, display_type, team_name, player_name, detail)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        events.append(
            {
                "minute": elapsed_display,
                "type": display_type,
                "team": team_name,
                "player": player_name,
                "detail": detail,
            }
        )
        if len(events) >= 8:
            break
    return events


def _build_prediction_vs_reality(record: dict, evidence_summary: str | None = None) -> dict:
    confidence = record.get("confidence") or "Unknown"
    winner_hit = bool(record.get("winner_hit")) if record.get("status") == "completed" else None
    winner_leg = "Hit" if winner_hit is True else "Miss" if winner_hit is False else "Pending"
    totals_required = bool(record.get("totals_required"))
    totals_hit = record.get("ou_hit")
    totals_leg = "Hit" if totals_hit is True else "Miss" if totals_hit is False else ("Not tracked" if not totals_required else "Pending")
    total_unit = "goals" if str(record.get("sport") or "").lower() == "soccer" else "points"

    upset_label = None
    actual_prob = _actual_outcome_probability(record)
    if actual_prob is not None:
        upset_label = _outcome_range_label(actual_prob)

    predicted_prob = _predicted_outcome_probability(record)
    actual_total = record.get("total_scored")
    if actual_total is not None:
        total_label = total_unit[:-1] if actual_total == 1 and total_unit.endswith("s") else total_unit
        reality_text = f"{record.get('actual_winner') or 'Unknown'}, {record.get('final_score_display') or 'Unknown'}, {actual_total} {total_label}"
    else:
        reality_text = _reality_sentence(record)

    return {
        "winner_pick": _prediction_sentence(record),
        "totals_pick": record.get("totals_pick_display"),
        "reality_text": reality_text,
        "winner_leg": winner_leg,
        "totals_leg": totals_leg,
        "overall_result": record.get("overall_game_result") or ("Win" if record.get("game_win") else "Loss"),
        "confidence": confidence,
        "upset_label": upset_label,
        "predicted_outcome_probability": predicted_prob,
        "actual_outcome_probability": actual_prob,
        "evidence_summary": evidence_summary or "Limited evidence available from the current data providers.",
    }


def _pick_stat_from_row(team_row: dict, aliases: list[str]) -> float | None:
    wanted = {alias.lower() for alias in aliases}
    for stat in team_row.get("statistics") or []:
        stat_type = str(stat.get("type") or "").strip().lower()
        if stat_type in wanted:
            return _parse_stat_value(stat.get("value"))
    return None


def _soccer_form_snapshot(team_id: int, league_id: int) -> dict | None:
    fixtures = ac.get_team_fixtures(team_id, league_id, SEASON, last=10)
    recent = pred.extract_form(pred.filter_recent_completed_fixtures(fixtures, current_season=SEASON), team_id)[:5]
    if not recent:
        return None
    return {
        "matches": len(recent),
        "wins": sum(1 for row in recent if row.get("result") == "W"),
        "draws": sum(1 for row in recent if row.get("result") == "D"),
        "losses": sum(1 for row in recent if row.get("result") == "L"),
        "avg_goals_for": round(sum(_safe_float(row.get("gf")) for row in recent) / len(recent), 2),
        "avg_goals_against": round(sum(_safe_float(row.get("ga")) for row in recent) / len(recent), 2),
    }


def _build_soccer_evidence(record: dict) -> dict:
    evidence = {
        "sport": "soccer",
        "available": False,
        "evidence_layer": "summary",
        "evidence_layer_label": "Evidence summary",
        "metrics": [],
        "key_events": [],
        "summary_rows": [],
        "summary_points": [],
        "goal_scorers": {
            "available": False,
            "home_team": record.get("team_a") or "Home",
            "away_team": record.get("team_b") or "Away",
            "home_goals": [],
            "away_goals": [],
        },
        "player_impacts": [],
        "injuries": {},
        "form_compare": {},
        "notes": [],
        "summary": "",
        "fixture_context": {},
    }

    league_id = _coerce_league_id(record.get("league_id"), default=DEFAULT_LEAGUE_ID)
    target_date = str(record.get("game_date") or record.get("date") or "")[:10]
    team_a_name = str(record.get("team_a") or "")
    team_b_name = str(record.get("team_b") or "")

    teams = ac.get_teams(league_id, SEASON)

    team_a = _resolve_provider_team_by_name(team_a_name, teams)
    team_b = _resolve_provider_team_by_name(team_b_name, teams)
    team_a_id = _safe_int((team_a or {}).get("id"))
    team_b_id = _safe_int((team_b or {}).get("id"))

    fixture = None
    fixture_id = _safe_int(record.get("fixture_id"))
    if fixture_id:
        fixture = ac.get_fixture_by_id(fixture_id) or None

    if team_a_id and team_b_id and not fixture:
        h2h_candidates = ac.get_h2h(team_a_id, team_b_id, last=20)

        for item in h2h_candidates:
            if not _fixture_finished(item):
                continue
            fixture_date = str((item.get("fixture") or {}).get("date") or "")[:10]
            home_name = ((item.get("teams") or {}).get("home") or {}).get("name", "")
            away_name = ((item.get("teams") or {}).get("away") or {}).get("name", "")
            names_match = (
                (_team_names_match(team_a_name, home_name) and _team_names_match(team_b_name, away_name))
                or (_team_names_match(team_a_name, away_name) and _team_names_match(team_b_name, home_name))
            )
            if not names_match:
                continue
            if target_date and fixture_date != target_date:
                continue
            fixture = item
            break

        if fixture is None:
            for item in h2h_candidates:
                if not _fixture_finished(item):
                    continue
                home_name = ((item.get("teams") or {}).get("home") or {}).get("name", "")
                away_name = ((item.get("teams") or {}).get("away") or {}).get("name", "")
                names_match = (
                    (_team_names_match(team_a_name, home_name) and _team_names_match(team_b_name, away_name))
                    or (_team_names_match(team_a_name, away_name) and _team_names_match(team_b_name, home_name))
                )
                if names_match:
                    fixture = item
                    break

    if not fixture_id and fixture:
        fixture_id = _safe_int((fixture.get("fixture") or {}).get("id"))

    stats_rows = []
    raw_events = []
    if fixture_id:
        try:
            stats_rows = ac.get_fixture_stats(fixture_id)
        except Exception:
            stats_rows = []
        try:
            raw_events = ac.get_fixture_events(fixture_id)
        except Exception:
            raw_events = []
        try:
            goal_scorers = ac.get_match_events(fixture_id)
            expected_goals = _safe_int(record.get("total_scored"))
            actual_goal_rows = len(goal_scorers.get("home_goals") or []) + len(goal_scorers.get("away_goals") or [])
            goal_scorers["available"] = bool(expected_goals > 0 and actual_goal_rows == expected_goals)
            if not goal_scorers.get("home_team"):
                goal_scorers["home_team"] = team_a_name
            if not goal_scorers.get("away_team"):
                goal_scorers["away_team"] = team_b_name
            evidence["goal_scorers"] = goal_scorers
        except Exception:
            pass

    team_a_row = next(
        (row for row in stats_rows if _team_names_match((row.get("team") or {}).get("name", ""), team_a_name)),
        {},
    )
    team_b_row = next(
        (row for row in stats_rows if _team_names_match((row.get("team") or {}).get("name", ""), team_b_name)),
        {},
    )

    metric_specs = [
        ("Possession", ["Ball Possession", "Possession"], True, True),
        ("Shots", ["Total Shots", "Shots"], False, True),
        ("Shots on Target", ["Shots on Goal", "Shots on Target"], False, True),
        ("xG", ["Expected Goals", "xG"], False, True),
        ("Corners", ["Corner Kicks", "Corners"], False, True),
        ("Fouls", ["Fouls", "Fouls Committed"], False, False),
        ("Yellow Cards", ["Yellow Cards"], False, False),
        ("Red Cards", ["Red Cards"], False, False),
    ]

    metrics = []
    support_score = 0
    for label, aliases, is_percent, higher_is_better in metric_specs:
        a_val = _pick_stat_from_row(team_a_row, aliases) if team_a_row else None
        b_val = _pick_stat_from_row(team_b_row, aliases) if team_b_row else None
        if a_val is None and b_val is None:
            continue

        leader = "Even"
        if a_val is not None and b_val is not None and a_val != b_val:
            a_better = a_val > b_val if higher_is_better else a_val < b_val
            leader = team_a_name if a_better else team_b_name
        elif a_val is not None and b_val is None:
            leader = team_a_name
        elif b_val is not None and a_val is None:
            leader = team_b_name

        actual_winner_code = str(record.get("actual_result") or "").lower()
        if actual_winner_code in {"a", "b"} and leader != "Even":
            winner_name = team_a_name if actual_winner_code == "a" else team_b_name
            support_score += 1 if leader == winner_name else -1

        metrics.append(
            {
                "label": label,
                "team_a": _format_stat_number(a_val, percent=is_percent),
                "team_b": _format_stat_number(b_val, percent=is_percent),
                "leader": leader,
            }
        )

    events = _build_soccer_key_events(raw_events)

    player_impacts = []
    if fixture_id:
        try:
            player_rows = ac.get_fixture_players(fixture_id)
        except Exception:
            player_rows = []

        for team_entry in player_rows:
            team_name = ((team_entry.get("team") or {}).get("name") or "")
            for player in team_entry.get("players") or []:
                player_name = ((player.get("player") or {}).get("name") or "")
                stat = (player.get("statistics") or [{}])[0]
                goals = _safe_int((stat.get("goals") or {}).get("total"))
                assists = _safe_int((stat.get("goals") or {}).get("assists"))
                shots_on = _safe_int((stat.get("shots") or {}).get("on"))
                rating = _safe_float((stat.get("games") or {}).get("rating"), default=0.0)
                impact = goals * 4 + assists * 3 + shots_on + (rating / 10)
                if impact <= 0:
                    continue
                player_impacts.append(
                    {
                        "name": player_name,
                        "team": team_name,
                        "goals": goals,
                        "assists": assists,
                        "shots_on": shots_on,
                        "rating": round(rating, 2) if rating else None,
                        "impact": round(impact, 2),
                    }
                )

    player_impacts.sort(key=lambda row: row.get("impact", 0), reverse=True)
    player_impacts = player_impacts[:6]

    form_compare = {}
    if team_a_id:
        snapshot = _soccer_form_snapshot(team_a_id, league_id)
        if snapshot:
            form_compare[team_a_name] = snapshot
    if team_b_id:
        snapshot = _soccer_form_snapshot(team_b_id, league_id)
        if snapshot:
            form_compare[team_b_name] = snapshot

    injuries = {}
    for team_name, team_id in ((team_a_name, team_a_id), (team_b_name, team_b_id)):
        if not team_id:
            continue
        try:
            items = _display_injuries(ac.get_injuries(league_id, SEASON, team_id))
        except Exception:
            items = []
        injuries[team_name] = {
            "count": len(items),
            "notable": [row.get("name") for row in items[:4] if row.get("name")],
        }

    injuries = _filter_useful_injury_context(injuries)

    actual_winner = record.get("actual_winner") or "Unknown"
    winner_support = [row["label"] for row in metrics if row.get("leader") == actual_winner][:3]
    decisive_goal = None
    if actual_winner == team_a_name:
        decisive_goal = (evidence["goal_scorers"].get("home_goals") or [None])[0]
    elif actual_winner == team_b_name:
        decisive_goal = (evidence["goal_scorers"].get("away_goals") or [None])[0]

    stats_available = bool(metrics)
    events_available = bool(events or evidence["goal_scorers"].get("available"))
    evidence_layer = "stats" if stats_available else "events" if events_available else "summary"

    extra_points = []
    if actual_winner == "Draw":
        if stats_available:
            extra_points.append(
                f"The match finished level at {record.get('final_score_display') or '0-0'}, and the available match stats did not show a decisive edge for either side."
            )
        elif events_available:
            extra_points.append(
                f"The result settled at {record.get('final_score_display') or '0-0'}, with the event feed showing the main swing moments rather than a full stat profile."
            )
    elif winner_support:
        extra_points.append(f"Match stats backed {actual_winner} through {_natural_join(winner_support)}.")
    elif stats_available and support_score < 0:
        extra_points.append(
            f"The match stats were mixed and did not cleanly support {actual_winner}, which points to a clinical or swing-moment result rather than full control."
        )
    elif stats_available:
        extra_points.append(
            f"The available match stats showed a narrow edge for {actual_winner} rather than one-way control."
        )

    if decisive_goal and decisive_goal.get("player"):
        goal_text = f"The decisive scoring moment came from {decisive_goal['player']} at {decisive_goal['minute']}"
        if decisive_goal.get("type") not in {"Goal", ""}:
            goal_text += f" ({str(decisive_goal['type']).lower()})"
        extra_points.append(goal_text + ".")

    if not stats_available and events:
        event_labels = [row.get("type") for row in events[:3] if row.get("type")]
        if event_labels:
            extra_points.append(
                f"When full match stats were unavailable, the event feed still captured the key turns through {_natural_join(event_labels)}."
            )

    summary_rows, summary_points, summary = _build_evidence_summary(
        record,
        evidence_layer,
        form_compare=form_compare,
        injuries=injuries,
        extra_points=extra_points,
    )

    evidence.update(
        {
            "available": bool(summary_rows or metrics or events or player_impacts or evidence["goal_scorers"].get("available")),
            "evidence_layer": evidence_layer,
            "evidence_layer_label": {
                "stats": "Full match stats",
                "events": "Match events",
                "summary": "Evidence summary",
            }.get(evidence_layer, "Evidence summary"),
            "metrics": metrics,
            "key_events": events,
            "player_impacts": player_impacts,
            "injuries": injuries,
            "form_compare": form_compare,
            "summary_rows": summary_rows,
            "summary_points": summary_points,
            "summary": summary,
            "fixture_context": {
                "fixture_id": fixture_id if fixture_id else None,
                "fixture_date": str(((fixture or {}).get("fixture") or {}).get("date") or "")[:10],
            },
        }
    )
    return evidence


def _build_nba_evidence(record: dict) -> dict:
    evidence = {
        "sport": "nba",
        "available": False,
        "evidence_layer": "summary",
        "evidence_layer_label": "Evidence summary",
        "metrics": [],
        "key_events": [],
        "summary_rows": [],
        "summary_points": [],
        "goal_scorers": {
            "available": False,
            "home_team": record.get("team_a") or "Home",
            "away_team": record.get("team_b") or "Away",
            "home_goals": [],
            "away_goals": [],
        },
        "player_impacts": [],
        "injuries": {},
        "form_compare": {},
        "notes": [],
        "summary": "",
    }

    if nc is None or np_nba is None:
        summary_rows, summary_points, summary = _build_evidence_summary(
            record,
            "summary",
            extra_points=["Live NBA providers were not configured, so this page falls back to tracked result data only."],
        )
        evidence.update(
            {
                "available": True,
                "summary_rows": summary_rows,
                "summary_points": summary_points,
                "summary": summary,
            }
        )
        return evidence

    team_a_name = str(record.get("team_a") or "")
    team_b_name = str(record.get("team_b") or "")
    target_date = str(record.get("game_date") or record.get("date") or "")[:10]

    candidate_days = []
    if target_date:
        try:
            candidate_days.append(datetime.fromisoformat(target_date))
        except ValueError:
            pass
    candidate_days.extend([datetime.now() - timedelta(days=1), datetime.now(), datetime.now() + timedelta(days=1)])

    matched_game = None
    fixture_id = str(record.get("fixture_id") or "").strip()
    if fixture_id:
        try:
            matched_game = nc.get_event_snapshot(fixture_id, date_hint=target_date)
        except Exception:
            matched_game = None

    seen_ids = set()
    for day in candidate_days:
        if matched_game:
            break
        try:
            games = nc.get_scoreboard_games(day)
        except Exception:
            games = []
        for game in games:
            game_id = str(game.get("id") or "")
            if game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            home_name = ((game.get("teams") or {}).get("home") or {}).get("name", "")
            away_name = ((game.get("teams") or {}).get("visitors") or {}).get("name", "")
            names_match = (
                (_team_names_match(team_a_name, home_name) and _team_names_match(team_b_name, away_name))
                or (_team_names_match(team_a_name, away_name) and _team_names_match(team_b_name, home_name))
            )
            if not names_match:
                continue
            game_date = str((game.get("date") or {}).get("start") or "")[:10]
            if target_date and game_date != target_date:
                continue
            matched_game = game
            break
        if matched_game:
            break

    if not matched_game:
        summary_rows, summary_points, summary = _build_evidence_summary(
            record,
            "summary",
            extra_points=["Detailed scoreboard evidence for this game was unavailable in the current NBA feeds."],
        )
        evidence.update(
            {
                "available": True,
                "summary_rows": summary_rows,
                "summary_points": summary_points,
                "summary": summary,
            }
        )
        return evidence

    teams = matched_game.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("visitors") or {}

    is_a_home = _team_names_match(team_a_name, home.get("name", ""))
    scores = matched_game.get("scores") or {}
    home_pts = _safe_int((scores.get("home") or {}).get("points"))
    away_pts = _safe_int((scores.get("visitors") or {}).get("points"))
    a_pts = home_pts if is_a_home else away_pts
    b_pts = away_pts if is_a_home else home_pts

    evidence["metrics"].append({"label": "Final Points", "team_a": str(a_pts), "team_b": str(b_pts), "leader": team_a_name if a_pts > b_pts else team_b_name})

    team_a_id = str(home.get("id") if is_a_home else away.get("id") or "")
    team_b_id = str(away.get("id") if is_a_home else home.get("id") or "")

    for label, field in (("PPG", "ppg"), ("Opp PPG", "opp_ppg"), ("Net Rating", "net_rtg")):
        try:
            stats_a = nc.get_team_season_stats(team_a_id)
        except Exception:
            stats_a = None
        try:
            stats_b = nc.get_team_season_stats(team_b_id)
        except Exception:
            stats_b = None
        a_val = stats_a.get(field) if isinstance(stats_a, dict) else None
        b_val = stats_b.get(field) if isinstance(stats_b, dict) else None
        if a_val is None and b_val is None:
            continue
        evidence["metrics"].append(
            {
                "label": label,
                "team_a": _format_stat_number(_safe_float(a_val) if a_val is not None else None),
                "team_b": _format_stat_number(_safe_float(b_val) if b_val is not None else None),
                "leader": team_a_name if _safe_float(a_val, -9999) > _safe_float(b_val, -9999) else team_b_name,
            }
        )

    leaders = matched_game.get("leaders") or {}
    if is_a_home:
        a_leaders = leaders.get("home") or []
        b_leaders = leaders.get("visitors") or []
    else:
        a_leaders = leaders.get("visitors") or []
        b_leaders = leaders.get("home") or []

    for side_name, side_leaders in ((team_a_name, a_leaders), (team_b_name, b_leaders)):
        for leader in side_leaders:
            top = (leader.get("leaders") or [{}])[0]
            athlete = top.get("athlete") or {}
            evidence["player_impacts"].append(
                {
                    "name": athlete.get("displayName") or athlete.get("fullName") or "",
                    "team": side_name,
                    "metric": leader.get("displayName") or leader.get("name") or "",
                    "value": top.get("displayValue") or "",
                }
            )

    evidence["player_impacts"] = [row for row in evidence["player_impacts"] if row.get("name")][:6]

    for name, team_id in ((team_a_name, team_a_id), (team_b_name, team_b_id)):
        if not team_id:
            continue
        try:
            injuries = nc.get_team_injuries(team_id)
        except Exception:
            injuries = []
        evidence["injuries"][name] = {
            "count": len(injuries),
            "notable": [
                " ".join(filter(None, [
                    (row.get("player") or {}).get("firstname"),
                    (row.get("player") or {}).get("lastname"),
                ])).strip()
                for row in injuries[:4]
            ],
        }

        try:
            raw_form = nc.get_team_recent_form(team_id, n=5)
            extracted = np_nba.extract_recent_form(raw_form, team_id, n=5)
        except Exception:
            extracted = []
        if extracted:
            evidence["form_compare"][name] = {
                "matches": len(extracted),
                "wins": sum(1 for row in extracted if row.get("result") == "W"),
                "losses": sum(1 for row in extracted if row.get("result") == "L"),
                "avg_points_for": round(sum(_safe_float(row.get("our_pts")) for row in extracted) / len(extracted), 2),
                "avg_points_against": round(sum(_safe_float(row.get("their_pts")) for row in extracted) / len(extracted), 2),
            }

    evidence["injuries"] = _filter_useful_injury_context(evidence["injuries"])
    evidence_layer = "stats" if evidence["metrics"] else "summary"
    extra_points = []
    if evidence["metrics"]:
        extra_points.append("Available scoreboard data and season-profile metrics explain how the final result landed.")
    if evidence["player_impacts"]:
        extra_points.append("Top individual leaders from the live feed are included below to show where the production came from.")

    summary_rows, summary_points, summary = _build_evidence_summary(
        record,
        evidence_layer,
        form_compare=evidence["form_compare"],
        injuries=evidence["injuries"],
        extra_points=extra_points,
    )

    evidence.update(
        {
            "available": bool(summary_rows or evidence["metrics"] or evidence["player_impacts"]),
            "evidence_layer": evidence_layer,
            "evidence_layer_label": {
                "stats": "Full match stats",
                "summary": "Evidence summary",
            }.get(evidence_layer, "Evidence summary"),
            "summary_rows": summary_rows,
            "summary_points": summary_points,
            "summary": summary,
        }
    )
    return evidence


def _clear_selected_matchup() -> None:
    for key in (
        "team_a_id",
        "team_a_name",
        "team_a_logo",
        "team_b_id",
        "team_b_name",
        "team_b_logo",
        "selected_fixture",
    ):
        session.pop(key, None)


def _coerce_league_id(value, default: int = DEFAULT_LEAGUE_ID) -> int:
    league_id = _safe_int(value, default)
    if league_id not in SUPPORTED_LEAGUE_IDS:
        return default
    return league_id


def _active_league_id() -> int:
    requested = request.args.get("league")
    if requested is None:
        requested = request.args.get("league_id")
    if requested is None:
        requested = request.form.get("league_id")

    if requested is not None and str(requested).strip() != "":
        return _coerce_league_id(requested)

    return _coerce_league_id(session.get(LEAGUE_SESSION_KEY), DEFAULT_LEAGUE_ID)


def _set_active_league(league_id: int) -> int:
    normalized = _coerce_league_id(league_id)
    previous = _coerce_league_id(session.get(LEAGUE_SESSION_KEY), DEFAULT_LEAGUE_ID)
    session[LEAGUE_SESSION_KEY] = normalized
    if previous != normalized:
        _clear_selected_matchup()
    return normalized


def _league_context(league_id: int | None = None) -> dict:
    selected_id = _coerce_league_id(league_id if league_id is not None else _active_league_id())
    selected_cfg = LEAGUE_BY_ID.get(selected_id, LEAGUE_BY_ID.get(DEFAULT_LEAGUE_ID, {}))
    return {
        "supported_leagues": _football_supported_leagues(),
        "current_league_id": selected_id,
        "current_league": selected_cfg,
    }


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
            p.get("league_id"),
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

        league_id = (fixture.get("league") or {}).get("id") or DEFAULT_LEAGUE_ID
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
        game_key = mt._get_game_key("soccer", fixture_date, home_name, away_name, league_id)
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
                league_id=league_id,
                league_name=(LEAGUE_BY_ID.get(league_id) or {}).get("name"),
                prediction_notes=best_pick.get("reasoning"),
                model_factors={
                    "team_a": prediction.get("components_a") if isinstance(prediction.get("components_a"), dict) else {},
                    "team_b": prediction.get("components_b") if isinstance(prediction.get("components_b"), dict) else {},
                },
                fixture_id=(fixture.get("fixture") or {}).get("id"),
                totals_pick=((_extract_totals_leg(prediction) or {}).get("pick")),
                totals_line=((_extract_totals_leg(prediction) or {}).get("line")),
                totals_market=((_extract_totals_leg(prediction) or {}).get("market")),
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
                    prediction_notes=best_pick.get("reasoning"),
                    model_factors={
                        "team_a": prediction.get("components_a") if isinstance(prediction.get("components_a"), dict) else {},
                        "team_b": prediction.get("components_b") if isinstance(prediction.get("components_b"), dict) else {},
                    },
                    fixture_id=game.get("id"),
                    totals_pick=((_extract_totals_leg(prediction) or {}).get("pick")),
                    totals_line=((_extract_totals_leg(prediction) or {}).get("line")),
                    totals_market=((_extract_totals_leg(prediction) or {}).get("market")),
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
    if request.endpoint in {None, "static", "health"}:
        return
    today_str = date.today().strftime("%Y-%m-%d")
    if app.config.get("TRACKING_LAST_BOOTSTRAP") == today_str:
        return
    # Mark immediately so subsequent requests don't also trigger bootstrap
    app.config["TRACKING_LAST_BOOTSTRAP"] = today_str
    import threading
    def _run():
        try:
            with app.app_context():
                _ensure_model_tracking()
        except Exception as exc:
            app.logger.debug("Daily tracking check failed: %s", exc, exc_info=True)
    threading.Thread(target=_run, daemon=True).start()



def _resolve_provider_team_by_name(name: str, teams: list[dict]) -> dict | None:
    return bootstrap_services.resolve_provider_team_by_name(name, teams)


def _selected_fixture() -> dict:
    return bootstrap_services.selected_fixture(session)



def _load_upcoming_fixtures(next_n: int = 20, max_deep_predictions: int = 40, league: int = None):
    return evidence_services.load_upcoming_fixtures(
        ac,
        pred,
        se,
        league=league if league is not None else LEAGUE,
        season=SEASON,
        logger=app.logger,
        football_data_source=_football_data_source,
        next_n=next_n,
        max_deep_predictions=max_deep_predictions,
    )
    fixtures_with_pred = []
    data_source = _football_data_source()

    try:
        upcoming = ac.get_upcoming_fixtures(selected_league_id, SEASON, next_n=next_n)
    except Exception as exc:
        upcoming = []
        load_error = str(exc)
        app.logger.error("Upcoming fixtures fetch failed: %s", exc)

    standings_cache: dict[int, list[dict]] = {}

    for fixture in upcoming:
        try:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            home_name = fixture["teams"]["home"]["name"]
            away_name = fixture["teams"]["away"]["name"]
            fixture_league_id = _safe_int((fixture.get("league") or {}).get("id"), selected_league_id)
            if fixture_league_id not in standings_cache:
                try:
                    standings_cache[fixture_league_id] = ac.get_standings(fixture_league_id, SEASON)
                except Exception as exc:
                    standings_cache[fixture_league_id] = []
                    app.logger.warning("Standings unavailable for league=%s: %s", fixture_league_id, exc)

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
                fixtures_home = _recent_team_fixtures_all_comps(home_id, fixture_league_id, season=SEASON, last=10)
            except Exception:
                app.logger.debug("Upcoming fixture home team form missing for %s", home_name)
            try:
                fixtures_away = _recent_team_fixtures_all_comps(away_id, fixture_league_id, season=SEASON, last=10)
            except Exception:
                app.logger.debug("Upcoming fixture away team form missing for %s", away_name)
            try:
                injuries_home = _clean_injuries(ac.get_injuries(fixture_league_id, SEASON, home_id))
            except Exception:
                app.logger.debug("Upcoming fixture home injuries missing for %s", home_name)
            try:
                injuries_away = _clean_injuries(ac.get_injuries(fixture_league_id, SEASON, away_id))
            except Exception:
                app.logger.debug("Upcoming fixture away injuries missing for %s", away_name)

            h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)

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
                opp_strengths=_build_opp_strengths(standings_cache.get(fixture_league_id, [])),
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


def _prediction_confidence_rank(item: dict) -> tuple[int, float]:
    pred = item.get("prediction", {})
    best_pick = pred.get("best_pick", {})
    conf = best_pick.get("confidence", "Low")
    conf_map = {"High": 0, "Medium": 1, "Low": 2}
    prob_gap = abs(
        pred.get("win_probabilities", {}).get("a", 0.5)
        - pred.get("win_probabilities", {}).get("b", 0.5)
    )
    return (conf_map.get(conf, 3), -prob_gap)


def _load_grouped_upcoming_fixtures_all_leagues(next_n_per_league: int = 8):
    grouped_fixtures: list[dict] = []
    all_fixtures: list[dict] = []
    load_errors: list[str] = []
    data_sources: set[str] = set()

    # Fetch all leagues concurrently to avoid sequential 15s-per-league stalls
    with ThreadPoolExecutor(max_workers=min(6, len(SUPPORTED_LEAGUE_IDS))) as executor:
        future_to_league = {
            executor.submit(_load_upcoming_fixtures, next_n=next_n_per_league, league=lid): lid
            for lid in SUPPORTED_LEAGUE_IDS
        }
        league_results: dict[int, tuple] = {}
        for future in future_to_league:
            lid = future_to_league[future]
            try:
                league_results[lid] = future.result()
            except Exception as exc:
                _logger.warning("Fixture fetch failed for league %s: %s", lid, exc)
                league_results[lid] = ([], str(exc), _football_data_source(), None)

    for league_id in SUPPORTED_LEAGUE_IDS:
        fixtures, load_error, data_source, _ = league_results.get(league_id, ([], None, _football_data_source(), None))
        data_sources.add(data_source)
        if load_error:
            league_name = (LEAGUE_BY_ID.get(league_id) or {}).get("name", f"League {league_id}")
            load_errors.append(f"{league_name}: {load_error}")

        fixtures = sorted(fixtures or [], key=_prediction_confidence_rank)
        league_info = LEAGUE_BY_ID.get(league_id, {})
        grouped_fixtures.append(
            {
                "league_id": league_id,
                "league_name": league_info.get("name", f"League {league_id}"),
                "league_flag": league_info.get("flag", ""),
                "fixtures": fixtures,
            }
        )
        all_fixtures.extend(fixtures)

    all_fixtures.sort(key=_prediction_confidence_rank)
    data_source = "Multiple providers" if len(data_sources) > 1 else (next(iter(data_sources)) if data_sources else _football_data_source())
    return all_fixtures, grouped_fixtures, " | ".join(load_errors), data_source


def _require_teams():

    return bootstrap_services.require_teams(session)


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


def _store_selected_teams(
    team_a: dict,
    team_b: dict,
    fixture_context: dict | None = None,
    league_id: int | None = None,
) -> None:
    selected_league_id = _coerce_league_id(league_id if league_id is not None else _active_league_id())
    session[LEAGUE_SESSION_KEY] = selected_league_id
    session["team_a_id"] = int(team_a["id"])
    session["team_a_name"] = team_a.get("name", "")
    session["team_a_logo"] = team_a.get("logo", "")
    session["team_b_id"] = int(team_b["id"])
    session["team_b_name"] = team_b.get("name", "")
    session["team_b_logo"] = team_b.get("logo", "")

    if fixture_context:
        fixture_context["league_id"] = fixture_context.get("league_id") or selected_league_id
        if not fixture_context.get("league_name"):
            fixture_context["league_name"] = (LEAGUE_BY_ID.get(selected_league_id) or {}).get("name", "")
        fixture_context["home_name"] = fixture_context["home_name"] or team_a.get("name", "")
        fixture_context["home_logo"] = fixture_context["home_logo"] or team_a.get("logo", "")
        fixture_context["away_name"] = fixture_context["away_name"] or team_b.get("name", "")
        fixture_context["away_logo"] = fixture_context["away_logo"] or team_b.get("logo", "")
        session["selected_fixture"] = fixture_context
    else:
        session.pop("selected_fixture", None)


def _recent_team_fixtures_all_comps(
    team_id: int,
    primary_league_id: int | None = None,
    *,
    season: int = SEASON,
    last: int = 20,
) -> list[dict]:
    selected_league_id = _coerce_league_id(primary_league_id if primary_league_id is not None else _active_league_id())
    ordered_leagues = [selected_league_id, *[lid for lid in SUPPORTED_LEAGUE_IDS if lid != selected_league_id]]
    fixtures_by_key: dict[str, dict] = {}

    for league_id in ordered_leagues:
        try:
            league_fixtures = ac.get_team_fixtures(team_id, league_id, season, last=last)
        except Exception:
            continue
        for fixture in league_fixtures or []:
            fixture_block = fixture.get("fixture") or {}
            teams_block = fixture.get("teams") or {}
            key = str(fixture_block.get("id") or "")
            if not key:
                home_id = (teams_block.get("home") or {}).get("id") or ""
                away_id = (teams_block.get("away") or {}).get("id") or ""
                key = f"{fixture_block.get('date') or ''}:{home_id}:{away_id}"
            if key not in fixtures_by_key:
                fixtures_by_key[key] = fixture

    fixtures = list(fixtures_by_key.values())
    fixtures.sort(key=lambda item: str((item.get("fixture") or {}).get("date") or ""), reverse=True)
    fixtures = pred.filter_recent_completed_fixtures(fixtures, current_season=season)
    return fixtures[:last]


def _team_form_payload(team_id: int, league_id: int | None = None) -> dict:
    selected_league_id = _coerce_league_id(league_id if league_id is not None else _active_league_id())
    fixtures = _recent_team_fixtures_all_comps(team_id, selected_league_id, season=SEASON, last=20)
    form = pred.extract_form(fixtures, team_id)[:5]
    return {"form_string": "".join(item.get("result", "") for item in form), "rows": form}


def _assistant_page_kind(page_path: str) -> str:
    if re.match(r"^/prediction-result/[^/]+$", page_path or ""):
        return "result_detail"
    if page_path == "/matchup":
        return "soccer_matchup"
    if page_path == "/prediction":
        return "soccer_prediction"
    if page_path == "/props":
        return "soccer_props"
    if page_path == "/model-performance":
        return "model_performance"
    if page_path in {"/nba", "/nba/"}:
        return "nba_home"
    if page_path == "/nba/matchup":
        return "nba_matchup"
    if page_path == "/nba/prediction":
        return "nba_prediction"
    if page_path == "/nba/player":
        return "nba_player"
    if page_path == "/nba/props":
        return "nba_props"
    if page_path == "/nba/standings":
        return "nba_standings"
    if page_path == "/soccer":
        return "soccer_home"
    if page_path == "/":
        return "home"
    return "generic"


def _assistant_store_page_context(page_kind: str, payload: dict | None = None) -> None:
    compact = {"page_kind": page_kind, "captured_at": _now_stamp()}
    if payload:
        compact.update(payload)
    session["assistant_page_context"] = compact


def _assistant_extract_top_factors(prediction: dict) -> list[str]:
    components_a = prediction.get("components_a") if isinstance(prediction.get("components_a"), dict) else {}
    components_b = prediction.get("components_b") if isinstance(prediction.get("components_b"), dict) else {}
    differences = []

    for key in set(components_a) | set(components_b):
        try:
            a_val = float(components_a.get(key, 0) or 0)
            b_val = float(components_b.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        diff = abs(a_val - b_val)
        if diff <= 0:
            continue
        differences.append((diff, key.replace("_", " ").title()))

    differences.sort(reverse=True)
    return [label for _, label in differences[:3]]


def _assistant_pick_probability(prediction: dict, team_a_name: str, team_b_name: str) -> float | None:
    win_probs = prediction.get("win_probabilities") if isinstance(prediction.get("win_probabilities"), dict) else {}
    pick = str(((prediction.get("best_pick") or {}).get("prediction") or "")).strip().lower()
    if not pick:
        return None
    if pick == str(team_a_name or "").strip().lower():
        return _safe_float(win_probs.get("a")) if win_probs.get("a") is not None else None
    if pick == str(team_b_name or "").strip().lower():
        return _safe_float(win_probs.get("b")) if win_probs.get("b") is not None else None
    if pick == "draw":
        return _safe_float(win_probs.get("draw")) if win_probs.get("draw") is not None else None
    return None


def _assistant_extract_totals_pick_display(prediction: dict) -> str | None:
    totals_leg = _extract_totals_leg(prediction)
    if not totals_leg:
        return None
    pick = str(totals_leg.get("pick") or "").strip()
    line = totals_leg.get("line")
    if pick and line is not None:
        return f"{pick} {line}"
    market = str(totals_leg.get("market") or "").strip()
    return market or pick or None


def _assistant_compact_prediction_context(
    prediction: dict,
    *,
    sport: str,
    team_a_name: str,
    team_b_name: str,
    league_name: str | None = None,
) -> dict:
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    return {
        "sport": sport,
        "team_a": team_a_name,
        "team_b": team_b_name,
        "league_name": league_name or "",
        "winner_pick": best_pick.get("prediction") or "",
        "winner_probability": _assistant_pick_probability(prediction, team_a_name, team_b_name),
        "confidence": best_pick.get("confidence") or prediction.get("confidence") or "",
        "reasoning": str(best_pick.get("reasoning") or "").strip(),
        "totals_pick": _assistant_extract_totals_pick_display(prediction),
        "top_factors": _assistant_extract_top_factors(prediction),
    }


def _assistant_store_soccer_matchup_context(
    *,
    team_a: dict,
    team_b: dict,
    prediction: dict,
    league_name: str,
    form_a: list[dict],
    form_b: list[dict],
    injuries_a: list[dict],
    injuries_b: list[dict],
) -> None:
    payload = _assistant_compact_prediction_context(
        prediction,
        sport="soccer",
        team_a_name=team_a.get("name", "Team A"),
        team_b_name=team_b.get("name", "Team B"),
        league_name=league_name,
    )
    payload.update(
        {
            "form_a": "".join(row.get("result", "") for row in form_a[:5]),
            "form_b": "".join(row.get("result", "") for row in form_b[:5]),
            "injury_count_a": len(injuries_a or []),
            "injury_count_b": len(injuries_b or []),
        }
    )
    _assistant_store_page_context("soccer_matchup", payload)


def _assistant_store_soccer_prediction_context(
    *,
    team_a: dict,
    team_b: dict,
    prediction: dict,
    league_name: str,
) -> None:
    _assistant_store_page_context(
        "soccer_prediction",
        _assistant_compact_prediction_context(
            prediction,
            sport="soccer",
            team_a_name=team_a.get("name", "Team A"),
            team_b_name=team_b.get("name", "Team B"),
            league_name=league_name,
        ),
    )


def _assistant_store_result_context(record: dict, comparison: dict, evidence: dict) -> None:
    _assistant_store_page_context(
        "result_detail",
        {
            "sport": record.get("sport") or "",
            "team_a": record.get("team_a") or "",
            "team_b": record.get("team_b") or "",
            "winner_pick": comparison.get("winner_pick") or "",
            "totals_pick": comparison.get("totals_pick") or "",
            "winner_leg": comparison.get("winner_leg") or "",
            "totals_leg": comparison.get("totals_leg") or "",
            "overall_result": comparison.get("overall_result") or "",
            "final_score": record.get("final_score_display") or "",
            "actual_winner": record.get("actual_winner") or "",
            "confidence": comparison.get("confidence") or "",
            "evidence_summary": evidence.get("summary") or comparison.get("evidence_summary") or "",
            "evidence_layer_label": evidence.get("evidence_layer_label") or "",
        },
    )


def _assistant_store_model_performance_context(metrics: dict, sport_filter: str) -> None:
    _assistant_store_page_context(
        "model_performance",
        {
            "sport": sport_filter or "all",
            "overall_accuracy": metrics.get("overall_accuracy"),
            "wins": metrics.get("wins"),
            "losses": metrics.get("losses"),
            "finalized_predictions": metrics.get("finalized_predictions"),
            "grading_logic": (
                "Completed picks are tracked from settled results, and football detail pages separate winner leg, totals leg, and overall verdict so accuracy reflects the final tracked outcome rather than just one leg."
            ),
        },
    )


def _assistant_selected_football_context() -> dict:
    team_a, team_b = _require_teams()
    league_id = _coerce_league_id(session.get(LEAGUE_SESSION_KEY), DEFAULT_LEAGUE_ID)
    return {
        "sport": "soccer",
        "league_id": league_id,
        "league_name": (LEAGUE_BY_ID.get(league_id) or {}).get("name", ""),
        "team_a": (team_a or {}).get("name", ""),
        "team_b": (team_b or {}).get("name", ""),
        "selected_fixture": (_selected_fixture() or {}).get("short_name", ""),
    }


def _assistant_selected_nba_context() -> dict:
    selected_game = session.get("nba_selected_game") or {}
    return {
        "sport": "nba",
        "team_a": session.get("nba_team_a_name", ""),
        "team_b": session.get("nba_team_b_name", ""),
        "selected_game": selected_game.get("short_name", ""),
    }


def _assistant_page_path_from_payload(payload: dict) -> str:
    candidate = str(payload.get("page_path") or "").strip()
    if candidate:
        return candidate
    if request.referrer:
        try:
            return urlparse(request.referrer).path or "/"
        except Exception:
            return "/"
    return "/"


def _assistant_page_context_for_kind(page_kind: str, page_path: str) -> dict:
    stored = session.get("assistant_page_context") or {}
    if stored.get("page_kind") == page_kind:
        return stored

    if page_kind == "result_detail":
        match = re.match(r"^/prediction-result/([^/]+)$", page_path or "")
        if match:
            record = mt.get_prediction_by_id(match.group(1))
            if record:
                return {
                    "page_kind": "result_detail",
                    "sport": record.get("sport") or "",
                    "team_a": record.get("team_a") or "",
                    "team_b": record.get("team_b") or "",
                    "winner_pick": _prediction_sentence(record),
                    "totals_pick": record.get("totals_pick_display") or "",
                    "winner_leg": "Hit" if record.get("winner_hit") is True else "Miss" if record.get("winner_hit") is False else "Pending",
                    "totals_leg": "Hit" if record.get("ou_hit") is True else "Miss" if record.get("ou_hit") is False else "Pending",
                    "overall_result": record.get("overall_game_result") or "",
                    "final_score": record.get("final_score_display") or "",
                    "actual_winner": record.get("actual_winner") or "",
                    "confidence": record.get("confidence") or "",
                }
    if page_kind == "model_performance":
        metrics = mt.get_summary_metrics()
        return {
            "page_kind": "model_performance",
            "overall_accuracy": metrics.get("overall_accuracy"),
            "wins": metrics.get("wins"),
            "losses": metrics.get("losses"),
            "finalized_predictions": metrics.get("finalized_predictions"),
            "grading_logic": (
                "Completed picks are tracked from settled results, and football detail pages separate winner leg, totals leg, and overall verdict so accuracy reflects the final tracked outcome rather than just one leg."
            ),
        }
    return {}


def _build_chat_request_context(payload: dict) -> dict:
    page_path = _assistant_page_path_from_payload(payload)
    page_kind = _assistant_page_kind(page_path)
    page_context = _assistant_page_context_for_kind(page_kind, page_path)
    inferred_sport = page_context.get("sport") or (
        "nba" if page_kind.startswith("nba") else "soccer" if page_kind.startswith("soccer") or page_kind == "result_detail" else ""
    )

    return {
        "page": {
            "path": page_path,
            "title": str(payload.get("page_title") or "").strip(),
            "kind": page_kind,
            "sport": inferred_sport,
        },
        "football": _assistant_selected_football_context(),
        "nba": _assistant_selected_nba_context(),
        "assistant_page": page_context,
    }


def _chat_reply(message: str, history: list[dict] | None = None, chat_context: dict | None = None) -> dict:
    ctx = chat_context or {}
    football_ctx = ctx.get("football") or {}
    _ta = football_ctx.get("team_a") or ""
    _tb = football_ctx.get("team_b") or ""
    team_a = {"name": _ta} if _ta else None
    team_b = {"name": _tb} if _tb else None
    page_ctx = ctx.get("assistant_page") or None
    return assistant_services.chat_reply(
        message,
        history=history,
        anthropic_module=anthropic,
        api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        team_a=team_a,
        team_b=team_b,
        page_ctx=page_ctx,
        logger=app.logger,
    )
 


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    home_context = _build_home_dashboard_context()
    return render_template("home.html", **_page_context(**home_context))


@app.route("/soccer", methods=["GET"])
def soccer():
    _logger.debug("Route /soccer hit")
    _set_data_refresh()
    league_id = _set_active_league(_active_league_id())
    teams = ac.get_teams(league_id, SEASON)
    try:
        fixtures = ac.get_upcoming_fixtures(league_id, SEASON)
    except Exception as exc:
        app.logger.warning("Upcoming fixtures fetch failed: %s", exc)
        fixtures = []
    return render_template(
        "soccer.html",
        teams=teams,
        upcoming_fixtures=fixtures,
        fixtures_error=None if fixtures else "No upcoming fixtures available.",
        fixtures_source=_football_data_source(),
        selection_notice=(request.args.get("selection_error") or "").strip() or None,
        selected_fixture=_selected_fixture(),
        **_league_context(league_id),
    )


@app.route("/fixtures", methods=["GET"])
def fixtures():
    """Legacy fixtures page route (kept for backwards compatibility)."""
    _set_data_refresh()
    selected_slug = (request.args.get("espn_slug") or "").strip()
    league_id = _active_league_id()
    if selected_slug and not request.args.get("league"):
        for candidate_id, slug in getattr(ac, "ESPN_SLUG_BY_LEAGUE", {}).items():
            if str(slug).lower() == selected_slug.lower():
                league_id = _coerce_league_id(candidate_id, league_id)
                break
    league_id = _set_active_league(league_id)
    selected_slug = getattr(ac, "ESPN_SLUG_BY_LEAGUE", {}).get(league_id, selected_slug)
    fixtures_data: list[dict] = []
    load_error = None
    data_source = _football_data_source()

    fixtures_data, load_error, data_source, _ = _load_upcoming_fixtures(next_n=20, league=league_id)

    return render_template(
        "fixtures.html",
        **_page_context(
            fixtures=fixtures_data or [],
            load_error=load_error,
            data_source=data_source,
            espn_slug=selected_slug,
            **_league_context(league_id),
        ),
    )


@app.route("/select", methods=["GET", "POST"])
@app.route("/select-game", methods=["GET", "POST"])
@app.route("/matchup", methods=["POST"])
def select_game():
    _set_data_refresh()
    league_id = _set_active_league(
        _coerce_league_id(request.form.get("league_id") or request.args.get("league") or _active_league_id())
    )
    a_id_raw = (request.form.get("team_a") or request.args.get("team_a") or "").strip()
    b_id_raw = (request.form.get("team_b") or request.args.get("team_b") or "").strip()
    fixture_context = _fixture_context_from_form()
    source = (fixture_context or {}).get("data_source", "configured")

    if not a_id_raw or not b_id_raw or a_id_raw == b_id_raw:
        return _selection_error_redirect("soccer", "The selected soccer fixture could not be prepared for Match Analysis.")

    try:
        teams = ac.get_teams(league_id, SEASON)
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
            "The selected soccer fixture could not be matched to the current provider, so Match Analysis was not loaded."
        )

    _store_selected_teams(team_a, team_b, fixture_context)
    return redirect(url_for("prediction"))


@app.route("/matchup", methods=["GET"])
def matchup():
    _set_data_refresh()
    league_id = _set_active_league(_active_league_id())
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
        fixtures_a = _recent_team_fixtures_all_comps(id_a, league_id, season=SEASON, last=20)
    except Exception as exc:
        app.logger.error("Team A fixtures fetch error: %s", exc)

    try:
        fixtures_b = _recent_team_fixtures_all_comps(id_b, league_id, season=SEASON, last=20)
    except Exception as exc:
        app.logger.error("Team B fixtures fetch error: %s", exc)

    h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)

    try:
        injuries_a_raw = ac.get_injuries(league_id, SEASON, id_a)
    except Exception as exc:
        app.logger.error("Team A injuries fetch error: %s", exc)

    try:
        injuries_b_raw = ac.get_injuries(league_id, SEASON, id_b)
    except Exception as exc:
        app.logger.error("Team B injuries fetch error: %s", exc)

    h2h_raw = pred.filter_recent_completed_fixtures(h2h_raw, current_season=SEASON, seasons_back=5)


    if not h2h_raw and not fixtures_a and not fixtures_b:
        app.logger.warning("Matchup has no historical source data; using fallback neutral values for %s vs %s", team_a["name"], team_b["name"])

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

    def _avg(rows: list[dict], *keys: str) -> float:
        if not rows:
            return 0.0
        total = 0.0
        count = 0
        for row in rows:
            value = None
            for key in keys:
                if row.get(key) is not None:
                    value = row.get(key)
                    break
            if value is None:
                value = 0
            total += float(value or 0)
            count += 1
        return round(total / count, 2) if count else 0.0

    stats_compare = [
        {"label": "Goals scored", "a": _avg(form_a, "goals_for", "gf"), "b": _avg(form_b, "goals_for", "gf")},
        {"label": "Goals conceded", "a": _avg(form_a, "goals_against", "ga"), "b": _avg(form_b, "goals_against", "ga")},
        {"label": "Shots", "a": _avg(form_a, "shots"), "b": _avg(form_b, "shots")},
        {"label": "Shots on target", "a": _avg(form_a, "shots_on_target"), "b": _avg(form_b, "shots_on_target")},
        {"label": "Possession", "a": _avg(form_a, "possession"), "b": _avg(form_b, "possession")},
        {"label": "Corners", "a": _avg(form_a, "corners"), "b": _avg(form_b, "corners")},
    ]

    # ── Scorpred Engine ────────────────────────────────────────────────────────

    # H2H form from each team's perspective for the Scorpred model
    h2h_form_a = pred.extract_form(h2h_raw, id_a)[:10]
    h2h_form_b = pred.extract_form(h2h_raw, id_b)[:10]

    # Restore context variables from results dict
    standings_for_opp = results.get("standings_for_opp") or []
    squad_a = results.get("squad_a") or []
    squad_b = results.get("squad_b") or []

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
    league_id = _set_active_league(_active_league_id())

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
            prediction=mastermind,
            scorpred=mastermind.get("ui_prediction") or {},
            selected_fixture=selected_fixture,
            **_league_context(league_id),
        ),
    )


@app.route("/players", methods=["GET"])
def players():
    _set_data_refresh()

    league_id = _set_active_league(_active_league_id())
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("soccer", league=league_id))

    squad_a_raw = []
    squad_b_raw = []

    try:
        squad_a_raw = _fetch_team_squad(team_a["id"], SEASON, league_id)
    except Exception as exc:
        app.logger.warning("Players fetch failed for %s: %s", team_a["name"], exc)

    try:
        squad_b_raw = _fetch_team_squad(team_b["id"], SEASON, league_id)
    except Exception as exc:
        app.logger.warning("Players fetch failed for %s: %s", team_b["name"], exc)

    squad_a = _group_squad_by_position(squad_a_raw)
    squad_b = _group_squad_by_position(squad_b_raw)

    return render_template(
        "player.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            squad_a=squad_a,
            squad_b=squad_b,
            selected_fixture=_selected_fixture(),
            **_league_context(league_id),
        ),
    )


@app.route("/props", methods=["GET"])
def props():
    _set_data_refresh()
    league_id = _set_active_league(_active_league_id())
    team_a, team_b = _require_teams()
    squad_a: list = []
    squad_b: list = []
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
            **_league_context(league_id),
        ),
    )


# ── Props Bet Builder ─────────────────────────────────────────────────────────

@app.route("/props/generate", methods=["GET", "POST"])
def props_generate():
    _set_data_refresh()
    payload = request.get_json(silent=True) or request.values
    active_league_id = _set_active_league(_active_league_id())

    player_id = _safe_int(payload.get("player_id", 0), 0)
    player_name = payload.get("player_name", "Unknown Player")
    player_team_id = _safe_int(payload.get("player_team_id", 0), 0)
    opponent_id = _safe_int(payload.get("opponent_id", 0), 0)
    opponent_name = payload.get("opponent_name", "Opponent")
    is_home_str = str(payload.get("is_home", "true")).lower()
    markets_str = str(payload.get("markets", "goals,assists,shots_on_target,key_passes"))
    season = _safe_int(payload.get("season", SEASON), SEASON)
    league = _coerce_league_id(payload.get("league", active_league_id), active_league_id)
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
    payload = request.get_json(silent=True) or request.form or {}
    message = payload.get("message", "")
    message = str(message).strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    rate_limit = app.config.get("CHAT_RATE_LIMIT_COUNT", 10)
    rate_window = app.config.get("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60)
    retry_after = check_chat_rate_limit(rate_limit, rate_window)
    if retry_after:
        return jsonify({"error": "chat rate limit exceeded", "retry_after": retry_after}), 429

    history = session.get("chat_history", [])[-8:]
    chat_context = _build_chat_request_context(payload)
    response = _chat_reply(message, history=history, chat_context=chat_context)
    if isinstance(response, str):
        reply = response
        suggestions: list = []
        intent = None
        mode = "fallback"
    else:
        reply = response.get("reply") or ""
        suggestions = response.get("suggestions", [])
        intent = response.get("intent")
        mode = response.get("mode")
    history.extend(
        [
            {"role": "user", "content": message, "timestamp": _now_stamp()},
            {"role": "assistant", "content": reply, "timestamp": _now_stamp()},
        ]
    )
    session["chat_history"] = history[-10:]
    return jsonify(
        {
            "reply": reply,
            "suggestions": suggestions,
            "intent": intent,
            "mode": mode,
            "history": session["chat_history"],
            "last_updated": _now_stamp(),
        }
    )


@app.route("/chat/clear", methods=["POST"])
def chat_clear():
    session.pop("chat_history", None)
    return jsonify({"status": "cleared", "last_updated": _now_stamp()})


@app.route("/api/football/leagues", methods=["GET"])
def api_football_leagues():
    current_league_id = _set_active_league(_active_league_id())
    return jsonify(
        {
            "leagues": _football_supported_leagues(),
            "season": SEASON,
            "current_league_id": current_league_id,
        }
    )


@app.route("/api/football/teams", methods=["GET"])
def api_football_teams():
    league_id = _set_active_league(_coerce_league_id(request.args.get("league", _active_league_id())))
    try:
        teams = ac.get_teams(league_id, SEASON)
    except Exception as exc:
        app.logger.error("api_football_teams failed: %s", exc)
        return jsonify({"error": "Unable to load teams", "league": league_id, "season": SEASON}), 503
    return jsonify({"teams": teams or [], "league": league_id, "season": SEASON})


@app.route("/api/football/squad", methods=["GET"])
def api_football_squad():
    team_id = _safe_int(request.args.get("team_id", 0), 0)
    league_id = _coerce_league_id(request.args.get("league", _active_league_id()))
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    try:
        squad = ac.get_squad(team_id, SEASON, league_id)
    except Exception as exc:
        app.logger.error("api_football_squad failed for team_id=%s: %s", team_id, exc)
        return jsonify({"error": "Unable to load squad", "team_id": team_id}), 503
    return jsonify({"team_id": team_id, "league": league_id, "squad": squad or []})


@app.route("/api/football/team-form", methods=["GET"])
def api_football_team_form():
    team_id = _safe_int(request.args.get("team_id", 0), 0)
    league_id = _coerce_league_id(request.args.get("league", _active_league_id()))
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    try:
        payload = _team_form_payload(team_id, league_id=league_id)
    except Exception as exc:
        app.logger.error("api_football_team_form failed for team_id=%s: %s", team_id, exc)
        return jsonify({"error": "Unable to load team form", "team_id": team_id}), 503

    return jsonify({**payload, "league": league_id})


@app.route("/api/player-stats", methods=["GET"])
def api_player_stats():
    player_id = _safe_int(request.args.get("player_id", 0), 0)
    if not player_id:
        return jsonify({"error": "player_id is required"}), 400
    season = _safe_int(request.args.get("season", SEASON), SEASON)
    league = _coerce_league_id(request.args.get("league", _active_league_id()))
    try:
        stats = ac.get_player_stats(player_id, season=season, league_id=league)
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
    league_id = _set_active_league(_active_league_id())
    fixtures_with_pred, grouped_fixtures, load_error, data_source = _load_grouped_upcoming_fixtures_all_leagues(
        next_n_per_league=12
    )

    def _build_prediction_item(fixture: dict) -> dict | None:
        try:
            teams_block = fixture.get("teams", {})
            home_team = teams_block.get("home", {})
            away_team = teams_block.get("away", {})
            league_block = fixture.get("league", {})
            prediction = fixture.get("prediction", {})
            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})

            return {
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
                "score_gap": prediction.get("score_gap"),
                "has_data": bool(prediction.get("form_a") and prediction.get("form_b")),
            }
        except Exception as e:
            app.logger.warning("Error preparing fixture prediction: %s", e)
            return None

    predictions = [item for item in (_build_prediction_item(fixture) for fixture in fixtures_with_pred) if item]
    grouped_predictions = []
    for group in grouped_fixtures:
        items = [item for item in (_build_prediction_item(fixture) for fixture in group.get("fixtures", [])) if item]
        grouped_predictions.append({**group, "predictions": items})

    return render_template(
        "today_predictions.html",
        **_page_context(
            predictions=predictions,
            grouped_predictions=grouped_predictions,
            total_fixtures=len(fixtures_with_pred),
            total_predictions=len(predictions),
            load_error=load_error,
            data_source=data_source,
            **_league_context(league_id),
        ),
    )


@app.route("/top-picks-today", methods=["GET"])
def top_picks_today():
    """Show high-confidence picks from today's soccer and NBA predictions."""
    _set_data_refresh()
    league_id = _set_active_league(_active_league_id())
    soccer_predictions, grouped_soccer_fixtures, load_error, _ = _load_grouped_upcoming_fixtures_all_leagues(
        next_n_per_league=12
    )
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
                predicted_winner = best_pick.get("prediction", "—")
                if predicted_winner == home_team.get("name"):
                    probability = probs.get("a", 50)
                elif predicted_winner == away_team.get("name"):
                    probability = probs.get("b", 50)
                elif str(predicted_winner).lower() == "draw":
                    probability = probs.get("draw", 0)
                else:
                    probability = max(probs.get("a", 0), probs.get("b", 0), probs.get("draw", 0))

                soccer_picks.append({
                    "fixture": fixture,
                    "home_team": home_team,
                    "away_team": away_team,
                    "league_id": _safe_int((fixture.get("league") or {}).get("id"), league_id),
                    "predicted_winner": predicted_winner,
                    "confidence": "High",
                    "prob_home": probs.get("a", 50),
                    "prob_draw": probs.get("draw", 0),
                    "prob_away": probs.get("b", 50),
                    "pick": f"{predicted_winner} to Win" if str(predicted_winner).lower() != "draw" else "Draw",
                    "probability": round(float(probability), 1),
                    "note": best_pick.get("reasoning", "Model confidence edge"),
                    "pick_type": "match_winner" if best_pick.get("prediction") != "Draw" else "draw",
                    "reasoning": best_pick.get("reasoning", ""),
                })
        except Exception as e:
            app.logger.debug("Error preparing soccer top pick: %s", e)
            continue

    soccer_picks.sort(key=lambda item: (-float(item.get("probability", 0)), item.get("league_id", 0)))
    grouped_soccer_picks = []
    for group in grouped_soccer_fixtures:
        league_picks = [pick for pick in soccer_picks if pick.get("league_id") == group.get("league_id")]
        grouped_soccer_picks.append({**group, "picks": league_picks})
    
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
            if record.get("confidence") != "High":
                continue

            winner_code = str(record.get("predicted_winner", "")).strip().lower()
            if winner_code == "a":
                predicted_winner = record.get("team_a", "Team A")
                win_probability = record.get("prob_a", 50)
            elif winner_code == "b":
                predicted_winner = record.get("team_b", "Team B")
                win_probability = record.get("prob_b", 50)
            elif winner_code == "draw":
                predicted_winner = "Draw"
                win_probability = record.get("prob_draw", 0)
            else:
                predicted_winner = record.get("predicted_winner", "Unknown")
                win_probability = max(record.get("prob_a", 0), record.get("prob_b", 0), record.get("prob_draw", 0))

            nba_picks.append(
                {
                    "home_team": {"id": "", "name": record.get("team_a", "Team A")},
                    "away_team": {"id": "", "name": record.get("team_b", "Team B")},
                    "predicted_winner": predicted_winner,
                    "confidence": record.get("confidence", "Low"),
                    "win_probability": round(float(win_probability), 1),
                }
            )
    except Exception as e:
        app.logger.debug("Error loading NBA picks: %s", e)
    
    return render_template(
        "top_picks_today.html",
        **_page_context(
            soccer_totals=soccer_picks[:10],
            grouped_soccer_picks=grouped_soccer_picks,
            nba_winners=nba_picks[:10],
            soccer_picks=soccer_picks[:10],
            nba_picks=nba_picks[:10],
            load_error=load_error,
            **_league_context(league_id),
        ),
    )


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
        metrics.setdefault("by_league", {})
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

    _assistant_store_model_performance_context(metrics, sport_filter)

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
        ),
    )


@app.route("/prediction-result/<prediction_id>")
def prediction_result_detail(prediction_id: str):
    record = mt.get_prediction(prediction_id) or {}
    if not record:
        return _critical_error("Prediction not found.", 404)

    sport = str(record.get("sport") or "soccer").lower()
    if sport == "nba":
        evidence = _build_nba_evidence(record)
    else:
        evidence = _build_soccer_evidence(record)
    comparison = _build_prediction_vs_reality(record)

    probability_rows = [
        {"label": record.get("team_a") or "Team A", "value": _safe_float(record.get("prob_a"), 0.0)},
        {"label": "Draw", "value": _safe_float(record.get("prob_draw"), 0.0)} if sport == "soccer" else None,
        {"label": record.get("team_b") or "Team B", "value": _safe_float(record.get("prob_b"), 0.0)},
    ]
    probability_rows = [row for row in probability_rows if row]

    model_component_sections = _prepare_model_component_sections(record)

    return render_template(
        "prediction_result_detail.html",
        **_page_context(
            record=record,
            prediction_date_display=_format_prediction_date(record.get("date") or record.get("created_at")),
            updated_at_display=_format_prediction_date(record.get("updated_at") or record.get("date")),
            predicted_pick_display=_prediction_pick_display(record),
            probability_rows=probability_rows,
            evidence=evidence,
            comparison=comparison,
            model_component_sections=model_component_sections,
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
