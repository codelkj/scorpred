"""
test_props.py — Unit tests for props_engine.py

Tests the projection formula and all statistical layers with controlled mock data.
Run with:  python -m pytest test_props.py -v
       or: python test_props.py
"""

import math
import sys
import unittest

import props_engine as pe


# ── Mock data factories ────────────────────────────────────────────────────────

def _nba_game(pts, reb, ast, stl=1, blk=0, tpm=1, tov=2, minutes="32:00"):
    """Build a minimal NBA per-game record in API-NBA format."""
    return {
        "game": {"id": 1},
        "statistics": [{
            "points":    pts,
            "rebounds":  reb,
            "assists":   ast,
            "steals":    stl,
            "blocks":    blk,
            "tpm":       tpm,
            "turnovers": tov,
            "min":       minutes,
            "fgm": 8, "fga": 18, "ftm": 4, "fta": 5,
            "tpa": 3, "offReb": 1, "defReb": reb - 1,
        }],
    }


def _soccer_game(goals=0, assists=0, shots_on=2, key_passes=3, minutes=87,
                 home_id=33, away_id=66, date="2024-11-01"):
    """Build a minimal soccer per-game record (flat dict from props_engine)."""
    return {
        "fixture_id":     1000,
        "date":           date,
        "home_id":        home_id,
        "away_id":        away_id,
        "goals":          goals,
        "assists":        assists,
        "shots_on_target":shots_on,
        "key_passes":     key_passes,
        "dribbles":       1,
        "tackles":        2,
        "yellow_cards":   0,
        "minutes":        minutes,
    }


# ── 1. Helper / math tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_round_half(self):
        self.assertEqual(pe._round_half(24.8), 25.0)
        self.assertEqual(pe._round_half(25.1), 25.0)
        self.assertEqual(pe._round_half(25.4), 25.5)
        self.assertEqual(pe._round_half(25.6), 25.5)
        self.assertEqual(pe._round_half(25.75), 26.0)

    def test_weighted_avg_all_present(self):
        # All weights present → standard weighted mean
        result = pe._weighted_avg([(10.0, 0.25), (20.0, 0.30), (15.0, 0.15),
                                    (12.0, 0.20), (11.0, 0.10)])
        expected = 10*0.25 + 20*0.30 + 15*0.15 + 12*0.20 + 11*0.10
        self.assertAlmostEqual(result, expected, places=4)

    def test_weighted_avg_missing_value(self):
        # One None → weight redistributed proportionally to remaining
        result = pe._weighted_avg([(10.0, 0.50), (None, 0.30), (20.0, 0.20)])
        # Valid weights: 0.50 + 0.20 = 0.70; redistributed: 10*(0.50/0.70) + 20*(0.20/0.70)
        expected = 10 * (0.50 / 0.70) + 20 * (0.20 / 0.70)
        self.assertAlmostEqual(result, expected, places=4)

    def test_weighted_avg_all_none(self):
        self.assertIsNone(pe._weighted_avg([(None, 0.5), (None, 0.5)]))

    def test_std_dev(self):
        values = [20.0, 25.0, 30.0, 22.0, 28.0]
        result = pe._std_dev(values)
        self.assertAlmostEqual(result, 4.074, places=1)

    def test_hit_rate(self):
        values = [20, 25, 30, 18, 24, 22, 26, 19, 27, 23]
        hits, total = pe._hit_rate(values, 22.0)
        self.assertEqual(total, 10)
        over_22 = sum(1 for v in values if v >= 22.0)
        self.assertEqual(hits, over_22)

    def test_weighted_rolling_avg(self):
        # 10 values most-recent first
        # last3 (indices 0-2): [30, 28, 32] → avg 30.0
        # mid4  (indices 3-6): [25, 24, 26, 23] → avg 24.5
        # last3 (indices 7-9): [20, 22, 21] → avg 21.0
        values = [30, 28, 32, 25, 24, 26, 23, 20, 22, 21]
        result = pe._weighted_rolling_avg(values)
        expected = 30.0 * 0.50 + 24.5 * 0.30 + 21.0 * 0.20
        self.assertAlmostEqual(result, expected, places=1)

    def test_lean_over(self):
        # adjusted 27.2 vs line 25.0 → ratio 1.088 > 1.08 threshold → OVER
        self.assertEqual(pe._lean(27.2, 25.0), "OVER")

    def test_lean_under(self):
        # adjusted 22.0 vs line 25.0 → ratio 0.88 < 0.92 → UNDER
        self.assertEqual(pe._lean(22.0, 25.0), "UNDER")

    def test_lean_push(self):
        # adjusted 25.4 vs line 25.5 → ratio ≈ 0.996 → PUSH (within 8%)
        self.assertEqual(pe._lean(25.4, 25.5), "PUSH")
        self.assertEqual(pe._lean(25.9, 25.5), "PUSH")   # 1.0157 < 1.08

    def test_lean_over_8pct(self):
        # 25.5 * 1.08 = 27.54 → need adjusted > 27.54 for OVER
        self.assertEqual(pe._lean(27.6, 25.5), "OVER")
        self.assertEqual(pe._lean(27.5, 25.5), "PUSH")


