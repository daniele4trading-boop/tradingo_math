import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest_mz_ma_scalper import BacktestConfig, load_ohlc_csv, run_backtest
from tsentry_config import (
    DEFAULT_TSENTRY_DB_PATH,
    TSENTRY_DB_PATH_ENV,
    get_tsentry_db_path,
)
from tsentry_runner import init_state_db


class RepositorySmokeTest(unittest.TestCase):
    def test_requirements_file_exists(self):
        repo_root = Path(__file__).resolve().parents[1]

        self.assertTrue((repo_root / "requirements.txt").is_file())

    def test_requirements_include_trading_dependencies(self):
        repo_root = Path(__file__).resolve().parents[1]
        requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("numpy", requirements)
        self.assertIn("pandas", requirements)
        self.assertIn("streamlit", requirements)
        self.assertIn('MetaTrader5; platform_system == "Windows"', requirements)

    def test_tsentry_db_path_uses_default_without_env(self):
        original = os.environ.pop(TSENTRY_DB_PATH_ENV, None)
        try:
            self.assertEqual(get_tsentry_db_path(), DEFAULT_TSENTRY_DB_PATH)
        finally:
            if original is not None:
                os.environ[TSENTRY_DB_PATH_ENV] = original

    def test_tsentry_runner_initializes_state_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state" / "tradingo.db"

            init_state_db(str(db_path))

            self.assertTrue(db_path.is_file())

    def test_mz_ma_backtester_runs_on_synthetic_ohlc(self):
        rows = []
        for i in range(40):
            base = 2000.0 + i * 0.15
            close = base + (0.20 if i % 3 else -0.05)
            rows.append(
                {
                    "time": pd.Timestamp("2026-04-01 16:30:00") + pd.Timedelta(minutes=i),
                    "open": base,
                    "high": base + 0.45,
                    "low": base - 0.45,
                    "close": close,
                    "spread": 20,
                }
            )
        df = pd.DataFrame(rows)
        cfg = BacktestConfig(
            initial_balance=10_000,
            fixed_spread_points=20,
            max_spread_points=50,
            use_trailing=True,
            use_session=True,
        )

        summary, trades = run_backtest(df, cfg)

        self.assertEqual(summary["bars"], len(df))
        self.assertGreaterEqual(summary["trades"], 1)
        self.assertEqual(summary["trades"], len(trades))

    def test_mz_ma_loader_accepts_mt5_export_csv(self):
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "rates.csv"
            csv_path.write_text(
                "time,open,high,low,close,tick_volume,spread,real_volume\n"
                "2026-04-01 16:30:00,2000,2001,1999,2000.5,100,20,0\n",
                encoding="utf-8",
            )

            df = load_ohlc_csv(csv_path)

            self.assertEqual(list(df.columns), ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
            self.assertEqual(len(df), 1)


if __name__ == "__main__":
    unittest.main()
