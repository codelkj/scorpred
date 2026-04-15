"""Unified prediction orchestration for soccer and NBA routes.

ScorMastermind blends:
- Rule-based engine output (scorpred_engine)
- Optional ML signal (report-driven or provided model output)
- Lightweight heuristics (form + context)

Primary API:
    predict_match(context) -> dict
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import ml_service
from runtime_paths import elo_state_path, ml_report_path
import scorpred_engine as se

_ML_REPORT_PATH = ml_report_path()

# ── ELO state cache (loaded once from training output) ───────────────────────────
class _EloCache:
    ratings: dict[str, float] | None = None


def _load_soccer_elo() -> dict[str, float]:
    """Return ELO ratings dict saved by train_model.py. Falls back to empty dict."""
    if _EloCache.ratings is not None:
        return _EloCache.ratings
    try:
        path = elo_state_path()
        if path.exists():
            _EloCache.ratings = json.loads(path.read_text(encoding="utf-8"))
            return _EloCache.ratings
    except Exception:
        pass
    _EloCache.ratings = {}
    return _EloCache.ratings


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.72:
        return "High"
    if confidence >= 0.57:
        return "Medium"
    return "Low"


def _is_weak_data_quality(data_quality: str) -> bool:
    return str(data_quality or "").strip().lower() in {"limited", "weak", "poor"}


def _load_ml_report() -> dict[str, Any] | None:
    if not _ML_REPORT_PATH.exists():
        return None
    try:
        return json.loads(_ML_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _results_to_points(rows: list[dict], sport: str) -> float:
    if not rows:
        return 0.5
    pts = 0.0
    for row in rows[:5]:
        result = str(row.get("result", "")).upper()
        if result == "W":
            pts += 1.0
        elif result == "D" and sport == "soccer":
            pts += 0.45
    return pts / max(1.0, min(5.0, float(len(rows[:5]))))


def _heuristic_signal(context: dict[str, Any]) -> dict[str, Any]:
    sport = str(context.get("sport") or "soccer").lower()
    form_a = context.get("form_a") or []
    form_b = context.get("form_b") or []
    team_a_is_home = bool(context.get("team_a_is_home", True))

    form_a_pts = _results_to_points(form_a, sport)
    form_b_pts = _results_to_points(form_b, sport)
    form_delta = form_a_pts - form_b_pts

    home_adv = 0.06 if team_a_is_home else -0.06
    prob_a = _clamp(0.5 + form_delta * 0.22 + home_adv, 0.05, 0.95)
    return {
        "available": True,
        "prob_a": prob_a,
        "form_delta": round(form_delta, 3),
        "home_advantage": home_adv,
    }


def _average_metric(rows: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    if not rows:
        return default
    values = [_safe_float(row.get(key), default) for row in rows]
    return sum(values) / len(values)


_ELO_DEFAULT = 1500.0


def _build_elo_features(context: dict[str, Any]) -> dict[str, float]:
    """Look up pre-match ELO for both teams from the saved training state.

    Keys checked in context: ``team_a_name`` / ``team_b_name`` (exact match
    against the team names used in historical_matches.csv).  Falls back to
    the neutral 1500.0 baseline for unknown teams or a missing state file.
    """
    elo = _load_soccer_elo()
    team_a = str(context.get("team_a_name") or context.get("home_team") or "").strip()
    team_b = str(context.get("team_b_name") or context.get("away_team") or "").strip()
    home_elo = float(elo.get(team_a, _ELO_DEFAULT))
    away_elo = float(elo.get(team_b, _ELO_DEFAULT))
    return {
        "home_elo":  round(home_elo, 2),
        "away_elo":  round(away_elo, 2),
        "elo_diff":  round(home_elo - away_elo, 2),
    }


def _ml_features(context: dict[str, Any]) -> dict[str, float]:
    """Build pre-match feature dict matching FEATURE_COLUMNS in train_model.py.

    Computes all 47 features from the live form context where data is available.
    Features requiring data absent from the live context (H2H records, opponent
    PPG history) use neutral defaults that are safe for inference.
    """
    form_a = context.get("form_a") or []   # home team's recent match dicts
    form_b = context.get("form_b") or []   # away team's recent match dicts
    sport  = str(context.get("sport") or "soccer").lower()

    def _avg(rows: list[dict], key: str, window: int = 5, default: float = 0.0) -> float:
        vals = [_safe_float(row.get(key), default) for row in rows[:window]
                if row.get(key) is not None]
        return sum(vals) / len(vals) if vals else default

    def _ppg(rows: list[dict], window: int = 5) -> float:
        """Points per game – Win=3, Draw=1 (soccer only), Loss=0."""
        recent = rows[:window]
        if not recent:
            return 0.0
        pts = 0.0
        for row in recent:
            r = str(row.get("result", "")).upper()
            if r == "W":
                pts += 3.0
            elif r == "D" and sport == "soccer":
                pts += 1.0
        return pts / float(len(recent))

    def _clean_sheet_rate(rows: list[dict], window: int = 5) -> float:
        recent = rows[:window]
        if not recent:
            return 0.0
        return sum(1.0 for r in recent if _safe_float(r.get("ga"), 1.0) == 0.0) / len(recent)

    def _scored_rate(rows: list[dict], window: int = 5) -> float:
        recent = rows[:window]
        if not recent:
            return 0.0
        return sum(1.0 for r in recent if _safe_float(r.get("gf"), 0.0) >= 1.0) / len(recent)

    def _venue_rows(rows: list[dict], is_home: bool, window: int = 5) -> list[dict]:
        """Filter form entries by venue using 'is_home' or 'venue' key if available.
        Falls back to all entries when no venue metadata is present."""
        filtered = []
        for r in rows:
            r_home  = r.get("is_home")
            r_venue = str(r.get("venue", "")).upper()
            if r_home is not None:
                if bool(r_home) == is_home:
                    filtered.append(r)
            elif r_venue in ("H", "A"):
                if (r_venue == "H") == is_home:
                    filtered.append(r)
        return filtered[:window] if filtered else rows[:window]

    def _days_since_last(rows: list[dict]) -> float:
        """Estimate days since last match from the most recent form entry's date."""
        if not rows:
            return 7.0
        try:
            from datetime import date as _date
            date_str = rows[0].get("date") or rows[0].get("match_date")
            if date_str:
                last  = _date.fromisoformat(str(date_str).strip())
                today = _date.today()
                return min(float(max(0, (today - last).days)), 60.0)
        except Exception:
            pass
        return 7.0

    # ── Overall last-5 ────────────────────────────────────────────────────────
    h_gf5  = round(_avg(form_a, "gf"),    4)
    h_ga5  = round(_avg(form_a, "ga"),    4)
    a_gf5  = round(_avg(form_b, "gf"),    4)
    a_ga5  = round(_avg(form_b, "ga"),    4)
    h_ppg5 = round(_ppg(form_a, 5),       4)
    a_ppg5 = round(_ppg(form_b, 5),       4)

    # ── Overall last-10 ───────────────────────────────────────────────────────
    h_gf10  = round(_avg(form_a, "gf", 10), 4)
    h_ga10  = round(_avg(form_a, "ga", 10), 4)
    a_gf10  = round(_avg(form_b, "gf", 10), 4)
    a_ga10  = round(_avg(form_b, "ga", 10), 4)
    h_ppg10 = round(_ppg(form_a, 10),        4)
    a_ppg10 = round(_ppg(form_b, 10),        4)

    # ── Venue-specific rows ───────────────────────────────────────────────────
    h_home_rows = _venue_rows(form_a, is_home=True)
    a_away_rows = _venue_rows(form_b, is_home=False)

    h_home_ppg5 = round(_ppg(h_home_rows, 5), 4)
    a_away_ppg5 = round(_ppg(a_away_rows, 5), 4)
    h_scored_rate5 = round(_scored_rate(form_a, 5), 4)
    a_scored_rate5 = round(_scored_rate(form_b, 5), 4)
    h_clean_sheet_rate5 = round(_clean_sheet_rate(form_a, 5), 4)
    a_clean_sheet_rate5 = round(_clean_sheet_rate(form_b, 5), 4)
    days_home = _days_since_last(form_a)
    days_away = _days_since_last(form_b)

    attack_vs_defense_home = round(h_gf5 - a_ga5, 4)
    attack_vs_defense_away = round(a_gf5 - h_ga5, 4)

    return {
        # Overall last-5
        "home_avg_gf_5":         h_gf5,
        "home_avg_ga_5":         h_ga5,
        "home_avg_gd_5":         round(h_gf5 - h_ga5, 4),
        "home_ppg_5":            h_ppg5,
        "away_avg_gf_5":         a_gf5,
        "away_avg_ga_5":         a_ga5,
        "away_avg_gd_5":         round(a_gf5 - a_ga5, 4),
        "away_ppg_5":            a_ppg5,
        # Overall last-10
        "home_avg_gf_10":        h_gf10,
        "home_avg_ga_10":        h_ga10,
        "home_ppg_10":           h_ppg10,
        "away_avg_gf_10":        a_gf10,
        "away_avg_ga_10":        a_ga10,
        "away_ppg_10":           a_ppg10,
        # Trend delta
        "home_ppg_delta_5v10":   round(h_ppg5 - h_ppg10, 4),
        "home_gf_delta_5v10":    round(h_gf5  - h_gf10,  4),
        "away_ppg_delta_5v10":   round(a_ppg5 - a_ppg10, 4),
        "away_gf_delta_5v10":    round(a_gf5  - a_gf10,  4),
        # Venue-specific form
        "home_home_avg_gf_5":    round(_avg(h_home_rows, "gf"),    4),
        "home_home_avg_ga_5":    round(_avg(h_home_rows, "ga"),    4),
        "home_home_ppg_5":       h_home_ppg5,
        "away_away_avg_gf_5":    round(_avg(a_away_rows, "gf"),    4),
        "away_away_avg_ga_5":    round(_avg(a_away_rows, "ga"),    4),
        "away_away_ppg_5":       a_away_ppg5,
        # Scoring consistency
        "home_clean_sheet_rate_5": h_clean_sheet_rate5,
        "away_clean_sheet_rate_5": a_clean_sheet_rate5,
        "home_scored_rate_5":      h_scored_rate5,
        "away_scored_rate_5":      a_scored_rate5,
        # Opponent strength (not in live context – neutral 1.0 default)
        "home_opp_avg_ppg_5":    1.0,
        "away_opp_avg_ppg_5":    1.0,
        # Rest / fatigue
        "days_since_last_match_home": days_home,
        "days_since_last_match_away": days_away,
        # H2H (not in live context – neutral defaults)
        "h2h_home_points_avg":   1.0,
        "h2h_goal_diff_avg":     0.0,
        # Derived comparison features
        "ppg_diff_5":            round(h_ppg5 - a_ppg5, 4),
        "gf_diff_5":             round(h_gf5 - a_gf5, 4),
        "ga_diff_5":             round(a_ga5 - h_ga5, 4),
        "venue_ppg_diff_5":      round(h_home_ppg5 - a_away_ppg5, 4),
        "attack_vs_defense_home": attack_vs_defense_home,
        "attack_vs_defense_away": attack_vs_defense_away,
        "attack_balance_diff":   round(attack_vs_defense_home - attack_vs_defense_away, 4),
        "scored_rate_diff_5":    round(h_scored_rate5 - a_scored_rate5, 4),
        "clean_sheet_diff_5":    round(h_clean_sheet_rate5 - a_clean_sheet_rate5, 4),
        "rest_diff_days":        round(days_home - days_away, 4),
        # ELO ratings (looked up from training state; default to 1500 if unknown)
        **_build_elo_features(context),
    }


