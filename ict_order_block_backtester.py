"""
ICT Order Block backtesting engine.

The engine is intentionally independent from MetaTrader5 so it can be tested
with CSV data and then fed MT5 OHLC candles by a small runner script.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json

import numpy as np
import pandas as pd


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class BacktestConfig:
    lookback_bars: int = 200
    fast_ma_period: int = 20
    slow_ma_period: int = 50
    atr_period: int = 14
    adx_period: int = 14
    swing_window: int = 2
    liquidity_lookback: int = 30
    fvg_lookahead: int = 5
    bos_lookahead: int = 5
    ob_search_bars: int = 5
    max_ob_age_bars: int = 200
    min_stars: int = 3
    momentum_atr_mult: float = 1.2
    momentum_body_ratio: float = 0.60
    sl_atr_mult: float = 1.5
    trailing_atr_mult: float = 1.5
    adx_entry_soft_filter: float = 20.0
    adx_upgrade_threshold: float = 25.0
    enable_max_gain: bool = True
    point_value: float = 1.0

    @classmethod
    def from_json(cls, path: str | Path) -> "BacktestConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in raw.items() if key in allowed})


@dataclass
class FibLevels:
    entry: float
    mitigation: float
    tp1: float
    trigger_tp2: float
    tp2: float
    trigger_tp3: float
    tp3: float
    trigger_trail: float


@dataclass
class OrderBlock:
    symbol: str
    direction: Direction
    ob_index: int
    impulse_index: int
    time: Any
    high: float
    low: float
    midpoint: float
    stars: int
    liquidity_sweep: bool
    fvg: bool
    trend_filter: bool
    bos: bool
    fvg_index: Optional[int] = None
    structure_level: Optional[float] = None
    active: bool = True
    invalidated_reason: str = ""

    @property
    def fib(self) -> FibLevels:
        return calculate_fib_levels(self.direction, self.high, self.low)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction.value
        data["fib"] = asdict(self.fib)
        return data


@dataclass
class TradeResult:
    symbol: str
    direction: str
    entry_time: Any
    exit_time: Any
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    sl_initial: float
    sl_final: float
    tp_final: float
    exit_reason: str
    tp_level: str
    pnl_points: float
    pnl_value: float
    r_multiple: float
    bars_held: int
    stars: int
    liquidity_sweep: bool
    fvg: bool
    trend_filter: bool
    bos: bool
    adx_at_entry: float
    atr_at_entry: float
    adx_soft_pass: bool
    tp2_upgraded: bool
    tp3_upgraded: bool
    trailing_activated: bool
    ob_time: Any
    ob_high: float
    ob_low: float


@dataclass
class BacktestResult:
    symbol: str
    trades: List[TradeResult]
    order_blocks: List[OrderBlock]
    invalidated_order_blocks: List[OrderBlock]
    summary: Dict[str, Any]

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(trade) for trade in self.trades])

    def order_blocks_frame(self) -> pd.DataFrame:
        return pd.DataFrame([ob.to_dict() for ob in self.order_blocks])


@dataclass
class _OpenTrade:
    order_block: OrderBlock
    entry_index: int
    entry_time: Any
    direction: Direction
    entry_price: float
    sl_initial: float
    sl_current: float
    active_tp: float
    active_tp_label: str
    atr_at_entry: float
    adx_at_entry: float
    adx_soft_pass: bool
    tp2_upgraded: bool = False
    tp3_upgraded: bool = False
    trailing_activated: bool = False


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalized lower-case OHLC column names."""
    if df.empty:
        raise ValueError("OHLC data frame is empty")

    aliases = {
        "datetime": "time",
        "timestamp": "time",
        "date": "time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "tick_volume": "volume",
    }
    normalized = df.rename(columns={col: aliases.get(col, col.lower()) for col in df.columns}).copy()
    required = {"open", "high", "low", "close"}
    missing = required - set(normalized.columns)
    if missing:
        raise ValueError(f"Missing OHLC columns: {', '.join(sorted(missing))}")

    if "time" not in normalized.columns:
        normalized["time"] = np.arange(len(normalized))
    else:
        normalized["time"] = pd.to_datetime(normalized["time"], errors="ignore", utc=True)

    for col in ("open", "high", "low", "close"):
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    normalized = normalized.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if normalized.empty:
        raise ValueError("OHLC data frame has no valid rows after numeric conversion")
    return normalized


