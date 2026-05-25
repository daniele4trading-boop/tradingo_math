import unittest

import pandas as pd

from ict_order_block_backtester import (
    BacktestConfig,
    Direction,
    ICTOrderBlockBacktester,
    calculate_fib_levels,
)


class ICTOrderBlockBacktesterTests(unittest.TestCase):
    def test_fibonacci_levels_are_mirrored_for_bullish_and_bearish_obs(self):
        bullish = calculate_fib_levels(Direction.BULLISH, high=110.0, low=100.0)
        self.assertEqual(bullish.entry, 105.0)
        self.assertEqual(bullish.mitigation, 105.0)
        self.assertAlmostEqual(bullish.tp1, 111.27)
        self.assertEqual(bullish.trigger_tp2, 110.0)
        self.assertAlmostEqual(bullish.tp2, 111.618)
        self.assertEqual(bullish.trigger_tp3, 114.0)
        self.assertAlmostEqual(bullish.tp3, 123.812)
        self.assertEqual(bullish.trigger_trail, 120.0)

        bearish = calculate_fib_levels(Direction.BEARISH, high=110.0, low=100.0)
        self.assertEqual(bearish.entry, 105.0)
        self.assertEqual(bearish.mitigation, 105.0)
        self.assertAlmostEqual(bearish.tp1, 98.73)
        self.assertEqual(bearish.trigger_tp2, 100.0)
        self.assertAlmostEqual(bearish.tp2, 98.382)
        self.assertEqual(bearish.trigger_tp3, 96.0)
        self.assertAlmostEqual(bearish.tp3, 86.188)
        self.assertEqual(bearish.trigger_trail, 90.0)

    def test_synthetic_bullish_setup_generates_valid_order_block_and_trade(self):
        df = self._synthetic_bullish_data()
        cfg = BacktestConfig(
            momentum_atr_mult=0.7,
            momentum_body_ratio=0.50,
            enable_max_gain=False,
            min_stars=3,
        )
        result = ICTOrderBlockBacktester(cfg).run(df, "XAUUSD")

        valid_obs = [ob for ob in result.order_blocks if ob.stars >= cfg.min_stars]
        self.assertGreaterEqual(len(valid_obs), 1)
        self.assertTrue(any(ob.direction == Direction.BULLISH for ob in valid_obs))
        self.assertGreaterEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.direction, "BUY")
        self.assertEqual(trade.tp_level, "TP1")
        self.assertGreater(trade.pnl_points, 0)
        self.assertGreaterEqual(trade.stars, 3)

    @staticmethod
    def _synthetic_bullish_data():
        rows = []
        base_time = pd.Timestamp("2026-01-01T00:00:00Z")

        def add(open_, high, low, close):
            rows.append(
                {
                    "time": base_time + pd.Timedelta(minutes=5 * len(rows)),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 100,
                }
            )

        # Warm-up bars with enough history for MA/ATR/ADX and prior swings.
        for index in range(55):
            close = 100.0 + (index % 5) * 0.15
            add(close - 0.05, close + 0.40, close - 0.40, close)

        # Create a known swing high and swing low before the liquidity sweep.
        add(100.4, 102.8, 100.0, 102.0)
        add(102.0, 103.0, 101.5, 102.7)
        add(102.7, 102.9, 101.8, 102.1)
        add(102.1, 102.3, 100.2, 100.8)
        add(100.8, 101.0, 99.5, 100.2)

        # Sweep below the prior swing low, then close back above it.
        add(100.2, 101.0, 98.9, 100.6)

        # Bullish OB: last bearish candle before the impulse.
        add(100.6, 101.0, 98.0, 99.0)

        # Momentum candle breaks structure.
        add(99.0, 106.0, 99.0, 105.5)

        # FVG against the OB candle: this low is above OB high.
        add(105.5, 108.0, 104.0, 107.0)
        add(107.0, 108.2, 104.5, 106.5)

        # Pullback holds above the midpoint until the retest bar touches it.
        add(106.5, 107.0, 103.0, 104.0)
        add(104.0, 104.5, 101.0, 101.2)
        add(101.2, 102.0, 99.5, 101.9)

        # TP1 is above the OB high by 12.7% of the range.
        add(101.9, 102.0, 101.2, 101.8)
        add(101.8, 102.5, 101.0, 102.0)

        return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()

