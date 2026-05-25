from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


Direction = Literal["BUY", "SELL"]


@dataclass
class ManualTradeInput:
    tenant_id: str
    symbol: str
    hedge_direction: Direction
    entry_price: float
    sl_distance: float
    tp_distance: float
    prop_balance: float
    hedge_balance: float
    prop_daily_dd_max_pct: float
    prop_total_dd_max_pct: float
    prop_daily_dd_used_pct: float = 0.0
    prop_total_dd_used_pct: float = 0.0
    prop_risk_pct: float = 0.5
    prop_contract_size: float = 100.0
    hedge_contract_size: float = 100.0
    hedge_lot_multiplier: float = 1.4
    max_prop_lot: float = 10.0
    max_hedge_lot: float = 10.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    notes: str = ""


@dataclass
class ManualTradePlan:
    plan_id: str
    created_at: str
    tenant_id: str
    symbol: str
    hedge_direction: Direction
    prop_direction: Direction
    entry_price: float
    prop_lot: float
    hedge_lot: float
    prop_sl: float
    prop_tp: float
    hedge_sl: float
    hedge_tp: float
    estimated_prop_loss: float
    estimated_hedge_loss: float
    estimated_prop_profit: float
    estimated_hedge_profit: float
    remaining_daily_dd_pct: float
    remaining_total_dd_pct: float
    risk_budget: float
    raw_prop_lot: float
    raw_hedge_lot: float
    prop_lot_capped: bool
    hedge_lot_capped: bool
    prop_contract_size: float
    hedge_contract_size: float
    status: str = "PLANNED"
    notes: str = ""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def opposite(direction: Direction) -> Direction:
    return "SELL" if direction == "BUY" else "BUY"


