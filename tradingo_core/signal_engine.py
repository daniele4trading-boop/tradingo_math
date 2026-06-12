"""Live dry-run signal engine.

Reads recent M1 candles from a local MT5 terminal, detects ICT sniper setups,
publishes valid signals to the central API, and appends a CSV journal.  It does
not execute trades; execution remains the responsibility of the MQL5 EA, which
is currently configured in dry-run mode.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from .ict_sniper import ICTSniperConfig, ICTSniperSetup, ICTSniperStrategy
from .market_data import normalize_rates_frame


def run_once(args) -> Optional[ICTSniperSetup]:
    df = fetch_mt5_m1(args.symbol, args.terminal_path, args.bars)
    strategy = ICTSniperStrategy(build_strategy_config(args))
    setup = strategy.find_setup(df)
    if setup is None:
        append_status(args.journal_csv, args.symbol, "NO_SETUP", "No valid setup")
        return None

    signal_id = make_signal_id(args.symbol, setup)
    if signal_already_seen(args.journal_csv, signal_id):
        append_status(args.journal_csv, args.symbol, "DUPLICATE", signal_id)
        return setup

    payload = setup_to_payload(
        symbol=args.symbol,
        setup=setup,
        signal_id=signal_id,
        risk_pct=args.risk_pct,
        expires_minutes=args.expires_minutes,
    )
    response = publish_signal(args.api_base_url, args.admin_api_key, payload)
    append_signal(args.journal_csv, payload, setup, "PUBLISHED", json.dumps(response, sort_keys=True))
    return setup


def loop(args) -> None:
    while True:
        try:
            setup = run_once(args)
            if setup:
                print(f"setup={setup.direction} score={setup.score:.2f} entry={setup.entry:.2f}")
            else:
                print(f"{datetime.now(timezone.utc).isoformat()} no setup")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            append_status(args.journal_csv, args.symbol, "ERROR", str(exc))
            print(f"ERROR: {exc}")
        time.sleep(args.poll_seconds)


def fetch_mt5_m1(symbol: str, terminal_path: str, bars: int) -> pd.DataFrame:
    import MetaTrader5 as mt5

    if not mt5.initialize(path=terminal_path):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 returned no M1 rates: {mt5.last_error()}")
        return normalize_rates_frame(pd.DataFrame(rates))
    finally:
        mt5.shutdown()


def build_strategy_config(args) -> ICTSniperConfig:
    return ICTSniperConfig(
        min_score=args.min_score,
        min_sweep_volume_z=args.min_sweep_volume_z,
        min_displacement_range_atr=args.min_displacement_range_atr,
        min_displacement_volume_z=args.min_displacement_volume_z,
        max_retest_volume_z=args.max_retest_volume_z,
        rr_target=args.rr,
        sl_buffer_atr=args.sl_buffer_atr,
    )


def make_signal_id(symbol: str, setup: ICTSniperSetup) -> str:
    timestamp = setup.timestamp.strftime("%Y%m%d%H%M")
    entry = f"{setup.entry:.2f}".replace(".", "")
    return f"ICT-{symbol.upper()}-{timestamp}-{setup.direction}-{entry}"


def setup_to_payload(
    symbol: str,
    setup: ICTSniperSetup,
    signal_id: str,
    risk_pct: float,
    expires_minutes: int,
) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return {
        "signal_id": signal_id,
        "symbol": symbol.upper(),
        "direction": setup.direction,
        "entry_type": "LIMIT",
        "entry": round(setup.entry, 3),
        "sl": round(setup.sl, 3),
        "tp1": round(setup.tp1, 3),
        "tp2": round(setup.tp2, 3),
        "risk_pct": risk_pct,
        "score": round(setup.score, 2),
        "strategy": "ICT_SNIPER",
        "expires_at": expires_at.isoformat(),
        "metadata": {
            "session": setup.session,
            "bias": setup.bias,
            "rr": setup.rr,
            "fvg_low": round(setup.fvg.low, 3),
            "fvg_high": round(setup.fvg.high, 3),
            "sweep_level": round(setup.sweep.level, 3),
            "sweep_extreme": round(setup.sweep.extreme, 3),
            "reasons": list(setup.reasons),
        },
    }


def publish_signal(api_base_url: str, admin_api_key: str, payload: dict) -> dict:
    url = api_base_url.rstrip("/") + "/signals/publish"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": admin_api_key,
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"API publish failed HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except URLError as exc:
        raise RuntimeError(f"API publish failed: {exc}") from exc


def signal_already_seen(journal_csv: str | Path, signal_id: str) -> bool:
    path = Path(journal_csv)
    if not path.exists():
        return False
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return any(row.get("signal_id") == signal_id for row in reader)


def append_signal(journal_csv: str | Path, payload: dict, setup: ICTSniperSetup, status: str, detail: str) -> None:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "detail": detail,
        "signal_id": payload["signal_id"],
        "symbol": payload["symbol"],
        "direction": payload["direction"],
        "entry": payload["entry"],
        "sl": payload["sl"],
        "tp1": payload["tp1"],
        "tp2": payload["tp2"],
        "risk_pct": payload["risk_pct"],
        "score": payload["score"],
        "session": setup.session,
        "bias": setup.bias,
    }
    append_row(journal_csv, row)


def append_status(journal_csv: str | Path, symbol: str, status: str, detail: str) -> None:
    append_row(
        journal_csv,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "detail": detail,
            "signal_id": "",
            "symbol": symbol.upper(),
            "direction": "",
            "entry": "",
            "sl": "",
            "tp1": "",
            "tp2": "",
            "risk_pct": "",
            "score": "",
            "session": "",
            "bias": "",
        },
    )


def append_row(journal_csv: str | Path, row: dict) -> None:
    path = Path(journal_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live ICT sniper dry-run signal publishing.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--terminal-path", required=True)
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--admin-api-key", required=True)
    parser.add_argument("--journal-csv", default="reports/live_signal_journal.csv")
    parser.add_argument("--risk-pct", type=float, default=0.005)
    parser.add_argument("--expires-minutes", type=int, default=90)
    parser.add_argument("--min-score", type=float, default=65.0)
    parser.add_argument("--min-sweep-volume-z", type=float, default=0.4)
    parser.add_argument("--min-displacement-range-atr", type=float, default=0.7)
    parser.add_argument("--min-displacement-volume-z", type=float, default=0.0)
    parser.add_argument("--max-retest-volume-z", type=float, default=1.2)
    parser.add_argument("--sl-buffer-atr", type=float, default=0.05)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.loop:
        loop(args)
    else:
        run_once(args)


if __name__ == "__main__":
    main()
