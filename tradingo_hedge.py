"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — HEDGE ENGINE  (UltimaMarkets 10k)                               ║
║   Processo separato: si connette SOLO al terminale UltimaMarkets             ║
║   - Legge segnale da tradingo_state.json (scritto dalla Prop)                ║
║   - Apre trade in direzione ALLINEATA al segnale                             ║
║   - Gestisce Reverse Hedge e Trailing Stop                                   ║
║   - Monitora floor equity (hard stop a 9.400$)                               ║
║                                                                              ║
║   Avvio: python tradingo_hedge.py                                            ║
║   (in parallelo con tradingo_prop.py in altra finestra PowerShell)           ║
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

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("hedge.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("HEDGE")


# ──────────────────────────────────────────────────────────────────────────────
# ENUMERAZIONI
# ──────────────────────────────────────────────────────────────────────────────
class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class HedgeConfig:
    # ── Terminale UltimaMarkets ───────────────────────────────────────────────
    terminal_path: str = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
    login:         int = 843409
    password:      str = "v!34bIbx"
    server:        str = "UltimaMarkets-Demo"

    # ── Simbolo ──────────────────────────────────────────────────────────────
    symbol: str = "XAUUSD"

    # ── Sizing ───────────────────────────────────────────────────────────────
    hedge_lot:              float = 0.14
    reverse_lot_multiplier: float = 2.1   # lotto reverse = hedge_lot * multiplier

    # ── Soglie ───────────────────────────────────────────────────────────────
    hedge_floor_equity:    float = 9_400.0   # Hard stop: equity < floor → halt
    reverse_trigger_pct:   float = 0.50      # Attiva reverse quando perdita >= 50% attesa
    trailing_atr_mult:     float = 2.0       # Distanza trailing stop in ATR

    # ── Jitter stealth (ms) ───────────────────────────────────────────────────
    jitter_min_ms: int = 300
    jitter_max_ms: int = 800

    # ── Loop ──────────────────────────────────────────────────────────────────
    loop_interval_sec:  float = 2.0    # Hedge controlla più frequentemente
    signal_timeout_sec: float = 30.0   # Secondi max di attesa segnale prima di ignorarlo

    # ── File stato condiviso con Prop ─────────────────────────────────────────
    state_file: str = "tradingo_state.json"

    # ── Magic numbers ─────────────────────────────────────────────────────────
    magic_hedge:   int = 20260002
    magic_reverse: int = 20260003


# ──────────────────────────────────────────────────────────────────────────────
# STATE FILE READER
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

        self._ticket          = 0        # ticket hedge principale
        self._reverse_ticket  = 0        # ticket reverse hedge
        self._signal          = Signal.NONE
        self._last_signal_id  = 0        # per rilevare nuovi segnali dalla Prop
        self._entry_price     = 0.0      # prezzo entrata hedge
        self._reverse_entry   = 0.0      # prezzo entrata reverse
        self._expected_loss   = 0.0      # perdita max attesa sull'hedge
        self._trend_riding    = False    # True dopo chiusura Prop
        self._running         = False

    # ── Connessione ──────────────────────────────────────────────────────────
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

    # ── Jitter ───────────────────────────────────────────────────────────────
    def _jitter(self):
        time.sleep(random.randint(self.cfg.jitter_min_ms, self.cfg.jitter_max_ms) / 1000.0)

    # ── Lettura ATR dal file di stato ─────────────────────────────────────────
    def _get_atr_from_state(self) -> float:
        data = self.state.read()
        return float(data.get("atr", 10.0))

    # ── Apertura ordine Hedge (direzione ALLINEATA al segnale) ───────────────
    def _open_hedge(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        if signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * 1.5
            tp         = price + atr * 3.0
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * 1.5
            tp         = price - atr * 3.0

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
            f"Hedge trade aperto → ticket={result.order} | "
            f"{'BUY' if order_type==mt5.ORDER_TYPE_BUY else 'SELL'} | "
            f"price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        self._entry_price = result.price
        return result.order

    # ── Apertura Reverse Hedge ────────────────────────────────────────────────
    def _open_reverse(self, signal: Signal, atr: float) -> Optional[int]:
        """Direzione OPPOSTA al trade hedge originale."""
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        lot = round(self.cfg.hedge_lot * self.cfg.reverse_lot_multiplier, 2)

        if signal == Signal.BUY:
            # Hedge era BUY → Reverse fa SELL
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * 2.0
            tp         = price - atr * 2.0
        else:
            # Hedge era SELL → Reverse fa BUY
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * 2.0
            tp         = price + atr * 2.0

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
            f"Reverse Hedge aperto → ticket={result.order} | lot={lot} | "
            f"price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        self._reverse_entry = result.price
        return result.order

    # ── Chiusura posizione ────────────────────────────────────────────────────
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

        request = {
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
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.log.info(f"Posizione chiusa → ticket={ticket}")
            return True
        self.log.error(f"Chiusura fallita ticket={ticket}: {mt5.last_error()}")
        return False

    # ── Modifica SL (trailing) ────────────────────────────────────────────────
    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        result = mt5.order_send({
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol":   self.cfg.symbol,
            "sl":       new_sl,
            "tp":       pos.tp,
        })
        return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

    # ── Stima perdita attesa su hedge ─────────────────────────────────────────
    def _estimate_loss(self, atr: float) -> float:
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None:
            return 140.0
        sl_dist   = atr * 1.5
        sl_ticks  = sl_dist / sym.trade_tick_size
        return sl_ticks * sym.trade_tick_value * self.cfg.hedge_lot

    # ── Gestione trade aperti ─────────────────────────────────────────────────
    def _manage_open_trades(self, current_price: float, atr: float, hedge_pnl: float):
        """
        Chiamato ogni ciclo quando l'hedge è aperto.
        Gestisce: Reverse Hedge, Trailing Stop (Trend Riding), chiusura per break-even.
        """
        state_data = self.state.read()
        prop_closed = state_data.get("prop_closed", False)

        # ── Trend Riding: Prop ha chiuso → attiva trailing stop ──────────────
        if prop_closed and not self._trend_riding:
            self.log.info("Prop chiusa → attivo Trend Riding (trailing stop)")
            self._trend_riding = True

        if self._trend_riding and self._ticket > 0:
            positions = mt5.positions_get(ticket=self._ticket)
            if positions:
                pos        = positions[0]
                trail_dist = atr * self.cfg.trailing_atr_mult
                if self._signal == Signal.BUY:
                    new_sl = current_price - trail_dist
                    if new_sl > pos.sl:
                        if self._modify_sl(self._ticket, new_sl):
                            self.log.info(f"Trailing SL aggiornato → {new_sl:.2f}")
                else:
                    new_sl = current_price + trail_dist
                    if new_sl < pos.sl or pos.sl == 0:
                        if self._modify_sl(self._ticket, new_sl):
                            self.log.info(f"Trailing SL aggiornato → {new_sl:.2f}")

        # ── Reverse Hedge: attiva se perdita >= 50% attesa ───────────────────
        if (
            self._ticket > 0
            and self._reverse_ticket == 0
            and not self._trend_riding
            and self._expected_loss > 0
        ):
            loss_pct = abs(hedge_pnl) / self._expected_loss if hedge_pnl < 0 else 0.0
            if loss_pct >= self.cfg.reverse_trigger_pct:
                self.log.warning(
                    f"Reverse trigger! perdita={hedge_pnl:.2f} | "
                    f"attesa={self._expected_loss:.2f} | pct={loss_pct:.1%}"
                )
                rev_ticket = self._open_reverse(self._signal, atr)
                if rev_ticket:
                    self._reverse_ticket = rev_ticket

        # ── Reverse break-even: chiudi reverse se torna al prezzo di entrata ─
        if self._reverse_ticket > 0:
            rev_pos = mt5.positions_get(ticket=self._reverse_ticket)
            if rev_pos:
                rev_pnl = float(rev_pos[0].profit)
                if rev_pnl > 0 and abs(current_price - self._reverse_entry) <= 0.50:
                    self.log.info("Reverse a break-even → chiudo")
                    self._close_position(self._reverse_ticket)
                    self._reverse_ticket = 0
            else:
                # Chiuso autonomamente (SL/TP)
                self._reverse_ticket = 0

    # ── Loop principale ───────────────────────────────────────────────────────
    def run(self):
        self.log.info("═══ HEDGE ENGINE — AVVIO ═══")

        if not self._connect():
            self.log.error("Connessione fallita. Esco.")
            return

        self.log.info("In attesa di segnali dalla Prop...")
        self._running = True

        while self._running:
            try:
                # ── Dati account ──────────────────────────────────────────────
                info = mt5.account_info()
                if info is None:
                    self.log.warning("account_info None, riconnetto...")
                    self._reconnect()
                    continue

                equity  = info.equity
                balance = info.balance

                # ── Hard Stop ─────────────────────────────────────────────────
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

                # ── Leggi stato dalla Prop ────────────────────────────────────
                state_data  = self.state.read()
                signal_str  = state_data.get("signal", "NONE")
                signal_id   = int(state_data.get("signal_id", 0))
                atr         = float(state_data.get("atr", 10.0))
                tick        = mt5.symbol_info_tick(self.cfg.symbol)
                current_price = float(tick.last if tick else 0)

                # ── Helper scrittura campi hedge nel file condiviso ───────────
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

                # ── Gestione trade già aperto ─────────────────────────────────
                if self._ticket > 0:
                    pos = mt5.positions_get(ticket=self._ticket)
                    if pos:
                        hedge_pnl = float(pos[0].profit)
                        self._manage_open_trades(current_price, atr, hedge_pnl)
                        _update_hedge_fields(hedge_pnl)
                        self.log.info(
                            f"Hedge aperto → ticket={self._ticket} | "
                            f"pnl={hedge_pnl:.2f} | equity={equity:.2f} | "
                            f"reverse={'SÌ' if self._reverse_ticket>0 else 'NO'} | "
                            f"trend_riding={'SÌ' if self._trend_riding else 'NO'}"
                        )
                    else:
                        # Hedge chiuso (SL/TP)
                        self.log.info(f"Hedge chiuso → ticket={self._ticket}")
                        self._ticket        = 0
                        self._signal        = Signal.NONE
                        self._trend_riding  = False
                        self._expected_loss = 0.0
                        _update_hedge_fields(0.0)

                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # ── Nessun trade aperto — attendi nuovo segnale ───────────────
                _update_hedge_fields(0.0)

                # Nuovo segnale dalla Prop?
                is_new_signal = (
                    signal_str not in ("NONE", "")
                    and signal_id > self._last_signal_id
                )

                if not is_new_signal:
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # Verifica che il segnale non sia troppo vecchio
                ts_str = state_data.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        if age > self.cfg.signal_timeout_sec:
                            self.log.warning(f"Segnale scaduto ({age:.0f}s) — ignoro")
                            self._last_signal_id = signal_id
                            time.sleep(self.cfg.loop_interval_sec)
                            continue
                    except Exception:
                        pass

                # Apri trade Hedge (direzione allineata al segnale)
                self._signal         = Signal(signal_str)
                self._last_signal_id = signal_id

                self.log.info(
                    f"Nuovo segnale ricevuto: {self._signal} | "
                    f"signal_id={signal_id} | atr={atr:.2f}"
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


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg = HedgeConfig()
    engine = HedgeEngine(cfg)
    engine.run()
