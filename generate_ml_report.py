"""Generate and save a model comparison report for Strategy Lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import ml_pipeline as mlp


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "matches", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    raise ValueError("Input JSON must be a list of rows or a dict containing 'rows', 'matches', or 'data'.")


def _feature_keys(text: str) -> list[str]:
    keys = [item.strip() for item in str(text or "").split(",") if item.strip()]
    if not keys:
        raise ValueError("At least one feature key is required.")
    return keys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a saved logistic regression vs Random Forest comparison report.",
    )
    parser.add_argument("--input", required=True, help="Path to the JSON dataset.")
    parser.add_argument(
        "--features",
        required=True,
        help="Comma-separated feature keys present in each row.",
    )
    parser.add_argument("--label", default="label", help="Binary label field name.")
    parser.add_argument("--date-key", default="date", help="Chronological date field.")
    parser.add_argument("--test-ratio", type=float, default=0.25, help="Fraction reserved for the chronological test window.")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed for the model suite.")
    parser.add_argument(
        "--output",
        default=str(mlp.DEFAULT_REPORT_PATH),
        help="Output path for the saved comparison report.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    rows = _load_rows(input_path)
    report = mlp.compare_binary_models(
        rows,
        feature_keys=_feature_keys(args.features),
        label_key=args.label,
        date_key=args.date_key,
        test_ratio=args.test_ratio,
        random_state=args.random_state,
    )
    output_path = mlp.save_comparison_report(report, args.output)
    print(f"Saved ML comparison report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
