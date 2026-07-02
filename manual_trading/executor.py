from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manual_trading.order_manager import OrderManager, now_utc

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - MT5 is only available on Windows VPS
    mt5 = None


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "systems_config.json"


@dataclass
class ExecutorConfig:
    execution_enabled: bool
    orders_db: Path
    prop_terminal: str
    hedge_terminal: str
    prop_magic: int
    hedge_magic: int
    prop_deviation: int
    hedge_deviation: int
    hedge_equity_floor: float
    hedge_close_scope: str
    phase2_enabled: bool
    phase2_trigger_sl_fraction: float
    loop_interval_sec: float


def load_config() -> ExecutorConfig:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    cfg = data.get("manual_trading", {})
    return ExecutorConfig(
        execution_enabled=bool(cfg.get("execution_enabled", False)),
        orders_db=ROOT / cfg.get("orders_db", "data/manual_orders.sqlite"),
        prop_terminal=str(cfg.get("prop_terminal", r"C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe")),
        hedge_terminal=str(cfg.get("hedge_terminal", r"C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe")),
        prop_magic=int(cfg.get("prop_magic", 20260001)),
        hedge_magic=int(cfg.get("hedge_magic", 20260002)),
        prop_deviation=int(cfg.get("prop_deviation", 30)),
        hedge_deviation=int(cfg.get("hedge_deviation", 30)),
        hedge_equity_floor=float(cfg.get("hedge_equity_floor", 0.0)),
        hedge_close_scope=str(cfg.get("hedge_close_scope", "all")),
        phase2_enabled=bool(cfg.get("phase2_enabled", True)),
        phase2_trigger_sl_fraction=float(cfg.get("phase2_trigger_sl_fraction", 0.5)),
        loop_interval_sec=float(cfg.get("executor_loop_interval_sec", 2.0)),
    )


def require_mt5() -> None:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 Python package is not available in this environment")


def initialize_terminal(path: str) -> None:
    require_mt5()
    mt5.shutdown()
    if not mt5.initialize(path=path):
        raise RuntimeError(f"MT5 initialize failed for {path}: {mt5.last_error()}")


def shutdown_terminal() -> None:
    if mt5 is not None:
        mt5.shutdown()


def order_type(direction: str) -> int:
    return mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL


def close_order_type(position_type: int) -> int:
    return mt5.ORDER_TYPE_SELL if position_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY


def current_price(symbol: str, direction: str) -> float:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick for {symbol}")
    return float(tick.ask if direction == "BUY" else tick.bid)


def send_market_order(row: dict[str, Any], side: str, cfg: ExecutorConfig) -> tuple[int, float]:
    symbol = row["symbol"]
    direction = row[f"{side}_direction"]
    lot = float(row[f"{side}_lot"])
    sl = float(row[f"{side}_sl"])
    tp = float(row[f"{side}_tp"])
    magic = cfg.hedge_magic if side == "hedge" else cfg.prop_magic
    deviation = cfg.hedge_deviation if side == "hedge" else cfg.prop_deviation
    price = current_price(symbol, direction)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type(direction),
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": f"TG_MANUAL_{row['plan_id'][:8]}_{side.upper()}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        comment = getattr(result, "comment", mt5.last_error())
        retcode = getattr(result, "retcode", "None")
        raise RuntimeError(f"{side} order failed retcode={retcode} comment={comment}")
    time.sleep(0.5)
    positions = mt5.positions_get(symbol=symbol, magic=magic)
    entry = float(result.price)
    ticket = int(result.order)
    if positions:
        latest = sorted(positions, key=lambda p: p.time, reverse=True)[0]
        entry = float(latest.price_open)
        ticket = int(latest.ticket)
    return ticket, entry


def execute_order(row: dict[str, Any], manager: OrderManager, cfg: ExecutorConfig) -> None:
    plan_id = row["plan_id"]
    if not cfg.execution_enabled:
        manager.update_status(plan_id, "BLOCKED", "execution_enabled is false")
        return
    if float(row["prop_lot"]) <= 0 or float(row["hedge_lot"]) <= 0:
        manager.update_status(plan_id, "REJECTED", "Calculated lot is zero")
        return

    try:
        initialize_terminal(cfg.hedge_terminal)
        hedge_ticket, hedge_entry = send_market_order(row, "hedge", cfg)
        manager.update_execution(
            plan_id,
            status="HEDGE_OPENED",
            hedge_ticket=str(hedge_ticket),
            hedge_entry_price=hedge_entry,
            executed_at=now_utc(),
            execution_error=None,
        )
    except Exception as exc:
        manager.update_status(plan_id, "ERROR", f"hedge open failed: {exc}")
        return
    finally:
        shutdown_terminal()

    try:
        initialize_terminal(cfg.prop_terminal)
        prop_ticket, prop_entry = send_market_order(row, "prop", cfg)
        manager.update_execution(
            plan_id,
            status="ACTIVE",
            prop_ticket=str(prop_ticket),
            prop_entry_price=prop_entry,
            execution_error=None,
        )
    except Exception as exc:
        manager.update_status(plan_id, "ERROR", f"prop open failed after hedge opened: {exc}")
    finally:
        shutdown_terminal()


