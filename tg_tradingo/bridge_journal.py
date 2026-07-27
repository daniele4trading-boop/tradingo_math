"""Structured bridge event journal (JSONL, one file per UTC day)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge_core import atomic_write_text_timed, is_unc_path

log = logging.getLogger("TradinGo")


def journal_root(config: dict) -> Path:
    base = Path(config.get("paths", {}).get("base", r"C:\TG_TradinGo"))
    root = Path(config.get("paths", {}).get("journal", base / "journal"))
    return root


def bridge_events_path(config: dict, day: datetime | None = None) -> Path:
    day = day or datetime.now(timezone.utc)
    d = journal_root(config) / "bridge_events"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"events_{day.strftime('%Y%m%d')}.jsonl"


def append_bridge_event(config: dict, row: dict[str, Any]) -> None:
    """Append one JSON line; never raise into the bridge hot path."""
    try:
        path = bridge_events_path(config)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        log.warning("bridge journal write failed: %s", exc)


def write_heartbeat(config: dict, interval_hint_sec: int = 30) -> None:
    """Rewrite heartbeat file for the EA (UTC timestamp).

    Uses atomic replace so the EA does not briefly see a missing file (SMB race).
    UNC targets are timed out so a hung Tailscale share cannot freeze Telethon.
    """
    try:
        signals = Path(config["paths"]["signals"])
        signals.mkdir(parents=True, exist_ok=True)
        targets = [signals]
        for inst in config.get("mt5_instances", []) or []:
            if not inst.get("enabled", True):
                continue
            p = inst.get("signals_path")
            if p:
                targets.append(Path(p))
        # De-dupe while preserving order (local first)
        seen: set[str] = set()
        ordered: list[Path] = []
        for t in sorted(targets, key=lambda x: (1 if is_unc_path(x) else 0, str(x).lower())):
            key = str(t).lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(t)
        payload = {
            "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interval_sec": interval_hint_sec,
            "source": "tradingo_bridge",
        }
        text = json.dumps(payload, indent=2)
        for t in ordered:
            try:
                t.mkdir(parents=True, exist_ok=True)
                atomic_write_text_timed(
                    t / "tradingo_heartbeat.json",
                    text,
                    retries=2 if is_unc_path(t) else 3,
                )
            except Exception as exc:
                log.warning("heartbeat write %s: %s", t, exc)
    except Exception as exc:
        log.warning("heartbeat failed: %s", exc)
