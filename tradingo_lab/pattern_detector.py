from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PatternSignal:
    pattern_id: str
    pattern_name: str
    direction: str
    sl_suggested: float


def _body(bar: Dict[str, Any]) -> float:
    return abs(float(bar["close"]) - float(bar["open"]))


def _range(bar: Dict[str, Any]) -> float:
    return float(bar["high"]) - float(bar["low"])


def detect_engulfing(bars: List[Dict[str, Any]], direction: str) -> Optional[PatternSignal]:
    if len(bars) < 2:
        return None
    prev = bars[-2]
    curr = bars[-1]
    prev_open = float(prev["open"])
    prev_close = float(prev["close"])
    curr_open = float(curr["open"])
    curr_close = float(curr["close"])
    prev_body = _body(prev)
    curr_body = _body(curr)
    if curr_body <= prev_body or prev_body <= 0:
        return None

    if (
        direction == "long"
        and prev_close < prev_open
        and curr_close > curr_open
        and curr_open <= prev_close
        and curr_close >= prev_open
    ):
        return PatternSignal("Pattern 1", "ENGULFING", direction, float(curr["low"]))

    if (
        direction == "short"
        and prev_close > prev_open
        and curr_close < curr_open
        and curr_open >= prev_close
        and curr_close <= prev_open
    ):
        return PatternSignal("Pattern 1", "ENGULFING", direction, float(curr["high"]))

    return None


def detect_pin_bar(bars: List[Dict[str, Any]], direction: str) -> Optional[PatternSignal]:
    if not bars:
        return None
    bar = bars[-1]
    high = float(bar["high"])
    low = float(bar["low"])
    open_price = float(bar["open"])
    close_price = float(bar["close"])
    candle_range = high - low
    if candle_range <= 0:
        return None

    body_low = min(open_price, close_price)
    body_high = max(open_price, close_price)
    body = body_high - body_low
    midpoint = low + candle_range / 2.0
    lower_wick = body_low - low
    upper_wick = high - body_high

    if (
        direction == "long"
        and lower_wick >= 2.0 * body
        and body_low >= midpoint
        and close_price > midpoint
    ):
        return PatternSignal("Pattern 2", "PIN_BAR", direction, low)

    if (
        direction == "short"
        and upper_wick >= 2.0 * body
        and body_high <= midpoint
        and close_price < midpoint
    ):
        return PatternSignal("Pattern 2", "PIN_BAR", direction, high)

    return None


def detect_star(
    bars: List[Dict[str, Any]],
    direction: str,
    atr_m1: float,
) -> Optional[PatternSignal]:
    if len(bars) < 3 or atr_m1 <= 0:
        return None
    first, second, third = bars[-3], bars[-2], bars[-1]
    first_open = float(first["open"])
    first_close = float(first["close"])
    third_open = float(third["open"])
    third_close = float(third["close"])
    first_midpoint = (first_open + first_close) / 2.0

    if _range(second) >= atr_m1 * 0.5:
        return None

    if (
        direction == "long"
        and first_close < first_open
        and third_close > third_open
        and third_close > first_midpoint
    ):
        return PatternSignal(
            "Pattern 3",
            "MORNING_STAR",
            direction,
            min(float(bar["low"]) for bar in (first, second, third)),
        )

    if (
        direction == "short"
        and first_close > first_open
        and third_close < third_open
        and third_close < first_midpoint
    ):
        return PatternSignal(
            "Pattern 3",
            "EVENING_STAR",
            direction,
            max(float(bar["high"]) for bar in (first, second, third)),
        )

    return None


def detect_trigger_pattern(
    bars: List[Dict[str, Any]],
    direction: str,
    atr_m1: float,
) -> Optional[PatternSignal]:
    for detector in (
        lambda values: detect_engulfing(values, direction),
        lambda values: detect_pin_bar(values, direction),
        lambda values: detect_star(values, direction, atr_m1),
    ):
        signal = detector(bars)
        if signal is not None:
            return signal
    return None

