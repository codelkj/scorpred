# ScorPred — Sports Decision Intelligence Platform

<<<<<<< HEAD
A full-stack analytics system that combines rule-based modeling and machine learning to generate explainable, data-driven match recommendations.
=======
A football and NBA sports prediction web app built with Flask. Provides head-to-head analysis, multi-league predictions, model performance tracking, player prop line generation, live standings, and an AI-powered chatbot assistant.
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561

**Portfolio snapshot**

- **Stack:** Python, Flask, Jinja, scikit-learn, pytest
- **Sports covered:** Soccer and NBA
- **Core value:** Explainable recommendations, not black-box picks
- **Current local test baseline:** `115 passing tests` on April 13, 2026
- **CI:** GitHub Actions runs the test suite on push and pull request

<<<<<<< HEAD
## What It Does
=======
| Feature | Description |
|---|---|
| **Football Matchup** | H2H history, form tables, home/away splits, injury reports |
| **Today Soccer Predictions** | Grouped predictions across all supported soccer leagues |
| **Top Picks Today** | High-confidence picks grouped by league, plus NBA high-confidence picks |
| **Win Prediction** | Poisson distribution model weighted by form, H2H, home advantage, and injuries |
| **Player Props** | 6-layer statistical prop line builder (season avg, last-5, vs-opponent, consistency, context, confidence) |
| **Fixtures** | Upcoming fixtures with quick standings-based predictions |
| **NBA Section** | Full NBA module — scoreboard, standings, matchup, players, predictions, today predictions |
| **Model Performance** | Tracks prediction outcomes with accuracy by confidence, sport, and soccer league |
| **World Cup** | World Cup fixture viewer and team vs team predictor |
| **AI Chatbot** | Claude-powered assistant with conversation history (falls back gracefully without API key) |
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561

- Analyzes soccer and NBA matchups using form, injuries, H2H context, standings, and team trends
- Generates a final recommendation through weighted rule-based modeling
- Explains predictions with key drivers, confidence, and risk context
- Tracks historical performance and reconciles predictions against completed results
- Compares strategies through tracked backtesting views in Strategy Lab
- Evaluates ML baselines with Logistic Regression vs Random Forest

## Demo Flow

1. Select a soccer fixture or NBA game from the app home flow.
2. Open the Match Analysis / Prediction view to inspect the recommendation, edge, and explanation.
3. Add a pick or prop to the bet-slip-style workflow.
4. Visit Strategy Lab to review tracked performance, segment breakdowns, and the ML comparison report.

<<<<<<< HEAD
**Core routes**

- `/soccer` and `/nba/` for game selection
- `/matchup` and `/prediction` for analysis
- `/props` for prop workflows
- `/model-performance` for tracked outcomes
- `/strategy-lab` for strategy and ML comparison views

## Architecture Overview

