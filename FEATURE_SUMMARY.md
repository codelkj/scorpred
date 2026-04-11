# Two New Features Added to ScorPred

## FEATURE 1: Model Accuracy Tracker

### What It Does
Automatically tracks every prediction made by the Scorpred model and stores metrics to measure accuracy over time.

### Files Modified

**1. Created: `model_tracker.py`**
- Lightweight JSON-based tracking system (stored in `cache/prediction_tracking.json`)
- Functions:
  - `save_prediction()` - Records a new prediction when generated
  - `update_prediction_result()` - Updates prediction with actual game result when known
  - `get_summary_metrics()` - Computes: overall accuracy, accuracy by confidence level, accuracy by sport, recent predictions

**2. Modified: `app.py`**
- Added import: `import model_tracker as mt`
- Added tracking in `/prediction` route (football):
  ```python
  mt.save_prediction(
      sport="soccer",
      team_a=team_a["name"],
      team_b=team_b["name"],
      predicted_winner=pred_winner,
      win_probs=probs,
      confidence=conf,
  )
  ```
- Added new route: `@app.route("/model-performance")` - Shows performance dashboard

**3. Modified: `nba_routes.py`**
- Added import: `import model_tracker as mt`
- Added tracking in `/prediction` route (NBA):
  ```python
  mt.save_prediction(
      sport="nba",
      team_a=team_a.get("nickname") or team_a["name"],
      team_b=team_b.get("nickname") or team_b["name"],
      predicted_winner=pred_winner,
      win_probs=probs,
      confidence=conf,
  )
  ```

### New Route: `/model-performance`

**Display:**
- Overall accuracy percentage
- Finalized predictions count
- Accuracy breakdown by confidence level (High/Medium/Low)
- Accuracy breakdown by sport (Soccer/NBA)
- Recent predictions list (last 10)
  - Date, matchup, predicted winner
  - Win probabilities
  - Confidence level
  - Actual result (if available)
  - Status (Correct/Wrong/Pending)

**Template:** `templates/model_performance.html`
- Clean card-based UI
- Color-coded accuracy (green ≥55%, yellow 45-55%, red <45%)
- Empty state when no predictions exist yet

---

## FEATURE 2: NBA Today's Predictions Page

### What It Does
Shows all NBA games scheduled for today in a single view with predictions for each game.

### Files Modified

**Modified: `nba_routes.py`**
- Added new route: `@nba_bp.route("/today-predictions")`
  
**Route Logic:**
1. Fetches all NBA games for current day (`nc.get_today_games()`)
2. For each game:
   - Gets home and away team details
   - Fetches recent form (last 5 games)
   - Fetches head-to-head history
   - Fetches injury data
   - Builds opponent strength lookup from standings
   - **Runs unified Scorpred prediction** for the matchup
3. Extracts key prediction info: winner, probabilities, confidence, reasoning
4. Sorts games by confidence (High → Medium → Low) and probability gap
5. Passes to template for display

### New Route: `/nba/today-predictions`

**Features:**
- **Game Cards** - Each card shows:
  - Team logos and names
  - Kickoff time/date
  - Win probabilities (home % | away %)
  - **Confidence badge** (High/Medium/Low) - color-coded
  - Prediction pick and reasoning
  - **Clickable** - clicking card opens detailed matchup analysis page

- **Sorting**: Strongest picks first (ordered by confidence + probability gap)

- **Summary Stats** at bottom:
  - Count of High, Medium, Low confidence picks
  - Total games vs. predictions with data

- **Empty State**: Friendly message if no games today

**Template:** `templates/nba/today_predictions.html`
- Responsive card layout (6-col on lg, 4-col on xl)
- Hover effects on game cards
- Color-coded confidence badges
- Quick navigation to detailed analysis pages

---

## Data Flow

### Prediction Tracking Flow
```
User generates prediction (Football or NBA)
    ↓
Scorpred Engine calculates model scores
    ↓
Extract: winner, probabilities, confidence
    ↓
save_prediction(sport, teams, winner, probs, confidence)
    ↓
Store in cache/prediction_tracking.json
    ↓
Later: Fetch final game result →
update_prediction_result(pred_id, actual_result)
    ↓
Accuracy metrics update automatically
```

### Today's Predictions Flow
```
User visits /nba/today-predictions
    ↓
Fetch all games for today
    ↓
For each game:
  - Fetch form, H2H, injuries
  - Build opponent strength
  - Run Scorpred prediction
    ↓
Display cards sorted by confidence
    ↓
User clicks card → Goes to /nba/matchup (deeper analysis)
```

---

## Integration Points

### 1. Football Prediction (`/prediction`)
- ✅ Automatically tracks each prediction
- ✅ No changes to existing UI
- ✅ Tracking happens silently in background

### 2. NBA Prediction (`/nba/prediction`)
- ✅ Automatically tracks each prediction
- ✅ No changes to existing UI
- ✅ Tracking happens silently in background

### 3. New Pages
- ✅ `/model-performance` - View all metrics
- ✅ `/nba/today-predictions` - View today's games with predictions
- ✅ Both link to each other for easy navigation

---

## Tech Details

### Tracking Storage Format
```json
{
  "predictions": [
    {
      "id": "abc12345",
      "sport": "nba",
      "date": "2026-04-11",
      "team_a": "Lakers",
      "team_b": "Celtics",
      "predicted_winner": "A",
      "prob_a": 68.5,
      "prob_b": 31.5,
      "prob_draw": 0.0,
      "confidence": "High",
      "actual_result": "A",
      "is_correct": true,
      "created_at": "2026-04-11T10:30:00Z",
      "updated_at": "2026-04-11T14:45:00Z"
    }
  ]
}
```

### Metrics Calculation
- **Overall Accuracy**: (correct predictions / finalized predictions) × 100
- **By Confidence**: Same calculation, grouped by confidence level
- **By Sport**: Same calculation, grouped by sport
- Only predictions with `is_correct` set are included in accuracy calculation

---

## Testing Checklist

- [ ] Generate a football prediction → stored in tracking.json
- [ ] Generate an NBA prediction → stored in tracking.json
- [ ] Visit `/model-performance` → shows stats and recent predictions
- [ ] Visit `/nba/today-predictions` → shows all today's games with predictions
- [ ] Click a game card → goes to `/nba/matchup` page
- [ ] Verify probabilities sum to 100% (soccer: a + draw + b = 100)
- [ ] Verify probabilities sum to 100% (NBA: a + b = 100)
- [ ] Check that all games are shown (or if none, empty state displays)

---

## Key Implementation Notes

1. **Single Model Only**: Uses ONLY the unified Scorpred Engine (no old prediction models)
2. **Non-Breaking**: All changes are additive - existing routes/features unchanged
3. **Lightweight**: JSON storage, no database needed
4. **Silent Tracking**: Prediction capture doesn't interfere with normal flow
5. **Error Handling**: Tracking failures don't break prediction routes
6. **Responsive UI**: Templates work on mobile and desktop
7. **Easy Navigation**: Model performance and today's games link to each other

---

## Future Enhancements (Optional)

- Add SQLite backend for faster querying of large datasets
- Add prediction filtering/search on /model-performance
- Add game result manual entry UI for when API results aren't available yet
- Add chart visualizations (accuracy over time, by sport, etc.)
- Add export CSV functionality
- Add comparison: Scorpred vs other prediction sources
