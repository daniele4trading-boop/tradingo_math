"""Macchina a stati di una singola strategia Pattern GO (un timeframe).

L'engine e' puro: consuma barre chiuse e restituisce intenzioni operative.
Chi lo usa (il runner) le traduce in chiamate al broker e gli notifica fill e
chiusure. Non conosce ne' rete ne' orologio: tutto passa dalle barre.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .strategy import (
    SessionSpec,
    SessionState,
    SwingTracker,
    compute_features,
    match_pattern,
    take_profit,
    trigger_and_stop,
)
from .types import Bar, ExitReason, OpenTrade, PendingOrder, Side, SwingType

PLACE_ORDER = "PLACE_ORDER"
CANCEL_ORDER = "CANCEL_ORDER"
CLOSE_TRADE = "CLOSE_TRADE"
SIGNAL_REJECTED = "SIGNAL_REJECTED"
SESSION_EVENT = "SESSION_EVENT"


@dataclass
class Intent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    order: PendingOrder | None = None
    trade: OpenTrade | None = None


class Sizer(Protocol):
    def __call__(self, sl_distance: float) -> tuple[float, str]: ...


@dataclass
class StrategyConfigView:
    """Sottoinsieme di configurazione che serve all'engine."""

    name: str
    bias_window: int
    max_hold: int
    day_bars: int
    filters: Any
    tp_fallback_r: float = 1.5
    tp_min_r: float = 0.5
    tp_swing_mode: str = "last_before_entry"


