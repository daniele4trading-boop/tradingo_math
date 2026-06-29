import pathlib
import pandas as pd
from backtest.data_loader import load_m1_directory, build_multitf
from strategies.structure import fractal_swings, equal_levels, compute_atr, detect_sweep, detect_bos

m1 = load_m1_directory(pathlib.Path("data/XAUUSD/M1"))
h1 = build_multitf(m1)["H1"]
m15 = build_multitf(m1)["M15"]
sweeps = bos_ok = 0
for i in range(50, len(h1)):
    sub = h1.iloc[: i + 1]
    bar = sub.iloc[-1]
    t = pd.Timestamp(bar["time"])
    atr = float(compute_atr(sub, 14).iloc[-1])
    if atr <= 0:
        continue
    highs, lows = fractal_swings(sub)
    recent_h = [s for s in highs if s.index >= max(0, len(sub) - 120)]
    recent_l = [s for s in lows if s.index >= max(0, len(sub) - 120)]
    levels = equal_levels(recent_h, atr, float(bar["close"]), 0.7, 1) + equal_levels(recent_l, atr, float(bar["close"]), 0.7, 1)
    for lvl in levels:
        if detect_sweep(bar, lvl, atr):
            sweeps += 1
            direction = "SHORT" if lvl.kind == "high" else "LONG"
            m15s = m15[m15["time"] >= t]
            if len(m15s) < 5:
                continue
            h, l = fractal_swings(m15s)
            if detect_bos(m15s, l, h, direction):
                bos_ok += 1
print({"h1_bars": len(h1), "sweeps": sweeps, "bos": bos_ok})
