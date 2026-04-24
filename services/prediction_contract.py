from __future__ import annotations

from typing import Any
import logging


REQUIRED_ANALYSIS_FIELDS = (
    "match_id",
    "action",
    "recommended_side",
    "confidence",
    "probabilities",
    "reason",
    "data_quality",
    "metric_breakdown",
)

FORBIDDEN_CONFIDENCE_DEFAULTS = {53}
FORBIDDEN_PROBABILITY_PATTERNS = [
    {"a": 38, "draw": 26, "b": 36},
    {"home": 38, "draw": 26, "away": 36},
]

_logger = logging.getLogger(__name__)


def validate_analysis_contract(analysis: dict[str, Any] | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(analysis, dict):
        return ["analysis must be a dict"]

    for field in REQUIRED_ANALYSIS_FIELDS:
        if field not in analysis:
            errors.append(f"missing required field: {field}")

    confidence = analysis.get("confidence")
    if not isinstance(confidence, (int, float)):
        errors.append("confidence must be numeric")
    elif confidence in FORBIDDEN_CONFIDENCE_DEFAULTS:
        errors.append(f"forbidden confidence default detected: {confidence}")

    probs = analysis.get("probabilities")
    if not isinstance(probs, dict):
        errors.append("probabilities must be a dict")
    else:
        keys = set(probs.keys())
        if keys not in ({"a", "draw", "b"}, {"home", "draw", "away"}):
            errors.append("probabilities keys must be either {a,draw,b} or {home,draw,away}")
        if probs in FORBIDDEN_PROBABILITY_PATTERNS:
            errors.append("forbidden probability fallback pattern detected")

    metric_breakdown = analysis.get("metric_breakdown")
    if metric_breakdown not in (None, "Unavailable"):
        if _looks_fake_5050(metric_breakdown):
            errors.append("metric_breakdown appears to use forbidden fake 50/50 defaults")

    return errors


def validate_analysis(analysis: dict[str, Any] | None) -> dict[str, Any]:
    errors = validate_analysis_contract(analysis)
    if errors:
        message = "; ".join(errors)
        _logger.error("invalid_analysis_contract: %s", message, extra={"errors": errors})
        raise ValueError(message)
    return analysis


def _looks_fake_5050(metric_breakdown: Any) -> bool:
    if not isinstance(metric_breakdown, dict):
        return False
    values: list[tuple[float, float]] = []
    for metric in metric_breakdown.values():
        if not isinstance(metric, dict):
            continue
        home = metric.get("home") if "home" in metric else metric.get("a")
        away = metric.get("away") if "away" in metric else metric.get("b")
        if isinstance(home, (int, float)) and isinstance(away, (int, float)):
            values.append((float(home), float(away)))
    if not values:
        return False
    return all(home == 50.0 and away == 50.0 for home, away in values)
