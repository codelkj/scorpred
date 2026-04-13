"""Leakage-safe ML comparison utilities for match outcome modeling."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path
from typing import Any

from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from utils.parsing import normalize_date, safe_float

DEFAULT_REPORT_PATH = Path(__file__).resolve().parent / "cache" / "ml" / "model_comparison.json"
MODEL_LABELS = {
    "logistic_regression": "Baseline Logistic Regression",
    "random_forest": "Random Forest",
}


def _row_date(row: dict[str, Any], date_key: str) -> str:
    value = normalize_date(row.get(date_key))
    if not value:
        raise ValueError(f"Row is missing a valid '{date_key}' value: {row}")
    return value


def _encode_binary_label(value: Any, label_key: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, float) and value in (0.0, 1.0):
        return int(value)

    text = str(value or "").strip().lower()
    positive = {"1", "true", "win", "won", "home", "a", "yes"}
    negative = {"0", "false", "loss", "lost", "away", "b", "no"}
    if text in positive:
        return 1
    if text in negative:
        return 0
    raise ValueError(f"Unsupported binary label for '{label_key}': {value!r}")


def chronological_train_test_split(
    rows: list[dict[str, Any]],
    date_key: str = "date",
    test_ratio: float = 0.25,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sort rows chronologically and split them without look-ahead leakage."""
    if len(rows) < 2:
        raise ValueError("Need at least 2 rows for a chronological split.")
    if not 0 < test_ratio < 1:
        raise ValueError("test_ratio must be between 0 and 1.")

    ordered = sorted(rows, key=lambda row: _row_date(row, date_key))
    test_size = max(1, min(len(ordered) - 1, math.ceil(len(ordered) * test_ratio)))
    split_index = len(ordered) - test_size
    return ordered[:split_index], ordered[split_index:]


def build_model_suite(random_state: int = 42) -> dict[str, Pipeline]:
    """Return the baseline classifiers used in the comparison report."""
    return {
        "logistic_regression": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000, random_state=random_state)),
            ]
        ),
        "random_forest": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=80,
                        max_depth=6,
                        min_samples_leaf=2,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def _matrix(rows: list[dict[str, Any]], feature_keys: list[str]) -> list[list[float]]:
    return [
        [safe_float(row.get(feature), math.nan) for feature in feature_keys]
        for row in rows
    ]


def _labels(rows: list[dict[str, Any]], label_key: str) -> list[int]:
    return [_encode_binary_label(row.get(label_key), label_key) for row in rows]


