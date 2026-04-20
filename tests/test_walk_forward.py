"""Tests for walk-forward backtesting module."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import walk_forward_backtest as wf
from walk_forward_backtest import (
    DEFAULT_REPORT_PATH,
    generate_folds,
    load_walk_forward_report,
    _class_distribution,
    _policy_metrics,
    _flat_stake_roi,
)


# ── Fold generation ───────────────────────────────────────────────────────────


class TestGenerateFolds:
    def test_basic_folds(self):
        folds = generate_folds(200, n_folds=5, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        assert len(folds) >= 1
        for f in folds:
            assert f["train_end"] > 0
            assert f["cal_start"] == f["train_end"]
            assert f["test_start"] == f["cal_end"]
            assert f["test_end"] > f["test_start"]

    def test_chronological_order(self):
        """Folds must be strictly chronological — no overlap between train/cal/test."""
        folds = generate_folds(200, n_folds=5, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        for f in folds:
            assert f["train_start"] < f["train_end"]
            assert f["train_end"] <= f["cal_start"]
            assert f["cal_start"] < f["cal_end"]
            assert f["cal_end"] <= f["test_start"]
            assert f["test_start"] < f["test_end"]

    def test_no_overlap_across_folds(self):
        """Test sets across folds should not overlap."""
        folds = generate_folds(200, n_folds=5, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        test_ranges = [(f["test_start"], f["test_end"]) for f in folds]
        for i, (s1, e1) in enumerate(test_ranges):
            for j, (s2, e2) in enumerate(test_ranges):
                if i >= j:
                    continue
                assert e1 <= s2 or e2 <= s1, f"Fold {i+1} and {j+1} test sets overlap"

    def test_expanding_train(self):
        """Train window should expand across folds."""
        folds = generate_folds(200, n_folds=5, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        if len(folds) < 2:
            pytest.skip("Too few folds")
        for i in range(1, len(folds)):
            assert folds[i]["train_end"] >= folds[i - 1]["train_end"]

    def test_minimum_train_respected(self):
        """Must enforce minimum training size."""
        folds = generate_folds(100, n_folds=10, min_train_pct=0.50, test_pct=0.10, cal_pct=0.05)
        min_train = max(20, int(100 * 0.50))
        for f in folds:
            assert f["train_size"] >= min_train

    def test_too_small_dataset(self):
        """Very small dataset should yield zero or very few folds."""
        folds = generate_folds(30, n_folds=5, min_train_pct=0.50, test_pct=0.10, cal_pct=0.05)
        assert len(folds) <= 5

    def test_single_fold(self):
        folds = generate_folds(100, n_folds=1, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        assert len(folds) <= 1

    def test_all_rows_within_bounds(self):
        n = 150
        folds = generate_folds(n, n_folds=4, min_train_pct=0.40, test_pct=0.10, cal_pct=0.05)
        for f in folds:
            assert f["train_start"] >= 0
            assert f["test_end"] <= n


# ── Class distribution ────────────────────────────────────────────────────────


class TestClassDistribution:
    def test_basic(self):
        dist = _class_distribution([0, 0, 1, 2])
        assert dist["HomeWin"] == 50.0
        assert dist["Draw"] == 25.0
        assert dist["AwayWin"] == 25.0

    def test_empty(self):
        dist = _class_distribution([])
        for v in dist.values():
            assert v == 0.0


# ── Policy metrics ────────────────────────────────────────────────────────────


class TestPolicyMetrics:
    @pytest.fixture
    def default_policy(self):
        return {
            "min_confidence_pct": 53.0,
            "min_top_two_gap_pct": 3.0,
            "lean_min_confidence_pct": 51.0,
            "bet_min_confidence_pct": 70.0,
            "draw_min_top_prob_pct": 37.0,
        }

    def test_all_confident_correct(self, default_policy):
        """All predictions with high confidence should get placed."""
        y_true = [0, 0, 2]
        preds = [0, 0, 2]
        # All prob vectors have a strong favourite
        probs = [[0.70, 0.15, 0.15], [0.65, 0.20, 0.15], [0.10, 0.15, 0.75]]
        result = _policy_metrics(y_true, preds, probs, default_policy)
        assert result["total_placed"] > 0
        assert result["hit_rate_pct"] == 100.0

    def test_low_confidence_avoided(self, default_policy):
        """Low-confidence picks should be avoided."""
        y_true = [0]
        preds = [0]
        probs = [[0.35, 0.33, 0.32]]  # Very low confidence
        result = _policy_metrics(y_true, preds, probs, default_policy)
        assert result["total_avoided"] >= 1
        assert result["total_placed"] == 0

    def test_draw_below_threshold_avoided(self, default_policy):
        """Draw predictions below draw_min_top_prob_pct should be avoided."""
        y_true = [1]
        preds = [1]
        probs = [[0.32, 0.36, 0.32]]  # draw at 36% < 37% threshold
        result = _policy_metrics(y_true, preds, probs, default_policy)
        assert result["total_avoided"] >= 1

    def test_return_structure(self, default_policy):
        result = _policy_metrics([0], [0], [[0.6, 0.2, 0.2]], default_policy)
        required_keys = {"total_evaluated", "total_placed", "total_avoided",
                         "coverage_pct", "hit_rate_pct", "bets", "leans",
                         "avoids", "by_class"}
        assert required_keys.issubset(result.keys())


# ── Flat-stake ROI ────────────────────────────────────────────────────────────


class TestFlatStakeROI:
    @pytest.fixture
    def default_policy(self):
        return {
            "min_confidence_pct": 53.0,
            "min_top_two_gap_pct": 3.0,
            "lean_min_confidence_pct": 51.0,
            "bet_min_confidence_pct": 70.0,
            "draw_min_top_prob_pct": 37.0,
        }

    def test_all_wins(self, default_policy):
        y_true = [0, 2]
        preds = [0, 2]
        probs = [[0.70, 0.15, 0.15], [0.12, 0.15, 0.73]]
        result = _flat_stake_roi(y_true, preds, probs, default_policy)
        assert result["bets_placed"] >= 1
        assert result["net_profit"] > 0

    def test_all_losses(self, default_policy):
        y_true = [2, 0]
        preds = [0, 2]
        probs = [[0.70, 0.15, 0.15], [0.12, 0.15, 0.73]]
        result = _flat_stake_roi(y_true, preds, probs, default_policy)
        # Staked but returned 0
        if result["bets_placed"] > 0:
            assert result["net_profit"] < 0

    def test_return_structure(self, default_policy):
        result = _flat_stake_roi([0], [0], [[0.6, 0.2, 0.2]], default_policy)
        required_keys = {"bets_placed", "total_staked", "total_returned",
                         "net_profit", "roi_pct", "flat_points"}
        assert required_keys.issubset(result.keys())


# ── Report loading ────────────────────────────────────────────────────────────


class TestLoadReport:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_walk_forward_report(tmp_path / "nonexistent.json") is None

    def test_valid_json(self, tmp_path):
        p = tmp_path / "report.json"
        data = {"aggregate": {"n_folds": 3}}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_walk_forward_report(p)
        assert result is not None
        assert result["aggregate"]["n_folds"] == 3

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json at all", encoding="utf-8")
        assert load_walk_forward_report(p) is None

    def test_default_path_uses_runtime_helper(self, tmp_path, monkeypatch):
        p = tmp_path / "runtime_report.json"
        data = {"selector": {"default_source": "ml"}}
        p.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(wf, "walk_forward_report_path", lambda: p)
        result = load_walk_forward_report()
        assert result == data
