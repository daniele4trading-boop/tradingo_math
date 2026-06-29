"""Pure price-action structure utilities for LQS-MTF."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: pd.Timestamp
    price: float
    kind: str  # "high" | "low"


@dataclass(frozen=True)
class LiquidityLevel:
    price: float
    kind: str  # "high" | "low"
    touches: int
    first_time: pd.Timestamp
    last_time: pd.Timestamp


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def fractal_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """Return confirmed swing highs and lows using a simple fractal rule."""
    highs: List[SwingPoint] = []
    lows: List[SwingPoint] = []
    if len(df) < left + right + 1:
        return highs, lows

    for i in range(left, len(df) - right):
        window_high = df["high"].iloc[i - left : i + right + 1]
        window_low = df["low"].iloc[i - left : i + right + 1]
        ts = pd.Timestamp(df["time"].iloc[i])
        if df["high"].iloc[i] == window_high.max():
            highs.append(SwingPoint(i, ts, float(df["high"].iloc[i]), "high"))
        if df["low"].iloc[i] == window_low.min():
            lows.append(SwingPoint(i, ts, float(df["low"].iloc[i]), "low"))
    return highs, lows


def trend_from_swings(highs: List[SwingPoint], lows: List[SwingPoint]) -> str:
    """Classify structure as bullish, bearish, or neutral."""
    if len(highs) < 2 or len(lows) < 2:
        return "neutral"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "neutral"


def equal_levels(
    swings: List[SwingPoint],
    atr: float,
    price: float,
    tolerance_atr_mult: float = 0.5,
    min_touches: int = 2,
) -> List[LiquidityLevel]:
    if not swings or atr <= 0:
        return []
    tol = max(price * 0.0015, atr * tolerance_atr_mult)
    groups: List[List[SwingPoint]] = []
    for swing in swings:
        placed = False
        for group in groups:
            if abs(group[-1].price - swing.price) <= tol:
                group.append(swing)
                placed = True
                break
        if not placed:
            groups.append([swing])
    levels: List[LiquidityLevel] = []
    for group in groups:
        if len(group) < min_touches:
            continue
        avg_price = float(np.mean([g.price for g in group]))
        levels.append(
            LiquidityLevel(
                price=avg_price,
                kind=group[0].kind,
                touches=len(group),
                first_time=group[0].time,
                last_time=group[-1].time,
            )
        )
    return levels


def is_impulsive(row: pd.Series, min_body_ratio: float = 0.55) -> bool:
    rng = float(row["high"] - row["low"])
    if rng <= 0:
        return False
    body = abs(float(row["close"] - row["open"]))
    return body / rng >= min_body_ratio


def detect_sweep(
    bar: pd.Series,
    level: LiquidityLevel,
    atr: float,
    sweep_atr_mult: float = 0.3,
    min_body_ratio: float = 0.55,
) -> bool:
    """Detect liquidity sweep on a single closed bar."""
    if atr <= 0:
        return False
    min_pen = atr * sweep_atr_mult
    if level.kind == "high":
        pierced = float(bar["high"]) > level.price + min_pen
        wick_reject = float(bar["close"]) < level.price
        bear_impulse = float(bar["close"]) < float(bar["open"]) and is_impulsive(bar, min_body_ratio)
        return pierced and (wick_reject or bear_impulse)
    pierced = float(bar["low"]) < level.price - min_pen
    wick_reject = float(bar["close"]) > level.price
    bull_impulse = float(bar["close"]) > float(bar["open"]) and is_impulsive(bar, min_body_ratio)
    return pierced and (wick_reject or bull_impulse)


def detect_bos(
    df: pd.DataFrame,
    lows: List[SwingPoint],
    highs: List[SwingPoint],
    direction: str,
    accept_bars: int = 1,
) -> Optional[Tuple[pd.Timestamp, float, int]]:
    """
  Return (bos_time, broken_level, bar_index) when structure breaks.
  SHORT -> break below recent swing low. LONG -> break above recent swing high.
    """
    if len(df) < 3:
        return None
    last = df.iloc[-1]
    if direction == "SHORT":
        recent = [s for s in lows if s.index < len(df) - 1]
        if not recent:
            return None
        level = recent[-1].price
        if float(last["close"]) < level:
            accepted = True
            if accept_bars > 0 and len(df) >= accept_bars + 1:
                accepted = all(float(df["close"].iloc[-k]) < level for k in range(1, accept_bars + 1))
            if accepted:
                return pd.Timestamp(last["time"]), level, len(df) - 1
    else:
        recent = [s for s in highs if s.index < len(df) - 1]
        if not recent:
            return None
        level = recent[-1].price
        if float(last["close"]) > level:
            accepted = True
            if accept_bars > 0 and len(df) >= accept_bars + 1:
                accepted = all(float(df["close"].iloc[-k]) > level for k in range(1, accept_bars + 1))
            if accepted:
                return pd.Timestamp(last["time"]), level, len(df) - 1
    return None


def displacement_leg(df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> Tuple[float, float]:
    """Return (leg_low, leg_high) for the displacement move."""
    seg = df.iloc[start_idx : end_idx + 1]
    return float(seg["low"].min()), float(seg["high"].max())


def emission_zone(df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> Tuple[float, float]:
    """
  Last opposite candle before displacement.
  SHORT -> last bullish candle range. LONG -> last bearish candle range.
    """
    for i in range(end_idx, max(start_idx - 1, 0) - 1, -1):
        row = df.iloc[i]
        if direction == "SHORT" and row["close"] > row["open"]:
            return float(row["low"]), float(row["high"])
        if direction == "LONG" and row["close"] < row["open"]:
            return float(row["low"]), float(row["high"])
    row = df.iloc[end_idx]
    return float(row["low"]), float(row["high"])


def midpoint_zone(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    low = max(a[0], b[0])
    high = min(a[1], b[1])
    if low <= high:
        return low, high
    # fallback: union midpoint
    u_low = min(a[0], b[0])
    u_high = max(a[1], b[1])
    mid = (u_low + u_high) / 2.0
    pad = (u_high - u_low) * 0.1
    return mid - pad, mid + pad


def round_gold_price(price: float, step: float = 0.50) -> float:
    return round(price / step) * step


def find_fvg(df: pd.DataFrame, direction: str, lookback: int = 30) -> Optional[Tuple[float, float]]:
    """Simple 3-candle FVG detector on recent bars."""
    if len(df) < 3:
        return None
    start = max(2, len(df) - lookback)
    for i in range(len(df) - 1, start - 1, -1):
        c0 = df.iloc[i - 2]
        c2 = df.iloc[i]
        if direction == "SHORT":
            if float(c0["low"]) > float(c2["high"]):
                return float(c2["high"]), float(c0["low"])
        else:
            if float(c0["high"]) < float(c2["low"]):
                return float(c0["high"]), float(c2["low"])
    return None


def detect_bos_after(
    df: pd.DataFrame,
    lows: List[SwingPoint],
    highs: List[SwingPoint],
    direction: str,
    start_idx: int = 0,
) -> Optional[Tuple[pd.Timestamp, float, int]]:
    """Find first BOS after start_idx in direction."""
    for i in range(max(3, start_idx), len(df)):
        sub = df.iloc[: i + 1]
        h, l = fractal_swings(sub)
        bos = detect_bos(sub, l, h, direction, accept_bars=1)
        if bos is not None:
            return bos
    return None


def in_session(ts: pd.Timestamp, london: Tuple[int, int], ny: Tuple[int, int], broker_utc_offset_hours: int = 2) -> bool:
    """Session windows defined in broker local time (UTC+2 by default)."""
    local = ts + pd.Timedelta(hours=broker_utc_offset_hours)
    minutes = local.hour * 60 + local.minute
    zones = [(9 * 60, 12 * 60), (15 * 60, 20 * 60)]
    return any(start <= minutes <= end for start, end in zones)
