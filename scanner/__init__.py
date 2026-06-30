"""MODULO 2 — scanner: download/cache storico MT5 per coppie canoniche."""

from scanner.data_fetch import BarSeries, DataFetchError, fetch_bars, overlap_bars
from scanner.scanner import LegScanResult, PairScanResult, scan_all_pairs, scan_pair
from scanner.timeframes import TimeframeError, structural_timeframe, trigger_timeframe_for_category

__all__ = [
    "BarSeries",
    "DataFetchError",
    "LegScanResult",
    "PairScanResult",
    "TimeframeError",
    "fetch_bars",
    "overlap_bars",
    "scan_all_pairs",
    "scan_pair",
    "structural_timeframe",
    "trigger_timeframe_for_category",
]
