from dataclasses import dataclass, replace
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Convergenza7Config:
    """Runtime parameters for the CONVERGENZA 7 historical backtest."""

    symbol: str = "XAUUSD"
    source_timeframe: str = "M1"

    atr_period: int = 14
    swing_left: int = 2
    swing_right: int = 2

    h1_structure_swings: int = 3

    m15_lateral_lookback: int = 10
    m15_lateral_atr_threshold: float = 1.5

    structural_level_lookback: int = 50
    structural_level_min_touches: int = 2
    structural_level_tolerance_atr: float = 0.3

    setup_distance_atr: float = 0.5
    retracement_lookback: int = 3

    m1_zone_distance_atr: float = 0.5
    min_rr: float = 2.0
    risk_percent_per_trade: float = 1.0
    min_stop_distance: float = 1e-9

    max_trade_bars: int = 1440
    same_bar_exit_policy: str = "conservative"

    output_trades_csv: str = "convergenza7_trades.csv"
    output_stats_json: str = "convergenza7_stats.json"

    @classmethod
    def from_dict(cls, values: Optional[Dict[str, Any]] = None) -> "Convergenza7Config":
        if not values:
            return cls()
        allowed = {field for field in cls.__dataclass_fields__}
        filtered = {key: value for key, value in values.items() if key in allowed}
        return replace(cls(), **filtered)

