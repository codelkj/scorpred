"""Context builders for the Strategy Lab page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import generate_ml_report as report_generator
import ml_service
import ml_pipeline as mlp
import model_tracker as mt
from runtime_paths import clean_soccer_dataset_path, clean_soccer_model_path, ml_report_path
from train_model import FEATURE_COLUMNS

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

_DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "historical_matches.csv"
_CLEAN_DATASET = clean_soccer_dataset_path()
_DEFAULT_MATCH_DATASET = clean_soccer_dataset_path()
_DEFAULT_FEATURES = "form,goals_scored,goals_conceded,goal_diff"
_DEFAULT_LABEL = "result"
_DEFAULT_DATE_KEY = "date"


def _as_percent(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if 0.0 <= numeric <= 1.0:
        numeric *= 100.0
    return round(numeric, 1)


def _is_report_stale(report_path: Path) -> bool:
    payload = mlp.load_comparison_report(report_path)
    if not payload:
        return True

    workflow = payload.get("workflow") or {}
    report_features = workflow.get("feature_keys") or []
    if report_features != FEATURE_COLUMNS:
        return True

    clean_dataset = Path(_CLEAN_DATASET)
    expected_model = clean_soccer_model_path()
    expected_dataset = clean_dataset if clean_dataset.exists() else Path(_DEFAULT_DATASET)

    workflow_dataset = Path(str(workflow.get("dataset_path") or "")) if workflow.get("dataset_path") else None
    workflow_model = Path(str(workflow.get("model_path") or "")) if workflow.get("model_path") else None

    if clean_dataset.exists() and expected_model.exists():
        if workflow_dataset != clean_dataset or workflow_model != expected_model:
            return True

    if not report_path.exists():
        return True

    report_mtime = report_path.stat().st_mtime
    newest_sources = [expected_dataset.stat().st_mtime]
    if expected_model.exists():
        newest_sources.append(expected_model.stat().st_mtime)
    newest_input = max(newest_sources)
    return report_mtime < newest_input


def _ensure_ml_report_exists(ml_module: Any) -> bool:
    report_path = Path(ml_module.DEFAULT_REPORT_PATH)
    canonical_report_path = Path(ml_report_path())

    if report_path != canonical_report_path:
        if report_path.exists():
            return True
        if not _DEFAULT_DATASET.exists():
            return False
        try:
            report_generator.generate_report(
                input_path=_DEFAULT_DATASET,
                features=_DEFAULT_FEATURES,
                label=_DEFAULT_LABEL,
                date_key=_DEFAULT_DATE_KEY,
                output=report_path,
            )
        except Exception:
            return False
        return report_path.exists()

    if report_path.exists():
        if not _is_report_stale(report_path):
            return True

    if _CLEAN_DATASET.exists() and clean_soccer_model_path().exists():
        try:
            report_generator.generate_clean_soccer_report(
                dataset_path=_CLEAN_DATASET,
                model_path=clean_soccer_model_path(),
                output=report_path,
            )
            return report_path.exists()
        except Exception:
            pass

    if not _DEFAULT_DATASET.exists():
        return False

    try:
        report_generator.generate_report(
            input_path=_DEFAULT_DATASET,
            features=_DEFAULT_FEATURES,
            label=_DEFAULT_LABEL,
            date_key=_DEFAULT_DATE_KEY,
            output=report_path,
        )
    except Exception:
        return False

    return report_path.exists()


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
    performance_comparison: dict[str, Any],
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

    combined_accuracy = performance_comparison.get("combined_accuracy")
    ml_accuracy = performance_comparison.get("ml_accuracy")
    if combined_accuracy is not None and ml_accuracy is not None:
        insights.append(
            f"Combined rule + ML signal currently evaluates at {combined_accuracy:.1f}% vs standalone ML at {ml_accuracy:.1f}%."
        )
    elif ml_summary.get("available"):
        insights.append(ml_summary.get("summary"))
    else:
        insights.append(
            "The Strategy Lab ML card is ready to display the offline comparison as soon as a saved report is generated."
        )

    return insights[:4]


def _performance_comparison(metrics: dict[str, Any]) -> dict[str, Any]:
    report = mlp.load_comparison_report()
    if report:
        workflow = report.get("workflow") or {}
        performance = report.get("performance") or {}
        saved_ml_accuracy = _as_percent(performance.get("ml_accuracy"))
        saved_combined_accuracy = _as_percent(performance.get("combined_accuracy"))
        saved_rule_accuracy = _as_percent(performance.get("rule_accuracy"))
        if saved_ml_accuracy is not None and saved_combined_accuracy is not None:
            rule_accuracy = metrics.get("overall_accuracy")
            if rule_accuracy is None:
                rule_accuracy = saved_rule_accuracy

            evaluation_matches = performance.get("evaluation_matches")
            if not isinstance(evaluation_matches, int):
                evaluation_matches = workflow.get("test_size") or 0

            return {
                "available": True,
                "message": None,
                "rule_accuracy": rule_accuracy,
                "ml_accuracy": saved_ml_accuracy,
                "combined_accuracy": saved_combined_accuracy,
                "evaluation_matches": evaluation_matches,
            }

    comparison = ml_service.evaluate_model_comparison(dataset_path=_DEFAULT_MATCH_DATASET)
    rule_accuracy = metrics.get("overall_accuracy")
    if rule_accuracy is None:
        rule_accuracy = comparison.get("rule_accuracy")

    return {
        "available": bool(comparison.get("available")),
        "message": comparison.get("message"),
        "rule_accuracy": rule_accuracy,
        "ml_accuracy": comparison.get("ml_accuracy"),
        "combined_accuracy": comparison.get("combined_accuracy"),
        "evaluation_matches": comparison.get("evaluation_matches") or 0,
    }


def empty_strategy_lab_context() -> dict[str, Any]:
    """Return a safe empty Strategy Lab context."""
    metrics = dict(_EMPTY_METRICS)
    ml_summary = mlp.build_strategy_lab_summary(report={})
    comparison = _performance_comparison(metrics)
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
        "key_insights": _key_insights(metrics, [], [], ml_summary, comparison),
        "ml_comparison": ml_summary,
        "performance_comparison": comparison,
        "recent_completed_predictions": [],
    }


def _ml_vs_rule_insights(
    metrics: dict[str, Any],
    confidence_rows: list[dict[str, Any]],
    ml_summary: dict[str, Any],
    performance_comparison: dict[str, Any],
) -> list[str]:
    insights: list[str] = []
    live_accuracy = metrics.get("overall_accuracy")
    ml_accuracy = performance_comparison.get("ml_accuracy")
    combined_accuracy = performance_comparison.get("combined_accuracy")

    if ml_accuracy is not None and combined_accuracy is not None:
        if combined_accuracy > ml_accuracy:
            insights.append(
                f"Combined rule + ML signal is outperforming standalone ML ({combined_accuracy:.1f}% vs {ml_accuracy:.1f}%)."
            )
        elif combined_accuracy < ml_accuracy:
            insights.append(
                f"Standalone ML is currently stronger than the combined signal ({ml_accuracy:.1f}% vs {combined_accuracy:.1f}%)."
            )
        else:
            insights.append(
                f"Combined and standalone ML are currently tied at {combined_accuracy:.1f}%."
            )

    if ml_summary.get("available") and live_accuracy is not None:
        rf_accuracy = ml_summary.get("random_forest_accuracy")
        if isinstance(rf_accuracy, (int, float)):
            if rf_accuracy > live_accuracy:
                insights.append(
                    f"ML currently leads in offline evaluation ({rf_accuracy:.1f}% vs live tracked {live_accuracy:.1f}%)."
                )
            elif rf_accuracy < live_accuracy:
                insights.append(
                    f"Rule workflow is currently stronger in tracked outcomes ({live_accuracy:.1f}% vs ML {rf_accuracy:.1f}%)."
                )
            else:
                insights.append(
                    f"ML and tracked rule workflow are currently aligned at {live_accuracy:.1f}%."
                )

    best_confidence = _best_row(confidence_rows)
    if best_confidence:
        insights.append(
            f"Agreement is strongest in {best_confidence['label']} confidence picks ({best_confidence['accuracy_display']})."
        )
    else:
        insights.append("Agreement strength is still stabilizing as finalized samples grow.")

    if ml_summary.get("available"):
        insights.append(ml_summary.get("summary", "ML comparison report is available."))
    else:
        insights.append("ML report is not available yet, so rule-vs-ML comparison is provisional.")

    return insights[:3]


def build_strategy_lab_context(
    tracker_module: Any = mt,
    ml_module: Any = mlp,
) -> dict[str, Any]:
    """Build the view model for the Strategy Lab page."""
    metrics = _safe_metrics(tracker_module.get_summary_metrics())
    completed_predictions = tracker_module.get_completed_predictions(limit=6)
    avoid_impact_predictions = tracker_module.get_completed_predictions(limit=50)
    sport_rows = _format_breakdown_rows(
        metrics.get("by_sport") or {},
        ["soccer", "nba"],
        labels=_SPORT_LABELS,
    )
    confidence_rows = _format_breakdown_rows(
        metrics.get("by_confidence") or {},
        ["High", "Medium", "Low"],
    )
    _ensure_ml_report_exists(ml_module)
    comparison = _performance_comparison(metrics)
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
        "key_insights": _key_insights(metrics, sport_rows, confidence_rows, ml_summary, comparison),
        "ml_comparison": ml_summary,
        "ml_rule_insights": _ml_vs_rule_insights(metrics, confidence_rows, ml_summary, comparison),
        "performance_comparison": comparison,
        "recent_completed_predictions": completed_predictions,
        "avoid_impact_predictions": avoid_impact_predictions,
    }