def _top_features(model_pipeline: Pipeline, feature_keys: list[str], limit: int = 5) -> list[dict[str, Any]]:
    estimator = model_pipeline.named_steps["model"]
    if hasattr(estimator, "coef_"):
        ranked = sorted(
            zip(feature_keys, estimator.coef_[0], strict=False),
            key=lambda item: abs(float(item[1])),
            reverse=True,
        )
        return [
            {
                "feature": feature,
                "weight": round(float(weight), 4),
                "direction": "positive" if float(weight) >= 0 else "negative",
            }
            for feature, weight in ranked[:limit]
        ]

    if hasattr(estimator, "feature_importances_"):
        ranked = sorted(
            zip(feature_keys, estimator.feature_importances_, strict=False),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        return [
            {"feature": feature, "importance": round(float(weight), 4)}
            for feature, weight in ranked[:limit]
        ]

    return []


def _report_path(path: str | Path | None = None) -> Path:
    return Path(path or DEFAULT_REPORT_PATH)


def _display_accuracy(value: Any) -> float | None:
    numeric = safe_float(value, math.nan)
    if math.isnan(numeric):
        return None
    if 0.0 <= numeric <= 1.0:
        numeric *= 100.0
    return round(float(numeric), 1)


def _model_label(name: str) -> str:
    return MODEL_LABELS.get(name, name.replace("_", " ").title())


def _top_signal_names(entries: Any, limit: int = 5) -> list[str]:
    signals: list[str] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            name = str(entry.get("feature") or entry.get("name") or "").strip()
        else:
            name = str(entry or "").strip()
        if name and name not in signals:
            signals.append(name)
        if len(signals) >= limit:
            break
    return signals


def save_comparison_report(
    report: dict[str, Any],
    path: str | Path | None = None,
) -> Path:
    """Persist a comparison report to disk for UI consumption."""
    target = _report_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(json.dumps(report))
    payload.setdefault("generated_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_comparison_report(path: str | Path | None = None) -> dict[str, Any] | None:
    """Load a saved comparison report if it exists."""
    target = _report_path(path)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_strategy_lab_summary(
    report: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Convert the saved comparison report into a compact, UI-friendly payload for
    Strategy Lab.
    """
    report_path = _report_path(path)
    payload = report if isinstance(report, dict) else load_comparison_report(report_path)
    fallback_command = (
        f'python generate_ml_report.py --input path\\to\\matches.json '
        f'--features feature_a,feature_b,feature_c --label label --date-key date '
        f'--output "{report_path}"'
    )

    fallback = {
        "available": False,
        "best_model": None,
        "best_model_label": None,
        "baseline_logistic_accuracy": None,
        "random_forest_accuracy": None,
        "accuracy_gap": None,
        "accuracy_gap_display": None,
        "evaluation_matches": None,
        "summary": "ML comparison is not available yet.",
        "message": (
            "Generate the saved ML comparison report to surface the logistic "
            "baseline, Random Forest challenger, and top feature signals here."
        ),
        "command": fallback_command,
        "report_path": str(report_path),
        "top_signals": [],
        "generated_at": None,
        "workflow": {},
    }

    if not payload:
        return fallback

    models = payload.get("models") or {}
    logistic = models.get("logistic_regression") or {}
    random_forest = models.get("random_forest") or {}
    logistic_accuracy = _display_accuracy(logistic.get("accuracy"))
    random_forest_accuracy = _display_accuracy(random_forest.get("accuracy"))
    if logistic_accuracy is None or random_forest_accuracy is None:
        return fallback

    best_model = str(
        payload.get("best_model")
        or (payload.get("ranking") or [{}])[0].get("model")
        or ""
    ).strip()
    if not best_model:
        best_model = (
            "random_forest"
            if random_forest_accuracy >= logistic_accuracy
            else "logistic_regression"
        )

    workflow = payload.get("workflow") or {}
    feature_keys = workflow.get("feature_keys") or []
    gap = round(random_forest_accuracy - logistic_accuracy, 1)
    evaluation_matches = workflow.get("test_size")
    top_signals = _top_signal_names(
        (models.get(best_model) or {}).get("top_features"),
        limit=5,
    )
    leader_label = _model_label(best_model)
    summary = (
        f"{leader_label} leads the saved leakage-safe evaluation by "
        f"{abs(gap):.1f} pts across {evaluation_matches or 0} matches."
    )
    if gap == 0:
        summary = (
            f"Baseline Logistic Regression and Random Forest are tied in the "
            f"saved evaluation across {evaluation_matches or 0} matches."
        )

    return {
        "available": True,
        "best_model": best_model,
        "best_model_label": leader_label,
        "baseline_logistic_accuracy": logistic_accuracy,
        "random_forest_accuracy": random_forest_accuracy,
        "accuracy_gap": gap,
        "accuracy_gap_display": f"{gap:+.1f} pts",
        "evaluation_matches": evaluation_matches,
        "summary": summary,
        "message": None,
        "command": fallback_command,
        "report_path": str(report_path),
        "top_signals": top_signals,
        "generated_at": payload.get("generated_at"),
        "workflow": {
            "train_size": workflow.get("train_size"),
            "test_size": workflow.get("test_size"),
            "train_start": workflow.get("train_start"),
            "train_end": workflow.get("train_end"),
            "test_start": workflow.get("test_start"),
            "test_end": workflow.get("test_end"),
            "feature_count": len(feature_keys),
        },
    }


def compare_binary_models(
    rows: list[dict[str, Any]],
    feature_keys: list[str],
    label_key: str = "label",
    date_key: str = "date",
    test_ratio: float = 0.25,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Train and evaluate logistic regression and random forest models using a
    strictly chronological split to avoid time leakage.
    """
    if len(rows) < 8:
        raise ValueError("Need at least 8 rows to compare ML models meaningfully.")
    if not feature_keys:
        raise ValueError("feature_keys must not be empty.")

    train_rows, test_rows = chronological_train_test_split(rows, date_key=date_key, test_ratio=test_ratio)
    y_train = _labels(train_rows, label_key)
    y_test = _labels(test_rows, label_key)
    if len(set(y_train)) < 2 or len(set(y_test)) < 2:
        raise ValueError("Both train and test windows need both outcome classes for a meaningful comparison.")

    x_train = _matrix(train_rows, feature_keys)
    x_test = _matrix(test_rows, feature_keys)
    models = build_model_suite(random_state=random_state)

    reports: dict[str, Any] = {}
    for name, pipeline in models.items():
        pipeline.fit(x_train, y_train)
        probabilities = pipeline.predict_proba(x_test)[:, 1]
        predictions = [1 if probability >= 0.5 else 0 for probability in probabilities]

        reports[name] = {
            "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
            "log_loss": round(float(log_loss(y_test, probabilities, labels=[0, 1])), 4),
            "brier_score": round(float(brier_score_loss(y_test, probabilities)), 4),
            "positive_rate": round(float(sum(probabilities) / len(probabilities)), 4),
            "top_features": _top_features(pipeline, feature_keys),
        }

    ranking = sorted(
        (
            {"model": name, **metrics}
            for name, metrics in reports.items()
        ),
        key=lambda entry: (entry["log_loss"], -entry["accuracy"], entry["brier_score"]),
    )

    train_dates = [_row_date(row, date_key) for row in train_rows]
    test_dates = [_row_date(row, date_key) for row in test_rows]

    return {
        "best_model": ranking[0]["model"],
        "ranking": ranking,
        "models": reports,
        "workflow": {
            "chronological_split": True,
            "train_size": len(train_rows),
            "test_size": len(test_rows),
            "train_start": min(train_dates),
            "train_end": max(train_dates),
            "test_start": min(test_dates),
            "test_end": max(test_dates),
            "feature_keys": feature_keys,
            "label_key": label_key,
        },
    }
