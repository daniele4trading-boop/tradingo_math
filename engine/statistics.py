from __future__ import annotations

import math

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint


class StatisticsError(ValueError):
    """Raised when statistical tests cannot run."""


def pearson_correlation(series_a: pd.Series, series_b: pd.Series) -> float:
    if len(series_a) < 20:
        raise StatisticsError("campione troppo piccolo per correlazione")
    return float(series_a.corr(series_b))


def adf_pvalue(series: pd.Series) -> float:
    values = series.dropna().to_numpy(dtype=float)
    if len(values) < 30:
        raise StatisticsError("campione troppo piccolo per ADF")
    result = adfuller(values, autolag="AIC")
    return float(result[1])


def cointegration_pvalue(log_a: pd.Series, log_b: pd.Series) -> float:
    a = log_a.dropna().to_numpy(dtype=float)
    b = log_b.dropna().to_numpy(dtype=float)
    n = min(len(a), len(b))
    if n < 30:
        raise StatisticsError("campione troppo piccolo per cointegration")
    _score, pvalue, _crit = coint(a[:n], b[:n])
    return float(pvalue)


def halflife_bars(spread: pd.Series) -> float:
    values = spread.dropna().to_numpy(dtype=float)
    if len(values) < 30:
        raise StatisticsError("campione troppo piccolo per halflife")
    lag = values[:-1]
    delta = np.diff(values)
    if len(lag) < 20:
        raise StatisticsError("campione troppo piccolo per halflife lag")
    beta, _alpha = np.polyfit(lag, delta, 1)
    if beta >= 0:
        return math.inf
    return float(-math.log(2.0) / beta)


def halflife_hours(spread: pd.Series, bar_hours: float) -> float:
    bars = halflife_bars(spread)
    if not math.isfinite(bars):
        return math.inf
    return bars * bar_hours
