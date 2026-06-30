from __future__ import annotations

from typing import Any

import pandas as pd

from backtest.costs import estimate_lots, pnl_scale, round_trip_cost
from backtest.window import slice_bars_last_days
from backtest.metrics import max_drawdown_pct, profit_factor, sharpe_ratio
from backtest.models import BacktestMetrics, BacktestResult, TradeRecord
from backtest.simulator import prepare_trigger_frame, simulate_spread_strategy
from core.config import CANDIDATE_PAIRS, AccountProfile
from engine.cache_loader import CacheLoadError, load_cached_pair
from engine.signals import bar_hours_for_timeframe
from scanner.timeframes import structural_timeframe, trigger_timeframe_for_category


class BacktestError(ValueError):
    """Raised when a pair backtest cannot be completed."""


def _bars_per_year(trigger_tf: str) -> float:
    hours = bar_hours_for_timeframe(trigger_tf)
    return (365.0 * 24.0) / hours


def run_all_pair_backtests(
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
) -> list[BacktestResult]:
    results: list[BacktestResult] = []
    for candidate in CANDIDATE_PAIRS:
        results.append(
            run_pair_backtest(
                profile,
                accounts,
                params,
                candidate.index,
                candidate.leg_a,
                candidate.leg_b,
                candidate.category,
            )
        )
    return results


def run_pair_backtest(
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    index: int,
    leg_a: str,
    leg_b: str,
    category: str,
) -> BacktestResult:
    pair_label = f"{leg_a}/{leg_b}"
    structural_tf = structural_timeframe(params)
    trigger_tf = trigger_timeframe_for_category(category, params)

    try:
        structural_a, structural_b, trigger_a, trigger_b, _ba, _bb = load_cached_pair(
            profile,
            accounts,
            params,
            leg_a,
            leg_b,
            category,
        )
    except CacheLoadError as exc:
        metrics = BacktestMetrics(
            pair_label=pair_label,
            selected=False,
            bars=0,
            trades=0,
            win_rate=0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            profit_factor=0.0,
            gross_pnl=0.0,
            costs=0.0,
            net_pnl=0.0,
            error=str(exc),
        )
        return BacktestResult(
            pair_label=pair_label,
            category=category,
            selected=False,
            hedge_ratio=float("nan"),
            halflife_h=float("nan"),
            trigger_tf=trigger_tf,
            metrics=metrics,
        )

    lookback_days = int(params["backtest"].get("lookback_days", 0) or 0)
    if lookback_days > 0:
        trigger_a = slice_bars_last_days(trigger_a, lookback_days)
        trigger_b = slice_bars_last_days(trigger_b, lookback_days)

    trigger_aligned, beta, halflife_h, selected = prepare_trigger_frame(
        structural_a,
        structural_b,
        trigger_a,
        trigger_b,
        params,
        structural_tf,
    )

    spread, positions, raw_trades = simulate_spread_strategy(
        trigger_aligned,
        beta,
        halflife_h,
        trigger_tf,
        params,
    )

    initial_equity = float(params["backtest"]["initial_equity"])
    equity = initial_equity
    equity_curve = [equity]
    bar_returns: list[float] = []

    price_a = trigger_aligned["close_a"].astype(float)
    price_b = trigger_aligned["close_b"].astype(float)
    lot_a, lot_b = estimate_lots(float(price_a.iloc[-1]), float(price_b.iloc[-1]), beta, params)
    scale = pnl_scale(float(price_a.iloc[-1]), lot_a, float(params["backtest"]["contract_size"]), params)

    trade_records: list[TradeRecord] = []
    costs_total = 0.0

    for i in range(1, len(spread)):
        ds = float(spread.iloc[i] - spread.iloc[i - 1])
        pos = int(positions.iloc[i])
        bar_pnl = pos * ds * scale
        equity += bar_pnl
        equity_curve.append(equity)
        bar_returns.append(bar_pnl)

    for raw in raw_trades:
        entry_i = raw["entry_idx"]
        exit_i = raw["exit_idx"]
        ds_trade = float(spread.iloc[exit_i] - spread.iloc[entry_i])
        direction = raw["direction"]
        sign = 1 if direction == "LONG_SPREAD" else -1
        gross = sign * ds_trade * scale
        spread_a = (
            float(trigger_a.iloc[exit_i]["spread"])
            if "spread" in trigger_a.columns
            else 0.0
        )
        spread_b = (
            float(trigger_b.iloc[exit_i]["spread"])
            if "spread" in trigger_b.columns
            else 0.0
        )
        costs = round_trip_cost(lot_a, lot_b, params, spread_points_a=spread_a, spread_points_b=spread_b)
        net = gross - costs
        costs_total += costs
        trade_records.append(
            TradeRecord(
                entry_time=str(trigger_aligned["time"].iloc[entry_i]),
                exit_time=str(trigger_aligned["time"].iloc[exit_i]),
                direction=direction,
                entry_z=float(raw["entry_z"]),
                exit_z=float(raw["exit_z"]),
                bars_held=int(raw["bars_held"]),
                gross_pnl=gross,
                costs=costs,
                net_pnl=net,
            )
        )

    wins = [t.net_pnl for t in trade_records if t.net_pnl > 0]
    losses = [t.net_pnl for t in trade_records if t.net_pnl <= 0]
    gross_total = equity - initial_equity
    net_total = gross_total - costs_total
    total_return_pct = net_total / initial_equity * 100.0 if initial_equity > 0 else 0.0
    win_rate = (len(wins) / len(trade_records) * 100.0) if trade_records else 0.0

    metrics = BacktestMetrics(
        pair_label=pair_label,
        selected=selected,
        bars=len(trigger_aligned),
        trades=len(trade_records),
        win_rate=win_rate,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct(equity_curve),
        sharpe=sharpe_ratio(bar_returns, _bars_per_year(trigger_tf)),
        profit_factor=profit_factor(wins, losses),
        gross_pnl=gross_total,
        costs=costs_total,
        net_pnl=net_total,
        error=None,
    )

    return BacktestResult(
        pair_label=pair_label,
        category=category,
        selected=selected,
        hedge_ratio=beta,
        halflife_h=halflife_h,
        trigger_tf=trigger_tf,
        metrics=metrics,
        trades=trade_records,
        equity_curve=equity_curve,
    )
