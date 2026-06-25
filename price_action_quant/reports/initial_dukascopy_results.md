# Price Action Quant v0.1 - Initial Dukascopy Results

Initial research run using Dukascopy BID OHLC data.

## Data coverage

| Symbol | Timeframe | Bars | First bar UTC | Last bar UTC |
| --- | ---: | ---: | --- | --- |
| EURUSD | H1 | 33,847 | 2021-01-03 22:00 | 2026-06-08 00:00 |
| EURUSD | H4 | 8,750 | 2021-01-03 20:00 | 2026-06-08 00:00 |
| GBPUSD | H1 | 33,844 | 2021-01-03 22:00 | 2026-06-08 00:00 |
| GBPUSD | H4 | 8,749 | 2021-01-03 20:00 | 2026-06-08 00:00 |

Notes:

- Data source is Dukascopy BID candles, not the final execution broker feed.
- Current results do not include spread, commission, slippage, or swap.
- Raw downloaded CSV files are local artifacts under `data/backtests/` and are intentionally ignored by git.

## Baseline configuration

- Direction: long only.
- Pattern: strict bullish engulfing with close above previous high.
- RSI filter: minimum RSI Z-Score over the last 3 closed bars <= -2.0.
- Regime: close above EMA200 and EMA200 slope non-negative over 10 bars.
- Stop: 2.0 ATR.
- Target: 1.5R.
- Same-bar stop/target policy: stop first.

## Baseline results

| Symbol | TF | Trades | Win rate | Profit factor | Expectancy R | Total R | Max DD R | Longest losing streak |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | H1 | 31 | 25.81% | 0.52 | -0.35 | -11.0 | 14.5 | 6 |
| EURUSD | H4 | 9 | 22.22% | 0.43 | -0.44 | -4.0 | 5.5 | 4 |
| GBPUSD | H1 | 46 | 43.48% | 1.15 | 0.09 | 4.0 | 9.0 | 9 |
| GBPUSD | H4 | 12 | 16.67% | 0.30 | -0.58 | -7.0 | 7.0 | 7 |

Read:

- The strict baseline is not acceptable on EURUSD or GBPUSD H4.
- GBPUSD H1 is the only baseline with positive expectancy, but the drawdown and losing streak are still too high for immediate deployment.
- H4 samples are too small for conclusions.

## Best rows from first constrained grid

Grid:

- RSI Z threshold: -1.5, -1.75, -2.0, -2.25, -2.5.
- ATR stop: 1.5, 2.0, 2.5.
- Reward/risk: 1.0, 1.5, 2.0.
- Close above previous high: on/off.
- Minimum trades filter: 5.

| Symbol | TF | Z long | ATR SL | R:R | Close break | Trades | Win rate | PF | Expectancy R | Total R | Max DD R | Losing streak |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | H1 | -1.75 | 2.0 | 2.0 | false | 97 | 37.11% | 1.18 | 0.11 | 11.0 | 17.0 | 8 |
| EURUSD | H4 | -2.00 | 2.5 | 2.0 | true | 9 | 33.33% | 1.00 | 0.00 | 0.0 | 4.0 | 4 |
| GBPUSD | H1 | -2.50 | 1.5 | 1.0 | true | 20 | 60.00% | 1.50 | 0.20 | 4.0 | 2.0 | 2 |
| GBPUSD | H4 | -2.25 | 1.5 | 2.0 | false | 7 | 42.86% | 1.50 | 0.29 | 2.0 | 2.0 | 2 |

Read:

- EURUSD H1 improves when the close-break requirement is removed and R:R is increased to 2.0, but max drawdown remains large relative to total R.
- GBPUSD H1 improves with a stricter RSI Z threshold, tighter 1.5 ATR stop, and 1.0R target. This supports the earlier hypothesis that a lower PF but higher frequency/win-rate profile may be more useful.
- H4 optimized rows have too few trades and should not be trusted yet.

## Next recommended test cycle

1. Focus on GBPUSD H1 and EURUSD H1.
2. Compare strict engulfing vs relaxed close-break on an out-of-sample split.
3. Add spread/commission assumptions in R or price terms.
4. Test short side specularly.
5. Add GOLD only after the FX workflow is stable.
6. Optimize speed further if we expand the grid or add more symbols.
