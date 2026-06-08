"""
TSEntry price-action engine.

This module is intentionally independent from MetaTrader5 so the same logic can
be used for historical backtests, signal review, and live/demo execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd


NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Bias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class StyleSpec:
    name: str
    description: str
    bias_tf: str
    range_tf: str
    entry_tf: str
    include_asia_range: bool
    include_prior_entry_range: bool
    allowed_weekdays: Optional[Tuple[int, ...]]
    ny_windows: Tuple[Tuple[time, time], ...]
    max_holding_bars: int
    require_h1_first_minutes: bool = False
    h1_entry_cutoff_minute: int = 35


STYLE_SPECS: Dict[str, StyleSpec] = {
    "swing": StyleSpec(
        name="swing",
        description="Monthly/Weekly context, Daily entries, multi-week targets.",
        bias_tf="MN1",
        range_tf="W1",
        entry_tf="D1",
        include_asia_range=False,
        include_prior_entry_range=False,
        allowed_weekdays=None,
        ny_windows=(),
        max_holding_bars=30,
    ),
    "short_term_weekly": StyleSpec(
        name="short_term_weekly",
        description="Weekly expansion idea, Monday/Tuesday entries only.",
        bias_tf="W1",
        range_tf="D1",
        entry_tf="H1",
        include_asia_range=False,
        include_prior_entry_range=True,
        allowed_weekdays=(0, 1),
        ny_windows=(),
        max_holding_bars=120,
    ),
    "daytrading_daily": StyleSpec(
        name="daytrading_daily",
        description="Daily draw-on-liquidity, London/NY intraday execution.",
        bias_tf="D1",
        range_tf="D1",
        entry_tf="M5",
        include_asia_range=True,
        include_prior_entry_range=False,
        allowed_weekdays=(0, 1, 2, 3, 4),
        ny_windows=((time(2, 0), time(5, 0)), (time(9, 30), time(11, 30))),
        max_holding_bars=180,
    ),
    "scalping_h1": StyleSpec(
        name="scalping_h1",
        description="H1 candle manipulation, exit before the hourly idea expires.",
        bias_tf="D1",
        range_tf="H1",
        entry_tf="M1",
        include_asia_range=True,
        include_prior_entry_range=True,
        allowed_weekdays=(0, 1, 2, 3, 4),
        ny_windows=((time(2, 0), time(5, 0)), (time(9, 30), time(11, 30))),
        max_holding_bars=60,
        require_h1_first_minutes=True,
    ),
}


TIMEFRAME_RULES = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "H1": "1h",
    "D1": "1D",
    "W1": "W-MON",
    "MN1": "MS",
}


@dataclass(frozen=True)
class TsEntryParams:
    symbol: str = "XAUUSD"
    smt_symbol: str = "XAGUSD"
    risk_fraction: float = 0.01
    starting_equity: float = 100_000.0
    spread_buffer_points: float = 80.0
    point_size: float = 0.01
    min_rr_to_tp1: float = 0.6
    require_smt: bool = False
    one_trade_at_a_time: bool = True

    @property
    def price_buffer(self) -> float:
        return self.spread_buffer_points * self.point_size


@dataclass(frozen=True)
class KeyLevel:
    name: str
    price: float
    side: str
    range_high: float
    range_low: float
    priority: int


@dataclass(frozen=True)
class TsEntrySignal:
    style: str
    timestamp: pd.Timestamp
    direction: Direction
    entry_price: float
    level_name: str
    swept_level: float
    bias: Bias
    smt_confirmed: bool
    smt_checked: bool
    score: float
    range_high: float
    range_low: float
    stop_loss: float
    tp1: float
    tp2: float


@dataclass(frozen=True)
class BacktestTrade:
    style: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: Direction
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    result_r: float
    pnl: float
    exit_reason: str
    level_name: str
    smt_confirmed: bool
    score: float


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return an OHLC DataFrame indexed by UTC timestamp."""
    if df.empty:
        return df.copy()

    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
        out = out.set_index("time")
    elif not isinstance(out.index, pd.DatetimeIndex):
        raise ValueError("OHLC data must have a DatetimeIndex or a 'time' column")

    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index()
    required = {"open", "high", "low", "close"}
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Missing OHLC columns: {sorted(missing)}")

    cols = ["open", "high", "low", "close"]
    if "tick_volume" in out.columns:
        cols.append("tick_volume")
    return out[cols].dropna()


