"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — HEDGE ENGINE  v2.2  (UltimaMarkets 10k)  — Phase 1             ║
║   - Multi-trade: ogni trade vive indipendentemente                           ║
║   - Handshake atomico: apre trade e scrive hedge_ready=True                  ║
║   - Recovery avvio: se prop ha trade aperto, hedge si allinea subito         ║
║   - Trend Riding legato al signal_id della prop abbinata                     ║
║   - SL protettivo 20% profitto all'attivazione + trailing ATR                ║
║   - Hard stop su floor equity totale                                         ║
║   - NESSUN Reverse Hedge (Phase 1)                                           ║
║   - Signal timeout 120s                                                      ║
║   - SL sanity check + max 3 retry modify                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import MetaTrader5 as mt5
import numpy as np
import time, json, random, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
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
        log.info(f"Config → lot={o.hedge_lot} SL={o.sl_atr_mult} TP={o.tp_atr_mult} "
                 f"trail={o.trailing_atr_mult} timeout={o.signal_timeout_sec}s")
        return o


class StateFile:
    def __init__(self, path):
        self.path = Path(path)
    def read(self) -> dict:
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except: return {}
    def write(self, data: dict):
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    def update(self, **kw):
        d = self.read(); d.update(kw)
        self.write(d)


# ─── Struttura dati per un singolo trade hedge ────────────────────────────────
@dataclass
class HedgeTrade:
    ticket:        int
    signal:        Signal
    signal_id:     int
    entry_price:   float
    expected_loss: float
    trend_riding:  bool = False   # True dopo che la prop abbinata ha chiuso


