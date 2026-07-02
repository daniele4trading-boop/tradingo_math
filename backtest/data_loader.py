"""Load and resample XAUUSD historical data."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


OHLC_COLS = ["open", "high", "low", "close"]


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "timestamp" in out.columns and "time" not in out.columns:
        out["time"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
    else:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    for col in OHLC_COLS:
        out[col] = out[col].astype(float)
    out = out.sort_values("time").drop_duplicates("time", keep="last")
    out = out.reset_index(drop=True)
    return out


def load_m1_csvs(paths: Iterable[Path]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in sorted(paths):
        df = pd.read_csv(path)
        frames.append(_normalize_df(df))
    if not frames:
        raise FileNotFoundError("No CSV files found for M1 load")
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    return merged


def load_m1_directory(directory: Path, pattern: str = "*.csv") -> pd.DataFrame:
    paths = list(directory.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"No CSV in {directory}")
    return load_m1_csvs(paths)


def load_parquet_m1(paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for path in sorted(paths):
        df = pd.read_parquet(path)
        if "time_utc" in df.columns:
            df["time"] = pd.to_datetime(df["time_utc"], utc=True)
        elif "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        frames.append(_normalize_df(df))
    merged = pd.concat(frames, ignore_index=True)
    return merged.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)


def resample_ohlc(df_m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    tmp = df_m1.set_index("time")
    agg = tmp.resample(rule, label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
    )
    if "tick_volume" in tmp.columns:
        agg["tick_volume"] = tmp["tick_volume"].resample(rule, label="right", closed="right").sum()
    agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return agg


def build_multitf(m1: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    return {
        "M1": m1,
        "M5": resample_ohlc(m1, "5min"),
        "M15": resample_ohlc(m1, "15min"),
        "M45": resample_ohlc(m1, "45min"),
        "H1": resample_ohlc(m1, "1h"),
        "H4": resample_ohlc(m1, "4h"),
        "D1": resample_ohlc(m1, "1D"),
    }


def slice_closed(df: pd.DataFrame, current_time: pd.Timestamp) -> pd.DataFrame:
    """Return only bars that closed at or before current_time."""
    return df[df["time"] <= current_time].copy()
