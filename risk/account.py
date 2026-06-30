from __future__ import annotations

from types import ModuleType

from core.config import AccountProfile
from core.mt5_connection import Mt5Session
from risk.models import AccountRiskMetrics
from risk.snapshots import daily_loss_pct, drawdown_pct, update_equity_snapshot


def _margin_level(info: object) -> float:
    margin_level = float(getattr(info, "margin_level", 0) or 0)
    if margin_level > 0:
        return margin_level
    equity = float(getattr(info, "equity", 0) or 0)
    margin = float(getattr(info, "margin", 0) or 0)
    if margin <= 0:
        return float("inf")
    return (equity / margin) * 100.0


def read_account_metrics(profile: AccountProfile) -> AccountRiskMetrics:
    with Mt5Session(profile) as mt5:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"account_info assente profilo={profile.name}: {mt5.last_error()}")
        equity = float(info.equity)
        balance = float(info.balance)
        margin = float(info.margin)
        margin_level = _margin_level(info)
        start_equity, peak_equity = update_equity_snapshot(profile.name, equity)

    return AccountRiskMetrics(
        profile_name=profile.name,
        equity=equity,
        balance=balance,
        margin=margin,
        margin_level=margin_level,
        daily_loss_pct=daily_loss_pct(start_equity, equity),
        drawdown_pct=drawdown_pct(peak_equity, equity),
    )
