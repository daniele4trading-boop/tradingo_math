"""Bar-by-bar backtest engine for LQS-MTF (multi-profile)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.data_loader import build_multitf
from strategies.lqs_mtf import LQSMtfConfig, LQSMtfStrategy, TradeDirection
from strategies.structure import in_session


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
class BacktestResult:
    trades: pd.DataFrame
    metrics: Dict
    equity: pd.DataFrame
    profile: str


def _build_end_index(times: np.ndarray, ref_times: np.ndarray) -> np.ndarray:
    return np.searchsorted(times, ref_times, side="right") - 1


class BacktestEngine:
    def __init__(
        self,
        m1: pd.DataFrame,
        config: Optional[LQSMtfConfig] = None,
        risk_per_trade_usd: float = 100.0,
        initial_balance: float = 10_000.0,
        tf: Optional[Dict[str, pd.DataFrame]] = None,
    ):
        self.tf = tf if tf is not None else build_multitf(m1)
        self.strategy = LQSMtfStrategy(config)
        self.cfg = config or LQSMtfConfig()
        self.risk_per_trade_usd = risk_per_trade_usd
        self.initial_balance = initial_balance
        self.spread_price = self.cfg.spread_points * self.cfg.point_size

    def run(self, start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None) -> BacktestResult:
        m5 = self.tf["M5"].copy()
        if start is not None:
            m5 = m5[m5["time"] >= start]
        if end is not None:
            m5 = m5[m5["time"] <= end]
        m5 = m5.reset_index(drop=True)

        liq_key = self.cfg.liquidity_tf
        confirm_key = self.cfg.confirm_tf
        context_key = str(self.cfg.spec["context_tf"])

        df_liq = self.tf[liq_key]
        df_confirm = self.tf[confirm_key]
        df_context = self.tf[context_key]

        liq_t = df_liq["time"].to_numpy()
        confirm_t = df_confirm["time"].to_numpy()
        context_t = df_context["time"].to_numpy()
        m5_t = m5["time"].to_numpy()

        liq_end = _build_end_index(liq_t, m5_t)
        confirm_end = _build_end_index(confirm_t, m5_t)
        context_end = _build_end_index(context_t, m5_t)

        pending: Optional[PendingOrder] = None
        open_trade: Optional[OpenTrade] = None
        closed: List[Dict] = []
        last_liq_end = -1
        last_confirm_end = -1
        confirm_is_m5 = confirm_key == "M5"
        min_liq_bars = 20

        warmup = 200
        for i in range(warmup, len(m5)):
            bar = m5.iloc[i]
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

            if liq_end[i] > last_liq_end and liq_end[i] >= min_liq_bars:
                self.strategy.register_liquidity_bar(
                    df_context.iloc[: context_end[i] + 1],
                    df_liq.iloc[: liq_end[i] + 1],
                )
                last_liq_end = liq_end[i]

            if liq_end[i] < min_liq_bars:
                continue

            # M5 confirm: scan every M5 bar; M15/H4 confirm: on confirm TF bar advance
            if not confirm_is_m5:
                if confirm_end[i] == last_confirm_end and pending is None:
                    continue
                last_confirm_end = confirm_end[i]

            signal = self.strategy.try_signal(
                m5_time=t,
                df_context=df_context.iloc[: context_end[i] + 1],
                df_liquidity=df_liq.iloc[: liq_end[i] + 1],
                df_confirm=df_confirm.iloc[: confirm_end[i] + 1],
                df_m5=m5.iloc[: i + 1],
            )
            if signal is not None and pending is None and open_trade is None:
                pending = PendingOrder(
                    signal_time=signal.signal_time,
                    created_time=t,
                    expire_time=t + pd.Timedelta(minutes=5 * self.cfg.limit_expire_bars_m5),
                    direction=signal.direction,
                    entry_price=signal.entry_price,
                    sl=signal.sl,
                    tp1=signal.tp1,
                    tp2=signal.tp2,
                    tp3=signal.tp3,
                    reason=signal.reason,
                    profile=signal.profile,
                )

        trades_df = pd.DataFrame(closed)
        from backtest.metrics import compute_metrics, equity_curve

        metrics = compute_metrics(trades_df, self.initial_balance)
        eq = equity_curve(trades_df, self.initial_balance)
        return BacktestResult(
            trades=trades_df,
            metrics=metrics,
            equity=eq,
            profile=self.cfg.profile.value,
        )

    def _half_spread(self) -> float:
        return self.spread_price / 2.0

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