# ── 2. Layer 2 — Core Averages ─────────────────────────────────────────────────

class TestCoreAverages(unittest.TestCase):

    def _make_nba_samples(self, game_log, vs_log=None):
        return {
            "sport":            "nba",
            "player_id":        2544,
            "player_team_id":   17,
            "opponent_team_id": 2,
            "season":           2024,
            "full_season_log":  game_log,
            "last5":            game_log[-5:] if len(game_log) >= 5 else game_log,
            "last10":           game_log[-10:] if len(game_log) >= 10 else game_log,
            "vs_opponent":      {
                "games":         len(vs_log or []),
                "records":       vs_log or [],
                "averages":      None,
                "limited_sample": len(vs_log or []) < 3,
            },
            "team_injuries":    [],
        }

    def test_season_avg(self):
        games = [_nba_game(pts=p, reb=5, ast=7) for p in [20, 25, 30, 22, 28, 24, 26, 19, 27, 23]]
        samples = self._make_nba_samples(games)
        avgs = pe._build_core_averages(samples, "points", is_home=True, sport="nba")
        expected_season = sum([20, 25, 30, 22, 28, 24, 26, 19, 27, 23]) / 10
        self.assertAlmostEqual(avgs["season_avg"], expected_season, places=1)

    def test_last5_avg(self):
        pts = [20, 25, 30, 22, 28, 24, 26, 19, 27, 23]
        games = [_nba_game(pts=p, reb=5, ast=7) for p in pts]
        samples = self._make_nba_samples(games)
        avgs = pe._build_core_averages(samples, "points", is_home=True, sport="nba")
        expected_l5 = sum(pts[-5:]) / 5
        self.assertAlmostEqual(avgs["last5_avg"], expected_l5, places=1)

    def test_vs_opponent_avg(self):
        all_games = [_nba_game(pts=25, reb=7, ast=8)] * 10
        vs_games  = [_nba_game(pts=23, reb=6, ast=7)] * 5
        samples   = self._make_nba_samples(all_games, vs_log=vs_games)
        avgs = pe._build_core_averages(samples, "points", is_home=True, sport="nba")
        self.assertAlmostEqual(avgs["vs_opponent_avg"], 23.0, places=1)
        self.assertEqual(avgs["vs_opponent_games"], 5)

    def test_missing_vs_opponent_excluded_from_base(self):
        """When vs_opponent is None, weight redistributed to other sources."""
        games = [_nba_game(pts=25, reb=7, ast=8)] * 10
        samples = self._make_nba_samples(games, vs_log=[])
        avgs  = pe._build_core_averages(samples, "points", is_home=True, sport="nba")
        base  = pe._base_projection(
            avgs["season_avg"], avgs["last5_avg"], avgs["last10_avg"],
            avgs["vs_opponent_avg"], avgs["active_ha_avg"]
        )
        # Should still produce a valid projection even without vs_opp data
        self.assertGreater(base, 0)


