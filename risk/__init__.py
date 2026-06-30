"""Risk package — portfolio limits, account guards, entry gate."""

from risk.guards import account_limit_violations, evaluate_entry_gate
from risk.manager import RiskManager
from risk.models import AccountRiskMetrics, PortfolioSnapshot, RiskGateResult
from risk.portfolio import portfolio_from_magics, scan_portfolio
from risk.snapshots import daily_loss_pct, drawdown_pct

__all__ = [
    "AccountRiskMetrics",
    "PortfolioSnapshot",
    "RiskGateResult",
    "RiskManager",
    "account_limit_violations",
    "daily_loss_pct",
    "drawdown_pct",
    "evaluate_entry_gate",
    "portfolio_from_magics",
    "scan_portfolio",
]
