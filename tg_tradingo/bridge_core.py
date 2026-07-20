"""
Core utilities for TG TradinGo bridge: state persistence, deduplication,
payload validation, and atomic JSON writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("TradinGo")

VALID_ACTIONS = frozenset({
    "NONE",
    "OPEN",
    "OPEN_NOW",
    "UPDATE_OPEN",
    "CHECK_AND_BE",
    "CHECK_AND_CLOSE_TP",
    "CLOSE_ALL_SYMBOL",
    "BREAK_EVEN_PRICE",
    "CLOSE_HALF_BE",
    "UPDATE_TP",
    "UPDATE_SL",
    "CHECK_AND_CLOSE",
})

ACTIONS_REQUIRING_DIRECTION = frozenset({
    "OPEN",
    "OPEN_NOW",
    "UPDATE_OPEN",
})

ACTIONS_REQUIRING_SYMBOL = frozenset({
    "OPEN",
    "OPEN_NOW",
    "UPDATE_OPEN",
    "UPDATE_TP",
    "UPDATE_SL",
    "CHECK_AND_CLOSE",
    "CLOSE_ALL_SYMBOL",
    "BREAK_EVEN_PRICE",
    "CLOSE_HALF_BE",
})

ACTIONS_WITH_SL_TP = frozenset({
    "OPEN",
    "UPDATE_OPEN",
})


def atomic_write_text(path: Path, payload: str) -> None:
    """Write text atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))


