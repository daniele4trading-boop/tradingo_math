import unittest

import pandas as pd

from tradingo_core import BacktestConfig, ICTSniperBacktester, ICTSniperConfig, ICTSniperStrategy
from tradingo_core.ict_sniper import pandas_resample_rule


def synthetic_bullish_m1() -> pd.DataFrame:
    start = pd.Timestamp("2026-06-08T03:00:00Z")
    rows = []
    price = 100.0
    for i in range(300):
        ts = start + pd.Timedelta(minutes=i)
        price += 0.015
        open_ = price
        close = price + 0.01
        high = max(open_, close) + 0.08
        low = min(open_, close) - 0.08
        volume = 100
        rows.append(
            {
                "time": ts,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": volume,
                "spread": 10,
                "real_volume": 0,
            }
        )

    # Build a clean prior swing low.
    rows[232].update({"open": 103.20, "high": 103.32, "low": 102.80, "close": 103.05, "tick_volume": 120})
    rows[233].update({"open": 103.05, "high": 103.35, "low": 103.00, "close": 103.25, "tick_volume": 110})
    rows[234].update({"open": 103.25, "high": 103.48, "low": 103.18, "close": 103.40, "tick_volume": 110})

    # Liquidity sweep below the swing low, closing back above it.
    rows[240].update({"open": 103.10, "high": 103.25, "low": 102.55, "close": 102.95, "tick_volume": 430})

    # Bullish displacement and FVG: c1.high < c3.low.
    rows[241].update({"open": 102.95, "high": 103.05, "low": 102.88, "close": 103.00, "tick_volume": 130})
    rows[242].update({"open": 103.02, "high": 104.45, "low": 102.98, "close": 104.30, "tick_volume": 520})
    rows[243].update({"open": 104.25, "high": 104.55, "low": 103.55, "close": 104.20, "tick_volume": 220})

    # Retest into the FVG with lower volume, then move to target.
    rows[248].update({"open": 104.10, "high": 104.25, "low": 103.20, "close": 103.90, "tick_volume": 70})
    rows[249].update({"open": 103.90, "high": 104.80, "low": 103.25, "close": 104.70, "tick_volume": 230})
    rows[250].update({"open": 104.70, "high": 106.20, "low": 104.60, "close": 106.00, "tick_volume": 260})
    rows[251].update({"open": 106.00, "high": 107.20, "low": 105.90, "close": 107.00, "tick_volume": 240})
    return pd.DataFrame(rows)


class ICTSniperStrategyTest(unittest.TestCase):
    def test_pandas_resample_rule_accepts_trading_aliases(self):
        self.assertEqual(pandas_resample_rule("H1"), "1h")
        self.assertEqual(pandas_resample_rule("1H"), "1h")
        self.assertEqual(pandas_resample_rule("M5"), "5min")

    def test_detects_bullish_sweep_fvg_retest(self):
        cfg = ICTSniperConfig(
            htf_timeframe="5min",
            setup_timeframe="1min",
            volume_z_window=20,
            atr_z_window=20,
            min_sweep_volume_z=0.2,
            min_displacement_range_atr=0.7,
            min_displacement_volume_z=0.2,
            min_score=55.0,
            max_fvg_age_bars=15,
        )
        setup = ICTSniperStrategy(cfg).find_setup(synthetic_bullish_m1().iloc[:252])
        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, "BUY")
        self.assertGreater(setup.score, 55.0)
        self.assertLess(setup.sl, setup.entry)
        self.assertGreater(setup.tp2, setup.entry)
        self.assertEqual(setup.session, "London Open")

    def test_backtester_closes_synthetic_trade(self):
        strategy_cfg = ICTSniperConfig(
            htf_timeframe="5min",
            setup_timeframe="1min",
            volume_z_window=20,
            atr_z_window=20,
            min_sweep_volume_z=0.2,
            min_displacement_range_atr=0.7,
            min_displacement_volume_z=0.2,
            min_score=55.0,
            max_fvg_age_bars=15,
        )
        backtest_cfg = BacktestConfig(
            initial_equity=100_000.0,
            risk_per_trade_pct=0.005,
            max_daily_dd_pct=0.02,
            max_daily_trades=3,
            pending_expiry_minutes=30,
            signal_evaluation_minutes=1,
        )
        report = ICTSniperBacktester(strategy_cfg, backtest_cfg).run(synthetic_bullish_m1())
        closed = [t for t in report.trades if t.status not in ("EXPIRED", "OPEN")]
        self.assertGreaterEqual(len(closed), 1)
        self.assertGreater(report.final_equity, report.initial_equity)
        self.assertLessEqual(report.max_daily_drawdown_pct, 0.02)


if __name__ == "__main__":
    unittest.main()
