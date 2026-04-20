"""Tests for Strategy Lab service helpers."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import strategy_lab


def _window_payload(label: str, accuracy: float, start: str, end: str) -> dict:
    return {
        "label": label,
        "config": {
            "date_range": [start, end],
            "total_rows": 1200,
        },
        "aggregate": {
            "n_folds": 5,
            "total_test_matches": 240,
            "combined": {
                "mean_combined_accuracy": accuracy,
                "std_combined_accuracy": 0.012,
                "mean_rule_accuracy": accuracy - 0.02,
                "mean_ml_accuracy": accuracy - 0.01,
                "mean_avg_confidence_pct": 63.5,
            },
            "policy": {
                "aggregate_hit_rate_pct": 58.4,
                "aggregate_coverage_pct": 46.2,
                "total_placed": 111,
            },
            "base_models": {
                "stacking_ensemble": {"mean_accuracy": accuracy - 0.01},
                "lightgbm": {"mean_accuracy": accuracy - 0.03},
            },
            "trend": "stable",
            "trend_delta": 0.004,
        },
    }


def test_walk_forward_summary_supports_windowed_reports(tmp_path, monkeypatch):
    report_path = tmp_path / "walk_forward_report.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-19T00:00:00Z",
                "windows": {
                    "all_history": _window_payload("All History", 0.541, "2021-08-08", "2026-04-19"),
                    "last_3_years": _window_payload("Last 3 Years", 0.556, "2023-04-20", "2026-04-19"),
                },
                "selector": {
                    "default_source": "combined",
                    "default_accuracy": 0.556,
                    "segments": {
                        "overall": {"count": 240, "rule_accuracy": 0.53, "ml_accuracy": 0.548, "combined_accuracy": 0.556},
                        "model_disagreement": {"count": 90, "rule_accuracy": 0.46, "ml_accuracy": 0.57, "combined_accuracy": 0.51},
                    },
                    "overrides": [
                        {
                            "segment": "model_disagreement",
                            "preferred_source": "ml",
                            "sample_size": 90,
                            "preferred_accuracy": 0.57,
                            "default_accuracy": 0.51,
                            "gain_vs_default": 0.06,
                            "reason": "Rule and ML disagree on the likely winner.",
                        }
                    ],
                    "summary": "Default to Combined using recent backtests, with one segment override.",
                    "min_sample_size": 60,
                    "min_gain": 0.01,
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(strategy_lab, "walk_forward_report_path", lambda: report_path)

    summary = strategy_lab.walk_forward_summary()

    assert summary["available"] is True
    assert summary["windows"]["all_history"]["label"] == "All History"
    assert summary["windows"]["last_3_years"]["label"] == "Last 3 Years"
    assert summary["windows"]["last_3_years"]["mean_combined_accuracy"] == 55.6
    assert summary["selector"]["available"] is True
    assert summary["selector"]["default_source_label"] == "Combined"
    assert summary["selector"]["override_rows"][0]["preferred_source_label"] == "Ensemble ML"
