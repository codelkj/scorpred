
# --- Enhanced Data Preparation for ML Feature Parity ---
import pandas as pd
import os
from pathlib import Path

DATA_PATH = "data/raw"
OUT_PATH = "data/processed/matches.csv"

feature_columns = [
    "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR",
    "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
    # Add more columns as needed for feature engineering
]

dfs = []
for file in os.listdir(DATA_PATH):
    if not file.endswith(".csv"): continue
    path = os.path.join(DATA_PATH, file)
    df = pd.read_csv(path)
    # Only keep columns that exist in this file
    keep_cols = [col for col in feature_columns if col in df.columns]
    df = df[keep_cols]
    df["Season"] = file
    dfs.append(df)

if not dfs:
    raise RuntimeError("No raw CSV files found in data/raw/")

full_df = pd.concat(dfs, ignore_index=True)

# Save all available features for downstream feature engineering
full_df.to_csv(OUT_PATH, index=False)
print(f"Dataset prepared successfully. Rows: {len(full_df)} Columns: {len(full_df.columns)} -> {OUT_PATH}")