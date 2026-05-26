import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from config import Convergenza7Config


TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
}

BAR_FIELDS = ("time", "open", "high", "low", "close", "volume")


def parse_timestamp(value: Any) -> datetime:
    """Parse common CSV/Parquet timestamp encodings into UTC datetimes."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("empty timestamp")
        if text.isdigit():
            return parse_timestamp(int(text))
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                raise

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _find_column(columns: Iterable[str], aliases: Iterable[str]) -> Optional[str]:
    lookup = {column.lower().strip(): column for column in columns}
    for alias in aliases:
        if alias in lookup:
            return lookup[alias]
    return None


def _normalize_row(row: Mapping[str, Any], column_map: Mapping[str, str]) -> Dict[str, Any]:
    bar = {
        "time": parse_timestamp(row[column_map["time"]]),
        "open": float(row[column_map["open"]]),
        "high": float(row[column_map["high"]]),
        "low": float(row[column_map["low"]]),
        "close": float(row[column_map["close"]]),
        "volume": float(row[column_map["volume"]]) if column_map.get("volume") else 0.0,
    }
    if bar["high"] < bar["low"]:
        raise ValueError(f"invalid OHLC range at {bar['time']}: high < low")
    return bar


def _build_column_map(columns: Iterable[str]) -> Dict[str, str]:
    columns = list(columns)
    column_map = {
        "time": _find_column(columns, ("time", "timestamp", "datetime", "date")),
        "open": _find_column(columns, ("open", "o")),
        "high": _find_column(columns, ("high", "h")),
        "low": _find_column(columns, ("low", "l")),
        "close": _find_column(columns, ("close", "c")),
        "volume": _find_column(columns, ("volume", "vol", "tick_volume", "real_volume", "v")),
    }
    missing = [key for key in ("time", "open", "high", "low", "close") if column_map[key] is None]
    if missing:
        raise ValueError(f"missing required OHLCV columns: {', '.join(missing)}")
    return {key: value for key, value in column_map.items() if value is not None}


def _dedupe_and_sort(bars: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_time = {bar["time"]: bar for bar in bars}
    return [by_time[key] for key in sorted(by_time)]


def load_csv(path: str) -> List[Dict[str, Any]]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        column_map = _build_column_map(reader.fieldnames)
        return _dedupe_and_sort(_normalize_row(row, column_map) for row in reader)


def load_parquet(path: str) -> List[Dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Parquet loading requires pandas/pyarrow already installed in the environment. "
            "CSV loading uses only the Python standard library."
        ) from exc

    df = pd.read_parquet(path)
    records = df.to_dict(orient="records")
    column_map = _build_column_map(df.columns)
    return _dedupe_and_sort(_normalize_row(row, column_map) for row in records)


def load_ohlcv(path: str) -> List[Dict[str, Any]]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix in (".parquet", ".pq"):
        return load_parquet(path)
    raise ValueError(f"unsupported data file extension: {suffix}")


def floor_time(timestamp: datetime, timeframe_minutes: int) -> datetime:
    base = timestamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
    minutes = (base.hour * 60 + base.minute) // timeframe_minutes * timeframe_minutes
    return base.replace(hour=minutes // 60, minute=minutes % 60)


def aggregate_bars(bars: List[Dict[str, Any]], timeframe: str) -> List[Dict[str, Any]]:
    minutes = TIMEFRAME_MINUTES[timeframe]
    if minutes == 1:
        return list(bars)

    buckets: Dict[datetime, Dict[str, Any]] = {}
    for bar in sorted(bars, key=lambda item: item["time"]):
        bucket_time = floor_time(bar["time"], minutes)
        bucket = buckets.get(bucket_time)
        if bucket is None:
            buckets[bucket_time] = {
                "time": bucket_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
            continue
        bucket["high"] = max(bucket["high"], bar["high"])
        bucket["low"] = min(bucket["low"], bar["low"])
        bucket["close"] = bar["close"]
        bucket["volume"] += bar["volume"]

    return [buckets[key] for key in sorted(buckets)]


def load_timeframes_from_m1(path: str) -> Dict[str, List[Dict[str, Any]]]:
    m1 = load_ohlcv(path)
    if not m1:
        raise ValueError(f"no bars loaded from {path}")
    return {
        "M1": m1,
        "M5": aggregate_bars(m1, "M5"),
        "M15": aggregate_bars(m1, "M15"),
        "H1": aggregate_bars(m1, "H1"),
    }


def load_timeframes(
    paths: Mapping[str, str],
    config: Optional[Convergenza7Config] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Load supplied timeframes and fill missing higher TFs from M1 when possible."""
    cfg = config or Convergenza7Config()
    loaded: Dict[str, List[Dict[str, Any]]] = {
        timeframe.upper(): load_ohlcv(path) for timeframe, path in paths.items()
    }

    if "M1" not in loaded and cfg.source_timeframe.upper() in loaded:
        source_tf = cfg.source_timeframe.upper()
        if source_tf != "M1":
            raise ValueError("M1 data is required for a walk-forward M1 backtest loop")

    if "M1" not in loaded:
        raise ValueError("provide an M1 CSV/Parquet path")

    for timeframe in ("M5", "M15", "H1"):
        if timeframe not in loaded:
            loaded[timeframe] = aggregate_bars(loaded["M1"], timeframe)

    return loaded


def completed_bars(
    bars: List[Dict[str, Any]],
    current_close_time: datetime,
    timeframe: str,
) -> List[Dict[str, Any]]:
    duration = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    return [bar for bar in bars if bar["time"] + duration <= current_close_time]

