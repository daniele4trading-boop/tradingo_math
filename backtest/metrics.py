from __future__ import annotations

import math

import numpy as np


def max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            dd = (peak - value) / peak * 100.0
            max_dd = max(max_dd, dd)
    return max_dd


def sharpe_ratio(returns: list[float], bars_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    std = float(arr.std(ddof=0))
    if std <= 0:
        return 0.0
    mean = float(arr.mean())
    return (mean / std) * math.sqrt(bars_per_year)


def profit_factor(wins: list[float], losses: list[float]) -> float:
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss <= 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss
