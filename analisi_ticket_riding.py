"""
Analisi PNL realizzato per ticket hedge specifici
Cerca i ticket di sig_id 5 e 18 (e tutti i riding) nel journal MT5
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone

TERMINAL = r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe"
LOGIN    = 843409
PASSWORD = "v!34bIbx"
SERVER   = "UltimaMarkets-Demo"
MAGIC    = 20260002

# Mapping completo ticket → sig_id dal log
TICKET_TO_SIG = {
    150519316: (1,  False),
    150613039: (2,  True),
    150811609: (3,  True),
    150866296: (4,  False),
    151155138: (5,  True),   # ← CASO PROBLEMATICO
    151221703: (6,  True),
    151295645: (7,  True),
    151363005: (9,  False),
    151511944: (10, True),
    151823337: (11, False),
    151880102: (12, True),
    152169454: (13, False),
    152360184: (14, False),
    152532183: (15, False),
    152639685: (16, True),
    152697585: (17, True),
    152965140: (18, True),   # ← CASO PROBLEMATICO
    153032918: (19, False),
    153372155: (20, False),
    153548618: (21, False),
    153659334: (22, True),
    153805451: (23, False),
    154043294: (24, False),
    154179547: (25, False),
    154409329: (26, True),
    154474396: (27, True),
    154829826: (28, True),
    155071916: (29, False),
}

# ── Connessione ───────────────────────────────────────────────────────────────
ok = mt5.initialize(path=TERMINAL, login=LOGIN, password=PASSWORD, server=SERVER)
if not ok:
    print(f"Connessione fallita: {mt5.last_error()}")
    exit(1)

info = mt5.account_info()
print(f"Connesso → {info.login} balance={info.balance:.2f}\n")

# ── Scarica tutto lo storico deal ampio ───────────────────────────────────────
from_date = datetime(2026, 4, 20, tzinfo=timezone.utc)
to_date   = datetime(2026, 4, 26, tzinfo=timezone.utc)
deals = mt5.history_deals_get(from_date, to_date)

if deals is None:
    print("Nessuna deal trovata.")
    mt5.shutdown()
    exit(0)

# Indicizza per order (il campo 'order' in una deal OUT corrisponde al ticket della posizione)
deals_by_order  = {}
deals_by_ticket = {}
for d in deals:
    deals_by_order[d.order]   = d
    deals_by_ticket[d.ticket] = d

print(f"Totale deal nel periodo: {len(deals)}\n")

# ── Abbina ogni ticket hedge alle deal ───────────────────────────────────────
print("=== PNL REALIZZATO PER OGNI TRADE HEDGE ===\n")
print(f"{'sig_id':>6} | {'riding':>6} | {'ticket_pos':>12} | {'deal_ticket':>12} | "
      f"{'time_close':>20} | {'profit':>8} | {'comment'}")
print("-" * 100)

riding_profit  = 0.0
normal_profit  = 0.0
riding_count   = 0
normal_count   = 0

for pos_ticket in sorted(TICKET_TO_SIG.keys()):
    sig_id, is_riding = TICKET_TO_SIG[pos_ticket]

    # Cerca la deal di chiusura: order == pos_ticket e entry == OUT
    found = None
    for d in deals:
        if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT and d.order == pos_ticket:
            found = d
            break
    # Fallback: cerca per position_id
    if not found:
        for d in deals:
            if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT and d.position_id == pos_ticket:
                found = d
                break

    riding_label = "🏄 SI" if is_riding else "  no"

    if found:
        dt = datetime.fromtimestamp(found.time).strftime("%Y-%m-%d %H:%M:%S")
        profit = found.profit
        comment = found.comment
        flag = "⚠️ <<< PROBLEMA" if sig_id in (5, 18) else ""
        print(f"{sig_id:>6} | {riding_label:>6} | {pos_ticket:>12} | {found.ticket:>12} | "
              f"{dt:>20} | {profit:>8.2f} | {comment} {flag}")
        if is_riding:
            riding_profit += profit
            riding_count  += 1
        else:
            normal_profit += profit
            normal_count  += 1
    else:
        print(f"{sig_id:>6} | {riding_label:>6} | {pos_ticket:>12} | {'NON TROVATO':>12} | "
              f"{'':>20} | {'?':>8} |")

print("-" * 100)
print(f"\nRiding  ({riding_count:>2} trade): profit totale = {riding_profit:>8.2f} $  "
      f"| media = {riding_profit/riding_count if riding_count else 0:>7.2f} $/trade")
print(f"Normal  ({normal_count:>2} trade): profit totale = {normal_profit:>8.2f} $  "
      f"| media = {normal_profit/normal_count if normal_count else 0:>7.2f} $/trade")
print(f"TOTALE  ({riding_count+normal_count:>2} trade): profit totale = "
      f"{riding_profit+normal_profit:>8.2f} $")

mt5.shutdown()
print("\nFine analisi.")
