from datetime import UTC, date, datetime, time

import pytest

from pattern_go.risk import (
    ALLOW,
    BLOCK_NEW,
    CLOSE_ALL,
    AccountState,
    RiskConfig,
    RiskManager,
    trading_day_key,
)

CFG = RiskConfig(initial_balance=10_000.0, cap_size=11_000.0)


@pytest.fixture
def rm():
    return RiskManager(CFG)


def state(equity, balance=None, **kw):
    balance = equity if balance is None else balance
    return AccountState(equity=equity, balance=balance, **kw)


def test_static_floor_is_97_percent_of_starting_balance(rm):
    assert rm.static_floor == pytest.approx(9_700.0)


def test_effective_floor_is_the_higher_of_static_and_daily(rm):
    # in profitto il vincolo che morde e' il daily, non il floor statico
    s = state(10_500.0, day_start_balance=10_500.0)
    assert rm.effective_floor(s) == pytest.approx(10_185.0)
    # in perdita il floor statico resta il limite assoluto
    s = state(9_800.0, day_start_balance=9_800.0)
    assert rm.effective_floor(s) == pytest.approx(9_700.0)


def test_reservoir_and_risk_amount_at_activation(rm):
    s = state(10_000.0, day_start_balance=10_000.0)
    assert rm.reservoir(s) == pytest.approx(300.0)
    assert rm.risk_amount(s) == pytest.approx(9.0)


def test_static_reservoir_is_frozen_at_cap_size(rm):
    s = state(12_000.0, balance=12_000.0, day_start_balance=12_000.0)
    assert rm.static_reservoir(s) == pytest.approx(1_300.0)
    s2 = state(20_000.0, balance=20_000.0, day_start_balance=20_000.0)
    assert rm.static_reservoir(s2) == rm.static_reservoir(s)


def test_reservoir_is_the_tighter_of_static_and_daily(rm):
    # conto molto in profitto: il daily floor (11.640) morde piu' del floor statico
    s = state(12_000.0, balance=12_000.0, day_start_balance=12_000.0)
    assert rm.reservoir(s) == pytest.approx(360.0)
    assert rm.risk_amount(s) == pytest.approx(10.8)


def test_reservoir_shrinks_within_a_losing_day(rm):
    s = state(9_900.0, balance=10_000.0, day_start_balance=10_000.0)
    # equity 9.900 con floor 9.700: resta meno margine di inizio giornata
    assert rm.reservoir(s) == pytest.approx(200.0)
    assert rm.risk_amount(s) == pytest.approx(6.0)


def test_quantity_on_gold_is_in_ounces(rm):
    # XAU su DXtrade: lotSize 1.0 -> 1 unita' = 1 USD per 1 USD di prezzo
    s = state(10_000.0, day_start_balance=10_000.0)
    qty, reason = rm.quantity(s, sl_distance=3.67)
    assert reason == "ok"
    assert qty == pytest.approx(2.45)
    assert qty * 3.67 <= rm.risk_amount(s)


def test_quantity_below_minimum_is_rounded_up_to_minimum(rm):
    s = state(9_705.0, balance=9_705.0, day_start_balance=9_705.0)
    qty, reason = rm.quantity(s, sl_distance=50.0)
    assert (qty, reason) == (0.01, "rounded_up_to_min")


def test_quantity_below_minimum_can_skip_the_trade():
    rm = RiskManager(
        RiskConfig(initial_balance=10_000.0, cap_size=11_000.0, round_below_min_to_min=False)
    )
    s = state(9_705.0, balance=9_705.0, day_start_balance=9_705.0)
    assert rm.quantity(s, sl_distance=50.0) == (0.0, "below_min_quantity")


def test_quantity_rejects_non_positive_stop_distance(rm):
    s = state(10_000.0, day_start_balance=10_000.0)
    assert rm.quantity(s, sl_distance=0.0) == (0.0, "sl_distance<=0")


def test_two_hundred_consecutive_full_losses_stay_above_the_floor(rm):
    """Il rischio e' una frazione del serbatoio: il serbatoio non puo' azzerarsi."""
    balance = 10_000.0
    for _ in range(200):
        s = state(balance, balance=balance, day_start_balance=10_000.0)
        risk = rm.risk_amount(s)
        qty, _ = rm.quantity(s, sl_distance=3.67)
        balance -= min(risk, qty * 3.67) if qty else 0.0
        assert balance > rm.static_floor
    assert balance > rm.static_floor


