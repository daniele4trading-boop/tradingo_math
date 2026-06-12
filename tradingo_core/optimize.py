"""Parameter grid optimizer for ICT sniper backtests."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from itertools import product
from pathlib import Path

import pandas as pd

from .backtester import BacktestConfig, BacktestReport, ICTSniperBacktester
from .ict_sniper import ICTSniperConfig
from .market_data import LocalDataArchive, parse_utc_datetime


def run_optimization(args) -> int:
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

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    grid = list(
        product(
            parse_float_list(args.min_score_values),
            parse_float_list(args.min_sweep_volume_z_values),
            parse_float_list(args.min_displacement_range_atr_values),
            parse_float_list(args.min_displacement_volume_z_values),
            parse_float_list(args.max_retest_volume_z_values),
            parse_float_list(args.rr_values),
            parse_float_list(args.sl_buffer_atr_values),
        )
    )
    print(f"Optimization grid size: {len(grid)}")

    for idx, (
        min_score,
        min_sweep_volume_z,
        min_displacement_range_atr,
        min_displacement_volume_z,
        max_retest_volume_z,
        rr,
        sl_buffer_atr,
    ) in enumerate(grid, start=1):
        strategy_cfg = ICTSniperConfig(
            min_score=min_score,
            min_sweep_volume_z=min_sweep_volume_z,
            min_displacement_range_atr=min_displacement_range_atr,
            min_displacement_volume_z=min_displacement_volume_z,
            max_retest_volume_z=max_retest_volume_z,
            rr_target=rr,
            sl_buffer_atr=sl_buffer_atr,
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
        row = {
            "rank_score": robust_score(report),
            "grid_index": idx,
            "min_score": min_score,
            "min_sweep_volume_z": min_sweep_volume_z,
            "min_displacement_range_atr": min_displacement_range_atr,
            "min_displacement_volume_z": min_displacement_volume_z,
            "max_retest_volume_z": max_retest_volume_z,
            "rr": rr,
            "sl_buffer_atr": sl_buffer_atr,
            **report_fields(report),
            **monthly_robustness(report),
        }
        rows.append(row)
        if idx % max(1, args.progress_every) == 0 or idx == len(grid):
            best = max(rows, key=lambda r: r["rank_score"])
            print(
                f"{idx}/{len(grid)} best_score={best['rank_score']:.2f} "
                f"trades={best['trade_count']} wr={best['winrate']:.2%} expR={best['expectancy_r']:.2f}"
            )

    rows.sort(key=lambda r: r["rank_score"], reverse=True)
    if args.max_rows > 0:
        rows = rows[: args.max_rows]
    write_rows(output, rows)
    print(f"Saved optimization results: {output}")
    if rows:
        best = rows[0]
        print("Best parameter set")
        for key in [
            "rank_score",
            "trade_count",
            "winrate",
            "expectancy_r",
            "profit_factor",
            "max_drawdown_pct",
            "positive_month_ratio",
            "min_score",
            "min_sweep_volume_z",
            "min_displacement_range_atr",
            "min_displacement_volume_z",
            "max_retest_volume_z",
            "rr",
            "sl_buffer_atr",
        ]:
            print(f"{key}: {best[key]}")
    return 0


def report_fields(report: BacktestReport) -> dict:
    return {
        "setup_count": report.setup_count,
        "trade_count": report.trade_count,
        "initial_equity": report.initial_equity,
        "final_equity": report.final_equity,
        "net_profit": report.final_equity - report.initial_equity,
        "max_drawdown_pct": report.max_drawdown_pct,
        "max_daily_drawdown_pct": report.max_daily_drawdown_pct,
        "winrate": report.winrate,
        "profit_factor": report.profit_factor,
        "expectancy_r": report.expectancy_r,
    }


def monthly_robustness(report: BacktestReport) -> dict:
    closed = [t for t in report.trades if t.status not in ("EXPIRED", "OPEN")]
    if not closed:
        return {
            "months_traded": 0,
            "positive_months": 0,
            "positive_month_ratio": 0.0,
            "worst_month_r": 0.0,
            "avg_month_r": 0.0,
        }
    frame = pd.DataFrame(
        {
            "month": [pd.Timestamp(t.exit_time).strftime("%Y-%m") for t in closed],
            "r": [t.r_result for t in closed],
        }
    )
    monthly = frame.groupby("month")["r"].sum()
    positive = int((monthly > 0).sum())
    return {
        "months_traded": int(len(monthly)),
        "positive_months": positive,
        "positive_month_ratio": float(positive / len(monthly)),
        "worst_month_r": float(monthly.min()),
        "avg_month_r": float(monthly.mean()),
    }


def robust_score(report: BacktestReport) -> float:
    fields = report_fields(report)
    monthly = monthly_robustness(report)
    trade_count = fields["trade_count"]
    if trade_count < 5:
        trade_penalty = (5 - trade_count) * 2.0
    else:
        trade_penalty = 0.0
    dd_penalty = fields["max_drawdown_pct"] * 40.0 + fields["max_daily_drawdown_pct"] * 80.0
    return (
        fields["expectancy_r"] * min(trade_count, 40)
        + monthly["positive_month_ratio"] * 5.0
        + fields["winrate"] * 3.0
        - dd_penalty
        - trade_penalty
    )


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def write_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize ICT sniper parameters on archived data.")
    parser.add_argument("--archive-root", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M1")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--risk-pct", type=float, default=0.005)
    parser.add_argument("--max-daily-dd-pct", type=float, default=0.02)
    parser.add_argument("--max-daily-trades", type=int, default=3)
    parser.add_argument("--signal-evaluation-minutes", type=int, default=5)
    parser.add_argument("--signal-history-bars", type=int, default=2500)
    parser.add_argument("--min-score-values", default="60,65,70")
    parser.add_argument("--min-sweep-volume-z-values", default="0.2,0.4,0.6")
    parser.add_argument("--min-displacement-range-atr-values", default="0.7,0.9,1.1")
    parser.add_argument("--min-displacement-volume-z-values", default="0.0,0.2,0.4")
    parser.add_argument("--max-retest-volume-z-values", default="0.8,1.2")
    parser.add_argument("--rr-values", default="2.0,2.5")
    parser.add_argument("--sl-buffer-atr-values", default="0.05,0.08")
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--max-rows", type=int, default=0, help="Limit rows written after ranking; 0 writes all.")
    return parser


def main() -> None:
    raise SystemExit(run_optimization(build_parser().parse_args()))


if __name__ == "__main__":
    main()