# ── 3. Layer 3 — Variance Analysis ────────────────────────────────────────────

class TestVariance(unittest.TestCase):

    def _samples_with_log(self, log):
        return {
            "sport": "nba",
            "full_season_log": log,
            "last10": log[-10:] if len(log) >= 10 else log,
            "per_game_log": [],
        }

    def test_hit_rate_7_of_10(self):
        # 7 games >= 25.0, 3 games below
        pts = [26, 28, 30, 24, 27, 29, 22, 26, 20, 25]
        games = [_nba_game(pts=p, reb=5, ast=7) for p in pts]
        samples = self._samples_with_log(games)
        vrn = pe._build_variance(samples, "points", line=25.0, sport="nba")
        self.assertEqual(vrn["hit_count"],   sum(1 for p in pts[-10:] if p >= 25.0))
        self.assertEqual(vrn["sample_games"], 10)

    def test_ceiling_floor(self):
        pts = [15, 20, 38, 22, 28, 24, 16, 19, 27, 23]
        games = [_nba_game(pts=p, reb=5, ast=7) for p in pts]
        samples = self._samples_with_log(games)
        vrn = pe._build_variance(samples, "points", line=22.0, sport="nba")
        self.assertEqual(vrn["ceiling"], max(pts))
        self.assertEqual(vrn["floor"],   min(pts))

    def test_boom_bust_rates(self):
        # line=20.0; boom = >= 30 (150%); bust = <= 10 (50%)
        pts = [30, 35, 8, 20, 22, 31, 9, 25, 20, 21]  # 3 boom, 2 bust
        games = [_nba_game(pts=p, reb=5, ast=7) for p in pts]
        samples = self._samples_with_log(games)
        vrn = pe._build_variance(samples, "points", line=20.0, sport="nba")
        expected_boom = sum(1 for p in pts if p >= 30.0)
        expected_bust = sum(1 for p in pts if p <= 10.0)
        self.assertEqual(round(vrn["boom_rate_pct"]), round(expected_boom / 10 * 100))
        self.assertEqual(round(vrn["bust_rate_pct"]), round(expected_bust / 10 * 100))

    def test_std_deviation(self):
        import statistics as stats_mod
        pts = [20, 25, 30, 22, 28, 24, 26, 19, 27, 23]
        games = [_nba_game(pts=p, reb=5, ast=7) for p in pts]
        samples = self._samples_with_log(games)
        vrn = pe._build_variance(samples, "points", line=24.0, sport="nba")
        expected_sd = stats_mod.stdev(pts)
        self.assertAlmostEqual(vrn["std_dev"], expected_sd, places=1)


# ── 4. Layer 4 — Contextual Modifiers ─────────────────────────────────────────

