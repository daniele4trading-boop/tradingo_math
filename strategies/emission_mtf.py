"""Emission MTF strategy: dominance + B2S/S2B emission zones (video DO7kdX-dByE)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd

from strategies.structure import (
    compute_atr,
    detect_engulfing,
    detect_evening_star,
    detect_morning_star,
    displacement_leg,
    emission_sl_from_candle,
    emission_zone,
    find_emission_candle_index,
    fractal_swings,
    in_session,
    price_in_fib_extension,
    price_in_zone,
    round_gold_price,
    round_number_theory,
    trend_from_swings,
)


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class EmissionStyle(str, Enum):
    SCALPING = "SCALPING"
    INTRADAY = "INTRADAY"


class EntryMethod(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class EmissionProfile(str, Enum):
    SCALPING_LIMIT = "SCALPING_LIMIT"
    SCALPING_MARKET = "SCALPING_MARKET"
    INTRADAY_LIMIT = "INTRADAY_LIMIT"
    INTRADAY_MARKET = "INTRADAY_MARKET"


STYLE_SPECS: Dict[EmissionStyle, Dict[str, object]] = {
    EmissionStyle.SCALPING: {
        "context_outer": "H4",
        "context_inner": "H1",
        "operational_tf": "M5",
        "exec_tf": "M5",
        "exec_minutes": 5,
        "limit_expire_bars": 24,
        "cooldown_bars": 6,
        "max_setup_age_bars": 18,
        "label": "Scalping H4→H1 → M5",
    },
    EmissionStyle.INTRADAY: {
        "context_outer": "D1",
        "context_inner": "H4",
        "operational_tf": "H1",
        "exec_tf": "H1",
        "exec_minutes": 60,
        "limit_expire_bars": 12,
        "cooldown_bars": 3,
        "max_setup_age_bars": 8,
        "label": "Intraday D1→H4 → H1",
    },
}


def profile_parts(profile: EmissionProfile) -> Tuple[EmissionStyle, EntryMethod]:
    mapping = {
        EmissionProfile.SCALPING_LIMIT: (EmissionStyle.SCALPING, EntryMethod.LIMIT),
        EmissionProfile.SCALPING_MARKET: (EmissionStyle.SCALPING, EntryMethod.MARKET),
        EmissionProfile.INTRADAY_LIMIT: (EmissionStyle.INTRADAY, EntryMethod.LIMIT),
        EmissionProfile.INTRADAY_MARKET: (EmissionStyle.INTRADAY, EntryMethod.MARKET),
    }
    return mapping[profile]


@dataclass
class EmissionMtfConfig:
    profile: EmissionProfile = EmissionProfile.SCALPING_LIMIT
    fractal_left: int = 2
    fractal_right: int = 2
    atr_period: int = 14
    range_lookback: int = 50
    supply_pct: float = 0.80
    demand_pct: float = 0.20
    bos_accept_bars: int = 1
    min_rr: float = 2.0
    price_round_step: float = 0.50
    sl_atr_buffer_mult: float = 0.15
    spread_points: int = 65
    point_size: float = 0.01
    broker_utc_offset_hours: int = 2
    session_filter: bool = False
    context_filter: bool = True
    dominance_filter: bool = True
    fib_filter: bool = False
    use_number_theory: bool = True
    # discretionary — off by default, refine in optimization
    limit_expire_bars: Optional[int] = None
    cooldown_bars: Optional[int] = None
    max_setup_age_bars: Optional[int] = None
    reverse_signals: bool = False

    @property
    def style(self) -> EmissionStyle:
        return profile_parts(self.profile)[0]

    @property
    def entry_method(self) -> EntryMethod:
        return profile_parts(self.profile)[1]

    @property
    def spec(self) -> Dict[str, object]:
        return STYLE_SPECS[self.style]

    @property
    def context_outer_tf(self) -> str:
        return str(self.spec["context_outer"])

    @property
    def context_inner_tf(self) -> str:
        return str(self.spec["context_inner"])

    @property
    def operational_tf(self) -> str:
        return str(self.spec["operational_tf"])

    @property
    def exec_tf(self) -> str:
        return str(self.spec["exec_tf"])

    @property
    def exec_minutes(self) -> int:
        return int(self.spec["exec_minutes"])

    @property
    def effective_limit_expire_bars(self) -> int:
        if self.limit_expire_bars is not None:
            return self.limit_expire_bars
        return int(self.spec["limit_expire_bars"])

    @property
    def effective_cooldown_bars(self) -> int:
        if self.cooldown_bars is not None:
            return self.cooldown_bars
        return int(self.spec["cooldown_bars"])

    @property
    def effective_max_setup_age_bars(self) -> int:
        if self.max_setup_age_bars is not None:
            return self.max_setup_age_bars
        return int(self.spec["max_setup_age_bars"])


@dataclass
class EmissionSignal:
    direction: TradeDirection
    signal_time: pd.Timestamp
    entry_price: float
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    rr_tp1: float
    reason: str
    profile: str
    entry_type: str  # "limit" | "market"
    setup_id: int


@dataclass
class _EmissionSetup:
    setup_id: int
    direction: TradeDirection
    bos_time: pd.Timestamp
    bos_idx: int
    emit_low: float
    emit_high: float
    emit_idx: int
    op_bar_index: int
    leg_low: float
    leg_high: float
    sl: float
    limit_armed: bool = False
    signaled: bool = False


class EmissionMtfStrategy:
    """Dominance + emission zone strategy on operational TF."""

    def __init__(self, config: Optional[EmissionMtfConfig] = None):
        self.cfg = config or EmissionMtfConfig()
        self._setups: List[_EmissionSetup] = []
        self._next_setup_id = 1
        self._last_op_index = -1
        self._cooldown_until: Optional[pd.Timestamp] = None
        self._used_setup_ids: set = set()

    def has_active_setups(self) -> bool:
        return any(
            s.setup_id not in self._used_setup_ids and not s.signaled for s in self._setups
        )

    def register_operational_bar(
        self,
        df_outer: pd.DataFrame,
        df_inner: pd.DataFrame,
        df_op: pd.DataFrame,
    ) -> None:
        if len(df_op) < self.cfg.atr_period + 10:
            return
        op_idx = len(df_op) - 1
        if op_idx == self._last_op_index:
            return
        self._last_op_index = op_idx
        self._prune_setups(op_idx)
        self._detect_new_setup(df_outer, df_inner, df_op, op_idx)

    def try_signal(
        self,
        exec_time: pd.Timestamp,
        df_outer: pd.DataFrame,
        df_inner: pd.DataFrame,
        df_op: pd.DataFrame,
        df_exec: pd.DataFrame,
    ) -> Optional[EmissionSignal]:
        if self.cfg.session_filter and not in_session(
            exec_time, (9, 0), (20, 0), self.cfg.broker_utc_offset_hours
        ):
            return None
        if self._cooldown_until is not None and exec_time < self._cooldown_until:
            return None
        if len(df_op) < 8 or len(df_exec) < 2:
            return None

        bar = df_exec.iloc[-1]
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        close = float(bar["close"])
        for setup in reversed(self._setups):
            if setup.setup_id in self._used_setup_ids:
                continue
            direction = "SHORT" if setup.direction == TradeDirection.SHORT else "LONG"
            zone = (setup.emit_low, setup.emit_high)
            if self.cfg.fib_filter and not price_in_fib_extension(
                close, setup.leg_low, setup.leg_high, direction
            ):
                continue

            if self.cfg.entry_method == EntryMethod.LIMIT:
                sig = self._try_limit(setup, exec_time, close, bar_low, bar_high, zone, direction)
            else:
                sig = self._try_market(setup, exec_time, bar, bar_low, bar_high, zone, df_op, direction)
            if sig is not None:
                self._used_setup_ids.add(setup.setup_id)
                return sig
        return None

    def register_sl_hit(self, hit_time: pd.Timestamp) -> None:
        self._cooldown_until = hit_time + pd.Timedelta(
            minutes=self.cfg.exec_minutes * self.cfg.effective_cooldown_bars
        )

    def _detect_new_setup(
        self,
        df_outer: pd.DataFrame,
        df_inner: pd.DataFrame,
        df_op: pd.DataFrame,
        op_idx: int,
    ) -> None:
        lookback = 120
        op_win = df_op.iloc[max(0, op_idx - lookback) : op_idx + 1]
        for direction in ("SHORT", "LONG"):
            trade_dir = TradeDirection.SHORT if direction == "SHORT" else TradeDirection.LONG
            if not self._context_allows(trade_dir, df_outer, df_inner):
                continue
            if not self._dominance_allows(trade_dir, op_win):
                continue
            bos = self._bos_on_bar(op_win, len(op_win) - 1, direction)
            if bos is None:
                continue
            bos_time, _, rel_idx = bos
            bos_idx = op_idx - (len(op_win) - 1 - rel_idx)
            if bos_idx != op_idx:
                continue
            if any(s.bos_time == bos_time and s.direction == trade_dir for s in self._setups):
                continue

            emit = emission_zone(df_op, max(0, bos_idx - 30), bos_idx, direction)
            emit_idx = find_emission_candle_index(df_op, bos_idx, direction)
            emit_row = df_op.iloc[emit_idx]
            atr = float(compute_atr(df_op.iloc[max(0, bos_idx - 30) : bos_idx + 1], self.cfg.atr_period).iloc[-1])
            sl = emission_sl_from_candle(emit_row, direction, atr, self.cfg.sl_atr_buffer_mult)
            leg_low, leg_high = displacement_leg(df_op, max(0, bos_idx - 30), bos_idx, direction)
            if leg_high <= leg_low:
                continue

            self._setups.append(
                _EmissionSetup(
                    setup_id=self._next_setup_id,
                    direction=trade_dir,
                    bos_time=bos_time,
                    bos_idx=bos_idx,
                    emit_low=emit[0],
                    emit_high=emit[1],
                    emit_idx=emit_idx,
                    op_bar_index=op_idx,
                    leg_low=leg_low,
                    leg_high=leg_high,
                    sl=sl,
                )
            )
            self._next_setup_id += 1

    def _try_limit(
        self,
        setup: _EmissionSetup,
        exec_time: pd.Timestamp,
        close: float,
        bar_low: float,
        bar_high: float,
        zone: Tuple[float, float],
        direction: str,
    ) -> Optional[EmissionSignal]:
        if not setup.limit_armed:
            if direction == "SHORT" and close < zone[0]:
                setup.limit_armed = True
            elif direction == "LONG" and close > zone[1]:
                setup.limit_armed = True
            else:
                return None
        if setup.signaled:
            return None

        mid = (zone[0] + zone[1]) / 2.0
        entry = round_number_theory(mid) if self.cfg.use_number_theory else round_gold_price(mid, self.cfg.price_round_step)
        sl = setup.sl
        tp1, tp2, tp3, rr = self._targets(entry, sl, direction)
        if rr < self.cfg.min_rr:
            return None

        setup.signaled = True
        prof = self.cfg.profile.value
        emit_label = "B2S" if direction == "SHORT" else "S2B"
        return EmissionSignal(
            direction=setup.direction,
            signal_time=exec_time,
            entry_price=entry,
            entry_low=zone[0],
            entry_high=zone[1],
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            rr_tp1=rr,
            reason=f"[{prof}] {direction} limit@{emit_label} bos@{setup.bos_time}",
            profile=prof,
            entry_type="limit",
            setup_id=setup.setup_id,
        )

    def _try_market(
        self,
        setup: _EmissionSetup,
        exec_time: pd.Timestamp,
        bar: pd.Series,
        bar_low: float,
        bar_high: float,
        zone: Tuple[float, float],
        df_op: pd.DataFrame,
        direction: str,
    ) -> Optional[EmissionSignal]:
        if not price_in_zone(bar_low, bar_high, zone):
            return None
        window = df_op.iloc[max(0, len(df_op) - 3) :]
        if len(window) < 2:
            return None
        pattern = False
        if direction == "SHORT":
            pattern = detect_engulfing(window, "SHORT") or detect_evening_star(window)
        else:
            pattern = detect_engulfing(window, "LONG") or detect_morning_star(window)
        if not pattern or setup.signaled:
            return None

        entry = float(bar["close"])
        sl = setup.sl
        tp1, tp2, tp3, rr = self._targets(entry, sl, direction)
        if rr < self.cfg.min_rr:
            return None

        setup.signaled = True
        prof = self.cfg.profile.value
        emit_label = "B2S" if direction == "SHORT" else "S2B"
        return EmissionSignal(
            direction=setup.direction,
            signal_time=exec_time,
            entry_price=entry,
            entry_low=zone[0],
            entry_high=zone[1],
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            rr_tp1=rr,
            reason=f"[{prof}] {direction} market@{emit_label} bos@{setup.bos_time}",
            profile=prof,
            entry_type="market",
            setup_id=setup.setup_id,
        )

    def _targets(self, entry: float, sl: float, direction: str) -> Tuple[float, float, float, float]:
        risk = abs(entry - sl)
        if risk <= 0:
            return entry, entry, entry, 0.0
        if direction == "SHORT":
            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.0
            tp3 = entry - risk * 4.0
        else:
            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.0
            tp3 = entry + risk * 4.0
        rr = abs(entry - tp1) / risk
        return tp1, tp2, tp3, rr

    def _bos_on_bar(
        self, df_op: pd.DataFrame, op_idx: int, direction: str
    ) -> Optional[Tuple[pd.Timestamp, float, int]]:
        if op_idx < 3:
            return None
        window = df_op.iloc[: op_idx + 1]
        highs, lows = fractal_swings(window, self.cfg.fractal_left, self.cfg.fractal_right)
        bar = df_op.iloc[op_idx]
        if direction == "SHORT":
            recent = [s for s in lows if s.index < op_idx]
            if not recent:
                return None
            level = recent[-1].price
            if float(bar["close"]) < level:
                return pd.Timestamp(bar["time"]), level, op_idx
        else:
            recent = [s for s in highs if s.index < op_idx]
            if not recent:
                return None
            level = recent[-1].price
            if float(bar["close"]) > level:
                return pd.Timestamp(bar["time"]), level, op_idx
        return None

    def _context_allows(
        self,
        direction: TradeDirection,
        df_outer: pd.DataFrame,
        df_inner: pd.DataFrame,
    ) -> bool:
        if not self.cfg.context_filter:
            return True
        for df in (df_outer, df_inner):
            if len(df) < self.cfg.range_lookback + 5:
                continue
            sub = df.iloc[-self.cfg.range_lookback :]
            rng_low = float(sub["low"].min())
            rng_high = float(sub["high"].max())
            rng = rng_high - rng_low
            if rng <= 0:
                continue
            close = float(df["close"].iloc[-1])
            top = rng_low + self.cfg.supply_pct * rng
            bottom = rng_low + self.cfg.demand_pct * rng
            if direction == TradeDirection.LONG and close >= top:
                return False
            if direction == TradeDirection.SHORT and close <= bottom:
                return False
        return True

    def _dominance_allows(self, direction: TradeDirection, df_op: pd.DataFrame) -> bool:
        if not self.cfg.dominance_filter:
            return True
        highs, lows = fractal_swings(df_op, self.cfg.fractal_left, self.cfg.fractal_right)
        trend = trend_from_swings(highs, lows)
        if direction == TradeDirection.LONG and trend == "bearish":
            return False
        if direction == TradeDirection.SHORT and trend == "bullish":
            return False
        return True

    def _prune_setups(self, op_idx: int) -> None:
        cutoff = op_idx - self.cfg.effective_max_setup_age_bars
        self._setups = [s for s in self._setups if s.op_bar_index >= cutoff]

    @classmethod
    def from_json_config(cls, cfg: Dict) -> "EmissionMtfStrategy":
        section = dict(cfg.get("emission_mtf", {}))
        if "profile" in section and isinstance(section["profile"], str):
            section["profile"] = EmissionProfile(section["profile"])
        fields = EmissionMtfConfig.__dataclass_fields__
        return cls(EmissionMtfConfig(**{k: v for k, v in section.items() if k in fields}))
