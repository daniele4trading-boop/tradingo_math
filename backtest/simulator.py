from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from engine.selection import safe_evaluate_selection
from engine.signals import bar_hours_for_timeframe, zscore_lookback_bars
from engine.spread import align_closes, build_spread


def _time_stop_bars(
    halflife_h: float,
    trigger_bar_hours: float,
    multiplier: float,
    bar_count: int,
) -> int:
    """Cap time-stop; infinite half-life => no practical time exit."""
    cap = max(bar_count, 1)
    if not math.isfinite(halflife_h) or halflife_h <= 0 or trigger_bar_hours <= 0:
        return cap
    raw = (halflife_h / trigger_bar_hours) * multiplier
    if not math.isfinite(raw):
        return cap
    return int(max(1, min(round(raw), cap)))


def compute_zscore_series(spread: pd.Series, lookback: int) -> pd.Series:
    values = spread.astype(float)
    rolling_mean = values.rolling(lookback, min_periods=max(lookback // 2, 10)).mean()
    rolling_std = values.rolling(lookback, min_periods=max(lookback // 2, 10)).std(ddof=0)
    z = (values - rolling_mean) / rolling_std
    return z.replace([np.inf, -np.inf], np.nan)


def simulate_spread_strategy(
    aligned_trigger: pd.DataFrame,
    hedge_ratio: float,
    halflife_h: float,
    trigger_tf: str,
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
    spread, _ = build_spread(aligned_trigger, beta=hedge_ratio)
    trigger_bar_hours = bar_hours_for_timeframe(trigger_tf)
    lookback = zscore_lookback_bars(halflife_h, trigger_bar_hours, params)
    zseries = compute_zscore_series(spread, lookback)

    signals_cfg = params["signals"]
    entry_z = float(signals_cfg["entry_z"])
    exit_z = float(signals_cfg["exit_z"])
    stop_z = float(signals_cfg["stop_z"])
    time_stop_bars = _time_stop_bars(
        halflife_h,
        trigger_bar_hours,
        float(signals_cfg["time_stop_halflife_mult"]),
        len(spread),
    )

    position = 0
    bars_in_trade = 0
    entry_idx: int | None = None
    entry_z_val = 0.0
    trades: list[dict[str, Any]] = []
    position_series = pd.Series(0, index=spread.index, dtype=int)

    for i in range(1, len(spread)):
        z = zseries.iloc[i]
        if math.isnan(z):
            position_series.iloc[i] = position
            continue

        if position == 0:
            if z <= -entry_z:
                position = 1
                entry_idx = i
                entry_z_val = float(z)
                bars_in_trade = 0
            elif z >= entry_z:
                position = -1
                entry_idx = i
                entry_z_val = float(z)
                bars_in_trade = 0
        else:
            bars_in_trade += 1
            stop_hit = abs(z) >= stop_z
            time_hit = bars_in_trade >= time_stop_bars
            if position == 1:
                exit_signal = z >= -exit_z or stop_hit or time_hit
            else:
                exit_signal = z <= exit_z or stop_hit or time_hit

            if exit_signal and entry_idx is not None:
                trades.append(
                    {
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "LONG_SPREAD" if position == 1 else "SHORT_SPREAD",
                        "entry_z": entry_z_val,
                        "exit_z": float(z),
                        "bars_held": bars_in_trade,
                    }
                )
                position = 0
                entry_idx = None
                bars_in_trade = 0

        position_series.iloc[i] = position

    return spread, position_series, trades


def prepare_trigger_frame(
    structural_a: pd.DataFrame,
    structural_b: pd.DataFrame,
    trigger_a: pd.DataFrame,
    trigger_b: pd.DataFrame,
    params: dict[str, Any],
    structural_tf: str,
) -> tuple[pd.DataFrame, float, float, bool]:
    selection = safe_evaluate_selection(
        "pair",
        "cat",
        structural_a,
        structural_b,
        params,
        bar_hours=bar_hours_for_timeframe(structural_tf),
    )
    structural_aligned = align_closes(structural_a, structural_b)
    trigger_aligned = align_closes(trigger_a, trigger_b)
    _, beta = build_spread(structural_aligned, beta=selection.hedge_ratio)
    return trigger_aligned, beta, selection.halflife_h, selection.selected
