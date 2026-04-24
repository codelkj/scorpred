from __future__ import annotations

from typing import Any


def compute_trust_score(
    *,
    calibration_score: float | None,
    recent_accuracy: float | None,
    average_data_quality: float | None,
    sample_size: int,
) -> dict[str, Any]:
    if sample_size < 5:
        return {
            "trust_score": None,
            "label": "Insufficient Data",
            "sample_size": sample_size,
        }

    cal = float(calibration_score or 0.0)
    acc = float(recent_accuracy or 0.0)
    dq = float(average_data_quality or 0.0) / 100.0
    sample_size_score = min(1.0, sample_size / 40.0)

    trust_score = (cal * 0.35 + acc * 0.30 + dq * 0.20 + sample_size_score * 0.15) * 100
    if trust_score >= 85:
        label = "Elite Trust"
    elif trust_score >= 70:
        label = "Strong Trust"
    elif trust_score >= 55:
        label = "Developing Trust"
    else:
        label = "Low Trust"
    return {
        "trust_score": round(trust_score, 1),
        "label": label,
        "sample_size": sample_size,
    }
