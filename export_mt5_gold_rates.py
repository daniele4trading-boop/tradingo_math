import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export MT5 Gold OHLC rates to CSV for Python backtests.")
    parser.add_argument("--symbol", default="XAUUSD", help="Broker symbol, for example XAUUSD, GOLD, or GOLD#.")
    parser.add_argument("--timeframe", choices=TIMEFRAMES.keys(), default="M1")
    parser.add_argument("--from-date", required=True, type=parse_dt, help="Start date, e.g. 2026-04-01T00:00:00")
    parser.add_argument("--to-date", required=True, type=parse_dt, help="End date, e.g. 2026-04-30T23:59:59")
    parser.add_argument("--output", required=True, type=Path, help="Output CSV path.")
    parser.add_argument("--terminal-path", default=None, help="Optional terminal64.exe path.")
    parser.add_argument("--login", type=int, default=None, help="Optional MT5 login.")
    parser.add_argument("--password", default=None, help="Optional MT5 password.")
    parser.add_argument("--server", default=None, help="Optional MT5 server.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("MetaTrader5 package is required. Run this on the Windows VPS MT5 environment.") from exc

    init_kwargs = {}
    if args.terminal_path:
        init_kwargs["path"] = args.terminal_path
    if args.login is not None:
        init_kwargs["login"] = args.login
    if args.password:
        init_kwargs["password"] = args.password
    if args.server:
        init_kwargs["server"] = args.server

    if not mt5.initialize(**init_kwargs):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

    try:
        timeframe = getattr(mt5, TIMEFRAMES[args.timeframe])
        rates = mt5.copy_rates_range(args.symbol, timeframe, args.from_date, args.to_date)
        if rates is None or len(rates) == 0:
            raise SystemExit(f"No rates returned for {args.symbol} {args.timeframe}: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        print(f"Exported {len(df)} bars to {args.output}")
    finally:
        mt5.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
