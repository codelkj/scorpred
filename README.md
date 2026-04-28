# ScorPred — Sports Decision Intelligence Platform

> AI-powered match outcome prediction with explainability, walk-forward backtesting, and a hybrid ML + rule-based engine.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey) ![scikit-learn](https://img.shields.io/badge/scikit--learn-Pipeline-orange) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Overview

ScorPred is a full-stack sports analytics platform that predicts soccer and NBA match outcomes, explains *why* each prediction was made, and gives users a clean dashboard experience built for decision-making — not just raw numbers.

It combines a **machine learning pipeline** (Logistic Regression → Random Forest → XGBoost → LightGBM → Stacking Ensemble) with a **deterministic rule engine** (form, home advantage, goal rates, H2H) into a calibrated **hybrid signal**, then evaluates it across 7 seasons of data using strict walk-forward backtesting.

---

## Features

| Feature | Description |
|---|---|
| **Dashboard** | Live KPIs, upcoming matches, top confidence picks, confidence tier charts |
| **Soccer Predictions** | Premier League + 10 other competitions via ESPN fallback |
| **NBA Predictions** | Game predictions with team form, standings, and injury context |
| **Hybrid Engine** | ML × 0.65 + Rules × 0.35 blended prediction signal |
| **Performance Tracker** | Track real predictions, grade results, calibration chart |
| **Alerts** | High-confidence opportunity alerts |
| **Watchlist** | Monitor specific teams across upcoming fixtures |
| **Match Analysis** | Deep per-match analysis with decision card, win probabilities, risk level |

---

## Tech Stack

```
Backend        Flask 3.x · SQLAlchemy (SQLite/PostgreSQL-ready)
ML Pipeline    scikit-learn · XGBoost · LightGBM · joblib
Data           pandas · numpy · 7 seasons Premier League CSV
Frontend       Jinja2 templates · Chart.js · Custom design system
API Data       ESPN public feeds (soccer) · RapidAPI NBA
Security       CSRF protection · rate limiting · session management
Testing        pytest (30+ test files)
```

---

## Architecture

```
scorpred/
├── app.py                             # Flask app (routes + middleware)
├── nba_routes.py                      # NBA blueprint routes
├── scorpred_engine.py                 # Core prediction orchestrator
├── decision_ui.py                     # Card builder + sort/filter utilities
├── ml_pipeline.py                     # sklearn model comparison & reporting
├── ml_service.py                      # Rule engine + ML inference + hybrid blend
├── train_model.py                     # Training pipeline entry point
├── walk_forward_backtest.py           # Chronological fold evaluation
├── generate_ml_report.py              # Offline model report generator
├── api_client.py                      # API-Football / ESPN data layer
├── nba_client.py                      # NBA API data layer
├── model_tracker.py                   # Prediction tracking & grading
├── services/
│   ├── strategy_lab.py                # Strategy Lab view model builder
│   ├── calibration_service.py         # Confidence calibration analysis
│   ├── feature_attribution_engine.py  # Feature impact attribution
│   ├── evidence.py                    # Evidence aggregation
│   ├── match_brain.py                 # Match intelligence orchestrator
│   └── prediction_service.py         # Fixture card pipeline
├── templates/
│   ├── base.html                      # Shell + sidebar + nav
│   ├── soccer.html                    # Soccer picks
│   ├── strategy_lab.html              # Strategy Lab
│   ├── backtesting.html               # Walk-forward results
│   ├── compare.html                   # ML vs Rules side-by-side
│   ├── explainability.html            # Feature attribution
│   ├── performance.html               # Prediction tracker
│   └── nba/                          # NBA-specific templates
├── data/
│   ├── raw/E0_20{18-25}.csv          # Premier League data (7 seasons)
│   ├── processed/                     # Cleaned training set + ELO state
│   ├── models/                        # Saved joblib model pipelines
│   └── backtests/                     # Walk-forward report JSON
└── tests/                             # pytest test suite (30+ files)
```

---

## ML Pipeline

### Training

```bash
python prepare_dataset.py       # Feature engineering, ELO, form windows
python train_model.py           # Train + save model pipeline
python generate_ml_report.py    # Generate offline comparison report
python walk_forward_backtest.py # Chronological fold evaluation
```

### Pipeline Architecture

```
Raw CSV → Feature Engineering → sklearn Pipeline
                                    ├── SimpleImputer (median)
                                    ├── StandardScaler
                                    └── Classifier (LR / RF / XGB / LGBM)
                                         ↓
                               CalibratedClassifierCV (isotonic)
                                         ↓
                               Stacking Ensemble (meta-LR on OOF)
                                         ↓
                               Hybrid Blend: ML×0.65 + Rules×0.35
```

**Features (40+):** recent form (5/10 game windows), PPG delta, goal scored/conceded rates, goal difference, home/away ELO, H2H record, shot proxies, form trajectory.

**Target:** 3-class outcome — HomeWin / Draw / AwayWin

**Evaluation:** Walk-forward with 5 expanding folds, strict no-look-ahead constraints.

### Model Results (Walk-Forward, 5 folds, 3,790 test matches)

| Model | Mean Accuracy | Brier Score |
|---|---|---|
| Stacking Ensemble | 51.0% | 0.2024 |
| Random Forest | 50.9% | 0.2013 |
| Logistic Regression | 50.0% | 0.2018 |
| XGBoost | 48.8% | 0.2127 |
| LightGBM | 47.4% | 0.2172 |
| **Hybrid (ML+Rules)** | **49.2%** | — |

> **High-confidence tier (70%+): 70.7% accuracy** across 539 test matches. The model's confidence scores are genuinely calibrated — higher stated confidence correlates with higher real accuracy.

---

## How to Run Locally

```bash
git clone https://github.com/AnoHondz/scorpred
cd scorpred
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your API keys
python app.py
```

### Environment Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `API_FOOTBALL_KEY` | RapidAPI key for API-Football |
| `NBA_API_KEY` | RapidAPI key for NBA data |
| `DATABASE_URL` | PostgreSQL URL (optional, defaults to SQLite) |

```bash
# Run the test suite
pytest tests/ -v
```

---

## Pages

| URL | Description |
|---|---|
| `/` | Dashboard |
| `/soccer` | Soccer predictions |
| `/nba/` | NBA predictions |
| `/strategy-lab` | Redirects to `/insights` (retired analytics page) |
| `/backtesting` | Redirects to `/insights` (retired analytics page) |
| `/compare` | Redirects to `/insights` (retired analytics page) |
| `/explainability` | Redirects to `/insights` (retired analytics page) |
| `/performance` | Prediction tracking & calibration |
| `/insights` | Cross-sport insights |
| `/prediction` | Match analysis |
| `/alerts` | High-confidence alerts |

### API Endpoints

```
GET  /api/dashboard/summary       Dashboard KPIs
GET  /api/dashboard/picks         Top opportunities
GET  /api/dashboard/performance   Performance metrics
GET  /health                      Health check
```

---

## Resume Bullet Points

- Built a **full-stack sports decision intelligence platform** in Flask with a two-layer hybrid prediction engine (ML × 0.65 + rules × 0.35) evaluated on 7 seasons of Premier League data
- Engineered a **scikit-learn Pipeline** (SimpleImputer → StandardScaler → Classifier) wrapped in `CalibratedClassifierCV`, assembled into a stacking ensemble, and persisted with joblib for zero-drift inference
- Implemented **walk-forward backtesting** across 5 chronological folds (3,790 test matches) with strict no-look-ahead constraints; 70.7% accuracy in the high-confidence tier (70%+)
- Built a **feature attribution engine** that quantifies which signals drive correct vs incorrect predictions using mean-delta analysis across graded outcomes, surfaced through an interactive explainability dashboard
- Designed a premium dark analytics UI with Chart.js visualizations across strategy lab, backtesting, ML vs rules comparison, and explainability pages
- Integrated ESPN public API + RapidAPI with in-memory caching, disk fallback, 403/429 suppression, and per-request deduplication for production reliability

---

## License

MIT
