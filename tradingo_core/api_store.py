"""JSON-backed storage and models for the TradinGo signal API."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4


Direction = Literal["BUY", "SELL"]
EntryType = Literal["LIMIT", "MARKET"]
SignalStatus = Literal["ACTIVE", "CANCELLED", "EXPIRED"]


def parse_key_set(value: str) -> frozenset[str]:
    return frozenset(k.strip() for k in value.split(",") if k.strip())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc_iso(value: str) -> str:
    return parse_iso(value).isoformat()


@dataclass(frozen=True)
class ApiSettings:
    """Runtime settings read from environment on the VPS."""

    data_dir: Path
    api_keys: frozenset[str]
    admin_api_keys: frozenset[str]

    @classmethod
    def from_env(cls) -> "ApiSettings":
        data_dir = Path(os.getenv("TRADINGO_API_DATA_DIR", "runtime/api_state"))
        api_keys = parse_key_set(os.getenv("TRADINGO_API_KEYS", ""))
        admin_keys = parse_key_set(os.getenv("TRADINGO_ADMIN_API_KEYS", ""))
        if os.getenv("TRADINGO_API_ALLOW_DEV_KEY") == "1":
            api_keys = frozenset(set(api_keys) | {"dev-local-key"})
            admin_keys = frozenset(set(admin_keys) | {"dev-local-admin-key"})
        return cls(data_dir=data_dir, api_keys=api_keys, admin_api_keys=admin_keys)


@dataclass
class SignalRecord:
    symbol: str
    direction: Direction
    entry_type: EntryType
    entry: float
    sl: float
    tp1: float
    tp2: float
    risk_pct: float
    score: float
    strategy: str = "ICT_SNIPER"
    signal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: Optional[str] = None
    status: SignalStatus = "ACTIVE"
    min_rr: float = 2.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SignalRecord":
        symbol = self.symbol.strip().upper().replace("/", "")
        direction = self.direction.upper()
        entry_type = self.entry_type.upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")
        if entry_type not in ("LIMIT", "MARKET"):
            raise ValueError("entry_type must be LIMIT or MARKET")
        risk = abs(float(self.entry) - float(self.sl))
        reward = abs(float(self.tp2) - float(self.entry))
        rr = reward / risk if risk > 0 else 0.0
        if risk <= 0:
            raise ValueError("entry and sl must define positive risk")
        if rr < self.min_rr:
            raise ValueError(f"tp2 must be at least {self.min_rr:.2f}R")
        if self.risk_pct <= 0:
            raise ValueError("risk_pct must be positive")
        return SignalRecord(
            symbol=symbol,
            direction=direction,  # type: ignore[arg-type]
            entry_type=entry_type,  # type: ignore[arg-type]
            entry=float(self.entry),
            sl=float(self.sl),
            tp1=float(self.tp1),
            tp2=float(self.tp2),
            risk_pct=float(self.risk_pct),
            score=float(self.score),
            strategy=self.strategy,
            signal_id=self.signal_id,
            created_at=to_utc_iso(self.created_at),
            expires_at=to_utc_iso(self.expires_at) if self.expires_at else None,
            status=self.status,
            min_rr=float(self.min_rr),
            metadata=dict(self.metadata or {}),
        )

    def is_active(self, now: Optional[datetime] = None) -> bool:
        if self.status != "ACTIVE":
            return False
        if self.expires_at:
            now = now or datetime.now(timezone.utc)
            return parse_iso(self.expires_at) >= now
        return True


@dataclass
class AckRecord:
    signal_id: str
    client_id: str
    status: str
    broker: str = ""
    account_login: str = ""
    order_ticket: str = ""
    message: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class HeartbeatRecord:
    client_id: str
    broker: str
    account_login: str
    balance: float
    equity: float
    symbol: str = ""
    open_positions: int = 0
    daily_pnl: float = 0.0
    last_error: str = ""
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class RiskConfigRecord:
    allow_live_trading: bool = False
    max_daily_dd_pct: float = 0.02
    max_daily_trades: int = 3
    risk_per_trade_pct: float = 0.005
    max_spread_points: int = 80
    min_signal_score: float = 65.0


class JsonSignalStore:
    """Small JSON store for signals and EA telemetry."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def publish_signal(self, signal: SignalRecord) -> SignalRecord:
        record = signal.normalized()
        signals = self.list_signals(include_inactive=True)
        signals = [s for s in signals if s.signal_id != record.signal_id]
        signals.append(record)
        self._write_json("signals.json", [asdict(s) for s in signals])
        return record

    def latest_signal(self, symbol: Optional[str] = None, now: Optional[datetime] = None) -> Optional[SignalRecord]:
        signals = self.list_signals(include_inactive=False, now=now)
        if symbol:
            normalized = symbol.strip().upper().replace("/", "")
            signals = [s for s in signals if s.symbol == normalized]
        if not signals:
            return None
        return sorted(signals, key=lambda s: s.created_at)[-1]

    def list_signals(
        self,
        include_inactive: bool = False,
        now: Optional[datetime] = None,
    ) -> list[SignalRecord]:
        raw = self._read_json("signals.json", [])
        out = [SignalRecord(**item).normalized() for item in raw]
        if include_inactive:
            return out
        return [s for s in out if s.is_active(now)]

    def add_ack(self, ack: AckRecord) -> AckRecord:
        acks = self._read_json("acks.json", [])
        acks.append(asdict(ack))
        self._write_json("acks.json", acks[-1000:])
        return ack

    def upsert_heartbeat(self, heartbeat: HeartbeatRecord) -> HeartbeatRecord:
        heartbeats = self._read_json("heartbeats.json", {})
        heartbeats[heartbeat.client_id] = asdict(heartbeat)
        self._write_json("heartbeats.json", heartbeats)
        return heartbeat

    def list_heartbeats(self) -> list[HeartbeatRecord]:
        raw = self._read_json("heartbeats.json", {})
        return [HeartbeatRecord(**item) for item in raw.values()]

    def get_risk_config(self) -> RiskConfigRecord:
        return RiskConfigRecord(**self._read_json("risk_config.json", asdict(RiskConfigRecord())))

    def set_risk_config(self, config: RiskConfigRecord) -> RiskConfigRecord:
        self._write_json("risk_config.json", asdict(config))
        return config

    def _read_json(self, filename: str, default):
        path = self.data_dir / filename
        with self._lock:
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, filename: str, data) -> None:
        path = self.data_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                delete=False,
                suffix=".tmp",
            ) as tmp:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp_path = Path(tmp.name)
            tmp_path.replace(path)


