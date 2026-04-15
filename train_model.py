"""Train a Random Forest match outcome model on clean pre-match features only.

Target encoding:
- 0: Home Win
- 1: Draw
- 2: Away Win

Feature engineering removes all target leakage: every feature is a rolling
average computed ONLY from matches that occurred BEFORE the target match.
Team histories are updated AFTER feature extraction for each row.

Upgraded feature set (47 features):

    Overall rolling form – last 5 prior matches:
        home_avg_gf_5, home_avg_ga_5, home_avg_gd_5, home_ppg_5
        away_avg_gf_5, away_avg_ga_5, away_avg_gd_5, away_ppg_5

    Overall rolling form – last 10 prior matches:
        home_avg_gf_10, home_avg_ga_10, home_ppg_10
        away_avg_gf_10, away_avg_ga_10, away_ppg_10

    Trend delta (recent vs medium-term form):
        home_ppg_delta_5v10, home_gf_delta_5v10
        away_ppg_delta_5v10, away_gf_delta_5v10

    Venue-specific form (home team's prior home matches / away team's prior away):
        home_home_avg_gf_5, home_home_avg_ga_5, home_home_ppg_5
        away_away_avg_gf_5, away_away_avg_ga_5, away_away_ppg_5

    Scoring consistency (last 5):
        home_clean_sheet_rate_5, away_clean_sheet_rate_5
        home_scored_rate_5,      away_scored_rate_5

    Opponent-strength proxy (avg PPG of last 5 opponents at time of match):
        home_opp_avg_ppg_5, away_opp_avg_ppg_5

    Rest / fatigue:
        days_since_last_match_home, days_since_last_match_away

    Head-to-head (prior meetings only, strictly leakage-safe):
        h2h_home_points_avg, h2h_goal_diff_avg

    Derived comparison features (all leakage-safe combinations of pre-match data):
        ppg_diff_5, gf_diff_5, ga_diff_5, venue_ppg_diff_5
        attack_vs_defense_home, attack_vs_defense_away
        attack_balance_diff, scored_rate_diff_5, clean_sheet_diff_5
        rest_diff_days
"""

from __future__ import annotations

import argparse
import collections
import csv
from datetime import date
from pathlib import Path
from typing import Any

import json

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix

from runtime_paths import (
    clean_soccer_dataset_path,
    clean_soccer_model_path,
    data_dir,
    elo_state_path,
    historical_dataset_path,
)
from utils.parsing import safe_float


# ── Feature schema ────────────────────────────────────────────────────────────

SHORT_WINDOW = 5
LONG_WINDOW  = 10
H2H_WINDOW   = 5
MIN_HISTORY  = 3  # minimum prior matches per team before a row is usable

FEATURE_COLUMNS = [
    # Overall rolling form – last 5
    "home_avg_gf_5",
    "home_avg_ga_5",
    "home_avg_gd_5",
    "home_ppg_5",
    "away_avg_gf_5",
    "away_avg_ga_5",
    "away_avg_gd_5",
    "away_ppg_5",
    # Overall rolling form – last 10
    "home_avg_gf_10",
    "home_avg_ga_10",
    "home_ppg_10",
    "away_avg_gf_10",
    "away_avg_ga_10",
    "away_ppg_10",
    # Trend delta: short-term vs medium-term
    "home_ppg_delta_5v10",
    "home_gf_delta_5v10",
    "away_ppg_delta_5v10",
    "away_gf_delta_5v10",
    # Venue-specific form (home team at home / away team away) – last 5
    "home_home_avg_gf_5",
    "home_home_avg_ga_5",
    "home_home_ppg_5",
    "away_away_avg_gf_5",
    "away_away_avg_ga_5",
    "away_away_ppg_5",
    # Scoring consistency – last 5
    "home_clean_sheet_rate_5",
    "away_clean_sheet_rate_5",
    "home_scored_rate_5",
    "away_scored_rate_5",
    # Opponent-strength proxy – avg PPG of last 5 opponents faced
    "home_opp_avg_ppg_5",
    "away_opp_avg_ppg_5",
    # Rest / fatigue
    "days_since_last_match_home",
    "days_since_last_match_away",
    # Head-to-head (prior meetings only)
    "h2h_home_points_avg",
    "h2h_goal_diff_avg",
    # Derived comparison features
    "ppg_diff_5",
    "gf_diff_5",
    "ga_diff_5",
    "venue_ppg_diff_5",
    "attack_vs_defense_home",
    "attack_vs_defense_away",
    "attack_balance_diff",
    "scored_rate_diff_5",
    "clean_sheet_diff_5",
    "rest_diff_days",
    # ELO ratings (pre-match, leakage-safe)
    "home_elo",
    "away_elo",
    "elo_diff",
]

