"""Generate and save a model comparison report for Strategy Lab."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import ml_pipeline as mlp


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]

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
    parser.add_argument("--input", required=True, help="Path to the dataset (.csv or .json).")
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


def generate_report(
    input_path: Path,
    features: str,
    label: str = "label",
    date_key: str = "date",
    test_ratio: float = 0.25,
    random_state: int = 42,
    output: str | Path = mlp.DEFAULT_REPORT_PATH,
) -> Path:
    rows = _load_rows(input_path)
    report = mlp.compare_binary_models(
        rows,
        feature_keys=_feature_keys(features),
        label_key=label,
        date_key=date_key,
        test_ratio=test_ratio,
        random_state=random_state,
    )
    return mlp.save_comparison_report(report, output)


def main() -> int:
    args = build_parser().parse_args()
    output_path = generate_report(
        input_path=Path(args.input),
        features=args.features,
        label=args.label,
        date_key=args.date_key,
        test_ratio=args.test_ratio,
        random_state=args.random_state,
        output=args.output,
    )
    print(f"Saved ML comparison report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
