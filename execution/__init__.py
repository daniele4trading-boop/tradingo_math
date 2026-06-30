"""Execution package — hedge orders on leg_A / leg_B MT5 terminals."""

from execution.direction import leg_actions
from execution.hedge import HedgeExecutionResult, close_hedge, open_hedge
from execution.orders import ExecutionError, OrderOutcome
from execution.sizing import compute_hedge_volumes, round_volume

__all__ = [
    "ExecutionError",
    "HedgeExecutionResult",
    "OrderOutcome",
    "close_hedge",
    "close_pair_hedge",
    "compute_hedge_volumes",
    "execute_pair_signal",
    "execute_pair_signal_with_risk",
    "leg_actions",
    "open_hedge",
    "round_volume",
]


def __getattr__(name: str):
    if name in ("close_pair_hedge", "execute_pair_signal", "execute_pair_signal_with_risk"):
        from execution.executor import (
            close_pair_hedge,
            execute_pair_signal,
            execute_pair_signal_with_risk,
        )

        exports = {
            "close_pair_hedge": close_pair_hedge,
            "execute_pair_signal": execute_pair_signal,
            "execute_pair_signal_with_risk": execute_pair_signal_with_risk,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