class TestModifiers(unittest.TestCase):

    def test_trend_hot_streak(self):
        # last3 > season by >20% → +10% bonus
        mult, raw, label = pe._trend_modifier(last3_avg=30.0, season_avg=24.0)
        # (30-24)/24 = 0.25 > 0.20 → hot streak
        self.assertAlmostEqual(mult, 1.10, places=3)
        self.assertIn("hot", label.lower())

    def test_trend_cold_streak(self):
        # last3 < season by >20% → -10% penalty
        mult, raw, label = pe._trend_modifier(last3_avg=18.0, season_avg=24.0)
        # (18-24)/24 = -0.25 < -0.20 → cold streak
        self.assertAlmostEqual(mult, 0.90, places=3)
        self.assertIn("cold", label.lower())

    def test_trend_neutral(self):
        mult, raw, label = pe._trend_modifier(last3_avg=24.5, season_avg=24.0)
        # only 2% diff → neutral or slight
        self.assertGreaterEqual(mult, 0.97)
        self.assertLessEqual(mult, 1.03)

    def test_trend_none_inputs(self):
        mult, raw, label = pe._trend_modifier(None, 24.0)
        self.assertEqual(mult, 1.0)

    def test_home_away_modifier_home_boost(self):
        # home_avg=27, away_avg=23 → at home should boost
        mult, raw, label = pe._home_away_modifier(27.0, 23.0, is_home=True, base_proj=25.0)
        self.assertGreater(mult, 1.0)

    def test_home_away_modifier_away_penalty(self):
        # home_avg=27, away_avg=23 → away should penalise
        mult, raw, label = pe._home_away_modifier(27.0, 23.0, is_home=False, base_proj=25.0)
        self.assertLess(mult, 1.0)

    def test_nba_opponent_modifier_tough(self):
        # opponent PPG allowed well below season avg → tough → multiplier < 1
        opp_stats = {"opp_ppg": 105.0, "net_rtg": 5.0}
        mult, raw, label = pe._opponent_modifier_nba(opp_stats, "points", season_avg=25.0)
        self.assertLessEqual(mult, 1.0)
        self.assertIn("tough", label)

    def test_nba_opponent_modifier_weak(self):
        # opponent PPG allowed well above league avg → easy → multiplier > 1
        opp_stats = {"opp_ppg": 125.0, "net_rtg": -8.0}
        mult, raw, label = pe._opponent_modifier_nba(opp_stats, "points", season_avg=25.0)
        self.assertGreater(mult, 1.0)
        self.assertIn("weak", label)

    def test_injury_modifier_key_player_out(self):
        injuries = [
            {"player": {"id": 99}, "status": "out"},
            {"player": {"id": 88}, "status": "out"},
        ]
        mult, raw, label = pe._injury_modifier(injuries, player_id=2544)
        self.assertLess(mult, 1.0)

    def test_injury_modifier_no_injuries(self):
        mult, raw, label = pe._injury_modifier([], player_id=2544)
        self.assertEqual(mult, 1.0)


# ── 5. Layer 5 — Projection Formula ───────────────────────────────────────────

class TestProjectionFormula(unittest.TestCase):

    def test_base_projection_all_inputs(self):
        """Full formula: (season×0.25 + last5×0.30 + last10×0.15 + vsOpp×0.20 + H/A×0.10)"""
        season=24.8; l5=27.2; l10=25.6; vs=23.1; ha=23.9
        result = pe._base_projection(season, l5, l10, vs, ha)
        expected = season*0.25 + l5*0.30 + l10*0.15 + vs*0.20 + ha*0.10
        self.assertAlmostEqual(result, expected, places=2)

    def test_base_projection_missing_vs_opponent(self):
        """Missing vs_opponent redistributes its 0.20 weight proportionally."""
        season=24.8; l5=27.2; l10=25.6; vs=None; ha=23.9
        result = pe._base_projection(season, l5, l10, vs, ha)
        # Available weights: 0.25+0.30+0.15+0.10 = 0.80
        # Redistribute: season 0.25/0.80, l5 0.30/0.80, l10 0.15/0.80, ha 0.10/0.80
        total_w = 0.25 + 0.30 + 0.15 + 0.10
        expected = (season * 0.25 + l5 * 0.30 + l10 * 0.15 + ha * 0.10) / total_w
        self.assertAlmostEqual(result, expected, places=2)

    def test_base_projection_only_season(self):
        """When only season_avg is present, it carries full weight."""
        result = pe._base_projection(24.8, None, None, None, None)
        self.assertAlmostEqual(result, 24.8, places=2)

    def test_apply_modifiers_multiplicative(self):
        """Modifiers are multiplied together (all multiplicative)."""
        mods = [
            {"multiplier": 0.97},
            {"multiplier": 1.10},
            {"multiplier": 1.05},
        ]
        base = 25.4
        result = pe._apply_all_modifiers(base, mods)
        expected = round(25.4 * 0.97 * 1.10 * 1.05, 2)
        self.assertAlmostEqual(result, expected, places=2)

    def test_pra_correlation_discount(self):
        """PRA projection applies -3% correlation discount."""
        result = pe._pra_projection(25.0, 8.0, 7.5)
        expected = round((25.0 + 8.0 + 7.5) * 0.97, 2)
        self.assertAlmostEqual(result, expected, places=2)

    def test_pra_none_components(self):
        """PRA with one None component still returns a value."""
        result = pe._pra_projection(25.0, None, 7.5)
        # Only pts + ast available
        expected = round((25.0 + 7.5) * 0.97, 2)
        self.assertAlmostEqual(result, expected, places=2)

    def test_full_projection_lebron_scenario(self):
        """
        End-to-end test with LeBron-like numbers.
        Uses the exact formula from the spec:
          base = (24.8×0.25) + (27.2×0.30) + (25.6×0.15) + (23.1×0.20) + (23.9×0.10)
        Then modifiers applied multiplicatively.
        """
        season=24.8; l5=27.2; l10=25.6; vs=23.1; ha=23.9
        base = pe._base_projection(season, l5, l10, vs, ha)

        # Modifiers from spec example
        mods = [
            {"multiplier": 0.97},   # tough defence  −3%
            {"multiplier": 0.98},   # away game       −2%
            {"multiplier": 1.10},   # hot streak     +10%
            {"multiplier": 1.05},   # minutes up      +5%
            {"multiplier": 1.00},   # no injuries
        ]
        adjusted = pe._apply_all_modifiers(base, mods)
        line     = pe._round_half(adjusted)

        # The projection should be in a reasonable range (22–32)
        self.assertGreater(adjusted, 20.0)
        self.assertLess(adjusted, 35.0)
        # Line should be a half-integer
        self.assertEqual(line * 2, round(line * 2))

        expected_base = 24.8*0.25 + 27.2*0.30 + 25.6*0.15 + 23.1*0.20 + 23.9*0.10
        self.assertAlmostEqual(base, expected_base, places=2)


