"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   TRADINGO — TEST SIGNAL INJECTOR                                            ║
║   Inietta un segnale manuale BUY o SELL nel sistema                          ║
║   Calcola ATR reale dal mercato per SL/TP                                    ║
║   Apre i trade su ENTRAMBI i conti (Prop + Hedge)                            ║
║                                                                              ║
║   Uso: python test_signal.py BUY                                             ║
║        python test_signal.py SELL                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import json
import random
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("TEST")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE (stessi valori di prop/hedge)
# ──────────────────────────────────────────────────────────────────────────────
PROP_PATH     = r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
PROP_LOGIN    = 1513075253
PROP_PASSWORD = "$*CS4HIJUr2"
PROP_SERVER   = "FTMO-Demo"
PROP_LOT      = 1.00
MAGIC_PROP    = 20260001

HEDGE_PATH     = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
HEDGE_LOGIN    = 843409
HEDGE_PASSWORD = "v!34bIbx"
HEDGE_SERVER   = "UltimaMarkets-Demo"
HEDGE_LOT      = 0.14
MAGIC_HEDGE    = 20260002

SYMBOL      = "XAUUSD"
ATR_PERIOD  = 14
TIMEFRAME   = mt5.TIMEFRAME_M5
STATE_FILE  = "tradingo_state.json"

JITTER_MIN = 300
JITTER_MAX = 800

# ──────────────────────────────────────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────────────────────────────────────
def jitter():
    time.sleep(random.randint(JITTER_MIN, JITTER_MAX) / 1000.0)

def compute_atr() -> float:
    """Calcola ATR(14) M5 reale dal mercato."""
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 100)
    if rates is None or len(rates) == 0:
        log.warning("Impossibile leggere rates — uso ATR default 10.0")
        return 10.0
    df = pd.DataFrame(rates)
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean().iloc[-1]
    return float(atr)

