from __future__ import annotations

from typing import Any

_BUCKETS = [
    (0, 40, "0-39"),
    (40, 60, "40-59"),
    (60, 80, "60-79"),
    (80, 101, "80-100"),
]


def get_calibration(evaluated_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in evaluated_rows if str(r.get("status") or "").lower() == "completed"]
    rows = [r for r in rows if r.get("is_correct") is not None and str(r.get("overall_result") or "").lower() != "push"]
    if len(rows) < 2:
        return {"rows": [], "calibration_error": None, "calibration_score": None, "sample_size": len(rows)}

    bucket_rows: list[dict[str, Any]] = []
    total_error = 0.0
    total_samples = 0
    for low, high, label in _BUCKETS:
        members = [r for r in rows if low <= float(r.get("confidence", 0)) < high]
        if not members:
            continue
        avg_conf = sum(float(r.get("confidence", 0)) for r in members) / len(members)
        actual = sum(1 for r in members if r.get("is_correct") is True) / len(members) * 100
        error = abs(avg_conf - actual)
        total_error += error * len(members)
        total_samples += len(members)
        bucket_rows.append(
            {
                "bucket": label,
                "sample_size": len(members),
                "avg_confidence": round(avg_conf, 1),
                "actual_win_rate": round(actual, 1),
                "error": round(error, 1),
            }
        )

    if total_samples == 0:
        return {"rows": [], "calibration_error": None, "calibration_score": None, "sample_size": 0}

    calibration_error = total_error / total_samples
    calibration_score = max(0.0, min(1.0, 1.0 - calibration_error / 100.0))
    return {
        "rows": bucket_rows,
        "calibration_error": round(calibration_error, 2),
        "calibration_score": round(calibration_score, 4),
        "sample_size": total_samples,
    }
