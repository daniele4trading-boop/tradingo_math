import unittest

import pandas as pd

from tsentry_strategy import Direction, TsEntryParams, backtest_style, detect_tsentry_signals


def _ohlc(index, rows):
    return pd.DataFrame(rows, index=pd.to_datetime(index, utc=True))


class TsEntryStrategyTest(unittest.TestCase):
    def test_daytrading_daily_bullish_sweep_generates_buy(self):
        daily = _ohlc(
            ["2026-06-01 00:00:00Z", "2026-06-02 00:00:00Z"],
            [
                {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "tick_volume": 1000},
                {"open": 106.0, "high": 112.0, "low": 101.0, "close": 111.0, "tick_volume": 1000},
            ],
        )
        m5_index = pd.date_range("2026-06-03 00:00:00Z", periods=220, freq="5min")
        rows = [
            {"open": 106.0, "high": 106.2, "low": 105.8, "close": 106.0, "tick_volume": 100}
            for _ in m5_index
        ]
        signal_time = pd.Timestamp("2026-06-03 13:35:00Z")
        signal_idx = list(m5_index).index(signal_time)
        rows[signal_idx] = {"open": 102.0, "high": 103.0, "low": 100.0, "close": 102.2, "tick_volume": 200}
        rows[signal_idx + 1] = {"open": 102.3, "high": 103.0, "low": 102.0, "close": 102.8, "tick_volume": 200}
        rows[signal_idx + 2] = {"open": 102.8, "high": 107.0, "low": 102.5, "close": 106.6, "tick_volume": 200}
        rows[signal_idx + 3] = {"open": 106.6, "high": 112.3, "low": 106.0, "close": 111.8, "tick_volume": 200}
        entry = pd.DataFrame(rows, index=m5_index)

        frames = {"D1": daily, "M5": entry}
        params = TsEntryParams(spread_buffer_points=10, point_size=0.01, min_rr_to_tp1=0.5)

        signals = detect_tsentry_signals("daytrading_daily", frames, params)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].direction, Direction.BUY)
        self.assertEqual(signals[0].level_name, "prev_D1_low")

    def test_backtest_records_tp2_result(self):
        daily = _ohlc(
            ["2026-06-01 00:00:00Z", "2026-06-02 00:00:00Z"],
            [
                {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "tick_volume": 1000},
                {"open": 106.0, "high": 112.0, "low": 101.0, "close": 111.0, "tick_volume": 1000},
            ],
        )
        m5_index = pd.date_range("2026-06-03 00:00:00Z", periods=220, freq="5min")
        rows = [
            {"open": 106.0, "high": 106.2, "low": 105.8, "close": 106.0, "tick_volume": 100}
            for _ in m5_index
        ]
        signal_idx = list(m5_index).index(pd.Timestamp("2026-06-03 13:35:00Z"))
        rows[signal_idx] = {"open": 102.0, "high": 103.0, "low": 100.0, "close": 102.2, "tick_volume": 200}
        rows[signal_idx + 1] = {"open": 102.3, "high": 103.0, "low": 102.0, "close": 102.8, "tick_volume": 200}
        rows[signal_idx + 2] = {"open": 102.8, "high": 107.0, "low": 102.5, "close": 106.6, "tick_volume": 200}
        rows[signal_idx + 3] = {"open": 106.6, "high": 112.3, "low": 106.0, "close": 111.8, "tick_volume": 200}
        entry = pd.DataFrame(rows, index=m5_index)
        params = TsEntryParams(spread_buffer_points=10, point_size=0.01, min_rr_to_tp1=0.5)

        trades, summary = backtest_style("daytrading_daily", {"D1": daily, "M5": entry}, params)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "TP2")
        self.assertGreater(trades[0].result_r, 0)
        self.assertEqual(int(summary.iloc[0]["trades"]), 1)

    def test_daily_loss_circuit_breaker_limits_same_day_losses(self):
        daily = _ohlc(
            ["2026-06-01 00:00:00Z", "2026-06-02 00:00:00Z"],
            [
                {"open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "tick_volume": 1000},
                {"open": 106.0, "high": 112.0, "low": 101.0, "close": 111.0, "tick_volume": 1000},
            ],
        )
        m5_index = pd.date_range("2026-06-03 00:00:00Z", periods=220, freq="5min")
        rows = [
            {"open": 106.0, "high": 106.2, "low": 105.8, "close": 106.0, "tick_volume": 100}
            for _ in m5_index
        ]
        for signal_time in ("2026-06-03 13:35:00Z", "2026-06-03 14:35:00Z"):
            signal_idx = list(m5_index).index(pd.Timestamp(signal_time))
            rows[signal_idx] = {"open": 102.0, "high": 103.0, "low": 100.0, "close": 102.2, "tick_volume": 200}
            rows[signal_idx + 1] = {"open": 102.2, "high": 102.4, "low": 101.9, "close": 102.0, "tick_volume": 200}
            rows[signal_idx + 2] = {"open": 102.0, "high": 102.1, "low": 99.7, "close": 100.0, "tick_volume": 200}
        entry = pd.DataFrame(rows, index=m5_index)
        params = TsEntryParams(
            spread_buffer_points=10,
            point_size=0.01,
            min_rr_to_tp1=0.5,
            max_consecutive_daily_losses=1,
        )

        trades, summary = backtest_style("daytrading_daily", {"D1": daily, "M5": entry}, params)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "SL")
        self.assertLess(trades[0].result_r, 0)
        self.assertEqual(int(summary.iloc[0]["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