def _normalize_probabilities(prob_a: float, prob_draw: float, prob_b: float) -> tuple[float, float, float]:
    total = max(prob_a + prob_draw + prob_b, 1e-9)
    return prob_a / total, prob_draw / total, prob_b / total


def _feature_edge_summary(features: dict[str, float]) -> dict[str, float]:
    ppg_diff = _safe_float(features.get("ppg_diff_5"), 0.0)
    gf_diff = _safe_float(features.get("gf_diff_5"), 0.0)
    ga_diff = _safe_float(features.get("ga_diff_5"), 0.0)
    venue_diff = _safe_float(features.get("venue_ppg_diff_5"), 0.0)
    attack_balance = _safe_float(features.get("attack_balance_diff"), 0.0)
    scored_rate_diff = _safe_float(features.get("scored_rate_diff_5"), 0.0)
    clean_sheet_diff = _safe_float(features.get("clean_sheet_diff_5"), 0.0)
    rest_diff_days = _safe_float(features.get("rest_diff_days"), 0.0)
    elo_diff = _safe_float(features.get("elo_diff"), 0.0)

    side_edge = (
        0.34 * ppg_diff
        + 0.15 * gf_diff
        + 0.15 * ga_diff
        + 0.18 * attack_balance
        + 0.10 * venue_diff
        + 0.08 * scored_rate_diff
        + 0.06 * clean_sheet_diff
        + 0.015 * rest_diff_days
        + 0.0022 * elo_diff
    )

    return {
        "ppg_diff": round(ppg_diff, 4),
        "gf_diff": round(gf_diff, 4),
        "ga_diff": round(ga_diff, 4),
        "venue_diff": round(venue_diff, 4),
        "attack_balance": round(attack_balance, 4),
        "elo_diff": round(elo_diff, 2),
        "side_edge": round(side_edge, 4),
    }


