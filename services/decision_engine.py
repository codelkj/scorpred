from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any


@dataclass(slots=True)
class DecisionEngine:
    """Centralized intelligence layer that builds canonical match decisions."""
    _log = logging.getLogger(__name__)

    def build_decision(self, match_data: dict[str, Any]) -> dict[str, Any]:
        probabilities = self._extract_probabilities(match_data)
        side = self._pick_side(match_data, probabilities)
        confidence = self._confidence(match_data, probabilities, side)
        confidence = self._apply_feature_feedback(confidence, match_data.get("feature_attribution"))
        model_probability = round(max(0.0, min(1.0, confidence / 100.0)), 4)
        implied = self._implied_probability(match_data, side)
        edge_score = None if implied is None else round(model_probability - implied, 4)
        expected_value = None if edge_score is None else round(edge_score * 100.0, 4)
        data_quality = self._data_quality(match_data)
        risk_score = self._risk_score(confidence, data_quality, probabilities)
        risk_level = self._risk_level(risk_score)
        adaptive = self._adaptive_adjustment(match_data)
        action = self._action(
            confidence,
            edge_score,
            risk_level,
            implied is None,
            data_quality,
            bet_min_confidence=adaptive["bet_min_confidence"],
            consider_min_confidence=adaptive["consider_min_confidence"],
            max_risk_allowed=adaptive["max_risk_allowed"],
        )
        action = self._apply_trust_guard(action, match_data.get("trust_score"))
        drift_status = match_data.get("drift_status") if isinstance(match_data.get("drift_status"), dict) else {}
        original_action = action
        action = self._apply_drift_guard(action, confidence, adaptive)
        if action != original_action and adaptive.get("drift_detected"):
            self._log.info(
                "drift_action_adjustment timestamp=%s severity=%s short_win_rate=%s long_win_rate=%s calibration_change=%s action_adjustment=%s->%s",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                adaptive.get("drift_severity"),
                ((drift_status.get("short_window_metrics") or {}).get("win_rate")),
                ((drift_status.get("long_window_metrics") or {}).get("win_rate")),
                drift_status.get("calibration_change"),
                original_action,
                action,
            )
        decision_grade = self._decision_grade(confidence, risk_score, edge_score, data_quality)
        reasoning = self._reasoning(match_data, side, confidence, data_quality)

        return {
            "side": side,
            "action": action,
            "confidence": confidence,
            "probabilities": probabilities,
            "model_probability": model_probability,
            "implied_probability": implied,
            "edge_score": edge_score,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "expected_value": expected_value,
            "decision_grade": decision_grade,
            "data_quality": data_quality,
            "reasoning": reasoning,
            "adaptive_adjustment": {
                "threshold_shift": adaptive["threshold_shift"],
                "trust_modifier": adaptive["trust_modifier"],
                "calibration_penalty": adaptive["calibration_penalty"],
                "drift_modifier": adaptive["drift_modifier"],
                "drift_detected": adaptive["drift_detected"],
                "drift_severity": adaptive["drift_severity"],
            },
        }

    def _extract_probabilities(self, match_data: dict[str, Any]) -> dict[str, float]:
        raw = match_data.get("probabilities") or match_data.get("win_probabilities") or {}
        home = float(raw.get("home", raw.get("a", 0.0)) or 0.0)
        draw = float(raw.get("draw", 0.0) or 0.0)
        away = float(raw.get("away", raw.get("b", 0.0)) or 0.0)
        total = home + draw + away
        if total <= 0:
            home, draw, away = 34.0, 32.0, 34.0
            total = 100.0
        if abs(total - 100.0) > 0.01:
            scale = 100.0 / total
            home, draw, away = home * scale, draw * scale, away * scale
        return {"home": round(home, 1), "draw": round(draw, 1), "away": round(away, 1)}

    def _pick_side(self, match_data: dict[str, Any], probabilities: dict[str, float]) -> str:
        explicit = str(match_data.get("recommended_side") or match_data.get("side") or "").strip()
        if explicit:
            return explicit
        mapping = {
            "home": match_data.get("home_name") or "Home",
            "draw": "Draw",
            "away": match_data.get("away_name") or "Away",
        }
        key = max(probabilities, key=probabilities.get)
        return str(mapping.get(key) or "Home")

    def _confidence(self, match_data: dict[str, Any], probabilities: dict[str, float], side: str) -> int:
        raw_conf = match_data.get("confidence") or match_data.get("confidence_pct")
        if raw_conf is not None:
            return int(max(0, min(100, round(float(raw_conf)))))
        side_key = "home" if side == match_data.get("home_name") else "away"
        if side.lower() == "draw":
            side_key = "draw"
        return int(max(0, min(100, round(probabilities.get(side_key, max(probabilities.values()))))))

    def _implied_probability(self, match_data: dict[str, Any], side: str) -> float | None:
        odds = match_data.get("odds") or {}
        if not isinstance(odds, dict):
            raw = match_data.get("implied_probability")
            if raw in (None, ""):
                return None
            return max(0.01, min(0.99, float(raw)))
        side_key = "home"
        if side.lower() == "draw":
            side_key = "draw"
        elif side == match_data.get("away_name") or side.lower().startswith("away"):
            side_key = "away"
        odd = odds.get(side_key)
        try:
            odd_f = float(odd)
            if odd_f > 1.0:
                return max(0.01, min(0.99, 1.0 / odd_f))
        except (TypeError, ValueError):
            pass
        raw = match_data.get("implied_probability")
        if raw in (None, ""):
            return None
        return max(0.01, min(0.99, float(raw)))

    def _data_quality(self, match_data: dict[str, Any]) -> int:
        raw = match_data.get("data_quality")
        if isinstance(raw, (int, float)):
            return int(max(0, min(100, round(float(raw)))))
        tier = str((match_data.get("data_completeness") or {}).get("tier") or raw or "partial").lower()
        if "strong" in tier:
            return 85
        if "limited" in tier or "low" in tier:
            return 45
        return 65

    def _risk_score(self, confidence: int, data_quality: int, probabilities: dict[str, float]) -> float:
        spread = max(probabilities.values()) - min(probabilities.values())
        confidence_penalty = max(0.0, (65 - confidence) / 100.0)
        quality_penalty = max(0.0, (70 - data_quality) / 100.0)
        variance_penalty = max(0.0, (15 - spread) / 100.0)
        return round(min(1.0, confidence_penalty + quality_penalty + variance_penalty), 4)

    def _risk_level(self, risk_score: float) -> str:
        if risk_score >= 0.45:
            return "HIGH"
        if risk_score >= 0.2:
            return "MEDIUM"
        return "LOW"

    def _action(
        self,
        confidence: int,
        edge_score: float | None,
        risk_level: str,
        missing_market: bool,
        data_quality: int,
        *,
        bet_min_confidence: int,
        consider_min_confidence: int,
        max_risk_allowed: str,
    ) -> str:
        if self._risk_rank(risk_level) > self._risk_rank(max_risk_allowed):
            return "SKIP"
        if missing_market:
            if confidence >= bet_min_confidence and data_quality >= 70 and risk_level != "HIGH":
                return "BET"
            if confidence >= consider_min_confidence:
                return "CONSIDER"
            return "SKIP"
        if confidence >= bet_min_confidence and (edge_score or 0.0) >= 0.02 and risk_level != "HIGH":
            return "BET"
        if confidence >= consider_min_confidence and (edge_score or 0.0) >= -0.01:
            return "CONSIDER"
        return "SKIP"

    @staticmethod
    def _risk_rank(value: str) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(str(value or "").upper(), 2)

    def _decision_grade(
        self,
        confidence: int,
        risk_score: float,
        edge_score: float | None,
        data_quality: int,
    ) -> str:
        quality = confidence * 0.5 + data_quality * 0.3 + (1 - risk_score) * 100 * 0.2
        if edge_score is not None:
            quality += edge_score * 100 * 0.2
        if quality >= 82:
            return "A"
        if quality >= 72:
            return "B"
        if quality >= 60:
            return "C"
        return "D"

    @staticmethod
    def _apply_trust_guard(action: str, trust_score: Any) -> str:
        if trust_score is None:
            return action
        try:
            value = float(trust_score)
        except (TypeError, ValueError):
            return action
        if value >= 55:
            return action
        if action == "BET":
            return "CONSIDER"
        if action == "CONSIDER":
            return "SKIP"
        return action

    def _adaptive_adjustment(self, match_data: dict[str, Any]) -> dict[str, Any]:
        trust = self._coerce_float(match_data.get("trust_score"))
        calibration_score = self._coerce_float(match_data.get("calibration_score"))
        calibration_error = self._coerce_float(match_data.get("calibration_error"))
        drift_status = match_data.get("drift_status") if isinstance(match_data.get("drift_status"), dict) else {}
        thresholds = match_data.get("adaptive_thresholds") or {}
        base_bet = int(round(self._coerce_float(thresholds.get("bet_min_confidence"), 64)))
        base_consider = int(round(self._coerce_float(thresholds.get("consider_min_confidence"), 54)))
        max_risk = str(thresholds.get("max_risk_allowed") or "MEDIUM").upper()

        trust_modifier = 0
        if trust is not None:
            if trust < 55:
                trust_modifier = 4
            elif trust > 75:
                trust_modifier = -2

        calibration_penalty = 0
        if calibration_error is not None and calibration_error > 12:
            calibration_penalty = 3
        elif calibration_score is not None and calibration_score < 65:
            calibration_penalty = 2

        shift = trust_modifier + calibration_penalty
        bet = max(60, min(85, base_bet + shift))
        consider = max(50, min(75, base_consider + max(0, shift // 2)))
        if shift >= 4:
            max_risk = "LOW"
        elif shift >= 2 and max_risk == "HIGH":
            max_risk = "MEDIUM"

        drift_modifier = 0
        drift_detected = bool(drift_status.get("drift_detected"))
        drift_severity = str(drift_status.get("severity") or "LOW").upper()
        if drift_detected:
            drift_modifier = {"LOW": 2, "MEDIUM": 4, "HIGH": 6}.get(drift_severity, 2)
            bet = max(60, min(85, bet + drift_modifier))
            consider = max(50, min(75, consider + max(1, drift_modifier // 2)))
            if drift_severity in {"MEDIUM", "HIGH"}:
                max_risk = "LOW"
            elif max_risk == "HIGH":
                max_risk = "MEDIUM"

        return {
            "bet_min_confidence": bet,
            "consider_min_confidence": consider,
            "max_risk_allowed": max_risk,
            "threshold_shift": shift + drift_modifier,
            "trust_modifier": trust_modifier,
            "calibration_penalty": calibration_penalty,
            "drift_modifier": drift_modifier,
            "drift_detected": drift_detected,
            "drift_severity": drift_severity,
        }

    @staticmethod
    def _coerce_float(value: Any, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _apply_feature_feedback(self, confidence: int, attribution: Any) -> int:
        if not isinstance(attribution, dict) or not attribution:
            return confidence
        weighted = 0.0
        considered = 0
        for feature, payload in attribution.items():
            if not isinstance(payload, dict):
                continue
            sample_size = int(payload.get("sample_size") or 0)
            if sample_size < 8:
                continue
            impact = self._coerce_float(payload.get("impact"), 0.0) or 0.0
            weighted += impact
            considered += 1
            if considered >= 4:
                break
        if considered == 0:
            return confidence
        adjustment = max(-3.0, min(3.0, (weighted / considered) * 10))
        for feature, payload in list(attribution.items())[:4]:
            if not isinstance(payload, dict):
                continue
            self._log.info(
                "feature_adjustment feature=%s impact=%s sample_size=%s applied_adjustment=%s",
                feature,
                payload.get("impact"),
                payload.get("sample_size"),
                round(adjustment, 3),
            )
        return int(max(0, min(100, round(confidence + adjustment))))

    def _reasoning(self, match_data: dict[str, Any], side: str, confidence: int, data_quality: int) -> dict[str, list[str]]:
        strengths = []
        risks = []

        for item in (match_data.get("strengths") or []):
            text = str(item).strip()
            if text:
                strengths.append(text)
        for item in (match_data.get("risks") or []):
            text = str(item).strip()
            if text:
                risks.append(text)

        if not strengths:
            strengths = [
                f"Model probabilities favor {side}",
                f"Confidence signal is {confidence}%",
            ]
        if not risks:
            risks = [
                "Line movement can reduce edge before kickoff",
                "Late squad news may change expected outcome",
            ]

        if data_quality < 55:
            risks.append("Data quality is limited for this fixture")

        return {
            "strengths": strengths[:3],
            "risks": risks[:3],
        }

    @staticmethod
    def _apply_drift_guard(action: str, confidence: int, adaptive: dict[str, Any]) -> str:
        if not adaptive.get("drift_detected"):
            return action
        severity = str(adaptive.get("drift_severity") or "LOW").upper()
        bet_min = int(adaptive.get("bet_min_confidence") or 64)
        if action == "BET":
            if severity == "HIGH" and confidence < min(100, bet_min + 6):
                return "SKIP"
            return "CONSIDER"
        if action == "CONSIDER":
            if severity == "HIGH":
                return "SKIP"
            return "CONSIDER"
        return action
