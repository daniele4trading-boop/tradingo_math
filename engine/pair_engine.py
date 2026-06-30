from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.config import AccountProfile
from engine.cache_loader import CacheLoadError, load_cached_pair
from engine.selection import SelectionResult, safe_evaluate_selection
from engine.signals import SignalSnapshot, bar_hours_for_timeframe, build_signal_snapshot
from engine.spread import SpreadError
from scanner.timeframes import structural_timeframe, trigger_timeframe_for_category


@dataclass(frozen=True)
class PairEngineResult:
    index: int
    pair_label: str
    category: str
    broker_a: str
    broker_b: str
    structural_tf: str
    trigger_tf: str
    selection: SelectionResult
    signal: SignalSnapshot | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and self.signal is not None


def analyze_cached_pair(
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    index: int,
    leg_a: str,
    leg_b: str,
    category: str,
) -> PairEngineResult:
    pair_label = f"{leg_a}/{leg_b}"
    structural_tf = structural_timeframe(params)
    trigger_tf = trigger_timeframe_for_category(category, params)

    try:
        structural_a, structural_b, trigger_a, trigger_b, broker_a, broker_b = load_cached_pair(
            profile,
            accounts,
            params,
            leg_a,
            leg_b,
            category,
        )
    except CacheLoadError as exc:
        return PairEngineResult(
            index=index,
            pair_label=pair_label,
            category=category,
            broker_a="",
            broker_b="",
            structural_tf=structural_tf,
            trigger_tf=trigger_tf,
            selection=safe_evaluate_selection(pair_label, category, pd.DataFrame(), pd.DataFrame(), params),
            signal=None,
            error=str(exc),
        )

    selection = safe_evaluate_selection(
        pair_label,
        category,
        structural_a,
        structural_b,
        params,
        bar_hours=bar_hours_for_timeframe(structural_tf),
    )

    try:
        signal = build_signal_snapshot(
            trigger_a,
            trigger_b,
            selection.hedge_ratio,
            selection.halflife_h,
            params,
            trigger_tf=trigger_tf,
        )
    except (SpreadError, ValueError) as exc:
        return PairEngineResult(
            index=index,
            pair_label=pair_label,
            category=category,
            broker_a=broker_a,
            broker_b=broker_b,
            structural_tf=structural_tf,
            trigger_tf=trigger_tf,
            selection=selection,
            signal=None,
            error=str(exc),
        )

    return PairEngineResult(
        index=index,
        pair_label=pair_label,
        category=category,
        broker_a=broker_a,
        broker_b=broker_b,
        structural_tf=structural_tf,
        trigger_tf=trigger_tf,
        selection=selection,
        signal=signal,
        error=None,
    )
