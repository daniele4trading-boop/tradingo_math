from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import AccountProfile
from core.mt5_connection import Mt5Session
from core.symbols import SymbolResolutionError, get_contract_metadata, resolve_broker_symbol
from engine.pair_engine import PairEngineResult
from engine.signals import SignalState
from execution.direction import DirectionError, leg_actions
from execution.orders import ExecutionError, OrderOutcome, market_price, send_market_deal
from execution.positions import close_position, list_open_positions
from execution.sizing import compute_hedge_volumes


@dataclass(frozen=True)
class ResolvedLeg:
    profile: AccountProfile
    canonical: str
    broker_symbol: str
    meta: Any


@dataclass(frozen=True)
class HedgeExecutionResult:
    pair_label: str
    signal_state: SignalState
    leg_a: OrderOutcome | None
    leg_b: OrderOutcome | None
    lot_a: float
    lot_b: float
    dry_run: bool
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and self.leg_a is not None and self.leg_b is not None


def _execution_comment(params: dict[str, Any], pair_label: str, suffix: str) -> str:
    prefix = str(params["execution"]["comment_prefix"])
    return f"{prefix}:{pair_label}:{suffix}"[:31]


def _resolve_leg(
    profile: AccountProfile,
    canonical: str,
    accounts: dict[str, Any],
    mt5: Any,
) -> ResolvedLeg:
    broker_symbol = resolve_broker_symbol(canonical, profile, accounts, mt5)
    meta = get_contract_metadata(mt5, canonical, broker_symbol)
    return ResolvedLeg(profile=profile, canonical=canonical, broker_symbol=broker_symbol, meta=meta)


def _account_equity(mt5: Any) -> float:
    info = mt5.account_info()
    if info is None:
        raise ExecutionError(f"account_info assente: {mt5.last_error()}")
    return float(info.equity)


def open_hedge(
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    canonical_a: str,
    canonical_b: str,
    signal_state: SignalState,
    hedge_ratio: float,
    magic_a: int,
    magic_b: int,
) -> HedgeExecutionResult:
    pair_label = f"{canonical_a}/{canonical_b}"
    dry_run = bool(params["execution"]["dry_run"])
    deviation = int(params["execution"]["deviation_points"])

    try:
        action_a, action_b = leg_actions(signal_state)
    except DirectionError as exc:
        return HedgeExecutionResult(
            pair_label=pair_label,
            signal_state=signal_state,
            leg_a=None,
            leg_b=None,
            lot_a=0.0,
            lot_b=0.0,
            dry_run=dry_run,
            error=str(exc),
        )

    leg_a_outcome: OrderOutcome | None = None
    leg_b_outcome: OrderOutcome | None = None
    lot_a = 0.0
    lot_b = 0.0
    leg_a: ResolvedLeg | None = None
    leg_b: ResolvedLeg | None = None

    try:
        with Mt5Session(leg_a_profile) as mt5_a:
            leg_a = _resolve_leg(leg_a_profile, canonical_a, accounts, mt5_a)
            price_a = market_price(mt5_a, leg_a.broker_symbol, action_a)
            equity_a = _account_equity(mt5_a)

        with Mt5Session(leg_b_profile) as mt5_b:
            leg_b = _resolve_leg(leg_b_profile, canonical_b, accounts, mt5_b)
            price_b = market_price(mt5_b, leg_b.broker_symbol, action_b)
            equity_b = _account_equity(mt5_b)

        if leg_a is None or leg_b is None:
            raise ExecutionError("risoluzione gambe incompleta")

        equity = min(equity_a, equity_b)
        lot_a, lot_b = compute_hedge_volumes(
            leg_a.meta,
            leg_b.meta,
            price_a,
            price_b,
            hedge_ratio,
            equity,
            params,
        )

        with Mt5Session(leg_a_profile) as mt5_a:
            leg_a_outcome = send_market_deal(
                mt5_a,
                leg_a.broker_symbol,
                action_a,
                lot_a,
                magic_a,
                deviation,
                _execution_comment(params, pair_label, "openA"),
                dry_run=dry_run,
            )

        with Mt5Session(leg_b_profile) as mt5_b:
            leg_b_outcome = send_market_deal(
                mt5_b,
                leg_b.broker_symbol,
                action_b,
                lot_b,
                magic_b,
                deviation,
                _execution_comment(params, pair_label, "openB"),
                dry_run=dry_run,
            )
    except (ExecutionError, ValueError, SymbolResolutionError) as exc:
        return HedgeExecutionResult(
            pair_label=pair_label,
            signal_state=signal_state,
            leg_a=leg_a_outcome,
            leg_b=leg_b_outcome,
            lot_a=lot_a,
            lot_b=lot_b,
            dry_run=dry_run,
            error=str(exc),
        )

    return HedgeExecutionResult(
        pair_label=pair_label,
        signal_state=signal_state,
        leg_a=leg_a_outcome,
        leg_b=leg_b_outcome,
        lot_a=lot_a,
        lot_b=lot_b,
        dry_run=dry_run,
        error=None,
    )


def close_hedge(
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    canonical_a: str,
    canonical_b: str,
    magic_a: int,
    magic_b: int,
) -> tuple[OrderOutcome | None, OrderOutcome | None, str | None]:
    pair_label = f"{canonical_a}/{canonical_b}"
    dry_run = bool(params["execution"]["dry_run"])
    deviation = int(params["execution"]["deviation_points"])
    leg_a_outcome: OrderOutcome | None = None
    leg_b_outcome: OrderOutcome | None = None

    try:
        with Mt5Session(leg_a_profile) as mt5_a:
            broker_a = resolve_broker_symbol(canonical_a, leg_a_profile, accounts, mt5_a)
            positions_a = list_open_positions(mt5_a, symbol=broker_a, magic=magic_a)
            if not positions_a:
                raise ExecutionError(f"nessuna posizione leg_a {pair_label} magic={magic_a}")
            leg_a_outcome = close_position(
                mt5_a,
                positions_a[0],
                deviation,
                _execution_comment(params, pair_label, "closeA"),
                dry_run=dry_run,
            )

        with Mt5Session(leg_b_profile) as mt5_b:
            broker_b = resolve_broker_symbol(canonical_b, leg_b_profile, accounts, mt5_b)
            positions_b = list_open_positions(mt5_b, symbol=broker_b, magic=magic_b)
            if not positions_b:
                raise ExecutionError(f"nessuna posizione leg_b {pair_label} magic={magic_b}")
            leg_b_outcome = close_position(
                mt5_b,
                positions_b[0],
                deviation,
                _execution_comment(params, pair_label, "closeB"),
                dry_run=dry_run,
            )
    except (ExecutionError, ValueError, SymbolResolutionError) as exc:
        return leg_a_outcome, leg_b_outcome, str(exc)

    return leg_a_outcome, leg_b_outcome, None
