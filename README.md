# ScorPred

ScorPred is a Flask app for soccer and NBA predictions, matchup analysis, props context, and result tracking.

The app combines live API data with locally trained models. For soccer, the training pipeline builds a leakage-safe feature set from `data/historical_matches.csv` and trains an ensemble model before deploy.

## What Is In This Repo

- Flask app and templates in `app.py`, `templates/`, and `static/`
- Model training pipeline in `train_model.py`
- Shared runtime paths in `runtime_paths.py`
- Historical and generated data under `data/`
- Tests under `tests/`
- Render deployment config in `render.yaml`

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in the keys you want to use.
4. Run the app:

```bash
python app.py
```

The default local URL is `http://127.0.0.1:5000`.

## Training The Soccer Model

Train from the bundled historical dataset:

```bash
python -X utf8 train_model.py
```

Expected inputs and outputs:

- Input dataset: `data/historical_matches.csv`
- Trained model: `data/models/soccer_ensemble_stack.pkl`
- ELO state: `data/processed/soccer_elo_state.json`
- Clean training dataset: `data/processed/soccer_training_data_clean.csv`

## Environment Variables

Core variables:

- `SECRET_KEY`: Flask session and CSRF secret
- `API_FOOTBALL_KEY`: soccer data provider key
- `NBA_API_KEY`: NBA data provider key
- `ANTHROPIC_API_KEY`: optional, enables Claude-backed chat responses
- `ODDS_API_KEY`: optional, enables odds/edge enrichment in matchup views

Optional storage variable:

- `SCORPRED_DATA_ROOT`: override the runtime data root. When unset, the app uses the repository root.

## Render Deploy Notes

The Render deploy is designed to:

1. Install dependencies
2. Train the soccer model during the build
3. Start Gunicorn with `app:app`
4. Use `/health` for health checks

Important notes:

- `SECRET_KEY` is defined in `render.yaml` with `generateValue: true`, so Render can create one automatically if the service does not already have it.
- Build artifacts are written under the app directory so the trained model is available at runtime.
- Render's default filesystem is ephemeral across redeploys and restarts. If you need long-lived local files, use a persistent disk or a managed datastore.

## Testing

Run the test suite with:

```bash
pytest tests -q
```

Lint with:

```bash
ruff check .
```

## Project Structure

```text
scorpred/
  app.py
  train_model.py
  runtime_paths.py
  render.yaml
  requirements.txt
  static/
  templates/
  tests/
  data/
```
