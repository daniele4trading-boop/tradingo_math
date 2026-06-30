from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.config import CANDIDATE_PAIRS, get_profile, load_accounts, load_params
from backtest.models import BacktestResult
from backtest.runner import run_all_pair_backtests
from engine.pair_engine import analyze_cached_pair
from risk.guards import evaluate_entry_gate
from risk.manager import RiskManager
from risk.models import AccountRiskMetrics, PortfolioSnapshot, RiskGateResult


@dataclass(frozen=True)
class PairRow:
    index: int
    pair_label: str
    category: str
    selected: bool
    correlation: float | None
    adf_p: float | None
    halflife_h: float | None
    zscore: float | None
    signal: str
    trigger_tf: str
    gate_allowed: bool | None
    gate_reason: str
    error: str | None


@dataclass(frozen=True)
class BacktestPortfolioSummary:
    lookback_days: int
    initial_equity: float
    total_trades: int
    pairs_analyzed: int
    pairs_selected: int
    pairs_profitable: int
    gross_pnl: float
    costs: float
    net_pnl: float
    total_return_pct: float


@dataclass(frozen=True)
class DashboardSnapshot:
    pair_rows: list[PairRow]
    portfolio: PortfolioSnapshot | None
    account_metrics: list[AccountRiskMetrics]
    risk_warnings: list[str]
    data_source: str
    leg_a_profile: str
    leg_b_profile: str
    dry_run: bool
    load_errors: list[str]


def _fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None or value != value:
        return "n/d"
    if abs(value) >= 1e6:
        return f"{value:.0f}"
    return f"{value:.{digits}f}"


def analyze_pairs_offline() -> tuple[list[Any], str]:
    accounts = load_accounts()
    params = load_params()
    profile = get_profile("data_source", accounts)
    results = []
    for candidate in CANDIDATE_PAIRS:
        results.append(
            analyze_cached_pair(
                profile,
                accounts,
                params,
                candidate.index,
                candidate.leg_a,
                candidate.leg_b,
                candidate.category,
            )
        )
    return results, profile.name


def build_pair_rows(
    engine_results: list[Any],
    gates: dict[int, RiskGateResult] | None = None,
) -> list[PairRow]:
    rows: list[PairRow] = []
    for result in engine_results:
        sel = result.selection
        sig = result.signal
        gate = gates.get(result.index) if gates else None
        rows.append(
            PairRow(
                index=result.index,
                pair_label=result.pair_label,
                category=result.category,
                selected=sel.selected,
                correlation=sel.correlation if sel.correlation == sel.correlation else None,
                adf_p=sel.adf_pvalue_full if sel.adf_pvalue_full == sel.adf_pvalue_full else None,
                halflife_h=sel.halflife_h if sel.halflife_h == sel.halflife_h else None,
                zscore=sig.zscore if sig else None,
                signal=sig.state.value if sig else "ERROR",
                trigger_tf=sig.recommended_trigger_tf if sig else result.trigger_tf,
                gate_allowed=gate.allowed if gate else None,
                gate_reason=gate.summary if gate and gate.reasons else "",
                error=result.error,
            )
        )
    return rows


def pair_rows_dataframe(rows: list[PairRow]) -> pd.DataFrame:
    data = []
    for row in rows:
        data.append(
            {
                "Coppia": row.pair_label,
                "Cat": row.category,
                "Sel": "sì" if row.selected else "no",
                "Corr": _fmt_float(row.correlation),
                "ADF": _fmt_float(row.adf_p, 4),
                "HL (h)": _fmt_float(row.halflife_h, 1),
                "Z": _fmt_float(row.zscore),
                "Segnale": row.signal,
                "TF": row.trigger_tf,
                "Risk OK": "sì" if row.gate_allowed else ("no" if row.gate_allowed is False else "—"),
                "Note": row.gate_reason or row.error or "",
            }
        )
    return pd.DataFrame(data)


