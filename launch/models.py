from __future__ import annotations

from dataclasses import dataclass, field

from engine.pair_engine import PairEngineResult
from execution.hedge import HedgeExecutionResult
from risk.models import AccountRiskMetrics, PortfolioSnapshot, RiskGateResult


@dataclass(frozen=True)
class ActionPlan:
    pair_label: str
    index: int
    selected: bool
    signal: str
    zscore: float | None
    gate_allowed: bool | None
    gate_reason: str
    has_open_hedge: bool
    action: str  # HOLD | OPEN | CLOSE | SKIP


@dataclass
class CycleResult:
    refresh_data: bool
    live_risk: bool
    live_execute: bool
    scan_pairs_ok: int
    pairs_analyzed: int
    selected_count: int
    open_hedged_count: int
    risk_warnings: list[str] = field(default_factory=list)
    plans: list[ActionPlan] = field(default_factory=list)
    engine_results: list[PairEngineResult] = field(default_factory=list)
    executions: list[HedgeExecutionResult] = field(default_factory=list)
    closes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    portfolio: PortfolioSnapshot | None = None
    account_metrics: list[AccountRiskMetrics] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
