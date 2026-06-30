from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config import PROJECT_ROOT


DATA_ROOT = PROJECT_ROOT / "state" / "data"


def profile_data_dir(profile_name: str) -> Path:
    path = DATA_ROOT / profile_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_file(profile_name: str, broker_symbol: str, timeframe: str) -> Path:
    safe_symbol = broker_symbol.replace("\\", "_").replace("/", "_").replace(":", "_")
    return profile_data_dir(profile_name) / f"{safe_symbol}_{timeframe.upper()}.csv"


def save_bars(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "time" in frame.columns:
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame
