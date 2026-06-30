"""LQS-MTF strategy: Liquidity sweep + BOS confirmation + 50% / emission entry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd

from strategies.structure import (
    LiquidityLevel,
    compute_atr,
    detect_bos_after,
    detect_sweep,
    displacement_leg,
    emission_zone,
    equal_levels,
    find_fvg,
    fractal_swings,
    in_session,
    midpoint_zone,
    round_gold_price,
)


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class LQSProfile(str, Enum):
    """3 profili allineati alla regola dei 2 gradini (video SMC)."""

    H4_M15 = "H4_M15"  # Liquidità H4 → conferma M15 (swing)
    H1_M15 = "H1_M15"  # Liquidità H1 → conferma M15 (intraday)
    H1_M5 = "H1_M5"    # Liquidità H1 → conferma M5  (scalping/intraday rapido)


PROFILE_SPECS: Dict[LQSProfile, Dict[str, object]] = {
    LQSProfile.H4_M15: {
        "liquidity_tf": "H4",
        "confirm_tf": "M15",
        "context_tf": "H4",
        "liquidity_lookback": 60,
        "max_setup_age_bars": 4,
        "label": "H4 sweep → M15 BOS",
    },
    LQSProfile.H1_M15: {
        "liquidity_tf": "H1",
        "confirm_tf": "M15",
        "context_tf": "H4",
        "liquidity_lookback": 120,
        "max_setup_age_bars": 8,
        "label": "H1 sweep → M15 BOS",
    },
    LQSProfile.H1_M5: {
        "liquidity_tf": "H1",
        "confirm_tf": "M5",
        "context_tf": "H4",
        "liquidity_lookback": 120,
        "max_setup_age_bars": 8,
        "label": "H1 sweep → M5 BOS",
    },
}


@dataclass
class LQSMtfConfig:
    profile: LQSProfile = LQSProfile.H1_M15
    fractal_left: int = 2
    fractal_right: int = 2
    atr_period: int = 14
    h4_range_lookback: int = 50
    h4_supply_pct: float = 0.80
    h4_demand_pct: float = 0.20
    equal_highs_tolerance_atr: float = 0.5
    sweep_atr_mult: float = 0.3
    impulsive_body_ratio: float = 0.55
    bos_accept_bars: int = 1
    min_rr: float = 1.5
    limit_expire_bars_m5: int = 12
    cooldown_bars_m5: int = 6
    price_round_step: float = 0.50
    sl_atr_buffer_mult: float = 0.25
    spread_points: int = 65
    point_size: float = 0.01
    broker_utc_offset_hours: int = 2
    session_filter: bool = False

    @property
    def spec(self) -> Dict[str, object]:
        return PROFILE_SPECS[self.profile]

    @property
    def liquidity_tf(self) -> str:
        return str(self.spec["liquidity_tf"])

    @property
    def confirm_tf(self) -> str:
        return str(self.spec["confirm_tf"])

    @property
    def liquidity_lookback(self) -> int:
        return int(self.spec["liquidity_lookback"])

    @property
    def max_setup_age_bars(self) -> int:
        return int(self.spec["max_setup_age_bars"])


@dataclass
class SetupSignal:
    direction: TradeDirection
    signal_time: pd.Timestamp
    entry_low: float
    entry_high: float
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    rr_tp1: float
    reason: str
    sweep_level: float
    sweep_extreme: float
    profile: str


@dataclass
class _SweepEvent:
    direction: TradeDirection
    level: LiquidityLevel
    sweep_time: pd.Timestamp
    sweep_extreme: float
    liq_index: int


class LQSMtfStrategy:
    """Stateful scanner multi-profilo. Esecuzione sempre su M5."""

    def __init__(self, config: Optional[LQSMtfConfig] = None):
        self.cfg = config or LQSMtfConfig()
        self._recent_sweeps: List[_SweepEvent] = []
        self._last_signal_time: Optional[pd.Timestamp] = None
        self._cooldown_until: Optional[pd.Timestamp] = None
        self._bos_cache: Dict[Tuple[pd.Timestamp, int, str], Optional[Tuple[pd.Timestamp, float, int]]] = {}

    def register_liquidity_bar(self, df_context: pd.DataFrame, df_liquidity: pd.DataFrame) -> None:
        if len(df_liquidity) < self.cfg.atr_period + 10:
            return
        self._register_sweeps(df_liquidity)
        self._prune_sweeps(df_liquidity)

    def register_h1_bar(self, df_h4: pd.DataFrame, df_h1: pd.DataFrame) -> None:
        """Backward compat."""
        self.register_liquidity_bar(df_h4, df_h1)

    def try_signal(
        self,
        m5_time: pd.Timestamp,
        df_context: pd.DataFrame,
        df_liquidity: pd.DataFrame,
        df_confirm: pd.DataFrame,
        df_m5: Optional[pd.DataFrame] = None,
    ) -> Optional[SetupSignal]:
        if self.cfg.session_filter and not in_session(
            m5_time, (9, 0), (15, 0), self.cfg.broker_utc_offset_hours
        ):
            return None
        if self._cooldown_until is not None and m5_time < self._cooldown_until:
            return None
        if len(df_context) < self.cfg.h4_range_lookback + 5:
            return None
        min_confirm = 5 if self.cfg.confirm_tf == "M15" else 8
        if len(df_confirm) < min_confirm:
            return None

        for sweep in reversed(self._recent_sweeps):
            signal = self._try_confirm(sweep, df_context, df_liquidity, df_confirm, m5_time)
            if signal is not None:
                if self._last_signal_time == signal.signal_time:
                    return None
                self._last_signal_time = signal.signal_time
                return signal
        return None

    def register_sl_hit(self, hit_time: pd.Timestamp) -> None:
        self._cooldown_until = hit_time + pd.Timedelta(minutes=5 * self.cfg.cooldown_bars_m5)

    def _register_sweeps(self, df_liq: pd.DataFrame) -> None:
        atr_series = compute_atr(df_liq, self.cfg.atr_period)
        atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
        if atr <= 0:
            return

        highs, lows = fractal_swings(df_liq, self.cfg.fractal_left, self.cfg.fractal_right)
        lookback_start = max(0, len(df_liq) - self.cfg.liquidity_lookback)
        recent_highs = [s for s in highs if s.index >= lookback_start]
        recent_lows = [s for s in lows if s.index >= lookback_start]
        price = float(df_liq["close"].iloc[-1])
        bar = df_liq.iloc[-1]
        liq_idx = len(df_liq) - 1

        for level in equal_levels(
            recent_highs, atr, price, self.cfg.equal_highs_tolerance_atr, min_touches=1
        ):
            if not self._level_already_swept(level, TradeDirection.SHORT) and detect_sweep(
                bar, level, atr, self.cfg.sweep_atr_mult, self.cfg.impulsive_body_ratio
            ):
                self._recent_sweeps.append(
                    _SweepEvent(
                        TradeDirection.SHORT, level, pd.Timestamp(bar["time"]),
                        float(bar["high"]), liq_idx,
                    )
                )

        for level in equal_levels(
            recent_lows, atr, price, self.cfg.equal_highs_tolerance_atr, min_touches=1
        ):
            if not self._level_already_swept(level, TradeDirection.LONG) and detect_sweep(
                bar, level, atr, self.cfg.sweep_atr_mult, self.cfg.impulsive_body_ratio
            ):
                self._recent_sweeps.append(
                    _SweepEvent(
                        TradeDirection.LONG, level, pd.Timestamp(bar["time"]),
                        float(bar["low"]), liq_idx,
                    )
                )

        if recent_highs:
            self._maybe_add_swing_sweep(
                df_liq, recent_highs[-1].price, "high", atr, TradeDirection.SHORT, liq_idx
            )
        if recent_lows:
            self._maybe_add_swing_sweep(
                df_liq, recent_lows[-1].price, "low", atr, TradeDirection.LONG, liq_idx
            )

    def _maybe_add_swing_sweep(
        self, df_liq: pd.DataFrame, price: float, kind: str, atr: float,
        direction: TradeDirection, liq_index: int,
    ) -> None:
        level = LiquidityLevel(
            price=price, kind=kind, touches=1,
            first_time=pd.Timestamp(df_liq["time"].iloc[-1]),
            last_time=pd.Timestamp(df_liq["time"].iloc[-1]),
        )
        if self._level_already_swept(level, direction):
            return
        bar = df_liq.iloc[-1]
        if detect_sweep(bar, level, atr, self.cfg.sweep_atr_mult, self.cfg.impulsive_body_ratio):
            self._recent_sweeps.append(
                _SweepEvent(
                    direction, level, pd.Timestamp(bar["time"]),
                    float(bar["high"] if direction == TradeDirection.SHORT else bar["low"]),
                    liq_index,
                )
            )

    def _level_already_swept(self, level: LiquidityLevel, direction: TradeDirection) -> bool:
        for ev in self._recent_sweeps:
            if ev.direction == direction and abs(ev.level.price - level.price) < 1e-6:
                return True
        return False

    def _prune_sweeps(self, df_liq: pd.DataFrame) -> None:
        if not self._recent_sweeps:
            return
        cutoff = len(df_liq) - 1 - self.cfg.max_setup_age_bars
        self._recent_sweeps = [s for s in self._recent_sweeps if s.liq_index >= cutoff]

    def _context_allows(self, direction: TradeDirection, df_context: pd.DataFrame) -> bool:
        sub = df_context.iloc[-self.cfg.h4_range_lookback :]
        rng_low = float(sub["low"].min())
        rng_high = float(sub["high"].max())
        rng = rng_high - rng_low
        if rng <= 0:
            return True
        close = float(df_context["close"].iloc[-1])
        top = rng_low + self.cfg.h4_supply_pct * rng
        bottom = rng_low + self.cfg.h4_demand_pct * rng
        if direction == TradeDirection.LONG and close >= top:
            return False
        if direction == TradeDirection.SHORT and close <= bottom:
            return False
        return True

    def _try_confirm(
        self,
        sweep: _SweepEvent,
        df_context: pd.DataFrame,
        df_liquidity: pd.DataFrame,
        df_confirm: pd.DataFrame,
        m5_time: pd.Timestamp,
    ) -> Optional[SetupSignal]:
        direction = "SHORT" if sweep.direction == TradeDirection.SHORT else "LONG"
        if not self._context_allows(sweep.direction, df_context):
            return None

        confirm_after = df_confirm[df_confirm["time"] >= sweep.sweep_time]
        if len(confirm_after) < 5:
            return None

        cache_key = (sweep.sweep_time, len(confirm_after), direction)
        if cache_key not in self._bos_cache:
            self._bos_cache[cache_key] = detect_bos_after(confirm_after, direction, start_idx=3)
        bos = self._bos_cache[cache_key]
        if bos is None:
            return None
        bos_time, _, bos_idx = bos
        if bos_time > m5_time:
            return None

        highs, lows = fractal_swings(confirm_after, self.cfg.fractal_left, self.cfg.fractal_right)

        leg_low, leg_high = displacement_leg(confirm_after, 0, bos_idx, direction)
        if leg_high <= leg_low:
            return None
        mid_50 = (leg_low + leg_high) / 2.0
        zone_50 = (mid_50 - (leg_high - leg_low) * 0.05, mid_50 + (leg_high - leg_low) * 0.05)
        emit = emission_zone(confirm_after, 0, bos_idx, direction)
        entry_low, entry_high = midpoint_zone(zone_50, emit)
        entry_price = round_gold_price((entry_low + entry_high) / 2.0, self.cfg.price_round_step)

        atr_liq = float(compute_atr(df_liquidity, self.cfg.atr_period).iloc[-1])
        if direction == "SHORT":
            sl = sweep.sweep_extreme + atr_liq * self.cfg.sl_atr_buffer_mult
            risk = sl - entry_price
            if risk <= 0:
                return None
            tp1 = entry_price - risk * 1.5
            tp2 = sweep.level.price - risk * 0.5
            fvg = find_fvg(confirm_after.iloc[: bos_idx + 1], direction)
            if fvg:
                tp2 = (fvg[0] + fvg[1]) / 2.0
            tp3 = entry_price - risk * 3.0
            swing_lows = [s.price for s in lows if s.index <= bos_idx]
            if swing_lows:
                tp1 = min(tp1, min(swing_lows))
        else:
            sl = sweep.sweep_extreme - atr_liq * self.cfg.sl_atr_buffer_mult
            risk = entry_price - sl
            if risk <= 0:
                return None
            tp1 = entry_price + risk * 1.5
            tp2 = sweep.level.price + risk * 0.5
            fvg = find_fvg(confirm_after.iloc[: bos_idx + 1], direction)
            if fvg:
                tp2 = (fvg[0] + fvg[1]) / 2.0
            tp3 = entry_price + risk * 3.0
            swing_highs = [s.price for s in highs if s.index <= bos_idx]
            if swing_highs:
                tp1 = max(tp1, max(swing_highs))

        reward = abs(entry_price - tp1)
        rr = reward / risk if risk > 0 else 0.0
        if rr < self.cfg.min_rr:
            return None

        prof = self.cfg.profile.value
        return SetupSignal(
            direction=sweep.direction,
            signal_time=bos_time,
            entry_low=entry_low,
            entry_high=entry_high,
            entry_price=entry_price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            rr_tp1=rr,
            reason=f"[{prof}] {direction} sweep@{sweep.level.price:.2f} bos@{bos_time}",
            sweep_level=sweep.level.price,
            sweep_extreme=sweep.sweep_extreme,
            profile=prof,
        )

    @classmethod
    def from_json_config(cls, cfg: Dict) -> "LQSMtfStrategy":
        section = dict(cfg.get("lqs_mtf", {}))
        if "profile" in section and isinstance(section["profile"], str):
            section["profile"] = LQSProfile(section["profile"])
        fields = LQSMtfConfig.__dataclass_fields__
        return cls(LQSMtfConfig(**{k: v for k, v in section.items() if k in fields}))
