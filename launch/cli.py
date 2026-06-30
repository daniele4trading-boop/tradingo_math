"""CLI entrypoint for StatArb launch cycles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_accounts, load_params
from launch.pipeline import run_cycle, save_cycle_report


def _print_plans(result) -> None:
    print()
    print("=== Action plan ===")
    print("coppia         | sel | signal       | z      | open | action | gate")
    print("-" * 78)
    for plan in result.plans:
        z = f"{plan.zscore:.2f}" if plan.zscore is not None and plan.zscore == plan.zscore else "n/d"
        print(
            f"{plan.pair_label:<14} | "
            f"{'sì' if plan.selected else 'no':<3} | "
            f"{plan.signal:<12} | "
            f"{z:<6} | "
            f"{'sì' if plan.has_open_hedge else 'no':<4} | "
            f"{plan.action:<6} | "
            f"{plan.gate_reason or ''}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StatArb launch cycle")
    parser.add_argument("--refresh", action="store_true", help="Scarica storico MT5 (Modulo 2)")
    parser.add_argument(
        "--no-risk",
        action="store_true",
        help="Salta lettura MT5 risk/portfolio",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Solo analisi + piano, nessun ordine",
    )
    parser.add_argument(
        "--loop",
        type=int,
        metavar="MINUTES",
        help="Ripeti ogni N minuti (APScheduler)",
    )
    args = parser.parse_args(argv)

    accounts = load_accounts()
    params = load_params()

    def _once() -> int:
        result = run_cycle(
            accounts,
            params,
            refresh_data=args.refresh or None,
            live_risk=not args.no_risk,
            live_execute=not args.no_execute,
        )
        print("STATARB LAUNCH CYCLE")
        print(f"  Analizzate : {result.pairs_analyzed}")
        print(f"  Selezionate: {result.selected_count}")
        print(f"  Aperti     : {result.open_hedged_count}")
        print(f"  Esecuzioni : {len(result.executions)}")
        print(f"  Chiusure   : {len(result.closes)}")
        if result.risk_warnings:
            print(f"  Warnings   : {'; '.join(result.risk_warnings)}")
        if result.errors:
            print(f"  Errori     : {len(result.errors)}")
        _print_plans(result)
        report_path = save_cycle_report(result)
        print(f"\nReport: {report_path}")
        if result.errors:
            for err in result.errors:
                print(f"  - {err}")
        return 1 if result.errors else 0

    if args.loop:
        from apscheduler.schedulers.blocking import BlockingScheduler

        scheduler = BlockingScheduler()
        scheduler.add_job(_once, "interval", minutes=args.loop, max_instances=1)
        print(f"Scheduler attivo ogni {args.loop} min — Ctrl+C per fermare")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("Scheduler fermato.")
        return 0

    return _once()


if __name__ == "__main__":
    raise SystemExit(main())