def open_order(order_type: int, lot: float, sl: float, tp: float, magic: int, stealth: bool = False) -> int:
    """Invia ordine a mercato. Restituisce ticket o 0."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        log.error("symbol_info_tick None")
        return 0

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        magic,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if not stealth:
        request["comment"] = f"TG_TEST_{magic}"

    jitter()
    result = mt5.order_send(request)
    if result is None:
        log.error(f"order_send None: {mt5.last_error()}")
        return 0
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"Ordine rifiutato: retcode={result.retcode} | {result.comment}")
        return 0

    direction = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
    log.info(f"✓ Ordine eseguito → ticket={result.order} | {direction} {lot} lot | price={result.price:.2f} | SL={sl:.2f} | TP={tp:.2f}")
    return result.order

def write_state(signal: str, atr: float, prop_ticket: int, hedge_ticket: int):
    """Scrive stato su file JSON per la dashboard."""
    state = {
        "signal":       signal,
        "signal_id":    1,
        "atr":          atr,
        "prop_ticket":  prop_ticket,
        "prop_closed":  False,
        "hedge_ticket": hedge_ticket,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "test_mode":    True,
    }
    Path(STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")
    log.info(f"State file aggiornato → {STATE_FILE}")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2 or sys.argv[1].upper() not in ("BUY", "SELL"):
        print("\nUso: python test_signal.py BUY")
        print("     python test_signal.py SELL\n")
        sys.exit(1)

    signal = sys.argv[1].upper()
    log.info(f"═══ TEST SIGNAL INJECTOR — Segnale: {signal} ═══")

    # ── STEP 1: Connetti alla PROP (FTMO) e leggi ATR ────────────────────────
    log.info("Connessione alla PROP (FTMO)...")
    ok = mt5.initialize(
        path=PROP_PATH,
        login=PROP_LOGIN,
        password=PROP_PASSWORD,
        server=PROP_SERVER,
    )
    if not ok:
        log.error(f"Connessione PROP fallita: {mt5.last_error()}")
        sys.exit(1)

    info = mt5.account_info()
    log.info(f"PROP connessa → Login:{info.login} | Balance:{info.balance:.2f}")

    # Calcola ATR reale
    atr = compute_atr()
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask if signal == "BUY" else tick.bid
    log.info(f"ATR={atr:.2f} | Prezzo attuale={price:.2f}")

    # ── STEP 2: Calcola SL/TP ────────────────────────────────────────────────
    if signal == "BUY":
        # Prop fa SELL (contrario)
        prop_type = mt5.ORDER_TYPE_SELL
        prop_sl   = price + atr * 1.5
        prop_tp   = price - atr * 3.0
        # Hedge fa BUY (allineato)
        hedge_type = mt5.ORDER_TYPE_BUY
        hedge_sl   = price - atr * 1.5
        hedge_tp   = price + atr * 3.0
    else:  # SELL
        # Prop fa BUY (contrario)
        prop_type = mt5.ORDER_TYPE_BUY
        prop_sl   = price - atr * 1.5
        prop_tp   = price + atr * 3.0
        # Hedge fa SELL (allineato)
        hedge_type = mt5.ORDER_TYPE_SELL
        hedge_sl   = price + atr * 1.5
        hedge_tp   = price - atr * 3.0

    log.info(f"Parametri calcolati:")
    log.info(f"  PROP  → {'SELL' if prop_type==mt5.ORDER_TYPE_SELL else 'BUY'} {PROP_LOT} lot | SL={prop_sl:.2f} | TP={prop_tp:.2f}")
    log.info(f"  HEDGE → {'BUY' if hedge_type==mt5.ORDER_TYPE_BUY else 'SELL'} {HEDGE_LOT} lot | SL={hedge_sl:.2f} | TP={hedge_tp:.2f}")
    log.info(f"  Rischio Prop:  ~{atr*1.5*100:.0f}$ | Target Prop:  ~{atr*3.0*100:.0f}$")
    log.info(f"  Rischio Hedge: ~{atr*1.5*HEDGE_LOT*100:.0f}$ | Target Hedge: ~{atr*3.0*HEDGE_LOT*100:.0f}$")

    # ── STEP 3: Apri trade PROP ───────────────────────────────────────────────
    log.info("Apertura trade PROP...")
    prop_ticket = open_order(prop_type, PROP_LOT, prop_sl, prop_tp, MAGIC_PROP, stealth=True)
    if prop_ticket == 0:
        log.error("Apertura PROP fallita — abbandono")
        mt5.shutdown()
        sys.exit(1)

    # ── STEP 4: Disconnetti PROP e connetti HEDGE ────────────────────────────
    log.info("Disconnessione PROP...")
    mt5.shutdown()
    time.sleep(1.0)

    log.info("Connessione all'HEDGE (UltimaMarkets)...")
    ok = mt5.initialize(
        path=HEDGE_PATH,
        login=HEDGE_LOGIN,
        password=HEDGE_PASSWORD,
        server=HEDGE_SERVER,
    )
    if not ok:
        log.error(f"Connessione HEDGE fallita: {mt5.last_error()}")
        log.warning(f"Trade PROP aperto (ticket={prop_ticket}) ma HEDGE non aperto!")
        sys.exit(1)

    info = mt5.account_info()
    log.info(f"HEDGE connessa → Login:{info.login} | Balance:{info.balance:.2f}")

    # ── STEP 5: Apri trade HEDGE ─────────────────────────────────────────────
    log.info("Apertura trade HEDGE...")
    hedge_ticket = open_order(hedge_type, HEDGE_LOT, hedge_sl, hedge_tp, MAGIC_HEDGE, stealth=False)
    if hedge_ticket == 0:
        log.error("Apertura HEDGE fallita")
    
    mt5.shutdown()

    # ── STEP 6: Scrivi stato su file ─────────────────────────────────────────
    write_state(signal, atr, prop_ticket, hedge_ticket)

    # ── Riepilogo ─────────────────────────────────────────────────────────────
    log.info("═══ RIEPILOGO ═══")
    log.info(f"Segnale   : {signal}")
    log.info(f"ATR       : {atr:.2f}")
    log.info(f"PROP      : ticket={prop_ticket} | {'SELL' if prop_type==mt5.ORDER_TYPE_SELL else 'BUY'} {PROP_LOT} lot")
    log.info(f"HEDGE     : ticket={hedge_ticket} | {'BUY' if hedge_type==mt5.ORDER_TYPE_BUY else 'SELL'} {HEDGE_LOT} lot")
    if prop_ticket > 0 and hedge_ticket > 0:
        log.info("✓ ENTRAMBI I TRADE APERTI — Sistema asimmetrico attivo")
    else:
        log.warning("⚠ Apertura parziale — controlla i terminali MT5")

if __name__ == "__main__":
    main()
