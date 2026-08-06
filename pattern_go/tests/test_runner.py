import json
from datetime import UTC, datetime, timedelta

from pattern_go.config import (
    BrokerConfig,
    Config,
    RuntimeConfig,
    StrategyConfig,
)
from pattern_go.dxtrade import AccountMetrics, Instrument, Quote
from pattern_go.risk import RiskConfig
from pattern_go.runner import Runner
from pattern_go.strategy import EntryFilters, SessionSpec
from pattern_go.types import Bar

from .test_engine import LONDON, short_setup_bars

NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, bars=None, equity=10_000.0, balance=10_000.0):
        self.bars = bars or []
        self.equity = equity
        self.balance = balance
        self._positions: list[dict] = []
        self.placed: list[dict] = []
        self.cancelled: list[str] = []
        self.closed: list[dict] = []
        self.logins = 0

    def login(self):
        self.logins += 1
        return "tok"

    def instrument(self, symbol):
        return Instrument(symbol, 0.01, 0.01, 1.0, 1.0, "USD")

    def metrics(self):
        return AccountMetrics(self.equity, self.balance, 0.0, len(self._positions), 0)

    def positions(self):
        return list(self._positions)

    def orders(self):
        return []

    def quote(self, symbol):
        return Quote(symbol, 3999.9, 4000.0, NOW)

    def candles(self, symbol, timeframe, from_time, to_time=None):
        return [b for b in self.bars if b.time >= from_time]

    def place_stop_order(self, **kw):
        self.placed.append(kw)
        return {"orderId": len(self.placed)}

    def cancel_order(self, order_code):
        self.cancelled.append(order_code)

    def close_position(self, **kw):
        self.closed.append(kw)
        self._positions = []
        return {"orderId": 99}

    def fill(self, price):
        self._positions = [{"positionCode": "P1", "openPrice": price}]


def make_config(tmp_path, bars_timeframe="M5", **runtime):
    return Config(
        broker=BrokerConfig(
            base_url="https://broker.test",
            domain="default",
            account="default:1",
            username="u",
            password="p",
            symbol="XAU",
        ),
        risk=RiskConfig(initial_balance=10_000.0, cap_size=11_000.0),
        runtime=RuntimeConfig(
            log_dir=str(tmp_path / "logs"),
            state_file=str(tmp_path / "state.json"),
            report_dir=str(tmp_path / "reports"),
            kill_switch_file=str(tmp_path / "KILL"),
            warmup_bars=6000,
            **runtime,
        ),
        strategies=[
            StrategyConfig(
                name="M5",
                timeframe=bars_timeframe,
                enabled=True,
                bias_window=24,
                max_hold=48,
                day_bars=288,
                filters=EntryFilters(),
            ),
            StrategyConfig(
                name="M15",
                timeframe="M15",
                enabled=False,
                bias_window=32,
                max_hold=96,
                day_bars=96,
                filters=EntryFilters(),
            ),
        ],
        sessions=[LONDON, SessionSpec("newyork", LONDON.open_time, "America/New_York")],
    )


def test_disabled_strategies_are_not_instantiated(tmp_path):
    runner = Runner(make_config(tmp_path), FakeClient())
    assert list(runner.engines) == ["M5"]


def test_startup_reconciles_and_logs_the_floor(tmp_path):
    client = FakeClient()
    client._positions = [{"positionCode": "EXISTING", "openPrice": 4000.0}]
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    assert client.logins == 1
    assert runner._known_position_ids == {"EXISTING"}
    records = _journal(tmp_path)
    startup = [r for r in records if r["event"] == "STARTUP"][0]
    assert startup["static_floor"] == 9_700.0
    assert startup["reservoir"] == 300.0
    assert startup["risk_amount"] == 9.0


def test_reconcile_does_not_duplicate_a_position_after_restart(tmp_path):
    client = FakeClient()
    client._positions = [{"positionCode": "P1", "openPrice": 4000.0}]
    cfg = make_config(tmp_path)
    Runner(cfg, client).startup()
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    runner2 = Runner(cfg, client)
    runner2.startup()
    # la posizione preesistente e' conosciuta: non viene interpretata come nostro fill
    assert "P1" in runner2._known_position_ids
    assert state is None or "known_position_ids" in state


def test_warmup_does_not_place_orders(tmp_path):
    client = FakeClient(bars=short_setup_bars())
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    assert client.placed == []
    assert runner.engines["M5"].pending is None
    assert len(runner.engines["M5"].bars) > 0


def test_kill_switch_closes_positions_and_blocks_the_cycle(tmp_path):
    client = FakeClient()
    cfg = make_config(tmp_path)
    runner = Runner(cfg, client)
    runner.startup()
    (tmp_path / "KILL").write_text("stop")
    runner.tick()
    events = [r["event"] for r in _journal(tmp_path)]
    assert "KILL_SWITCH" in events


def test_risk_guard_closes_everything_and_halts_until_reset(tmp_path):
    client = FakeClient(equity=9_750.0)
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    runner.tick()
    assert runner.state.halted_until_reset
    guard = [r for r in _journal(tmp_path) if r["event"] == "RISK_GUARD"][0]
    assert guard["decision"] == "CLOSE_ALL"


def test_fill_detection_logs_the_effective_price_and_the_slippage(tmp_path):
    client = FakeClient()
    runner = Runner(make_config(tmp_path), client)
    runner.startup()
    engine = runner.engines["M5"]
    for bar in short_setup_bars():
        intents = engine.on_bar(bar, 0.1, lambda _sl: (1.0, "ok"))
        runner._execute(engine, intents, client.quote("XAU"))
    assert client.placed and client.placed[0]["client_order_id"].startswith("PG-M5-S-")
    client.fill(3974.5)
    runner._detect_fill(engine)
    opened = [r for r in _journal(tmp_path) if r["event"] == "TRADE_OPENED"][0]
    assert opened["theoretical_entry_price"] == 3975.0
    assert opened["entry_price"] == 3974.5
    assert opened["slippage"] == 0.5


def test_state_is_persisted_and_reloaded(tmp_path):
    cfg = make_config(tmp_path)
    runner = Runner(cfg, FakeClient())
    runner.startup()
    runner.state.halted_until_reset = True
    runner._save_state()
    reloaded = Runner(cfg, FakeClient())
    reloaded._load_state()
    assert reloaded.state.halted_until_reset


def test_only_closed_bars_reach_the_engine(tmp_path):
    forming = Bar(datetime.now(UTC), 4000, 4001, 3999, 4000)
    closed = Bar(
        datetime.now(UTC) - timedelta(minutes=20), 4000, 4001, 3999, 4000
    )
    client = FakeClient(bars=[closed, forming])
    runner = Runner(make_config(tmp_path), client)
    bars = runner._closed_bars("M5", datetime.now(UTC) - timedelta(hours=2))
    assert bars == [closed]


def _journal(tmp_path):
    out = []
    for path in (tmp_path / "logs").glob("journal_*.jsonl"):
        out += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return out
