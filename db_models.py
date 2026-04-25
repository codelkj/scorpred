from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    saved_picks = db.Column(db.PickleType, default=list)
    history = db.Column(db.PickleType, default=list)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "created_at": self.created_at.isoformat() + "Z",
            "saved_picks": self.saved_picks or [],
            "history": self.history or [],
        }


class Bet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.String(80), nullable=True, index=True)
    matchup = db.Column(db.String(255), nullable=True)
    recommended_side = db.Column(db.String(120), nullable=True)
    action = db.Column(db.String(40), nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    probabilities_json = db.Column(db.Text, nullable=True)
    data_quality = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    idempotency_key = db.Column(db.String(64), nullable=False, unique=True, index=True)

    __table_args__ = (
        UniqueConstraint("match_id", "idempotency_key", name="uq_bet_match_id_idempotency_key"),
    )
