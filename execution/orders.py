from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any

from execution.direction import LegAction


class ExecutionError(RuntimeError):
    """Raised when MT5 rejects or cannot process an order."""


@dataclass(frozen=True)
class OrderOutcome:
    symbol: str
    action: LegAction
    volume: float
    magic: int
    dry_run: bool
    retcode: int
    comment: str
    deal_ticket: int | None
    order_ticket: int | None
    request_price: float


def _order_type(mt5: ModuleType, action: LegAction) -> int:
    if action == "BUY":
        return mt5.ORDER_TYPE_BUY
    if action == "SELL":
        return mt5.ORDER_TYPE_SELL
    raise ExecutionError(f"azione non supportata: {action}")


def choose_filling_mode(mt5: ModuleType, symbol: str) -> int:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise ExecutionError(f"symbol_info assente per {symbol}: {mt5.last_error()}")
    mode = int(getattr(info, "filling_mode", 0))
    if mode & 1:
        return mt5.ORDER_FILLING_FOK
    if mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def market_price(mt5: ModuleType, symbol: str, action: LegAction) -> float:
    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        if action == "BUY":
            price = float(tick.ask)
        else:
            price = float(tick.bid)
        if price > 0:
            return price

    info = mt5.symbol_info(symbol)
    if info is not None:
        last = float(getattr(info, "last", 0) or 0)
        if last > 0:
            return last

    raise ExecutionError(f"prezzo non disponibile per {symbol} (mercato chiuso?): {mt5.last_error()}")


def build_market_deal_request(
    mt5: ModuleType,
    symbol: str,
    action: LegAction,
    volume: float,
    magic: int,
    deviation: int,
    comment: str,
) -> dict[str, Any]:
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": _order_type(mt5, action),
        "price": market_price(mt5, symbol, action),
        "deviation": int(deviation),
        "magic": int(magic),
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": choose_filling_mode(mt5, symbol),
    }


def _parse_result(
    result: Any,
    symbol: str,
    action: LegAction,
    volume: float,
    magic: int,
    dry_run: bool,
    request_price: float,
) -> OrderOutcome:
    if result is None:
        raise ExecutionError(f"order fallito per {symbol}: {action} (result=None)")

    retcode = int(getattr(result, "retcode", -1))
    comment = str(getattr(result, "comment", "") or "")
    deal_ticket = getattr(result, "deal", None)
    order_ticket = getattr(result, "order", None)

    success_codes = {10009, 10008}  # TRADE_RETCODE_DONE, PLACED
    market_closed_codes = {10018}  # TRADE_RETCODE_MARKET_CLOSED
    if dry_run:
        success_codes.add(0)
        success_codes.update(market_closed_codes)

    if retcode not in success_codes:
        raise ExecutionError(
            f"order rifiutato {symbol} {action} vol={volume} retcode={retcode} comment={comment}"
        )

    return OrderOutcome(
        symbol=symbol,
        action=action,
        volume=volume,
        magic=magic,
        dry_run=dry_run,
        retcode=retcode,
        comment=comment,
        deal_ticket=int(deal_ticket) if deal_ticket else None,
        order_ticket=int(order_ticket) if order_ticket else None,
        request_price=request_price,
    )


def send_market_deal(
    mt5: ModuleType,
    symbol: str,
    action: LegAction,
    volume: float,
    magic: int,
    deviation: int,
    comment: str,
    *,
    dry_run: bool,
) -> OrderOutcome:
    request = build_market_deal_request(mt5, symbol, action, volume, magic, deviation, comment)
    request_price = float(request["price"])
    if dry_run:
        result = mt5.order_check(request)
    else:
        result = mt5.order_send(request)
    return _parse_result(result, symbol, action, volume, magic, dry_run, request_price)
