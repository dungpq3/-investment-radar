import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from market_brief import etf_flow_is_fresh


class FlowFreshnessTests(unittest.TestCase):
    def test_recent_farside_row(self):
        self.assertTrue(etf_flow_is_fresh(date(2026, 10, 7), date(2026, 10, 8)))

    def test_old_farside_row_not_live(self):
        self.assertFalse(etf_flow_is_fresh(date(2026, 9, 1), date(2026, 10, 8)))

    def test_future_data_rejected(self):
        self.assertFalse(etf_flow_is_fresh(date(2026, 10, 9), date(2026, 10, 8)))


if __name__ == "__main__":
    unittest.main()
