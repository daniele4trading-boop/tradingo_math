#!/usr/bin/env python3
"""Backtest Emission MTF — 4 varianti: scalping/intraday × limit/market."""

from __future__ import annotations

import argparse
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
from strategies.emission_mtf import (
    EmissionMtfConfig,
    EmissionProfile,
    EntryMethod,
    EmissionStyle,
    STYLE_SPECS,
    profile_parts,
)

ALL_PROFILES = [
    EmissionProfile.SCALPING_LIMIT,
    EmissionProfile.SCALPING_MARKET,
    EmissionProfile.INTRADAY_LIMIT,
    EmissionProfile.INTRADAY_MARKET,
]


def base_config() -> EmissionMtfConfig:
    return EmissionMtfConfig(
        session_filter=False,
        context_filter=True,
        dominance_filter=True,
        fib_filter=False,
        min_rr=2.0,
        use_number_theory=True,
    )


def run_one(profile: EmissionProfile, m1: pd.DataFrame, tf: dict) -> dict:
    style, method = profile_parts(profile)
    spec = STYLE_SPECS[style]
    cfg = replace(base_config(), profile=profile)
    print(
        f"--- {profile.value}: {spec['label']} | metodo={method.value} | exec={spec['exec_tf']} ---"
    )
    engine = EmissionBacktestEngine(m1, config=cfg, tf=tf)
    result = engine.run()
    m = result.metrics
    print(
        f"    Trade: {m['trades']} | WR: {m['win_rate_pct']}% | "
        f"Exp: {m['expectancy_r']}R | PF: {m['profit_factor']} | "
        f"DD: {m['max_drawdown_pct']}% | PnL: {m['net_pnl']} USD\n"
    )
    return {"result": result, "metrics": m, "style": style.value, "method": method.value, "spec": spec}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Emission MTF strategy")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "XAUUSD" / "M1")
    parser.add_argument(
        "--profile",
        choices=[p.value for p in ALL_PROFILES],
        help="Run single profile (default: all 4)",
    )
    args = parser.parse_args()

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    m1 = load_m1_directory(args.data_dir)
    tf = build_multitf(m1)
    profiles = [EmissionProfile(args.profile)] if args.profile else ALL_PROFILES

    print(f"Data: {m1['time'].min()} -> {m1['time'].max()} ({len(m1)} M1 bars)\n")

    summary_rows = []
    all_trades = []

    for profile in profiles:
        row = run_one(profile, m1, tf)
        result = row["result"]
        m = row["metrics"]
        spec = row["spec"]

        result.trades.to_csv(results_dir / f"emission_trades_{profile.value}.csv", index=False)
        result.equity.to_csv(results_dir / f"emission_equity_{profile.value}.csv", index=False)

        summary_rows.append({
            "profile": profile.value,
            "style": row["style"],
            "method": row["method"],
            "label": spec["label"],
            "context": f"{spec['context_outer']}→{spec['context_inner']}",
            "operational_tf": spec["operational_tf"],
            "exec_tf": spec["exec_tf"],
            **m,
        })
        if not result.trades.empty:
            all_trades.append(result.trades)

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(results_dir / "emission_profiles_comparison.csv", index=False)

    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True).sort_values("entry_time")
        combined.to_csv(results_dir / "emission_trades_all.csv", index=False)

    payload = {
        "data_from": str(m1["time"].min()),
        "data_to": str(m1["time"].max()),
        "bars_m1": len(m1),
        "config": {
            "session_filter": False,
            "context_filter": True,
            "dominance_filter": True,
            "fib_filter": False,
            "min_rr": 2.0,
        },
        "profiles": summary_rows,
    }
    (results_dir / "emission_profiles_metrics.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )

    lines = [
        "# Emission MTF — Backtest 4 varianti\n",
        f"**Periodo:** {m1['time'].min()} → {m1['time'].max()}  ",
        f"**Barre M1:** {len(m1):,}  ",
        "**Strategia:** dominance + B2S/S2B (video DO7kdX-dByE)\n",
        "## Confronto\n",
        "| Profilo | Stile | Metodo | Contesto | Exec | Trade | Win% | Exp | PF | Max DD | PnL |",
        "|---------|-------|--------|----------|------|-------|------|-----|-----|--------|-----|",
    ]
    for row in summary_rows:
        lines.append(
            f"| **{row['profile']}** | {row['style']} | {row['method']} | {row['context']} | "
            f"{row['exec_tf']} | {row['trades']} | {row['win_rate_pct']}% | "
            f"{row['expectancy_r']}R | {row['profit_factor']} | {row['max_drawdown_pct']}% | {row['net_pnl']} |"
        )
    lines += [
        "\n## Profili\n",
        "- **SCALPING_LIMIT**: H4→H1 contesto, M5 operativo, sell/buy limit su B2S/S2B",
        "- **SCALPING_MARKET**: H4→H1 contesto, M5 operativo, engulfing/evening star in zona",
        "- **INTRADAY_LIMIT**: D1→H4 contesto, H1 operativo, limit su emissione",
        "- **INTRADAY_MARKET**: D1→H4 contesto, H1 operativo, pattern in zona emissione\n",
        "Filtri discrezionali (fib, wyckoff) disattivati — da affinare in ottimizzazione.\n",
    ]
    (results_dir / "EMISSION_BACKTEST_REPORT.md").write_text("\n".join(lines))

    print("=== SUMMARY ===")
    print(summary_df.to_string(index=False))
    print(f"\nReport: results/EMISSION_BACKTEST_REPORT.md")


if __name__ == "__main__":
    main()
