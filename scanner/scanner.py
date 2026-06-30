from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from core.config import CANDIDATE_PAIRS, AccountProfile
from core.logging_setup import setup_logging
from core.symbols import ResolvedPair, resolve_pair
from scanner.cache import cache_file, save_bars
from scanner.data_fetch import BarSeries, DataFetchError, fetch_bars, overlap_bars
from scanner.timeframes import structural_timeframe, trigger_timeframe_for_category


LOGGER = setup_logging("statarb.scanner")


@dataclass(frozen=True)
class LegScanResult:
    canonical: str
    broker_symbol: str
    structural: BarSeries
    trigger: BarSeries
    structural_cache: Path
    trigger_cache: Path


@dataclass(frozen=True)
class PairScanResult:
    index: int
    pair_label: str
    category: str
    leg_a: LegScanResult
    leg_b: LegScanResult
    structural_overlap: int
    trigger_overlap: int
    trigger_timeframe: str

    @property
    def ok(self) -> bool:
        return (
            self.leg_a.structural.ok
            and self.leg_b.structural.ok
            and self.leg_a.trigger.ok
            and self.leg_b.trigger.ok
            and self.structural_overlap >= min(self.leg_a.structural.minimum_required, self.leg_b.structural.minimum_required)
            and self.trigger_overlap >= min(self.leg_a.trigger.minimum_required, self.leg_b.trigger.minimum_required)
        )


def _scan_leg(
    mt5: ModuleType,
    profile: AccountProfile,
    canonical: str,
    broker_symbol: str,
    structural_tf: str,
    trigger_tf: str,
    structural_days: int,
    trigger_days: int,
) -> LegScanResult:
    structural = fetch_bars(mt5, broker_symbol, structural_tf, structural_days)
    trigger = fetch_bars(mt5, broker_symbol, trigger_tf, trigger_days)

    structural_path = cache_file(profile.name, broker_symbol, structural_tf)
    trigger_path = cache_file(profile.name, broker_symbol, trigger_tf)
    save_bars(structural.bars, structural_path)
    save_bars(trigger.bars, trigger_path)

    LOGGER.info(
        "Storico scaricato profilo=%s symbol=%s structural=%s(%s) trigger=%s(%s)",
        profile.name,
        broker_symbol,
        structural_tf,
        structural.count,
        trigger_tf,
        trigger.count,
    )

    return LegScanResult(
        canonical=canonical,
        broker_symbol=broker_symbol,
        structural=structural,
        trigger=trigger,
        structural_cache=structural_path,
        trigger_cache=trigger_path,
    )


def scan_pair(
    mt5: ModuleType,
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    pair_index: int,
    leg_a: str,
    leg_b: str,
    category: str,
) -> PairScanResult:
    resolved = resolve_pair(leg_a, leg_b, profile, accounts, mt5)
    structural_tf = structural_timeframe(params)
    trigger_tf = trigger_timeframe_for_category(category, params)
    structural_days = int(params["data"]["structural_lookback_days"])
    trigger_days = int(params["data"]["trigger_lookback_days"])

    leg_a_result = _scan_leg(
        mt5,
        profile,
        resolved.canonical_a,
        resolved.broker_a,
        structural_tf,
        trigger_tf,
        structural_days,
        trigger_days,
    )
    leg_b_result = _scan_leg(
        mt5,
        profile,
        resolved.canonical_b,
        resolved.broker_b,
        structural_tf,
        trigger_tf,
        structural_days,
        trigger_days,
    )

    structural_overlap, _, _ = overlap_bars(leg_a_result.structural, leg_b_result.structural)
    trigger_overlap, _, _ = overlap_bars(leg_a_result.trigger, leg_b_result.trigger)

    return PairScanResult(
        index=pair_index,
        pair_label=f"{leg_a}/{leg_b}",
        category=category,
        leg_a=leg_a_result,
        leg_b=leg_b_result,
        structural_overlap=structural_overlap,
        trigger_overlap=trigger_overlap,
        trigger_timeframe=trigger_tf,
    )


def scan_all_pairs(
    mt5: ModuleType,
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
) -> list[PairScanResult]:
    results: list[PairScanResult] = []
    for candidate in CANDIDATE_PAIRS:
        try:
            results.append(
                scan_pair(
                    mt5,
                    profile,
                    accounts,
                    params,
                    candidate.index,
                    candidate.leg_a,
                    candidate.leg_b,
                    candidate.category,
                )
            )
        except (DataFetchError, Exception) as exc:  # noqa: BLE001 - collect per-pair failures
            LOGGER.warning(
                "Coppia scartata in scan dati idx=%s pair=%s/%s motivo=%s",
                candidate.index,
                candidate.leg_a,
                candidate.leg_b,
                exc,
            )
    return results
