"""
CLI for TSEntry data collection, backtesting, and demo execution.

Examples:
  python tsentry_runner.py collect --broker-name vantage --symbols XAUUSD XAGUSD --days 365
  python tsentry_runner.py backtest --styles all --base-timeframe M1
  python tsentry_runner.py live --style daytrading_daily
  python tsentry_runner.py live --style daytrading_daily --execute

MT5 connection values are read from environment variables unless passed as CLI
arguments:
  TSENTRY_MT5_PATH, TSENTRY_MT5_LOGIN, TSENTRY_MT5_PASSWORD, TSENTRY_MT5_SERVER
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from tsentry_strategy import (
    STYLE_SPECS,
    BacktestTrade,
    TsEntryParams,
    backtest_style,
    detect_tsentry_signals,
    ensure_timeframes,
    normalize_ohlc,
    trades_to_frame,
)

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - MT5 is available only on the trading VPS.
    mt5 = None


DEFAULT_DB_PATH = os.environ.get("TSENTRY_DB_PATH", "C:/tradingo_math/tsentry_archive.db")

MT5_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}

TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
    "MN1": 43200,
}


def load_csv_ohlc(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    renamed = {col: str(col).strip().lower() for col in df.columns}
    df = df.rename(columns=renamed)
    if "time" not in df.columns:
        for candidate in ("datetime", "date", "timestamp"):
            if candidate in df.columns:
                df = df.rename(columns={candidate: "time"})
                break
    return normalize_ohlc(df)


def discover_csv(data_dir: Path, symbol: str, timeframe: str, source: str) -> Optional[Path]:
    pattern = f"{symbol.upper()}_{timeframe.upper()}_{source}_*.csv"
    matches = sorted(data_dir.glob(pattern))
    if not matches:
        legacy = sorted(data_dir.glob(f"{symbol.upper()}_{timeframe.upper()}.csv"))
        matches = legacy
    return matches[-1] if matches else None


def timeframe_can_support(base_timeframe: str, required_timeframe: str) -> bool:
    base = TIMEFRAME_MINUTES.get(base_timeframe.upper())
    required = TIMEFRAME_MINUTES.get(required_timeframe.upper())
    if base is None or required is None:
        return False
    return base <= required


class TsEntryArchive:
    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles (
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                time_utc TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                tick_volume REAL,
                spread REAL,
                real_volume REAL,
                PRIMARY KEY (broker, symbol, timeframe, time_utc)
            );

            CREATE INDEX IF NOT EXISTS idx_candles_lookup
            ON candles(symbol, timeframe, time_utc);

            CREATE TABLE IF NOT EXISTS backtest_runs (
                run_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                smt_symbol TEXT,
                styles TEXT NOT NULL,
                params_json TEXT NOT NULL,
                summary_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS backtest_trades (
                run_id TEXT NOT NULL,
                style TEXT NOT NULL,
                signal_time TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                result_r REAL NOT NULL,
                pnl REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                level_name TEXT NOT NULL,
                smt_confirmed INTEGER NOT NULL,
                score REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS live_signals (
                signal_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                style TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                level_name TEXT NOT NULL,
                smt_confirmed INTEGER NOT NULL,
                executed INTEGER NOT NULL,
                order_result_json TEXT
            );
            """
        )
        self.conn.commit()

    def store_candles(self, broker: str, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        src = normalize_ohlc(df)
        rows = []
        for timestamp, row in src.iterrows():
            rows.append(
                (
                    broker,
                    symbol,
                    timeframe,
                    timestamp.isoformat(),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row.get("tick_volume", 0.0)),
                    float(row.get("spread", 0.0)),
                    float(row.get("real_volume", 0.0)),
                )
            )
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO candles
            (broker, symbol, timeframe, time_utc, open, high, low, close, tick_volume, spread, real_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def load_candles(
        self,
        broker: str,
        symbol: str,
        timeframe: str,
        start_utc: Optional[datetime] = None,
        end_utc: Optional[datetime] = None,
    ) -> pd.DataFrame:
        clauses = ["broker = ?", "symbol = ?", "timeframe = ?"]
        params: List[object] = [broker, symbol, timeframe]
        if start_utc:
            clauses.append("time_utc >= ?")
            params.append(start_utc.astimezone(timezone.utc).isoformat())
        if end_utc:
            clauses.append("time_utc <= ?")
            params.append(end_utc.astimezone(timezone.utc).isoformat())
        sql = f"""
            SELECT time_utc, open, high, low, close, tick_volume
            FROM candles
            WHERE {' AND '.join(clauses)}
            ORDER BY time_utc
        """
        df = pd.read_sql_query(sql, self.conn, params=params)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df.pop("time_utc"), utc=True)
        return normalize_ohlc(df)

    def store_backtest_run(
        self,
        broker: str,
        symbol: str,
        smt_symbol: str,
        styles: Sequence[str],
        params: TsEntryParams,
        summaries: Dict[str, pd.DataFrame],
        trades: Sequence[BacktestTrade],
    ) -> str:
        run_id = str(uuid.uuid4())
        summary_payload = {style: frame.to_dict(orient="records")[0] for style, frame in summaries.items()}
        self.conn.execute(
            """
            INSERT INTO backtest_runs
            (run_id, created_at_utc, broker, symbol, smt_symbol, styles, params_json, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                broker,
                symbol,
                smt_symbol,
                ",".join(styles),
                json.dumps(asdict(params), sort_keys=True),
                json.dumps(summary_payload, sort_keys=True),
            ),
        )
        self.conn.executemany(
            """
            INSERT INTO backtest_trades
            (run_id, style, signal_time, entry_time, exit_time, direction, entry_price, stop_loss,
             tp1, tp2, result_r, pnl, exit_reason, level_name, smt_confirmed, score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    trade.style,
                    trade.signal_time.isoformat(),
                    trade.entry_time.isoformat(),
                    trade.exit_time.isoformat(),
                    trade.direction.value,
                    trade.entry_price,
                    trade.stop_loss,
                    trade.tp1,
                    trade.tp2,
                    trade.result_r,
                    trade.pnl,
                    trade.exit_reason,
                    trade.level_name,
                    1 if trade.smt_confirmed else 0,
                    trade.score,
                )
                for trade in trades
            ],
        )
        self.conn.commit()
        return run_id

    def store_live_signal(self, broker: str, symbol: str, signal, executed: bool, order_result: Optional[dict]) -> str:
        signal_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO live_signals
            (signal_id, created_at_utc, broker, symbol, style, direction, signal_time, entry_price,
             stop_loss, tp1, tp2, level_name, smt_confirmed, executed, order_result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                datetime.now(timezone.utc).isoformat(),
                broker,
                symbol,
                signal.style,
                signal.direction.value,
                signal.timestamp.isoformat(),
                signal.entry_price,
                signal.stop_loss,
                signal.tp1,
                signal.tp2,
                signal.level_name,
                1 if signal.smt_confirmed else 0,
                1 if executed else 0,
                json.dumps(order_result or {}, sort_keys=True),
            ),
        )
        self.conn.commit()
        return signal_id


