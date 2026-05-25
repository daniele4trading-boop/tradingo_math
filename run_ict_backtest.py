"""
CLI runner for the ICT Order Block backtester.

Examples:
  python run_ict_backtest.py --csv-dir data --symbols XAUUSD BTCUSD ETHUSD
  python run_ict_backtest.py --source mt5 --bars 10000 --timeframe M5

MT5 credentials are read from environment variables unless passed explicitly:
  MT5_TERMINAL_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from ict_order_block_backtester import BacktestConfig, ICTOrderBlockBacktester


TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest ICT Order Block strategy.")
    parser.add_argument("--symbols", nargs="+", default=["XAUUSD", "BTCUSD", "ETHUSD"])
    parser.add_argument("--source", choices=["csv", "mt5"], default="csv")
    parser.add_argument("--csv-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("backtest_results"))
    parser.add_argument("--config", type=Path, default=Path("ict_backtest_config.json"))
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAME_NAMES), default="M5")
    parser.add_argument("--bars", type=int, default=5000)
    parser.add_argument("--mt5-path", default=os.getenv("MT5_TERMINAL_PATH"))
    parser.add_argument("--mt5-login", type=int, default=int(os.getenv("MT5_LOGIN", "0") or "0"))
    parser.add_argument("--mt5-password", default=os.getenv("MT5_PASSWORD"))
    parser.add_argument("--mt5-server", default=os.getenv("MT5_SERVER"))
    parser.add_argument("--disable-max-gain", action="store_true", help="Close at TP1 without upgrades/trailing.")
    return parser.parse_args()


def load_csv(symbol: str, csv_dir: Path) -> pd.DataFrame:
    candidates = [
        csv_dir / f"{symbol}.csv",
        csv_dir / f"{symbol.lower()}.csv",
        csv_dir / f"{symbol.upper()}.csv",
    ]
    for path in candidates:
        if path.exists():
            return pd.read_csv(path)
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No CSV found for {symbol}. Checked: {checked}")


def mt5_timeframe(mt5_module, timeframe: str) -> int:
    attr = TIMEFRAME_NAMES[timeframe]
    try:
        return int(getattr(mt5_module, attr))
    except AttributeError as exc:
        raise ValueError(f"MetaTrader5 module does not expose {attr}") from exc


def load_mt5(
    symbol: str,
    timeframe: str,
    bars: int,
    terminal_path: Optional[str],
    login: int,
    password: Optional[str],
    server: Optional[str],
) -> pd.DataFrame:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is not installed in this Python environment") from exc

    init_kwargs = {}
    if terminal_path:
        init_kwargs["path"] = terminal_path
    if login:
        init_kwargs["login"] = login
    if password:
        init_kwargs["password"] = password
    if server:
        init_kwargs["server"] = server

    if not mt5.initialize(**init_kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe(mt5, timeframe), 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 returned no rates for {symbol}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df
    finally:
        mt5.shutdown()


def write_result(output_dir: Path, symbol: str, result) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    trades = result.trades_frame()
    if not trades.empty:
        trades.to_csv(output_dir / f"{symbol}_trades.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / f"{symbol}_trades.csv", index=False)

    obs = result.order_blocks_frame()
    if not obs.empty:
        obs.to_csv(output_dir / f"{symbol}_order_blocks.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / f"{symbol}_order_blocks.csv", index=False)

    (output_dir / f"{symbol}_summary.json").write_text(
        json.dumps(result.summary, indent=2, default=str),
        encoding="utf-8",
    )


def print_summary(summaries: Iterable[dict]) -> None:
    print("\nICT ORDER BLOCK BACKTEST SUMMARY")
    print("=" * 100)
    print(
        f"{'Symbol':<10} {'Trades':>7} {'Win%':>8} {'NetPts':>12} "
        f"{'AvgR':>8} {'OBs':>7} {'ValidOBs':>9} {'Mitigated':>10}"
    )
    for summary in summaries:
        print(
            f"{summary['symbol']:<10} "
            f"{summary['trades']:>7} "
            f"{summary['win_rate'] * 100:>7.1f}% "
            f"{summary['net_pnl_points']:>12.2f} "
            f"{summary['average_r']:>8.2f} "
            f"{summary['order_blocks_detected']:>7} "
            f"{summary['order_blocks_valid']:>9} "
            f"{summary['order_blocks_invalidated_before_retest']:>10}"
        )
    print("=" * 100)


def main() -> None:
    args = parse_args()
    cfg = BacktestConfig.from_json(args.config) if args.config.exists() else BacktestConfig()
    if args.disable_max_gain:
        cfg.enable_max_gain = False

    backtester = ICTOrderBlockBacktester(cfg)
    summaries = []

    for symbol in args.symbols:
        if args.source == "mt5":
            df = load_mt5(
                symbol=symbol,
                timeframe=args.timeframe,
                bars=args.bars,
                terminal_path=args.mt5_path,
                login=args.mt5_login,
                password=args.mt5_password,
                server=args.mt5_server,
            )
        else:
            df = load_csv(symbol, args.csv_dir)

        result = backtester.run(df, symbol)
        write_result(args.output_dir, symbol, result)
        summaries.append(result.summary)

    (args.output_dir / "combined_summary.json").write_text(
        json.dumps(summaries, indent=2, default=str),
        encoding="utf-8",
    )
    print_summary(summaries)
    print(f"\nResults written to: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()

