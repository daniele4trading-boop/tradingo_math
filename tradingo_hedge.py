"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — HEDGE ENGINE  v2.0  (UltimaMarkets 10k)  — Phase 1             ║
║   - Apre trade ALLINEATO al segnale della Prop                               ║
║   - Trailing stop dopo chiusura Prop (Trend Riding)                          ║
║   - Hard stop su floor equity                                                ║
║   - NESSUN Reverse Hedge (rimosso in Phase 1)                                ║
║   - Signal timeout 120s                                                      ║
║   - SL sanity check + max 3 retry modify                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import MetaTrader5 as mt5
import pandas as np_unused
import numpy as np
import time, json, random, logging
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


def load_config_json(path="config.json") -> dict:
    p = Path(path)
    if not p.exists(): return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        def strip(d):
            return {k: strip(v) if isinstance(v, dict) else v
                    for k, v in d.items() if k != "_note"}
        return strip(raw)
    except: return {}


@dataclass
class HedgeConfig:
    terminal_path:      str   = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
    login:              int   = 843409
    password:           str   = "v!34bIbx"
    server:             str   = "UltimaMarkets-Demo"
    symbol:             str   = "XAUUSD"
    hedge_lot:          float = 0.14
    sl_atr_mult:        float = 1.5
    tp_atr_mult:        float = 3.0
    trailing_atr_mult:  float = 2.0
    hedge_floor_equity: float = 9_400.0
    jitter_min_ms:      int   = 300
    jitter_max_ms:      int   = 800
    loop_interval_sec:  float = 2.0
    signal_timeout_sec: float = 120.0
    state_file:         str   = "tradingo_state.json"
    magic_hedge:        int   = 20260002

    @classmethod
    def from_json(cls) -> "HedgeConfig":
        cfg = load_config_json()
        o   = cls()
        if not cfg: return o
        s  = cfg.get("sizing", {});  sl = cfg.get("sl_tp", {})
        r  = cfg.get("gestione_rischio", {}); si = cfg.get("sistema", {})
        o.hedge_lot         = float(s.get("hedge_lot", o.hedge_lot))
        o.sl_atr_mult       = float(sl.get("sl_atr_mult", o.sl_atr_mult))
        o.tp_atr_mult       = float(sl.get("tp_atr_mult", o.tp_atr_mult))
        o.trailing_atr_mult = float(r.get("trailing_atr_mult", o.trailing_atr_mult))
        o.hedge_floor_equity= float(r.get("hedge_floor_equity", o.hedge_floor_equity))
        o.loop_interval_sec = float(si.get("hedge_loop_interval_sec", o.loop_interval_sec))
        o.signal_timeout_sec= float(si.get("signal_timeout_sec", o.signal_timeout_sec))
        o.jitter_min_ms     = int(si.get("jitter_min_ms", o.jitter_min_ms))
        o.jitter_max_ms     = int(si.get("jitter_max_ms", o.jitter_max_ms))
        log.info(f"Config → lot={o.hedge_lot} SL={o.sl_atr_mult} TP={o.tp_atr_mult} trail={o.trailing_atr_mult} timeout={o.signal_timeout_sec}s")
        return o


