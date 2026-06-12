"""ICT/SMC sniper setup detection.

This module turns the discretionary idea into measurable rules:

* higher timeframe bias;
* liquidity sweep of a recent swing;
* displacement candle creating a Fair Value Gap;
* volume/ATR quality filters;
* entry at FVG midpoint, SL beyond the sweep, TP at fixed R.

It is designed for research/backtesting first. Live execution should consume the
resulting setup objects through a separate risk/execution layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .market_data import normalize_rates_frame


Direction = Literal["BUY", "SELL"]
Bias = Literal["BULLISH", "BEARISH", "NEUTRAL"]


@dataclass(frozen=True)
class ICTSniperConfig:
    """Parameters for the fused ICT FVG + M1 sniper model."""

    htf_timeframe: str = "1H"
    setup_timeframe: str = "5min"
    entry_timeframe: str = "1min"
    swing_lookback: int = 2
    recent_swing_window: int = 30
    fvg_lookback: int = 8
    atr_period: int = 14
    volume_z_window: int = 50
    atr_z_window: int = 50
    min_sweep_volume_z: float = 0.4
    min_displacement_range_atr: float = 0.8
    min_displacement_volume_z: float = 0.2
    max_retest_volume_z: float = 1.2
    min_score: float = 65.0
    rr_target: float = 2.0
    tp1_rr: float = 1.0
    entry_fvg_fraction: float = 0.50
    sl_buffer_atr: float = 0.08
    max_fvg_age_bars: int = 12
    max_daily_trades: int = 3
    session_timezone: str = "Europe/Rome"
    kill_zones: tuple[tuple[time, time, str], ...] = (
        (time(7, 0), time(10, 0), "London Open"),
        (time(14, 30), time(16, 30), "NY Open"),
    )


@dataclass(frozen=True)
class FairValueGap:
    direction: Direction
    created_at: pd.Timestamp
    low: float
    high: float
    impulse_index: int
    range_atr: float
    volume_z: float


@dataclass(frozen=True)
class LiquiditySweep:
    direction: Direction
    swept_at: pd.Timestamp
    level: float
    extreme: float
    volume_z: float
    candle_index: int


@dataclass(frozen=True)
class ICTSniperSetup:
    direction: Direction
    timestamp: pd.Timestamp
    session: str
    bias: Bias
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    score: float
    sweep: LiquiditySweep
    fvg: FairValueGap
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def risk_points(self) -> float:
        return abs(self.entry - self.sl)


class ICTSniperStrategy:
    """Detect one high-quality setup from historical candles up to now."""

    def __init__(self, config: Optional[ICTSniperConfig] = None):
        self.cfg = config or ICTSniperConfig()

    def find_setup(self, m1_rates: pd.DataFrame) -> Optional[ICTSniperSetup]:
        """Return the latest valid setup, using only candles in ``m1_rates``."""
        m1 = normalize_rates_frame(m1_rates)
        if len(m1) < max(150, self.cfg.volume_z_window + self.cfg.atr_z_window):
            return None

        setup_tf = resample_ohlcv(m1, self.cfg.setup_timeframe)
        htf = resample_ohlcv(m1, self.cfg.htf_timeframe)
        if len(setup_tf) < 60 or len(htf) < 20:
            return None

        now = setup_tf["time"].iloc[-1]
        session = self.session_name(now)
        if session is None:
            return None

        bias = infer_bias(htf, self.cfg.swing_lookback)
        if bias == "NEUTRAL":
            return None

        enriched = add_quality_metrics(setup_tf, self.cfg)
        sweep = find_recent_sweep(enriched, self.cfg)
        if sweep is None:
            return None

        if sweep.direction == "BUY" and bias != "BULLISH":
            return None
        if sweep.direction == "SELL" and bias != "BEARISH":
            return None

        fvg = find_recent_fvg_after_sweep(enriched, sweep, self.cfg)
        if fvg is None:
            return None

        retest = latest_retest(enriched, fvg)
        if retest is None:
            return None

        setup = self._build_setup(enriched, bias, session, sweep, fvg, retest)
        if setup.score < self.cfg.min_score:
            return None
        return setup

    def session_name(self, ts: pd.Timestamp) -> Optional[str]:
        local = ts.tz_convert(ZoneInfo(self.cfg.session_timezone))
        local_t = local.time()
        for start, end, label in self.cfg.kill_zones:
            if start <= local_t <= end:
                return label
        return None

    def _build_setup(
        self,
        df: pd.DataFrame,
        bias: Bias,
        session: str,
        sweep: LiquiditySweep,
        fvg: FairValueGap,
        retest: pd.Series,
    ) -> ICTSniperSetup:
        atr = float(df["atr"].iloc[-1])
        buffer = max(atr * self.cfg.sl_buffer_atr, 0.0)
        fraction = self.cfg.entry_fvg_fraction

        if fvg.direction == "BUY":
            entry = fvg.low + (fvg.high - fvg.low) * fraction
            sl = sweep.extreme - buffer
            risk = entry - sl
            tp1 = entry + risk * self.cfg.tp1_rr
            tp2 = entry + risk * self.cfg.rr_target
        else:
            entry = fvg.high - (fvg.high - fvg.low) * fraction
            sl = sweep.extreme + buffer
            risk = sl - entry
            tp1 = entry - risk * self.cfg.tp1_rr
            tp2 = entry - risk * self.cfg.rr_target

        if risk <= 0:
            score = 0.0
        else:
            score = score_setup(sweep, fvg, retest, self.cfg)

        reasons = (
            f"session={session}",
            f"bias={bias}",
            f"sweep_volume_z={sweep.volume_z:.2f}",
            f"fvg_range_atr={fvg.range_atr:.2f}",
            f"fvg_volume_z={fvg.volume_z:.2f}",
            f"retest_volume_z={float(retest['volume_z']):.2f}",
        )
        return ICTSniperSetup(
            direction=fvg.direction,
            timestamp=pd.Timestamp(retest["time"]),
            session=session,
            bias=bias,
            entry=float(entry),
            sl=float(sl),
            tp1=float(tp1),
            tp2=float(tp2),
            rr=self.cfg.rr_target,
            score=float(score),
            sweep=sweep,
            fvg=fvg,
            reasons=reasons,
        )


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample normalized candles to a higher timeframe."""
    clean = normalize_rates_frame(df).set_index("time")
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "tick_volume": "sum",
        "spread": "mean",
        "real_volume": "sum",
    }
    out = clean.resample(pandas_resample_rule(rule), label="right", closed="right").agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return normalize_rates_frame(out)


