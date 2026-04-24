from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_BUCKETS: list[tuple[int, int, str]] = [
    (50, 60, "50-60"),
    (60, 70, "60-70"),
    (70, 80, "70-80"),
    (80, 90, "80-90"),
    (90, 101, "90-100"),
]


@dataclass(slots=True)
class CalibrationEngine:
    min_samples: int = 20

    def build_snapshot(self, decision: dict[str, Any]) -> dict[str, Any]:
        probs = decision.get("probabilities") or {}
        return {
            "match_id": str(decision.get("match_id") or ""),
            "predicted_side": decision.get("recommended_side") or decision.get("side"),
            "confidence": int(round(float(decision.get("confidence") or 50))),
            "probabilities": {
                "home": probs.get("home"),
                "draw": probs.get("draw"),
                "away": probs.get("away"),
            },
            "edge_score": decision.get("edge_score"),
            "expected_value": decision.get("expected_value"),
            "data_quality": decision.get("data_quality"),
            "timestamp": decision.get("tracked_at"),
        }

    def evaluate_completed(self, row: dict[str, Any]) -> dict[str, Any]:
        confidence = int(round(float(row.get("confidence") or 50)))
        return {
            "actual_result": row.get("actual_result"),
            "is_correct": row.get("is_correct"),
            "confidence_bucket": self._bucket_for(confidence),
        }

    def get_model_metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        total_predictions = len(rows)
        completed = [r for r in rows if str(r.get("status") or "").lower() == "completed" and r.get("is_correct") is not None]
        completed_predictions = len(completed)
        wins = sum(1 for r in completed if r.get("is_correct") is True)
        win_rate = (wins / completed_predictions * 100.0) if completed_predictions else None

        buckets: dict[str, dict[str, float | int | None]] = {label: {"sample_size": 0, "predicted": None, "actual": None, "error": None} for *_rng, label in _BUCKETS}
        errors = []
        for low, high, label in _BUCKETS:
            members = [r for r in completed if low <= int(round(float(r.get("confidence") or 0))) < high]
            if not members:
                continue
            predicted = sum(float(r.get("confidence") or 0) for r in members) / len(members)
            actual = sum(1 for r in members if r.get("is_correct") is True) / len(members) * 100.0
            err = abs(predicted - actual)
            errors.append(err)
            buckets[label] = {
                "sample_size": len(members),
                "predicted": round(predicted, 2),
                "actual": round(actual, 2),
                "error": round(err, 2),
            }

        if completed_predictions < self.min_samples or not errors:
            calibration_score: float | str = "insufficient data"
            trust_score = self._trust_score(None, win_rate, completed_predictions)
        else:
            mae = sum(errors) / len(errors)
            calibration_score = round(max(0.0, 100.0 - mae), 2)
            trust_score = self._trust_score(calibration_score, win_rate, completed_predictions)

        return {
            "total_predictions": total_predictions,
            "completed_predictions": completed_predictions,
            "win_rate": round(win_rate, 2) if win_rate is not None else None,
            "calibration_score": calibration_score,
            "trust_score": trust_score,
            "bucket_breakdown": buckets,
        }

    def _bucket_for(self, confidence: int) -> str:
        for low, high, label in _BUCKETS:
            if low <= confidence < high:
                return label
        return "90-100"

    @staticmethod
    def _trust_score(calibration_score: float | None, win_rate: float | None, sample_size: int) -> float:
        cal = float(calibration_score or 0.0)
        wr = float(win_rate or 0.0)
        sample_component = min(100.0, (sample_size / 100.0) * 100.0)
        return round(cal * 0.50 + wr * 0.30 + sample_component * 0.20, 2)