def _top_outcomes(prob_a: float, prob_b: float, prob_draw: float = 0.0) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = [
        {"team": "A", "prob": prob_a},
        {"team": "B", "prob": prob_b},
    ]
    if prob_draw > 0.0:
        outcomes.append({"team": "draw", "prob": prob_draw})
    outcomes.sort(key=lambda item: _safe_float(item.get("prob"), 0.0), reverse=True)
    return outcomes


def _blend_soccer_probabilities(
    rule_prob_a_total: float,
    rule_prob_draw: float,
    rule_prob_b_total: float,
    ml: dict[str, Any],
    edge_summary: dict[str, float],
    data_quality: str,
) -> tuple[float, float, float]:
    weak_quality = _is_weak_data_quality(data_quality)
    ml_weight = 0.56 if ml.get("available") and not weak_quality else 0.50 if ml.get("available") else 0.0
    rule_weight = 1.0 - ml_weight if ml.get("available") else 1.0

    prob_a = rule_prob_a_total
    prob_draw = rule_prob_draw
    prob_b = rule_prob_b_total

    if ml.get("available") and ml.get("prob_draw") is not None:
        ml_prob_a = _clamp(_safe_float(ml.get("prob_a"), 0.3333), 0.01, 0.99)
        ml_prob_draw = _clamp(_safe_float(ml.get("prob_draw"), 0.3333), 0.0, 0.98)
        ml_prob_b = _clamp(_safe_float(ml.get("prob_b"), 0.3334), 0.01, 0.99)

        prob_a = rule_weight * rule_prob_a_total + ml_weight * ml_prob_a
        prob_draw = rule_weight * rule_prob_draw + ml_weight * ml_prob_draw
        prob_b = rule_weight * rule_prob_b_total + ml_weight * ml_prob_b
    elif ml.get("available"):
        rule_non_draw = max(0.01, rule_prob_a_total + rule_prob_b_total)
        rule_non_draw_a = _clamp(rule_prob_a_total / rule_non_draw, 0.01, 0.99)
        ml_non_draw_a = _clamp(_safe_float(ml.get("prob_a"), 0.5), 0.01, 0.99)
        combined_non_draw_a = _clamp(rule_weight * rule_non_draw_a + ml_weight * ml_non_draw_a, 0.01, 0.99)
        prob_draw = rule_prob_draw
        prob_a = combined_non_draw_a * (1.0 - prob_draw)
        prob_b = (1.0 - combined_non_draw_a) * (1.0 - prob_draw)

    prob_a, prob_draw, prob_b = _normalize_probabilities(prob_a, prob_draw, prob_b)

    side_gap = abs(prob_a - prob_b)
    edge_strength = abs(_safe_float(edge_summary.get("side_edge"), 0.0))
    if prob_draw > 0.0:
        draw_transfer = min(
            prob_draw * 0.28,
            max(0.0, (edge_strength - 0.22) * 0.11 + max(0.0, side_gap - 0.04) * 0.70),
        )
        if draw_transfer > 0.0:
            side_total = max(prob_a + prob_b, 1e-9)
            prob_draw -= draw_transfer
            prob_a += draw_transfer * (prob_a / side_total)
            prob_b += draw_transfer * (prob_b / side_total)

    return _normalize_probabilities(prob_a, prob_draw, prob_b)