# ── 6. Layer 6 — Confidence Score ─────────────────────────────────────────────

class TestConfidenceScore(unittest.TestCase):

    def test_max_confidence(self):
        """All inputs perfect → confidence near 100."""
        vrn = {"std_dev_pct": 15, "hit_rate_pct": 75, "sample_games": 10}
        conf = pe._confidence_score(
            vs_opp_games=12,
            variance=vrn,
            lean="OVER",
            last5_avg=28.0,
            vs_opp_avg=25.0,
            modifiers=[{"multiplier": 1.10}, {"multiplier": 1.05}],
            season_avg=24.0,
        )
        # sample=20, consistency=20, hit_rate=20, trend=20 (both agree over), ctx=20 → 100
        self.assertGreaterEqual(conf["score"], 75)
        self.assertIn("Elite" if conf["score"] >= 80 else "Strong", conf["label"])

    def test_poor_confidence_no_data(self):
        """No vs-opponent data, high variance, low hit rate → poor confidence."""
        vrn = {"std_dev_pct": 80, "hit_rate_pct": 20, "sample_games": 10}
        conf = pe._confidence_score(
            vs_opp_games=0,
            variance=vrn,
            lean="OVER",
            last5_avg=20.0,
            vs_opp_avg=None,
            modifiers=[],
            season_avg=24.0,
        )
        self.assertLess(conf["score"], 40)

    def test_sample_size_scoring(self):
        """Test each sample-size band."""
        base_vrn = {"std_dev_pct": 20, "hit_rate_pct": 60, "sample_games": 10}
        base_kw = dict(variance=base_vrn, lean="PUSH", last5_avg=None, vs_opp_avg=None,
                       modifiers=[], season_avg=24.0)

        c10 = pe._confidence_score(vs_opp_games=10, **base_kw)["components"]["sample_size"]
        c7  = pe._confidence_score(vs_opp_games=7,  **base_kw)["components"]["sample_size"]
        c3  = pe._confidence_score(vs_opp_games=3,  **base_kw)["components"]["sample_size"]
        c0  = pe._confidence_score(vs_opp_games=0,  **base_kw)["components"]["sample_size"]

        self.assertEqual(c10, 20)
        self.assertEqual(c7, 15)
        self.assertEqual(c3, 8)
        self.assertEqual(c0, 3)

    def test_hit_rate_scoring(self):
        """Hit rate bands mapped correctly."""
        def _hit_pts(hit_pct):
            vrn = {"std_dev_pct": 20, "hit_rate_pct": hit_pct, "sample_games": 10}
            return pe._confidence_score(0, vrn, "PUSH", None, None, [], 24.0)["components"]["hit_rate"]

        self.assertEqual(_hit_pts(80), 20)
        self.assertEqual(_hit_pts(65), 15)
        self.assertEqual(_hit_pts(45), 8)
        self.assertEqual(_hit_pts(20), 3)

    def test_trend_alignment_both_agree(self):
        """Both last5 and vs_opp above season → lean OVER → both agree → 20pts."""
        vrn = {"std_dev_pct": 20, "hit_rate_pct": 60, "sample_games": 10}
        conf = pe._confidence_score(
            vs_opp_games=5,
            variance=vrn,
            lean="OVER",
            last5_avg=28.0,    # > season_avg → agrees OVER
            vs_opp_avg=26.0,   # > season_avg → agrees OVER
            modifiers=[],
            season_avg=24.0,
        )
        self.assertEqual(conf["components"]["trend_alignment"], 20)

    def test_trend_alignment_neither_agrees(self):
        """Both last5 and vs_opp below season → lean OVER → neither agrees → 0pts."""
        vrn = {"std_dev_pct": 20, "hit_rate_pct": 60, "sample_games": 10}
        conf = pe._confidence_score(
            vs_opp_games=5,
            variance=vrn,
            lean="OVER",
            last5_avg=21.0,    # < season_avg → disagrees
            vs_opp_avg=20.0,   # < season_avg → disagrees
            modifiers=[],
            season_avg=24.0,
        )
        self.assertEqual(conf["components"]["trend_alignment"], 0)

    def test_confidence_labels(self):
        self.assertEqual(pe._confidence_label(85), "🔥 Elite pick")
        self.assertEqual(pe._confidence_label(70), "✅ Strong pick")
        self.assertEqual(pe._confidence_label(55), "📊 Moderate pick")
        self.assertEqual(pe._confidence_label(40), "⚠️ Lean only")
        self.assertEqual(pe._confidence_label(25), "❌ Insufficient data")


