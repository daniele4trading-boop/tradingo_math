from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import CANDIDATE_PAIRS, AccountProfile, STATE_DIR, get_profile, load_accounts, load_params
from core.logging_setup import setup_logging
from core.mt5_connection import Mt5Session
from engine.pair_engine import analyze_cached_pair, PairEngineResult
from engine.signals import SignalState
from execution.executor import close_pair_hedge, execute_pair_signal_with_risk
from launch.models import ActionPlan, CycleResult
from risk.guards import account_limit_violations, evaluate_entry_gate
from risk.manager import RiskManager
from risk.models import PortfolioSnapshot
from scanner.scanner import scan_all_pairs

LOGGER = setup_logging("statarb.launch")
REPORT_DIR = STATE_DIR / "launch"


def _candidate_by_index(index: int):
    for candidate in CANDIDATE_PAIRS:
        if candidate.index == index:
            return candidate
    raise ValueError(f"index non valido: {index}")


def _open_pair_labels(portfolio: PortfolioSnapshot | None) -> dict[int, bool]:
    if portfolio is None:
        return {}
    mapping: dict[int, bool] = {}
    for exposure in portfolio.exposures:
        if exposure.fully_hedged:
            mapping[exposure.candidate.index] = True
    return mapping


def _build_plans(
    engine_results: list[PairEngineResult],
    portfolio: PortfolioSnapshot | None,
    gates: dict[int, Any],
) -> list[ActionPlan]:
    open_map = _open_pair_labels(portfolio)
    plans: list[ActionPlan] = []

    for result in engine_results:
        signal_state = result.signal.state.value if result.signal else "ERROR"
        zscore = result.signal.zscore if result.signal else None
        gate = gates.get(result.index)
        gate_allowed = gate.allowed if gate else None
        gate_reason = gate.summary if gate and gate.reasons else ""
        has_open = open_map.get(result.index, False)

        if result.error or result.signal is None:
            action = "SKIP"
        elif has_open and result.signal.state == SignalState.FLAT:
            action = "CLOSE"
        elif has_open:
            action = "HOLD"
        elif result.selection.selected and result.signal.state != SignalState.FLAT:
            if gate_allowed:
                action = "OPEN"
            else:
                action = "SKIP"
        else:
            action = "SKIP"

        plans.append(
            ActionPlan(
                pair_label=result.pair_label,
                index=result.index,
                selected=result.selection.selected,
                signal=signal_state,
                zscore=zscore,
                gate_allowed=gate_allowed,
                gate_reason=gate_reason,
                has_open_hedge=has_open,
                action=action,
            )
        )
    return plans


def _refresh_cache(profile: AccountProfile, accounts: dict[str, Any], params: dict[str, Any]) -> int:
    ok_count = 0
    with Mt5Session(profile) as mt5:
        results = scan_all_pairs(mt5, profile, accounts, params)
        ok_count = sum(1 for item in results if item.ok)
        LOGGER.info("Scan dati completato: %s/%s coppie OK", ok_count, len(CANDIDATE_PAIRS))
    return ok_count


