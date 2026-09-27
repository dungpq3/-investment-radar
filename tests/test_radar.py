import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("radar", ROOT / "src" / "radar.py")
radar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(radar)


class RadarTests(unittest.TestCase):
    def test_pct(self):
        self.assertAlmostEqual(radar.pct(110, 100), 10.0)

    def test_spread_bps(self):
        s = radar.spread_bps({"bidPrice": "99", "askPrice": "101"})
        self.assertAlmostEqual(s, 200.0)

    def test_state_already_moved(self):
        cfg = {
            "signal": {
                "already_moved_24h_pct": 35,
                "already_moved_12h_pct": 30,
                "early_min_12h_pct": 4,
                "early_max_12h_pct": 25,
                "early_min_volume_ratio_4h": 1.5,
                "early_min_confirmed_candles": 2,
                "wake_min_12h_pct": 2,
                "wake_max_12h_pct": 25,
                "wake_min_volume_ratio_4h": 1.25,
            }
        }
        self.assertEqual(radar.classify_state({"change_24h_pct": 50}, cfg), "ALREADY_MOVED")


    def test_qnt_like_early_breakout_is_watch(self):
        feat = {
            "state": "WAKE_UP",
            "drawdown_major_pct": -80.56,
            "weeks_since_26w_low": 4,
            "base_range_12w_pct": 26.99,
            "position_52w": 0.234,
            "daily_breakout_20d": True,
            "near_daily_breakout_20d": True,
            "spread_bps": 3.83,
            "volume_ratio_4h": 1.27,
            "ret_12h_pct": 4.42,
            "confirmed_candles_3x4h": 1,
            "breakout_20x4h": False,
            "near_breakout_20x4h": False,
            "change_24h_pct": 8.19,
            "entry_reference": {"state": "WAIT_BREAKOUT_RETEST"},
        }
        cfg = {"ranking": {
            "structure_watch_min": 55,
            "trigger_watch_min": 30,
            "ready_trigger_min": 50,
        }}
        feat["structure_score"] = radar.structure_score(feat)
        feat["trigger_score"] = radar.trigger_score(feat)
        self.assertGreaterEqual(feat["structure_score"], 55)
        self.assertGreaterEqual(feat["trigger_score"], 30)
        self.assertEqual(radar.opportunity_tier(feat, cfg), "WATCH")

if __name__ == "__main__":
    unittest.main()
