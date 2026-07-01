#!/usr/bin/env python3
"""
Ottimizzazione scalping H1_M5 e M15_M5 — fase 1: massimizzare frequenza trade.
Grid mirata + campione random su train Mar-Apr, validazione full sample.
"""

from __future__ import annotations

import itertools
import json
import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.data_loader import build_multitf, load_m1_directory
from backtest.engine import BacktestEngine
from strategies.lqs_mtf import LQSProfile, LQSMtfConfig

SCALPING_PROFILES = [LQSProfile.H1_M5, LQSProfile.M15_M5]

PARAM_KEYS = [
    "sweep_atr_mult", "equal_highs_tolerance_atr", "min_rr",
    "limit_expire_bars_m5", "impulsive_body_ratio", "max_setup_age_bars",
    "sl_atr_buffer_mult", "cooldown_bars_m5", "h4_supply_pct",
    "context_filter", "liquidity_lookback_bars",
]

# Grid compatta orientata frequenza (972 combo → campioniamo)
FREQ_SPACE = {
    "sweep_atr_mult": [0.15, 0.20, 0.25],
    "equal_highs_tolerance_atr": [0.6, 0.8],
    "min_rr": [1.0, 1.2, 1.5],
    "limit_expire_bars_m5": [18, 30],
    "impulsive_body_ratio": [0.45, 0.50],
    "max_setup_age_bars": [12, 18],
    "sl_atr_buffer_mult": [0.25, 0.30],
    "cooldown_bars_m5": [3, 6],
    "h4_supply_pct": [0.90, 0.95],
    "context_filter": [False, True],
    "liquidity_lookback_bars": [80, 120],
}

# Preset manuali ad alta frequenza (sempre testati)
FREQ_PRESETS: List[Dict[str, Any]] = [
    {"sweep_atr_mult": 0.15, "equal_highs_tolerance_atr": 0.8, "min_rr": 1.0,
     "limit_expire_bars_m5": 30, "impulsive_body_ratio": 0.45, "max_setup_age_bars": 18,
     "sl_atr_buffer_mult": 0.30, "cooldown_bars_m5": 3, "h4_supply_pct": 0.95,
     "context_filter": False, "liquidity_lookback_bars": 120},
    {"sweep_atr_mult": 0.20, "equal_highs_tolerance_atr": 0.6, "min_rr": 1.2,
     "limit_expire_bars_m5": 24, "impulsive_body_ratio": 0.50, "max_setup_age_bars": 12,
     "sl_atr_buffer_mult": 0.25, "cooldown_bars_m5": 3, "h4_supply_pct": 0.90,
     "context_filter": False, "liquidity_lookback_bars": 96},
    {"sweep_atr_mult": 0.25, "equal_highs_tolerance_atr": 0.8, "min_rr": 1.5,
     "limit_expire_bars_m5": 18, "impulsive_body_ratio": 0.50, "max_setup_age_bars": 18,
     "sl_atr_buffer_mult": 0.25, "cooldown_bars_m5": 6, "h4_supply_pct": 0.95,
     "context_filter": True, "liquidity_lookback_bars": 80},
]

RANDOM_EXTRA = 10


