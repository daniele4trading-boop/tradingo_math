"""Modulo 2 acceptance test: download storico MT5 + cache + overlap coppie."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params
from core.mt5_connection import Mt5Session
from scanner.scanner import PairScanResult, scan_pair
from scanner.timeframes import structural_timeframe, trigger_timeframe_for_category

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module2_acceptance.txt"


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


@dataclass
class PairRow:
    pair_label: str
    category: str
    trigger_tf: str
    leg: str
    broker: str
    structural_bars: int
    structural_min: int
    trigger_bars: int
    trigger_min: int
    overlap_struct: int
    overlap_trigger: int
    ok: bool


def _print_table(rows: list[PairRow]) -> None:
    headers = (
        "coppia",
        "cat",
        "trig_tf",
        "leg",
        "broker",
        "bars_H4",
        "min_H4",
        "bars_trig",
        "min_trig",
        "ovlp_H4",
        "ovlp_trig",
        "OK",
    )
    widths = [14, 8, 7, 8, 18, 8, 7, 9, 8, 8, 9, 4]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        values = [
            row.pair_label,
            row.category,
            row.trigger_tf,
            row.leg,
            row.broker,
            str(row.structural_bars),
            str(row.structural_min),
            str(row.trigger_bars),
            str(row.trigger_min),
            str(row.overlap_struct),
            str(row.overlap_trigger),
            "sì" if row.ok else "no",
        ]
        print(" | ".join(str(v).ljust(w) for v, w in zip(values, widths)))


def _rows_from_result(result: PairScanResult) -> list[PairRow]:
    shared_ok = result.ok
    rows = []
    for leg_name, leg in (("A", result.leg_a), ("B", result.leg_b)):
        rows.append(
            PairRow(
                pair_label=result.pair_label,
                category=result.category,
                trigger_tf=result.trigger_timeframe,
                leg=leg_name,
                broker=leg.broker_symbol,
                structural_bars=leg.structural.count,
                structural_min=leg.structural.minimum_required,
                trigger_bars=leg.trigger.count,
                trigger_min=leg.trigger.minimum_required,
                overlap_struct=result.structural_overlap,
                overlap_trigger=result.trigger_overlap,
                ok=shared_ok,
            )
        )
    return rows


def _run_acceptance() -> int:
    accounts = load_accounts()
    params = load_params()
    profile = get_profile("data_source", accounts)

    print("MODULO 2 — test accettazione scanner dati")
    print(f"Profilo data_source: {profile.name}")
    print(f"Terminale: {profile.path}")
    print(f"Structural TF: {structural_timeframe(params)} / lookback {params['data']['structural_lookback_days']}d")
    print(
        f"Trigger TF: forex/metalli={params['data']['trigger_timeframe_default']} "
        f"| indici={params['data']['trigger_timeframe_indices']} "
        f"/ lookback {params['data']['trigger_lookback_days']}d"
    )
    print(f"Coppie canoniche: {len(CANDIDATE_PAIRS)}")
    print()

    rows: list[PairRow] = []
    failures: list[str] = []

    with Mt5Session(profile) as mt5:
        for candidate in CANDIDATE_PAIRS:
            trigger_tf = trigger_timeframe_for_category(candidate.category, params)
            try:
                result = scan_pair(
                    mt5,
                    profile,
                    accounts,
                    params,
                    candidate.index,
                    candidate.leg_a,
                    candidate.leg_b,
                    candidate.category,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{candidate.leg_a}/{candidate.leg_b} ({candidate.category}) -> {exc}")
                continue

            rows.extend(_rows_from_result(result))
            if not result.ok:
                failures.append(
                    f"{result.pair_label} overlap_struct={result.structural_overlap} "
                    f"overlap_trigger={result.trigger_overlap}"
                )

        _print_table(rows)

        print()
        print("=== Cache CSV (state/data) ===")
        cache_dir = PROJECT_ROOT / "state" / "data" / profile.name
        if cache_dir.exists():
            for path in sorted(cache_dir.glob("*.csv")):
                print(f"  {path.name} ({path.stat().st_size} bytes)")
        else:
            print("  (nessun file)")

        print()
        print("=== Coppie NON ok ===")
        if failures:
            for item in failures:
                print(f"  - {item}")
        else:
            print("  (nessuna)")

    print()
    print("Sessione MT5 chiusa.")
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