class StateFile:
    def __init__(self, path):
        self.path = Path(path)
    def read(self) -> dict:
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except: return {}
    def update(self, **kw):
        d = self.read(); d.update(kw)
        d["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(d, indent=2), encoding="utf-8")


class HedgeEngine:
    def __init__(self, cfg: HedgeConfig):
        self.cfg   = cfg
        self.state = StateFile(cfg.state_file)
        self._ticket        = 0
        self._signal        = Signal.NONE
        self._last_signal_id= 0
        self._entry_price   = 0.0
        self._trend_riding  = False
        self._expected_loss = 0.0
        self._running       = False

    def _connect(self) -> bool:
        ok = mt5.initialize(path=self.cfg.terminal_path,login=self.cfg.login,
                            password=self.cfg.password,server=self.cfg.server)
        if not ok: log.error(f"Init fallito: {mt5.last_error()}"); return False
        info = mt5.account_info()
        if info is None: log.error("account_info None"); return False
        log.info(f"Connesso → {info.login} balance={info.balance:.2f} server={info.server}")
        return True

    def _reconnect(self) -> bool:
        mt5.shutdown(); time.sleep(5); return self._connect()

    def _jitter(self):
        time.sleep(random.randint(self.cfg.jitter_min_ms,self.cfg.jitter_max_ms)/1000.0)

    def _get_price(self) -> float:
        t = mt5.symbol_info_tick(self.cfg.symbol)
        return (t.bid+t.ask)/2.0 if (t and t.bid>100 and t.ask>100) else 0.0

    def _open_hedge(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return None
        if signal == Signal.BUY:
            ot=mt5.ORDER_TYPE_BUY; pr=tick.ask
            sl=pr-atr*self.cfg.sl_atr_mult; tp=pr+atr*self.cfg.tp_atr_mult
        else:
            ot=mt5.ORDER_TYPE_SELL; pr=tick.bid
            sl=pr+atr*self.cfg.sl_atr_mult; tp=pr-atr*self.cfg.tp_atr_mult
        self._jitter()
        r = mt5.order_send({"action":mt5.TRADE_ACTION_DEAL,"symbol":self.cfg.symbol,
                            "volume":self.cfg.hedge_lot,"type":ot,"price":pr,
                            "sl":sl,"tp":tp,"deviation":20,"magic":self.cfg.magic_hedge,
                            "comment":f"TG_HEDGE_{self.cfg.magic_hedge}",
                            "type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC})
        if r is None: log.error(f"order_send None: {mt5.last_error()}"); return None
        if r.retcode != mt5.TRADE_RETCODE_DONE: log.error(f"Rifiutato: {r.retcode} {r.comment}"); return None
        log.info(f"Hedge → ticket={r.order} {'BUY' if ot==mt5.ORDER_TYPE_BUY else 'SELL'} price={r.price:.2f} SL={sl:.2f} TP={tp:.2f}")
        self._entry_price = r.price
        return r.order

    def _close_position(self, ticket: int) -> bool:
        self._jitter()
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return False
        p=pos[0]; tick=mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return False
        ct = mt5.ORDER_TYPE_SELL if p.type==mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        pr = tick.bid if ct==mt5.ORDER_TYPE_SELL else tick.ask
        r = mt5.order_send({"action":mt5.TRADE_ACTION_DEAL,"symbol":self.cfg.symbol,
                            "volume":p.volume,"type":ct,"position":ticket,"price":pr,
                            "deviation":20,"magic":p.magic,
                            "type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC})
        if r and r.retcode==mt5.TRADE_RETCODE_DONE:
            log.info(f"Chiuso ticket={ticket}"); return True
        log.error(f"Chiusura fallita {ticket}: {mt5.last_error()}"); return False

    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        if new_sl < 100:
            log.warning(f"SL anomalo {new_sl:.2f} — ignorato"); return False
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return False
        p = pos[0]
        for _ in range(3):
            r = mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":ticket,
                                "symbol":self.cfg.symbol,"sl":new_sl,"tp":p.tp})
            if r and r.retcode==mt5.TRADE_RETCODE_DONE: return True
            time.sleep(0.5)
        log.warning(f"modify_sl fallito dopo 3 tentativi ticket={ticket}"); return False

    def _estimate_loss(self, atr: float) -> float:
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None: return 140.0
        return (atr*self.cfg.sl_atr_mult/sym.trade_tick_size)*sym.trade_tick_value*self.cfg.hedge_lot

    def _update_fields(self, equity, balance, pnl=0.0):
        mode = ("Trend Riding" if self._trend_riding else
                ("Normal Mode" if self._ticket>0 else "IDLE"))
        self.state.update(
            hedge_balance=balance, hedge_equity=equity,
            hedge_pnl_float=pnl, hedge_connected=True,
            hedge_ticket=self._ticket, reverse_ticket=0,
            reverse_active=False, trailing_active=self._trend_riding,
            hedge_expected_loss=self._expected_loss,
            floor_distance=equity-self.cfg.hedge_floor_equity,
            mode=mode,
        )

    def run(self):
        log.info("═══ HEDGE ENGINE v2.0 Phase 1 — AVVIO ═══")
        log.info(f"lot={self.cfg.hedge_lot} SL={self.cfg.sl_atr_mult}ATR TP={self.cfg.tp_atr_mult}ATR timeout={self.cfg.signal_timeout_sec}s")
        if not self._connect(): log.error("Connessione fallita."); return
        log.info("In attesa segnali Prop...")
        self._running = True

        while self._running:
            try:
                info = mt5.account_info()
                if info is None: self._reconnect(); continue
                equity=info.equity; balance=info.balance

                # Hard Stop
                if 0 < equity < self.cfg.hedge_floor_equity:
                    log.critical(f"HARD STOP! eq={equity:.2f} < floor={self.cfg.hedge_floor_equity:.2f}")
                    if self._ticket>0: self._close_position(self._ticket)
                    self._running=False; break

                state  = self.state.read()
                sig_str= state.get("signal","NONE")
                sig_id = int(state.get("signal_id",0))
                atr    = float(state.get("atr",10.0))
                price  = self._get_price()

                # Trade aperto
                if self._ticket > 0:
                    pos = mt5.positions_get(ticket=self._ticket)
                    if pos:
                        pnl = float(pos[0].profit)
                        prop_closed = state.get("prop_closed",False)

                        # Trend Riding: attiva trailing dopo chiusura Prop
                        if prop_closed and not self._trend_riding:
                            log.info("Prop chiusa → Trend Riding attivo")
                            self._trend_riding = True

                        if self._trend_riding and price > 100:
                            p = pos[0]
                            td = atr * self.cfg.trailing_atr_mult
                            if self._signal == Signal.BUY:
                                nsl = price - td
                                if nsl > 100 and nsl > p.sl:
                                    if self._modify_sl(self._ticket, nsl):
                                        log.info(f"Trailing SL → {nsl:.2f}")
                            else:
                                nsl = price + td
                                if nsl > 100 and (nsl < p.sl or p.sl==0):
                                    if self._modify_sl(self._ticket, nsl):
                                        log.info(f"Trailing SL → {nsl:.2f}")

                        self._update_fields(equity, balance, pnl)
                        log.info(f"Hedge → ticket={self._ticket} pnl={pnl:.2f} eq={equity:.2f} trend={'SÌ' if self._trend_riding else 'NO'}")
                    else:
                        log.info(f"Hedge chiuso ticket={self._ticket}")
                        self._ticket=0; self._signal=Signal.NONE
                        self._trend_riding=False; self._expected_loss=0.0
                        self._update_fields(equity, balance, 0.0)
                    time.sleep(self.cfg.loop_interval_sec); continue

                # Attesa segnale
                self._update_fields(equity, balance, 0.0)
                is_new = sig_str not in ("NONE","") and sig_id > self._last_signal_id
                if not is_new: time.sleep(self.cfg.loop_interval_sec); continue

                # Timeout check
                ts_str = state.get("timestamp","")
                if ts_str:
                    try:
                        ts  = datetime.fromisoformat(ts_str)
                        age = (datetime.now(timezone.utc)-ts).total_seconds()
                        if age > self.cfg.signal_timeout_sec:
                            log.warning(f"Segnale scaduto ({age:.0f}s) — ignoro")
                            self._last_signal_id=sig_id; time.sleep(self.cfg.loop_interval_sec); continue
                        log.info(f"Segnale fresco ({age:.0f}s)")
                    except: pass

                self._signal=Signal(sig_str); self._last_signal_id=sig_id
                log.info(f"Segnale {self._signal} id={sig_id} atr={atr:.2f}")

                ticket = self._open_hedge(self._signal, atr)
                if ticket:
                    self._ticket=ticket; self._trend_riding=False
                    self._expected_loss=self._estimate_loss(atr)
                    self._update_fields(equity, balance, 0.0)
                    log.info(f"Hedge in posizione ticket={ticket} exp_loss={self._expected_loss:.2f}$")
                else:
                    log.error("Apertura Hedge fallita")

                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                log.info("Stop."); self._running=False
            except Exception as e:
                log.error(f"Errore: {e}", exc_info=True)
                self._reconnect(); time.sleep(self.cfg.loop_interval_sec*2)

        log.info("Hedge Engine fermato."); mt5.shutdown()


if __name__ == "__main__":
    HedgeEngine(HedgeConfig.from_json()).run()