def mt5_connect(args) -> None:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not available in this environment.")
    path = args.mt5_path or os.environ.get("TSENTRY_MT5_PATH")
    login = args.mt5_login or os.environ.get("TSENTRY_MT5_LOGIN")
    password = args.mt5_password or os.environ.get("TSENTRY_MT5_PASSWORD")
    server = args.mt5_server or os.environ.get("TSENTRY_MT5_SERVER")

    kwargs = {}
    if path:
        kwargs["path"] = path
    if login:
        kwargs["login"] = int(login)
    if password:
        kwargs["password"] = password
    if server:
        kwargs["server"] = server
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def mt5_timeframe(name: str) -> int:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not available.")
    attr = MT5_TIMEFRAMES.get(name)
    if not attr or not hasattr(mt5, attr):
        raise ValueError(f"Unsupported MT5 timeframe: {name}")
    return getattr(mt5, attr)


def mt5_rates(symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    rates = mt5.copy_rates_range(symbol, mt5_timeframe(timeframe), start, end)
    if rates is None:
        raise RuntimeError(f"copy_rates_range failed for {symbol} {timeframe}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return normalize_ohlc(df)


def command_collect(args) -> None:
    archive = TsEntryArchive(args.db)
    try:
        mt5_connect(args)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                df = mt5_rates(symbol, timeframe, start, end)
                stored = archive.store_candles(args.broker_name, symbol, timeframe, df)
                print(f"{args.broker_name} {symbol} {timeframe}: stored {stored} candles")
    finally:
        archive.close()
        if mt5 is not None:
            mt5.shutdown()


def build_frames_from_archive(
    archive: TsEntryArchive,
    broker: str,
    symbol: str,
    base_timeframe: str,
    styles: Iterable[str],
    start_utc: Optional[datetime],
    end_utc: Optional[datetime],
) -> Dict[str, pd.DataFrame]:
    required = set()
    for style_name in styles:
        spec = STYLE_SPECS[style_name]
        required.update([spec.bias_tf, spec.range_tf, spec.entry_tf])

    frames: Dict[str, pd.DataFrame] = {}
    base = archive.load_candles(broker, symbol, base_timeframe, start_utc, end_utc)
    if base.empty:
        raise RuntimeError(f"No candles in archive for {broker} {symbol} {base_timeframe}")

    frames.update(ensure_timeframes(base, required))
    for timeframe in required:
        direct = archive.load_candles(broker, symbol, timeframe, start_utc, end_utc)
        if not direct.empty:
            frames[timeframe] = direct
    return frames


def command_backtest(args) -> None:
    styles = list(STYLE_SPECS) if args.styles == ["all"] else args.styles
    params = TsEntryParams(
        symbol=args.symbol,
        smt_symbol=args.smt_symbol,
        risk_fraction=args.risk,
        starting_equity=args.starting_equity,
        spread_buffer_points=args.buffer_points,
        point_size=args.point_size,
        require_smt=args.require_smt,
        max_consecutive_daily_losses=args.max_consecutive_daily_losses,
    )

    archive = TsEntryArchive(args.db)
    try:
        start = _parse_dt(args.start)
        end = _parse_dt(args.end)
        frames = build_frames_from_archive(archive, args.broker_name, args.symbol, args.base_timeframe, styles, start, end)

        smt_frames = None
        smt_base = archive.load_candles(args.broker_name, args.smt_symbol, args.base_timeframe, start, end)
        if not smt_base.empty:
            wanted = {STYLE_SPECS[style].entry_tf for style in styles}
            smt_frames = ensure_timeframes(smt_base, wanted)

        all_trades: List[BacktestTrade] = []
        summaries: Dict[str, pd.DataFrame] = {}
        for style_name in styles:
            trades, summary = backtest_style(style_name, frames, params, smt_frames=smt_frames)
            summaries[style_name] = summary
            all_trades.extend(trades)
            print(f"\n[{style_name}]")
            print(summary.to_string(index=False))

        if all_trades:
            overlay = trades_to_frame(all_trades).sort_values("entry_time")
            print("\n[overlay]")
            print(
                pd.DataFrame(
                    [
                        {
                            "trades": len(overlay),
                            "total_r": float(overlay["result_r"].sum()),
                            "expectancy_r": float(overlay["result_r"].mean()),
                            "net_pnl": float(overlay["pnl"].sum()),
                        }
                    ]
                ).to_string(index=False)
            )
        run_id = archive.store_backtest_run(args.broker_name, args.symbol, args.smt_symbol, styles, params, summaries, all_trades)
        print(f"\nBacktest run stored: {run_id}")
    finally:
        archive.close()


def command_csv_backtest(args) -> None:
    styles = list(STYLE_SPECS) if args.styles == ["all"] else args.styles
    data_dir = Path(args.data_dir)
    csv_path = args.csv or discover_csv(data_dir, args.symbol, args.csv_timeframe, args.source)
    if csv_path is None:
        raise RuntimeError(
            f"No CSV found for {args.symbol} {args.csv_timeframe} in {data_dir}. "
            "Download it first with price_action_quant.research download-dukascopy."
        )
    csv_path = Path(csv_path)
    base_df = load_csv_ohlc(csv_path)
    start = _parse_dt(args.start)
    end = _parse_dt(args.end)
    if start:
        base_df = base_df[base_df.index >= pd.Timestamp(start)]
    if end:
        base_df = base_df[base_df.index <= pd.Timestamp(end)]

    params = TsEntryParams(
        symbol=args.symbol,
        smt_symbol=args.smt_symbol,
        risk_fraction=args.risk,
        starting_equity=args.starting_equity,
        spread_buffer_points=args.buffer_points,
        point_size=args.point_size,
        require_smt=args.require_smt,
        max_consecutive_daily_losses=args.max_consecutive_daily_losses,
    )

    smt_frames = None
    smt_csv_path = args.smt_csv or discover_csv(data_dir, args.smt_symbol, args.csv_timeframe, args.source)
    if smt_csv_path:
        smt_base = load_csv_ohlc(Path(smt_csv_path))
        if start:
            smt_base = smt_base[smt_base.index >= pd.Timestamp(start)]
        if end:
            smt_base = smt_base[smt_base.index <= pd.Timestamp(end)]
        smt_wanted = {
            STYLE_SPECS[style].entry_tf
            for style in styles
            if timeframe_can_support(args.csv_timeframe, STYLE_SPECS[style].entry_tf)
        }
        if smt_wanted:
            smt_frames = ensure_timeframes(smt_base, smt_wanted)

    all_trades: List[BacktestTrade] = []
    summaries: Dict[str, pd.DataFrame] = {}
    skipped: Dict[str, str] = {}
    run_label = csv_run_label(args)
    for style_name in styles:
        spec = STYLE_SPECS[style_name]
        if not timeframe_can_support(args.csv_timeframe, spec.entry_tf):
            skipped[style_name] = (
                f"{args.csv_timeframe} CSV cannot be downsampled to required entry timeframe {spec.entry_tf}"
            )
            print(f"\n[{style_name}] skipped: {skipped[style_name]}")
            continue

        required = {spec.bias_tf, spec.range_tf, spec.entry_tf}
        frames = ensure_timeframes(base_df, required)
        trades, summary = backtest_style(style_name, frames, params, smt_frames=smt_frames)
        summaries[style_name] = summary
        all_trades.extend(trades)
        print(f"\n[{style_name}]")
        print(summary.to_string(index=False))

        prefix = f"TSENTRY_{args.symbol.upper()}_{spec.entry_tf}_{style_name}_{run_label}"
        trades_out = data_dir / f"{prefix}_trades.csv"
        summary_out = data_dir / f"{prefix}_summary.json"
        frame = trades_to_frame(trades)
        trades_out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(trades_out, index=False)
        summary_out.write_text(summary.to_json(orient="records", indent=2), encoding="utf-8")

    overlay = trades_to_frame(all_trades).sort_values("entry_time") if all_trades else pd.DataFrame()
    if not overlay.empty:
        overlay_out = data_dir / f"TSENTRY_{args.symbol.upper()}_{args.csv_timeframe}_{run_label}_overlay_trades.csv"
        overlay.to_csv(overlay_out, index=False)
        print("\n[overlay]")
        print(
            pd.DataFrame(
                [
                    {
                        "trades": len(overlay),
                        "total_r": float(overlay["result_r"].sum()),
                        "expectancy_r": float(overlay["result_r"].mean()),
                        "net_pnl": float(overlay["pnl"].sum()),
                    }
                ]
            ).to_string(index=False)
        )

    report_path = write_csv_backtest_report(
        args=args,
        csv_path=csv_path,
        smt_csv_path=Path(smt_csv_path) if smt_csv_path else None,
        data=base_df,
        summaries=summaries,
        skipped=skipped,
        trades=all_trades,
    )
    print(f"\nReport written: {report_path}")


def command_live(args) -> None:
    params = TsEntryParams(
        symbol=args.symbol,
        smt_symbol=args.smt_symbol,
        risk_fraction=args.risk,
        starting_equity=args.starting_equity,
        spread_buffer_points=args.buffer_points,
        point_size=args.point_size,
        require_smt=args.require_smt,
        max_consecutive_daily_losses=args.max_consecutive_daily_losses,
    )
    archive = TsEntryArchive(args.db)
    try:
        mt5_connect(args)
        spec = STYLE_SPECS[args.style]
        needed = {spec.bias_tf, spec.range_tf, spec.entry_tf}
        lookback_days = args.lookback_days
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)

        base_tf = args.base_timeframe or spec.entry_tf
        base_df = mt5_rates(args.symbol, base_tf, start, end)
        archive.store_candles(args.broker_name, args.symbol, base_tf, base_df)
        frames = ensure_timeframes(base_df, needed)

        smt_frames = None
        try:
            smt_base = mt5_rates(args.smt_symbol, base_tf, start, end)
            archive.store_candles(args.broker_name, args.smt_symbol, base_tf, smt_base)
            smt_frames = ensure_timeframes(smt_base, {spec.entry_tf})
        except Exception as exc:
            print(f"SMT unavailable for {args.smt_symbol}: {exc}")

        signals = detect_tsentry_signals(args.style, frames, params, smt_frames=smt_frames)
        if not signals:
            print("No TSEntry signal.")
            return

        signal = signals[-1]
        print(
            f"TSEntry {signal.style} {signal.direction.value} @ {signal.entry_price:.2f} "
            f"SL {signal.stop_loss:.2f} TP1 {signal.tp1:.2f} TP2 {signal.tp2:.2f} "
            f"level={signal.level_name} smt={signal.smt_confirmed}"
        )
        order_result = None
        if args.execute:
            order_result = execute_split_order(args.symbol, signal, params)
        signal_id = archive.store_live_signal(args.broker_name, args.symbol, signal, args.execute, order_result)
        print(f"Live signal stored: {signal_id} executed={args.execute}")
    finally:
        archive.close()
        if mt5 is not None:
            mt5.shutdown()


def write_csv_backtest_report(
    args,
    csv_path: Path,
    smt_csv_path: Optional[Path],
    data: pd.DataFrame,
    summaries: Dict[str, pd.DataFrame],
    skipped: Dict[str, str],
    trades: Sequence[BacktestTrade],
) -> Path:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_path = report_dir / (
        f"{args.symbol.lower()}_{args.csv_timeframe.lower()}_tsentry_csv_backtest_"
        f"{csv_run_label(args)}_{stamp}.md"
    )

    first = data.index.min().strftime("%Y-%m-%d %H:%M UTC") if not data.empty else "n/a"
    last = data.index.max().strftime("%Y-%m-%d %H:%M UTC") if not data.empty else "n/a"

    lines = [
        f"# TSEntry CSV Backtest - {args.symbol.upper()} {args.csv_timeframe.upper()}",
        "",
        "## Data used",
        "",
        f"- Primary file: `{csv_path}`",
        f"- Symbol: `{args.symbol.upper()}`",
        f"- Timeframe: `{args.csv_timeframe.upper()}`",
        f"- Source: `{args.source}`",
        f"- Period: {first} -> {last}",
        f"- Bars: {len(data):,}",
        f"- SMT file: `{smt_csv_path}`" if smt_csv_path else "- SMT file: not available / not used",
        "",
        "## Assumptions",
        "",
        f"- Risk per trade: {args.risk:.2%}",
        f"- Starting equity for PnL normalization: {args.starting_equity:,.2f}",
        f"- Sweep buffer: {args.buffer_points} points x point size {args.point_size}",
        f"- Max consecutive losing trades per NY day: {args.max_consecutive_daily_losses}",
        f"- SMT required: {args.require_smt}",
        "- Spread/commission/slippage: not explicitly charged beyond the sweep buffer.",
        "- Same-bar ambiguity: bar-based backtest uses conservative stop checks before target checks.",
        "- Execution feed: historical CSV, not live broker tick feed.",
        "",
        "## Per-style results",
        "",
        "| Style | Trades | Win rate | Total R | Expectancy R | Net PnL | Max DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for style_name, summary in summaries.items():
        row = summary.to_dict(orient="records")[0]
        lines.append(
            "| {style} | {trades} | {win_rate:.2%} | {total_r:.2f} | {expectancy_r:.3f} | {net_pnl:.2f} | {max_dd:.2f} |".format(
                style=style_name,
                trades=int(row["trades"]),
                win_rate=float(row["win_rate"]),
                total_r=float(row["total_r"]),
                expectancy_r=float(row["expectancy_r"]),
                net_pnl=float(row["net_pnl"]),
                max_dd=float(row["max_drawdown"]),
            )
        )

    if skipped:
        lines.extend(["", "## Skipped styles", ""])
        for style_name, reason in skipped.items():
            lines.append(f"- `{style_name}`: {reason}")

    if trades:
        overlay = trades_to_frame(list(trades))
        lines.extend(
            [
                "",
                "## Overlay",
                "",
                f"- Trades: {len(overlay)}",
                f"- Total R: {float(overlay['result_r'].sum()):.2f}",
                f"- Expectancy R: {float(overlay['result_r'].mean()):.3f}",
                f"- Net PnL: {float(overlay['pnl'].sum()):.2f}",
            ]
        )

    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            "Example command:",
            "",
            "```bash",
            (
                "python3 tsentry_runner.py csv-backtest "
                f"--symbol {args.symbol} --csv-timeframe {args.csv_timeframe} "
                f"--source {args.source} --styles {' '.join(args.styles)}"
                + (f" --start {args.start}" if args.start else "")
                + (f" --end {args.end}" if args.end else "")
            ),
            "```",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def csv_run_label(args) -> str:
    parts = ["smt" if getattr(args, "require_smt", False) else "base"]
    if getattr(args, "start", None):
        parts.append(str(args.start).replace("-", "").replace(":", "").replace("+", "").replace("Z", ""))
    if getattr(args, "end", None):
        parts.append(str(args.end).replace("-", "").replace(":", "").replace("+", "").replace("Z", ""))
    return "_".join(parts)


def execute_split_order(symbol: str, signal, params: TsEntryParams) -> dict:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    account = mt5.account_info()
    if tick is None or info is None or account is None:
        raise RuntimeError("Missing MT5 tick/symbol/account info.")

    price = tick.ask if signal.direction.value == "BUY" else tick.bid
    stop_distance = abs(price - signal.stop_loss)
    if stop_distance <= 0:
        raise RuntimeError("Invalid stop distance.")

    risk_amount = float(account.equity) * params.risk_fraction
    loss_per_lot = (stop_distance / info.trade_tick_size) * info.trade_tick_value
    total_volume = risk_amount / loss_per_lot
    total_volume = _round_volume(total_volume, info.volume_step, info.volume_min, info.volume_max)
    half_volume = _round_volume(total_volume / 2.0, info.volume_step, info.volume_min, info.volume_max)
    order_type = mt5.ORDER_TYPE_BUY if signal.direction.value == "BUY" else mt5.ORDER_TYPE_SELL

    results = []
    for volume, tp, label in ((half_volume, signal.tp1, "TP1"), (half_volume, signal.tp2, "TP2")):
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(signal.stop_loss),
            "tp": float(tp),
            "deviation": 20,
            "magic": 20260608,
            "comment": f"TSENTRY_{label}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        results.append(
            {
                "target": label,
                "volume": volume,
                "retcode": getattr(result, "retcode", None),
                "order": getattr(result, "order", None),
                "comment": getattr(result, "comment", None),
            }
        )
    return {"orders": results, "risk_amount": risk_amount, "total_volume": total_volume}


def _round_volume(volume: float, step: float, min_volume: float, max_volume: float) -> float:
    if step <= 0:
        return max(min_volume, min(volume, max_volume))
    rounded = round(volume / step) * step
    return float(max(min_volume, min(rounded, max_volume)))


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def add_mt5_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mt5-path", default=None)
    parser.add_argument("--mt5-login", default=None)
    parser.add_argument("--mt5-password", default=None)
    parser.add_argument("--mt5-server", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TSEntry archive, backtest, and demo runner")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Collect historical candles from MT5 into SQLite")
    collect.add_argument("--broker-name", required=True)
    collect.add_argument("--symbols", nargs="+", default=["XAUUSD", "XAGUSD"])
    collect.add_argument("--timeframes", nargs="+", default=["M1", "M5", "M15", "H1", "D1", "W1", "MN1"])
    collect.add_argument("--days", type=int, default=365)
    add_mt5_args(collect)
    collect.set_defaults(func=command_collect)

    backtest = sub.add_parser("backtest", help="Backtest one or all TSEntry styles from the archive")
    backtest.add_argument("--broker-name", required=True)
    backtest.add_argument("--symbol", default="XAUUSD")
    backtest.add_argument("--smt-symbol", default="XAGUSD")
    backtest.add_argument("--styles", nargs="+", default=["all"], choices=["all", *STYLE_SPECS.keys()])
    backtest.add_argument("--base-timeframe", default="M1")
    backtest.add_argument("--start", default=None)
    backtest.add_argument("--end", default=None)
    backtest.add_argument("--risk", type=float, default=0.01)
    backtest.add_argument("--starting-equity", type=float, default=100_000.0)
    backtest.add_argument("--buffer-points", type=float, default=80.0)
    backtest.add_argument("--point-size", type=float, default=0.01)
    backtest.add_argument("--max-consecutive-daily-losses", type=int, default=2)
    backtest.add_argument("--require-smt", action="store_true")
    backtest.set_defaults(func=command_backtest)

    csv_bt = sub.add_parser("csv-backtest", help="Backtest TSEntry from shared CSV files under data/backtests")
    csv_bt.add_argument("--data-dir", default="data/backtests")
    csv_bt.add_argument("--report-dir", default="price_action_quant/reports")
    csv_bt.add_argument("--csv", type=Path, default=None)
    csv_bt.add_argument("--smt-csv", type=Path, default=None)
    csv_bt.add_argument("--source", default="dukascopy")
    csv_bt.add_argument("--symbol", default="XAUUSD")
    csv_bt.add_argument("--smt-symbol", default="XAGUSD")
    csv_bt.add_argument("--csv-timeframe", default="H1")
    csv_bt.add_argument("--start", default=None)
    csv_bt.add_argument("--end", default=None)
    csv_bt.add_argument("--styles", nargs="+", default=["all"], choices=["all", *STYLE_SPECS.keys()])
    csv_bt.add_argument("--risk", type=float, default=0.01)
    csv_bt.add_argument("--starting-equity", type=float, default=100_000.0)
    csv_bt.add_argument("--buffer-points", type=float, default=80.0)
    csv_bt.add_argument("--point-size", type=float, default=0.01)
    csv_bt.add_argument("--max-consecutive-daily-losses", type=int, default=2)
    csv_bt.add_argument("--require-smt", action="store_true")
    csv_bt.set_defaults(func=command_csv_backtest)

    live = sub.add_parser("live", help="Check current TSEntry setup and optionally execute on demo")
    live.add_argument("--broker-name", required=True)
    live.add_argument("--symbol", default="XAUUSD")
    live.add_argument("--smt-symbol", default="XAGUSD")
    live.add_argument("--style", choices=list(STYLE_SPECS), default="daytrading_daily")
    live.add_argument("--base-timeframe", default=None)
    live.add_argument("--lookback-days", type=int, default=90)
    live.add_argument("--risk", type=float, default=0.01)
    live.add_argument("--starting-equity", type=float, default=100_000.0)
    live.add_argument("--buffer-points", type=float, default=80.0)
    live.add_argument("--point-size", type=float, default=0.01)
    live.add_argument("--max-consecutive-daily-losses", type=int, default=2)
    live.add_argument("--require-smt", action="store_true")
    live.add_argument("--execute", action="store_true", help="Actually place demo orders; omitted means dry-run")
    add_mt5_args(live)
    live.set_defaults(func=command_live)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