```mermaid
flowchart LR
    UI["Flask + Jinja UI"] --> API["Flask Backend"]
    API --> RULE["ScorPred Rule Engine"]
    API --> TRACK["Tracking + Result Reconciliation"]
    API --> ML["ScorMind ML Pipeline"]
    RULE --> EXPLAIN["Explainability Layer"]
    TRACK --> LAB["Strategy Lab"]
    ML --> LAB
=======
```bash
git clone <your-repo-url>
cd scorpred
pip install -r requirements.txt
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561
```

| Component | Responsibility | Main files |
| --- | --- | --- |
| Flask backend | Route handling, page rendering, request orchestration | `app.py`, `nba_routes.py` |
| ScorPred rule engine | Weighted matchup scoring for soccer and NBA | `scorpred_engine.py`, `predictor.py`, `nba_predictor.py` |
| ScorMind ML pipeline | Leakage-safe model comparison and saved reporting | `ml_pipeline.py`, `generate_ml_report.py` |
| Weighting engine | Aggregates form, injuries, venue, H2H, and opponent strength into a final edge | `scorpred_engine.py` |
| Explainability layer | Surfaces components, reasoning, key edges, and readable summaries | `scorpred_engine.py`, `services/strategy_lab.py` |
| Backtesting engine | Converts tracked predictions into reviewable performance views | `model_tracker.py`, `result_updater.py`, `services/strategy_lab.py` |
| Result tracking system | Stores predictions, reconciles outcomes, and builds dashboard metrics | `model_tracker.py`, `result_updater.py` |

## ML Pipeline

- **Model comparison:** Logistic Regression vs Random Forest
- **Split strategy:** chronological train/test split
- **Evaluation style:** leakage-safe, with later matches reserved for test only
- **Signals surfaced:** top feature weights/importances for the leading model
- **Output format:** saved JSON report consumed by Strategy Lab

**What this means**

- Earlier matches train the models.
- Later matches evaluate the models.
- Feature signal summaries make the comparison readable instead of dumping raw diagnostics.
- Strategy Lab shows the winning model, accuracy gap, evaluation sample size, and top signals.

## Strategy Lab

- Highlights the current tracked hit rate across finalized predictions
- Shows best-performing sport and confidence segments
- Supports quick accuracy comparison across tracked slices
- Helps surface where users should avoid weaker-performing segments as the sample grows
- Displays the ML comparison report alongside live tracking metrics
- Summarizes insights in a clean, product-facing format

## Screenshots

| Match Analysis | Strategy Lab | ML Comparison |
| --- | --- | --- |
| ![Match Analysis placeholder](docs/screenshots/match-analysis-placeholder.svg) | ![Strategy Lab placeholder](docs/screenshots/strategy-lab-placeholder.svg) | ![ML comparison placeholder](docs/screenshots/ml-comparison-placeholder.svg) |

## Run Locally

Tested locally with Python 3.12 on Windows.

### 1. Create the virtual environment

```powershell
py -3.12 -m venv .venv
```

If `py` is not available:

<<<<<<< HEAD
```powershell
python -m venv .venv
=======
```bash
python app.py
# Visit http://localhost:5001 (or PORT if set)
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561
```

### 2. Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Create your local env file

```powershell
Copy-Item .env.example .env
```

### 4. Fill in `.env`

| Variable | Required to boot | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Recommended | Flask session/CSRF secret. If omitted, the app still starts with an ephemeral secret for the current process only. |
| `API_FOOTBALL_KEY` | Needed for live soccer data | RapidAPI key for soccer fixtures, teams, injuries, and player data. |
| `NBA_API_KEY` | Needed for legacy NBA/team/props data | RapidAPI key for NBA endpoints used by parts of the app. |
| `ANTHROPIC_API_KEY` | Optional | Enables Claude-backed chat responses. Without it, chat falls back to the built-in responder. |
| `PORT` | Optional | Local port, defaults to `5000`. |
| `FLASK_DEBUG` | Optional | Set to `1` to enable Flask debug mode. |
| `FLASK_USE_RELOADER` | Optional | Set to `1` to enable the Flask reloader. |
| `SCORPRED_DATA_ROOT` | Optional | Overrides where generated runtime files are stored. Default is the repo root, which writes to `cache/`. |

### 5. Start the app

```powershell
.\.venv\Scripts\python.exe app.py
```

