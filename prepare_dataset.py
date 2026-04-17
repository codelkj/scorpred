import pandas as pd
import os

DATA_PATH = "data/raw"

files = [f for f in os.listdir(DATA_PATH) if f.endswith(".csv")]

dfs = []

for file in files:
    path = os.path.join(DATA_PATH, file)
    df = pd.read_csv(path)

    df = df[["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]]
    df["Season"] = file

    dfs.append(df)

full_df = pd.concat(dfs)

full_df.to_csv("data/processed/matches.csv", index=False)

print("Dataset prepared successfully.")