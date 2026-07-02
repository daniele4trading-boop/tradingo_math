"""Tests for emission candlestick patterns."""

from __future__ import annotations

import pandas as pd

from strategies.structure import (
    detect_engulfing,
    detect_evening_star,
    detect_morning_star,
    price_in_zone,
    round_number_theory,
)


def _df(rows):
    return pd.DataFrame(rows)


def test_bearish_engulfing():
    df = _df([
        {"time": "2026-01-01", "open": 100, "high": 102, "low": 99, "close": 101},
        {"time": "2026-01-02", "open": 101.5, "high": 101.8, "low": 98, "close": 99},
    ])
    assert detect_engulfing(df, "SHORT")


def test_morning_star():
    df = _df([
        {"time": "2026-01-01", "open": 102, "high": 103, "low": 100, "close": 100.5},
        {"time": "2026-01-02", "open": 100.5, "high": 101, "low": 100, "close": 100.2},
        {"time": "2026-01-03", "open": 100.2, "high": 104, "low": 100, "close": 103.5},
    ])
    assert detect_morning_star(df)


def test_price_in_zone():
    assert price_in_zone(99, 101, (100, 102))
    assert not price_in_zone(103, 104, (100, 102))


def test_round_number_theory():
    assert round_number_theory(2650.47) == 2650.50
    assert round_number_theory(2650.18) == 2650.20