CLASS_LABELS = {0: "HomeWin", 1: "Draw", 2: "AwayWin"}

ELO_BASE = 1500.0   # starting ELO for every new team
ELO_K    = 20.0     # update factor per match


# ── Target parsing ─────────────────────────────────────────────────────────────

def _target_from_row(row: dict[str, Any]) -> int | None:
    """Parse result column → 0 (HomeWin), 1 (Draw), 2 (AwayWin), or None."""
    raw = str(row.get("result") or row.get("target") or "").strip()
    lower = raw.lower()
    if lower in {"homewin", "home win", "h"} or raw == "0":
        return 0
    if lower in {"draw", "d", "x", "tie"} or raw == "1":
        return 1
    if lower in {"awaywin", "away win", "a"} or raw == "2":
        return 2
    return None


# ── Rolling feature engineering ───────────────────────────────────────────────

def _rolling_stats(history: list[dict[str, Any]], window: int = SHORT_WINDOW) -> dict[str, float]:
    """Compute rolling averages from the last `window` entries in history.

    Each history entry must have: gf (float), ga (float), pts (float).
    Optional field: opp_ppg (float) – opponent's PPG at time of match.
    """
    recent = history[-window:] if history else []
    if not recent:
        return {
            "avg_gf": 0.0, "avg_ga": 0.0, "avg_gd": 0.0, "ppg": 0.0,
            "clean_sheet_rate": 0.0, "scored_rate": 0.0, "opp_avg_ppg": 1.0,
        }
    n = float(len(recent))
    avg_gf = sum(r["gf"] for r in recent) / n
    avg_ga = sum(r["ga"] for r in recent) / n
    ppg    = sum(r["pts"] for r in recent) / n
    clean_sheet_rate = sum(1.0 for r in recent if r["ga"] == 0.0) / n
    scored_rate      = sum(1.0 for r in recent if r["gf"] >= 1.0) / n
    opp_avg_ppg      = sum(r.get("opp_ppg", 1.0) for r in recent) / n
    return {
        "avg_gf":           round(avg_gf, 4),
        "avg_ga":           round(avg_ga, 4),
        "avg_gd":           round(avg_gf - avg_ga, 4),
        "ppg":              round(ppg, 4),
        "clean_sheet_rate": round(clean_sheet_rate, 4),
        "scored_rate":      round(scored_rate, 4),
        "opp_avg_ppg":      round(opp_avg_ppg, 4),
    }


def _venue_rolling_stats(
    history: list[dict[str, Any]], is_home: bool, window: int = SHORT_WINDOW
) -> dict[str, float]:
    """Compute rolling stats filtered to home or away matches only."""
    venue_hist = [r for r in history if r.get("is_home") == is_home]
    return _rolling_stats(venue_hist, window)


def _parse_date(date_str: str) -> date | None:
    """Parse ISO-format date string (YYYY-MM-DD) to a date object."""
    try:
        return date.fromisoformat(str(date_str).strip())
    except ValueError:
        return None


