import time, sqlite3, os, pandas as pd
import MetaTrader5 as mt5
from tsentry_config import get_tsentry_db_path

# --- CONFIGURAZIONE v3.5.0 ---
DB_PATH = get_tsentry_db_path()
ULTIMA_PATH = "C:/Program Files/Ultima Markets MT5 Terminal/terminal64.exe"
SYMBOL, LOT_SIZE, MAGIC_HEDGE = "XAUUSD", 0.10, 843409
EQUITY_FLOOR = 47550.0
FASE2_ATR_MULTIPLIER = 0.5

# ============ DATABASE ============
def db_set(key, value):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Write Error: {e}")

def db_get(key, default=None):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("SELECT value FROM state WHERE key=?", (key,))
        res = c.fetchone()
        conn.close()
        if res:
            val = res[0]
            if val.lower() == 'true': return True
            if val.lower() == 'false': return False
            if val == 'None' or val == 'none': return None
            try: return float(val) if '.' in val else int(val)
            except: return val
        return default
    except:
        return default

# ============ FUNZIONI ============
def get_atr_m5():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 14)
    if rates is not None and len(rates) > 0:
        df = pd.DataFrame(rates)
        return float((df['high'] - df['low']).mean())
    return 2.5

def get_safe_sl(entry, direction):
    info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if info is None or not hasattr(info, 'stops_level') or tick is None:
        return entry
    min_dist = (info.stops_level + 20) * info.point
    if direction == mt5.ORDER_TYPE_BUY:
        return min(entry, tick.bid - min_dist)
    else:
        return max(entry, tick.ask + min_dist)

def open_hedge_trade(direction, atr):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None, None

    sl_dist = atr * 1.0
    tp_dist = atr * 1.0

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl = price + sl_dist
        tp = price - tp_dist

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "magic": MAGIC_HEDGE,
        "comment": "Hedge v3.5.0",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        time.sleep(0.5)
        pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_HEDGE)
        entry = pos[0].price_open if pos else res.price
        print(f"✅ HEDGE APERTO: {res.order} @ {entry} | SL: {sl:.2f} | TP: {tp:.2f}")
        return res.order, entry
    else:
        print(f"❌ HEDGE ERRORE: {res.comment} (Codice: {res.retcode})")
    return None, None

# ============ LOOP PRINCIPALE ============
def run_hedge_engine():
    print("--- TradinGo Hedge v3.5.0 (Setup B: Trigger 0.5x ATR) ---")
    if not mt5.initialize(path=ULTIMA_PATH):
        print(f"Errore MT5: {mt5.last_error()}")
        return

    ciclo = 0
    while True:
        ciclo += 1
        # HEARTBEAT: primi 10 cicli + ogni 200 cicli (~3 minuti)
        if ciclo <= 10:
            print(f"[Startup] Ciclo {ciclo} - Hedge Monitoring OK")
        elif ciclo % 200 == 0:
            acc = mt5.account_info()
            eq = acc.equity if acc else 0
            print(f"[{ciclo}] Hedge Equity: {eq:.2f} | Signal: {db_get('signal')} | Fase2: {db_get('fase2_attiva', False)}")

        try:
            info = mt5.symbol_info(SYMBOL)
            tick = mt5.symbol_info_tick(SYMBOL)
            if info is None or not hasattr(info, 'stops_level') or tick is None or tick.ask == 0:
                time.sleep(1)
                continue

            acc = mt5.account_info()
            if acc and acc.equity <= EQUITY_FLOOR:
                print(f"!!! EMERGENCY: Equity {acc.equity:.2f} <= Floor {EQUITY_FLOOR} !!!")
                my_pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_HEDGE)
                if my_pos:
                    for p in my_pos:
                        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        close_price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
                        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": p.volume,
                               "type": close_type, "price": close_price, "position": p.ticket,
                               "magic": MAGIC_HEDGE, "type_filling": mt5.ORDER_FILLING_IOC}
                        mt5.order_send(req)
                    print("🚨 TUTTE LE POSIZIONI HEDGE CHIUSE (Floor raggiunto)")
                time.sleep(5)
                continue

            my_pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_HEDGE)
            signal = db_get('signal')

            if signal and not my_pos and not db_get('hedge_ready', False):
                atr = db_get('atr', 2.5)
                if isinstance(atr, str):
                    try: atr = float(atr)
                    except: atr = 2.5
                ticket, entry = open_hedge_trade(signal, atr)
                if ticket:
                    db_set('hedge_ticket', ticket)
                    db_set('hedge_ready', True)
                    db_set('hedge_entry_price', entry)

            if my_pos and not db_get('hedge_ready', False):
                db_set('hedge_ticket', my_pos[0].ticket)
                db_set('hedge_ready', True)
                db_set('hedge_entry_price', my_pos[0].price_open)

            prop_ticket = db_get('prop_ticket', 0)
            if prop_ticket and prop_ticket != 0 and not db_get('fase2_attiva', False):
                entry_prop = db_get('prop_entry_price', 0)
                if isinstance(entry_prop, str):
                    try: entry_prop = float(entry_prop)
                    except: entry_prop = 0

                if entry_prop > 0:
                    atr = get_atr_m5()
                    trigger = FASE2_ATR_MULTIPLIER * atr
                    distanza = abs(tick.bid - entry_prop)

                    if distanza >= trigger:
                        db_set('fase2_attiva', True)
                        print(f"🛡️ FASE 2 ATTIVATA: Distanza {distanza:.2f} >= Trigger {trigger:.2f} (0.5x ATR)")

            if db_get('fase2_attiva', False) and my_pos and not db_get('hedge_sl_set', False):
                hedge_entry = db_get('hedge_entry_price', 0)
                if isinstance(hedge_entry, str):
                    try: hedge_entry = float(hedge_entry)
                    except: hedge_entry = 0

                if hedge_entry > 0:
                    sl = get_safe_sl(hedge_entry, my_pos[0].type)
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "sl": float(sl),
                        "tp": 0.0,
                        "position": my_pos[0].ticket
                    }
                    res = mt5.order_send(req)
                    if res.retcode == mt5.TRADE_RETCODE_DONE:
                        db_set('hedge_sl_set', True)
                        print(f"🛡️ FASE 2: Hedge SL congelato a {sl:.2f} | TP rimosso (trailing)")
                    else:
                        print(f"⚠️ FASE 2 SL Errore: {res.comment} (Codice: {res.retcode})")

        except Exception as e:
            print(f"Errore: {e}")
        time.sleep(1.5)

if __name__ == "__main__":
    run_hedge_engine()
