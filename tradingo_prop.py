import time, sqlite3, os, pandas as pd, numpy as np
import MetaTrader5 as mt5
from tsentry_config import get_tsentry_db_path

# --- CONFIGURAZIONE v3.5.3 (Cross-Back Window + Fase 2 Fix) ---
DB_PATH = get_tsentry_db_path()
PROP_PATH = "C:/Program Files/STARTRADER Financial MetaTrader 5/terminal64.exe"
SYMBOL, LOT_SIZE, MAGIC_PROP = "XAUUSD", 0.30, 1610077148
MAX_SPREAD_POINTS = 80
MAX_DD_PERCENT = 0.025
CROSSBACK_WINDOW_CANDLES = 6  # Cross-Back valido per 6 candele M5 = 30 minuti

# ============ DATABASE ============
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS state 
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

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
            try:
                return float(val) if '.' in val else int(val)
            except:
                return val
        return default
    except:
        return default

def db_reset():
    for k in ['signal', 'strategy', 'signal_id', 'hedge_ready', 'hedge_ticket',
              'hedge_entry_price', 'hedge_sl_set', 'prop_ticket', 'prop_entry_price',
              'prop_sl_set', 'fase2_attiva', 'atr',
              'crossback_direction', 'crossback_time']:
        db_set(k, 'None')
    for k in ['hedge_ready', 'hedge_sl_set', 'prop_sl_set', 'fase2_attiva']:
        db_set(k, 'False')
    db_set('prop_ticket', 0)
    db_set('hedge_ticket', 0)

# ============ INDICATORI ============
def get_atr_m5():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 14)
    if rates is not None and len(rates) > 0:
        df = pd.DataFrame(rates)
        return float((df['high'] - df['low']).mean())
    return 2.5

def get_rsi(timeframe, period=7, count=50):
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, count)
    if rates is None or len(rates) < period + 1:
        return None
    df = pd.DataFrame(rates)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_ema50_m15():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 60)
    if rates is None or len(rates) < 50:
        return None
    df = pd.DataFrame(rates)
    ema = df['close'].ewm(span=50, adjust=False).mean()
    return float(ema.iloc[-1])

def check_crossback_m5():
    """
    Verifica se c'è stato un Cross-Back RSI M5 nelle ultime CROSSBACK_WINDOW_CANDLES candele.
    Restituisce la direzione ('SELL' o 'BUY') e il timestamp della candela del cross,
    oppure (None, None) se non trovato.
    """
    rsi_m5 = get_rsi(mt5.TIMEFRAME_M5, period=7, count=50)
    if rsi_m5 is None or len(rsi_m5) < CROSSBACK_WINDOW_CANDLES + 2:
        return None, None

    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 50)
    if rates is None:
        return None, None

    # Scansiona le ultime CROSSBACK_WINDOW_CANDLES candele (dalla più recente alla più vecchia)
    for i in range(1, CROSSBACK_WINDOW_CANDLES + 1):
        idx_now = len(rsi_m5) - i
        idx_prev = idx_now - 1
        if idx_prev < 0:
            break

        r_now = rsi_m5.iloc[idx_now]
        r_prev = rsi_m5.iloc[idx_prev]

        # Cross-Back SELL: RSI era > 80, ora < 75
        if r_prev > 80 and r_now < 75:
            cross_time = int(rates[idx_now]['time'])
            return "SELL", cross_time

        # Cross-Back BUY: RSI era < 20, ora > 25
        if r_prev < 20 and r_now > 25:
            cross_time = int(rates[idx_now]['time'])
            return "BUY", cross_time

    return None, None

