from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


TIMEFRAME_MT5 = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

DUKASCOPY_INTERVALS = {
    "M1": "INTERVAL_MIN_1",
    "M5": "INTERVAL_MIN_5",
    "M15": "INTERVAL_MIN_15",
    "M30": "INTERVAL_MIN_30",
    "H1": "INTERVAL_HOUR_1",
    "H4": "INTERVAL_HOUR_4",
    "D1": "INTERVAL_DAY_1",
}

DUKASCOPY_INSTRUMENTS = {
    "EURUSD": "INSTRUMENT_FX_MAJORS_EUR_USD",
    "GBPUSD": "INSTRUMENT_FX_MAJORS_GBP_USD",
    "USDJPY": "INSTRUMENT_FX_MAJORS_USD_JPY",
    "AUDUSD": "INSTRUMENT_FX_MAJORS_AUD_USD",
    "USDCAD": "INSTRUMENT_FX_MAJORS_USD_CAD",
    "USDCHF": "INSTRUMENT_FX_MAJORS_USD_CHF",
    "NZDUSD": "INSTRUMENT_FX_MAJORS_NZD_USD",
    "XAUUSD": "INSTRUMENT_FX_METALS_XAU_USD",
    "GOLD": "INSTRUMENT_FX_METALS_XAU_USD",
    "XAGUSD": "INSTRUMENT_FX_METALS_XAG_USD",
    "SILVER": "INSTRUMENT_FX_METALS_XAG_USD",
}


@dataclass(frozen=True)
class StrategyConfig:
    symbol: str = "EURUSD"
    timeframe: str = "H1"
    direction: str = "long"
    rsi_period: int = 14
    rsi_z_lookback: int = 50
    rsi_z_threshold_long: float = -2.0
    rsi_z_threshold_short: float = 2.0
    rsi_z_recent_bars: int = 3
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    reward_risk: float = 1.5
    regime_ema_period: int = 200
    regime_slope_lookback: int = 10
    enable_regime_filter: bool = True
    require_previous_opposite: bool = True
    require_body_engulfing: bool = True
    require_close_break: bool = True
    min_body_atr_mult: float = 0.0
    max_upper_wick_atr_mult: float = 0.0
    max_lower_wick_atr_mult: float = 0.0
    same_bar_exit_policy: str = "stop_first"
    cost_per_trade_r: float = 0.0


