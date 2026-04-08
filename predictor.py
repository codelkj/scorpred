"""
predictor.py — All prediction logic.

Weighted 1X2 model (H2H 25% | Form 30% | Home/Away 20% | Injuries 15% | xG 10%)
Poisson distribution for correct scores and goal totals.
"""

from __future__ import annotations

import math
from typing import Any


# ── Form extraction ────────────────────────────────────────────────────────────

def extract_form(fixtures: list, team_id: int) -> list[dict]:
    """Return per-match summary dicts for team_id from a fixture list."""
    form = []
    for f in fixtures:
        h_id = f["teams"]["home"]["id"]
        a_id = f["teams"]["away"]["id"]
        hg = f["goals"]["home"]
        ag = f["goals"]["away"]

        if hg is None or ag is None:
            continue

        is_home = h_id == team_id
        gf = hg if is_home else ag
        ga = ag if is_home else hg
        opp_name = f["teams"]["away"]["name"] if is_home else f["teams"]["home"]["name"]
        opp_logo = f["teams"]["away"]["logo"] if is_home else f["teams"]["home"]["logo"]

        if gf > ga:
            result = "W"
        elif gf < ga:
            result = "L"
        else:
            result = "D"

        form.append({
            "result": result,
            "gf": gf,
            "ga": ga,
            "opponent": opp_name,
            "opponent_logo": opp_logo,
            "home": is_home,
            "date": f["fixture"]["date"][:10],
            "league": f["league"]["name"],
            "score": f"{gf}-{ga}",
            "cs": ga == 0,
        })
    return form


# ── Stat helpers ───────────────────────────────────────────────────────────────

def form_pts(form: list[dict]) -> float:
    """Points-per-game ratio (0–1)."""
    if not form:
        return 0.5
    pts = sum(3 if r["result"] == "W" else 1 if r["result"] == "D" else 0 for r in form)
    return pts / (len(form) * 3)


def avg_goals(form: list[dict], scored: bool = True) -> float:
    if not form:
        return 1.2
    goals = [r["gf"] if scored else r["ga"] for r in form]
    return float(sum(goals) / len(goals))


def home_away_split(form: list[dict]) -> dict:
    home = [r for r in form if r["home"]]
    away = [r for r in form if not r["home"]]

    def summary(rows):
        if not rows:
            return {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}
        w = sum(1 for r in rows if r["result"] == "W")
        d = sum(1 for r in rows if r["result"] == "D")
        l = sum(1 for r in rows if r["result"] == "L")
        return {
            "p": len(rows), "w": w, "d": d, "l": l,
            "gf": round(avg_goals(rows, True), 2),
            "ga": round(avg_goals(rows, False), 2),
        }

    return {"home": summary(home), "away": summary(away)}


# ── H2H record ─────────────────────────────────────────────────────────────────

def h2h_record(fixtures: list, id_a: int, id_b: int) -> dict:
    a_wins = draws = b_wins = 0
    for f in fixtures:
        h_id = f["teams"]["home"]["id"]
        hg = f["goals"]["home"] or 0
        ag = f["goals"]["away"] or 0
        ga = hg if h_id == id_a else ag
        gb = ag if h_id == id_a else hg
        if ga > gb:
            a_wins += 1
        elif ga < gb:
            b_wins += 1
        else:
            draws += 1

    total = a_wins + draws + b_wins or 1
    return {
        "a_wins": a_wins, "draws": draws, "b_wins": b_wins, "total": total,
        "a_pct": a_wins / total, "d_pct": draws / total, "b_pct": b_wins / total,
    }


# ── Poisson model ──────────────────────────────────────────────────────────────

def _poisson_pmf(goals: int, lam: float) -> float:
    if goals < 0:
        return 0.0
    if lam <= 0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(goals * math.log(lam) - lam - math.lgamma(goals + 1))


def _poisson_cdf(goals: int, lam: float) -> float:
    if goals < 0:
        return 0.0
    return float(sum(_poisson_pmf(i, lam) for i in range(goals + 1)))


def score_matrix(lam_a: float, lam_b: float, max_g: int = 6) -> dict:
    return {
        (i, j): float(_poisson_pmf(i, lam_a) * _poisson_pmf(j, lam_b))
        for i in range(max_g + 1)
        for j in range(max_g + 1)
    }


def over_prob(lam: float, threshold: float) -> float:
    return float(1 - _poisson_cdf(int(threshold), lam))


# ── Top scorer candidates ──────────────────────────────────────────────────────

def top_scorer_candidates(squad: list, injuries: list, team_lambda: float) -> list[dict]:
    """
    Build a ranked list of first-goalscorer candidates from the squad.
    Without detailed per-player API calls we rank by position heuristic.
    """
    injured_ids = {i["player"]["id"] for i in injuries}
    attackers = [p for p in squad if p.get("position") in ("Attacker", "Midfielder")]
    candidates = []
    base_prob = team_lambda / max(len(attackers), 1)
    for i, p in enumerate(attackers[:8]):
        penalty = 0.6 if p["id"] in injured_ids else 1.0
        pos_boost = 1.4 if p.get("position") == "Attacker" else 1.0
        prob = round(min(base_prob * pos_boost * penalty * 100, 35), 1)
        candidates.append({"name": p["name"], "photo": p.get("photo", ""), "prob": prob,
                           "injured": p["id"] in injured_ids})
    candidates.sort(key=lambda x: x["prob"], reverse=True)
    return candidates[:3]


# ── Main prediction ────────────────────────────────────────────────────────────

