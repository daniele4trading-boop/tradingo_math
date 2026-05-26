from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from config import Convergenza7Config
from structure_detector import StructuralLevel, identify_swings


@dataclass(frozen=True)
class RiskPlan:
    entry_price: float
    sl_price: float
    tp_price: float
    rr_effective: float
    target_level_price: float


@dataclass
class OpenTrade:
    timestamp_entry: Any
    direction: str
    entry_price: float
    initial_sl_price: float
    sl_price: float
    tp_price: float
    rr_effective: float
    setup_name: str
    pattern_id: str
    pattern_name: str
    initial_risk: float
    breakeven_trigger: Optional[float]
    breakeven_active: bool = False
    bars_held: int = 0


def structural_target_available(
    entry_price: float,
    sl_price: float,
    direction: str,
    levels: List[StructuralLevel],
    min_rr: float = 2.0,
) -> Optional[StructuralLevel]:
    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return None

    if direction == "long":
        minimum_target = entry_price + risk * min_rr
        candidates = [
            level for level in levels
            if level.kind in ("resistance", "mixed") and level.price >= minimum_target
        ]
        return min(candidates, key=lambda level: level.price) if candidates else None

    minimum_target = entry_price - risk * min_rr
    candidates = [
        level for level in levels
        if level.kind in ("support", "mixed") and level.price <= minimum_target
    ]
    return max(candidates, key=lambda level: level.price) if candidates else None


def build_risk_plan(
    entry_price: float,
    direction: str,
    pattern_sl: float,
    levels: List[StructuralLevel],
    config: Convergenza7Config,
    sweep_extreme: Optional[float] = None,
) -> Optional[RiskPlan]:
    if direction == "long":
        sl_price = min(pattern_sl, sweep_extreme) if sweep_extreme is not None else pattern_sl
        if entry_price - sl_price <= config.min_stop_distance:
            return None
    else:
        sl_price = max(pattern_sl, sweep_extreme) if sweep_extreme is not None else pattern_sl
        if sl_price - entry_price <= config.min_stop_distance:
            return None

    target = structural_target_available(entry_price, sl_price, direction, levels, config.min_rr)
    if target is None:
        return None

    rr_effective = abs(target.price - entry_price) / abs(entry_price - sl_price)
    if rr_effective < config.min_rr:
        return None

    return RiskPlan(
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=target.price,
        rr_effective=rr_effective,
        target_level_price=target.price,
    )


def find_breakeven_trigger(
    entry_price: float,
    direction: str,
    m15_bars: List[Dict[str, Any]],
    config: Convergenza7Config,
) -> Optional[float]:
    swings = identify_swings(m15_bars, config.swing_left, config.swing_right)
    if direction == "long":
        highs = [swing.price for swing in swings if swing.kind == "high" and swing.price > entry_price]
        return min(highs) if highs else None

    lows = [swing.price for swing in swings if swing.kind == "low" and swing.price < entry_price]
    return max(lows) if lows else None


def _exit_reason_for_stop(trade: OpenTrade) -> str:
    if trade.breakeven_active and abs(trade.sl_price - trade.entry_price) <= 1e-9:
        return "BE"
    return "SL"


def close_trade(
    trade: OpenTrade,
    timestamp_exit: Any,
    exit_price: float,
    exit_reason: str,
    config: Convergenza7Config,
) -> Dict[str, Any]:
    if trade.direction == "long":
        realized_rr = (exit_price - trade.entry_price) / trade.initial_risk
    else:
        realized_rr = (trade.entry_price - exit_price) / trade.initial_risk

    result = asdict(trade)
    result.update(
        {
            "timestamp_exit": timestamp_exit,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "realized_rr": realized_rr,
            "pnl_percent": realized_rr * config.risk_percent_per_trade,
            "sl_price": trade.initial_sl_price,
            "final_sl_price": trade.sl_price,
        }
    )
    return result


def update_breakeven(trade: OpenTrade, bar: Dict[str, Any]) -> None:
    if trade.breakeven_active or trade.breakeven_trigger is None:
        return
    if trade.direction == "long" and float(bar["high"]) >= trade.breakeven_trigger:
        trade.sl_price = trade.entry_price
        trade.breakeven_active = True
    elif trade.direction == "short" and float(bar["low"]) <= trade.breakeven_trigger:
        trade.sl_price = trade.entry_price
        trade.breakeven_active = True


def evaluate_trade_on_bar(
    trade: OpenTrade,
    bar: Dict[str, Any],
    config: Convergenza7Config,
) -> Optional[Dict[str, Any]]:
    trade.bars_held += 1
    high = float(bar["high"])
    low = float(bar["low"])

    if trade.direction == "long":
        sl_hit = low <= trade.sl_price
        tp_hit = high >= trade.tp_price
    else:
        sl_hit = high >= trade.sl_price
        tp_hit = low <= trade.tp_price

    if sl_hit and tp_hit:
        if config.same_bar_exit_policy == "optimistic":
            return close_trade(trade, bar["time"], trade.tp_price, "TP", config)
        reason = _exit_reason_for_stop(trade)
        return close_trade(trade, bar["time"], trade.sl_price, reason, config)
    if sl_hit:
        reason = _exit_reason_for_stop(trade)
        return close_trade(trade, bar["time"], trade.sl_price, reason, config)
    if tp_hit:
        return close_trade(trade, bar["time"], trade.tp_price, "TP", config)

    update_breakeven(trade, bar)

    if trade.direction == "long":
        sl_hit_after_be = low <= trade.sl_price
    else:
        sl_hit_after_be = high >= trade.sl_price
    if sl_hit_after_be:
        reason = _exit_reason_for_stop(trade)
        return close_trade(trade, bar["time"], trade.sl_price, reason, config)

    if trade.bars_held >= config.max_trade_bars:
        return close_trade(trade, bar["time"], float(bar["close"]), "timeout", config)

    return None

