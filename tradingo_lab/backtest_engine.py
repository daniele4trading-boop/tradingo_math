import argparse
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import Convergenza7Config
from data_loader import TIMEFRAME_MINUTES, load_timeframes
from pattern_detector import detect_trigger_pattern
from risk_manager import (
    OpenTrade,
    build_risk_plan,
    close_trade,
    evaluate_trade_on_bar,
    find_breakeven_trigger,
)
from stats_reporter import write_report
from structure_detector import (
    SetupSignal,
    determine_bias,
    detect_liquidity_sweep,
    detect_structural_zone_setup,
    identify_horizontal_levels,
    is_lateral_market,
    latest_atr,
)


class Convergenza7BacktestEngine:
    """Walk-forward M1 backtester for the CONVERGENZA 7 framework."""

    def __init__(self, timeframes: Dict[str, List[Dict[str, Any]]], config: Optional[Convergenza7Config] = None):
        self.config = config or Convergenza7Config()
        self.timeframes = {key.upper(): value for key, value in timeframes.items()}
        for timeframe in ("M1", "M5", "M15", "H1"):
            if timeframe not in self.timeframes:
                raise ValueError(f"missing timeframe: {timeframe}")
        self.open_trade: Optional[OpenTrade] = None
        self.trades: List[Dict[str, Any]] = []

    @staticmethod
    def _advance_completed_index(
        bars: List[Dict[str, Any]],
        current_index: int,
        current_close_time: Any,
        timeframe: str,
    ) -> int:
        duration = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        while current_index < len(bars) and bars[current_index]["time"] + duration <= current_close_time:
            current_index += 1
        return current_index

    @staticmethod
    def _recent(bars: List[Dict[str, Any]], end_index: int, length: int) -> List[Dict[str, Any]]:
        start = max(0, end_index - length)
        return bars[start:end_index]

    def _histories(
        self,
        indices: Dict[str, int],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        h1_history = self._recent(self.timeframes["H1"], indices["H1"], 300)
        m15_history = self._recent(self.timeframes["M15"], indices["M15"], 300)
        m5_history = self._recent(self.timeframes["M5"], indices["M5"], 120)
        return h1_history, m15_history, m5_history

    def _setup_is_on_m1_zone(self, setup: SetupSignal, m1_bar: Dict[str, Any]) -> bool:
        tolerance = setup.zone_atr * self.config.m1_zone_distance_atr
        return (
            float(m1_bar["low"]) - tolerance <= setup.level_price <= float(m1_bar["high"]) + tolerance
            or abs(float(m1_bar["close"]) - setup.level_price) <= tolerance
        )

    def _find_setup(
        self,
        direction: str,
        m15_history: List[Dict[str, Any]],
        m5_history: List[Dict[str, Any]],
        levels: List[Any],
        atr_m15: float,
    ) -> Optional[SetupSignal]:
        setup = detect_structural_zone_setup(m15_history, direction, levels, atr_m15, self.config)
        if setup is not None:
            return setup
        return detect_liquidity_sweep(m5_history, m15_history, direction, atr_m15, self.config)

    def _try_open_trade(
        self,
        m1_history: List[Dict[str, Any]],
        h1_history: List[Dict[str, Any]],
        m15_history: List[Dict[str, Any]],
        m5_history: List[Dict[str, Any]],
        current_close_time: Any,
    ) -> None:
        cfg = self.config
        if len(m1_history) < 3 or len(h1_history) < 20 or len(m15_history) < cfg.m15_lateral_lookback:
            return

        direction = determine_bias(
            h1_history,
            min_swings=cfg.h1_structure_swings,
            left=cfg.swing_left,
            right=cfg.swing_right,
        )
        if direction == "NONE":
            return

        atr_m15 = latest_atr(m15_history, cfg.atr_period)
        if is_lateral_market(
            m15_history,
            atr_m15,
            lookback=cfg.m15_lateral_lookback,
            atr_threshold=cfg.m15_lateral_atr_threshold,
        ):
            return

        levels = identify_horizontal_levels(
            m15_history,
            atr_m15,
            lookback=cfg.structural_level_lookback,
            min_touches=cfg.structural_level_min_touches,
            tolerance_atr=cfg.structural_level_tolerance_atr,
        )
        if not levels:
            return

        setup = self._find_setup(direction, m15_history, m5_history, levels, atr_m15)
        if setup is None or not self._setup_is_on_m1_zone(setup, m1_history[-1]):
            return

        atr_m1 = latest_atr(m1_history, cfg.atr_period)
        pattern = detect_trigger_pattern(m1_history, setup.direction, atr_m1)
        if pattern is None:
            return

        entry_price = float(m1_history[-1]["close"])
        risk_plan = build_risk_plan(
            entry_price,
            setup.direction,
            pattern.sl_suggested,
            levels,
            cfg,
            sweep_extreme=setup.sweep_extreme,
        )
        if risk_plan is None:
            return

        initial_risk = abs(risk_plan.entry_price - risk_plan.sl_price)
        breakeven_trigger = find_breakeven_trigger(entry_price, setup.direction, m15_history, cfg)
        self.open_trade = OpenTrade(
            timestamp_entry=current_close_time,
            direction=setup.direction,
            entry_price=risk_plan.entry_price,
            initial_sl_price=risk_plan.sl_price,
            sl_price=risk_plan.sl_price,
            tp_price=risk_plan.tp_price,
            rr_effective=risk_plan.rr_effective,
            setup_name=setup.setup_name,
            pattern_id=pattern.pattern_id,
            pattern_name=pattern.pattern_name,
            initial_risk=initial_risk,
            breakeven_trigger=breakeven_trigger,
        )

    def run(self) -> List[Dict[str, Any]]:
        m1 = self.timeframes["M1"]
        indices = {"M5": 0, "M15": 0, "H1": 0}

        for m1_index, bar in enumerate(m1):
            current_close_time = bar["time"] + timedelta(minutes=1)
            for timeframe in ("M5", "M15", "H1"):
                indices[timeframe] = self._advance_completed_index(
                    self.timeframes[timeframe],
                    indices[timeframe],
                    current_close_time,
                    timeframe,
                )

            if self.open_trade is not None:
                closed = evaluate_trade_on_bar(self.open_trade, bar, self.config)
                if closed is not None:
                    self.trades.append(closed)
                    self.open_trade = None
                continue

            h1_history, m15_history, m5_history = self._histories(indices)
            m1_history = self._recent(m1, m1_index + 1, 120)
            self._try_open_trade(m1_history, h1_history, m15_history, m5_history, current_close_time)

        if self.open_trade is not None and m1:
            last_bar = m1[-1]
            closed = close_trade(
                self.open_trade,
                last_bar["time"] + timedelta(minutes=1),
                float(last_bar["close"]),
                "timeout",
                self.config,
            )
            self.trades.append(closed)
            self.open_trade = None

        return self.trades


def run_backtest(
    m1_path: str,
    config: Optional[Convergenza7Config] = None,
    trades_csv: Optional[str] = None,
    stats_json: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = config or Convergenza7Config()
    timeframes = load_timeframes({"M1": m1_path}, cfg)
    engine = Convergenza7BacktestEngine(timeframes, cfg)
    trades = engine.run()
    stats = write_report(trades, cfg, trades_csv=trades_csv, stats_json=stats_json)
    return trades, stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CONVERGENZA 7 backtest on XAUUSD M1 OHLCV data.")
    parser.add_argument("--m1", required=True, help="Path to local M1 CSV or Parquet file.")
    parser.add_argument("--trades-csv", default=None, help="Output CSV path for trade log.")
    parser.add_argument("--stats-json", default=None, help="Output JSON path for aggregate statistics.")
    parser.add_argument("--max-trade-bars", type=int, default=None, help="Override max bars before timeout.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = Convergenza7Config()
    if args.max_trade_bars is not None:
        config = Convergenza7Config.from_dict({"max_trade_bars": args.max_trade_bars})
    run_backtest(args.m1, config=config, trades_csv=args.trades_csv, stats_json=args.stats_json)


if __name__ == "__main__":
    main()

