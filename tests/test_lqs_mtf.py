import pandas as pd

from backtest.data_loader import build_multitf
from strategies.lqs_mtf import LQSMtfConfig, LQSMtfStrategy, LQSProfile


def _make_trend_m1(n: int = 3000, start: float = 2600.0) -> pd.DataFrame:
    rows = []
    price = start
    t0 = pd.Timestamp("2026-03-01", tz="UTC")
    for i in range(n):
        drift = 0.02 if (i // 200) % 2 == 0 else -0.02
        o = price
        c = price + drift
        h = max(o, c) + 0.8
        l = min(o, c) - 0.8
        rows.append({
            "time": t0 + pd.Timedelta(minutes=i),
            "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 10,
        })
        price = c
    return pd.DataFrame(rows)


def test_strategy_runs_all_profiles():
    m1 = _make_trend_m1(3000)
    tf = build_multitf(m1)
    for profile in LQSProfile:
        strat = LQSMtfStrategy(LQSMtfConfig(profile=profile, session_filter=False))
        m5 = tf["M5"]
        liq = tf[strat.cfg.liquidity_tf]
        confirm = tf[strat.cfg.confirm_tf]
        context = tf[str(strat.cfg.spec["context_tf"])]
        for i in range(len(m5) - 50, len(m5)):
            t = pd.Timestamp(m5.iloc[i]["time"])
            strat.register_liquidity_bar(
                context[context["time"] <= t],
                liq[liq["time"] <= t],
            )
            sig = strat.try_signal(
                m5_time=t,
                df_context=context[context["time"] <= t],
                df_liquidity=liq[liq["time"] <= t],
                df_confirm=confirm[confirm["time"] <= t],
            )
            assert sig is None or sig.entry_price > 0
