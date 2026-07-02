#!/usr/bin/env python3
"""Backtest scalping emission con segnali invertiti (reverse)."""

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
from backtest.emission_engine import EmissionBacktestEngine
from strategies.emission_mtf import EmissionMtfConfig, EmissionProfile

SCALPING = [EmissionProfile.SCALPING_LIMIT, EmissionProfile.SCALPING_MARKET]


def main() -> None:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    tf = build_multitf(m1)
    print(f"Data: {m1['time'].min()} -> {m1['time'].max()} ({len(m1)} M1 bars)\n")
    print("=== REVERSE: stessi setup/trigger, direzione opposta ===\n")

    rows = []
    for profile in SCALPING:
        cfg = replace(
            EmissionMtfConfig(profile=profile, reverse_signals=True),
            session_filter=False,
        )
        print(f"--- {profile.value}_REVERSE ---")
        result = EmissionBacktestEngine(m1, config=cfg, tf=tf).run()
        m = result.metrics
        print(
            f"    Trade: {m['trades']} | WR: {m['win_rate_pct']}% | "
            f"Exp: {m['expectancy_r']}R | PF: {m['profit_factor']} | "
            f"DD: {m['max_drawdown_pct']}% | PnL: {m['net_pnl']} USD\n"
        )
        result.trades.to_csv(results_dir / f"emission_reverse_{profile.value}.csv", index=False)
        rows.append({
            "profile": f"{profile.value}_REVERSE",
            "original_profile": profile.value,
            **m,
        })

    # Confronto con originale se disponibile
    orig_path = results_dir / "emission_profiles_metrics.json"
    if orig_path.exists():
        orig = json.loads(orig_path.read_text()).get("profiles", [])
        orig_map = {r["profile"]: r for r in orig}
        print("=== CONFRONTO ORIGINALE vs REVERSE ===\n")
        print(f"{'Profilo':<25} {'':^6} {'Trade':>6} {'WR%':>7} {'Exp':>8} {'PF':>6} {'PnL':>10}")
        print("-" * 72)
        for row in rows:
            op = row["original_profile"]
            o = orig_map.get(op, {})
            print(
                f"{op:<25} {'ORIG':>6} {o.get('trades', '-'):>6} "
                f"{o.get('win_rate_pct', '-'):>7} {o.get('expectancy_r', '-'):>8} "
                f"{o.get('profit_factor', '-'):>6} {o.get('net_pnl', '-'):>10}"
            )
            print(
                f"{'':<25} {'REV':>6} {row['trades']:>6} "
                f"{row['win_rate_pct']:>7} {row['expectancy_r']:>8} "
                f"{row['profit_factor']:>6} {row['net_pnl']:>10}"
            )
            print()

    payload = {"reverse": True, "profiles": rows}
    (results_dir / "emission_scalping_reverse.json").write_text(json.dumps(payload, indent=2, default=str))

    lines = [
        "# Scalping Reverse — stesso setup, direzione opposta\n",
        f"**Periodo:** {m1['time'].min()} → {m1['time'].max()}\n",
        "| Profilo | Trade | Win% | Exp | PF | Max DD | PnL |",
        "|---------|-------|------|-----|-----|--------|-----|",
    ]
    for row in rows:
        lines.append(
            f"| **{row['profile']}** | {row['trades']} | {row['win_rate_pct']}% | "
            f"{row['expectancy_r']}R | {row['profit_factor']} | {row['max_drawdown_pct']}% | {row['net_pnl']} |"
        )
    if orig_path.exists():
        lines.append("\n## Confronto originale\n")
        lines.append("| Profilo | | Trade | Win% | Exp | PF | PnL |")
        lines.append("|---------|---|-------|------|-----|-----|-----|")
        for row in rows:
            op = row["original_profile"]
            o = orig_map.get(op, {})
            lines.append(
                f"| {op} | ORIG | {o.get('trades','-')} | {o.get('win_rate_pct','-')}% | "
                f"{o.get('expectancy_r','-')}R | {o.get('profit_factor','-')} | {o.get('net_pnl','-')} |"
            )
            lines.append(
                f"| | **REV** | **{row['trades']}** | **{row['win_rate_pct']}%** | "
                f"**{row['expectancy_r']}R** | **{row['profit_factor']}** | **{row['net_pnl']}** |"
            )
    (results_dir / "SCALPING_REVERSE_REPORT.md").write_text("\n".join(lines))
    print("Report: results/SCALPING_REVERSE_REPORT.md")


if __name__ == "__main__":
    main()
