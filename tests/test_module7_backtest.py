"""Modulo 7 acceptance: backtest su cache Modulo 2 (no MT5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.runner import run_pair_backtest
from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module7_acceptance.txt"
REPORT_PATH = PROJECT_ROOT / "state" / "backtest" / "last_acceptance_summary.json"


class _Tee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _print_table(results: list) -> None:
    headers = (
        "coppia",
        "sel",
        "tf",
        "trades",
        "win%",
        "ret%",
        "maxdd%",
        "sharpe",
        "net",
    )
    widths = [14, 4, 4, 6, 6, 7, 7, 7, 9]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-" * 72)
    for result in results:
        m = result.metrics
        net = f"{m.net_pnl:.1f}" if m.error is None else "ERR"
        row = [
            result.pair_label,
            "sì" if result.selected else "no",
            result.trigger_tf,
            str(m.trades),
            f"{m.win_rate:.1f}",
            f"{m.total_return_pct:.2f}",
            f"{m.max_drawdown_pct:.2f}",
            f"{m.sharpe:.2f}",
            net,
        ]
        print(" | ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def _run_acceptance() -> int:
    accounts = load_accounts()
    params = load_params()
    profile = get_profile("data_source", accounts)

    print("MODULO 7 — test accettazione backtest")
    print(f"Cache: state/data/{profile.name}/")
    print(
        f"Equity iniziale={params['backtest']['initial_equity']} "
        f"lot_a={params['backtest']['lot_a']} "
        f"commission={params['costs']['model_commission_per_lot']}/lot"
    )
    print()

    results = []
    failures = []
    total_trades = 0

    for candidate in CANDIDATE_PAIRS:
        result = run_pair_backtest(
            profile,
            accounts,
            params,
            candidate.index,
            candidate.leg_a,
            candidate.leg_b,
            candidate.category,
        )
        results.append(result)
        if result.metrics.error:
            failures.append(f"{result.pair_label}: {result.metrics.error}")
        total_trades += result.metrics.trades

    _print_table(results)

    print()
    print("=== Riepilogo ===")
    selected = sum(1 for r in results if r.selected)
    profitable = sum(1 for r in results if r.metrics.net_pnl > 0 and not r.metrics.error)
    print(f"  Coppie analizzate : {len(results)}")
    print(f"  Selezionate (H4)  : {selected}")
    print(f"  Trade totali      : {total_trades}")
    print(f"  Coppie net > 0    : {profitable}")

    summary = []
    for result in results:
        m = result.metrics
        summary.append(
            {
                "pair": result.pair_label,
                "selected": result.selected,
                "trades": m.trades,
                "return_pct": m.total_return_pct,
                "net_pnl": m.net_pnl,
                "error": m.error,
            }
        )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"  Report JSON       : {REPORT_PATH}")

    if failures:
        print()
        print("=== Errori ===")
        for item in failures:
            print(f"  - {item}")

    if total_trades == 0 and not failures:
        print()
        print("  WARN: zero trade generati — verifica parametri segnale/cache")

    return 1 if failures else 0


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("w", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, log_file)
    try:
        return _run_acceptance()
    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log salvato: {LOG_PATH}", file=original_stdout)


if __name__ == "__main__":
    raise SystemExit(main())
