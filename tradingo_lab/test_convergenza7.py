import unittest
from datetime import datetime, timedelta, timezone

from config import Convergenza7Config
from data_loader import aggregate_bars
from pattern_detector import detect_engulfing, detect_pin_bar, detect_star
from risk_manager import build_risk_plan
from stats_reporter import calculate_stats
from structure_detector import StructuralLevel


def bar(offset, open_price, high, low, close, volume=1.0):
    return {
        "time": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=offset),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class Convergenza7CoreTest(unittest.TestCase):
    def test_aggregate_bars_uses_standard_ohlcv_rules(self):
        bars = [
            bar(0, 100.0, 101.0, 99.5, 100.5, 10.0),
            bar(1, 100.5, 102.0, 100.0, 101.0, 11.0),
            bar(2, 101.0, 101.5, 98.0, 99.0, 12.0),
            bar(3, 99.0, 100.0, 97.0, 98.5, 13.0),
            bar(4, 98.5, 103.0, 98.0, 102.0, 14.0),
        ]

        aggregated = aggregate_bars(bars, "M5")

        self.assertEqual(len(aggregated), 1)
        self.assertEqual(aggregated[0]["open"], 100.0)
        self.assertEqual(aggregated[0]["high"], 103.0)
        self.assertEqual(aggregated[0]["low"], 97.0)
        self.assertEqual(aggregated[0]["close"], 102.0)
        self.assertEqual(aggregated[0]["volume"], 60.0)

    def test_detects_strict_long_engulfing(self):
        bars = [
            bar(0, 100.0, 101.0, 98.0, 99.0),
            bar(1, 98.8, 102.0, 98.5, 101.2),
        ]

        signal = detect_engulfing(bars, "long")

        self.assertIsNotNone(signal)
        self.assertEqual(signal.pattern_id, "Pattern 1")
        self.assertEqual(signal.sl_suggested, 98.5)

    def test_detects_short_pin_bar(self):
        bars = [bar(0, 99.2, 103.0, 99.0, 99.4)]

        signal = detect_pin_bar(bars, "short")

        self.assertIsNotNone(signal)
        self.assertEqual(signal.pattern_id, "Pattern 2")
        self.assertEqual(signal.sl_suggested, 103.0)

    def test_detects_morning_star_with_small_middle_candle(self):
        bars = [
            bar(0, 100.0, 100.2, 98.0, 98.5),
            bar(1, 98.4, 98.6, 98.3, 98.5),
            bar(2, 98.6, 100.0, 98.4, 99.5),
        ]

        signal = detect_star(bars, "long", atr_m1=1.0)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.pattern_id, "Pattern 3")
        self.assertEqual(signal.sl_suggested, 98.0)

    def test_risk_plan_requires_structural_target_at_minimum_two_r(self):
        levels = [
            StructuralLevel(101.5, "resistance", 2, None, None),
            StructuralLevel(102.1, "resistance", 2, None, None),
        ]
        config = Convergenza7Config(min_rr=2.0)

        plan = build_risk_plan(100.0, "long", 99.0, levels, config)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.tp_price, 102.1)
        self.assertAlmostEqual(plan.rr_effective, 2.1)

    def test_stats_include_requested_aggregate_metrics(self):
        stats = calculate_stats(
            [
                {"pnl_percent": 2.0, "realized_rr": 2.0, "setup_name": "Setup A", "pattern_id": "Pattern 1"},
                {"pnl_percent": -1.0, "realized_rr": -1.0, "setup_name": "Setup B", "pattern_id": "Pattern 2"},
                {"pnl_percent": 3.0, "realized_rr": 3.0, "setup_name": "Setup A", "pattern_id": "Pattern 1"},
            ]
        )

        self.assertEqual(stats["total_trades"], 3)
        self.assertAlmostEqual(stats["win_rate_percent"], 66.6666666667)
        self.assertEqual(stats["avg_rr_winners"], 2.5)
        self.assertEqual(stats["profit_factor"], 5.0)
        self.assertEqual(stats["distribution_by_setup"], {"Setup A": 2, "Setup B": 1})
        self.assertEqual(stats["distribution_by_pattern"], {"Pattern 1": 2, "Pattern 2": 1})


if __name__ == "__main__":
    unittest.main()

