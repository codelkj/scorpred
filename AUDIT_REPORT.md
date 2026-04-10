# ScorPred Audit Report
Generated: 2026-04-09 19:45:29

## Phase Results
- Phase 1 Environment: PASS
- Phase 2 api_client.py: PASS
- Phase 3 API Data Flow: 11/11 checks passing
- Phase 4 nba_client.py: PASS
- Phase 5 Templates: 10/10 templates fixed
- Phase 6 Routes: 17/17 routes working
- Phase 7 Charts: PASS
- Phase 8 Mobile: PASS
- Phase 9 End to End: 4/4 routes passing

## Data Verified Working
- Football `get_teams(39, 2024)` returning 20 Premier League teams
- Football `get_standings(39, 2024)` returning 20 table rows
- Football `get_team_fixtures(33, 39, 2024, 5)` returning recent Manchester United fixtures
- Football `get_h2h(33, 66, 5)` returning Manchester United vs Aston Villa history
- Football `get_player_stats(276, 39, 2024)` returning Bruno Fernandes season data
- Football `get_squad(33)` returning Manchester United squad data
- Football `get_top_scorers(39, 2024)` returning Premier League scorers
- Football `get_injuries(39, 2024, 33)` returning injury status or graceful no-injury placeholder
- Football `get_opponent_defensive_stats(50, 39, 2024)` returning team defensive profile
- Football `get_teams(140, 2024)` returning La Liga teams
- Football `get_teams(2, 2024)` returning Champions League teams
- Football app routes `/`, `/matchup`, `/player`, `/prediction`, `/props`, `/props/generate`, `/chat`, `/chat/clear`
- NBA `get_teams()` returning 30 teams
- NBA standings route `/nba/standings` returning live conference tables
- NBA home route `/nba/` returning live and upcoming games
- NBA matchup, player, and prediction routes rendering with live roster, schedule, standings, and injury data
- NBA player analysis routes `/nba/player/analyze` and `/nba/api/player-analysis` returning live player overview data

## Still Limited by Free API Tier
- The supplied API-Football RapidAPI key is not subscribed to the paid API-Football plan, so football live data is served through ESPN public fallback endpoints where needed
- Full API-Football fixture-level stats, events, and player-by-player coverage can still be thinner than a subscribed API-Football plan
- NBA public feeds do not provide full paid-tier player game-log depth and opponent-specific prop modeling, so NBA player analysis falls back to season averages, recent public game logs, and limited-data warnings
- Official sportsbook odds and market pricing are not provided by the current free feeds

## App Status
READY

## Recommended Next Steps
- Upgrade the API-Football subscription if you want full native fixture stats, events, and player detail without ESPN fallback
- Add automated browser tests for the football and NBA flows now that the route and data layers are stable
- Add a dedicated NBA paid data source if you want deeper opponent-specific player props and richer last-10 game modeling
