"""
Reusable research and execution infrastructure for TradinGo systems.

The package is intentionally independent from the current live prop/hedge
engines so data, backtests, and future strategies can be developed safely.
"""

from .market_data import LocalDataArchive, MarketDataRequest, MT5HistoricalDownloader
from .ict_sniper import ICTSniperConfig, ICTSniperSetup, ICTSniperStrategy
from .backtester import BacktestConfig, BacktestReport, ICTSniperBacktester, TradeResult
from .optimize import robust_score

__all__ = [
    "BacktestConfig",
    "BacktestReport",
    "ICTSniperBacktester",
    "ICTSniperConfig",
    "ICTSniperSetup",
    "ICTSniperStrategy",
    "LocalDataArchive",
    "MarketDataRequest",
    "MT5HistoricalDownloader",
    "robust_score",
    "TradeResult",
]
