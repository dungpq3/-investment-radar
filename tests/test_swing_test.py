import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("swing_test", ROOT / "src" / "swing_test.py")
swing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(swing)


class SwingTestTests(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "eligible_tiers": ["READY", "WATCH"],
            "eligible_states": ["EARLY_IGNITION", "WAKE_UP"],
            "min_signal_score": 70,
            "initial_usdt": 100,
            "dca_usdt": 100,
            "dca_trigger_pct": -12,
            "take_profit_pct": 25,
            "stop_loss_pct": -25,
            "fee_bps": 10,
            "slippage_bps": 5,
            "shadow_targets_pct": [20, 25, 30],
        }

    def test_rank_prefers_stronger_non_extended_setup(self):
        a = {
            "symbol": "AAAUSDT", "opportunity_tier": "WATCH", "state": "WAKE_UP",
            "signal_score": 78, "trigger_score": 70, "structure_score": 75,
            "entry_reference": {"state": "WAIT_BREAKOUT_RETEST"}, "last_price": 10,
            "spread_bps": 4,
        }
        b = {
            "symbol": "BBBUSDT", "opportunity_tier": "READY", "state": "EARLY_IGNITION",
            "signal_score": 80, "trigger_score": 80, "structure_score": 60,
            "entry_reference": {"state": "IN_REF_ZONE"}, "last_price": 20,
            "spread_bps": 5,
        }
        c = {
            "symbol": "CCCUSDT", "opportunity_tier": "WATCH", "state": "WAKE_UP",
            "signal_score": 95, "trigger_score": 95, "structure_score": 90,
            "entry_reference": {"state": "EXTENDED_ABOVE_REF"}, "last_price": 30,
            "spread_bps": 2,
        }
        ranked = swing.ranked_candidates([a, b, c], self.policy)
        self.assertEqual([x["symbol"] for x in ranked], ["BBBUSDT", "AAAUSDT"])

    def test_round_trip_cost_is_realistic_and_negative_when_flat(self):
        buy = swing.buy_fill(100, 10, 10, 5)
        sell = swing.sell_fill(buy["net_qty"], 10, 10, 5)
        self.assertLess(sell["net_usdt"], 100)
        self.assertGreater(sell["net_usdt"], 99.5)

    def test_tp25_closes_without_dca(self):
        trade = {
            "status": "OPEN",
            "entry_at_utc": "2026-09-29T00:00:00+00:00",
            "entry_market_price": 10.0,
            "buy_fills": [{**swing.buy_fill(100, 10, 10, 5), "kind": "ENTRY"}],
            "dca_done": False,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "shadow_targets": {str(x): {"hit": False, "first_hit_close_ms": None} for x in [20,25,30]},
            "last_processed_close_ms": 0,
        }
        swing.recalc_position(trade)
        tp = swing.current_levels(trade, self.policy)["tp"]
        rows = [[1790640900000, "10", str(tp * 1.01), "9.9", str(tp), "1", 1790641799999]]
        events = swing.process_candles(trade, rows, self.policy)
        self.assertIn("TP25", events)
        self.assertEqual(trade["status"], "CLOSED")
        self.assertGreater(trade["net_pnl_usdt"], 20)

    def test_dca_then_no_same_candle_tp(self):
        trade = {
            "status": "OPEN",
            "entry_at_utc": "2026-09-29T00:00:00+00:00",
            "entry_market_price": 10.0,
            "buy_fills": [{**swing.buy_fill(100, 10, 10, 5), "kind": "ENTRY"}],
            "dca_done": False,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "shadow_targets": {str(x): {"hit": False, "first_hit_close_ms": None} for x in [20,25,30]},
            "last_processed_close_ms": 0,
        }
        swing.recalc_position(trade)
        rows = [[1790640900000, "10", "13", "8.7", "10", "1", 1790641799999]]
        events = swing.process_candles(trade, rows, self.policy)
        self.assertIn("DCA1", events)
        self.assertTrue(trade["dca_done"])
        self.assertEqual(trade["status"], "OPEN")
        self.assertAlmostEqual(trade["capital_deployed_usdt"], 200.0, places=6)


if __name__ == "__main__":
    unittest.main()
