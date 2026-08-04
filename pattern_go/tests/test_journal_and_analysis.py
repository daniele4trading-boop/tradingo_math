import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pattern_go.analyze_logs import build_summary, collect, load_records
from pattern_go.analyze_logs import main as analyze_main
from pattern_go.config import load_config
from pattern_go.journal import Journal
from pattern_go.report import summarize, write_daily_report
from pattern_go.strategy import EntryFilters, compute_features
from pattern_go.types import Bar, OpenTrade, PendingOrder, Side

T = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _order(strategy="M5", spread=0.5, risk=15.0):
    prev = Bar(T, 4000, 4004, 3996, 4003)
    cur = Bar(T + timedelta(minutes=5), 4003, 4004, 3992, 3993)
    return PendingOrder(
        strategy=strategy,
        side=Side.SHORT,
        trigger_price=3992.0,
        stop_loss=4004.0,
        take_profit=3974.0,
        risk=risk,
        quantity=1.0,
        client_order_id=f"PG-{strategy}-S-20260805T080500",
        signal_bar_index=1,
        signal_bar_time=cur.time,
        expires_after_bar_index=2,
        spread_at_signal=spread,
        features=compute_features(prev, cur, risk, spread),
    )


def _trade(order, fill=3991.7):
    return OpenTrade(
        strategy=order.strategy,
        side=order.side,
        quantity=order.quantity,
        entry_price=fill,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        risk=order.risk,
        entry_bar_index=2,
        entry_time=T + timedelta(minutes=10),
        client_order_id=order.client_order_id,
        theoretical_entry_price=order.trigger_price,
    )


def test_journal_writes_one_json_object_per_line(tmp_path):
    journal = Journal(tmp_path)
    order = _order()
    journal.order_event("ORDER_PLACED", order)
    journal.trade_opened(_trade(order), order)
    files = list(tmp_path.glob("journal_*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert [r["event"] for r in records] == ["ORDER_PLACED", "TRADE_OPENED"]
    assert records[0]["theoretical_entry_price"] == 3992.0
    assert records[0]["spread_at_signal"] == 0.5
    assert records[0]["risk_spread_mult"] == 30.0


def test_slippage_is_logged_on_every_opened_trade(tmp_path):
    journal = Journal(tmp_path)
    order = _order()
    record = journal.trade_opened(_trade(order, fill=3991.7), order)
    # short eseguito 0.30 sotto il trigger: slippage sfavorevole
    assert record["slippage"] == pytest.approx(0.3)


def test_r_realized_is_computed_on_close(tmp_path):
    journal = Journal(tmp_path)
    order = _order()
    trade = _trade(order, fill=3992.0)
    record = journal.trade_closed(trade, exit_price=3974.0, reason="TAKE_PROFIT", pnl=18.0)
    assert record["r_realized"] == 1.2


def test_daily_report_aggregates_the_journal(tmp_path):
    journal = Journal(tmp_path / "logs")
    order = _order()
    journal.order_event("ORDER_PLACED", order)
    trade = _trade(order, fill=3992.0)
    journal.trade_opened(trade, order)
    journal.trade_closed(trade, exit_price=3974.0, reason="TAKE_PROFIT", pnl=18.0)
    journal.write("SIGNAL_REJECTED", strategy="M5", reason="filters", failed=["body2_frac"])

    day = datetime.now(UTC).strftime("%Y%m%d")
    path = write_daily_report(
        log_dir=tmp_path / "logs",
        report_dir=tmp_path / "reports",
        day=day,
        equity=10_018.0,
        effective_floor=9_700.0,
    )
    text = path.read_text()
    assert "Pattern GO — report" in text and "M5" in text
    summary = json.loads((tmp_path / "reports" / f"report_{day}.json").read_text())
    assert summary["strategies"]["M5"]["trades"] == 1
    assert summary["strategies"]["M5"]["signals_rejected"] == 1


def test_summarize_handles_an_empty_journal(tmp_path):
    assert summarize([]) == {"strategies": {}, "errors": 0}


def test_analysis_flags_slippage_above_the_shutdown_threshold(tmp_path):
    journal = Journal(tmp_path)
    order = _order()
    journal.order_event("ORDER_PLACED", order)
    # 0.40 USD = 40 punti di slippage, sopra la soglia di 30 punti su M5
    trade = _trade(order, fill=3991.6)
    journal.trade_opened(trade, order)
    journal.trade_closed(trade, exit_price=3974.0, reason="TAKE_PROFIT", pnl=17.6)

    summary = build_summary(collect(load_records(tmp_path, None, None)))
    m5 = summary["strategies"]["M5"]
    assert m5["avg_slippage_points"] == pytest.approx(40.0)
    assert m5["avg_spread_points"] == pytest.approx(50.0)
    assert m5["estimated_round_trip_points"] == pytest.approx(130.0)
    assert any("criterio di disattivazione" in w for w in summary["warnings"])
    assert any("break-even" in w for w in summary["warnings"])


def test_analysis_cli_returns_nonzero_when_there_are_warnings(tmp_path, capsys):
    journal = Journal(tmp_path)
    order = _order()
    trade = _trade(order, fill=3991.0)
    journal.trade_opened(trade, order)
    journal.trade_closed(trade, exit_price=3974.0, reason="TAKE_PROFIT", pnl=17.0)
    assert analyze_main(["--log-dir", str(tmp_path)]) == 1
    assert "slippage medio" in capsys.readouterr().out


def test_analysis_counts_unfilled_orders_for_the_fill_rate(tmp_path):
    journal = Journal(tmp_path)
    order = _order()
    journal.order_event("ORDER_PLACED", order)
    journal.order_event("ORDER_PLACED", order)
    journal.order_event("ORDER_CANCELLED", order, reason="not_triggered_within_one_bar")
    summary = build_summary(collect(load_records(tmp_path, None, None)))
    assert summary["strategies"]["M5"]["fill_rate"] == pytest.approx(0.5)


def test_example_config_loads_and_carries_the_velotrade_rules(monkeypatch):
    monkeypatch.setenv("DXTRADE_USERNAME", "u")
    monkeypatch.setenv("DXTRADE_PASSWORD", "p")
    cfg = load_config(Path(__file__).parent.parent / "config.example.json")
    assert cfg.risk.max_dd_pct == 0.03 and cfg.risk.daily_loss_pct == 0.03
    assert cfg.risk.risk_fraction == 0.05
    assert cfg.risk.max_open_positions == 2
    assert cfg.broker.symbol == "XAU"
    assert {s.name for s in cfg.strategies} == {"M5", "M15"}
    m5 = next(s for s in cfg.strategies if s.name == "M5")
    assert m5.filters == EntryFilters(0.741, 4.941, 1.142, 1.872)
    assert [s.name for s in cfg.sessions] == ["london", "newyork"]


def test_config_requires_the_credentials_in_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("DXTRADE_USERNAME", raising=False)
    raw = json.loads((Path(__file__).parent.parent / "config.example.json").read_text())
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    try:
        load_config(path)
    except ValueError as exc:
        assert "DXTRADE_USERNAME" in str(exc)
    else:
        raise AssertionError("atteso ValueError sulle credenziali mancanti")
