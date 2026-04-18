"""Build structured ScorPred verdicts from the app's existing prediction signals."""

from __future__ import annotations

import re
from typing import Any

_CONFIDENCE_SCORES = {"Low": 2.0, "Medium": 5.0, "High": 8.0}
_EDGE_LABELS = ((7.5, "Strong"), (4.8, "Decent"), (0.0, "Weak"))
_PARLAY_LABELS = ((7.8, "Strong"), (6.0, "Playable"), (4.0, "Thin"), (0.0, "Not Recommended"))


def build_verdict(
    sport: str,
    prediction: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    sport_key = str(sport or "").strip().lower()
    if sport_key in {"soccer", "football"}:
        return build_soccer_verdict(prediction, **kwargs)
    if sport_key == "nba":
        return build_nba_verdict(prediction, **kwargs)
    raise ValueError(f"Unsupported sport for verdict engine: {sport!r}")


def build_soccer_verdict(
    prediction: dict[str, Any],
    *,
    team_a_name: str,
    team_b_name: str,
    form_a: list[dict[str, Any]] | None = None,
    form_b: list[dict[str, Any]] | None = None,
    h2h_form_a: list[dict[str, Any]] | None = None,
    h2h_form_b: list[dict[str, Any]] | None = None,
    injuries_a: list[dict[str, Any]] | None = None,
    injuries_b: list[dict[str, Any]] | None = None,
    league_name: str | None = None,
) -> dict[str, Any]:
    form_a = form_a or []
    form_b = form_b or []
    h2h_form_a = h2h_form_a or []
    h2h_form_b = h2h_form_b or []
    injuries_a = injuries_a or []
    injuries_b = injuries_b or []

    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    prediction_confidence = _normalize_confidence(best_pick.get("confidence") or prediction.get("confidence"))
    probabilities = prediction.get("win_probabilities") if isinstance(prediction.get("win_probabilities"), dict) else {}
    ordered_probs = _sorted_probabilities(probabilities, team_a_name, team_b_name, include_draw=True)
    best_prob = ordered_probs[0]
    second_prob = ordered_probs[1] if len(ordered_probs) > 1 else ("", "", 0.0)
    probability_gap = max(0.0, best_prob[2] - second_prob[2])
    score_gap = _safe_float(prediction.get("score_gap"))
    data_quality = _normalize_data_quality(prediction.get("data_quality"))
    key_edges = prediction.get("key_edges") if isinstance(prediction.get("key_edges"), list) else []
    top_edge_margin = _safe_float((key_edges[0] or {}).get("margin")) if key_edges else 0.0

    form_summary_a = _form_summary(form_a, sport="soccer")
    form_summary_b = _form_summary(form_b, sport="soccer")
    h2h_summary_a = _form_summary(h2h_form_a, sport="soccer")
    h2h_summary_b = _form_summary(h2h_form_b, sport="soccer")
    injuries_summary_a = _injury_summary(injuries_a, sport="soccer")
    injuries_summary_b = _injury_summary(injuries_b, sport="soccer")
    predicted_side = _soccer_pick_side(best_pick.get("prediction"), team_a_name, team_b_name)
    predicted_team = _predicted_team_name(predicted_side, team_a_name, team_b_name)

    form_edge = _form_edge(form_summary_a, form_summary_b)
    h2h_edge = _form_edge(h2h_summary_a, h2h_summary_b)
    predicted_form_edge = _side_edge_value(predicted_side, form_edge)
    predicted_h2h_edge = _side_edge_value(predicted_side, h2h_edge)
    injury_edge = injuries_summary_b["weighted_load"] - injuries_summary_a["weighted_load"]
    predicted_injury_edge = _side_edge_value(predicted_side, injury_edge)

    totals_pick, totals_line = _extract_totals_pick_from_prediction(prediction)
    totals_signal = _soccer_totals_signal(form_a, form_b, totals_line)

    winner_score = _confidence_score(prediction_confidence)
    winner_score += _band_score(best_prob[2], ((62.0, 2.0), (55.0, 1.2), (48.0, 0.4)))
    winner_score += _band_score(probability_gap, ((16.0, 2.5), (10.0, 1.6), (6.0, 0.8)))
    winner_score += _band_score(score_gap, ((1.9, 2.0), (1.1, 1.2), (0.7, 0.4)))
    winner_score += _band_score(top_edge_margin, ((1.1, 1.0), (0.7, 0.5)))
    winner_score += _band_score(predicted_form_edge, ((1.0, 1.0), (0.35, 0.5)))
    winner_score += _band_score(predicted_injury_edge, ((0.9, 0.8), (0.3, 0.3)))
    winner_score += {"Strong": 0.9, "Moderate": 0.2, "Limited": -1.0}.get(data_quality, 0.0)
    if predicted_side == "draw":
        winner_score -= 1.6
    winner_score = _cap_score(winner_score)

    totals_score = _cap_score(totals_signal["score"] + {"Strong": 0.7, "Moderate": 0.1, "Limited": -0.5}.get(data_quality, 0.0))

    supporting_reasons = _soccer_supporting_reasons(
        prediction=prediction,
        team_a_name=team_a_name,
        team_b_name=team_b_name,
        predicted_side=predicted_side,
        predicted_team=predicted_team,
        form_summary_a=form_summary_a,
        form_summary_b=form_summary_b,
        h2h_summary_a=h2h_summary_a,
        h2h_summary_b=h2h_summary_b,
        predicted_form_edge=predicted_form_edge,
        predicted_h2h_edge=predicted_h2h_edge,
        predicted_injury_edge=predicted_injury_edge,
        totals_signal=totals_signal,
        league_name=league_name,
    )
    warning_flags = _soccer_warning_flags(
        predicted_side=predicted_side,
        predicted_team=predicted_team,
        prediction_confidence=prediction_confidence,
        probability_gap=probability_gap,
        score_gap=score_gap,
        data_quality=data_quality,
        predicted_injury_edge=predicted_injury_edge,
        predicted_form_edge=predicted_form_edge,
        predicted_h2h_edge=predicted_h2h_edge,
        totals_signal=totals_signal,
    )

    winner_playable = predicted_side in {"a", "b"} and winner_score >= 5.8
    totals_playable = totals_pick is not None and totals_score >= 5.3
    parlay_score = _soccer_parlay_score(winner_score, totals_score, warning_flags, data_quality)
    parlay_rating = _parlay_label(parlay_score)
    parlay_advice = _soccer_parlay_advice(
        winner_playable=winner_playable,
        totals_playable=totals_playable,
        parlay_rating=parlay_rating,
        totals_signal=totals_signal,
    )

    if winner_playable and totals_playable and winner_score >= 7.0 and totals_score >= 6.6 and len(warning_flags) <= 1:
        primary_play = f"{predicted_team} to win + {totals_pick}"
        play_type = "parlay"
        primary_score = min(winner_score, totals_score) - 0.4
    elif winner_playable:
        primary_play = f"{predicted_team} to win"
        play_type = "winner"
        primary_score = winner_score
    elif totals_playable:
        primary_play = totals_pick or "Avoid"
        play_type = "totals"
        primary_score = totals_score
    else:
        primary_play = "Avoid"
        play_type = "avoid"
        primary_score = min(winner_score, totals_score)

    confidence = "Low" if play_type == "avoid" else _score_to_confidence(primary_score)
    edge_strength = "Weak" if play_type == "avoid" else _edge_label(primary_score)
    risk_level = _risk_level(
        primary_score=primary_score,
        play_type=play_type,
        warning_count=len(warning_flags),
        data_quality=data_quality,
    )

    summary = _soccer_summary(
        play_type=play_type,
        primary_play=primary_play,
        predicted_team=predicted_team,
        supporting_reasons=supporting_reasons,
        warning_flags=warning_flags,
        totals_signal=totals_signal,
    )

    return {
        "sport": "soccer",
        "primary_play": primary_play,
        "play_type": play_type,
        "confidence": confidence,
        "risk_level": risk_level,
        "edge_strength": edge_strength,
        "parlay_rating": parlay_rating,
        "parlay_advice": parlay_advice,
        "summary": summary,
        "supporting_reasons": supporting_reasons[:4],
        "warning_flags": warning_flags[:4],
        "data_quality": data_quality,
        "secondary_play": totals_pick if play_type == "winner" else (f"{predicted_team} to win" if winner_playable and predicted_side in {"a", "b"} else None),
        "market_context": {
            "winner": {
                "pick": None if predicted_side == "draw" else f"{predicted_team} to win",
                "probability": round(best_prob[2], 1),
                "score": round(winner_score, 1),
            },
            "totals": {
                "pick": totals_pick,
                "line": totals_line,
                "score": round(totals_score, 1),
            },
        },
    }


def build_nba_verdict(
    prediction: dict[str, Any],
    *,
    team_a_name: str,
    team_b_name: str,
    market_analysis: dict[str, Any] | None = None,
    form_a: list[dict[str, Any]] | None = None,
    form_b: list[dict[str, Any]] | None = None,
    h2h_form_a: list[dict[str, Any]] | None = None,
    h2h_form_b: list[dict[str, Any]] | None = None,
    injuries_a: list[dict[str, Any]] | None = None,
    injuries_b: list[dict[str, Any]] | None = None,
    stats_a: dict[str, Any] | None = None,
    stats_b: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_analysis = market_analysis or {}
    form_a = form_a or []
    form_b = form_b or []
    h2h_form_a = h2h_form_a or []
    h2h_form_b = h2h_form_b or []
    injuries_a = injuries_a or []
    injuries_b = injuries_b or []
    stats_a = stats_a or {}
    stats_b = stats_b or {}

    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    probabilities = prediction.get("win_probabilities") if isinstance(prediction.get("win_probabilities"), dict) else {}
    winner_pick = _nba_winner_pick(best_pick.get("prediction"), team_a_name, team_b_name)
    winner_prob = _winner_pick_probability(probabilities, winner_pick, team_a_name, team_b_name)
    probability_gap = abs(_safe_float(probabilities.get("a")) - _safe_float(probabilities.get("b")))
    score_gap = _safe_float(prediction.get("score_gap"))
    prediction_confidence = _normalize_confidence(best_pick.get("confidence") or prediction.get("confidence"))
    data_quality = _normalize_data_quality(prediction.get("data_quality"))

    winner_leg = market_analysis.get("winner_leg") if isinstance(market_analysis.get("winner_leg"), dict) else {}
    spread_leg = market_analysis.get("spread_leg") if isinstance(market_analysis.get("spread_leg"), dict) else {}
    totals_leg = market_analysis.get("totals_leg") if isinstance(market_analysis.get("totals_leg"), dict) else {}
    alignment = market_analysis.get("alignment") if isinstance(market_analysis.get("alignment"), dict) else {}

    form_summary_a = _form_summary(form_a, sport="nba")
    form_summary_b = _form_summary(form_b, sport="nba")
    h2h_summary_a = _form_summary(h2h_form_a, sport="nba")
    h2h_summary_b = _form_summary(h2h_form_b, sport="nba")
    form_edge = _form_edge(form_summary_a, form_summary_b)
    h2h_edge = _form_edge(h2h_summary_a, h2h_summary_b)
    injuries_summary_a = _injury_summary(injuries_a, sport="nba")
    injuries_summary_b = _injury_summary(injuries_b, sport="nba")
    injury_edge = injuries_summary_b["weighted_load"] - injuries_summary_a["weighted_load"]
    predicted_side = _team_side_from_name(winner_pick, team_a_name, team_b_name)
    predicted_injury_edge = _side_edge_value(predicted_side, injury_edge)
    predicted_form_edge = _side_edge_value(predicted_side, form_edge)
    predicted_h2h_edge = _side_edge_value(predicted_side, h2h_edge)

    expected_margin = abs(_safe_float(market_analysis.get("expected_margin")))
    expected_total = _safe_float(market_analysis.get("expected_total"))
    model_total_line = _safe_float(market_analysis.get("model_total_line"))
    totals_edge = abs(expected_total - model_total_line)
    net_edge = _safe_float(stats_a.get("net_rtg")) - _safe_float(stats_b.get("net_rtg"))
    predicted_net_edge = _side_edge_value(predicted_side, net_edge)

    winner_score = _confidence_score(_normalize_confidence(winner_leg.get("confidence") or prediction_confidence))
    winner_score += _band_score(winner_prob, ((68.0, 2.2), (60.0, 1.4), (55.0, 0.7)))
    winner_score += _band_score(probability_gap, ((14.0, 2.0), (8.0, 1.2), (4.0, 0.5)))
    winner_score += _band_score(score_gap, ((1.7, 1.4), (0.9, 0.8), (0.5, 0.2)))
    winner_score += _band_score(predicted_form_edge, ((6.0, 1.0), (2.5, 0.4)))
    winner_score += _band_score(predicted_net_edge, ((6.0, 1.0), (2.5, 0.4)))
    winner_score += _band_score(predicted_injury_edge, ((0.9, 0.9), (0.25, 0.4)))
    winner_score += {"Strong": 0.8, "Moderate": 0.2, "Limited": -0.8}.get(data_quality, 0.0)
    winner_score = _cap_score(winner_score)

    spread_score = _confidence_score(_normalize_confidence(spread_leg.get("confidence")))
    spread_score += _band_score(expected_margin, ((9.0, 2.0), (6.0, 1.0), (3.5, 0.4)))
    spread_score += _band_score(predicted_net_edge, ((6.0, 1.0), (2.5, 0.4)))
    spread_score = _cap_score(spread_score)

    totals_score = _confidence_score(_normalize_confidence(totals_leg.get("confidence")))
    totals_score += _band_score(totals_edge, ((10.0, 2.4), (6.0, 1.4), (3.0, 0.6)))
    totals_score += _band_score(abs(form_summary_a["avg_scored"] + form_summary_b["avg_scored"] - model_total_line), ((8.0, 0.8), (4.0, 0.3)))
    totals_score = _cap_score(totals_score)

    supporting_reasons = _nba_supporting_reasons(
        winner_pick=winner_pick,
        market_analysis=market_analysis,
        form_summary_a=form_summary_a,
        form_summary_b=form_summary_b,
        h2h_summary_a=h2h_summary_a,
        h2h_summary_b=h2h_summary_b,
        predicted_form_edge=predicted_form_edge,
        predicted_h2h_edge=predicted_h2h_edge,
        predicted_net_edge=predicted_net_edge,
        predicted_injury_edge=predicted_injury_edge,
    )
    warning_flags = _nba_warning_flags(
        winner_score=winner_score,
        spread_score=spread_score,
        totals_score=totals_score,
        probability_gap=probability_gap,
        expected_margin=expected_margin,
        totals_edge=totals_edge,
        data_quality=data_quality,
        predicted_injury_edge=predicted_injury_edge,
        alignment=alignment,
    )

    winner_playable = winner_score >= 5.8
    spread_playable = spread_score >= 5.8
    totals_playable = totals_score >= 5.8
    parlay_score = _nba_parlay_score(
        winner_score=winner_score,
        spread_score=spread_score,
        totals_score=totals_score,
        alignment=alignment,
        warning_flags=warning_flags,
    )
    parlay_rating = _parlay_label(parlay_score)
    parlay_advice = _nba_parlay_advice(
        winner_playable=winner_playable,
        spread_playable=spread_playable,
        totals_playable=totals_playable,
        winner_score=winner_score,
        totals_score=totals_score,
        parlay_rating=parlay_rating,
    )

    if winner_playable and totals_playable and winner_score >= 7.0 and totals_score >= 6.8 and alignment.get("overall") != "Low alignment":
        primary_play = f"{winner_pick} + {str(totals_leg.get('recommendation') or '').strip()}".strip(" +")
        play_type = "parlay"
        primary_score = min(winner_score, totals_score) - 0.3
    elif totals_score > winner_score + 0.7 and totals_playable:
        primary_play = str(totals_leg.get("recommendation") or "Avoid")
        play_type = "totals"
        primary_score = totals_score
    elif spread_score > winner_score + 1.0 and spread_playable:
        primary_play = str(spread_leg.get("recommendation") or "Avoid")
        play_type = "spread"
        primary_score = spread_score
    elif winner_playable:
        primary_play = winner_pick
        play_type = "winner"
        primary_score = winner_score
    else:
        primary_play = "Avoid"
        play_type = "avoid"
        primary_score = max(winner_score, spread_score, totals_score)

    confidence = "Low" if play_type == "avoid" else _score_to_confidence(primary_score)
    edge_strength = "Weak" if play_type == "avoid" else _edge_label(primary_score)
    risk_level = _risk_level(
        primary_score=primary_score,
        play_type=play_type,
        warning_count=len(warning_flags),
        data_quality=data_quality,
    )

    summary = _nba_summary(
        play_type=play_type,
        primary_play=primary_play,
        supporting_reasons=supporting_reasons,
        warning_flags=warning_flags,
    )

    return {
        "sport": "nba",
        "primary_play": primary_play,
        "play_type": play_type,
        "confidence": confidence,
        "risk_level": risk_level,
        "edge_strength": edge_strength,
        "parlay_rating": parlay_rating,
        "parlay_advice": parlay_advice,
        "summary": summary,
        "supporting_reasons": supporting_reasons[:5],
        "warning_flags": warning_flags[:4],
        "data_quality": data_quality,
        "secondary_play": _nba_secondary_play(play_type, winner_pick, spread_leg, totals_leg),
        "market_context": {
            "winner": {
                "pick": winner_pick,
                "probability": round(winner_prob, 1),
                "score": round(winner_score, 1),
            },
            "spread": {
                "pick": spread_leg.get("recommendation"),
                "score": round(spread_score, 1),
            },
            "totals": {
                "pick": totals_leg.get("recommendation"),
                "score": round(totals_score, 1),
            },
        },
    }


def build_result_review(
    record: dict[str, Any],
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparison = comparison or {}
    winner_value = _clean_text(comparison.get("winner_pick") or record.get("predicted_winner_display") or record.get("predicted_winner") or "")
    winner_probability = _safe_float(comparison.get("predicted_outcome_probability") or record.get("predicted_outcome_probability"))
    confidence = _normalize_confidence(record.get("confidence") or record.get("predicted_confidence"))
    actual_outcome = _clean_text(comparison.get("actual_outcome") or record.get("actual_result_label") or "")
    totals_pick = _clean_text((comparison.get("totals_leg") or {}).get("value") or record.get("totals_pick") or "")
    totals_hit = comparison.get("totals_leg_hit")
    prediction_hit = comparison.get("winner_hit")

    reasons = []
    warnings = []

    if winner_value and winner_probability:
        reasons.append(f"Original best play was {winner_value} with a model probability of {winner_probability:.1f}%.")
    elif winner_value:
        reasons.append(f"Original best play was {winner_value}.")

    if prediction_hit is True:
        reasons.append("The tracked winner side landed, so the pre-match edge translated cleanly.")
    elif prediction_hit is False and confidence == "Low":
        warnings.append("The miss came from a weak pre-match edge rather than a confident model position.")
    elif prediction_hit is False and actual_outcome:
        warnings.append(f"The winner side missed despite a {confidence.lower()} confidence lean, which points to a true upset or late swing.")

    if totals_pick and totals_hit is True:
        reasons.append(f"The totals angle ({totals_pick}) aligned better than the winner side.")
    elif totals_pick and totals_hit is False:
        warnings.append(f"The secondary totals angle ({totals_pick}) also failed, so there was no cleaner alternative market.")

    if not reasons:
        reasons.append("Tracked result context was limited, so only a light post-match review is available.")

    summary = reasons[0]
    if warnings:
        summary += f" {warnings[0]}"

    return {
        "primary_play": winner_value or "Review unavailable",
        "play_type": "winner" if winner_value else "avoid",
        "confidence": confidence,
        "risk_level": "Avoid" if confidence == "Low" and prediction_hit is False else ("Moderate" if prediction_hit else "Risky"),
        "edge_strength": "Weak" if confidence == "Low" else ("Strong" if confidence == "High" else "Decent"),
        "parlay_rating": "Not Recommended",
        "parlay_advice": "Result review only; no new parlay recommendation is implied.",
        "summary": summary,
        "supporting_reasons": reasons[:4],
        "warning_flags": warnings[:4],
        "data_quality": "Moderate" if reasons else "Limited",
    }


def _sorted_probabilities(
    probabilities: dict[str, Any],
    team_a_name: str,
    team_b_name: str,
    *,
    include_draw: bool,
) -> list[tuple[str, str, float]]:
    ordered = [
        ("a", team_a_name, _safe_float(probabilities.get("a"))),
        ("b", team_b_name, _safe_float(probabilities.get("b"))),
    ]
    if include_draw:
        ordered.append(("draw", "Draw", _safe_float(probabilities.get("draw"))))
    ordered.sort(key=lambda item: item[2], reverse=True)
    return ordered


def _form_summary(form: list[dict[str, Any]], *, sport: str) -> dict[str, Any]:
    if not form:
        return {
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "avg_margin": 0.0,
            "avg_scored": 0.0,
            "avg_allowed": 0.0,
            "scored_rate": 0.0,
            "allowed_rate": 0.0,
            "label": "0-0-0",
        }

    wins = draws = losses = 0
    margins: list[float] = []
    scored_values: list[float] = []
    allowed_values: list[float] = []
    scored_non_zero = 0
    allowed_non_zero = 0
    scored_key = "our_pts" if sport == "nba" else "gf"
    allowed_key = "their_pts" if sport == "nba" else "ga"

    for game in form[:5]:
        result = str(game.get("result") or "").upper()
        if result == "W":
            wins += 1
        elif result == "D":
            draws += 1
        elif result == "L":
            losses += 1

        scored = _safe_float(game.get(scored_key) or game.get("goals_for") or game.get("points_for"))
        allowed = _safe_float(game.get(allowed_key) or game.get("goals_against") or game.get("points_against"))
        scored_values.append(scored)
        allowed_values.append(allowed)
        margins.append(scored - allowed)
        if scored > 0:
            scored_non_zero += 1
        if allowed > 0:
            allowed_non_zero += 1

    total_games = max(1, min(len(form), 5))
    return {
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "avg_margin": round(sum(margins) / total_games, 2),
        "avg_scored": round(sum(scored_values) / total_games, 2),
        "avg_allowed": round(sum(allowed_values) / total_games, 2),
        "scored_rate": round(scored_non_zero / total_games, 2),
        "allowed_rate": round(allowed_non_zero / total_games, 2),
        "label": f"{wins}-{draws}-{losses}" if sport == "soccer" else f"{wins}-{losses}",
    }


def _injury_summary(injuries: list[dict[str, Any]], *, sport: str) -> dict[str, float]:
    weighted_load = 0.0
    serious_count = 0
    for injury in injuries:
        status = _clean_text(injury.get("status") or (injury.get("player") or {}).get("status")).lower()
        position = _clean_text(
            injury.get("position")
            or (injury.get("player") or {}).get("position")
            or (injury.get("player") or {}).get("pos")
        ).lower()
        status_weight = 0.35
        if status in {"out", "injured"}:
            status_weight = 1.0
            serious_count += 1
        elif status in {"doubtful"}:
            status_weight = 0.7
            serious_count += 1
        elif status in {"questionable", "day-to-day", "day to day"}:
            status_weight = 0.45

        role_weight = 1.0
        if sport == "nba":
            if position in {"pg", "sg", "g", "sf", "pf", "f"}:
                role_weight = 1.1
            elif position == "c":
                role_weight = 1.2
        else:
            if position in {"goalkeeper"}:
                role_weight = 1.25
            elif position in {"attacker", "forward", "striker", "winger", "midfielder"}:
                role_weight = 1.1
            elif position in {"defender", "fullback", "center back", "wing back"}:
                role_weight = 1.0

        weighted_load += status_weight * role_weight

    return {
        "count": float(len(injuries)),
        "serious_count": float(serious_count),
        "weighted_load": round(weighted_load, 2),
    }


def _extract_totals_pick_from_prediction(prediction: dict[str, Any]) -> tuple[str | None, float | None]:
    picks = prediction.get("optional_picks") if isinstance(prediction.get("optional_picks"), list) else []
    for pick in picks:
        market = _clean_text((pick or {}).get("market"))
        lean = _clean_text((pick or {}).get("lean"))
        if "over/under" not in market.lower() and "o/u" not in market.lower():
            continue
        match = re.search(r"(\d+(?:\.\d+)?)", market)
        line = float(match.group(1)) if match else None
        if lean and line is not None:
            return (f"{lean} {line:g}", line)
        if market:
            return (market, line)
    return (None, None)


def _soccer_totals_signal(
    form_a: list[dict[str, Any]],
    form_b: list[dict[str, Any]],
    line: float | None,
) -> dict[str, Any]:
    form_summary_a = _form_summary(form_a, sport="soccer")
    form_summary_b = _form_summary(form_b, sport="soccer")
    target_line = line if line is not None else 2.5
    expected_total = (
        form_summary_a["avg_scored"]
        + form_summary_a["avg_allowed"]
        + form_summary_b["avg_scored"]
        + form_summary_b["avg_allowed"]
    ) / 2.0
    expected_btts = (
        form_summary_a["scored_rate"]
        + form_summary_a["allowed_rate"]
        + form_summary_b["scored_rate"]
        + form_summary_b["allowed_rate"]
    ) / 4.0
    distance = abs(expected_total - target_line)

    score = _band_score(distance, ((1.1, 7.5), (0.7, 5.8), (0.35, 4.2), (0.0, 2.5)))
    if expected_btts >= 0.7:
        score += 0.7
    elif expected_btts <= 0.35:
        score += 0.5

    lean = "Over" if expected_total >= target_line else "Under"
    return {
        "pick": f"{lean} {target_line:g}",
        "expected_total": round(expected_total, 2),
        "btts_indicator": round(expected_btts, 2),
        "score": _cap_score(score),
    }


def _soccer_supporting_reasons(
    *,
    prediction: dict[str, Any],
    team_a_name: str,
    team_b_name: str,
    predicted_side: str,
    predicted_team: str,
    form_summary_a: dict[str, Any],
    form_summary_b: dict[str, Any],
    h2h_summary_a: dict[str, Any],
    h2h_summary_b: dict[str, Any],
    predicted_form_edge: float,
    predicted_h2h_edge: float,
    predicted_injury_edge: float,
    totals_signal: dict[str, Any],
    league_name: str | None,
) -> list[str]:
    reasons: list[str] = []
    key_edges = prediction.get("key_edges") if isinstance(prediction.get("key_edges"), list) else []
    for edge in key_edges[:2]:
        detail = _clean_text((edge or {}).get("detail"))
        if detail:
            reasons.append(detail)

    if predicted_side in {"a", "b"} and predicted_form_edge > 0.2:
        reasons.append(
            f"Recent form is with {predicted_team}: {team_a_name} are {form_summary_a['label']} and {team_b_name} are {form_summary_b['label']} across the last five."
        )
    if predicted_side in {"a", "b"} and predicted_injury_edge > 0.25:
        reasons.append(f"The squad situation is cleaner for {predicted_team}, which lowers the fragility of the winner lean.")
    if predicted_side in {"a", "b"} and predicted_h2h_edge > 0.3:
        reasons.append(f"Head-to-head results also lean toward {predicted_team}, so the matchup history is not fighting the current read.")
    if league_name and totals_signal["score"] >= 5.5:
        reasons.append(
            f"The scoring profile in {league_name} points toward {totals_signal['pick']} with an estimated total around {totals_signal['expected_total']:.2f}."
        )
    elif totals_signal["score"] >= 5.5:
        reasons.append(
            f"The recent goal profile points toward {totals_signal['pick']} with an estimated total around {totals_signal['expected_total']:.2f}."
        )
    return _dedupe_strings(reasons)


def _soccer_warning_flags(
    *,
    predicted_side: str,
    predicted_team: str,
    prediction_confidence: str,
    probability_gap: float,
    score_gap: float,
    data_quality: str,
    predicted_injury_edge: float,
    predicted_form_edge: float,
    predicted_h2h_edge: float,
    totals_signal: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if predicted_side == "draw":
        warnings.append("The model's top winner outcome is a draw, which is usually a thin betting edge rather than a clean single.")
    if prediction_confidence == "Low":
        warnings.append("The model confidence is low, so this matchup does not clear a strong action threshold.")
    if probability_gap < 6.0:
        warnings.append("Winner probability separation is thin, so the main side is vulnerable to one swing event.")
    if score_gap < 0.8:
        warnings.append("ScorPred team scores are tightly clustered, which signals a fragile edge.")
    if data_quality == "Limited":
        warnings.append("Available pre-match evidence is limited, so the verdict stays conservative.")
    if predicted_side in {"a", "b"} and predicted_injury_edge < -0.2:
        warnings.append(f"{predicted_team} carry the heavier injury pressure, which raises downside risk.")
    if predicted_side in {"a", "b"} and predicted_form_edge > 0.2 and predicted_h2h_edge < -0.2:
        warnings.append("Current form and head-to-head history are pulling in different directions.")
    if totals_signal["score"] < 4.5:
        warnings.append("The totals leg is not strong enough to upgrade this into a trustworthy parlay.")
    return _dedupe_strings(warnings)


def _soccer_parlay_score(winner_score: float, totals_score: float, warning_flags: list[str], data_quality: str) -> float:
    if winner_score < 5.8:
        return 1.5 if totals_score >= 5.8 else 0.0
    score = min(winner_score, totals_score)
    if totals_score < 5.0:
        score -= 2.0
    score -= len(warning_flags) * 0.5
    if data_quality == "Limited":
        score -= 1.0
    return _cap_score(score)


def _soccer_parlay_advice(
    *,
    winner_playable: bool,
    totals_playable: bool,
    parlay_rating: str,
    totals_signal: dict[str, Any],
) -> str:
    if parlay_rating == "Strong":
        return "Playable two-leg parlay with both the winner and totals profile aligned."
    if parlay_rating == "Playable":
        return "Playable two-leg parlay, but it is still weaker than the best single."
    if winner_playable and not totals_playable:
        return "Strong single, weak parlay. The winner edge is fine, but the totals leg is too thin."
    if totals_playable and not winner_playable:
        return f"Avoid the full parlay; only the totals side ({totals_signal['pick']}) looks actionable."
    return "No clean edge -- pass on this matchup rather than forcing a parlay."


def _soccer_summary(
    *,
    play_type: str,
    primary_play: str,
    predicted_team: str,
    supporting_reasons: list[str],
    warning_flags: list[str],
    totals_signal: dict[str, Any],
) -> str:
    if play_type == "winner":
        summary = f"{predicted_team} have the cleaner pre-match edge based on the strongest underlying signals in the model."
        if totals_signal["score"] < 5.5:
            summary += " Totals support is only moderate, so the single is stronger than the parlay."
        return summary
    if play_type == "totals":
        return f"{primary_play} is clearer than the winner market because the goal profile is stronger than the side edge."
    if play_type == "parlay":
        return f"{primary_play} lines up across the main winner read and the goals profile, but it still carries more risk than a straight bet."
    if warning_flags:
        return f"The winner edge is too thin to trust, and {warning_flags[0].rstrip('.').lower()}."
    if supporting_reasons:
        return f"No single market cleared the action threshold even though {supporting_reasons[0].rstrip('.').lower()}."
    return "No clean edge emerged from the available football signals, so the honest call is to pass."


def _nba_supporting_reasons(
    *,
    winner_pick: str,
    market_analysis: dict[str, Any],
    form_summary_a: dict[str, Any],
    form_summary_b: dict[str, Any],
    h2h_summary_a: dict[str, Any],
    h2h_summary_b: dict[str, Any],
    predicted_form_edge: float,
    predicted_h2h_edge: float,
    predicted_net_edge: float,
    predicted_injury_edge: float,
) -> list[str]:
    reasons: list[str] = []
    for point in (market_analysis.get("evidence_points") or [])[:3]:
        text = _clean_text(point)
        if text:
            reasons.append(text)

    if predicted_form_edge > 1.5:
        reasons.append(
            f"Recent form margin supports {winner_pick}: one side is running clearly better over the last five games."
        )
    if predicted_net_edge > 2.5:
        reasons.append(f"The net rating gap also leans the same way, which makes the winner side more stable than a one-game hot streak.")
    if predicted_h2h_edge > 1.5:
        reasons.append("Head-to-head results are not fighting the current model read.")
    if predicted_injury_edge > 0.25:
        reasons.append("Injury pressure is lighter on the preferred side, which lowers the risk of lineup-driven volatility.")
    if form_summary_a["avg_scored"] + form_summary_b["avg_scored"] > 230:
        reasons.append("The recent scoring profile is strong enough to keep the totals market live.")
    return _dedupe_strings(reasons)


def _nba_warning_flags(
    *,
    winner_score: float,
    spread_score: float,
    totals_score: float,
    probability_gap: float,
    expected_margin: float,
    totals_edge: float,
    data_quality: str,
    predicted_injury_edge: float,
    alignment: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if probability_gap < 5.0:
        warnings.append("Winner probability separation is narrow, so the moneyline edge is not especially forgiving.")
    if expected_margin < 3.0:
        warnings.append("The spread signal is fragile because the projected margin is still inside one late possession cluster.")
    if totals_edge < 3.0:
        warnings.append("The totals edge is thin, so it should not be forced into a parlay leg.")
    if winner_score >= 6.0 and spread_score < 5.2:
        warnings.append("The winner lean is stronger than the spread, which limits how far the side should be stretched.")
    if totals_score >= 6.2 and winner_score < 5.8:
        warnings.append("The totals side is cleaner than the winner side, so the matchup should not be treated as a full-game side stack.")
    if predicted_injury_edge < -0.2:
        warnings.append("The preferred side carries the heavier injury burden, which adds lineup risk.")
    if str(alignment.get("overall") or "").lower().startswith("low"):
        warnings.append("Market signals do not align cleanly enough to support an aggressive multi-leg position.")
    if data_quality == "Limited":
        warnings.append("Available NBA context is limited, so the verdict stays conservative.")
    return _dedupe_strings(warnings)


def _nba_parlay_score(
    *,
    winner_score: float,
    spread_score: float,
    totals_score: float,
    alignment: dict[str, Any],
    warning_flags: list[str],
) -> float:
    best_two = sorted([winner_score, spread_score, totals_score], reverse=True)[:2]
    score = min(best_two)
    overall = str(alignment.get("overall") or "").lower()
    if "strong" in overall:
        score += 0.8
    elif "selective" in overall:
        score += 0.1
    else:
        score -= 1.2
    score -= len(warning_flags) * 0.45
    return _cap_score(score)


def _nba_parlay_advice(
    *,
    winner_playable: bool,
    spread_playable: bool,
    totals_playable: bool,
    winner_score: float,
    totals_score: float,
    parlay_rating: str,
) -> str:
    if parlay_rating == "Strong":
        return "Playable multi-leg spot: the strongest markets are pointing in the same direction."
    if parlay_rating == "Playable":
        return "Playable two-leg parlay, but keep it selective instead of stacking every market."
    if winner_playable and totals_playable:
        return "Winner and totals can be paired, but the full market stack is still thinner than it looks."
    if winner_playable and not totals_playable:
        return "Strong winner single, weak parlay. The side is better than the add-on legs."
    if totals_playable and not winner_playable:
        return "Avoid the full parlay; only the totals side has a clean enough edge."
    if spread_playable:
        return "The spread is the only market with some traction, so a parlay is not justified."
    if totals_score > winner_score:
        return "Avoid the full parlay; only the totals market shows any value."
    return "No clean edge -- pass on this matchup instead of forcing a parlay."


def _nba_secondary_play(play_type: str, winner_pick: str, spread_leg: dict[str, Any], totals_leg: dict[str, Any]) -> str | None:
    if play_type == "winner":
        return _clean_text(totals_leg.get("recommendation")) or _clean_text(spread_leg.get("recommendation")) or None
    if play_type == "totals":
        return winner_pick or None
    if play_type == "spread":
        return _clean_text(totals_leg.get("recommendation")) or winner_pick or None
    if play_type == "parlay":
        return winner_pick or None
    return None


def _nba_summary(
    *,
    play_type: str,
    primary_play: str,
    supporting_reasons: list[str],
    warning_flags: list[str],
) -> str:
    if play_type == "totals":
        return f"{primary_play} is the clearest edge here; the side markets are more fragile than the scoring environment read."
    if play_type == "winner":
        summary = f"{primary_play} is the strongest straight play from the current NBA signals."
        if warning_flags:
            summary += f" {warning_flags[0]}"
        return summary
    if play_type == "spread":
        return f"{primary_play} stands out more than the moneyline because the projected margin is doing more work than the raw winner probability."
    if play_type == "parlay":
        return f"{primary_play} works as a selective two-leg parlay, but the extra leg still makes it materially riskier than the best single."
    if warning_flags:
        return f"Signals are too conflicted to recommend action: {warning_flags[0].rstrip('.')}."
    if supporting_reasons:
        return f"Several signals showed up, but none were strong enough to justify action. {supporting_reasons[0]}"
    return "Signals are too conflicted to recommend action on this NBA matchup."


def _risk_level(*, primary_score: float, play_type: str, warning_count: int, data_quality: str) -> str:
    if play_type == "avoid":
        return "Avoid"
    if play_type == "parlay":
        if primary_score >= 7.5 and warning_count <= 1 and data_quality == "Strong":
            return "Moderate"
        return "Risky"
    if primary_score >= 8.0 and warning_count == 0 and data_quality == "Strong":
        return "Safe"
    if primary_score >= 5.8 and warning_count <= 2:
        return "Moderate"
    return "Risky"


def _score_to_confidence(score: float) -> str:
    if score >= 7.4:
        return "High"
    if score >= 4.8:
        return "Medium"
    return "Low"


def _edge_label(score: float) -> str:
    for threshold, label in _EDGE_LABELS:
        if score >= threshold:
            return label
    return "Weak"


def _parlay_label(score: float) -> str:
    for threshold, label in _PARLAY_LABELS:
        if score >= threshold:
            return label
    return "Not Recommended"


def _band_score(value: float, bands: tuple[tuple[float, float], ...]) -> float:
    for threshold, score in bands:
        if value >= threshold:
            return score
    return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence_score(label: str) -> float:
    return _CONFIDENCE_SCORES.get(_normalize_confidence(label), 2.0)


def _normalize_confidence(label: Any) -> str:
    text = _clean_text(label).lower()
    if text == "high":
        return "High"
    if text == "medium":
        return "Medium"
    return "Low"


def _normalize_data_quality(label: Any) -> str:
    text = _clean_text(label).lower()
    if text == "strong":
        return "Strong"
    if text == "limited":
        return "Limited"
    return "Moderate"


def _soccer_pick_side(prediction_text: Any, team_a_name: str, team_b_name: str) -> str:
    text = _clean_text(prediction_text).lower()
    if not text:
        return ""
    if text == "draw":
        return "draw"
    if team_a_name.lower() in text:
        return "a"
    if team_b_name.lower() in text:
        return "b"
    if text.endswith(" win"):
        winner_text = text[:-4].strip()
        if winner_text == team_a_name.lower():
            return "a"
        if winner_text == team_b_name.lower():
            return "b"
    return ""


def _nba_winner_pick(prediction_text: Any, team_a_name: str, team_b_name: str) -> str:
    text = _clean_text(prediction_text)
    lower = text.lower()
    if team_a_name.lower() in lower:
        return team_a_name
    if team_b_name.lower() in lower:
        return team_b_name
    return text or team_a_name


def _winner_pick_probability(probabilities: dict[str, Any], winner_pick: str, team_a_name: str, team_b_name: str) -> float:
    if winner_pick == team_b_name:
        return _safe_float(probabilities.get("b"))
    return _safe_float(probabilities.get("a"))


def _team_side_from_name(name: str, team_a_name: str, team_b_name: str) -> str:
    text = _clean_text(name).lower()
    if text == team_a_name.lower():
        return "a"
    if text == team_b_name.lower():
        return "b"
    return ""


def _predicted_team_name(predicted_side: str, team_a_name: str, team_b_name: str) -> str:
    if predicted_side == "a":
        return team_a_name
    if predicted_side == "b":
        return team_b_name
    return "Draw"


def _form_edge(summary_a: dict[str, Any], summary_b: dict[str, Any]) -> float:
    return _safe_float(summary_a.get("avg_margin")) - _safe_float(summary_b.get("avg_margin"))


def _side_edge_value(side: str, edge: float) -> float:
    if side == "a":
        return edge
    if side == "b":
        return -edge
    return 0.0


def _cap_score(score: float) -> float:
    return round(max(0.0, min(10.0, score)), 2)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _clean_text(value: Any) -> str:
    return str(value or "").strip()