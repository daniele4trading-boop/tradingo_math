"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — PROP ENGINE  (FTMO 100k)                                        ║
║   Processo separato: si connette SOLO al terminale FTMO                      ║
║   - Legge segnali (VWAP + CVD + ATR Z-Score)                                 ║
║   - Apre trade in direzione OPPOSTA al segnale                               ║
║   - Scrive segnale e stato su tradingo_state.json                            ║
║   - Gestisce regole FTMO (daily DD, total DD, consistency)                   ║
║                                                                              ║
║   Avvio: python tradingo_prop.py                                             ║
║   (in parallelo con tradingo_hedge.py in altra finestra PowerShell)          ║
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
from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from enum import Enum

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("prop.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("PROP")


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
class PropConfig:
    # ── Terminale FTMO ───────────────────────────────────────────────────────
    terminal_path: str = r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
    login:         int = 1513075253
    password:      str = "$*CS4HIJUr2"
    server:        str = "FTMO-Demo"

    # ── Simbolo ──────────────────────────────────────────────────────────────
    symbol:        str = "XAUUSD"

    # ── Filtri operativi ─────────────────────────────────────────────────────
    max_spread_points:    int   = 130    # 13 pips — allargato per demo
    atr_zscore_threshold: float = -1.0  # Demo: disabilitato

    # ── Sizing ───────────────────────────────────────────────────────────────
    prop_lot: float = 1.00

    # ── Timeframe e indicatori ────────────────────────────────────────────────
    timeframe:   int = mt5.TIMEFRAME_M5
    atr_period:  int = 14
    vwap_period: int = 20
    cvd_period:  int = 10

    # ── Jitter stealth (ms) ───────────────────────────────────────────────────
    jitter_min_ms: int = 300
    jitter_max_ms: int = 800

    # ── Loop ──────────────────────────────────────────────────────────────────
    loop_interval_sec: float = 10.0

    # ── File stato condiviso con Hedge ────────────────────────────────────────
    state_file: str = "tradingo_state.json"

    # ── Magic number ──────────────────────────────────────────────────────────
    magic: int = 20260001

    # ── FTMO Risk ────────────────────────────────────────────────────────────
    prop_cost_eur:        float = 680.0
    prop_initial_balance: float = 100_000.0
    daily_dd_safety:      float = 0.027   # 2.7% (limite reale 3%)
    total_dd_safety:      float = 0.095   # 9.5% (limite reale 10%)


# ──────────────────────────────────────────────────────────────────────────────
# STATE FILE  (comunicazione con tradingo_hedge.py)
# ──────────────────────────────────────────────────────────────────────────────
class StateFile:
    """
    Scrive e legge il file JSON condiviso tra Prop e Hedge.
    Struttura chiave:
      signal        : "BUY" / "SELL" / "NONE"
      signal_id     : intero incrementale — l'Hedge lo usa per capire se è nuovo
      prop_ticket   : ticket ordine Prop aperto (0 = nessuno)
      prop_closed   : True quando la Prop ha chiuso (SL colpito)
      atr           : valore ATR corrente (usato dall'Hedge per SL/TP)
      timestamp     : ora UTC ISO
    """

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
        # Filtro: ignora barre con volume zero o prezzi anomali
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
# FTMO RISK MANAGER (semplificato — solo check, no persistenza)
# ──────────────────────────────────────────────────────────────────────────────
class FTMORisk:
    def __init__(self, cfg: PropConfig):
        self.cfg = cfg
        self.log = logging.getLogger("PROP.FTMO")
        self._midnight_balance = cfg.prop_initial_balance
        self._peak_balance     = cfg.prop_initial_balance
        self._last_date        = ""

    def daily_update(self, balance: float):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_date:
            self._midnight_balance = balance
            self._peak_balance     = max(self._peak_balance, balance)
            self._last_date        = today
            self.log.info(f"FTMO daily update → midnight={balance:.2f} | peak={self._peak_balance:.2f}")

    def can_trade(self, equity: float, balance: float) -> Tuple[bool, str]:
        # Daily DD
        daily_limit = self._midnight_balance * (1.0 - self.cfg.daily_dd_safety)
        if equity < daily_limit:
            return False, f"DAILY_DD equity={equity:.0f} < limit={daily_limit:.0f}"

        # Total DD
        total_limit = self._peak_balance * (1.0 - self.cfg.total_dd_safety)
        if equity < total_limit:
            return False, f"TOTAL_DD equity={equity:.0f} < limit={total_limit:.0f}"

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

        self._ticket       = 0          # ticket ordine aperto
        self._signal_id    = 0          # incrementale per segnali
        self._running      = False

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

    # ── Apertura ordine Prop (direzione OPPOSTA al segnale) ──────────────────
    def _open_trade(self, signal: Signal, atr: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        if signal == Signal.BUY:
            # Segnale BUY → Prop fa SELL (si aspetta che il mercato salga, Prop brucia)
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * 1.5
            tp         = price - atr * 3.0
        else:
            # Segnale SELL → Prop fa BUY
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * 1.5
            tp         = price + atr * 3.0

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
            # Nessun commento — stealth mode Prop
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

    # ── Check se il ticket è ancora aperto ───────────────────────────────────
    def _is_open(self, ticket: int) -> bool:
        if ticket == 0:
            return False
        pos = mt5.positions_get(ticket=ticket)
        return bool(pos)

    # ── Loop principale ───────────────────────────────────────────────────────
    def run(self):
        self.log.info("═══ PROP ENGINE — AVVIO ═══")

        if not self._connect():
            self.log.error("Connessione fallita. Esco.")
            return

        # Inizializza state file
        self.state.write({
            "signal": "NONE",
            "signal_id": 0,
            "prop_ticket": 0,
            "prop_closed": False,
            "atr": 0.0,
            "prop_balance": 0.0,
            "prop_equity": 0.0,
        })

        self._running = True

        while self._running:
            try:
                # ── Dati account ─────────────────────────────────────────────
                info = mt5.account_info()
                if info is None:
                    self.log.warning("account_info None, riconnetto...")
                    self._reconnect()
                    continue

                balance = info.balance
                equity  = info.equity

                self.ftmo.daily_update(balance)

                # ── Dati mercato ──────────────────────────────────────────────
                df = self.analyzer.get_rates(200)
                if df is None:
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                spread = self.analyzer.get_spread_points()
                spread_ok = spread <= self.cfg.max_spread_points
                atr    = float(self.analyzer.compute_atr(df).iloc[-1])
                z      = self.analyzer.compute_atr_zscore(df)
                vwap   = self.analyzer.compute_vwap(df)
                cvd, cvd_trend = self.analyzer.compute_cvd(df)

                spread_str = "✓ OK" if spread_ok else f"✗ BLOCCATO ({spread}pts)"
                self.log.info(
                    f"Ciclo → spread={spread}pts [{spread_str}] | "
                    f"Z={z:.2f} | VWAP={vwap:.2f} | CVD={cvd:.0f} [{cvd_trend}] | "
                    f"balance={balance:.2f} | equity={equity:.2f}"
                )

                # ── Check trade già aperto ────────────────────────────────────
                if self._ticket > 0:
                    if self._is_open(self._ticket):
                        # Trade ancora aperto — aggiorna stato
                        self.state.update(
                            prop_ticket=self._ticket,
                            prop_closed=False,
                            prop_balance=balance,
                            prop_equity=equity,
                        )
                    else:
                        # Trade chiuso (SL o TP colpito)
                        self.log.info(f"Prop trade chiuso → ticket={self._ticket}")
                        self._ticket = 0
                        self.state.update(
                            prop_ticket=0,
                            prop_closed=True,
                            signal="NONE",
                            prop_balance=balance,
                            prop_equity=equity,
                        )
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # ── Nessun trade aperto — cerca segnale ───────────────────────
                # Reset prop_closed quando siamo in attesa di nuovo segnale
                self.state.update(prop_closed=False)

                # FTMO check
                ftmo_ok, ftmo_reason = self.ftmo.can_trade(equity, balance)
                if not ftmo_ok:
                    self.log.warning(f"FTMO BLOCK: {ftmo_reason}")
                    self.state.update(signal="NONE", prop_balance=balance, prop_equity=equity)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                if not spread_ok:
                    self.state.update(signal="NONE", prop_balance=balance, prop_equity=equity)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                # Genera segnale
                signal, z, vwap, cvd, cvd_trend = self.analyzer.generate_signal(df)

                if signal == Signal.NONE:
                    self.state.update(signal="NONE", atr=atr, prop_balance=balance, prop_equity=equity)
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                self.log.info(f"Segnale {signal} | Z={z:.2f} | VWAP={vwap:.2f} | CVD={cvd:.0f}")

                # Pubblica segnale PRIMA di aprire — l'Hedge lo legge e si prepara
                self._signal_id += 1
                self.state.update(
                    signal=signal.value,
                    signal_id=self._signal_id,
                    atr=atr,
                    prop_ticket=0,
                    prop_closed=False,
                    prop_balance=balance,
                    prop_equity=equity,
                )

                # Piccola pausa per dare tempo all'Hedge di leggere il segnale
                time.sleep(0.5)

                # Apri trade Prop (direzione opposta)
                ticket = self._open_trade(signal, atr)

                if ticket:
                    self._ticket = ticket
                    self.state.update(prop_ticket=ticket)
                    self.log.info(f"Prop in posizione → ticket={ticket}")
                else:
                    # Apertura fallita — annulla segnale
                    self.log.error("Apertura Prop fallita — annullo segnale")
                    self.state.update(signal="NONE", signal_id=self._signal_id)

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


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg = PropConfig()
    engine = PropEngine(cfg)
    engine.run()
