from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.config import CANDIDATE_PAIRS
from engine.spread import SpreadError, align_closes, build_spread
from engine.statistics import (
    adf_pvalue,
    cointegration_pvalue,
    halflife_hours,
    pearson_correlation,
)


@dataclass
class SelectionResult:
    pair_label: str
    category: str
    correlation: float
    coint_pvalue: float
    adf_pvalue_full: float
    adf_pvalue_w1: float | None
    adf_pvalue_w2: float | None
    halflife_h: float
    hedge_ratio: float
    selected: bool
    reject_reasons: list[str] = field(default_factory=list)


def _effective_adf_threshold(params: dict[str, Any]) -> float:
    alpha = float(params["selection"]["adf_pvalue_max"])
    if params["selection"]["bonferroni_correction"]:
        alpha = alpha / max(len(CANDIDATE_PAIRS), 1)
    return alpha


def _two_window_adf(spread: pd.Series) -> tuple[float, float]:
    midpoint = len(spread) // 2
    w1 = spread.iloc[:midpoint]
    w2 = spread.iloc[midpoint:]
    return adf_pvalue(w1), adf_pvalue(w2)


def evaluate_selection(
    pair_label: str,
    category: str,
    structural_a: pd.DataFrame,
    structural_b: pd.DataFrame,
    params: dict[str, Any],
    *,
    bar_hours: float = 4.0,
) -> SelectionResult:
    reject: list[str] = []
    selection = params["selection"]

    aligned = align_closes(structural_a, structural_b)
    spread, beta = build_spread(aligned)
    corr = pearson_correlation(aligned["log_a"], aligned["log_b"])
    corr_for_filter = abs(corr) if selection.get("correlation_use_abs", False) else corr
    coint_p = cointegration_pvalue(aligned["log_a"], aligned["log_b"])
    adf_full = adf_pvalue(spread)
    adf_w1: float | None = None
    adf_w2: float | None = None

    if selection["require_two_window_validation"]:
        adf_w1, adf_w2 = _two_window_adf(spread)

    hl_h = halflife_hours(spread, bar_hours)
    adf_threshold = _effective_adf_threshold(params)
    corr_threshold = float(selection["correlation_prefilter"])

    if corr_for_filter < corr_threshold:
        corr_label = "abs_corr" if selection.get("correlation_use_abs", False) else "corr"
        reject.append(f"{corr_label}={corr_for_filter:.3f}<{corr_threshold}")
    if selection.get("require_cointegration", True) and coint_p > adf_threshold:
        reject.append(f"coint_p={coint_p:.4f}>{adf_threshold:.4f}")
    if adf_full > adf_threshold:
        reject.append(f"adf_full={adf_full:.4f}>{adf_threshold:.4f}")
    if selection["require_two_window_validation"]:
        if adf_w1 is not None and adf_w1 > adf_threshold:
            reject.append(f"adf_w1={adf_w1:.4f}>{adf_threshold:.4f}")
        if adf_w2 is not None and adf_w2 > adf_threshold:
            reject.append(f"adf_w2={adf_w2:.4f}>{adf_threshold:.4f}")
    if hl_h < float(selection["halflife_min_hours"]):
        reject.append(f"halflife={hl_h:.1f}h<{selection['halflife_min_hours']}")
    if hl_h > float(selection["halflife_max_hours"]):
        reject.append(f"halflife={hl_h:.1f}h>{selection['halflife_max_hours']}")
    if not math.isfinite(hl_h):
        reject.append("halflife=inf")

    return SelectionResult(
        pair_label=pair_label,
        category=category,
        correlation=corr,
        coint_pvalue=coint_p,
        adf_pvalue_full=adf_full,
        adf_pvalue_w1=adf_w1,
        adf_pvalue_w2=adf_w2,
        halflife_h=hl_h,
        hedge_ratio=beta,
        selected=len(reject) == 0,
        reject_reasons=reject,
    )


def safe_evaluate_selection(
    pair_label: str,
    category: str,
    structural_a: pd.DataFrame,
    structural_b: pd.DataFrame,
    params: dict[str, Any],
    *,
    bar_hours: float = 4.0,
) -> SelectionResult:
    try:
        return evaluate_selection(
            pair_label,
            category,
            structural_a,
            structural_b,
            params,
            bar_hours=bar_hours,
        )
    except (SpreadError, ValueError) as exc:
        return SelectionResult(
            pair_label=pair_label,
            category=category,
            correlation=float("nan"),
            coint_pvalue=float("nan"),
            adf_pvalue_full=float("nan"),
            adf_pvalue_w1=None,
            adf_pvalue_w2=None,
            halflife_h=float("inf"),
            hedge_ratio=float("nan"),
            selected=False,
            reject_reasons=[str(exc)],
        )
