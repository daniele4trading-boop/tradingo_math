#!/usr/bin/env python3
"""Finalizza ottimizzazione frequenza scalping da risultati train già noti."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.data_loader import build_multitf, load_m1_directory
from backtest.engine import BacktestEngine
from strategies.lqs_mtf import LQSProfile, LQSMtfConfig

PARAM_KEYS = [
    "sweep_atr_mult", "equal_highs_tolerance_atr", "min_rr",
    "limit_expire_bars_m5", "impulsive_body_ratio", "max_setup_age_bars",
    "sl_atr_buffer_mult", "cooldown_bars_m5", "h4_supply_pct",
    "context_filter", "liquidity_lookback_bars",
]

# Best train da results/scalping_opt.log (fase 1 frequenza)
BEST_TRAIN = {
    "H1_M5": {
        "params": {
            "sweep_atr_mult": 0.25, "equal_highs_tolerance_atr": 0.8, "min_rr": 1.5,
            "limit_expire_bars_m5": 18, "impulsive_body_ratio": 0.50, "max_setup_age_bars": 18,
            "sl_atr_buffer_mult": 0.25, "cooldown_bars_m5": 6, "h4_supply_pct": 0.95,
            "context_filter": True, "liquidity_lookback_bars": 80,
        },
        "train": {"trades": 61, "expectancy_r": -0.78, "profit_factor": 0.0, "win_rate_pct": 0.0, "freq_score": 17.2},
    },
    "M15_M5": {
        "params": {
            "sweep_atr_mult": 0.15, "equal_highs_tolerance_atr": 0.8, "min_rr": 1.0,
            "limit_expire_bars_m5": 30, "impulsive_body_ratio": 0.45, "max_setup_age_bars": 18,
            "sl_atr_buffer_mult": 0.30, "cooldown_bars_m5": 3, "h4_supply_pct": 0.95,
            "context_filter": False, "liquidity_lookback_bars": 120,
        },
        "train": {"trades": 96, "expectancy_r": -0.47, "profit_factor": 0.0, "win_rate_pct": 0.0, "freq_score": 28.1},
    },
}


def run_full(profile: LQSProfile, params: dict, m1, tf) -> dict:
    cfg = replace(
        LQSMtfConfig(profile=profile, session_filter=False),
        **{k: v for k, v in params.items() if k in LQSMtfConfig.__dataclass_fields__},
    )
    t0 = time.time()
    print(f"  Full backtest {profile.value}...", flush=True)
    result = BacktestEngine(m1, config=cfg, tf=tf).run()
    elapsed = time.time() - t0
    print(f"  Done {profile.value}: {result.metrics['trades']} trades ({elapsed:.0f}s)", flush=True)
    return result


def main() -> None:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    print("Loading M1 data...", flush=True)
    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    tf = build_multitf(m1)

    best_by_profile = {}
    for name, data in BEST_TRAIN.items():
        profile = LQSProfile(name)
        params = data["params"]
        result = run_full(profile, params, m1, tf)
        result.trades.to_csv(results_dir / f"scalping_{name}_optimized.csv", index=False)
        m = result.metrics
        best_by_profile[name] = {
            "params": params,
            "train": data["train"],
            "full": {
                "trades": m["trades"],
                "expectancy_r": m["expectancy_r"],
                "profit_factor": m["profit_factor"],
                "win_rate_pct": m["win_rate_pct"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "net_pnl": m["net_pnl"],
            },
        }

    cfg_path = ROOT / "config.json"
    with cfg_path.open() as f:
        cfg = json.load(f)
    cfg["lqs_mtf_scalping"] = {
        "_note": "Fase 1 frequenza — profili separati H1_M5 e M15_M5",
        "_optimized": "2026-06-30",
        "H1_M5": best_by_profile["H1_M5"]["params"],
        "M15_M5": best_by_profile["M15_M5"]["params"],
    }
    with cfg_path.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    summary = {
        "profiles": best_by_profile,
        "train": "2026-03-01->2026-04-30",
        "full": "2026-02-24->2026-06-05",
    }
    (results_dir / "scalping_freq_opt.json").write_text(json.dumps(summary, indent=2, default=str))

    lines = [
        "# Scalping — Ottimizzazione Frequenza (Fase 1)\n",
        "Obiettivo: massimizzare numero trade su train Mar–Apr, validazione full sample.\n",
        "Fase 2 (affinamento expectancy/PF) da fare successivamente.\n",
        "| Profilo | Train trades | Full trades | Full exp | Full PF | Win% | Max DD | PnL |",
        "|---------|-------------|-------------|----------|---------|------|--------|-----|",
    ]
    for name in ["H1_M5", "M15_M5"]:
        b = best_by_profile[name]
        f, t = b["full"], b["train"]
        lines.append(
            f"| **{name}** | {t['trades']} | {f['trades']} | {f['expectancy_r']:+.2f}R | "
            f"{f['profit_factor']:.2f} | {f['win_rate_pct']:.1f}% | {f['max_drawdown_pct']:.1f}% | {f['net_pnl']:.0f} |"
        )
    for name in ["H1_M5", "M15_M5"]:
        lines.append(f"\n### {name}\n```json\n{json.dumps(best_by_profile[name]['params'], indent=2)}\n```")
    (results_dir / "SCALPING_FREQ_REPORT.md").write_text("\n".join(lines))
    print("\nDONE — results/SCALPING_FREQ_REPORT.md", flush=True)


if __name__ == "__main__":
    main()
