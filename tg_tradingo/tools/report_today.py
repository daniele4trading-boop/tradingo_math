"""Report deterministico della giornata: messaggi, segnali e trade per canale.

Va eseguito sulla VPS del bridge (dove gira anche MT5): legge il log del bridge
e lo storico deal del terminale collegato, e stampa un riepilogo in markdown.
Serve come fonte di verita' per gli agenti AI, che non devono dedurre i numeri
di produzione dal codice.

    python report_today.py [--date 2026-08-18] [--days 1] [--out report.md]

Nessuna scrittura sui file di sistema: sola lettura piu' l'eventuale --out.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
from pathlib import Path

BASE = Path(r"C:\TG_TradinGo")
CONFIG = BASE / "tradingo_config.json"
LOGS = BASE / "logs"

MSG_RE = re.compile(r"\[(CH_[A-Z0-9_]+)\]\s+(MSG|EDIT):")
SIGNAL_RE = re.compile(r"\[(CH_[A-Z0-9_]+)\]\s+->\s+(\S+)\s+\|\s+action=(\w+)"
                       r"(?:\s+symbol=(\S+))?(?:\s+dir=(\S*))?")


def load_channels() -> dict[int, str]:
    """magic_base -> nome canale."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for ch in cfg.get("channels", []):
        base = ch.get("magic_base")
        if base is not None:
            out[int(base)] = f"{ch.get('id', '?')} ({ch.get('name', '?')})"
    return out


def channel_of(magic: int, bases: dict[int, str]) -> str:
    """Il magic e' magic_base + indice dello split."""
    for base in sorted(bases, reverse=True):
        if base <= magic < base + 100:
            return bases[base]
    return "sconosciuto"


def log_lines(day: dt.date) -> list[str]:
    """Righe di log del giorno: file giornaliero se presente, altrimenti stdout."""
    stamp = day.strftime("%Y-%m-%d")
    daily = LOGS / f"tradingo_{day:%Y%m%d}.log"
    lines: list[str] = []
    for path in (daily, LOGS / "bridge_stdout.log"):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = [ln for ln in text.splitlines() if ln.startswith(stamp)]
        if found:
            lines = found
            break
    return lines


def bridge_section(day: dt.date) -> list[str]:
    lines = log_lines(day)
    msgs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    signals: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    warnings = 0
    logging_errors = 0
    for ln in lines:
        m = MSG_RE.search(ln)
        if m:
            msgs[m.group(1)][m.group(2)] += 1
        s = SIGNAL_RE.search(ln)
        if s:
            key = (ln[:19], s.group(1), s.group(3))
            if key not in seen:  # lo stesso segnale e' scritto su piu' terminali
                seen.add(key)
                signals.append((ln[11:19], s.group(1), s.group(3),
                                s.group(4) or "", s.group(5) or ""))
        if "[WARNING]" in ln:
            warnings += 1
        if "Logging error" in ln:
            logging_errors += 1

    out = [f"## Bridge — {day:%d/%m/%Y}", ""]
    if not lines:
        out += ["Nessuna riga di log trovata per questa data.", ""]
        return out
    out += [f"Righe di log: {len(lines)} · warning: {warnings} · "
            f"errori di logging (emoji): {logging_errors}", "",
            "| Canale | messaggi | edit |", "|---|---|---|"]
    for ch in sorted(msgs):
        out.append(f"| {ch} | {msgs[ch]['MSG']} | {msgs[ch]['EDIT']} |")
    out += ["", f"### Segnali emessi ({len(signals)})", ""]
    if signals:
        out += ["| ora | canale | action | symbol | dir |", "|---|---|---|---|---|"]
        out += [f"| {t} | {ch} | {act} | {sym} | {d} |" for t, ch, act, sym, d in signals]
    else:
        out.append("Nessun segnale emesso.")
    out.append("")
    return out


def mt5_section(day: dt.date, days: int) -> list[str]:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return ["## MT5", "", "Pacchetto MetaTrader5 non disponibile.", ""]
    if not mt5.initialize():
        return ["## MT5", "", f"initialize fallita: {mt5.last_error()}", ""]

    bases = load_channels()
    info = mt5.account_info()
    start = dt.datetime.combine(day, dt.time()) - dt.timedelta(days=days - 1)
    end = dt.datetime.combine(day, dt.time()) + dt.timedelta(days=1, hours=6)
    deals = mt5.history_deals_get(start, end) or []

    per_ch: dict[str, dict] = collections.defaultdict(
        lambda: {"deals": 0, "pl": 0.0, "sym": set(), "magics": set()})
    for d in deals:
        ch = channel_of(d.magic, bases)
        rec = per_ch[ch]
        rec["deals"] += 1
        rec["pl"] += d.profit + d.commission + d.swap
        rec["sym"].add(d.symbol)
        rec["magics"].add(d.magic)

    out = ["## Terminale MT5", ""]
    if info is not None:
        out.append(f"Conto {info.login} · {info.server} · equity {info.equity:.2f} "
                   f"· balance {info.balance:.2f}")
    out += ["", f"Deal dal {start:%d/%m} al {end:%d/%m} (ora broker): {len(deals)}", "",
            "| Canale | deal | P/L | simboli | magic |", "|---|---|---|---|---|"]
    for ch in sorted(per_ch, key=lambda k: per_ch[k]["pl"]):
        r = per_ch[ch]
        out.append(f"| {ch} | {r['deals']} | {r['pl']:.2f} | "
                   f"{','.join(sorted(r['sym']))} | "
                   f"{','.join(str(m) for m in sorted(r['magics']))} |")

    positions = mt5.positions_get() or []
    out += ["", f"### Posizioni aperte ({len(positions)})", ""]
    if positions:
        out += ["| symbol | canale | magic | vol | open | sl | tp | P/L |",
                "|---|---|---|---|---|---|---|---|"]
        for p in positions:
            out.append(f"| {p.symbol} | {channel_of(p.magic, bases)} | {p.magic} | "
                       f"{p.volume} | {p.price_open} | {p.sl} | {p.tp} | {p.profit:.2f} |")
    else:
        out.append("Nessuna posizione aperta.")
    out.append("")
    mt5.shutdown()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="giorno da analizzare (YYYY-MM-DD), default oggi")
    ap.add_argument("--days", type=int, default=1, help="giorni di storico deal")
    ap.add_argument("--out", help="scrive il report anche su questo file")
    args = ap.parse_args()

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    report = [f"# Report TG TradinGo — {day:%d/%m/%Y}",
              f"_generato {dt.datetime.now():%d/%m/%Y %H:%M} su {BASE}_", ""]
    report += bridge_section(day)
    report += mt5_section(day, max(1, args.days))
    text = "\n".join(report)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
