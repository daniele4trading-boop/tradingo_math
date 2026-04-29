"""
TradinGO Fase 2 — Logger avanzato
Registra ogni 2s: timestamp, price, pnl_prop, pnl_hedge, rsi_14, atr_14, momentum, dist_sl_prop%, dist_tp_prop%
Da usare in PARALLELO al tradingo_system.py esistente (non lo sostituisce).
Output: fase2_log_YYYYMMDD.csv nella cartella C:\\TradinGO_Math\\logs\\

Installazione:
  1. Copia in C:\\TradinGO_Math\\
  2. Avvia con: python fase2_logger.py
  3. Lascia girare in background (finestra separata)
"""

import MetaTrader5 as mt5
import csv
import os
import time
import math
from datetime import datetime, timezone

# ── Configurazione ─────────────────────────────────────────────────────────────
PROP_TERMINAL  = r"C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe"
PROP_LOGIN     = 1610077148
PROP_PASSWORD  = "4h!R9TkJ"
PROP_SERVER    = "STARTRADERFinancial-Demo"
PROP_MAGIC     = 20260001

HEDGE_TERMINAL = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
HEDGE_LOGIN    = 843409
HEDGE_PASSWORD = "v!34bIbx"
HEDGE_SERVER   = "UltimaMarkets-Demo"
HEDGE_MAGIC    = 20260002

SYMBOL        = "XAUUSD"
INTERVAL_S    = 2       # campionamento ogni 2 secondi
RSI_PERIOD    = 14
ATR_PERIOD    = 14
MOM_PERIOD    = 10      # momentum = close[now] - close[N barre fa] su M1
LOG_DIR       = r"C:\TradinGO_Math\logs"
LOG_PREFIX    = "fase2_log"

# ── Helpers ────────────────────────────────────────────────────────────────────

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 4)

def calc_momentum(closes, period=10):
    if len(closes) < period + 1:
        return None
    return round(closes[-1] - closes[-(period+1)], 4)

