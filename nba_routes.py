"""
nba_routes.py -- Flask Blueprint for the NBA prediction module.

Registered in app.py as:
    from nba_routes import nba_bp
    app.register_blueprint(nba_bp)

All routes live under /nba prefix.
Session keys use the nba_ prefix to avoid collisions with the football section.
"""

from __future__ import annotations
import traceback
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, jsonify, current_app,
)
import nba_client as nc
import nba_predictor as np_nba

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


def _log_err(msg: str, exc: Exception = None) -> None:
    current_app.logger.error("%s%s", msg, f": {exc}" if exc else "")
    if exc:
        current_app.logger.debug(traceback.format_exc())


def _support(route_name: str) -> dict:
    """Return route_support dict for the given route name."""
    return nc.get_route_support(route_name)


# -- Routes ------------------------------------------------------------------

@nba_bp.route("/", methods=["GET"])
def index():
    load_error  = None
    teams       = []
    today_games = []

    try:
        teams = nc.get_teams()
    except Exception as e:
        load_error = str(e)
        _log_err("NBA teams fetch failed", e)

    try:
        today_games = nc.get_today_games()
    except Exception as e:
        _log_err("NBA today games fetch failed", e)

    return render_template(
        "nba/index.html",
        teams=teams,
        today_games=today_games,
        load_error=load_error,
        route_support=_support("index"),
    )


@nba_bp.route("/select", methods=["POST"])
def select():
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

    session["nba_team_a_id"]       = a_id
    session["nba_team_a_name"]     = ta.get("name", "")
    session["nba_team_a_logo"]     = ta.get("logo", "")
    session["nba_team_a_nickname"] = ta.get("nickname", "")
    session["nba_team_a_city"]     = ta.get("city", "")

    session["nba_team_b_id"]       = b_id
    session["nba_team_b_name"]     = tb.get("name", "")
    session["nba_team_b_logo"]     = tb.get("logo", "")
    session["nba_team_b_nickname"] = tb.get("nickname", "")
    session["nba_team_b_city"]     = tb.get("city", "")

    return redirect(url_for("nba.matchup"))


@nba_bp.route("/matchup")
def matchup():
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error      = None

    h2h_rows   = []
    form_a     = []
    form_b     = []
    split_a    = {}
    split_b    = {}
    injuries_a = []
    injuries_b = []
    stats_a    = None
    stats_b    = None

    try:
        raw_h2h  = nc.get_h2h(id_a, id_b)
        h2h_rows = np_nba.h2h_display(raw_h2h, id_a, id_b)
    except Exception as e:
        _log_err("H2H fetch", e)

    try:
        recent_a = nc.get_team_recent_form(id_a)
        form_a   = np_nba.extract_form_for_display(recent_a, id_a)
    except Exception as e:
        _log_err("Form A fetch", e)

    try:
        recent_b = nc.get_team_recent_form(id_b)
        form_b   = np_nba.extract_form_for_display(recent_b, id_b)
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
    except Exception as e:
        _log_err("Injuries A", e)

    try:
        injuries_b = nc.get_team_injuries(id_b)
    except Exception as e:
        _log_err("Injuries B", e)

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

    return render_template(
        "nba/matchup.html",
        team_a=team_a, team_b=team_b,
        h2h_rows=h2h_rows,
        form_a=form_a, form_b=form_b,
        split_a=split_a, split_b=split_b,
        stats_a=stats_a, stats_b=stats_b,
        injuries_a=injuries_a, injuries_b=injuries_b,
        error=error,
        route_support=_support("matchup"),
    )


@nba_bp.route("/player")
def player():
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error      = None
    roster_a   = []
    roster_b   = []

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

    return render_template(
        "nba/player.html",
        team_a=team_a, team_b=team_b,
        roster_a=roster_a, roster_b=roster_b,
        error=error,
        route_support=_support("player"),
    )


