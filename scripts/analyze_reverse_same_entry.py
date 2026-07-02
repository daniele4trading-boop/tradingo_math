#!/usr/bin/env python3
"""
Simula reverse su GLI STESSI trade eseguiti (stessa entry, stesso momento).
Non cambia i fill dei limit — solo inverte direzione e specchia SL/TP.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest.data_loader import build_multitf, load_m1_directory
from backtest.emission_engine import EmissionBacktestEngine, OpenTrade
from strategies.emission_mtf import TradeDirection


def mirror_trade(row: pd.Series) -> OpenTrade:
    entry = float(row["entry_price"])
    direction = TradeDirection.LONG if row["direction"] == "SHORT" else TradeDirection.SHORT
    sl = 2 * entry - float(row["sl"])
    tp1 = 2 * entry - float(row["tp1"])
    tp2 = 2 * entry - float(row["tp2"])
    tp3 = 2 * entry - float(row["tp3"])
    return OpenTrade(
        direction=direction,
        entry_time=pd.Timestamp(row["entry_time"]),
        entry_price=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        initial_sl=sl,
        reason=str(row.get("reason", "")) + " [REVERSE-SAME-ENTRY]",
        profile=str(row["profile"]) + "_REVERSE_SAME",
    )


def simulate_profile(name: str, m5: pd.DataFrame) -> dict:
  path = ROOT / "results" / f"emission_trades_{name}.csv"
  if not path.exists():
      return {}
  df = pd.read_csv(path)
  engine = EmissionBacktestEngine.__new__(EmissionBacktestEngine)
  engine.risk_per_trade_usd = 100.0
  engine.cfg = type("C", (), {"broker_utc_offset_hours": 2})()

  closed = []
  m5 = m5.reset_index(drop=True)
  times = m5["time"].values

  for _, row in df.iterrows():
      trade = mirror_trade(row)
      entry_t = trade.entry_time
      idx = m5[m5["time"] >= entry_t].index
      if len(idx) == 0:
          continue
      start_i = idx[0]
      for i in range(start_i, len(m5)):
          bar = m5.iloc[i]
          trade, done = engine._manage_trade(trade, bar)
          if done is not None:
              closed.append(done)
              break

  out = pd.DataFrame(closed)
  if out.empty:
      return {"profile": name, "trades": 0}

  wins = (out["pnl_r"] > 0).sum()
  total = len(out)
  return {
      "profile": name,
      "trades": total,
      "win_rate_pct": round(wins / total * 100, 2),
      "expectancy_r": round(out["pnl_r"].mean(), 3),
      "profit_factor": round(
          out.loc[out["pnl_r"] > 0, "pnl_r"].sum() / abs(out.loc[out["pnl_r"] < 0, "pnl_r"].sum())
          if (out["pnl_r"] < 0).any() else float("inf"),
          3,
      ),
      "net_pnl": round(out["pnl_usd"].sum(), 2),
      "orig_trades": len(df),
      "orig_wr": round((df["pnl_r"] > 0).mean() * 100, 2),
      "orig_exp": round(df["pnl_r"].mean(), 3),
  }


def main() -> None:
    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    m5 = build_multitf(m1)["M5"]
    print("=== REVERSE su STESSA ENTRY (trade eseguiti originali) ===\n")
    rows = []
    for name in ["SCALPING_LIMIT", "SCALPING_MARKET"]:
        r = simulate_profile(name, m5)
        if not r:
            continue
        rows.append(r)
        print(f"--- {name} ---")
        print(f"  Originale: {r['orig_trades']} trade | WR {r['orig_wr']}% | exp {r['orig_exp']}R")
        print(
            f"  Reverse:   {r['trades']} trade | WR {r['win_rate_pct']}% | "
            f"exp {r['expectancy_r']}R | PF {r['profit_factor']} | PnL {r['net_pnl']}\n"
        )

    lines = [
        "# Reverse — stessa entry dei trade originali\n",
        "| Profilo | | Trade | Win% | Exp | PF | PnL |",
        "|---------|---|-------|------|-----|-----|-----|",
    ]
    for r in rows:
        lines.append(
            f"| {r['profile']} | ORIG | {r['orig_trades']} | {r['orig_wr']}% | {r['orig_exp']}R | — | — |"
        )
        lines.append(
            f"| | **REV** | {r['trades']} | **{r['win_rate_pct']}%** | "
            f"**{r['expectancy_r']}R** | **{r['profit_factor']}** | **{r['net_pnl']}** |"
        )
    (ROOT / "results" / "SCALPING_REVERSE_SAME_ENTRY.md").write_text("\n".join(lines))
    print("Report: results/SCALPING_REVERSE_SAME_ENTRY.md")


if __name__ == "__main__":
    main()