def resample_ohlc(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample lower timeframe OHLC data to a strategy timeframe."""
    if timeframe not in TIMEFRAME_RULES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    src = normalize_ohlc(df)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "tick_volume" in src.columns:
        agg["tick_volume"] = "sum"
    return src.resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").agg(agg).dropna()


def ensure_timeframes(base_df: pd.DataFrame, wanted: Iterable[str]) -> Dict[str, pd.DataFrame]:
    """Build all requested timeframes from one lower-timeframe series."""
    return {tf: resample_ohlc(base_df, tf) for tf in sorted(set(wanted), key=_tf_sort_key)}


def compute_bias_at(df: pd.DataFrame, timestamp: pd.Timestamp) -> Bias:
    """Bias from the last closed HTF candle before timestamp."""
    htf = normalize_ohlc(df)
    closed = htf[htf.index < timestamp]
    if len(closed) < 2:
        return Bias.NEUTRAL
    last = closed.iloc[-1]
    prev = closed.iloc[-2]
    if float(last["close"]) > float(prev["high"]):
        return Bias.BULLISH
    if float(last["close"]) < float(prev["low"]):
        return Bias.BEARISH
    return Bias.NEUTRAL


def _last_closed_range(df: pd.DataFrame, timestamp: pd.Timestamp) -> Optional[pd.Series]:
    closed = normalize_ohlc(df)
    closed = closed[closed.index < timestamp]
    if closed.empty:
        return None
    return closed.iloc[-1]


def _ny_time(timestamp: pd.Timestamp) -> pd.Timestamp:
    return timestamp.tz_convert(NY_TZ)


def _inside_ny_window(timestamp: pd.Timestamp, windows: Tuple[Tuple[time, time], ...]) -> bool:
    if not windows:
        return True
    t = _ny_time(timestamp).time()
    return any(start <= t <= end for start, end in windows)


def _weekday_allowed(timestamp: pd.Timestamp, allowed: Optional[Tuple[int, ...]]) -> bool:
    return allowed is None or _ny_time(timestamp).weekday() in allowed


def _inside_h1_cutoff(timestamp: pd.Timestamp, cutoff_minute: int) -> bool:
    return _ny_time(timestamp).minute <= cutoff_minute


def _asia_range(entry_df: pd.DataFrame, timestamp: pd.Timestamp) -> Optional[Tuple[float, float]]:
    src = normalize_ohlc(entry_df)
    ny_ts = _ny_time(timestamp)
    end_ny = ny_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if ny_ts.time() < time(0, 0):
        end_ny = end_ny - pd.Timedelta(days=1)
    start_ny = end_ny - pd.Timedelta(hours=4)
    start_utc = start_ny.tz_convert(UTC_TZ)
    end_utc = end_ny.tz_convert(UTC_TZ)
    sub = src[(src.index >= start_utc) & (src.index < end_utc)]
    if sub.empty:
        return None
    return float(sub["high"].max()), float(sub["low"].min())


def _build_levels(
    style: StyleSpec,
    timestamp: pd.Timestamp,
    frames: Dict[str, pd.DataFrame],
) -> List[KeyLevel]:
    levels: List[KeyLevel] = []
    ref = _last_closed_range(frames[style.range_tf], timestamp)
    if ref is not None:
        high = float(ref["high"])
        low = float(ref["low"])
        levels.extend(
            [
                KeyLevel(f"prev_{style.range_tf}_high", high, "HIGH", high, low, 100),
                KeyLevel(f"prev_{style.range_tf}_low", low, "LOW", high, low, 100),
            ]
        )

    if style.include_prior_entry_range:
        prior_entry = _last_closed_range(frames[style.entry_tf], timestamp)
        if prior_entry is not None:
            high = float(prior_entry["high"])
            low = float(prior_entry["low"])
            levels.extend(
                [
                    KeyLevel(f"prev_{style.entry_tf}_high", high, "HIGH", high, low, 50),
                    KeyLevel(f"prev_{style.entry_tf}_low", low, "LOW", high, low, 50),
                ]
            )

    if style.include_asia_range:
        asia = _asia_range(frames[style.entry_tf], timestamp)
        if asia is not None:
            high, low = asia
            levels.extend(
                [
                    KeyLevel("asia_high", high, "HIGH", high, low, 80),
                    KeyLevel("asia_low", low, "LOW", high, low, 80),
                ]
            )

    return levels


def _smt_confirms(
    direction: Direction,
    primary_bar: pd.Series,
    smt_df: Optional[pd.DataFrame],
    timestamp: pd.Timestamp,
    lookback_bars: int = 20,
) -> Tuple[bool, bool]:
    if smt_df is None or smt_df.empty:
        return False, False
    smt = normalize_ohlc(smt_df)
    closed = smt[smt.index <= timestamp]
    if len(closed) < lookback_bars + 1:
        return False, False
    window = closed.iloc[-lookback_bars - 1 : -1]
    last = closed.iloc[-1]
    if direction == Direction.SELL:
        primary_swept_high = float(primary_bar["high"])
        _ = primary_swept_high  # kept explicit for readability of the SMT branch
        return float(last["high"]) <= float(window["high"].max()), True
    return float(last["low"]) >= float(window["low"].min()), True


def detect_tsentry_signals(
    style_name: str,
    frames: Dict[str, pd.DataFrame],
    params: TsEntryParams,
    smt_frames: Optional[Dict[str, pd.DataFrame]] = None,
) -> List[TsEntrySignal]:
    """Detect TSEntry signals for one style."""
    if style_name not in STYLE_SPECS:
        raise ValueError(f"Unknown TSEntry style: {style_name}")
    style = STYLE_SPECS[style_name]
    required = {style.bias_tf, style.range_tf, style.entry_tf}
    missing = required.difference(frames)
    if missing:
        raise ValueError(f"Missing frames for {style_name}: {sorted(missing)}")

    entry_df = normalize_ohlc(frames[style.entry_tf])
    smt_df = None
    if smt_frames and style.entry_tf in smt_frames:
        smt_df = normalize_ohlc(smt_frames[style.entry_tf])

    signals: List[TsEntrySignal] = []
    for timestamp, bar in entry_df.iloc[2:].iterrows():
        if not _weekday_allowed(timestamp, style.allowed_weekdays):
            continue
        if not _inside_ny_window(timestamp, style.ny_windows):
            continue
        if style.require_h1_first_minutes and not _inside_h1_cutoff(timestamp, style.h1_entry_cutoff_minute):
            continue

        bias = compute_bias_at(frames[style.bias_tf], timestamp)
        if bias == Bias.NEUTRAL:
            continue

        for level in sorted(_build_levels(style, timestamp, frames), key=lambda item: item.priority, reverse=True):
            signal = _signal_from_bar(style.name, timestamp, bar, level, bias, params, smt_df)
            if signal is not None:
                signals.append(signal)
                break
    return signals


def _signal_from_bar(
    style_name: str,
    timestamp: pd.Timestamp,
    bar: pd.Series,
    level: KeyLevel,
    bias: Bias,
    params: TsEntryParams,
    smt_df: Optional[pd.DataFrame],
) -> Optional[TsEntrySignal]:
    buffer = params.price_buffer
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])

    direction: Optional[Direction] = None
    if level.side == "HIGH" and high > level.price + buffer and close < level.price and bias == Bias.BEARISH:
        direction = Direction.SELL
    elif level.side == "LOW" and low < level.price - buffer and close > level.price and bias == Bias.BULLISH:
        direction = Direction.BUY
    if direction is None:
        return None

    smt_confirmed, smt_checked = _smt_confirms(direction, bar, smt_df, timestamp)
    if params.require_smt and not smt_confirmed:
        return None

    entry = close
    if direction == Direction.SELL:
        sl = max(high + buffer, level.range_high + buffer)
        tp1 = (level.range_high + level.range_low) / 2.0
        tp2 = level.range_low
        risk = sl - entry
        reward1 = entry - tp1
    else:
        sl = min(low - buffer, level.range_low - buffer)
        tp1 = (level.range_high + level.range_low) / 2.0
        tp2 = level.range_high
        risk = entry - sl
        reward1 = tp1 - entry

    if risk <= 0 or reward1 / risk < params.min_rr_to_tp1:
        return None

    score = 1.0 + (level.priority / 100.0)
    if smt_confirmed:
        score += 1.0

    return TsEntrySignal(
        style=style_name,
        timestamp=timestamp,
        direction=direction,
        entry_price=entry,
        level_name=level.name,
        swept_level=level.price,
        bias=bias,
        smt_confirmed=smt_confirmed,
        smt_checked=smt_checked,
        score=score,
        range_high=level.range_high,
        range_low=level.range_low,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
    )


def backtest_style(
    style_name: str,
    frames: Dict[str, pd.DataFrame],
    params: TsEntryParams,
    smt_frames: Optional[Dict[str, pd.DataFrame]] = None,
) -> Tuple[List[BacktestTrade], pd.DataFrame]:
    """Backtest one TSEntry style and return trades plus summary DataFrame."""
    style = STYLE_SPECS[style_name]
    entry_df = normalize_ohlc(frames[style.entry_tf])
    signals = detect_tsentry_signals(style_name, frames, params, smt_frames=smt_frames)
    trades: List[BacktestTrade] = []
    next_allowed_time: Optional[pd.Timestamp] = None

    for signal in signals:
        if params.one_trade_at_a_time and next_allowed_time and signal.timestamp <= next_allowed_time:
            continue

        loc = entry_df.index.searchsorted(signal.timestamp, side="right")
        if loc >= len(entry_df):
            continue
        entry_time = entry_df.index[loc]
        entry_price = float(entry_df.iloc[loc]["open"])
        simulated = _simulate_trade(signal, entry_df.iloc[loc + 1 : loc + 1 + style.max_holding_bars], entry_time, entry_price, params)
        if simulated is None:
            continue
        trades.append(simulated)
        next_allowed_time = simulated.exit_time

    return trades, summarize_trades(trades, params)


def _simulate_trade(
    signal: TsEntrySignal,
    future: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    params: TsEntryParams,
) -> Optional[BacktestTrade]:
    if future.empty:
        return None

    stop = signal.stop_loss
    tp1 = signal.tp1
    tp2 = signal.tp2
    risk = (stop - entry_price) if signal.direction == Direction.SELL else (entry_price - stop)
    if risk <= 0:
        return None

    tp1_hit = False
    result_r = 0.0
    exit_reason = "TIME"
    exit_time = future.index[-1]

    for timestamp, bar in future.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        if signal.direction == Direction.SELL:
            if high >= stop:
                result_r += -0.5 if tp1_hit else -1.0
                exit_reason = "SL_AFTER_TP1" if tp1_hit else "SL"
                exit_time = timestamp
                break
            if not tp1_hit and low <= tp1:
                result_r += 0.5 * ((entry_price - tp1) / risk)
                tp1_hit = True
            if tp1_hit and low <= tp2:
                result_r += 0.5 * ((entry_price - tp2) / risk)
                exit_reason = "TP2"
                exit_time = timestamp
                break
        else:
            if low <= stop:
                result_r += -0.5 if tp1_hit else -1.0
                exit_reason = "SL_AFTER_TP1" if tp1_hit else "SL"
                exit_time = timestamp
                break
            if not tp1_hit and high >= tp1:
                result_r += 0.5 * ((tp1 - entry_price) / risk)
                tp1_hit = True
            if tp1_hit and high >= tp2:
                result_r += 0.5 * ((tp2 - entry_price) / risk)
                exit_reason = "TP2"
                exit_time = timestamp
                break

        if timestamp == future.index[-1]:
            mark_r = ((entry_price - close) / risk) if signal.direction == Direction.SELL else ((close - entry_price) / risk)
            result_r += (0.5 * mark_r) if tp1_hit else mark_r

    pnl = result_r * params.risk_fraction * params.starting_equity
    return BacktestTrade(
        style=signal.style,
        signal_time=signal.timestamp,
        entry_time=entry_time,
        exit_time=exit_time,
        direction=signal.direction,
        entry_price=entry_price,
        stop_loss=stop,
        tp1=tp1,
        tp2=tp2,
        result_r=float(result_r),
        pnl=float(pnl),
        exit_reason=exit_reason,
        level_name=signal.level_name,
        smt_confirmed=signal.smt_confirmed,
        score=signal.score,
    )


def summarize_trades(trades: List[BacktestTrade], params: TsEntryParams) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            [
                {
                    "trades": 0,
                    "win_rate": 0.0,
                    "total_r": 0.0,
                    "expectancy_r": 0.0,
                    "net_pnl": 0.0,
                    "max_drawdown": 0.0,
                }
            ]
        )

    rows = [trade.__dict__ for trade in trades]
    df = pd.DataFrame(rows)
    wins = df[df["result_r"] > 0]
    equity = params.starting_equity + df["pnl"].cumsum()
    peak = equity.cummax()
    drawdown = equity - peak
    return pd.DataFrame(
        [
            {
                "trades": int(len(df)),
                "win_rate": float(len(wins) / len(df)),
                "total_r": float(df["result_r"].sum()),
                "expectancy_r": float(df["result_r"].mean()),
                "net_pnl": float(df["pnl"].sum()),
                "max_drawdown": float(drawdown.min()),
            }
        ]
    )


def trades_to_frame(trades: List[BacktestTrade]) -> pd.DataFrame:
    rows = []
    for trade in trades:
        row = trade.__dict__.copy()
        row["direction"] = trade.direction.value
        rows.append(row)
    return pd.DataFrame(rows)


def _tf_sort_key(timeframe: str) -> int:
    order = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "D1": 1440, "W1": 10080, "MN1": 43200}
    return order.get(timeframe, 999999)
