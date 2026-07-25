"""Smoke test for offline journal analyzer on fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TG = Path(__file__).resolve().parents[1]


def test_analyze_journal_fixture():
    cmd = [
        sys.executable,
        str(TG / "analyze_journal.py"),
        "--journal-root",
        str(TG / "docs/fixtures/journal_sample"),
        "--from",
        "2026-07-24",
        "--to",
        "2026-07-24",
        "--news-calendar",
        str(TG / "docs/fixtures/news_calendar.csv"),
        "--lot-mult",
        "ivan=0.2",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)
    assert "parser_coverage" in data
    assert data["parser_coverage"]["outcomes"].get("EMITTED", 0) >= 1
    assert "channels" in data
