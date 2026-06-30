"""MODULO 3 — signal engine: selezione stat-arb + z-score su cache Modulo 2."""

from engine.cache_loader import CacheLoadError, load_cached_pair
from engine.pair_engine import PairEngineResult, analyze_cached_pair
from engine.selection import SelectionResult, evaluate_selection, safe_evaluate_selection
from engine.signals import SignalSnapshot, SignalState, build_signal_snapshot, recommend_trigger_timeframe
from engine.spread import SpreadError, align_closes, build_spread, hedge_ratio
from engine.statistics import adf_pvalue, cointegration_pvalue, halflife_hours, pearson_correlation

__all__ = [
    "CacheLoadError",
    "PairEngineResult",
    "SelectionResult",
    "SignalSnapshot",
    "SignalState",
    "SpreadError",
    "analyze_cached_pair",
    "build_signal_snapshot",
    "build_spread",
    "evaluate_selection",
    "load_cached_pair",
    "recommend_trigger_timeframe",
    "safe_evaluate_selection",
]