# ── 7. NBA probability markets ─────────────────────────────────────────────────

class TestNBAProbabilityMarkets(unittest.TestCase):

    def test_double_double_probability(self):
        """3 DD in 10 games → ~30%."""
        # pts=12, reb=11, ast=3 → pts+reb ≥10 = DD
        log = (
            [_nba_game(12, 11, 3)] * 3 +    # DD (pts≥10 AND reb≥10)
            [_nba_game(25, 6, 8)]  * 7       # no DD
        )
        result = pe._double_double_probability(log)
        self.assertAlmostEqual(result["probability"], 30.0, places=0)
        self.assertEqual(result["count"], 3)

    def test_triple_double_probability(self):
        """2 TD in 20 games → 10% → HIGH RISK."""
        log = (
            [_nba_game(12, 11, 10)] * 2 +    # TD
            [_nba_game(25, 7, 8)]   * 18
        )
        result = pe._triple_double_probability(log)
        self.assertAlmostEqual(result["probability"], 10.0, places=0)
        self.assertEqual(result["risk_note"], "HIGH RISK BET")

    def test_triple_double_viable(self):
        """8 TD in 20 games → 40% → viable."""
        log = (
            [_nba_game(11, 12, 10)] * 8 +
            [_nba_game(25, 7, 8)]   * 12
        )
        result = pe._triple_double_probability(log)
        self.assertAlmostEqual(result["probability"], 40.0, places=0)
        self.assertEqual(result["risk_note"], "viable")


# ── 8. Bet slip builder ────────────────────────────────────────────────────────