Then open [http://localhost:5000](http://localhost:5000).

### Optional: seed local demo data

This populates Performance and Strategy Lab immediately on a new clone.

```powershell
.\.venv\Scripts\python.exe seed_tracking_data.py
.\.venv\Scripts\python.exe generate_ml_report.py --input data\historical_matches.csv --features form,goals_scored,goals_conceded,goal_diff --label result --date-key date
```

### Optional: train the real Random Forest model

This trains a 3-class match outcome model and saves it to `data/model.pkl`.

```powershell
.\.venv\Scripts\python.exe train_model.py
```

To retrain later with updated data:

```powershell
.\.venv\Scripts\python.exe retrain_model.py
```

### Optional: refresh tracked results

```powershell
.\.venv\Scripts\python.exe -c "import result_updater as ru; print(ru.update_pending_predictions())"
```

### Optional: tune live confidence policy from backtests

This fits a data-driven decision policy (avoid/lean/bet thresholds) from finalized
tracked outcomes and writes it to `cache/ml/prediction_policy.json`.

```powershell
.\.venv\Scripts\python.exe optimize_prediction_policy.py
```

### Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```


## Local & Persistent Runtime Files

All tracked predictions, results, strategy artifacts, mistake analysis, and user accounts are stored under the runtime root.

By default, this is `<repo>/cache/` for local/dev. For production (Render, etc), set `SCORPRED_DATA_ROOT` to a persistent disk path (e.g. `/persistent`).

The app creates these folders automatically:

- `cache/football`, `cache/props`, `cache/nba`, `cache/nba_public`, `cache/ml`
- `user_data/` (for user accounts and saved picks)
- `data/processed`, `data/models`, `data/backtests`, `data/analysis`, `data/logs`

Main generated files:
- `cache/prediction_tracking.json` (system-level tracked predictions)
- `cache/prediction_history.json`
- `cache/ml/model_comparison.json`
- `data/analysis/mistake_report.json`
- `data/backtests/walk_forward_report.json`
- `user_data/*.json` (per-user data)

## Testing + CI

- Full `pytest` suite with route, tracking, predictor, and ML coverage
- Current local baseline: `115 passed` on April 13, 2026
- GitHub Actions workflow: `.github/workflows/tests.yml`
- CI command: `pytest tests -q`
- Tests use mocks heavily, so the suite stays stable without live API dependency

## Limitations

- Upstream API quality and availability directly affect analysis quality
- The ML models are baseline comparators, not production-grade forecasting systems
- Strategy conclusions are only as strong as the tracked sample size
- This project is an engineering portfolio piece and local decision-support tool, not financial advice


## Deploy in One Command

The app ships a `Procfile` and is ready for [Render](https://render.com), [Railway](https://railway.app), and [Fly.io](https://fly.io) with no extra configuration files beyond what is already in the repo.

### Render (recommended for new deployments)

1. Push the repo to GitHub.
2. In Render → **New Web Service** → connect the repo.
3. Render auto-detects the `Procfile`. Confirm the start command is:
    ```
    gunicorn app:app --workers 2 --threads 2 --timeout 60 --bind 0.0.0.0:$PORT
    ```
4. Set environment variables under **Environment → Secret Files or Env Vars**:

| Variable | Required | Value / notes |
|---|---|---|
<<<<<<< HEAD
| `SECRET_KEY` | Yes | Any long random string (e.g. `openssl rand -hex 32`) |
| `API_FOOTBALL_KEY` | Yes for soccer | RapidAPI key for api-football-v1 |
| `NBA_API_KEY` | Yes for NBA | RapidAPI key for nba-api-free-data |
| `ANTHROPIC_API_KEY` | Optional | Enables Claude-backed chat; falls back gracefully without it |
| `SCORPRED_DATA_ROOT` | Yes for persistence | Set to `/persistent` or your Render disk mount path |
| `FLASK_DEBUG` | Never in prod | Leave unset (defaults to `0`) |
| `PORT` | Auto-injected by Render | Do not set manually |
| `EXTERNAL_API_TIMEOUT_SECONDS` | Optional | Default `20`; raise if your API plan is slow |
| `EXTERNAL_API_RETRY_ATTEMPTS` | Optional | Default `3`; safe as-is |
=======
| `API_FOOTBALL_KEY` | Recommended | RapidAPI key for API-Football (fallback sources are used when missing) |
| `NBA_API_KEY` | Recommended | RapidAPI key for NBA data (fallback sources are used when missing) |
| `ANTHROPIC_API_KEY` | No | Enables Claude AI chatbot (falls back to rule-based replies without it) |
| `SECRET_KEY` | Yes (production) | Flask session secret — change to a long random string in production |
| `FLASK_DEBUG` | No | Set to `1` for debug mode (default: `0`) |
| `PORT` | No | Server port (default: `5001`) |
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561

5. Click **Deploy**. Health check passes when the root `/` returns HTTP 200.

**Startup health check** — Render pings `/` before routing traffic. The app returns 200 on `/` with no external API calls, so it boots even without keys configured.

### Persistence & Auth

- All tracked predictions, results, and user accounts are stored under the persistent root (`SCORPRED_DATA_ROOT`).
- Guest/demo mode: anyone can use the app without logging in. Only login is required to save picks/history.
- User accounts and saved picks are stored in `user_data/` under the persistent root.
- No forced signup wall; public demo is always available.

<<<<<<< HEAD
### Railway

```bash
# From the repo root, logged into the Railway CLI:
railway login
railway init          # link or create project
railway up            # deploys from the Procfile automatically
```

Then set vars in the Railway dashboard (Project → Variables) using the same table above. Railway injects `$PORT` automatically.

### Fly.io

```bash
# One-time setup (only needed on first deploy):
fly launch --no-deploy          # generates fly.toml; accept defaults
fly secrets set SECRET_KEY="$(openssl rand -hex 32)"
fly secrets set API_FOOTBALL_KEY="your_key"
fly secrets set NBA_API_KEY="your_key"

# Deploy:
fly deploy
=======
```
ScorPred/
├── app.py                  # Main Flask app — football routes, chat, props
├── nba_routes.py           # NBA Blueprint (/nba prefix)
├── api_client.py           # API-Football + ESPN wrapper with caching
├── nba_client.py           # NBA RapidAPI wrapper
├── nba_live_client.py      # ESPN public feed NBA client (no auth needed)
├── scorpred_engine.py      # Unified prediction engine (soccer + NBA scoring components)
├── predictor.py            # Football prediction logic (Poisson model)
├── nba_predictor.py        # Legacy NBA model utilities (ScorPred is the primary NBA predictor)
├── props_engine.py         # 6-layer player prop line calculator
├── model_tracker.py        # Prediction tracking + accuracy metrics
├── result_updater.py       # Auto-update pending predictions with final results
├── league_config.py        # Supported leagues and configuration constants
│
├── templates/
│   ├── base.html           # Master layout (navbar, chat widget, footer)
│   ├── home.html           # Landing page
│   ├── soccer.html         # Football selector + upcoming fixtures
│   ├── matchup.html        # H2H analysis
│   ├── player.html         # Squad/key threats comparison
│   ├── prediction.html     # Win probability results
│   ├── props.html          # Props bet builder
│   ├── fixtures.html       # Fixture list
│   ├── today_predictions.html  # Soccer predictions grouped by league
│   ├── top_picks_today.html    # Soccer/NBA top-confidence picks
│   ├── model_performance.html  # Accuracy dashboard
│   ├── worldcup.html       # World Cup predictor
│   └── nba/                # NBA-specific templates
│
├── static/
│   ├── style.css           # Dark theme with green accents
│   ├── main.js             # Animations, chat widget, nav
│   └── charts.js           # Chart.js visualisations
│
├── tests/
│   ├── test_routes.py      # Flask route integration tests
│   └── test_predictor.py   # Predictor unit tests
│
├── .env.example            # Template for environment variables
├── .gitignore
└── requirements.txt
```

---

## Pages & Routes

### Football

| Route | Method | Description |
|---|---|---|
| `/` | GET | Home / landing |
| `/soccer` | GET | Football team list + upcoming fixtures |
| `/select` | POST | Select teams A and B |
| `/matchup` | GET | H2H and form analysis |
| `/players` | GET | Squad side-by-side comparison |
| `/prediction` | GET | Win probability with Poisson model |
| `/fixtures` | GET | Upcoming fixtures with quick predictions |
| `/today-soccer-predictions` | GET | Predictions grouped by supported leagues |
| `/top-picks-today` | GET | High-confidence soccer and NBA picks |
| `/model-performance` | GET | Accuracy dashboard (overall, by confidence/sport/league) |
| `/update-prediction-results` | GET/POST | Auto-update pending predictions with final scores |
| `/worldcup` | GET/POST | World Cup predictor |
| `/props` | GET | Player prop line builder UI |
| `/props/generate` | GET/POST | Generate prop lines (JSON) |
| `/health` | GET | Health check |

### NBA

| Route | Description |
|---|---|
| `/nba/` | NBA home — live scoreboard |
| `/nba/select` | Select NBA teams |
| `/nba/matchup` | NBA head-to-head analysis |
| `/nba/player` | NBA player comparison |
| `/nba/prediction` | NBA win probability |
| `/nba/today-predictions` | NBA predictions for today's/next games |
| `/nba/props` | NBA props page |
| `/nba/props/generate` | Generate NBA props (JSON/HTML) |
| `/nba/standings` | Current NBA standings |

### API endpoints

| Route | Description |
|---|---|
| `/api/football/leagues` | List supported leagues |
| `/api/football/teams` | Teams for a league |
| `/api/football/squad` | Squad list with positions |
| `/api/football/team-form` | Last-5 form string and rows for a team |
| `/api/player-stats` | Player season stats |
| `/chat` | POST — AI chatbot message |
| `/chat/clear` | POST — Clear chat history |

---

## Chatbot

The chat widget in the bottom-right corner of every page is powered by Claude (Anthropic). It has full conversation history and is tuned to help users navigate the app, understand predictions, and interpret stats.

**With `ANTHROPIC_API_KEY` set:** Powered by `claude-3-5-haiku-latest` with a ScorPred system prompt and up to 8-message history.

**Without the key:** Falls back to a rule-based responder that handles common questions about predictions, props, injuries, and navigation.

---

## Prediction Model

### Football (Poisson)

Weights for the 1X2 probability model:

| Factor | Weight |
|---|---|
| Recent form | 30% |
| Head-to-head record | 25% |
| Home/away advantage | 20% |
| Injury impact | 15% |
| Expected goals (xG proxy) | 10% |

Goals are then modelled with a Poisson distribution to produce:
- Win / draw / loss probabilities
- Correct score matrix (up to 6-6)
- Over/under probabilities
- First goalscorer candidates

### NBA (ScorPred Engine)

NBA predictions use the unified ScorPred engine and expose a single `scorpred` payload in templates/routes.

Weighted components:

| Factor | Weight |
|---|---|
| Recent form | 40% |
| Attack | 15% |
| Defense | 15% |
| Head-to-head | 10% |
| Venue (home/away) | 8% |
| Opponent quality | 7% |
| Squad availability | 5% |

Outputs include team scores (0-10 scale), win probabilities, confidence, best pick, key edges, and matchup reading.

### Props (6-layer model)

Each player prop line is built through six layers:

1. **Sample collection** — season stats, last 5 games, vs this opponent
2. **Core averages** — season mean, rolling weighted last-5
3. **Consistency** — standard deviation, hit rate, floor/ceiling
4. **Context modifiers** — home/away, position, opponent defensive rating
5. **Final projection** — weighted blend of layers 1-4
6. **Confidence score** — based on sample size and variance

---

## Caching

All API responses are cached as JSON files in the `cache/` directory. TTLs:

| Data type | TTL |
|---|---|
| Live scoreboard | 30 minutes |
| Current standings / fixtures | 1-2 hours |
| Season player stats | 1 hour |
| Historical / H2H | 6 hours |
| Career / multi-season | 24 hours |

Force a cache refresh on any page by appending `?refresh=1`.

Prediction tracking data is stored separately at `cache/prediction_tracking.json`.

---

## Running Tests

```bash
pytest -q
```

Tests use `unittest.mock` to patch API calls, so no live network APIs are required.

Useful targeted test runs:

```bash
pytest tests/test_routes.py tests/test_tracking_and_updater.py -q
>>>>>>> 62bd5ec8721b3dac5055a532ac430cfd8dbf4561
```

`fly launch` will detect the `Procfile` and configure the internal port correctly. The generated `fly.toml` works as-is; no edits required for a basic deployment.

### Post-deploy checks

```bash
# Smoke-test the live app (replace with your URL):
curl -o /dev/null -s -w "%{http_code}" https://your-app.onrender.com/
# Expected: 200

# Check the soccer fixtures endpoint (needs API_FOOTBALL_KEY):
curl -o /dev/null -s -w "%{http_code}" https://your-app.onrender.com/fixtures
# Expected: 200

# Check the NBA home (needs NBA_API_KEY):
curl -o /dev/null -s -w "%{http_code}" https://your-app.onrender.com/nba/
# Expected: 200
```

## Repository Layout

```text
app.py                  Main Flask app and route orchestration
nba_routes.py           NBA blueprint and views
predictor.py            Soccer history and form logic
scorpred_engine.py      Shared weighted recommendation engine
ml_pipeline.py          Leakage-safe ML comparison utilities
generate_ml_report.py   Saved ML comparison report generator
model_tracker.py        Prediction persistence and summary metrics
result_updater.py       Result reconciliation for completed games
props_engine.py         Prop recommendation helpers
services/               Extracted service modules for app composition
templates/              Jinja templates
static/                 Frontend assets
tests/                  Pytest suite
docs/                   Notes, screenshots, and supporting docs
```
