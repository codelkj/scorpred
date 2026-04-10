"""
scorpred_engine.py — Scorpred Weighted Prediction Engine

Scoring model (all components scored 0-10, final score 0-10):
  Form Score                (40%)  Win=+2, Draw=+1, Loss=0 · recency weights · margin bonus
  Offensive Strength        (15%)  Avg goals/pts scored in last 5 + trend adjustment
  Defensive Strength        (15%)  Avg goals/pts conceded in last 5 (fewer = higher)
  Head-to-Head Score        (10%)  Last 5 meetings, recency-weighted · recent H2H > old H2H
  Home/Away Advantage        (8%)  Moderate venue boost — real form data, not hardcoded
  Squad Availability         (5%)  Injury impact — key absences reduce score
  Opponent Strength Adj      (7%)  Adjusts form value by quality of opponents faced

Recency weights applied to last 5 matches (most recent first):
  1st = 40%,  2nd = 25%,  3rd = 15%,  4th = 10%,  5th = 10%

Final Team Score =
  (Form × 0.40) + (Offense × 0.15) + (Defense × 0.15) + (H2H × 0.10)
  + (Home/Away × 0.08) + (Squad × 0.05) + (Opp Strength × 0.07)

Design rules:
  - H2H must NOT overpower current form
  - Venue is a moderate contextual boost, not a dominant factor
  - Opponent Strength separates inflated form from real form
  - Prefer current evidence over old narratives
"""

from __future__ import annotations
import re
from typing import Any

_RECENCY_WEIGHTS = [0.40, 0.25, 0.15, 0.10, 0.10]


# ── Name normalisation (for opp-strength lookups) ─────────────────────────────

