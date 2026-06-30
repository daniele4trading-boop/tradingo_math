from __future__ import annotations

from types import ModuleType

from core.config import CANDIDATE_PAIRS, AccountProfile, MAGIC_MAX, MAGIC_MIN
from core.mt5_connection import Mt5Session
from risk.models import PairExposure, PortfolioSnapshot


def _is_statarb_magic(magic: int) -> bool:
    return MAGIC_MIN <= magic <= MAGIC_MAX


def _open_magics(mt5: ModuleType) -> set[int]:
    magics: set[int] = set()
    raw = mt5.positions_get()
    if raw is None:
        return magics
    for item in raw:
        magic = int(getattr(item, "magic", 0))
        if _is_statarb_magic(magic):
            magics.add(magic)
    return magics


def scan_portfolio(
    leg_a_profile: AccountProfile,
    leg_b_profile: AccountProfile,
) -> PortfolioSnapshot:
    with Mt5Session(leg_a_profile) as mt5_a:
        magics_a = _open_magics(mt5_a)
    with Mt5Session(leg_b_profile) as mt5_b:
        magics_b = _open_magics(mt5_b)

    exposures: list[PairExposure] = []
    for candidate in CANDIDATE_PAIRS:
        leg_a_open = candidate.magic_a in magics_a
        leg_b_open = candidate.magic_b in magics_b
        if leg_a_open or leg_b_open:
            exposures.append(
                PairExposure(
                    candidate=candidate,
                    leg_a_open=leg_a_open,
                    leg_b_open=leg_b_open,
                )
            )
    return PortfolioSnapshot(exposures=exposures)


def portfolio_from_magics(
    magics_a: set[int],
    magics_b: set[int],
) -> PortfolioSnapshot:
    exposures: list[PairExposure] = []
    for candidate in CANDIDATE_PAIRS:
        leg_a_open = candidate.magic_a in magics_a
        leg_b_open = candidate.magic_b in magics_b
        if leg_a_open or leg_b_open:
            exposures.append(
                PairExposure(
                    candidate=candidate,
                    leg_a_open=leg_a_open,
                    leg_b_open=leg_b_open,
                )
            )
    return PortfolioSnapshot(exposures=exposures)
