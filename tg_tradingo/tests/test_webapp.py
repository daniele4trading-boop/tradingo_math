"""Webapp auth + collector tests (no network, no FastAPI server needed)."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TG_ROOT = Path(__file__).resolve().parents[1]
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))

from webapp.auth import (
    RateLimiter,
    SessionManager,
    hash_password,
    verify_password,
)
from webapp.collector import Collector, STATUS_CRIT, STATUS_OFF, STATUS_OK


class TestPasswords:
    def test_hash_and_verify_roundtrip(self):
        h = hash_password("s3cret-pass", iterations=1000)
        assert h.startswith("pbkdf2$1000$")
        assert verify_password("s3cret-pass", h)
        assert not verify_password("wrong", h)

    def test_verify_rejects_garbage(self):
        assert not verify_password("x", "not-a-hash")
        assert not verify_password("x", "")


class TestSessions:
    def test_create_and_verify(self):
        sm = SessionManager("topsecret", hours=1)
        token = sm.create("daniele")
        assert sm.verify(token) == "daniele"

    def test_tampered_token_rejected(self):
        sm = SessionManager("topsecret", hours=1)
        token = sm.create("daniele")
        assert sm.verify(token + "x") is None
        parts = token.split(".")
        forged = f"{parts[0]}.{int(time.time()) + 99999}.{parts[2]}"
        assert sm.verify(forged) is None

    def test_expired_token_rejected(self):
        sm = SessionManager("topsecret", hours=-1)
        token = sm.create("daniele")
        assert sm.verify(token) is None

    def test_different_secret_rejected(self):
        token = SessionManager("secret-a", hours=1).create("daniele")
        assert SessionManager("secret-b", hours=1).verify(token) is None

    def test_empty_secret_refused(self):
        try:
            SessionManager("", hours=1)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestRateLimiter:
    def test_locks_after_max_attempts(self):
        rl = RateLimiter(max_attempts=3, window_sec=60)
        for _ in range(3):
            assert not rl.is_locked("ip:1.2.3.4")
            rl.record_failure("ip:1.2.3.4")
        assert rl.is_locked("ip:1.2.3.4")
        assert rl.retry_after_sec("ip:1.2.3.4") > 0

    def test_reset_unlocks(self):
        rl = RateLimiter(max_attempts=1, window_sec=60)
        rl.record_failure("user:x")
        assert rl.is_locked("user:x")
        rl.reset("user:x")
        assert not rl.is_locked("user:x")

    def test_window_expiry_unlocks(self):
        rl = RateLimiter(max_attempts=1, window_sec=0)
        rl.record_failure("k")
        assert not rl.is_locked("k")


def _make_env(tmp_path: Path, hb_age_sec: int = 5) -> dict:
    signals = tmp_path / "signals"
    journal = tmp_path / "journal" / "bridge_events"
    signals.mkdir(parents=True)
    journal.mkdir(parents=True)

    hb_ts = (datetime.now(timezone.utc) - timedelta(seconds=hb_age_sec)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    (signals / "tradingo_heartbeat.json").write_text(
        json.dumps({"ts_utc": hb_ts, "source": "tradingo_bridge"}), encoding="utf-8"
    )

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    rows = [
        {"ts_utc": hb_ts, "channel_id": "CH_ORO", "event_type": "NEW",
         "outcome": "EMITTED", "action": "OPEN", "signal_id": "abc123",
         "raw_text": "XAUUSD buy 4042 TP 4048 SL 4038"},
        {"ts_utc": hb_ts, "channel_id": "CH_ORO", "event_type": "NEW",
         "outcome": "IGNORED_PATTERN", "raw_text": "Take profit preso +60 pips"},
        {"ts_utc": hb_ts, "channel_id": "CH_GOLD", "event_type": "EDIT",
         "outcome": "UNPARSED", "raw_text": "boh"},
    ]
    with (journal / f"events_{day}.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    tcfg = tmp_path / "tradingo_config.json"
    tcfg.write_text(json.dumps({
        "channels": [
            {"id": "CH_ORO", "name": "Sala ORO VIP", "enabled": True},
            {"id": "CH_GOLD", "name": "Sala GOLD VIP", "enabled": True},
        ]
    }), encoding="utf-8")

    return {
        "refresh_seconds": 15,
        "max_events": 20,
        "tradingo_config": str(tcfg),
        "checks": {
            "bridge_heartbeat": str(signals / "tradingo_heartbeat.json"),
            "heartbeat_warn_sec": 90,
            "heartbeat_crit_sec": 180,
            "journal_dir": str(journal),
            "mt5_process": "",
            "friend_host": "",
            "friend_share": "",
            "friend_heartbeat": "",
        },
    }


class TestCollector:
    def test_snapshot_green_heartbeat_and_channels(self, tmp_path: Path):
        col = Collector(_make_env(tmp_path, hb_age_sec=5))
        snap = col.collect_once()
        assert snap["lights"]["bridge"]["status"] == STATUS_OK
        assert snap["lights"]["friend_link"]["status"] == STATUS_OFF
        oro = next(c for c in snap["channels"] if c["id"] == "CH_ORO")
        assert oro["today"]["emitted"] == 1
        assert oro["today"]["ignored"] == 1
        assert oro["last_emitted"]["action"] == "OPEN"
        gold = next(c for c in snap["channels"] if c["id"] == "CH_GOLD")
        assert gold["today"]["unparsed"] == 1
        assert len(snap["events"]) == 3
        # newest first
        assert snap["events"][0]["channel_id"] == "CH_GOLD"

    def test_stale_heartbeat_is_crit(self, tmp_path: Path):
        col = Collector(_make_env(tmp_path, hb_age_sec=999))
        snap = col.collect_once()
        assert snap["lights"]["bridge"]["status"] == STATUS_CRIT
        assert snap["overall"] == STATUS_CRIT

    def test_missing_heartbeat_is_crit(self, tmp_path: Path):
        cfg = _make_env(tmp_path)
        cfg["checks"]["bridge_heartbeat"] = str(tmp_path / "missing.json")
        snap = Collector(cfg).collect_once()
        assert snap["lights"]["bridge"]["status"] == STATUS_CRIT
