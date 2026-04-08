"""
app.py — Flask application for ScorPred football prediction app.
"""

import os
from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify
)
from dotenv import load_dotenv
import api_client_provider as ac
import predictor as pred

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "scorpred-dev-secret")

LEAGUE = 39   # Premier League
SEASON = 2024


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_teams():
    """Return (team_a, team_b) session dicts, or None if not set."""
    if "team_a_id" not in session:
        return None, None
    return (
        {"id": session["team_a_id"], "name": session["team_a_name"], "logo": session["team_a_logo"]},
        {"id": session["team_b_id"], "name": session["team_b_name"], "logo": session["team_b_logo"]},
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    load_error = None
    try:
        teams = ac.get_teams(LEAGUE, SEASON)
    except Exception as e:
        teams = []
        load_error = str(e)
        app.logger.error("Failed to fetch teams: %s", e)
    return render_template("index.html", teams=teams, load_error=load_error)


@app.route("/select", methods=["POST"])
def select():
    a_id = request.form.get("team_a", type=int)
    b_id = request.form.get("team_b", type=int)

    if not a_id or not b_id or a_id == b_id:
        return redirect(url_for("index"))

    # Resolve names/logos from teams list
    try:
        teams = ac.get_teams(LEAGUE, SEASON)
    except Exception:
        return redirect(url_for("index"))

    team_map = {t["team"]["id"]: t["team"] for t in teams}

    if a_id not in team_map or b_id not in team_map:
        return redirect(url_for("index"))

    session["team_a_id"] = a_id
    session["team_a_name"] = team_map[a_id]["name"]
    session["team_a_logo"] = team_map[a_id]["logo"]
    session["team_b_id"] = b_id
    session["team_b_name"] = team_map[b_id]["name"]
    session["team_b_logo"] = team_map[b_id]["logo"]

    return redirect(url_for("matchup"))


@app.route("/matchup")
def matchup():
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    id_a, id_b = team_a["id"], team_b["id"]

    try:
        h2h_raw = ac.get_h2h(id_a, id_b, last=10)
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=10)
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=10)
        injuries_a = ac.get_injuries(id_a, LEAGUE, SEASON)
        injuries_b = ac.get_injuries(id_b, LEAGUE, SEASON)
    except Exception as e:
        app.logger.error("matchup fetch error: %s", e)
        return render_template("error.html", msg=str(e))

    # Enrich last 5 H2H fixtures with events + stats
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

    return render_template(
        "matchup.html",
        team_a=team_a, team_b=team_b,
        h2h=h2h_enriched,
        h2h_rec=h2h_rec,
        form_a=form_a, form_b=form_b,
        split_a=split_a, split_b=split_b,
        injuries_a=injuries_a, injuries_b=injuries_b,
    )


@app.route("/player")
def player():
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    try:
        squad_a = ac.get_squad(team_a["id"])
        squad_b = ac.get_squad(team_b["id"])
    except Exception as e:
        app.logger.error("player fetch error: %s", e)
        squad_a, squad_b = [], []

    return render_template(
        "player.html",
        team_a=team_a, team_b=team_b,
        squad_a=squad_a, squad_b=squad_b,
    )


@app.route("/api/player-stats")
def player_stats_api():
    pid = request.args.get("id", type=int)
    if not pid:
        return jsonify({"error": "missing id"}), 400
    try:
        data = ac.get_player_stats(pid, SEASON)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prediction")
def prediction():
    team_a, team_b = _require_teams()
    if not team_a:
        return redirect(url_for("index"))

    id_a, id_b = team_a["id"], team_b["id"]

    try:
        h2h = ac.get_h2h(id_a, id_b, last=10)
        fixtures_a = ac.get_team_fixtures(id_a, LEAGUE, SEASON, last=10)
        fixtures_b = ac.get_team_fixtures(id_b, LEAGUE, SEASON, last=10)
        injuries_a = ac.get_injuries(id_a, LEAGUE, SEASON)
        injuries_b = ac.get_injuries(id_b, LEAGUE, SEASON)
        squad_a = ac.get_squad(id_a)
        squad_b = ac.get_squad(id_b)
    except Exception as e:
        app.logger.error("prediction fetch error: %s", e)
        return render_template("error.html", msg=str(e))

    result = pred.predict(
        id_a, id_b, h2h, fixtures_a, fixtures_b,
        injuries_a, injuries_b, squad_a, squad_b
    )

    return render_template(
        "prediction.html",
        team_a=team_a, team_b=team_b,
        result=result,
    )


# ── Error page ────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", msg="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", msg=str(e)), 500


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
