from __future__ import annotations

from typing import Any

import pandas as pd

from core.config import AccountProfile
from scanner.cache import cache_file, load_bars
from scanner.timeframes import structural_timeframe, trigger_timeframe_for_category


class CacheLoadError(FileNotFoundError):
    """Raised when Modulo 2 cache files are missing."""


def broker_symbol(profile_name: str, canonical: str, accounts: dict[str, Any]) -> str:
    symbol = accounts.get("symbol_map", {}).get(profile_name, {}).get(canonical, "")
    if not symbol:
        raise CacheLoadError(f"symbol_map mancante per {profile_name}/{canonical}")
    return symbol


def load_cached_leg(
    profile_name: str,
    broker: str,
    timeframe: str,
) -> pd.DataFrame:
    path = cache_file(profile_name, broker, timeframe)
    if not path.exists():
        raise CacheLoadError(f"cache assente: {path}")
    return load_bars(path)


def load_cached_pair(
    profile: AccountProfile,
    accounts: dict[str, Any],
    params: dict[str, Any],
    leg_a: str,
    leg_b: str,
    category: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    structural_tf = structural_timeframe(params)
    trigger_tf = trigger_timeframe_for_category(category, params)
    broker_a = broker_symbol(profile.name, leg_a, accounts)
    broker_b = broker_symbol(profile.name, leg_b, accounts)

    structural_a = load_cached_leg(profile.name, broker_a, structural_tf)
    structural_b = load_cached_leg(profile.name, broker_b, structural_tf)
    trigger_a = load_cached_leg(profile.name, broker_a, trigger_tf)
    trigger_b = load_cached_leg(profile.name, broker_b, trigger_tf)
    return structural_a, structural_b, trigger_a, trigger_b, broker_a, broker_b
