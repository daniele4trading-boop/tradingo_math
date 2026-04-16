"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — PROP ENGINE  (FTMO 100k)                                        ║
║   v1.1 — Fix: FTMO DD hard stop, cooldown post-SL, config.json              ║
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


# ──────────────────────────────────────────────────────────────────────────────
# CARICAMENTO CONFIG ESTERNO
# ──────────────────────────────────────────────────────────────────────────────
def load_config_json(path: str = "config.json") -> dict:
    p = Path(path)
    if not p.exists():
        log.warning(f"config.json non trovato — uso valori default")
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        def strip_notes(d):
            return {k: strip_notes(v) if isinstance(v, dict) else v
                    for k, v in d.items() if k != "_note"}
        cfg = strip_notes(raw)
        log.info(f"config.json caricato")
        return cfg
    except Exception as e:
        log.error(f"Errore config.json: {e} — uso default")
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class PropConfig:
    terminal_path: str = r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
    login:         int = 1513126769
    password:      str = "!!ftn3*?T4@"
    server:        str = "FTMO-Demo"
    symbol:        str = "XAUUSD"

    max_spread_points:    int   = 65
    atr_zscore_threshold: float = 0.8

    prop_lot:    float = 1.00
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0

    timeframe:   int = mt5.TIMEFRAME_M5
    atr_period:  int = 14
    vwap_period: int = 20
    cvd_period:  int = 10

    jitter_min_ms: int = 300
    jitter_max_ms: int = 800

    loop_interval_sec: float = 10.0

    # ── FIX: cooldown post-SL ─────────────────────────────────────────────────
    cooldown_after_sl_min: float = 30.0   # minuti di pausa dopo uno SL

    state_file: str = "tradingo_state.json"
    magic:      int = 20260001

    prop_cost_eur:        float = 680.0
    prop_initial_balance: float = 100_000.0
    daily_dd_safety:      float = 0.027
    total_dd_safety:      float = 0.095

    @classmethod
    def from_json(cls) -> "PropConfig":
        cfg = load_config_json()
        obj = cls()
        if not cfg:
            return obj
        f   = cfg.get("filtri", {})
        s   = cfg.get("sizing", {})
        sl  = cfg.get("sl_tp", {})
        i   = cfg.get("indicatori", {})
        sis = cfg.get("sistema", {})
        ft  = cfg.get("ftmo", {})

        obj.symbol               = cfg.get("symbol", obj.symbol)
        obj.max_spread_points    = int(f.get("max_spread_points", obj.max_spread_points))
        obj.atr_zscore_threshold = float(f.get("atr_zscore_threshold", obj.atr_zscore_threshold))
        obj.prop_lot             = float(s.get("prop_lot", obj.prop_lot))
        obj.sl_atr_mult          = float(sl.get("sl_atr_mult", obj.sl_atr_mult))
        obj.tp_atr_mult          = float(sl.get("tp_atr_mult", obj.tp_atr_mult))
        obj.atr_period           = int(i.get("atr_period", obj.atr_period))
        obj.vwap_period          = int(i.get("vwap_period", obj.vwap_period))
        obj.cvd_period           = int(i.get("cvd_period", obj.cvd_period))
        obj.loop_interval_sec    = float(sis.get("prop_loop_interval_sec", obj.loop_interval_sec))
        obj.cooldown_after_sl_min = float(sis.get("cooldown_after_sl_min", obj.cooldown_after_sl_min))
        obj.jitter_min_ms        = int(sis.get("jitter_min_ms", obj.jitter_min_ms))
        obj.jitter_max_ms        = int(sis.get("jitter_max_ms", obj.jitter_max_ms))
        obj.prop_cost_eur        = float(ft.get("prop_cost_eur", obj.prop_cost_eur))
        obj.prop_initial_balance = float(ft.get("prop_initial_balance", obj.prop_initial_balance))
        obj.daily_dd_safety      = float(ft.get("daily_dd_safety", obj.daily_dd_safety))
        obj.total_dd_safety      = float(ft.get("total_dd_safety", obj.total_dd_safety))

        log.info(
            f"Config → spread={obj.max_spread_points}pts | zscore={obj.atr_zscore_threshold} | "
            f"lot={obj.prop_lot} | SL={obj.sl_atr_mult}ATR | TP={obj.tp_atr_mult}ATR | "
            f"cooldown={obj.cooldown_after_sl_min}min"
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

    def write(self, data: dict):
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def update(self, **kwargs):
        current = self.read()
        current.update(kwargs)
        self.write(current)


# ──────────────────────────────────────────────────────────────────────────────
# MARKET ANALYZER
# ──────────────────────────────────────────────────────────────────────────────
class MarketAnalyzer:
    def __init__(self, cfg: PropConfig):
        self.cfg = cfg
        self.log = logging.getLogger("PROP.Analyzer")

    def get_rates(self, n: int = 200) -> Optional[pd.DataFrame]:
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, self.cfg.timeframe, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def get_spread_points(self) -> int:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        sym  = mt5.symbol_info(self.cfg.symbol)
        if tick is None or sym is None:
            return 9999
        return int((tick.ask - tick.bid) / sym.point)

    def compute_atr(self, df: pd.DataFrame) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        return tr.rolling(self.cfg.atr_period).mean()

    def compute_atr_zscore(self, df: pd.DataFrame) -> float:
        atr = self.compute_atr(df).dropna()
        if len(atr) < 50:
            return 0.0
        w = atr.iloc[-50:]
        std = w.std()
        if std == 0:
            return 0.0
        return float((atr.iloc[-1] - w.mean()) / std)

    def compute_vwap(self, df: pd.DataFrame) -> float:
        sub = df.iloc[-self.cfg.vwap_period:].copy()
        tp  = (sub["high"] + sub["low"] + sub["close"]) / 3.0
        vol = sub["tick_volume"]
        valid = (vol > 0) & (sub["close"] > 100)
        if valid.sum() == 0:
            return float(df["close"].iloc[-1])
        return float((tp[valid] * vol[valid]).sum() / vol[valid].sum())

    def compute_cvd(self, df: pd.DataFrame) -> Tuple[float, str]:
        sub = df.iloc[-self.cfg.cvd_period:].copy()
        sub["tick_volume"] = sub["tick_volume"].astype(np.int64)
        sub["delta"] = np.where(sub["close"] > sub["open"], sub["tick_volume"], -sub["tick_volume"])
        cvd = float(sub["delta"].sum())
        trend = "UP" if cvd > 0 else ("DOWN" if cvd < 0 else "NEUTRAL")
        return cvd, trend

    def generate_signal(self, df: pd.DataFrame) -> Tuple[Signal, float, float, float, str]:
        z    = self.compute_atr_zscore(df)
        vwap = self.compute_vwap(df)
        cvd, trend = self.compute_cvd(df)
        price = float(df["close"].iloc[-1])

        if z < self.cfg.atr_zscore_threshold:
            return Signal.NONE, z, vwap, cvd, trend

        if price > vwap and trend == "UP":
            return Signal.BUY, z, vwap, cvd, trend
        elif price < vwap and trend == "DOWN":
            return Signal.SELL, z, vwap, cvd, trend

        return Signal.NONE, z, vwap, cvd, trend


# ──────────────────────────────────────────────────────────────────────────────
# FTMO RISK MANAGER — FIX: controllo equity ad ogni ciclo + hard stop immediato
# ──────────────────────────────────────────────────────────────────────────────
class FTMORisk:
    def __init__(self, cfg: PropConfig):
        self.cfg = cfg
        self.log = logging.getLogger("PROP.FTMO")
        self._midnight_balance = cfg.prop_initial_balance
        self._peak_balance     = cfg.prop_initial_balance
        self._last_date        = ""
        self._halted           = False   # FIX: flag blocco permanente giornaliero
        self._halt_reason      = ""

    def daily_update(self, balance: float):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_date:
            # Nuovo giorno: reset halt flag e aggiorna balance mezzanotte
            self._halted       = False
            self._halt_reason  = ""
            self._midnight_balance = balance
            self._peak_balance     = max(self._peak_balance, balance)
            self._last_date        = today
            self.log.info(
                f"FTMO daily reset → midnight={balance:.2f} | peak={self._peak_balance:.2f}"
            )

    def can_trade(self, equity: float, balance: float) -> Tuple[bool, str]:
        # Se già haltato oggi, non rientrare MAI finché non cambia giorno
        if self._halted:
            return False, self._halt_reason

        # Daily DD — controllo su equity in tempo reale
        daily_limit = self._midnight_balance * (1.0 - self.cfg.daily_dd_safety)
        if equity < daily_limit:
            reason = (
                f"DAILY_DD — equity={equity:.0f} < limit={daily_limit:.0f} "
                f"({(self._midnight_balance - equity)/self._midnight_balance:.2%} usato)"
            )
            self._halted      = True
            self._halt_reason = reason
            self.log.critical(f"⛔ FTMO HALT: {reason}")
            return False, reason

        # Total DD
        total_limit = self._peak_balance * (1.0 - self.cfg.total_dd_safety)
        if equity < total_limit:
            reason = (
                f"TOTAL_DD — equity={equity:.0f} < limit={total_limit:.0f} "
                f"({(self._peak_balance - equity)/self._peak_balance:.2%} usato)"
            )
            self._halted      = True
            self._halt_reason = reason
            self.log.critical(f"⛔ FTMO HALT: {reason}")
            return False, reason

        # Warning a 80% della soglia daily
        daily_used_pct = (self._midnight_balance - equity) / self._midnight_balance
        if daily_used_pct > self.cfg.daily_dd_safety * 0.8:
            self.log.warning(
                f"⚠ FTMO ATTENZIONE: DD giornaliero al "
                f"{daily_used_pct:.2%} (soglia {self.cfg.daily_dd_safety:.2%})"
            )

        return True, "OK"


# ──────────────────────────────────────────────────────────────────────────────
# PROP ENGINE
# ──────────────────────────────────────────────────────────────────────────────
class PropEngine:
    def __init__(self, cfg: PropConfig):
        self.cfg      = cfg
        self.analyzer = MarketAnalyzer(cfg)
        self.ftmo     = FTMORisk(cfg)
        self.state    = StateFile(cfg.state_file)
        self.log      = logging.getLogger("PROP.Engine")

        self._ticket          = 0
        self._signal_id       = 0
        self._running         = False
        # FIX: cooldown post-SL
        self._last_sl_time: Optional[datetime] = None

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

    def _in_cooldown(self) -> bool:
        """Verifica se siamo in cooldown post-SL."""
        if self._last_sl_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_sl_time).total_seconds() / 60.0
        if elapsed < self.cfg.cooldown_after_sl_min:
            remaining = self.cfg.cooldown_after_sl_min - elapsed
            self.log.info(f"⏳ Cooldown post-SL: {remaining:.1f} minuti rimanenti")
            return True
        return False

    def _open_trade(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        if signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * self.cfg.sl_atr_mult
            tp         = price - atr * self.cfg.tp_atr_mult
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * self.cfg.sl_atr_mult
            tp         = price + atr * self.cfg.tp_atr_mult

        self._jitter()
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.cfg.symbol,
            "volume":       self.cfg.prop_lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        self.cfg.magic,
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
            f"Prop trade aperto → ticket={result.order} | "
            f"{'SELL' if order_type==mt5.ORDER_TYPE_SELL else 'BUY'} | "
            f"price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        return result.order

    def _is_open(self, ticket: int) -> bool:
        if ticket == 0:
            return False
        return bool(mt5.positions_get(ticket=ticket))

    def _write_full_state(self, balance, equity, spread, spread_ok,
                          z, vwap, cvd, cvd_trend, signal, atr,
                          ftmo_ok, ftmo_reason, in_cooldown=False):
        midnight  = self.ftmo._midnight_balance
        peak      = self.ftmo._peak_balance
        daily_lim = midnight * (1.0 - self.cfg.daily_dd_safety)
        total_lim = peak    * (1.0 - self.cfg.total_dd_safety)
        daily_pct = max(0.0, (midnight - equity) / midnight) if midnight > 0 else 0.0
        total_pct = max(0.0, (peak    - equity) / peak)     if peak    > 0 else 0.0
        profit_oggi = balance - midnight
        cons_limit  = max(0.0, midnight - self.cfg.prop_initial_balance)

        prop_pnl = 0.0
        if self._ticket > 0:
            pos = mt5.positions_get(ticket=self._ticket)
            if pos:
                prop_pnl = float(pos[0].profit)

        current = self.state.read()

        # Determina mode
        if self.ftmo._halted:
            mode = "HALTED"
        elif in_cooldown:
            mode = "COOLDOWN"
        elif self._ticket > 0:
            mode = "Normal Mode"
        else:
            mode = current.get("mode", "IDLE")

        self.state.write({
            "signal":       signal,
            "signal_id":    self._signal_id,
            "atr":          atr,
            "prop_ticket":  self._ticket,
            "prop_closed":  current.get("prop_closed", False),
            "last_signal":  signal,
            "prop_balance":    balance,
            "prop_equity":     equity,
            "prop_pnl_float":  prop_pnl,
            "prop_connected":  True,
            "hedge_balance":         current.get("hedge_balance", 0.0),
            "hedge_equity":          current.get("hedge_equity", 0.0),
            "hedge_pnl_float":       current.get("hedge_pnl_float", 0.0),
            "hedge_connected":       current.get("hedge_connected", False),
            "hedge_ticket":          current.get("hedge_ticket", 0),
            "reverse_ticket":        current.get("reverse_ticket", 0),
            "reverse_active":        current.get("reverse_active", False),
            "trailing_active":       current.get("trailing_active", False),
            "hedge_realized_profit": current.get("hedge_realized_profit", 0.0),
            "hedge_expected_loss":   current.get("hedge_expected_loss", 0.0),
            "net_system_profit":     current.get("hedge_realized_profit", 0.0) - self.cfg.prop_cost_eur,
            "floor_distance":        current.get("hedge_equity", 0.0) - 9400.0,
            "spread_points": spread,
            "spread_ok":     spread_ok,
            "atr_zscore":    z,
            "vwap":          vwap,
            "cvd":           cvd,
            "cvd_trend":     cvd_trend,
            "mode":          mode,
            "session_active": True,
            "session_name":  "DEMO MODE",
            "last_error":    "",
            "ftmo_daily_dd_pct":      daily_pct,
            "ftmo_total_dd_pct":      total_pct,
            "ftmo_daily_dd_limit":    daily_lim,
            "ftmo_total_dd_limit":    total_lim,
            "ftmo_profit_oggi":       profit_oggi,
            "ftmo_consistency_limit": cons_limit,
            "ftmo_consistency_ok":    profit_oggi < cons_limit or cons_limit <= 0,
            "ftmo_can_trade":         ftmo_ok,
            "ftmo_block_reason":      ftmo_reason,
            "ftmo_final_phase":       False,
        })

    def run(self):
        self.log.info("═══ PROP ENGINE v1.1 — AVVIO ═══")
        self.log.info(f"Cooldown post-SL: {self.cfg.cooldown_after_sl_min} minuti")
        self.log.info(f"FTMO Daily DD safety: {self.cfg.daily_dd_safety:.1%}")

        if not self._connect():
            self.log.error("Connessione fallita. Esco.")
            return

        self._running = True
        spread, spread_ok = 0, True
        z, vwap, cvd, cvd_trend = 0.0, 0.0, 0.0, "NEUTRAL"
        atr = 0.0
        ftmo_ok, ftmo_reason = True, "OK"

        while self._running:
            try:
                info = mt5.account_info()
                if info is None:
                    self.log.warning("account_info None, riconnetto...")
                    self._reconnect()
                    continue

                balance = info.balance
                equity  = info.equity
                self.ftmo.daily_update(balance)

                df = self.analyzer.get_rates(200)
                if df is None:
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                spread    = self.analyzer.get_spread_points()
                spread_ok = spread <= self.cfg.max_spread_points
                atr       = float(self.analyzer.compute_atr(df).iloc[-1])
                z         = self.analyzer.compute_atr_zscore(df)
                vwap      = self.analyzer.compute_vwap(df)
                cvd, cvd_trend = self.analyzer.compute_cvd(df)

                spread_str = "✓ OK" if spread_ok else f"✗ BLOCCATO ({spread}pts)"
                self.log.info(
                    f"Ciclo → spread={spread}pts [{spread_str}] | "
                    f"Z={z:.2f} | VWAP={vwap:.2f} | CVD={cvd:.0f} [{cvd_trend}] | "
                    f"balance={balance:.2f} | equity={equity:.2f}"
                )

                # ── FIX 1: FTMO check su equity in tempo reale ───────────────
                ftmo_ok, ftmo_reason = self.ftmo.can_trade(equity, balance)
                if not ftmo_ok:
                    self.log.warning(f"FTMO BLOCK: {ftmo_reason}")
                    # Chiudi posizione aperta se FTMO halta
                    if self._ticket > 0 and self._is_open(self._ticket):
                        self.log.critical("Chiusura forzata posizione per FTMO DD!")
                        tick = mt5.symbol_info_tick(self.cfg.symbol)
                        if tick:
                            pos = mt5.positions_get(ticket=self._ticket)
                            if pos:
                                p = pos[0]
                                close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                                price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
                                mt5.order_send({
                                    "action": mt5.TRADE_ACTION_DEAL,
                                    "symbol": self.cfg.symbol,
                                    "volume": p.volume,
                                    "type": close_type,
                                    "position": self._ticket,
                                    "price": price,
                                    "deviation": 20,
                                    "magic": p.magic,
                                    "type_time": mt5.ORDER_TIME_GTC,
                                    "type_filling": mt5.ORDER_FILLING_IOC,
                                })
                        self._ticket = 0
                    self._write_full_state(balance, equity, spread, spread_ok,
                                           z, vwap, cvd, cvd_trend, "NONE", atr,
                                           ftmo_ok, ftmo_reason)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # ── Check trade già aperto ────────────────────────────────────
                if self._ticket > 0:
                    if self._is_open(self._ticket):
                        current = self.state.read()
                        current["mode"] = "Normal Mode"
                        self.state.write(current)
                    else:
                        self.log.info(f"Prop trade chiuso → ticket={self._ticket}")
                        # FIX 2: registra tempo chiusura per cooldown
                        self._last_sl_time = datetime.now(timezone.utc)
                        self.log.info(
                            f"⏳ Cooldown attivato: prossimo trade tra "
                            f"{self.cfg.cooldown_after_sl_min:.0f} minuti"
                        )
                        self._ticket = 0
                        current = self.state.read()
                        current["prop_closed"] = True
                        current["mode"]        = "Trend Riding"
                        self.state.write(current)

                    self._write_full_state(balance, equity, spread, spread_ok,
                                           z, vwap, cvd, cvd_trend,
                                           self.state.read().get("signal", "NONE"),
                                           atr, ftmo_ok, ftmo_reason)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # ── FIX 2: Cooldown post-SL ───────────────────────────────────
                in_cooldown = self._in_cooldown()
                if in_cooldown:
                    self._write_full_state(balance, equity, spread, spread_ok,
                                           z, vwap, cvd, cvd_trend, "NONE", atr,
                                           ftmo_ok, ftmo_reason, in_cooldown=True)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                if not spread_ok:
                    self._write_full_state(balance, equity, spread, spread_ok,
                                           z, vwap, cvd, cvd_trend, "NONE", atr,
                                           ftmo_ok, ftmo_reason)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                signal, z, vwap, cvd, cvd_trend = self.analyzer.generate_signal(df)

                if signal == Signal.NONE:
                    self._write_full_state(balance, equity, spread, spread_ok,
                                           z, vwap, cvd, cvd_trend, "NONE", atr,
                                           ftmo_ok, ftmo_reason)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                self.log.info(f"Segnale {signal} | Z={z:.2f} | VWAP={vwap:.2f} | CVD={cvd:.0f}")

                self._signal_id += 1
                self._write_full_state(balance, equity, spread, spread_ok,
                                       z, vwap, cvd, cvd_trend, signal.value, atr,
                                       ftmo_ok, ftmo_reason)
                current = self.state.read()
                current["signal_id"]   = self._signal_id
                current["mode"]        = "Normal Mode"
                current["prop_closed"] = False
                self.state.write(current)

                time.sleep(0.5)

                ticket = self._open_trade(signal, atr)

                if ticket:
                    self._ticket = ticket
                    current = self.state.read()
                    current["prop_ticket"] = ticket
                    self.state.write(current)
                    self.log.info(f"Prop in posizione → ticket={ticket}")
                else:
                    self.log.error("Apertura Prop fallita — annullo segnale")
                    current = self.state.read()
                    current["signal"] = "NONE"
                    current["mode"]   = "IDLE"
                    self.state.write(current)

                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                self.log.info("Interruzione manuale. Esco.")
                self._running = False

            except Exception as e:
                self.log.error(f"Errore nel loop: {e}", exc_info=True)
                self._reconnect()
                time.sleep(self.cfg.loop_interval_sec * 2)

        self.log.info("Prop Engine fermato.")
        mt5.shutdown()


if __name__ == "__main__":
    cfg = PropConfig.from_json()
    engine = PropEngine(cfg)
    engine.run()
