"""Context builders for the Strategy Lab page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import generate_ml_report as report_generator
import ml_service
import ml_pipeline as mlp
import model_tracker as mt
import soccer_selector as selector
from runtime_paths import clean_soccer_dataset_path, clean_soccer_model_path, ensemble_soccer_model_path, ml_report_path, walk_forward_report_path
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
    # Prefer ensemble model, fall back to standalone RF
    expected_model = ensemble_soccer_model_path() if ensemble_soccer_model_path().exists() else clean_soccer_model_path()
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
    """Return True if a usable ML report file is available on disk.

    This function is intentionally READ-ONLY at request time.  Report
    generation is handled offline by ``daily_refresh.py`` / ``weekly_retrain.py``
    so that page loads never block on expensive model evaluation.
    """
    report_path = Path(ml_module.DEFAULT_REPORT_PATH)
    canonical_report_path = Path(ml_report_path())

    # Always accept any existing file at the configured path — the pipeline
    # is responsible for keeping it fresh; the app just reads it.
    if report_path.exists():
        return True

    # Fallback: canonical path differs (legacy config) — accept that too.
    if report_path != canonical_report_path and canonical_report_path.exists():
        return True

    # Report not found — pipeline has not run yet.  Return False so the
    # Strategy Lab page shows an appropriate "awaiting pipeline" message
    # rather than triggering an on-demand expensive computation.
    return False


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
    """Build an offline model-comparison summary.

    All three accuracy figures (rule / ml / combined) MUST come from the same
    offline evaluation population.  ``metrics`` (the live tracker) is accepted
    for signature compatibility but is intentionally NOT mixed into the offline
    numbers any more — doing so would compare apples to oranges.
    """
    report = mlp.load_comparison_report()
    if report:
        workflow = report.get("workflow") or {}
        performance = report.get("performance") or {}
        saved_ml_accuracy = _as_percent(performance.get("ml_accuracy"))
        saved_combined_accuracy = _as_percent(performance.get("combined_accuracy"))
        saved_rule_accuracy = _as_percent(performance.get("rule_accuracy"))
        if saved_ml_accuracy is not None and saved_combined_accuracy is not None:
            evaluation_matches = performance.get("evaluation_matches")
            if not isinstance(evaluation_matches, int):
                evaluation_matches = workflow.get("test_size") or 0

            return {
                "available": True,
                "message": None,
                "rule_accuracy": saved_rule_accuracy,
                "ml_accuracy": saved_ml_accuracy,
                "combined_accuracy": saved_combined_accuracy,
                "evaluation_matches": evaluation_matches,
            }

    comparison = ml_service.evaluate_model_comparison(dataset_path=_DEFAULT_MATCH_DATASET)

    return {
        "available": bool(comparison.get("available")),
        "message": comparison.get("message"),
        "rule_accuracy": comparison.get("rule_accuracy"),
        "ml_accuracy": comparison.get("ml_accuracy"),
        "combined_accuracy": comparison.get("combined_accuracy"),
        "evaluation_matches": comparison.get("evaluation_matches") or 0,
    }


def _date_range_display(values: list[str] | None) -> str:
    if not values or len(values) < 2:
        return "Date range unavailable"
    start, end = str(values[0] or "").strip(), str(values[1] or "").strip()
    if not start or not end:
        return "Date range unavailable"
    return f"{start} to {end}"


def _best_model_summary(models: dict[str, Any]) -> tuple[str | None, float | None]:
    best_name = None
    best_accuracy = None
    for name, payload in (models or {}).items():
        accuracy = _as_percent((payload or {}).get("mean_accuracy"))
        if accuracy is None:
            continue
        if best_accuracy is None or accuracy > best_accuracy:
            best_name = name
            best_accuracy = accuracy
    return best_name, best_accuracy


def _window_summary(window: dict[str, Any] | None, *, label: str) -> dict[str, Any]:
    payload = window or {}
    agg = payload.get("aggregate") or {}
    if not agg:
        return {"available": False, "label": label}

    combined = agg.get("combined", {})
    policy = agg.get("policy", {})
    config = payload.get("config", {})
    best_model_name, best_model_accuracy = _best_model_summary(agg.get("base_models", {}))

    return {
        "available": True,
        "label": label,
        "n_folds": agg.get("n_folds", 0),
        "total_test_matches": agg.get("total_test_matches", 0),
        "mean_combined_accuracy": _as_percent(combined.get("mean_combined_accuracy")),
        "std_combined_accuracy": _as_percent(combined.get("std_combined_accuracy")),
        "mean_rule_accuracy": _as_percent(combined.get("mean_rule_accuracy")),
        "mean_ml_accuracy": _as_percent(combined.get("mean_ml_accuracy")),
        "mean_avg_confidence_pct": combined.get("mean_avg_confidence_pct"),
        "policy_hit_rate_pct": policy.get("aggregate_hit_rate_pct"),
        "policy_coverage_pct": policy.get("aggregate_coverage_pct"),
        "policy_total_placed": policy.get("total_placed", 0),
        "trend": agg.get("trend", "N/A"),
        "trend_delta": _as_percent(agg.get("trend_delta")),
        "best_model": best_model_name,
        "best_model_accuracy": best_model_accuracy,
        "date_range": config.get("date_range") or [],
        "date_range_display": _date_range_display(config.get("date_range") or []),
        "total_rows": config.get("total_rows", 0),
    }


def _selector_display(payload: dict[str, Any] | None) -> dict[str, Any]:
    profile = payload or {}
    if not profile:
        return {"available": False}

    segment_rows: list[dict[str, Any]] = []
    segments = profile.get("segments") or {}
    for key in ["overall", *selector.SEGMENT_PRIORITY]:
        metrics = segments.get(key)
        if not metrics:
            continue
        best_source = str(metrics.get("best_source") or "")
        if not best_source:
            best_candidates = {
                "combined": metrics.get("combined_accuracy"),
                "ml": metrics.get("ml_accuracy"),
                "rule": metrics.get("rule_accuracy"),
            }
            valid = {name: value for name, value in best_candidates.items() if isinstance(value, (int, float))}
            if valid:
                best_source = max(valid, key=valid.get)
        segment_rows.append(
            {
                "key": key,
                "label": "Overall" if key == "overall" else selector.SEGMENT_METADATA.get(key, {}).get("label", key.replace("_", " ").title()),
                "description": "Whole recent evaluation window." if key == "overall" else selector.SEGMENT_METADATA.get(key, {}).get("description", ""),
                "sample_size": metrics.get("count", 0),
                "rule_accuracy": _as_percent(metrics.get("rule_accuracy")),
                "ml_accuracy": _as_percent(metrics.get("ml_accuracy")),
                "combined_accuracy": _as_percent(metrics.get("combined_accuracy")),
                "best_source": best_source,
                "best_source_label": selector.source_label(best_source),
            }
        )

    override_rows: list[dict[str, Any]] = []
    for row in profile.get("overrides") or []:
        segment = str(row.get("segment") or "")
        preferred_source = row.get("preferred_source")
        override_rows.append(
            {
                "segment": segment,
                "label": selector.SEGMENT_METADATA.get(segment, {}).get("label", segment.replace("_", " ").title()),
                "preferred_source": preferred_source,
                "preferred_source_label": selector.source_label(preferred_source),
                "sample_size": row.get("sample_size", 0),
                "preferred_accuracy": _as_percent(row.get("preferred_accuracy")),
                "default_accuracy": _as_percent(row.get("default_accuracy")),
                "gain_vs_default": _as_percent(row.get("gain_vs_default")),
                "reason": row.get("reason") or selector.SEGMENT_METADATA.get(segment, {}).get("description", ""),
            }
        )

    default_source = profile.get("default_source")
    return {
        "available": True,
        "default_source": default_source,
        "default_source_label": selector.source_label(default_source),
        "default_accuracy": _as_percent(profile.get("default_accuracy")),
        "segment_rows": segment_rows,
        "override_rows": override_rows,
        "summary": profile.get("summary") or "Selector profile available.",
        "min_sample_size": profile.get("min_sample_size", 0),
        "min_gain": _as_percent(profile.get("min_gain")),
    }


def walk_forward_summary() -> dict[str, Any]:
    """Load walk-forward backtest report and build a display-ready summary."""
    path = walk_forward_report_path()
    if not path.exists():
        return {"available": False}
    try:
        import json
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"available": False}

    all_history_payload = (report.get("windows") or {}).get("all_history") or {
        "aggregate": report.get("aggregate"),
        "config": report.get("config"),
        "folds": report.get("folds"),
    }
    recent_payload = (report.get("windows") or {}).get("last_3_years") or {}

    all_history = _window_summary(all_history_payload, label="All History")
    last_3_years = _window_summary(recent_payload, label="Last 3 Years")
    headline = last_3_years if last_3_years.get("available") else all_history
    if not headline.get("available"):
        return {"available": False}

    selector_summary = _selector_display(
        report.get("selector")
        or recent_payload.get("selector")
        or all_history_payload.get("selector")
    )

    return {
        "available": True,
        "n_folds": all_history.get("n_folds", 0),
        "total_test_matches": all_history.get("total_test_matches", 0),
        "mean_combined_accuracy": all_history.get("mean_combined_accuracy"),
        "std_combined_accuracy": all_history.get("std_combined_accuracy"),
        "mean_rule_accuracy": all_history.get("mean_rule_accuracy"),
        "mean_ml_accuracy": all_history.get("mean_ml_accuracy"),
        "mean_avg_confidence_pct": all_history.get("mean_avg_confidence_pct"),
        "policy_hit_rate_pct": all_history.get("policy_hit_rate_pct"),
        "policy_coverage_pct": all_history.get("policy_coverage_pct"),
        "policy_total_placed": all_history.get("policy_total_placed", 0),
        "trend": all_history.get("trend", "N/A"),
        "trend_delta": all_history.get("trend_delta"),
        "best_model": all_history.get("best_model"),
        "best_model_accuracy": all_history.get("best_model_accuracy"),
        "windows": {
            "all_history": all_history,
            "last_3_years": last_3_years,
        },
        "selector": selector_summary,
        "headline_window": headline.get("label"),
        "generated_at": report.get("generated_at"),
    }


def empty_strategy_lab_context() -> dict[str, Any]:
    """Return a safe empty Strategy Lab context."""
    metrics = dict(_EMPTY_METRICS)
    ml_summary = mlp.build_strategy_lab_summary(report={})
    comparison = _performance_comparison(metrics)
    return {
        "metrics": metrics,
        # Explicit source-labelled accuracy fields (both None when no data yet).
        "live_hit_rate": None,
        "live_sample_size": 0,
        "offline_accuracy": None,
        "hero_cards": _hero_cards(metrics, []),
        "backtest_summary": {
            "overall_accuracy_display": _display_accuracy(None),
            "finalized_predictions": 0,
            "pending_predictions": 0,
            "best_sport": None,
            "best_confidence": None,
            "blurb": (
                "Live hit rate comes from real tracked + graded predictions. "
                "Offline accuracy comes from a held-out evaluation set that was "
                "never seen during training. These two numbers measure different "
                "things and must not be averaged."
            ),
        },
        "sport_breakdown": [],
        "confidence_breakdown": [],
        "key_insights": _key_insights(metrics, [], [], ml_summary, comparison),
        "ml_comparison": ml_summary,
        "performance_comparison": comparison,
        "recent_completed_predictions": [],
        "walk_forward": {"available": False, "windows": {}, "selector": {"available": False}},
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
            # NOTE: rf_accuracy is from an offline holdout; live_accuracy is
            # from real tracked predictions.  Report them side-by-side but
            # do NOT frame one as "beating" the other — they are different
            # evaluation populations.
            insights.append(
                f"Offline ML holdout accuracy: {rf_accuracy:.1f}%.  "
                f"Live tracked hit rate: {live_accuracy:.1f}% (different evaluation populations)."
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
    """Build the view model for the Strategy Lab page.

    Data-source contract — NEVER mix these two numbers:
    ┌──────────────────────┬──────────────────────────────────────────────────┐
    │ offline_accuracy     │ Holdout / backtest accuracy from model_comparison │
    │                      │ .json or walk_forward_report.json.  These rows    │
    │                      │ were never seen during training.                  │
    ├──────────────────────┼──────────────────────────────────────────────────┤
    │ live_hit_rate        │ Hit rate from *real* finalized tracked predictions │
    │ live_sample_size     │ (model_tracker.json, excluding seeded demo data). │
    └──────────────────────┴──────────────────────────────────────────────────┘
    """
    # ── Live tracking (model_tracker) ─────────────────────────────────────────
    # Source: cache/prediction_tracking.json — real predictions graded against
    # actual results.  This is what the model does in production.
    metrics = _safe_metrics(tracker_module.get_summary_metrics())
    completed_predictions = tracker_module.get_completed_predictions(limit=6)
    avoid_impact_predictions = tracker_module.get_completed_predictions(limit=50)

    # live_hit_rate and live_sample_size are the authoritative live numbers.
    live_hit_rate: float | None = metrics.get("overall_accuracy")
    live_sample_size: int = int(metrics.get("finalized_predictions") or 0)

    sport_rows = _format_breakdown_rows(
        metrics.get("by_sport") or {},
        ["soccer", "nba"],
        labels=_SPORT_LABELS,
    )
    confidence_rows = _format_breakdown_rows(
        metrics.get("by_confidence") or {},
        ["High", "Medium", "Low"],
    )

    # ── Offline evaluation (holdout / backtest) ────────────────────────────────
    # Source: cache/ml/model_comparison.json written by generate_ml_report.py /
    # daily_refresh.py.  Accuracy figures here come from a chronological holdout
    # split that was never seen during training — they are NOT live predictions.
    _ensure_ml_report_exists(ml_module)
    comparison = _performance_comparison(metrics)
    ml_summary = ml_module.build_strategy_lab_summary()

    # offline_accuracy: best available holdout figure (combined signal > ensemble > None)
    offline_accuracy: float | None = (
        comparison.get("combined_accuracy")
        or (ml_summary.get("ensemble_accuracy") if ml_summary.get("available") else None)
    )

    pending_count = max(
        int(metrics.get("total_predictions") or 0) - live_sample_size,
        0,
    )
    best_sport = _best_row(sport_rows)
    best_confidence = _best_row(confidence_rows)

    return {
        "metrics": metrics,
        # ── Explicit source-labelled accuracy fields ──────────────────────────
        # Use these in templates instead of deriving from nested dicts.
        "live_hit_rate": live_hit_rate,
        "live_sample_size": live_sample_size,
        "offline_accuracy": offline_accuracy,
        # ─────────────────────────────────────────────────────────────────────
        "hero_cards": _hero_cards(metrics, completed_predictions),
        "backtest_summary": {
            "overall_accuracy_display": _display_accuracy(live_hit_rate),
            "finalized_predictions": live_sample_size,
            "pending_predictions": pending_count,
            "best_sport": best_sport,
            "best_confidence": best_confidence,
            "blurb": (
                "Live hit rate comes from real tracked + graded predictions. "
                "Offline accuracy comes from a held-out evaluation set that was "
                "never seen during training. These two numbers measure different "
                "things and must not be averaged."
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
        "walk_forward": walk_forward_summary(),
    }
