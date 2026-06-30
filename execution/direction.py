from __future__ import annotations

from engine.signals import SignalState

LegAction = str  # "BUY" | "SELL"


class DirectionError(ValueError):
    """Raised when a signal state cannot be mapped to hedge legs."""


def leg_actions(state: SignalState) -> tuple[LegAction, LegAction]:
    """Return (leg_a, leg_b) market actions for opening the spread position."""
    if state == SignalState.LONG_SPREAD:
        return "BUY", "SELL"
    if state == SignalState.SHORT_SPREAD:
        return "SELL", "BUY"
    raise DirectionError(f"segnale {state.value} non apre hedge")


def close_actions(open_a: LegAction, open_b: LegAction) -> tuple[LegAction, LegAction]:
    flip = {"BUY": "SELL", "SELL": "BUY"}
    return flip[open_a], flip[open_b]
