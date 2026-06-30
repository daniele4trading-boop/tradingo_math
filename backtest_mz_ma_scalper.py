import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


@dataclass
class BacktestConfig:
    fast_period: int = 5
    slow_period: int = 10
    ma_method: str = "EMA"
    use_break: bool = True
    use_bounce: bool = True
    require_confirm: bool = True
    cooldown_bars: int = 3
    max_positions: int = 1
    sl_points: int = 200
    use_risk_percent: bool = True
    risk_percent: float = 1.0
    fixed_lot: float = 0.05
    use_trailing: bool = True
    trail_start_points: int = 200
    trail_dist_points: int = 200
    trail_step_points: int = 50
    use_session: bool = True
    start_hour: int = 16
    start_minute: int = 30
    end_hour: int = 19
    end_minute: int = 0
    max_spread_points: int = 50
    point: float = 0.01
    tick_size: float = 0.01
    tick_value: float = 1.0
    initial_balance: float = 10_000.0
    fixed_spread_points: float = 0.0


@dataclass
class Position:
    side: str
    entry_time: str
    entry_index: int
    entry_price: float
    sl: float
    lot: float


@dataclass
class Trade:
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    lot: float
    pnl: float
    exit_reason: str
    bars_held: int


def load_ohlc_csv(path: Path, time_column: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if time_column is None:
        for candidate in ("time", "datetime", "date", "Date", "Time"):
            if candidate in df.columns:
                time_column = candidate
                break
    if time_column is None or time_column not in df.columns:
        raise ValueError("CSV must include a time/datetime/date column or use --time-column.")

    rename_map = {time_column: "time"}
    for column in df.columns:
        lower = column.lower()
        if lower in {"open", "high", "low", "close", "spread"}:
            rename_map[column] = lower
    df = df.rename(columns=rename_map)

    required = {"time", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"CSV missing required OHLC columns: {sorted(missing)}")

    df["time"] = pd.to_datetime(df["time"], utc=False)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def moving_average(series: pd.Series, period: int, method: str) -> pd.Series:
    method = method.upper()
    if method == "EMA":
        return series.ewm(span=period, adjust=False).mean()
    if method == "SMA":
        return series.rolling(period).mean()
    raise ValueError("--ma-method must be EMA or SMA.")


def in_session(ts: pd.Timestamp, cfg: BacktestConfig) -> bool:
    if not cfg.use_session:
        return True

    now_min = ts.hour * 60 + ts.minute
    start_min = cfg.start_hour * 60 + cfg.start_minute
    end_min = cfg.end_hour * 60 + cfg.end_minute

    if start_min <= end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def spread_points_at(row: pd.Series, cfg: BacktestConfig) -> float:
    if "spread" in row and pd.notna(row["spread"]):
        return float(row["spread"])
    return cfg.fixed_spread_points


def calc_lot(balance: float, cfg: BacktestConfig) -> float:
    if not cfg.use_risk_percent:
        return max(0.0, round(cfg.fixed_lot, 2))

    risk_money = balance * cfg.risk_percent / 100.0
    sl_dist_price = cfg.sl_points * cfg.point
    if cfg.tick_size <= 0 or cfg.tick_value <= 0 or sl_dist_price <= 0:
        return max(0.0, round(cfg.fixed_lot, 2))

    loss_per_lot = (sl_dist_price / cfg.tick_size) * cfg.tick_value
    if loss_per_lot <= 0:
        return max(0.0, round(cfg.fixed_lot, 2))
    return max(0.0, round(risk_money / loss_per_lot, 2))


def trade_pnl(side: str, entry: float, exit_price: float, lot: float, cfg: BacktestConfig) -> float:
    if side == "BUY":
        price_delta = exit_price - entry
    else:
        price_delta = entry - exit_price
    return (price_delta / cfg.tick_size) * cfg.tick_value * lot


def should_enter(row1: pd.Series, row2: pd.Series, cfg: BacktestConfig) -> str | None:
    fast1, fast2 = row1["fast_ma"], row2["fast_ma"]
    slow1, slow2 = row1["slow_ma"], row2["slow_ma"]
    if pd.isna(fast1) or pd.isna(fast2) or pd.isna(slow1) or pd.isna(slow2):
        return None

    bull_candle = row1["close"] > row1["open"]
    bear_candle = row1["close"] < row1["open"]
    cross_up = fast2 <= slow2 and fast1 > slow1
    cross_down = fast2 >= slow2 and fast1 < slow1
    bias_long = fast1 > slow1
    bias_short = fast1 < slow1

    if cfg.use_break:
        if cross_up and row1["close"] > slow1 and (not cfg.require_confirm or bull_candle):
            return "BUY"
        if cross_down and row1["close"] < slow1 and (not cfg.require_confirm or bear_candle):
            return "SELL"

    if cfg.use_bounce:
        if bias_long and row1["low"] <= fast1 and row1["close"] > fast1 and (
            not cfg.require_confirm or bull_candle
        ):
            return "BUY"
        if bias_short and row1["high"] >= fast1 and row1["close"] < fast1 and (
            not cfg.require_confirm or bear_candle
        ):
            return "SELL"

    return None


def manage_position(pos: Position, row: pd.Series, index: int, cfg: BacktestConfig) -> Trade | None:
    high = float(row["high"])
    low = float(row["low"])
    exit_time = row["time"].isoformat()

    if pos.side == "BUY":
        if low <= pos.sl:
            pnl = trade_pnl(pos.side, pos.entry_price, pos.sl, pos.lot, cfg)
            return Trade(pos.side, pos.entry_time, exit_time, pos.entry_price, pos.sl, pos.lot, pnl, "SL", index - pos.entry_index)

        if cfg.use_trailing and (high - pos.entry_price) / cfg.point >= cfg.trail_start_points:
            new_sl = high - cfg.trail_dist_points * cfg.point
            if new_sl > pos.entry_price - cfg.point and new_sl >= pos.sl + cfg.trail_step_points * cfg.point:
                pos.sl = round(new_sl, 5)
                if low <= pos.sl:
                    pnl = trade_pnl(pos.side, pos.entry_price, pos.sl, pos.lot, cfg)
                    return Trade(
                        pos.side, pos.entry_time, exit_time, pos.entry_price, pos.sl, pos.lot, pnl, "TRAIL", index - pos.entry_index
                    )
    else:
        if high >= pos.sl:
            pnl = trade_pnl(pos.side, pos.entry_price, pos.sl, pos.lot, cfg)
            return Trade(pos.side, pos.entry_time, exit_time, pos.entry_price, pos.sl, pos.lot, pnl, "SL", index - pos.entry_index)

        if cfg.use_trailing and (pos.entry_price - low) / cfg.point >= cfg.trail_start_points:
            new_sl = low + cfg.trail_dist_points * cfg.point
            if new_sl < pos.entry_price + cfg.point and new_sl <= pos.sl - cfg.trail_step_points * cfg.point:
                pos.sl = round(new_sl, 5)
                if high >= pos.sl:
                    pnl = trade_pnl(pos.side, pos.entry_price, pos.sl, pos.lot, cfg)
                    return Trade(
                        pos.side, pos.entry_time, exit_time, pos.entry_price, pos.sl, pos.lot, pnl, "TRAIL", index - pos.entry_index
                    )
    return None


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> tuple[dict, list[Trade]]:
    if cfg.fast_period >= cfg.slow_period:
        raise ValueError("fast_period must be lower than slow_period.")

    data = df.copy()
    data["fast_ma"] = moving_average(data["close"], cfg.fast_period, cfg.ma_method)
    data["slow_ma"] = moving_average(data["close"], cfg.slow_period, cfg.ma_method)

    balance = cfg.initial_balance
    equity_peak = balance
    max_drawdown = 0.0
    open_positions: list[Position] = []
    trades: list[Trade] = []
    last_trade_index: int | None = None

    for index in range(2, len(data)):
        row = data.iloc[index]

        closed: list[Position] = []
        for pos in open_positions:
            trade = manage_position(pos, row, index, cfg)
            if trade is not None:
                trades.append(trade)
                balance += trade.pnl
                equity_peak = max(equity_peak, balance)
                max_drawdown = max(max_drawdown, equity_peak - balance)
                closed.append(pos)
        if closed:
            open_positions = [pos for pos in open_positions if pos not in closed]

        if len(open_positions) >= cfg.max_positions:
            continue
        if last_trade_index is not None and index - last_trade_index < cfg.cooldown_bars:
            continue
        if not in_session(row["time"], cfg):
            continue
        if cfg.max_spread_points > 0 and spread_points_at(row, cfg) > cfg.max_spread_points:
            continue

        signal = should_enter(data.iloc[index - 1], data.iloc[index - 2], cfg)
        if signal is None:
            continue

        spread_price = spread_points_at(row, cfg) * cfg.point
        entry = float(row["open"]) + spread_price if signal == "BUY" else float(row["open"])
        sl_dist = cfg.sl_points * cfg.point
        sl = entry - sl_dist if signal == "BUY" else entry + sl_dist
        lot = calc_lot(balance, cfg)
        if lot <= 0:
            continue

        open_positions.append(
            Position(
                side=signal,
                entry_time=row["time"].isoformat(),
                entry_index=index,
                entry_price=round(entry, 5),
                sl=round(sl, 5),
                lot=lot,
            )
        )
        last_trade_index = index

    if open_positions:
        last = data.iloc[-1]
        for pos in open_positions:
            exit_price = float(last["close"])
            pnl = trade_pnl(pos.side, pos.entry_price, exit_price, pos.lot, cfg)
            trades.append(
                Trade(
                    pos.side,
                    pos.entry_time,
                    last["time"].isoformat(),
                    pos.entry_price,
                    exit_price,
                    pos.lot,
                    pnl,
                    "END",
                    len(data) - 1 - pos.entry_index,
                )
            )
            balance += pnl
            equity_peak = max(equity_peak, balance)
            max_drawdown = max(max_drawdown, equity_peak - balance)

    wins = [trade for trade in trades if trade.pnl > 0]
    losses = [trade for trade in trades if trade.pnl <= 0]
    gross_profit = sum(trade.pnl for trade in wins)
    gross_loss = sum(trade.pnl for trade in losses)
    summary = {
        "bars": len(data),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_profit": round(balance - cfg.initial_balance, 2),
        "initial_balance": round(cfg.initial_balance, 2),
        "final_balance": round(balance, 2),
        "max_drawdown_money": round(max_drawdown, 2),
        "profit_factor": round(gross_profit / abs(gross_loss), 2) if gross_loss < 0 else None,
    }
    return summary, trades


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the MA-based MZ_MA_Scalper reconstruction on OHLC CSV data.")
    parser.add_argument("--csv", required=True, type=Path, help="OHLC CSV exported from MT5 or another data source.")
    parser.add_argument("--time-column", default=None, help="Optional timestamp column name.")
    parser.add_argument("--trades-out", type=Path, default=None, help="Optional path for trade-by-trade CSV output.")
    parser.add_argument("--summary-out", type=Path, default=None, help="Optional path for JSON summary output.")
    parser.add_argument("--fast-period", type=int, default=5)
    parser.add_argument("--slow-period", type=int, default=10)
    parser.add_argument("--ma-method", choices=["EMA", "SMA"], default="EMA")
    parser.add_argument("--fixed-spread-points", type=float, default=0.0)
    parser.add_argument("--max-spread-points", type=int, default=50)
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--risk-percent", type=float, default=1.0)
    parser.add_argument("--fixed-lot", type=float, default=0.05)
    parser.add_argument("--use-risk-percent", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use-break", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use-bounce", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-confirm", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use-session", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use-trailing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--start-hour", type=int, default=16)
    parser.add_argument("--start-minute", type=int, default=30)
    parser.add_argument("--end-hour", type=int, default=19)
    parser.add_argument("--end-minute", type=int, default=0)
    parser.add_argument("--point", type=float, default=0.01)
    parser.add_argument("--tick-size", type=float, default=0.01)
    parser.add_argument("--tick-value", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BacktestConfig(
        fast_period=args.fast_period,
        slow_period=args.slow_period,
        ma_method=args.ma_method,
        use_break=args.use_break,
        use_bounce=args.use_bounce,
        require_confirm=args.require_confirm,
        use_session=args.use_session,
        use_trailing=args.use_trailing,
        fixed_spread_points=args.fixed_spread_points,
        max_spread_points=args.max_spread_points,
        initial_balance=args.initial_balance,
        risk_percent=args.risk_percent,
        fixed_lot=args.fixed_lot,
        use_risk_percent=args.use_risk_percent,
        start_hour=args.start_hour,
        start_minute=args.start_minute,
        end_hour=args.end_hour,
        end_minute=args.end_minute,
        point=args.point,
        tick_size=args.tick_size,
        tick_value=args.tick_value,
    )

    df = load_ohlc_csv(args.csv, args.time_column)
    summary, trades = run_backtest(df, cfg)
    output = {"config": asdict(cfg), "summary": summary}
    print(json.dumps(output, indent=2))

    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    if args.trades_out:
        args.trades_out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(asdict(trade) for trade in trades).to_csv(args.trades_out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
