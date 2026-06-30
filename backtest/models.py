from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradeRecord:
    entry_time: str
    exit_time: str
    direction: str
    entry_z: float
    exit_z: float
    bars_held: int
    gross_pnl: float
    costs: float
    net_pnl: float


@dataclass
class BacktestMetrics:
    pair_label: str
    selected: bool
    bars: int
    trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    profit_factor: float
    gross_pnl: float
    costs: float
    net_pnl: float
    error: str | None = None


@dataclass
class BacktestResult:
    pair_label: str
    category: str
    selected: bool
    hedge_ratio: float
    halflife_h: float
    trigger_tf: str
    metrics: BacktestMetrics
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