class TestBetSlip(unittest.TestCase):

    def _card(self, player, market, lean, line, conf_score, conf_label):
        return {
            "player_name":  player,
            "market_label": market,
            "projection":   {"lean": lean, "suggested_line": line},
            "confidence":   {"score": conf_score, "label": conf_label},
        }

    def test_parlay_confidence_formula(self):
        """
        Parlay conf: multiply confidences together, apply -5% penalty per pick after the first.
        Formula: c1 × c2 × 0.95 × c3 × 0.95 × 100  (flat ×0.95 per additional pick)
        = 0.78 × 0.74 × 0.95 × 0.68 × 0.95 × 100
        """
        cards = [
            self._card("LeBron", "Points",   "OVER",  25.5, 78, "✅ Strong"),
            self._card("Bruno",  "Assists",  "OVER",  3.5,  74, "✅ Strong"),
            self._card("Bruno",  "Shots",    "OVER",  1.5,  68, "📊 Moderate"),
        ]
        slip = pe._build_bet_slip(cards)
        # Each pick after the first gets one ×0.95 penalty applied in that iteration
        expected = 0.78 * 0.74 * 0.95 * 0.68 * 0.95 * 100
        self.assertAlmostEqual(slip["parlay_confidence"], round(expected, 1), places=0)

    def test_parlay_not_recommended_with_weak_pick(self):
        cards = [
            self._card("LeBron", "Points",  "OVER",  25.5, 78, "✅ Strong"),
            self._card("Player", "Dribbles","OVER",  2.5,  45, "⚠️ Lean only"),
        ]
        slip = pe._build_bet_slip(cards)
        self.assertEqual(slip["parlay_risk"], "HIGH")
        self.assertIn("not recommended", slip["parlay_advice"])

    def test_best_single_is_highest_confidence(self):
        cards = [
            self._card("LeBron", "Points",  "OVER",  25.5, 78, "✅ Strong"),
            self._card("Bruno",  "Assists", "OVER",  3.5,  74, "✅ Strong"),
        ]
        slip = pe._build_bet_slip(cards)
        self.assertIn("LeBron", slip["best_single"])
        self.assertIn("25.5", str(slip["best_single"]))

    def test_push_picks_excluded_from_slip(self):
        cards = [
            self._card("Player A", "Points",  "PUSH",  25.5, 78, "✅ Strong"),
            self._card("Player B", "Assists", "OVER",  3.5,  74, "✅ Strong"),
        ]
        slip = pe._build_bet_slip(cards)
        self.assertEqual(len(slip["picks"]), 1)
        self.assertEqual(slip["picks"][0]["market"], "Assists")

    def test_no_picks_returns_empty_slip(self):
        cards = [self._card("P", "Points", "PUSH", 25.0, 60, "📊 Moderate")]
        slip = pe._build_bet_slip(cards)
        self.assertEqual(len(slip["picks"]), 0)
        self.assertIsNone(slip["best_single"])


# ── 9. Soccer per-90 normalisation ────────────────────────────────────────────

class TestSoccerPer90(unittest.TestCase):

    def test_per_90_normalisation(self):
        """A player who scored 1 goal in 45 mins = 2.0 goals per 90."""
        game = _soccer_game(goals=1, minutes=45)
        # Put it in a soccer "per_game_log" style
        vals = pe._extract_values([game], "goals", sport="soccer", per_90=True)
        self.assertEqual(len(vals), 1)
        self.assertAlmostEqual(vals[0], 2.0, places=2)

    def test_per_90_excludes_low_minutes(self):
        """Games with < 10 minutes are excluded from per-90 calculations."""
        game = _soccer_game(goals=1, minutes=5)
        vals = pe._extract_values([game], "goals", sport="soccer", per_90=True)
        self.assertEqual(len(vals), 0)

    def test_per_game_no_normalisation(self):
        """Yellow cards are per-game, not per-90."""
        game = _soccer_game(minutes=90)
        game["yellow_cards"] = 1
        vals = pe._extract_values([game], "yellow_cards", sport="soccer", per_90=False)
        self.assertEqual(vals[0], 1.0)


