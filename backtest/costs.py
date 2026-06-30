from __future__ import annotations

from typing import Any


def round_trip_cost(
    lot_a: float,
    lot_b: float,
    params: dict[str, Any],
    *,
    spread_points_a: float = 0.0,
    spread_points_b: float = 0.0,
) -> float:
    costs = params["costs"]
    commission = float(costs["model_commission_per_lot"])
    total = 0.0
    # Open + close, both legs
    total += 4.0 * commission * (lot_a + lot_b) / 2.0
    if costs["model_spread"] and (spread_points_a > 0 or spread_points_b > 0):
        # MT5 spread column: rough charge in account currency units
        total += (spread_points_a * lot_a + spread_points_b * lot_b) * 0.01
    return total


def estimate_lots(
    price_a: float,
    price_b: float,
    hedge_ratio: float,
    params: dict[str, Any],
) -> tuple[float, float]:
    backtest = params["backtest"]
    equity = float(backtest["initial_equity"])
    lot_a = float(backtest["lot_a"])
    contract = float(backtest["contract_size"])
    beta = abs(float(hedge_ratio)) if hedge_ratio > 0 else 1.0
    notional_a = lot_a * contract * price_a
    notional_b_per_lot = contract * price_b
    lot_b = (notional_a * beta) / notional_b_per_lot if notional_b_per_lot > 0 else lot_a
    lot_b = max(lot_b, float(backtest["lot_min"]))
    return lot_a, lot_b


def pnl_scale(price_a: float, lot_a: float, contract_size: float, params: dict[str, Any]) -> float:
    """Convert log-spread change to approximate currency PnL."""
    backtest = params["backtest"]
    equity = float(backtest["initial_equity"])
    risk_pct = float(params["risk"]["risk_per_trade_pct"])
    move_pct = float(params["execution"]["assumed_move_pct_for_sizing"]) / 100.0
    notional = lot_a * contract_size * price_a
    risk_money = equity * risk_pct / 100.0
    if move_pct <= 0:
        return notional
    return risk_money / move_pct
