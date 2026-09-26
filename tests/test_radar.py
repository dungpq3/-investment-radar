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


if __name__ == "__main__":
    unittest.main()
