from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingo_lab.bars import build_bars_from_ticks, discover_tick_files, load_tick_files, save_bars
from tradingo_lab.config import ensure_storage_dirs, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OHLC bars from exported MT5 ticks.")
    parser.add_argument("--config", default="config/research_config.json")
    parser.add_argument("--timeframe", default="1min", help="Pandas resample rule, e.g. 1min, 5min, 15min.")
    parser.add_argument("--ticks", nargs="*", help="Optional explicit tick parquet files.")
    args = parser.parse_args()

    config = load_config(args.config)
    ensure_storage_dirs(config)
    tick_files = [Path(path) for path in args.ticks] if args.ticks else discover_tick_files(config)
    if not tick_files:
        raise FileNotFoundError(f"No tick parquet files found under {config.storage.ticks_dir / config.symbol}")

    ticks = load_tick_files(tick_files)
    bars = build_bars_from_ticks(ticks, timeframe=args.timeframe)
    output_path = save_bars(config, bars, args.timeframe)
    print(f"Loaded tick files: {len(tick_files)}")
    print(f"Bars: {len(bars)}")
    print(f"Written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