def score_frequency(metrics: Dict[str, Any]) -> float:
    trades = int(metrics.get("trades", 0))
    if trades < 5:
        return -200.0 + trades
    exp = float(metrics.get("expectancy_r", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    if pf == float("inf"):
        pf = 1.5
    dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
    return trades * 0.30 + exp * 1.2 + min(pf, 1.5) * 0.15 - dd * 0.004


def run_combo(profile: LQSProfile, params: Dict[str, Any], m1, tf, start, end) -> Dict[str, Any]:
    base = LQSMtfConfig(profile=profile, session_filter=False)
    fields = LQSMtfConfig.__dataclass_fields__
    cfg = replace(base, **{k: v for k, v in params.items() if k in fields})
    result = BacktestEngine(m1, config=cfg, tf=tf).run(start=start, end=end)
    return {**params, "profile": profile.value, **result.metrics, "freq_score": score_frequency(result.metrics)}


def build_candidates() -> List[Dict[str, Any]]:
    keys = list(FREQ_SPACE.keys())
    universe = [dict(zip(keys, v)) for v in itertools.product(*FREQ_SPACE.values())]
    random.seed(42)
    sample = random.sample(universe, min(RANDOM_EXTRA, len(universe)))
    seen = {tuple(p[k] for k in PARAM_KEYS) for p in FREQ_PRESETS}
    out = list(FREQ_PRESETS)
    for s in sample:
        t = tuple(s[k] for k in PARAM_KEYS)
        if t not in seen:
            seen.add(t)
            out.append(s)
    return out


def optimize_profile(profile: LQSProfile, m1, tf, train_start, train_end) -> Dict[str, Any]:
    candidates = build_candidates()
    print(f"\n{'='*55}\n  {profile.value} — {len(candidates)} candidati\n{'='*55}")
    rows = []
    t0 = time.time()
    for i, params in enumerate(candidates, 1):
        row = run_combo(profile, params, m1, tf, train_start, train_end)
        rows.append(row)
        print(
            f"  [{i}/{len(candidates)}] trades={row['trades']:3d} exp={row['expectancy_r']:+.2f}R "
            f"score={row['freq_score']:.1f} ({time.time()-t0:.0f}s)"
        )
    df = pd.DataFrame(rows).sort_values("freq_score", ascending=False)
    return df.iloc[0].to_dict()


def main() -> None:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    tf = build_multitf(m1)
    train_start = pd.Timestamp("2026-03-01", tz="UTC")
    train_end = pd.Timestamp("2026-04-30 23:59:00", tz="UTC")

    best_by_profile: Dict[str, Dict] = {}

    for profile in SCALPING_PROFILES:
        best_train = optimize_profile(profile, m1, tf, train_start, train_end)
        params = {k: best_train[k] for k in PARAM_KEYS}
        full = run_combo(profile, params, m1, tf, None, None)

        cfg = replace(
            LQSMtfConfig(profile=profile, session_filter=False),
            **{k: v for k, v in params.items() if k in LQSMtfConfig.__dataclass_fields__},
        )
        BacktestEngine(m1, config=cfg, tf=tf).run().trades.to_csv(
            results_dir / f"scalping_{profile.value}_optimized.csv", index=False
        )

        best_by_profile[profile.value] = {
            "params": params,
            "train": {k: best_train[k] for k in ["trades", "expectancy_r", "profit_factor", "win_rate_pct", "freq_score"]},
            "full": {k: full[k] for k in ["trades", "expectancy_r", "profit_factor", "win_rate_pct", "max_drawdown_pct", "net_pnl", "freq_score"]},
        }
        print(f"\n  >> {profile.value} BEST: train={best_train['trades']} full={full['trades']} trades", flush=True)
        # Salva incrementale per non perdere progresso su validazione full lenta
        (results_dir / "scalping_freq_opt.json").write_text(
            json.dumps({"profiles": best_by_profile, "train": f"{train_start.date()}->{train_end.date()}"}, indent=2, default=str)
        )

    cfg_path = ROOT / "config.json"
    with cfg_path.open() as f:
        cfg = json.load(f)
    cfg["lqs_mtf_scalping"] = {
        "_note": "Fase 1 frequenza — profili separati",
        "_optimized": "2026-06-30",
        "H1_M5": best_by_profile["H1_M5"]["params"],
        "M15_M5": best_by_profile["M15_M5"]["params"],
    }
    with cfg_path.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    summary = {"profiles": best_by_profile, "train": f"{train_start.date()}->{train_end.date()}"}
    (results_dir / "scalping_freq_opt.json").write_text(json.dumps(summary, indent=2, default=str))

    lines = [
        "# Scalping — Ottimizzazione Frequenza\n",
        "| Profilo | Train trades | Full trades | Full exp | Full PF | PnL |",
        "|---------|-------------|-------------|----------|---------|-----|",
    ]
    for p in SCALPING_PROFILES:
        b = best_by_profile[p.value]
        f = b["full"]
        lines.append(f"| **{p.value}** | {b['train']['trades']} | {f['trades']} | {f['expectancy_r']}R | {f['profit_factor']} | {f['net_pnl']} |")
    for p in SCALPING_PROFILES:
        lines.append(f"\n### {p.value}\n```json\n{json.dumps(best_by_profile[p.value]['params'], indent=2)}\n```")
    (results_dir / "SCALPING_FREQ_REPORT.md").write_text("\n".join(lines))
    print("\nDONE — results/SCALPING_FREQ_REPORT.md")


if __name__ == "__main__":
    main()
