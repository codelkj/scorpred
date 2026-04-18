"""Shared runtime path helpers for local cache and generated data."""

from __future__ import annotations

import os
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent
_DATA_ROOT_ENV = "SCORPRED_DATA_ROOT"


def repo_root() -> Path:
    return _REPO_ROOT


def data_root() -> Path:
    configured = os.getenv(_DATA_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _REPO_ROOT


def cache_root() -> Path:
    return data_root() / "cache"


def data_dir() -> Path:
    # Keep generated/runtime data under SCORPRED_DATA_ROOT when configured.
    # When SCORPRED_DATA_ROOT is unset, data_root() falls back to repo root so
    # this remains <repo>/data for local development.
    return data_root() / "data"


def cache_dir(*parts: str) -> Path:
    return cache_root().joinpath(*parts)


def prediction_tracking_path() -> Path:
    return cache_root() / "prediction_tracking.json"


def prediction_history_path() -> Path:
    return cache_root() / "prediction_history.json"


def ml_report_path() -> Path:
    return cache_dir("ml") / "model_comparison.json"


def prediction_policy_path() -> Path:
    return cache_dir("ml") / "prediction_policy.json"


def matches_dataset_path() -> Path:
    return data_dir() / "matches.csv"


def historical_dataset_path() -> Path:
    return data_dir() / "historical_matches.csv"


def trained_model_path() -> Path:
    return data_dir() / "model.pkl"


def clean_soccer_dataset_path() -> Path:
    """Clean pre-match feature dataset (no target leakage)."""
    return data_dir() / "processed" / "soccer_training_data_clean.csv"


def clean_soccer_model_path() -> Path:
    """Random Forest trained on clean pre-match features."""
    return data_dir() / "models" / "soccer_random_forest_clean.pkl"


def ensemble_soccer_model_path() -> Path:
    """Stacking ensemble (LR + RF + XGBoost + LightGBM) trained on clean pre-match features."""
    return data_dir() / "models" / "soccer_ensemble_stack.pkl"


def nba_model_path() -> Path:
    """Calibrated Random Forest model for NBA home/away win prediction."""
    return data_dir() / "models" / "nba_random_forest.pkl"


def elo_state_path() -> Path:
    """Final ELO ratings for all teams, saved after training (used at runtime)."""
    return data_dir() / "processed" / "soccer_elo_state.json"


def walk_forward_report_path() -> Path:
    """Walk-forward backtest report JSON."""
    return data_dir() / "backtests" / "walk_forward_report.json"


def mistake_report_path() -> Path:
    """Mistake analysis report JSON."""
    return data_dir() / "analysis" / "mistake_report.json"


def policy_adjustments_path() -> Path:
    """Learned policy adjustments JSON."""
    return data_dir() / "analysis" / "policy_adjustments.json"


def ensure_runtime_dirs() -> None:
    data_root().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    for folder in (
        cache_root(),
        cache_dir("football"),
        cache_dir("props"),
        cache_dir("nba"),
        cache_dir("nba_public"),
        cache_dir("ml"),
        data_dir() / "processed",
        data_dir() / "models",
        data_dir() / "backtests",
        data_dir() / "analysis",
        data_dir() / "logs",
    ):
        folder.mkdir(parents=True, exist_ok=True)