def round_lot(value: float, step: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return 0.0
    rounded = round(round(value / step) * step, 2)
    return min(maximum, rounded)


def build_manual_trade_plan(inp: ManualTradeInput) -> ManualTradePlan:
    if inp.entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if inp.sl_distance <= 0:
        raise ValueError("sl_distance must be positive")
    if inp.tp_distance <= 0:
        raise ValueError("tp_distance must be positive")
    if inp.hedge_direction not in ("BUY", "SELL"):
        raise ValueError("hedge_direction must be BUY or SELL")

    remaining_daily = max(0.0, inp.prop_daily_dd_max_pct - inp.prop_daily_dd_used_pct)
    remaining_total = max(0.0, inp.prop_total_dd_max_pct - inp.prop_total_dd_used_pct)
    allowed_prop_risk_pct = min(inp.prop_risk_pct, remaining_daily, remaining_total)
    risk_budget = inp.prop_balance * (allowed_prop_risk_pct / 100.0)

    raw_prop_lot = risk_budget / (inp.sl_distance * inp.prop_contract_size)
    prop_lot = round_lot(raw_prop_lot, inp.lot_step, inp.min_lot, inp.max_prop_lot)
    raw_hedge_lot = prop_lot * inp.hedge_lot_multiplier
    hedge_lot = round_lot(raw_hedge_lot, inp.lot_step, inp.min_lot, inp.max_hedge_lot)
    prop_lot_capped = raw_prop_lot > inp.max_prop_lot
    hedge_lot_capped = raw_hedge_lot > inp.max_hedge_lot

    hedge_direction = inp.hedge_direction
    prop_direction = opposite(hedge_direction)

    if hedge_direction == "BUY":
        hedge_sl = inp.entry_price - inp.sl_distance
        hedge_tp = inp.entry_price + inp.tp_distance
        prop_sl = inp.entry_price + inp.sl_distance
        prop_tp = inp.entry_price - inp.tp_distance
    else:
        hedge_sl = inp.entry_price + inp.sl_distance
        hedge_tp = inp.entry_price - inp.tp_distance
        prop_sl = inp.entry_price - inp.sl_distance
        prop_tp = inp.entry_price + inp.tp_distance

    estimated_prop_loss = prop_lot * inp.sl_distance * inp.prop_contract_size
    estimated_hedge_loss = hedge_lot * inp.sl_distance * inp.hedge_contract_size
    estimated_prop_profit = prop_lot * inp.tp_distance * inp.prop_contract_size
    estimated_hedge_profit = hedge_lot * inp.tp_distance * inp.hedge_contract_size

    return ManualTradePlan(
        plan_id=str(uuid.uuid4()),
        created_at=now_utc(),
        tenant_id=inp.tenant_id,
        symbol=inp.symbol.upper(),
        hedge_direction=hedge_direction,
        prop_direction=prop_direction,
        entry_price=round(inp.entry_price, 5),
        prop_lot=prop_lot,
        hedge_lot=hedge_lot,
        prop_sl=round(prop_sl, 5),
        prop_tp=round(prop_tp, 5),
        hedge_sl=round(hedge_sl, 5),
        hedge_tp=round(hedge_tp, 5),
        estimated_prop_loss=round(estimated_prop_loss, 2),
        estimated_hedge_loss=round(estimated_hedge_loss, 2),
        estimated_prop_profit=round(estimated_prop_profit, 2),
        estimated_hedge_profit=round(estimated_hedge_profit, 2),
        remaining_daily_dd_pct=round(remaining_daily, 4),
        remaining_total_dd_pct=round(remaining_total, 4),
        risk_budget=round(risk_budget, 2),
        raw_prop_lot=round(raw_prop_lot, 4),
        raw_hedge_lot=round(raw_hedge_lot, 4),
        prop_lot_capped=prop_lot_capped,
        hedge_lot_capped=hedge_lot_capped,
        prop_contract_size=inp.prop_contract_size,
        hedge_contract_size=inp.hedge_contract_size,
        notes=inp.notes,
    )


class OrderManager:
    EXECUTION_COLUMNS: dict[str, str] = {
        "prop_ticket": "TEXT",
        "hedge_ticket": "TEXT",
        "prop_entry_price": "REAL",
        "hedge_entry_price": "REAL",
        "phase2_active": "INTEGER NOT NULL DEFAULT 0",
        "phase2_activated_at": "TEXT",
        "prop_sl_set": "INTEGER NOT NULL DEFAULT 0",
        "hedge_sl_set": "INTEGER NOT NULL DEFAULT 0",
        "execution_error": "TEXT",
        "executed_at": "TEXT",
    }

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_trade_orders (
                    plan_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    hedge_direction TEXT NOT NULL,
                    prop_direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    prop_lot REAL NOT NULL,
                    hedge_lot REAL NOT NULL,
                    prop_sl REAL NOT NULL,
                    prop_tp REAL NOT NULL,
                    hedge_sl REAL NOT NULL,
                    hedge_tp REAL NOT NULL,
                    estimated_prop_loss REAL NOT NULL,
                    estimated_hedge_loss REAL NOT NULL,
                    estimated_prop_profit REAL NOT NULL,
                    estimated_hedge_profit REAL NOT NULL,
                    remaining_daily_dd_pct REAL NOT NULL,
                    remaining_total_dd_pct REAL NOT NULL,
                    risk_budget REAL NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            existing = {row[1] for row in conn.execute("PRAGMA table_info(manual_trade_orders)").fetchall()}
            for name, sql_type in self.EXECUTION_COLUMNS.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE manual_trade_orders ADD COLUMN {name} {sql_type}")
            conn.commit()

    def queue_plan(self, plan: ManualTradePlan) -> None:
        payload = asdict(plan)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_trade_orders (
                    plan_id, created_at, updated_at, tenant_id, symbol,
                    hedge_direction, prop_direction, entry_price,
                    prop_lot, hedge_lot, prop_sl, prop_tp, hedge_sl, hedge_tp,
                    estimated_prop_loss, estimated_hedge_loss,
                    estimated_prop_profit, estimated_hedge_profit,
                    remaining_daily_dd_pct, remaining_total_dd_pct, risk_budget,
                    status, notes, payload_json
                ) VALUES (
                    :plan_id, :created_at, :updated_at, :tenant_id, :symbol,
                    :hedge_direction, :prop_direction, :entry_price,
                    :prop_lot, :hedge_lot, :prop_sl, :prop_tp, :hedge_sl, :hedge_tp,
                    :estimated_prop_loss, :estimated_hedge_loss,
                    :estimated_prop_profit, :estimated_hedge_profit,
                    :remaining_daily_dd_pct, :remaining_total_dd_pct, :risk_budget,
                    :status, :notes, :payload_json
                )
                """,
                {
                    **payload,
                    "updated_at": now_utc(),
                    "status": "QUEUED",
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                },
            )
            conn.commit()

    def get_order(self, plan_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM manual_trade_orders WHERE plan_id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def list_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM manual_trade_orders
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_executable_orders(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM manual_trade_orders
                WHERE status IN ('QUEUED', 'ARMED')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_orders(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM manual_trade_orders
                WHERE status IN ('HEDGE_OPENED', 'PROP_OPENED', 'ACTIVE', 'PHASE2')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_status(self, plan_id: str, status: str, error: str | None = None) -> None:
        updates = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, now_utc()]
        if error is not None:
            updates.append("execution_error = ?")
            values.append(error)
        values.append(plan_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE manual_trade_orders SET {', '.join(updates)} WHERE plan_id = ?",
                values,
            )
            conn.commit()

    def update_execution(self, plan_id: str, **fields: Any) -> None:
        allowed = set(self.EXECUTION_COLUMNS) | {"status"}
        payload = {k: v for k, v in fields.items() if k in allowed}
        if not payload:
            return
        payload["updated_at"] = now_utc()
        updates = [f"{key} = ?" for key in payload]
        values = list(payload.values()) + [plan_id]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE manual_trade_orders SET {', '.join(updates)} WHERE plan_id = ?",
                values,
            )
            conn.commit()
