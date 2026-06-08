import time, sqlite3, os, pandas as pd
import MetaTrader5 as mt5
from tsentry_config import get_tsentry_db_path

# --- CONFIGURAZIONE v3.4.0 (SQLITE MODE) -----
DB_PATH = get_tsentry_db_path()
PROP_PATH = "C:/Program Files/STARTRADER Financial MetaTrader 5/terminal64.exe" 
SYMBOL, LOT_SIZE, MAGIC_PROP = "XAUUSD", 1.0, 1610077148

def db_set(key, value):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except: pass

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
            if val == 'None': return None
            try: return float(val) if '.' in val else int(val)
            except: return val
        return default
    except: return default

def check_signals_fast():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 30)
    tick = mt5.symbol_info_tick(SYMBOL)
    if rates is None or len(rates) < 14 or tick is None: return None, None
    df = pd.DataFrame(rates)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    if rsi.iloc[-1] > 85: return "SELL", "FAST-RSI"
    if rsi.iloc[-1] < 15: return "BUY", "FAST-RSI"
    return None, None

def run_prop_engine_fast():
    print("--- TradinGo Prop v3.4.0 FAST (SQLite Mode) ---")
    if not mt5.initialize(path=PROP_PATH):
        print(f"Errore MT5: {mt5.last_error()}")
        return
    
    ciclo = 0
    while True:
        ciclo += 1
        try:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None or tick.ask == 0:
                time.sleep(1); continue

            has_pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_PROP)
            
            # Reset DB se le posizioni sono state chiuse manualmente o da SL
            if not has_pos and not db_get('signal'):
                if db_get('prop_ticket', 0) != 0:
                    for k in ['signal','strategy','fase2_attiva','prop_sl_set','hedge_ready','hedge_sl_set']:
                        db_set(k, 'False' if 'set' in k or 'attiva' in k else 'None')
                    db_set('prop_ticket', 0)
                    print("--- DB Cleaned: Pronto per nuovi segnali ---")

            # Ricerca Segnale
            if not has_pos and not db_get('signal'):
                sig, strat = check_signals_fast()
                if sig:
                    db_set('signal', sig)
                    db_set('strategy', strat)
                    db_set('hedge_ready', 'False')
                    print(f"🎯 SEGNALE RILEVATO: {sig}")

            # Apertura Prop (Handshake via DB)
            if db_get('signal') and db_get('hedge_ready', False) and not has_pos:
                prop_dir = "BUY" if db_get('signal') == "SELL" else "SELL"
                req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": float(LOT_SIZE), "type": mt5.ORDER_TYPE_BUY if prop_dir == "BUY" else mt5.ORDER_TYPE_SELL, "price": tick.ask if prop_dir == "BUY" else tick.bid, "magic": MAGIC_PROP, "comment": "Prop Fast v3.4.0", "type_filling": mt5.ORDER_FILLING_IOC}
                res = mt5.order_send(req)
                if res.retcode == mt5.TRADE_RETCODE_DONE:
                    time.sleep(0.5); pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_PROP)
                    db_set('prop_ticket', res.order)
                    db_set('prop_entry_price', pos[0].price_open if pos else res.price)
                    print(f"✅ PROP APERTA: {res.order} @ {db_get('prop_entry_price')}")

            # Auto-recovery se il DB fosse vuoto ma Startrader ha la posizione
            if has_pos and not db_get('prop_ticket', 0):
                db_set('prop_ticket', has_pos[0].ticket)
                db_set('prop_entry_price', has_pos[0].price_open)

            # Esecuzione SL Prop (Fase 2)
            if db_get('fase2_attiva', False) and has_pos and not db_get('prop_sl_set', False):
                req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL, "sl": float(db_get('prop_entry_price', 0)), "position": has_pos[0].ticket}
                if mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
                    db_set('prop_sl_set', True)
                    print("🛡️ FASE 2: Prop Protected (SL at Entry)")

            if ciclo <= 5: print(f"Heartbeat Prop Ciclo {ciclo} OK")
        except Exception as e: print(f"Loop Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    run_prop_engine_fast()
