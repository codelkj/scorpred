from __future__ import annotations

from typing import Any


class ValidationError(ValueError):
    """Raised when request payload validation fails."""


def validate_bet_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    match_id = str(data.get("match_id") or "").strip()
    recommended_side = str(data.get("recommended_side") or "").strip()
    action = str(data.get("action") or "").strip().upper()

    if not match_id:
        raise ValidationError("match_id is required")
    if not recommended_side:
        raise ValidationError("recommended_side is required")
    if action not in {"BET", "CONSIDER", "SKIP"}:
        raise ValidationError("action must be BET, CONSIDER, or SKIP")

    confidence_raw = data.get("confidence")
    if confidence_raw in (None, ""):
        raise ValidationError("confidence is required")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError("confidence must be numeric") from exc
    if confidence < 0 or confidence > 100:
        raise ValidationError("confidence must be between 0 and 100")

    data["match_id"] = match_id
    data["recommended_side"] = recommended_side
    data["action"] = action
    data["confidence"] = confidence
    return data