def add_indicators(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    out = normalize_ohlc(df)
    out["fast_ma"] = out["close"].rolling(cfg.fast_ma_period, min_periods=cfg.fast_ma_period).mean()
    out["slow_ma"] = out["close"].rolling(cfg.slow_ma_period, min_periods=cfg.slow_ma_period).mean()

    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = true_range.rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()

    up_move = out["high"].diff()
    down_move = -out["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_wilder = true_range.ewm(alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=out.index).ewm(
        alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period
    ).mean() / atr_wilder
    minus_di = 100 * pd.Series(minus_dm, index=out.index).ewm(
        alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period
    ).mean() / atr_wilder
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    out["adx"] = dx.ewm(alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period).mean()

    out["swing_high"] = _pivot_mask(out["high"], cfg.swing_window, is_high=True)
    out["swing_low"] = _pivot_mask(out["low"], cfg.swing_window, is_high=False)
    return out


def calculate_fib_levels(direction: Direction, high: float, low: float) -> FibLevels:
    rng = high - low
    if rng <= 0:
        raise ValueError("Order block high must be greater than low")

    if direction == Direction.BULLISH:
        return FibLevels(
            entry=low + 0.5 * rng,
            mitigation=low + 0.5 * rng,
            tp1=high + 0.127 * rng,
            trigger_tp2=high,
            tp2=high + 0.1618 * rng,
            trigger_tp3=high + 0.4 * rng,
            tp3=high + 1.3812 * rng,
            trigger_trail=high + 1.0 * rng,
        )

    return FibLevels(
        entry=high - 0.5 * rng,
        mitigation=high - 0.5 * rng,
        tp1=low - 0.127 * rng,
        trigger_tp2=low,
        tp2=low - 0.1618 * rng,
        trigger_tp3=low - 0.4 * rng,
        tp3=low - 1.3812 * rng,
        trigger_trail=low - 1.0 * rng,
    )


class ICTOrderBlockBacktester:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.cfg = config or BacktestConfig()

    def run(self, raw_df: pd.DataFrame, symbol: str) -> BacktestResult:
        df = add_indicators(raw_df, self.cfg)
        active_obs: List[OrderBlock] = []
        all_obs: List[OrderBlock] = []
        invalidated_obs: List[OrderBlock] = []
        trades: List[TradeResult] = []
        seen_ob_keys: set[tuple[str, int, str]] = set()
        open_trade: Optional[_OpenTrade] = None

        start_index = max(self.cfg.slow_ma_period, self.cfg.atr_period, self.cfg.adx_period) + self.cfg.swing_window + 1

        for index in range(start_index, len(df)):
            row = df.iloc[index]

            if open_trade is not None:
                maybe_result = self._manage_open_trade(open_trade, df, index, symbol)
                if maybe_result is not None:
                    trades.append(maybe_result)
                    open_trade = None

            self._invalidate_active_obs(active_obs, invalidated_obs, df, index)

            if open_trade is None:
                open_trade = self._try_open_trade(active_obs, df, index)
                if open_trade is not None:
                    # A retested OB is consumed once a simulated pending entry is filled.
                    open_trade.order_block.active = False
                    active_obs = [ob for ob in active_obs if ob.active]

            confirmation_lookback = max(self.cfg.fvg_lookahead + 2, self.cfg.bos_lookahead, 2)
            first_impulse = max(start_index, index - confirmation_lookback)
            for impulse_index in range(first_impulse, index + 1):
                new_ob = self._detect_order_block(df, impulse_index, symbol, confirmation_index=index)
                if new_ob is not None:
                    key = (symbol, new_ob.ob_index, new_ob.direction.value)
                    if key not in seen_ob_keys:
                        seen_ob_keys.add(key)
                        all_obs.append(new_ob)
                        if new_ob.active:
                            active_obs.append(new_ob)

            active_obs = [
                ob
                for ob in active_obs
                if ob.active and index - ob.impulse_index <= self.cfg.max_ob_age_bars
            ]

        if open_trade is not None:
            final_index = len(df) - 1
            trades.append(self._close_trade(open_trade, df, final_index, "END_OF_DATA", open_trade.active_tp_label, symbol))

        return BacktestResult(
            symbol=symbol,
            trades=trades,
            order_blocks=all_obs,
            invalidated_order_blocks=invalidated_obs,
            summary=self._build_summary(symbol, trades, all_obs, invalidated_obs),
        )

    def _detect_order_block(
        self,
        df: pd.DataFrame,
        impulse_index: int,
        symbol: str,
        confirmation_index: Optional[int] = None,
    ) -> Optional[OrderBlock]:
        confirmation_index = impulse_index if confirmation_index is None else confirmation_index
        row = df.iloc[impulse_index]
        atr = row.get("atr")
        if pd.isna(atr) or atr <= 0:
            return None

        candle_range = row["high"] - row["low"]
        body = abs(row["close"] - row["open"])
        if candle_range <= 0:
            return None
        if body < atr * self.cfg.momentum_atr_mult:
            return None
        if body / candle_range < self.cfg.momentum_body_ratio:
            return None

        if row["close"] > row["open"]:
            direction = Direction.BULLISH
            ob_index = self._find_last_opposite_candle(df, impulse_index, bearish=True)
        elif row["close"] < row["open"]:
            direction = Direction.BEARISH
            ob_index = self._find_last_opposite_candle(df, impulse_index, bearish=False)
        else:
            return None

        if ob_index is None:
            return None

        ob_row = df.iloc[ob_index]
        liquidity = self._has_liquidity_sweep(df, ob_index, direction)
        fvg, fvg_index = self._has_fvg(df, ob_index, impulse_index, confirmation_index, direction)
        trend = self._passes_trend_filter(df, impulse_index, direction)
        bos, structure_level = self._has_bos(df, ob_index, impulse_index, confirmation_index, direction)
        stars = sum([liquidity, fvg, trend, bos])

        return OrderBlock(
            symbol=symbol,
            direction=direction,
            ob_index=ob_index,
            impulse_index=impulse_index,
            time=ob_row["time"],
            high=float(ob_row["high"]),
            low=float(ob_row["low"]),
            midpoint=float((ob_row["high"] + ob_row["low"]) / 2),
            stars=stars,
            liquidity_sweep=liquidity,
            fvg=fvg,
            trend_filter=trend,
            bos=bos,
            fvg_index=fvg_index,
            structure_level=structure_level,
            active=stars >= self.cfg.min_stars,
            invalidated_reason="" if stars >= self.cfg.min_stars else "INSUFFICIENT_STARS",
        )

    def _find_last_opposite_candle(self, df: pd.DataFrame, impulse_index: int, bearish: bool) -> Optional[int]:
        first = max(0, impulse_index - self.cfg.ob_search_bars)
        for index in range(impulse_index - 1, first - 1, -1):
            row = df.iloc[index]
            if bearish and row["close"] < row["open"]:
                return index
            if not bearish and row["close"] > row["open"]:
                return index
        return None

    def _has_liquidity_sweep(self, df: pd.DataFrame, ob_index: int, direction: Direction) -> bool:
        start = max(0, ob_index - self.cfg.liquidity_lookback)
        for index in range(start, ob_index):
            row = df.iloc[index]
            if direction == Direction.BULLISH:
                swing = self._previous_swing_level(df, index, "low")
                if swing is not None and row["low"] < swing and row["close"] > swing:
                    return True
            else:
                swing = self._previous_swing_level(df, index, "high")
                if swing is not None and row["high"] > swing and row["close"] < swing:
                    return True
        return False

    def _has_fvg(
        self,
        df: pd.DataFrame,
        ob_index: int,
        impulse_index: int,
        confirmation_index: int,
        direction: Direction,
    ) -> tuple[bool, Optional[int]]:
        end = min(len(df) - 3, impulse_index + self.cfg.fvg_lookahead, confirmation_index - 2)
        if end < ob_index:
            return False, None
        for index in range(ob_index, end + 1):
            first = df.iloc[index]
            third = df.iloc[index + 2]
            if direction == Direction.BULLISH and third["low"] > first["high"]:
                return True, index
            if direction == Direction.BEARISH and third["high"] < first["low"]:
                return True, index
        return False, None

    def _passes_trend_filter(self, df: pd.DataFrame, index: int, direction: Direction) -> bool:
        row = df.iloc[index]
        if pd.isna(row["fast_ma"]) or pd.isna(row["slow_ma"]):
            return False
        if direction == Direction.BULLISH:
            return bool(row["close"] > row["fast_ma"] and row["close"] > row["slow_ma"])
        return bool(row["close"] < row["fast_ma"] and row["close"] < row["slow_ma"])

    def _has_bos(
        self,
        df: pd.DataFrame,
        ob_index: int,
        impulse_index: int,
        confirmation_index: int,
        direction: Direction,
    ) -> tuple[bool, Optional[float]]:
        if direction == Direction.BULLISH:
            swing = self._previous_swing_level(df, ob_index, "high")
            if swing is None:
                return False, None
            end = min(len(df) - 1, impulse_index + self.cfg.bos_lookahead, confirmation_index)
            return bool(df.iloc[ob_index + 1 : end + 1]["high"].max() > swing), float(swing)

        swing = self._previous_swing_level(df, ob_index, "low")
        if swing is None:
            return False, None
        end = min(len(df) - 1, impulse_index + self.cfg.bos_lookahead, confirmation_index)
        return bool(df.iloc[ob_index + 1 : end + 1]["low"].min() < swing), float(swing)

    def _previous_swing_level(self, df: pd.DataFrame, index: int, kind: str) -> Optional[float]:
        if kind == "high":
            mask_col = "swing_high"
            value_col = "high"
        else:
            mask_col = "swing_low"
            value_col = "low"
        last_known = index - self.cfg.swing_window
        if last_known <= 0:
            return None
        prior = df.iloc[:last_known]
        swings = prior[prior[mask_col]]
        if swings.empty:
            return None
        return float(swings[value_col].iloc[-1])

    def _invalidate_active_obs(
        self,
        active_obs: List[OrderBlock],
        invalidated_obs: List[OrderBlock],
        df: pd.DataFrame,
        index: int,
    ) -> None:
        row = df.iloc[index]
        for ob in active_obs:
            if not ob.active or index <= ob.impulse_index:
                continue
            if ob.direction == Direction.BULLISH and row["close"] < ob.midpoint:
                ob.active = False
                ob.invalidated_reason = "MITIGATED_BEFORE_RETEST"
                invalidated_obs.append(ob)
            elif ob.direction == Direction.BEARISH and row["close"] > ob.midpoint:
                ob.active = False
                ob.invalidated_reason = "MITIGATED_BEFORE_RETEST"
                invalidated_obs.append(ob)

    def _try_open_trade(self, active_obs: Iterable[OrderBlock], df: pd.DataFrame, index: int) -> Optional[_OpenTrade]:
        row = df.iloc[index]
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            return None

        for ob in sorted(active_obs, key=lambda item: item.impulse_index):
            if index <= ob.impulse_index or not ob.active:
                continue
            if index - ob.impulse_index > self.cfg.max_ob_age_bars:
                continue
            if not self._entry_trend_confirmed(row, ob.direction):
                continue

            fib = ob.fib
            touched = row["low"] <= fib.entry <= row["high"]
            if not touched:
                continue

            if ob.direction == Direction.BULLISH and row["close"] < fib.mitigation:
                continue
            if ob.direction == Direction.BEARISH and row["close"] > fib.mitigation:
                continue

            entry = float(fib.entry)
            atr = float(row["atr"])
            if ob.direction == Direction.BULLISH:
                sl = entry - atr * self.cfg.sl_atr_mult
            else:
                sl = entry + atr * self.cfg.sl_atr_mult

            return _OpenTrade(
                order_block=ob,
                entry_index=index,
                entry_time=row["time"],
                direction=ob.direction,
                entry_price=entry,
                sl_initial=float(sl),
                sl_current=float(sl),
                active_tp=float(fib.tp1),
                active_tp_label="TP1",
                atr_at_entry=atr,
                adx_at_entry=float(row["adx"]) if not pd.isna(row["adx"]) else 0.0,
                adx_soft_pass=bool((not pd.isna(row["adx"])) and row["adx"] > self.cfg.adx_entry_soft_filter),
            )
        return None

    def _entry_trend_confirmed(self, row: pd.Series, direction: Direction) -> bool:
        if pd.isna(row["fast_ma"]) or pd.isna(row["slow_ma"]):
            return False
        if direction == Direction.BULLISH:
            return bool(row["close"] > row["fast_ma"] and row["close"] > row["slow_ma"])
        return bool(row["close"] < row["fast_ma"] and row["close"] < row["slow_ma"])

    def _manage_open_trade(
        self, trade: _OpenTrade, df: pd.DataFrame, index: int, symbol: str
    ) -> Optional[TradeResult]:
        row = df.iloc[index]
        fib = trade.order_block.fib
        adx = float(row["adx"]) if not pd.isna(row["adx"]) else 0.0
        atr = float(row["atr"]) if not pd.isna(row["atr"]) else trade.atr_at_entry

        if trade.direction == Direction.BULLISH:
            if row["low"] <= trade.sl_current:
                return self._close_trade(trade, df, index, "SL", "SL", symbol, exit_price=trade.sl_current)

            if self.cfg.enable_max_gain:
                if (not trade.tp2_upgraded) and row["high"] >= fib.trigger_tp2 and adx > self.cfg.adx_upgrade_threshold:
                    trade.tp2_upgraded = True
                    trade.active_tp = fib.tp2
                    trade.active_tp_label = "TP2"
                    trade.sl_current = max(trade.sl_current, trade.entry_price)
                if (not trade.tp3_upgraded) and row["high"] >= fib.trigger_tp3 and adx > self.cfg.adx_upgrade_threshold:
                    trade.tp3_upgraded = True
                    trade.active_tp = fib.tp3
                    trade.active_tp_label = "TP3"
                if row["high"] >= fib.trigger_trail and adx > self.cfg.adx_upgrade_threshold:
                    trade.trailing_activated = True

            if trade.trailing_activated:
                trade.sl_current = max(trade.sl_current, float(row["close"] - atr * self.cfg.trailing_atr_mult))

            if row["high"] >= trade.active_tp:
                return self._close_trade(
                    trade, df, index, trade.active_tp_label, trade.active_tp_label, symbol, exit_price=trade.active_tp
                )
            return None

        if row["high"] >= trade.sl_current:
            return self._close_trade(trade, df, index, "SL", "SL", symbol, exit_price=trade.sl_current)

        if self.cfg.enable_max_gain:
            if (not trade.tp2_upgraded) and row["low"] <= fib.trigger_tp2 and adx > self.cfg.adx_upgrade_threshold:
                trade.tp2_upgraded = True
                trade.active_tp = fib.tp2
                trade.active_tp_label = "TP2"
                trade.sl_current = min(trade.sl_current, trade.entry_price)
            if (not trade.tp3_upgraded) and row["low"] <= fib.trigger_tp3 and adx > self.cfg.adx_upgrade_threshold:
                trade.tp3_upgraded = True
                trade.active_tp = fib.tp3
                trade.active_tp_label = "TP3"
            if row["low"] <= fib.trigger_trail and adx > self.cfg.adx_upgrade_threshold:
                trade.trailing_activated = True

        if trade.trailing_activated:
            trade.sl_current = min(trade.sl_current, float(row["close"] + atr * self.cfg.trailing_atr_mult))

        if row["low"] <= trade.active_tp:
            return self._close_trade(
                trade, df, index, trade.active_tp_label, trade.active_tp_label, symbol, exit_price=trade.active_tp
            )
        return None

    def _close_trade(
        self,
        trade: _OpenTrade,
        df: pd.DataFrame,
        index: int,
        reason: str,
        tp_level: str,
        symbol: str,
        exit_price: Optional[float] = None,
    ) -> TradeResult:
        row = df.iloc[index]
        close_price = float(row["close"] if exit_price is None else exit_price)
        if trade.direction == Direction.BULLISH:
            pnl_points = close_price - trade.entry_price
            initial_risk = trade.entry_price - trade.sl_initial
        else:
            pnl_points = trade.entry_price - close_price
            initial_risk = trade.sl_initial - trade.entry_price

        r_multiple = pnl_points / initial_risk if initial_risk else 0.0
        ob = trade.order_block
        return TradeResult(
            symbol=symbol,
            direction="BUY" if trade.direction == Direction.BULLISH else "SELL",
            entry_time=trade.entry_time,
            exit_time=row["time"],
            entry_index=trade.entry_index,
            exit_index=index,
            entry_price=trade.entry_price,
            exit_price=close_price,
            sl_initial=trade.sl_initial,
            sl_final=trade.sl_current,
            tp_final=trade.active_tp,
            exit_reason=reason,
            tp_level=tp_level,
            pnl_points=float(pnl_points),
            pnl_value=float(pnl_points * self.cfg.point_value),
            r_multiple=float(r_multiple),
            bars_held=index - trade.entry_index,
            stars=ob.stars,
            liquidity_sweep=ob.liquidity_sweep,
            fvg=ob.fvg,
            trend_filter=ob.trend_filter,
            bos=ob.bos,
            adx_at_entry=trade.adx_at_entry,
            atr_at_entry=trade.atr_at_entry,
            adx_soft_pass=trade.adx_soft_pass,
            tp2_upgraded=trade.tp2_upgraded,
            tp3_upgraded=trade.tp3_upgraded,
            trailing_activated=trade.trailing_activated,
            ob_time=ob.time,
            ob_high=ob.high,
            ob_low=ob.low,
        )

    def _build_summary(
        self,
        symbol: str,
        trades: List[TradeResult],
        order_blocks: List[OrderBlock],
        invalidated_order_blocks: List[OrderBlock],
    ) -> Dict[str, Any]:
        pnl = [trade.pnl_points for trade in trades]
        wins = [value for value in pnl if value > 0]
        losses = [value for value in pnl if value <= 0]
        gross_profit = float(sum(wins))
        gross_loss = float(sum(losses))
        return {
            "symbol": symbol,
            "trades": len(trades),
            "order_blocks_detected": len(order_blocks),
            "order_blocks_valid": sum(1 for ob in order_blocks if ob.stars >= self.cfg.min_stars),
            "order_blocks_invalidated_before_retest": len(invalidated_order_blocks),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades)) if trades else 0.0,
            "net_pnl_points": float(sum(pnl)),
            "gross_profit_points": gross_profit,
            "gross_loss_points": gross_loss,
            "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss else None,
            "average_r": float(np.mean([trade.r_multiple for trade in trades])) if trades else 0.0,
            "max_drawdown_points": self._max_drawdown(pnl),
        }

    @staticmethod
    def _max_drawdown(pnl: List[float]) -> float:
        equity = np.cumsum(pnl)
        if len(equity) == 0:
            return 0.0
        peaks = np.maximum.accumulate(equity)
        drawdowns = equity - peaks
        return float(drawdowns.min())


def _pivot_mask(series: pd.Series, window: int, is_high: bool) -> pd.Series:
    values = series.to_numpy()
    mask = np.zeros(len(values), dtype=bool)
    for index in range(window, len(values) - window):
        segment = values[index - window : index + window + 1]
        if is_high:
            mask[index] = values[index] == np.nanmax(segment) and np.sum(segment == values[index]) == 1
        else:
            mask[index] = values[index] == np.nanmin(segment) and np.sum(segment == values[index]) == 1
    return pd.Series(mask, index=series.index)