def _select_soccer_outcome(prob_a: float, prob_draw: float, prob_b: float, edge_summary: dict[str, float]) -> str:
    side_gap = abs(prob_a - prob_b)
    edge_strength = abs(_safe_float(edge_summary.get("side_edge"), 0.0))

    draw_viable = (
        prob_draw >= 0.34
        and side_gap <= 0.07
        and edge_strength <= 0.42
        and prob_draw >= max(prob_a, prob_b) - 0.01
    )
    draw_balanced = (
        prob_draw >= 0.37
        and side_gap <= 0.045
        and edge_strength <= 0.28
    )

    if draw_viable or draw_balanced:
        return "draw"
    return "A" if prob_a >= prob_b else "B"


def _confidence_score(
    prob_a: float,
    prob_draw: float,
    prob_b: float,
    *,
    selected_team: str,
    ml: dict[str, Any],
    rule_prob_a_for_compare: float,
    rule_prob_draw: float,
    has_forms: bool,
    has_stats: bool,
    data_quality: str,
    edge_summary: dict[str, float],
) -> tuple[float, float, float, bool]:
    outcomes = _top_outcomes(prob_a, prob_b, prob_draw)
    top_prob = _safe_float(outcomes[0].get("prob"), 0.0)
    second_prob = _safe_float(outcomes[1].get("prob"), 0.0) if len(outcomes) > 1 else top_prob
    gap = max(0.0, top_prob - second_prob)

    ml_prob_draw = _safe_float(ml.get("prob_draw"), -1.0)
    ml_top_team = ""
    if ml.get("available"):
        if ml_prob_draw >= 0.0:
            ml_candidates = {
                "A": _safe_float(ml.get("prob_a"), 0.0),
                "draw": ml_prob_draw,
                "B": _safe_float(ml.get("prob_b"), 0.0),
            }
            ml_top_team = max(ml_candidates, key=ml_candidates.get)
        else:
            ml_top_team = "A" if _safe_float(ml.get("prob_a"), 0.5) >= 0.5 else "B"

    rule_top_team = "draw" if rule_prob_draw >= max(rule_prob_a_for_compare * (1.0 - rule_prob_draw), 1.0 - rule_prob_a_for_compare) and rule_prob_draw > 0.0 else "A" if rule_prob_a_for_compare >= 0.5 else "B"

    agreement_bonus = 0.0
    if ml_top_team and ml_top_team == selected_team:
        agreement_bonus += 0.05
    if rule_top_team == selected_team:
        agreement_bonus += 0.03
    strong_disagreement = bool(ml_top_team) and ml_top_team != rule_top_team and ml_top_team != selected_team and rule_top_team != selected_team
    if strong_disagreement:
        agreement_bonus -= 0.04

    edge_strength = abs(_safe_float(edge_summary.get("side_edge"), 0.0))
    edge_bonus = min(0.08, edge_strength * 0.08) if selected_team != "draw" else min(0.03, max(0.0, 0.35 - edge_strength) * 0.10)
    cluster_penalty = max(0.0, 0.08 - gap) * 0.90

    data_penalty = 0.0
    if not has_forms:
        data_penalty += 0.06
    if not has_stats:
        data_penalty += 0.05
    if _is_weak_data_quality(data_quality):
        data_penalty += 0.05
    if selected_team == "draw" and gap < 0.05:
        data_penalty += 0.03

    confidence = _clamp(top_prob * 0.72 + gap * 1.10 + agreement_bonus + edge_bonus - cluster_penalty - data_penalty, 0.05, 0.95)
    return confidence, top_prob * 100.0, gap * 100.0, strong_disagreement


