#!/usr/bin/env python3
"""Run LQS-MTF backtest on local XAUUSD M1 CSV data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest.data_loader import load_m1_directory, load_parquet_m1
from backtest.engine import BacktestEngine
from dataclasses import replace

from strategies.lqs_mtf import LQSMtfConfig, LQSMtfStrategy, LQSProfile


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LQS-MTF backtest runner")
    p.add_argument("--data-dir", default="data/XAUUSD/M1", help="Directory with broker M1 CSV files")
    p.add_argument("--parquet-dir", default=None, help="Optional parquet directory fallback")
    p.add_argument("--from", dest="date_from", default=None)
    p.add_argument("--to", dest="date_to", default=None)
    p.add_argument("--report", default="results/backtest_metrics.json")
    p.add_argument("--profile", default=None, choices=["H4_M15", "H1_M15", "H1_M5", "M15_M5"],
                   help="LQS profile (default: from config.json)")
    p.add_argument("--risk-usd", type=float, default=100.0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    results_dir = Path("results")
    results_dir.mkdir(parents=True, exist_ok=True)

    if data_dir.exists() and any(data_dir.glob("*.csv")):
        m1 = load_m1_directory(data_dir)
        source = str(data_dir)
    elif args.parquet_dir:
        m1 = load_parquet_m1(Path(args.parquet_dir).glob("*.parquet"))
        source = args.parquet_dir
    else:
        raise FileNotFoundError(f"No data in {data_dir}")

    start = pd.Timestamp(args.date_from, tz="UTC") if args.date_from else None
    end = pd.Timestamp(args.date_to, tz="UTC") if args.date_to else None

    cfg_path = Path("config.json")
    if cfg_path.exists():
        with cfg_path.open() as f:
            raw = json.load(f)
        strategy = LQSMtfStrategy.from_json_config(raw)
        config = strategy.cfg
    else:
        config = LQSMtfConfig()
    if args.profile:
        config = replace(config, profile=LQSProfile(args.profile))

    engine = BacktestEngine(m1, config=config, risk_per_trade_usd=args.risk_usd)
    result = engine.run(start=start, end=end)

    result.trades.to_csv(results_dir / "backtest_trades.csv", index=False)
    result.equity.to_csv(results_dir / "equity_curve.csv", index=False)

    payload = {
        "data_source": source,
        "date_from": str(m1["time"].min()),
        "date_to": str(m1["time"].max()),
        "backtest_from": str(start) if start else None,
        "backtest_to": str(end) if end else None,
        "bars_m1": len(m1),
        "profile": config.profile.value,
        "metrics": result.metrics,
    }
    with (results_dir / "backtest_metrics.json").open("w") as f:
        json.dump(payload, f, indent=2)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
