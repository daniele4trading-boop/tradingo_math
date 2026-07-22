"""
Analizza tradingo_signal_stats.csv (EA) e opzionalmente log bridge.

Uso:
  python analyze_signal_stats.py
  python analyze_signal_stats.py --stats "C:\\...\\MQL5\\Files\\tradingo_signal_stats.csv"
  python analyze_signal_stats.py --bridge-log C:\\TG_TradinGo\\logs\\tradingo_20260721.log
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_STATS = Path(
    r"C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal"
    r"\AE2CC2E013FDE1E3CDF010AA51C60400\MQL5\Files\tradingo_signal_stats.csv"
)
DEFAULT_BRIDGE_LOG = Path(r"C:\TG_TradinGo\logs")


def load_stats(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def parse_bridge_opens(log_path: Path) -> list[dict]:
    """Estrae OPEN dal log bridge: [CH_ORO] -> signal ... action=OPEN"""
    if not log_path or not log_path.exists():
        return []
    pat = re.compile(
        r"\[(?P<ch>CH_\w+)\].*?->\s+\S+\s+\|\s+action=(?P<action>\w+)"
        r"(?:\s+symbol=(?P<sym>\w+))?(?:\s+dir=(?P<dir>\w+))?"
    )
    opens: list[dict] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "action=OPEN" not in line and "action=OPEN_NOW" not in line:
            continue
        m = pat.search(line)
        if m:
            opens.append(m.groupdict())
    return opens


def fnum(val: str | None) -> float:
    if not val:
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def summarize(rows: list[dict]) -> str:
    if not rows:
        return "Nessuna riga in tradingo_signal_stats.csv"

    by_ch: dict[str, dict] = defaultdict(lambda: {
        "executed": 0,
        "cancelled": 0,
        "in_range": 0,
        "tolerance": 0,
        "slippage_sum": 0.0,
        "slippage_n": 0,
        "dist_cancel_sum": 0.0,
    })

    for r in rows:
        ch = r.get("channel_id") or r.get("channel_file") or "?"
        status = (r.get("status") or "").upper()
        bucket = by_ch[ch]
        if status == "CANCELLED_RANGE":
            bucket["cancelled"] += 1
            bucket["dist_cancel_sum"] += abs(fnum(r.get("distance_points")))
        elif status.startswith("EXECUTED"):
            bucket["executed"] += 1
            if status == "EXECUTED_IN_RANGE":
                bucket["in_range"] += 1
            elif status == "EXECUTED_TOLERANCE":
                bucket["tolerance"] += 1
            slip = fnum(r.get("slippage_points"))
            if slip != 0.0 or fnum(r.get("fill_price")) > 0:
                bucket["slippage_sum"] += slip
                bucket["slippage_n"] += 1

    lines = ["=" * 72, "CLASSIFICA CANALI (da tradingo_signal_stats.csv)", "=" * 72]
    ranked = []
    for ch, b in by_ch.items():
        total = b["executed"] + b["cancelled"]
        if total == 0:
            continue
        exec_rate = 100.0 * b["executed"] / total
        avg_slip = b["slippage_sum"] / b["slippage_n"] if b["slippage_n"] else 0.0
        avg_miss = b["dist_cancel_sum"] / b["cancelled"] if b["cancelled"] else 0.0
        ranked.append((exec_rate, ch, b, avg_slip, avg_miss))

    ranked.sort(reverse=True)
    lines.append(f"{'Canale':<12} {'Exec':>5} {'Canc':>5} {'%Exec':>7} {'Slip avg':>9} {'Miss pts':>9}")
    lines.append("-" * 72)
    for exec_rate, ch, b, avg_slip, avg_miss in ranked:
        lines.append(
            f"{ch:<12} {b['executed']:>5} {b['cancelled']:>5} {exec_rate:>6.1f}% "
            f"{avg_slip:>9.1f} {avg_miss:>9.1f}"
        )
    lines.append("")
    lines.append("Slip avg = punti fill vs entry segnale (positivo = slippage sfavorevole BUY)")
    lines.append("Miss pts  = distanza media (punti) sui trade CANCELLED_RANGE")
    return "\n".join(lines)


def collect_bridge_logs(bridge_log: Path | None, bridge_log_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    if bridge_log:
        paths.append(bridge_log)
    if bridge_log_dir and bridge_log_dir.exists():
        paths.extend(sorted(bridge_log_dir.glob("tradingo_*.log")))
    # dedupe preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Analisi performance segnali per canale")
    p.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    p.add_argument("--bridge-log", type=Path, default=None,
                   help="Log bridge (opzionale) per conteggio OPEN emessi")
    p.add_argument("--bridge-log-dir", type=Path, default=None,
                   help="Cartella logs bridge (es. C:\\TG_TradinGo\\logs)")
    p.add_argument("--from-date", type=str, default=None,
                   help="Filtra log YYYYMMDD inizio (inclusive), es. 20260720")
    p.add_argument("--to-date", type=str, default=None,
                   help="Filtra log YYYYMMDD fine (inclusive), es. 20260722")
    args = p.parse_args()

    rows = load_stats(args.stats)
    print(summarize(rows))
    print(f"\nFile stats: {args.stats} ({len(rows)} righe)")

    log_paths = collect_bridge_logs(args.bridge_log, args.bridge_log_dir)
    if args.from_date or args.to_date:
        filtered: list[Path] = []
        for lp in log_paths:
            m = re.search(r"tradingo_(\d{8})", lp.name)
            if not m:
                filtered.append(lp)
                continue
            day = m.group(1)
            if args.from_date and day < args.from_date:
                continue
            if args.to_date and day > args.to_date:
                continue
            filtered.append(lp)
        log_paths = filtered

    if log_paths:
        all_opens: list[dict] = []
        for lp in log_paths:
            all_opens.extend(parse_bridge_opens(lp))
        print(f"\nBridge OPEN nei log ({len(log_paths)} file): {len(all_opens)}")
        by = defaultdict(int)
        by_action = defaultdict(int)
        for o in all_opens:
            by[o.get("ch", "?")] += 1
            by_action[o.get("action", "?")] += 1
        for ch, n in sorted(by.items()):
            print(f"  {ch}: {n}")
        if by_action:
            print("Per action:")
            for act, n in sorted(by_action.items()):
                print(f"  {act}: {n}")
    elif args.bridge_log or args.bridge_log_dir:
        print("\nNessun log bridge trovato / leggibile.")


if __name__ == "__main__":
    main()
