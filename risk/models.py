from __future__ import annotations

from dataclasses import dataclass, field

from core.config import CandidatePair


@dataclass(frozen=True)
class AccountRiskMetrics:
    profile_name: str
    equity: float
    balance: float
    margin: float
    margin_level: float
    daily_loss_pct: float
    drawdown_pct: float


@dataclass(frozen=True)
class PairExposure:
    candidate: CandidatePair
    leg_a_open: bool
    leg_b_open: bool

    @property
    def pair_label(self) -> str:
        return f"{self.candidate.leg_a}/{self.candidate.leg_b}"

    @property
    def fully_hedged(self) -> bool:
        return self.leg_a_open and self.leg_b_open

    @property
    def unhedged(self) -> bool:
        return self.leg_a_open != self.leg_b_open


@dataclass
class PortfolioSnapshot:
    exposures: list[PairExposure] = field(default_factory=list)

    @property
    def open_pairs(self) -> list[PairExposure]:
        return [item for item in self.exposures if item.fully_hedged]

    @property
    def unhedged_pairs(self) -> list[PairExposure]:
        return [item for item in self.exposures if item.unhedged]

    @property
    def open_pair_count(self) -> int:
        return len(self.open_pairs)

    def leg_usage(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for exposure in self.exposures:
            if exposure.leg_a_open:
                counts[exposure.candidate.leg_a] = counts.get(exposure.candidate.leg_a, 0) + 1
            if exposure.leg_b_open:
                counts[exposure.candidate.leg_b] = counts.get(exposure.candidate.leg_b, 0) + 1
        return counts


@dataclass(frozen=True)
class RiskGateResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return "; ".join(self.reasons)