def _prediction_text(team_key: str, team_a_name: str, team_b_name: str) -> str:
    if team_key == "A":
        return f"{team_a_name} Win"
    if team_key == "B":
        return f"{team_b_name} Win"
    return "Draw"


def _ml_signal(context: dict[str, Any]) -> dict[str, Any]:
    ml_outputs = context.get("ml_outputs") or {}
    report = context.get("ml_report") or _load_ml_report() or {}

    for key in ("prob_a", "home_win_prob", "winner_prob"):
        if key in ml_outputs:
            prob = _clamp(_safe_float(ml_outputs.get(key), 0.5), 0.01, 0.99)
            return {
                "available": True,
                "prob_a": prob,
                "prob_draw": None,
                "prob_b": 1.0 - prob,
                "confidence": max(prob, 1.0 - prob),
                "source": "provided_ml_output",
                "top_features": ml_outputs.get("top_features") or [],
            }

    inference = ml_service.predict_match(_ml_features(context))
    if inference.get("available"):
        probs = inference.get("probabilities") or [0.3333, 0.3333, 0.3334]
        return {
            "available": True,
            "prob_a": _clamp(_safe_float(probs[0], 0.3333), 0.01, 0.99),
            "prob_draw": _clamp(_safe_float(probs[1], 0.3333), 0.0, 0.98),
            "prob_b": _clamp(_safe_float(probs[2], 0.3334), 0.01, 0.99),
            "confidence": _clamp(_safe_float(inference.get("confidence"), 0.0), 0.0, 1.0),
            "prediction": inference.get("prediction"),
            "source": "random_forest_model",
            "top_features": ml_outputs.get("top_features") or [],
        }

    ranking = report.get("ranking") or []
    best = ranking[0] if ranking else {}
    top_features = best.get("top_features") or []
    if not top_features:
        return {
            "available": False,
            "prob_a": 0.5,
            "source": "missing_ml_data",
            "top_features": [],
        }

    form_a = context.get("form_a") or []
    form_b = context.get("form_b") or []
    sport = str(context.get("sport") or "soccer").lower()

    form_delta = _results_to_points(form_a, sport) - _results_to_points(form_b, sport)
    feature_weight = min(1.0, sum(_safe_float(item.get("importance", item.get("weight", 0.0))) for item in top_features[:3]))
    prob = _clamp(0.5 + form_delta * 0.2 * max(0.3, feature_weight), 0.05, 0.95)

    return {
        "available": True,
        "prob_a": prob,
        "prob_draw": None,
        "prob_b": 1.0 - prob,
        "confidence": max(prob, 1.0 - prob),
        "source": "model_comparison_report",
        "top_features": top_features[:5],
    }