@nba_bp.route("/api/player-analysis")
def player_analysis_api():
    """AJAX endpoint for the player props page."""
    player_id        = request.args.get("player_id",        "").strip()
    player_team_id   = request.args.get("player_team_id",   "").strip()
    opponent_team_id = request.args.get("opponent_team_id", "").strip()

    if not player_id or not player_team_id or not opponent_team_id:
        return jsonify({"error": "Missing required params"}), 400

    try:
        season_avgs = nc.get_player_season_averages(player_id)

        last5_records = nc.get_player_last_n_games(player_id, n=5)
        last5_avgs    = nc.compute_last5_averages_from_records(last5_records)
        last5_log     = [nc.format_game_stat_line(r) for r in last5_records]

        last10_records = nc.get_player_last_n_games(player_id, n=10)
        last10_log     = [nc.format_game_stat_line(r) for r in reversed(last10_records)]

        vs_opp         = nc.get_player_vs_team(player_id, opponent_team_id,
                                                player_team_id)
        vs_opp_avgs    = vs_opp.get("averages")
        vs_opp_limited = vs_opp.get("limited_sample", True)
        vs_opp_records = [nc.format_game_stat_line(r)
                          for r in vs_opp.get("records", [])[:3]]

        props = np_nba.generate_prop_lines(
            season_avgs, last5_avgs, vs_opp_avgs, vs_opp_limited,
        )

        return jsonify({
            "season_avgs":    season_avgs,
            "last5_avgs":     last5_avgs,
            "last5_log":      last5_log,
            "last10_log":     last10_log,
            "vs_opp_avgs":    vs_opp_avgs,
            "vs_opp_records": vs_opp_records,
            "vs_opp_games":   vs_opp.get("games", 0),
            "vs_opp_limited": vs_opp_limited,
            "props":          props,
            "is_mock":        season_avgs.get("is_mock", False) if season_avgs else False,
        })

    except Exception as e:
        _log_err("player-analysis API", e)
        return jsonify({"error": str(e)}), 500


@nba_bp.route("/prediction")
def prediction():
    team_a, team_b = _require_nba_teams()
    if not team_a:
        return redirect(url_for("nba.index"))

    id_a, id_b = str(team_a["id"]), str(team_b["id"])
    error           = None
    result          = None
    h2h_games       = []
    form_a_raw      = []
    form_b_raw      = []
    injuries_a      = []
    injuries_b      = []
    stats_a         = None
    stats_b         = None

    try:
        h2h_games = nc.get_h2h(id_a, id_b)
    except Exception as e:
        _log_err("H2H for prediction", e)

    try:
        form_a_raw = nc.get_team_recent_form(id_a)
    except Exception as e:
        _log_err("Form A for prediction", e)

    try:
        form_b_raw = nc.get_team_recent_form(id_b)
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

    try:
        result = np_nba.predict_winner(
            team_a, team_b,
            h2h_games=h2h_games,
            form_a=form_a_raw,
            form_b=form_b_raw,
            injuries_a=injuries_a,
            injuries_b=injuries_b,
            stats_a=stats_a,
            stats_b=stats_b,
            team_a_is_home=True,
        )
    except Exception as e:
        _log_err("Prediction model", e)
        error = str(e)

    best_bets_list = []
    if result:
        try:
            best_bets_list = np_nba.best_bets(
                result, [], [], team_a["name"], team_b["name"]
            )
        except Exception as e:
            _log_err("Best bets", e)

    form_a_display = np_nba.extract_form_for_display(form_a_raw, id_a)
    form_b_display = np_nba.extract_form_for_display(form_b_raw, id_b)

    # Determine which components used mock data
    data_notes = []
    if any(g.get("is_mock") for g in h2h_games):
        data_notes.append("H2H history is simulated (no live endpoint)")
    if any(g.get("is_mock") for g in form_a_raw):
        data_notes.append("Recent form is simulated from live standings signals")
    data_notes.append("Team stats (PPG, net rating, records) are live from standings")

    return render_template(
        "nba/prediction.html",
        team_a=team_a, team_b=team_b,
        result=result,
        best_bets=best_bets_list,
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        stats_a=stats_a,
        stats_b=stats_b,
        form_a=form_a_display,
        form_b=form_b_display,
        data_notes=data_notes,
        error=error,
        route_support=_support("prediction"),
    )


@nba_bp.route("/standings")
def standings():
    data  = {"east": [], "west": []}
    error = None
    try:
        data = nc.get_standings()
    except Exception as e:
        error = str(e)
        _log_err("Standings fetch", e)
    return render_template(
        "nba/standings.html",
        standings=data,
        error=error,
        route_support=_support("standings"),
    )