def safe_sl_at_entry(symbol: str, entry: float, position_type: int) -> float:
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return entry
    min_dist = (getattr(info, "stops_level", 0) + 20) * info.point
    if position_type == mt5.ORDER_TYPE_BUY:
        return min(entry, tick.bid - min_dist)
    return max(entry, tick.ask + min_dist)


def update_position_sltp(position, sl: float, tp: float = 0.0) -> None:
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": position.ticket,
        "sl": float(sl),
        "tp": float(tp),
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        comment = getattr(result, "comment", mt5.last_error())
        raise RuntimeError(f"SLTP update failed for {position.ticket}: {comment}")


def close_position(position, magic: int) -> None:
    tick = mt5.symbol_info_tick(position.symbol)
    if tick is None:
        raise RuntimeError(f"No tick to close {position.symbol}")
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_order_type(position.type),
        "position": position.ticket,
        "price": tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask,
        "magic": magic,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "comment": "TG_HEDGE_EQUITY_FLOOR",
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        comment = getattr(result, "comment", mt5.last_error())
        raise RuntimeError(f"Close failed for {position.ticket}: {comment}")


def enforce_hedge_equity_floor(cfg: ExecutorConfig) -> None:
    if cfg.hedge_equity_floor <= 0:
        return
    initialize_terminal(cfg.hedge_terminal)
    try:
        account = mt5.account_info()
        if account is None or float(account.equity) > cfg.hedge_equity_floor:
            return
        if cfg.hedge_close_scope == "all":
            positions = mt5.positions_get() or []
        else:
            positions = mt5.positions_get(magic=cfg.hedge_magic) or []
        for position in positions:
            close_position(position, cfg.hedge_magic)
    finally:
        shutdown_terminal()


def manage_phase2_for_order(row: dict[str, Any], manager: OrderManager, cfg: ExecutorConfig) -> None:
    if not cfg.phase2_enabled or int(row.get("phase2_active") or 0):
        return
    if not row.get("prop_ticket") or not row.get("hedge_ticket"):
        return

    symbol = row["symbol"]
    trigger_distance = abs(float(row["prop_sl"]) - float(row["entry_price"])) * cfg.phase2_trigger_sl_fraction
    prop_entry = float(row.get("prop_entry_price") or row["entry_price"])

    initialize_terminal(cfg.prop_terminal)
    try:
        prop_positions = mt5.positions_get(ticket=int(row["prop_ticket"])) or []
        if not prop_positions:
            manager.update_status(row["plan_id"], "PROP_CLOSED", "prop position not found")
            return
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return
        current = tick.bid if prop_positions[0].type == mt5.ORDER_TYPE_BUY else tick.ask
        if abs(float(current) - prop_entry) < trigger_distance:
            return
        update_position_sltp(prop_positions[0], prop_entry, 0.0)
    finally:
        shutdown_terminal()

    initialize_terminal(cfg.hedge_terminal)
    try:
        hedge_positions = mt5.positions_get(ticket=int(row["hedge_ticket"])) or []
        if hedge_positions:
            hedge_entry = float(row.get("hedge_entry_price") or row["entry_price"])
            hedge_sl = safe_sl_at_entry(symbol, hedge_entry, hedge_positions[0].type)
            update_position_sltp(hedge_positions[0], hedge_sl, 0.0)
    finally:
        shutdown_terminal()

    manager.update_execution(
        row["plan_id"],
        status="PHASE2",
        phase2_active=1,
        phase2_activated_at=now_utc(),
        prop_sl_set=1,
        hedge_sl_set=1,
    )


def run_once(manager: OrderManager, cfg: ExecutorConfig) -> None:
    enforce_hedge_equity_floor(cfg)
    for row in manager.list_executable_orders():
        execute_order(row, manager, cfg)
    for row in manager.list_active_orders():
        try:
            manage_phase2_for_order(row, manager, cfg)
        except Exception as exc:
            manager.update_status(row["plan_id"], row.get("status") or "ACTIVE", f"phase2 failed: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    manager = OrderManager(cfg.orders_db)

    if args.daemon:
        while True:
            run_once(manager, cfg)
            time.sleep(cfg.loop_interval_sec)
    else:
        run_once(manager, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
