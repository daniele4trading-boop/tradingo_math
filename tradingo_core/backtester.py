"""Candle-by-candle backtester for ICT sniper setups."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal, Optional

import pandas as pd

from .ict_sniper import ICTSniperConfig, ICTSniperSetup, ICTSniperStrategy
from .market_data import normalize_rates_frame


TradeStatus = Literal["WIN", "LOSS", "BREAKEVEN", "EXPIRED", "OPEN"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: float = 100_000.0
    risk_per_trade_pct: float = 0.005
    max_daily_dd_pct: float = 0.02
    max_daily_trades: int = 3
    pending_expiry_minutes: int = 90
    break_even_at_r: float = 1.0
    conservative_intrabar: bool = True
    signal_evaluation_minutes: int = 5
    signal_history_bars: int = 2_500


@dataclass(frozen=True)
class TradeResult:
    setup_time: pd.Timestamp
    entry_time: Optional[pd.Timestamp]
    exit_time: Optional[pd.Timestamp]
    direction: str
    entry: float
    sl: float
    tp: float
    score: float
    status: TradeStatus
    r_result: float
    pnl: float
    session: str
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BacktestReport:
    trades: tuple[TradeResult, ...]
    initial_equity: float
    final_equity: float
    max_drawdown_pct: float
    max_daily_drawdown_pct: float
    winrate: float
    profit_factor: float
    expectancy_r: float

    @property
    def trade_count(self) -> int:
        return len([t for t in self.trades if t.status not in ("EXPIRED", "OPEN")])

    @property
    def setup_count(self) -> int:
        return len(self.trades)


class ICTSniperBacktester:
    """Backtest the strategy using only completed M1 candles."""

    def __init__(
        self,
        strategy_config: Optional[ICTSniperConfig] = None,
        backtest_config: Optional[BacktestConfig] = None,
    ):
        self.strategy_config = strategy_config or ICTSniperConfig()
        self.backtest_config = backtest_config or BacktestConfig()
        self.strategy = ICTSniperStrategy(self.strategy_config)

    def run(self, m1_rates: pd.DataFrame) -> BacktestReport:
        data = normalize_rates_frame(m1_rates)
        if data.empty:
            return self._empty_report()

        equity = self.backtest_config.initial_equity
        peak_equity = equity
        max_dd = 0.0
        max_daily_dd = 0.0
        day_start_equity = equity
        current_day: Optional[date] = None
        daily_trades = 0
        daily_halted = False
        pending: Optional[ICTSniperSetup] = None
        pending_expires: Optional[pd.Timestamp] = None
        open_trade: Optional[_OpenTrade] = None
        results: list[TradeResult] = []
        seen_setup_keys: set[tuple[pd.Timestamp, str, float]] = set()

        warmup = max(180, self.strategy_config.volume_z_window + 120)
        for i in range(warmup, len(data)):
            row = data.iloc[i]
            ts = pd.Timestamp(row["time"])
            row_day = ts.date()
            if current_day != row_day:
                current_day = row_day
                day_start_equity = equity
                daily_trades = 0
                daily_halted = False

            if open_trade is not None:
                close_result = self._advance_open_trade(open_trade, row, equity)
                if close_result is not None:
                    equity += close_result.pnl
                    results.append(close_result)
                    open_trade = None

                    peak_equity = max(peak_equity, equity)
                    max_dd = max(max_dd, drawdown_pct(equity, peak_equity))
                    max_daily_dd = max(max_daily_dd, drawdown_pct(equity, day_start_equity))
                    if drawdown_pct(equity, day_start_equity) >= self.backtest_config.max_daily_dd_pct:
                        daily_halted = True

            if pending is not None and open_trade is None:
                if pending_expires is not None and ts > pending_expires:
                    results.append(
                        TradeResult(
                            setup_time=pending.timestamp,
                            entry_time=None,
                            exit_time=ts,
                            direction=pending.direction,
                            entry=pending.entry,
                            sl=pending.sl,
                            tp=pending.tp2,
                            score=pending.score,
                            status="EXPIRED",
                            r_result=0.0,
                            pnl=0.0,
                            session=pending.session,
                            notes=("pending_order_expired",),
                        )
                    )
                    pending = None
                    pending_expires = None
                elif self._fills(pending, row):
                    risk_amount = equity * self.backtest_config.risk_per_trade_pct
                    open_trade = _OpenTrade(
                        setup=pending,
                        entry_time=ts,
                        risk_amount=risk_amount,
                        current_sl=pending.sl,
                        break_even_done=False,
                    )
                    daily_trades += 1
                    pending = None
                    pending_expires = None

            if open_trade is not None or pending is not None or daily_halted:
                continue
            if daily_trades >= self.backtest_config.max_daily_trades:
                continue
            if (
                self.backtest_config.signal_evaluation_minutes > 1
                and ts.minute % self.backtest_config.signal_evaluation_minutes != 0
            ):
                continue
            if self.strategy.session_name(ts) is None:
                continue

            start_idx = max(0, i + 1 - self.backtest_config.signal_history_bars)
            history = data.iloc[start_idx : i + 1]
            setup = self.strategy.find_setup(history)
            if setup is None:
                continue

            key = (setup.fvg.created_at, setup.direction, round(setup.entry, 5))
            if key in seen_setup_keys:
                continue
            seen_setup_keys.add(key)
            pending = setup
            pending_expires = ts + timedelta(minutes=self.backtest_config.pending_expiry_minutes)

        if open_trade is not None:
            setup = open_trade.setup
            last_ts = pd.Timestamp(data["time"].iloc[-1])
            results.append(
                TradeResult(
                    setup_time=setup.timestamp,
                    entry_time=open_trade.entry_time,
                    exit_time=last_ts,
                    direction=setup.direction,
                    entry=setup.entry,
                    sl=open_trade.current_sl,
                    tp=setup.tp2,
                    score=setup.score,
                    status="OPEN",
                    r_result=0.0,
                    pnl=0.0,
                    session=setup.session,
                    notes=("still_open_at_end",),
                )
            )

        return build_report(tuple(results), self.backtest_config.initial_equity, equity, max_dd, max_daily_dd)

    def _advance_open_trade(
        self,
        trade: "_OpenTrade",
        row: pd.Series,
        equity_before: float,
    ) -> Optional[TradeResult]:
        setup = trade.setup
        ts = pd.Timestamp(row["time"])
        high = float(row["high"])
        low = float(row["low"])
        risk_points = setup.risk_points
        if risk_points <= 0:
            return self._close_result(trade, ts, "LOSS", -1.0, equity_before, "invalid_risk")

        if setup.direction == "BUY":
            current_r = (high - setup.entry) / risk_points
            if not trade.break_even_done and current_r >= self.backtest_config.break_even_at_r:
                trade.current_sl = setup.entry
                trade.break_even_done = True

            hit_sl = low <= trade.current_sl
            hit_tp = high >= setup.tp2
            if hit_sl and hit_tp and self.backtest_config.conservative_intrabar:
                r = 0.0 if trade.current_sl == setup.entry else -1.0
                return self._close_result(trade, ts, "BREAKEVEN" if r == 0 else "LOSS", r, equity_before, "same_bar_sl_tp")
            if hit_tp:
                return self._close_result(trade, ts, "WIN", setup.rr, equity_before, "tp2_hit")
            if hit_sl:
                r = 0.0 if trade.current_sl == setup.entry else -1.0
                return self._close_result(trade, ts, "BREAKEVEN" if r == 0 else "LOSS", r, equity_before, "sl_hit")
        else:
            current_r = (setup.entry - low) / risk_points
            if not trade.break_even_done and current_r >= self.backtest_config.break_even_at_r:
                trade.current_sl = setup.entry
                trade.break_even_done = True

            hit_sl = high >= trade.current_sl
            hit_tp = low <= setup.tp2
            if hit_sl and hit_tp and self.backtest_config.conservative_intrabar:
                r = 0.0 if trade.current_sl == setup.entry else -1.0
                return self._close_result(trade, ts, "BREAKEVEN" if r == 0 else "LOSS", r, equity_before, "same_bar_sl_tp")
            if hit_tp:
                return self._close_result(trade, ts, "WIN", setup.rr, equity_before, "tp2_hit")
            if hit_sl:
                r = 0.0 if trade.current_sl == setup.entry else -1.0
                return self._close_result(trade, ts, "BREAKEVEN" if r == 0 else "LOSS", r, equity_before, "sl_hit")

        return None

    def _close_result(
        self,
        trade: "_OpenTrade",
        exit_time: pd.Timestamp,
        status: TradeStatus,
        r_result: float,
        equity_before: float,
        note: str,
    ) -> TradeResult:
        setup = trade.setup
        pnl = trade.risk_amount * r_result
        return TradeResult(
            setup_time=setup.timestamp,
            entry_time=trade.entry_time,
            exit_time=exit_time,
            direction=setup.direction,
            entry=setup.entry,
            sl=trade.current_sl,
            tp=setup.tp2,
            score=setup.score,
            status=status,
            r_result=r_result,
            pnl=pnl,
            session=setup.session,
            notes=(note, f"equity_before={equity_before:.2f}"),
        )

    @staticmethod
    def _fills(setup: ICTSniperSetup, row: pd.Series) -> bool:
        return float(row["low"]) <= setup.entry <= float(row["high"])

    def _empty_report(self) -> BacktestReport:
        return BacktestReport(
            trades=(),
            initial_equity=self.backtest_config.initial_equity,
            final_equity=self.backtest_config.initial_equity,
            max_drawdown_pct=0.0,
            max_daily_drawdown_pct=0.0,
            winrate=0.0,
            profit_factor=0.0,
            expectancy_r=0.0,
        )


@dataclass
class _OpenTrade:
    setup: ICTSniperSetup
    entry_time: pd.Timestamp
    risk_amount: float
    current_sl: float
    break_even_done: bool


def build_report(
    trades: tuple[TradeResult, ...],
    initial_equity: float,
    final_equity: float,
    max_dd: float,
    max_daily_dd: float,
) -> BacktestReport:
    closed = [t for t in trades if t.status not in ("EXPIRED", "OPEN")]
    wins = [t for t in closed if t.r_result > 0]
    losses = [t for t in closed if t.r_result < 0]
    winrate = len(wins) / len(closed) if closed else 0.0
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_win / gross_loss if gross_loss else (float("inf") if gross_win else 0.0)
    expectancy_r = sum(t.r_result for t in closed) / len(closed) if closed else 0.0
    return BacktestReport(
        trades=trades,
        initial_equity=initial_equity,
        final_equity=final_equity,
        max_drawdown_pct=max_dd,
        max_daily_drawdown_pct=max_daily_dd,
        winrate=winrate,
        profit_factor=profit_factor,
        expectancy_r=expectancy_r,
    )


def drawdown_pct(equity: float, reference: float) -> float:
    if reference <= 0:
        return 0.0
    return max(0.0, (reference - equity) / reference)