# ============ SEGNALI (Setup 2 v3.5.3 — Cross-Back Window) ============
def check_signals():
    """
    Setup 2 v3.5.3:
    - Trigger: RSI(7) M5 Cross-Back 80/20 con FINESTRA di 30 minuti (6 candele M5)
    - Filtro: RSI(7) M15 > 65 (SELL) / < 35 (BUY)
    - Bussola: EMA50 M15 bloccante
    - BYPASS: Se RSI(7) M15 > 80 → SELL senza EMA
              Se RSI(7) M15 < 20 → BUY senza EMA
    """
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None or tick.ask == 0:
        return None, None

    # Filtro Spread
    spread = (tick.ask - tick.bid) / info.point
    if spread > MAX_SPREAD_POINTS:
        return None, None

    # Cross-Back M5 con finestra temporale
    cb_direction, cb_time = check_crossback_m5()
    if cb_direction is None:
        return None, None

    # Verifica che il Cross-Back non sia troppo vecchio (30 minuti = 1800 secondi)
    now_ts = int(time.time())
    if cb_time and (now_ts - cb_time) > 1800:
        return None, None

    # RSI M15 (Filtro conferma + Bypass)
    rsi_m15 = get_rsi(mt5.TIMEFRAME_M15, period=7, count=50)
    if rsi_m15 is None:
        return None, None
    rsi_m15_now = rsi_m15.iloc[-1]

    # EMA 50 M15 (Bussola)
    ema50 = get_ema50_m15()
    if ema50 is None:
        return None, None

    current_price = tick.bid

    # --- SEGNALE SELL ---
    if cb_direction == "SELL":
        if rsi_m15_now > 65:
            # BYPASS: RSI M15 > 80 → ignora EMA
            if rsi_m15_now > 80:
                print(f"⚠️ BYPASS EMA: SELL con RSI M15 = {rsi_m15_now:.1f} (estremo) | Cross-Back {int((now_ts - cb_time)/60)} min fa")
                return "SELL", "MR-M5-BYPASS"
            # Normale: prezzo SOTTO EMA50
            elif current_price < ema50:
                print(f"✅ SELL standard: RSI M15 = {rsi_m15_now:.1f} | Cross-Back {int((now_ts - cb_time)/60)} min fa")
                return "SELL", "MR-M5"

    # --- SEGNALE BUY ---
    if cb_direction == "BUY":
        if rsi_m15_now < 35:
            # BYPASS: RSI M15 < 20 → ignora EMA
            if rsi_m15_now < 20:
                print(f"⚠️ BYPASS EMA: BUY con RSI M15 = {rsi_m15_now:.1f} (estremo) | Cross-Back {int((now_ts - cb_time)/60)} min fa")
                return "BUY", "MR-M5-BYPASS"
            # Normale: prezzo SOPRA EMA50
            elif current_price > ema50:
                print(f"✅ BUY standard: RSI M15 = {rsi_m15_now:.1f} | Cross-Back {int((now_ts - cb_time)/60)} min fa")
                return "BUY", "MR-M5"

    return None, None

# ============ ESECUZIONE ============
def open_prop_trade(signal, atr):
    """Apre trade CONTRARIAN con SL/TP dinamici a 1.0x ATR"""
    prop_dir = "BUY" if signal == "SELL" else "SELL"
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None, None

    sl_dist = atr * 1.0
    tp_dist = atr * 1.0

    if prop_dir == "BUY":
        price = tick.ask
        sl = price - sl_dist
        tp = price + tp_dist
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + sl_dist
        tp = price - tp_dist
        order_type = mt5.ORDER_TYPE_SELL

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": float(LOT_SIZE),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "magic": MAGIC_PROP,
        "comment": "Prop v3.5.3",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        time.sleep(0.5)
        pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_PROP)
        entry = pos[0].price_open if pos else res.price
        print(f"✅ PROP APERTA: {res.order} @ {entry} | SL: {sl:.2f} | TP: {tp:.2f}")
        return res.order, entry
    else:
        print(f"❌ PROP ERRORE: {res.comment} (Codice: {res.retcode})")
    return None, None