class BridgeState:
    """Persistent CH2 naked→complete pending state."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.ch2_pending_dir: str | None = None
        self.ch2_pending_open: bool = False
        self.load()

    def load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            ch2 = data.get("ch2_pending", {})
            self.ch2_pending_dir = ch2.get("pending_dir")
            self.ch2_pending_open = bool(ch2.get("pending_open", False))
            log.info(
                "Bridge state loaded: ch2_pending_open=%s dir=%s",
                self.ch2_pending_open,
                self.ch2_pending_dir,
            )
        except Exception as exc:
            log.warning("Could not load bridge state %s: %s", self.state_file, exc)

    def save(self) -> None:
        payload = {
            "ch2_pending": {
                "pending_open": self.ch2_pending_open,
                "pending_dir": self.ch2_pending_dir,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(self.state_file, payload)

    def set_ch2_pending(self, direction: str) -> None:
        self.ch2_pending_dir = direction
        self.ch2_pending_open = True
        self.save()

    def clear_ch2_pending(self) -> None:
        self.ch2_pending_open = False
        self.ch2_pending_dir = None
        self.save()


class EphemeralBridgeState(BridgeState):
    """In-memory CH2 state for dry-run; never reads/writes disk (Windows-safe)."""

    def __init__(self):
        self.state_file = Path("_ephemeral_")
        self.ch2_pending_dir: str | None = None
        self.ch2_pending_open: bool = False

    def load(self) -> None:
        return

    def save(self) -> None:
        return


class ProcessedMessageStore:
    """Persistent deduplication for Telegram events."""

    def __init__(self, store_file: Path, max_entries: int = 5000):
        self.store_file = store_file
        self.max_entries = max_entries
        self._keys: list[str] = []
        self._seen: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.store_file.exists():
            return
        try:
            data = json.loads(self.store_file.read_text(encoding="utf-8"))
            self._keys = list(data.get("keys", []))
            self._seen = set(self._keys)
            log.info("Loaded %d processed message keys", len(self._keys))
        except Exception as exc:
            log.warning("Could not load processed messages %s: %s", self.store_file, exc)

    def save(self) -> None:
        if len(self._keys) > self.max_entries:
            self._keys = self._keys[-self.max_entries :]
            self._seen = set(self._keys)
        atomic_write_json(
            self.store_file,
            {"keys": self._keys, "updated_at": datetime.now(timezone.utc).isoformat()},
        )

    @staticmethod
    def make_key(
        chat_id: int,
        message_id: int,
        event_type: str,
        text: str,
    ) -> str:
        if event_type == "EDIT":
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            return f"{chat_id}:{message_id}:EDIT:{digest}"
        return f"{chat_id}:{message_id}:NEW"

    def is_duplicate(self, key: str) -> bool:
        return key in self._seen

    def mark_processed(self, key: str) -> None:
        if key in self._seen:
            return
        self._keys.append(key)
        self._seen.add(key)
        self.save()


def _sl_coherent(direction: str, entry: float | None, sl: float) -> bool:
    if entry is None:
        return sl > 0
    if direction == "BUY":
        return sl < entry
    if direction == "SELL":
        return sl > entry
    return False


def _tp_coherent(direction: str, entry: float | None, tps: list[float]) -> bool:
    if not tps:
        return True
    for tp in tps:
        if tp <= 0:
            return False
        if entry is None:
            continue
        if direction == "BUY" and tp <= entry:
            return False
        if direction == "SELL" and tp >= entry:
            return False
    return True


def _entry_range_plausible(entry_range: list[float] | None) -> bool:
    if not entry_range:
        return True
    if len(entry_range) != 2:
        return False
    lo, hi = entry_range
    if lo <= 0 or hi <= 0:
        return False
    if lo > hi:
        return False
    return (hi - lo) <= 500


def _splits_valid(splits: list[float] | None) -> bool:
    if splits is None:
        return True
    if not splits:
        return False
    if any(s < 0 for s in splits):
        return False
    total = sum(splits)
    return 0.95 <= total <= 1.05


def validate_signal(signal: dict) -> tuple[bool, str]:
    """Validate payload before writing JSON for the EA."""
    action = signal.get("action")
    if action not in VALID_ACTIONS:
        return False, f"invalid action: {action!r}"

    if action in ACTIONS_REQUIRING_DIRECTION:
        direction = signal.get("direction")
        if direction not in ("BUY", "SELL"):
            return False, f"direction must be BUY/SELL, got {direction!r}"

    if action in ACTIONS_REQUIRING_SYMBOL:
        symbol = (signal.get("symbol") or "").strip()
        if not symbol:
            return False, "symbol is required"

    magic_base = signal.get("magic_base")
    if magic_base is not None:
        try:
            if int(magic_base) <= 0:
                return False, "magic_base must be positive"
        except (TypeError, ValueError):
            return False, "magic_base must be an integer"

    if not _splits_valid(signal.get("splits")):
        return False, "splits must sum to ~1.0 and be non-negative"

    if action in ACTIONS_WITH_SL_TP:
        direction = signal.get("direction", "")
        entry = signal.get("entry")
        entry_range = signal.get("entry_range")
        sl = signal.get("sl")
        tps = signal.get("tp_levels") or []

        if entry_range is not None and not _entry_range_plausible(entry_range):
            return False, "entry_range is not plausible"

        if sl is not None and direction in ("BUY", "SELL"):
            if not _sl_coherent(direction, entry, sl):
                return False, f"SL {sl} incoherent with {direction} entry {entry}"

        if tps and direction in ("BUY", "SELL"):
            if not _tp_coherent(direction, entry, tps):
                return False, f"TP levels {tps} incoherent with {direction} entry {entry}"

    if action == "OPEN_NOW":
        if signal.get("entry") is not None:
            return False, "OPEN_NOW must not include entry"
        if signal.get("sl") is not None or signal.get("tp_levels"):
            return False, "OPEN_NOW must not include SL/TP"

    return True, ""


def apply_lot_rules(signal: dict, ch: dict) -> dict:
    """Fixed lots: 0.20 with one TP, 0.10 per TP when multiple levels are set."""
    exec_cfg = ch.get("execution", {})
    lot_single = float(exec_cfg.get("fixed_lot_single", ch.get("fixed_lot_single", 0.20)))
    lot_per_tp = float(exec_cfg.get("fixed_lot_per_tp", ch.get("fixed_lot_per_tp", 0.10)))

    action = signal.get("action", "")
    if action not in ("OPEN", "OPEN_NOW", "UPDATE_OPEN"):
        return signal

    tps = signal.get("tp_levels") or []
    n_tp = len(tps)

    signal["use_fixed_lot"] = True
    signal.pop("risk_percent", None)

    if n_tp >= 2:
        signal["trades"] = n_tp
        signal["fixed_lot"] = lot_per_tp
        signal["splits"] = [round(1.0 / n_tp, 4)] * n_tp
    else:
        signal["trades"] = 1
        signal["fixed_lot"] = lot_single
        signal["splits"] = [1.0]

    return signal
