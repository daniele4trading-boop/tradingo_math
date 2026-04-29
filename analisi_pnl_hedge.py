"""
Analisi PNL realizzato trade hedge — 21-25 aprile
Legge il journal MT5 Ultima Markets e stampa profitto/perdita di ogni trade chiuso
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone

TERMINAL = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
LOGIN    = 843409
PASSWORD = "v!34bIbx"
SERVER   = "UltimaMarkets-Demo"
MAGIC    = 20260002

FROM_DATE = datetime(2026, 4, 21, tzinfo=timezone.utc)
TO_DATE   = datetime(2026, 4, 25, 23, 59, 59, tzinfo=timezone.utc)

# ── Connessione ───────────────────────────────────────────────────────────────
ok = mt5.initialize(path=TERMINAL, login=LOGIN, password=PASSWORD, server=SERVER)
if not ok:
    print(f"Connessione fallita: {mt5.last_error()}")
    exit(1)

info = mt5.account_info()
print(f"Connesso → {info.login} balance={info.balance:.2f}\n")

# ── Scarica storico deal ──────────────────────────────────────────────────────
deals = mt5.history_deals_get(FROM_DATE, TO_DATE)
if deals is None or len(deals) == 0:
    print("Nessuna deal trovata nel periodo.")
    mt5.shutdown()
    exit(0)

# Filtra per magic hedge e solo deal di chiusura (entry=1 = OUT)
hedge_deals = [d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT]

print(f"Deal hedge chiuse trovate: {len(hedge_deals)}\n")
print(f"{'ticket':>12} | {'time':>20} | {'type':>5} | {'volume':>7} | {'price':>8} | {'profit':>8} | {'comment'}")
print("-" * 90)

total_profit = 0.0
for d in sorted(hedge_deals, key=lambda x: x.time):
    tipo = "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL"
    dt   = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{d.ticket:>12} | {dt:>20} | {tipo:>5} | {d.volume:>7.2f} | {d.price:>8.2f} | {d.profit:>8.2f} | {d.comment}")
    total_profit += d.profit

print("-" * 90)
print(f"{'TOTALE PROFIT HEDGE':>50}: {total_profit:>8.2f} $\n")

# ── Focus su sig_id 5 e 18 ────────────────────────────────────────────────────
# Orari di attivazione riding dai log:
# sig_id 5:  attivazione 14:30:17, chiusura 14:30:35 (durata 18s)
# sig_id 18: attivazione 02:13:47, chiusura 02:14:55 (durata 68s)

print("=" * 90)
print("FOCUS: deal nelle finestre temporali di sig_id 5 e 18\n")

finestre = [
    ("sig_id=5",  datetime(2026, 4, 21, 14, 28, 0), datetime(2026, 4, 21, 14, 32, 0)),
    ("sig_id=18", datetime(2026, 4, 23,  2, 12, 0), datetime(2026, 4, 23,  2, 16, 0)),
]

all_deals = [d for d in deals if d.magic == MAGIC]
for label, t_from, t_to in finestre:
    ts_from = t_from.replace(tzinfo=timezone.utc).timestamp()
    ts_to   = t_to.replace(tzinfo=timezone.utc).timestamp()
    subset  = [d for d in all_deals if ts_from <= d.time <= ts_to]
    print(f"--- {label} ({t_from.strftime('%H:%M')} - {t_to.strftime('%H:%M')}) ---")
    if not subset:
        print("  Nessuna deal trovata in questa finestra.")
    for d in sorted(subset, key=lambda x: x.time):
        tipo = "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL"
        entry_lbl = {0: "IN", 1: "OUT", 2: "INOUT"}.get(d.entry, str(d.entry))
        dt = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {dt} | {entry_lbl:>5} | {tipo} | vol={d.volume:.2f} | price={d.price:.2f} | profit={d.profit:.2f} | {d.comment}")
    print()

mt5.shutdown()
print("Fine analisi.")
