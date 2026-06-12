import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tests.test_ict_sniper import synthetic_bullish_m1
from tradingo_core.ict_sniper import ICTSniperConfig, ICTSniperStrategy
from tradingo_core.signal_engine import make_signal_id, setup_to_payload, signal_already_seen, append_signal


class SignalEngineTest(unittest.TestCase):
    def _setup(self):
        cfg = ICTSniperConfig(
            htf_timeframe="5min",
            setup_timeframe="1min",
            volume_z_window=20,
            atr_z_window=20,
            min_sweep_volume_z=0.2,
            min_displacement_range_atr=0.7,
            min_displacement_volume_z=0.2,
            min_score=55.0,
            max_fvg_age_bars=15,
        )
        setup = ICTSniperStrategy(cfg).find_setup(synthetic_bullish_m1().iloc[:252])
        self.assertIsNotNone(setup)
        return setup

    def test_signal_payload_respects_rr_and_metadata(self):
        setup = self._setup()
        signal_id = make_signal_id("XAUUSD", setup)
        payload = setup_to_payload("XAUUSD", setup, signal_id, 0.005, 90)
        self.assertEqual(payload["signal_id"], signal_id)
        self.assertEqual(payload["symbol"], "XAUUSD")
        self.assertEqual(payload["direction"], "BUY")
        self.assertGreaterEqual(abs(payload["tp2"] - payload["entry"]) / abs(payload["entry"] - payload["sl"]), 1.99)
        self.assertIn("session", payload["metadata"])

    def test_journal_deduplicates_signal_ids(self):
        setup = self._setup()
        signal_id = make_signal_id("XAUUSD", setup)
        payload = setup_to_payload("XAUUSD", setup, signal_id, 0.005, 90)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.csv"
            self.assertFalse(signal_already_seen(path, signal_id))
            append_signal(path, payload, setup, "PUBLISHED", "{}")
            self.assertTrue(signal_already_seen(path, signal_id))


if __name__ == "__main__":
    unittest.main()
