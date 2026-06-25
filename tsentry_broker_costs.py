"""
Broker cost tooling for TSEntry validation.

The module has two jobs:

1. Export real broker spread metrics from an MT5 terminal into data/backtests/.
2. Apply exported broker costs to an existing TSEntry trade list.

It is safe to import on Linux without MetaTrader5 installed; only the MT5 export
command requires the package and a local terminal.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd


POINT_SIZE_DEFAULT = 0.01
START_CAPITAL_DEFAULT = 50_000.0
RISK_FRACTION_DEFAULT = 0.01


@dataclass(frozen=True)
class BrokerCostProfile:
    broker: str
    symbol: str
    source_file: str
    point_size: float
    spread_points_mean: float
    spread_points_median: float
    spread_points_p75: float
    spread_points_p90: float
    spread_points_p95: float
    spread_points_max: float
    samples: int
    commission_r: float
    slippage_points: float
    notes: str = ""


def load_trade_list(path: Path) -> pd.DataFrame:
    trades = pd.read_csv(path)
    required = {"family", "entry_time", "exit_time", "entry_price", "stop_loss", "result_r"}
    missing = required.difference(trades.columns)
    if missing:
        raise ValueError(f"Missing trade columns: {sorted(missing)}")
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    trades["risk_price"] = (trades["entry_price"] - trades["stop_loss"]).abs()
    return trades[trades["risk_price"] > 0].copy()


def load_profile(path: Path) -> BrokerCostProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    return BrokerCostProfile(**data)


def summarize_spreads(
    ticks: pd.DataFrame,
    broker: str,
    symbol: str,
    source_file: Path,
    point_size: float,
    commission_r: float,
    slippage_points: float,
    notes: str = "",
) -> BrokerCostProfile:
    if ticks.empty:
        raise ValueError("No tick/spread data to summarize")
    if "spread_points" not in ticks.columns:
        if not {"bid", "ask"}.issubset(ticks.columns):
            raise ValueError("Ticks must have spread_points or bid/ask columns")
        ticks = ticks.copy()
        ticks["spread_points"] = (ticks["ask"] - ticks["bid"]) / point_size
    spread = pd.to_numeric(ticks["spread_points"], errors="coerce").dropna()
    spread = spread[spread >= 0]
    if spread.empty:
        raise ValueError("No valid non-negative spread values")
    return BrokerCostProfile(
        broker=broker,
        symbol=symbol,
        source_file=str(source_file),
        point_size=point_size,
        spread_points_mean=float(spread.mean()),
        spread_points_median=float(spread.median()),
        spread_points_p75=float(spread.quantile(0.75)),
        spread_points_p90=float(spread.quantile(0.90)),
        spread_points_p95=float(spread.quantile(0.95)),
        spread_points_max=float(spread.max()),
        samples=int(len(spread)),
        commission_r=float(commission_r),
        slippage_points=float(slippage_points),
        notes=notes,
    )


def apply_profile(
    trades: pd.DataFrame,
    profile: BrokerCostProfile,
    spread_quantile: str,
    start_capital: float,
    risk_fraction: float,
) -> pd.DataFrame:
    spread_attr = {
        "mean": "spread_points_mean",
        "median": "spread_points_median",
        "p75": "spread_points_p75",
        "p90": "spread_points_p90",
        "p95": "spread_points_p95",
        "max": "spread_points_max",
    }.get(spread_quantile)
    if spread_attr is None:
        raise ValueError("spread_quantile must be one of mean, median, p75, p90, p95, max")

    spread_points = float(getattr(profile, spread_attr))
    price_cost = (spread_points + profile.slippage_points) * profile.point_size
    out = trades.copy()
    out["broker"] = profile.broker
    out["spread_quantile"] = spread_quantile
    out["spread_points_applied"] = spread_points
    out["slippage_points_applied"] = profile.slippage_points
    out["commission_r_applied"] = profile.commission_r
    out["cost_r"] = (price_cost / out["risk_price"]) + profile.commission_r
    out["result_r_stressed"] = out["result_r"] - out["cost_r"]
    out["pnl_stressed"] = out["result_r_stressed"] * (start_capital * risk_fraction)
    return out


def summarize_trades(df: pd.DataFrame, start_capital: float) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "winrate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "total_r": 0.0,
            "net_pnl": 0.0,
            "max_daily_drawdown": 0.0,
            "max_drawdown": 0.0,
            "capital_final": start_capital,
        }
    gp = float(df.loc[df["pnl_stressed"] > 0, "pnl_stressed"].sum())
    gl = float(df.loc[df["pnl_stressed"] < 0, "pnl_stressed"].sum())
    pf = gp / abs(gl) if gl < 0 else (math.inf if gp > 0 else 0.0)
    ordered = df.sort_values("exit_time").copy()
    equity = start_capital + ordered["pnl_stressed"].cumsum()
    peak = equity.cummax().clip(lower=start_capital)
    dd = equity - peak
    return {
        "trades": int(len(df)),
        "winrate": float((df["result_r_stressed"] > 0).mean()),
        "profit_factor": float(pf),
        "expectancy_r": float(df["result_r_stressed"].mean()),
        "total_r": float(df["result_r_stressed"].sum()),
        "net_pnl": float(df["pnl_stressed"].sum()),
        "max_daily_drawdown": float(max_daily_drawdown(df)),
        "max_drawdown": float(dd.min()),
        "capital_final": float(start_capital + df["pnl_stressed"].sum()),
    }


def max_daily_drawdown(df: pd.DataFrame) -> float:
    work = df.copy()
    work["ny_day"] = work["exit_time"].dt.tz_convert("America/New_York").dt.date
    worst = 0.0
    for _, group in work.sort_values("exit_time").groupby("ny_day"):
        cumulative = group["pnl_stressed"].cumsum()
        peak = cumulative.cummax().clip(lower=0.0)
        dd = cumulative - peak
        worst = min(worst, float(dd.min()))
    return worst


def command_profile_from_csv(args: argparse.Namespace) -> int:
    ticks = pd.read_csv(args.csv)
    profile = summarize_spreads(
        ticks=ticks,
        broker=args.broker,
        symbol=args.symbol,
        source_file=args.csv,
        point_size=args.point_size,
        commission_r=args.commission_r,
        slippage_points=args.slippage_points,
        notes=args.notes,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
    print(json.dumps(asdict(profile), indent=2))
    return 0


def command_apply_profiles(args: argparse.Namespace) -> int:
    trades = load_trade_list(args.trades)
    rows = []
    stressed_frames = []
    for profile_path in args.profile:
        profile = load_profile(profile_path)
        stressed = apply_profile(
            trades=trades,
            profile=profile,
            spread_quantile=args.spread_quantile,
            start_capital=args.start_capital,
            risk_fraction=args.risk_fraction,
        )
        stressed_frames.append(stressed)
        for family, family_df in stressed.groupby("family"):
            row = summarize_trades(family_df, args.start_capital)
            row.update(
                {
                    "broker": profile.broker,
                    "symbol": profile.symbol,
                    "family": family,
                    "spread_quantile": args.spread_quantile,
                    "spread_points": float(getattr(profile, f"spread_points_{args.spread_quantile}")),
                    "slippage_points": profile.slippage_points,
                    "commission_r": profile.commission_r,
                    "avg_cost_r": float(family_df["cost_r"].mean()),
                }
            )
            rows.append(row)

    summary = pd.DataFrame(rows)
    args.out_summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out_summary, index=False)
    if args.out_trades:
        pd.concat(stressed_frames, ignore_index=True).to_csv(args.out_trades, index=False)
    print(summary.to_string(index=False))
    return 0


def command_export_mt5(args: argparse.Namespace) -> int:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is required for export-mt5") from exc

    kwargs = {}
    path = args.mt5_path or os.environ.get("TSENTRY_MT5_PATH")
    login = args.mt5_login or os.environ.get("TSENTRY_MT5_LOGIN")
    password = args.mt5_password or os.environ.get("TSENTRY_MT5_PASSWORD")
    server = args.mt5_server or os.environ.get("TSENTRY_MT5_SERVER")
    if path:
        kwargs["path"] = path
    if login:
        kwargs["login"] = int(login)
    if password:
        kwargs["password"] = password
    if server:
        kwargs["server"] = server

    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(args.symbol, True):
            raise RuntimeError(f"symbol_select failed for {args.symbol}: {mt5.last_error()}")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        ticks = mt5.copy_ticks_range(args.symbol, start, end, mt5.COPY_TICKS_INFO)
        if ticks is None or len(ticks) == 0:
            raise RuntimeError(f"No ticks exported for {args.symbol}: {mt5.last_error()}")
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["spread_points"] = (df["ask"] - df["bid"]) / args.point_size
        args.out_ticks.parent.mkdir(parents=True, exist_ok=True)
        df[["time", "bid", "ask", "spread_points"]].to_csv(args.out_ticks, index=False)
        profile = summarize_spreads(
            ticks=df,
            broker=args.broker,
            symbol=args.symbol,
            source_file=args.out_ticks,
            point_size=args.point_size,
            commission_r=args.commission_r,
            slippage_points=args.slippage_points,
            notes=f"MT5 tick export, last {args.days} days",
        )
        args.out_profile.parent.mkdir(parents=True, exist_ok=True)
        args.out_profile.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        print(json.dumps(asdict(profile), indent=2))
    finally:
        mt5.shutdown()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TSEntry broker cost export and validation")
    sub = parser.add_subparsers(dest="command", required=True)

    mt5 = sub.add_parser("export-mt5", help="Export spread ticks and profile from a local MT5 terminal")
    mt5.add_argument("--broker", required=True)
    mt5.add_argument("--symbol", default="XAUUSD")
    mt5.add_argument("--days", type=int, default=30)
    mt5.add_argument("--point-size", type=float, default=POINT_SIZE_DEFAULT)
    mt5.add_argument("--commission-r", type=float, default=0.0)
    mt5.add_argument("--slippage-points", type=float, default=0.0)
    mt5.add_argument("--out-ticks", required=True, type=Path)
    mt5.add_argument("--out-profile", required=True, type=Path)
    mt5.add_argument("--mt5-path")
    mt5.add_argument("--mt5-login")
    mt5.add_argument("--mt5-password")
    mt5.add_argument("--mt5-server")
    mt5.set_defaults(func=command_export_mt5)

    profile = sub.add_parser("profile-from-csv", help="Build broker cost profile from bid/ask or spread CSV")
    profile.add_argument("--broker", required=True)
    profile.add_argument("--symbol", default="XAUUSD")
    profile.add_argument("--csv", required=True, type=Path)
    profile.add_argument("--point-size", type=float, default=POINT_SIZE_DEFAULT)
    profile.add_argument("--commission-r", type=float, default=0.0)
    profile.add_argument("--slippage-points", type=float, default=0.0)
    profile.add_argument("--notes", default="")
    profile.add_argument("--out", required=True, type=Path)
    profile.set_defaults(func=command_profile_from_csv)

    apply = sub.add_parser("apply-profiles", help="Apply one or more broker cost profiles to a trade list")
    apply.add_argument("--trades", required=True, type=Path)
    apply.add_argument("--profile", nargs="+", required=True, type=Path)
    apply.add_argument("--spread-quantile", default="p95", choices=("mean", "median", "p75", "p90", "p95", "max"))
    apply.add_argument("--start-capital", type=float, default=START_CAPITAL_DEFAULT)
    apply.add_argument("--risk-fraction", type=float, default=RISK_FRACTION_DEFAULT)
    apply.add_argument("--out-summary", required=True, type=Path)
    apply.add_argument("--out-trades", type=Path)
    apply.set_defaults(func=command_apply_profiles)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
