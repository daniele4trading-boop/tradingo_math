"""
Analisi comparata Prop vs Hedge per ogni segnale
Abbina ogni trade prop al relativo hedge e mostra PNL di entrambi
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone

# ── Credenziali ───────────────────────────────────────────────────────────────
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

FROM_DATE = datetime(2026, 4, 20, tzinfo=timezone.utc)
TO_DATE   = datetime(2026, 4, 26, tzinfo=timezone.utc)

# Mapping ticket hedge → sig_id (dal log)
HEDGE_TICKET_TO_SIG = {
    150519316:  1,  150613039:  2,  150811609:  3,  150866296:  4,
    151155138:  5,  151221703:  6,  151295645:  7,  151363005:  9,
    151511944: 10,  151823337: 11,  151880102: 12,  152169454: 13,
    152360184: 14,  152532183: 15,  152639685: 16,  152697585: 17,
    152965140: 18,  153032918: 19,  153372155: 20,  153548618: 21,
    153659334: 22,  153805451: 23,  154043294: 24,  154179547: 25,
    154409329: 26,  154474396: 27,  154829826: 28,  155071916: 29,
}

RIDING_SIGS = {2,3,5,6,7,10,12,16,17,18,22,26,27,28}

# ── Connessione HEDGE ─────────────────────────────────────────────────────────
ok = mt5.initialize(
    path=HEDGE_TERMINAL, login=HEDGE_LOGIN,
    password=HEDGE_PASSWORD, server=HEDGE_SERVER
)
if not ok:
    print(f"Connessione hedge fallita: {mt5.last_error()}")
    exit(1)

hedge_deals_raw = mt5.history_deals_get(FROM_DATE, TO_DATE)
mt5.shutdown()

# ── Connessione PROP ──────────────────────────────────────────────────────────
ok = mt5.initialize(
    path=PROP_TERMINAL, login=PROP_LOGIN,
    password=PROP_PASSWORD, server=PROP_SERVER
)
if not ok:
    print(f"Connessione prop fallita: {mt5.last_error()}")
    exit(1)

prop_info  = mt5.account_info()
prop_deals_raw = mt5.history_deals_get(FROM_DATE, TO_DATE)
mt5.shutdown()

print(f"Prop  deals raw: {len(prop_deals_raw)}")
print(f"Hedge deals raw: {len(hedge_deals_raw)}\n")

# ── Indicizza deal per position_id ───────────────────────────────────────────
# Per ogni posizione raccogliamo deal IN e deal OUT
def build_positions(deals_raw, magic):
    positions = {}  # position_id → {in: deal, out: [deals]}
    for d in deals_raw:
        if d.magic != magic:
            continue
        pid = d.position_id
        if pid not in positions:
            positions[pid] = {'in': None, 'out': [], 'all': []}
        positions[pid]['all'].append(d)
        if d.entry == mt5.DEAL_ENTRY_IN:
            positions[pid]['in'] = d
        elif d.entry == mt5.DEAL_ENTRY_OUT:
            positions[pid]['out'].append(d)
    return positions

prop_positions  = build_positions(prop_deals_raw,  PROP_MAGIC)
hedge_positions = build_positions(hedge_deals_raw, HEDGE_MAGIC)

# ── Abbina hedge ticket → sig_id → prop position ────────────────────────────
# Inverti: sig_id → hedge_position_id
sig_to_hedge_pid = {}
for pid in hedge_positions:
    if pid in HEDGE_TICKET_TO_SIG:
        sig = HEDGE_TICKET_TO_SIG[pid]
        sig_to_hedge_pid[sig] = pid

# Per la prop: ordina per tempo di apertura e assegna sig_id progressivo
prop_pids_sorted = sorted(
    prop_positions.keys(),
    key=lambda p: prop_positions[p]['in'].time if prop_positions[p]['in'] else 0
)

# ── Stampa analisi comparata ─────────────────────────────────────────────────
print("=" * 110)
print("ANALISI COMPARATA PROP vs HEDGE — per segnale")
print("=" * 110)

grand_prop  = 0.0
grand_hedge = 0.0

for i, prop_pid in enumerate(prop_pids_sorted):
    pp = prop_positions[prop_pid]
    if not pp['in']:
        continue

    # Cerca il sig_id abbinato guardando l'ordine temporale
    # La prop apre segnali 1,2,3... nell'ordine — usiamo i sig_id noti
    # Abbiniamo per posizione temporale relativa
    prop_in = pp['in']
    prop_out_deals = sorted(pp['out'], key=lambda d: d.time)

    # Calcola profit totale prop per questa posizione
    prop_profit = sum(d.profit for d in pp['out'])
    prop_open_dt  = datetime.fromtimestamp(prop_in.time).strftime("%Y-%m-%d %H:%M:%S")

    # Trova il sig_id che corrisponde temporalmente
    matched_sig = None
    for sig, hpid in sig_to_hedge_pid.items():
        hp = hedge_positions[hpid]
        if hp['in']:
            # Accetta se hedge apre entro 60s dalla prop
            delta = abs(hp['in'].time - prop_in.time)
            if delta < 60:
                matched_sig = sig
                break
    # Fallback: usa ordine sequenziale
    if matched_sig is None:
        # assegna per indice
        sigs_sorted = sorted(sig_to_hedge_pid.keys())
        if i < len(sigs_sorted):
            matched_sig = sigs_sorted[i]

    riding_label = "🏄 RIDING" if matched_sig in RIDING_SIGS else "  normal"
    print(f"\n{'─'*110}")
    print(f"  SIG_ID={matched_sig or '?':>2}  {riding_label}  │  PROP position_id={prop_pid}")
    print(f"{'─'*110}")

    # PROP
    prop_dir = "SELL" if prop_in.type == mt5.DEAL_TYPE_SELL else "BUY"
    print(f"  PROP  IN : {prop_open_dt}  {prop_dir:>4}  vol={prop_in.volume:.2f}  "
          f"price={prop_in.price:.2f}")
    for d in prop_out_deals:
        dt  = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
        dir_= "BUY " if d.type == mt5.DEAL_TYPE_BUY else "SELL"
        print(f"  PROP  OUT: {dt}  {dir_:>4}  vol={d.volume:.2f}  "
              f"price={d.price:.2f}  profit={d.profit:>8.2f}  {d.comment}")

    print(f"  PROP  TOTALE: {prop_profit:>8.2f} $")
    grand_prop += prop_profit

    # HEDGE
    if matched_sig and matched_sig in sig_to_hedge_pid:
        hpid = sig_to_hedge_pid[matched_sig]
        hp   = hedge_positions[hpid]
        hedge_profit = sum(d.profit for d in hp['out'])
        grand_hedge += hedge_profit

        if hp['in']:
            hedge_open_dt = datetime.fromtimestamp(hp['in'].time).strftime("%Y-%m-%d %H:%M:%S")
            hdir = "SELL" if hp['in'].type == mt5.DEAL_TYPE_SELL else "BUY"
            print(f"  HEDGE IN : {hedge_open_dt}  {hdir:>4}  vol={hp['in'].volume:.2f}  "
                  f"price={hp['in'].price:.2f}")

        for d in sorted(hp['out'], key=lambda x: x.time):
            dt  = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
            dir_= "BUY " if d.type == mt5.DEAL_TYPE_BUY else "SELL"
            print(f"  HEDGE OUT: {dt}  {dir_:>4}  vol={d.volume:.2f}  "
                  f"price={d.price:.2f}  profit={d.profit:>8.2f}  {d.comment}")

        print(f"  HEDGE TOTALE: {hedge_profit:>8.2f} $")
        combined = prop_profit + hedge_profit
        print(f"  ── COMBINATO: {combined:>8.2f} $")
    else:
        print(f"  HEDGE: non abbinato")

print(f"\n{'='*110}")
print(f"  PROP  TOTALE GENERALE : {grand_prop:>10.2f} $")
print(f"  HEDGE TOTALE GENERALE : {grand_hedge:>10.2f} $")
print(f"  COMBINATO GENERALE    : {grand_prop+grand_hedge:>10.2f} $")
print(f"{'='*110}")
print("\nFine analisi.")
