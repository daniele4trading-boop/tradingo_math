"""Logging strutturato JSON con rotazione.

Ogni evento e' una riga JSON in `journal_YYYYMMDD.jsonl`. Il campo piu' importante
del forward test e' lo scostamento fra prezzo teorico e fill effettivo, quindi
viene loggato su ogni evento di ordine, anche cancellato o non eseguito.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .types import OpenTrade, PendingOrder


class Journal:
    def __init__(
        self,
        log_dir: str | Path,
        max_bytes: int = 20_000_000,
        backup_count: int = 30,
    ) -> None:
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handlers: dict[str, logging.Handler] = {}
        self._loggers: dict[str, logging.Logger] = {}

    def _logger(self) -> logging.Logger:
        day = datetime.now(UTC).strftime("%Y%m%d")
        if day in self._loggers:
            return self._loggers[day]
        logger = logging.getLogger(f"pattern_go.journal.{day}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            self.dir / f"journal_{day}.jsonl",
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.handlers = [handler]
        self._loggers[day] = logger
        self._handlers[day] = handler
        return logger

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            **_jsonable(fields),
        }
        self._logger().info(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return record

    # --- helper specifici ----------------------------------------------------

    def order_event(self, event: str, order: PendingOrder, **extra: Any) -> dict[str, Any]:
        return self.write(
            event,
            strategy=order.strategy,
            side=order.side.value,
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            signal_time=order.signal_bar_time.isoformat(),
            theoretical_entry_price=order.trigger_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            risk=order.risk,
            quantity=order.quantity,
            spread_at_signal=order.spread_at_signal,
            **order.features.as_dict(),
            **extra,
        )

    def trade_opened(self, trade: OpenTrade, order: PendingOrder, **extra: Any) -> dict[str, Any]:
        return self.write(
            "TRADE_OPENED",
            strategy=trade.strategy,
            side=trade.side.value,
            client_order_id=trade.client_order_id,
            signal_time=order.signal_bar_time.isoformat(),
            entry_time=trade.entry_time.isoformat(),
            theoretical_entry_price=trade.theoretical_entry_price,
            entry_price=trade.entry_price,
            slippage=trade.slippage,
            spread_at_signal=order.spread_at_signal,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            risk=trade.risk,
            quantity=trade.quantity,
            risk_currency=trade.risk * trade.quantity,
            **order.features.as_dict(),
            **extra,
        )

    def trade_closed(
        self,
        trade: OpenTrade,
        exit_price: float,
        reason: str,
        pnl: float,
        **extra: Any,
    ) -> dict[str, Any]:
        r_realized = 0.0
        if trade.risk > 0:
            move = (
                exit_price - trade.entry_price
                if trade.side.value == "LONG"
                else trade.entry_price - exit_price
            )
            r_realized = move / trade.risk
        return self.write(
            "TRADE_CLOSED",
            strategy=trade.strategy,
            side=trade.side.value,
            client_order_id=trade.client_order_id,
            entry_time=trade.entry_time.isoformat(),
            entry_price=trade.entry_price,
            theoretical_entry_price=trade.theoretical_entry_price,
            slippage=trade.slippage,
            exit_price=exit_price,
            exit_reason=reason,
            quantity=trade.quantity,
            risk=trade.risk,
            pnl=pnl,
            r_realized=r_realized,
            **extra,
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and type(value).__mro__[1] is str:
        return value.value
    return value
