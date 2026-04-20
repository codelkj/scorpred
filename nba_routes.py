"""
nba_routes.py -- Flask Blueprint for the NBA prediction module.

Registered in app.py as:
    from nba_routes import nba_bp
    app.register_blueprint(nba_bp)

All routes live under /nba prefix.
Session keys use the nba_ prefix to avoid collisions with the football section.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib
import json
import os
import re
import time
import traceback

from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, jsonify, current_app,
)
import scorpred_engine as se
import model_tracker as mt
from runtime_paths import cache_dir

nba_bp = Blueprint(
    "nba",
    __name__,
    url_prefix="/nba",
    template_folder="templates",
)


class _LazyModuleProxy:
    """Lazy-load heavyweight NBA dependencies on first real use."""

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


requests = _LazyModuleProxy("requests")
nc = _LazyModuleProxy("nba_live_client")
np_nba = _LazyModuleProxy("nba_predictor")
sm = _LazyModuleProxy("scormastermind")


# -- Helpers -----------------------------------------------------------------

_NBA_TEAM_ALIASES = {
    "atlanta hawks": "hawks",
    "hawks": "hawks",
    "atl": "hawks",
    "boston celtics": "celtics",
    "celtics": "celtics",
    "bos": "celtics",
    "brooklyn nets": "nets",
    "nets": "nets",
    "bkn": "nets",
    "charlotte hornets": "hornets",
    "hornets": "hornets",
    "cha": "hornets",
    "chicago bulls": "bulls",
    "bulls": "bulls",
    "chi": "bulls",
    "cleveland cavaliers": "cavaliers",
    "cavaliers": "cavaliers",
    "cavs": "cavaliers",
    "cle": "cavaliers",
    "dallas mavericks": "mavericks",
    "mavericks": "mavericks",
    "mavs": "mavericks",
    "dal": "mavericks",
    "denver nuggets": "nuggets",
    "nuggets": "nuggets",
    "den": "nuggets",
    "detroit pistons": "pistons",
    "pistons": "pistons",
    "det": "pistons",
    "golden state warriors": "warriors",
    "warriors": "warriors",
    "gs": "warriors",
    "gsw": "warriors",
    "houston rockets": "rockets",
    "rockets": "rockets",
    "hou": "rockets",
    "indiana pacers": "pacers",
    "pacers": "pacers",
    "ind": "pacers",
    "los angeles clippers": "clippers",
    "la clippers": "clippers",
    "clippers": "clippers",
    "lac": "clippers",
    "los angeles lakers": "lakers",
    "la lakers": "lakers",
    "lakers": "lakers",
    "lal": "lakers",
    "memphis grizzlies": "grizzlies",
    "grizzlies": "grizzlies",
    "mem": "grizzlies",
    "miami heat": "heat",
    "heat": "heat",
    "mia": "heat",
    "milwaukee bucks": "bucks",
    "bucks": "bucks",
    "mil": "bucks",
    "minnesota timberwolves": "timberwolves",
    "timberwolves": "timberwolves",
    "wolves": "timberwolves",
    "min": "timberwolves",
    "new orleans pelicans": "pelicans",
    "pelicans": "pelicans",
    "nop": "pelicans",
    "no": "pelicans",
    "new york knicks": "knicks",
    "knicks": "knicks",
    "ny": "knicks",
    "nyk": "knicks",
    "oklahoma city thunder": "thunder",
    "thunder": "thunder",
    "okc": "thunder",
    "orlando magic": "magic",
    "magic": "magic",
    "orl": "magic",
    "philadelphia 76ers": "76ers",
    "philadelphia sixers": "76ers",
    "76ers": "76ers",
    "sixers": "76ers",
    "phi": "76ers",
    "phoenix suns": "suns",
    "suns": "suns",
    "phx": "suns",
    "portland trail blazers": "trail blazers",
    "portland trailblazers": "trail blazers",
    "trail blazers": "trail blazers",
    "blazers": "trail blazers",
    "por": "trail blazers",
    "sacramento kings": "kings",
    "kings": "kings",
    "sac": "kings",
    "san antonio spurs": "spurs",
    "spurs": "spurs",
    "sa": "spurs",
    "sas": "spurs",
    "toronto raptors": "raptors",
    "raptors": "raptors",
    "tor": "raptors",
    "utah jazz": "jazz",
    "jazz": "jazz",
    "uta": "jazz",
    "washington wizards": "wizards",
    "wizards": "wizards",
    "was": "wizards",
}

_NBA_TEAM_METADATA = {
    "hawks": {"name": "Atlanta Hawks", "city": "Atlanta", "nickname": "Hawks"},
    "celtics": {"name": "Boston Celtics", "city": "Boston", "nickname": "Celtics"},
    "nets": {"name": "Brooklyn Nets", "city": "Brooklyn", "nickname": "Nets"},
    "hornets": {"name": "Charlotte Hornets", "city": "Charlotte", "nickname": "Hornets"},
    "bulls": {"name": "Chicago Bulls", "city": "Chicago", "nickname": "Bulls"},
    "cavaliers": {"name": "Cleveland Cavaliers", "city": "Cleveland", "nickname": "Cavaliers"},
    "mavericks": {"name": "Dallas Mavericks", "city": "Dallas", "nickname": "Mavericks"},
    "nuggets": {"name": "Denver Nuggets", "city": "Denver", "nickname": "Nuggets"},
    "pistons": {"name": "Detroit Pistons", "city": "Detroit", "nickname": "Pistons"},
    "warriors": {"name": "Golden State Warriors", "city": "Golden State", "nickname": "Warriors"},
    "rockets": {"name": "Houston Rockets", "city": "Houston", "nickname": "Rockets"},
    "pacers": {"name": "Indiana Pacers", "city": "Indiana", "nickname": "Pacers"},
    "clippers": {"name": "Los Angeles Clippers", "city": "Los Angeles", "nickname": "Clippers"},
    "lakers": {"name": "Los Angeles Lakers", "city": "Los Angeles", "nickname": "Lakers"},
    "grizzlies": {"name": "Memphis Grizzlies", "city": "Memphis", "nickname": "Grizzlies"},
    "heat": {"name": "Miami Heat", "city": "Miami", "nickname": "Heat"},
    "bucks": {"name": "Milwaukee Bucks", "city": "Milwaukee", "nickname": "Bucks"},
    "timberwolves": {"name": "Minnesota Timberwolves", "city": "Minnesota", "nickname": "Timberwolves"},
    "pelicans": {"name": "New Orleans Pelicans", "city": "New Orleans", "nickname": "Pelicans"},
    "knicks": {"name": "New York Knicks", "city": "New York", "nickname": "Knicks"},
    "thunder": {"name": "Oklahoma City Thunder", "city": "Oklahoma City", "nickname": "Thunder"},
    "magic": {"name": "Orlando Magic", "city": "Orlando", "nickname": "Magic"},
    "76ers": {"name": "Philadelphia 76ers", "city": "Philadelphia", "nickname": "76ers"},
    "suns": {"name": "Phoenix Suns", "city": "Phoenix", "nickname": "Suns"},
    "trail blazers": {"name": "Portland Trail Blazers", "city": "Portland", "nickname": "Trail Blazers"},
    "kings": {"name": "Sacramento Kings", "city": "Sacramento", "nickname": "Kings"},
    "spurs": {"name": "San Antonio Spurs", "city": "San Antonio", "nickname": "Spurs"},
    "raptors": {"name": "Toronto Raptors", "city": "Toronto", "nickname": "Raptors"},
    "jazz": {"name": "Utah Jazz", "city": "Utah", "nickname": "Jazz"},
    "wizards": {"name": "Washington Wizards", "city": "Washington", "nickname": "Wizards"},
}


def _normalize_nba_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[.\-_/]+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _canonical_nba_name(value: str) -> str:
    normalized = _normalize_nba_name(value)
    if not normalized:
        return ""
    return _NBA_TEAM_ALIASES.get(normalized, normalized)


def _team_name_candidates(team: dict) -> list[str]:
    values = [
        team.get("name", ""),
        team.get("nickname", ""),
        team.get("shortName", ""),
        team.get("abbrev", ""),
        " ".join(part for part in [team.get("city", ""), team.get("nickname", "")] if part),
        " ".join(part for part in [team.get("city", ""), team.get("name", "")] if part),
    ]
    return [value for value in values if str(value or "").strip()]


def _match_reason(selected_names: list[str], team_index: dict[str, list[dict]]) -> str:
    if not selected_names:
        return "no selected team names provided"
    canonical_selected = [_canonical_nba_name(name) for name in selected_names if _canonical_nba_name(name)]
    if not canonical_selected:
        return "selected team names normalized to empty canonical values"
    missing = [name for name in canonical_selected if name not in team_index]
    if missing:
        return f"no canonical match for {', '.join(missing)}"
    return "canonical match was ambiguous or unavailable"


def _log_team_match_debug(stage: str, selected_home: str, selected_away: str, teams: list[dict], reason: str = "") -> None:
    available_names = [team.get("name", "") for team in teams]
    normalized_selected = {
        "home": _canonical_nba_name(selected_home),
        "away": _canonical_nba_name(selected_away),
    }
    normalized_teams = [
        {
            "id": str(team.get("id", "")),
            "name": team.get("name", ""),
            "canonical": sorted({_canonical_nba_name(candidate) for candidate in _team_name_candidates(team) if _canonical_nba_name(candidate)}),
        }
        for team in teams
    ]
    current_app.logger.info(
        "nba select_game trace stage=%s selected_home=%r selected_away=%r normalized_selected=%s available_team_names=%s normalized_team_names=%s failure_reason=%s",
        stage,
        selected_home,
        selected_away,
        normalized_selected,
        available_names,
        normalized_teams,
        reason or "resolved",
    )


def _selection_mismatch_notice(selected_home: str, selected_away: str, teams: list[dict], reason: str) -> str:
    return "The selected NBA game could not be matched to the current team list. Please refresh and try again."


def _resolve_nba_team_from_selection(raw_id: str, raw_name: str, teams: list[dict]) -> tuple[dict | None, str]:
    team_by_id = {str(team.get("id", "")).strip(): team for team in teams if str(team.get("id", "")).strip()}
    if raw_id and raw_id in team_by_id:
        return team_by_id[raw_id], "matched by provider id"

    selected_canonical = _canonical_nba_name(raw_name)
    if not selected_canonical:
        return None, "selected team name normalized to empty canonical value"

    canonical_index: dict[str, list[dict]] = {}
    for team in teams:
        canonical_names = {
            _canonical_nba_name(candidate)
            for candidate in _team_name_candidates(team)
            if _canonical_nba_name(candidate)
        }
        for canonical_name in canonical_names:
            canonical_index.setdefault(canonical_name, []).append(team)

    matches = canonical_index.get(selected_canonical, [])
    if len(matches) == 1:
        return matches[0], f"matched by canonical name {selected_canonical}"
    if len(matches) > 1:
        return matches[0], f"matched by canonical name {selected_canonical} with duplicates"
    return None, _match_reason([raw_name], canonical_index)


def _fallback_nba_team_from_selection(raw_id: str, raw_name: str, raw_logo: str) -> tuple[dict | None, str]:
    canonical = _canonical_nba_name(raw_name)
    if not raw_id or not canonical:
        return None, "payload fallback unavailable"

    metadata = _NBA_TEAM_METADATA.get(canonical, {})
    if not metadata:
        return None, f"payload fallback unavailable for canonical name {canonical}"

    display_name = metadata.get("name") or raw_name.strip() or canonical.title()
    nickname = metadata.get("nickname") or display_name.split()[-1]
    city = metadata.get("city") or display_name.removesuffix(f" {nickname}").strip()
    return {
        "id": str(raw_id).strip(),
        "name": display_name,
        "nickname": nickname,
        "shortName": nickname,
        "city": city,
        "logo": raw_logo or "",
        "abbrev": "",
    }, f"matched by selection payload canonical name {canonical}"

def _require_nba_teams():
    """Return (team_a, team_b) dicts from session, or (None, None) if not set."""
    if "nba_team_a_id" not in session:
        return None, None
    return (
        {
            "id":       session["nba_team_a_id"],
            "name":     session["nba_team_a_name"],
            "logo":     session["nba_team_a_logo"],
            "nickname": session.get("nba_team_a_nickname", ""),
            "city":     session.get("nba_team_a_city", ""),
        },
        {
            "id":       session["nba_team_b_id"],
            "name":     session["nba_team_b_name"],
            "logo":     session["nba_team_b_logo"],
            "nickname": session.get("nba_team_b_nickname", ""),
            "city":     session.get("nba_team_b_city", ""),
        },
    )


def _selected_nba_game():
    return session.get("nba_selected_game")


def _selection_error_redirect(message: str):
    return redirect(url_for("nba.index", selection_error=message))


def _store_nba_teams(team_a: dict, team_b: dict) -> None:
    session["nba_team_a_id"] = str(team_a.get("id", ""))
    session["nba_team_a_name"] = team_a.get("name", "")
    session["nba_team_a_logo"] = team_a.get("logo", "")
    session["nba_team_a_nickname"] = team_a.get("nickname", "")
    session["nba_team_a_city"] = team_a.get("city", "")

    session["nba_team_b_id"] = str(team_b.get("id", ""))
    session["nba_team_b_name"] = team_b.get("name", "")
    session["nba_team_b_logo"] = team_b.get("logo", "")
    session["nba_team_b_nickname"] = team_b.get("nickname", "")
    session["nba_team_b_city"] = team_b.get("city", "")


def _store_selected_game_from_payload(payload) -> None:
    event_id = payload.get("event_id", "").strip()
    if not event_id:
        session.pop("nba_selected_game", None)
        return

    session["nba_selected_game"] = {
        "event_id": event_id,
        "date": payload.get("event_date", "").strip(),
        "status": payload.get("event_status", "").strip(),
        "venue_name": payload.get("venue_name", "").strip(),
        "short_name": payload.get("short_name", "").strip(),
        "home_name": payload.get("team_a_name", "").strip(),
        "home_logo": payload.get("team_a_logo", "").strip(),
        "away_name": payload.get("team_b_name", "").strip(),
        "away_logo": payload.get("team_b_logo", "").strip(),
        "sport": "nba",
        "league_name": "NBA",
    }


def _store_assistant_page_context(page_kind: str, payload: dict | None = None) -> None:
    compact = {"page_kind": page_kind, "captured_at": _now_stamp()}
    if payload:
        compact.update(payload)
    session["assistant_page_context"] = compact


def _assistant_pick_probability(prediction: dict, team_a_name: str, team_b_name: str) -> float | None:
    win_probs = prediction.get("win_probabilities") if isinstance(prediction.get("win_probabilities"), dict) else {}
    pick = str(((prediction.get("best_pick") or {}).get("prediction") or "")).strip().lower()
    if pick == str(team_a_name or "").strip().lower():
        value = win_probs.get("a")
    elif pick == str(team_b_name or "").strip().lower():
        value = win_probs.get("b")
    else:
        value = None
    try:
        return round(float(value), 1) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _assistant_totals_pick_display(prediction: dict) -> str | None:
    totals_leg = _extract_totals_leg(prediction)
    if not totals_leg:
        return None
    pick = str(totals_leg.get("pick") or "").strip()
    line = totals_leg.get("line")
    if pick and line is not None:
        return f"{pick} {line}"
    return str(totals_leg.get("market") or pick or "").strip() or None


def _assistant_prediction_context(prediction: dict, team_a_name: str, team_b_name: str, market_analysis: dict | None = None) -> dict:
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    return {
        "sport": "nba",
        "team_a": team_a_name,
        "team_b": team_b_name,
        "winner_pick": best_pick.get("prediction") or "",
        "winner_probability": _assistant_pick_probability(prediction, team_a_name, team_b_name),
        "confidence": best_pick.get("confidence") or prediction.get("confidence") or "",
        "reasoning": str(best_pick.get("reasoning") or "").strip(),
        "totals_pick": ((market_analysis or {}).get("totals_leg") or {}).get("recommendation") or _assistant_totals_pick_display(prediction),
        "spread_pick": ((market_analysis or {}).get("spread_leg") or {}).get("recommendation") or "",
        "top_factors": _assistant_extract_top_factors(prediction),
    }


def _log_err(msg: str, exc: Exception = None) -> None:
    current_app.logger.error("%s%s", msg, f": {exc}" if exc else "")
    if exc:
        current_app.logger.debug(traceback.format_exc())


class _route_timer:
    """Context manager that logs route execution time."""

    def __init__(self, route_name: str):
        self.route_name = route_name
        self.start: float = 0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *_exc):
        elapsed_ms = (time.perf_counter() - self.start) * 1000
        current_app.logger.info(
            "NBA %-25s rendered in %7.0f ms", self.route_name, elapsed_ms,
        )
        return False


def _support(route_name: str) -> dict:
    """Return route_support dict for the given route name."""
    return nc.get_route_support(route_name)


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _page_context(**kwargs) -> dict:
    context = {
        "data_source": "ESPN public NBA feeds + live standings source",
        "last_updated": _now_stamp(),
    }
    context.update(kwargs)
    return context


def _game_side(game: dict, side: str) -> dict:
    teams = game.get("teams") or {}
    if side == "away":
        return teams.get("visitors") or teams.get("away") or {}
    return teams.get("home") or {}


def _build_nba_opp_strengths(nba_standings: dict | list | None) -> dict:
    flat = []
    if isinstance(nba_standings, dict):
        for conf_teams in nba_standings.values():
            flat.extend(conf_teams)
    elif nba_standings:
        flat = list(nba_standings)

    ranked = []
    for index, entry in enumerate(flat):
        team_info = entry.get("team") or entry
        name = team_info.get("name") or team_info.get("nickname", "")
        rank = entry.get("rank") or entry.get("conference", {}).get("rank") or (index + 1)
        if name:
            ranked.append({"team": {"name": name}, "rank": rank})

    return se.build_opp_strengths_from_standings(ranked) if ranked else {}


def _build_upcoming_prediction_card(game: dict, team_map: dict[str, dict], nba_opp_strengths: dict) -> dict:
    home_id = str(_game_side(game, "home").get("id") or "")
    away_id = str(_game_side(game, "away").get("id") or "")
    home_team = team_map.get(home_id)
    away_team = team_map.get(away_id)

    if not home_team or not away_team:
        return {**game, "prediction": None}

    form_home = []
    form_away = []
    form_home_context = {"using_historical_context": False}
    form_away_context = {"using_historical_context": False}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {
            "form_home": executor.submit(nc.get_team_recent_form_context, home_id, nc.NBA_SEASON, 10, 0, "page"),
            "form_away": executor.submit(nc.get_team_recent_form_context, away_id, nc.NBA_SEASON, 10, 0, "page"),
        }

        for key, future in future_map.items():
            try:
                result = future.result()
            except Exception:
                continue

            if key == "form_home":
                form_home_context = result or form_home_context
                form_home_raw = form_home_context.get("current_games") or []
                form_home = np_nba.extract_recent_form(form_home_raw, home_id, n=5)
            elif key == "form_away":
                form_away_context = result or form_away_context
                form_away_raw = form_away_context.get("current_games") or []
                form_away = np_nba.extract_recent_form(form_away_raw, away_id, n=5)

    prediction = se.scorpred_predict(
        form_a=form_home,
        form_b=form_away,
        h2h_form_a=[],
        h2h_form_b=[],
        injuries_a=[],
        injuries_b=[],
        team_a_is_home=True,
        team_a_name=home_team.get("nickname") or home_team["name"],
        team_b_name=away_team.get("nickname") or away_team["name"],
        sport="nba",
        opp_strengths=nba_opp_strengths,
    )
    prediction = _apply_nba_confidence_profile(
        prediction,
        form_a_games=len(form_home),
        form_b_games=len(form_away),
        stats_a_available=True,
        stats_b_available=True,
        used_historical_context=bool(
            form_home_context.get("using_historical_context")
            or form_away_context.get("using_historical_context")
        ),
        data_limited=(len(form_home) < 2 or len(form_away) < 2),
    )
    return {**game, "prediction": prediction}


def _confidence_display_label(conf_key: str) -> str:
    key = str(conf_key or "").strip()
    if key == "High":
        return "High Confidence"
    if key == "Medium":
        return "Moderate Confidence"
    if key == "Low":
        return "Low Confidence"
    return "Limited Data"


def _downgrade_confidence_key(conf_key: str) -> str:
    if conf_key == "High":
        return "Medium"
    if conf_key == "Medium":
        return "Low"
    if conf_key == "Low":
        return "Limited Data"
    return "Limited Data"


def _apply_nba_confidence_profile(
    prediction: dict,
    *,
    form_a_games: int,
    form_b_games: int,
    stats_a_available: bool,
    stats_b_available: bool,
    used_historical_context: bool,
    data_limited: bool,
) -> dict:
    if not isinstance(prediction, dict):
        return prediction

    best_pick = prediction.get("best_pick") or {}
    win_probs = prediction.get("win_probabilities") or {}
    prob_a = float(win_probs.get("a", 50.0) or 50.0)
    prob_b = float(win_probs.get("b", 50.0) or 50.0)
    prob_gap = abs(prob_a - prob_b)

    form_quality = min(form_a_games, form_b_games)
    stats_ok = bool(stats_a_available and stats_b_available)

    if data_limited or form_quality < 2 or not stats_ok:
        conf_key = "Limited Data"
    elif prob_gap >= 14 and form_quality >= 5:
        conf_key = "High"
    elif prob_gap >= 7 and form_quality >= 3:
        conf_key = "Medium"
    else:
        conf_key = "Low"

    if used_historical_context and conf_key in {"High", "Medium", "Low"}:
        conf_key = _downgrade_confidence_key(conf_key)

    best_pick["confidence"] = conf_key
    best_pick["confidence_label"] = _confidence_display_label(conf_key)
    prediction["best_pick"] = best_pick
    prediction["confidence_label"] = best_pick["confidence_label"]
    return prediction


def _nba_data_completeness(
    *,
    form_a_games: int,
    form_b_games: int,
    stats_a_available: bool,
    stats_b_available: bool,
    used_historical_context: bool,
    data_limited: bool,
) -> dict:
    form_quality = min(form_a_games, form_b_games)
    stats_ok = bool(stats_a_available and stats_b_available)

    if data_limited or form_quality < 2 or not stats_ok:
        return {
            "tier": "limited",
            "label": "Limited data",
            "summary": "Current-season coverage is thin here, so treat this matchup as a lower-trust read.",
        }
    if used_historical_context or form_quality < 4:
        return {
            "tier": "partial",
            "label": "Mixed data quality",
            "summary": "Mostly current-season context is available, with some historical support filling the gaps.",
        }
    return {
        "tier": "full",
        "label": "Current-season data",
        "summary": "Form, team stats, and matchup context are all coming from current-season inputs.",
    }


def _nba_prediction_edge_state(prediction: dict) -> dict[str, str]:
    win_probs = prediction.get("win_probabilities") or {}
    prob_a = float(win_probs.get("a", 50.0) or 50.0)
    prob_b = float(win_probs.get("b", 50.0) or 50.0)
    gap = abs(prob_a - prob_b)

    if gap < 4:
        return {
            "title": "No clear advantage detected",
            "summary": "The teams project closely enough that the safer read is to treat this as a high-uncertainty matchup.",
        }
    if gap < 8:
        return {
            "title": "Small edge",
            "summary": "One side grades better, but the separation is still modest.",
        }
    if gap < 14:
        return {
            "title": "Clear edge",
            "summary": "The model sees a meaningful pre-game gap between the two teams.",
        }
    return {
        "title": "Strong edge",
        "summary": "Several inputs are lining up in the same direction, creating a stronger-than-usual signal.",
    }


def _nba_reason_tags(prediction: dict, data_completeness: dict) -> list[str]:
    tags: list[str] = []
    key_edges = prediction.get("key_edges") or []
    if key_edges:
        category = str((key_edges[0] or {}).get("category") or "").strip()
        if category:
            tags.append(f"{category} edge")

    win_probs = prediction.get("win_probabilities") or {}
    prob_a = float(win_probs.get("a", 50.0) or 50.0)
    prob_b = float(win_probs.get("b", 50.0) or 50.0)
    prob_gap = abs(prob_a - prob_b)
    if prob_gap < 4:
        tags.append("Close matchup")
    elif prob_gap >= 14:
        tags.append("Strong separation")

    tier = str(data_completeness.get("tier") or "")
    if tier == "limited":
        tags.append("Limited data")
    elif tier == "partial":
        tags.append("Mixed data")

    return tags[:4]


def _build_nba_prediction_explainer(
    prediction: dict,
    *,
    data_completeness: dict,
    team_a_name: str,
    team_b_name: str,
) -> dict:
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    edge_state = _nba_prediction_edge_state(prediction)
    summary = str(
        best_pick.get("reasoning")
        or prediction.get("matchup_reading")
        or edge_state["summary"]
    ).strip()

    return {
        "headline": edge_state["title"],
        "summary": summary,
        "supporting_note": edge_state["summary"],
        "reliability_label": data_completeness.get("label") or "Match context",
        "reliability_note": data_completeness.get("summary") or "The prediction is using the available pre-game context.",
        "tags": _nba_reason_tags(prediction, data_completeness),
        "raw_score_note": (
            f"Internal rating: {team_a_name} {prediction.get('team_a_score', 0)} - "
            f"{prediction.get('team_b_score', 0)} {team_b_name}"
        ),
    }


def _apply_nba_product_presentation(
    prediction: dict,
    *,
    data_completeness: dict,
    team_a_name: str,
    team_b_name: str,
) -> dict:
    if not isinstance(prediction, dict):
        return prediction

    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    confidence = str(best_pick.get("confidence") or "")
    win_probs = prediction.get("win_probabilities") or {}
    prob_a = float(win_probs.get("a", 50.0) or 50.0)
    prob_b = float(win_probs.get("b", 50.0) or 50.0)
    prob_gap = abs(prob_a - prob_b)

    if data_completeness.get("tier") == "limited" or confidence in {"Low", "Limited Data"} or prob_gap < 4:
        play_type = "AVOID"
        risk_label = "Elevated"
    elif confidence == "High" and prob_gap >= 14:
        play_type = "BET"
        risk_label = "Controlled"
    else:
        play_type = "LEAN"
        risk_label = "Balanced"

    prediction["play_type"] = play_type
    prediction["confidence_pct"] = round(max(prob_a, prob_b), 1)
    prediction["risk_label"] = risk_label
    prediction["data_completeness"] = data_completeness
    prediction["decision_explainer"] = _build_nba_prediction_explainer(
        prediction,
        data_completeness=data_completeness,
        team_a_name=team_a_name,
        team_b_name=team_b_name,
    )
    return prediction


def _refresh_requested() -> bool:
    return str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}


def _clear_nba_cache() -> None:
    for folder in (cache_dir("nba"), cache_dir("nba_public")):
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                continue


def _apply_refresh() -> None:
    if _refresh_requested():
        _clear_nba_cache()


_ESPN_NBA_OVERVIEW_CACHE = cache_dir("nba")
_ESPN_NBA_OVERVIEW_TTL = 1800       # 30 minutes
_ESPN_TIMEOUT    = float(os.getenv("EXTERNAL_API_TIMEOUT_SECONDS", "20"))
_ESPN_RETRIES    = max(1, int(os.getenv("EXTERNAL_API_RETRY_ATTEMPTS", "3")))
_ESPN_BACKOFF    = float(os.getenv("EXTERNAL_API_RETRY_BACKOFF_SECONDS", "1.2"))
_ESPN_RETRY_CODES = {429, 500, 502, 503, 504}


def _espn_player_overview(player_id: str) -> dict:
    """Fetch ESPN player overview with retry, cache, and stale-cache fallback."""
    url = (
        f"https://site.web.api.espn.com/apis/common/v3/sports"
        f"/basketball/nba/athletes/{player_id}/overview"
    )
    cache_key = hashlib.md5(f"nba_espn_overview:{player_id}".encode()).hexdigest()
    path = _ESPN_NBA_OVERVIEW_CACHE / f"espn_ov_{cache_key}.json"

    if path.exists():
        age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds()
        if age < _ESPN_NBA_OVERVIEW_TTL:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)

    last_exc: Exception | None = None
    for attempt in range(_ESPN_RETRIES):
        try:
            with requests.Session() as sess:
                sess.trust_env = False
                resp = sess.get(
                    url,
                    timeout=_ESPN_TIMEOUT,
                    headers={"Accept": "application/json"},
                )
            if resp.status_code in _ESPN_RETRY_CODES and attempt < _ESPN_RETRIES - 1:
                time.sleep(_ESPN_BACKOFF * (2 ** attempt))
                continue
            resp.raise_for_status()
            data = resp.json()
            _ESPN_NBA_OVERVIEW_CACHE.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            return data
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < _ESPN_RETRIES - 1:
                time.sleep(_ESPN_BACKOFF * (2 ** attempt))

    # Stale cache is better than a hard failure
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    raise RuntimeError(
        f"ESPN NBA player overview unavailable for player_id={player_id}"
    ) from last_exc


def _season_split_map(overview: dict) -> dict:
    statistics = overview.get("statistics") or {}
    names = statistics.get("names") or []
    splits = statistics.get("splits") or []
    regular = next((split for split in splits if split.get("displayName") == "Regular Season"), None)
    stats = (regular or {}).get("stats") or []
    return {name: stats[idx] for idx, name in enumerate(names) if idx < len(stats)}


def _recent_game_log(overview: dict) -> list[dict]:
    game_log = overview.get("gameLog") or {}
    stat_groups = game_log.get("statistics") or []
    if not stat_groups:
        return []
    totals = stat_groups[0]
    names = totals.get("names") or []
    events_by_id = game_log.get("events") or {}
    rows = []
    for event_stats in (totals.get("events") or [])[:5]:
        event_id = str(event_stats.get("eventId") or "")
        values = event_stats.get("stats") or []
        value_map = {name: values[idx] for idx, name in enumerate(names) if idx < len(values)}
        event = events_by_id.get(event_id) or {}
        rows.append(
            {
                "event_id": event_id,
                "date": (event.get("gameDate") or "")[:10],
                "opponent": event.get("opponent", ""),
                "result": event.get("gameResult", ""),
                "minutes": value_map.get("minutes", "0"),
                "min": value_map.get("minutes", "0"),
                "points": float(value_map.get("points", 0) or 0),
                "rebounds": float(value_map.get("totalRebounds", 0) or 0),
                "assists": float(value_map.get("assists", 0) or 0),
                "blocks": float(value_map.get("blocks", 0) or 0),
                "steals": float(value_map.get("steals", 0) or 0),
                "turnovers": float(value_map.get("turnovers", 0) or 0),
                "threePointPct": float(value_map.get("threePointPct", 0) or 0),
                "fieldGoalPct": float(value_map.get("fieldGoalPct", 0) or 0),
                "tpm": 0,
                "fgm": "-",
                "fga": "-",
                "fgp": float(value_map.get("fieldGoalPct", 0) or 0),
                "pra": round(
                    float(value_map.get("points", 0) or 0)
                    + float(value_map.get("totalRebounds", 0) or 0)
                    + float(value_map.get("assists", 0) or 0),
                    1,
                ),
            }
        )
    return rows


def _build_nba_props_from_avgs(season_avgs: dict, limited_data: bool) -> list[dict]:
    if not season_avgs:
        return []

    def _line(value: float) -> float:
        return round(max(0.5, value) * 2) / 2

    gp = int(float(season_avgs.get("gamesPlayed", 0) or 0))
    base_conf = 74 if gp >= 40 else 68 if gp >= 20 else 60
    note = "Limited by public endpoint depth" if limited_data else ""
    candidates = [
        ("Points", float(season_avgs.get("avgPoints", 0) or 0)),
        ("Rebounds", float(season_avgs.get("avgRebounds", 0) or 0)),
        ("Assists", float(season_avgs.get("avgAssists", 0) or 0)),
        ("PRA", round(
            float(season_avgs.get("avgPoints", 0) or 0)
            + float(season_avgs.get("avgRebounds", 0) or 0)
            + float(season_avgs.get("avgAssists", 0) or 0),
            1,
        )),
    ]
    props = []
    for label, projection in candidates:
        line = _line(projection)
        lean = "OVER" if projection >= line else "UNDER"
        props.append(
            {
                "label": label,
                "line": line,
                "projection": round(projection, 1),
                "season_avg": round(projection, 1),
                "last5_avg": round(projection, 1),
                "opp_avg": round(projection, 1),
                "lean": lean,
                "confidence": base_conf,
                "breakdown": f"Season average {projection:.1f} | Public feed recent-game context {'available' if not limited_data else 'limited'}",
                "opp_note": note,
            }
        )
    return props


def _build_nba_key_threats(roster: list, featured: list) -> list[dict]:
    """Return up to 5 key threat players for a team.

    If live featured leaders exist (from a selected game) we use those first,
    then fill remaining slots from the roster ordered by position importance.
    """
    position_meta = {
        "PG": {"label": "Playmaker", "contribution": "points + assists", "rank": 1},
        "SG": {"label": "Scorer",    "contribution": "points + 3-pointers", "rank": 2},
        "SF": {"label": "Wing",      "contribution": "points + rebounds",  "rank": 3},
        "PF": {"label": "Power Forward", "contribution": "rebounds + mid-range", "rank": 4},
        "C":  {"label": "Rim Anchor", "contribution": "rebounds + blocks", "rank": 5},
        "G":  {"label": "Guard",     "contribution": "points + assists",   "rank": 2},
        "F":  {"label": "Forward",   "contribution": "points + rebounds",  "rank": 3},
    }

    threats = []
    featured_ids = set()

    # First: promoted featured leaders (live stat leaders for this game)
    for fp in featured[:3]:
        pid = str(fp.get("id") or fp.get("playerId") or "")
        if not pid:
            continue
        featured_ids.add(pid)
        pos = fp.get("position") or fp.get("abbreviation") or "G"
        meta = position_meta.get(pos, position_meta["G"])
        threats.append({
            "id": pid,
            "name": fp.get("name") or fp.get("displayName") or "—",
            "photo": fp.get("headshot") or fp.get("photo") or "",
            "position": pos,
            "threat_label": meta["label"],
            "contribution": meta["contribution"],
            "injured": False,
            "live_stat": f"{fp.get('value', '')} {fp.get('metric', '')}".strip(),
            "is_featured": True,
        })

    # Then: fill remaining slots from roster by position rank
    for p in roster:
        if len(threats) >= 5:
            break
        pid = str(p.get("id") or "")
        if pid in featured_ids or not pid:
            continue
        injuries = p.get("injuries") or []
        is_injured = bool(injuries) and (injuries[0].get("status") or "").lower() == "out"
        if is_injured:
            continue  # skip confirmed-out players

        pos_raw = ""
        if p.get("leagues") and p["leagues"].get("standard"):
            pos_raw = p["leagues"]["standard"].get("pos") or ""
        if not pos_raw:
            pos_raw = p.get("position") or "G"

        meta = position_meta.get(pos_raw, position_meta["G"])
        threats.append({
            "id": pid,
            "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip() or p.get("displayName","—"),
            "photo": p.get("photo") or "",
            "position": pos_raw,
            "threat_label": meta["label"],
            "contribution": meta["contribution"],
            "injured": bool(injuries),
            "live_stat": "",
            "is_featured": False,
        })

    return threats[:5]


def _build_player_analysis(player_id: str, player_name: str = "") -> dict:
    overview = _espn_player_overview(str(player_id))
    season_avgs = _season_split_map(overview)
    last5_log = _recent_game_log(overview)
    limited_data = len(last5_log) < 5
    return {
        "player": {"id": str(player_id), "name": player_name},
        "season_avgs": {
            "games": int(float(season_avgs.get("gamesPlayed", 0) or 0)),
            "min": float(season_avgs.get("avgMinutes", 0) or 0),
            "points": float(season_avgs.get("avgPoints", 0) or 0),
            "rebounds": float(season_avgs.get("avgRebounds", 0) or 0),
            "assists": float(season_avgs.get("avgAssists", 0) or 0),
            "blocks": float(season_avgs.get("avgBlocks", 0) or 0),
            "steals": float(season_avgs.get("avgSteals", 0) or 0),
            "turnovers": float(season_avgs.get("avgTurnovers", 0) or 0),
            "fgp": float(season_avgs.get("fieldGoalPct", 0) or 0),
            "tpp": float(season_avgs.get("threePointPct", 0) or 0),
            "ftp": float(season_avgs.get("freeThrowPct", 0) or 0),
            "tpm": round(float(season_avgs.get("avgPoints", 0) or 0) / 3.5, 1),
        },
        "last5_log": last5_log,
        "last5_limited": limited_data,
        "vs_opp_records": [],
        "vs_opp_games": 0,
        "vs_opp_avgs": None,
        "vs_opp_limited": True,
        "limited_data_warning": limited_data,
        "props": _build_nba_props_from_avgs(season_avgs, limited_data),
        "data_source": "ESPN player overview",
        "last_updated": _now_stamp(),
    }


# -- Routes ------------------------------------------------------------------

@nba_bp.route("", methods=["GET"])
@nba_bp.route("/", methods=["GET"])
def index():
    with _route_timer("index"):
      return _index_inner()


def _index_inner():
    _apply_refresh()
    load_error = None
    teams = []
    today_games = []
    upcoming_games = []
    upcoming_games_with_predictions = []

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_teams = pool.submit(nc.get_teams)
            fut_today = pool.submit(nc.get_today_games, "page")
            fut_upcoming = pool.submit(nc.get_upcoming_games, 12, 5, "page")
            fut_standings = pool.submit(nc.get_standings)

        teams = fut_teams.result()
    except Exception as e:
        load_error = str(e)
        _log_err("NBA teams fetch failed", e)

    try:
        today_games = fut_today.result()
    except Exception as e:
        _log_err("NBA today games fetch failed", e)

    try:
        upcoming_games = fut_upcoming.result()
    except Exception as e:
        _log_err("NBA upcoming games fetch failed", e)

    # ── Generate Scorpred predictions for each upcoming game ──────────────────
    team_map = {str(t["id"]): t for t in teams} if teams else {}
    nba_opp_strengths = {}
    try:
        nba_opp_strengths = _build_nba_opp_strengths(fut_standings.result())
    except Exception as e:
        _log_err("NBA standings fetch failed for index predictions", e)

    if upcoming_games:
        indexed_games = list(enumerate(upcoming_games))
        ordered_results: list[dict | None] = [None] * len(indexed_games)
        max_workers = min(6, len(indexed_games)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_build_upcoming_prediction_card, game, team_map, nba_opp_strengths): index
                for index, game in indexed_games
            }
            for future in as_completed(future_map):
                index = future_map[future]
                game = indexed_games[index][1]
                try:
                    ordered_results[index] = future.result()
                except Exception as e:
                    _log_err(f"Prediction for NBA game {game.get('id')}", e)
                    ordered_results[index] = {**game, "prediction": None}

        upcoming_games_with_predictions = [result for result in ordered_results if result is not None]

    return render_template(
        "nba/index.html",
        **_page_context(
            teams=teams,
            today_games=today_games,
            upcoming_games=upcoming_games_with_predictions,
            selection_notice=(request.args.get("selection_error") or "").strip() or None,
            selected_game=_selected_nba_game() or {},
            load_error=load_error,
            route_support=_support("index"),
        ),
    )


@nba_bp.route("/matchup", methods=["POST"])
@nba_bp.route("/select", methods=["POST"])
def select():
    _apply_refresh()
    a_id = request.form.get("team_a", "").strip()
    b_id = request.form.get("team_b", "").strip()

    if not a_id or not b_id or a_id == b_id:
        return _selection_error_redirect("The selected NBA matchup could not be prepared for Match Analysis.")

    try:
        teams = nc.get_teams()
    except Exception:
        return _selection_error_redirect("The selected NBA matchup could not be loaded because team data is unavailable.")

    # IDs from the new provider are strings like "1", "2" etc.
    team_map = {str(t["id"]): t for t in teams}
    if a_id not in team_map or b_id not in team_map:
        return _selection_error_redirect("The selected NBA matchup could not be matched to the current team list.")

    ta, tb = team_map[a_id], team_map[b_id]
    _store_nba_teams(ta, tb)
    session.pop("nba_selected_game", None)

    return redirect(url_for("nba.prediction"))


@nba_bp.route("/select-game", methods=["GET", "POST"])
def select_game():
    _apply_refresh()
    # Support both GET (card links) and POST (form submissions)
    a_id = (request.form.get("team_a") or request.args.get("team_a") or "").strip()
    b_id = (request.form.get("team_b") or request.args.get("team_b") or "").strip()
    a_name = (request.form.get("team_a_name") or request.args.get("team_a_name") or "").strip()
    b_name = (request.form.get("team_b_name") or request.args.get("team_b_name") or "").strip()
    a_logo = (request.form.get("team_a_logo") or request.args.get("team_a_logo") or "").strip()
    b_logo = (request.form.get("team_b_logo") or request.args.get("team_b_logo") or "").strip()

    if not a_id or not b_id or a_id == b_id:
        return _selection_error_redirect("The selected NBA game could not be prepared for Match Analysis.")

    try:
        teams = nc.get_teams()
    except Exception:
        return _selection_error_redirect("The selected NBA game could not be loaded because team data is unavailable.")

    team_a, reason_a = _resolve_nba_team_from_selection(a_id, a_name, teams)
    team_b, reason_b = _resolve_nba_team_from_selection(b_id, b_name, teams)

    if not team_a:
        team_a, fallback_reason_a = _fallback_nba_team_from_selection(a_id, a_name, a_logo)
        if team_a:
            reason_a = fallback_reason_a
    if not team_b:
        team_b, fallback_reason_b = _fallback_nba_team_from_selection(b_id, b_name, b_logo)
        if team_b:
            reason_b = fallback_reason_b

    if not team_a or not team_b:
        failure_reason = f"home={reason_a}; away={reason_b}"
        _log_team_match_debug(
            "failed",
            a_name,
            b_name,
            teams,
            reason=failure_reason,
        )
        return _selection_error_redirect(_selection_mismatch_notice(a_name, b_name, teams, failure_reason))

    _log_team_match_debug(
        "resolved",
        a_name,
        b_name,
        teams,
        reason=f"home={reason_a}; away={reason_b}",
    )

    _store_nba_teams(team_a, team_b)
    if request.method == "POST":
        _store_selected_game_from_payload(request.form)
    else:
        _store_selected_game_from_payload(request.args)
    return redirect(url_for("nba.prediction"))


@nba_bp.route("/matchup")
def matchup():
    with _route_timer("matchup"):
      return _matchup_inner()


def _matchup_inner():
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return _selection_error_redirect("Match Analysis could not be opened because no NBA game is selected.")

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error = None
    selected_game = _selected_nba_game()
    game_snapshot = None

    h2h_rows = []
    h2h_summary = {}
    form_a = []
    form_b = []
    recent_form_a = []
    recent_form_b = []
    split_a = {}
    split_b = {}
    injuries_a = []
    injuries_b = []
    injury_summary_a = {}
    injury_summary_b = {}
    key_players_a = []
    key_players_b = []
    stats_a = None
    stats_b = None
    roster_a = []
    roster_b = []
    raw_h2h = []
    form_context_a = {"current_season": nc.NBA_SEASON, "current_games": [], "historical_games": [], "using_historical_context": False}
    form_context_b = {"current_season": nc.NBA_SEASON, "current_games": [], "historical_games": [], "using_historical_context": False}

    # ── Parallel data fetching ────────────────────────────────────────────────
    _fetch_tasks: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=8) as _pool:
        if selected_game and selected_game.get("event_id"):
            _fetch_tasks["snapshot"] = _pool.submit(
                nc.get_event_snapshot, selected_game["event_id"], selected_game.get("date"), "page",
            )
        _fetch_tasks["h2h"] = _pool.submit(nc.get_h2h, id_a, id_b, nc.NBA_SEASON, "page")
        _fetch_tasks["form_a"] = _pool.submit(nc.get_team_recent_form_context, id_a, nc.NBA_SEASON, 10, 2, "page")
        _fetch_tasks["form_b"] = _pool.submit(nc.get_team_recent_form_context, id_b, nc.NBA_SEASON, 10, 2, "page")
        _fetch_tasks["stats_a"] = _pool.submit(nc.get_team_season_stats, id_a)
        _fetch_tasks["stats_b"] = _pool.submit(nc.get_team_season_stats, id_b)
        _fetch_tasks["roster_a"] = _pool.submit(nc.get_team_roster, id_a, nc.NBA_SEASON, "page")
        _fetch_tasks["roster_b"] = _pool.submit(nc.get_team_roster, id_b, nc.NBA_SEASON, "page")
        _fetch_tasks["standings"] = _pool.submit(nc.get_standings)

    if "snapshot" in _fetch_tasks:
        try:
            game_snapshot = _fetch_tasks["snapshot"].result()
        except Exception as e:
            _log_err("Selected game snapshot", e)

    try:
        raw_h2h = _fetch_tasks["h2h"].result()
        h2h_rows = np_nba.h2h_display(raw_h2h, id_a, id_b)
        h2h_summary = np_nba.build_h2h_summary(raw_h2h, id_a, id_b, n=5)
    except Exception as e:
        _log_err("H2H fetch", e)

    try:
        form_context_a = _fetch_tasks["form_a"].result()
        recent_a = form_context_a.get("current_games") or []
        form_a = np_nba.extract_form_for_display(recent_a, id_a)
        recent_form_a = np_nba.extract_recent_form(recent_a, id_a, n=5)
    except Exception as e:
        _log_err("Form A fetch", e)

    try:
        form_context_b = _fetch_tasks["form_b"].result()
        recent_b = form_context_b.get("current_games") or []
        form_b = np_nba.extract_form_for_display(recent_b, id_b)
        recent_form_b = np_nba.extract_recent_form(recent_b, id_b, n=5)
    except Exception as e:
        _log_err("Form B fetch", e)

    try:
        stats_a = _fetch_tasks["stats_a"].result()
    except Exception as e:
        _log_err("Stats A", e)

    try:
        stats_b = _fetch_tasks["stats_b"].result()
    except Exception as e:
        _log_err("Stats B", e)

    try:
        roster_a = _fetch_tasks["roster_a"].result()
        injuries_a = nc.get_injuries_from_roster(roster_a)
        key_players_a = np_nba.build_key_player_stats_summary(roster_a, limit=5)
        injury_summary_a = np_nba.build_injury_summary(injuries_a, roster_a)
    except Exception as e:
        _log_err("Roster A", e)

    try:
        roster_b = _fetch_tasks["roster_b"].result()
        injuries_b = nc.get_injuries_from_roster(roster_b)
        key_players_b = np_nba.build_key_player_stats_summary(roster_b, limit=5)
        injury_summary_b = np_nba.build_injury_summary(injuries_b, roster_b)
    except Exception as e:
        _log_err("Roster B", e)

    def _splits(form_list):
        home = [g for g in form_list if g["is_home"]]
        away = [g for g in form_list if not g["is_home"]]

        def _agg(lst):
            if not lst:
                return {"w": 0, "l": 0, "ppg": 0, "opp_ppg": 0}
            w = sum(1 for g in lst if g["result"] == "W")
            return {
                "w": w, "l": len(lst) - w,
                "ppg":     round(sum(g["our_pts"]   for g in lst) / len(lst), 1),
                "opp_ppg": round(sum(g["their_pts"] for g in lst) / len(lst), 1),
            }

        return {"home": _agg(home), "away": _agg(away)}

    split_a = _splits(form_a)
    split_b = _splits(form_b)

    # ── Scorpred Engine ────────────────────────────────────────────────────────
    scorpred = None
    try:
        h2h_form_a = np_nba.extract_recent_form(raw_h2h, id_a, n=10)
        h2h_form_b = np_nba.extract_recent_form(raw_h2h, id_b, n=10)

        # Build opponent-strength lookup from NBA standings (pre-fetched in parallel)
        nba_opp_strengths = {}
        try:
            nba_opp_strengths = _build_nba_opp_strengths(_fetch_tasks["standings"].result())
        except Exception:
            pass

        mastermind = sm.predict_match(
            {
                "sport": "nba",
                "team_a_name": team_a.get("nickname") or team_a["name"],
                "team_b_name": team_b.get("nickname") or team_b["name"],
                "team_a_is_home": True,
                "form_a": recent_form_a,
                "form_b": recent_form_b,
                "h2h_form_a": h2h_form_a,
                "h2h_form_b": h2h_form_b,
                "injuries_a": injuries_a,
                "injuries_b": injuries_b,
                "opp_strengths": nba_opp_strengths,
                "team_stats": {
                    "a": stats_a or {},
                    "b": stats_b or {},
                },
            }
        )
        scorpred = mastermind.get("ui_prediction") or {}
        scorpred = _apply_nba_confidence_profile(
            scorpred,
            form_a_games=len(recent_form_a),
            form_b_games=len(recent_form_b),
            stats_a_available=bool(stats_a),
            stats_b_available=bool(stats_b),
            used_historical_context=bool(form_context_a.get("using_historical_context") or form_context_b.get("using_historical_context")),
            data_limited=(len(recent_form_a) < 2 or len(recent_form_b) < 2),
        )
    except Exception as e:
        _log_err("Scorpred NBA engine", e)

    season_context = {
        "current_season": nc.NBA_SEASON,
        "form_a_current": len(form_context_a.get("current_games") or []),
        "form_b_current": len(form_context_b.get("current_games") or []),
        "form_a_historical": len(form_context_a.get("historical_games") or []),
        "form_b_historical": len(form_context_b.get("historical_games") or []),
        "has_historical_context": bool(form_context_a.get("historical_games") or form_context_b.get("historical_games")),
    }

    return render_template(
        "nba/matchup.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_game=selected_game or {},
            game_snapshot=game_snapshot or {},
            h2h_rows=h2h_rows,
            h2h_summary=h2h_summary,
            form_a=form_a,
            form_b=form_b,
            recent_form_a=recent_form_a,
            recent_form_b=recent_form_b,
            split_a=split_a,
            split_b=split_b,
            stats_a=stats_a or {},
            stats_b=stats_b or {},
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            injury_summary_a=injury_summary_a,
            injury_summary_b=injury_summary_b,
            key_players_a=key_players_a,
            key_players_b=key_players_b,
            scorpred=scorpred,
            season_context=season_context,
            error=error,
            route_support=_support("matchup"),
        ),
    )


@nba_bp.route("/player")
def player():
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error = None
    roster_a = []
    roster_b = []
    selected_game = _selected_nba_game()
    game_snapshot = None
    featured_players = {"home": [], "visitors": []}

    if selected_game and selected_game.get("event_id"):
        try:
            game_snapshot = nc.get_event_snapshot(
                selected_game["event_id"], selected_game.get("date")
            )
        except Exception as e:
            _log_err("Selected game snapshot for player page", e)

    try:
        roster_a = nc.get_team_roster(id_a)
        roster_a.sort(key=lambda p: p.get("lastname", ""))
    except Exception as e:
        _log_err("Roster A", e)
        error = str(e)

    try:
        roster_b = nc.get_team_roster(id_b)
        roster_b.sort(key=lambda p: p.get("lastname", ""))
    except Exception as e:
        _log_err("Roster B", e)

    if selected_game and selected_game.get("event_id"):
        try:
            featured_players = nc.get_featured_players_for_event(
                selected_game["event_id"], selected_game.get("date")
            )
        except Exception as e:
            _log_err("Featured players", e)

    threats_a = _build_nba_key_threats(roster_a, featured_players.get("home", []))
    threats_b = _build_nba_key_threats(roster_b, featured_players.get("visitors", []))

    return render_template(
        "nba/player.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            roster_a=roster_a,
            roster_b=roster_b,
            threats_a=threats_a,
            threats_b=threats_b,
            selected_game=selected_game or {},
            game_snapshot=game_snapshot or {},
            featured_players=featured_players,
            error=error,
            route_support=_support("player"),
        ),
    )


@nba_bp.route("/player/analyze", methods=["POST"])
@nba_bp.route("/api/player-analysis")
def player_analysis_api():
    _apply_refresh()
    payload = request.get_json(silent=True) or request.values
    player_id = str(payload.get("player_id", "")).strip()
    player_name = str(payload.get("player_name", "")).strip()
    if not player_id:
        return jsonify({"error": "player_id is required"}), 400

    try:
        analysis = _build_player_analysis(player_id, player_name=player_name)
        return jsonify(analysis)
    except Exception as exc:
        _log_err("NBA player analysis", exc)
        return jsonify(
            {
                "error": str(exc),
                "season_avgs": {},
                "last5_log": [],
                "vs_opp_records": [],
                "props": [],
                "limited_data_warning": True,
                "data_source": "ESPN player overview",
                "last_updated": _now_stamp(),
            }
        ), 200


@nba_bp.route("/prediction")
def prediction():
    with _route_timer("prediction"):
      return _prediction_inner()


def _prediction_inner():
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return _selection_error_redirect("Match Analysis could not be opened because no NBA game is selected.")

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error = None
    h2h_games = []
    h2h_games_filtered = []
    h2h_rows = []
    h2h_summary = {}
    form_a_raw = []
    form_b_raw = []
    form_a_filtered = []
    form_b_filtered = []
    injuries_a = []
    injuries_b = []
    stats_a = None
    stats_b = None
    selected_game = _selected_nba_game()
    game_snapshot = None
    form_context_a = {"current_season": nc.NBA_SEASON, "current_games": [], "historical_games": [], "using_historical_context": False}
    form_context_b = {"current_season": nc.NBA_SEASON, "current_games": [], "historical_games": [], "using_historical_context": False}

    # ── Parallel data fetching ────────────────────────────────────────────────
    _fetch_tasks: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=9) as _pool:
        if selected_game and selected_game.get("event_id"):
            _fetch_tasks["snapshot"] = _pool.submit(
                nc.get_event_snapshot, selected_game["event_id"], selected_game.get("date"), "page",
            )
        _fetch_tasks["h2h"] = _pool.submit(nc.get_h2h, id_a, id_b, nc.NBA_SEASON, "page")
        _fetch_tasks["form_a"] = _pool.submit(nc.get_team_recent_form_context, id_a, nc.NBA_SEASON, 10, 2, "page")
        _fetch_tasks["form_b"] = _pool.submit(nc.get_team_recent_form_context, id_b, nc.NBA_SEASON, 10, 2, "page")
        _fetch_tasks["inj_a"] = _pool.submit(nc.get_team_injuries, id_a, nc.NBA_SEASON, "page")
        _fetch_tasks["inj_b"] = _pool.submit(nc.get_team_injuries, id_b, nc.NBA_SEASON, "page")
        _fetch_tasks["stats_a"] = _pool.submit(nc.get_team_season_stats, id_a)
        _fetch_tasks["stats_b"] = _pool.submit(nc.get_team_season_stats, id_b)
        _fetch_tasks["standings"] = _pool.submit(nc.get_standings)

    if "snapshot" in _fetch_tasks:
        try:
            game_snapshot = _fetch_tasks["snapshot"].result()
        except Exception as e:
            _log_err("Selected game snapshot for prediction", e)

    try:
        h2h_games = _fetch_tasks["h2h"].result()
        h2h_games_filtered = np_nba.filter_completed_nba_games(h2h_games)
        h2h_rows = np_nba.h2h_display(h2h_games_filtered, id_a, id_b)
        h2h_summary = np_nba.build_h2h_summary(h2h_games_filtered, id_a, id_b, n=5)
    except Exception as e:
        _log_err("H2H for prediction", e)

    try:
        form_context_a = _fetch_tasks["form_a"].result()
        form_a_raw = form_context_a.get("current_games") or []
        form_a_filtered = np_nba.filter_completed_nba_games(form_a_raw)
    except Exception as e:
        _log_err("Form A for prediction", e)

    try:
        form_context_b = _fetch_tasks["form_b"].result()
        form_b_raw = form_context_b.get("current_games") or []
        form_b_filtered = np_nba.filter_completed_nba_games(form_b_raw)
    except Exception as e:
        _log_err("Form B for prediction", e)

    try:
        injuries_a = _fetch_tasks["inj_a"].result()
    except Exception as e:
        _log_err("Injuries A for prediction", e)

    try:
        injuries_b = _fetch_tasks["inj_b"].result()
    except Exception as e:
        _log_err("Injuries B for prediction", e)

    try:
        stats_a = _fetch_tasks["stats_a"].result()
    except Exception as e:
        _log_err("Stats A for prediction", e)

    try:
        stats_b = _fetch_tasks["stats_b"].result()
    except Exception as e:
        _log_err("Stats B for prediction", e)

    # NOTE: Removed legacy nba_predictor.predict_winner() - using ONLY Scorpred Engine now
    # This ensures a single source of truth for all predictions

    form_a_display = np_nba.extract_form_for_display(form_a_filtered, id_a)
    form_b_display = np_nba.extract_form_for_display(form_b_filtered, id_b)
    h2h_rows = np_nba.h2h_display(h2h_games_filtered, id_a, id_b)

    # ── Scorpred Engine ────────────────────────────────────────────────────────
    scorpred = None
    market_analysis = None
    try:
        nba_form_a = np_nba.extract_recent_form(form_a_filtered, id_a, n=5)
        nba_form_b = np_nba.extract_recent_form(form_b_filtered, id_b, n=5)
        h2h_form_a = np_nba.extract_recent_form(h2h_games_filtered, id_a, n=5)
        h2h_form_b = np_nba.extract_recent_form(h2h_games_filtered, id_b, n=5)

        # Build opponent-strength lookup from NBA standings (pre-fetched in parallel)
        nba_opp_strengths = {}
        try:
            nba_opp_strengths = _build_nba_opp_strengths(_fetch_tasks["standings"].result())
        except Exception:
            pass

        mastermind = sm.predict_match(
            {
                "sport": "nba",
                "team_a_name": team_a.get("nickname") or team_a["name"],
                "team_b_name": team_b.get("nickname") or team_b["name"],
                "team_a_is_home": True,
                "form_a": nba_form_a,
                "form_b": nba_form_b,
                "h2h_form_a": h2h_form_a,
                "h2h_form_b": h2h_form_b,
                "injuries_a": injuries_a,
                "injuries_b": injuries_b,
                "opp_strengths": nba_opp_strengths,
                "team_stats": {
                    "a": stats_a or {},
                    "b": stats_b or {},
                },
            }
        )
        scorpred = mastermind.get("ui_prediction") or {}
        scorpred = _apply_nba_confidence_profile(
            scorpred,
            form_a_games=len(nba_form_a),
            form_b_games=len(nba_form_b),
            stats_a_available=bool(stats_a),
            stats_b_available=bool(stats_b),
            used_historical_context=bool(form_context_a.get("using_historical_context") or form_context_b.get("using_historical_context")),
            data_limited=(len(nba_form_a) < 2 or len(nba_form_b) < 2),
        )
        market_analysis = np_nba.build_market_recommendations(
            team_a,
            team_b,
            scorpred,
            nba_form_a,
            nba_form_b,
            h2h_games_filtered,
            injuries_a,
            injuries_b,
            stats_a=stats_a,
            stats_b=stats_b,
            team_a_is_home=True,
        )
    except Exception as e:
        _log_err("Scorpred NBA engine", e)

    has_historical_context = bool(form_context_a.get("historical_games") or form_context_b.get("historical_games"))
    limited_current_season = len(form_a_filtered) < 2 or len(form_b_filtered) < 2

    data_notes = [
        "Upcoming/live game context is from ESPN's public scoreboard and summary feeds.",
        "Primary analysis uses current-season completed form and current-season team snapshot data.",
        "Head-to-head is shown as historical context and is not treated as current-season form.",
    ]
    if limited_current_season:
        data_notes.append("Current-season data is limited for this matchup.")
    if has_historical_context:
        data_notes.append("Historical context is shown where current-season coverage is incomplete.")

    season_context = {
        "current_season": nc.NBA_SEASON,
        "form_a_current": len(form_context_a.get("current_games") or []),
        "form_b_current": len(form_context_b.get("current_games") or []),
        "form_a_historical": len(form_context_a.get("historical_games") or []),
        "form_b_historical": len(form_context_b.get("historical_games") or []),
        "has_historical_context": has_historical_context,
        "limited_current_season": limited_current_season,
        "stats_current_available": bool(stats_a and stats_b),
    }

    if scorpred:
        data_completeness = _nba_data_completeness(
            form_a_games=season_context["form_a_current"],
            form_b_games=season_context["form_b_current"],
            stats_a_available=bool(stats_a),
            stats_b_available=bool(stats_b),
            used_historical_context=has_historical_context,
            data_limited=limited_current_season,
        )
        scorpred = _apply_nba_product_presentation(
            scorpred,
            data_completeness=data_completeness,
            team_a_name=team_a.get("nickname") or team_a["name"],
            team_b_name=team_b.get("nickname") or team_b["name"],
        )

    # Track this prediction
    try:
        if scorpred:
            best_pick = scorpred.get("best_pick", {})
            pred_winner = best_pick.get("tracking_team") or best_pick.get("team", "")
            probs = scorpred.get("win_probabilities", {})
            conf = best_pick.get("confidence", "Medium")
            totals_leg_data = (market_analysis or {}).get("totals_leg") or {}
            totals_pick_text = str(totals_leg_data.get("recommendation") or "").strip()
            totals_match = re.match(r"^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", totals_pick_text, flags=re.IGNORECASE)
            totals_leg = {
                "pick": totals_match.group(1).title() if totals_match else None,
                "line": float(totals_match.group(2)) if totals_match else None,
                "market": f"Total Points O/U {totals_match.group(2)}" if totals_match else None,
            }
            
            mt.save_prediction(
                sport="nba",
                team_a=team_a.get("nickname") or team_a["name"],
                team_b=team_b.get("nickname") or team_b["name"],
                predicted_winner=pred_winner,
                win_probs=probs,
                confidence=conf,
                game_date=(selected_game or {}).get("date") or None,
                team_a_id=team_a["id"],
                team_b_id=team_b["id"],
                totals_pick=totals_leg.get("pick"),
                totals_line=totals_leg.get("line"),
                totals_market=totals_leg.get("market"),
            )
    except Exception:
        current_app.logger.warning("Prediction tracking failed (nba)", exc_info=True)

    _store_assistant_page_context(
        "nba_prediction",
        _assistant_prediction_context(
            scorpred or {},
            team_a.get("nickname") or team_a["name"],
            team_b.get("nickname") or team_b["name"],
            market_analysis=market_analysis,
        ),
    )

    return render_template(
        "nba/prediction.html",
        **_page_context(
            team_a=team_a,
            team_b=team_b,
            selected_game=selected_game or {},
            game_snapshot=game_snapshot or {},
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            stats_a=stats_a or {},
            stats_b=stats_b or {},
            form_a=form_a_display,
            form_b=form_b_display,
            h2h_rows=h2h_rows,
            h2h_summary=h2h_summary,
            prediction=scorpred,
            scorpred=scorpred,    # template guards on {% if scorpred %} — expose it directly
            data_notes=data_notes,
            show_data_notice=(limited_current_season or has_historical_context),
            season_context=season_context,
            error=error,
            market_analysis=market_analysis or {},
            route_support=_support("prediction"),
        ),
    )


def _build_today_prediction_card(
    game: dict, team_map: dict[str, dict], nba_opp_strengths: dict,
) -> dict | None:
    """Build a single prediction card for the today-predictions dashboard.

    Runs all per-game fetches (H2H, form, injuries) in parallel.
    Designed to be called from a ThreadPoolExecutor so multiple games
    are processed concurrently.
    """
    teams_block = game.get("teams") or {}
    home_raw = teams_block.get("home") or {}
    away_raw = teams_block.get("visitors") or {}
    home_id = str(home_raw.get("id") or "")
    away_id = str(away_raw.get("id") or "")

    if not home_id or not away_id:
        return None

    home_team = team_map.get(home_id) or home_raw
    away_team = team_map.get(away_id) or away_raw

    game_date_start = (game.get("date") or {}).get("start") or ""
    game_date = game_date_start[:10] if game_date_start else ""
    game_time = game_date_start[11:16] if len(game_date_start) > 10 else ""

    # ── Parallel per-game data fetches ─────────────────────────────────────
    h2h_raw: list = []
    form_home: list = []
    form_away: list = []
    injuries_home: list = []
    injuries_away: list = []
    form_home_context: dict = {"using_historical_context": False}
    form_away_context: dict = {"using_historical_context": False}

    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_h2h = pool.submit(nc.get_h2h, home_id, away_id)
        fut_form_h = pool.submit(nc.get_team_recent_form_context, home_id, nc.NBA_SEASON, 10)
        fut_form_a = pool.submit(nc.get_team_recent_form_context, away_id, nc.NBA_SEASON, 10)
        fut_inj_h = pool.submit(nc.get_team_injuries, home_id)
        fut_inj_a = pool.submit(nc.get_team_injuries, away_id)

    try:
        h2h_raw = fut_h2h.result()
    except Exception:
        pass
    try:
        form_home_context = fut_form_h.result()
        form_home_raw = form_home_context.get("current_games") or []
        form_home = np_nba.extract_recent_form(form_home_raw, home_id, n=5)
    except Exception:
        pass
    try:
        form_away_context = fut_form_a.result()
        form_away_raw = form_away_context.get("current_games") or []
        form_away = np_nba.extract_recent_form(form_away_raw, away_id, n=5)
    except Exception:
        pass
    try:
        injuries_home = fut_inj_h.result()
    except Exception:
        pass
    try:
        injuries_away = fut_inj_a.result()
    except Exception:
        pass

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
    prediction = _apply_nba_confidence_profile(
        prediction,
        form_a_games=len(form_home),
        form_b_games=len(form_away),
        stats_a_available=True,
        stats_b_available=True,
        used_historical_context=bool(
            form_home_context.get("using_historical_context")
            or form_away_context.get("using_historical_context")
        ),
        data_limited=(len(form_home) < 2 or len(form_away) < 2),
    )

    best_pick = prediction.get("best_pick", {})
    probs = prediction.get("win_probabilities", {})

    return {
        "game": game,
        "game_date": game_date,
        "game_time": game_time,
        "home_team": home_team,
        "away_team": away_team,
        "prediction": prediction,
        "predicted_winner": best_pick.get("prediction", "—"),
        "confidence": best_pick.get("confidence", "Low"),
        "prob_home": probs.get("a", 50),
        "prob_away": probs.get("b", 50),
        "reasoning": best_pick.get("reasoning", ""),
    }


@nba_bp.route("/today-predictions")
def today_predictions():
    with _route_timer("today_predictions"):
      return _today_predictions_inner()


def _today_predictions_inner():
    """
    Show NBA predictions for today's games (or next available games if none today).
    """
    _apply_refresh()
    load_error = None
    today_games = []
    team_map = {}

    # Build team_map from the teams directory (used as a name/logo supplement)
    try:
        teams = nc.get_teams()
        team_map = {str(t["id"]): t for t in teams}
    except Exception as e:
        _log_err("Teams fetch for today predictions", e)

    # Fetch today's NBA scoreboard
    now_utc = datetime.now(timezone.utc)
    current_app.logger.info(
        "today_predictions: UTC=%s — fetching today's scoreboard",
        now_utc.strftime("%Y-%m-%d %H:%M"),
    )
    try:
        today_games = nc.get_today_games()
        current_app.logger.info("today_predictions: today_games=%d", len(today_games))
    except Exception as e:
        _log_err("Today games fetch", e)
        load_error = str(e)

    # If no games today, fall back to the next 36 hours (days_ahead=2 scans today+2)
    if not today_games:
        current_app.logger.info(
            "today_predictions: no games on today's scoreboard — scanning next 2 days for upcoming"
        )
        try:
            today_games = nc.get_upcoming_games(next_n=12, days_ahead=2)
            current_app.logger.info(
                "today_predictions: upcoming fallback found %d games", len(today_games)
            )
        except Exception as e:
            _log_err("Upcoming games fallback", e)

    # Build opponent-strength lookup once (shared across all games)
    nba_opp_strengths = {}
    try:
        nba_standings = nc.get_standings()
        flat: list = []
        if isinstance(nba_standings, dict):
            for conf_teams in nba_standings.values():
                flat.extend(conf_teams)
        else:
            flat = list(nba_standings)
        ranked = []
        for i, entry in enumerate(flat):
            team_info = entry.get("team") or entry
            name = team_info.get("name") or team_info.get("nickname", "")
            rank = entry.get("rank") or entry.get("conference", {}).get("rank") or (i + 1)
            if name:
                ranked.append({"team": {"name": name}, "rank": rank})
        nba_opp_strengths = se.build_opp_strengths_from_standings(ranked)
    except Exception:
        pass

    # Build predictions for each game — parallelized across games
    predictions_for_games = []
    if today_games:
        max_workers = min(6, len(today_games)) or 1
        indexed_games = list(enumerate(today_games))
        ordered_results: list[dict | None] = [None] * len(indexed_games)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_build_today_prediction_card, game, team_map, nba_opp_strengths): idx
                for idx, game in indexed_games
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    result = future.result()
                    ordered_results[idx] = result
                except Exception as e:
                    _log_err(f"Prediction for game {indexed_games[idx][1].get('id')}", e)

        predictions_for_games = [r for r in ordered_results if r is not None]

    current_app.logger.info(
        "today_predictions: built %d predictions from %d games",
        len(predictions_for_games), len(today_games),
    )

    # Sort by confidence then probability gap
    conf_order = {"High": 0, "Medium": 1, "Low": 2}
    predictions_for_games.sort(
        key=lambda x: (
            conf_order.get(x["confidence"], 3),
            -abs(x["prob_home"] - x["prob_away"]),
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
            if p.get("sport") == "nba"
            and p.get("date", "") in (yesterday_str, today_str)
            and p.get("is_correct") is not None
        ]
    except Exception:
        yesterday_results = []

    return render_template(
        "nba/today_predictions.html",
        **_page_context(
            predictions=predictions_for_games,
            total_games=len(today_games),
            total_predictions=len(predictions_for_games),
            load_error=load_error,
            yesterday_results=yesterday_results,
            route_support=_support("today_predictions"),
        ),
    )


@nba_bp.route("/props/generate", methods=["GET", "POST"])
def nba_props_generate():
    """
    NBA player prop generation endpoint.
    Query params:
      player_id       int   — API-NBA player id
      player_name     str   — display name
      player_team_id  int   — player's team id
      opponent_id     int   — opponent team id
      opponent_name   str   — opponent display name
      is_home         bool  — "true" or "false"
      markets         str   — comma-separated e.g. "points,rebounds,assists,pra"
      season          int   — optional, defaults to 2024
    """
    import props_engine as pe

    _apply_refresh()
    payload = request.get_json(silent=True) or request.values
    player_id = int(payload.get("player_id", 0) or 0)
    player_name = payload.get("player_name", "Unknown Player")
    player_team_id = int(payload.get("player_team_id", 0) or 0)
    opponent_id = int(payload.get("opponent_id", 0) or 0)
    opponent_name = payload.get("opponent_name", "Opponent")
    is_home_str = str(payload.get("is_home", "true")).lower()
    markets_str = str(payload.get("markets", "points,rebounds,assists,pra"))
    season = int(payload.get("season", 2024) or 2024)
    position = payload.get("position", "")

    if not player_id or not player_team_id or not opponent_id:
        return jsonify({"error": "Required: player_id, player_team_id, opponent_id"}), 400

    is_home = is_home_str not in ("false", "0", "no")
    markets = [m.strip() for m in markets_str.split(",") if m.strip()]

    try:
        result = pe.generate_props(
            sport             = "nba",
            player_id         = player_id,
            player_name       = player_name,
            player_team_id    = player_team_id,
            opponent_team_id  = opponent_id,
            opponent_name     = opponent_name,
            is_home           = is_home,
            markets           = markets,
            player_position   = position,
            season            = season,
        )
        result["data_source"] = "ESPN live roster + configured NBA prop model"
        result["last_updated"] = _now_stamp()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error("NBA props generation failed: %s", e)
        return jsonify({"error": str(e), "data_source": "ESPN live roster + configured NBA prop model", "last_updated": _now_stamp()}), 500


@nba_bp.route("/props")
def nba_props_page():
    """Render the NBA props bet builder page."""
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    roster_a, roster_b = [], []
    if team_a:
        try:
            roster_a = nc.get_team_roster(str(team_a["id"]))
        except Exception:
            pass
    if team_b:
        try:
            roster_b = nc.get_team_roster(str(team_b["id"]))
        except Exception:
            pass
    from flask import render_template
    return render_template(
        "props.html",
        **_page_context(
            team_a=team_a or {},
            team_b=team_b or {},
            squad_a=roster_a,
            squad_b=roster_b,
            sport="nba",
        ),
    )


@nba_bp.route("/standings")
def standings():
    _apply_refresh()
    data  = {"east": [], "west": []}
    error = None
    try:
        data = nc.get_standings()
    except Exception as e:
        error = str(e)
        _log_err("Standings fetch", e)
    return render_template(
        "nba/standings.html",
        **_page_context(
            standings=data,
            error=error,
            route_support=_support("standings"),
        ),
    )
