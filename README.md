# ScorPred

ScorPred is a Flask app for soccer and NBA matchup analysis. It combines fixture data, recent form, head-to-head context, team stats, player props tooling, tracking, and a lightweight chat assistant into a single local web app.

Status: active development. The current local baseline is `111` passing tests. Basic CI, CSRF protection, stronger secret handling, chat rate limiting, and a leakage-safe ML comparison utility are now in place, but the repo is still not production-ready yet.

## Features

- Soccer matchup analysis with form, H2H, injuries, standings context, and prediction pages
- NBA scoreboard, matchup, player, and prediction routes backed by the live ESPN-based client
- JSON-backed prediction tracking and result reconciliation
- Player prop generation for NBA and soccer
- Leakage-safe ML model comparison utilities for logistic regression vs. random forest baselines
- Filesystem caching for upstream API responses
- Chat assistant with Anthropic support and a graceful fallback mode

## Quick Start

```bash
git clone <your-repo-url>
cd ScorPred
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Visit `http://localhost:5000`.

## Environment Variables

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|---|---|---|
| `API_FOOTBALL_KEY` | Yes | RapidAPI key for football data |
| `NBA_API_KEY` | Yes | RapidAPI key for NBA data used by legacy/props flows |
| `ANTHROPIC_API_KEY` | No | Enables the chat assistant's Anthropic mode |
| `SECRET_KEY` | Yes | Flask session secret |
| `FLASK_DEBUG` | No | Set to `1` for debug mode |
| `PORT` | No | App port, default `5000` |

## Project Layout

```text
app.py                  Main Flask app for soccer routes, chat, and tracking pages
nba_routes.py           NBA blueprint and route handlers
api_client.py           Soccer data client and caching layer
predictor.py            Soccer prediction and history logic
scorpred_engine.py      Shared prediction/explainability logic
model_tracker.py        Prediction persistence and summary metrics
result_updater.py       Result reconciliation for completed games
nba_live_client.py      Current NBA route data client
nba_client.py           Legacy NBA compatibility helpers used by props/live adapters
props_engine.py         Player props engine
ml_pipeline.py          Leakage-safe ML model comparison helpers
templates/              Jinja templates
static/                 Frontend assets
tests/                  Pytest suite
docs/                   Historical implementation notes and audits
```

The home route renders `templates/home.html`. The older duplicate `templates/index.html` has been removed.

## Key Routes

### Soccer

- `/` home page
- `/soccer` team and fixture selection
- `/matchup` detailed matchup analysis
- `/prediction` soccer prediction page
- `/fixtures` upcoming fixtures
- `/props` player props UI
- `/model-performance` prediction tracking dashboard

### NBA

- `/nba/` scoreboard and landing page
- `/nba/matchup` matchup analysis
- `/nba/player` player analysis
- `/nba/prediction` prediction page
- `/nba/standings` conference standings

## Testing

Run the suite with:

```bash
pytest tests -q
```

Current local baseline:

```text
111 passed
```

Tests use mocks for external APIs, so the suite does not depend on live network responses.

## Notes

- Predictions are informational and should not be treated as betting advice.
- The app still contains some legacy compatibility modules while the repo is being cleaned up incrementally.
- Cached API responses are created on demand under `cache/` and should not be committed.
