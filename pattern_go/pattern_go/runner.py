"""Servizio persistente Pattern GO: polling barre chiuse -> engine -> broker.

Proprieta' operative:

* decide **solo su barre chiuse**: la barra in formazione viene scartata;
* `client_order_id` deterministico (strategia + timestamp barra segnale), quindi un
  retry dopo un timeout non apre una seconda posizione;
* al riavvio rilegge posizioni e ordini dal broker e si riallinea prima di operare;
* kill switch a file, guard di drawdown Velotrade su ogni ciclo;
* riconnessione con backoff esponenziale gestita dal client.
"""

from __future__ import annotations

import json
import logging
import signal
import time as time_module
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config, StrategyConfig
from .dxtrade import DXTradeClient, Instrument, Quote
from .engine import (
    CANCEL_ORDER,
    CLOSE_TRADE,
    PLACE_ORDER,
    SESSION_EVENT,
    SIGNAL_REJECTED,
    Intent,
    StrategyConfigView,
    StrategyEngine,
)
from .journal import Journal
from .report import write_daily_report
from .risk import ALLOW, CLOSE_ALL, AccountState, RiskManager
from .types import ExitReason, Side

LOG = logging.getLogger("pattern_go.runner")

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}


def client_order_id(strategy: str, signal_time: datetime, side: Side) -> str:
    stamp = signal_time.astimezone(UTC).strftime("%Y%m%dT%H%M%S")
    return f"PG-{strategy}-{side.value[0]}-{stamp}"


