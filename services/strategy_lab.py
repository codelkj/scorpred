"""Context builders for the Strategy Lab page."""

from __future__ import annotations

from typing import Any

import ml_pipeline as mlp
import model_tracker as mt

_EMPTY_METRICS = {
    "total_predictions": 0,
    "finalized_predictions": 0,
    "wins": 0,
    "losses": 0,
    "overall_accuracy": None,
    "by_confidence": {},
    "by_sport": {},
    "recent_predictions": [],
}

_SPORT_LABELS = {
    "soccer": "Soccer",
    "nba": "NBA",
}


def _tone_for_accuracy(value: float | None) -> str:
    if value is None:
        return "muted"
    if value >= 55:
        return "positive"
    if value >= 45:
        return "warning"
    return "critical"


def _display_accuracy(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "Awaiting sample"


def _safe_metrics(raw_metrics: dict[str, Any] | None) -> dict[str, Any]:
    metrics = dict(_EMPTY_METRICS)
    if isinstance(raw_metrics, dict):
        metrics.update(raw_metrics)
    metrics.setdefault("by_confidence", {})
    metrics.setdefault("by_sport", {})
    metrics.setdefault("recent_predictions", [])
    return metrics


def _best_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: (row.get("accuracy") or -1, row.get("count") or 0))


def _format_breakdown_rows(payload: dict[str, Any], order: list[str], labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in order:
        item = payload.get(key)
        if not item:
            continue
        accuracy = item.get("accuracy")
        rows.append(
            {
                "key": key,
                "label": (labels or {}).get(key, key),
                "accuracy": accuracy,
                "accuracy_display": _display_accuracy(accuracy),
                "count": item.get("count", 0),
                "wins": item.get("wins", 0),
                "losses": item.get("losses", 0),
                "tone": _tone_for_accuracy(accuracy),
            }
        )
    return rows


def _recent_record(completed_predictions: list[dict[str, Any]]) -> str:
    if not completed_predictions:
        return "No finalized run yet"
    sample = completed_predictions[:5]
    wins = sum(1 for row in sample if row.get("winner_hit"))
    losses = len(sample) - wins
    return f"{wins}-{losses} in the last {len(sample)}"


def _hero_cards(metrics: dict[str, Any], completed_predictions: list[dict[str, Any]]) -> list[dict[str, str]]:
    pending_count = max(
        int(metrics.get("total_predictions") or 0) - int(metrics.get("finalized_predictions") or 0),
        0,
    )
    return [
        {
            "label": "Tracked Predictions",
            "value": str(metrics.get("total_predictions") or 0),
            "meta": "All saved winner calls across soccer and NBA",
            "tone": "positive",
        },
        {
            "label": "Finalized Backtests",
            "value": str(metrics.get("finalized_predictions") or 0),
            "meta": "Predictions already reconciled against real results",
            "tone": "muted",
        },
        {
            "label": "Live Hit Rate",
            "value": _display_accuracy(metrics.get("overall_accuracy")),
            "meta": "Graded from finalized winner outcomes only",
            "tone": _tone_for_accuracy(metrics.get("overall_accuracy")),
        },
        {
            "label": "Recent Record",
            "value": _recent_record(completed_predictions),
            "meta": f"{pending_count} pending prediction(s) still waiting on results",
            "tone": "muted",
        },
    ]


def _key_insights(
    metrics: dict[str, Any],
    sport_rows: list[dict[str, Any]],
    confidence_rows: list[dict[str, Any]],
    ml_summary: dict[str, Any],
) -> list[str]:
    insights: list[str] = []
    overall_accuracy = metrics.get("overall_accuracy")
    finalized_predictions = metrics.get("finalized_predictions") or 0

    if overall_accuracy is None:
        insights.append(
            "Tracked prediction grading is online, but the live sample still needs finalized results before a reliable hit rate can be shown."
        )
    else:
        insights.append(
            f"Live winner tracking is currently landing at {overall_accuracy:.1f}% across {finalized_predictions} finalized predictions."
        )

    best_sport = _best_row(sport_rows)
    if best_sport:
        insights.append(
            f"{best_sport['label']} is the strongest tracked segment so far at {best_sport['accuracy_display']} across {best_sport['count']} graded predictions."
        )
    else:
        insights.append(
            "Sport-level breakdowns will sharpen as more reconciled soccer and NBA predictions accumulate."
        )

    best_confidence = _best_row(confidence_rows)
    if best_confidence:
        insights.append(
            f"{best_confidence['label']} confidence picks are performing best at {best_confidence['accuracy_display']} across {best_confidence['count']} graded calls."
        )
    else:
        insights.append(
            "Confidence-level segmentation is available, but it still needs more finalized outcomes to become informative."
        )

    if ml_summary.get("available"):
        insights.append(ml_summary.get("summary"))
    else:
        insights.append(
            "The Strategy Lab ML card is ready to display the offline comparison as soon as a saved report is generated."
        )

    return insights[:4]


def empty_strategy_lab_context() -> dict[str, Any]:
    """Return a safe empty Strategy Lab context."""
    metrics = dict(_EMPTY_METRICS)
    ml_summary = mlp.build_strategy_lab_summary(report={})
    return {
        "metrics": metrics,
        "hero_cards": _hero_cards(metrics, []),
        "backtest_summary": {
            "overall_accuracy_display": _display_accuracy(metrics.get("overall_accuracy")),
            "finalized_predictions": 0,
            "pending_predictions": 0,
            "best_sport": None,
            "best_confidence": None,
            "blurb": (
                "Tracked winner predictions are graded from finalized real-world results, while the ML section reads from the saved offline comparison report."
            ),
        },
        "sport_breakdown": [],
        "confidence_breakdown": [],
        "key_insights": _key_insights(metrics, [], [], ml_summary),
        "ml_comparison": ml_summary,
        "recent_completed_predictions": [],
    }


def build_strategy_lab_context(
    tracker_module: Any = mt,
    ml_module: Any = mlp,
) -> dict[str, Any]:
    """Build the view model for the Strategy Lab page."""
    metrics = _safe_metrics(tracker_module.get_summary_metrics())
    completed_predictions = tracker_module.get_completed_predictions(limit=6)
    sport_rows = _format_breakdown_rows(
        metrics.get("by_sport") or {},
        ["soccer", "nba"],
        labels=_SPORT_LABELS,
    )
    confidence_rows = _format_breakdown_rows(
        metrics.get("by_confidence") or {},
        ["High", "Medium", "Low"],
    )
    ml_summary = ml_module.build_strategy_lab_summary()

    pending_count = max(
        int(metrics.get("total_predictions") or 0) - int(metrics.get("finalized_predictions") or 0),
        0,
    )
    best_sport = _best_row(sport_rows)
    best_confidence = _best_row(confidence_rows)

    return {
        "metrics": metrics,
        "hero_cards": _hero_cards(metrics, completed_predictions),
        "backtest_summary": {
            "overall_accuracy_display": _display_accuracy(metrics.get("overall_accuracy")),
            "finalized_predictions": metrics.get("finalized_predictions") or 0,
            "pending_predictions": pending_count,
            "best_sport": best_sport,
            "best_confidence": best_confidence,
            "blurb": (
                "Use this page to compare live tracked outcomes with the saved leakage-safe ML evaluation without mixing the two measurement windows together."
            ),
        },
        "sport_breakdown": sport_rows,
        "confidence_breakdown": confidence_rows,
        "key_insights": _key_insights(metrics, sport_rows, confidence_rows, ml_summary),
        "ml_comparison": ml_summary,
        "recent_completed_predictions": completed_predictions,
    }
