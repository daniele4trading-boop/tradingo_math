import pandas as pd

from strategies.structure import (
    detect_bos,
    detect_sweep,
    equal_levels,
    fractal_swings,
    is_impulsive,
    midpoint_zone,
    trend_from_swings,
)
from strategies.structure import LiquidityLevel


def _sample_df() -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(30):
        o = price
        c = price + (1 if i % 5 < 3 else -1)
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        rows.append({"time": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=i), "open": o, "high": h, "low": l, "close": c})
        price = c
    return pd.DataFrame(rows)


def test_fractal_swings_detect_points():
    df = _sample_df()
    highs, lows = fractal_swings(df)
    assert len(highs) > 0
    assert len(lows) > 0


def test_trend_from_swings():
    highs, lows = fractal_swings(_sample_df())
    assert trend_from_swings(highs, lows) in {"bullish", "bearish", "neutral"}


def test_equal_levels_grouping():
    swings_high, _ = fractal_swings(_sample_df())
    levels = equal_levels(swings_high, atr=1.0, price=100.0, tolerance_atr_mult=2.0, min_touches=2)
    assert isinstance(levels, list)


def test_impulsive_candle():
    row = pd.Series({"open": 100, "high": 102, "low": 99, "close": 101.5})
    assert is_impulsive(row, 0.5) is True


def test_midpoint_zone_overlap():
    z = midpoint_zone((100.0, 101.0), (100.5, 101.5))
    assert z[0] <= z[1]


def test_detect_sweep_high():
    level = LiquidityLevel(price=105.0, kind="high", touches=2, first_time=pd.Timestamp("2026-01-01", tz="UTC"), last_time=pd.Timestamp("2026-01-02", tz="UTC"))
    bar = pd.Series({"open": 106.8, "high": 107.0, "low": 104.0, "close": 104.2})
    assert detect_sweep(bar, level, atr=2.0, sweep_atr_mult=0.2) is True


def test_detect_bos_short():
    df = _sample_df()
    df = df.copy()
    last_low = float(df["low"].iloc[-5])
    df.loc[df.index[-1], "close"] = last_low - 2
    df.loc[df.index[-1], "open"] = last_low + 1
    df.loc[df.index[-1], "high"] = last_low + 1.5
    df.loc[df.index[-1], "low"] = last_low - 2.5
    _, lows = fractal_swings(df)
    bos = detect_bos(df, lows, [], "SHORT", accept_bars=1)
    assert bos is not None
