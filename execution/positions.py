from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any

from execution.direction import LegAction, close_actions
from execution.orders import (
    ExecutionError,
    OrderOutcome,
    choose_filling_mode,
    market_price,
    send_market_deal,
)


@dataclass(frozen=True)
class OpenPosition:
    ticket: int
    symbol: str
    magic: int
    volume: float
    position_type: int
    open_action: LegAction


def _position_open_action(mt5: ModuleType, position_type: int) -> LegAction:
    if position_type == mt5.POSITION_TYPE_BUY:
        return "BUY"
    if position_type == mt5.POSITION_TYPE_SELL:
        return "SELL"
    raise ExecutionError(f"position_type non supportato: {position_type}")


def list_open_positions(
    mt5: ModuleType,
    *,
    symbol: str | None = None,
    magic: int | None = None,
) -> list[OpenPosition]:
    if symbol:
        raw = mt5.positions_get(symbol=symbol)
    else:
        raw = mt5.positions_get()
    if raw is None:
        return []
    positions: list[OpenPosition] = []
    for item in raw:
        item_magic = int(getattr(item, "magic", 0))
        if magic is not None and item_magic != magic:
            continue
        positions.append(
            OpenPosition(
                ticket=int(item.ticket),
                symbol=str(item.symbol),
                magic=item_magic,
                volume=float(item.volume),
                position_type=int(item.type),
                open_action=_position_open_action(mt5, int(item.type)),
            )
        )
    return positions


def build_close_request(
    mt5: ModuleType,
    position: OpenPosition,
    deviation: int,
    comment: str,
) -> dict[str, Any]:
    close_action = close_actions(position.open_action, position.open_action)[0]
    close_type = mt5.ORDER_TYPE_SELL if position.open_action == "BUY" else mt5.ORDER_TYPE_BUY
    price = market_price(mt5, position.symbol, close_action)
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_type,
        "price": price,
        "deviation": int(deviation),
        "magic": position.magic,
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": choose_filling_mode(mt5, position.symbol),
    }


def close_position(
    mt5: ModuleType,
    position: OpenPosition,
    deviation: int,
    comment: str,
    *,
    dry_run: bool,
) -> OrderOutcome:
    close_action = close_actions(position.open_action, position.open_action)[0]
    request = build_close_request(mt5, position, deviation, comment)
    request_price = float(request["price"])
    if dry_run:
        result = mt5.order_check(request)
    else:
        result = mt5.order_send(request)
    if result is None:
        raise ExecutionError(f"close fallito ticket={position.ticket}")

    retcode = int(getattr(result, "retcode", -1))
    result_comment = str(getattr(result, "comment", "") or "")
    success_codes = {10009, 10008}
    market_closed_codes = {10018}
    if dry_run:
        success_codes.add(0)
        success_codes.update(market_closed_codes)
    if retcode not in success_codes:
        raise ExecutionError(
            f"close rifiutato ticket={position.ticket} retcode={retcode} comment={result_comment}"
        )
    return OrderOutcome(
        symbol=position.symbol,
        action=close_action,
        volume=position.volume,
        magic=position.magic,
        dry_run=dry_run,
        retcode=retcode,
        comment=result_comment,
        deal_ticket=int(getattr(result, "deal", 0)) or None,
        order_ticket=int(getattr(result, "order", 0)) or None,
        request_price=request_price,
    )
