from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any


class TimeframeError(ValueError):
    """Raised when a timeframe string cannot be mapped to MT5."""


@dataclass(frozen=True)
class TimeframeSpec:
    label: str
    mt5_name: str
    bars_per_day: int


TIMEFRAME_SPECS: dict[str, TimeframeSpec] = {
    "M15": TimeframeSpec("M15", "TIMEFRAME_M15", 96),
    "H1": TimeframeSpec("H1", "TIMEFRAME_H1", 24),
    "H4": TimeframeSpec("H4", "TIMEFRAME_H4", 6),
    "D1": TimeframeSpec("D1", "TIMEFRAME_D1", 1),
}


def resolve_timeframe(mt5: ModuleType, label: str) -> tuple[int, TimeframeSpec]:
    spec = TIMEFRAME_SPECS.get(label.upper())
    if spec is None:
        raise TimeframeError(f"Timeframe non supportato: {label}")
    constant = getattr(mt5, spec.mt5_name, None)
    if constant is None:
        raise TimeframeError(f"Costante MT5 mancante: {spec.mt5_name}")
    return int(constant), spec


def expected_bars(spec: TimeframeSpec, lookback_days: int, *, buffer_ratio: float = 0.80) -> tuple[int, int]:
    """Return (requested_count, minimum_acceptable_bars)."""
    requested = max(int(lookback_days * spec.bars_per_day * 1.20) + 10, 100)
    minimum = max(int(lookback_days * spec.bars_per_day * buffer_ratio), 50)
    return requested, minimum


def trigger_timeframe_for_category(category: str, params: dict[str, Any]) -> str:
    data = params["data"]
    if category == "indici":
        return str(data["trigger_timeframe_indices"]).upper()
    return str(data["trigger_timeframe_default"]).upper()


def structural_timeframe(params: dict[str, Any]) -> str:
    return str(params["data"]["structural_timeframe"]).upper()
