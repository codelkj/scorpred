"""Decision-first UI helpers for ScorPred.

These helpers translate existing prediction/tracking payloads into the
action-first shape rendered by the Flask templates. Internal confidence tiers
can still exist in stored data, but this module never exposes those tier names
as user-facing labels.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re
from typing import Any


ACTION_ORDER = {"BET": 0, "CONSIDER": 1, "SKIP": 2}
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


def probability_from_prediction(prediction: dict[str, Any] | None) -> float:
    if not isinstance(prediction, dict):
        return 0.0

    explicit = prediction.get("confidence_pct")
    if explicit not in (None, ""):
        return normalize_percent(explicit)

    probs = prediction.get("win_probabilities")
    if not isinstance(probs, dict):
        probs = {
            "a": prediction.get("prob_a") or prediction.get("team_a_probability"),
            "b": prediction.get("prob_b") or prediction.get("team_b_probability"),
            "draw": prediction.get("prob_draw"),
        }

    values = [
        normalize_percent(value)
        for key, value in probs.items()
        if key not in {"label", "name"} and value not in (None, "")
    ]
    return max(values) if values else 0.0


def probability_gap(prediction: dict[str, Any] | None, *, sport: str = "soccer") -> float:
    if not isinstance(prediction, dict):
        return 0.0
    probs = prediction.get("win_probabilities") or {}
    a = normalize_percent(probs.get("a") or probs.get("team_a") or prediction.get("prob_a"), 50)
    b = normalize_percent(probs.get("b") or probs.get("team_b") or prediction.get("prob_b"), 50)
    if sport == "soccer":
        draw = normalize_percent(probs.get("draw") or prediction.get("prob_draw"), 0)
        return max(abs(a - b), abs(max(a, b) - draw))
    return abs(a - b)


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


def pick_side(
    prediction: dict[str, Any] | None,
    *,
    team_a: str = "Team A",
    team_b: str = "Team B",
    sport: str = "soccer",
) -> tuple[str, bool]:
    if not isinstance(prediction, dict):
        return "No reliable edge", True

    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    pick = _raw_pick(best_pick, prediction)
    tracking = str(best_pick.get("tracking_team") or best_pick.get("team") or prediction.get("predicted_winner") or "").strip()
    pick_l = pick.lower()
    tracking_l = tracking.lower()

    if tracking_l in {"a", "home", team_a.lower()}:
        return team_a, False
    if tracking_l in {"b", "away", team_b.lower()}:
        return team_b, False
    if tracking_l in {"draw", "avoid", "skip"} or pick_l in {"draw", "avoid", "skip"}:
        return "No reliable edge", True

    if pick:
        for suffix in (" to win", " win", " moneyline", " ml"):
            if pick_l.endswith(suffix):
                pick = pick[: -len(suffix)].strip()
                pick_l = pick.lower()
                break
        if "draw" in pick_l or "no reliable" in pick_l:
            return "No reliable edge", True
        return pick, False

    probs = prediction.get("win_probabilities") or {}
    a = normalize_percent(probs.get("a") or probs.get("team_a") or prediction.get("prob_a"), 0)
    b = normalize_percent(probs.get("b") or probs.get("team_b") or prediction.get("prob_b"), 0)
    draw = normalize_percent(probs.get("draw") or prediction.get("prob_draw"), 0)
    if sport == "soccer" and draw >= max(a, b):
        return "No reliable edge", True
    if a > b:
        return team_a, False
    if b > a:
        return team_b, False
    return "No reliable edge", True


def action_for_prediction(
    prediction: dict[str, Any] | None,
    *,
    data_state: str,
    no_side: bool,
    sport: str = "soccer",
) -> str:
    if data_state == "limited" or no_side or not isinstance(prediction, dict):
        return "SKIP"

    existing = str(prediction.get("action") or prediction.get("action_label") or prediction.get("play_type") or "").strip().upper()
    if existing == "BET":
        return "BET"
    if existing in {"CONSIDER", "LEAN"}:
        return "CONSIDER"
    if existing in {"SKIP", "AVOID"}:
        return "SKIP"

    pct = probability_from_prediction(prediction)
    gap = probability_gap(prediction, sport=sport)
    if pct >= 62 and gap >= 10:
        return "BET"
    if pct >= 52 and gap >= 4:
        return "CONSIDER"
    return "SKIP"


def display_confidence(raw_pct: float, action: str) -> int:
    if action == "BET":
        return int(round(clamp(raw_pct or 62, 62, 88)))
    if action == "CONSIDER":
        return int(round(clamp(raw_pct or 54, 52, 61)))
    return int(round(clamp(raw_pct or 49, 35, 49)))


def clean_reason(text: str | None) -> str:
    reason = str(text or "").strip()
    if not reason:
        return ""
    replacements = [
        (r"\bmodel[- ]?derived\b", "data-backed"),
        (r"\bmodel\b", "read"),
        (r"\bengine\b", "system"),
        (r"\bprediction\b", "pick"),
        (r"\blean(?:ing)?\b", "edge"),
        (r"\bavoid\b", "skip"),
        (r"score gap[:\s]*[0-9.\/]+", ""),
        (r"gap[:\s]*[0-9.\/]+", ""),
        (r"internal rating[:\s].*", ""),
    ]
    for pattern, replacement in replacements:
        reason = re.sub(pattern, replacement, reason, flags=re.IGNORECASE)
    reason = re.sub(r"\s+", " ", reason).strip(" .")
    return reason[:1].upper() + reason[1:] if reason else ""


def fallback_reason(
    *,
    action: str,
    data_state: str,
    no_side: bool,
    sport: str,
    pick: str,
) -> str:
    if data_state == "limited":
        return "Limited data available"
    if action == "SKIP":
        return "Even matchup, high draw risk" if sport == "soccer" else "Even matchup, no reliable edge"
    if action == "BET":
        return "Clear edge across recent form and matchup context"
    if pick and pick != "No reliable edge":
        return "Slight edge, monitor team news"
    return "No reliable edge"


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
) -> dict[str, Any]:
    has_prediction = isinstance(prediction, dict) and bool(prediction)
    prediction = prediction if isinstance(prediction, dict) else {}
    best_pick = prediction.get("best_pick") if isinstance(prediction.get("best_pick"), dict) else {}
    badge = data_badge(prediction.get("data_completeness") or {}, has_prediction=has_prediction)
    side, no_side = pick_side(prediction, team_a=team_a, team_b=team_b, sport=sport)
    action = action_for_prediction(prediction, data_state=badge["state"], no_side=no_side, sport=sport)
    raw_pct = probability_from_prediction(prediction)
    confidence_pct = display_confidence(raw_pct, action)
    reason = clean_reason(best_pick.get("reasoning") or prediction.get("matchup_reading") or prediction.get("decision_summary"))
    if not reason:
        reason = fallback_reason(
            action=action,
            data_state=badge["state"],
            no_side=no_side,
            sport=sport,
            pick=side,
        )
    if not support_text:
        if badge["state"] == "limited":
            support_text = "Treat this as a no-play until stronger context is available."
        elif action == "BET":
            support_text = "Clear enough to lead the slate."
        elif action == "CONSIDER":
            support_text = "Worth watching, but not automatic."
        else:
            support_text = "Protect the bankroll when the edge is thin."

    return {
        "sport": sport,
        "matchup": f"{team_a} vs {team_b}",
        "team_a": team_a,
        "team_b": team_b,
        "competition": competition,
        "match_date": match_date,
        "venue": venue,
        "action": action,
        "action_class": action.lower(),
        "pick": side if action != "SKIP" else "No reliable edge",
        "confidence_pct": confidence_pct,
        "raw_confidence_pct": round(raw_pct, 1),
        "reason": reason,
        "data_badge": badge,
        "support_text": support_text,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "cta_method": cta_method.lower() if cta_method else "get",
        "cta_payload": cta_payload or {},
        "confidence_tier": internal_confidence_tier(confidence_pct),
    }


def internal_confidence_tier(confidence_pct: float) -> str:
    if confidence_pct >= 62:
        return "high"
    if confidence_pct >= 52:
        return "medium"
    return "low"


def plan_summary(cards: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter((card.get("action") or "SKIP").upper() for card in cards or [])
    return {
        "BET": counts.get("BET", 0),
        "CONSIDER": counts.get("CONSIDER", 0),
        "SKIP": counts.get("SKIP", 0),
    }


def sort_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        cards or [],
        key=lambda card: (
            ACTION_ORDER.get(str(card.get("action") or "SKIP").upper(), 3),
            DATA_ORDER.get(((card.get("data_badge") or {}).get("state") or "limited"), 3),
            -safe_float(card.get("confidence_pct"), 0),
            str(card.get("match_date") or ""),
        ),
    )


def top_opportunities(cards: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    return [card for card in sort_cards(cards) if card.get("action") in {"BET", "CONSIDER"}][:limit]


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


def result_status(record: dict[str, Any], action: str) -> str:
    if action == "SKIP":
        return "skipped"
    raw = str(record.get("overall_game_result") or record.get("result") or "").strip().lower()
    if raw in {"push", "void"} or record.get("is_push"):
        return "push"
    if record.get("is_correct") is True or record.get("winner_hit") is True or record.get("game_win") is True:
        return "correct"
    if record.get("is_correct") is False or record.get("winner_hit") is False or raw in {"loss", "incorrect"}:
        return "incorrect"
    return "push"


def normalize_result_record(record: dict[str, Any]) -> dict[str, Any]:
    sport = str(record.get("sport") or "soccer").lower()
    team_a = record.get("team_a") or record.get("home_team") or "Team A"
    team_b = record.get("team_b") or record.get("away_team") or "Team B"
    prediction = {
        "best_pick": {
            "prediction": record.get("predicted_pick_label") or record.get("predicted_winner"),
            "team": record.get("predicted_winner"),
            "reasoning": record.get("reasoning") or record.get("decision_explainer"),
            "confidence": record.get("confidence"),
        },
        "win_probabilities": {
            "a": record.get("prob_a"),
            "b": record.get("prob_b"),
            "draw": record.get("prob_draw"),
        },
        "confidence_pct": record.get("confidence_pct"),
        "action_label": record.get("action_label"),
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
    )
    action = str(record.get("action_label") or card["action"]).upper()
    if action in {"LEAN"}:
        action = "CONSIDER"
    elif action in {"AVOID"}:
        action = "SKIP"
    elif action not in {"BET", "CONSIDER", "SKIP"}:
        action = card["action"]
    card["action"] = action
    card["action_class"] = action.lower()
    status = result_status(record, action)
    return {
        "date": format_date(record.get("game_date") or record.get("date") or record.get("created_at")),
        "raw_date": str(record.get("game_date") or record.get("date") or record.get("created_at") or ""),
        "competition": card["competition"],
        "matchup": card["matchup"],
        "final_score": record.get("final_score_display") or record.get("score") or "Pending",
        "action": action,
        "action_class": action.lower(),
        "predicted_side": card["pick"],
        "result": status,
        "result_label": status.title(),
        "confidence_pct": card["confidence_pct"],
        "data_badge": card["data_badge"],
        "reason": card["reason"],
        "detail_url": card["cta_url"],
    }


def results_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["result"] for row in rows)
    graded = counts["correct"] + counts["incorrect"] + counts["push"]
    win_rate = round((counts["correct"] / max(1, counts["correct"] + counts["incorrect"])) * 100, 1) if graded else 0.0

    recent = [row for row in rows if row["result"] in {"correct", "incorrect", "push"}]
    last_10 = recent[:10]
    last_20 = recent[:20]

    streak_type = "none"
    streak_count = 0
    for row in recent:
        if row["result"] not in {"correct", "incorrect"}:
            if streak_count == 0:
                continue
            break
        if streak_type == "none":
            streak_type = row["result"]
            streak_count = 1
            continue
        if row["result"] == streak_type:
            streak_count += 1
        else:
            break

    return {
        "total_graded": graded,
        "win_rate": win_rate,
        "correct": counts["correct"],
        "incorrect": counts["incorrect"],
        "pushes": counts["push"],
        "skips": counts["skipped"],
        "recent_form": [row["result"] for row in last_10],
        "last_10_count": len(last_10),
        "last_20_count": len(last_20),
        "last_10_win_rate": _row_win_rate(last_10),
        "last_20_win_rate": _row_win_rate(last_20),
        "current_streak": f"{streak_count} {streak_type}" if streak_count else "Awaiting graded picks",
    }


def _row_win_rate(rows: list[dict[str, Any]]) -> float:
    correct = sum(1 for row in rows if row["result"] == "correct")
    incorrect = sum(1 for row in rows if row["result"] == "incorrect")
    if correct + incorrect == 0:
        return 0.0
    return round((correct / (correct + incorrect)) * 100, 1)


def results_breakdowns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_comp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_comp[row["competition"]].append(row)
        by_action[row["action"]].append(row)

    competition_rows = []
    for name, items in by_comp.items():
        competition_rows.append(
            {
                "name": name,
                "count": len([item for item in items if item["result"] != "skipped"]),
                "win_rate": _row_win_rate(items),
            }
        )
    competition_rows.sort(key=lambda item: (item["win_rate"], item["count"]), reverse=True)

    action_rows = []
    for action in ("BET", "CONSIDER", "SKIP"):
        items = by_action.get(action, [])
        action_rows.append(
            {
                "name": action,
                "count": len(items),
                "win_rate": _row_win_rate(items),
                "usage": len(items),
            }
        )

    return {
        "competitions": competition_rows,
        "actions": action_rows,
        "best_competition": competition_rows[0]["name"] if competition_rows else "Awaiting results",
    }