# ── 10. End-to-end mock test ───────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """
    Full prop card build with completely mocked data (no API calls).
    Verifies all layers are populated and the output structure is correct.
    """

    def _make_samples(self):
        pts = [24, 27, 30, 22, 28, 25, 26, 19, 29, 23,
               24, 26, 28, 21, 25, 30, 22, 27, 24, 25]
        full_log = [_nba_game(pts=p, reb=7, ast=7, minutes="34:00") for p in pts]
        vs_log   = [_nba_game(pts=p, reb=6, ast=7, minutes="34:00") for p in [23, 25, 21, 24, 22]]
        return {
            "sport":            "nba",
            "player_id":        2544,
            "player_team_id":   17,
            "opponent_team_id": 2,
            "season":           2024,
            "full_season_log":  full_log,
            "last5":            full_log[-5:],
            "last10":           full_log[-10:],
            "vs_opponent":      {
                "games": 5, "records": vs_log,
                "averages": None, "limited_sample": False,
            },
            "team_injuries": [],
        }

    def test_prop_card_structure(self):
        samples = self._make_samples()
        opp_stats = {"opp_ppg": 115.0, "net_rtg": -2.0}
        card = pe._build_prop_card(
            sport="nba",
            market_key="points",
            samples=samples,
            is_home=False,
            opponent_stats=opp_stats,
            player_name="LeBron James",
            opponent_name="Boston Celtics",
        )

        # Top-level keys
        self.assertIn("market_key",    card)
        self.assertIn("layers",        card)
        self.assertIn("variance",      card)
        self.assertIn("modifiers",     card)
        self.assertIn("projection",    card)
        self.assertIn("confidence",    card)

        # Layers populated
        layers = card["layers"]
        self.assertIsNotNone(layers["season_avg"])
        self.assertIsNotNone(layers["last5_avg"])
        self.assertIsNotNone(layers["last10_avg"])
        self.assertIsNotNone(layers["vs_opponent_avg"])

        # Projection valid
        proj = card["projection"]
        self.assertIn(proj["lean"], ("OVER", "UNDER", "PUSH"))
        self.assertIsNotNone(proj["suggested_line"])
        # Line is a half-integer (0 or .5)
        self.assertEqual(proj["suggested_line"] * 2, round(proj["suggested_line"] * 2))

        # Confidence valid
        conf = card["confidence"]
        self.assertGreaterEqual(conf["score"], 0)
        self.assertLessEqual(conf["score"],    100)
        self.assertIn("score",  conf)
        self.assertIn("label",  conf)
        self.assertIn("components", conf)
        self.assertEqual(len(conf["components"]), 5)

        # Exactly 5 modifier entries
        self.assertEqual(len(card["modifiers"]), 5)

    def test_pra_card(self):
        samples = self._make_samples()
        card = pe._build_prop_card(
            sport="nba",
            market_key="pra",
            samples=samples,
            is_home=False,
            opponent_stats=None,
            player_name="LeBron James",
            opponent_name="Boston Celtics",
        )
        self.assertNotIn("error", card)
        self.assertIsNotNone(card["projection"]["adjusted"])
        # PRA should be higher than points alone
        pts_card = pe._build_prop_card("nba", "points", samples, False, None,
                                        "LeBron James", "Boston Celtics")
        self.assertGreater(card["projection"]["adjusted"],
                           pts_card["projection"]["adjusted"])

    def test_full_generate_props_mock(self):
        """
        generate_props() with no API calls (player_id=0 → will fail data fetch,
        but structure should still be returned with empty logs and error notes).
        """
        result = pe.generate_props(
            sport            = "nba",
            player_id        = 0,
            player_name      = "Test Player",
            player_team_id   = 0,
            opponent_team_id = 0,
            opponent_name    = "Test Opponent",
            is_home          = True,
            markets          = ["points", "rebounds", "pra"],
            season           = 2024,
        )

        self.assertIn("props",     result)
        self.assertIn("bet_slip",  result)
        self.assertIn("player",    result)
        self.assertIn("opponent",  result)
        self.assertIn("errors",    result)


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader  = unittest.TestLoader()
    suite   = loader.loadTestsFromModule(sys.modules[__name__])
    runner  = unittest.TextTestRunner(verbosity=2)
    result  = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