def test_guard_blocks_new_orders_at_60_percent_of_allowance(rm):
    s = state(9_820.0, balance=10_000.0, day_start_balance=10_000.0)
    decision, _ = rm.evaluate(s)
    assert decision == BLOCK_NEW


def test_guard_closes_everything_at_80_percent_of_allowance(rm):
    s = state(9_760.0, balance=10_000.0, day_start_balance=10_000.0)
    decision, _ = rm.evaluate(s)
    assert decision == CLOSE_ALL


def test_guard_closes_everything_below_the_floor(rm):
    s = state(9_690.0, balance=10_000.0, day_start_balance=10_000.0)
    assert rm.evaluate(s)[0] == CLOSE_ALL


def test_guard_allows_when_healthy(rm):
    s = state(9_990.0, balance=10_000.0, day_start_balance=10_000.0)
    assert rm.evaluate(s)[0] == ALLOW


def test_guard_blocks_while_halted_until_reset(rm):
    s = state(9_990.0, balance=10_000.0, day_start_balance=10_000.0, halted_until_reset=True)
    assert rm.evaluate(s)[0] == BLOCK_NEW


def test_guard_blocks_at_max_open_positions(rm):
    s = state(9_990.0, balance=10_000.0, day_start_balance=10_000.0, open_positions=2)
    assert rm.evaluate(s)[0] == BLOCK_NEW


def test_guard_thresholds_in_equity_terms(rm):
    s = state(10_000.0, day_start_balance=10_000.0)
    assert rm.block_new_equity(s) == pytest.approx(9_820.0)
    assert rm.close_all_equity(s) == pytest.approx(9_760.0)


def test_trading_day_rolls_at_00_30_utc():
    reset = time(0, 30)
    assert trading_day_key(datetime(2026, 8, 5, 0, 15, tzinfo=UTC), reset) == date(
        2026, 8, 4
    )
    assert trading_day_key(datetime(2026, 8, 5, 0, 45, tzinfo=UTC), reset) == date(
        2026, 8, 5
    )


def test_roll_day_resets_halt_and_rebases_the_daily_floor(rm):
    s = state(9_800.0, balance=9_800.0, day_start_balance=10_000.0, halted_until_reset=True)
    s.day_key = date(2026, 8, 4)
    assert rm.roll_day(s, datetime(2026, 8, 5, 1, 0, tzinfo=UTC))
    assert s.day_start_balance == 9_800.0
    assert not s.halted_until_reset
    # nuovo daily floor 9506 < floor statico 9700: vince lo statico
    assert rm.effective_floor(s) == pytest.approx(9_700.0)
    assert not rm.roll_day(s, datetime(2026, 8, 5, 2, 0, tzinfo=UTC))


def test_quantity_is_capped_by_available_margin(rm):
    """XAU ha marginRate 0.16666: uno stop stretto chiede piu' nozionale del margine."""
    s = state(10_000.0, day_start_balance=10_000.0, margin_free=1_000.0)
    qty, reason = rm.quantity(s, sl_distance=0.10, price=4_200.0)
    assert reason == "capped_by_margin"
    # meta' del margine libero, al 16,666% di margine su un prezzo di 4.200
    assert qty == pytest.approx(0.71, abs=0.01)
    assert qty * 4_200.0 * rm.cfg.margin_rate <= 0.5 * 1_000.0


def test_quantity_ignores_the_margin_cap_when_it_is_not_binding(rm):
    s = state(10_000.0, day_start_balance=10_000.0, margin_free=8_000.0)
    assert rm.quantity(s, sl_distance=3.67, price=4_200.0) == (2.45, "ok")


def test_consecutive_losses_in_one_day_cannot_break_the_daily_limit(rm):
    """Perdite piene consecutive nello stesso giorno UTC: il guard chiude prima di -300."""
    equity = balance = 10_000.0
    for _ in range(50):
        s = state(equity, balance=balance, day_start_balance=10_000.0)
        decision, _ = rm.evaluate(s)
        if decision != ALLOW:
            break
        qty, _ = rm.quantity(s, sl_distance=3.67)
        # la perdita reale eccede il rischio pianificato: slippage misurato ~1,1R
        equity = balance = equity - 1.2 * qty * 3.67
    assert decision == BLOCK_NEW  # il blocco scatta al 60% dell'allowance, prima del limite
    assert equity > 10_000.0 - 300.0
