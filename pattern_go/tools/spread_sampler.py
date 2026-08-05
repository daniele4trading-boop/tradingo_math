"""Campiona lo spread reale su XAU e stima quanti segnali passerebbero i filtri.

Lo spread e' il parametro che decide se Pattern GO e' tradabile su questo broker:
il filtro `risk_spread_mult` richiede SL >= 4.941 x spread su M5 e >= 8.625 x spread
su M15. Con spread di 150 punti servirebbe uno SL di 741 punti su M5, contro un
mediano di backtest di 367.

Uso:
    python tools/spread_sampler.py --minutes 60 --interval 30 --out spread_samples.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from pattern_go.dxtrade import DXTradeClient

POINT = 0.01
MEDIAN_SL_POINTS = {"M5": 367, "M15": 713}
MULT_MIN = {"M5": 4.941, "M15": 8.625}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://dx.velotrade.com/dxsca-web")
    parser.add_argument("--account", default=os.environ.get("DXTRADE_ACCOUNT_REF", ""))
    parser.add_argument("--symbol", default="XAU")
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--out", default="spread_samples.jsonl")
    args = parser.parse_args(argv)

    client = DXTradeClient(
        base_url=args.base_url,
        username=os.environ["DXTRADE_USERNAME"],
        password=os.environ["DXTRADE_PASSWORD"],
        account=args.account,
    )
    client.login()

    out = Path(args.out)
    deadline = time.time() + args.minutes * 60
    spreads: list[float] = []
    with out.open("a", encoding="utf-8") as fh:
        while time.time() < deadline:
            quote = client.quote(args.symbol)
            points = quote.spread / POINT
            spreads.append(points)
            fh.write(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "bid": quote.bid,
                        "ask": quote.ask,
                        "spread_points": round(points, 2),
                    }
                )
                + "\n"
            )
            fh.flush()
            time.sleep(args.interval)

    if not spreads:
        print("nessun campione raccolto")
        return 1
    print(f"campioni: {len(spreads)}")
    print(f"spread medio: {statistics.fmean(spreads):.1f} punti")
    print(f"spread mediano: {statistics.median(spreads):.1f} punti")
    print(f"min/max: {min(spreads):.1f} / {max(spreads):.1f} punti")
    median = statistics.median(spreads)
    for tf, mult in MULT_MIN.items():
        needed = mult * median
        print(
            f"{tf}: con spread mediano servono SL >= {needed:.0f} punti "
            f"(SL mediano di backtest {MEDIAN_SL_POINTS[tf]}) -> "
            f"{'PASSA' if MEDIAN_SL_POINTS[tf] >= needed else 'BLOCCATO'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
