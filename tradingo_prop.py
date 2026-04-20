"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — PROP ENGINE  v2.1  (XM Demo / FTMO)  — Phase 1                 ║
║   - Apre trade OPPOSTO al segnale (Prop brucia by design)                    ║
║   - DD giornaliero max 3%: chiude trade e riprende domani                    ║
║   - Handshake atomico: prop apre SOLO dopo hedge_ready=True                  ║
║   - Cooldown dopo ogni chiusura trade                                        ║
║   - NESSUN Reverse Hedge (Phase 1)                                           ║
║   - Config da config.json                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time, json, random, logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("prop.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("PROP")


class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


def load_config_json(path="config.json") -> dict:
    p = Path(path)
    if not p.exists():
        log.warning("config.json non trovato — uso default")
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        def strip(d):
            return {k: strip(v) if isinstance(v, dict) else v
                    for k, v in d.items() if k != "_note"}
        return strip(raw)
    except Exception as e:
        log.error(f"Errore config.json: {e}")
        return {}


@dataclass
class PropConfig:
    terminal_path: str  = r"C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe"
    login:         int  = 1610077148
    password:      str  = "4h!R9TkJ"
    server:        str  = "STARTRADERFinancial-Demo"
    symbol:        str  = "XAUUSD"
    max_spread_points:        int   = 65
    atr_zscore_threshold:     float = 0.8
    prop_lot:                 float = 1.00
    sl_atr_mult:              float = 1.5
    tp_atr_mult:              float = 3.0
    timeframe:                int   = mt5.TIMEFRAME_M5
    atr_period:               int   = 14
    vwap_period:              int   = 20
    cvd_period:               int   = 10
    jitter_min_ms:            int   = 300
    jitter_max_ms:            int   = 800
    loop_interval_sec:        float = 10.0
    cooldown_after_trade_min: float = 30.0
    state_file:               str   = "tradingo_state.json"
    magic:                    int   = 20260001
    prop_cost_eur:            float = 0.0
    prop_initial_balance:     float = 100_000.0
    daily_dd_pct:             float = 0.03
    daily_dd_alert:           float = 0.027
    total_dd_safety:          float = 0.095
    handshake_timeout_sec:    float = 10.0

    @classmethod
    def from_json(cls) -> "PropConfig":
        cfg = load_config_json()
        o   = cls()
        if not cfg:
            return o
        f  = cfg.get("filtri", {});  s = cfg.get("sizing", {})
        sl = cfg.get("sl_tp", {});   i = cfg.get("indicatori", {})
        si = cfg.get("sistema", {}); ft= cfg.get("ftmo", {})
        o.max_spread_points        = int(f.get("max_spread_points", o.max_spread_points))
        o.atr_zscore_threshold     = float(f.get("atr_zscore_threshold", o.atr_zscore_threshold))
        o.prop_lot                 = float(s.get("prop_lot", o.prop_lot))
        o.sl_atr_mult              = float(sl.get("sl_atr_mult", o.sl_atr_mult))
        o.tp_atr_mult              = float(sl.get("tp_atr_mult", o.tp_atr_mult))
        o.atr_period               = int(i.get("atr_period", o.atr_period))
        o.vwap_period              = int(i.get("vwap_period", o.vwap_period))
        o.cvd_period               = int(i.get("cvd_period", o.cvd_period))
        o.loop_interval_sec        = float(si.get("prop_loop_interval_sec", o.loop_interval_sec))
        o.cooldown_after_trade_min = float(si.get("cooldown_after_sl_min", o.cooldown_after_trade_min))
        o.jitter_min_ms            = int(si.get("jitter_min_ms", o.jitter_min_ms))
        o.jitter_max_ms            = int(si.get("jitter_max_ms", o.jitter_max_ms))
        o.prop_initial_balance     = float(ft.get("prop_initial_balance", o.prop_initial_balance))
        o.daily_dd_pct             = float(ft.get("daily_dd_pct", o.daily_dd_pct))
        o.daily_dd_alert           = float(ft.get("daily_dd_alert", o.daily_dd_alert))
        o.total_dd_safety          = float(ft.get("total_dd_safety", o.total_dd_safety))
        o.prop_cost_eur            = float(ft.get("prop_cost_eur", o.prop_cost_eur))
        o.handshake_timeout_sec    = float(si.get("handshake_timeout_sec", o.handshake_timeout_sec))
        log.info(f"Config → spread={o.max_spread_points} zscore={o.atr_zscore_threshold} lot={o.prop_lot} SL={o.sl_atr_mult} TP={o.tp_atr_mult} cooldown={o.cooldown_after_trade_min}min")
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
        d = self.read(); d.update(kw); self.write(d)


class MarketAnalyzer:
    def __init__(self, cfg: PropConfig):
        self.cfg = cfg

    def get_rates(self, n=200) -> Optional[pd.DataFrame]:
        r = mt5.copy_rates_from_pos(self.cfg.symbol, self.cfg.timeframe, 0, n)
        if r is None or len(r) == 0: return None
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def get_spread_points(self) -> int:
        t = mt5.symbol_info_tick(self.cfg.symbol)
        s = mt5.symbol_info(self.cfg.symbol)
        if t is None or s is None: return 9999
        return int((t.ask - t.bid) / s.point)

    def compute_atr(self, df) -> pd.Series:
        h,l,c = df["high"],df["low"],df["close"]
        tr = pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
        return tr.rolling(self.cfg.atr_period).mean()

    def compute_atr_zscore(self, df) -> float:
        atr = self.compute_atr(df).dropna()
        if len(atr) < 50: return 0.0
        w = atr.iloc[-50:]; std = w.std()
        return float((atr.iloc[-1]-w.mean())/std) if std > 0 else 0.0

    def compute_vwap(self, df) -> float:
        sub = df.iloc[-self.cfg.vwap_period:].copy()
        tp  = (sub["high"]+sub["low"]+sub["close"])/3.0
        vol = sub["tick_volume"]
        v   = (vol>0)&(sub["close"]>100)
        if v.sum()==0: return float(df["close"].iloc[-1])
        return float((tp[v]*vol[v]).sum()/vol[v].sum())

    def compute_cvd(self, df) -> Tuple[float,str]:
        sub = df.iloc[-self.cfg.cvd_period:].copy()
        sub["tick_volume"] = sub["tick_volume"].astype(np.int64)
        sub["d"] = np.where(sub["close"]>sub["open"],sub["tick_volume"],-sub["tick_volume"])
        cvd = float(sub["d"].sum())
        return cvd, ("UP" if cvd>0 else ("DOWN" if cvd<0 else "NEUTRAL"))

    def generate_signal(self, df) -> Tuple[Signal,float,float,float,str]:
        z = self.compute_atr_zscore(df)
        vwap = self.compute_vwap(df)
        cvd,trend = self.compute_cvd(df)
        price = float(df["close"].iloc[-1])
        if z < self.cfg.atr_zscore_threshold: return Signal.NONE,z,vwap,cvd,trend
        if price > vwap and trend=="UP":   return Signal.BUY,z,vwap,cvd,trend
        if price < vwap and trend=="DOWN": return Signal.SELL,z,vwap,cvd,trend
        return Signal.NONE,z,vwap,cvd,trend


class DailyDDGuard:
    """
    Gestisce il DD giornaliero della prop.
    Logica brucia controllata:
      - Ogni giorno nuovo: salva balance midnight, resetta blocco
      - Se DD >= daily_dd_alert (2.7%): chiude trade e blocca per oggi
      - Se DD >= daily_dd_pct  (3.0%): hard stop (safety net)
      - Domani: riprende automaticamente
    """
    def __init__(self, cfg: PropConfig):
        self.cfg            = cfg
        self._midnight      = cfg.prop_initial_balance
        self._peak          = cfg.prop_initial_balance
        self._date          = ""
        self._day_halted    = False   # bloccato per oggi (DD raggiunto)
        self._halt_reason   = ""

    def daily_update(self, balance: float):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._date:
            self._day_halted  = False
            self._halt_reason = ""
            self._midnight    = balance
            self._peak        = max(self._peak, balance)
            self._date        = today
            log.info(f"Nuovo giorno → midnight={balance:.2f} peak={self._peak:.2f} — DD reset")

    def dd_pct(self, equity: float) -> float:
        if self._midnight <= 0: return 0.0
        return (self._midnight - equity) / self._midnight

    def should_close_now(self, equity: float) -> Tuple[bool, str]:
        """Ritorna (True, motivo) se il trade aperto va chiuso subito."""
        if self._day_halted:
            return True, self._halt_reason
        dd = self.dd_pct(equity)
        if dd >= self.cfg.daily_dd_pct:
            r = f"DAILY_DD_HARD eq={equity:.0f} dd={dd:.2%} >= {self.cfg.daily_dd_pct:.2%}"
            self._day_halted = True; self._halt_reason = r
            log.critical(f"⛔ {r}"); return True, r
        if dd >= self.cfg.daily_dd_alert:
            r = f"DAILY_DD_ALERT eq={equity:.0f} dd={dd:.2%} >= {self.cfg.daily_dd_alert:.2%}"
            self._day_halted = True; self._halt_reason = r
            log.warning(f"⚠ {r} — chiudo trade e blocco oggi"); return True, r
        if dd >= self.cfg.daily_dd_alert * 0.85:
            log.warning(f"⚠ DD vicino alla soglia: {dd:.2%}/{self.cfg.daily_dd_alert:.2%}")
        return False, "OK"

    def can_open(self, equity: float) -> Tuple[bool, str]:
        """Ritorna (True, 'OK') se si può aprire un nuovo trade."""
        if self._day_halted:
            return False, self._halt_reason
        dd = self.dd_pct(equity)
        if dd >= self.cfg.daily_dd_alert:
            return False, f"DD giornaliero raggiunto ({dd:.2%}) — attendo domani"
        tl = self._peak * (1.0 - self.cfg.total_dd_safety)
        if equity < tl:
            r = f"TOTAL_DD eq={equity:.0f}<{tl:.0f}"
            log.critical(f"⛔ {r}"); return False, r
        return True, "OK"


class PropEngine:
    def __init__(self, cfg: PropConfig):
        self.cfg      = cfg
        self.analyzer = MarketAnalyzer(cfg)
        self.dd       = DailyDDGuard(cfg)
        self.state    = StateFile(cfg.state_file)
        self._ticket         = 0
        self._signal_id      = 0
        self._running        = False
        self._last_close_time: Optional[datetime] = None

    def _connect(self) -> bool:
        ok = mt5.initialize(
            path=self.cfg.terminal_path,
            login=self.cfg.login,
            password=self.cfg.password,
            server=self.cfg.server,
            timeout=30000
        )
        if not ok: log.error(f"Init fallito: {mt5.last_error()}"); return False
        info = mt5.account_info()
        if info is None: log.error("account_info None"); return False
        if info.login != self.cfg.login:
            log.error(f"Conto errato: {info.login} invece di {self.cfg.login}")
            mt5.shutdown(); return False
        log.info(f"Connesso → {info.login} balance={info.balance:.2f} server={info.server}")
        return True

    def _reconnect(self) -> bool:
        mt5.shutdown(); time.sleep(5); return self._connect()

    def _jitter(self):
        time.sleep(random.randint(self.cfg.jitter_min_ms, self.cfg.jitter_max_ms)/1000.0)

    def _in_cooldown(self) -> Tuple[bool,float]:
        if self._last_close_time is None: return False, 0.0
        elapsed = (datetime.now(timezone.utc)-self._last_close_time).total_seconds()/60.0
        rem = self.cfg.cooldown_after_trade_min - elapsed
        return (rem>0, rem)

    def _force_close(self, ticket: int):
        pos = mt5.positions_get(ticket=ticket)
        if not pos: return
        p = pos[0]; tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return
        ct = mt5.ORDER_TYPE_SELL if p.type==mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        pr = tick.bid if ct==mt5.ORDER_TYPE_SELL else tick.ask
        mt5.order_send({"action":mt5.TRADE_ACTION_DEAL,"symbol":self.cfg.symbol,
                        "volume":p.volume,"type":ct,"position":ticket,"price":pr,
                        "deviation":20,"magic":p.magic,
                        "type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC})

    def _open_trade(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None: return None
        if signal == Signal.BUY:
            ot=mt5.ORDER_TYPE_SELL; pr=tick.bid
            sl=pr+atr*self.cfg.sl_atr_mult; tp=pr-atr*self.cfg.tp_atr_mult
        else:
            ot=mt5.ORDER_TYPE_BUY; pr=tick.ask
            sl=pr-atr*self.cfg.sl_atr_mult; tp=pr+atr*self.cfg.tp_atr_mult
        self._jitter()
        r = mt5.order_send({"action":mt5.TRADE_ACTION_DEAL,"symbol":self.cfg.symbol,
                            "volume":self.cfg.prop_lot,"type":ot,"price":pr,
                            "sl":sl,"tp":tp,"deviation":20,"magic":self.cfg.magic,
                            "type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC})
        if r is None: log.error(f"order_send None: {mt5.last_error()}"); return None
        if r.retcode != mt5.TRADE_RETCODE_DONE:
            log.error(f"Rifiutato: {r.retcode} {r.comment}"); return None
        log.info(f"Prop → ticket={r.order} {'SELL' if ot==mt5.ORDER_TYPE_SELL else 'BUY'} price={r.price:.2f} SL={sl:.2f} TP={tp:.2f}")
        return r.order

    def _is_open(self, ticket: int) -> bool:
        return bool(mt5.positions_get(ticket=ticket)) if ticket > 0 else False

    def _write_state(self, bal, eq, sp, sp_ok, z, vwap, cvd, cvd_t, sig, atr, can_open, block_reason, mode):
        m  = self.dd._midnight
        pk = self.dd._peak
        dd_pct = self.dd.dd_pct(eq)
        pnl = 0.0
        if self._ticket > 0:
            pos = mt5.positions_get(ticket=self._ticket)
            if pos: pnl = float(pos[0].profit)
        cur = self.state.read()
        self.state.write({
            "signal":sig,"signal_id":self._signal_id,"atr":atr,
            "prop_ticket":self._ticket,"prop_closed":cur.get("prop_closed",False),
            "hedge_ready":cur.get("hedge_ready",False),
            "last_signal":sig,"prop_balance":bal,"prop_equity":eq,
            "prop_pnl_float":pnl,"prop_connected":True,
            "hedge_balance":cur.get("hedge_balance",0.0),
            "hedge_equity":cur.get("hedge_equity",0.0),
            "hedge_pnl_float":cur.get("hedge_pnl_float",0.0),
            "hedge_connected":cur.get("hedge_connected",False),
            "hedge_ticket":cur.get("hedge_ticket",0),
            "reverse_ticket":0,"reverse_active":False,
            "trailing_active":cur.get("trailing_active",False),
            "hedge_realized_profit":cur.get("hedge_realized_profit",0.0),
            "hedge_expected_loss":cur.get("hedge_expected_loss",0.0),
            "net_system_profit":cur.get("hedge_realized_profit",0.0)-self.cfg.prop_cost_eur,
            "floor_distance":cur.get("hedge_equity",0.0)-9400.0,
            "spread_points":sp,"spread_ok":sp_ok,"atr_zscore":z,
            "vwap":vwap,"cvd":cvd,"cvd_trend":cvd_t,
            "mode":mode,"session_active":True,"session_name":"DEMO MODE","last_error":"",
            "daily_dd_pct":dd_pct,"daily_dd_midnight":m,
            "daily_dd_limit":self.cfg.daily_dd_alert,
            "daily_dd_halted":self.dd._day_halted,
            "prop_can_open":can_open,"prop_block_reason":block_reason,
        })

    def run(self):
        log.info("═══ PROP ENGINE v2.1 Phase 1 — AVVIO ═══")
        log.info(f"Login:{self.cfg.login} | Cooldown:{self.cfg.cooldown_after_trade_min}min | DD_alert:{self.cfg.daily_dd_alert:.1%} | Spread:{self.cfg.max_spread_points}pts")
        if not self._connect(): log.error("Connessione fallita."); return
        self._running = True
        sp,sp_ok = 0,True
        z,vwap,cvd,cvd_t = 0.0,0.0,0.0,"NEUTRAL"
        atr = 0.0

        while self._running:
            try:
                info = mt5.account_info()
                if info is None: self._reconnect(); continue
                bal = info.balance; eq = info.equity
                self.dd.daily_update(bal)

                df = self.analyzer.get_rates(200)
                if df is None: time.sleep(self.cfg.loop_interval_sec); continue

                sp    = self.analyzer.get_spread_points()
                sp_ok = sp <= self.cfg.max_spread_points
                atr   = float(self.analyzer.compute_atr(df).iloc[-1])
                z     = self.analyzer.compute_atr_zscore(df)
                vwap  = self.analyzer.compute_vwap(df)
                cvd,cvd_t = self.analyzer.compute_cvd(df)

                log.info(f"Ciclo → sp={sp}{'✓' if sp_ok else '✗'} Z={z:.2f} VWAP={vwap:.2f} CVD={cvd:.0f}[{cvd_t}] bal={bal:.2f} eq={eq:.2f}")

                # ── Trade aperto ──────────────────────────────────────────────
                if self._ticket > 0:
                    if self._is_open(self._ticket):
                        # Check DD: se supera soglia chiude subito
                        must_close, reason = self.dd.should_close_now(eq)
                        if must_close:
                            log.warning(f"DD raggiunto ({reason}) — chiudo trade prop")
                            self._force_close(self._ticket)
                            self._ticket = 0
                            self._last_close_time = datetime.now(timezone.utc)
                            cur = self.state.read()
                            cur["prop_closed"] = True; cur["hedge_ready"] = False
                            cur["mode"] = "DD_HALT"
                            self.state.write(cur)
                            self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,False,reason,"DD_HALT")
                        else:
                            self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,
                                              self.state.read().get("signal","NONE"),atr,True,"OK","Normal Mode")
                    else:
                        # Chiuso naturalmente (SL/TP)
                        log.info(f"Prop chiusa ticket={self._ticket}")
                        self._ticket = 0; self._last_close_time = datetime.now(timezone.utc)
                        log.info(f"⏳ Cooldown {self.cfg.cooldown_after_trade_min:.0f}min")
                        cur = self.state.read()
                        cur["prop_closed"] = True; cur["hedge_ready"] = False
                        cur["mode"] = "Trend Riding"
                        self.state.write(cur)
                        self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,True,"OK","Trend Riding")
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Cooldown ──────────────────────────────────────────────────
                in_cd,rem = self._in_cooldown()
                if in_cd:
                    log.info(f"⏳ Cooldown {rem:.1f}min rimanenti")
                    self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,False,"COOLDOWN","COOLDOWN")
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Can open? (DD giornaliero) ────────────────────────────────
                can_open, block_reason = self.dd.can_open(eq)
                if not can_open:
                    log.info(f"⛔ Apertura bloccata: {block_reason}")
                    self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,False,block_reason,"DD_HALT")
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Spread ────────────────────────────────────────────────────
                if not sp_ok:
                    self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,True,"OK","IDLE")
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Segnale ───────────────────────────────────────────────────
                signal,z,vwap,cvd,cvd_t = self.analyzer.generate_signal(df)
                if signal == Signal.NONE:
                    self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,"NONE",atr,True,"OK","IDLE")
                    time.sleep(self.cfg.loop_interval_sec); continue

                log.info(f"✦ Segnale {signal} Z={z:.2f} VWAP={vwap:.2f} CVD={cvd:.0f}")
                self._signal_id += 1

                # ── Handshake: scrivi segnale e aspetta hedge_ready ───────────
                cur = self.state.read()
                cur["signal"]      = signal.value
                cur["signal_id"]   = self._signal_id
                cur["prop_closed"] = False
                cur["hedge_ready"] = False
                self.state.write(cur)
                log.info(f"Handshake → segnale={signal.value} id={self._signal_id} — attendo hedge_ready (max {self.cfg.handshake_timeout_sec:.0f}s)")

                deadline = time.time() + self.cfg.handshake_timeout_sec
                hedge_confirmed = False
                while time.time() < deadline:
                    time.sleep(0.5)
                    st = self.state.read()
                    if st.get("hedge_ready", False):
                        hedge_confirmed = True
                        log.info("✅ Hedge confermato — apro trade prop")
                        break

                if not hedge_confirmed:
                    log.error(f"❌ Hedge non risponde entro {self.cfg.handshake_timeout_sec:.0f}s — annullo segnale")
                    cur = self.state.read()
                    cur["signal"] = "NONE"; cur["hedge_ready"] = False
                    self.state.write(cur)
                    time.sleep(self.cfg.loop_interval_sec); continue

                # ── Apri trade prop ───────────────────────────────────────────
                ticket = self._open_trade(signal, atr)
                if ticket:
                    self._ticket = ticket
                    cur = self.state.read()
                    cur["prop_ticket"] = ticket; cur["prop_closed"] = False
                    self.state.write(cur)
                    log.info(f"Prop in posizione ticket={ticket}")
                    self._write_state(bal,eq,sp,sp_ok,z,vwap,cvd,cvd_t,signal.value,atr,True,"OK","Normal Mode")
                else:
                    log.error("Apertura prop fallita — chiudo anche hedge")
                    cur = self.state.read()
                    cur["signal"] = "NONE"; cur["prop_abort"] = True
                    self.state.write(cur)

                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                log.info("Stop."); self._running=False
            except Exception as e:
                log.error(f"Errore: {e}", exc_info=True)
                self._reconnect(); time.sleep(self.cfg.loop_interval_sec*2)

        log.info("Prop Engine fermato."); mt5.shutdown()


if __name__ == "__main__":
    PropEngine(PropConfig.from_json()).run()