def run_cycle(
    accounts: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    *,
    refresh_data: bool | None = None,
    live_risk: bool = True,
    live_execute: bool = True,
) -> CycleResult:
    accounts = accounts or load_accounts()
    params = params or load_params()
    launch_cfg = params.get("launch", {})

    if refresh_data is None:
        refresh_data = bool(launch_cfg.get("refresh_data_on_cycle", False))

    data_profile = get_profile("data_source", accounts)
    leg_a_profile = get_profile("leg_A", accounts)
    leg_b_profile = get_profile("leg_B", accounts)

    result = CycleResult(
        refresh_data=refresh_data,
        live_risk=live_risk,
        live_execute=live_execute,
        scan_pairs_ok=0,
        pairs_analyzed=0,
        selected_count=0,
        open_hedged_count=0,
    )

    if refresh_data:
        try:
            result.scan_pairs_ok = _refresh_cache(data_profile, accounts, params)
        except Exception as exc:  # noqa: BLE001
            msg = f"refresh_data fallito: {exc}"
            LOGGER.error(msg)
            result.errors.append(msg)

    engine_results: list[PairEngineResult] = []
    for candidate in CANDIDATE_PAIRS:
        engine_results.append(
            analyze_cached_pair(
                data_profile,
                accounts,
                params,
                candidate.index,
                candidate.leg_a,
                candidate.leg_b,
                candidate.category,
            )
        )
    result.engine_results = engine_results
    result.pairs_analyzed = len(engine_results)
    result.selected_count = sum(1 for item in engine_results if item.selection.selected)

    portfolio: PortfolioSnapshot | None = None
    metrics: list = []
    gates: dict[int, Any] = {}

    if live_risk:
        try:
            manager = RiskManager(leg_a_profile, leg_b_profile, params)
            portfolio = manager.load_portfolio()
            metrics = manager.load_account_metrics()
            result.portfolio = portfolio
            result.account_metrics = metrics
            result.open_hedged_count = portfolio.open_pair_count
            result.risk_warnings = []
            if portfolio.unhedged_pairs:
                result.risk_warnings.append(
                    "unhedged: " + ", ".join(p.pair_label for p in portfolio.unhedged_pairs)
                )
            result.risk_warnings.extend(account_limit_violations(metrics, params))
            for candidate in CANDIDATE_PAIRS:
                gates[candidate.index] = evaluate_entry_gate(
                    candidate, portfolio, metrics, params
                )
        except Exception as exc:  # noqa: BLE001
            msg = f"risk phase fallita: {exc}"
            LOGGER.error(msg)
            result.errors.append(msg)

    result.plans = _build_plans(engine_results, portfolio, gates)

    if not live_execute:
        return result

    max_exec = int(launch_cfg.get("max_executions_per_cycle", 1))
    executions_done = 0
    risk_manager = RiskManager(leg_a_profile, leg_b_profile, params)

    # Chiudi prima
    for plan in result.plans:
        if plan.action != "CLOSE":
            continue
        try:
            close_a, close_b, err = close_pair_hedge(
                plan.pair_label,
                leg_a_profile,
                leg_b_profile,
                accounts,
                params,
            )
            if err:
                result.errors.append(f"close {plan.pair_label}: {err}")
            else:
                result.closes.append(plan.pair_label)
                LOGGER.info("Chiuso hedge %s", plan.pair_label)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"close {plan.pair_label}: {exc}")

    # Apri con limiti
    for plan in result.plans:
        if plan.action != "OPEN":
            continue
        if executions_done >= max_exec:
            LOGGER.info("max_executions_per_cycle=%s raggiunto", max_exec)
            break
        engine_result = next(r for r in engine_results if r.index == plan.index)
        try:
            exec_result = execute_pair_signal_with_risk(
                engine_result,
                leg_a_profile,
                leg_b_profile,
                accounts,
                params,
                risk_manager,
            )
            if exec_result is None:
                continue
            result.executions.append(exec_result)
            if exec_result.ok:
                executions_done += 1
                LOGGER.info("Hedge aperto %s dry_run=%s", exec_result.pair_label, exec_result.dry_run)
            elif exec_result.error:
                result.errors.append(f"open {exec_result.pair_label}: {exec_result.error}")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"open {plan.pair_label}: {exc}")

    return result


def save_cycle_report(result: CycleResult, path: Path | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = path if path else REPORT_DIR / "last_cycle.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "refresh_data": result.refresh_data,
        "live_risk": result.live_risk,
        "live_execute": result.live_execute,
        "scan_pairs_ok": result.scan_pairs_ok,
        "pairs_analyzed": result.pairs_analyzed,
        "selected_count": result.selected_count,
        "open_hedged_count": result.open_hedged_count,
        "risk_warnings": result.risk_warnings,
        "errors": result.errors,
        "closes": result.closes,
        "executions": [
            {
                "pair": item.pair_label,
                "signal": item.signal_state.value,
                "ok": item.ok,
                "dry_run": item.dry_run,
                "error": item.error,
            }
            for item in result.executions
        ],
        "plans": [
            {
                "pair": p.pair_label,
                "selected": p.selected,
                "signal": p.signal,
                "zscore": p.zscore,
                "action": p.action,
                "gate": p.gate_reason,
            }
            for p in result.plans
        ],
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
