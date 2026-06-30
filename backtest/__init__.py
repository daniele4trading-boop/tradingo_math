"""Backtest package — spread z-score strategy on Modulo 2 cache."""

from backtest.models import BacktestMetrics, BacktestResult, TradeRecord
from backtest.runner import run_pair_backtest

__all__ = [
    "BacktestMetrics",
    "BacktestResult",
    "TradeRecord",
    "run_pair_backtest",
]
