"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          TRADINGO ASYMMETRIC SYSTEM v1.0  —  XAUUSD (GOLD)                  ║
║          Dual-Account Engine: Prop (100k) + Hedge (10k)                     ║
║          Autore: Sistema generato su specifiche Daniele / doppiozero         ║
╚══════════════════════════════════════════════════════════════════════════════╝

ARCHITETTURA:
  - TradinGoConfig       : Tutti i parametri configurabili
  - MT5Connector         : Connessione e riconnessione ai due terminali MT5
  - MarketAnalyzer       : Calcolo ATR Z-Score, VWAP, CVD, spread check
  - TradeExecutor        : Invio ordini con jitter e stealth mode
  - SmartController      : Logica crisi / reverse hedge / trailing stop
  - TradinGoEngine       : Orchestratore principale del loop
  - StateManager         : Stato condiviso tra engine e dashboard (JSON file)

DIPENDENZE:
  pip install MetaTrader5 pandas numpy streamlit
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import json
import random
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple
from enum import Enum

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("tradingo.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("TradinGo")


# ──────────────────────────────────────────────────────────────────────────────
# ENUMERAZIONI
# ──────────────────────────────────────────────────────────────────────────────
class SystemMode(str, Enum):
    IDLE         = "IDLE"
    NORMAL       = "Normal Mode"
    MITIGATION   = "Mitigation"
    TREND_RIDING = "Trend Riding"
    HALTED       = "HALTED"


class Signal(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class TradinGoConfig:
    # ── Path terminali MT5 (MODIFICA con i tuoi path reali) ──────────────────
    prop_terminal_path:  str = r"C:\Program Files\MetaTrader 5 Prop\terminal64.exe"
    hedge_terminal_path: str = r"C:\Program Files\MetaTrader 5 Hedge\terminal64.exe"

    # ── Credenziali account (MODIFICA) ───────────────────────────────────────
    prop_login:    int = 1234567          # Login conto Prop 100k Demo
    prop_password: str = "PropPassword"
    prop_server:   str = "PropServer-Demo"

    hedge_login:    int = 7654321         # Login conto Hedge 10k
    hedge_password: str = "HedgePassword"
    hedge_server:   str = "HedgeServer"

    # ── Simbolo ──────────────────────────────────────────────────────────────
    symbol: str = "XAUUSD"

    # ── Parametri finanziari ─────────────────────────────────────────────────
    prop_cost_eur:        float = 680.0    # Costo acquisto Prop
    hedge_initial_balance: float = 10_000.0
    hedge_floor_equity:   float = 9_400.0  # Hard stop: se equity < floor -> halt

    # ── Filtri operativi ─────────────────────────────────────────────────────
    max_spread_points: int = 130           # 13 pips su Gold — allargato per fase demo
    atr_zscore_threshold: float = -1.0    # Demo: disabilitato (accetta qualsiasi volatilità)

    # ── Sizing lotti ─────────────────────────────────────────────────────────
    prop_lot:              float = 1.00
    hedge_lot:             float = 0.14
    reverse_lot_multiplier: float = 2.1   # Moltiplicatore per il reverse hedge

    # ── Soglia attivazione Reverse Hedge ─────────────────────────────────────
    # Percentuale della perdita massima attesa sull'Hedge prima di attivare
    reverse_trigger_pct:  float = 0.50   # 50% della perdita prevista

    # ── Trailing Stop ────────────────────────────────────────────────────────
    trailing_atr_multiplier: float = 2.0

    # ── Timeframe ────────────────────────────────────────────────────────────
    timeframe: int = mt5.TIMEFRAME_M5
    atr_period: int = 14
    vwap_period: int = 20   # barre per VWAP rolling
    cvd_period: int = 10

    # ── Jitter stealth (millisecondi) ─────────────────────────────────────────
    jitter_min_ms: int = 300
    jitter_max_ms: int = 800

    # ── Loop principale ───────────────────────────────────────────────────────
    loop_interval_sec: float = 10.0       # Frequenza polling stato

    # ── File di stato condiviso con la dashboard ──────────────────────────────
    state_file: str = "tradingo_state.json"

    # ── Magic numbers (per identificare i trade del sistema) ──────────────────
    magic_prop:    int = 20260001
    magic_hedge:   int = 20260002
    magic_reverse: int = 20260003


# ──────────────────────────────────────────────────────────────────────────────
# STATO CONDIVISO (scritto su file JSON per la dashboard Streamlit)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class SystemState:
    mode:                  str   = SystemMode.IDLE
    timestamp:             str   = ""

    # Conti
    prop_balance:          float = 0.0
    prop_equity:           float = 0.0
    prop_pnl_float:        float = 0.0

    hedge_balance:         float = 0.0
    hedge_equity:          float = 0.0
    hedge_pnl_float:       float = 0.0

    # Metriche sistema
    net_system_profit:     float = 0.0   # (profitto hedge realizzato) - prop_cost
    floor_distance:        float = 0.0   # hedge_equity - floor
    hedge_realized_profit: float = 0.0   # Profit chiuso sull'hedge

    # Segnali
    last_signal:           str   = Signal.NONE
    session_active:        bool  = False
    session_name:          str   = "FUORI SESSIONE"
    next_session:          str   = ""
    atr_zscore:            float = 0.0
    spread_points:         int   = 0
    spread_ok:             bool  = True
    vwap:                  float = 0.0
    cvd:                   float = 0.0
    cvd_trend:             str   = "NEUTRAL"

    # Trade attivi
    prop_ticket:           int   = 0
    hedge_ticket:          int   = 0
    reverse_ticket:        int   = 0

    # Controller
    hedge_expected_loss:   float = 0.0
    reverse_active:        bool  = False
    trailing_active:       bool  = False

    # FTMO Risk
    ftmo_daily_dd_pct:     float = 0.0
    ftmo_total_dd_pct:     float = 0.0
    ftmo_daily_dd_limit:   float = 97_300.0
    ftmo_total_dd_limit:   float = 90_500.0
    ftmo_profit_oggi:      float = 0.0
    ftmo_consistency_limit: float = 0.0
    ftmo_consistency_ok:   bool  = True
    ftmo_can_trade:        bool  = True
    ftmo_block_reason:     str   = ""
    ftmo_final_phase:      bool  = False

    # Errori
    last_error:            str   = ""
    prop_connected:        bool  = False
    hedge_connected:       bool  = False


# ──────────────────────────────────────────────────────────────────────────────
# MT5 CONNECTOR
# ──────────────────────────────────────────────────────────────────────────────
class MT5Connector:
    """
    Gestisce la connessione a UN singolo terminale MT5.

    ARCHITETTURA DUAL-ACCOUNT:
    La libreria MetaTrader5 Python ha UN solo contesto globale per processo.
    Non è possibile tenere due connessioni simultanee nello stesso processo.

    Soluzione implementata:
      - Si usa UN SOLO terminale MT5 (il Prop) come processo principale.
      - Per leggere i dati del conto Hedge si usa mt5.login() che switcha
        l'account attivo sul terminale già inizializzato, senza re-inizializzare.
      - Questo elimina il loop "connessione persa / re-inizializzo" che
        si verificava ad ogni ciclo.

    Il terminale MT5 deve avere entrambi gli account salvati (AutoLogin).
    """

    def __init__(self, name: str, terminal_path: str,
                 login: int, password: str, server: str):
        self.name          = name
        self.terminal_path = terminal_path
        self.login         = login
        self.password      = password
        self.server        = server
        self._connected    = False
        self.log           = logging.getLogger(f"MT5[{name}]")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def initialize(self) -> bool:
        """
        Inizializza il terminale MT5 (chiamare UNA SOLA VOLTA all'avvio).
        Usa il path del terminale in portable mode.
        """
        try:
            ok = mt5.initialize(
                path=self.terminal_path,
                login=self.login,
                password=self.password,
                server=self.server,
                # portable=True,  # RIMOSSO: usare terminale già aperto
            )
            if not ok:
                self.log.error(f"Initialize fallito: {mt5.last_error()}")
                self._connected = False
                return False

            info = mt5.account_info()
            if info is None:
                self.log.error("account_info() None dopo initialize")
                self._connected = False
                return False

            self.log.info(
                f"Inizializzato → Login:{info.login} | "
                f"Balance:{info.balance:.2f} | Server:{info.server}"
            )
            self._connected = True
            return True

        except Exception as e:
            self.log.error(f"Eccezione in initialize(): {e}")
            self._connected = False
            return False

    def switch_to(self) -> bool:
        """
        Switcha l'account attivo su questo connector usando mt5.login().
        NON re-inizializza il terminale — usa la sessione già aperta.
        Molto più veloce e stabile rispetto a chiamare initialize() ripetutamente.
        """
        try:
            # Verifica se siamo già su questo account
            info = mt5.account_info()
            if info is not None and info.login == self.login:
                self._connected = True
                return True

            # Switch account
            ok = mt5.login(
                login=self.login,
                password=self.password,
                server=self.server,
            )
            if not ok:
                self.log.error(f"login() fallito: {mt5.last_error()}")
                self._connected = False
                return False

            self._connected = True
            return True

        except Exception as e:
            self.log.error(f"Eccezione in switch_to(): {e}")
            self._connected = False
            return False

    def connect(self) -> bool:
        """Compatibilità: alias di switch_to() per il codice esistente."""
        return self.switch_to()

    def disconnect(self):
        """Chiude il terminale MT5 (chiamare solo alla fine del programma)."""
        mt5.shutdown()
        self._connected = False
        self.log.info("Terminale MT5 chiuso.")

    def reconnect(self, max_attempts: int = 5, delay: float = 5.0) -> bool:
        """Tenta la reinizializzazione completa del terminale in caso di crash."""
        for attempt in range(1, max_attempts + 1):
            self.log.warning(f"Tentativo reinizializzazione {attempt}/{max_attempts}...")
            mt5.shutdown()
            time.sleep(delay * attempt)
            if self.initialize():
                self.log.info("Reinizializzazione riuscita.")
                return True
        self.log.error("Reinizializzazione fallita dopo tutti i tentativi.")
        return False

    def get_account_info(self) -> Optional[mt5.AccountInfo]:
        """Legge le info account dopo aver switchato su questo connector."""
        if not self.switch_to():
            return None
        info = mt5.account_info()
        if info is None:
            self.log.warning("account_info() None, tentativo reconnect...")
            if self.reconnect():
                self.switch_to()
                info = mt5.account_info()
        return info

    def get_positions(self, magic: int) -> list:
        """Restituisce le posizioni aperte filtrate per magic number."""
        positions = mt5.positions_get(symbol=None)
        if positions is None:
            return []
        return [p for p in positions if p.magic == magic]



# ──────────────────────────────────────────────────────────────────────────────
# SESSION FILTER
# ──────────────────────────────────────────────────────────────────────────────
class SessionFilter:
    """
    Filtra i trade alle sole Kill Zones operative su XAUUSD.
    Usa l'orario del BROKER MT5 (tick.time) che è già UTC+2 (ora italiana).

    Kill Zones attive:
      - London Open : 09:00 - 12:00 (ora italiana / broker)
      - NY Open     : 15:00 - 20:00 (ora italiana / broker)

    Fuori da queste finestre il sistema non apre nuovi trade,
    ma gestisce normalmente quelli già aperti.
    """

    # Orari in ora ITALIANA (= broker time UTC+2)
    KILL_ZONES = [
        {"name": "London Open", "start": (9,  0), "end": (12, 0)},
        {"name": "NY Open",     "start": (15, 0), "end": (20, 0)},
    ]

    def __init__(self):
        self.log = logging.getLogger("SessionFilter")

    def _broker_hour_minute(self) -> tuple:
        """
        Legge l'ora corrente dal tick MT5 (broker time).
        Fallback su ora di sistema UTC+2 se il tick non è disponibile.
        """
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick and tick.time > 0:
            dt = datetime.fromtimestamp(tick.time, tz=timezone.utc)
            # Broker FTMO/UltimaMarkets = UTC+2
            dt_it = dt + __import__('datetime').timedelta(hours=2)
            return dt_it.hour, dt_it.minute
        # Fallback: orario sistema + UTC+2
        now = datetime.now(timezone.utc)
        now_it = now + __import__('datetime').timedelta(hours=2)
        return now_it.hour, now_it.minute

    def is_active(self) -> tuple:
        """
        Verifica se siamo in una Kill Zone attiva.
        Restituisce (is_active: bool, session_name: str)
        """
        h, m = self._broker_hour_minute()
        current_minutes = h * 60 + m

        for zone in self.KILL_ZONES:
            start_min = zone["start"][0] * 60 + zone["start"][1]
            end_min   = zone["end"][0]   * 60 + zone["end"][1]
            if start_min <= current_minutes <= end_min:
                return True, zone["name"]

        return False, "FUORI SESSIONE"

    def next_session(self) -> str:
        """Restituisce il nome della prossima sessione."""
        h, m = self._broker_hour_minute()
        current_minutes = h * 60 + m
        for zone in sorted(self.KILL_ZONES, key=lambda z: z["start"][0] * 60 + z["start"][1]):
            start_min = zone["start"][0] * 60 + zone["start"][1]
            if start_min > current_minutes:
                return f"{zone['name']} ({zone['start'][0]:02d}:{zone['start'][1]:02d})"
        return f"{self.KILL_ZONES[0]['name']} (domani {self.KILL_ZONES[0]['start'][0]:02d}:{self.KILL_ZONES[0]['start'][1]:02d})"

# ──────────────────────────────────────────────────────────────────────────────
# MARKET ANALYZER
# ──────────────────────────────────────────────────────────────────────────────
class MarketAnalyzer:
    """
    Calcola indicatori tecnici su dati M5 di XAUUSD.
    ATR Z-Score, VWAP rolling, Cumulative Volume Delta, spread check.
    """

    def __init__(self, config: TradinGoConfig):
        self.cfg = config
        self.log = logging.getLogger("MarketAnalyzer")

    def get_rates(self, n_bars: int = 200) -> Optional[pd.DataFrame]:
        """Scarica le ultime n_bars candele M5 come DataFrame."""
        rates = mt5.copy_rates_from_pos(
            self.cfg.symbol, self.cfg.timeframe, 0, n_bars
        )
        if rates is None or len(rates) == 0:
            self.log.warning("copy_rates_from_pos ha restituito None")
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def get_spread_points(self) -> int:
        """Restituisce lo spread corrente in punti (tick size units)."""
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return 9999
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None:
            return 9999
        spread_points = int((tick.ask - tick.bid) / sym.point)
        return spread_points

    def is_spread_ok(self) -> Tuple[bool, int]:
        """Verifica se lo spread è sotto la soglia operativa."""
        sp = self.get_spread_points()
        return sp <= self.cfg.max_spread_points, sp

    def compute_atr(self, df: pd.DataFrame) -> pd.Series:
        """ATR(14) classico su high/low/close."""
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.cfg.atr_period).mean()
        return atr

    def compute_atr_zscore(self, df: pd.DataFrame) -> float:
        """
        Z-Score dell'ATR corrente rispetto alla media mobile degli ultimi 50 valori.
        Misura quanto la volatilità attuale devia dalla norma.
        """
        atr = self.compute_atr(df)
        atr_clean = atr.dropna()
        if len(atr_clean) < 50:
            return 0.0
        window = atr_clean.iloc[-50:]
        mean = window.mean()
        std  = window.std()
        if std == 0:
            return 0.0
        zscore = (atr_clean.iloc[-1] - mean) / std
        return float(zscore)

    def compute_vwap(self, df: pd.DataFrame) -> float:
        """
        VWAP rolling: prezzo medio ponderato per volume
        sulle ultime vwap_period candele.

        Filtra candele anomale (tick_volume == 0 o prezzi chiaramente errati)
        per evitare VWAP distorto da barre vuote di fine sessione.
        """
        n   = self.cfg.vwap_period
        sub = df.iloc[-n:].copy()
        # Filtra candele con volume zero o prezzi anomali (< 100 su XAUUSD = errore dati)
        sub = sub[sub["tick_volume"] > 0]
        sub = sub[sub["close"] > 100]
        if sub.empty:
            return float(df["close"].iloc[-1])
        typical = (sub["high"] + sub["low"] + sub["close"]) / 3.0
        vol  = sub["tick_volume"].astype(np.int64)
        vwap = float((typical * vol).sum() / vol.sum())
        return vwap

    def compute_cvd(self, df: pd.DataFrame) -> Tuple[float, str]:
        """
        Cumulative Volume Delta (proxy): differenza tra barre bullish e bearish
        nell'ultima finestra cvd_period.
        CVD > 0 → pressione d'acquisto dominante → trend UP.
        CVD < 0 → pressione di vendita dominante  → trend DOWN.

        Nota: tick_volume viene castato a int64 firmato per evitare overflow
        su piattaforme che restituiscono uint64.
        """
        n   = self.cfg.cvd_period
        sub = df.iloc[-n:].copy()
        # Cast esplicito a int64 per evitare overflow uint64 (bug CVD = 2^64-1)
        vol = sub["tick_volume"].astype(np.int64)
        sub["delta"] = np.where(
            sub["close"] > sub["open"],
             vol,
            -vol,
        )
        cvd = float(sub["delta"].sum())
        trend = "UP" if cvd > 0 else ("DOWN" if cvd < 0 else "NEUTRAL")
        return cvd, trend

    def generate_signal(self, df: pd.DataFrame) -> Tuple[Signal, float, float, float, str]:
        """
        Combina ATR Z-Score + VWAP + CVD per generare un segnale.
        
        Logica:
          - Z-Score > threshold → volatilità sufficiente
          - Prezzo > VWAP E CVD trend UP   → segnale BUY
          - Prezzo < VWAP E CVD trend DOWN → segnale SELL
        
        Restituisce: (Signal, z_score, vwap, cvd, cvd_trend)
        """
        z     = self.compute_atr_zscore(df)
        vwap  = self.compute_vwap(df)
        cvd, cvd_trend = self.compute_cvd(df)
        price = float(df["close"].iloc[-1])

        if z < self.cfg.atr_zscore_threshold:
            return Signal.NONE, z, vwap, cvd, cvd_trend

        if price > vwap and cvd_trend == "UP":
            return Signal.BUY, z, vwap, cvd, cvd_trend
        elif price < vwap and cvd_trend == "DOWN":
            return Signal.SELL, z, vwap, cvd, cvd_trend

        return Signal.NONE, z, vwap, cvd, cvd_trend


# ──────────────────────────────────────────────────────────────────────────────
# TRADE EXECUTOR
# ──────────────────────────────────────────────────────────────────────────────
class TradeExecutor:
    """
    Invia ordini MT5 con gestione stealth e time jitter.
    - Prop: nessun commento, nessun identificatore visibile.
    - Hedge: commento con magic per debug.
    """

    def __init__(self, config: TradinGoConfig):
        self.cfg = config
        self.log = logging.getLogger("TradeExecutor")

    def _jitter(self):
        """Pausa casuale tra jitter_min e jitter_max ms per evitare pattern rilevabili."""
        ms = random.randint(self.cfg.jitter_min_ms, self.cfg.jitter_max_ms)
        time.sleep(ms / 1000.0)

    def _get_symbol_info(self) -> Optional[mt5.SymbolInfo]:
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym is None:
            self.log.error(f"symbol_info({self.cfg.symbol}) restituito None")
        return sym

    def _market_order(
        self,
        order_type: int,   # mt5.ORDER_TYPE_BUY / SELL
        lot: float,
        sl: float,
        tp: float,
        magic: int,
        stealth: bool = False,  # True = nessun commento (Prop)
        deviation: int = 20,
    ) -> Optional[mt5.OrderSendResult]:
        """Invia un ordine a mercato con SL/TP."""
        self._jitter()

        sym  = self._get_symbol_info()
        if sym is None:
            return None

        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            self.log.error("symbol_info_tick restituito None")
            return None

        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    self.cfg.symbol,
            "volume":    lot,
            "type":      order_type,
            "price":     price,
            "sl":        sl,
            "tp":        tp,
            "deviation": deviation,
            "magic":     magic,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Stealth mode: nessun commento sull'ordine Prop
        if not stealth:
            request["comment"] = f"TG_{magic}"

        result = mt5.order_send(request)
        if result is None:
            err = mt5.last_error()
            self.log.error(f"order_send None, errore MT5: {err}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log.error(
                f"Ordine rifiutato: retcode={result.retcode} | comment={result.comment}"
            )
            return None

        self.log.info(
            f"Ordine eseguito → ticket={result.order} | "
            f"type={'BUY' if order_type==mt5.ORDER_TYPE_BUY else 'SELL'} | "
            f"lot={lot} | price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}"
        )
        return result

    def open_prop_trade(self, signal: Signal, atr: float) -> Optional[int]:
        """
        Apre il trade sulla Prop in direzione OPPOSTA al segnale.
        Signal=BUY → Prop fa SELL.
        SL/TP basati su ATR.
        """
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        # Inversione segnale per Prop
        if signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * 1.5
            tp         = price - atr * 3.0
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * 1.5
            tp         = price + atr * 3.0

        result = self._market_order(
            order_type=order_type,
            lot=self.cfg.prop_lot,
            sl=sl,
            tp=tp,
            magic=self.cfg.magic_prop,
            stealth=True,  # Nessun commento sulla Prop
        )
        return result.order if result else None

    def open_hedge_trade(self, signal: Signal, atr: float) -> Optional[int]:
        """
        Apre il trade sull'Hedge in direzione ALLINEATA al segnale.
        Signal=BUY → Hedge fa BUY.
        """
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

        result = self._market_order(
            order_type=order_type,
            lot=self.cfg.hedge_lot,
            sl=sl,
            tp=tp,
            magic=self.cfg.magic_hedge,
            stealth=False,
        )
        return result.order if result else None

    def open_reverse_hedge(self, original_signal: Signal, atr: float) -> Optional[int]:
        """
        Apre il Reverse Hedge in direzione OPPOSTA al trade hedge originale.
        Lotto = hedge_lot * reverse_lot_multiplier.
        """
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return None

        lot = round(self.cfg.hedge_lot * self.cfg.reverse_lot_multiplier, 2)

        # Direzione opposta all'hedge originale
        if original_signal == Signal.BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = price + atr * 2.0
            tp         = price - atr * 2.0
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = price - atr * 2.0
            tp         = price + atr * 2.0

        result = self._market_order(
            order_type=order_type,
            lot=lot,
            sl=sl,
            tp=tp,
            magic=self.cfg.magic_reverse,
            stealth=False,
        )
        return result.order if result else None

    def close_position(self, ticket: int) -> bool:
        """Chiude una posizione aperta per ticket."""
        self._jitter()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            self.log.warning(f"Posizione ticket={ticket} non trovata per chiusura")
            return False

        pos  = positions[0]
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return False

        # Direzione chiusura opposta all'apertura
        if pos.type == mt5.ORDER_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask

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

        self.log.error(f"Chiusura fallita per ticket={ticket}: {mt5.last_error()}")
        return False

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Modifica lo Stop Loss di una posizione aperta."""
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False

        pos = positions[0]
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol":   self.cfg.symbol,
            "sl":       new_sl,
            "tp":       pos.tp,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.log.debug(f"SL aggiornato → ticket={ticket} | new_sl={new_sl:.2f}")
            return True
        return False


# ──────────────────────────────────────────────────────────────────────────────
# FTMO RISK MANAGER
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class FTMOState:
    """
    Stato persistente delle regole FTMO — salvato su file JSON.
    Sopravvive ai riavvii del sistema.
    """
    # Balance di mezzanotte del giorno precedente (base per daily DD)
    midnight_balance_yesterday: float = 100_000.0
    # Picco massimo dei balance di mezzanotte (base per total DD — solo sale mai)
    peak_midnight_balance:      float = 100_000.0
    # Profitto cumulato fino a ieri (base per consistency rule)
    profit_cumulated_yesterday: float = 0.0
    # Data dell'ultimo aggiornamento (formato YYYY-MM-DD)
    last_update_date:           str   = ""


class FTMORiskManager:
    """
    Gestisce tutte le regole del conto FTMO Challenge 100k.

    Regole implementate:
    ─────────────────────────────────────────────────────────────────
    1. DAILY DRAWDOWN (soglia sicurezza 2.7% vs limite reale 3%)
       - Base: balance a mezzanotte del giorno precedente
       - Aggiornato ogni giorno al primo ciclo dopo mezzanotte
       - Ferma nuovi trade se equity < midnight_balance_yesterday * (1 - 0.027)

    2. MAX TOTAL DRAWDOWN (soglia sicurezza 9.5% vs limite reale 10%)
       - Base: picco massimo dei balance di mezzanotte (solo cresce)
       - Ferma nuovi trade se equity < peak_midnight_balance * (1 - 0.095)
       - FINAL PHASE se equity < peak_midnight_balance * (1 - 0.085)

    3. CONSISTENCY RULE (50% cap)
       - Limite giornaliero = profit_cumulated_yesterday
         (= balance_ieri_mezzanotte - 100.000€)
       - Se profit oggi >= limite → chiude trade in profitto, stop nuovi
       - profit_cumulated_yesterday aggiornato ogni notte

    4. PROFIT TARGET (10% = 110.000€)
       - Se balance_prop >= 110.000€ → scenario inatteso, attiva consistency
         aggressiva per non violare la regola
    ─────────────────────────────────────────────────────────────────

    Il balance iniziale fisso è sempre 100.000€.
    """

    PROP_INITIAL_BALANCE: float = 100_000.0
    DAILY_DD_SAFETY:      float = 0.027   # 2.7% soglia sicurezza (limite reale 3%)
    TOTAL_DD_SAFETY:      float = 0.095   # 9.5% soglia sicurezza (limite reale 10%)
    TOTAL_DD_WARN:        float = 0.085   # 8.5% → entra in FINAL PHASE (avviso)
    PROFIT_TARGET:        float = 0.10    # 10% = 110.000€

    def __init__(self, state_file: str = "ftmo_state.json"):
        self.state_file = Path(state_file)
        self.state      = self._load_state()
        self.log        = logging.getLogger("FTMORiskManager")
        self._today     = self._today_str()

    # ── Persistenza ──────────────────────────────────────────────────────────
    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self) -> FTMOState:
        if not self.state_file.exists():
            s = FTMOState(last_update_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            self._save_state(s)
            return s
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return FTMOState(**data)
        except Exception:
            return FTMOState(last_update_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def _save_state(self, state: FTMOState):
        # Scrittura atomica per evitare PermissionError
        tmp = self.state_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except PermissionError:
            pass  # Riprova al prossimo ciclo

    # ── Aggiornamento giornaliero (chiamato ad ogni ciclo) ───────────────────
    def daily_update(self, current_prop_balance: float):
        """
        Controlla se è cambiato il giorno.
        Se sì, aggiorna:
          - midnight_balance_yesterday = balance corrente (proxy mezzanotte)
          - peak_midnight_balance = max(peak, balance corrente)  [solo sale]
          - profit_cumulated_yesterday = balance corrente - 100.000€
          - last_update_date = oggi
        """
        today = self._today_str()
        if today == self.state.last_update_date:
            return  # Già aggiornato oggi

        self.log.info(
            f"Nuovo giorno rilevato ({today}). "
            f"Aggiorno stato FTMO. Balance prop attuale: {current_prop_balance:.2f}€"
        )

        # Peak midnight balance: solo sale, mai scende
        new_peak = max(self.state.peak_midnight_balance, current_prop_balance)

        # Profit cumulato fino a ieri (base consistency rule)
        profit_yesterday = max(0.0, current_prop_balance - self.PROP_INITIAL_BALANCE)

        self.state.midnight_balance_yesterday = current_prop_balance
        self.state.peak_midnight_balance      = new_peak
        self.state.profit_cumulated_yesterday = profit_yesterday
        self.state.last_update_date           = today
        self._today = today

        self._save_state(self.state)
        self.log.info(
            f"FTMO State aggiornato → "
            f"midnight_bal={current_prop_balance:.2f}€ | "
            f"peak={new_peak:.2f}€ | "
            f"profit_ieri={profit_yesterday:.2f}€"
        )

    # ── Check Daily Drawdown ─────────────────────────────────────────────────
    def check_daily_dd(self, prop_equity: float) -> Tuple[bool, float, float]:
        """
        Verifica il Daily Drawdown.
        Restituisce: (violazione, equity_limit, dd_usato_pct)
        """
        limit = self.state.midnight_balance_yesterday * (1.0 - self.DAILY_DD_SAFETY)
        dd_used = (self.state.midnight_balance_yesterday - prop_equity) / \
                   self.state.midnight_balance_yesterday
        violated = prop_equity < limit
        if violated:
            self.log.warning(
                f"DAILY DD LIMIT RAGGIUNTO! "
                f"equity={prop_equity:.2f} < limit={limit:.2f} | "
                f"DD usato={dd_used:.2%}"
            )
        return violated, limit, dd_used

    # ── Check Total Drawdown ─────────────────────────────────────────────────
    def check_total_dd(self, prop_equity: float) -> Tuple[bool, bool, float, float]:
        """
        Verifica il Max Total Drawdown.
        Restituisce: (violazione_hard, warning_final_phase, equity_limit, dd_usato_pct)
        """
        limit_hard = self.state.peak_midnight_balance * (1.0 - self.TOTAL_DD_SAFETY)
        limit_warn = self.state.peak_midnight_balance * (1.0 - self.TOTAL_DD_WARN)
        dd_used    = (self.state.peak_midnight_balance - prop_equity) / \
                      self.state.peak_midnight_balance

        violated    = prop_equity < limit_hard
        final_phase = prop_equity < limit_warn

        if violated:
            self.log.warning(
                f"TOTAL DD LIMIT RAGGIUNTO! "
                f"equity={prop_equity:.2f} < limit={limit_hard:.2f} | "
                f"DD usato={dd_used:.2%}"
            )
        elif final_phase:
            self.log.info(
                f"FINAL PHASE attivata. "
                f"equity={prop_equity:.2f} | limit_hard={limit_hard:.2f} | "
                f"DD usato={dd_used:.2%}"
            )

        return violated, final_phase, limit_hard, dd_used

    # ── Check Consistency Rule ───────────────────────────────────────────────
    def check_consistency(self, current_prop_balance: float) -> Tuple[bool, float, float]:
        """
        Verifica la Consistency Rule.

        Logica:
          profit_oggi = balance_attuale - midnight_balance_yesterday
          limite_oggi = profit_cumulated_yesterday
                        (= profit accumulato fino a ieri, calcolato su base 100k)

        Se profit_oggi >= limite_oggi → violazione imminente → stop trade prop.

        Caso speciale: se profit_cumulated_yesterday == 0 (primo giorno di trading),
        la consistency rule non si applica perché non c'è ancora un profitto storico.

        Restituisce: (violazione, profit_oggi, limite_giornaliero)
        """
        profit_oggi = current_prop_balance - self.state.midnight_balance_yesterday

        # Primo giorno: nessun limite di consistenza applicabile
        if self.state.profit_cumulated_yesterday <= 0:
            return False, profit_oggi, float("inf")

        limite = self.state.profit_cumulated_yesterday
        violated = profit_oggi >= limite

        if violated:
            self.log.warning(
                f"CONSISTENCY RULE: profit oggi {profit_oggi:.2f}€ >= "
                f"limite {limite:.2f}€ (profit cumulato ieri). "
                f"Stop nuovi trade sulla Prop."
            )

        return violated, profit_oggi, limite

    # ── Check Profit Target ──────────────────────────────────────────────────
    def check_profit_target(self, current_prop_balance: float) -> bool:
        """
        Verifica se la Prop ha raggiunto il profit target (110.000€).
        Scenario improbabile — vogliamo bruciare la Prop — ma gestito.
        """
        target = self.PROP_INITIAL_BALANCE * (1.0 + self.PROFIT_TARGET)
        reached = current_prop_balance >= target
        if reached:
            self.log.warning(
                f"PROFIT TARGET RAGGIUNTO sulla Prop! "
                f"balance={current_prop_balance:.2f}€ >= target={target:.2f}€. "
                f"Stop nuovi trade per non violare consistency."
            )
        return reached

    # ── Metodo principale: can_open_new_trade ────────────────────────────────
    def can_open_new_trade(
        self,
        prop_equity:   float,
        prop_balance:  float,
    ) -> Tuple[bool, str]:
        """
        Punto di ingresso unico: verifica TUTTE le regole FTMO.
        Restituisce (può_aprire, motivo_blocco).

        Ordine di priorità:
          1. Daily DD → blocco immediato
          2. Total DD hard → blocco immediato
          3. Consistency Rule → blocco se prop in profitto
          4. Profit Target → blocco se prop ha superato il target
          5. Total DD warn → lascia aprire ma segnala FINAL PHASE
        """
        # 1. Daily DD
        daily_violated, daily_limit, daily_pct = self.check_daily_dd(prop_equity)
        if daily_violated:
            return False, f"DAILY_DD_LIMIT ({daily_pct:.2%} usato, limit={daily_limit:.0f}€)"

        # 2. Total DD hard
        total_violated, final_phase, total_limit, total_pct = self.check_total_dd(prop_equity)
        if total_violated:
            return False, f"TOTAL_DD_LIMIT ({total_pct:.2%} usato, limit={total_limit:.0f}€)"

        # 3. Consistency Rule
        consistency_violated, profit_oggi, limite_oggi = self.check_consistency(prop_balance)
        if consistency_violated:
            return False, (
                f"CONSISTENCY_RULE (profit oggi {profit_oggi:.0f}€ >= "
                f"limite {limite_oggi:.0f}€)"
            )

        # 4. Profit Target
        if self.check_profit_target(prop_balance):
            return False, f"PROFIT_TARGET_REACHED (balance={prop_balance:.0f}€)"

        # 5. Final Phase: può aprire ma il motore sa che siamo vicini alla fine
        if final_phase:
            return True, "FINAL_PHASE"

        return True, "OK"

    # ── Getters per la dashboard ─────────────────────────────────────────────
    def get_dashboard_data(self, prop_equity: float, prop_balance: float) -> dict:
        """Dati formattati per la dashboard Streamlit."""
        daily_lim   = self.state.midnight_balance_yesterday * (1.0 - self.DAILY_DD_SAFETY)
        total_lim   = self.state.peak_midnight_balance      * (1.0 - self.TOTAL_DD_SAFETY)
        daily_used  = self.state.midnight_balance_yesterday - prop_equity
        total_used  = self.state.peak_midnight_balance      - prop_equity
        daily_pct   = daily_used  / self.state.midnight_balance_yesterday
        total_pct   = total_used  / self.state.peak_midnight_balance
        profit_oggi = prop_balance - self.state.midnight_balance_yesterday
        consistency_limit = self.state.profit_cumulated_yesterday

        return {
            "midnight_balance_yesterday": self.state.midnight_balance_yesterday,
            "peak_midnight_balance":      self.state.peak_midnight_balance,
            "daily_dd_limit":             daily_lim,
            "daily_dd_used_eur":          daily_used,
            "daily_dd_used_pct":          daily_pct,
            "daily_dd_safety_pct":        self.DAILY_DD_SAFETY,
            "total_dd_limit":             total_lim,
            "total_dd_used_eur":          total_used,
            "total_dd_used_pct":          total_pct,
            "total_dd_safety_pct":        self.TOTAL_DD_SAFETY,
            "profit_oggi":                profit_oggi,
            "consistency_limit":          consistency_limit,
            "consistency_ok":             profit_oggi < consistency_limit or consistency_limit <= 0,
            "profit_target":              self.PROP_INITIAL_BALANCE * (1 + self.PROFIT_TARGET),
            "prop_cumulated_profit":      prop_balance - self.PROP_INITIAL_BALANCE,
        }


# ──────────────────────────────────────────────────────────────────────────────
# SMART CONTROLLER
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# FASE 2 LOGGER  —  CSV in tempo reale per analisi successiva
# ──────────────────────────────────────────────────────────────────────────────
import csv
import os

class Fase2Logger:
    """
    Scrive un CSV con snapshot ogni ciclo (10s) quando i trade sono aperti.
    Campi: timestamp, price, pnl_prop, pnl_hedge, rsi_14, atr_14, mom_10,
           dist_sl_prop_pct, dist_tp_prop_pct, fase2_attiva, mode
    """
    def __init__(self, log_dir: str = r"C:\TradinGO_Math\logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.log_dir  = log_dir
        self._file    = None
        self._writer  = None
        self._cur_day = None
        self.log      = logging.getLogger("Fase2Logger")
        self.HEADER   = [
            "timestamp", "sig_id", "mode",
            "price", "pnl_prop", "pnl_hedge",
            "rsi_14", "atr_14", "mom_10",
            "dist_sl_prop_pct", "dist_tp_prop_pct",
            "dist_sl_hedge_pct", "dist_tp_hedge_pct",
            "fase2_attiva", "fase2_trigger_reason",
        ]

    def _rotate(self):
        today = datetime.now().strftime("%Y%m%d")
        if today != self._cur_day:
            if self._file:
                self._file.close()
            path = os.path.join(self.log_dir, f"fase2_{today}.csv")
            new_file = not os.path.exists(path)
            self._file   = open(path, "a", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            if new_file:
                self._writer.writerow(self.HEADER)
            self._cur_day = today

    def write(self, row: dict):
        try:
            self._rotate()
            self._writer.writerow([row.get(k, "") for k in self.HEADER])
            self._file.flush()
        except Exception as e:
            self.log.warning(f"Fase2Logger write error: {e}")

    def close(self):
        if self._file:
            self._file.close()


# ──────────────────────────────────────────────────────────────────────────────
# SMART CONTROLLER  (versione con Fase 2)
# ──────────────────────────────────────────────────────────────────────────────
class SmartController:
    """
    Fase 1 (già implementata):
      - Normal Mode      : monitoraggio passivo.
      - Mitigation       : Reverse Hedge quando hedge perde troppo.
      - Trend Riding     : trailing stop dopo chiusura Prop al SL.

    Fase 2 (nuova):
      - Si attiva quando il prezzo raggiunge il 30% del percorso entry→SL della Prop.
      - Filtri di conferma: RSI allineato >= 40, Momentum 10 barre >= 2.0 punti.
      - SE filtri OK  → cristallizza la situazione:
            * Conto in PROFIT (hedge): trailing stop a 0.5×ATR dal picco corrente.
            * Conto in LOSS   (prop) : nessuna azione aggiuntiva (Fase 1 continua).
      - SE filtri NON OK → nessuna azione (si lascia la Fase 1 senza intervenire).

    NOTA: questi parametri (30%, RSI>=40, MOM10>=2.0, trailing 0.5×ATR) sono
    derivati dall'analisi su 28 trade reali (21-24 aprile 2026). Win rate atteso
    ~59%. Vanno riottimizzati dopo 3-4 giorni di logging con fase2_logger.
    """

    # ── Parametri Fase 2 (da riottimizzare con dati reali) ──────────────────
    FASE2_DIST_SL_PCT     = 0.30   # attiva quando prezzo è al 30% del percorso entry→SL prop
    FASE2_RSI_MIN         = 40.0   # RSI allineato alla direzione hedge >= 40
    FASE2_MOM10_MIN       = 2.0    # Momentum 10 barre nella dir hedge >= 2.0 punti
    FASE2_TRAILING_ATR    = 0.5    # Trailing hedge = 0.5×ATR dal picco

    def __init__(self, config: TradinGoConfig, executor: TradeExecutor, analyzer: MarketAnalyzer):
        self.cfg      = config
        self.executor = executor
        self.analyzer = analyzer
        self.log      = logging.getLogger("SmartController")

        # Stato Fase 2
        self._fase2_attiva         = False
        self._fase2_peak_pnl       = 0.0    # picco PNL hedge raggiunto dopo attivazione
        self._fase2_trailing_sl    = 0.0    # SL calcolato dal trailing Fase 2
        self._fase2_trigger_reason = ""

    # ── Fase 1: check reverse trigger ────────────────────────────────────────
    def check_reverse_trigger(
        self,
        hedge_pnl: float,
        expected_loss: float,
        df: pd.DataFrame,
        original_signal: Signal,
    ) -> bool:
        if expected_loss == 0:
            return False
        loss_pct = abs(hedge_pnl) / abs(expected_loss)
        if loss_pct < self.cfg.reverse_trigger_pct:
            return False
        _, _, vwap, cvd, cvd_trend = self.analyzer.generate_signal(df)
        price = float(df["close"].iloc[-1])
        if original_signal == Signal.BUY:
            confirmed = (price < vwap) and (cvd_trend == "DOWN")
        else:
            confirmed = (price > vwap) and (cvd_trend == "UP")
        if confirmed:
            self.log.warning(
                f"Reverse trigger: loss_pct={loss_pct:.1%} | vwap={vwap:.2f} | cvd_trend={cvd_trend}"
            )
        return confirmed

    # ── Fase 1: trailing stop dopo prop chiusa ────────────────────────────────
    def update_trailing_stop(
        self,
        hedge_ticket: int,
        current_price: float,
        atr: float,
        original_signal: Signal,
    ) -> bool:
        positions = mt5.positions_get(ticket=hedge_ticket)
        if not positions:
            return False
        pos        = positions[0]
        trail_dist = atr * self.cfg.trailing_atr_multiplier
        if original_signal == Signal.BUY:
            new_sl = current_price - trail_dist
            if new_sl > pos.sl:
                return self.executor.modify_sl(hedge_ticket, new_sl)
        else:
            new_sl = current_price + trail_dist
            if new_sl < pos.sl or pos.sl == 0:
                return self.executor.modify_sl(hedge_ticket, new_sl)
        return False

    # ── Fase 1: check breakeven reverse ──────────────────────────────────────
    def check_reverse_breakeven(
        self,
        reverse_ticket: int,
        entry_price: float,
        current_price: float,
        original_signal: Signal,
    ) -> bool:
        tolerance = 0.50
        if abs(current_price - entry_price) <= tolerance:
            self.log.info(f"Reverse Hedge a break-even → chiusura ticket={reverse_ticket}")
            return self.executor.close_position(reverse_ticket)
        return False

    # ── Fase 2: verifica se si deve attivare ─────────────────────────────────
    def check_fase2_trigger(
        self,
        prop_entry: float,
        prop_sl: float,
        prop_signal: Signal,      # direzione PROP (opposta all'hedge)
        current_price: float,
        df: pd.DataFrame,
        atr: float,
    ) -> tuple:
        """
        Restituisce (attiva: bool, reason: str)
        Attiva = True se tutti i filtri passano.
        """
        if self._fase2_attiva:
            return False, "già_attiva"

        sl_dist_total = abs(prop_entry - prop_sl)
        if sl_dist_total == 0:
            return False, "sl_dist_zero"

        # Distanza percorsa verso SL della prop
        if prop_signal == Signal.BUY:
            pct_to_sl = (prop_entry - current_price) / sl_dist_total
        else:
            pct_to_sl = (current_price - prop_entry) / sl_dist_total

        if pct_to_sl < self.FASE2_DIST_SL_PCT:
            return False, f"dist_sl={pct_to_sl:.2f}<{self.FASE2_DIST_SL_PCT}"

        # Calcola indicatori dal df M5
        closes = df["close"].values
        if len(closes) < 14:
            return False, "dati_insufficienti"

        # RSI 14
        delta  = pd.Series(closes).diff()
        gain   = delta.clip(lower=0)
        loss   = (-delta).clip(lower=0)
        avg_g  = gain.ewm(com=13, min_periods=14).mean().iloc[-1]
        avg_l  = loss.ewm(com=13, min_periods=14).mean().iloc[-1]
        rsi    = 100.0 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))

        # Momentum 10 barre
        if len(closes) >= 11:
            mom10 = float(closes[-1] - closes[-11])
        else:
            return False, "dati_mom_insufficienti"

        # Allinea RSI e momentum alla direzione dell'HEDGE
        # hedge è opposto alla prop: se prop=BUY → hedge=SELL
        if prop_signal == Signal.BUY:
            # hedge è SELL → voglio RSI basso (ribassista) e mom10 negativo
            rsi_aligned  = 100.0 - rsi
            mom10_aligned = -mom10
        else:
            # hedge è BUY → voglio RSI alto (rialzista) e mom10 positivo
            rsi_aligned  = rsi
            mom10_aligned = mom10

        if rsi_aligned < self.FASE2_RSI_MIN:
            return False, f"rsi_aligned={rsi_aligned:.1f}<{self.FASE2_RSI_MIN}"

        if mom10_aligned < self.FASE2_MOM10_MIN:
            return False, f"mom10_aligned={mom10_aligned:.2f}<{self.FASE2_MOM10_MIN}"

        reason = (f"FASE2 OK: dist_sl={pct_to_sl:.2f} | rsi_aln={rsi_aligned:.1f} | "
                  f"mom10_aln={mom10_aligned:.2f}")
        return True, reason

    # ── Fase 2: attiva il trailing sull'hedge ────────────────────────────────
    def activate_fase2(self, hedge_pnl: float, atr: float):
        """
        Cristallizza il PNL hedge corrente come picco di partenza.
        Da questo momento in poi il trailing mantiene min questo livello.
        """
        self._fase2_attiva      = True
        self._fase2_peak_pnl    = hedge_pnl
        self._fase2_trailing_sl = hedge_pnl - (atr * self.FASE2_TRAILING_ATR * 0.14 * 10)
        self.log.info(
            f"[FASE2] Attivata! PNL_hedge={hedge_pnl:.2f}$ | "
            f"peak={self._fase2_peak_pnl:.2f}$ | "
            f"trailing_floor={self._fase2_trailing_sl:.2f}$"
        )

    # ── Fase 2: aggiorna trailing e verifica se chiudere hedge ───────────────
    def update_fase2_trailing(
        self,
        hedge_ticket: int,
        hedge_pnl: float,
        current_price: float,
        atr: float,
        original_signal: Signal,
    ) -> bool:
        """
        Aggiorna il picco e controlla se il PNL è sceso sotto il floor.
        Se sì → chiude l'hedge al prezzo corrente (incassa quello che c'è).
        Restituisce True se ha chiuso l'hedge.
        """
        if not self._fase2_attiva:
            return False

        # Aggiorna picco
        if hedge_pnl > self._fase2_peak_pnl:
            self._fase2_peak_pnl    = hedge_pnl
            self._fase2_trailing_sl = hedge_pnl - (atr * self.FASE2_TRAILING_ATR * 0.14 * 10)
            self.log.info(
                f"[FASE2] Nuovo picco: {self._fase2_peak_pnl:.2f}$ | "
                f"floor aggiornato: {self._fase2_trailing_sl:.2f}$"
            )

        # Controlla se il PNL è sceso sotto il floor
        if hedge_pnl < self._fase2_trailing_sl:
            self.log.warning(
                f"[FASE2] PNL {hedge_pnl:.2f}$ sotto floor {self._fase2_trailing_sl:.2f}$ → CHIUDO HEDGE"
            )
            closed = self.executor.close_position(hedge_ticket)
            if closed:
                self._reset_fase2()
            return closed

        return False

    def _reset_fase2(self):
        self._fase2_attiva         = False
        self._fase2_peak_pnl       = 0.0
        self._fase2_trailing_sl    = 0.0
        self._fase2_trigger_reason = ""

    def get_fase2_state(self) -> dict:
        return {
            "attiva":         self._fase2_attiva,
            "peak_pnl":       self._fase2_peak_pnl,
            "trailing_floor": self._fase2_trailing_sl,
            "trigger_reason": self._fase2_trigger_reason,
        }



# ──────────────────────────────────────────────────────────────────────────────
# STATE MANAGER  (invariato)
# ──────────────────────────────────────────────────────────────────────────────
class StateManager:
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self._lock      = threading.Lock()

    def save(self, state: SystemState):
        data = asdict(state)
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            tmp = self.state_file.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(self.state_file)
            except PermissionError:
                pass

    def load(self) -> dict:
        if not self.state_file.exists():
            return {}
        with self._lock:
            return json.loads(self.state_file.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────────
# TRADINGO ENGINE  —  Orchestratore con Fase 2
# ──────────────────────────────────────────────────────────────────────────────
class TradinGoEngine:
    """
    Loop principale. Aggiunto rispetto alla v1:
    - Fase2Logger: scrive CSV con snapshot ogni ciclo
    - check_fase2_trigger in _handle_open_trades
    - update_fase2_trailing ogni ciclo quando Fase 2 è attiva
    - prop_entry / prop_sl salvati all'apertura per calcolo distanza
    """

    def __init__(self, config: TradinGoConfig):
        self.cfg            = config
        self.state          = SystemState()
        self.sm             = StateManager(config.state_file)

        self.prop_conn  = MT5Connector(
            "PROP",
            config.prop_terminal_path,
            config.prop_login, config.prop_password, config.prop_server,
        )
        self.hedge_conn = MT5Connector(
            "HEDGE",
            config.hedge_terminal_path,
            config.hedge_login, config.hedge_password, config.hedge_server,
        )

        self.session_filter = SessionFilter()
        self.analyzer       = MarketAnalyzer(config)
        self.executor       = TradeExecutor(config)
        self.controller     = SmartController(config, self.executor, self.analyzer)
        self.ftmo           = FTMORiskManager()
        self.fase2_logger   = Fase2Logger()

        # Stato trade corrente
        self._prop_ticket         = 0
        self._hedge_ticket        = 0
        self._reverse_ticket      = 0
        self._original_signal     = Signal.NONE
        self._hedge_expected_loss = 0.0
        self._hedge_realized      = 0.0
        self._running             = False

        # Info prop per Fase 2
        self._prop_entry_price    = 0.0
        self._prop_sl_price       = 0.0
        self._sig_id              = 0      # contatore segnali per log CSV

    def _connect_all(self) -> bool:
        if not self.prop_conn.connect():
            return False
        if not self.hedge_conn.connect():
            return False
        log.info("Entrambi i connettori MT5 attivi.")
        return True

    def _switch_to_prop(self):
        self.prop_conn.connect()

    def _read_prop_account(self):
        self._switch_to_prop()
        info = self.prop_conn.get_account_info()
        if info:
            return info.balance, info.equity, info.equity - info.balance
        return 0.0, 0.0, 0.0

    def _read_hedge_account(self):
        self.hedge_conn.connect()
        info = self.hedge_conn.get_account_info()
        if info:
            return info.balance, info.equity, info.equity - info.balance
        return 0.0, 0.0, 0.0

    def _check_hard_stop(self, hedge_equity: float) -> bool:
        if hedge_equity > 0 and hedge_equity < self.cfg.hedge_floor_equity:
            log.critical(
                f"HARD STOP: hedge equity {hedge_equity:.2f} < floor {self.cfg.hedge_floor_equity:.2f}"
            )
            self._close_all_positions()
            return True
        return False

    def _close_all_positions(self):
        self._switch_to_prop()
        for p in mt5.positions_get(symbol=self.cfg.symbol) or []:
            if p.magic in (self.cfg.magic_prop, self.cfg.magic_reverse):
                self.executor.close_position(p.ticket)
        self.hedge_conn.connect()
        for p in mt5.positions_get(symbol=self.cfg.symbol) or []:
            if p.magic == self.cfg.magic_hedge:
                self.executor.close_position(p.ticket)

    def _no_open_trades(self) -> bool:
        return self._prop_ticket == 0 and self._hedge_ticket == 0

    def _estimate_hedge_expected_loss(self, atr: float) -> float:
        sl_dist_atr = 1.48
        return -(atr * sl_dist_atr * self.cfg.hedge_lot * 10)

    def _handle_open_trades(self, df: pd.DataFrame, hedge_pnl: float, hedge_equity: float):
        current_price = float(df["close"].iloc[-1])
        atr_series    = self.analyzer.compute_atr(df)
        atr           = float(atr_series.iloc[-1])

        # ── Calcola indicatori per log CSV ────────────────────────────────
        closes = df["close"].values
        delta  = pd.Series(closes).diff()
        gain   = delta.clip(lower=0)
        loss   = (-delta).clip(lower=0)
        avg_g  = gain.ewm(com=13, min_periods=14).mean().iloc[-1]
        avg_l  = loss.ewm(com=13, min_periods=14).mean().iloc[-1]
        rsi14  = 100.0 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))
        mom10  = float(closes[-1] - closes[-11]) if len(closes) >= 11 else 0.0

        # ── PNL prop corrente ─────────────────────────────────────────────
        self._switch_to_prop()
        prop_positions = mt5.positions_get(ticket=self._prop_ticket)
        prop_open      = bool(prop_positions) if self._prop_ticket > 0 else False
        prop_pnl       = float(prop_positions[0].profit) if prop_open else 0.0

        # ── Distanze da SL/TP ─────────────────────────────────────────────
        dist_sl_prop_pct  = ""
        dist_tp_prop_pct  = ""
        dist_sl_hedge_pct = ""
        dist_tp_hedge_pct = ""

        if prop_open and self._prop_entry_price > 0 and self._prop_sl_price > 0:
            sl_dist = abs(self._prop_entry_price - self._prop_sl_price)
            if self._original_signal == Signal.SELL:  # prop è SELL (verso SL in salita)
                pct_sl = (current_price - self._prop_entry_price) / sl_dist
            else:
                pct_sl = (self._prop_entry_price - current_price) / sl_dist
            dist_sl_prop_pct = f"{pct_sl:.3f}"

        self.hedge_conn.connect()
        hedge_positions = mt5.positions_get(ticket=self._hedge_ticket)
        if hedge_positions:
            hp = hedge_positions[0]
            if hp.sl > 0:
                sl_h = abs(hp.price_open - hp.sl)
                if hp.type == mt5.ORDER_TYPE_BUY:
                    dist_sl_hedge_pct = f"{(hp.price_open - current_price)/sl_h:.3f}"
                    dist_tp_hedge_pct = f"{(current_price - hp.price_open)/sl_h:.3f}" if hp.tp > 0 else ""
                else:
                    dist_sl_hedge_pct = f"{(current_price - hp.price_open)/sl_h:.3f}"

        # ── Fase 2: check trigger ─────────────────────────────────────────
        fase2_attiva  = False
        fase2_reason  = ""
        if (prop_open and self._prop_entry_price > 0
                and self._prop_sl_price > 0
                and not self.controller._fase2_attiva
                and self.state.mode == SystemMode.NORMAL):

            attiva, reason = self.controller.check_fase2_trigger(
                prop_entry    = self._prop_entry_price,
                prop_sl       = self._prop_sl_price,
                prop_signal   = self._original_signal,
                current_price = current_price,
                df            = df,
                atr           = atr,
            )
            if attiva:
                self.controller._fase2_trigger_reason = reason
                self.controller.activate_fase2(hedge_pnl, atr)
                self.state.mode = SystemMode.TREND_RIDING
                log.info(f"[FASE2] {reason}")
            else:
                fase2_reason = reason

        # ── Fase 2: trailing attivo ───────────────────────────────────────
        if self.controller._fase2_attiva and self._hedge_ticket > 0:
            fase2_attiva = True
            chiuso = self.controller.update_fase2_trailing(
                self._hedge_ticket, hedge_pnl, current_price, atr, self._original_signal
            )
            if chiuso:
                self._hedge_ticket    = 0
                self._original_signal = Signal.NONE
                self.state.mode       = SystemMode.IDLE
                log.info("[FASE2] Hedge chiuso dal trailing Fase 2.")

        # ── Fase 1: prop chiusa → Trend Riding classico ───────────────────
        if self._prop_ticket > 0 and not prop_open:
            log.info("Prop chiusa (SL). Attivo Trend Riding Fase 1 sull'Hedge.")
            self._prop_ticket         = 0
            self.state.mode           = SystemMode.TREND_RIDING
            self.state.trailing_active = True
            self.controller._reset_fase2()  # Fase 2 non più rilevante

        if self.state.mode == SystemMode.TREND_RIDING and self._hedge_ticket > 0:
            if not self.controller._fase2_attiva:  # solo se Fase 2 non ha già gestito
                self.hedge_conn.connect()
                self.controller.update_trailing_stop(
                    self._hedge_ticket, current_price, atr, self._original_signal
                )

        # ── Fase 1: reverse hedge ─────────────────────────────────────────
        if (self._hedge_ticket > 0
                and self._reverse_ticket == 0
                and self.state.mode == SystemMode.NORMAL):
            self.hedge_conn.connect()
            hedge_pos2 = mt5.positions_get(ticket=self._hedge_ticket)
            hedge_pnl2 = float(hedge_pos2[0].profit) if hedge_pos2 else hedge_pnl
            should_reverse = self.controller.check_reverse_trigger(
                hedge_pnl2, self._hedge_expected_loss, df, self._original_signal
            )
            if should_reverse:
                self.state.mode = SystemMode.MITIGATION
                tick = self.executor.open_reverse_hedge(self._original_signal, atr)
                if tick:
                    self._reverse_ticket      = tick
                    self._reverse_entry_price = current_price
                    self.state.reverse_active = True
                    log.info(f"Reverse Hedge aperto → ticket={tick}")

        # ── Fase 1: check BE reverse ──────────────────────────────────────
        if self._reverse_ticket > 0 and self._reverse_entry_price > 0:
            rev_pos = mt5.positions_get(ticket=self._reverse_ticket)
            if rev_pos:
                rev_pnl = float(rev_pos[0].profit)
                if rev_pnl > 0:
                    closed = self.controller.check_reverse_breakeven(
                        self._reverse_ticket, self._reverse_entry_price,
                        current_price, self._original_signal
                    )
                    if closed:
                        self._reverse_ticket      = 0
                        self.state.reverse_active = False
                        self._hedge_realized      += rev_pnl
            else:
                self._reverse_ticket      = 0
                self.state.reverse_active = False

        # ── Check hedge chiuso ────────────────────────────────────────────
        self.hedge_conn.connect()
        if self._hedge_ticket > 0:
            hedge_pos3 = mt5.positions_get(ticket=self._hedge_ticket)
            if not hedge_pos3:
                log.info("Hedge chiuso (SL/TP naturale).")
                self._hedge_ticket    = 0
                self._original_signal = Signal.NONE
                self.state.mode       = SystemMode.IDLE
                self.controller._reset_fase2()

        # ── Scrivi riga CSV Fase 2 ────────────────────────────────────────
        f2state = self.controller.get_fase2_state()
        self.fase2_logger.write({
            "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sig_id":            self._sig_id,
            "mode":              self.state.mode,
            "price":             f"{current_price:.2f}",
            "pnl_prop":          f"{prop_pnl:.2f}",
            "pnl_hedge":         f"{hedge_pnl:.2f}",
            "rsi_14":            f"{rsi14:.1f}",
            "atr_14":            f"{atr:.3f}",
            "mom_10":            f"{mom10:.2f}",
            "dist_sl_prop_pct":  dist_sl_prop_pct,
            "dist_tp_prop_pct":  dist_tp_prop_pct,
            "dist_sl_hedge_pct": dist_sl_hedge_pct,
            "dist_tp_hedge_pct": dist_tp_hedge_pct,
            "fase2_attiva":      "1" if fase2_attiva else "0",
            "fase2_trigger_reason": f2state["trigger_reason"] or fase2_reason,
        })

    def _update_state(self):
        prop_bal, prop_eq, prop_pnl   = self._read_prop_account()
        hedge_bal, hedge_eq, hedge_pnl = self._read_hedge_account()

        self.state.prop_balance     = prop_bal
        self.state.prop_equity      = prop_eq
        self.state.prop_pnl_float   = prop_pnl
        self.state.hedge_balance    = hedge_bal
        self.state.hedge_equity     = hedge_eq
        self.state.hedge_pnl_float  = hedge_pnl
        self.state.floor_distance   = hedge_eq - self.cfg.hedge_floor_equity
        self.state.net_system_profit = self._hedge_realized + hedge_pnl - self.cfg.prop_cost_eur
        self.state.hedge_realized_profit = self._hedge_realized
        self.state.prop_ticket      = self._prop_ticket
        self.state.hedge_ticket     = self._hedge_ticket
        self.state.reverse_ticket   = self._reverse_ticket
        self.state.hedge_expected_loss = self._hedge_expected_loss
        self.state.prop_connected   = self.prop_conn.is_connected
        self.state.hedge_connected  = self.hedge_conn.is_connected

        if prop_bal > 0:
            ftmo_data = self.ftmo.get_dashboard_data(prop_eq, prop_bal)
            self.state.ftmo_daily_dd_pct       = ftmo_data["daily_dd_used_pct"]
            self.state.ftmo_total_dd_pct       = ftmo_data["total_dd_used_pct"]
            self.state.ftmo_daily_dd_limit     = ftmo_data["daily_dd_limit"]
            self.state.ftmo_total_dd_limit     = ftmo_data["total_dd_limit"]
            self.state.ftmo_profit_oggi        = ftmo_data["profit_oggi"]
            self.state.ftmo_consistency_limit  = ftmo_data["consistency_limit"]
            self.state.ftmo_consistency_ok     = ftmo_data["consistency_ok"]

        self.sm.save(self.state)

    def run(self):
        log.info("═══ TradinGo Asymmetric System v2 (Fase 2) — AVVIO ═══")

        if not self._connect_all():
            log.error("Impossibile connettersi ai terminali MT5. Esco.")
            return

        self._running = True

        while self._running:
            try:
                self.prop_conn.connect()
                prop_info_quick = self.prop_conn.get_account_info()
                if prop_info_quick:
                    self.ftmo.daily_update(prop_info_quick.balance)

                df = self.analyzer.get_rates(200)
                if df is None:
                    time.sleep(self.cfg.loop_interval_sec)
                    continue

                spread_ok, spread_pts = self.analyzer.is_spread_ok()
                self.state.spread_ok     = spread_ok
                self.state.spread_points = spread_pts

                _, hedge_eq, hedge_pnl = self._read_hedge_account()
                if self._check_hard_stop(hedge_eq):
                    break

                atr_series = self.analyzer.compute_atr(df)
                atr        = float(atr_series.iloc[-1])
                z_score    = self.analyzer.compute_atr_zscore(df)
                vwap       = self.analyzer.compute_vwap(df)
                cvd, cvd_t = self.analyzer.compute_cvd(df)

                self.state.atr_zscore = z_score
                self.state.vwap       = vwap
                self.state.cvd        = cvd
                self.state.cvd_trend  = cvd_t

                sess_active, sess_name = self.session_filter.is_active()
                next_sess = self.session_filter.next_session()
                self.state.session_active = sess_active
                self.state.session_name   = sess_name
                self.state.next_session   = next_sess

                spread_status = "✓ OK" if spread_ok else f"✗ BLOCCATO ({spread_pts}pts)"
                log.info(
                    f"Ciclo → sess={sess_name} | spread={spread_pts}pts [{spread_status}] | "
                    f"Z={z_score:.2f} | VWAP={vwap:.2f} | CVD={cvd:.0f} [{cvd_t}]"
                )

                prop_bal_now = prop_info_quick.balance if prop_info_quick else 0.0
                prop_eq_now  = prop_info_quick.equity  if prop_info_quick else 0.0
                ftmo_can, ftmo_reason = self.ftmo.can_open_new_trade(prop_eq_now, prop_bal_now)

                self.state.ftmo_can_trade    = ftmo_can
                self.state.ftmo_block_reason = ftmo_reason
                self.state.ftmo_final_phase  = (ftmo_reason == "FINAL_PHASE")

                if not ftmo_can:
                    log.warning(f"FTMO BLOCK: {ftmo_reason}")

                # ── Apertura nuovi trade ──────────────────────────────────
                if self._no_open_trades() and spread_ok and ftmo_can:
                    signal, z, _, _, _ = self.analyzer.generate_signal(df)
                    self.state.last_signal = signal

                    if signal != Signal.NONE:
                        log.info(f"Segnale {signal} | Z={z:.2f} | VWAP={vwap:.2f}")

                        time.sleep(random.randint(
                            self.cfg.jitter_min_ms, self.cfg.jitter_max_ms) / 1000.0
                        )

                        self.prop_conn.connect()
                        p_ticket = self.executor.open_prop_trade(signal, atr)

                        time.sleep(random.randint(
                            self.cfg.jitter_min_ms, self.cfg.jitter_max_ms) / 1000.0
                        )

                        self.hedge_conn.connect()
                        h_ticket = self.executor.open_hedge_trade(signal, atr)

                        if p_ticket and h_ticket:
                            self._prop_ticket         = p_ticket
                            self._hedge_ticket        = h_ticket
                            self._original_signal     = signal
                            self._hedge_expected_loss = self._estimate_hedge_expected_loss(atr)
                            self.state.mode           = SystemMode.NORMAL
                            self._sig_id             += 1

                            # ── Salva entry e SL prop per Fase 2 ─────────
                            self._switch_to_prop()
                            p_pos = mt5.positions_get(ticket=p_ticket)
                            if p_pos:
                                self._prop_entry_price = p_pos[0].price_open
                                self._prop_sl_price    = p_pos[0].sl
                            else:
                                self._prop_entry_price = 0.0
                                self._prop_sl_price    = 0.0

                            log.info(
                                f"Trade aperti → Prop={p_ticket} | Hedge={h_ticket} | "
                                f"prop_entry={self._prop_entry_price:.2f} | "
                                f"prop_sl={self._prop_sl_price:.2f} | "
                                f"sig_id={self._sig_id}"
                            )
                        else:
                            if p_ticket:
                                self.executor.close_position(p_ticket)
                            if h_ticket:
                                self.executor.close_position(h_ticket)
                            log.error("Apertura coppia fallita, posizioni annullate.")

                # ── Gestione trade aperti ─────────────────────────────────
                elif not self._no_open_trades():
                    self.hedge_conn.connect()
                    self._handle_open_trades(df, hedge_pnl, hedge_eq)

                self._update_state()
                time.sleep(self.cfg.loop_interval_sec)

            except KeyboardInterrupt:
                log.info("Interruzione manuale. Esco.")
                self._running = False

            except Exception as e:
                log.error(f"Errore nel loop: {e}", exc_info=True)
                self.state.last_error = str(e)
                self.prop_conn.reconnect()
                self.hedge_conn.reconnect()
                time.sleep(self.cfg.loop_interval_sec * 2)

        log.info("TradinGo Engine v2 fermato.")
        self.fase2_logger.close()
        self.prop_conn.disconnect()


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    config = TradinGoConfig(
        prop_terminal_path  = r"C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe",
        hedge_terminal_path = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe",

        prop_login    = 1610077148,
        prop_password = "4h!R9TkJ",
        prop_server   = "STARTRADERFinancial-Demo",

        hedge_login    = 843409,
        hedge_password = "v!34bIbx",
        hedge_server   = "UltimaMarkets-Demo",

        symbol = "XAUUSD",
    )

    engine = TradinGoEngine(config)
    engine.run()
