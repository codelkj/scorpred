"""Generate and save a model comparison report for Strategy Lab."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import ml_pipeline as mlp
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import ml_service
from runtime_paths import clean_soccer_dataset_path, clean_soccer_model_path
from train_model import FEATURE_COLUMNS
from utils.parsing import safe_float


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "matches", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    raise ValueError("Input JSON must be a list of rows or a dict containing 'rows', 'matches', or 'data'.")


def _feature_keys(text: str) -> list[str]:
    keys = [item.strip() for item in str(text or "").split(",") if item.strip()]
    if not keys:
        raise ValueError("At least one feature key is required.")
    return keys


def _clean_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _matrix(rows: list[dict[str, Any]], feature_keys: list[str]) -> list[list[float]]:
    return [[safe_float(row.get(feature), math.nan) for feature in feature_keys] for row in rows]


def _targets(rows: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for row in rows:
        raw = row.get("target")
        if raw is None:
            raise ValueError("Clean dataset row missing 'target' field.")
        values.append(int(raw))
    return values


def _top_rf_features(model: Any, feature_keys: list[str], limit: int = 5) -> list[dict[str, Any]]:
    if not hasattr(model, "feature_importances_"):
        return []
    ranked = sorted(
        zip(feature_keys, model.feature_importances_, strict=False),
        key=lambda item: float(item[1]),
        reverse=True,
    )
    return [
        {"feature": feature, "importance": round(float(weight), 4)}
        for feature, weight in ranked[:limit]
    ]


def _top_logistic_features(model: Any, feature_keys: list[str], limit: int = 5) -> list[dict[str, Any]]:
    if not hasattr(model, "coef_"):
        return []
    coef = model.coef_
    if not len(coef):
        return []
    ranked: list[tuple[str, float]] = []
    for idx, feature in enumerate(feature_keys):
        max_abs = max(abs(float(row[idx])) for row in coef)
        ranked.append((feature, max_abs))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [
        {"feature": feature, "weight": round(weight, 4), "direction": "mixed"}
        for feature, weight in ranked[:limit]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a saved logistic regression vs Random Forest comparison report.",
    )
    parser.add_argument("--input", required=True, help="Path to the dataset (.csv or .json).")
    parser.add_argument(
        "--features",
        required=True,
        help="Comma-separated feature keys present in each row.",
    )
    parser.add_argument("--label", default="label", help="Binary label field name.")
    parser.add_argument("--date-key", default="date", help="Chronological date field.")
    parser.add_argument("--test-ratio", type=float, default=0.25, help="Fraction reserved for the chronological test window.")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed for the model suite.")
    parser.add_argument(
        "--output",
        default=str(mlp.DEFAULT_REPORT_PATH),
        help="Output path for the saved comparison report.",
    )
    return parser


def generate_report(
    input_path: Path,
    features: str,
    label: str = "label",
    date_key: str = "date",
    test_ratio: float = 0.25,
    random_state: int = 42,
    output: str | Path = mlp.DEFAULT_REPORT_PATH,
) -> Path:
    rows = _load_rows(input_path)
    report = mlp.compare_binary_models(
        rows,
        feature_keys=_feature_keys(features),
        label_key=label,
        date_key=date_key,
        test_ratio=test_ratio,
        random_state=random_state,
    )
    return mlp.save_comparison_report(report, output)


def generate_clean_soccer_report(
    dataset_path: Path | None = None,
    model_path: Path | None = None,
    output: str | Path = mlp.DEFAULT_REPORT_PATH,
    random_state: int = 42,
) -> Path:
    """Generate Strategy Lab report from the current clean soccer ML assets."""
    dataset = Path(dataset_path or clean_soccer_dataset_path())
    model_file = Path(model_path or clean_soccer_model_path())

    if not dataset.exists():
        raise FileNotFoundError(f"Clean dataset not found: {dataset}")
    if not model_file.exists():
        raise FileNotFoundError(f"Clean model not found: {model_file}")

    rows = _clean_rows(dataset)
    if len(rows) < 20:
        raise ValueError(f"Need at least 20 rows for evaluation, found {len(rows)}")

    n_test = max(1, int(len(rows) * 0.2))
    train_rows = rows[:-n_test]
    test_rows = rows[-n_test:]

    x_train = _matrix(train_rows, FEATURE_COLUMNS)
    y_train = _targets(train_rows)
    x_test = _matrix(test_rows, FEATURE_COLUMNS)
    y_test = _targets(test_rows)

    logistic = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=1500,
                    random_state=random_state,
                ),
            ),
        ]
    )
    logistic.fit(x_train, y_train)
    log_model = logistic.named_steps["model"]
    logistic_predictions = logistic.predict(x_test)
    logistic_accuracy = float(accuracy_score(y_test, logistic_predictions))

    bundle = ml_service.load_model(model_path=model_file, force_reload=True)
    if not bundle or bundle.get("model") is None:
        raise ValueError("Unable to load trained Random Forest bundle for report generation.")

    rf_model = bundle["model"]
    rf_predictions = rf_model.predict(x_test)
    rf_probabilities = rf_model.predict_proba(x_test)
    rf_accuracy = float(accuracy_score(y_test, rf_predictions))

    rule_predictions = [ml_service._rule_prediction_from_features(features) for features in x_test]
    rule_probabilities = [ml_service._rule_probabilities(features) for features in x_test]
    combined_predictions: list[int] = []
    for idx, probs in enumerate(rf_probabilities):
        combined = ml_service._combine_probabilities(rule_probabilities[idx], [float(p) for p in probs])
        combined_predictions.append(int(max(range(3), key=lambda class_idx: combined[class_idx])))

    rule_accuracy = float(accuracy_score(y_test, rule_predictions))
    combined_accuracy = float(accuracy_score(y_test, combined_predictions))

    report = {
        "best_model": "random_forest" if rf_accuracy >= logistic_accuracy else "logistic_regression",
        "ranking": [
            {
                "model": "random_forest",
                "accuracy": round(rf_accuracy, 4),
                "top_features": _top_rf_features(rf_model, FEATURE_COLUMNS),
            },
            {
                "model": "logistic_regression",
                "accuracy": round(logistic_accuracy, 4),
                "top_features": _top_logistic_features(log_model, FEATURE_COLUMNS),
            },
        ],
        "models": {
            "logistic_regression": {
                "accuracy": round(logistic_accuracy, 4),
                "top_features": _top_logistic_features(log_model, FEATURE_COLUMNS),
            },
            "random_forest": {
                "accuracy": round(rf_accuracy, 4),
                "top_features": _top_rf_features(rf_model, FEATURE_COLUMNS),
            },
        },
        "workflow": {
            "chronological_split": True,
            "train_size": len(train_rows),
            "test_size": len(test_rows),
            "train_start": train_rows[0].get("date") if train_rows else None,
            "train_end": train_rows[-1].get("date") if train_rows else None,
            "test_start": test_rows[0].get("date") if test_rows else None,
            "test_end": test_rows[-1].get("date") if test_rows else None,
            "feature_keys": list(FEATURE_COLUMNS),
            "label_key": "target",
            "dataset_path": str(dataset),
            "model_path": str(model_file),
        },
        "performance": {
            "rule_accuracy": round(rule_accuracy, 4),
            "ml_accuracy": round(rf_accuracy, 4),
            "combined_accuracy": round(combined_accuracy, 4),
            "evaluation_matches": len(test_rows),
        },
    }

    return mlp.save_comparison_report(report, output)


def main() -> int:
    args = build_parser().parse_args()
    output_path = generate_report(
        input_path=Path(args.input),
        features=args.features,
        label=args.label,
        date_key=args.date_key,
        test_ratio=args.test_ratio,
        random_state=args.random_state,
        output=args.output,
    )
    print(f"Saved ML comparison report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