class StrategyEngine:
    def __init__(
        self,
        cfg: StrategyConfigView,
        sessions: list[SessionSpec],
        client_order_id_factory: Callable[[str, datetime, Side], str],
    ) -> None:
        self.cfg = cfg
        self.sessions = sessions
        self._coid = client_order_id_factory
        self.bars: list[Bar] = []
        self.tracker = SwingTracker()
        self.session: SessionState | None = None
        self.pending: PendingOrder | None = None
        self.trade: OpenTrade | None = None
        self.last_exit_index: int = -1

    # --- ciclo principale ----------------------------------------------------

    def on_bar(self, bar: Bar, spread: float, sizer: Sizer) -> list[Intent]:
        """Processa una barra **chiusa** e restituisce le intenzioni operative."""
        if self.bars and bar.time <= self.bars[-1].time:
            return []
        self.bars.append(bar)
        i = len(self.bars) - 1
        intents: list[Intent] = []

        self.tracker.confirm(self.bars, i - 1)
        intents += self._manage_session(i)
        intents += self._manage_open_trade(i)
        intents += self._maybe_signal(i, spread, sizer)
        intents += self._expire_pending(i)
        return intents

    # --- sessione ------------------------------------------------------------

    def _manage_session(self, i: int) -> list[Intent]:
        intents: list[Intent] = []
        session = self.session
        if session is not None and session.expired(i):
            if self.trade is not None:
                intents.append(
                    Intent(
                        CLOSE_TRADE,
                        {"reason": ExitReason.SESSION_END.value},
                        trade=self.trade,
                    )
                )
            if self.pending is not None:
                intents.append(Intent(CANCEL_ORDER, {"reason": "session_end"}, order=self.pending))
                self.pending = None
            intents.append(
                Intent(SESSION_EVENT, {"kind": "session_closed", "session": session.spec.name})
            )
            self.session = None
            session = None

        bar_time = self.bars[i].time
        for spec in self.sessions:
            if spec.opens_on(bar_time) and session is None:
                self.session = SessionState(
                    spec=spec,
                    open_index=i,
                    day_bars=self.cfg.day_bars,
                    bias_window=self.cfg.bias_window,
                )
                intents.append(
                    Intent(
                        SESSION_EVENT,
                        {
                            "kind": "session_opened",
                            "session": spec.name,
                            "bar_time": bar_time.isoformat(),
                        },
                    )
                )
                session = self.session
                break

        if session is not None:
            session.resolve_reference_swings(self.tracker)
            before = session.bias
            bias = session.update_bias(self.bars, i)
            if bias is not None and before is None:
                intents.append(
                    Intent(
                        SESSION_EVENT,
                        {
                            "kind": "bias_confirmed",
                            "session": session.spec.name,
                            "bias": bias.value,
                            "sw_high": session.sw_high,
                            "sw_low": session.sw_low,
                            "bar_time": self.bars[i].time.isoformat(),
                        },
                    )
                )
            elif session.bias_failed and not session.closed:
                session.closed = True
                intents.append(
                    Intent(
                        SESSION_EVENT,
                        {"kind": "bias_not_confirmed", "session": session.spec.name},
                    )
                )
        return intents

    # --- trade aperto --------------------------------------------------------

    def _manage_open_trade(self, i: int) -> list[Intent]:
        trade = self.trade
        if trade is None:
            return []
        if i - trade.entry_bar_index >= self.cfg.max_hold:
            return [
                Intent(CLOSE_TRADE, {"reason": ExitReason.MAX_HOLD.value}, trade=trade)
            ]
        return []

    # --- nuovo segnale -------------------------------------------------------

    def _maybe_signal(self, i: int, spread: float, sizer: Sizer) -> list[Intent]:
        session = self.session
        if self.trade is not None or self.pending is not None or session is None:
            return []
        if session.bias is None or session.bias_confirm_index is None:
            return []
        if i <= session.bias_confirm_index or i <= self.last_exit_index:
            return []
        if i < 1:
            return []

        prev, cur = self.bars[i - 1], self.bars[i]
        bias = session.bias
        if not match_pattern(prev, cur, bias):
            return []

        trigger, stop_loss = trigger_and_stop(cur, bias)
        risk = stop_loss - trigger if bias is Side.SHORT else trigger - stop_loss
        if risk <= 0:
            return [
                Intent(
                    SIGNAL_REJECTED,
                    {"reason": "risk<=0", "bar_time": cur.time.isoformat()},
                )
            ]

        features = compute_features(prev, cur, risk, spread)
        rejections = self.cfg.filters.rejections(features)
        if rejections:
            return [
                Intent(
                    SIGNAL_REJECTED,
                    {
                        "reason": "filters",
                        "failed": rejections,
                        "bias": bias.value,
                        "spread": spread,
                        "risk": risk,
                        "bar_time": cur.time.isoformat(),
                        **features.as_dict(),
                    },
                )
            ]

        quantity, size_reason = sizer(risk)
        if quantity <= 0:
            return [
                Intent(
                    SIGNAL_REJECTED,
                    {
                        "reason": f"sizing:{size_reason}",
                        "bias": bias.value,
                        "risk": risk,
                        "bar_time": cur.time.isoformat(),
                    },
                )
            ]

        swing = self._tp_swing(bias, i)
        tp, tp_source = take_profit(
            entry=trigger,
            risk=risk,
            bias=bias,
            swing=swing,
            fallback_r=self.cfg.tp_fallback_r,
            min_r=self.cfg.tp_min_r,
        )
        order = PendingOrder(
            strategy=self.cfg.name,
            side=bias,
            trigger_price=trigger,
            stop_loss=stop_loss,
            take_profit=tp,
            risk=risk,
            quantity=quantity,
            client_order_id=self._coid(self.cfg.name, cur.time, bias),
            signal_bar_index=i,
            signal_bar_time=cur.time,
            expires_after_bar_index=i + 1,
            spread_at_signal=spread,
            features=features,
        )
        self.pending = order
        return [
            Intent(
                PLACE_ORDER,
                {"tp_source": tp_source, "size_reason": size_reason},
                order=order,
            )
        ]

    def _tp_swing(self, bias: Side, i: int):
        kind = SwingType.LOW if bias is Side.SHORT else SwingType.HIGH
        if self.cfg.tp_swing_mode == "first_after_entry":
            return self.tracker.first_of_type_after(kind, i)
        return self.tracker.last_of_type(kind, i + 1)

    # --- pending -------------------------------------------------------------

    def _expire_pending(self, i: int) -> list[Intent]:
        order = self.pending
        if order is None or i < order.expires_after_bar_index:
            return []
        self.pending = None
        self.last_exit_index = i
        return [Intent(CANCEL_ORDER, {"reason": "not_triggered_within_one_bar"}, order=order)]

    # --- notifiche dal runner ------------------------------------------------

    def on_fill(self, fill_price: float, position_id: str | None = None) -> OpenTrade:
        order = self.pending
        if order is None:
            raise RuntimeError("fill senza ordine pendente")
        self.pending = None
        self.trade = OpenTrade(
            strategy=order.strategy,
            side=order.side,
            quantity=order.quantity,
            entry_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            risk=order.risk,
            entry_bar_index=len(self.bars) - 1,
            entry_time=self.bars[-1].time if self.bars else order.signal_bar_time,
            client_order_id=order.client_order_id,
            theoretical_entry_price=order.trigger_price,
            position_id=position_id,
        )
        return self.trade

    def adopt_trade(self, trade: OpenTrade) -> OpenTrade:
        """Riprende in gestione un trade sopravvissuto a un riavvio del servizio.

        `entry_bar_index` viene riancorato alla barra dell'ingresso presente nel
        warmup, altrimenti `max_hold` ripartirebbe da zero a ogni riavvio.
        """
        index = len(self.bars) - 1
        for i, bar in enumerate(self.bars):
            if bar.time <= trade.entry_time:
                index = i
            else:
                break
        trade.entry_bar_index = index
        self.trade = trade
        self.pending = None
        return trade

    def on_trade_closed(self) -> None:
        self.trade = None
        self.last_exit_index = len(self.bars) - 1

    def on_order_cancelled(self) -> None:
        self.pending = None
