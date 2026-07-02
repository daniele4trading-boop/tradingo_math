#!/usr/bin/env python3
"""Metriche win rate vs non-loss (include BE e TP1+BE)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def classify_trades(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {}

    pnl = df["pnl_r"]
    tp1 = df["tp1_hit"].astype(bool)

    win = pnl > 0
    be_flat = pnl == 0
    full_loss = pnl <= -0.99  # ~-1R

    # TP1 raggiunto poi chiusura su SL (tipicamente BE sul residuo)
    tp1_then_sl = tp1 & (df["exit_reason"] == "SL")

    # Non-loss: win, BE piatto, oppure TP1 toccato (anche se PnL netto misto)
    non_loss = win | be_flat | tp1

    # Non-loss stretto: solo win o BE esatto (pnl >= 0)
    non_loss_strict = pnl >= 0

    # Non-loss ampio: non ha perso 1R intero (evita full stop out)
    non_loss_no_full_sl = ~full_loss

    return {
        "trades": n,
        "win_pct": round(win.sum() / n * 100, 2),
        "be_flat_pct": round(be_flat.sum() / n * 100, 2),
        "tp1_hit_pct": round(tp1.sum() / n * 100, 2),
        "tp1_then_sl_pct": round(tp1_then_sl.sum() / n * 100, 2),
        "non_loss_pct": round(non_loss.sum() / n * 100, 2),
        "non_loss_strict_pct": round(non_loss_strict.sum() / n * 100, 2),
        "non_loss_no_full_sl_pct": round(non_loss_no_full_sl.sum() / n * 100, 2),
        "full_loss_pct": round(full_loss.sum() / n * 100, 2),
        "expectancy_r": round(pnl.mean(), 3),
        "net_pnl": round(df["pnl_usd"].sum(), 2),
    }


def load_profile(name: str, reverse: bool = False) -> pd.DataFrame | None:
    if reverse:
        path = ROOT / "results" / f"emission_reverse_{name}.csv"
    else:
        path = ROOT / "results" / f"emission_trades_{name}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def main() -> None:
    profiles = ["SCALPING_LIMIT", "SCALPING_MARKET"]
    rows = []

    print("=== Test 1 — Win rate vs Non-loss (ORIG vs REVERSE engine) ===\n")
    header = (
        f"{'Profilo':<22} {'Side':<5} {'N':>5} {'Win%':>7} {'TP1%':>7} "
        f"{'TP1→SL%':>8} {'NonLoss%':>9} {'NoFullSL%':>10} {'FullSL%':>8} {'Exp':>7}"
    )
    print(header)
    print("-" * len(header))

    for name in profiles:
        for reverse, side in [(False, "ORIG"), (True, "REV")]:
            df = load_profile(name, reverse=reverse)
            if df is None:
                continue
            m = classify_trades(df)
            m["profile"] = name
            m["side"] = side
            rows.append(m)
            print(
                f"{name:<22} {side:<5} {m['trades']:>5} {m['win_pct']:>6.1f}% "
                f"{m['tp1_hit_pct']:>6.1f}% {m['tp1_then_sl_pct']:>7.1f}% "
                f"{m['non_loss_pct']:>8.1f}% {m['non_loss_no_full_sl_pct']:>9.1f}% "
                f"{m['full_loss_pct']:>7.1f}% {m['expectancy_r']:>7.3f}"
            )

    lines = [
        "# Scalping — Win% vs Non-loss% (Test 1 reverse engine)\n",
        "**Non-loss%** = trade con `pnl > 0`, oppure `pnl = 0` (BE), oppure **TP1 toccato** "
        "(inclusi TP1 → SL/BE sul residuo).\n",
        "| Profilo | Side | Trade | Win% | TP1% | TP1→SL% | **Non-loss%** | No full SL% | Full SL% | Exp | PnL |",
        "|---------|------|-------|------|------|---------|---------------|-------------|----------|-----|-----|",
    ]
    for m in rows:
        lines.append(
            f"| {m['profile']} | {m['side']} | {m['trades']} | {m['win_pct']}% | "
            f"{m['tp1_hit_pct']}% | {m['tp1_then_sl_pct']}% | **{m['non_loss_pct']}%** | "
            f"{m['non_loss_no_full_sl_pct']}% | {m['full_loss_pct']}% | {m['expectancy_r']}R | {m['net_pnl']} |"
        )

    lines.append("\n### Legenda\n")
    lines.append("- **Win%**: solo `pnl_r > 0`")
    lines.append("- **Non-loss%**: win + BE piatto + qualsiasi trade che ha toccato TP1")
    lines.append("- **TP1→SL%**: TP1 raggiunto, chiusura finale su SL (tipico BE sul 50% residuo)")
    lines.append("- **No full SL%**: non ha perso -1R intero")
    lines.append("- **Full SL%**: stop out completo (~-1R)")

    out = ROOT / "results" / "SCALPING_NON_LOSS_REPORT.md"
    out.write_text("\n".join(lines))
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
