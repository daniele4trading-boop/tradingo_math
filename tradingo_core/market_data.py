"""Market data download and local archival utilities.

The first production source is MetaTrader 5 because it matches the broker
symbols, sessions, and pricing used by the live execution environment.  Data is
stored as monthly CSV partitions to keep the archive simple, inspectable, and
usable by other agents without extra binary dependencies.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


RATE_COLUMNS = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
]


@dataclass(frozen=True)
class MarketDataRequest:
    """Historical candle request for a single symbol/timeframe."""

    symbol: str
    timeframe: str
    start: datetime
    end: datetime

    def normalized(self) -> "MarketDataRequest":
        start = _ensure_utc(self.start)
        end = _ensure_utc(self.end)
        if end <= start:
            raise ValueError("end must be after start")
        return MarketDataRequest(
            symbol=normalize_symbol(self.symbol),
            timeframe=normalize_timeframe(self.timeframe),
            start=start,
            end=end,
        )


class LocalDataArchive:
    """CSV archive partitioned by symbol, timeframe, and month."""

    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)

    def partition_path(self, symbol: str, timeframe: str, month: str) -> Path:
        symbol = normalize_symbol(symbol)
        timeframe = normalize_timeframe(timeframe)
        return self.root / symbol / timeframe / f"{month}.csv"

    def write_rates(self, df: pd.DataFrame, symbol: str, timeframe: str) -> list[Path]:
        """Append/update candles and rewrite affected monthly partitions.

        The write is atomic per partition. Existing candles with the same time
        are replaced by the newest row.
        """
        clean = normalize_rates_frame(df)
        if clean.empty:
            return []

        written: list[Path] = []
        clean["month"] = clean["time"].dt.strftime("%Y-%m")

        for month, chunk in clean.groupby("month", sort=True):
            path = self.partition_path(symbol, timeframe, month)
            path.parent.mkdir(parents=True, exist_ok=True)
            out = chunk.drop(columns=["month"]).copy()

            if path.exists():
                existing = pd.read_csv(path, parse_dates=["time"])
                existing = normalize_rates_frame(existing)
                out = pd.concat([existing, out], ignore_index=True)
                out = normalize_rates_frame(out)

            self._atomic_csv_write(out, path)
            written.append(path)

        return written

    def read_rates(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Read candles from the archive for [start, end]."""
        req = MarketDataRequest(symbol, timeframe, start, end).normalized()
        frames = []
        for month in iter_months(req.start, req.end):
            path = self.partition_path(req.symbol, req.timeframe, month)
            if path.exists():
                frames.append(pd.read_csv(path, parse_dates=["time"]))

        if not frames:
            return pd.DataFrame(columns=RATE_COLUMNS)

        df = normalize_rates_frame(pd.concat(frames, ignore_index=True))
        mask = (df["time"] >= req.start) & (df["time"] <= req.end)
        return df.loc[mask].reset_index(drop=True)

    @staticmethod
    def _atomic_csv_write(df: pd.DataFrame, path: Path) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            df.to_csv(tmp.name, index=False)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)


class MT5HistoricalDownloader:
    """Download historical candles from a local MetaTrader 5 terminal."""

    def __init__(
        self,
        terminal_path: str | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
    ):
        self.terminal_path = terminal_path or os.getenv("MT5_TERMINAL_PATH")
        self.login = login or _env_int("MT5_LOGIN")
        self.password = password or os.getenv("MT5_PASSWORD")
        self.server = server or os.getenv("MT5_SERVER")
        self._mt5 = None

    def __enter__(self) -> "MT5HistoricalDownloader":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    def connect(self) -> None:
        import MetaTrader5 as mt5

        kwargs = {}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if self.login is not None:
            kwargs["login"] = int(self.login)
        if self.password:
            kwargs["password"] = self.password
        if self.server:
            kwargs["server"] = self.server

        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._mt5 = mt5

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None

    def download(self, request: MarketDataRequest) -> pd.DataFrame:
        """Download one request with MT5 copy_rates_range."""
        if self._mt5 is None:
            raise RuntimeError("MT5HistoricalDownloader is not connected")
        req = request.normalized()
        timeframe = mt5_timeframe(self._mt5, req.timeframe)
        rates = self._mt5.copy_rates_range(req.symbol, timeframe, req.start, req.end)
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=RATE_COLUMNS)
        df = pd.DataFrame(rates)
        return normalize_rates_frame(df)

    def download_to_archive(
        self,
        request: MarketDataRequest,
        archive: LocalDataArchive,
        chunk_days: int = 7,
    ) -> list[Path]:
        """Download in chunks and write affected archive partitions."""
        req = request.normalized()
        written: list[Path] = []
        cur = req.start
        while cur < req.end:
            nxt = min(cur + timedelta(days=chunk_days), req.end)
            chunk = self.download(MarketDataRequest(req.symbol, req.timeframe, cur, nxt))
            written.extend(archive.write_rates(chunk, req.symbol, req.timeframe))
            cur = nxt
        return sorted(set(written))