def run_backtests_offline() -> tuple[list[BacktestResult], BacktestPortfolioSummary]:
    accounts = load_accounts()
    params = load_params()
    profile = get_profile("data_source", accounts)
    lookback_days = int(params["backtest"].get("lookback_days", 0) or 0)
    initial_equity = float(params["backtest"]["initial_equity"])

    results = run_all_pair_backtests(profile, accounts, params)
    total_trades = 0
    gross_pnl = 0.0
    costs = 0.0
    net_pnl = 0.0
    pairs_profitable = 0

    for result in results:
        m = result.metrics
        if m.error:
            continue
        total_trades += m.trades
        gross_pnl += m.gross_pnl
        costs += m.costs
        net_pnl += m.net_pnl
        if m.net_pnl > 0:
            pairs_profitable += 1

    summary = BacktestPortfolioSummary(
        lookback_days=lookback_days,
        initial_equity=initial_equity,
        total_trades=total_trades,
        pairs_analyzed=len(results),
        pairs_selected=sum(1 for r in results if r.selected),
        pairs_profitable=pairs_profitable,
        gross_pnl=gross_pnl,
        costs=costs,
        net_pnl=net_pnl,
        total_return_pct=(net_pnl / initial_equity * 100.0) if initial_equity > 0 else 0.0,
    )
    return results, summary


def backtest_results_dataframe(results: list[BacktestResult]) -> pd.DataFrame:
    data = []
    for result in results:
        m = result.metrics
        data.append(
            {
                "Coppia": result.pair_label,
                "Cat": result.category,
                "Sel": "sì" if result.selected else "no",
                "TF": result.trigger_tf,
                "Trade": m.trades if m.error is None else "—",
                "Win%": _fmt_float(m.win_rate, 1) if m.error is None else "—",
                "Ret%": _fmt_float(m.total_return_pct, 2) if m.error is None else "—",
                "MaxDD%": _fmt_float(m.max_drawdown_pct, 2) if m.error is None else "—",
                "Sharpe": _fmt_float(m.sharpe, 2) if m.error is None else "—",
                "Net": f"{m.net_pnl:.1f}" if m.error is None else "ERR",
                "Note": m.error or "",
            }
        )
    return pd.DataFrame(data)


def evaluate_gates(
    manager: RiskManager,
    portfolio: PortfolioSnapshot,
    metrics: list[AccountRiskMetrics],
    params: dict[str, Any],
) -> dict[int, RiskGateResult]:
    gates: dict[int, RiskGateResult] = {}
    for candidate in CANDIDATE_PAIRS:
        gates[candidate.index] = evaluate_entry_gate(candidate, portfolio, metrics, params)
    return gates


def load_dashboard_snapshot(include_live: bool = True) -> DashboardSnapshot:
    accounts = load_accounts()
    params = load_params()
    leg_a = get_profile("leg_A", accounts)
    leg_b = get_profile("leg_B", accounts)
    errors: list[str] = []

    engine_results, data_source = analyze_pairs_offline()
    portfolio: PortfolioSnapshot | None = None
    metrics: list[AccountRiskMetrics] = []
    warnings: list[str] = []
    gates: dict[int, RiskGateResult] | None = None

    if include_live:
        try:
            manager = RiskManager(leg_a, leg_b, params)
            portfolio = manager.load_portfolio()
            metrics = manager.load_account_metrics()
            warnings = []
            if portfolio.unhedged_pairs:
                warnings.append(
                    "unhedged: " + ", ".join(p.pair_label for p in portfolio.unhedged_pairs)
                )
            from risk.guards import account_limit_violations

            warnings.extend(account_limit_violations(metrics, params))
            gates = evaluate_gates(manager, portfolio, metrics, params)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"live MT5/risk: {exc}")

    pair_rows = build_pair_rows(engine_results, gates)
    return DashboardSnapshot(
        pair_rows=pair_rows,
        portfolio=portfolio,
        account_metrics=metrics,
        risk_warnings=warnings,
        data_source=data_source,
        leg_a_profile=leg_a.name,
        leg_b_profile=leg_b.name,
        dry_run=bool(params["execution"]["dry_run"]),
        load_errors=errors,
    )
