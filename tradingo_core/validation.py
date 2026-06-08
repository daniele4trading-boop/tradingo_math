"""CLI validation runner for archived ICT sniper backtests."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .backtester import BacktestConfig, ICTSniperBacktester
from .ict_sniper import ICTSniperConfig
from .market_data import LocalDataArchive, parse_utc_datetime


def run_validation(args) -> int:
    archive = LocalDataArchive(args.archive_root)
    data = archive.read_rates(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=parse_utc_datetime(args.start),
        end=parse_utc_datetime(args.end),
    )
    if data.empty:
        print("No archived data found for the requested range.")
        return 2

    strategy_cfg = ICTSniperConfig(
        min_score=args.min_score,
        rr_target=args.rr,
        max_daily_trades=args.max_daily_trades,
    )
    backtest_cfg = BacktestConfig(
        initial_equity=args.initial_equity,
        risk_per_trade_pct=args.risk_pct,
        max_daily_dd_pct=args.max_daily_dd_pct,
        max_daily_trades=args.max_daily_trades,
        signal_evaluation_minutes=args.signal_evaluation_minutes,
        signal_history_bars=args.signal_history_bars,
    )
    report = ICTSniperBacktester(strategy_cfg, backtest_cfg).run(data)

    print("ICT Sniper validation report")
    print("----------------------------")
    print(f"symbol:                 {args.symbol}")
    print(f"range:                  {args.start} -> {args.end}")
    print(f"setups:                 {report.setup_count}")
    print(f"closed trades:          {report.trade_count}")
    print(f"final equity:           {report.final_equity:.2f}")
    print(f"winrate:                {report.winrate:.2%}")
    print(f"profit factor:          {report.profit_factor:.2f}")
    print(f"expectancy R:           {report.expectancy_r:.2f}")
    print(f"max drawdown:           {report.max_drawdown_pct:.2%}")
    print(f"max daily drawdown:     {report.max_daily_drawdown_pct:.2%}")

    if args.trades_csv:
        write_trades_csv(report.trades, Path(args.trades_csv))
        print(f"trades csv:             {args.trades_csv}")

    return 0


def write_trades_csv(trades, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "setup_time",
                "entry_time",
                "exit_time",
                "direction",
                "entry",
                "sl",
                "tp",
                "score",
                "status",
                "r_result",
                "pnl",
                "session",
                "notes",
            ]
        )
        for trade in trades:
            writer.writerow(
                [
                    trade.setup_time,
                    trade.entry_time,
                    trade.exit_time,
                    trade.direction,
                    trade.entry,
                    trade.sl,
                    trade.tp,
                    trade.score,
                    trade.status,
                    trade.r_result,
                    trade.pnl,
                    trade.session,
                    "|".join(trade.notes),
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ICT sniper validation on archived data.")
    parser.add_argument("--archive-root", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M1")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--risk-pct", type=float, default=0.005)
    parser.add_argument("--max-daily-dd-pct", type=float, default=0.02)
    parser.add_argument("--max-daily-trades", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=65.0)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--signal-evaluation-minutes", type=int, default=5)
    parser.add_argument("--signal-history-bars", type=int, default=2500)
    parser.add_argument("--trades-csv", default=None)
    return parser


def main() -> None:
    raise SystemExit(run_validation(build_parser().parse_args()))


if __name__ == "__main__":
    main()