def normalize_rates_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a validated, sorted OHLCV frame with UTC timestamps."""
    if df is None or df.empty:
        return pd.DataFrame(columns=RATE_COLUMNS)

    out = df.copy()
    if "time" not in out.columns:
        raise ValueError("rates frame must include a time column")

    if pd.api.types.is_numeric_dtype(out["time"]):
        out["time"] = pd.to_datetime(out["time"], unit="s", utc=True)
    else:
        out["time"] = pd.to_datetime(out["time"], utc=True)

    for col in RATE_COLUMNS:
        if col not in out.columns:
            out[col] = 0

    out = out[RATE_COLUMNS]
    numeric_cols = [c for c in RATE_COLUMNS if c != "time"]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["time", "open", "high", "low", "close"])
    out = out.drop_duplicates(subset=["time"], keep="last")
    out = out.sort_values("time").reset_index(drop=True)
    return out


def iter_months(start: datetime, end: datetime) -> Iterable[str]:
    start = _ensure_utc(start)
    end = _ensure_utc(end)
    cur = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    last = datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    while cur <= last:
        yield cur.strftime("%Y-%m")
        year = cur.year + (cur.month // 12)
        month = (cur.month % 12) + 1
        cur = datetime(year, month, 1, tzinfo=timezone.utc)


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "")


def normalize_timeframe(timeframe: str) -> str:
    tf = timeframe.strip().upper()
    aliases = {"1M": "M1", "5M": "M5", "15M": "M15", "1H": "H1", "4H": "H4"}
    tf = aliases.get(tf, tf)
    valid = {"M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1"}
    if tf not in valid:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return tf


def mt5_timeframe(mt5_module, timeframe: str):
    tf = normalize_timeframe(timeframe)
    attr = f"TIMEFRAME_{tf}"
    if not hasattr(mt5_module, attr):
        raise ValueError(f"MT5 module does not expose {attr}")
    return getattr(mt5_module, attr)


def parse_utc_datetime(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return _ensure_utc(dt)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _env_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    return int(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MT5 historical candles to CSV archive.")
    parser.add_argument("--symbol", required=True, help="Broker symbol, e.g. XAUUSD")
    parser.add_argument("--timeframe", default="M1", help="M1, M5, M15, H1, H4")
    parser.add_argument("--start", required=True, help="UTC ISO datetime, e.g. 2026-01-01T00:00:00Z")
    parser.add_argument("--end", required=True, help="UTC ISO datetime")
    parser.add_argument("--archive-root", default="data", help="Archive root directory")
    parser.add_argument("--terminal-path", default=None, help="Optional MT5 terminal64.exe path")
    parser.add_argument("--login", type=int, default=None, help="Optional MT5 account login")
    parser.add_argument("--server", default=None, help="Optional MT5 server")
    parser.add_argument("--chunk-days", type=int, default=7, help="Download chunk size")
    args = parser.parse_args()

    request = MarketDataRequest(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=parse_utc_datetime(args.start),
        end=parse_utc_datetime(args.end),
    )
    archive = LocalDataArchive(args.archive_root)
    with MT5HistoricalDownloader(
        terminal_path=args.terminal_path,
        login=args.login,
        server=args.server,
    ) as downloader:
        written = downloader.download_to_archive(request, archive, chunk_days=args.chunk_days)
    print(f"Written partitions: {len(written)}")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
