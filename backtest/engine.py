"""Backtest engine base per strategie TradinGO.

Il motore e' volutamente conservativo: carica dati M1 CSV, chiama una strategia
senza lookahead e produce trade log/report. Le strategie concrete verranno
aggiunte in `backtest/strategies/` quando saranno estratte dai file TXT.
"""

from __future__ import annotations

import argparse
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class BacktestParams:
    pair: str
    initial_capital: float = 10_000.0
    lot_size: float = 0.1
    leverage: float = 1.0
    commission_per_trade: float = 0.0


def load_m1_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"datetime", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").set_index("datetime")
    return df


def load_strategy(dotted_path: str, params: dict[str, Any]):
    module_name, class_name = dotted_path.rsplit(":", 1)
    module = importlib.import_module(module_name)
    strategy_cls = getattr(module, class_name)
    return strategy_cls(**params)


def run_backtest(df_m1: pd.DataFrame, strategy, params: BacktestParams) -> dict[str, Any]:
    signals = strategy.generate_signals(df_m1.copy())
    if "signal" not in signals.columns:
        raise ValueError("Strategy must return a DataFrame with a 'signal' column")

    trades = []
    equity = params.initial_capital
    position = None

    for timestamp, row in signals.iterrows():
        signal = int(row.get("signal", 0))
        price = float(row["close"])

        if position is None and signal != 0:
            position = {
                "entry_time": timestamp.isoformat(),
                "direction": "BUY" if signal > 0 else "SELL",
                "entry_price": price,
                "signal": signal,
            }
            continue

        if position is not None and signal == -position["signal"]:
            direction = position["signal"]
            pnl_points = (price - position["entry_price"]) * direction
            pnl = pnl_points * params.lot_size * params.leverage - params.commission_per_trade
            equity += pnl
            trades.append(
                {
                    **position,
                    "exit_time": timestamp.isoformat(),
                    "exit_price": price,
                    "pnl": pnl,
                    "reason": "opposite_signal",
                    "equity": equity,
                }
            )
            position = None

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    net_pnl = sum(t["pnl"] for t in trades)

    report = {
        "pair": params.pair,
        "total_trades": len(trades),
        "win_rate": (len(wins) / len(trades)) if trades else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "max_dd": None,
        "sharpe": None,
        "net_pnl": net_pnl,
        "final_equity": equity,
        "trades": trades,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--strategy", required=True, help="Example: backtest.strategies.strategy_001:Strategy")
    parser.add_argument("--pair", required=True)
    parser.add_argument("--strategy-params", default="{}")
    parser.add_argument("--out", default="backtest/output")
    args = parser.parse_args()

    df = load_m1_csv(Path(args.csv))
    strategy = load_strategy(args.strategy, json.loads(args.strategy_params))
    report = run_backtest(df, strategy, BacktestParams(pair=args.pair))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(report["trades"]).to_csv(out_dir / "trades.csv", index=False)


if __name__ == "__main__":
    main()
