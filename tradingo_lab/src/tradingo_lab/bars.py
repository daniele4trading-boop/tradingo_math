from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import ResearchConfig


def load_tick_files(paths: Iterable[str | Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        file_path = Path(path)
        if file_path.exists():
            frames.append(pd.read_parquet(file_path))
    if not frames:
        return pd.DataFrame()
    ticks = pd.concat(frames, ignore_index=True)
    return normalize_tick_index(ticks)


def discover_tick_files(config: ResearchConfig) -> list[Path]:
    root = config.storage.ticks_dir / config.symbol
    if not root.exists():
        return []
    return sorted(root.glob("**/*.parquet"))


def normalize_tick_index(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks.empty:
        return ticks
    result = ticks.copy()
    result["time_utc"] = pd.to_datetime(result["time_utc"], utc=True)
    result = result.sort_values("time_utc").drop_duplicates(subset=["time_utc", "bid", "ask"])
    return result


def build_bars_from_ticks(ticks: pd.DataFrame, timeframe: str = "1min") -> pd.DataFrame:
    if ticks.empty:
        return pd.DataFrame()

    data = normalize_tick_index(ticks).set_index("time_utc")
    price_col = "mid" if "mid" in data.columns else "bid"
    grouped = data.resample(timeframe)

    bars = grouped[price_col].ohlc()
    bars.columns = ["open", "high", "low", "close"]
    bars["tick_count"] = grouped[price_col].count()

    if "bid" in data.columns:
        bid_ohlc = grouped["bid"].ohlc()
        bars["bid_open"] = bid_ohlc["open"]
        bars["bid_high"] = bid_ohlc["high"]
        bars["bid_low"] = bid_ohlc["low"]
        bars["bid_close"] = bid_ohlc["close"]

    if "ask" in data.columns:
        ask_ohlc = grouped["ask"].ohlc()
        bars["ask_open"] = ask_ohlc["open"]
        bars["ask_high"] = ask_ohlc["high"]
        bars["ask_low"] = ask_ohlc["low"]
        bars["ask_close"] = ask_ohlc["close"]

    if "spread_points" in data.columns:
        bars["spread_points_mean"] = grouped["spread_points"].mean()
        bars["spread_points_max"] = grouped["spread_points"].max()

    if "volume" in data.columns:
        bars["volume"] = grouped["volume"].sum()
    if "volume_real" in data.columns:
        bars["volume_real"] = grouped["volume_real"].sum()

    bars = bars.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return bars


def save_bars(config: ResearchConfig, bars: pd.DataFrame, timeframe: str) -> Path:
    output_dir = config.storage.bars_dir / config.symbol
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{timeframe}.parquet"
    bars.to_parquet(output_path, index=False)
    return output_path
