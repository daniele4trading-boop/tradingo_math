"""Bar-by-bar backtest engine for Emission MTF strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.data_loader import build_multitf
from strategies.emission_mtf import EmissionMtfConfig, EmissionMtfStrategy, EntryMethod, TradeDirection


@dataclass
class PendingOrder:
    signal_time: pd.Timestamp
    created_time: pd.Timestamp
    expire_time: pd.Timestamp
    direction: TradeDirection
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    reason: str
    profile: str
    setup_id: int


@dataclass
class OpenTrade:
    direction: TradeDirection
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    initial_sl: float
    size: float = 1.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    be_active: bool = False
    risk_usd: float = 100.0
    reason: str = ""
    profile: str = ""


@dataclass
class EmissionBacktestResult:
    trades: pd.DataFrame
    metrics: Dict
    equity: pd.DataFrame
    profile: str


def _build_end_index(times: np.ndarray, ref_times: np.ndarray) -> np.ndarray:
    return np.searchsorted(times, ref_times, side="right") - 1


class EmissionBacktestEngine:
    def __init__(
        self,
        m1: pd.DataFrame,
        config: Optional[EmissionMtfConfig] = None,
        risk_per_trade_usd: float = 100.0,
        initial_balance: float = 10_000.0,
        tf: Optional[Dict[str, pd.DataFrame]] = None,
    ):
        self.tf = tf if tf is not None else build_multitf(m1)
        self.strategy = EmissionMtfStrategy(config)
        self.cfg = config or EmissionMtfConfig()
        self.risk_per_trade_usd = risk_per_trade_usd
        self.initial_balance = initial_balance
        self.spread_price = self.cfg.spread_points * self.cfg.point_size

    def run(self, start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None) -> EmissionBacktestResult:
        exec_key = self.cfg.exec_tf
        exec_df = self.tf[exec_key].copy()
        if start is not None:
            exec_df = exec_df[exec_df["time"] >= start]
        if end is not None:
            exec_df = exec_df[exec_df["time"] <= end]
        exec_df = exec_df.reset_index(drop=True)

        outer_key = self.cfg.context_outer_tf
        inner_key = self.cfg.context_inner_tf
        op_key = self.cfg.operational_tf

        df_outer = self.tf[outer_key]
        df_inner = self.tf[inner_key]
        df_op = self.tf[op_key]

        outer_t = df_outer["time"].to_numpy()
        inner_t = df_inner["time"].to_numpy()
        op_t = df_op["time"].to_numpy()
        exec_t = exec_df["time"].to_numpy()

        outer_end = _build_end_index(outer_t, exec_t)
        inner_end = _build_end_index(inner_t, exec_t)
        op_end = _build_end_index(op_t, exec_t)

        pending: Optional[PendingOrder] = None
        open_trade: Optional[OpenTrade] = None
        closed: List[Dict] = []
        last_op_end = -1
        min_op_bars = 30
        warmup = 120

        for i in range(warmup, len(exec_df)):
            bar = exec_df.iloc[i]
            t = pd.Timestamp(bar["time"])

            if open_trade is not None:
                open_trade, done = self._manage_trade(open_trade, bar)
                if done is not None:
                    closed.append(done)
                    open_trade = None
                    if done["exit_reason"] == "SL":
                        self.strategy.register_sl_hit(pd.Timestamp(done["exit_time"]))
                continue

            if pending is not None:
                filled = self._try_fill_limit(pending, bar)
                if filled:
                    open_trade = filled
                    pending = None
                    continue
                if t >= pending.expire_time:
                    pending = None

            if op_end[i] > last_op_end and op_end[i] >= min_op_bars:
                self.strategy.register_operational_bar(
                    df_outer.iloc[: outer_end[i] + 1],
                    df_inner.iloc[: inner_end[i] + 1],
                    df_op.iloc[: op_end[i] + 1],
                )
                last_op_end = op_end[i]

            if op_end[i] < min_op_bars:
                continue

            if not self.strategy.has_active_setups():
                continue

            signal = self.strategy.try_signal(
                exec_time=t,
                df_outer=df_outer.iloc[: outer_end[i] + 1],
                df_inner=df_inner.iloc[: inner_end[i] + 1],
                df_op=df_op.iloc[: op_end[i] + 1],
                df_exec=exec_df.iloc[: i + 1],
            )
            if signal is None or open_trade is not None:
                continue
            if pending is not None and signal.setup_id == pending.setup_id:
                continue

            if signal.entry_type == "market":
                open_trade = self._open_market(signal, bar)
            elif pending is None:
                pending = PendingOrder(
                    signal_time=signal.signal_time,
                    created_time=t,
                    expire_time=t + pd.Timedelta(minutes=self.cfg.exec_minutes * self.cfg.effective_limit_expire_bars),
                    direction=signal.direction,
                    entry_price=signal.entry_price,
                    sl=signal.sl,
                    tp1=signal.tp1,
                    tp2=signal.tp2,
                    tp3=signal.tp3,
                    reason=signal.reason,
                    profile=signal.profile,
                    setup_id=signal.setup_id,
                )

        trades_df = pd.DataFrame(closed)
        from backtest.metrics import compute_metrics, equity_curve

        metrics = compute_metrics(trades_df, self.initial_balance)
        eq = equity_curve(trades_df, self.initial_balance)
        return EmissionBacktestResult(
            trades=trades_df,
            metrics=metrics,
            equity=eq,
            profile=self.cfg.profile.value,
        )

    def _half_spread(self) -> float:
        return self.spread_price / 2.0

    def _open_market(self, signal, bar: pd.Series) -> OpenTrade:
        if signal.direction == TradeDirection.LONG:
            entry = float(bar["close"]) + self._half_spread() + 0.10
        else:
            entry = float(bar["close"]) - self._half_spread() - 0.10
        return OpenTrade(
            direction=signal.direction,
            entry_time=pd.Timestamp(bar["time"]),
            entry_price=entry,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            initial_sl=signal.sl,
            risk_usd=self.risk_per_trade_usd,
            reason=signal.reason,
            profile=signal.profile,
        )

    def _try_fill_limit(self, pending: PendingOrder, bar: pd.Series) -> Optional[OpenTrade]:
        limit = pending.entry_price
        if pending.direction == TradeDirection.LONG:
            if float(bar["low"]) > limit:
                return None
            entry = limit + self._half_spread() + 0.10
        else:
            if float(bar["high"]) < limit:
                return None
            entry = limit - self._half_spread() - 0.10
        if abs(entry - pending.sl) <= 0:
            return None
        return OpenTrade(
            direction=pending.direction,
            entry_time=pd.Timestamp(bar["time"]),
            entry_price=entry,
            sl=pending.sl,
            tp1=pending.tp1,
            tp2=pending.tp2,
            tp3=pending.tp3,
            initial_sl=pending.sl,
            risk_usd=self.risk_per_trade_usd,
            reason=pending.reason,
            profile=pending.profile,
        )

    def _manage_trade(self, trade: OpenTrade, bar: pd.Series) -> Tuple[Optional[OpenTrade], Optional[Dict]]:
        direction = trade.direction
        high = float(bar["high"])
        low = float(bar["low"])
        sl = trade.sl

        if direction == TradeDirection.LONG:
            sl_hit = low <= sl
            tp1_hit = high >= trade.tp1
            tp2_hit = high >= trade.tp2
            tp3_hit = high >= trade.tp3
            if not trade.be_active and tp1_hit:
                trade.be_active = True
                trade.sl = trade.entry_price
                sl = trade.sl
        else:
            sl_hit = high >= sl
            tp1_hit = low <= trade.tp1
            tp2_hit = low <= trade.tp2
            tp3_hit = low <= trade.tp3
            if not trade.be_active and tp1_hit:
                trade.be_active = True
                trade.sl = trade.entry_price
                sl = trade.sl

        if sl_hit:
            return None, self._close_trade(trade, bar, sl, "SL", -1.0 * trade.size, trade.tp1_hit, trade.tp2_hit, False)

        exit_price = None
        exit_reason = None
        size_close = 0.0
        tp1_done = trade.tp1_hit
        tp2_done = trade.tp2_hit
        tp3_done = False

        if not trade.tp1_hit and tp1_hit:
            trade.tp1_hit = True
            tp1_done = True
            size_close += 0.5
            exit_price = trade.tp1
            exit_reason = "TP1"
        if trade.tp1_hit and not trade.tp2_hit and tp2_hit:
            trade.tp2_hit = True
            tp2_done = True
            size_close += 0.3
            exit_price = trade.tp2
            exit_reason = "TP2"
        if trade.tp2_hit and tp3_hit:
            tp3_done = True
            size_close += trade.size
            exit_price = trade.tp3
            exit_reason = "TP3"

        if size_close > 0 and exit_price is not None:
            risk = abs(trade.entry_price - trade.initial_sl)
            if direction == TradeDirection.LONG:
                pnl_r = ((exit_price - trade.entry_price) / risk) * size_close
            else:
                pnl_r = ((trade.entry_price - exit_price) / risk) * size_close
            trade.size -= size_close
            if trade.size <= 1e-9:
                return None, self._close_trade(trade, bar, exit_price, exit_reason, pnl_r, tp1_done, tp2_done, tp3_done)
        return trade, None

    def _close_trade(
        self, trade: OpenTrade, bar: pd.Series, exit_price: float, reason: str,
        pnl_r: float, tp1_hit: bool, tp2_hit: bool, tp3_hit: bool,
    ) -> Dict:
        t = pd.Timestamp(bar["time"])
        local = t + pd.Timedelta(hours=self.cfg.broker_utc_offset_hours)
        mins = local.hour * 60 + local.minute
        if 9 * 60 <= mins <= 12 * 60:
            session = "London"
        elif 15 * 60 <= mins <= 20 * 60:
            session = "NY"
        else:
            session = "Other"
        return {
            "profile": trade.profile,
            "direction": trade.direction.value,
            "entry_time": trade.entry_time,
            "exit_time": t,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "sl": trade.initial_sl,
            "tp1": trade.tp1,
            "tp2": trade.tp2,
            "tp3": trade.tp3,
            "exit_reason": reason,
            "pnl_r": pnl_r,
            "pnl_usd": pnl_r * trade.risk_usd,
            "realized_rr": pnl_r,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "tp3_hit": tp3_hit,
            "session": session,
            "reason": trade.reason,
        }