def pandas_resample_rule(rule: str) -> str:
    """Return a pandas 3 compatible resample rule.

    Pandas 3 rejects uppercase hourly aliases such as ``1H``. Strategy configs
    still use trading-friendly labels like H1/H4/1H, so we normalize here.
    """
    text = rule.strip()
    aliases = {
        "M1": "1min",
        "M3": "3min",
        "M5": "5min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "D1": "1D",
        "1H": "1h",
        "4H": "4h",
    }
    if text in aliases:
        return aliases[text]
    if text.endswith("H"):
        return text[:-1] + "h"
    return text


def add_quality_metrics(df: pd.DataFrame, cfg: ICTSniperConfig) -> pd.DataFrame:
    out = normalize_rates_frame(df)
    out["atr"] = compute_atr(out, cfg.atr_period)
    out["atr_z"] = zscore(out["atr"], cfg.atr_z_window)
    out["volume_z"] = zscore(out["tick_volume"], cfg.volume_z_window)
    out["range"] = out["high"] - out["low"]
    out["range_atr"] = out["range"] / out["atr"].replace(0, np.nan)
    return out


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
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


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(5, window // 3)).mean()
    std = series.rolling(window, min_periods=max(5, window // 3)).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def infer_bias(df: pd.DataFrame, swing_lookback: int = 2) -> Bias:
    swings = find_swings(df, swing_lookback)
    highs = swings[swings["swing_high"]].tail(2)
    lows = swings[swings["swing_low"]].tail(2)
    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs["high"].iloc[-1] > highs["high"].iloc[-2]
        higher_low = lows["low"].iloc[-1] > lows["low"].iloc[-2]
        lower_high = highs["high"].iloc[-1] < highs["high"].iloc[-2]
        lower_low = lows["low"].iloc[-1] < lows["low"].iloc[-2]
        if higher_high and higher_low:
            return "BULLISH"
        if lower_high and lower_low:
            return "BEARISH"

    close = df["close"]
    ema = close.ewm(span=50, adjust=False).mean()
    if len(close) >= 50 and close.iloc[-1] > ema.iloc[-1] and ema.iloc[-1] > ema.iloc[-10]:
        return "BULLISH"
    if len(close) >= 50 and close.iloc[-1] < ema.iloc[-1] and ema.iloc[-1] < ema.iloc[-10]:
        return "BEARISH"
    return "NEUTRAL"


def find_swings(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    out = df.copy()
    if pd.api.types.is_numeric_dtype(out["time"]):
        out["time"] = pd.to_datetime(out["time"], unit="s", utc=True)
    else:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    out = out.sort_values("time").reset_index(drop=True)
    out["swing_high"] = False
    out["swing_low"] = False
    for i in range(lookback, len(out) - lookback):
        window = out.iloc[i - lookback : i + lookback + 1]
        out.at[out.index[i], "swing_high"] = out["high"].iloc[i] == window["high"].max()
        out.at[out.index[i], "swing_low"] = out["low"].iloc[i] == window["low"].min()
    return out


def find_recent_sweep(df: pd.DataFrame, cfg: ICTSniperConfig) -> Optional[LiquiditySweep]:
    swings = find_swings(df, cfg.swing_lookback)
    start = max(cfg.swing_lookback + 1, len(swings) - cfg.recent_swing_window)

    for idx in range(len(swings) - 1, start, -1):
        row = swings.iloc[idx]
        previous = swings.iloc[:idx]
        prev_lows = previous[previous["swing_low"]].tail(5)
        prev_highs = previous[previous["swing_high"]].tail(5)

        if not prev_lows.empty:
            level = float(prev_lows["low"].iloc[-1])
            if row["low"] < level and row["close"] > level:
                vol_z = safe_float(row["volume_z"])
                if vol_z >= cfg.min_sweep_volume_z:
                    return LiquiditySweep(
                        direction="BUY",
                        swept_at=pd.Timestamp(row["time"]),
                        level=level,
                        extreme=float(row["low"]),
                        volume_z=vol_z,
                        candle_index=idx,
                    )

        if not prev_highs.empty:
            level = float(prev_highs["high"].iloc[-1])
            if row["high"] > level and row["close"] < level:
                vol_z = safe_float(row["volume_z"])
                if vol_z >= cfg.min_sweep_volume_z:
                    return LiquiditySweep(
                        direction="SELL",
                        swept_at=pd.Timestamp(row["time"]),
                        level=level,
                        extreme=float(row["high"]),
                        volume_z=vol_z,
                        candle_index=idx,
                    )
    return None


def find_recent_fvg_after_sweep(
    df: pd.DataFrame,
    sweep: LiquiditySweep,
    cfg: ICTSniperConfig,
) -> Optional[FairValueGap]:
    first = sweep.candle_index + 1
    last = min(len(df) - 1, first + cfg.max_fvg_age_bars)
    best: Optional[FairValueGap] = None

    for i in range(max(2, first), last + 1):
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]
        if sweep.direction == "BUY":
            has_gap = c1["high"] < c3["low"] and c2["close"] > c2["open"]
            low, high = float(c1["high"]), float(c3["low"])
        else:
            has_gap = c1["low"] > c3["high"] and c2["close"] < c2["open"]
            low, high = float(c3["high"]), float(c1["low"])

        range_atr = safe_float(c2["range_atr"])
        volume_z = safe_float(c2["volume_z"])
        if (
            has_gap
            and high > low
            and range_atr >= cfg.min_displacement_range_atr
            and volume_z >= cfg.min_displacement_volume_z
        ):
            candidate = FairValueGap(
                direction=sweep.direction,
                created_at=pd.Timestamp(c3["time"]),
                low=low,
                high=high,
                impulse_index=i - 1,
                range_atr=range_atr,
                volume_z=volume_z,
            )
            if best is None or candidate.range_atr > best.range_atr:
                best = candidate
    return best


def latest_retest(df: pd.DataFrame, fvg: FairValueGap) -> Optional[pd.Series]:
    after = df[df["time"] > fvg.created_at]
    if after.empty:
        return None

    for _, row in after.tail(12).iterrows():
        touched = row["low"] <= fvg.high and row["high"] >= fvg.low
        if touched:
            return row
    return None


def score_setup(
    sweep: LiquiditySweep,
    fvg: FairValueGap,
    retest: pd.Series,
    cfg: ICTSniperConfig,
) -> float:
    score = 45.0
    score += min(18.0, max(0.0, sweep.volume_z) * 6.0)
    score += min(18.0, max(0.0, fvg.range_atr - cfg.min_displacement_range_atr) * 12.0)
    score += min(12.0, max(0.0, fvg.volume_z) * 4.0)
    retest_volume_z = safe_float(retest["volume_z"])
    if retest_volume_z <= cfg.max_retest_volume_z:
        score += min(12.0, (cfg.max_retest_volume_z - retest_volume_z) * 5.0)
    else:
        score -= min(20.0, (retest_volume_z - cfg.max_retest_volume_z) * 10.0)
    return max(0.0, min(100.0, score))


def safe_float(value) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(out) or np.isinf(out):
        return 0.0
    return out
