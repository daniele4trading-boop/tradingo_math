"""Modulo 8 acceptance: launch pipeline offline + optional live risk."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_accounts, load_params
from launch.pipeline import run_cycle, save_cycle_report

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module8_acceptance.txt"


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


def _run_acceptance() -> int:
    accounts = load_accounts()
    params = load_params()
    failures: list[str] = []

    print("MODULO 8 — test accettazione launch")
    print()

    print("=== Ciclo offline (cache + piano, no execute) ===")
    offline = run_cycle(
        accounts,
        params,
        refresh_data=False,
        live_risk=False,
        live_execute=False,
    )
    print(f"  Coppie analizzate : {offline.pairs_analyzed}")
    print(f"  Selezionate       : {offline.selected_count}")
    print(f"  Piani generati    : {len(offline.plans)}")
    open_plans = [p for p in offline.plans if p.action == "OPEN"]
    close_plans = [p for p in offline.plans if p.action == "CLOSE"]
    print(f"  Azioni OPEN       : {len(open_plans)}")
    print(f"  Azioni CLOSE      : {len(close_plans)}")
    if offline.pairs_analyzed != 10:
        failures.append(f"attese 10 coppie, ottenute {offline.pairs_analyzed}")
    if offline.errors:
        failures.extend(offline.errors)
    report = save_cycle_report(offline, PROJECT_ROOT / "state" / "launch" / "module8_acceptance_cycle.json")
    print(f"  Report            : {report}")

    print()
    print("=== Ciclo live risk (MT5, no execute) ===")
    try:
        live = run_cycle(
            accounts,
            params,
            refresh_data=False,
            live_risk=True,
            live_execute=False,
        )
        print(f"  Pair aperti       : {live.open_hedged_count}")
        print(f"  Risk warnings     : {len(live.risk_warnings)}")
        for plan in live.plans:
            if plan.action == "OPEN":
                print(f"    OPEN candidate: {plan.pair_label} z={plan.zscore}")
        if live.errors:
            failures.extend(live.errors)
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN live risk skip: {exc}")

    print()
    print("=== Riepilogo ===")
    print(f"  Errori: {len(failures)}")
    if failures:
        for item in failures:
            print(f"  - {item}")
    else:
        print("  Tutti i controlli PASS")
        print()
        print("Avvio ciclo manuale:")
        print("  python launch\\cli.py --no-execute")
        print("  python launch\\cli.py --refresh --no-execute")
        print("  C:\\StatArb\\run_statarb_cycle.bat")

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
