"""Tests for the leakage-safe ML comparison helpers."""

from __future__ import annotations

from datetime import date, timedelta
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import ml_pipeline as mlp


def _sample_rows(count: int = 24) -> list[dict]:
    rows = []
    start = date(2024, 1, 1)
    for idx in range(count):
        form_gap = (idx % 6) - 2
        xg_gap = round(form_gap * 0.7 + (0.9 if idx % 2 == 0 else -0.4), 2)
        home_edge = 1 if idx % 3 != 1 else 0
        injuries_gap = -1 if idx % 5 == 0 else 0
        label = 1 if (form_gap + xg_gap + home_edge + injuries_gap) > 0.5 else 0
        rows.append(
            {
                "date": (start + timedelta(days=idx)).isoformat(),
                "form_gap": form_gap,
                "xg_gap": xg_gap,
                "home_edge": home_edge,
                "injuries_gap": injuries_gap,
                "label": label,
            }
        )
    return rows


def test_chronological_train_test_split_orders_rows_before_splitting():
    rows = [
        {"date": "2024-02-10", "label": 1},
        {"date": "2024-01-15", "label": 0},
        {"date": "2024-03-05", "label": 1},
        {"date": "2024-01-20", "label": 0},
    ]

    train_rows, test_rows = mlp.chronological_train_test_split(rows, test_ratio=0.25)

    assert [row["date"] for row in train_rows] == ["2024-01-15", "2024-01-20", "2024-02-10"]
    assert [row["date"] for row in test_rows] == ["2024-03-05"]
    assert max(row["date"] for row in train_rows) < min(row["date"] for row in test_rows)


def test_compare_binary_models_reports_both_baselines_and_workflow():
    report = mlp.compare_binary_models(
        _sample_rows(),
        feature_keys=["form_gap", "xg_gap", "home_edge", "injuries_gap"],
        test_ratio=0.25,
    )

    assert report["best_model"] in {"logistic_regression", "random_forest"}
    assert [entry["model"] for entry in report["ranking"]] == ["logistic_regression", "random_forest"] or [
        entry["model"] for entry in report["ranking"]
    ] == ["random_forest", "logistic_regression"]
    assert set(report["models"]) == {"logistic_regression", "random_forest"}
    assert report["workflow"]["chronological_split"] is True
    assert report["workflow"]["train_size"] == 18
    assert report["workflow"]["test_size"] == 6
    assert report["workflow"]["train_end"] < report["workflow"]["test_start"]
    assert report["models"]["logistic_regression"]["top_features"]
    assert report["models"]["random_forest"]["top_features"]


def test_compare_binary_models_rejects_single_class_train_or_test_windows():
    rows = _sample_rows(10)
    for idx, row in enumerate(rows):
        row["label"] = 1 if idx < 9 else 0

    with pytest.raises(ValueError, match="Both train and test windows need both outcome classes"):
        mlp.compare_binary_models(
            rows,
            feature_keys=["form_gap", "xg_gap", "home_edge", "injuries_gap"],
            test_ratio=0.2,
        )
