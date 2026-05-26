import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import Convergenza7Config


TRADE_COLUMNS = [
    "timestamp_entry",
    "timestamp_exit",
    "direction",
    "entry_price",
    "sl_price",
    "tp_price",
    "exit_price",
    "exit_reason",
    "rr_effective",
    "realized_rr",
    "pnl_percent",
    "setup_name",
    "pattern_id",
    "pattern_name",
    "breakeven_active",
    "bars_held",
]


def _serializable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _max_drawdown(pnls: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def calculate_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(trades)
    wins = [trade for trade in trades if float(trade.get("pnl_percent", 0.0)) > 0]
    losses = [trade for trade in trades if float(trade.get("pnl_percent", 0.0)) < 0]
    gross_profit = sum(float(trade["pnl_percent"]) for trade in wins)
    gross_loss = abs(sum(float(trade["pnl_percent"]) for trade in losses))
    profit_factor: Optional[float]
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = None

    return {
        "total_trades": total,
        "win_rate_percent": (len(wins) / total * 100.0) if total else 0.0,
        "avg_rr_winners": (
            sum(float(trade.get("realized_rr", 0.0)) for trade in wins) / len(wins)
            if wins else 0.0
        ),
        "profit_factor": profit_factor,
        "max_drawdown_percent": _max_drawdown(float(trade.get("pnl_percent", 0.0)) for trade in trades),
        "net_pnl_percent": sum(float(trade.get("pnl_percent", 0.0)) for trade in trades),
        "distribution_by_setup": dict(Counter(str(trade.get("setup_name", "")) for trade in trades)),
        "distribution_by_pattern": dict(Counter(str(trade.get("pattern_id", "")) for trade in trades)),
        "gross_profit_percent": gross_profit,
        "gross_loss_percent": gross_loss,
    }


def save_trades_csv(trades: List[Dict[str, Any]], path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for trade in trades:
            writer.writerow({key: _serializable(trade.get(key, "")) for key in TRADE_COLUMNS})


def save_stats_json(stats: Dict[str, Any], path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")


def print_summary(stats: Dict[str, Any]) -> None:
    print("CONVERGENZA 7 BACKTEST SUMMARY")
    print(f"Total trades        : {stats['total_trades']}")
    print(f"Win rate            : {stats['win_rate_percent']:.2f}%")
    print(f"Avg RR winners      : {stats['avg_rr_winners']:.2f}")
    if stats["profit_factor"] is None:
        print("Profit factor       : n/a")
    else:
        print(f"Profit factor       : {stats['profit_factor']:.2f}")
    print(f"Max drawdown        : {stats['max_drawdown_percent']:.2f}%")
    print(f"Net PnL             : {stats['net_pnl_percent']:.2f}%")
    print(f"By setup            : {stats['distribution_by_setup']}")
    print(f"By pattern          : {stats['distribution_by_pattern']}")


def write_report(
    trades: List[Dict[str, Any]],
    config: Convergenza7Config,
    trades_csv: Optional[str] = None,
    stats_json: Optional[str] = None,
    print_to_console: bool = True,
) -> Dict[str, Any]:
    stats = calculate_stats(trades)
    save_trades_csv(trades, trades_csv or config.output_trades_csv)
    save_stats_json(stats, stats_json or config.output_stats_json)
    if print_to_console:
        print_summary(stats)
    return stats

