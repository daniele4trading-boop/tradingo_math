"""Modulo 1 acceptance test: symbol_map + MT5 contract metadata on XM data_source."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts
from core.mt5_connection import Mt5Session

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module1_acceptance.txt"


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
class SymbolRow:
    pair_label: str
    canonical: str
    broker_name: str
    found: bool
    tick_size: str
    tick_value: str
    contract_size: str
    volume_min: str
    volume_step: str
    digits: str
    history_ok: bool
    history_bars: int


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _translate(profile_name: str, canonical: str, accounts: dict[str, Any]) -> str:
    return accounts.get("symbol_map", {}).get(profile_name, {}).get(canonical, "")


def _inspect_mapped_symbol(mt5: Any, broker_symbol: str) -> tuple[bool, dict[str, Any]]:
    if not broker_symbol:
        return False, {}

    selected = mt5.symbol_select(broker_symbol, True)
    info = mt5.symbol_info(broker_symbol) if selected else None
    if not selected or info is None:
        return False, {}

    return True, {
        "tick_size": getattr(info, "trade_tick_size", None),
        "tick_value": getattr(info, "trade_tick_value", None),
        "contract_size": getattr(info, "trade_contract_size", None),
        "volume_min": getattr(info, "volume_min", None),
        "volume_step": getattr(info, "volume_step", None),
        "digits": getattr(info, "digits", None),
    }


def _check_history(mt5: Any, broker_symbol: str) -> tuple[bool, int]:
    timeframe = mt5.TIMEFRAME_H1
    rates = mt5.copy_rates_from_pos(broker_symbol, timeframe, 0, 10)
    if rates is None:
        return False, 0
    return len(rates) == 10, len(rates)


def _print_table(rows: list[SymbolRow]) -> None:
    headers = (
        "coppia",
        "canonico",
        "nome_broker",
        "TROVATO",
        "tick_size",
        "tick_value",
        "contract_size",
        "volume_min",
        "volume_step",
        "digits",
        "storico_H1",
    )
    widths = [14, 10, 22, 8, 12, 12, 14, 12, 12, 8, 12]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        storico = f"{row.history_bars}/10" if row.found else "n/d"
        values = [
            row.pair_label,
            row.canonical,
            row.broker_name or "(mappa vuota)",
            "sì" if row.found else "no",
            row.tick_size,
            row.tick_value,
            row.contract_size,
            row.volume_min,
            row.volume_step,
            row.digits,
            storico if row.history_ok else f"FAIL {storico}",
        ]
        print(" | ".join(str(v).ljust(w) for v, w in zip(values, widths)))


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


def _run_acceptance() -> int:
    accounts = load_accounts()
    profile = get_profile("data_source", accounts)
    profile_name = profile.name

    print("MODULO 1 — test accettazione simboli")
    print(f"Profilo data_source: {profile_name}")
    print(f"Terminale: {profile.path}")
    print(f"Coppie canoniche: {len(CANDIDATE_PAIRS)}")
    print()

    rows: list[SymbolRow] = []
    not_found: list[str] = []
    history_failures: list[str] = []

    with Mt5Session(profile) as mt5:
        for pair in CANDIDATE_PAIRS:
            pair_label = f"{pair.leg_a}/{pair.leg_b}"
            for canonical in (pair.leg_a, pair.leg_b):
                broker_name = _translate(profile_name, canonical, accounts)
                found, meta = _inspect_mapped_symbol(mt5, broker_name)
                history_ok, history_bars = (False, 0)
                if found and broker_name:
                    history_ok, history_bars = _check_history(mt5, broker_name)
                    if not history_ok:
                        history_failures.append(f"{canonical} -> {broker_name} ({history_bars}/10 barre H1)")

                row = SymbolRow(
                    pair_label=pair_label,
                    canonical=canonical,
                    broker_name=broker_name,
                    found=found,
                    tick_size=_fmt(meta.get("tick_size")),
                    tick_value=_fmt(meta.get("tick_value")),
                    contract_size=_fmt(meta.get("contract_size")),
                    volume_min=_fmt(meta.get("volume_min")),
                    volume_step=_fmt(meta.get("volume_step")),
                    digits=_fmt(meta.get("digits")),
                    history_ok=history_ok,
                    history_bars=history_bars,
                )
                rows.append(row)
                if not found:
                    not_found.append(f"{canonical} (coppia {pair_label}) mappa='{broker_name}'")

        _print_table(rows)

        print()
        print("=== Simboli NON trovati (correggere symbol_map) ===")
        if not_found:
            for item in not_found:
                print(f"  - {item}")
        else:
            print("  (nessuno)")

        print()
        print("=== Verifica storico H1 (10 barre) ===")
        if history_failures:
            for item in history_failures:
                print(f"  - FAIL: {item}")
        else:
            found_symbols = {row.broker_name for row in rows if row.found and row.broker_name}
            print(f"  OK: {len(found_symbols)} simboli broker con 10 barre H1")

    print()
    print("Sessione MT5 chiusa.")
    return 1 if not_found or history_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
