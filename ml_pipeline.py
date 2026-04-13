"""Leakage-safe ML comparison utilities for match outcome modeling."""

from __future__ import annotations

import math
from typing import Any

from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from utils.parsing import normalize_date, safe_float


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
