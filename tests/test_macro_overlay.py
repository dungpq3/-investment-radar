import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import macro_overlay as m


class MacroOverlayTests(unittest.TestCase):
    def test_headwind_does_not_change_trade_weights(self):
        out = m.build_overlay(date(2026, 10, 8),
            yields_fn=lambda _: {"status": "OK", "direction": "UP"},
            dxy_fn=lambda _: {"status": "OK", "direction": "UP"})
        self.assertEqual(out["macro_state"], "MACRO_HEADWIND")
        self.assertIn("does not change", out["policy"])

    def test_stale_macro_cannot_infer_risk_on(self):
        out = m.build_overlay(date(2026, 10, 8),
            yields_fn=lambda _: {"status": "STALE", "direction": "DOWN"},
            dxy_fn=lambda _: {"status": "OK", "direction": "DOWN"})
        self.assertEqual(out["macro_state"], "UNKNOWN")
        self.assertEqual(out["status"], "PARTIAL")

    def test_fred_series_parser(self):
        rows = "DATE,DFII10\\n" + "".join(
            f"2026-10-{day:02d},{2.10 + day * 0.01:.2f}\\n" for day in range(1, 9)
        )
        result = m.real_yield(date(2026, 10, 8), fetch=lambda _: rows)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["direction"], "UP")


if __name__ == "__main__":
    unittest.main()
