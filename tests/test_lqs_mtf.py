import pandas as pd

from backtest.data_loader import build_multitf
from strategies.lqs_mtf import LQSMtfStrategy


def _make_trend_m1(n: int = 5000, start: float = 2600.0) -> pd.DataFrame:
    rows = []
    price = start
    t0 = pd.Timestamp("2026-03-01", tz="UTC")
    for i in range(n):
        drift = 0.02 if (i // 200) % 2 == 0 else -0.02
        o = price
        c = price + drift
        h = max(o, c) + 0.8
        l = min(o, c) - 0.8
        rows.append({"time": t0 + pd.Timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "tick_volume": 10})
        price = c
    return pd.DataFrame(rows)


def test_strategy_runs_without_error():
    m1 = _make_trend_m1(3000)
    tf = build_multitf(m1)
    strat = LQSMtfStrategy()
    m5 = tf["M5"]
    # run last 50 bars
    for i in range(len(m5) - 50, len(m5)):
        t = pd.Timestamp(m5.iloc[i]["time"])
        sig = strat.on_bar(
            m5_time=t,
            df_h4=tf["H4"][tf["H4"]["time"] <= t],
            df_h1=tf["H1"][tf["H1"]["time"] <= t],
            df_m15=tf["M15"][tf["M15"]["time"] <= t],
            df_m5=m5.iloc[: i + 1],
        )
        assert sig is None or sig.entry_price > 0
