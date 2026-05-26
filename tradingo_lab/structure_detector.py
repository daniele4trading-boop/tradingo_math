from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from config import Convergenza7Config


@dataclass(frozen=True)
class Swing:
    time: Any
    index: int
    price: float
    kind: str


@dataclass(frozen=True)
class StructuralLevel:
    price: float
    kind: str
    touches: int
    first_time: Any
    last_time: Any


@dataclass(frozen=True)
class SetupSignal:
    setup_name: str
    direction: str
    level_price: float
    level_kind: str
    zone_atr: float
    sweep_extreme: Optional[float] = None


def latest_atr(bars: List[Dict[str, Any]], period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    true_ranges: List[float] = []
    prev_close = float(bars[0]["close"])
    for bar in bars[1:]:
        high = float(bar["high"])
        low = float(bar["low"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = float(bar["close"])
    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window) if window else 0.0


def identify_swings(
    bars: List[Dict[str, Any]],
    left: int = 2,
    right: int = 2,
) -> List[Swing]:
    swings: List[Swing] = []
    if len(bars) < left + right + 1:
        return swings

    for idx in range(left, len(bars) - right):
        center = bars[idx]
        left_bars = bars[idx - left:idx]
        right_bars = bars[idx + 1:idx + right + 1]
        high = float(center["high"])
        low = float(center["low"])

        if high > max(float(bar["high"]) for bar in left_bars) and high > max(
            float(bar["high"]) for bar in right_bars
        ):
            swings.append(Swing(center["time"], idx, high, "high"))

        if low < min(float(bar["low"]) for bar in left_bars) and low < min(
            float(bar["low"]) for bar in right_bars
        ):
            swings.append(Swing(center["time"], idx, low, "low"))

    return sorted(swings, key=lambda swing: (swing.index, swing.kind))


def determine_bias(
    bars: List[Dict[str, Any]],
    min_swings: int = 3,
    left: int = 2,
    right: int = 2,
) -> str:
    swings = identify_swings(bars, left=left, right=right)
    highs = [swing for swing in swings if swing.kind == "high"][-min_swings:]
    lows = [swing for swing in swings if swing.kind == "low"][-min_swings:]
    if len(highs) < min_swings or len(lows) < min_swings:
        return "NONE"

    higher_highs = all(highs[idx].price > highs[idx - 1].price for idx in range(1, len(highs)))
    higher_lows = all(lows[idx].price > lows[idx - 1].price for idx in range(1, len(lows)))
    lower_highs = all(highs[idx].price < highs[idx - 1].price for idx in range(1, len(highs)))
    lower_lows = all(lows[idx].price < lows[idx - 1].price for idx in range(1, len(lows)))

    if higher_highs and higher_lows:
        return "long"
    if lower_highs and lower_lows:
        return "short"
    return "NONE"


def is_lateral_market(
    bars: List[Dict[str, Any]],
    atr_value: float,
    lookback: int = 10,
    atr_threshold: float = 1.5,
) -> bool:
    if len(bars) < lookback or atr_value <= 0:
        return False
    window = bars[-lookback:]
    range_size = max(float(bar["high"]) for bar in window) - min(float(bar["low"]) for bar in window)
    return range_size <= atr_value * atr_threshold


def _event_touches_level(bar: Dict[str, Any], price: float, tolerance: float) -> bool:
    return float(bar["low"]) - tolerance <= price <= float(bar["high"]) + tolerance


def _level_kind(support_touches: int, resistance_touches: int) -> str:
    if support_touches and resistance_touches:
        return "mixed"
    if support_touches:
        return "support"
    return "resistance"


def identify_horizontal_levels(
    bars: List[Dict[str, Any]],
    atr_value: float,
    lookback: int = 50,
    min_touches: int = 2,
    tolerance_atr: float = 0.3,
) -> List[StructuralLevel]:
    if not bars:
        return []

    window = bars[-lookback:]
    tolerance = max(atr_value * tolerance_atr, 1e-9)
    groups: List[Dict[str, Any]] = []

    for bar in window:
        events = (
            (float(bar["low"]), "support", bar["time"]),
            (float(bar["high"]), "resistance", bar["time"]),
        )
        for price, kind, timestamp in events:
            matched = None
            for group in groups:
                if abs(price - group["price"]) <= tolerance:
                    matched = group
                    break
            if matched is None:
                matched = {
                    "price": price,
                    "events": [],
                    "support": 0,
                    "resistance": 0,
                }
                groups.append(matched)
            matched["events"].append((timestamp, price, kind))
            matched[kind] += 1
            matched["price"] = sum(event[1] for event in matched["events"]) / len(matched["events"])

    levels: List[StructuralLevel] = []
    for group in groups:
        unique_timestamps = {event[0] for event in group["events"]}
        touches = len(unique_timestamps)
        if touches < min_touches:
            continue
        levels.append(
            StructuralLevel(
                price=float(group["price"]),
                kind=_level_kind(group["support"], group["resistance"]),
                touches=touches,
                first_time=min(unique_timestamps),
                last_time=max(unique_timestamps),
            )
        )
    return sorted(levels, key=lambda level: level.price)


def count_level_touches(
    bars: Iterable[Dict[str, Any]],
    price: float,
    tolerance: float,
) -> int:
    return sum(1 for bar in bars if _event_touches_level(bar, price, tolerance))


def is_retracement(bars: List[Dict[str, Any]], direction: str, lookback: int = 3) -> bool:
    if len(bars) <= lookback:
        return False
    current_close = float(bars[-1]["close"])
    prior_close = float(bars[-1 - lookback]["close"])
    if direction == "long":
        return current_close <= prior_close
    return current_close >= prior_close


def detect_structural_zone_setup(
    m15_bars: List[Dict[str, Any]],
    direction: str,
    levels: List[StructuralLevel],
    atr_value: float,
    config: Convergenza7Config,
) -> Optional[SetupSignal]:
    if not m15_bars or atr_value <= 0:
        return None
    if not is_retracement(m15_bars, direction, config.retracement_lookback):
        return None

    current_price = float(m15_bars[-1]["close"])
    max_distance = atr_value * config.setup_distance_atr
    allowed_kinds = ("support", "mixed") if direction == "long" else ("resistance", "mixed")

    candidates = [
        level for level in levels
        if level.kind in allowed_kinds and abs(current_price - level.price) <= max_distance
    ]
    if direction == "long":
        candidates = [level for level in candidates if level.price <= current_price + max_distance]
    else:
        candidates = [level for level in candidates if level.price >= current_price - max_distance]
    if not candidates:
        return None

    chosen = min(candidates, key=lambda level: abs(current_price - level.price))
    return SetupSignal("Setup A", direction, chosen.price, chosen.kind, atr_value)


def _recent_swing_level(
    m15_bars: List[Dict[str, Any]],
    direction: str,
    config: Convergenza7Config,
) -> Optional[Swing]:
    swings = identify_swings(m15_bars, config.swing_left, config.swing_right)
    wanted = "low" if direction == "long" else "high"
    candidates = [swing for swing in swings if swing.kind == wanted]
    return candidates[-1] if candidates else None


def detect_liquidity_sweep(
    m5_bars: List[Dict[str, Any]],
    m15_bars: List[Dict[str, Any]],
    direction: str,
    atr_value: float,
    config: Convergenza7Config,
) -> Optional[SetupSignal]:
    if not m5_bars or not m15_bars or atr_value <= 0:
        return None

    swing = _recent_swing_level(m15_bars, direction, config)
    if swing is None:
        return None

    tolerance = atr_value * config.structural_level_tolerance_atr
    prior_bars = [bar for bar in m15_bars if bar["time"] < swing.time]
    if count_level_touches(prior_bars, swing.price, tolerance) < config.structural_level_min_touches:
        return None

    candle = m5_bars[-1]
    close_price = float(candle["close"])
    high = float(candle["high"])
    low = float(candle["low"])

    if direction == "long" and low < swing.price and close_price > swing.price:
        return SetupSignal("Setup B", direction, swing.price, "support", atr_value, sweep_extreme=low)
    if direction == "short" and high > swing.price and close_price < swing.price:
        return SetupSignal("Setup B", direction, swing.price, "resistance", atr_value, sweep_extreme=high)
    return None