# ============ LOOP PRINCIPALE ============
def run_prop_engine():
    init_db()
    print("--- TradinGo Prop v3.5.3 (Cross-Back Window 30min + Bypass RSI M15) ---")
    if not mt5.initialize(path=PROP_PATH):
        print(f"Errore MT5: {mt5.last_error()}")
        return

    ciclo = 0
    while True:
        ciclo += 1
        # HEARTBEAT: primi 10 cicli + ogni 300 cicli (~5 minuti)
        if ciclo <= 10:
            print(f"[Startup] Ciclo {ciclo} - Prop Monitoring OK")
        elif ciclo % 300 == 0:
            rsi_m5 = get_rsi(mt5.TIMEFRAME_M5, period=7, count=50)
            rsi_m15 = get_rsi(mt5.TIMEFRAME_M15, period=7, count=50)
            ema = get_ema50_m15()
            tick = mt5.symbol_info_tick(SYMBOL)
            info = mt5.symbol_info(SYMBOL)
            spread = (tick.ask - tick.bid) / info.point if tick and info else 999
            r5 = rsi_m5.iloc[-1] if rsi_m5 is not None and len(rsi_m5) > 0 else 0
            r15 = rsi_m15.iloc[-1] if rsi_m15 is not None and len(rsi_m15) > 0 else 0
            ema_val = ema if ema is not None else 0
            price_val = tick.bid if tick else 0

            # Cross-Back status
            cb_dir, cb_ts = check_crossback_m5()
            cb_info = ""
            if cb_dir:
                age_min = int((int(time.time()) - cb_ts) / 60)
                cb_info = f" | 🔄 CB {cb_dir} ({age_min}min fa)"

            # Bypass status
            bypass = ""
            if r15 > 80:
                bypass = " | ⚠️ BYPASS SELL ATTIVO"
            elif r15 < 20:
                bypass = " | ⚠️ BYPASS BUY ATTIVO"

            print(f"[{ciclo}] RSI M5: {r5:.1f} | RSI M15: {r15:.1f} | EMA50: {ema_val:.2f} | Price: {price_val:.2f} | Spread: {spread:.0f}{cb_info}{bypass}")

        try:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None or tick.ask == 0:
                time.sleep(1)
                continue

            # Equity Guard
            acc = mt5.account_info()
            if acc:
                dd = (acc.equity - acc.balance) / acc.balance
                if dd <= -MAX_DD_PERCENT:
                    if ciclo % 30 == 0:
                        print(f"!!! EQUITY GUARD: {dd:.2%} — Nessun nuovo trade !!!")
                    time.sleep(1)
                    continue

            has_pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_PROP)

            # RESET se non ci sono posizioni e non c'è segnale pendente
            if not has_pos and not db_get('signal'):
                if db_get('prop_ticket', 0) != 0:
                    db_reset()
                    print("--- DB Reset: Sistema pronto per nuovi segnali ---")

            # AUTO-RECOVERY: MT5 ha posizione ma DB no
            if has_pos and db_get('prop_ticket', 0) == 0:
                db_set('prop_ticket', has_pos[0].ticket)
                db_set('prop_entry_price', has_pos[0].price_open)

            # 1. RICERCA SEGNALE (con finestra Cross-Back)
            if not has_pos and not db_get('signal'):
                sig, strat = check_signals()
                if sig:
                    atr = get_atr_m5()
                    db_set('signal', sig)
                    db_set('strategy', strat)
                    db_set('signal_id', int(time.time()))
                    db_set('hedge_ready', 'False')
                    db_set('atr', atr)
                    print(f"🎯 SEGNALE: {sig} ({strat}) | ATR: {atr:.2f}")

            # 2. HANDSHAKE: Hedge ha confermato → Apri Prop (Contrarian)
            if db_get('signal') and db_get('hedge_ready', False) and not has_pos:
                current_pos = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_PROP)
                if not current_pos:
                    atr = db_get('atr', 2.5)
                    if isinstance(atr, str):
                        try:
                            atr = float(atr)
                        except:
                            atr = 2.5
                    ticket, entry = open_prop_trade(db_get('signal'), atr)
                    if ticket:
                        db_set('prop_ticket', ticket)
                        db_set('prop_entry_price', entry)

            # 3. FASE 2: Congela SL a Entry + Rimuovi TP (per trailing)
            if db_get('fase2_attiva', False) and has_pos and not db_get('prop_sl_set', False):
                entry = db_get('prop_entry_price', 0)
                if isinstance(entry, str):
                    try:
                        entry = float(entry)
                    except:
                        entry = 0
                if entry > 0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "sl": float(entry),
                        "tp": 0.0,  # Rimuove TP per lasciar correre il trailing
                        "position": has_pos[0].ticket
                    }
                    res = mt5.order_send(req)
                    if res.retcode == mt5.TRADE_RETCODE_DONE:
                        db_set('prop_sl_set', True)
                        print(f"🛡️ FASE 2: Prop SL congelato a {entry:.2f} | TP rimosso")
                    else:
                        print(f"⚠️ FASE 2 Prop Errore: {res.comment} (Codice: {res.retcode})")

        except Exception as e:
            print(f"Errore: {e}")
        time.sleep(1)

if __name__ == "__main__":
    run_prop_engine()
