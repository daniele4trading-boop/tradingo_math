from __future__ import annotations

from typing import Any

from core.config import CandidatePair
from risk.models import AccountRiskMetrics, PortfolioSnapshot, RiskGateResult


def account_limit_violations(metrics: list[AccountRiskMetrics], params: dict[str, Any]) -> list[str]:
    return _account_limits_ok(metrics, params)


def _account_limits_ok(metrics: list[AccountRiskMetrics], params: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    risk = params["risk"]
    daily_limit = float(risk["per_account_daily_loss_pct"])
    dd_limit = float(risk["per_account_max_dd_pct"])
    margin_floor = float(risk["margin_floor_pct"])

    for metric in metrics:
        if metric.daily_loss_pct > daily_limit:
            reasons.append(
                f"{metric.profile_name} daily_loss={metric.daily_loss_pct:.2f}%>{daily_limit}%"
            )
        if metric.drawdown_pct > dd_limit:
            reasons.append(
                f"{metric.profile_name} drawdown={metric.drawdown_pct:.2f}%>{dd_limit}%"
            )
        if metric.margin_level < margin_floor:
            reasons.append(
                f"{metric.profile_name} margin_level={metric.margin_level:.1f}%<{margin_floor}%"
            )
    return reasons


def evaluate_entry_gate(
    candidate: CandidatePair,
    portfolio: PortfolioSnapshot,
    account_metrics: list[AccountRiskMetrics],
    params: dict[str, Any],
) -> RiskGateResult:
    reasons: list[str] = []
    risk = params["risk"]

    if portfolio.unhedged_pairs:
        labels = ", ".join(item.pair_label for item in portfolio.unhedged_pairs)
        reasons.append(f"unhedged_positions={labels}")

    max_pairs = int(risk["max_concurrent_pairs"])
    if portfolio.open_pair_count >= max_pairs:
        reasons.append(
            f"max_concurrent_pairs={portfolio.open_pair_count}>={max_pairs}"
        )

    max_share = int(risk["max_pairs_sharing_leg"])
    leg_usage = portfolio.leg_usage()
    for leg in (candidate.leg_a, candidate.leg_b):
        used = leg_usage.get(leg, 0)
        if used >= max_share:
            reasons.append(f"leg {leg} già in {used} pair (>={max_share})")

    reasons.extend(account_limit_violations(account_metrics, params))

    return RiskGateResult(allowed=len(reasons) == 0, reasons=reasons)
