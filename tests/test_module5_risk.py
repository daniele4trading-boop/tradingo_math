"""Modulo 5 acceptance: risk guards offline + portfolio/account MT5 scan."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params
from risk.guards import evaluate_entry_gate
from risk.manager import RiskManager
from risk.models import AccountRiskMetrics
from risk.portfolio import portfolio_from_magics
from risk.snapshots import daily_loss_pct, drawdown_pct

LOG_PATH = PROJECT_ROOT / "state" / "statarb_logs" / "module5_acceptance.txt"


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

    if daily_loss_pct(10000, 9500) != 5.0:
        failures.append("daily_loss_pct calcolo errato")
    if drawdown_pct(10000, 9200) != 8.0:
        failures.append("drawdown_pct calcolo errato")
    if daily_loss_pct(10000, 10100) != 0.0:
        failures.append("daily_loss_pct non zero su guadagno")

    # Simula 2 pair aperte + EURUSD condiviso
    eur_gbp = CANDIDATE_PAIRS[3]
    eur_chf = CANDIDATE_PAIRS[5]
    magics_a = {eur_gbp.magic_a, eur_chf.magic_a}
    magics_b = {eur_gbp.magic_b, eur_chf.magic_b}
    portfolio = portfolio_from_magics(magics_a, magics_b)

    if portfolio.open_pair_count != 2:
        failures.append(f"open_pair_count atteso 2 ottenuto {portfolio.open_pair_count}")

    gate = evaluate_entry_gate(
        CANDIDATE_PAIRS[6],  # EURUSD/AUDUSD shares EURUSD
        portfolio,
        [],
        params,
    )
    if gate.allowed:
        failures.append("gate dovrebbe bloccare EURUSD/AUDUSD per leg sharing")

    metrics_bad = [
        AccountRiskMetrics("ULTIMA_DEMO", 9000, 9000, 100, 500, 5.0, 3.0),
        AccountRiskMetrics("VANTAGE_DEMO", 9000, 9000, 100, 500, 2.0, 2.0),
    ]
    gate_dd = evaluate_entry_gate(CANDIDATE_PAIRS[0], portfolio_from_magics(set(), set()), metrics_bad, params)
    if gate_dd.allowed:
        failures.append("gate dovrebbe bloccare daily loss > 4%")

    metrics_margin = [
        AccountRiskMetrics("ULTIMA_DEMO", 10000, 10000, 5000, 150, 0, 0),
        AccountRiskMetrics("VANTAGE_DEMO", 10000, 10000, 100, 500, 0, 0),
    ]
    gate_margin = evaluate_entry_gate(
        CANDIDATE_PAIRS[0], portfolio_from_magics(set(), set()), metrics_margin, params
    )
    if gate_margin.allowed:
        failures.append("gate dovrebbe bloccare margin_level < 200%")

    unhedged = portfolio_from_magics({eur_gbp.magic_a}, set())
    gate_unhedged = evaluate_entry_gate(CANDIDATE_PAIRS[0], unhedged, [], params)
    if gate_unhedged.allowed:
        failures.append("gate dovrebbe bloccare con posizioni unhedged")

    return failures


def _live_status_tests(params: dict) -> list[str]:
    failures: list[str] = []
    accounts = load_accounts()
    leg_a = get_profile("leg_A", accounts)
    leg_b = get_profile("leg_B", accounts)
    manager = RiskManager(leg_a, leg_b, params)

    portfolio, metrics, warnings = manager.full_status()

    print("=== Account metrics ===")
    for metric in metrics:
        print(
            f"  {metric.profile_name}: equity={metric.equity:.2f} "
            f"margin_lvl={metric.margin_level:.1f}% "
            f"daily_loss={metric.daily_loss_pct:.2f}% dd={metric.drawdown_pct:.2f}%"
        )

    print()
    print("=== Portfolio ===")
    print(f"  Pair aperti (hedged): {portfolio.open_pair_count}")
    if portfolio.open_pairs:
        for item in portfolio.open_pairs:
            print(f"    - {item.pair_label}")
    if portfolio.unhedged_pairs:
        for item in portfolio.unhedged_pairs:
            print(f"    UNHEDGED {item.pair_label} (A={item.leg_a_open} B={item.leg_b_open})")

    print()
    print("=== Risk warnings ===")
    if warnings:
        for warning in warnings:
            print(f"  WARN: {warning}")
    else:
        print("  (nessuno)")

    print()
    print("=== Gate test GER40/EU50 (candidato nuovo ingresso) ===")
    ger_eu = CANDIDATE_PAIRS[9]
    gate = manager.check_new_entry(ger_eu)
    print(f"  allowed={gate.allowed}")
    if gate.reasons:
        for reason in gate.reasons:
            print(f"    - {reason}")

    # Live test passes if manager can read accounts without exception
    return failures


def _run_acceptance() -> int:
    params = load_params()
    risk = params["risk"]

    print("MODULO 5 — test accettazione risk")
    print(
        f"Limits: max_pairs={risk['max_concurrent_pairs']} "
        f"max_leg_share={risk['max_pairs_sharing_leg']} "
        f"daily_loss={risk['per_account_daily_loss_pct']}% "
        f"max_dd={risk['per_account_max_dd_pct']}% "
        f"margin_floor={risk['margin_floor_pct']}%"
    )
    print()

    failures: list[str] = []

    print("=== Test offline (guards + portfolio logic) ===")
    offline = _offline_tests(params)
    if offline:
        for item in offline:
            print(f"  FAIL: {item}")
        failures.extend(offline)
    else:
        print("  OK")

    failures.extend(_live_status_tests(params))

    print()
    print("=== Riepilogo ===")
    print(f"  Errori: {len(failures)}")
    if failures:
        for item in failures:
            print(f"  - {item}")
    else:
        print("  Tutti i controlli PASS")

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