class HedgeEngine:
    def __init__(self, cfg: HedgeConfig):
        self.cfg             = cfg
        self.state           = StateFile(cfg.state_file)
        self._trades: Dict[int, HedgeTrade] = {}   # ticket → HedgeTrade
        self._last_signal_id = 0
        self._running        = False
        # Fase 2
        self._fase2_attiva    = False
        self._fase2_caso      = ""     # "A"=hedge vince, "B"=prop vince
        self._fase2_peak_pnl  = 0.0   # picco PNL del vincente
        self._fase2_floor_pnl = 0.0   # floor = picco - trailing

    # ── Connessione ───────────────────────────────────────────────────────────

    def _connect(self) -> bool:
        ok = mt5.initialize(path=self.cfg.terminal_path, login=self.cfg.login,
                            password=self.cfg.password, server=self.cfg.server)
        if not ok: log.error(f"Init fallito: {mt5.last_error()}"); return False
        info = mt5.account_info()
        if info is None: log.error("account_info None"); return False
        log.info(f"Connesso → {info.login} balance={info.balance:.2f} server={info.server}")
        return True

    def _reconnect(self) -> bool:
        mt5.shutdown(); time.sleep(5); return self._connect()

    def _jitter(self):
        time.sleep(random.randint(self.cfg.jitter_min_ms, self.cfg.jitter_max_ms) / 1000.0)

    def _get_price(self) -> float:
        t = mt5.symbol_info_tick(self.cfg.symbol)
        return (t.bid + t.ask) / 2.0 if (t and t.bid > 100 and t.ask > 100) else 0.0

    # ── Operazioni MT5 ────────────────────────────────────────────────────────

    def _open_hedge(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return None
        if signal == Signal.BUY:
            ot = mt5.ORDER_TYPE_BUY;  pr = tick.ask
            sl = pr - atr * self.cfg.sl_atr_mult
            tp = pr + atr * self.cfg.tp_atr_mult
        else:
            ot = mt5.ORDER_TYPE_SELL; pr = tick.bid
            sl = pr + atr * self.cfg.sl_atr_mult
            tp = pr - atr * self.cfg.tp_atr_mult
        self._jitter()
        r = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       self.cfg.hedge_lot,
            "type":         ot,
            "price":        pr,
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        self.cfg.magic_hedge,
            "comment":      f"TG_HEDGE_{self.cfg.magic_hedge}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if r is None:
            log.error(f"order_send None: {mt5.last_error()}"); return None
        if r.retcode != mt5.TRADE_RETCODE_DONE:
            log.error(f"Rifiutato: {r.retcode} {r.comment}"); return None
        log.info(f"Hedge aperto → ticket={r.order} "
                 f"{'BUY' if ot == mt5.ORDER_TYPE_BUY else 'SELL'} "
                 f"price={r.price:.2f} SL={sl:.2f} TP={tp:.2f}")
        return r.order

    def _close_position(self, ticket: int) -> bool:
        self._jitter()
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return False
        p    = pos[0]
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return False
        ct = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        pr = tick.bid if ct == mt5.ORDER_TYPE_SELL else tick.ask
        r  = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       p.volume,
            "type":         ct,
            "position":     ticket,
            "price":        pr,
            "deviation":    20,
            "magic":        p.magic,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"Chiuso ticket={ticket}"); return True
        log.error(f"Chiusura fallita {ticket}: {mt5.last_error()}"); return False

    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        if new_sl < 100:
            log.warning(f"SL anomalo {new_sl:.2f} — ignorato"); return False
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return False
        p = pos[0]
        for _ in range(3):
            r = mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol":   self.cfg.symbol,
                "sl":       new_sl,
                "tp":       p.tp,
            })
            if r and r.retcode == mt5.TRADE_RETCODE_DONE: return True
            time.sleep(0.5)
        log.warning(f"modify_sl fallito dopo 3 tentativi ticket={ticket}"); return False

    def _estimate_loss(self, atr: float) -> float:
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None: return 140.0
        return (atr * self.cfg.sl_atr_mult / sym.trade_tick_size) * sym.trade_tick_value * self.cfg.hedge_lot

    # ── Fase 2: costanti ──────────────────────────────────────────────────────
    FASE2_ATR_TRIGGER    = 0.8   # trigger: prezzo si muove 0.8×ATR a favore del vincente
    FASE2_RSI_MIN        = 40.0  # RSI allineato >= 40
    FASE2_MOM10_MIN      = 2.0   # momentum 10 barre >= 2.0 punti
    FASE2_TRAIL_HEDGE    = 1.5   # trailing hedge vincente: 1.5×ATR
    FASE2_TRAIL_PROP     = 1.0   # trailing prop vincente:  1.0×ATR
    FASE2_BUFFER_LOSS    = 30    # punti buffer per congelare il perdente

    def _calc_rsi_mom(self, rates) -> tuple:
        """Calcola RSI14 e Momentum10 dai rates M5. Ritorna (rsi, mom10)."""
        if rates is None or len(rates) < 15:
            return 50.0, 0.0
        closes = [r[4] for r in rates]  # close = indice 4
        import numpy as np
        c = np.array(closes)
        delta = np.diff(c)
        gain  = np.where(delta > 0, delta, 0.0)
        loss  = np.where(delta < 0, -delta, 0.0)
        period = 14
        if len(gain) < period:
            return 50.0, 0.0
        avg_g = gain[-period:].mean()
        avg_l = loss[-period:].mean()
        rsi   = 100.0 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))
        mom10 = float(c[-1] - c[-11]) if len(c) >= 11 else 0.0
        return float(rsi), mom10

    def _check_fase2_trigger(self, state: dict, price: float, atr: float, rates) -> tuple:
        """
        Controlla se la Fase 2 va attivata.
        Ritorna (attiva: bool, caso: str, reason: str)
        caso='A': hedge vince, prop perde
        caso='B': prop vince, hedge perde
        """
        if state.get("fase2_attiva", False):
            return False, "", "già_attiva"

        prop_entry = float(state.get("prop_entry_price", 0))
        prop_sl    = float(state.get("prop_sl_price", 0))
        prop_sig   = state.get("signal", "NONE")
        if prop_entry == 0 or prop_sl == 0 or prop_sig == "NONE":
            return False, "", "dati_prop_mancanti"

        # Movimento a favore di uno dei due trade >= 0.8×ATR
        # Se prop=BUY (hedge=SELL): prezzo scende → hedge guadagna (caso A)
        # Se prop=SELL (hedge=BUY): prezzo sale → hedge guadagna (caso A)
        if prop_sig == "BUY":
            move_hedge = prop_entry - price   # positivo se prezzo scende (hedge SELL guadagna)
            move_prop  = price - prop_entry   # positivo se prezzo sale (prop BUY guadagna)
        else:
            move_hedge = price - prop_entry   # positivo se prezzo sale (hedge BUY guadagna)
            move_prop  = prop_entry - price   # positivo se prezzo scende (prop SELL guadagna)

        caso = ""
        if move_hedge >= atr * self.FASE2_ATR_TRIGGER:
            caso = "A"   # hedge vince
        elif move_prop >= atr * self.FASE2_ATR_TRIGGER:
            caso = "B"   # prop vince
        else:
            return False, "", f"movimento insufficiente hedge={move_hedge:.2f} prop={move_prop:.2f} soglia={atr*self.FASE2_ATR_TRIGGER:.2f}"

        # Filtri RSI e momentum
        rsi, mom10 = self._calc_rsi_mom(rates)
        if caso == "A":
            # hedge vince → allinea RSI alla dir hedge
            rsi_aln  = (100 - rsi) if prop_sig == "BUY" else rsi
            mom_aln  = -mom10 if prop_sig == "BUY" else mom10
        else:
            # prop vince → allinea RSI alla dir prop
            rsi_aln  = rsi if prop_sig == "BUY" else (100 - rsi)
            mom_aln  = mom10 if prop_sig == "BUY" else -mom10

        if rsi_aln < self.FASE2_RSI_MIN:
            return False, "", f"rsi_aln={rsi_aln:.1f}<{self.FASE2_RSI_MIN}"
        if mom_aln < self.FASE2_MOM10_MIN:
            return False, "", f"mom10_aln={mom_aln:.2f}<{self.FASE2_MOM10_MIN}"

        reason = (f"FASE2-{caso} OK: move={move_hedge if caso=='A' else move_prop:.2f} "
                  f"rsi_aln={rsi_aln:.1f} mom10_aln={mom_aln:.2f}")
        return True, caso, reason

    # ── State file ────────────────────────────────────────────────────────────

    def _update_state(self, equity: float, balance: float):
        open_trades  = list(self._trades.values())
        riding       = [t.ticket for t in open_trades if t.trend_riding]
        paired       = [t.ticket for t in open_trades if not t.trend_riding]
        mode = "IDLE"
        if riding and paired: mode = f"Mixed ({len(riding)} riding + {len(paired)} paired)"
        elif riding:          mode = f"Trend Riding ({len(riding)} trade)"
        elif paired:          mode = f"Normal Mode ({len(paired)} trade)"
        self.state.update(
            hedge_balance=balance,
            hedge_equity=equity,
            hedge_connected=True,
            hedge_ticket=paired[0] if paired else (riding[0] if riding else 0),
            hedge_open_tickets=list(self._trades.keys()),
            hedge_riding_tickets=riding,
            hedge_paired_tickets=paired,
            trailing_active=bool(riding),
            mode=mode,
        )

    # ── Gestione di un singolo trade nel loop ─────────────────────────────────

    def _manage_trade(self, ht: HedgeTrade, state: dict, price: float, atr: float) -> bool:
        """
        Gestisce un singolo trade aperto.
        Ritorna False se il trade è stato chiuso (SL/TP hit), True se ancora aperto.
        """
        pos = mt5.positions_get(ticket=ht.ticket)
        if not pos:
            log.info(f"Trade chiuso ticket={ht.ticket} sig_id={ht.signal_id} "
                     f"({'Trend Riding' if ht.trend_riding else 'Normal'})")
            return False

        p   = pos[0]
        pnl = float(p.profit)

        # ── Attivazione Trend Riding ──────────────────────────────────────────
        if not ht.trend_riding:
            prop_closed  = state.get("prop_closed", False)
            state_sig_id = int(state.get("signal_id", 0))
            if prop_closed and state_sig_id == ht.signal_id and ht.signal_id > 0:
                log.info(f"Prop chiusa (sig_id={ht.signal_id}) → "
                         f"Trend Riding attivo su ticket={ht.ticket} pnl={pnl:.2f}$")
                ht.trend_riding = True

                # SL protettivo: prezzo corrente con buffer 20% del profitto
                if pnl > 0 and price > 100:
                    sym = mt5.symbol_info(self.cfg.symbol)
                    if sym:
                        tick_val   = sym.trade_tick_value * self.cfg.hedge_lot
                        buffer_pts = (pnl * 0.20 / tick_val) * sym.trade_tick_size if tick_val > 0 else 0
                        if ht.signal == Signal.BUY:
                            protective_sl = price - buffer_pts
                        else:
                            protective_sl = price + buffer_pts
                        if self._modify_sl(ht.ticket, protective_sl):
                            log.info(f"SL protettivo @ {protective_sl:.2f} "
                                     f"(pnl={pnl:.2f}$ buffer={pnl*0.20:.2f}$) ticket={ht.ticket}")

        # ── Trailing stop (solo se Trend Riding attivo) ───────────────────────
        if ht.trend_riding and price > 100:
            td = atr * self.cfg.trailing_atr_mult
            if ht.signal == Signal.BUY:
                nsl = price - td
                if nsl > 100 and nsl > p.sl:
                    if self._modify_sl(ht.ticket, nsl):
                        log.info(f"Trailing SL → {nsl:.2f} ticket={ht.ticket}")
            else:
                nsl = price + td
                if nsl > 100 and (nsl < p.sl or p.sl == 0):
                    if self._modify_sl(ht.ticket, nsl):
                        log.info(f"Trailing SL → {nsl:.2f} ticket={ht.ticket}")

        log.info(f"Hedge ticket={ht.ticket} sig_id={ht.signal_id} "
                 f"pnl={pnl:.2f} {'[RIDING]' if ht.trend_riding else '[paired]'}")
        return True

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        log.info("═══ HEDGE ENGINE v2.2 Phase 1 — AVVIO ═══")
        log.info(f"lot={self.cfg.hedge_lot} SL={self.cfg.sl_atr_mult}ATR "
                 f"TP={self.cfg.tp_atr_mult}ATR trail={self.cfg.trailing_atr_mult}ATR "
                 f"timeout={self.cfg.signal_timeout_sec}s")
        if not self._connect():
            log.error("Connessione fallita."); return
        self._running = True

        # ── RECOVERY AVVIO ────────────────────────────────────────────────────
        try:
            st           = self.state.read()
            prop_ticket  = int(st.get("prop_ticket", 0))
            sig_str_boot = st.get("signal", "NONE")
            sig_id_boot  = int(st.get("signal_id", 0))
            atr_boot     = float(st.get("atr", 10.0))
            prop_closed  = st.get("prop_closed", False)

            # Recupera trade hedge già aperti su MT5 con il nostro magic
            existing = mt5.positions_get(symbol=self.cfg.symbol) or []
            for p in existing:
                if p.magic == self.cfg.magic_hedge:
                    ht = HedgeTrade(
                        ticket        = p.ticket,
                        signal        = Signal.BUY if p.type == mt5.ORDER_TYPE_BUY else Signal.SELL,
                        signal_id     = sig_id_boot,
                        entry_price   = p.price_open,
                        expected_loss = self._estimate_loss(atr_boot),
                        trend_riding  = prop_closed,
                    )
                    self._trades[p.ticket] = ht
                    self._last_signal_id   = max(self._last_signal_id, sig_id_boot)
                    log.info(f"RECOVERY: recuperato ticket={p.ticket} "
                             f"signal={ht.signal.value} "
                             f"riding={'SÌ' if ht.trend_riding else 'NO'}")

            # Se prop ha trade aperto ma nessun hedge accoppiato esiste
            if prop_ticket > 0 and sig_str_boot not in ("NONE", "") and not prop_closed:
                paired_exists = any(
                    not t.trend_riding and t.signal_id == sig_id_boot
                    for t in self._trades.values()
                )
                if not paired_exists:
                    log.warning(f"RECOVERY: prop trade aperto (ticket={prop_ticket}) "
                                f"senza hedge accoppiato — apro allineato")
                    sig_boot = Signal(sig_str_boot)
                    ticket   = self._open_hedge(sig_boot, atr_boot)
                    if ticket:
                        pos_info  = mt5.positions_get(ticket=ticket)
                        entry_pr  = pos_info[0].price_open if pos_info else 0.0
                        ht = HedgeTrade(
                            ticket        = ticket,
                            signal        = sig_boot,
                            signal_id     = sig_id_boot,
                            entry_price   = entry_pr,
                            expected_loss = self._estimate_loss(atr_boot),
                        )
                        self._trades[ticket] = ht
                        self._last_signal_id = max(self._last_signal_id, sig_id_boot)
                        cur = self.state.read()
                        cur["hedge_ready"]  = True
                        cur["hedge_ticket"] = ticket
                        self.state.write(cur)
                        log.info(f"RECOVERY OK → hedge ticket={ticket} sig_id={sig_id_boot}")
                    else:
                        log.error("RECOVERY fallito: impossibile aprire hedge allineato")

        except Exception as e:
            log.error(f"Errore recovery avvio: {e}", exc_info=True)
        # ─────────────────────────────────────────────────────────────────────

        log.info(f"Trade attivi dopo recovery: {list(self._trades.keys()) or 'nessuno'}")
        log.info("In ascolto segnali Prop...")

        while self._running:
            try:
                info = mt5.account_info()
                if info is None: self._reconnect(); continue
                equity  = info.equity
                balance = info.balance

                # Hard Stop su equity totale
                if 0 < equity < self.cfg.hedge_floor_equity:
                    log.critical(f"HARD STOP! eq={equity:.2f} < floor={self.cfg.hedge_floor_equity:.2f}")
                    for ticket in list(self._trades.keys()):
                        self._close_position(ticket)
                    self._trades.clear()
                    self._running = False; break

                state = self.state.read()
                atr   = float(state.get("atr", 10.0))
                price = self._get_price()

                # ── Gestione tutti i trade attivi (ognuno indipendente) ───────
                for ticket in list(self._trades.keys()):
                    alive = self._manage_trade(self._trades[ticket], state, price, atr)
                    if not alive:
                        del self._trades[ticket]

                # ── FASE 2: check trigger e gestione ─────────────────────────
                if self._trades and not self._fase2_attiva:
                    rates = mt5.copy_rates_from_pos(self.cfg.symbol, mt5.TIMEFRAME_M5, 0, 30)
                    attiva, caso, reason = self._check_fase2_trigger(state, price, atr, rates)
                    if attiva:
                        self._fase2_attiva = True
                        self._fase2_caso   = caso
                        log.info(f"[FASE2] {reason}")

                        tick_info = mt5.symbol_info_tick(self.cfg.symbol)
                        spread_pts = int((tick_info.ask - tick_info.bid) / 0.01) if tick_info else 30
                        buffer_loss = self.FASE2_BUFFER_LOSS + spread_pts * 0.01

                        if caso == "A":
                            # Hedge vince → trailing 1.5×ATR; prop perde → congela
                            for ticket, ht in self._trades.items():
                                if not ht.trend_riding:
                                    pos = mt5.positions_get(ticket=ticket)
                                    if pos:
                                        pnl = float(pos[0].profit)
                                        self._fase2_peak_pnl  = pnl
                                        trail_dist = atr * self.FASE2_TRAIL_HEDGE
                                        self._fase2_floor_pnl = pnl - trail_dist * self.cfg.hedge_lot * 10
                                        log.info(f"[FASE2-A] Hedge VINCE pnl={pnl:.2f}$ "
                                                 f"floor={self._fase2_floor_pnl:.2f}$")
                            # Scrivi sul JSON per la prop (congela SL)
                            cur = self.state.read()
                            cur["fase2_attiva"]        = True
                            cur["fase2_caso"]          = "A"
                            cur["fase2_prop_sl_locked"] = False
                            self.state.write(cur)

                        else:  # caso B: prop vince, hedge perde
                            for ticket, ht in self._trades.items():
                                if not ht.trend_riding:
                                    pos = mt5.positions_get(ticket=ticket)
                                    if pos:
                                        p = pos[0]
                                        # Congela SL hedge al prezzo + buffer
                                        if ht.signal.value == "BUY":
                                            nsl = price - buffer_loss
                                        else:
                                            nsl = price + buffer_loss
                                        self._modify_sl(ticket, nsl)
                                        log.info(f"[FASE2-B] Hedge PERDE → SL congelato a {nsl:.2f}")
                            cur = self.state.read()
                            cur["fase2_attiva"]        = True
                            cur["fase2_caso"]          = "B"
                            cur["fase2_prop_sl_locked"] = False
                            self.state.write(cur)

                    else:
                        if self._trades:
                            log.info(f"[FASE2] no trigger: {reason}")

                elif self._fase2_attiva and self._trades:
                    # ── Fase 2 attiva: gestione vincente ─────────────────────
                    rates = mt5.copy_rates_from_pos(self.cfg.symbol, mt5.TIMEFRAME_M5, 0, 30)
                    tick_info = mt5.symbol_info_tick(self.cfg.symbol)
                    spread_pts = int((tick_info.ask - tick_info.bid) / 0.01) if tick_info else 30
                    buffer_loss = self.FASE2_BUFFER_LOSS + spread_pts * 0.01

                    if self._fase2_caso == "A":
                        # Hedge vince: aggiorna trailing 1.5×ATR
                        for ticket, ht in self._trades.items():
                            if not ht.trend_riding:
                                pos = mt5.positions_get(ticket=ticket)
                                if pos:
                                    pnl = float(pos[0].profit)
                                    if pnl > self._fase2_peak_pnl:
                                        self._fase2_peak_pnl  = pnl
                                        trail_dist = atr * self.FASE2_TRAIL_HEDGE
                                        self._fase2_floor_pnl = pnl - trail_dist * self.cfg.hedge_lot * 10
                                        log.info(f"[FASE2-A] Nuovo picco hedge={pnl:.2f}$ "
                                                 f"floor={self._fase2_floor_pnl:.2f}$")
                                    elif pnl < self._fase2_floor_pnl:
                                        log.warning(f"[FASE2-A] PNL {pnl:.2f}$ < floor "
                                                    f"{self._fase2_floor_pnl:.2f}$ → CHIUDO HEDGE")
                                        self._close_position(ticket)
                                        self._fase2_attiva = False
                                        cur = self.state.read()
                                        cur["fase2_attiva"] = False
                                        self.state.write(cur)

                    else:  # caso B: prop vince, hedge perde (congelato)
                        # Hedge già congelato — non fare nulla, la prop gestisce il trailing
                        # Controlla solo che il trade hedge esista ancora
                        for ticket in list(self._trades.keys()):
                            pos = mt5.positions_get(ticket=ticket)
                            if not pos:
                                self._fase2_attiva = False
                                cur = self.state.read()
                                cur["fase2_attiva"] = False
                                self.state.write(cur)

                elif not self._trades and self._fase2_attiva:
                    # Tutti i trade chiusi → reset Fase 2
                    self._fase2_attiva    = False
                    self._fase2_caso      = ""
                    self._fase2_peak_pnl  = 0.0
                    self._fase2_floor_pnl = 0.0
                    cur = self.state.read()
                    cur["fase2_attiva"]        = False
                    cur["fase2_caso"]          = ""
                    cur["fase2_prop_sl_locked"] = False
                    self.state.write(cur)
                    log.info("[FASE2] Reset — nessun trade attivo")

                # ── Check abort da prop ───────────────────────────────────────
                if state.get("prop_abort", False):
                    # Chiudi solo il trade accoppiato più recente (non i riding)
                    paired = [(t, ht) for t, ht in self._trades.items() if not ht.trend_riding]
                    if paired:
                        newest = max(paired, key=lambda x: x[1].signal_id)[0]
                        log.warning(f"Prop abort → chiudo hedge accoppiato ticket={newest}")
                        self._close_position(newest)
                        if newest in self._trades:
                            del self._trades[newest]
                    cur = self.state.read()
                    cur["prop_abort"] = False; cur["hedge_ready"] = False
                    self.state.write(cur)
                    self._update_state(equity, balance)
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Aggiorna state file ───────────────────────────────────────
                self._update_state(equity, balance)

                # ── Nuovo segnale? ────────────────────────────────────────────
                sig_str = state.get("signal", "NONE")
                sig_id  = int(state.get("signal_id", 0))
                is_new  = sig_str not in ("NONE", "") and sig_id > self._last_signal_id
                if not is_new:
                    time.sleep(self.cfg.loop_interval_sec); continue

                # Timeout check
                ts_str = state.get("timestamp", "")
                if ts_str:
                    try:
                        ts  = datetime.fromisoformat(ts_str)
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        if age > self.cfg.signal_timeout_sec:
                            log.warning(f"Segnale scaduto ({age:.0f}s) — ignoro sig_id={sig_id}")
                            self._last_signal_id = sig_id
                            time.sleep(self.cfg.loop_interval_sec); continue
                        log.info(f"Segnale fresco ({age:.0f}s)")
                    except:
                        pass

                signal = Signal(sig_str)
                log.info(f"Nuovo segnale {signal} id={sig_id} atr={atr:.2f} "
                         f"— apro hedge (trade attivi: {len(self._trades)})")

                # Apri nuovo trade hedge
                ticket = self._open_hedge(signal, atr)
                if ticket:
                    pos_info = mt5.positions_get(ticket=ticket)
                    entry_pr = pos_info[0].price_open if pos_info else 0.0
                    ht = HedgeTrade(
                        ticket        = ticket,
                        signal        = signal,
                        signal_id     = sig_id,
                        entry_price   = entry_pr,
                        expected_loss = self._estimate_loss(atr),
                    )
                    self._trades[ticket] = ht
                    self._last_signal_id = sig_id

                    # HANDSHAKE: scrivi hedge_ready=True → sblocca prop
                    cur = self.state.read()
                    cur["hedge_ready"]  = True
                    cur["hedge_ticket"] = ticket
                    self.state.write(cur)

                    self._update_state(equity, balance)
                    log.info(f"✅ Hedge in posizione ticket={ticket} sig_id={sig_id} "
                             f"hedge_ready=True | trade attivi totali: {len(self._trades)}")
                else:
                    log.error(f"Apertura hedge fallita sig_id={sig_id} "
                              f"— hedge_ready rimane False, prop non aprirà")
                    self._last_signal_id = sig_id

                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                log.info("Stop."); self._running = False
            except Exception as e:
                log.error(f"Errore: {e}", exc_info=True)
                self._reconnect(); time.sleep(self.cfg.loop_interval_sec * 2)

        log.info("Hedge Engine fermato."); mt5.shutdown()


if __name__ == "__main__":
    HedgeEngine(HedgeConfig.from_json()).run()