def get_positions(magic):
    """Restituisce lista posizioni aperte per un dato magic number."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == magic]

def pnl_totale(positions):
    return sum(p.profit for p in positions)

def dist_pct(pos, field_sl, field_tp, price_bid, price_ask):
    """
    Distanza % del prezzo corrente rispetto a SL e TP.
    Restituisce (dist_sl_pct, dist_tp_pct) — positivo = ancora spazio.
    """
    if pos.type == mt5.ORDER_TYPE_BUY:
        price = price_bid
        sl_dist = (price - pos.sl) / price * 100 if pos.sl > 0 else None
        tp_dist = (pos.tp - price) / price * 100 if pos.tp > 0 else None
    else:  # SELL
        price = price_ask
        sl_dist = (pos.sl - price) / price * 100 if pos.sl > 0 else None
        tp_dist = (price - pos.tp) / price * 100 if pos.tp > 0 else None
    return (
        round(sl_dist, 4) if sl_dist is not None else None,
        round(tp_dist, 4) if tp_dist is not None else None,
    )

# ── Connessione ────────────────────────────────────────────────────────────────

def connect(terminal, login, password, server, label):
    ok = mt5.initialize(path=terminal, login=login, password=password, server=server)
    if not ok:
        print(f"[ERRORE] Connessione {label} fallita: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    print(f"[OK] Connesso {label} → login={info.login} balance={info.balance:.2f}")
    return True

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    # Il logger usa UN solo terminale MT5 alla volta — usiamo quello dell'hedge
    # che ha accesso ai prezzi XAUUSD. La prop viene monitorata tramite il file
    # di stato scritto dal tradingo_system.py esistente.
    # NOTA: mt5.initialize() può essere chiamato solo per un account alla volta.
    # Per leggere i PNL di entrambi, usiamo il trick: connetti hedge, leggi posizioni
    # hedge + price; poi switcha su prop, leggi posizioni prop; poi torna hedge.
    # Questo introduce ~100ms di latenza ma è accettabile per logging a 2s.

    print("=== TradinGO Fase 2 Logger ===")
    print(f"Campionamento ogni {INTERVAL_S}s | Log in {LOG_DIR}")
    print("Premi Ctrl+C per fermare.\n")

    # Buffer prezzi M1 per indicatori tecnici
    m1_closes = []
    m1_highs  = []
    m1_lows   = []
    last_m1_time = None

    csv_path = None
    csv_file = None
    writer   = None

    HEADER = [
        "timestamp", "sig_id_prop", "sig_id_hedge",
        "price_bid", "price_ask", "spread",
        "pnl_prop", "pnl_hedge", "pnl_combined",
        "rsi_14", "atr_14", "momentum_10",
        "dist_sl_prop_pct", "dist_tp_prop_pct",
        "dist_sl_hedge_pct", "dist_tp_hedge_pct",
        "n_pos_prop", "n_pos_hedge",
        "prop_sl", "prop_tp", "prop_entry", "prop_type",
        "hedge_sl", "hedge_tp", "hedge_entry", "hedge_type",
    ]

    try:
        while True:
            loop_start = time.time()
            now = datetime.now()

            # ── Apri/ruota file CSV giornaliero ──────────────────────────────
            day_str = now.strftime("%Y%m%d")
            new_path = os.path.join(LOG_DIR, f"{LOG_PREFIX}_{day_str}.csv")
            if new_path != csv_path:
                if csv_file:
                    csv_file.close()
                csv_path = new_path
                file_exists = os.path.exists(csv_path)
                csv_file = open(csv_path, "a", newline="", encoding="utf-8")
                writer = csv.writer(csv_file)
                if not file_exists:
                    writer.writerow(HEADER)
                print(f"[LOG] File: {csv_path}")

            # ── Connetti HEDGE — leggi price + posizioni hedge ────────────────
            row = {}
            row["timestamp"] = now.strftime("%Y-%m-%d %H:%M:%S")

            hedge_ok = connect(HEDGE_TERMINAL, HEDGE_LOGIN, HEDGE_PASSWORD, HEDGE_SERVER, "HEDGE")
            if hedge_ok:
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick:
                    row["price_bid"] = tick.bid
                    row["price_ask"] = tick.ask
                    row["spread"]    = round(tick.ask - tick.bid, 4)

                # Posizioni hedge
                h_pos = get_positions(HEDGE_MAGIC)
                row["n_pos_hedge"] = len(h_pos)
                row["pnl_hedge"]   = round(pnl_totale(h_pos), 2)

                if h_pos:
                    p = h_pos[0]  # assumiamo 1 posizione attiva
                    row["hedge_sl"]    = p.sl
                    row["hedge_tp"]    = p.tp
                    row["hedge_entry"] = p.price_open
                    row["hedge_type"]  = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                    row["sig_id_hedge"] = p.magic  # magic = 20260002, sig_id nel comment
                    # Estrai sig_id dal comment se disponibile
                    if p.comment and "sig" in p.comment.lower():
                        import re
                        m = re.search(r'sig[_\s]*(\d+)', p.comment, re.I)
                        if m:
                            row["sig_id_hedge"] = int(m.group(1))
                    ds, dt = dist_pct(p, p.sl, p.tp, tick.bid if tick else 0, tick.ask if tick else 0)
                    row["dist_sl_hedge_pct"] = ds
                    row["dist_tp_hedge_pct"] = dt

                # Aggiorna buffer M1 per indicatori
                bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, RSI_PERIOD + MOM_PERIOD + 5)
                if bars is not None and len(bars) > 0:
                    latest_ts = bars[-1][0]
                    if latest_ts != last_m1_time:
                        m1_closes = [b[4] for b in bars]  # close
                        m1_highs  = [b[2] for b in bars]  # high
                        m1_lows   = [b[3] for b in bars]  # low
                        last_m1_time = latest_ts

                row["rsi_14"]      = calc_rsi(m1_closes, RSI_PERIOD)
                row["atr_14"]      = calc_atr(m1_highs, m1_lows, m1_closes, ATR_PERIOD)
                row["momentum_10"] = calc_momentum(m1_closes, MOM_PERIOD)

                mt5.shutdown()

            # ── Connetti PROP — leggi posizioni prop ──────────────────────────
            prop_ok = connect(PROP_TERMINAL, PROP_LOGIN, PROP_PASSWORD, PROP_SERVER, "PROP")
            if prop_ok:
                tick_prop = mt5.symbol_info_tick(SYMBOL)

                p_pos = get_positions(PROP_MAGIC)
                row["n_pos_prop"] = len(p_pos)
                row["pnl_prop"]   = round(pnl_totale(p_pos), 2)

                if p_pos:
                    p = p_pos[0]
                    row["prop_sl"]    = p.sl
                    row["prop_tp"]    = p.tp
                    row["prop_entry"] = p.price_open
                    row["prop_type"]  = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                    row["sig_id_prop"] = p.magic
                    if p.comment:
                        import re
                        m = re.search(r'sig[_\s]*(\d+)', p.comment, re.I)
                        if m:
                            row["sig_id_prop"] = int(m.group(1))
                    # Usa price_bid/ask dell'hedge (stesso asset, broker diverso ma simile)
                    bid = row.get("price_bid", 0)
                    ask = row.get("price_ask", 0)
                    ds, dt = dist_pct(p, p.sl, p.tp, bid, ask)
                    row["dist_sl_prop_pct"] = ds
                    row["dist_tp_prop_pct"] = dt

                mt5.shutdown()

            # ── PNL combined ──────────────────────────────────────────────────
            p_pnl = row.get("pnl_prop", 0) or 0
            h_pnl = row.get("pnl_hedge", 0) or 0
            row["pnl_combined"] = round(p_pnl + h_pnl, 2)

            # ── Scrivi riga CSV ───────────────────────────────────────────────
            csv_row = [row.get(col, "") for col in HEADER]
            writer.writerow(csv_row)
            csv_file.flush()

            # ── Stampa a video sintetica ──────────────────────────────────────
            price_str = f"{row.get('price_bid','?')}"
            rsi_str   = f"RSI={row.get('rsi_14','?')}"
            atr_str   = f"ATR={row.get('atr_14','?')}"
            mom_str   = f"MOM={row.get('momentum_10','?')}"
            pnl_str   = f"PROP={p_pnl:>+8.2f}$ | HEDGE={h_pnl:>+8.2f}$ | COMB={p_pnl+h_pnl:>+8.2f}$"
            print(f"[{row['timestamp']}] {SYMBOL}={price_str} | {rsi_str} {atr_str} {mom_str} | {pnl_str}")

            # ── Attendi prossimo ciclo ────────────────────────────────────────
            elapsed = time.time() - loop_start
            sleep_time = max(0, INTERVAL_S - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[STOP] Logger fermato dall'utente.")
    finally:
        if csv_file:
            csv_file.close()
        try:
            mt5.shutdown()
        except:
            pass
        print(f"[OK] Log salvato in: {csv_path}")

if __name__ == "__main__":
    main()
