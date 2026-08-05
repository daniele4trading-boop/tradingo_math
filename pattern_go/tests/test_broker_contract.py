"""Regressioni sui difetti emersi dal test contro il conto demo Velotrade.

Ognuno di questi test corrisponde a un errore reale restituito dal broker o a un
comportamento che avrebbe prodotto ordini insensati.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pattern_go.config import ConfigError, load_config
from pattern_go.runner import Runner
from pattern_go.types import ExitReason

from .test_engine import short_setup_bars
from .test_runner import FakeClient, make_config


def test_candles_are_requested_with_an_explicit_to_time(tmp_path):
    """Senza `toTime`: errorCode 32 e il servizio non parte mai."""
    captured = {}

    class Client(FakeClient):
        def candles(self, symbol, timeframe, from_time, to_time=None):
            captured["to_time"] = to_time
            return []

    runner = Runner(make_config(tmp_path), Client())
    runner._closed_bars("M5", datetime.now(UTC) - timedelta(hours=1))
    assert isinstance(captured["to_time"], datetime)


def test_close_uses_the_position_code_returned_at_fill(tmp_path):
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)
    assert engine.trade.position_id == "P1"

    runner._close(engine, ExitReason.MANUAL.value)
    assert client.closed and client.closed[0]["position_code"] == "P1"
    assert engine.trade is None


def test_close_recovers_the_position_code_from_the_broker_after_a_restart(tmp_path):
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)
    engine.trade.position_id = None  # stato perso al riavvio
    client._positions = [{"positionCode": "P9", "symbol": "XAU", "openPrice": 3975.0}]

    runner._close(engine, ExitReason.RISK_GUARD.value)
    assert client.closed[0]["position_code"] == "P9"


def test_close_is_reported_as_failed_when_no_position_matches(tmp_path):
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)
    engine.trade.position_id = None
    client._positions = []

    runner._close(engine, ExitReason.RISK_GUARD.value)
    assert client.closed == []
    assert engine.trade is not None  # il trade resta aperto: va segnalato, non dimenticato
    failed = [r for r in _journal(tmp_path) if r["event"] == "CLOSE_FAILED"]
    assert failed and "positionCode" in failed[0]["error"]


def test_each_close_attempt_uses_a_fresh_order_code(tmp_path):
    """Il broker rifiuta orderCode duplicati: un secondo tentativo deve cambiarlo."""
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)
    trade = engine.trade

    runner._close(engine, ExitReason.MANUAL.value)
    engine.trade = trade  # simula un secondo tentativo sullo stesso trade
    client._positions = [{"positionCode": "P1", "symbol": "XAU", "openPrice": 3975.0}]
    runner._close(engine, ExitReason.MANUAL.value)
    codes = [c["client_order_id"] for c in client.closed]
    assert len(codes) == len(set(codes))


@pytest.mark.parametrize(
    ("side_bars", "price", "reason"),
    [
        ("short", 3991.0, ExitReason.STOP_LOSS.value),  # sopra lo stop a 3990
        ("short", 3950.0, ExitReason.TAKE_PROFIT.value),  # sotto il TP a 3952.5
    ],
)
def test_stop_and_target_are_enforced_by_the_runner(tmp_path, side_bars, price, reason):
    """Il broker non accetta SL/TP collegati: li sorveglia il runner."""
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)

    from pattern_go.dxtrade import Quote

    client.quote = lambda symbol: Quote(symbol, price - 0.01, price, datetime.now(UTC))
    runner._check_protective_exits(client.quote("XAU"))
    closed = [r for r in _journal(tmp_path) if r["event"] == "TRADE_CLOSED"]
    assert closed and closed[0]["exit_reason"] == reason


def test_protective_exit_does_not_fire_inside_the_range(tmp_path):
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        runner._execute(engine, engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok")), client.quote("X"))
    client.fill(3975.0)
    runner._detect_fill(engine)
    from pattern_go.dxtrade import Quote

    # short a 3975, SL 3990, TP 3952.5: 3970 sta dentro il range
    inside = Quote("XAU", 3969.99, 3970.0, datetime.now(UTC))
    runner._check_protective_exits(inside)
    assert engine.trade is not None and client.closed == []


# --- validazione della configurazione ---------------------------------------


def _raw_config():
    return json.loads((Path(__file__).parent.parent / "config.example.json").read_text())


def _write(tmp_path, raw):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    return path


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    monkeypatch.setenv("DXTRADE_USERNAME", "u")
    monkeypatch.setenv("DXTRADE_PASSWORD", "p")


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("risk", "risk_fraction"), -0.05, "risk_fraction"),
        (("risk", "risk_fraction"), 0.0, "risk_fraction"),
        (("risk", "max_dd_pct"), 1.5, "max_dd_pct"),
        (("risk", "daily_loss_pct"), 0.0, "daily_loss_pct"),
        (("risk", "min_quantity"), 0.0, "min_quantity"),
        (("risk", "max_open_positions"), 0, "posizioni aperte"),
        (("account", "cap_size"), 5_000.0, "cap_size"),
        (("account", "initial_balance"), -1.0, "initial_balance"),
    ],
)
def test_absurd_values_are_rejected_at_load(tmp_path, path, value, expected):
    raw = _raw_config()
    raw[path[0]][path[1]] = value
    with pytest.raises(ConfigError, match=expected):
        load_config(_write(tmp_path, raw))


def test_guard_thresholds_must_be_ordered(tmp_path):
    raw = _raw_config()
    raw["risk"]["block_new_at_allowance_used"] = 0.9
    raw["risk"]["close_all_at_allowance_used"] = 0.5
    with pytest.raises(ConfigError, match="deve precedere"):
        load_config(_write(tmp_path, raw))


@pytest.mark.parametrize("section", ["broker", "risk", "account", "strategies"])
def test_missing_sections_give_a_clear_error(tmp_path, section):
    raw = _raw_config()
    del raw[section]
    with pytest.raises(ConfigError, match=f"'{section}'"):
        load_config(_write(tmp_path, raw))


def test_no_sessions_is_rejected(tmp_path):
    raw = _raw_config()
    raw["sessions"] = []
    with pytest.raises(ConfigError, match="sessione"):
        load_config(_write(tmp_path, raw))


def _journal(tmp_path):
    out = []
    for path in (tmp_path / "logs").glob("journal_*.jsonl"):
        out += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return out