def _build_rule_prediction(context: dict[str, Any]) -> dict[str, Any]:
    return se.scorpred_predict(
        form_a=context.get("form_a") or [],
        form_b=context.get("form_b") or [],
        h2h_form_a=context.get("h2h_form_a") or [],
        h2h_form_b=context.get("h2h_form_b") or [],
        injuries_a=context.get("injuries_a") or [],
        injuries_b=context.get("injuries_b") or [],
        team_a_is_home=bool(context.get("team_a_is_home", True)),
        team_a_name=context.get("team_a_name") or "Team A",
        team_b_name=context.get("team_b_name") or "Team B",
        sport=str(context.get("sport") or "soccer"),
        opp_strengths=context.get("opp_strengths") or {},
    )


def _ui_prediction(
    context: dict[str, Any],
    rule_prediction: dict[str, Any],
    prob_a: float,
    prob_b: float,
    prob_draw: float,
    confidence_float: float,
    selected_team: str | None = None,
) -> dict[str, Any]:
    sport = str(context.get("sport") or "soccer").lower()
    team_a_name = context.get("team_a_name") or "Team A"
    team_b_name = context.get("team_b_name") or "Team B"
    confidence_label = _confidence_label(confidence_float)

    ui = dict(rule_prediction or {})

    if sport == "soccer":
        win_probs = {
            "a": round(prob_a * 100.0, 1),
            "draw": round(prob_draw * 100.0, 1),
            "b": round(prob_b * 100.0, 1),
        }
    else:
        win_probs = {
            "a": round(prob_a * 100.0, 1),
            "b": round(prob_b * 100.0, 1),
        }

    ui["win_probabilities"] = win_probs
    ui["prob_a"] = win_probs.get("a", 0.0)
    ui["prob_b"] = win_probs.get("b", 0.0)
    ui["prob_draw"] = win_probs.get("draw", 0.0)
    ui["home_pct"] = win_probs.get("a", 0.0)
    ui["away_pct"] = win_probs.get("b", 0.0)
    ui["draw_pct"] = win_probs.get("draw", 0.0)
    ui["confidence"] = confidence_label

    winner_team = selected_team or ("draw" if sport == "soccer" and win_probs.get("draw", 0.0) >= max(win_probs.get("a", 0.0), win_probs.get("b", 0.0)) else "A" if win_probs.get("a", 0.0) >= win_probs.get("b", 0.0) else "B")
    winner_text = _prediction_text(winner_team, team_a_name, team_b_name)

    ui["winner_label"] = winner_text
    ui["best_pick"] = {
        "prediction": winner_text,
        "team": winner_team,
        "confidence": confidence_label,
        "reasoning": f"ScorMastermind blended ML, rule model, and heuristic context for this edge.",
    }
    return ui


