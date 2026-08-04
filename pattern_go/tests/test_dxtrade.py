import json
from datetime import UTC, datetime

import pytest
import requests

from pattern_go.dxtrade import AuthError, DXTradeClient, DXTradeError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    @property
    def content(self):
        return self.text.encode()

    def json(self):
        return self._payload


class FakeSession:
    """Sessione HTTP scriptata: ogni chiamata consuma la prossima risposta."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def post(self, url, json=None, timeout=None, **kw):
        return self.request("POST", url, json=json, timeout=timeout, **kw)

    def request(self, method, url, json=None, params=None, headers=None, timeout=None):
        self.calls.append((method, url, headers.get("Authorization") if headers else None))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(script, **kw):
    return DXTradeClient(
        base_url="https://broker.test/dxsca-web",
        username="u",
        password="p",
        account="default:1",
        session=FakeSession(script),
        **kw,
    )


def test_login_stores_the_session_token():
    c = client([FakeResponse(payload={"sessionToken": "tok", "timeout": "00:30:00"})])
    assert c.login() == "tok"


def test_login_failure_raises_auth_error():
    c = client([FakeResponse(status_code=401, payload={"errorCode": "3"})])
    with pytest.raises(AuthError):
        c.login()


def test_expired_session_triggers_a_new_login_and_the_request_succeeds(monkeypatch):
    monkeypatch.setattr("pattern_go.dxtrade.time.sleep", lambda _s: None)
    c = client(
        [
            FakeResponse(payload={"sessionToken": "old"}),  # login iniziale
            FakeResponse(status_code=401),  # sessione scaduta
            FakeResponse(payload={"sessionToken": "new"}),  # re-login automatico
            FakeResponse(payload={"metrics": [_metrics()]}),
        ]
    )
    c.login()
    metrics = c.metrics()
    assert metrics.equity == 10_000.0
    assert c._token == "new"


def test_network_errors_are_retried_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr("pattern_go.dxtrade.time.sleep", sleeps.append)
    c = client(
        [
            FakeResponse(payload={"sessionToken": "tok"}),
            requests.ConnectionError("boom"),
            requests.ConnectionError("boom"),
            FakeResponse(payload={"metrics": [_metrics()]}),
        ]
    )
    c.login()
    assert c.metrics().balance == 10_000.0
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]


def test_server_errors_give_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("pattern_go.dxtrade.time.sleep", lambda _s: None)
    c = client(
        [FakeResponse(payload={"sessionToken": "tok"})] + [FakeResponse(status_code=503)] * 3,
        max_retries=3,
    )
    c.login()
    with pytest.raises(DXTradeError):
        c.metrics()


def test_client_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr("pattern_go.dxtrade.time.sleep", lambda _s: None)
    c = client(
        [
            FakeResponse(payload={"sessionToken": "tok"}),
            FakeResponse(status_code=400, text="bad quantity"),
        ]
    )
    c.login()
    with pytest.raises(DXTradeError, match="bad quantity"):
        c.metrics()


def test_quote_exposes_the_spread():
    c = client(
        [
            FakeResponse(payload={"sessionToken": "tok"}),
            FakeResponse(
                payload={
                    "events": [
                        {
                            "symbol": "XAU",
                            "type": "Quote",
                            "bid": 4063.55,
                            "ask": 4065.11,
                            "time": "2026-08-04T22:02:04Z",
                        }
                    ]
                }
            ),
        ]
    )
    c.login()
    quote = c.quote("XAU")
    assert quote.spread == pytest.approx(1.56)
    assert quote.time == datetime(2026, 8, 4, 22, 2, 4, tzinfo=UTC)


def test_candles_are_parsed_and_sorted():
    c = client(
        [
            FakeResponse(payload={"sessionToken": "tok"}),
            FakeResponse(
                payload={
                    "events": [
                        _candle("2026-08-04T18:05:00Z", 4070.46),
                        _candle("2026-08-04T18:00:00Z", 4070.84),
                    ]
                }
            ),
        ]
    )
    c.login()
    bars = c.candles("XAU", "M5", datetime(2026, 8, 4, 18, 0, tzinfo=UTC))
    assert [bar.open for bar in bars] == [4070.84, 4070.46]


def test_instrument_reports_gold_quantity_granularity():
    c = client(
        [
            FakeResponse(payload={"sessionToken": "tok"}),
            FakeResponse(
                payload={
                    "instruments": [
                        {
                            "symbol": "XAU",
                            "priceIncrement": 0.01,
                            "quantityIncrement": 0.01,
                            "lotSize": 1.0,
                            "multiplier": 1.0,
                            "currency": "USD",
                        }
                    ]
                }
            ),
        ]
    )
    c.login()
    instrument = c.instrument("XAU")
    assert (instrument.lot_size, instrument.quantity_increment) == (1.0, 0.01)


def test_stop_order_carries_a_deterministic_order_code_and_sl_tp():
    session = FakeSession(
        [FakeResponse(payload={"sessionToken": "tok"}), FakeResponse(payload={"orderId": 7})]
    )
    c = DXTradeClient(
        base_url="https://broker.test/dxsca-web",
        username="u",
        password="p",
        account="default:1",
        session=session,
    )
    c.login()
    captured = {}
    original = session.request

    def spy(method, url, json=None, **kw):
        captured.update(json or {})
        return original(method, url, json=json, **kw)

    session.request = spy
    c.place_stop_order(
        symbol="XAU",
        side="SELL",
        quantity=4.08,
        stop_price=3975.0,
        client_order_id="PG-M5-S-20260804T073500",
        stop_loss=3990.0,
        take_profit=3952.5,
    )
    assert captured["orderCode"] == "PG-M5-S-20260804T073500"
    assert captured["type"] == "STOP" and captured["side"] == "SELL"
    codes = {r["orderCode"]: r["side"] for r in captured["orderRequests"]}
    assert codes == {
        "PG-M5-S-20260804T073500-SL": "BUY",
        "PG-M5-S-20260804T073500-TP": "BUY",
    }


def _metrics():
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "openPL": 0.0,
        "openPositionsCount": 0,
        "openOrdersCount": 0,
    }


def _candle(ts, price):
    return {
        "symbol": "XAU",
        "type": "Candle",
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price,
        "volume": 1.0,
        "time": ts,
    }
