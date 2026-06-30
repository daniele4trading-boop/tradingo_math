# AGENTS.md

## Cursor Cloud specific instructions

This repo is a Python algorithmic trading project ("TradinGo") for XAUUSD (Gold). It contains two loosely-coupled products that share `config.json`:

- **Live MT5 dual-account trading system** (root: `tradingo_system.py`, `tradingo_prop*.py`, `tradingo_hedge.py`, `dashboard.py`, `check_mt5.py`, etc.). Depends on the `MetaTrader5` package, which is **Windows-only**, plus installed MT5 `terminal64.exe` executables at hard-coded `C:/...` paths and live broker credentials. **This product cannot run on the Linux Cloud VM** — do not try to `pip install MetaTrader5` or run these scripts here; the `import MetaTrader5` fails on Linux.
- **LQS-MTF backtest / strategy engine** (`strategies/`, `backtest/`, `scripts/`, `tests/`). Pure pandas/numpy — this is the part that runs and is testable on Linux.

There is **no `requirements.txt`/`pyproject.toml`/lockfile**; dependencies are inferred from imports. The startup update script installs them (`pandas`, `numpy`, `pytest`, `pyarrow`).

### Running things (LQS-MTF, the Linux-testable scope)

All commands need `PYTHONPATH` set to the repo root (scripts also self-insert it, but tests need it):

- **Unit tests:** `PYTHONPATH=/workspace python3 -m pytest tests/ -q` (generate synthetic data internally; no market data or MT5 needed).
- **Backtest:** `PYTHONPATH=/workspace python3 scripts/run_backtest.py --data-dir data/XAUUSD/M1`
- **Optimizer / diagnostics:** `scripts/optimize_lqs.py`, `scripts/diagnose_lqs.py` (same `--data-dir`).

### Data gotcha (important)

- `data/XAUUSD/` is **gitignored** and ships empty (only `.gitkeep`). `run_backtest.py`, `optimize_lqs.py`, and `diagnose_lqs.py` **require** historical XAUUSD M1 CSVs in `data/XAUUSD/M1/*.csv` and raise `FileNotFoundError` without them.
- Broker CSV format expected by `backtest/data_loader.py`: `time,open,high,low,close,tick_volume,spread,real_volume` (UTC). Parquet is also supported via `--parquet-dir` (needs `pyarrow`).
- For a quick end-to-end smoke test without real data, generate synthetic M1 CSVs in that directory (random-walk OHLC in the format above). Real-data backtests require user-supplied broker/Dukascopy exports.
- `results/*.csv` and `results/*.json` are also gitignored (backtest outputs).

### Notes

- A full backtest on ~100k M1 bars is slow (minutes). The bar-by-bar engine warms up 200 M5 bars before scanning.
- The `dashboard.py` Streamlit app reads a Windows-path JSON state file by default and targets the live system; it is not part of the Linux-testable flow.