def _norm(name: str) -> str:
    """Lowercase, alphanumeric only — for fuzzy team-name matching."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _lookup_opp_strength(opponent_name: str, opp_strengths: dict[str, float]) -> float:
    """
    Find opponent strength score (0-10) from a pre-built lookup dict.
    Falls back to 5.0 (neutral) when no match found.
    """
    if not opp_strengths or not opponent_name:
        return 5.0
    key = _norm(opponent_name)
    if key in opp_strengths:
        return opp_strengths[key]
    # Partial match fallback
    for stored_key, val in opp_strengths.items():
        if key and stored_key and (key in stored_key or stored_key in key):
            return val
    return 5.0


# ── Component calculators ──────────────────────────────────────────────────────

def _form_score(form: list[dict], sport: str = "soccer") -> tuple[float, dict]:
    """
    Form score 0-10 using recency-weighted results.
    Win=+2, Draw=+1 (soccer only), Loss=0.
    Big-margin wins/losses get a +/- 0.5 adjustment.
    """
    if not form:
        return 5.0, {"details": [], "note": "No form data — neutral score applied"}

    weighted_sum = 0.0
    details = []

    for i, match in enumerate(form[:5]):
        weight = _RECENCY_WEIGHTS[i]
        result = match.get("result", "")

        if sport == "nba":
            margin = int(match.get("our_pts", 0) or 0) - int(match.get("their_pts", 0) or 0)
        else:
            margin = int(match.get("gf", 0) or 0) - int(match.get("ga", 0) or 0)

        if result == "W":
            pts = 2.0
        elif result == "D" and sport == "soccer":
            pts = 1.0
        else:
            pts = 0.0

        big_margin = 3 if sport == "soccer" else 15
        if margin >= big_margin:
            pts = min(pts + 0.5, 2.5)
        elif margin <= -big_margin:
            pts = max(pts - 0.5, -0.5)

        pts = max(-0.5, min(2.5, pts))
        weighted_sum += pts * weight
        details.append({
            "match_num": i + 1,
            "result": result,
            "pts": round(pts, 1),
            "weight": weight,
            "margin": margin,
        })

    total_weight = sum(_RECENCY_WEIGHTS[: min(5, len(form))])
    max_possible = 2.5 * total_weight
    score = (weighted_sum / max_possible * 10) if max_possible > 0 else 5.0
    return round(max(0.0, min(10.0, score)), 2), {
        "details": details,
        "weighted_sum": round(weighted_sum, 3),
    }


def _offense_score(form: list[dict], sport: str = "soccer") -> tuple[float, dict]:
    """
    Offensive strength 0-10.
    Soccer: avg goals scored (3.0 = max). NBA: avg pts scored (85-115 range).
    Trend check (last 2 vs previous 3) applies a ±1 pt adjustment.
    """
    if not form:
        return 5.0, {"avg": 0, "trend": "neutral"}

    scored_key = "our_pts" if sport == "nba" else "gf"
    values = [float(m.get(scored_key, 0) or 0) for m in form[:5]]

    if not values:
        return 5.0, {"avg": 0, "trend": "neutral"}

    avg = sum(values) / len(values)

    if sport == "nba":
        base = max(0.0, min(10.0, (avg - 85.0) / 3.0))
    else:
        base = max(0.0, min(10.0, (avg / 3.0) * 10))

    trend = "neutral"
    bonus = 0.0
    if len(values) >= 3:
        recent_avg = sum(values[:2]) / 2
        older_avg = sum(values[2:]) / len(values[2:])
        threshold = 0.5 if sport == "soccer" else 5.0
        if recent_avg > older_avg + threshold:
            trend = "increasing"
            bonus = 1.0
        elif recent_avg < older_avg - threshold:
            trend = "decreasing"
            bonus = -1.0

    final = round(max(0.0, min(10.0, base + bonus)), 2)
    return final, {"avg": round(avg, 2), "trend": trend, "base_score": round(base, 2)}


def _defense_score(form: list[dict], sport: str = "soccer") -> tuple[float, dict]:
    """
    Defensive strength 0-10. Fewer goals/pts conceded = higher score.
    Soccer: 0 conceded = 10, 3+ = 0. NBA: 85 allowed = 10, 115+ = 0.
    """
    if not form:
        return 5.0, {"avg": 0}

    conceded_key = "their_pts" if sport == "nba" else "ga"
    values = [float(m.get(conceded_key, 0) or 0) for m in form[:5]]

    if not values:
        return 5.0, {"avg": 0}

    avg = sum(values) / len(values)

    if sport == "nba":
        base = max(0.0, min(10.0, (115.0 - avg) / 3.0))
    else:
        base = max(0.0, min(10.0, (3.0 - avg) / 3.0 * 10))

    return round(base, 2), {"avg": round(avg, 2)}


def _h2h_score(h2h_form: list[dict], sport: str = "soccer") -> tuple[float, dict]:
    """
    H2H score 0-10, recency-weighted across last 5 meetings.
    Win=+2, Draw=+1 (soccer), Loss=0.
    Recent H2H matters more than older-season meetings.
    Note: this component carries 10% weight — it should not override current form.
    """
    if not h2h_form:
        return 5.0, {"details": [], "note": "No H2H data — neutral score applied"}

    weighted_sum = 0.0
    details = []

    for i, match in enumerate(h2h_form[:5]):
        weight = _RECENCY_WEIGHTS[i]
        result = match.get("result", "")

        if result == "W":
            pts = 2.0
        elif result == "D" and sport == "soccer":
            pts = 1.0
        else:
            pts = 0.0

        weighted_sum += pts * weight
        details.append({
            "match_num": i + 1,
            "result": result,
            "pts": round(pts, 1),
            "weight": weight,
        })

    total_weight = sum(_RECENCY_WEIGHTS[: min(5, len(h2h_form))])
    max_possible = 2.0 * total_weight
    score = (weighted_sum / max_possible * 10) if max_possible > 0 else 5.0
    return round(max(0.0, min(10.0, score)), 2), {
        "details": details,
        "weighted_sum": round(weighted_sum, 3),
    }


def _home_away_score(form: list[dict], is_home: bool, sport: str = "soccer") -> tuple[float, dict]:
    """
    Venue advantage 0-10.
    Base: home=6.0, away=4.5 — a moderate gap, not a dominant factor.
    Adjusted by actual venue-specific win rate from recent matches.
    """
    base = 6.0 if is_home else 4.5
    venue_key = "is_home" if sport == "nba" else "home"
    venue_form = [m for m in form[:5] if m.get(venue_key) == is_home]

    adjustment = 0.0
    win_rate = None
    if venue_form:
        wins = sum(1 for m in venue_form if m.get("result") == "W")
        win_rate = wins / len(venue_form)
        if is_home:
            if win_rate >= 0.6:
                adjustment = 1.5   # strong home form
            elif win_rate <= 0.3:
                adjustment = -1.0  # poor home form
        else:
            if win_rate >= 0.5:
                adjustment = 1.0   # decent away form
            elif win_rate <= 0.2:
                adjustment = -1.5  # poor away form

    score = round(max(0.0, min(10.0, base + adjustment)), 2)
    return score, {
        "venue": "Home" if is_home else "Away",
        "base": base,
        "adjusted": score,
        "venue_matches": len(venue_form),
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
    }


def _squad_score(injuries: list, sport: str = "soccer") -> tuple[float, dict]:
    """
    Squad availability 0-10. Full squad = 10.
    Star/key absences penalise more than role-player absences.
    Out key player: -1.5. Out non-key: -0.5. Doubtful: -0.7. Questionable: -0.3.
    """
    if not injuries:
        return 10.0, {"total_injured": 0, "penalty": 0.0}

    key_positions = (
        {"G", "F", "C", "PG", "SG", "SF", "PF"}
        if sport == "nba"
        else {"Attacker", "Midfielder"}
    )

    penalty = 0.0
    for inj in injuries:
        status = str((inj.get("status") or "")).lower()
        if sport == "nba":
            pos = str((inj.get("player", {}).get("pos") or inj.get("position") or "")).upper()
        else:
            pos = str((inj.get("player", {}).get("position") or ""))

        is_key = pos in key_positions

        if status == "out":
            penalty += 1.5 if is_key else 0.5
        elif status == "doubtful":
            penalty += 0.7
        elif status == "questionable":
            penalty += 0.3

    score = round(max(0.0, min(10.0, 10.0 - penalty)), 2)
    return score, {"total_injured": len(injuries), "penalty": round(penalty, 2)}


def _opp_strength_score(
    form: list[dict],
    opp_strengths: dict[str, float],
    sport: str = "soccer",
) -> tuple[float, dict]:
    """
    Opponent Strength Adjustment 0-10.

    Separates genuine form from inflated/deflated records:
      - Strong win vs strong opponent  → high score
      - Strong win vs weak opponent    → modest score
      - Loss vs strong opponent        → small credit (expected)
      - Loss vs weak opponent          → heavy penalty

    Uses recency weighting across last 5 matches.
    Defaults to neutral 5.0 when no opponent strength data is available.
    """
    if not form:
        return 5.0, {"avg_opp_strength": 5.0, "note": "No form data"}

    # If no lookup table provided, return neutral
    if not opp_strengths:
        return 5.0, {"avg_opp_strength": 5.0, "note": "No standings data — neutral applied"}

    weighted_sum = 0.0
    total_weight = 0.0
    details = []

    for i, match in enumerate(form[:5]):
        weight = _RECENCY_WEIGHTS[i]
        result = match.get("result", "")
        opp_name = match.get("opponent", "")
        opp_str = _lookup_opp_strength(opp_name, opp_strengths)  # 0-10

        # Opponent quality factor: 0.0 = weakest, 1.0 = strongest
        opp_factor = opp_str / 10.0

        # Points earned, adjusted by opponent quality
        if result == "W":
            # Win vs top opponent = 2.0, vs weakest = 1.0
            pts = 1.0 + opp_factor
        elif result == "D" and sport == "soccer":
            # Draw vs top opponent = 0.75, vs weakest = 0.25
            pts = 0.25 + opp_factor * 0.5
        else:
            # Loss vs strongest = 0.3 credit; vs weakest = 0 (penalised)
            pts = opp_factor * 0.3

        weighted_sum += pts * weight
        total_weight += weight
        details.append({
            "match_num": i + 1,
            "opponent": opp_name,
            "opp_strength": round(opp_str, 1),
            "result": result,
            "pts": round(pts, 2),
        })

    # Max possible: Win against strongest opponent every game = 2.0 × sum_weights
    max_possible = 2.0 * sum(_RECENCY_WEIGHTS[: min(5, len(form))])
    avg_opp_str = sum(d["opp_strength"] for d in details) / max(len(details), 1)

    score = (weighted_sum / max_possible * 10) if max_possible > 0 else 5.0
    return round(max(0.0, min(10.0, score)), 2), {
        "avg_opp_strength": round(avg_opp_str, 1),
        "details": details,
        "weighted_sum": round(weighted_sum, 3),
    }


# ── Key edges + optional picks ─────────────────────────────────────────────────

def _build_key_edges(
    comp_a: dict,
    comp_b: dict,
    name_a: str,
    name_b: str,
) -> list[dict]:
    """Return top 3 biggest scoring advantages between the two teams."""
    labels = {
        "form":           "Recent Form",
        "offense":        "Attacking Power",
        "defense":        "Defensive Strength",
        "h2h":            "Head-to-Head Record",
        "home_away":      "Venue Advantage",
        "squad":          "Squad Availability",
        "opp_strength":   "Opponent Quality Faced",
    }

    diffs = [
        (key, label, comp_a.get(key, 5.0) - comp_b.get(key, 5.0),
         comp_a.get(key, 5.0), comp_b.get(key, 5.0))
        for key, label in labels.items()
    ]
    diffs.sort(key=lambda x: abs(x[2]), reverse=True)

    edges = []
    for key, label, diff, a_val, b_val in diffs[:3]:
        if abs(diff) < 0.3:
            continue
        winner_name = name_a if diff > 0 else name_b
        edges.append({
            "team": "A" if diff > 0 else "B",
            "team_name": winner_name,
            "category": label,
            "margin": round(abs(diff), 1),
            "a_val": round(a_val, 1),
            "b_val": round(b_val, 1),
            "detail": f"{winner_name} leads in {label} ({a_val:.1f} vs {b_val:.1f})",
        })

    return edges[:3]


def _build_matchup_reading(
    comp_a: dict,
    comp_b: dict,
    name_a: str,
    name_b: str,
    score_a: float,
    score_b: float,
    sport: str,
) -> str:
    """
    Generate a concise analytical matchup reading that explains which side
    is actually stronger right now, whether form is real, and what to watch.
    """
    lines = []

    stronger = name_a if score_a > score_b else (name_b if score_b > score_a else None)
    if stronger:
        lines.append(f"{stronger} hold the clearest overall edge ({score_a:.1f} vs {score_b:.1f}).")

    # Form vs H2H conflict check
    form_leader = "A" if comp_a["form"] > comp_b["form"] + 0.5 else (
        "B" if comp_b["form"] > comp_a["form"] + 0.5 else None
    )
    h2h_leader = "A" if comp_a["h2h"] > comp_b["h2h"] + 0.5 else (
        "B" if comp_b["h2h"] > comp_a["h2h"] + 0.5 else None
    )
    if form_leader and h2h_leader and form_leader != h2h_leader:
        form_name = name_a if form_leader == "A" else name_b
        h2h_name = name_a if h2h_leader == "A" else name_b
        lines.append(
            f"Current form favours {form_name}, but H2H history leans {h2h_name} — "
            f"recent form carries 4× the weight of H2H in this model."
        )

    # Opponent quality flag
    opp_a = comp_a.get("opp_strength", 5.0)
    opp_b = comp_b.get("opp_strength", 5.0)
    if opp_a < 4.0:
        lines.append(f"{name_a}'s recent results came against weaker opposition — treat their form with caution.")
    if opp_b < 4.0:
        lines.append(f"{name_b}'s recent results came against weaker opposition — treat their form with caution.")
    if opp_a > 7.0:
        lines.append(f"{name_a} have been tested by quality opponents recently, making their form more credible.")

    # Attack/defense summary
    att_leader = name_a if comp_a["offense"] > comp_b["offense"] + 1.0 else (
        name_b if comp_b["offense"] > comp_a["offense"] + 1.0 else None
    )
    def_leader = name_a if comp_a["defense"] > comp_b["defense"] + 1.0 else (
        name_b if comp_b["defense"] > comp_a["defense"] + 1.0 else None
    )
    if att_leader:
        lines.append(f"{att_leader} carry the stronger attacking threat right now.")
    if def_leader:
        lines.append(f"{def_leader} are the tighter defensive unit.")

    return " ".join(lines) if lines else "Scores are close — this is a genuinely competitive matchup."


def _optional_picks(form_a: list[dict], form_b: list[dict], sport: str) -> list[dict]:
    """Generate optional picks only when trends clearly support them."""
    picks = []

    if sport == "nba":
        scored_key, conceded_key = "our_pts", "their_pts"
    else:
        scored_key, conceded_key = "gf", "ga"

    a_scored = [float(m.get(scored_key, 0) or 0) for m in form_a[:5]]
    b_scored = [float(m.get(scored_key, 0) or 0) for m in form_b[:5]]
    a_conced = [float(m.get(conceded_key, 0) or 0) for m in form_a[:5]]
    b_conced = [float(m.get(conceded_key, 0) or 0) for m in form_b[:5]]

    if not a_scored or not b_scored:
        return picks

    avg_a = sum(a_scored) / len(a_scored)
    avg_b = sum(b_scored) / len(b_scored)
    avg_total = avg_a + avg_b

    if sport == "nba":
        line = 220.0
        lean = "Over" if avg_total > line else "Under"
        picks.append({
            "market": f"Total Points O/U {line:.0f}",
            "lean": lean,
            "reasoning": f"Avg combined scoring: {avg_total:.1f} pts/game",
        })
    else:
        lean = "Over" if avg_total > 2.5 else "Under"
        picks.append({
            "market": "Goals Over/Under 2.5",
            "lean": lean,
            "reasoning": f"Avg combined goals: {avg_total:.2f}/game",
        })

        # BTTS — only include if conviction is clear
        a_score_rate = sum(1 for v in a_scored if v > 0) / len(a_scored)
        b_score_rate = sum(1 for v in b_scored if v > 0) / len(b_scored)
        a_conc_rate  = sum(1 for v in a_conced if v > 0) / max(len(a_conced), 1)
        b_conc_rate  = sum(1 for v in b_conced if v > 0) / max(len(b_conced), 1)
        btts_prob = (a_score_rate + b_conc_rate + b_score_rate + a_conc_rate) / 4
        picks.append({
            "market": "Both Teams to Score",
            "lean": "Yes" if btts_prob >= 0.5 else "No",
            "reasoning": f"BTTS probability ~{btts_prob * 100:.0f}% from recent scoring rates",
        })

    return picks


# ── Core scoring function ──────────────────────────────────────────────────────

def calculate_team_score(
    form: list[dict],
    h2h_form: list[dict],
    injuries: list,
    is_home: bool,
    opp_strengths: dict[str, float] | None = None,
    sport: str = "soccer",
) -> tuple[float, dict]:
    """
    Calculate the final Scorpred team score (0-10) and full component breakdown.

    Args:
        form          — last 5 completed matches from this team's perspective
        h2h_form      — last 5 H2H meetings from this team's perspective
        injuries      — current injury list for this team
        is_home       — True if this team is playing at home
        opp_strengths — dict of normalised_name → strength (0-10) from standings
        sport         — "soccer" or "nba"
    """
    f_score,  f_det  = _form_score(form, sport)
    o_score,  o_det  = _offense_score(form, sport)
    d_score,  d_det  = _defense_score(form, sport)
    h_score,  h_det  = _h2h_score(h2h_form, sport)
    ha_score, ha_det = _home_away_score(form, is_home, sport)
    s_score,  s_det  = _squad_score(injuries, sport)
    os_score, os_det = _opp_strength_score(form, opp_strengths or {}, sport)

    final = round(
        f_score  * 0.40 +
        o_score  * 0.15 +
        d_score  * 0.15 +
        h_score  * 0.10 +
        ha_score * 0.08 +
        s_score  * 0.05 +
        os_score * 0.07,
        2,
    )
    final = max(0.0, min(10.0, final))

    return final, {
        "form":         f_score,
        "offense":      o_score,
        "defense":      d_score,
        "h2h":          h_score,
        "home_away":    ha_score,
        "squad":        s_score,
        "opp_strength": os_score,
        "details": {
            "form":         f_det,
            "offense":      o_det,
            "defense":      d_det,
            "h2h":          h_det,
            "home_away":    ha_det,
            "squad":        s_det,
            "opp_strength": os_det,
        },
    }


# ── Main prediction entry point ────────────────────────────────────────────────

def scorpred_predict(
    form_a: list[dict],
    form_b: list[dict],
    h2h_form_a: list[dict],
    h2h_form_b: list[dict],
    injuries_a: list,
    injuries_b: list,
    team_a_is_home: bool,
    team_a_name: str = "Team A",
    team_b_name: str = "Team B",
    sport: str = "soccer",
    opp_strengths: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Run the full Scorpred prediction model for a match.

    Args:
        form_a / form_b         — last 5 matches per team (team's perspective)
        h2h_form_a / h2h_form_b — last 5 H2H games per team (team's perspective)
        injuries_a / injuries_b — current injury lists
        team_a_is_home          — True if team A is the home side
        team_a_name / team_b_name — display names
        sport                   — "soccer" or "nba"
        opp_strengths           — dict of normalised_team_name → strength (0-10)
                                   built from league standings; if None, defaults
                                   to neutral 5.0 for opponent quality

    Returns a dict with:
        team_a_score / team_b_score  — final 0-10 scores
        score_gap                    — absolute difference
        components_a / components_b  — per-component scores
        comparison                   — which team leads each component
        key_edges                    — top 2-3 biggest advantages
        matchup_reading              — analytical explanation
        best_pick                    — prediction, confidence, reasoning
        optional_picks               — over/under and BTTS suggestions
    """
    score_a, comp_a = calculate_team_score(
        form_a, h2h_form_a, injuries_a, team_a_is_home, opp_strengths, sport
    )
    score_b, comp_b = calculate_team_score(
        form_b, h2h_form_b, injuries_b, not team_a_is_home, opp_strengths, sport
    )

    def _edge(a: float, b: float) -> str:
        if a > b + 0.3:
            return "A"
        if b > a + 0.3:
            return "B"
        return "equal"

    a_trend = comp_a["details"]["offense"].get("trend", "neutral")
    b_trend = comp_b["details"]["offense"].get("trend", "neutral")
    if a_trend == "increasing" and b_trend != "increasing":
        trending_up = "A"
    elif b_trend == "increasing" and a_trend != "increasing":
        trending_up = "B"
    elif a_trend == "increasing" and b_trend == "increasing":
        trending_up = "both"
    else:
        trending_up = "neither"

    comparison = {
        "form":                _edge(comp_a["form"],         comp_b["form"]),
        "offense":             _edge(comp_a["offense"],      comp_b["offense"]),
        "defense":             _edge(comp_a["defense"],      comp_b["defense"]),
        "h2h":                 _edge(comp_a["h2h"],          comp_b["h2h"]),
        "home_away":           _edge(comp_a["home_away"],    comp_b["home_away"]),
        "squad":               _edge(comp_a["squad"],        comp_b["squad"]),
        "opp_strength":        _edge(comp_a["opp_strength"], comp_b["opp_strength"]),
        "trending_up_offense": trending_up,
    }

    # Best pick + confidence
    gap = abs(score_a - score_b)
    if gap >= 2.0:
        confidence = "High"
    elif gap >= 0.8:
        confidence = "Medium"
    else:
        confidence = "Low"

    if score_a > score_b + 0.5:
        prediction = f"{team_a_name} Win"
        pick_team = "A"
    elif score_b > score_a + 0.5:
        prediction = f"{team_b_name} Win"
        pick_team = "B"
    else:
        if sport == "soccer":
            prediction = "Draw"
            pick_team = "draw"
        else:
            prediction = f"{team_a_name} Win" if score_a >= score_b else f"{team_b_name} Win"
            pick_team = "A" if score_a >= score_b else "B"

    comp_keys = ("form", "offense", "defense", "h2h", "home_away", "squad", "opp_strength")
    comp_a_clean = {k: comp_a[k] for k in comp_keys}
    comp_b_clean = {k: comp_b[k] for k in comp_keys}

    key_edges = _build_key_edges(comp_a_clean, comp_b_clean, team_a_name, team_b_name)
    matchup_reading = _build_matchup_reading(
        comp_a_clean, comp_b_clean, team_a_name, team_b_name, score_a, score_b, sport
    )

    top_edge_text = key_edges[0]["detail"] if key_edges else f"Scores are close ({score_a} vs {score_b})"
    reasoning = f"{top_edge_text}. Gap: {gap:.1f}/10."

    return {
        "team_a_score":   score_a,
        "team_b_score":   score_b,
        "score_gap":      round(gap, 2),
        "components_a":   comp_a_clean,
        "components_b":   comp_b_clean,
        "comparison":     comparison,
        "key_edges":      key_edges,
        "matchup_reading": matchup_reading,
        "best_pick": {
            "prediction": prediction,
            "team":       pick_team,
            "confidence": confidence,
            "reasoning":  reasoning,
        },
        "optional_picks": _optional_picks(form_a, form_b, sport),
    }


# ── Standings → opponent-strength lookup builder ──────────────────────────────

def build_opp_strengths_from_standings(standings: list) -> dict[str, float]:
    """
    Convert a league standings list into a normalised_name → strength (0-10) dict.

    Top of the table = 10, bottom = 1. Scales linearly across all teams.
    Returns empty dict when standings are unavailable.
    """
    if not standings:
        return {}
    total = len(standings)
    if total == 1:
        return {_norm((standings[0].get("team") or {}).get("name", "")): 5.0}

    lookup = {}
    for s in standings:
        name = (s.get("team") or {}).get("name", "")
        rank = s.get("rank", 0) or 0
        if not name or not rank:
            continue
        strength = round((total - rank) / (total - 1) * 10, 1)
        strength = max(0.0, min(10.0, strength))
        lookup[_norm(name)] = strength

    return lookup
