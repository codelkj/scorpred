"""Premium strength-tier UI helpers for ScorPred.

The product surface should recommend a side for every normal matchup, then
explain how strong the play is and how trustworthy the data is. Stored tracker
confidence tiers may still exist internally, but the UI renders strength tiers.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re
from typing import Any


TIER_ORDER = {"Best Bet": 0, "Strong Lean": 1, "Lean": 2, "Risky": 3, "No Pick": 4}
TIER_CLASS = {
    "Best Bet": "best-bet",
    "Strong Lean": "strong-lean",
    "Lean": "lean",
    "Risky": "risky",
    "No Pick": "no-pick",
}
DATA_ORDER = {"strong": 0, "partial": 1, "limited": 2}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_percent(value: Any, default: float = 0.0) -> float:
    number = safe_float(value, default)
    if 0 < number <= 1:
        number *= 100
    return round(clamp(number, 0, 100), 1)


def _probability_map(prediction: dict[str, Any] | None, *, sport: str = "soccer") -> dict[str, float]:
    prediction = prediction if isinstance(prediction, dict) else {}
    probs = prediction.get("win_probabilities")
    if not isinstance(probs, dict):
        probs = {
            "a": prediction.get("prob_a") or prediction.get("team_a_probability"),
            "b": prediction.get("prob_b") or prediction.get("team_b_probability"),
            "draw": prediction.get("prob_draw"),
        }
    a = normalize_percent(probs.get("a") or probs.get("team_a") or prediction.get("prob_a"), 0)
    b = normalize_percent(probs.get("b") or probs.get("team_b") or prediction.get("prob_b"), 0)
    draw = normalize_percent(probs.get("draw") or prediction.get("prob_draw"), 0) if sport == "soccer" else 0
    return {"a": a, "b": b, "draw": draw}


def probability_from_prediction(prediction: dict[str, Any] | None, *, sport: str = "soccer") -> float:
    if not isinstance(prediction, dict):
        return 0.0
    explicit = prediction.get("confidence_pct")
    if explicit not in (None, ""):
        return normalize_percent(explicit)
    probs = _probability_map(prediction, sport=sport)
    values = [probs["a"], probs["b"]]
    if sport == "soccer" and probs["draw"]:
        values.append(probs["draw"])
    return max(values) if values else 0.0


def data_badge(data: dict[str, Any] | None = None, *, has_prediction: bool = True) -> dict[str, str]:
    data = data or {}
    raw = str(data.get("tier") or data.get("state") or data.get("label") or "").strip().lower()

    if not has_prediction:
        state = "limited"
    elif raw in {"full", "strong", "strong data", "current-season data", "full live context"}:
        state = "strong"
    elif raw in {"partial", "mixed", "mixed data quality", "partial data", "partial live context"}:
        state = "partial"
    elif raw in {"limited", "limited data", "limited live context", "unavailable"}:
        state = "limited"
    elif data.get("all_data_available"):
        state = "strong"
    elif data.get("partial_data"):
        state = "partial"
    else:
        state = "partial" if has_prediction else "limited"

    labels = {
        "strong": "Strong Data",
        "partial": "Partial Data",
        "limited": "Limited Data",
    }
    return {"state": state, "label": labels[state]}


def _raw_pick(best_pick: dict[str, Any], prediction: dict[str, Any]) -> str:
    return str(
        best_pick.get("prediction")
        or best_pick.get("pick")
        or best_pick.get("winner_label")
        or prediction.get("winner_label")
        or ""
    ).strip()


def _clean_side_name(value: str) -> str:
    side = str(value or "").strip()
    lowered = side.lower()
    for suffix in (" to win", " win", " moneyline", " ml"):
        if lowered.endswith(suffix):
            side = side[: -len(suffix)].strip()
            lowered = side.lower()
            break
    return side


def _side_from_probabilities(probs: dict[str, float], *, team_a: str, team_b: str) -> tuple[str, str, bool]:
    if probs["a"] == 0 and probs["b"] == 0:
        return "No Pick", "", False
    side_key = "a" if probs["a"] >= probs["b"] else "b"
    draw_risk = bool(probs.get("draw", 0) >= max(probs["a"], probs["b"]))
    return (team_a if side_key == "a" else team_b), side_key, draw_risk


def pick_side(
    prediction: dict[str, Any] | None,
    *,
    team_a: str = "Team A",
    team_b: str = "Team B",
    sport: str = "soccer",
) -> tuple[str, bool, str, bool]:
    """Return side, no-pick flag, side key, and draw-risk flag."""

    if not isinstance(prediction, dict) or not prediction:
        return "No Pick", True, "", False

    probs = _probability_map(prediction, sport=sport)
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    pick = _clean_side_name(_raw_pick(best_pick, prediction))
    tracking = str(best_pick.get("tracking_team") or best_pick.get("team") or prediction.get("predicted_winner") or "").strip()
    pick_l = pick.lower()
    tracking_l = tracking.lower()

    if tracking_l in {"a", "home", team_a.lower()}:
        return team_a, False, "a", False
    if tracking_l in {"b", "away", team_b.lower()}:
        return team_b, False, "b", False

    if tracking_l in {"draw", "avoid", "skip"} or pick_l in {"draw", "avoid", "skip", "no pick"}:
        side, side_key, draw_risk = _side_from_probabilities(probs, team_a=team_a, team_b=team_b)
        return side, side == "No Pick", side_key, True if sport == "soccer" else draw_risk

    if pick:
        if "draw" in pick_l:
            side, side_key, draw_risk = _side_from_probabilities(probs, team_a=team_a, team_b=team_b)
            return side, side == "No Pick", side_key, True if sport == "soccer" else draw_risk
        return pick, False, "a" if pick.lower() == team_a.lower() else ("b" if pick.lower() == team_b.lower() else ""), False

    side, side_key, draw_risk = _side_from_probabilities(probs, team_a=team_a, team_b=team_b)
    return side, side == "No Pick", side_key, draw_risk


def edge_gap(prediction: dict[str, Any] | None, *, sport: str = "soccer") -> float:
    probs = _probability_map(prediction, sport=sport)
    return abs(probs["a"] - probs["b"])


def strength_for_prediction(
    prediction: dict[str, Any] | None,
    *,
    data_state: str,
    no_pick: bool,
    draw_risk: bool,
    sport: str,
) -> str:
    if no_pick or not isinstance(prediction, dict) or not prediction:
        return "No Pick"

    pct = probability_from_prediction(prediction, sport=sport)
    gap = edge_gap(prediction, sport=sport)
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    raw_conf = str(best_pick.get("confidence") or prediction.get("confidence") or "").strip().lower()

    score = pct + (gap * 0.75)
    if raw_conf == "high":
        score += 4
    elif raw_conf == "low":
        score -= 4
    if data_state == "strong":
        score += 4
    elif data_state == "limited":
        score -= 8
    if draw_risk:
        score -= 7

    if data_state == "limited":
        return "Lean" if score >= 55 and gap >= 5 else "Risky"
    if data_state == "partial":
        if score >= 67 and gap >= 8:
            return "Strong Lean"
        if score >= 55:
            return "Lean"
        return "Risky"
    if score >= 72 and gap >= 9:
        return "Best Bet"
    if score >= 64 and gap >= 6:
        return "Strong Lean"
    if score >= 53:
        return "Lean"
    return "Risky"


def display_confidence(raw_pct: float, tier: str) -> int:
    if tier == "Best Bet":
        return int(round(clamp(raw_pct or 64, 63, 88)))
    if tier == "Strong Lean":
        return int(round(clamp(raw_pct or 58, 56, 74)))
    if tier == "Lean":
        return int(round(clamp(raw_pct or 53, 51, 66)))
    if tier == "Risky":
        return int(round(clamp(raw_pct or 48, 42, 58)))
    return 0


def clean_reason(text: str | None) -> str:
    reason = str(text or "").strip()
    if not reason:
        return ""
    replacements = [
        (r"\bmodel[- ]?derived\b", "data-backed"),
        (r"\bmodel\b", "read"),
        (r"\bengine\b", "system"),
        (r"\bprediction\b", "pick"),
        (r"\bavoid\b", "risk control"),
        (r"score gap[:\s]*[0-9.\/]+", ""),
        (r"gap[:\s]*[0-9.\/]+", ""),
        (r"scores close\s*\([^)]*\)", "narrow matchup profile"),
        (r"internal rating[:\s].*", ""),
    ]
    for pattern, replacement in replacements:
        reason = re.sub(pattern, replacement, reason, flags=re.IGNORECASE)
    reason = re.sub(r"\s+", " ", reason).strip(" .")
    return reason[:1].upper() + reason[1:] if reason else ""


def fallback_reason(*, tier: str, data_state: str, draw_risk: bool, sport: str, side: str) -> str:
    if tier == "No Pick":
        return "Data feed unavailable for a responsible recommendation"
    if draw_risk and sport == "soccer":
        return "Narrow side edge with meaningful draw pressure"
    if tier == "Best Bet":
        return "Best blend of side edge, matchup support, and data quality"
    if tier == "Strong Lean":
        return "Better recent profile with a clear matchup advantage"
    if tier == "Lean":
        return "Playable side edge with enough support to track"
    if data_state == "limited":
        return "Higher uncertainty, but the side still grades ahead"
    return "Higher upside, but volatility remains"


def support_note_for(*, tier: str, data_state: str, draw_risk: bool, venue: str, side: str) -> str:
    if tier == "No Pick":
        return "Refresh or choose another matchup once baseline data returns."
    if draw_risk:
        return "Draw risk keeps this below the top tier, but the side remains playable."
    if data_state == "strong" and tier in {"Best Bet", "Strong Lean"}:
        return "Strong data quality supports the recommendation."
    if data_state == "partial":
        return "Partial data still supports the side, with some context to monitor."
    if data_state == "limited":
        return "Limited data lowers the tier, not the ability to analyze the match."
    if venue:
        return f"Venue context at {venue} supports the matchup read."
    return "Use the tier and confidence together before sizing the play."


def initials(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(value or ""))
    if not words:
        return "SP"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def probability_rows(
    *,
    sport: str,
    team_a: str,
    team_b: str,
    prediction: dict[str, Any],
    selected_key: str,
) -> list[dict[str, Any]]:
    probs = _probability_map(prediction, sport=sport)
    rows = [
        {"label": team_a, "value": round(probs["a"], 1), "selected": selected_key == "a", "kind": "home"},
        {"label": team_b, "value": round(probs["b"], 1), "selected": selected_key == "b", "kind": "away"},
    ]
    if sport == "soccer":
        rows.insert(1, {"label": "Draw", "value": round(probs["draw"], 1), "selected": False, "kind": "draw"})
    return rows


def _metric_value(data: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in data:
            value = safe_float(data.get(key), 0)
            return value * 10 if 0 < value <= 10 else value
    return 50


def comparison_metrics(prediction: dict[str, Any], *, team_a: str, team_b: str) -> list[dict[str, Any]]:
    comp_a = prediction.get("components_a") if isinstance(prediction.get("components_a"), dict) else {}
    comp_b = prediction.get("components_b") if isinstance(prediction.get("components_b"), dict) else {}
    if not comp_a and not comp_b:
        return []
    specs = [
        ("Recent form", ("form", "recent_form")),
        ("Attack", ("offense", "attack", "scoring")),
        ("Defense", ("defense", "defensive")),
        ("Venue/context", ("home_away", "venue", "match_context")),
    ]
    rows = []
    for label, keys in specs:
        a_value = round(clamp(_metric_value(comp_a, *keys), 0, 100), 1)
        b_value = round(clamp(_metric_value(comp_b, *keys), 0, 100), 1)
        rows.append(
            {
                "label": label,
                "team_a": team_a,
                "team_b": team_b,
                "a_value": a_value,
                "b_value": b_value,
                "leader": team_a if a_value >= b_value else team_b,
            }
        )
    return rows


def build_decision_card(
    *,
    sport: str,
    team_a: str,
    team_b: str,
    prediction: dict[str, Any] | None,
    competition: str = "",
    match_date: str = "",
    venue: str = "",
    cta_url: str = "",
    cta_label: str = "Analyze Match",
    cta_method: str = "get",
    cta_payload: dict[str, Any] | None = None,
    support_text: str = "",
    team_a_logo: str = "",
    team_b_logo: str = "",
    league_logo: str = "",
    form_strip: list[Any] | None = None,
) -> dict[str, Any]:
    has_prediction = isinstance(prediction, dict) and bool(prediction)
    prediction = prediction if isinstance(prediction, dict) else {}
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    badge = data_badge(prediction.get("data_completeness") or {}, has_prediction=has_prediction)
    side, no_pick, side_key, draw_risk = pick_side(prediction, team_a=team_a, team_b=team_b, sport=sport)
    tier = strength_for_prediction(
        prediction,
        data_state=badge["state"],
        no_pick=no_pick,
        draw_risk=draw_risk,
        sport=sport,
    )
    raw_pct = probability_from_prediction(prediction, sport=sport)
    confidence_pct = display_confidence(raw_pct, tier)
    reason = clean_reason(best_pick.get("reasoning") or prediction.get("matchup_reading") or prediction.get("decision_summary"))
    if not reason:
        reason = fallback_reason(tier=tier, data_state=badge["state"], draw_risk=draw_risk, sport=sport, side=side)
    if not support_text:
        support_text = support_note_for(tier=tier, data_state=badge["state"], draw_risk=draw_risk, venue=venue, side=side)

    strength_class = TIER_CLASS[tier]
    card = {
        "sport": sport,
        "matchup": f"{team_a} vs {team_b}",
        "team_a": team_a,
        "team_b": team_b,
        "team_a_logo": team_a_logo or "",
        "team_b_logo": team_b_logo or "",
        "team_a_initials": initials(team_a),
        "team_b_initials": initials(team_b),
        "league_logo": league_logo or "",
        "competition": competition,
        "match_date": match_date,
        "venue": venue,
        "recommended_side": side,
        "strength_tier": tier,
        "strength_class": strength_class,
        "confidence_pct": confidence_pct,
        "raw_confidence_pct": round(raw_pct, 1),
        "summary_reason": reason,
        "support_note": support_text,
        "data_confidence": badge,
        "probability_rows": probability_rows(
            sport=sport,
            team_a=team_a,
            team_b=team_b,
            prediction=prediction,
            selected_key=side_key,
        ),
        "comparison_metrics": comparison_metrics(prediction, team_a=team_a, team_b=team_b),
        "form_strip": form_strip or [],
        "draw_risk": draw_risk,
        "opportunity_rank": None,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "cta_method": cta_method.lower() if cta_method else "get",
        "cta_payload": cta_payload or {},
        "confidence_tier": internal_confidence_tier(confidence_pct),
    }
    # Backward-compatible aliases for routes/tests while templates migrate.
    card.update(
        {
            "action": tier,
            "action_class": strength_class,
            "pick": side,
            "reason": reason,
            "support_text": support_text,
            "data_badge": badge,
        }
    )
    return card


def internal_confidence_tier(confidence_pct: float) -> str:
    if confidence_pct >= 62:
        return "high"
    if confidence_pct >= 52:
        return "medium"
    return "low"


def _playable_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [card for card in cards or [] if card.get("strength_tier") != "No Pick"]


def sort_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        cards or [],
        key=lambda card: (
            TIER_ORDER.get(str(card.get("strength_tier") or card.get("action") or "No Pick"), 5),
            DATA_ORDER.get(((card.get("data_confidence") or card.get("data_badge") or {}).get("state") or "limited"), 3),
            -safe_float(card.get("confidence_pct"), 0),
            str(card.get("match_date") or ""),
        ),
    )


def assign_opportunity_ranks(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    playable = sort_cards(_playable_cards(cards))
    if playable and not any(card.get("strength_tier") == "Best Bet" for card in playable):
        best = playable[0]
        best["strength_tier"] = "Best Bet"
        best["strength_class"] = TIER_CLASS["Best Bet"]
        best["action"] = "Best Bet"
        best["action_class"] = TIER_CLASS["Best Bet"]
        if best.get("confidence_pct", 0) < 58:
            best["confidence_pct"] = 58
        best["support_note"] = "Best available edge on this slate."
        best["support_text"] = best["support_note"]
    for index, card in enumerate(playable, start=1):
        card["opportunity_rank"] = index
    return cards


def plan_summary(cards: list[dict[str, Any]]) -> dict[str, int]:
    assign_opportunity_ranks(cards or [])
    counts = Counter((card.get("strength_tier") or "No Pick") for card in cards or [])
    return {
        "best_bet": counts.get("Best Bet", 0),
        "strong_lean": counts.get("Strong Lean", 0),
        "lean": counts.get("Lean", 0),
        "risky": counts.get("Risky", 0),
        "no_pick": counts.get("No Pick", 0),
    }


def top_opportunities(cards: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    assign_opportunity_ranks(cards or [])
    return sort_cards(_playable_cards(cards))[:limit]


def format_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "TBD"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:25], fmt).strftime("%b %d, %Y")
        except ValueError:
            continue
    return text[:10] if len(text) >= 10 else text


def result_status(record: dict[str, Any]) -> str:
    raw = str(record.get("overall_game_result") or record.get("result") or "").strip().lower()
    if raw in {"push", "void"} or record.get("is_push"):
        return "push"
    if record.get("is_correct") is True or record.get("winner_hit") is True or record.get("game_win") is True:
        return "correct"
    if record.get("is_correct") is False or record.get("winner_hit") is False or raw in {"loss", "incorrect"}:
        return "incorrect"
    return "push"


def _logo_from_record(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_result_record(record: dict[str, Any]) -> dict[str, Any]:
    sport = str(record.get("sport") or "soccer").lower()
    team_a = record.get("team_a") or record.get("home_team") or "Team A"
    team_b = record.get("team_b") or record.get("away_team") or "Team B"
    prediction = {
        "best_pick": {
            "prediction": record.get("predicted_pick_label") or record.get("predicted_winner_display") or record.get("predicted_winner"),
            "team": record.get("predicted_winner"),
            "reasoning": record.get("reasoning") or record.get("decision_explainer") or record.get("prediction_notes"),
            "confidence": record.get("confidence"),
        },
        "win_probabilities": {
            "a": record.get("prob_a"),
            "b": record.get("prob_b"),
            "draw": record.get("prob_draw"),
        },
        "confidence_pct": record.get("confidence_pct"),
        "data_completeness": record.get("data_completeness") or {},
    }
    card = build_decision_card(
        sport=sport,
        team_a=team_a,
        team_b=team_b,
        prediction=prediction,
        competition=record.get("league_name") or record.get("competition") or sport.upper(),
        match_date=record.get("game_date") or record.get("date") or record.get("created_at"),
        cta_url=f"/prediction-result/{record.get('id')}" if record.get("id") else "",
        cta_label="View Result",
        team_a_logo=_logo_from_record(record, "team_a_logo", "home_logo"),
        team_b_logo=_logo_from_record(record, "team_b_logo", "away_logo"),
        league_logo=_logo_from_record(record, "league_logo", "competition_logo"),
    )
    status = result_status(record)
    return {
        "date": format_date(record.get("game_date") or record.get("date") or record.get("created_at")),
        "raw_date": str(record.get("game_date") or record.get("date") or record.get("created_at") or ""),
        "sport": sport,
        "competition": card["competition"],
        "matchup": card["matchup"],
        "team_a": card["team_a"],
        "team_b": card["team_b"],
        "team_a_logo": card["team_a_logo"],
        "team_b_logo": card["team_b_logo"],
        "team_a_initials": card["team_a_initials"],
        "team_b_initials": card["team_b_initials"],
        "league_logo": card["league_logo"],
        "final_score": record.get("final_score_display") or record.get("score") or "Pending",
        "strength_tier": card["strength_tier"],
        "strength_class": card["strength_class"],
        "recommended_side": card["recommended_side"],
        "result": status,
        "result_label": status.title(),
        "confidence_pct": card["confidence_pct"],
        "data_confidence": card["data_confidence"],
        "summary_reason": card["summary_reason"],
        "detail_url": card["cta_url"],
    }


def _row_win_rate(rows: list[dict[str, Any]]) -> float:
    correct = sum(1 for row in rows if row["result"] == "correct")
    incorrect = sum(1 for row in rows if row["result"] == "incorrect")
    if correct + incorrect == 0:
        return 0.0
    return round((correct / (correct + incorrect)) * 100, 1)


def results_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["result"] for row in rows)
    graded = counts["correct"] + counts["incorrect"] + counts["push"]
    recent = [row for row in rows if row["result"] in {"correct", "incorrect", "push"}]
    last_10 = recent[:10]
    by_sport = {}
    for sport in sorted({row.get("sport") or "soccer" for row in rows}):
        items = [row for row in rows if (row.get("sport") or "soccer") == sport]
        by_sport[sport] = {"count": len(items), "win_rate": _row_win_rate(items)}
    return {
        "total_graded": graded,
        "win_rate": _row_win_rate(rows),
        "recent_win_rate": _row_win_rate(last_10),
        "correct": counts["correct"],
        "incorrect": counts["incorrect"],
        "pushes": counts["push"],
        "recent_form": [row["result"] for row in last_10],
        "last_10_count": len(last_10),
        "by_sport": by_sport,
    }


def results_breakdowns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_comp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_comp[row["competition"]].append(row)
        by_tier[row["strength_tier"]].append(row)

    competition_rows = [
        {"name": name, "count": len(items), "win_rate": _row_win_rate(items)}
        for name, items in by_comp.items()
    ]
    competition_rows.sort(key=lambda item: (item["win_rate"], item["count"]), reverse=True)

    tier_rows = []
    for tier in ("Best Bet", "Strong Lean", "Lean", "Risky"):
        items = by_tier.get(tier, [])
        tier_rows.append(
            {
                "name": tier,
                "class": TIER_CLASS[tier],
                "count": len(items),
                "win_rate": _row_win_rate(items),
            }
        )

    return {
        "competitions": competition_rows,
        "tiers": tier_rows,
        "best_competition": competition_rows[0]["name"] if competition_rows else "Awaiting results",
        "recent_soccer": [row for row in rows if row.get("sport") == "soccer"][:10],
        "recent_nba": [row for row in rows if row.get("sport") == "nba"][:10],
    }
