from datetime import UTC, datetime, time, timedelta

from pattern_go.engine import (
    CANCEL_ORDER,
    CLOSE_TRADE,
    PLACE_ORDER,
    SIGNAL_REJECTED,
    StrategyConfigView,
    StrategyEngine,
)
from pattern_go.runner import client_order_id
from pattern_go.strategy import EntryFilters, SessionSpec
from pattern_go.types import Bar, ExitReason, Side

LONDON = SessionSpec("london", time(9, 0), "Europe/Rome")
OPEN_UTC = datetime(2026, 8, 4, 7, 0, tzinfo=UTC)  # 09:00 Europe/Rome


def cfg(**kw):
    base = dict(
        name="M5",
        bias_window=24,
        max_hold=48,
        day_bars=288,
        filters=EntryFilters(),
    )
    base.update(kw)
    return StrategyConfigView(**base)


def engine(**kw):
    return StrategyEngine(cfg(**kw), [LONDON], client_order_id)


def b(i, o, h, low, c, start=OPEN_UTC):
    return Bar(time=start + timedelta(minutes=5 * i), open=o, high=h, low=low, close=c)


def flat(i, price=4000.0):
    return b(i, price, price + 0.5, price - 0.5, price)


def sizer_ok(_sl):
    return 1.0, "ok"


def sizer_zero(_sl):
    return 0.0, "risk_blocked"


def short_setup_bars():
    """Sessione londinese con bias SHORT confermato e pattern ribassista."""
    bars = [
        flat(0, 4000.0),
        b(1, 4000, 4010, 3999, 4001),  # swing high 4010 (conferma su barra 2)
        flat(2, 4000.0),
        b(3, 4000, 4000.2, 3990, 3995),  # swing low 3990 (conferma su barra 4)
        flat(4, 4000.0),
        b(5, 4000, 4001, 3985, 3986),  # chiude sotto sw_low -> bias SHORT
        b(6, 3986, 3990, 3985, 3989),  # candela 1 rialzista
        b(7, 3989, 3990, 3975, 3980),  # candela 2: chiude sotto il low della 1
    ]
    return bars


def run(eng, bars, spread=0.1, sizer=sizer_ok):
    out = []
    for bar in bars:
        out.append(eng.on_bar(bar, spread, sizer))
    return out


def test_full_short_setup_places_a_stop_order():
    eng = engine()
    intents = run(eng, short_setup_bars())
    assert eng.session is not None and eng.session.bias is Side.SHORT
    placed = [i for step in intents for i in step if i.kind == PLACE_ORDER]
    assert len(placed) == 1
    order = placed[0].order
    assert order.side is Side.SHORT
    assert (order.trigger_price, order.stop_loss) == (3975.0, 3990.0)
    assert order.risk == 15.0
    assert order.expires_after_bar_index == order.signal_bar_index + 1
    assert order.client_order_id == "PG-M5-S-20260804T073500"


def test_order_is_cancelled_if_not_triggered_within_one_bar():
    eng = engine()
    run(eng, short_setup_bars())
    intents = eng.on_bar(flat(8, 3980.0), 0.1, sizer_ok)
    assert [i.kind for i in intents] == [CANCEL_ORDER]
    assert eng.pending is None


def test_no_new_signal_while_a_trade_is_open():
    eng = engine()
    run(eng, short_setup_bars())
    eng.on_fill(3975.0)
    assert eng.trade is not None
    for i in range(8, 14):
        intents = eng.on_bar(b(i, 3980, 3981, 3970, 3971), 0.1, sizer_ok)
        assert not [x for x in intents if x.kind == PLACE_ORDER]


def test_max_hold_closes_the_trade():
    eng = engine(max_hold=3)
    run(eng, short_setup_bars())
    eng.on_fill(3975.0)
    entry_index = eng.trade.entry_bar_index
    kinds = []
    for i in range(8, 12):
        kinds += [x.kind for x in eng.on_bar(flat(i, 3975.0), 0.1, sizer_ok)]
    assert CLOSE_TRADE in kinds
    assert len(eng.bars) - 1 - entry_index >= 3


def test_session_end_closes_the_trade():
    eng = engine(day_bars=10)
    run(eng, short_setup_bars())
    eng.on_fill(3975.0)
    kinds = []
    for i in range(8, 12):
        kinds += [x.kind for x in eng.on_bar(flat(i, 3975.0), 0.1, sizer_ok)]
    assert CLOSE_TRADE in kinds
    assert eng.session is None


def test_slippage_is_measured_against_the_theoretical_trigger():
    eng = engine()
    run(eng, short_setup_bars())
    trade = eng.on_fill(3974.0)  # short eseguito 1 USD peggio del trigger
    assert trade.theoretical_entry_price == 3975.0
    assert trade.slippage == 1.0


def test_filters_block_the_entry_and_the_rejection_is_reported():
    eng = engine(filters=EntryFilters(risk_spread_mult_min=8.625))
    intents = run(eng, short_setup_bars(), spread=5.0)
    rejected = [i for step in intents for i in step if i.kind == SIGNAL_REJECTED]
    assert rejected and rejected[-1].payload["failed"] == ["risk_spread_mult"]
    assert eng.pending is None


def test_risk_block_from_sizer_prevents_the_order():
    eng = engine()
    intents = run(eng, short_setup_bars(), sizer=sizer_zero)
    rejected = [i for step in intents for i in step if i.kind == SIGNAL_REJECTED]
    assert rejected and rejected[-1].payload["reason"] == "sizing:risk_blocked"


def test_take_profit_falls_back_when_the_only_swing_is_above_the_entry():
    eng = engine()
    run(eng, short_setup_bars())
    order = eng.pending
    # l'unico swing L confermato (3990) sta sopra l'ingresso short a 3975: non e' un TP
    assert order.take_profit == 3975.0 - 1.5 * 15.0


def test_duplicate_bar_is_ignored():
    eng = engine()
    bars = short_setup_bars()
    run(eng, bars)
    count = len(eng.bars)
    assert eng.on_bar(bars[-1], 0.1, sizer_ok) == []
    assert len(eng.bars) == count


def test_client_order_id_is_deterministic():
    t = datetime(2026, 8, 4, 7, 35, tzinfo=UTC)
    assert client_order_id("M15", t, Side.LONG) == "PG-M15-L-20260804T073500"
    assert client_order_id("M15", t, Side.LONG) == client_order_id("M15", t, Side.LONG)


def test_exit_reasons_are_reported_with_the_close_intent():
    eng = engine(max_hold=1)
    run(eng, short_setup_bars())
    eng.on_fill(3975.0)
    intents = eng.on_bar(flat(8, 3975.0), 0.1, sizer_ok)
    close = [i for i in intents if i.kind == CLOSE_TRADE][0]
    assert close.payload["reason"] == ExitReason.MAX_HOLD.value
