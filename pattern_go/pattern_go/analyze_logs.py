"""Confronto forward test vs backtest, con focus su slippage e costo round-trip.

Uso:
    python -m pattern_go.analyze_logs --log-dir logs [--from 20260805] [--to 20260930]

Il dato che conta e' lo scostamento fra prezzo teorico e fill effettivo: e' l'unico
modo di sapere se il PF reale regge i numeri del backtest. Le soglie di uscita sono
quelle misurate out-of-sample: costo round-trip di break-even 85 punti su M5 e 151 su
M15, e disattivazione di M5 se lo slippage medio supera 30 punti.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POINT = 0.01  # 1 punto = 0.01 USD sul prezzo dell'oro

BACKTEST = {
    "combined": {"win_rate": 0.572, "avg_r": 0.344, "profit_factor": 1.75},
    "M5": {
        "trades_per_month": 63,
        "median_sl_points": 367,
        "median_hold_minutes": 15,
        "breakeven_round_trip_points": 85,
        "max_avg_slippage_points": 30,
    },
    "M15": {
        "trades_per_month": 72,
        "median_sl_points": 713,
        "median_hold_minutes": 45,
        "breakeven_round_trip_points": 151,
        "max_avg_slippage_points": 100,
    },
}


@dataclass
class StrategyStats:
    trades: int = 0
    wins: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    r_values: list[float] | None = None
    slippage_points: list[float] | None = None
    spread_points: list[float] | None = None
    sl_points: list[float] | None = None
    orders_placed: int = 0
    orders_not_filled: int = 0
    rejected_by_filter: dict[str, int] | None = None

    def __post_init__(self) -> None:
        self.r_values = self.r_values or []
        self.slippage_points = self.slippage_points or []
        self.spread_points = self.spread_points or []
        self.sl_points = self.sl_points or []
        self.rejected_by_filter = self.rejected_by_filter or {}


def load_records(
    log_dir: str | Path, day_from: str | None, day_to: str | None
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(Path(log_dir).glob("journal_*.jsonl*")):
        day = path.name.split("_")[1].split(".")[0]
        if day_from and day < day_from:
            continue
        if day_to and day > day_to:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def collect(records: list[dict[str, Any]]) -> dict[str, StrategyStats]:
    stats: dict[str, StrategyStats] = {}

    def bucket(name: str) -> StrategyStats:
        return stats.setdefault(name, StrategyStats())

    for rec in records:
        event = rec.get("event")
        name = rec.get("strategy", "-")
        if event == "TRADE_OPENED":
            b = bucket(name)
            b.slippage_points.append(float(rec.get("slippage", 0.0)) / POINT)
            b.spread_points.append(float(rec.get("spread_at_signal", 0.0)) / POINT)
            b.sl_points.append(float(rec.get("risk", 0.0)) / POINT)
        elif event == "TRADE_CLOSED":
            b = bucket(name)
            b.trades += 1
            pnl = float(rec.get("pnl", 0.0))
            b.r_values.append(float(rec.get("r_realized", 0.0)))
            if pnl >= 0:
                b.wins += 1
                b.gross_profit += pnl
            else:
                b.gross_loss += -pnl
        elif event == "ORDER_PLACED":
            bucket(name).orders_placed += 1
        elif event == "ORDER_CANCELLED":
            bucket(name).orders_not_filled += 1
        elif event == "SIGNAL_REJECTED":
            b = bucket(name)
            for failed in rec.get("failed") or [rec.get("reason", "unknown")]:
                b.rejected_by_filter[failed] = b.rejected_by_filter.get(failed, 0) + 1
    return stats


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def build_summary(stats: dict[str, StrategyStats]) -> dict[str, Any]:
    out: dict[str, Any] = {"strategies": {}, "warnings": []}
    for name, s in sorted(stats.items()):
        avg_slip = _mean(s.slippage_points)
        avg_spread = _mean(s.spread_points)
        round_trip = None
        if avg_spread is not None and avg_slip is not None:
            round_trip = avg_spread + 2 * avg_slip
        expected = BACKTEST.get(name, {})
        entry = {
            "trades": s.trades,
            "win_rate": (s.wins / s.trades) if s.trades else None,
            "avg_r": _mean(s.r_values),
            "profit_factor": (s.gross_profit / s.gross_loss) if s.gross_loss else None,
            "avg_slippage_points": avg_slip,
            "median_slippage_points": _median(s.slippage_points),
            "avg_spread_points": avg_spread,
            "estimated_round_trip_points": round_trip,
            "median_sl_points": _median(s.sl_points),
            "orders_placed": s.orders_placed,
            "orders_not_filled": s.orders_not_filled,
            "fill_rate": (
                (s.orders_placed - s.orders_not_filled) / s.orders_placed
                if s.orders_placed
                else None
            ),
            "rejected_by_filter": s.rejected_by_filter,
            "backtest": expected,
        }
        out["strategies"][name] = entry

        limit = expected.get("max_avg_slippage_points")
        if limit is not None and avg_slip is not None and avg_slip > limit:
            out["warnings"].append(
                f"{name}: slippage medio {avg_slip:.1f} punti > soglia {limit} "
                "-> criterio di disattivazione della strategia raggiunto"
            )
        breakeven = expected.get("breakeven_round_trip_points")
        if breakeven is not None and round_trip is not None and round_trip > breakeven:
            out["warnings"].append(
                f"{name}: costo round-trip stimato {round_trip:.1f} punti > break-even "
                f"{breakeven} -> PF atteso sotto 1.00"
            )
    return out


def render(summary: dict[str, Any]) -> str:
    lines = ["# Pattern GO — forward test vs backtest", ""]
    for name, s in summary["strategies"].items():
        bt = s["backtest"]
        lines += [
            f"## {name}",
            "",
            f"- trade chiusi: **{s['trades']}** (attesi ~{bt.get('trades_per_month', '—')}/mese)",
            f"- win rate: {_pct(s['win_rate'])} (backtest combinato 57,2%)",
            f"- R medio: {_num(s['avg_r'])} (backtest combinato 0,344)",
            f"- profit factor: {_num(s['profit_factor'])} (backtest combinato 1,75)",
            f"- **slippage medio: {_num(s['avg_slippage_points'])} punti** "
            f"(mediano {_num(s['median_slippage_points'])}, soglia "
            f"{bt.get('max_avg_slippage_points', '—')})",
            f"- spread medio all'ordine: {_num(s['avg_spread_points'])} punti",
            f"- **costo round-trip stimato: {_num(s['estimated_round_trip_points'])} punti** "
            f"(break-even {bt.get('breakeven_round_trip_points', '—')})",
            f"- SL mediano: {_num(s['median_sl_points'])} punti "
            f"(backtest {bt.get('median_sl_points', '—')})",
            f"- ordini inviati {s['orders_placed']}, non eseguiti {s['orders_not_filled']} "
            f"(fill rate {_pct(s['fill_rate'])})",
            f"- segnali scartati per filtro: {s['rejected_by_filter'] or '—'}",
            "",
        ]
    if summary["warnings"]:
        lines.append("## Allarmi")
        lines.append("")
        lines += [f"- {w}" for w in summary["warnings"]]
        lines.append("")
    return "\n".join(lines)


def _num(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "—"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analisi log Pattern GO vs backtest")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--from", dest="day_from", default=None, help="YYYYMMDD incluso")
    parser.add_argument("--to", dest="day_to", default=None, help="YYYYMMDD incluso")
    parser.add_argument("--json", action="store_true", help="output JSON invece di markdown")
    args = parser.parse_args(argv)

    records = load_records(args.log_dir, args.day_from, args.day_to)
    summary = build_summary(collect(records))
    print(json.dumps(summary, indent=2) if args.json else render(summary))
    return 1 if summary["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
