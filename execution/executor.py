from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.config import CANDIDATE_PAIRS, AccountProfile
from core.symbols import get_pair_magic
from engine.pair_engine import PairEngineResult
from engine.signals import SignalState
from execution.hedge import HedgeExecutionResult, close_hedge, open_hedge

if TYPE_CHECKING:
    from risk.manager import RiskManager


def _candidate_for_result(pair_result: PairEngineResult):
    for candidate in CANDIDATE_PAIRS:
        if candidate.index == pair_result.index:
            return candidate
    raise ValueError(f"coppia non trovata index={pair_result.index}")


def execute_pair_signal(
    pair_result: PairEngineResult,
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
) -> HedgeExecutionResult | None:
    """Open hedge when pair is selected and signal is actionable."""
    if pair_result.error or pair_result.signal is None:
        return None
    if not pair_result.selection.selected:
        return None
    if pair_result.signal.state == SignalState.FLAT:
        return None

    candidate = _candidate_for_result(pair_result)
    return open_hedge(
        leg_a_profile,
        leg_b_profile,
        accounts,
        params,
        candidate.leg_a,
        candidate.leg_b,
        pair_result.signal.state,
        pair_result.selection.hedge_ratio,
        candidate.magic_a,
        candidate.magic_b,
    )


def close_pair_hedge(
    pair_label: str,
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, Any, str | None]:
    canonical_a, canonical_b = pair_label.split("/", maxsplit=1)
    magic_a, magic_b = get_pair_magic(canonical_a, canonical_b)
    return close_hedge(
        leg_a_profile,
        leg_b_profile,
        accounts,
        params,
        canonical_a,
        canonical_b,
        magic_a,
        magic_b,
    )


def execute_pair_signal_with_risk(
    pair_result: PairEngineResult,
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    risk_manager: RiskManager,
) -> HedgeExecutionResult | None:
    """Open hedge only if risk gate allows the entry."""
    if pair_result.error or pair_result.signal is None:
        return None
    if not pair_result.selection.selected:
        return None
    if pair_result.signal.state == SignalState.FLAT:
        return None

    candidate = _candidate_for_result(pair_result)
    gate = risk_manager.check_new_entry(candidate)
    if not gate.allowed:
        return HedgeExecutionResult(
            pair_label=pair_result.pair_label,
            signal_state=pair_result.signal.state,
            leg_a=None,
            leg_b=None,
            lot_a=0.0,
            lot_b=0.0,
            dry_run=bool(params["execution"]["dry_run"]),
            error=f"risk_gate: {gate.summary}",
        )

    return execute_pair_signal(
        pair_result,
        leg_a_profile,
        leg_b_profile,
        accounts,
        params,
    )
