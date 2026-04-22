"""Decision card pass-through helpers for soccer UI."""

from __future__ import annotations

from typing import Any

_REQUIRED_FIELDS = (
    "action",
    "recommended_side",
    "confidence",
    "reason",
    "data_quality",
    "metric_breakdown",
)


def build_decision_card(prediction: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a strict UI card from canonical prediction output.

    This function is intentionally pass-through only: it does not normalize,
    fabricate, or mutate model values.
    """
    if not isinstance(prediction, dict):
        return None

    probabilities = prediction.get("probabilities")
    if not isinstance(probabilities, dict):
        probabilities = prediction.get("win_probabilities")
    if not isinstance(probabilities, dict):
        return None
    if any(probabilities.get(key) is None for key in ("a", "draw", "b")):
        return None

    if any(prediction.get(field) is None for field in _REQUIRED_FIELDS):
        return None

    return {
        "action": prediction["action"],
        "recommended_side": prediction["recommended_side"],
        "confidence": prediction["confidence"],
        "probabilities": probabilities,
        "reason": prediction["reason"],
        "data_quality": prediction["data_quality"],
        "metric_breakdown": prediction["metric_breakdown"],
    }


def sort_cards_by_kickoff(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        cards or [],
        key=lambda row: str(((row.get("fixture") or {}).get("fixture") or {}).get("date") or ""),
    )


def top_opportunities(cards: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    def _score(card: dict[str, Any]) -> tuple[float, float]:
        confidence = float((card.get("card") or {}).get("confidence") or 0.0)
        probs = (card.get("card") or {}).get("probabilities") or {}
        best_prob = max(float(probs.get("a") or 0.0), float(probs.get("draw") or 0.0), float(probs.get("b") or 0.0))
        return confidence, best_prob

    ranked = sorted(cards or [], key=_score, reverse=True)
    return ranked[: max(0, int(limit))]


def plan_summary(cards: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"total": 0, "bet": 0, "lean": 0, "pass": 0}
    for row in cards or []:
        summary["total"] += 1
        action = str(((row.get("card") or {}).get("action") or "")).strip().upper()
        if action == "BET":
            summary["bet"] += 1
        elif action == "LEAN":
            summary["lean"] += 1
        else:
            summary["pass"] += 1
    return summary
