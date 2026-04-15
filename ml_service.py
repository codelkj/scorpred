"""Runtime ML inference and evaluation helpers for ScorPred."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import joblib
from sklearn.metrics import accuracy_score

from runtime_paths import clean_soccer_dataset_path, clean_soccer_model_path, trained_model_path
from train_model import CLASS_LABELS, FEATURE_COLUMNS, _target_from_row
from utils.parsing import safe_float


_MODEL_CACHE: dict[str, Any] = {"bundle": None, "path": None}
_FEATURE_INDEX = {name: idx for idx, name in enumerate(FEATURE_COLUMNS)}


def _default_probabilities() -> list[float]:
    return [0.3333, 0.3333, 0.3334]


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _row_to_features(row: dict[str, Any]) -> list[float]:
    return [safe_float(row.get(feature), 0.0) for feature in FEATURE_COLUMNS]


def _features_dict_to_vector(features_dict: dict[str, Any]) -> list[float]:
    return [safe_float(features_dict.get(feature), 0.0) for feature in FEATURE_COLUMNS]


def _feature_value(features: list[float], name: str, default: float = 0.0) -> float:
    idx = _FEATURE_INDEX.get(name)
    if idx is None or idx >= len(features):
        return default
    return float(features[idx])


def _rule_prediction_from_features(features: list[float]) -> int:
    side_edge = (
        0.34 * _feature_value(features, "ppg_diff_5")
        + 0.15 * _feature_value(features, "gf_diff_5")
        + 0.15 * _feature_value(features, "ga_diff_5")
        + 0.18 * _feature_value(features, "attack_balance_diff")
        + 0.10 * _feature_value(features, "venue_ppg_diff_5")
        + 0.08 * _feature_value(features, "scored_rate_diff_5")
        + 0.06 * _feature_value(features, "clean_sheet_diff_5")
        + 0.015 * _feature_value(features, "rest_diff_days")
        + 0.0022 * _feature_value(features, "elo_diff")
    )
    draw_pressure = max(
        0.0,
        0.24
        - abs(side_edge) * 0.65
        - abs(_feature_value(features, "gf_diff_5")) * 0.10
        - abs(_feature_value(features, "attack_balance_diff")) * 0.12,
    )
    if draw_pressure >= 0.16:
        return 1
    if side_edge > 0:
        return 0
    return 2


def _rule_probabilities(features: list[float]) -> list[float]:
    pred = _rule_prediction_from_features(features)
    side_edge = abs(
        0.34 * _feature_value(features, "ppg_diff_5")
        + 0.15 * _feature_value(features, "gf_diff_5")
        + 0.15 * _feature_value(features, "ga_diff_5")
        + 0.18 * _feature_value(features, "attack_balance_diff")
        + 0.10 * _feature_value(features, "venue_ppg_diff_5")
        + 0.0022 * _feature_value(features, "elo_diff")
    )
    if pred == 1:
        draw_prob = min(0.44, max(0.31, 0.36 - side_edge * 0.10))
        side_prob = (1.0 - draw_prob) / 2.0
        return [round(side_prob, 6), round(draw_prob, 6), round(side_prob, 6)]
    if pred == 0:
        home_prob = min(0.74, max(0.49, 0.55 + side_edge * 0.18))
        draw_prob = min(0.24, max(0.10, 0.22 - side_edge * 0.08))
        away_prob = max(0.06, 1.0 - home_prob - draw_prob)
        return [round(home_prob, 6), round(draw_prob, 6), round(away_prob, 6)]
    away_prob = min(0.74, max(0.49, 0.55 + side_edge * 0.18))
    draw_prob = min(0.24, max(0.10, 0.22 - side_edge * 0.08))
    home_prob = max(0.06, 1.0 - away_prob - draw_prob)
    return [round(home_prob, 6), round(draw_prob, 6), round(away_prob, 6)]


def _combine_probabilities(rule_probs: list[float], ml_probs: list[float]) -> list[float]:
    combined = [0.42 * rule_probs[idx] + 0.58 * ml_probs[idx] for idx in range(3)]
    if len(combined) == 3:
        draw_prob = combined[1]
        side_top = max(combined[0], combined[2])
        side_gap = abs(combined[0] - combined[2])
        rule_side_top = max(rule_probs[0], rule_probs[2]) if len(rule_probs) == 3 else side_top
        if draw_prob > 0.0 and rule_side_top >= rule_probs[1]:
            draw_transfer = min(
                draw_prob * 0.26,
                max(0.0, (side_top - draw_prob + 0.02) * 0.50 + max(0.0, side_gap - 0.04) * 0.40),
            )
            if draw_transfer > 0.0:
                side_total = max(combined[0] + combined[2], 1e-9)
                combined[1] -= draw_transfer
                combined[0] += draw_transfer * (combined[0] / side_total)
                combined[2] += draw_transfer * (combined[2] / side_total)

    total = sum(combined) or 1.0
    return [round(prob / total, 6) for prob in combined]


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.72:
        return "High"
    if confidence >= 0.57:
        return "Medium"
    return "Low"


def model_exists(model_path: Path | None = None) -> bool:
    return (model_path or clean_soccer_model_path()).exists()


def load_model(model_path: Path | None = None, force_reload: bool = False) -> dict[str, Any] | None:
    path = Path(model_path or clean_soccer_model_path())
    if not path.exists():
        return None

    if not force_reload and _MODEL_CACHE.get("bundle") is not None and _MODEL_CACHE.get("path") == str(path):
        cached = _MODEL_CACHE["bundle"]
        return cached if isinstance(cached, dict) else None

    try:
        bundle = joblib.load(path)
    except Exception:
        return None

    if not isinstance(bundle, dict) or "model" not in bundle:
        return None

    _MODEL_CACHE["bundle"] = bundle
    _MODEL_CACHE["path"] = str(path)
    return bundle


def predict_match(features_dict: dict[str, Any], model_path: Path | None = None) -> dict[str, Any]:
    bundle = load_model(model_path=model_path)
    if not bundle:
        return {
            "available": False,
            "prediction": None,
            "probabilities": _default_probabilities(),
            "confidence": 0.0,
            "error": "Trained model not found. Run train_model.py first.",
        }

    model = bundle.get("model")
    if model is None:
        return {
            "available": False,
            "prediction": None,
            "probabilities": _default_probabilities(),
            "confidence": 0.0,
            "error": "Trained model bundle is invalid.",
        }

    vector = _features_dict_to_vector(features_dict)
    try:
        probabilities_raw = model.predict_proba([vector])[0]
        prediction = int(model.predict([vector])[0])
    except Exception as exc:
        return {
            "available": False,
            "prediction": None,
            "probabilities": _default_probabilities(),
            "confidence": 0.0,
            "error": str(exc),
        }

    probabilities = [round(float(prob), 6) for prob in probabilities_raw]
    confidence = max(probabilities) if probabilities else 0.0
    return {
        "available": True,
        "prediction": prediction,
        "probabilities": probabilities,
        "confidence": round(float(confidence), 6),
        "class_labels": CLASS_LABELS,
    }


def evaluate_model_comparison(
    dataset_path: Path | None = None,
    model_path: Path | None = None,
    test_size: float = 0.25,
    random_state: int = 42,
) -> dict[str, Any]:
    dataset = Path(dataset_path or clean_soccer_dataset_path())
    if not dataset.exists():
        return {
            "available": False,
            "message": f"Dataset not found at {dataset}",
            "rule_accuracy": None,
            "ml_accuracy": None,
            "combined_accuracy": None,
            "evaluation_matches": 0,
        }

    bundle = load_model(model_path=model_path)
    if not bundle:
        return {
            "available": False,
            "message": "Trained model not found. Run train_model.py first.",
            "rule_accuracy": None,
            "ml_accuracy": None,
            "combined_accuracy": None,
            "evaluation_matches": 0,
        }

    model = bundle.get("model")
    rows = _load_rows(dataset)
    x: list[list[float]] = []
    y: list[int] = []
    for row in rows:
        target = _target_from_row(row)
        if target is None:
            continue
        features = _row_to_features(row)
        x.append(features)
        y.append(target)

    if len(x) < 20:
        return {
            "available": False,
            "message": "Not enough rows to evaluate model comparison.",
            "rule_accuracy": None,
            "ml_accuracy": None,
            "combined_accuracy": None,
            "evaluation_matches": len(x),
        }

    # Chronological holdout to match train_model.py and avoid look-ahead leakage.
    n_test = max(1, int(len(x) * test_size))
    x_train, x_test = x[:-n_test], x[-n_test:]
    y_train, y_test = y[:-n_test], y[-n_test:]

    try:
        ml_predictions = model.predict(x_test)
        ml_probabilities = model.predict_proba(x_test)
    except Exception as exc:
        return {
            "available": False,
            "message": f"ML evaluation failed: {exc}",
            "rule_accuracy": None,
            "ml_accuracy": None,
            "combined_accuracy": None,
            "evaluation_matches": len(x_test),
        }

    rule_predictions = [_rule_prediction_from_features(features) for features in x_test]
    rule_probs = [_rule_probabilities(features) for features in x_test]

    combined_predictions: list[int] = []
    for idx, probs in enumerate(ml_probabilities):
        combined = _combine_probabilities(rule_probs[idx], [float(p) for p in probs])
        combined_predictions.append(int(max(range(3), key=lambda class_idx: combined[class_idx])))

    rule_accuracy = float(accuracy_score(y_test, rule_predictions)) * 100.0
    ml_accuracy = float(accuracy_score(y_test, ml_predictions)) * 100.0
    combined_accuracy = float(accuracy_score(y_test, combined_predictions)) * 100.0

    combined_probs: list[list[float]] = [
        _combine_probabilities(rule_probs[idx], [float(p) for p in probs])
        for idx, probs in enumerate(ml_probabilities)
    ]
    top_probs = [max(probs) for probs in combined_probs]
    gaps = [
        sorted(probs, reverse=True)[0] - sorted(probs, reverse=True)[1]
        for probs in combined_probs
    ]
    confidence_counts = {"High": 0, "Medium": 0, "Low": 0}
    for top_prob, gap in zip(top_probs, gaps):
        label = _confidence_label(min(0.95, max(0.05, top_prob * 0.72 + gap * 1.10)))
        confidence_counts[label] += 1
    draw_predictions = sum(1 for pred in combined_predictions if pred == 1)

    return {
        "available": True,
        "message": None,
        "rule_accuracy": round(rule_accuracy, 1),
        "ml_accuracy": round(ml_accuracy, 1),
        "combined_accuracy": round(combined_accuracy, 1),
        "evaluation_matches": len(y_test),
        "train_matches": len(y_train),
        "diagnostics": {
            "draw_rate_pct": round((draw_predictions / len(combined_predictions)) * 100.0, 1) if combined_predictions else 0.0,
            "avg_top_probability_pct": round((sum(top_probs) / len(top_probs)) * 100.0, 1) if top_probs else 0.0,
            "avg_top_two_gap_pct": round((sum(gaps) / len(gaps)) * 100.0, 1) if gaps else 0.0,
            "confidence_distribution": confidence_counts,
        },
    }