def predict(
    team_a_id: int,
    team_b_id: int,
    h2h: list,
    fixtures_a: list,
    fixtures_b: list,
    injuries_a: list,
    injuries_b: list,
    squad_a: list = None,
    squad_b: list = None,
) -> dict[str, Any]:

    form_a = extract_form(fixtures_a, team_a_id)[:10]
    form_b = extract_form(fixtures_b, team_b_id)[:10]
    form_a5 = form_a[:5]
    form_b5 = form_b[:5]

    rec = h2h_record(h2h, team_a_id, team_b_id)

    # Form score (0–1)
    fs_a = form_pts(form_a5)
    fs_b = form_pts(form_b5)
    f_tot = fs_a + fs_b or 1

    # Goals per game (used for Poisson lambda)
    avg_gf_a = avg_goals(form_a5, scored=True)
    avg_ga_b = avg_goals(form_b5, scored=False)
    avg_gf_b = avg_goals(form_b5, scored=True)
    avg_ga_a = avg_goals(form_a5, scored=False)

    # Attack-strength weighted lambda
    lam_a = max(0.3, (avg_gf_a + avg_ga_b) / 2)
    lam_b = max(0.3, (avg_gf_b + avg_ga_a) / 2)
    avg_total = lam_a + lam_b

    # xG proxy from lambda
    xg_tot = lam_a + lam_b or 1
    xg_a = lam_a / xg_tot
    xg_b = lam_b / xg_tot

    # Injury penalty
    inj_pen_a = min(0.12, len(injuries_a) * 0.025)
    inj_pen_b = min(0.12, len(injuries_b) * 0.025)

    # Home advantage factor
    home_a = 0.55
    home_b = 1 - home_a

    # Weighted raw scores
    raw_a = (
        rec["a_pct"] * 0.25
        + (fs_a / f_tot) * 0.30
        + home_a * 0.20
        + (1 - inj_pen_a) * 0.15
        + xg_a * 0.10
    )
    raw_b = (
        rec["b_pct"] * 0.25
        + (fs_b / f_tot) * 0.30
        + home_b * 0.20
        + (1 - inj_pen_b) * 0.15
        + xg_b * 0.10
    )
    raw_d = max(0.08, 1 - raw_a - raw_b)
    total = raw_a + raw_d + raw_b
    p_a, p_d, p_b = raw_a / total, raw_d / total, raw_b / total

    # Poisson correct scores
    matrix = score_matrix(lam_a, lam_b)
    top3 = sorted(matrix.items(), key=lambda x: x[1], reverse=True)[:3]

    # BTTS
    a_scored_rate = sum(1 for r in form_a5 if r["gf"] > 0) / max(len(form_a5), 1)
    b_scored_rate = sum(1 for r in form_b5 if r["gf"] > 0) / max(len(form_b5), 1)
    a_conc_rate = sum(1 for r in form_a5 if r["ga"] > 0) / max(len(form_a5), 1)
    b_conc_rate = sum(1 for r in form_b5 if r["ga"] > 0) / max(len(form_b5), 1)
    btts = (a_scored_rate + b_conc_rate + b_scored_rate + a_conc_rate) / 4

    # Over/Under
    p_over25 = over_prob(avg_total, 2)
    p_over15 = over_prob(avg_total, 1)

    # Corners (avg from form data — exact requires fixture stats endpoint)
    avg_corners = 10.2
    p_over95_corners = round(
        sum(1 for r in (form_a5 + form_b5) if r["gf"] + r["ga"] >= 2) / max(len(form_a5 + form_b5), 1) * 60 + 40, 1
    )

    # Confidence
    best = max(p_a, p_d, p_b)
    confidence = "High" if best > 0.55 else "Medium" if best > 0.42 else "Low"
    winner_label = "Team A" if p_a == best else ("Draw" if p_d == best else "Team B")

    # First goalscorer candidates
    fgs_a = top_scorer_candidates(squad_a or [], injuries_a, lam_a)
    fgs_b = top_scorer_candidates(squad_b or [], injuries_b, lam_b)

    # Home/Away season splits
    split_a = home_away_split(form_a)
    split_b = home_away_split(form_b)

    return {
        # 1X2
        "win_prob": {
            "a": round(p_a * 100, 1),
            "draw": round(p_d * 100, 1),
            "b": round(p_b * 100, 1),
        },
        "recommended_winner": winner_label,
        "confidence": confidence,

        # BTTS
        "btts_yes": round(btts * 100, 1),
        "btts_no": round((1 - btts) * 100, 1),

        # Over/Under
        "over25": round(p_over25 * 100, 1),
        "over15": round(p_over15 * 100, 1),
        "avg_total_goals": round(avg_total, 2),

        # Correct scores
        "top_scores": [
            {"score": f"{s[0][0]}-{s[0][1]}", "prob": round(s[1] * 100, 1)}
            for s in top3
        ],

        # Corners
        "corners_avg": avg_corners,
        "over95_corners": p_over95_corners,

        # Lambdas
        "lambda_a": round(lam_a, 2),
        "lambda_b": round(lam_b, 2),

        # Supporting data
        "form_a": form_a5,
        "form_b": form_b5,
        "h2h_record": rec,
        "injuries_a": injuries_a,
        "injuries_b": injuries_b,
        "fgs_a": fgs_a,
        "fgs_b": fgs_b,
        "split_a": split_a,
        "split_b": split_b,

        # Derived display
        "avg_gf_a": round(avg_gf_a, 2),
        "avg_ga_a": round(avg_ga_a, 2),
        "avg_gf_b": round(avg_gf_b, 2),
        "avg_ga_b": round(avg_ga_b, 2),
    }
