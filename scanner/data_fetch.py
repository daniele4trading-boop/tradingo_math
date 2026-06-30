from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

import pandas as pd

from scanner.timeframes import TimeframeSpec, expected_bars, resolve_timeframe


class DataFetchError(RuntimeError):
    """Raised when MT5 cannot return usable OHLCV history."""


@dataclass(frozen=True)
class BarSeries:
    broker_symbol: str
    timeframe: str
    bars: pd.DataFrame
    requested: int
    minimum_required: int

    @property
    def count(self) -> int:
        return len(self.bars)

    @property
    def ok(self) -> bool:
        return self.count >= self.minimum_required

    @property
    def first_time(self) -> str:
        if self.bars.empty:
            return ""
        return str(self.bars["time"].iloc[0])

    @property
    def last_time(self) -> str:
        if self.bars.empty:
            return ""
        return str(self.bars["time"].iloc[-1])


def fetch_bars(
    mt5: ModuleType,
    broker_symbol: str,
    timeframe_label: str,
    lookback_days: int,
) -> BarSeries:
    timeframe, spec = resolve_timeframe(mt5, timeframe_label)
    requested, minimum = expected_bars(spec, lookback_days)

    selected = mt5.symbol_select(broker_symbol, True)
    if not selected:
        raise DataFetchError(
            f"symbol_select fallito per {broker_symbol}: {mt5.last_error()}"
        )

    rates = mt5.copy_rates_from_pos(broker_symbol, timeframe, 0, requested)
    if rates is None:
        raise DataFetchError(
            f"copy_rates_from_pos fallito per {broker_symbol} {timeframe_label}: {mt5.last_error()}"
        )
    if len(rates) == 0:
        raise DataFetchError(f"storico vuoto per {broker_symbol} {timeframe_label}")

    frame = pd.DataFrame(rates)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    frame = frame.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

    return BarSeries(
        broker_symbol=broker_symbol,
        timeframe=timeframe_label.upper(),
        bars=frame,
        requested=requested,
        minimum_required=minimum,
    )


def overlap_bars(series_a: BarSeries, series_b: BarSeries) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    merged_a = series_a.bars[["time"]].merge(
        series_b.bars[["time"]],
        on="time",
        how="inner",
    )
    overlap = len(merged_a)
    if overlap == 0:
        return 0, series_a.bars.iloc[0:0], series_b.bars.iloc[0:0]

    aligned_a = series_a.bars[series_a.bars["time"].isin(merged_a["time"])].reset_index(drop=True)
    aligned_b = series_b.bars[series_b.bars["time"].isin(merged_a["time"])].reset_index(drop=True)
    return overlap, aligned_a, aligned_b
