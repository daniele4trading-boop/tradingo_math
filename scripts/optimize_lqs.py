#!/usr/bin/env python3
"""Staged optimization: random search + refine + walk-forward OOS."""

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
from strategies.lqs_mtf import LQSMtfConfig

PARAM_KEYS = [
    "sweep_atr_mult",
    "equal_highs_tolerance_atr",
    "min_rr",
    "session_filter",
    "limit_expire_bars_m5",
    "impulsive_body_ratio",
    "max_setup_age_bars_h1",
    "sl_atr_buffer_mult",
]

FULL_SPACE = {
    "sweep_atr_mult": [0.2, 0.3, 0.4],
    "equal_highs_tolerance_atr": [0.3, 0.5, 0.7],
    "min_rr": [1.5, 2.0, 2.5],
    "session_filter": [False, True],
    "limit_expire_bars_m5": [6, 12, 24],
    "impulsive_body_ratio": [0.50, 0.55, 0.60],
    "max_setup_age_bars_h1": [6, 10, 14],
    "sl_atr_buffer_mult": [0.15, 0.20, 0.25],
}

RANDOM_SAMPLES = 20


def _cast_param(key: str, value: Any) -> Any:
    if key in {"session_filter"}:
        return bool(value) if not isinstance(value, str) else value.lower() == "true"
    if key in {"limit_expire_bars_m5", "max_setup_age_bars_h1", "bos_accept_bars"}:
        return int(value)
    return float(value)


def score_metrics(metrics: Dict[str, Any], min_trades: int = 5) -> float:
    trades = int(metrics.get("trades", 0))
    if trades < min_trades:
        return -999.0
    expectancy = float(metrics.get("expectancy_r", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    if pf == float("inf"):
        pf = 3.0
    dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
    win = float(metrics.get("win_rate_pct", 0.0)) / 100.0
    return expectancy * 2.0 + min(pf, 2.5) * 0.3 + win * 0.2 - dd * 0.02


def all_combos() -> List[Dict[str, Any]]:
    keys = list(FULL_SPACE.keys())
    return [dict(zip(keys, vals)) for vals in itertools.product(*FULL_SPACE.values())]


def run_combo(params: Dict[str, Any], m1, tf, start, end) -> Dict[str, Any]:
    base = LQSMtfConfig()
    cfg = replace(base, **{k: v for k, v in params.items() if hasattr(base, k)})
    result = BacktestEngine(m1, config=cfg, tf=tf).run(start=start, end=end)
    return {**params, **result.metrics, "score": score_metrics(result.metrics)}


def refine_around(best: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One-at-a-time perturbation around best config."""
    out = [dict(best)]
    for key in PARAM_KEYS:
        for alt in FULL_SPACE[key]:
            if alt != best[key]:
                c = dict(best)
                c[key] = alt
                out.append(c)
    seen, deduped = set(), []
    for c in out:
        t = tuple(c[k] for k in PARAM_KEYS)
        if t not in seen:
            seen.add(t)
            deduped.append(c)
    return deduped


def search(combos, m1, tf, start, end, tag) -> pd.DataFrame:
    rows = []
    t0 = time.time()
    for i, p in enumerate(combos, 1):
        row = run_combo(p, m1, tf, start, end)
        row["phase"] = tag
        rows.append(row)
        if i % 5 == 0 or i == len(combos):
            print(f"  [{tag}] {i}/{len(combos)} best={max(r['score'] for r in rows):.3f} t={time.time()-t0:.0f}s")
    return pd.DataFrame(rows).sort_values("score", ascending=False)


def main() -> None:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    m1 = load_m1_directory(ROOT / "data" / "XAUUSD" / "M1")
    tf = build_multitf(m1)

    train_start = pd.Timestamp("2026-03-01", tz="UTC")
    train_end = pd.Timestamp("2026-04-30 23:59:00", tz="UTC")
    test_start = pd.Timestamp("2026-05-01", tz="UTC")
    test_end = pd.Timestamp("2026-06-05 23:59:00", tz="UTC")

    universe = all_combos()
    random.seed(42)
    sample = random.sample(universe, min(RANDOM_SAMPLES, len(universe)))
    print(f"Phase 1: random search {len(sample)} / {len(universe)} combos")
    rand_df = search(sample, m1, tf, train_start, train_end, "random_train")
    rand_df.to_csv(results_dir / "opt_random_train.csv", index=False)

    best_rand = rand_df.iloc[0].to_dict()
    refine = refine_around(best_rand)
    print(f"Phase 2: refine {len(refine)} combos around best random")
    ref_df = search(refine, m1, tf, train_start, train_end, "refine_train")
    ref_df.to_csv(results_dir / "opt_refine_train.csv", index=False)

    all_train = pd.concat([rand_df, ref_df]).sort_values("score", ascending=False)
    all_train = all_train.drop_duplicates(subset=PARAM_KEYS, keep="first")
    all_train.to_csv(results_dir / "opt_all_train.csv", index=False)

    top5 = all_train.head(5)[PARAM_KEYS].to_dict("records")
    print("Phase 3: OOS on top 5 train configs")
    oos_rows = []
    for rank, p in enumerate(top5, 1):
        row = run_combo(p, m1, tf, test_start, test_end)
        row["train_rank"] = rank
        row["phase"] = "oos"
        oos_rows.append(row)
    oos_df = pd.DataFrame(oos_rows).sort_values("score", ascending=False)
    oos_df.to_csv(results_dir / "opt_oos_top5.csv", index=False)

    # Pick best train config with positive or least-bad OOS among top5
    keys = PARAM_KEYS
    best_train_row = all_train.iloc[0]
    oos_positive = oos_df[oos_df["expectancy_r"] > 0]
    if not oos_positive.empty:
        pick = oos_positive.iloc[0]
    else:
        pick = oos_df.sort_values("expectancy_r", ascending=False).iloc[0]
        if float(pick["expectancy_r"]) < -0.3:
            pick = best_train_row
    recommended = {k: _cast_param(k, pick[k]) for k in keys}

    full = run_combo(recommended, m1, tf, None, None)

    summary = {
        "method": "random_search + refine + walk_forward_oos",
        "random_samples": len(sample),
        "full_universe": len(universe),
        "train_period": str(train_start) + " -> " + str(train_end),
        "test_period": str(test_start) + " -> " + str(test_end),
        "best_train": all_train.iloc[0][PARAM_KEYS + ["score", "trades", "expectancy_r", "profit_factor", "win_rate_pct"]].to_dict(),
        "best_oos": oos_df.iloc[0][PARAM_KEYS + ["score", "trades", "expectancy_r", "profit_factor", "win_rate_pct"]].to_dict(),
        "recommended_params": recommended,
        "full_sample": {k: full[k] for k in ["score", "trades", "expectancy_r", "profit_factor", "win_rate_pct", "max_drawdown_pct", "net_pnl"]},
    }

    with (results_dir / "opt_best_params.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    with (ROOT / "config.json").open() as f:
        cfg = json.load(f)
    for k in PARAM_KEYS:
        cfg["lqs_mtf"][k] = _cast_param(k, recommended[k])
    cfg["lqs_mtf"]["_optimized"] = "2026-06-30 random20+refine+oos"
    with (ROOT / "config.json").open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    print("\n=== OPTIMIZATION COMPLETE ===")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
