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
from .types import ExitReason, OpenTrade, Side

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
        self._saved_trades: dict[str, dict[str, Any]] = {}
        self._close_counter: dict[str, int] = {}
        self._stop = False
        self._last_report_day = None
        self._last_heartbeat: datetime | None = None

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
        self.startup_with_retry()
        while not self._stop:
            try:
                self.tick()
            except Exception:  # il servizio non deve morire su un errore isolato
                LOG.exception("errore nel ciclo, continuo")
                self.journal.write("ERROR", where="tick")
            time_module.sleep(self.cfg.runtime.poll_seconds)
        self.journal.write("SHUTDOWN")

    def startup_with_retry(self) -> None:
        """Riprova lo startup finche' il broker non risponde, senza terminare.

        Un `503 no healthy upstream` del gateway Velotrade (tipico a mercato chiuso)
        faceva uscire il processo con exit code 1: il task pianificato non lo
        rimetteva in piedi e il servizio restava giu' fino a un intervento manuale.
        """
        delay = self.cfg.runtime.poll_seconds
        while not self._stop:
            try:
                self.startup()
                return
            except Exception as exc:
                LOG.warning("startup fallito (%s), riprovo tra %.0fs", exc, delay)
                self.journal.write("STARTUP_RETRY", error=str(exc), retry_in=delay)
                self._sleep(delay)
                delay = min(delay * 2, self.cfg.runtime.startup_retry_max_seconds)

    def _sleep(self, seconds: float) -> None:
        """Attesa interrompibile: un SIGTERM durante il backoff ferma il servizio."""
        deadline = time_module.monotonic() + seconds
        while not self._stop and time_module.monotonic() < deadline:
            time_module.sleep(min(1.0, deadline - time_module.monotonic()))

    def startup(self) -> None:
        self.client.login()
        self.instrument = self.client.instrument(self.cfg.broker.symbol)
        metrics = self.client.metrics()
        self.state.equity = metrics.equity
        self.state.balance = metrics.balance
        self.state.open_positions = metrics.open_positions
        self.state.margin_free = metrics.margin_free
        self._load_state()
        self.risk.roll_day(self.state, datetime.now(UTC))
        self.reconcile()
        self.warmup()
        self.resume_open_trades()
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

    def resume_open_trades(self) -> None:
        """Riprende la sorveglianza di SL/TP sulle posizioni aperte prima del riavvio.

        Senza questo passo un riavvio (o la morte del processo) lascia la posizione sul
        broker senza nessuno che ne controlli i livelli, dato che Velotrade non accetta
        SL/TP collegati all'ordine d'ingresso.
        """
        if not self.cfg.runtime.resume_open_trades:
            return
        positions = {
            str(p.get("positionCode") or p.get("id")): p
            for p in self.client.positions()
            if str(p.get("symbol") or p.get("instrument")) == self.cfg.broker.symbol
        }
        for name, engine in self.engines.items():
            saved = self._saved_trades.get(name)
            if saved is None or engine.trade is not None:
                continue
            position = positions.pop(str(saved.get("position_id")), None)
            if position is None:
                self.journal.write(
                    "TRADE_VANISHED",
                    strategy=name,
                    client_order_id=saved.get("client_order_id"),
                    position_id=saved.get("position_id"),
                )
                continue
            trade = engine.adopt_trade(self._trade_from_saved(name, saved, position))
            self._known_position_ids.add(str(trade.position_id))
            self.journal.write(
                "TRADE_RESUMED",
                strategy=name,
                client_order_id=trade.client_order_id,
                position_id=trade.position_id,
                side=trade.side.value,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                entry_time=trade.entry_time.isoformat(),
            )
        for code, position in positions.items():
            self.journal.write(
                "UNKNOWN_POSITION",
                position_id=code,
                side=position.get("side"),
                quantity=position.get("quantity"),
                closing=self.cfg.runtime.close_unknown_positions,
            )
            if self.cfg.runtime.close_unknown_positions:
                self._close_unknown(position)
        self._save_state()

    def _trade_from_saved(
        self, name: str, saved: dict[str, Any], position: dict[str, Any]
    ) -> OpenTrade:
        entry_price = float(saved["entry_price"])
        return OpenTrade(
            strategy=name,
            side=Side(saved["side"]),
            quantity=float(position.get("quantity") or saved["quantity"]),
            entry_price=entry_price,
            stop_loss=float(saved["stop_loss"]),
            take_profit=float(saved["take_profit"]),
            risk=float(saved["risk"]),
            entry_bar_index=0,
            entry_time=datetime.fromisoformat(saved["entry_time"]),
            client_order_id=str(saved["client_order_id"]),
            theoretical_entry_price=float(saved.get("theoretical_entry_price", entry_price)),
            position_id=str(saved.get("position_id") or "") or None,
        )

    def _close_unknown(self, position: dict[str, Any]) -> None:
        """Chiude a mercato una posizione che nessun engine sta sorvegliando."""
        code = str(position.get("positionCode") or position.get("id"))
        side = str(position.get("side") or "").upper()
        try:
            self.client.close_position(
                symbol=self.cfg.broker.symbol,
                side="BUY" if side == "BUY" else "SELL",
                quantity=float(position.get("quantity") or 0.0),
                client_order_id=f"PG-ORPHAN-{code}",
                position_code=code,
            )
            self.journal.write("UNKNOWN_POSITION_CLOSED", position_id=code)
        except Exception as exc:
            self.journal.write("CLOSE_FAILED", position_id=code, error=str(exc))

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
        self.state.margin_free = metrics.margin_free

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
        self._check_protective_exits(quote)
        for name, engine in self.engines.items():
            self._advance_strategy(name, engine, quote, allow_new=decision == ALLOW)
        self._heartbeat(now, quote, decision)

    def _heartbeat(self, now: datetime, quote: Quote, decision: str) -> None:
        """Traccia periodicamente che il ciclo gira.

        Senza, un servizio vivo ma fermo (nessuna barra nuova) e' indistinguibile da
        uno che semplicemente non trova setup: il journal resta vuoto in entrambi i casi.
        """
        every = self.cfg.runtime.heartbeat_seconds
        if every <= 0:
            return
        last = self._last_heartbeat
        if last is not None and (now - last).total_seconds() < every:
            return
        self._last_heartbeat = now
        self.journal.write(
            "HEARTBEAT",
            equity=self.state.equity,
            balance=self.state.balance,
            spread=round(quote.spread, 5),
            decision=decision,
            strategies={
                name: {
                    "last_bar": engine.bars[-1].time.isoformat() if engine.bars else None,
                    "session": engine.session.spec.name if engine.session else None,
                    "pending": engine.pending is not None,
                    "trade": engine.trade is not None,
                }
                for name, engine in self.engines.items()
            },
        )

    def _check_protective_exits(self, quote: Quote) -> None:
        """SL e TP sono gestiti qui, non dal broker.

        Velotrade rifiuta gli ordini di protezione collegati allo stop d'ingresso,
        quindi il livello viene sorvegliato a ogni ciclo e l'uscita e' a mercato: lo
        slippage sulle uscite e' quindi atteso piu' alto di quello del backtest.
        """
        for engine in self.engines.values():
            trade = engine.trade
            if trade is None:
                continue
            price = quote.bid if trade.side is Side.LONG else quote.ask
            if trade.side is Side.LONG:
                hit_sl, hit_tp = price <= trade.stop_loss, price >= trade.take_profit
            else:
                hit_sl, hit_tp = price >= trade.stop_loss, price <= trade.take_profit
            if hit_sl:
                self._close(engine, ExitReason.STOP_LOSS.value)
            elif hit_tp:
                self._close(engine, ExitReason.TAKE_PROFIT.value)

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
            return self.risk.quantity(self.state, sl_distance, price=quote.mid)

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
        position_code = trade.position_id or self._lookup_position_code(trade)
        if position_code is None:
            self.journal.write(
                "CLOSE_FAILED",
                strategy=trade.strategy,
                client_order_id=trade.client_order_id,
                error="positionCode sconosciuto: nessuna posizione corrispondente",
            )
            return
        try:
            self.client.close_position(
                symbol=self.cfg.broker.symbol,
                side="BUY" if trade.side is Side.LONG else "SELL",
                quantity=trade.quantity,
                client_order_id=f"{trade.client_order_id}-X-{self._close_attempts(trade)}",
                position_code=position_code,
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

    def _lookup_position_code(self, trade) -> str | None:
        """Recupera il codice posizione dal broker quando non e' noto (es. riavvio)."""
        for position in self.client.positions():
            if str(position.get("symbol") or position.get("instrument")) == self.cfg.broker.symbol:
                code = position.get("positionCode") or position.get("id")
                if code is not None:
                    return str(code)
        return None

    def _close_attempts(self, trade) -> int:
        """Il broker rifiuta orderCode duplicati: ogni tentativo ne usa uno nuovo."""
        key = trade.client_order_id
        self._close_counter[key] = self._close_counter.get(key, 0) + 1
        return self._close_counter[key]

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
        # `toTime` e' obbligatorio: senza, il broker risponde
        # `errorCode 32 Incorrect request parameters: <toTime> for event type Candle`
        now = datetime.now(UTC)
        minutes = TIMEFRAME_MINUTES[timeframe]
        bars = self.client.candles(self.cfg.broker.symbol, timeframe, frm, now)
        cutoff = now - timedelta(minutes=minutes)
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
                    "open_trade": _trade_to_dict(e.trade),
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
        self._saved_trades = {
            name: s["open_trade"]
            for name, s in (data.get("strategies") or {}).items()
            if isinstance(s, dict) and s.get("open_trade")
        }


def _trade_to_dict(trade: OpenTrade | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "side": trade.side.value,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "risk": trade.risk,
        "entry_time": trade.entry_time.isoformat(),
        "client_order_id": trade.client_order_id,
        "theoretical_entry_price": trade.theoretical_entry_price,
        "position_id": trade.position_id,
    }
