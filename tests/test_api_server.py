import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tradingo_core.api_server import create_app
from tradingo_core.api_store import ApiSettings, JsonSignalStore


class SignalApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = ApiSettings(
            data_dir=Path(self.tmp.name),
            api_keys=frozenset({"client-key"}),
            admin_api_keys=frozenset({"admin-key"}),
        )
        store = JsonSignalStore(settings.data_dir)
        self.client = TestClient(create_app(settings=settings, store=store))

    def tearDown(self):
        self.tmp.cleanup()

    def test_publish_and_fetch_latest_signal(self):
        payload = {
            "signal_id": "sig-1",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_type": "LIMIT",
            "entry": 2300.0,
            "sl": 2298.0,
            "tp1": 2302.0,
            "tp2": 2304.0,
            "risk_pct": 0.005,
            "score": 82,
        }
        publish = self.client.post(
            "/signals/publish",
            json=payload,
            headers={"X-API-Key": "admin-key"},
        )
        self.assertEqual(publish.status_code, 200)

        latest = self.client.get(
            "/signals/latest?symbol=XAUUSD",
            headers={"X-API-Key": "client-key"},
        )
        self.assertEqual(latest.status_code, 200)
        body = latest.json()
        self.assertEqual(body["signal"]["signal_id"], "sig-1")
        self.assertEqual(body["signal"]["direction"], "BUY")

    def test_rejects_signal_below_minimum_rr(self):
        payload = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "entry_type": "LIMIT",
            "entry": 2300.0,
            "sl": 2302.0,
            "tp1": 2299.0,
            "tp2": 2297.0,
            "risk_pct": 0.005,
            "score": 70,
            "min_rr": 2.0,
        }
        response = self.client.post(
            "/signals/publish",
            json=payload,
            headers={"X-API-Key": "admin-key"},
        )
        self.assertEqual(response.status_code, 422)

    def test_client_ack_and_heartbeat(self):
        ack = self.client.post(
            "/signals/ack",
            json={
                "signal_id": "sig-2",
                "client_id": "friend-1",
                "status": "DRY_RUN",
                "message": "live disabled",
            },
            headers={"X-API-Key": "client-key"},
        )
        self.assertEqual(ack.status_code, 200)

        hb = self.client.post(
            "/accounts/heartbeat",
            json={
                "client_id": "friend-1",
                "broker": "Vantage",
                "account_login": "123",
                "balance": 10000,
                "equity": 10010,
                "symbol": "XAUUSD",
            },
            headers={"X-API-Key": "client-key"},
        )
        self.assertEqual(hb.status_code, 200)

        heartbeats = self.client.get(
            "/accounts/heartbeats",
            headers={"X-API-Key": "admin-key"},
        )
        self.assertEqual(heartbeats.status_code, 200)
        self.assertEqual(heartbeats.json()["heartbeats"][0]["client_id"], "friend-1")

    def test_requires_api_key(self):
        response = self.client.get("/signals/latest?symbol=XAUUSD")
        self.assertEqual(response.status_code, 401)

    def test_latest_accepts_single_object_signal_file(self):
        signal_file = Path(self.tmp.name) / "signals.json"
        signal_file.write_text(
            """{
              "signal_id": "legacy-single",
              "symbol": "XAUUSD",
              "direction": "SELL",
              "entry_type": "LIMIT",
              "entry": 2300.0,
              "sl": 2302.0,
              "tp1": 2298.0,
              "tp2": 2296.0,
              "risk_pct": 0.005,
              "score": 75,
              "status": "ACTIVE"
            }""",
            encoding="utf-8",
        )
        latest = self.client.get(
            "/signals/latest?symbol=XAUUSD",
            headers={"X-API-Key": "client-key"},
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["signal"]["signal_id"], "legacy-single")


if __name__ == "__main__":
    unittest.main()
