#!/usr/bin/env python3
"""Backtest all 3 LQS-MTF profiles and produce comparison report."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest.data_loader import build_multitf, load_m1_directory
from backtest.engine import BacktestEngine
from strategies.lqs_mtf import LQSProfile, LQSMtfConfig, PROFILE_SPECS

PROFILES = [LQSProfile.H4_M15, LQSProfile.H1_M15, LQSProfile.H1_M5]


def base_config() -> LQSMtfConfig:
    """Shared params: session OFF for fair comparison, min_rr 1.5 for more trades."""
    return LQSMtfConfig(
        session_filter=False,
        min_rr=1.5,
        sweep_atr_mult=0.3,
        equal_highs_tolerance_atr=0.5,
        sl_atr_buffer_mult=0.25,
        limit_expire_bars_m5=12,
    )


def main() -> None:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    tf = build_multitf(m1)

    summary_rows = []
    all_trades = []

    print(f"Data: {m1['time'].min()} -> {m1['time'].max()} ({len(m1)} M1 bars)\n")

    for profile in PROFILES:
        spec = PROFILE_SPECS[profile]
        cfg = replace(base_config(), profile=profile)
        print(f"--- {profile.value}: {spec['label']} ---")
        print(f"    Liquidità: {spec['liquidity_tf']} | Conferma: {spec['confirm_tf']} | Esecuzione: M5")

        engine = BacktestEngine(m1, config=cfg, tf=tf)
        result = engine.run()

        m = result.metrics
        print(
            f"    Trade: {m['trades']} | WR: {m['win_rate_pct']}% | "
            f"Exp: {m['expectancy_r']}R | PF: {m['profit_factor']} | "
            f"DD: {m['max_drawdown_pct']}% | PnL: {m['net_pnl']} USD\n"
        )

        trades_path = results_dir / f"backtest_trades_{profile.value}.csv"
        result.trades.to_csv(trades_path, index=False)
        result.equity.to_csv(results_dir / f"equity_{profile.value}.csv", index=False)

        summary_rows.append({
            "profile": profile.value,
            "label": spec["label"],
            "liquidity_tf": spec["liquidity_tf"],
            "confirm_tf": spec["confirm_tf"],
            "exec_tf": "M5",
            **m,
        })
        if not result.trades.empty:
            all_trades.append(result.trades)

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(results_dir / "backtest_profiles_comparison.csv", index=False)

    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True).sort_values("entry_time")
        combined.to_csv(results_dir / "backtest_trades_all_profiles.csv", index=False)

    payload = {
        "data_from": str(m1["time"].min()),
        "data_to": str(m1["time"].max()),
        "bars_m1": len(m1),
        "config": {
            "session_filter": False,
            "min_rr": 1.5,
            "sweep_atr_mult": 0.3,
            "sl_atr_buffer_mult": 0.25,
        },
        "profiles": summary_rows,
    }
    with (results_dir / "backtest_profiles_metrics.json").open("w") as f:
        json.dump(payload, f, indent=2, default=str)

    # Markdown report
    lines = [
        "# LQS-MTF — Backtest 3 Profili\n",
        f"**Periodo:** {m1['time'].min()} → {m1['time'].max()}  ",
        f"**Barre M1:** {len(m1):,}  ",
        "**Esecuzione:** M5 | **Session filter:** OFF | **min_rr:** 1.5\n",
        "## Confronto profili\n",
        "| Profilo | Setup → Conferma | Trade | Win% | Expectancy | PF | Max DD | PnL |",
        "|---------|------------------|-------|------|------------|-----|--------|-----|",
    ]
    for row in summary_rows:
        lines.append(
            f"| **{row['profile']}** | {row['liquidity_tf']}→{row['confirm_tf']} | "
            f"{row['trades']} | {row['win_rate_pct']}% | {row['expectancy_r']}R | "
            f"{row['profit_factor']} | {row['max_drawdown_pct']}% | {row['net_pnl']} |"
        )
    lines += [
        "\n## Descrizione profili\n",
        "- **H4_M15**: sweep liquidità su H4, BOS su M15, entry limit M5 (swing)",
        "- **H1_M15**: sweep su H1, BOS su M15, entry limit M5 (intraday)",
        "- **H1_M5**: sweep su H1, BOS su M5, entry limit M5 (intraday rapido)\n",
    ]
    (results_dir / "BACKTEST_PROFILES_REPORT.md").write_text("\n".join(lines))

    print("=== SUMMARY ===")
    print(summary_df.to_string(index=False))
    print(f"\nReport: results/BACKTEST_PROFILES_REPORT.md")


if __name__ == "__main__":
    main()
