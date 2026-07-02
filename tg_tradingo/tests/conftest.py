"""Pytest setup: isolated config and state paths before bridge import."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

TG_ROOT = Path(__file__).resolve().parents[1]
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))


@pytest.fixture(scope="session")
def tg_root(tmp_path_factory) -> Path:
    return TG_ROOT


@pytest.fixture
def channel_configs(tg_root: Path) -> dict:
    example = json.loads((tg_root / "tradingo_config.example.json").read_text(encoding="utf-8"))
    return {ch["id"]: ch for ch in example["channels"]}


@pytest.fixture
def bridge_state(tmp_path: Path):
    from bridge_core import BridgeState

    return BridgeState(tmp_path / "bridge_state.json")
