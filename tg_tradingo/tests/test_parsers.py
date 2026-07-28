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
from bridge_core import (
    BridgeState,
    validate_signal,
    apply_lot_rules,
    match_close_all_intent,
    make_signal_id,
)
from tradingo_bridge import (
    parser_sala_gold,
    parser_sala_oro,
    parser_sala_stark,
    parser_sala_vip,
    parser_ivan_vip,
    parser_zanni_vip,
    coerce_edit_open_to_update,
    pf,
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


CH_ORO = {
    "id": "CH_ORO",
    "magic_base": 14100,
    "execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10},
}

CH_IVAN = {
    "id": "CH_IVAN",
    "magic_base": 17000,
    "execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10},
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

    def test_partial_closure_break_even(self, bridge_state: BridgeState):
        # Bug 20-22 Jul: "PARTIAL CLOSURE" did not match "PARTIAL CLOSE"
        sig = parser_sala_gold("Partial closure break Even", CH2, bridge_state)
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_partial_closure_break_even_exclaim(self, bridge_state: BridgeState):
        sig = parser_sala_gold(
            "Partial closure break Even!!!", CH2, bridge_state
        )
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_standalone_break_even(self, bridge_state: BridgeState):
        sig = parser_sala_gold("break Even", CH2, bridge_state)
        assert sig["action"] == "CHECK_AND_BE"
        assert sig["symbol"] == "XAUUSD"

    def test_tp1_hit_break_even(self, bridge_state: BridgeState):
        sig = parser_sala_gold(
            "TP1 hit gold +90 pips break even", CH2, bridge_state
        )
        assert sig["action"] == "CHECK_AND_BE"

    def test_partial_close_break_even_plus_pips(self, bridge_state: BridgeState):
        # Bug 23 Jul: comma before break even was parsed as BE price → crash
        sig = parser_sala_gold(
            "Partial close, break even +100 pips", CH2, bridge_state
        )
        assert sig is not None
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_this_other_partial_break_even(self, bridge_state: BridgeState):
        sig = parser_sala_gold(
            "This other partial break even", CH2, bridge_state
        )
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_break_even_plus_pips_not_price(self, bridge_state: BridgeState):
        # Must not treat "+100" / lone punctuation as BREAK_EVEN_PRICE
        sig = parser_sala_gold("break even +100 pips", CH2, bridge_state)
        assert sig["action"] == "CHECK_AND_BE"

    def test_state_persists_across_restart(self, tmp_path: Path):
        state_file = tmp_path / "bridge_state.json"
        s1 = BridgeState(state_file)
        parser_sala_gold("Gold buy now", CH2, s1)
        s2 = BridgeState(state_file)
        assert s2.ch2_pending_open is True
        assert s2.ch2_pending_dir == "BUY"


class TestCH3SalaVip:
    def test_open_xauusd(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        text = (
            "NUOVO ORDINE - XAUUSDpm Buy\n"
            "Entrata: 4736.64 [Lotti: 0.01]\n"
            "Nessuno SL\nNessuno TP"
        )
        assert parser_sala_vip(text, CH3, state) is None
        assert state.forex_pending_symbol == "XAUUSD"
        assert state.forex_pending_dir == "BUY"
        assert state.forex_pending_entry == 4736.64

        mod = (
            "XAUUSDpm Buy - Modificato\n"
            "Nuovo TP: 4747.00 [103.6 Pips]"
        )
        sig = parser_sala_vip(mod, CH3, state)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["symbol"] == "XAUUSD"
        assert sig["entry"] == 4736.64
        assert sig["tp_levels"] == [4747.0]
        sized = apply_lot_rules(sig, {"execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10}})
        assert sized["fixed_lot"] == 0.20
        assert sized["trades"] == 1

    def test_new_order_then_modified_open(self, tmp_path: Path):
        """Real flow — NEW ORDER senza TP, poi Modified con TP (NZDJPY 13:51)."""
        state = BridgeState(tmp_path / "bridge_state.json")
        new_order = (
            "NUOVO ORDINE - NZDJPYpm Sell\n"
            "Entrata: 95.102 [Lotti: 0.02]\n"
            "Nessuno SL\nNessuno TP"
        )
        assert parser_sala_vip(new_order, CH3, state) is None
        modified = (
            "NZDJPYpm Sell - Modificato\n"
            "Nuovo TP: 94.801 [30.1 Pips]"
        )
        sig = parser_sala_vip(modified, CH3, state)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "SELL"
        assert sig["symbol"] == "NZDJPY"
        assert sig["entry"] == 95.102
        assert sig["tp_levels"] == [94.801]

    def test_update_tp(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        parser_sala_vip(
            "NUOVO ORDINE - XAUUSDpm Buy\nEntrata: 4736.64\nNessuno TP",
            CH3,
            state,
        )
        parser_sala_vip(
            "XAUUSDpm Buy - Modificato\nNuovo TP: 4747.00 [103.6 Pips]",
            CH3,
            state,
        )
        text = (
            "XAUUSDpm Buy - Modificato\n"
            "Nuovo TP: 4750.00 [103.6 Pips]"
        )
        sig = parser_sala_vip(text, CH3, state)
        assert sig["action"] == "UPDATE_TP"
        assert sig["new_tp"] == 4750.0

    def test_update_sl_be(self, tmp_path: Path):
        text = (
            "XAUUSDpm Buy - Modificato\n"
            "Nuovo SL: 4730.00 [15.9 Pips]\n"
            "Stop spostato a pareggio"
        )
        sig = parser_sala_vip(text, CH3)
        assert sig["action"] == "UPDATE_SL"
        assert sig["new_sl"] == 4730.0
        assert sig["is_be"] is True

    def test_check_and_close(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        parser_sala_vip(
            "NUOVO ORDINE - XAUUSDpm Buy\nEntrata: 4736.64\nNessuno TP",
            CH3,
            state,
        )
        parser_sala_vip(
            "XAUUSDpm Buy - Modificato\nNuovo TP: 4747.00",
            CH3,
            state,
        )
        text = "CHIUSO - XAUUSDpm Buy"
        sig = parser_sala_vip(text, CH3, state)
        assert sig["action"] == "CHECK_AND_CLOSE"
        assert sig["direction"] == "BUY"
        assert state.forex_last_trade is None

    def test_open_forex_english(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        text = (
            "NEW ORDER - GBPCADpm Sell\n"
            "Entry: 1.89235 [Lots: 0.02]\n"
            "No SL\nNo TP"
        )
        assert parser_sala_vip(text, CH3, state) is None
        sig = parser_sala_vip(
            "GBPCADpm Sell - Modified\nNew TP: 1.88924 [31.1 Pips]",
            CH3,
            state,
        )
        assert sig["action"] == "OPEN"
        assert sig["symbol"] == "GBPCAD"
        assert sig["direction"] == "SELL"

    def test_update_tp_english(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        parser_sala_vip(
            "NEW ORDER - GBPCADpm Sell\nEntry: 1.89235\nNo TP",
            CH3,
            state,
        )
        parser_sala_vip(
            "GBPCADpm Sell - Modified\nNew TP: 1.88924 [31.1 Pips]",
            CH3,
            state,
        )
        text = (
            "GBPCADpm Sell - Modified\n"
            "New TP: 1.88500 [31.1 Pips]"
        )
        sig = parser_sala_vip(text, CH3, state)
        assert sig["action"] == "UPDATE_TP"
        assert sig["new_tp"] == 1.885

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
        sig = parser_sala_oro(text, CH_ORO)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert len(sig["tp_levels"]) == 2
        assert sig["sl"] == 4068.0
        assert sig["entry_range"] == [4071.0, 4073.0]
        assert sig["entry"] is None

    def test_open_single_tp(self):
        text = "XAUUSD BUY 4088\nTP 4098\nSL 4083"
        sig = parser_sala_oro(text, CH_ORO)
        assert len(sig["tp_levels"]) == 1

    def test_close_half_be_brekiven(self):
        sig = parser_sala_oro("60 PIPS CLOSE OR BREKIVEN ✅", CH_ORO)
        assert sig["action"] == "CLOSE_HALF_BE"
        assert sig["symbol"] == "XAUUSD"

    def test_compact_sell_without_symbol(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        assert parser_sala_oro("4020 sell", CH_ORO, state) is None
        assert state.oro_pending_dir == "SELL"
        assert state.oro_pending_entry == 4020.0

    def test_tp_sl_completes_pending(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        parser_sala_oro("4020 sell", CH_ORO, state)
        sig = parser_sala_oro("Tp 4010 | Sl 4024", CH_ORO, state)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "SELL"
        assert sig["symbol"] == "XAUUSD"
        assert sig["entry"] == 4020.0
        assert sig["tp_levels"] == [4010.0]
        assert sig["sl"] == 4024.0

    def test_update_tp_on_edit(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        sig1 = parser_sala_oro(
            "XAUUSD SELL 4020-4022\nTP 4010\nSL 4024", CH_ORO, state
        )
        assert sig1["action"] == "OPEN"
        sig2 = parser_sala_oro(
            "XAUUSD SELL 4020-4022\nTP 4012\nSL 4024", CH_ORO, state
        )
        assert sig2["action"] == "UPDATE_TP"
        assert sig2["new_tp"] == 4012.0

    def test_fragmented_sell_sl_tp_sequence(self, tmp_path: Path):
        """Real flow 13:32 — Sell 4034, Sl 4039, Tp 4027 as separate messages."""
        state = BridgeState(tmp_path / "bridge_state.json")
        assert parser_sala_oro("Sell 4034", CH_ORO, state) is None
        assert state.oro_pending_dir == "SELL"
        assert parser_sala_oro("Sl 4039", CH_ORO, state) is None
        assert state.oro_pending_sl == 4039.0
        sig = parser_sala_oro("Tp 4027", CH_ORO, state)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "SELL"
        assert sig["entry"] == 4034.0
        assert sig["sl"] == 4039.0
        assert sig["tp_levels"] == [4027.0]

    def test_range_only_updates_pending(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        parser_sala_oro("Sell 4029", CH_ORO, state)
        assert parser_sala_oro("4027-4029", CH_ORO, state) is None
        assert state.oro_pending_range == [4027.0, 4029.0]

    def test_zona_buy_range(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        assert parser_sala_oro("Zona buy 4026-4024", CH_ORO, state) is None
        assert state.oro_pending_dir == "BUY"
        assert state.oro_pending_entry is None
        assert state.oro_pending_range == [4024.0, 4026.0]

    def test_zona_buy_range_with_levels(self, tmp_path: Path):
        text = "Zona buy 4016-4010\nTP 4025\nSL 4008"
        sig = parser_sala_oro(text, CH_ORO)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["entry"] is None
        assert sig["entry_range"] == [4010.0, 4016.0]
        assert sig["tp_levels"] == [4025.0]
        assert sig["sl"] == 4008.0

    def test_jul24_edit_range_not_second_open(self, tmp_path: Path):
        """Fragment OPEN then complete-form / range EDITs must not stack OPENs."""
        state = BridgeState(tmp_path / "bridge_state.json")
        assert parser_sala_oro("Sell 4060", CH_ORO, state) is None
        assert parser_sala_oro("Sl 4065", CH_ORO, state) is None
        sig1 = parser_sala_oro("Tp 4053", CH_ORO, state)
        assert sig1["action"] == "OPEN"
        assert sig1["entry"] == 4060.0

        # Same levels as complete message → ignore
        assert (
            parser_sala_oro(
                "XAUUSD SELL 4060\nTP 4053\nSL 4065", CH_ORO, state
            )
            is None
        )

        # Range refinement → UPDATE_OPEN (not a second OPEN)
        sig2 = parser_sala_oro(
            "XAUUSD SELL 4060-4062\nTP 4053\nSL 4065", CH_ORO, state
        )
        assert sig2["action"] == "UPDATE_OPEN"
        assert sig2["entry_range"] == [4060.0, 4062.0]

        sig3 = parser_sala_oro(
            "XAUUSD SELL 4060-4063\nTP 4055\nSL 4065", CH_ORO, state
        )
        assert sig3["action"] == "UPDATE_OPEN"
        assert sig3["entry_range"] == [4060.0, 4063.0]
        assert sig3["tp_levels"] == [4055.0]

    def test_reentry_sets_allow_stack(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        sig1 = parser_sala_oro(
            "XAUUSD SELL 4060\nTP 4053\nSL 4065", CH_ORO, state
        )
        assert sig1["action"] == "OPEN"
        assert not sig1.get("allow_stack")
        sig2 = parser_sala_oro(
            "Rientriamo\nXAUUSD SELL 4055\nTP 4048\nSL 4060", CH_ORO, state
        )
        assert sig2["action"] == "OPEN"
        assert sig2["allow_stack"] is True

    def test_buy_now_price_sets_pending(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        assert parser_sala_oro("Buy now 4042", CH_ORO, state) is None
        assert state.oro_pending_dir == "BUY"
        assert state.oro_pending_entry == 4042.0

    def test_buy_now_after_stale_range_opens_clean(self, tmp_path: Path):
        """07:51 regression: Buy now 4042 + Sl/Tp must not reuse overnight range."""
        state = BridgeState(tmp_path / "bridge_state.json")
        state.set_oro_last_trade({
            "direction": "BUY",
            "entry": None,
            "entry_range": [4061.0, 4063.0],
            "sl": 4058.0,
            "tp_levels": [4070.0],
        })
        state.save()

        assert parser_sala_oro("Buy now 4042", CH_ORO, state) is None
        assert state.oro_pending_entry == 4042.0
        assert state.oro_last_trade is None

        sig = parser_sala_oro("Sl 4038 | Tp 4048", CH_ORO, state)
        assert sig is not None
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "BUY"
        assert sig["entry"] == 4042.0
        assert sig["entry_range"] is None
        assert sig["sl"] == 4038.0
        assert sig["tp_levels"] == [4048.0]
        ok, reason = validate_signal(sig)
        assert ok, reason

    def test_combined_sl_tp_without_pending_does_not_reuse_last(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        state.set_oro_last_trade({
            "direction": "BUY",
            "entry": None,
            "entry_range": [4061.0, 4063.0],
            "sl": 4058.0,
            "tp_levels": [4070.0],
        })
        state.save()
        assert parser_sala_oro("Sl 4038 | Tp 4048", CH_ORO, state) is None
        assert state.oro_last_trade["entry_range"] == [4061.0, 4063.0]
        assert state.oro_last_trade["sl"] == 4058.0


class TestCHIvan:
    def test_open_sell_four_tp(self):
        text = (
            "XAUUSD SELL 4011\n\n"
            "TP 1 4006\n"
            "TP 2 4004\n"
            "TP 3 4002\n"
            "TP 4 3990\n\n"
            "SL @ 4022"
        )
        sig = parser_ivan_vip(text, CH_IVAN)
        assert sig["action"] == "OPEN"
        assert sig["direction"] == "SELL"
        assert sig["entry"] == 4011.0
        assert sig["tp_levels"] == [4006.0, 4004.0, 4002.0, 3990.0]
        assert sig["sl"] == 4022.0
        sized = apply_lot_rules(sig, CH_IVAN)
        assert sized["trades"] == 4
        assert sized["fixed_lot"] == 0.10

    def test_check_and_be(self):
        sig = parser_ivan_vip("Spostiamo SL a BE", CH_IVAN)
        assert sig["action"] == "CHECK_AND_BE"
        assert sig["symbol"] == "XAUUSD"

    def test_close_now(self):
        sig = parser_ivan_vip("CHIUDERE ORA", CH_IVAN)
        assert sig["action"] == "CLOSE_ALL_SYMBOL"
        assert sig["symbol"] == "XAUUSD"

    def test_usciamo_ora(self):
        sig = parser_ivan_vip("USCIAMO ORA", CH_IVAN)
        assert sig["action"] == "CLOSE_ALL_SYMBOL"
        assert sig["symbol"] == "XAUUSD"

    def test_close_coverage_table(self, tmp_path: Path):
        state = BridgeState(tmp_path / "bridge_state.json")
        cases = [
            ("USCIAMO ORA", None),
            ("Usciamo qui a 5054 -40 PIPS❌", 5054.0),
            ("CHIUDERE ORA", None),
            ("Chiudiamo tutto", None),
            ("USCITE ORA", None),
            ("Usciamo a mercato", None),
            ("chiudete tutto adesso", None),
            ("Usciamo qui", None),
        ]
        for msg, ref in cases:
            sig = parser_ivan_vip(msg, CH_IVAN, BridgeState(tmp_path / f"st_{hash(msg)}.json"))
            assert sig is not None, msg
            assert sig["action"] == "CLOSE_ALL_SYMBOL", msg
            if ref is None:
                assert "reference_price" not in sig, msg
            else:
                assert sig.get("reference_price") == ref, msg

        # Price follow-up after USCIAMO ORA
        assert parser_ivan_vip("USCIAMO ORA", CH_IVAN, state)["action"] == "CLOSE_ALL_SYMBOL"
        follow = parser_ivan_vip("A 4060.5", CH_IVAN, state)
        assert follow is not None
        assert follow["action"] == "CLOSE_ALL_SYMBOL"
        assert follow["reference_price"] == 4060.5

    def test_close_ignore_preparatory(self):
        assert parser_ivan_vip("Pronti a chiudere se ve lo dico", CH_IVAN) is None
        assert parser_ivan_vip("Gestiamo a mercato", CH_IVAN) is None
        assert parser_ivan_vip("Se non li piace chiudete pure", CH_IVAN) is None
        assert parser_ivan_vip("TP 1 HIT SQUAD✔️", CH_IVAN) is None
        be = parser_ivan_vip("Spostiamo SL a BE", CH_IVAN)
        assert be["action"] == "CHECK_AND_BE"

    def test_meta_size_half_lot(self):
        text = (
            "XAUUSD BUY 4012\n\n"
            "TP 1 4018\n"
            "TP 2 4020\n"
            "TP 3 4023\n"
            "TP 4 4030\n\n"
            "SL @ 4000\n\n"
            "Meta size"
        )
        sig = parser_ivan_vip(text, CH_IVAN)
        assert sig["lot_factor"] == 0.5
        sized = apply_lot_rules(sig, CH_IVAN)
        assert sized["fixed_lot"] == 0.05

    def test_meta_size_accent_and_typo(self):
        base = (
            "XAUUSD SELL 4122\n\n"
            "TP 1 4117\n"
            "TP 2 4115\n"
            "TP 3 4112\n"
            "TP 4 4100\n\n"
            "SL @ 4135\n\n"
        )
        for suffix in ("METÀ SIZE", "MEZZA SIZE", "META SAZIE", "Half size"):
            sig = parser_ivan_vip(base + suffix, CH_IVAN)
            assert sig is not None, suffix
            assert sig["lot_factor"] == 0.5, suffix
            sized = apply_lot_rules(sig, CH_IVAN)
            assert sized["fixed_lot"] == 0.05, suffix

    def test_chat_ignored(self):
        assert parser_ivan_vip("BOOOOOOMM", CH_IVAN) is None
        assert parser_ivan_vip("SL", CH_IVAN) is None
        assert parser_ivan_vip("**TP 1 HIT SQUAD**", CH_IVAN) is None


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

    def test_lot_factor(self):
        ch = {"execution": {"fixed_lot_single": 0.20, "fixed_lot_per_tp": 0.10}}
        sig = apply_lot_rules(
            {"action": "OPEN", "tp_levels": [4100.0, 4110.0], "lot_factor": 0.5},
            ch,
        )
        assert sig["fixed_lot"] == 0.05


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


class TestEditOpenCoerce:
    def test_edit_open_becomes_update(self):
        sig = {"action": "OPEN", "direction": "SELL", "symbol": "XAUUSD"}
        out = coerce_edit_open_to_update(sig, is_edit=True)
        assert out["action"] == "UPDATE_OPEN"

    def test_new_open_unchanged(self):
        sig = {"action": "OPEN", "direction": "SELL", "symbol": "XAUUSD"}
        out = coerce_edit_open_to_update(sig, is_edit=False)
        assert out["action"] == "OPEN"

    def test_allow_stack_edit_keeps_open(self):
        sig = {
            "action": "OPEN",
            "direction": "SELL",
            "symbol": "XAUUSD",
            "allow_stack": True,
        }
        out = coerce_edit_open_to_update(sig, is_edit=True)
        assert out["action"] == "OPEN"


class TestGoldBreakEvenHardening:
    def test_partial_close_plus_pips_no_crash(self):
        sig = parser_sala_gold("Partial close, break even +100 pips", CH2)
        assert sig is not None
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_partial_closure_be(self):
        sig = parser_sala_gold("Partial closure break Even!!!", CH2)
        assert sig["action"] == "CLOSE_HALF_BE"

    def test_bare_break_even(self):
        sig = parser_sala_gold("break Even", CH2)
        assert sig["action"] == "CHECK_AND_BE"

    def test_manual_break_even_instruction(self):
        sig = parser_sala_gold(
            "MANUALLY SET A BREAK EVEN ON ALL YOUR POSITIONS!", CH2
        )
        assert sig["action"] == "CHECK_AND_BE"

    def test_pf_defensive(self):
        assert pf(".") is None
        assert pf("") is None
        assert pf("+100") == 100.0
        assert pf("5054") == 5054.0


class TestCloseIntentHelper:
    def test_match_close_with_price(self):
        ok, px = match_close_all_intent("USCIAMO QUI A 5054 -40 PIPS")
        assert ok is True
        assert px == 5054.0

    def test_match_chiudiamo_typos(self):
        for text in ("CHIDUAMO ORA", "Chiduamo ora !", "CHIUDAMO ORA"):
            ok, _ = match_close_all_intent(text.upper())
            assert ok is True, text

    def test_signal_id_stable(self):
        a = make_signal_id(1, 2, "NEW")
        b = make_signal_id(1, 2, "NEW")
        assert a == b
        assert len(a) == 10