def predict_match(context: dict[str, Any]) -> dict[str, Any]:
    """Return a unified prediction for soccer or NBA.

    Required context keys (flexible):
    - form_a, form_b, h2h_form_a, h2h_form_b
    - injuries_a, injuries_b
    - team_a_name, team_b_name
    - sport, team_a_is_home
    Optional:
    - ml_outputs, ml_report, team_stats, rule_prediction
    """
    sport = str(context.get("sport") or "soccer").lower()
    team_a_name = context.get("team_a_name") or "Team A"
    team_b_name = context.get("team_b_name") or "Team B"

    rule_prediction = context.get("rule_prediction") or _build_rule_prediction(context)
    rule_probs = rule_prediction.get("win_probabilities") or {}

    rule_prob_a_total = _clamp(_safe_float(rule_probs.get("a"), 50.0) / 100.0, 0.01, 0.99)
    rule_prob_b_total = _clamp(_safe_float(rule_probs.get("b"), 50.0) / 100.0, 0.01, 0.99)
    rule_prob_draw = _clamp(_safe_float(rule_probs.get("draw"), 0.0) / 100.0, 0.0, 0.6) if sport == "soccer" else 0.0

    ml = _ml_signal(context)
    features = _ml_features(context) if sport == "soccer" else {}
    edge_summary = _feature_edge_summary(features) if sport == "soccer" else {"side_edge": 0.0}
    data_quality = str(rule_prediction.get("data_quality") or "Moderate")
    weak_data_quality = _is_weak_data_quality(data_quality)

    if sport == "soccer":
        rule_non_draw = max(0.01, rule_prob_a_total + rule_prob_b_total)
        rule_prob_a_for_compare = _clamp(rule_prob_a_total / rule_non_draw, 0.01, 0.99)
        prob_a, prob_draw, prob_b = _blend_soccer_probabilities(
            rule_prob_a_total,
            rule_prob_draw,
            rule_prob_b_total,
            ml,
            edge_summary,
            data_quality,
        )
        selected_team = _select_soccer_outcome(prob_a, prob_draw, prob_b, edge_summary)
    else:
        rule_prob_a = _clamp(rule_prob_a_total, 0.01, 0.99)
        rule_prob_a_for_compare = rule_prob_a
        if ml.get("available"):
            ml_prob_a = _clamp(_safe_float(ml.get("prob_a"), 0.5), 0.01, 0.99)
            prob_a = _clamp(0.6 * rule_prob_a + 0.4 * ml_prob_a, 0.01, 0.99)
        else:
            prob_a = rule_prob_a
        prob_b = 1.0 - prob_a
        prob_draw = 0.0
        selected_team = "A" if prob_a >= prob_b else "B"

    has_forms = bool(context.get("form_a") and context.get("form_b"))
    stats = context.get("team_stats") or {}
    has_stats = bool((stats.get("a") or stats.get("team_a")) and (stats.get("b") or stats.get("team_b")))

    confidence, top_prob_pct, top_two_gap_pct, strong_disagreement_from_confidence = _confidence_score(
        prob_a,
        prob_draw,
        prob_b,
        selected_team=selected_team,
        ml=ml,
        rule_prob_a_for_compare=rule_prob_a_for_compare,
        rule_prob_draw=rule_prob_draw,
        has_forms=has_forms,
        has_stats=has_stats,
        data_quality=data_quality,
        edge_summary=edge_summary,
    )
    ml_confidence_pct = _safe_float(ml.get("confidence"), 0.0) * 100.0 if ml.get("available") else 0.0
    confidence_pct = confidence * 100.0
    winner = _prediction_text(selected_team, team_a_name, team_b_name)
    winner_prob = prob_draw if selected_team == "draw" else prob_a if selected_team == "A" else prob_b

    explanation = {
        "ml_signal": {
            "available": bool(ml.get("available")),
            "source": ml.get("source", "missing_ml_data"),
            "prob_a": round(_safe_float(ml.get("prob_a"), 0.5), 4),
            "prob_draw": round(_safe_float(ml.get("prob_draw"), 0.0), 4) if ml.get("prob_draw") is not None else None,
        },
        "rule_signal": {
            "winner": (rule_prediction.get("best_pick") or {}).get("prediction", ""),
            "probabilities": rule_probs,
            "confidence": (rule_prediction.get("best_pick") or {}).get("confidence", ""),
        },
        "edge_summary": edge_summary,
        "top_features": ml.get("top_features") or [],
    }

    ui_prediction = _ui_prediction(
        context,
        rule_prediction,
        prob_a=prob_a,
        prob_b=prob_b,
        prob_draw=prob_draw,
        confidence_float=confidence,
        selected_team=selected_team,
    )

    outcomes: list[dict[str, Any]] = [
        {"team": "A", "prediction": f"{team_a_name} Win", "prob": prob_a},
        {"team": "B", "prediction": f"{team_b_name} Win", "prob": prob_b},
    ]
    if sport == "soccer":
        outcomes.append({"team": "draw", "prediction": "Draw", "prob": prob_draw})
    outcomes.sort(key=lambda item: _safe_float(item.get("prob"), 0.0), reverse=True)

    top_outcome = next((item for item in outcomes if item.get("team") == selected_team), outcomes[0])
    second_outcome = outcomes[1] if len(outcomes) > 1 else outcomes[0]
    if second_outcome.get("team") == selected_team and len(outcomes) > 2:
        second_outcome = outcomes[2]

    ml_prob_a = _safe_float(ml.get("prob_a"), 0.5)
    ml_prob_draw = _safe_float(ml.get("prob_draw"), -1.0)
    if ml_prob_draw >= max(_safe_float(ml.get("prob_a"), 0.0), _safe_float(ml.get("prob_b"), 0.0), 0.0):
        ml_side = "draw"
    else:
        ml_side = "A" if ml_prob_a >= 0.56 else "B" if ml_prob_a <= 0.44 else ""
    rule_side = _select_soccer_outcome(rule_prob_a_total, rule_prob_draw, rule_prob_b_total, edge_summary) if sport == "soccer" else ("A" if rule_prob_a_for_compare >= 0.56 else "B" if rule_prob_a_for_compare <= 0.44 else "")
    strong_signal_disagreement = bool(ml.get("available")) and bool(ml_side) and bool(rule_side) and ml_side != rule_side and strong_disagreement_from_confidence

    avoid_reasons: list[str] = []
    if confidence_pct < 58.0:
        avoid_reasons.append("No strong edge found")
    if top_two_gap_pct < 3.0:
        avoid_reasons.append("Outcome probabilities are too close")
    if weak_data_quality:
        avoid_reasons.append("High uncertainty matchup")
    if strong_signal_disagreement:
        avoid_reasons.append("ML and rule signals disagree strongly")
    if sport == "soccer" and selected_team == "draw" and top_prob_pct < 37.0:
        avoid_reasons.append("Draw signal is not strong enough")

    avoid_triggered = bool(avoid_reasons)

    if confidence_pct < 58.0:
        play_type = "AVOID"
    elif confidence_pct < 72.0:
        play_type = "LEAN"
    else:
        play_type = "BET"
    top_lean = {
        "team": top_outcome.get("team"),
        "prediction": top_outcome.get("prediction"),
        "probability": round(top_prob_pct, 1),
        "display": f"Top lean: {top_outcome.get('prediction')} ({top_prob_pct:.1f}%)",
    }

    best_pick = ui_prediction.get("best_pick") or {}
    if avoid_triggered:
        reason = avoid_reasons[0]
        best_pick["prediction"] = "Avoid"
        best_pick["team"] = "avoid"
        best_pick["tracking_team"] = selected_team
        best_pick["confidence"] = "Low"
        best_pick["reasoning"] = reason
        ui_prediction["confidence"] = "Low"
        ui_prediction["recommended_play"] = "Avoid"
        ui_prediction["avoid_reasons"] = avoid_reasons
        ui_prediction["top_lean"] = top_lean
        ui_prediction["risk_label"] = "Elevated"
        ui_prediction["play_type"] = "AVOID"
    else:
        best_pick["tracking_team"] = best_pick.get("team") or selected_team
        ui_prediction["recommended_play"] = best_pick.get("prediction") or top_outcome.get("prediction")
        ui_prediction["avoid_reasons"] = []
        ui_prediction["top_lean"] = top_lean
        ui_prediction["play_type"] = play_type

    ui_prediction["confidence_pct"] = round(confidence_pct, 1)
    ui_prediction["ml_confidence_pct"] = round(ml_confidence_pct, 1)

    ui_prediction["best_pick"] = best_pick

    return {
        "winner": winner,
        "probability": round(winner_prob, 4),
        "confidence": round(confidence, 4),
        "explanation": explanation,
        "ui_prediction": ui_prediction,
        "rule_prediction": rule_prediction,
    }