class Runner:
    def __init__(self, cfg: Config, client: DXTradeClient | None = None) -> None:
        self.cfg = cfg
        self.journal = Journal(
            cfg.runtime.log_dir,
            max_bytes=cfg.runtime.log_max_bytes,
            backup_count=cfg.runtime.log_backup_count,
        )
        self.client = client or DXTradeClient(
            base_url=cfg.broker.base_url,
            username=cfg.broker.username,
            password=cfg.broker.password,
            account=cfg.broker.account,
            domain=cfg.broker.domain,
            timeout=cfg.broker.timeout,
            max_retries=cfg.broker.max_retries,
        )
        self.risk = RiskManager(cfg.risk)
        self.state = AccountState(
            equity=cfg.risk.initial_balance, balance=cfg.risk.initial_balance
        )
        self.engines: dict[str, StrategyEngine] = {}
        self.strategy_cfg: dict[str, StrategyConfig] = {}
        self.instrument: Instrument | None = None
        self._known_position_ids: set[str] = set()
        self._stop = False
        self._last_report_day = None

        for s in cfg.strategies:
            if not s.enabled:
                continue
            self.strategy_cfg[s.name] = s
            self.engines[s.name] = StrategyEngine(
                StrategyConfigView(
                    name=s.name,
                    bias_window=s.bias_window,
                    max_hold=s.max_hold,
                    day_bars=s.day_bars,
                    filters=s.filters,
                    tp_fallback_r=s.tp_fallback_r,
                    tp_min_r=s.tp_min_r,
                    tp_swing_mode=s.tp_swing_mode,
                ),
                sessions=cfg.sessions,
                client_order_id_factory=client_order_id,
            )

    # --- ciclo di vita -------------------------------------------------------

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: setattr(self, "_stop", True))

    def run(self) -> None:
        self.startup()
        while not self._stop:
            try:
                self.tick()
            except Exception:  # il servizio non deve morire su un errore isolato
                LOG.exception("errore nel ciclo, continuo")
                self.journal.write("ERROR", where="tick")
            time_module.sleep(self.cfg.runtime.poll_seconds)
        self.journal.write("SHUTDOWN")

    def startup(self) -> None:
        self.client.login()
        self.instrument = self.client.instrument(self.cfg.broker.symbol)
        metrics = self.client.metrics()
        self.state.equity = metrics.equity
        self.state.balance = metrics.balance
        self.state.open_positions = metrics.open_positions
        self._load_state()
        self.risk.roll_day(self.state, datetime.now(UTC))
        self.reconcile()
        self.warmup()
        self.journal.write(
            "STARTUP",
            symbol=self.instrument.symbol,
            quantity_increment=self.instrument.quantity_increment,
            equity=metrics.equity,
            balance=metrics.balance,
            static_floor=self.risk.static_floor,
            effective_floor=self.risk.effective_floor(self.state),
            reservoir=self.risk.reservoir(self.state),
            risk_amount=self.risk.risk_amount(self.state),
            strategies=sorted(self.engines),
        )

    def warmup(self) -> None:
        """Carica lo storico iniziale per ricostruire swing, sessioni e bias."""
        for name, engine in self.engines.items():
            tf = self.strategy_cfg[name].timeframe
            minutes = TIMEFRAME_MINUTES[tf]
            frm = datetime.now(UTC) - timedelta(
                minutes=minutes * self.cfg.runtime.warmup_bars
            )
            bars = self._closed_bars(tf, frm)
            spread = 0.0
            for bar in bars:
                # in warmup non si opera: lo spread reale non e' ricostruibile
                engine.on_bar(bar, spread, lambda _sl: (0.0, "warmup"))
            engine.pending = None
            self.journal.write("WARMUP", strategy=name, bars=len(bars))

    def reconcile(self) -> None:
        """Riallinea lo stato interno con posizioni e ordini realmente sul broker."""
        positions = self.client.positions()
        orders = self.client.orders()
        self._known_position_ids = {str(p.get("positionCode") or p.get("id")) for p in positions}
        self.journal.write(
            "RECONCILE",
            positions=len(positions),
            orders=len(orders),
            position_ids=sorted(self._known_position_ids),
            order_codes=[o.get("orderCode") for o in orders],
        )

    # --- ciclo -------------------------------------------------------------

    def tick(self) -> None:
        now = datetime.now(UTC)
        if self.risk.roll_day(self.state, now):
            self.journal.write(
                "DAY_ROLL",
                day=str(self.state.day_key),
                day_start_balance=self.state.day_start_balance,
                effective_floor=self.risk.effective_floor(self.state),
                allowance=self.risk.allowance(self.state),
            )
            self._emit_report(now)

        metrics = self.client.metrics()
        self.state.equity = metrics.equity
        self.state.balance = metrics.balance
        self.state.open_positions = metrics.open_positions

        if self.kill_switch_active():
            self.journal.write("KILL_SWITCH", closes=self.cfg.runtime.kill_switch_closes_positions)
            if self.cfg.runtime.kill_switch_closes_positions:
                self.close_everything(ExitReason.KILL_SWITCH)
            return

        decision, reason = self.risk.evaluate(self.state)
        if decision == CLOSE_ALL:
            self.journal.write(
                "RISK_GUARD",
                decision=decision,
                reason=reason,
                equity=self.state.equity,
                effective_floor=self.risk.effective_floor(self.state),
            )
            self.close_everything(ExitReason.RISK_GUARD)
            self.state.halted_until_reset = True
            return

        quote = self.client.quote(self.cfg.broker.symbol)
        for name, engine in self.engines.items():
            self._advance_strategy(name, engine, quote, allow_new=decision == ALLOW)

    def _advance_strategy(
        self, name: str, engine: StrategyEngine, quote: Quote, allow_new: bool
    ) -> None:
        tf = self.strategy_cfg[name].timeframe
        new_bars = self._new_closed_bars(engine, tf)
        if not new_bars:
            self._detect_fill(engine)
            return

        def sizer(sl_distance: float) -> tuple[float, str]:
            if not allow_new:
                return 0.0, "risk_blocked"
            return self.risk.quantity(self.state, sl_distance)

        for bar in new_bars:
            intents = engine.on_bar(bar, quote.spread, sizer)
            self._execute(engine, intents, quote)
        self._detect_fill(engine)

    def _execute(self, engine: StrategyEngine, intents: list[Intent], quote: Quote) -> None:
        for intent in intents:
            if intent.kind == SESSION_EVENT:
                self.journal.write("SESSION", strategy=engine.cfg.name, **intent.payload)
            elif intent.kind == SIGNAL_REJECTED:
                self.journal.write("SIGNAL_REJECTED", strategy=engine.cfg.name, **intent.payload)
            elif intent.kind == PLACE_ORDER and intent.order is not None:
                self._place(engine, intent, quote)
            elif intent.kind == CANCEL_ORDER and intent.order is not None:
                self._cancel(engine, intent)
            elif intent.kind == CLOSE_TRADE and intent.trade is not None:
                self._close(engine, intent.payload.get("reason", ExitReason.MANUAL.value))

    def _place(self, engine: StrategyEngine, intent: Intent, quote: Quote) -> None:
        order = intent.order
        assert order is not None
        side = "BUY" if order.side is Side.LONG else "SELL"
        try:
            resp = self.client.place_stop_order(
                symbol=self.cfg.broker.symbol,
                side=side,
                quantity=order.quantity,
                stop_price=order.trigger_price,
                client_order_id=order.client_order_id,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
        except Exception as exc:
            self.journal.order_event(
                "ORDER_REJECTED", order, error=str(exc), bid=quote.bid, ask=quote.ask
            )
            engine.on_order_cancelled()
            return
        order.broker_order_id = str(resp.get("orderId") or resp.get("orderCode") or "")
        self.journal.order_event(
            "ORDER_PLACED", order, bid=quote.bid, ask=quote.ask, **intent.payload
        )
        self._save_state()

    def _cancel(self, engine: StrategyEngine, intent: Intent) -> None:
        order = intent.order
        assert order is not None
        try:
            self.client.cancel_order(order.client_order_id)
            self.journal.order_event("ORDER_CANCELLED", order, **intent.payload)
        except Exception as exc:
            self.journal.order_event("ORDER_CANCEL_FAILED", order, error=str(exc))
        engine.on_order_cancelled()
        self._save_state()

    def _close(self, engine: StrategyEngine, reason: str) -> None:
        trade = engine.trade
        if trade is None:
            return
        quote = self.client.quote(self.cfg.broker.symbol)
        exit_price = quote.bid if trade.side is Side.LONG else quote.ask
        try:
            self.client.close_position(
                symbol=self.cfg.broker.symbol,
                side="BUY" if trade.side is Side.LONG else "SELL",
                quantity=trade.quantity,
                client_order_id=f"{trade.client_order_id}-X",
            )
        except Exception as exc:
            self.journal.write(
                "CLOSE_FAILED",
                strategy=trade.strategy,
                client_order_id=trade.client_order_id,
                error=str(exc),
            )
            return
        move = (
            exit_price - trade.entry_price
            if trade.side is Side.LONG
            else trade.entry_price - exit_price
        )
        self.journal.trade_closed(
            trade, exit_price=exit_price, reason=reason, pnl=move * trade.quantity
        )
        engine.on_trade_closed()
        self._save_state()

    def _detect_fill(self, engine: StrategyEngine) -> None:
        """Rileva l'esecuzione dello stop order confrontando le posizioni del broker."""
        order = engine.pending
        if order is None:
            return
        for position in self.client.positions():
            pid = str(position.get("positionCode") or position.get("id"))
            if pid in self._known_position_ids:
                continue
            fill_price = float(position.get("openPrice") or position.get("price") or 0.0)
            self._known_position_ids.add(pid)
            trade = engine.on_fill(fill_price or order.trigger_price, position_id=pid)
            self.journal.trade_opened(trade, order, position_id=pid)
            self._save_state()
            return

    # --- guard e utilita' ----------------------------------------------------

    def kill_switch_active(self) -> bool:
        return Path(self.cfg.runtime.kill_switch_file).exists()

    def close_everything(self, reason: ExitReason) -> None:
        for engine in self.engines.values():
            if engine.pending is not None:
                self._cancel(
                    engine, Intent(CANCEL_ORDER, {"reason": reason.value}, order=engine.pending)
                )
            if engine.trade is not None:
                self._close(engine, reason.value)

    def _closed_bars(self, timeframe: str, frm: datetime) -> list:
        minutes = TIMEFRAME_MINUTES[timeframe]
        bars = self.client.candles(self.cfg.broker.symbol, timeframe, frm)
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        return [b for b in bars if b.time <= cutoff]

    def _new_closed_bars(self, engine: StrategyEngine, timeframe: str) -> list:
        minutes = TIMEFRAME_MINUTES[timeframe]
        last = engine.bars[-1].time if engine.bars else None
        frm = (
            last + timedelta(minutes=minutes)
            if last is not None
            else datetime.now(UTC) - timedelta(minutes=minutes * 5)
        )
        return [b for b in self._closed_bars(timeframe, frm) if last is None or b.time > last]

    def _emit_report(self, now: datetime) -> None:
        day = (now - timedelta(days=1)).strftime("%Y%m%d")
        if self._last_report_day == day:
            return
        self._last_report_day = day
        try:
            path = write_daily_report(
                log_dir=self.cfg.runtime.log_dir,
                report_dir=self.cfg.runtime.report_dir,
                day=day,
                equity=self.state.equity,
                effective_floor=self.risk.effective_floor(self.state),
            )
            self.journal.write("DAILY_REPORT", path=str(path), day=day)
        except Exception as exc:
            self.journal.write("DAILY_REPORT_FAILED", day=day, error=str(exc))

    # --- stato su disco ------------------------------------------------------

    def _save_state(self) -> None:
        path = Path(self.cfg.runtime.state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "day_key": str(self.state.day_key) if self.state.day_key else None,
            "day_start_balance": self.state.day_start_balance,
            "halted_until_reset": self.state.halted_until_reset,
            "known_position_ids": sorted(self._known_position_ids),
            "strategies": {
                name: {
                    "pending": e.pending.client_order_id if e.pending else None,
                    "trade": e.trade.client_order_id if e.trade else None,
                }
                for name, e in self.engines.items()
            },
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        path = Path(self.cfg.runtime.state_file)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("day_key"):
            self.state.day_key = datetime.fromisoformat(data["day_key"]).date()
        self.state.day_start_balance = data.get("day_start_balance")
        self.state.halted_until_reset = bool(data.get("halted_until_reset", False))
        self._known_position_ids = set(data.get("known_position_ids") or [])
