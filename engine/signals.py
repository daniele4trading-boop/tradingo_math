from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from engine.spread import SpreadError, align_closes, build_spread


class SignalState(str, Enum):
    FLAT = "FLAT"
    LONG_SPREAD = "LONG_SPREAD"
    SHORT_SPREAD = "SHORT_SPREAD"


@dataclass(frozen=True)
class SignalSnapshot:
    zscore: float
    lookback_bars: int
    state: SignalState
    entry_z: float
    exit_z: float
    stop_z: float
    recommended_trigger_tf: str


def bar_hours_for_timeframe(label: str) -> float:
    mapping = {"M15": 0.25, "H1": 1.0, "H4": 4.0, "D1": 24.0}
    key = label.upper()
    if key not in mapping:
        raise ValueError(f"timeframe non supportato: {label}")
    return mapping[key]


def recommend_trigger_timeframe(halflife_hours: float, params: dict[str, Any]) -> str:
    rules = params["timeframe_rules"]
    if halflife_hours <= float(rules["halflife_under_hours_to_m15"]):
        return "M15"
    if halflife_hours <= float(rules["halflife_under_hours_to_h1"]):
        return "H1"
    return str(params["data"]["trigger_timeframe_default"]).upper()


def zscore_lookback_bars(halflife_hours: float, trigger_bar_hours: float, params: dict[str, Any]) -> int:
    multiplier = float(params["signals"]["zscore_lookback_multiplier"])
    if not math.isfinite(halflife_hours) or halflife_hours <= 0:
        return 50
    bars = int(round((halflife_hours / trigger_bar_hours) * multiplier))
    return max(bars, 20)


def compute_zscore(spread: pd.Series, lookback: int) -> float:
    window = spread.dropna().tail(lookback)
    if len(window) < max(lookback // 2, 10):
        raise SpreadError("finestra z-score insufficiente")
    mean = float(window.mean())
    std = float(window.std(ddof=0))
    if std <= 0:
        raise SpreadError("deviazione standard nulla per z-score")
    return float((window.iloc[-1] - mean) / std)


def classify_signal(zscore: float, params: dict[str, Any]) -> SignalState:
    signals = params["signals"]
    entry_z = float(signals["entry_z"])
    exit_z = float(signals["exit_z"])
    stop_z = float(signals["stop_z"])

    if abs(zscore) >= stop_z:
        return SignalState.FLAT
    if zscore <= -entry_z:
        return SignalState.LONG_SPREAD
    if zscore >= entry_z:
        return SignalState.SHORT_SPREAD
    if abs(zscore) <= exit_z:
        return SignalState.FLAT
    return SignalState.FLAT


def build_signal_snapshot(
    trigger_a: pd.DataFrame,
    trigger_b: pd.DataFrame,
    hedge_ratio: float,
    halflife_hours: float,
    params: dict[str, Any],
    *,
    trigger_tf: str,
) -> SignalSnapshot:
    aligned = align_closes(trigger_a, trigger_b)
    spread, _beta = build_spread(aligned, beta=hedge_ratio)
    trigger_bar_hours = bar_hours_for_timeframe(trigger_tf)
    lookback = zscore_lookback_bars(halflife_hours, trigger_bar_hours, params)
    zscore = compute_zscore(spread, lookback)
    recommended = recommend_trigger_timeframe(halflife_hours, params)
    state = classify_signal(zscore, params)
    signals = params["signals"]
    return SignalSnapshot(
        zscore=zscore,
        lookback_bars=lookback,
        state=state,
        entry_z=float(signals["entry_z"]),
        exit_z=float(signals["exit_z"]),
        stop_z=float(signals["stop_z"]),
        recommended_trigger_tf=recommended,
    )
