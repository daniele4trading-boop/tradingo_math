"""Parser regression tests for TG TradinGo bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TG_ROOT = Path(__file__).resolve().parents[1]
if str(TG_ROOT) not in sys.path:
    sys.path.insert(0, str(TG_ROOT))

# Import parsers without Telethon client startup side effects
from bridge_core import BridgeState, validate_signal, apply_lot_rules
from tradingo_bridge import (
    parser_sala_gold,
    parser_sala_oro,
    parser_sala_stark,
    parser_sala_vip,
    parser_zanni_vip,
)


CH1 = {
    "id": "CH1",
    "magic_base": 11000,
    "risk_percent": 0.5,
    "splits": [0.4, 0.4, 0.2],
}

CH2 = {
    "id": "CH2",
    "magic_base": 12000,
    "risk_percent": 0.5,
    "splits": [0.6, 0.4],
}

CH3 = {
    "id": "CH3",
    "magic_base": 13000,
    "fixed_lot_xauusd": 0.05,
    "fixed_lot_forex": 0.20,
}

CH4 = {
    "id": "CH4",
    "magic_base": 14000,
    "risk_percent": 0.5,
    "splits": [0.5, 0.4, 0.1],
}


class TestCH1ZanniVip:
    def test_open_buy_xauusd(self):
        text = (
            "🟢 BUY XAUUSD 4726\n\n"
            "TP1: 4729\nTP2: 4731\nTP3: 4735\n\nSL: 4717"
        )
        sig = parser_zanni_vip(text, CH1)
        assert sig is not None
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["symbol"] == "XAUUSD"
        assert sig["entry"] == 4726.0
        assert sig["tp_levels"] == [4729.0, 4731.0, 4735.0]
        assert sig["sl"] == 4717.0
        ok, _ = validate_signal(sig)
        assert ok

    def test_check_and_be_tp1(self):
        text = "TP1 ✅\nSpostiamo SL a BE"
        sig = parser_zanni_vip(text, CH1)
        assert sig["action"] == "CHECK_AND_BE"
        assert sig["tp_index"] == 1

    def test_check_and_close_tp2(self):
        text = "TP2 preso✅\n\nChiudete manualmente e stiamo dentro per il tp3"
        sig = parser_zanni_vip(text, CH1)
        assert sig["action"] == "CHECK_AND_CLOSE_TP"
        assert sig["tp_index"] == 2

    def test_close_tp3_explicit(self):
        text = "Noi chiudiamo ora il TP3"
        sig = parser_zanni_vip(text, CH1)
        assert sig["action"] == "CHECK_AND_CLOSE_TP"
        assert sig["tp_index"] == 3

    def test_close_all_generic(self):
        text = "cambio di trend, chiudiamo ora"
        sig = parser_zanni_vip(text, CH1)
        assert sig["action"] == "CLOSE_ALL_SYMBOL"


class TestCH2SalaGold:
    def test_open_now_naked(self, bridge_state: BridgeState):
        sig = parser_sala_gold("Gold sell now", CH2, bridge_state)
        assert sig["action"] == "OPEN_NOW"
        assert sig["direction"] == "SELL"
        assert bridge_state.ch2_pending_open is True
        assert bridge_state.ch2_pending_dir == "SELL"

    def test_update_open_after_naked(self, bridge_state: BridgeState):
        parser_sala_gold("Gold buy now", CH2, bridge_state)
        text = (
            "Buy gold now 4802 - 4795\n"
            "SL: 4790\n"
            "Tp: 4812\n"
            "Tp: 4835"
        )
        sig = parser_sala_gold(text, CH2, bridge_state)
        assert sig["action"] == "UPDATE_OPEN"
        assert sig["direction"] == "BUY"
        assert sig["sl"] == 4790.0
        assert sig["tp_levels"] == [4812.0, 4835.0]
        assert bridge_state.ch2_pending_open is False

    def test_standalone_open_with_range(self, bridge_state: BridgeState):
        text = (
            "Sell gold now 4796 - 4800\n"
            "SL: 4810\n"
            "Tp: 4785\n"
            "Tp: 4765"
        )
        sig = parser_sala_gold(text, CH2, bridge_state)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "SELL"
        assert sig["entry_range"] == [4796.0, 4800.0]
        assert sig["entry"] is None

    def test_break_even_price(self, bridge_state: BridgeState):
        sig = parser_sala_gold("4789 gold break even", CH2, bridge_state)
        assert sig["action"] == "BREAK_EVEN_PRICE"
        assert sig["be_price"] == 4789.0

    def test_close_half_be(self, bridge_state: BridgeState):
        sig = parser_sala_gold(
            "Close half break even close +100 pips", CH2, bridge_state
        )
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_state_persists_across_restart(self, tmp_path: Path):
        state_file = tmp_path / "bridge_state.json"
        s1 = BridgeState(state_file)
        parser_sala_gold("Gold buy now", CH2, s1)
        s2 = BridgeState(state_file)
        assert s2.ch2_pending_open is True
        assert s2.ch2_pending_dir == "BUY"


class TestCH3SalaVip:
    def test_open_xauusd(self):
        text = (
            "NUOVO ORDINE - XAUUSDpm Buy\n"
            "Entrata: 4736.64 [Lotti: 0.01]\n"
            "Nessuno SL\nNessuno TP"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["symbol"] == "XAUUSD"
        sized = apply_lot_rules(sig, {"execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10}})
        assert sized["fixed_lot"] == 0.20
        assert sized["trades"] == 1

    def test_update_tp(self):
        text = (
            "XAUUSDpm Buy - Modificato\n"
            "Nuovo TP: 4747.00 [103.6 Pips]"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "UPDATE_TP"
        assert sig["new_tp"] == 4747.0

    def test_update_sl_be(self):
        text = (
            "XAUUSDpm Buy - Modificato\n"
            "Nuovo SL: 4730.00 [15.9 Pips]\n"
            "Stop spostato a pareggio"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "UPDATE_SL"
        assert sig["new_sl"] == 4730.0
        assert sig["is_be"] is True

    def test_check_and_close(self):
        text = "CHIUSO - XAUUSDpm Buy"
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "CHECK_AND_CLOSE"
        assert sig["direction"] == "BUY"

    def test_open_forex_english(self):
        text = (
            "NEW ORDER - GBPCADpm Sell\n"
            "Entry: 1.89235 [Lots: 0.02]\n"
            "No SL\nNo TP"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "OPEN"
        assert sig["symbol"] == "GBPCAD"
        assert sig["direction"] == "SELL"

    def test_update_tp_english(self):
        text = (
            "GBPCADpm Sell - Modified\n"
            "New TP: 1.88924 [31.1 Pips]"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "UPDATE_TP"
        assert sig["new_tp"] == 1.88924

    def test_close_english(self):
        text = "CLOSED - GBPCADpm Sell"
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "CHECK_AND_CLOSE"


class TestCHORO:
    def test_open_with_two_tp(self):
        text = (
            "XAUUSD BUY 4073-4071\n"
            "TP 4094\n"
            "TP 4120\n"
            "SL 4068"
        )
        sig = parser_sala_oro(text, CH4)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert len(sig["tp_levels"]) == 2
        assert sig["sl"] == 4068.0
        assert sig["entry_range"] == [4071.0, 4073.0]
        assert sig["entry"] is None

    def test_open_single_tp(self):
        text = "XAUUSD BUY 4088\nTP 4098\nSL 4083"
        sig = parser_sala_oro(text, CH4)
        assert len(sig["tp_levels"]) == 1


class TestLotRules:
    def test_single_tp_020(self):
        ch = {"execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10}}
        sig = apply_lot_rules({"action": "OPEN", "tp_levels": [4100.0]}, ch)
        assert sig["trades"] == 1
        assert sig["fixed_lot"] == 0.20

    def test_two_tp_010_each(self):
        ch = {"execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10}}
        sig = apply_lot_rules({"action": "OPEN", "tp_levels": [4100.0, 4110.0]}, ch)
        assert sig["trades"] == 2
        assert sig["fixed_lot"] == 0.10


class TestCH4SalaStark:
    def test_open_markdown(self):
        text = (
            "Apro una nuova operazione\n"
            "XAUUSD BUY\n"
            "Entry: 4725\n"
            "SL: 4712.37\n"
            "TP1: 4726.87 / TP2: 4730.77 / TP3: 4798.71"
        )
        sig = parser_sala_stark(text, CH4)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["symbol"] == "XAUUSD"
        assert len(sig["tp_levels"]) == 3
        assert sig["is_add_signal"] is False

    def test_add_with_inherit(self):
        text = (
            "Aggiungo un'altra operazione\n"
            "XAUUSD BUY\n"
            "Entry: 4730"
        )
        sig = parser_sala_stark(text, CH4)
        assert sig["is_add_signal"] is True
        assert sig["inherit_from_first"] is True

    def test_add_with_own_sl_tp(self):
        text = (
            "Aggiungo un'altra operazione\n"
            "GBPUSD SELL\n"
            "Entry: 1.35200\n"
            "SL: 1.35800\n"
            "TP1: 1.35100"
        )
        sig = parser_sala_stark(text, CH4)
        assert sig["is_add_signal"] is True
        assert sig["inherit_from_first"] is False
        assert sig["sl"] == 1.358

    def test_flat_forex_open(self):
        text = "BUY   GBPUSD 1.35864\nSL    1.31230\nTP    1.36050"
        sig = parser_sala_stark(text, CH4)
        assert sig["action"] == "OPEN"
        assert sig["symbol"] == "GBPUSD"


class TestValidation:
    def test_rejects_incoherent_sl_for_buy(self):
        sig = {
            "action": "OPEN",
            "direction": "BUY",
            "symbol": "XAUUSD",
            "entry": 4800.0,
            "sl": 4810.0,
            "tp_levels": [4815.0],
            "magic_base": 11000,
            "splits": [0.5, 0.5],
        }
        ok, reason = validate_signal(sig)
        assert not ok
        assert "SL" in reason

    def test_rejects_bad_splits(self):
        sig = {
            "action": "OPEN",
            "direction": "BUY",
            "symbol": "XAUUSD",
            "entry": 4800.0,
            "sl": 4790.0,
            "tp_levels": [4810.0],
            "magic_base": 11000,
            "splits": [0.3, 0.3],
        }
        ok, reason = validate_signal(sig)
        assert not ok
        assert "splits" in reason
