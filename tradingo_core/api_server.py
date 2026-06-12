"""FastAPI server for central TradinGo signal distribution.

Run on the VPS after setting API keys, for example:

    set TRADINGO_API_KEYS=client-key-1,client-key-2
    set TRADINGO_ADMIN_API_KEYS=admin-key-1
    python -m uvicorn tradingo_core.api_server:create_app --factory --host 0.0.0.0 --port 8080

The service only distributes signals and receives telemetry. Trade execution
must remain inside the client EA with local spread/risk/fail-safe checks.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from .api_store import (
    AckRecord,
    ApiSettings,
    HeartbeatRecord,
    JsonSignalStore,
    RiskConfigRecord,
    SignalRecord,
)


class SignalPayload(BaseModel):
    symbol: str
    direction: str
    entry_type: str = "LIMIT"
    entry: float
    sl: float
    tp1: float
    tp2: float
    risk_pct: float = Field(gt=0)
    score: float
    strategy: str = "ICT_SNIPER"
    signal_id: Optional[str] = None
    expires_at: Optional[str] = None
    min_rr: float = 2.0
    metadata: dict = Field(default_factory=dict)


class AckPayload(BaseModel):
    signal_id: str
    client_id: str
    status: str
    broker: str = ""
    account_login: str = ""
    order_ticket: str = ""
    message: str = ""


class HeartbeatPayload(BaseModel):
    client_id: str
    broker: str
    account_login: str
    balance: float
    equity: float
    symbol: str = ""
    open_positions: int = 0
    daily_pnl: float = 0.0
    last_error: str = ""


class RiskConfigPayload(BaseModel):
    allow_live_trading: bool = False
    max_daily_dd_pct: float = Field(default=0.02, ge=0, le=0.2)
    max_daily_trades: int = Field(default=3, ge=0, le=50)
    risk_per_trade_pct: float = Field(default=0.005, ge=0, le=0.05)
    max_spread_points: int = Field(default=80, ge=0)
    min_signal_score: float = Field(default=65.0, ge=0, le=100)


def create_app(settings: Optional[ApiSettings] = None, store: Optional[JsonSignalStore] = None) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    store = store or JsonSignalStore(settings.data_dir)
    app = FastAPI(title="TradinGo Signal API", version="0.1.0")

    def require_client_key(x_api_key: str = Header(default="")) -> str:
        if not settings.api_keys:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TRADINGO_API_KEYS is not configured",
            )
        if x_api_key not in settings.api_keys and x_api_key not in settings.admin_api_keys:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
        return x_api_key

    def require_admin_key(x_api_key: str = Header(default="")) -> str:
        if not settings.admin_api_keys:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TRADINGO_ADMIN_API_KEYS is not configured",
            )
        if x_api_key not in settings.admin_api_keys:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin api key")
        return x_api_key

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/symbols")
    def symbols(_: str = Depends(require_client_key)):
        active = store.list_signals(include_inactive=False)
        return {"symbols": sorted({s.symbol for s in active})}

    @app.post("/signals/publish")
    def publish_signal(payload: SignalPayload, _: str = Depends(require_admin_key)):
        signal = SignalRecord(
            symbol=payload.symbol,
            direction=payload.direction.upper(),  # type: ignore[arg-type]
            entry_type=payload.entry_type.upper(),  # type: ignore[arg-type]
            entry=payload.entry,
            sl=payload.sl,
            tp1=payload.tp1,
            tp2=payload.tp2,
            risk_pct=payload.risk_pct,
            score=payload.score,
            strategy=payload.strategy,
            signal_id=payload.signal_id or SignalRecord(
                symbol=payload.symbol,
                direction=payload.direction.upper(),  # type: ignore[arg-type]
                entry_type=payload.entry_type.upper(),  # type: ignore[arg-type]
                entry=payload.entry,
                sl=payload.sl,
                tp1=payload.tp1,
                tp2=payload.tp2,
                risk_pct=payload.risk_pct,
                score=payload.score,
            ).signal_id,
            expires_at=payload.expires_at,
            min_rr=payload.min_rr,
            metadata=payload.metadata,
        )
        try:
            saved = store.publish_signal(signal)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return {"ok": True, "signal": asdict(saved)}

    @app.get("/signals/latest")
    def latest_signal(
        symbol: Optional[str] = Query(default=None),
        _: str = Depends(require_client_key),
    ):
        signal = store.latest_signal(symbol=symbol)
        if signal is None:
            return {"ok": True, "signal": None}
        return {"ok": True, "signal": asdict(signal)}

    @app.post("/signals/ack")
    def ack_signal(payload: AckPayload, _: str = Depends(require_client_key)):
        ack = store.add_ack(AckRecord(**payload.model_dump()))
        return {"ok": True, "ack": asdict(ack)}

    @app.get("/risk/config")
    def get_risk_config(_: str = Depends(require_client_key)):
        return {"ok": True, "risk": asdict(store.get_risk_config())}

    @app.post("/risk/config")
    def set_risk_config(payload: RiskConfigPayload, _: str = Depends(require_admin_key)):
        config = store.set_risk_config(RiskConfigRecord(**payload.model_dump()))
        return {"ok": True, "risk": asdict(config)}

    @app.post("/accounts/heartbeat")
    def heartbeat(payload: HeartbeatPayload, _: str = Depends(require_client_key)):
        hb = store.upsert_heartbeat(HeartbeatRecord(**payload.model_dump()))
        return {"ok": True, "heartbeat": asdict(hb)}

    @app.get("/accounts/heartbeats")
    def heartbeats(_: str = Depends(require_admin_key)):
        return {"ok": True, "heartbeats": [asdict(h) for h in store.list_heartbeats()]}

    return app


app = create_app()
