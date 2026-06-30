"""Modulo 4 acceptance: sizing offline + risoluzione simboli + hedge dry-run MT5."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params
from core.mt5_connection import Mt5Session
from core.symbols import ContractMetadata, resolve_broker_symbol
from engine.pair_engine import analyze_cached_pair
from engine.signals import SignalState
from execution.direction import leg_actions
from execution.hedge import open_hedge
from execution.sizing import compute_hedge_volumes, round_volume

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module4_acceptance.txt"
HEDGE_TEST_PAIR = ("GER40", "EU50")


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


def _offline_tests(params: dict) -> list[str]:
    failures: list[str] = []

    meta_a = ContractMetadata(
        canonical="LEG_A",
        broker_symbol="LEG_A",
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        currency_base="USD",
        currency_profit="USD",
        currency_margin="USD",
    )
    meta_b = ContractMetadata(
        canonical="LEG_B",
        broker_symbol="LEG_B",
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        currency_base="USD",
        currency_profit="USD",
        currency_margin="USD",
    )

    rounded = round_volume(0.037, meta_a)
    if rounded != 0.04:
        failures.append(f"round_volume atteso 0.04 ottenuto {rounded}")

    lot_a, lot_b = compute_hedge_volumes(meta_a, meta_b, 100.0, 50.0, 0.8, 10000.0, params)
    if lot_a < meta_a.volume_min or lot_b < meta_b.volume_min:
        failures.append(f"sizing offline non valido lot_a={lot_a} lot_b={lot_b}")

    long_a, long_b = leg_actions(SignalState.LONG_SPREAD)
    short_a, short_b = leg_actions(SignalState.SHORT_SPREAD)
    if (long_a, long_b) != ("BUY", "SELL"):
        failures.append(f"LONG_SPREAD directions errate: {long_a}/{long_b}")
    if (short_a, short_b) != ("SELL", "BUY"):
        failures.append(f"SHORT_SPREAD directions errate: {short_a}/{short_b}")

    return failures


def _unique_canonicals() -> list[str]:
    symbols: list[str] = []
    for pair in CANDIDATE_PAIRS:
        if pair.leg_a not in symbols:
            symbols.append(pair.leg_a)
        if pair.leg_b not in symbols:
            symbols.append(pair.leg_b)
    return symbols


def _symbol_resolution_tests(accounts: dict) -> list[str]:
    failures: list[str] = []
    leg_a_profile = get_profile("leg_A", accounts)
    leg_b_profile = get_profile("leg_B", accounts)
    canonicals = _unique_canonicals()

    print("=== Risoluzione simboli leg_A (ULTIMA) ===")
    with Mt5Session(leg_a_profile) as mt5_a:
        for canonical in canonicals:
            try:
                broker = resolve_broker_symbol(canonical, leg_a_profile, accounts, mt5_a)
                print(f"  OK {canonical} -> {broker}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"leg_A {canonical}: {exc}")
                print(f"  FAIL {canonical}: {exc}")

    print()
    print("=== Risoluzione simboli leg_B (VANTAGE) ===")
    with Mt5Session(leg_b_profile) as mt5_b:
        for canonical in canonicals:
            try:
                broker = resolve_broker_symbol(canonical, leg_b_profile, accounts, mt5_b)
                print(f"  OK {canonical} -> {broker}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"leg_B {canonical}: {exc}")
                print(f"  FAIL {canonical}: {exc}")

    return failures


def _hedge_dry_run_test(accounts: dict, params: dict) -> list[str]:
    failures: list[str] = []
    leg_a_profile = get_profile("leg_A", accounts)
    leg_b_profile = get_profile("leg_B", accounts)
    data_profile = get_profile("data_source", accounts)

    canonical_a, canonical_b = HEDGE_TEST_PAIR
    candidate = next(
        p for p in CANDIDATE_PAIRS if p.leg_a == canonical_a and p.leg_b == canonical_b
    )

    engine_result = analyze_cached_pair(
        data_profile,
        accounts,
        params,
        candidate.index,
        candidate.leg_a,
        candidate.leg_b,
        candidate.category,
    )
    signal_state = (
        engine_result.signal.state
        if engine_result.signal and engine_result.signal.state != SignalState.FLAT
        else SignalState.LONG_SPREAD
    )
    hedge_ratio = engine_result.selection.hedge_ratio
    if not hedge_ratio or hedge_ratio != hedge_ratio:
        hedge_ratio = 1.0

    dry_run = bool(params["execution"]["dry_run"])
    print()
    print(f"=== Hedge test {canonical_a}/{canonical_b} ===")
    print(f"  signal={signal_state.value} hedge_ratio={hedge_ratio:.4f} dry_run={dry_run}")

    result = open_hedge(
        leg_a_profile,
        leg_b_profile,
        accounts,
        params,
        canonical_a,
        canonical_b,
        signal_state,
        hedge_ratio,
        candidate.magic_a,
        candidate.magic_b,
    )

    if not result.ok:
        failures.append(result.error or "open_hedge fallito")
        print(f"  FAIL: {result.error}")
        if result.leg_a and result.leg_a.retcode == 10018:
            print("  (mercato chiuso — order_check 10018 accettabile in dry-run weekend)")
        return failures

    leg_a = result.leg_a
    leg_b = result.leg_b
    print(
        f"  leg_A {leg_a.action} {leg_a.volume} {leg_a.symbol} "
        f"retcode={leg_a.retcode} price={leg_a.request_price}"
    )
    print(
        f"  leg_B {leg_b.action} {leg_b.volume} {leg_b.symbol} "
        f"retcode={leg_b.retcode} price={leg_b.request_price}"
    )
    print(f"  lots: A={result.lot_a} B={result.lot_b}")
    return failures


def _run_acceptance(live_micro: bool) -> int:
    params = load_params()
    if live_micro:
        params = copy.deepcopy(params)
        params["execution"]["dry_run"] = False

    accounts = load_accounts()
    leg_a_profile = get_profile("leg_A", accounts)
    leg_b_profile = get_profile("leg_B", accounts)

    print("MODULO 4 — test accettazione execution")
    print(f"leg_A: {leg_a_profile.name} | leg_B: {leg_b_profile.name}")
    print(
        f"Execution: dry_run={params['execution']['dry_run']} "
        f"deviation={params['execution']['deviation_points']} "
        f"risk={params['risk']['risk_per_trade_pct']}%"
    )
    print()

    failures: list[str] = []
    print("=== Test offline (sizing + directions) ===")
    offline = _offline_tests(params)
    if offline:
        for item in offline:
            print(f"  FAIL: {item}")
        failures.extend(offline)
    else:
        print("  OK")

    failures.extend(_symbol_resolution_tests(accounts))
    failures.extend(_hedge_dry_run_test(accounts, params))

    print()
    print("=== Riepilogo ===")
    print(f"  Errori: {len(failures)}")
    if failures:
        print()
        print("=== Dettaglio errori ===")
        for item in failures:
            print(f"  - {item}")
    else:
        print("  Tutti i controlli PASS")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Modulo 4 acceptance execution")
    parser.add_argument(
        "--live-micro",
        action="store_true",
        help="Esegue ordini reali micro-lot su demo (dry_run=false).",
    )
    args = parser.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("w", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, log_file)
    try:
        return _run_acceptance(live_micro=args.live_micro)
    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log salvato: {LOG_PATH}", file=original_stdout)


if __name__ == "__main__":
    raise SystemExit(main())
