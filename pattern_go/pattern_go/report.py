"""Report giornaliero su file, generato dal journal JSON della giornata."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_journal(log_dir: str | Path, day: str) -> list[dict[str, Any]]:
    """Legge `journal_YYYYMMDD.jsonl` (compresi i file ruotati)."""
    directory = Path(log_dir)
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"journal_{day}.jsonl*")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trades": 0,
            "wins": 0,
            "pnl": 0.0,
            "r": [],
            "slippage": [],
            "spread": [],
            "signals_rejected": 0,
            "orders_placed": 0,
            "orders_cancelled": 0,
        }
    )
    errors = []
    for rec in records:
        strategy = rec.get("strategy", "-")
        bucket = by_strategy[strategy]
        event = rec.get("event")
        if event == "TRADE_CLOSED":
            bucket["trades"] += 1
            bucket["pnl"] += float(rec.get("pnl", 0.0))
            r = float(rec.get("r_realized", 0.0))
            bucket["r"].append(r)
            if r > 0:
                bucket["wins"] += 1
        elif event == "TRADE_OPENED":
            bucket["slippage"].append(float(rec.get("slippage", 0.0)))
            bucket["spread"].append(float(rec.get("spread_at_signal", 0.0)))
        elif event == "SIGNAL_REJECTED":
            bucket["signals_rejected"] += 1
        elif event == "ORDER_PLACED":
            bucket["orders_placed"] += 1
        elif event in ("ORDER_CANCELLED", "ORDER_REJECTED", "ORDER_CANCEL_FAILED"):
            bucket["orders_cancelled"] += 1
        elif event in ("ERROR", "CLOSE_FAILED", "DAILY_REPORT_FAILED"):
            errors.append(rec)

    out: dict[str, Any] = {"strategies": {}, "errors": len(errors)}
    for name, b in by_strategy.items():
        out["strategies"][name] = {
            "trades": b["trades"],
            "win_rate": (b["wins"] / b["trades"]) if b["trades"] else None,
            "pnl": round(b["pnl"], 2),
            "avg_r": round(statistics.fmean(b["r"]), 4) if b["r"] else None,
            "avg_slippage": round(statistics.fmean(b["slippage"]), 4) if b["slippage"] else None,
            "avg_spread": round(statistics.fmean(b["spread"]), 4) if b["spread"] else None,
            "signals_rejected": b["signals_rejected"],
            "orders_placed": b["orders_placed"],
            "orders_cancelled": b["orders_cancelled"],
        }
    return out


def render(summary: dict[str, Any], day: str, equity: float, effective_floor: float) -> str:
    lines = [
        f"# Pattern GO — report {day}",
        "",
        f"Equity: {equity:.2f} · floor effettivo: {effective_floor:.2f} "
        f"· margine: {equity - effective_floor:.2f}",
        f"Errori API/esecuzione loggati: {summary['errors']}",
        "",
        "| strategia | trade | win rate | PnL | R medio | slippage medio "
        "| spread medio | segnali scartati |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, s in sorted(summary["strategies"].items()):
        lines.append(
            "| {n} | {t} | {w} | {p} | {r} | {sl} | {sp} | {rej} |".format(
                n=name,
                t=s["trades"],
                w=f"{s['win_rate']:.1%}" if s["win_rate"] is not None else "—",
                p=s["pnl"],
                r=s["avg_r"] if s["avg_r"] is not None else "—",
                sl=s["avg_slippage"] if s["avg_slippage"] is not None else "—",
                sp=s["avg_spread"] if s["avg_spread"] is not None else "—",
                rej=s["signals_rejected"],
            )
        )
    return "\n".join(lines) + "\n"


def write_daily_report(
    log_dir: str | Path,
    report_dir: str | Path,
    day: str,
    equity: float,
    effective_floor: float,
) -> Path:
    summary = summarize(read_journal(log_dir, day))
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{day}.md"
    path.write_text(render(summary, day, equity, effective_floor), encoding="utf-8")
    (out_dir / f"report_{day}.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return path
