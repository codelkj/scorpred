"""
nba_routes.py -- Flask Blueprint for the NBA prediction module.

Registered in app.py as:
    from nba_routes import nba_bp
    app.register_blueprint(nba_bp)

All routes live under /nba prefix.
Session keys use the nba_ prefix to avoid collisions with the football section.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import traceback

import requests
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, jsonify, current_app,
)
import nba_live_client as nc
import nba_predictor as np_nba
import scorpred_engine as se
import model_tracker as mt

nba_bp = Blueprint(
    "nba",
    __name__,
    url_prefix="/nba",
    template_folder="templates",
)


# -- Helpers -----------------------------------------------------------------

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


def _store_selected_game_from_form() -> None:
    event_id = request.form.get("event_id", "").strip()
    if not event_id:
        session.pop("nba_selected_game", None)
        return

    session["nba_selected_game"] = {
        "event_id": event_id,
        "date": request.form.get("event_date", "").strip(),
        "status": request.form.get("event_status", "").strip(),
        "venue_name": request.form.get("venue_name", "").strip(),
        "short_name": request.form.get("short_name", "").strip(),
        "home_name": request.form.get("team_a_name", "").strip(),
        "home_logo": request.form.get("team_a_logo", "").strip(),
        "away_name": request.form.get("team_b_name", "").strip(),
        "away_logo": request.form.get("team_b_logo", "").strip(),
    }


def _log_err(msg: str, exc: Exception = None) -> None:
    current_app.logger.error("%s%s", msg, f": {exc}" if exc else "")
    if exc:
        current_app.logger.debug(traceback.format_exc())


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


def _refresh_requested() -> bool:
    return str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}


def _clear_nba_cache() -> None:
    for folder in (Path("cache/nba"), Path("cache/nba_public")):
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


def _espn_player_overview(player_id: str) -> dict:
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/overview"
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


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

@nba_bp.route("/", methods=["GET"])
def index():
    _apply_refresh()
    load_error = None
    teams = []
    today_games = []
    upcoming_games = []

    try:
        teams = nc.get_teams()
    except Exception as e:
        load_error = str(e)
        _log_err("NBA teams fetch failed", e)

    try:
        today_games = nc.get_today_games()
    except Exception as e:
        _log_err("NBA today games fetch failed", e)

    try:
        upcoming_games = nc.get_upcoming_games(next_n=12)
    except Exception as e:
        _log_err("NBA upcoming games fetch failed", e)

    return render_template(
        "nba/index.html",
        **_page_context(
            teams=teams,
            today_games=today_games,
            upcoming_games=upcoming_games,
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
        return redirect(url_for("nba.index"))

    try:
        teams = nc.get_teams()
    except Exception:
        return redirect(url_for("nba.index"))

    # IDs from the new provider are strings like "1", "2" etc.
    team_map = {str(t["id"]): t for t in teams}
    if a_id not in team_map or b_id not in team_map:
        return redirect(url_for("nba.index"))

    ta, tb = team_map[a_id], team_map[b_id]
    _store_nba_teams(ta, tb)
    session.pop("nba_selected_game", None)

    return redirect(url_for("nba.matchup"))


@nba_bp.route("/select-game", methods=["GET", "POST"])
def select_game():
    _apply_refresh()
    # Support both GET (card links) and POST (form submissions)
    a_id = (request.form.get("team_a") or request.args.get("team_a") or "").strip()
    b_id = (request.form.get("team_b") or request.args.get("team_b") or "").strip()

    if not a_id or not b_id or a_id == b_id:
        return redirect(url_for("nba.index"))

    try:
        teams = nc.get_teams()
    except Exception:
        return redirect(url_for("nba.index"))

    team_map = {str(t["id"]): t for t in teams}
    if a_id not in team_map or b_id not in team_map:
        return redirect(url_for("nba.index"))

    _store_nba_teams(team_map[a_id], team_map[b_id])
    if request.method == "POST":
        _store_selected_game_from_form()
    else:
        session.pop("nba_selected_game", None)
    return redirect(url_for("nba.matchup"))


@nba_bp.route("/matchup")
def matchup():
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

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

    if selected_game and selected_game.get("event_id"):
        try:
            game_snapshot = nc.get_event_snapshot(
                selected_game["event_id"], selected_game.get("date")
            )
        except Exception as e:
            _log_err("Selected game snapshot", e)

    try:
        raw_h2h  = nc.get_h2h(id_a, id_b)
        h2h_rows = np_nba.h2h_display(raw_h2h, id_a, id_b)
        h2h_summary = np_nba.build_h2h_summary(raw_h2h, id_a, id_b, n=5)
    except Exception as e:
        _log_err("H2H fetch", e)

    try:
        recent_a = nc.get_team_recent_form(id_a)
        form_a   = np_nba.extract_form_for_display(recent_a, id_a)
        recent_form_a = np_nba.extract_recent_form(recent_a, id_a, n=5)
    except Exception as e:
        _log_err("Form A fetch", e)

    try:
        recent_b = nc.get_team_recent_form(id_b)
        form_b   = np_nba.extract_form_for_display(recent_b, id_b)
        recent_form_b = np_nba.extract_recent_form(recent_b, id_b, n=5)
    except Exception as e:
        _log_err("Form B fetch", e)

    try:
        stats_a = nc.get_team_season_stats(id_a)
    except Exception as e:
        _log_err("Stats A", e)

    try:
        stats_b = nc.get_team_season_stats(id_b)
    except Exception as e:
        _log_err("Stats B", e)

    try:
        injuries_a = nc.get_team_injuries(id_a)
        injury_summary_a = np_nba.build_injury_summary(injuries_a, roster_a)
    except Exception as e:
        _log_err("Injuries A", e)

    try:
        injuries_b = nc.get_team_injuries(id_b)
        injury_summary_b = np_nba.build_injury_summary(injuries_b, roster_b)
    except Exception as e:
        _log_err("Injuries B", e)

    try:
        roster_a = nc.get_team_roster(id_a)
        key_players_a = np_nba.build_key_player_stats_summary(roster_a, limit=5)
        if injuries_a:
            injury_summary_a = np_nba.build_injury_summary(injuries_a, roster_a)
    except Exception as e:
        _log_err("Roster A", e)

    try:
        roster_b = nc.get_team_roster(id_b)
        key_players_b = np_nba.build_key_player_stats_summary(roster_b, limit=5)
        if injuries_b:
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
        h2h_form_a = np_nba.extract_recent_form(h2h_rows, id_a, n=10)
        h2h_form_b = np_nba.extract_recent_form(h2h_rows, id_b, n=10)

        # Build opponent-strength lookup from NBA standings
        nba_opp_strengths = {}
        try:
            nba_standings = nc.get_standings()
            # Standings are typically a list of team-stat dicts with 'team' and 'conference rank'
            # Build a flat list with rank derived from position in the list
            flat = []
            if isinstance(nba_standings, dict):
                for conf_teams in nba_standings.values():
                    flat.extend(conf_teams)
            else:
                flat = list(nba_standings)
            # Assign rank by position if no explicit rank key
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

        scorpred = se.scorpred_predict(
            form_a=recent_form_a,
            form_b=recent_form_b,
            h2h_form_a=h2h_form_a,
            h2h_form_b=h2h_form_b,
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            team_a_is_home=True,  # Assume team_a is home for now
            team_a_name=team_a.get("nickname") or team_a["name"],
            team_b_name=team_b.get("nickname") or team_b["name"],
            sport="nba",
            opp_strengths=nba_opp_strengths,
        )
    except Exception as e:
        _log_err("Scorpred NBA engine", e)

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
    _apply_refresh()
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error = None
    h2h_games = []
    h2h_games_filtered = []
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

    if selected_game and selected_game.get("event_id"):
        try:
            game_snapshot = nc.get_event_snapshot(
                selected_game["event_id"], selected_game.get("date")
            )
        except Exception as e:
            _log_err("Selected game snapshot for prediction", e)

    try:
        h2h_games = nc.get_h2h(id_a, id_b)
        h2h_games_filtered = np_nba.filter_completed_nba_games(h2h_games)
    except Exception as e:
        _log_err("H2H for prediction", e)

    try:
        form_a_raw = nc.get_team_recent_form(id_a)
        form_a_filtered = np_nba.filter_completed_nba_games(form_a_raw)
    except Exception as e:
        _log_err("Form A for prediction", e)

    try:
        form_b_raw = nc.get_team_recent_form(id_b)
        form_b_filtered = np_nba.filter_completed_nba_games(form_b_raw)
    except Exception as e:
        _log_err("Form B for prediction", e)

    try:
        injuries_a = nc.get_team_injuries(id_a)
    except Exception as e:
        _log_err("Injuries A for prediction", e)

    try:
        injuries_b = nc.get_team_injuries(id_b)
    except Exception as e:
        _log_err("Injuries B for prediction", e)

    try:
        stats_a = nc.get_team_season_stats(id_a)
    except Exception as e:
        _log_err("Stats A for prediction", e)

    try:
        stats_b = nc.get_team_season_stats(id_b)
    except Exception as e:
        _log_err("Stats B for prediction", e)

    # NOTE: Removed legacy nba_predictor.predict_winner() - using ONLY Scorpred Engine now
    # This ensures a single source of truth for all predictions

    form_a_display = np_nba.extract_form_for_display(form_a_filtered, id_a)
    form_b_display = np_nba.extract_form_for_display(form_b_filtered, id_b)

    # ── Scorpred Engine ────────────────────────────────────────────────────────
    scorpred = None
    try:
        nba_form_a = np_nba.extract_recent_form(form_a_filtered, id_a, n=5)
        nba_form_b = np_nba.extract_recent_form(form_b_filtered, id_b, n=5)
        h2h_form_a = np_nba.extract_recent_form(h2h_games_filtered, id_a, n=5)
        h2h_form_b = np_nba.extract_recent_form(h2h_games_filtered, id_b, n=5)

        # Build opponent-strength lookup from NBA standings
        nba_opp_strengths = {}
        try:
            nba_standings = nc.get_standings()
            # Standings are typically a list of team-stat dicts with 'team' and 'conference rank'
            # Build a flat list with rank derived from position in the list
            flat = []
            if isinstance(nba_standings, dict):
                for conf_teams in nba_standings.values():
                    flat.extend(conf_teams)
            else:
                flat = list(nba_standings)
            # Assign rank by position if no explicit rank key
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

        scorpred = se.scorpred_predict(
            form_a=nba_form_a,
            form_b=nba_form_b,
            h2h_form_a=h2h_form_a,
            h2h_form_b=h2h_form_b,
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            team_a_is_home=True,
            team_a_name=team_a.get("nickname") or team_a["name"],
            team_b_name=team_b.get("nickname") or team_b["name"],
            sport="nba",
            opp_strengths=nba_opp_strengths,
        )
    except Exception as e:
        _log_err("Scorpred NBA engine", e)

    data_notes = [
        "Upcoming/live game context is from ESPN's public scoreboard and summary feeds.",
        "Season records, PPG, and net rating are live from the standings feed.",
        "Recent form, head-to-head history, rosters, and injuries are all based on real schedule and roster data.",
        "Analysis uses only completed games (final/post state) for accurate recent form and H2H history.",
    ]

    # Track this prediction
    try:
        if scorpred:
            best_pick = scorpred.get("best_pick", {})
            pred_winner = best_pick.get("team", "")
            probs = scorpred.get("win_probabilities", {})
            conf = best_pick.get("confidence", "Medium")
            
            mt.save_prediction(
                sport="nba",
                team_a=team_a.get("nickname") or team_a["name"],
                team_b=team_b.get("nickname") or team_b["name"],
                predicted_winner=pred_winner,
                win_probs=probs,
                confidence=conf,
            )
    except Exception:
        pass  # Silent fail if tracking fails

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
            prediction=scorpred,
            scorpred=scorpred,    # template guards on {% if scorpred %} — expose it directly
            data_notes=data_notes,
            error=error,
            route_support=_support("prediction"),
        ),
    )


@nba_bp.route("/today-predictions")
def today_predictions():
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
    now_utc = datetime.utcnow()
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

    # Build predictions for each game
    predictions_for_games = []
    for game in today_games or []:
        try:
            # ── Fix: normalized games use game["teams"]["home"] / ["visitors"],
            #         NOT game["home"] / game["away"] ──────────────────────────
            teams_block = game.get("teams") or {}
            home_raw = teams_block.get("home") or {}
            away_raw = teams_block.get("visitors") or {}

            home_id = str(home_raw.get("id") or "")
            away_id = str(away_raw.get("id") or "")

            if not home_id or not away_id:
                current_app.logger.debug(
                    "today_predictions: skipping game %s — missing team IDs (home=%r away=%r)",
                    game.get("id"), home_id, away_id,
                )
                continue

            # Prefer team_map entry (has logo/nickname from directory); fall back to game data
            home_team = team_map.get(home_id) or home_raw
            away_team = team_map.get(away_id) or away_raw

            # Normalise game start time for the template
            game_date_start = (game.get("date") or {}).get("start") or ""
            game_date = game_date_start[:10] if game_date_start else ""
            game_time = game_date_start[11:16] if len(game_date_start) > 10 else ""

            current_app.logger.debug(
                "today_predictions: processing %s vs %s on %s",
                home_team.get("name") or home_team.get("nickname"),
                away_team.get("name") or away_team.get("nickname"),
                game_date or "unknown date",
            )

            # Fetch form and H2H for prediction
            h2h_raw = []
            form_home = []
            form_away = []
            injuries_home = []
            injuries_away = []

            try:
                h2h_raw = nc.get_h2h(home_id, away_id)
            except Exception:
                pass

            try:
                form_home_raw = nc.get_team_recent_form(home_id)
                form_home = np_nba.extract_recent_form(form_home_raw, home_id, n=5)
            except Exception:
                pass

            try:
                form_away_raw = nc.get_team_recent_form(away_id)
                form_away = np_nba.extract_recent_form(form_away_raw, away_id, n=5)
            except Exception:
                pass

            try:
                injuries_home = nc.get_team_injuries(home_id)
            except Exception:
                pass

            try:
                injuries_away = nc.get_team_injuries(away_id)
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

            best_pick = prediction.get("best_pick", {})
            probs = prediction.get("win_probabilities", {})

            predictions_for_games.append({
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
            })
        except Exception as e:
            _log_err(f"Prediction for game {game.get('id')}", e)
            continue

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
