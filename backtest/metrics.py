"""Backtest metrics for LQS-MTF."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def compute_metrics(trades: pd.DataFrame, initial_balance: float = 10_000.0) -> Dict:
    if trades.empty:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "avg_rr": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "expectancy_r": 0.0,
            "net_pnl": 0.0,
            "tp1_hit_pct": 0.0,
            "tp2_hit_pct": 0.0,
            "tp3_hit_pct": 0.0,
            "long_trades": 0,
            "short_trades": 0,
            "session_breakdown": {},
        }

    wins = trades[trades["pnl_r"] > 0]
    losses = trades[trades["pnl_r"] <= 0]
    gross_profit = wins["pnl_r"].sum()
    gross_loss = abs(losses["pnl_r"].sum())

    equity = initial_balance + trades["pnl_usd"].cumsum()
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)

    session = trades.groupby("session")["pnl_r"].agg(["count", "mean", "sum"]).to_dict("index")

    return {
        "trades": int(len(trades)),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2),
        "avg_rr": round(float(trades["realized_rr"].mean()), 3),
        "profit_factor": round(float(gross_profit / gross_loss), 3) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": round(float(dd.min() * 100), 2),
        "expectancy_r": round(float(trades["pnl_r"].mean()), 3),
        "net_pnl": round(float(trades["pnl_usd"].sum()), 2),
        "tp1_hit_pct": round(100.0 * trades["tp1_hit"].mean(), 2),
        "tp2_hit_pct": round(100.0 * trades["tp2_hit"].mean(), 2),
        "tp3_hit_pct": round(100.0 * trades["tp3_hit"].mean(), 2),
        "long_trades": int((trades["direction"] == "LONG").sum()),
        "short_trades": int((trades["direction"] == "SHORT").sum()),
        "session_breakdown": session,
    }


def equity_curve(trades: pd.DataFrame, initial_balance: float = 10_000.0) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time", "equity"])
    out = trades[["exit_time", "pnl_usd"]].copy()
    out["equity"] = initial_balance + out["pnl_usd"].cumsum()
    out = out.rename(columns={"exit_time": "time"})
    return out
