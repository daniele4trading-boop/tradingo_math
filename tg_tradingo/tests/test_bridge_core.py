"""Tests for bridge_core utilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

TG_ROOT = Path(__file__).resolve().parents[1]
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))

from bridge_core import (
    ProcessedMessageStore,
    atomic_write_text,
    validate_signal,
)


def test_atomic_write_no_partial_read(tmp_path: Path):
    target = tmp_path / "signal_ch1.json"
    payload = json.dumps({"action": "OPEN", "symbol": "XAUUSD"}, indent=2)
    atomic_write_text(target, payload)
    assert target.read_text(encoding="utf-8") == payload


def test_atomic_write_retries_permission_error(tmp_path: Path):
    target = tmp_path / "signal_ch_oro.json"
    payload = '{"action":"OPEN"}'
    calls = {"n": 0}
    real_replace = __import__("os").replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Access is denied", str(dst))
        return real_replace(src, dst)

    with patch("bridge_core.os.replace", side_effect=flaky_replace):
        with patch("bridge_core.time.sleep", return_value=None):
            atomic_write_text(target, payload, retries=5, backoff_ms=1)

    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == payload


def test_atomic_write_exhausted_retries(tmp_path: Path):
    target = tmp_path / "signal_ch_oro.json"

    def always_fail(src, dst):
        err = OSError(5, "Access is denied")
        err.winerror = 5
        raise err

    with patch("bridge_core.os.replace", side_effect=always_fail):
        with patch("bridge_core.time.sleep", return_value=None):
            with pytest.raises(OSError):
                atomic_write_text(target, "{}", retries=3, backoff_ms=1)


def test_dedup_new_and_edit(tmp_path: Path):
    store = ProcessedMessageStore(tmp_path / "processed.json")
    key_new = ProcessedMessageStore.make_key(-1001, 42, "NEW", "hello")
    assert not store.is_duplicate(key_new)
    store.mark_processed(key_new)
    assert store.is_duplicate(key_new)

    key_edit_a = ProcessedMessageStore.make_key(-1001, 42, "EDIT", "hello v1")
    key_edit_b = ProcessedMessageStore.make_key(-1001, 42, "EDIT", "hello v2")
    assert key_edit_a != key_edit_b
    store.mark_processed(key_edit_a)
    assert store.is_duplicate(key_edit_a)
    assert not store.is_duplicate(key_edit_b)


def test_validate_open_with_entry_range_no_entry_price():
    signal = {
        "action": "OPEN",
        "direction": "BUY",
        "symbol": "XAUUSD",
        "entry": None,
        "entry_range": [4006.0, 4007.0],
        "sl": 4004.0,
        "tp_levels": [4017.0],
        "magic_base": 14100,
    }
    ok, reason = validate_signal(signal)
    assert ok, reason


def test_validate_rejects_sl_inside_entry_range():
    signal = {
        "action": "OPEN",
        "direction": "BUY",
        "symbol": "XAUUSD",
        "entry": None,
        "entry_range": [4006.0, 4007.0],
        "sl": 4006.5,
        "tp_levels": [4017.0],
        "magic_base": 14100,
    }
    ok, reason = validate_signal(signal)
    assert not ok
    assert "range" in reason