@dataclass(frozen=True)
class Trade:
    symbol: str
    timeframe: str
    direction: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry: float
    stop: float
    target: float
    exit_price: float
    result: str
    pnl_r: float
    atr: float
    rsi_z: float
    regime_ok: bool


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return an OHLC dataframe with canonical lower-case columns."""
    if df.empty:
        raise ValueError("Input dataframe is empty")

    renamed = {col: str(col).strip().lower() for col in df.columns}
    df = df.rename(columns=renamed).copy()

    required = {"open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required OHLC columns: {sorted(missing)}")

    if "time" not in df.columns:
        for candidate in ("datetime", "date", "timestamp"):
            if candidate in df.columns:
                df = df.rename(columns={candidate: "time"})
                break

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
    elif isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        index_col = df.columns[0]
        df = df.rename(columns={index_col: "time"})
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
    else:
        df["time"] = pd.RangeIndex(start=0, stop=len(df), step=1).astype(str)

    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "tick_volume" in df.columns:
        df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)
    elif "volume" in df.columns:
        df["tick_volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    else:
        df["tick_volume"] = 0

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.reset_index(drop=True)


def load_csv(path: Path) -> pd.DataFrame:
    return normalize_ohlc(pd.read_csv(path))


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def download_mt5_history(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is not installed in this Python environment") from exc

    tf_name = TIMEFRAME_MT5.get(timeframe.upper())
    if not tf_name:
        raise ValueError(f"Unsupported timeframe {timeframe}. Use one of {sorted(TIMEFRAME_MT5)}")
    tf_value = getattr(mt5, tf_name)

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select failed for {symbol}: {mt5.last_error()}")
        rates = mt5.copy_rates_from_pos(symbol, tf_value, 0, bars)
    finally:
        mt5.shutdown()

    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 returned no rates for {symbol} {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return normalize_ohlc(df)


def parse_date(value: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC").tz_localize(None)
    return parsed


def download_dukascopy_history(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    offer_side: str = "bid",
) -> pd.DataFrame:
    try:
        import dukascopy_python as dukascopy  # type: ignore
        import dukascopy_python.instruments as instruments  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install dukascopy-python to use download-dukascopy") from exc

    symbol_key = symbol.replace("/", "").replace("_", "").upper()
    instrument_name = DUKASCOPY_INSTRUMENTS.get(symbol_key)
    if not instrument_name:
        raise ValueError(
            f"Unsupported Dukascopy symbol {symbol}. "
            f"Supported: {sorted(DUKASCOPY_INSTRUMENTS)}"
        )

    interval_name = DUKASCOPY_INTERVALS.get(timeframe.upper())
    if not interval_name:
        raise ValueError(f"Unsupported Dukascopy timeframe {timeframe}. Use one of {sorted(DUKASCOPY_INTERVALS)}")

    side = offer_side.lower()
    if side not in ("bid", "ask"):
        raise ValueError("--offer-side must be bid or ask")

    instrument = getattr(instruments, instrument_name)
    interval = getattr(dukascopy, interval_name)
    side_value = dukascopy.OFFER_SIDE_BID if side == "bid" else dukascopy.OFFER_SIDE_ASK

    df = dukascopy.fetch(
        instrument=instrument,
        interval=interval,
        offer_side=side_value,
        start=parse_date(start).to_pydatetime(),
        end=parse_date(end).to_pydatetime(),
        max_retries=5,
        debug=False,
    )
    return normalize_ohlc(df)


def rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def atr_wilder(df: pd.DataFrame, period: int) -> pd.Series:
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
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def add_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = normalize_ohlc(df)
    out["rsi"] = rsi_wilder(out["close"], cfg.rsi_period)
    rsi_mean = out["rsi"].rolling(cfg.rsi_z_lookback).mean()
    rsi_std = out["rsi"].rolling(cfg.rsi_z_lookback).std(ddof=0)
    out["rsi_z"] = (out["rsi"] - rsi_mean) / rsi_std.replace(0.0, np.nan)
    out["rsi_z_recent_min"] = out["rsi_z"].rolling(cfg.rsi_z_recent_bars).min()
    out["rsi_z_recent_max"] = out["rsi_z"].rolling(cfg.rsi_z_recent_bars).max()
    out["atr"] = atr_wilder(out, cfg.atr_period)
    out["regime_ema"] = out["close"].ewm(
        span=cfg.regime_ema_period,
        min_periods=cfg.regime_ema_period,
        adjust=False,
    ).mean()
    out["regime_ema_slope"] = out["regime_ema"] - out["regime_ema"].shift(cfg.regime_slope_lookback)
    return out


def bullish_engulfing(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    if i <= 0:
        return False
    cur = df.iloc[i]
    prev = df.iloc[i - 1]
    if cfg.require_previous_opposite and not (prev["close"] < prev["open"]):
        return False
    if not (cur["close"] > cur["open"]):
        return False
    if cfg.require_body_engulfing:
        if not (cur["open"] <= prev["close"] and cur["close"] >= prev["open"]):
            return False
    if cfg.require_close_break and not (cur["close"] > prev["high"]):
        return False
    if cfg.min_body_atr_mult > 0 and not _body_atr_ok(cur, cfg.min_body_atr_mult):
        return False
    if cfg.max_upper_wick_atr_mult > 0:
        upper_wick = cur["high"] - max(cur["open"], cur["close"])
        if upper_wick > cur["atr"] * cfg.max_upper_wick_atr_mult:
            return False
    return True


def bearish_engulfing(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    if i <= 0:
        return False
    cur = df.iloc[i]
    prev = df.iloc[i - 1]
    if cfg.require_previous_opposite and not (prev["close"] > prev["open"]):
        return False
    if not (cur["close"] < cur["open"]):
        return False
    if cfg.require_body_engulfing:
        if not (cur["open"] >= prev["close"] and cur["close"] <= prev["open"]):
            return False
    if cfg.require_close_break and not (cur["close"] < prev["low"]):
        return False
    if cfg.min_body_atr_mult > 0 and not _body_atr_ok(cur, cfg.min_body_atr_mult):
        return False
    if cfg.max_lower_wick_atr_mult > 0:
        lower_wick = min(cur["open"], cur["close"]) - cur["low"]
        if lower_wick > cur["atr"] * cfg.max_lower_wick_atr_mult:
            return False
    return True


def _body_atr_ok(row: pd.Series, min_body_atr_mult: float) -> bool:
    if not math.isfinite(row["atr"]) or row["atr"] <= 0:
        return False
    body = abs(row["close"] - row["open"])
    return body >= row["atr"] * min_body_atr_mult


def regime_ok(df: pd.DataFrame, i: int, direction: str, cfg: StrategyConfig) -> bool:
    if not cfg.enable_regime_filter:
        return True
    row = df.iloc[i]
    if not math.isfinite(row["regime_ema"]) or not math.isfinite(row["regime_ema_slope"]):
        return False
    if direction == "long":
        return bool(row["close"] > row["regime_ema"] and row["regime_ema_slope"] >= 0)
    return bool(row["close"] < row["regime_ema"] and row["regime_ema_slope"] <= 0)


def long_signal(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    row = df.iloc[i]
    if not bullish_engulfing(df, i, cfg):
        return False
    if not math.isfinite(row["rsi_z_recent_min"]):
        return False
    if row["rsi_z_recent_min"] > cfg.rsi_z_threshold_long:
        return False
    return regime_ok(df, i, "long", cfg)


def short_signal(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    row = df.iloc[i]
    if not bearish_engulfing(df, i, cfg):
        return False
    if not math.isfinite(row["rsi_z_recent_max"]):
        return False
    if row["rsi_z_recent_max"] < cfg.rsi_z_threshold_short:
        return False
    return regime_ok(df, i, "short", cfg)


def backtest(df: pd.DataFrame, cfg: StrategyConfig) -> tuple[list[Trade], dict]:
    return backtest_prepared(add_indicators(df, cfg), cfg)


def backtest_prepared(data: pd.DataFrame, cfg: StrategyConfig) -> tuple[list[Trade], dict]:
    """Run a backtest on data that already contains indicator columns."""
    trades: list[Trade] = []
    position: Optional[dict] = None

    min_bars = max(
        cfg.rsi_period + cfg.rsi_z_lookback + cfg.rsi_z_recent_bars,
        cfg.atr_period + 2,
        cfg.regime_ema_period + cfg.regime_slope_lookback + 2 if cfg.enable_regime_filter else 0,
    )

    for i in range(min_bars, len(data) - 1):
        row = data.iloc[i]

        if position is not None and i >= position["entry_index"]:
            closed = _try_close_position(data, i, position, cfg)
            if closed:
                trades.append(closed)
                position = None

        if position is not None:
            continue

        wants_long = cfg.direction in ("long", "both") and long_signal(data, i, cfg)
        wants_short = cfg.direction in ("short", "both") and short_signal(data, i, cfg)
        if wants_long and wants_short:
            continue

        direction = "long" if wants_long else ("short" if wants_short else "")
        if not direction:
            continue
        if not math.isfinite(row["atr"]) or row["atr"] <= 0:
            continue

        entry_row = data.iloc[i + 1]
        entry = float(entry_row["open"])
        risk_distance = float(row["atr"] * cfg.atr_stop_mult)
        if risk_distance <= 0:
            continue

        if direction == "long":
            stop = entry - risk_distance
            target = entry + risk_distance * cfg.reward_risk
        else:
            stop = entry + risk_distance
            target = entry - risk_distance * cfg.reward_risk

        position = {
            "symbol": cfg.symbol,
            "timeframe": cfg.timeframe,
            "direction": direction,
            "signal_time": str(row["time"]),
            "entry_time": str(entry_row["time"]),
            "entry_index": i + 1,
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk_distance": risk_distance,
            "atr": float(row["atr"]),
            "rsi_z": float(row["rsi_z"]) if math.isfinite(row["rsi_z"]) else 0.0,
            "regime_ok": regime_ok(data, i, direction, cfg),
        }

    if position is not None:
        last = data.iloc[-1]
        pnl_r = _pnl_r(position["direction"], position["entry"], float(last["close"]), position["risk_distance"])
        trades.append(
            Trade(
                symbol=cfg.symbol,
                timeframe=cfg.timeframe,
                direction=position["direction"],
                signal_time=position["signal_time"],
                entry_time=position["entry_time"],
                exit_time=str(last["time"]),
                entry=position["entry"],
                stop=position["stop"],
                target=position["target"],
                exit_price=float(last["close"]),
                result="open_marked_to_market",
                pnl_r=pnl_r - cfg.cost_per_trade_r,
                atr=position["atr"],
                rsi_z=position["rsi_z"],
                regime_ok=position["regime_ok"],
            )
        )

    return trades, metrics(trades, cfg)


def _try_close_position(df: pd.DataFrame, i: int, position: dict, cfg: StrategyConfig) -> Optional[Trade]:
    row = df.iloc[i]
    high = float(row["high"])
    low = float(row["low"])
    direction = position["direction"]

    if direction == "long":
        hit_stop = low <= position["stop"]
        hit_target = high >= position["target"]
    else:
        hit_stop = high >= position["stop"]
        hit_target = low <= position["target"]

    if not hit_stop and not hit_target:
        return None

    if hit_stop and hit_target:
        result = "loss" if cfg.same_bar_exit_policy == "stop_first" else "win"
    elif hit_target:
        result = "win"
    else:
        result = "loss"

    exit_price = position["target"] if result == "win" else position["stop"]
    pnl_r = _pnl_r(direction, position["entry"], exit_price, position["risk_distance"]) - cfg.cost_per_trade_r
    return Trade(
        symbol=position["symbol"],
        timeframe=position["timeframe"],
        direction=direction,
        signal_time=position["signal_time"],
        entry_time=position["entry_time"],
        exit_time=str(row["time"]),
        entry=position["entry"],
        stop=position["stop"],
        target=position["target"],
        exit_price=float(exit_price),
        result=result,
        pnl_r=float(pnl_r),
        atr=position["atr"],
        rsi_z=position["rsi_z"],
        regime_ok=position["regime_ok"],
    )


def _pnl_r(direction: str, entry: float, exit_price: float, risk_distance: float) -> float:
    if direction == "long":
        return (exit_price - entry) / risk_distance
    return (entry - exit_price) / risk_distance


def metrics(trades: list[Trade], cfg: StrategyConfig) -> dict:
    pnl = np.array([t.pnl_r for t in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_win = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(abs(losses.sum())) if losses.size else 0.0
    equity = pnl.cumsum() if pnl.size else np.array([])
    running_peak = np.maximum.accumulate(np.insert(equity, 0, 0.0))[1:] if pnl.size else np.array([])
    drawdown = running_peak - equity if pnl.size else np.array([])

    return {
        "config": asdict(cfg),
        "trades": int(len(trades)),
        "wins": int(wins.size),
        "losses": int(losses.size),
        "win_rate": float(wins.size / len(trades)) if trades else 0.0,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else None,
        "expectancy_r": float(pnl.mean()) if pnl.size else 0.0,
        "total_r": float(pnl.sum()) if pnl.size else 0.0,
        "max_drawdown_r": float(drawdown.max()) if drawdown.size else 0.0,
        "avg_win_r": float(wins.mean()) if wins.size else 0.0,
        "avg_loss_r": float(losses.mean()) if losses.size else 0.0,
        "longest_losing_streak": longest_losing_streak(pnl),
        "same_bar_exit_policy": cfg.same_bar_exit_policy,
    }


def longest_losing_streak(pnl: np.ndarray) -> int:
    streak = 0
    max_streak = 0
    for value in pnl:
        if value < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def trade_frame(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(t) for t in trades])


def config_from_args(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        direction=args.direction,
        rsi_z_threshold_long=args.rsi_z_threshold_long,
        rsi_z_threshold_short=args.rsi_z_threshold_short,
        atr_stop_mult=args.atr_stop_mult,
        reward_risk=args.reward_risk,
        enable_regime_filter=not args.no_regime_filter,
        require_close_break=not args.no_close_break,
        cost_per_trade_r=args.cost_per_trade_r,
    )


def optimize(df: pd.DataFrame, base_cfg: StrategyConfig, min_trades: int) -> pd.DataFrame:
    data = add_indicators(df, base_cfg)
    rows = []
    for z in (-1.5, -1.75, -2.0, -2.25, -2.5):
        for atr_mult in (1.5, 2.0, 2.5):
            for rr in (1.0, 1.5, 2.0):
                for close_break in (True, False):
                    cfg = replace(
                        base_cfg,
                        rsi_z_threshold_long=z,
                        atr_stop_mult=atr_mult,
                        reward_risk=rr,
                        require_close_break=close_break,
                    )
                    trades, summary = backtest_prepared(data, cfg)
                    if summary["trades"] >= min_trades:
                        rows.append(
                            {
                                "z_long": z,
                                "atr_stop_mult": atr_mult,
                                "reward_risk": rr,
                                "close_break": close_break,
                                "trades": summary["trades"],
                                "win_rate": summary["win_rate"],
                                "profit_factor": summary["profit_factor"] or 0.0,
                                "expectancy_r": summary["expectancy_r"],
                                "total_r": summary["total_r"],
                                "max_drawdown_r": summary["max_drawdown_r"],
                                "longest_losing_streak": summary["longest_losing_streak"],
                            }
                        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        by=["expectancy_r", "profit_factor", "trades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def write_summary(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Price Action Quant research tools")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download-mt5", help="Download OHLC data from the local MT5 terminal")
    dl.add_argument("--symbol", required=True)
    dl.add_argument("--timeframe", default="H1", choices=sorted(TIMEFRAME_MT5))
    dl.add_argument("--bars", type=int, default=50_000)
    dl.add_argument("--out", required=True, type=Path)

    duk = sub.add_parser("download-dukascopy", help="Download OHLC data from Dukascopy")
    duk.add_argument("--symbol", required=True)
    duk.add_argument("--timeframe", default="H1", choices=sorted(DUKASCOPY_INTERVALS))
    duk.add_argument("--start", required=True, help="UTC start date, e.g. 2021-01-01")
    duk.add_argument("--end", required=True, help="UTC end date, e.g. 2026-06-08")
    duk.add_argument("--offer-side", default="bid", choices=("bid", "ask"))
    duk.add_argument("--out", required=True, type=Path)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--csv", required=True, type=Path)
    common.add_argument("--symbol", default="EURUSD")
    common.add_argument("--timeframe", default="H1")
    common.add_argument("--direction", default="long", choices=("long", "short", "both"))
    common.add_argument("--rsi-z-threshold-long", type=float, default=-2.0)
    common.add_argument("--rsi-z-threshold-short", type=float, default=2.0)
    common.add_argument("--atr-stop-mult", type=float, default=2.0)
    common.add_argument("--reward-risk", type=float, default=1.5)
    common.add_argument("--cost-per-trade-r", type=float, default=0.0)
    common.add_argument("--no-regime-filter", action="store_true")
    common.add_argument("--no-close-break", action="store_true")

    bt = sub.add_parser("backtest", parents=[common], help="Run one backtest")
    bt.add_argument("--trades-out", type=Path)
    bt.add_argument("--summary-out", type=Path)

    opt = sub.add_parser("optimize", parents=[common], help="Run a small parameter grid")
    opt.add_argument("--min-trades", type=int, default=20)
    opt.add_argument("--out", required=True, type=Path)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download-mt5":
        df = download_mt5_history(args.symbol, args.timeframe, args.bars)
        save_csv(df, args.out)
        print(f"Saved {len(df)} bars to {args.out}")
        return 0

    if args.command == "download-dukascopy":
        df = download_dukascopy_history(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            offer_side=args.offer_side,
        )
        save_csv(df, args.out)
        print(f"Saved {len(df)} bars to {args.out}")
        return 0

    df = load_csv(args.csv)
    cfg = config_from_args(args)

    if args.command == "backtest":
        trades, summary = backtest(df, cfg)
        print(json.dumps(summary, indent=2))
        if args.trades_out:
            save_csv(trade_frame(trades), args.trades_out)
        if args.summary_out:
            write_summary(summary, args.summary_out)
        return 0

    if args.command == "optimize":
        result = optimize(df, cfg, args.min_trades)
        save_csv(result, args.out)
        if result.empty:
            print("No parameter set met the minimum trade threshold")
        else:
            print(result.head(10).to_string(index=False))
        return 0

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
