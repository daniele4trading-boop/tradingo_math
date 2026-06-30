from __future__ import annotations

from typing import Any

from core.config import AccountProfile, CandidatePair
from risk.account import read_account_metrics
from risk.guards import account_limit_violations, evaluate_entry_gate
from risk.models import AccountRiskMetrics, PortfolioSnapshot, RiskGateResult
from risk.portfolio import scan_portfolio


class RiskManager:
    def __init__(
        self,
        leg_a_profile: AccountProfile,
        leg_b_profile: AccountProfile,
        params: dict[str, Any],
    ) -> None:
        self.leg_a_profile = leg_a_profile
        self.leg_b_profile = leg_b_profile
        self.params = params

    def load_portfolio(self) -> PortfolioSnapshot:
        return scan_portfolio(self.leg_a_profile, self.leg_b_profile)

    def load_account_metrics(self) -> list[AccountRiskMetrics]:
        return [
            read_account_metrics(self.leg_a_profile),
            read_account_metrics(self.leg_b_profile),
        ]

    def check_new_entry(self, candidate: CandidatePair) -> RiskGateResult:
        portfolio = self.load_portfolio()
        metrics = self.load_account_metrics()
        return evaluate_entry_gate(candidate, portfolio, metrics, self.params)

    def full_status(self) -> tuple[PortfolioSnapshot, list[AccountRiskMetrics], list[str]]:
        portfolio = self.load_portfolio()
        metrics = self.load_account_metrics()
        warnings: list[str] = []
        if portfolio.unhedged_pairs:
            warnings.append(
                "unhedged: " + ", ".join(item.pair_label for item in portfolio.unhedged_pairs)
            )
        warnings.extend(account_limit_violations(metrics, self.params))
        return portfolio, metrics, warnings
