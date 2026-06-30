from __future__ import annotations

import pandas as pd


def slice_bars_last_days(frame: pd.DataFrame, days: int) -> pd.DataFrame:
    if days <= 0 or frame.empty or "time" not in frame.columns:
        return frame
    end = frame["time"].max()
    start = end - pd.Timedelta(days=days)
    sliced = frame[frame["time"] >= start].copy()
    return sliced if not sliced.empty else frame
