import unittest

import pandas as pd

from tradingo_core.backtester import BacktestReport, TradeResult
from tradingo_core.optimize import robust_score


def trade(status, r_result):
    return TradeResult(
        setup_time=pd.Timestamp("2026-01-01T08:00:00Z"),
        entry_time=pd.Timestamp("2026-01-01T08:01:00Z"),
        exit_time=pd.Timestamp("2026-01-01T08:10:00Z"),
        direction="BUY",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        score=70.0,
        status=status,
        r_result=r_result,
        pnl=500.0 * r_result,
        session="London Open",
    )


class OptimizeScoreTest(unittest.TestCase):
    def test_robust_score_prefers_positive_expectancy(self):
        good = BacktestReport(
            trades=(trade("WIN", 2.0), trade("WIN", 2.0), trade("LOSS", -1.0), trade("WIN", 2.0), trade("LOSS", -1.0)),
            initial_equity=100_000,
            final_equity=102_000,
            max_drawdown_pct=0.005,
            max_daily_drawdown_pct=0.005,
            winrate=0.6,
            profit_factor=3.0,
            expectancy_r=0.8,
        )
        bad = BacktestReport(
            trades=(trade("LOSS", -1.0), trade("LOSS", -1.0), trade("WIN", 2.0), trade("LOSS", -1.0), trade("LOSS", -1.0)),
            initial_equity=100_000,
            final_equity=99_000,
            max_drawdown_pct=0.02,
            max_daily_drawdown_pct=0.01,
            winrate=0.2,
            profit_factor=0.5,
            expectancy_r=-0.4,
        )
        self.assertGreater(robust_score(good), robust_score(bad))


if __name__ == "__main__":
    unittest.main()
