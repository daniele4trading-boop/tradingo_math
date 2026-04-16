"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — HEDGE ENGINE  (UltimaMarkets 10k)                               ║
║   v1.1 — Fix: signal_timeout 120s, tick.last→bid/ask, SL sanity check       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import json
import random
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from enum import Enum
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("hedge.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("HEDGE")


class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────────────────────────────────────
def load_config_json(path: str = "config.json") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        def strip_notes(d):
            return {k: strip_notes(v) if isinstance(v, dict) else v
                    for k, v in d.items() if k != "_note"}
        return strip_notes(raw)
    except Exception:
        return {}


@dataclass
class HedgeConfig:
    terminal_path: str = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
    login:         int = 843409
    password:      str = "v!34bIbx"
    server:        str = "UltimaMarkets-Demo"
    symbol:        str = "XAUUSD"

    hedge_lot:              float = 0.14
    reverse_lot_multiplier: float = 2.1
    sl_atr_mult:            float = 1.5
    tp_atr_mult:            float = 3.0
    reverse_sl_atr_mult:    float = 2.0
    reverse_tp_atr_mult:    float = 2.0

    hedge_floor_equity:  float = 9_400.0
    reverse_trigger_pct: float = 0.50
    trailing_atr_mult:   float = 2.0

    jitter_min_ms: int = 300
    jitter_max_ms: int = 800

    loop_interval_sec:  float = 2.0
    # FIX 3: timeout aumentato a 120 secondi
    signal_timeout_sec: float = 120.0

    state_file:    str = "tradingo_state.json"
    magic_hedge:   int = 20260002
    magic_reverse: int = 20260003

    @classmethod
    def from_json(cls) -> "HedgeConfig":
        cfg = load_config_json()
        obj = cls()
        if not cfg:
            return obj
        s   = cfg.get("sizing", {})
        sl  = cfg.get("sl_tp", {})
        r   = cfg.get("gestione_rischio", {})
        sis = cfg.get("sistema", {})

        obj.symbol               = cfg.get("symbol", obj.symbol)
        obj.hedge_lot            = float(s.get("hedge_lot", obj.hedge_lot))
        obj.reverse_lot_multiplier = float(s.get("reverse_lot_multiplier", obj.reverse_lot_multiplier))
        obj.sl_atr_mult          = float(sl.get("sl_atr_mult", obj.sl_atr_mult))
        obj.tp_atr_mult          = float(sl.get("tp_atr_mult", obj.tp_atr_mult))
        obj.reverse_sl_atr_mult  = float(sl.get("reverse_sl_atr_mult", obj.reverse_sl_atr_mult))
        obj.reverse_tp_atr_mult  = float(sl.get("reverse_tp_atr_mult", obj.reverse_tp_atr_mult))
        obj.hedge_floor_equity   = float(r.get("hedge_floor_equity", obj.hedge_floor_equity))
        obj.reverse_trigger_pct  = float(r.get("reverse_trigger_pct", obj.reverse_trigger_pct))
        obj.trailing_atr_mult    = float(r.get("trailing_atr_mult", obj.trailing_atr_mult))
        obj.loop_interval_sec    = float(sis.get("hedge_loop_interval_sec", obj.loop_interval_sec))
        obj.signal_timeout_sec   = float(sis.get("signal_timeout_sec", obj.signal_timeout_sec))
        obj.jitter_min_ms        = int(sis.get("jitter_min_ms", obj.jitter_min_ms))
        obj.jitter_max_ms        = int(sis.get("jitter_max_ms", obj.jitter_max_ms))

        log.info(
            f"Config → lot={obj.hedge_lot} | SL={obj.sl_atr_mult}ATR | "
            f"TP={obj.tp_atr_mult}ATR | timeout={obj.signal_timeout_sec}s"
        )
        return obj


# ──────────────────────────────────────────────────────────────────────────────
# STATE FILE
# ──────────────────────────────────────────────────────────────────────────────
class StateFile:
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def update(self, **kwargs):
        current = self.read()
        current.update(kwargs)
        current["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(current, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# HEDGE ENGINE
# ──────────────────────────────────────────────────────────────────────────────
class HedgeEngine:
    def __init__(self, cfg: HedgeConfig):
        self.cfg   = cfg
        self.state = StateFile(cfg.state_file)
        self.log   = logging.getLogger("HEDGE.Engine")

        self._ticket          = 0
        self._reverse_ticket  = 0
        self._signal          = Signal.NONE
        self._last_signal_id  = 0
        self._entry_price     = 0.0
        self._reverse_entry   = 0.0
        self._expected_loss   = 0.0
        self._trend_riding    = False
        self._running         = False

    def _connect(self) -> bool:
        ok = mt5.initialize(
            path=self.cfg.terminal_path,
            login=self.cfg.login,
            password=self.cfg.password,
            server=self.cfg.server,
        )
        if not ok:
            self.log.error(f"Initialize fallito: {mt5.last_error()}")
            return False
        info = mt5.account_info()
        if info is None:
            self.log.error("account_info() None")
            return False
        self.log.info(f"Connesso → Login:{info.login} | Balance:{info.balance:.2f} | Server:{info.server}")
        return True

    def _reconnect(self) -> bool:
        mt5.shutdown()
        time.sleep(5)
        return self._connect()

    def _jitter(self):
        time.sleep(random.randint(self.cfg.jitter_min_ms, self.cfg.jitter_max_ms) / 1000.0)

    def _get_current_price(self) -> float:
        """FIX: usa bid/ask invece di tick.last che può essere 0."""
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick and tick.bid > 100 and tick.ask > 100:
            return (tick.bid + tick.ask) / 2.0
        return 0.0

    def _open_hedge(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        if signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * self.cfg.sl_atr_mult
            tp         = price + atr * self.cfg.tp_atr_mult
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * self.cfg.sl_atr_mult
            tp         = price - atr * self.cfg.tp_atr_mult

        self._jitter()
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       self.cfg.hedge_lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        self.cfg.magic_hedge,
            "comment":      f"TG_HEDGE_{self.cfg.magic_hedge}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            self.log.error(f"order_send None: {mt5.last_error()}")
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log.error(f"Ordine rifiutato: retcode={result.retcode} | {result.comment}")
            return None

        self.log.info(
            f"Hedge aperto → ticket={result.order} | "
            f"{'BUY' if order_type==mt5.ORDER_TYPE_BUY else 'SELL'} | "
            f"price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        self._entry_price = result.price
        return result.order

    def _open_reverse(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        lot = round(self.cfg.hedge_lot * self.cfg.reverse_lot_multiplier, 2)

        if signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * self.cfg.reverse_sl_atr_mult
            tp         = price - atr * self.cfg.reverse_tp_atr_mult
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * self.cfg.reverse_sl_atr_mult
            tp         = price + atr * self.cfg.reverse_tp_atr_mult

        self._jitter()
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        self.cfg.magic_reverse,
            "comment":      f"TG_REVERSE_{self.cfg.magic_reverse}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            self.log.error(f"Reverse order_send None: {mt5.last_error()}")
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log.error(f"Reverse rifiutato: retcode={result.retcode} | {result.comment}")
            return None

        self.log.info(
            f"Reverse aperto → ticket={result.order} | lot={lot} | "
            f"price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        self._reverse_entry = result.price
        return result.order

    def _close_position(self, ticket: int) -> bool:
        self._jitter()
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos  = positions[0]
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return False

        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price      = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    20,
            "magic":        pos.magic,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.log.info(f"Posizione chiusa → ticket={ticket}")
            return True
        self.log.error(f"Chiusura fallita ticket={ticket}: {mt5.last_error()}")
        return False

    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        # FIX: sanity check SL + max 3 tentativi
        if new_sl < 100:
            self.log.warning(f"_modify_sl: SL anomalo {new_sl:.2f} — ignorato")
            return False
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        for _ in range(3):
            result = mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol":   self.cfg.symbol,
                "sl":       new_sl,
                "tp":       pos.tp,
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            time.sleep(0.5)
        self.log.warning(f"_modify_sl fallito dopo 3 tentativi ticket={ticket}")
        return False

    def _estimate_loss(self, atr: float) -> float:
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None:
            return 140.0
        sl_dist  = atr * self.cfg.sl_atr_mult
        sl_ticks = sl_dist / sym.trade_tick_size
        return sl_ticks * sym.trade_tick_value * self.cfg.hedge_lot

    def _manage_open_trades(self, current_price: float, atr: float, hedge_pnl: float):
        state_data  = self.state.read()
        prop_closed = state_data.get("prop_closed", False)

        if prop_closed and not self._trend_riding:
            self.log.info("Prop chiusa → Trend Riding attivo")
            self._trend_riding = True

        # Trailing stop (con sanity check)
        if self._trend_riding and self._ticket > 0 and current_price > 100:
            positions = mt5.positions_get(ticket=self._ticket)
            if positions:
                pos        = positions[0]
                trail_dist = atr * self.cfg.trailing_atr_mult
                if self._signal == Signal.BUY:
                    new_sl = current_price - trail_dist
                    if new_sl > 100 and new_sl > pos.sl:
                        if self._modify_sl(self._ticket, new_sl):
                            self.log.info(f"Trailing SL → {new_sl:.2f}")
                else:
                    new_sl = current_price + trail_dist
                    if new_sl > 100 and (new_sl < pos.sl or pos.sl == 0):
                        if self._modify_sl(self._ticket, new_sl):
                            self.log.info(f"Trailing SL → {new_sl:.2f}")

        # Reverse Hedge
        if (self._ticket > 0 and self._reverse_ticket == 0
                and not self._trend_riding and self._expected_loss > 0):
            loss_pct = abs(hedge_pnl) / self._expected_loss if hedge_pnl < 0 else 0.0
            if loss_pct >= self.cfg.reverse_trigger_pct:
                self.log.warning(
                    f"Reverse trigger! perdita={hedge_pnl:.2f} | "
                    f"attesa={self._expected_loss:.2f} | pct={loss_pct:.1%}"
                )
                rev = self._open_reverse(self._signal, atr)
                if rev:
                    self._reverse_ticket = rev

        # Reverse break-even
        if self._reverse_ticket > 0:
            rev_pos = mt5.positions_get(ticket=self._reverse_ticket)
            if rev_pos:
                rev_pnl = float(rev_pos[0].profit)
                if rev_pnl > 0 and abs(current_price - self._reverse_entry) <= 0.50:
                    self.log.info("Reverse a break-even → chiudo")
                    self._close_position(self._reverse_ticket)
                    self._reverse_ticket = 0
            else:
                self._reverse_ticket = 0

    def run(self):
        self.log.info("═══ HEDGE ENGINE v1.1 — AVVIO ═══")
        self.log.info(f"Signal timeout: {self.cfg.signal_timeout_sec}s")

        if not self._connect():
            self.log.error("Connessione fallita. Esco.")
            return

        self.log.info("In attesa di segnali dalla Prop...")
        self._running = True

        while self._running:
            try:
                info = mt5.account_info()
                if info is None:
                    self.log.warning("account_info None, riconnetto...")
                    self._reconnect()
                    continue

                equity  = info.equity
                balance = info.balance

                # Hard Stop
                if equity < self.cfg.hedge_floor_equity and equity > 0:
                    self.log.critical(
                        f"HARD STOP! equity={equity:.2f} < floor={self.cfg.hedge_floor_equity:.2f}"
                    )
                    if self._ticket > 0:
                        self._close_position(self._ticket)
                    if self._reverse_ticket > 0:
                        self._close_position(self._reverse_ticket)
                    self._running = False
                    break

                state_data = self.state.read()
                signal_str = state_data.get("signal", "NONE")
                signal_id  = int(state_data.get("signal_id", 0))
                atr        = float(state_data.get("atr", 10.0))
                current_price = self._get_current_price()

                def _update_hedge_fields(hedge_pnl: float = 0.0):
                    self.state.update(
                        hedge_balance=balance,
                        hedge_equity=equity,
                        hedge_pnl_float=hedge_pnl,
                        hedge_connected=True,
                        hedge_ticket=self._ticket,
                        reverse_ticket=self._reverse_ticket,
                        reverse_active=self._reverse_ticket > 0,
                        trailing_active=self._trend_riding,
                        hedge_expected_loss=self._expected_loss,
                        floor_distance=equity - self.cfg.hedge_floor_equity,
                        mode="Trend Riding" if self._trend_riding else
                             ("Mitigation" if self._reverse_ticket > 0 else
                              ("Normal Mode" if self._ticket > 0 else "IDLE")),
                    )

                # Gestione trade aperto
                if self._ticket > 0:
                    pos = mt5.positions_get(ticket=self._ticket)
                    if pos:
                        hedge_pnl = float(pos[0].profit)
                        self._manage_open_trades(current_price, atr, hedge_pnl)
                        _update_hedge_fields(hedge_pnl)
                        self.log.info(
                            f"Hedge → ticket={self._ticket} | pnl={hedge_pnl:.2f} | "
                            f"equity={equity:.2f} | reverse={'SÌ' if self._reverse_ticket>0 else 'NO'} | "
                            f"trend={'SÌ' if self._trend_riding else 'NO'}"
                        )
                    else:
                        self.log.info(f"Hedge chiuso → ticket={self._ticket}")
                        self._ticket        = 0
                        self._signal        = Signal.NONE
                        self._trend_riding  = False
                        self._expected_loss = 0.0
                        _update_hedge_fields(0.0)

                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # Attendi nuovo segnale
                _update_hedge_fields(0.0)

                is_new_signal = (
                    signal_str not in ("NONE", "")
                    and signal_id > self._last_signal_id
                )

                if not is_new_signal:
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # FIX 3: timeout 120 secondi
                ts_str = state_data.get("timestamp", "")
                if ts_str:
                    try:
                        ts  = datetime.fromisoformat(ts_str)
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        if age > self.cfg.signal_timeout_sec:
                            self.log.warning(f"Segnale scaduto ({age:.0f}s > {self.cfg.signal_timeout_sec:.0f}s) — ignoro")
                            self._last_signal_id = signal_id
                            time.sleep(self.cfg.loop_interval_sec)
                            continue
                        else:
                            self.log.info(f"Segnale fresco ({age:.0f}s) — procedo")
                    except Exception:
                        pass

                self._signal         = Signal(signal_str)
                self._last_signal_id = signal_id

                self.log.info(
                    f"Segnale {self._signal} | signal_id={signal_id} | atr={atr:.2f}"
                )

                ticket = self._open_hedge(self._signal, atr)

                if ticket:
                    self._ticket        = ticket
                    self._trend_riding  = False
                    self._expected_loss = self._estimate_loss(atr)
                    _update_hedge_fields(0.0)
                    self.log.info(
                        f"Hedge in posizione → ticket={ticket} | "
                        f"expected_loss={self._expected_loss:.2f}$"
                    )
                else:
                    self.log.error("Apertura Hedge fallita")

                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                self.log.info("Interruzione manuale. Esco.")
                self._running = False

            except Exception as e:
                self.log.error(f"Errore nel loop: {e}", exc_info=True)
                self._reconnect()
                time.sleep(self.cfg.loop_interval_sec * 2)

        self.log.info("Hedge Engine fermato.")
        mt5.shutdown()


if __name__ == "__main__":
    cfg = HedgeConfig.from_json()
    engine = HedgeEngine(cfg)
    engine.run()