def build_clean_features(historical_path: Path) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Build a leakage-free pre-match feature dataset from historical_matches.csv.

    Each row's features are computed ONLY from matches before that match's date.
    Both teams' histories are updated AFTER feature extraction for that row.
    Rows where either team has fewer than MIN_HISTORY prior matches are dropped.

    History entry fields stored per team:
        gf       (float) – goals scored
        ga       (float) – goals conceded
        pts      (float) – points earned (3/1/0)
        is_home  (bool)  – was this match at home?
        opp      (str)   – opponent team name
        opp_ppg  (float) – opponent's rolling PPG before this match
    """
    with historical_path.open("r", encoding="utf-8", newline="") as fh:
        raw_rows = list(csv.DictReader(fh))

    raw_rows.sort(key=lambda r: str(r.get("date", "")))

    team_history:     dict[str, list[dict[str, Any]]]        = collections.defaultdict(list)
    h2h_records:      dict[tuple[str, str], list[dict]]      = collections.defaultdict(list)
    last_match_dates: dict[str, date]                        = {}
    elo_ratings:      dict[str, float]                       = collections.defaultdict(lambda: ELO_BASE)
    processed:        list[dict[str, Any]]                   = []

    for row in raw_rows:
        home_team = str(row.get("home_team", "")).strip()
        away_team = str(row.get("away_team", "")).strip()
        if not home_team or not away_team:
            continue

        result = _target_from_row(row)
        if result is None:
            continue

        # Final scores – used ONLY to update histories after feature extraction
        home_gf      = safe_float(row.get("goals_scored"),  0.0)
        home_ga      = safe_float(row.get("goals_conceded"), 0.0)
        current_date = _parse_date(row.get("date", ""))

        home_hist = team_history[home_team]
        away_hist = team_history[away_team]

        # Capture ELO BEFORE this match (leakage-safe: pre-match strength estimate)
        h_elo = elo_ratings[home_team]
        a_elo = elo_ratings[away_team]

        # Pre-compute short-window stats for BOTH teams.
        # These are also used as the opp_ppg value stored in opponent history entries.
        home_s5 = _rolling_stats(home_hist, SHORT_WINDOW)
        away_s5 = _rolling_stats(away_hist, SHORT_WINDOW)

        # ── Feature extraction (only when both teams have enough prior data) ──
        if len(home_hist) >= MIN_HISTORY and len(away_hist) >= MIN_HISTORY:
            home_s10    = _rolling_stats(home_hist, LONG_WINDOW)
            away_s10    = _rolling_stats(away_hist, LONG_WINDOW)
            home_venue  = _venue_rolling_stats(home_hist, is_home=True,  window=SHORT_WINDOW)
            away_venue  = _venue_rolling_stats(away_hist, is_home=False, window=SHORT_WINDOW)

            # H2H: prior pairings where THIS home team was home vs THIS away team
            prior_h2h   = h2h_records[(home_team, away_team)][-H2H_WINDOW:]
            h2h_pts     = sum(e["pts"] for e in prior_h2h) / len(prior_h2h) if prior_h2h else 1.0
            h2h_gd      = sum(e["gd"]  for e in prior_h2h) / len(prior_h2h) if prior_h2h else 0.0

            # Days since last match (capped at 60 to suppress gaps from data sparsity)
            def _days(team: str) -> float:
                if current_date and team in last_match_dates:
                    return min(float((current_date - last_match_dates[team]).days), 60.0)
                return 7.0

            processed.append({
                "date":       row.get("date", ""),
                "home_team":  home_team,
                "away_team":  away_team,
                # Overall last-5
                "home_avg_gf_5":         home_s5["avg_gf"],
                "home_avg_ga_5":         home_s5["avg_ga"],
                "home_avg_gd_5":         home_s5["avg_gd"],
                "home_ppg_5":            home_s5["ppg"],
                "away_avg_gf_5":         away_s5["avg_gf"],
                "away_avg_ga_5":         away_s5["avg_ga"],
                "away_avg_gd_5":         away_s5["avg_gd"],
                "away_ppg_5":            away_s5["ppg"],
                # Overall last-10
                "home_avg_gf_10":        home_s10["avg_gf"],
                "home_avg_ga_10":        home_s10["avg_ga"],
                "home_ppg_10":           home_s10["ppg"],
                "away_avg_gf_10":        away_s10["avg_gf"],
                "away_avg_ga_10":        away_s10["avg_ga"],
                "away_ppg_10":           away_s10["ppg"],
                # Trend delta
                "home_ppg_delta_5v10":   round(home_s5["ppg"]    - home_s10["ppg"],    4),
                "home_gf_delta_5v10":    round(home_s5["avg_gf"] - home_s10["avg_gf"], 4),
                "away_ppg_delta_5v10":   round(away_s5["ppg"]    - away_s10["ppg"],    4),
                "away_gf_delta_5v10":    round(away_s5["avg_gf"] - away_s10["avg_gf"], 4),
                # Venue-specific form
                "home_home_avg_gf_5":    home_venue["avg_gf"],
                "home_home_avg_ga_5":    home_venue["avg_ga"],
                "home_home_ppg_5":       home_venue["ppg"],
                "away_away_avg_gf_5":    away_venue["avg_gf"],
                "away_away_avg_ga_5":    away_venue["avg_ga"],
                "away_away_ppg_5":       away_venue["ppg"],
                # Scoring consistency
                "home_clean_sheet_rate_5": home_s5["clean_sheet_rate"],
                "away_clean_sheet_rate_5": away_s5["clean_sheet_rate"],
                "home_scored_rate_5":      home_s5["scored_rate"],
                "away_scored_rate_5":      away_s5["scored_rate"],
                # Opponent-strength proxy
                "home_opp_avg_ppg_5":    home_s5["opp_avg_ppg"],
                "away_opp_avg_ppg_5":    away_s5["opp_avg_ppg"],
                # Rest / fatigue
                "days_since_last_match_home": _days(home_team),
                "days_since_last_match_away": _days(away_team),
                # H2H
                "h2h_home_points_avg":   round(h2h_pts, 4),
                "h2h_goal_diff_avg":     round(h2h_gd,  4),
                # Derived comparison features
                "ppg_diff_5":            round(home_s5["ppg"] - away_s5["ppg"], 4),
                "gf_diff_5":             round(home_s5["avg_gf"] - away_s5["avg_gf"], 4),
                "ga_diff_5":             round(away_s5["avg_ga"] - home_s5["avg_ga"], 4),
                "venue_ppg_diff_5":      round(home_venue["ppg"] - away_venue["ppg"], 4),
                "attack_vs_defense_home": round(home_s5["avg_gf"] - away_s5["avg_ga"], 4),
                "attack_vs_defense_away": round(away_s5["avg_gf"] - home_s5["avg_ga"], 4),
                "attack_balance_diff":   round(
                    (home_s5["avg_gf"] - away_s5["avg_ga"]) - (away_s5["avg_gf"] - home_s5["avg_ga"]),
                    4,
                ),
                "scored_rate_diff_5":    round(home_s5["scored_rate"] - away_s5["scored_rate"], 4),
                "clean_sheet_diff_5":    round(home_s5["clean_sheet_rate"] - away_s5["clean_sheet_rate"], 4),
                "rest_diff_days":        round(_days(home_team) - _days(away_team), 4),
                # ELO ratings (pre-match)
                "home_elo":              round(h_elo, 2),
                "away_elo":              round(a_elo, 2),
                "elo_diff":              round(h_elo - a_elo, 2),
                # Target
                "result": CLASS_LABELS[result],
                "target": result,
            })

        # ── Update histories AFTER feature extraction (no leakage) ──────────
        home_pts = 3.0 if result == 0 else (1.0 if result == 1 else 0.0)
        away_pts = 3.0 if result == 2 else (1.0 if result == 1 else 0.0)

        # opp_ppg stored = opponent's pre-match rolling PPG (computed above)
        team_history[home_team].append({
            "gf": home_gf, "ga": home_ga, "pts": home_pts,
            "is_home": True,  "opp": away_team, "opp_ppg": away_s5["ppg"],
        })
        team_history[away_team].append({
            "gf": home_ga, "ga": home_gf, "pts": away_pts,
            "is_home": False, "opp": home_team, "opp_ppg": home_s5["ppg"],
        })

        h2h_records[(home_team, away_team)].append(
            {"pts": home_pts, "gd": home_gf - home_ga}
        )
        h2h_records[(away_team, home_team)].append(
            {"pts": away_pts, "gd": home_ga - home_gf}
        )

        if current_date:
            last_match_dates[home_team] = current_date
            last_match_dates[away_team] = current_date

        # ── Update ELO AFTER feature extraction (no leakage) ────────────────
        home_score = 1.0 if result == 0 else (0.5 if result == 1 else 0.0)
        away_score = 1.0 - home_score
        h_expected = 1.0 / (1.0 + 10.0 ** ((a_elo - h_elo) / 400.0))
        a_expected = 1.0 - h_expected
        elo_ratings[home_team] = round(h_elo + ELO_K * (home_score - h_expected), 2)
        elo_ratings[away_team] = round(a_elo + ELO_K * (away_score - a_expected), 2)

    return processed, dict(elo_ratings)


# ── IO helpers ────────────────────────────────────────────────────────────────

def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("No rows available to write.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _row_to_features(row: dict[str, Any]) -> list[float]:
    return [safe_float(row.get(f), 0.0) for f in FEATURE_COLUMNS]


# ── Training pipeline ─────────────────────────────────────────────────────────

def train_model(
    historical_path: Path | None = None,
    output_path: Path | None = None,
    processed_dataset_path: Path | None = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Build clean features, train Random Forest, print metrics, save model."""
    historical = historical_path or historical_dataset_path()
    if not historical.exists():
        raise FileNotFoundError(
            f"Historical dataset not found: {historical}\n"
            "Provide data/historical_matches.csv to train the model."
        )

    print(f"Building clean pre-match features from: {historical}")
    rows, final_elo = build_clean_features(historical)

    if len(rows) < 20:
        raise ValueError(
            f"Only {len(rows)} usable rows after feature engineering (need ≥ 20). "
            f"Check that historical_matches.csv has enough rows and team_history ≥ {MIN_HISTORY}."
        )

    # ── Save processed dataset ────────────────────────────────────────────────
    processed_path = processed_dataset_path or clean_soccer_dataset_path()
    _write_rows(processed_path, rows)
    print(f"Saved clean dataset ({len(rows)} rows) → {processed_path}")

    # ── Feature matrix and targets ────────────────────────────────────────────
    x = [_row_to_features(r) for r in rows]
    y = [int(r["target"]) for r in rows]

    # ── Class balance ─────────────────────────────────────────────────────────
    class_counts = collections.Counter(y)
    print("\nClass balance:")
    for cls, label in CLASS_LABELS.items():
        count = class_counts.get(cls, 0)
        pct = count / len(y) * 100.0
        print(f"  {label:10s} ({cls}): {count:4d}  ({pct:.1f}%)")

    # ── Chronological train/test split (last 20% = test) ─────────────────────
    n_test = max(1, int(len(rows) * 0.2))
    x_train, x_test = x[:-n_test], x[-n_test:]
    y_train, y_test = y[:-n_test], y[-n_test:]
    print(f"\nChronological split: {len(x_train)} train / {len(x_test)} test")

    # ── Train ─────────────────────────────────────────────────────────────────
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=3,
        random_state=random_state,
    )
    model.fit(x_train, y_train)

    # ── Evaluate ──────────────────────────────────────────────────────────────
    predictions = model.predict(x_test)
    accuracy = float(accuracy_score(y_test, predictions))
    print(f"\nTest accuracy: {accuracy * 100:.1f}%  (random baseline ≈ 33%)")

    cm = confusion_matrix(y_test, predictions, labels=[0, 1, 2])
    print("\nConfusion matrix (rows=actual, cols=predicted):")
    print(f"  {'':10s}  " + "  ".join(f"{CLASS_LABELS[i]:10s}" for i in range(3)))
    for i, counts in enumerate(cm):
        print(f"  {CLASS_LABELS[i]:10s}  " + "  ".join(f"{v:10d}" for v in counts))

    # ── Feature importances ───────────────────────────────────────────────────
    print("\nFeature importances:")
    ranked = sorted(zip(FEATURE_COLUMNS, model.feature_importances_), key=lambda t: -t[1])
    for feat, imp in ranked:
        print(f"  {feat:30s}: {imp:.4f}")

    print(f"\nFeatures used ({len(FEATURE_COLUMNS)}): {FEATURE_COLUMNS}")

    # ── Save model bundle ─────────────────────────────────────────────────────
    save_path = output_path or clean_soccer_model_path()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_names": FEATURE_COLUMNS,
        "class_labels": CLASS_LABELS,
        "accuracy": accuracy,
        "rolling_window": SHORT_WINDOW,
        "dataset_path": str(processed_path),
    }
    joblib.dump(bundle, save_path)
    print(f"\nSaved model → {save_path}")

    # ── Save ELO state for runtime lookup ─────────────────────────────────────
    elo_path = elo_state_path()
    elo_path.parent.mkdir(parents=True, exist_ok=True)
    elo_path.write_text(json.dumps(final_elo, indent=2), encoding="utf-8")
    print(f"Saved ELO state ({len(final_elo)} teams) → {elo_path}")

    return {
        "dataset": str(processed_path),
        "model_path": str(save_path),
        "total_rows": len(rows),
        "train_size": len(x_train),
        "test_size": len(x_test),
        "accuracy": accuracy,
        "feature_names": FEATURE_COLUMNS,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train ScorPred Soccer Random Forest on clean pre-match features."
    )
    parser.add_argument(
        "--historical",
        default=str(historical_dataset_path()),
        help="Path to historical_matches.csv.",
    )
    parser.add_argument(
        "--output",
        default=str(clean_soccer_model_path()),
        help="Where to save the model pickle.",
    )
    parser.add_argument("--random-state", type=int, default=42, help="Random seed.")
    return parser


def main() -> int:
    data_dir().mkdir(parents=True, exist_ok=True)
    args = build_parser().parse_args()
    result = train_model(
        historical_path=Path(args.historical),
        output_path=Path(args.output),
        random_state=args.random_state,
    )
    print(f"\nDone. Test accuracy: {result['accuracy'] * 100:.1f}%")
    print(f"Clean dataset : {result['dataset']}")
    print(f"Saved model   : {result['model_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
