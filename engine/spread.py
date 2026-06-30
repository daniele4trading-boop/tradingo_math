from __future__ import annotations

import numpy as np
import pandas as pd


class SpreadError(ValueError):
    """Raised when spread series cannot be built from aligned prices."""


def align_closes(frame_a: pd.DataFrame, frame_b: pd.DataFrame) -> pd.DataFrame:
    merged = frame_a[["time", "close"]].merge(
        frame_b[["time", "close"]],
        on="time",
        how="inner",
        suffixes=("_a", "_b"),
    )
    if merged.empty:
        raise SpreadError("nessun timestamp comune tra le due gambe")
    merged = merged.sort_values("time").reset_index(drop=True)
    merged["log_a"] = np.log(merged["close_a"].astype(float))
    merged["log_b"] = np.log(merged["close_b"].astype(float))
    return merged


def hedge_ratio(log_a: pd.Series, log_b: pd.Series) -> float:
    x = log_b.to_numpy(dtype=float)
    y = log_a.to_numpy(dtype=float)
    if len(x) < 30:
        raise SpreadError("campione troppo piccolo per hedge ratio")
    beta, _intercept = np.polyfit(x, y, 1)
    return float(beta)


def build_spread(aligned: pd.DataFrame, beta: float | None = None) -> tuple[pd.Series, float]:
    beta_value = hedge_ratio(aligned["log_a"], aligned["log_b"]) if beta is None else beta
    spread = aligned["log_a"] - beta_value * aligned["log_b"]
    spread.name = "spread"
    return spread, beta_value
