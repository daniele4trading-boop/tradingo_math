"""Tests for bridge_core utilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TG_ROOT = Path(__file__).resolve().parents[1]
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))

from bridge_core import (
    ProcessedMessageStore,
    atomic_write_text,
)


def test_atomic_write_no_partial_read(tmp_path: Path):
    target = tmp_path / "signal_ch1.json"
    payload = json.dumps({"action": "OPEN", "symbol": "XAUUSD"}, indent=2)
    atomic_write_text(target, payload)
    assert target.read_text(encoding="utf-8") == payload


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
