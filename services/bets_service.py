from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from db_models import Bet, db
from sqlalchemy.exc import SQLAlchemyError


class BetValidationError(ValueError):
    """Raised when an incoming bet payload is invalid."""


IDEMPOTENCY_WINDOW_SECONDS = 30


def create_bet(data: dict[str, Any]) -> dict[str, Any]:
    payload = data or {}
    matchup = str(payload.get("matchup") or "").strip()
    recommended_side = str(payload.get("recommended_side") or "").strip()
    action = str(payload.get("action") or "").strip().upper()
    if not matchup:
        raise BetValidationError("matchup is required")
    if not recommended_side:
        raise BetValidationError("recommended_side is required")
    if action not in {"BET", "CONSIDER", "SKIP"}:
        raise BetValidationError("action must be BET, CONSIDER, or SKIP")

    confidence = payload.get("confidence")
    parsed_confidence: float | None = None
    if confidence not in (None, ""):
        try:
            parsed_confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise BetValidationError("confidence must be numeric") from exc

    dedupe_key = _idempotency_key(match_id=str(payload.get("match_id") or ""), matchup=matchup, side=recommended_side, action=action)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)
    existing = (
        Bet.query.filter(Bet.idempotency_key == dedupe_key, Bet.created_at >= cutoff)
        .order_by(Bet.created_at.desc())
        .first()
    )
    if existing:
        raise BetValidationError("duplicate bet blocked (idempotency window)")

    record = Bet(
        match_id=str(payload.get("match_id") or ""),
        matchup=matchup,
        recommended_side=recommended_side,
        action=action,
        confidence=parsed_confidence,
        probabilities_json=json.dumps(payload.get("probabilities") or {}),
        data_quality=payload.get("data_quality"),
        idempotency_key=dedupe_key,
    )
    db.session.add(record)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise BetValidationError("unable to persist bet") from exc
    return _to_dict(record)


def list_bets() -> list[dict[str, Any]]:
    rows = Bet.query.order_by(Bet.created_at.desc()).all()
    return [_to_dict(row) for row in rows]


def delete_bet(bet_id: int) -> bool:
    row = Bet.query.filter_by(id=bet_id).first()
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def clear_bets() -> None:
    try:
        Bet.query.delete()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise


def _idempotency_key(*, match_id: str, matchup: str, side: str, action: str) -> str:
    raw = f"{match_id}|{matchup}|{side}|{action}".lower().encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _to_dict(row: Bet) -> dict[str, Any]:
    probs = {}
    if row.probabilities_json:
        try:
            probs = json.loads(row.probabilities_json)
        except json.JSONDecodeError:
            probs = {}
    return {
        "id": row.id,
        "match_id": row.match_id,
        "matchup": row.matchup,
        "recommended_side": row.recommended_side,
        "action": row.action,
        "confidence": row.confidence,
        "probabilities": probs,
        "data_quality": row.data_quality,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
