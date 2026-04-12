# ScorPred

A football and NBA sports prediction web app built with Flask. Provides head-to-head analysis, win probability predictions, player prop line generation, live standings, and an AI-powered chatbot assistant.

---

## Features

| Feature | Description |
|---|---|
| **Football Matchup** | H2H history, form tables, home/away splits, injury reports |
| **Win Prediction** | Poisson distribution model weighted by form, H2H, home advantage, and injuries |
| **Player Props** | 6-layer statistical prop line builder (season avg, last-5, vs-opponent, consistency, context, confidence) |
| **Fixtures** | Upcoming fixtures with quick standings-based predictions |
| **NBA Section** | Full NBA module — scoreboard, standings, matchup, players, predictions |
| **World Cup** | World Cup fixture viewer and team vs team predictor |
| **AI Chatbot** | Claude-powered assistant with conversation history (falls back gracefully without API key) |

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd ScorPred
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

### 3. Run the app

```bash
python app.py
# Visit http://localhost:5001 (or PORT if set)
```

---

## Environment Variables

Copy `.env.example` to `.env` and set the following:

| Variable | Required | Description |
|---|---|---|
| `API_FOOTBALL_KEY` | Recommended | RapidAPI key for API-Football (fallback sources are used when missing) |
| `NBA_API_KEY` | Recommended | RapidAPI key for NBA data (fallback sources are used when missing) |
| `ANTHROPIC_API_KEY` | No | Enables Claude AI chatbot (falls back to rule-based replies without it) |
| `SECRET_KEY` | Yes (production) | Flask session secret — change to a long random string in production |
| `FLASK_DEBUG` | No | Set to `1` for debug mode (default: `0`) |
| `PORT` | No | Server port (default: `5001`) |

Get your RapidAPI key at [rapidapi.com](https://rapidapi.com). The app requires:
- `api-football-v1.p.rapidapi.com` — Football data
- `nba-api-free-data.p.rapidapi.com` — NBA data

Get your Anthropic API key at [console.anthropic.com](https://console.anthropic.com).

---

## Project Structure

```
ScorPred/
├── app.py                  # Main Flask app — football routes, chat, props
├── nba_routes.py           # NBA Blueprint (/nba prefix)
├── api_client.py           # API-Football + ESPN wrapper with caching
├── nba_client.py           # NBA RapidAPI wrapper
├── nba_live_client.py      # ESPN public feed NBA client (no auth needed)
├── predictor.py            # Football prediction logic (Poisson model)
├── nba_predictor.py        # NBA win probability model
├── props_engine.py         # 6-layer player prop line calculator
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
| `/worldcup` | GET/POST | World Cup predictor |
| `/props` | GET | Player prop line builder UI |
| `/props/generate` | GET/POST | Generate prop lines (JSON) |

### NBA

| Route | Description |
|---|---|
| `/nba/` | NBA home — live scoreboard |
| `/nba/select` | Select NBA teams |
| `/nba/matchup` | NBA head-to-head analysis |
| `/nba/player` | NBA player comparison |
| `/nba/prediction` | NBA win probability |
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

---

## Running Tests

```bash
pytest -q
```

Tests use `unittest.mock` to patch API calls, so no live network APIs are required.

---

## Supported Football Leagues

- Premier League (England)
- La Liga (Spain)
- Bundesliga (Germany)
- Serie A (Italy)
- Ligue 1 (France)
- Eredivisie (Netherlands)
- Primeira Liga (Portugal)
- Championship (England)
- MLS (USA)
- UEFA Champions League
- UEFA Europa League
- Copa del Rey
- FA Cup

---

## Tech Stack

- **Backend:** Python 3.11+, Flask 3.1
- **Data:** RapidAPI (API-Football, NBA), ESPN public feeds
- **AI:** Anthropic Claude (claude-3-5-haiku-latest)
- **Frontend:** Jinja2, Tailwind CSS (CDN), GSAP, Chart.js, Particles.js
- **Caching:** Filesystem JSON cache (no database required)
- **Tests:** pytest + unittest.mock

---

## Notes

- Predictions are for informational purposes only — not financial advice.
- The free RapidAPI tier has rate limits. The app handles 429 errors with automatic backoff and ESPN fallback data.
- Always confirm lineups, injuries, and odds from official sources before acting on any prediction.
