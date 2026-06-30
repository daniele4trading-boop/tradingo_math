from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from core.config import STATE_DIR


SNAPSHOT_PATH = STATE_DIR / "risk" / "equity_snapshots.json"


def _load_store() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        with SNAPSHOT_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_store(data: dict[str, Any]) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def update_equity_snapshot(profile_name: str, equity: float) -> tuple[float, float]:
    """Update daily start equity and peak equity for drawdown tracking."""
    today = date.today().isoformat()
    store = _load_store()
    entry = store.get(profile_name, {})
    if not isinstance(entry, dict):
        entry = {}

    if entry.get("date") != today:
        entry = {
            "date": today,
            "start_equity": equity,
            "peak_equity": equity,
        }
    else:
        entry["date"] = today
        entry["start_equity"] = float(entry.get("start_equity", equity))
        entry["peak_equity"] = max(float(entry.get("peak_equity", equity)), equity)

    store[profile_name] = entry
    _save_store(store)
    return float(entry["start_equity"]), float(entry["peak_equity"])


def daily_loss_pct(start_equity: float, equity: float) -> float:
    if start_equity <= 0:
        return 0.0
    loss = start_equity - equity
    if loss <= 0:
        return 0.0
    return (loss / start_equity) * 100.0


def drawdown_pct(peak_equity: float, equity: float) -> float:
    if peak_equity <= 0:
        return 0.0
    drop = peak_equity - equity
    if drop <= 0:
        return 0.0
    return (drop / peak_equity) * 100.0
