from __future__ import annotations

import math
from typing import Any

from core.symbols import ContractMetadata


class SizingError(ValueError):
    """Raised when hedge volumes cannot be computed."""


def round_volume(volume: float, meta: ContractMetadata) -> float:
    step = meta.volume_step
    if step <= 0:
        return float(meta.volume_min)
    steps = round(volume / step)
    clamped = steps * step
    clamped = max(float(meta.volume_min), min(float(meta.volume_max), clamped))
    if step >= 1:
        return float(int(clamped))
    decimals = max(0, int(round(-math.log10(step))) if step < 1 else 0)
    return round(clamped, decimals)


def notional_per_lot(meta: ContractMetadata, price: float) -> float:
    if price <= 0 or meta.trade_contract_size <= 0:
        raise SizingError(f"prezzo o contract_size non validi per {meta.broker_symbol}")
    return float(price) * float(meta.trade_contract_size)


def compute_hedge_volumes(
    meta_a: ContractMetadata,
    meta_b: ContractMetadata,
    price_a: float,
    price_b: float,
    hedge_ratio: float,
    equity: float,
    params: dict[str, Any],
) -> tuple[float, float]:
    risk = params["risk"]
    execution = params["execution"]
    risk_money = float(equity) * float(risk["risk_per_trade_pct"]) / 100.0
    move_pct = float(execution["assumed_move_pct_for_sizing"]) / 100.0
    if risk_money <= 0:
        raise SizingError("risk money <= 0")

    notional_a = notional_per_lot(meta_a, price_a)
    loss_per_lot_a = notional_a * move_pct
    if loss_per_lot_a <= 0:
        raise SizingError("loss_per_lot_a non positivo")

    lot_a = risk_money / loss_per_lot_a
    lot_a = round_volume(lot_a, meta_a)

    beta = abs(float(hedge_ratio))
    if not math.isfinite(beta) or beta <= 0:
        beta = 1.0

    notional_b_target = lot_a * notional_a * beta
    notional_b_per_lot = notional_per_lot(meta_b, price_b)
    lot_b = notional_b_target / notional_b_per_lot
    lot_b = round_volume(lot_b, meta_b)

    if lot_a < meta_a.volume_min or lot_b < meta_b.volume_min:
        raise SizingError(
            f"volumi sotto minimo: lot_a={lot_a} lot_b={lot_b} "
            f"(min {meta_a.volume_min}/{meta_b.volume_min})"
        )
    return lot_a, lot_b
